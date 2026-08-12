"""Cross-cutting envelope, authentication/authorization, ownership scoping,
pagination, ledger immutability, and immediate consistency."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_account,
    create_check_item,
    create_clearing_bank,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    PROCESSOR,
    get_account,
    list_ledger_entries,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        that is not one of the six declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        res = api.get_account(NON_EXISTENT_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_item_processor_cannot_create_account(self, api):
        """PRD §2.1: "A request whose role is authenticated but not in the
        endpoint's authorized role list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4 endpoint table: "POST `/bank/accounts` | Create a depositor
        account ... | OperationsAdmin".

        Design: Corner/rbac/item_processor_cannot_create_account
        """
        res = api.create_account(
            {"customer_name": "Bad", "account_number": "A-2032"}, PROCESSOR
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestCustomerOwnership:
    def test_customer_forbidden_from_others_account(self, api):
        """PRD §2.1: "The `Customer` role is entity-backed: when
        `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
        `DepositorAccount`" and "A `Customer` may only access resources whose
        `depositor_account_id` equals their `X-User-ID`; any other access is
        rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/customer_forbidden_from_others_account
        """
        acct_a = create_account(customer_name="CustA", account_number="A-2034")
        acct_b = create_account(customer_name="CustB", account_number="A-2035")

        headers_a = make_customer_headers(acct_a["id"])
        other = api.get_account(acct_b["id"], headers_a)
        validate_error(other, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        own = validate_success(api.get_account(acct_a["id"], headers_a), 200)
        assert own["id"] == acct_a["id"]


class TestNotFound:
    def test_item_not_found_returns_404(self, api):
        """PRD §2.10: "Each resource type has its own not-found error:
        `ERR_ACCOUNT_NOT_FOUND` for a depositor account,
        `ERR_CLEARING_BANK_NOT_FOUND` for a clearing bank, `ERR_ITEM_NOT_FOUND`
        for a check item," and "All eleven carry HTTP 404."

        Design: Corner/errors/item_not_found_returns_404
        """
        res = api.get_check_item(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_ITEM_NOT_FOUND)

    def test_case_not_found_returns_404(self, api):
        """PRD §2.10: "`ERR_ITEM_NOT_FOUND` for a check item,
        `ERR_CASE_NOT_FOUND` for an adjustment case, `ERR_CLAIM_NOT_FOUND`
        for an adjustment claim," and "All eleven carry HTTP 404."

        Design: Corner/errors/case_not_found_returns_404
        """
        res = api.get_adjustment_case(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_CASE_NOT_FOUND)


class TestPagination:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. ... The `offset` parameter specifies the number of
        items to skip and defaults to 0." and "Paginated list responses
        include the following fields in the `meta` object of the response
        envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope
        """
        bank = create_clearing_bank(name="CB PG", routing_number="222000037")
        account = create_account(customer_name="Yale", account_number="A-2029")
        for ref, amount in (("ITM-P1", 100), ("ITM-P2", 200), ("ITM-P3", 300)):
            create_check_item(
                account["id"], bank["id"], item_reference=ref,
                amount_cents=amount, capture_channel="ATM",
            )

        page1, meta1 = validate_paginated(
            api.list_check_items(
                ADMIN,
                params={"depositor_account_id": account["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_check_items(
                ADMIN,
                params={"depositor_account_id": account["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestLedger:
    def test_ledger_entry_carries_no_version_or_updated_at(self, api):
        """PRD §2.5: "A `CustomerNotification` and a `LedgerEntry` each carry
        only `id` and `created_at`; both `updated_at` and `version` are
        absent from them, because notifications are delivered exactly once
        and ledger entries are immutable by design."
        PRD §3.1: "When the opening balance is greater than zero, account
        creation posts exactly one `OPENING_CREDIT` ledger entry,
        non-provisional, for that amount."

        Design: Corner/entities/ledger_entry_immutable_common_fields_false
        """
        account = create_account(
            customer_name="Vic", account_number="A-2002", opening_balance_cents=5000
        )
        entries = list_ledger_entries(depositor_account_id=account["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "OPENING_CREDIT"
        assert entry["amount_cents"] == 5000
        assert entry["provisional"] is False
        assert "version" not in entry
        assert "updated_at" not in entry

    def test_ledger_writes_immediately_visible(self, api):
        """PRD §2.7: "An account's balances are never stored; they are
        derived from the ledger on every read and re-derived after every
        ledger write."
        PRD §3.2: "the system immediately posts a `DEPOSIT_CREDIT` ledger
        entry for the full `amount_cents`, marked provisional: the customer
        sees the funds at once, but nothing has settled."

        Design: Corner/consistency_model/ledger_writes_immediately_visible
        """
        bank = create_clearing_bank(name="CB IM", routing_number="222000047")
        account = create_account(customer_name="Hal", account_number="A-2044")
        item = create_check_item(
            account["id"], bank["id"], item_reference="ITM-IM",
            amount_cents=12345, capture_channel="ATM",
        )

        entries = list_ledger_entries(check_item_id=item["id"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "DEPOSIT_CREDIT"
        assert entries[0]["amount_cents"] == 12345

        assert get_account(account["id"])["available_balance_cents"] == 12345
