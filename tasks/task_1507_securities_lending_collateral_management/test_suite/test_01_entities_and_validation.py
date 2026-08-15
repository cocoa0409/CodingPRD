"""Reference data creation, request-shape validation, not-found, pagination.

Covers queue-B instances from the entities section plus the validation
priority-ordering pair.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_borrower_payload,
    create_security_payload,
    list_ledger_entries,
    make_borrower_rep_headers,
    make_owner_rep_headers,
    setup_booked_loan,
    setup_desk,
    validate_error,
    validate_paginated,
    validate_success,
    run_mtm,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["desk_trader_headers"]
OPS = TEST_USERS["ops_settler_headers"]


class TestSecurityCreation:
    def test_gov_bond_and_equity_haircut_defaults(self, api):
        """PRD §3.1: "The system derives the security's `haircut_bps` from its
        asset class — 200 basis points for `GOV_BOND`, 600 for `CORP_BOND`,
        1000 for `EQUITY` — and the security enters the book in `LENDABLE`
        status."

        Design: Corner/entities/security_creation_applies_haircut_defaults
        """
        gov = validate_success(api.create_security(
            create_security_payload(symbol="GOV1", asset_class="GOV_BOND",
                                    price_cents=10000), ADMIN),
            expected_status=201)
        eq = validate_success(api.create_security(
            create_security_payload(symbol="EQ1", asset_class="EQUITY",
                                    price_cents=1000), ADMIN),
            expected_status=201)
        assert gov["haircut_bps"] == 200
        assert gov["status"] == "LENDABLE"
        assert eq["haircut_bps"] == 1000
        assert eq["version"] == 1

    def test_missing_price_cents_rejected(self, api):
        """PRD §2.7: "required fields are present, enum values are in
        range, quantities and amounts are positive, dates are well-formed
        ISO values, and cross-references are consistent (a loan's
        `security_id` must equal the referenced position's `security_id`,
        and a loan's `owner_id` must equal the position's `owner_id`);
        otherwise `ERR_VALIDATION`."

        Design: Corner/entities/security_create_missing_required_price_returns_validation
        """
        resp = api.create_security(
            {"symbol": "BAD1", "asset_class": "EQUITY"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_asset_class_rejected(self, api):
        """PRD §3.1: "A `DeskAdmin` registers each lendable instrument as a
        `Security` with a unique `symbol`, an `asset_class` of `EQUITY`,
        `GOV_BOND`, or `CORP_BOND`, and an opening `price_cents`."
        PRD §2.7: "required fields are present, enum values are in range,
        quantities and amounts are positive, dates are well-formed ISO
        values, and cross-references are consistent (a loan's `security_id`
        must equal the referenced position's `security_id`, and a loan's
        `owner_id` must equal the position's `owner_id`); otherwise
        `ERR_VALIDATION`."

        Design: Corner/entities/security_create_invalid_enum_returns_validation
        """
        resp = api.create_security(
            create_security_payload(symbol="CRP1", asset_class="CRYPTO",
                                    price_cents=100), ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestNotFound:
    def test_get_unknown_loan_returns_not_found(self, api):
        """PRD §2.7: "path identifiers are resolved left to right, then body
        foreign-key references; any miss is `ERR_NOT_FOUND`."

        Design: Corner/entities/loan_get_unknown_id_returns_not_found
        """
        resp = api.get_loan("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", TRADER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLedgerImmutability:
    def test_ledger_entry_has_no_version_or_updated_at(self, api):
        """PRD §2.6: "Two resource types are exceptions: a
        `RevenueLedgerEntry` and a `PeriodClose` each carry only `id` and
        `created_at` — both `updated_at` and `version` are absent from them."
        PRD §3.9: "For a **securities-collateral** loan in `BOOKED` or
        `RECALLED`, each daily run posts a `FEE_ACCRUAL_PROVISIONAL` equal to
        that day's `outstanding_quantity` times that day's marked
        `price_cents` times the loan's `rate_bps`, divided by 10000 and then
        by the 360-day year, rounded half-up to whole cents per day"

        Design: Corner/entities/ledger_entry_is_immutable_without_version
        """
        ctx = setup_booked_loan(security_symbol="IMM1", price_cents=1000,
                                quantity_total=100000, loan_quantity=50000,
                                rate_bps=25)
        run_mtm()
        entries = list_ledger_entries(
            OPS, loan_id=ctx["loan"]["id"],
            entry_type="FEE_ACCRUAL_PROVISIONAL")
        assert len(entries) == 1
        entry = entries[0]
        # 50000 x 1000 x 25 / 10000 / 360 = 347.22 -> 347
        assert entry["amount_cents"] == 347
        for key in ("id", "created_at", "loan_id", "owner_id", "entry_type",
                    "amount_cents", "accrual_date", "period", "note"):
            assert key in entry, f"ledger entry missing key {key}"
        assert "version" not in entry
        assert "updated_at" not in entry


class TestPagination:
    def test_loans_list_paginates_with_envelope_defaults(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter sets the number of items to
        skip and defaults to 0."

        Design: Corner/entities/loans_list_paginates_with_envelope_defaults
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="PAG1", quantity_total=100000)
        for _ in range(12):
            resp = api.create_loan(
                {"owner_id": owner["id"], "borrower_id": borrower["id"],
                 "security_id": security["id"], "position_id": position["id"],
                 "quantity": 100, "collateral_type": "SECURITIES",
                 "rate_bps": 25}, TRADER)
            assert resp.status_code == 201, resp.text

        page1, meta1 = validate_paginated(
            api.list_loans(TRADER, params={"position_id": position["id"]}))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_loans(TRADER, params={"position_id": position["id"],
                                           "offset": 10}))
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestValidationPriorityOrdering:
    def test_missing_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "If `X-User-Role` is absent or is not one of the
        declared roles, the request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/create_security_missing_auth_header_unauthenticated
        """
        from test_helpers import ANONYMOUS_HEADERS
        resp = api.create_security(
            create_security_payload(symbol="NAU1", asset_class="EQUITY",
                                    price_cents=100), ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_role_check_fires_before_existence_on_confirm(self, api):
        """PRD §2.7: "When several checks could fail on the same request, the
        server evaluates them in a fixed priority order and reports the first
        failure" — role authorization (2. Role authorization — "the role
        appears in the endpoint's permitted roles; otherwise
        `ERR_FORBIDDEN`") precedes existence (5. Existence — "any miss is
        `ERR_NOT_FOUND`").

        Design: Corner/validations/role_check_fires_before_existence_on_confirm
        """
        resp = api.confirm_loan(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            make_borrower_rep_headers("00000000-0000-4000-8000-000000000001"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_request_shape_fires_before_existence_on_pledge(self, api):
        """PRD §2.7: "the server evaluates them in a fixed priority order and
        reports the first failure" — "required fields are present, enum
        values are in range, quantities and amounts are positive, dates are
        well-formed ISO values, and cross-references are consistent (a
        loan's `security_id` must equal the referenced position's
        `security_id`, and a loan's `owner_id` must equal the position's
        `owner_id`); otherwise `ERR_VALIDATION`."
        PRD §2.7: "path identifiers are resolved left to right, then body
        foreign-key references; any miss is `ERR_NOT_FOUND`."

        Design: Corner/validations/request_shape_fires_before_existence_on_pledge
        """
        resp = api.create_pledge(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            {"amount_cents": 100},
            make_borrower_rep_headers("00000000-0000-4000-8000-000000000001"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_owner_cannot_suspend_other_owners_position(self, api):
        """PRD §2.1: "when `X-User-Role` is `OwnerRep`, `X-User-ID` is the
        `id` of the acting `BeneficialOwner`, and ownership checks compare
        the resource's `owner_id` foreign key to `X-User-ID`."
        PRD §2.7: "for `OwnerRep` and `BorrowerRep` callers, the
        caller's `X-User-ID` equals the `owner_id` or `borrower_id` of the
        resource acted on (or supplied in the body), and list filters follow
        the auto-scoping rule; otherwise `ERR_FORBIDDEN`."

        Design: Corner/validations/owner_cannot_suspend_other_owners_position
        """
        security, _, _, _ = setup_desk(security_symbol="SCP1")
        from test_helpers import create_owner, create_position
        owner_a = create_owner(display_name="Owner A")
        owner_b = create_owner(display_name="Owner B")
        pos_b = create_position(owner_b, security, quantity_total=1000)
        resp = api.suspend_lendable_position(
            pos_b["id"], make_owner_rep_headers(owner_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_lendable_position(pos_b["id"], TRADER))
        assert after["status"] == "OPEN"
