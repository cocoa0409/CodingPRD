"""Master data: depositor accounts, clearing banks, freeze windows, account OCC."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_account,
    create_account_payload,
    create_clearing_bank,
    create_clearing_bank_payload,
    create_freeze_payload,
    get_account,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, OFFICER, PROCESSOR, create_check_item


class TestAccountCreation:
    def test_create_account_applies_defaults(self, api):
        """PRD §3.1: "an optional `risk_tier` of `STANDARD` (the default) or
        `HIGH_RISK`, an optional `reg_cc_eligible` flag defaulting to true, and
        an optional `opening_balance_cents` defaulting to zero."
        PRD §3.1: "A new account starts in `ACTIVE` status with its `version`
        at 1."

        Design: Corner/entities/create_account_applies_defaults
        """
        res = api.create_account(
            {"customer_name": "Tara", "account_number": "A-2000"}, ADMIN
        )
        account = validate_success(res, 201)
        assert account["risk_tier"] == "STANDARD"
        assert account["reg_cc_eligible"] is True
        assert account["status"] == "ACTIVE"
        assert account["available_balance_cents"] == 0
        assert account["settled_balance_cents"] == 0
        assert account["version"] == 1

    def test_create_account_missing_account_number_rejected(self, api):
        """PRD §3.1: "Depositor accounts are likewise created by an
        `OperationsAdmin`, with a `customer_name`, an `account_number` that
        must be unique (duplicates are rejected with
        `ERR_DUPLICATE_ACCOUNT_NUMBER`)"
        PRD §2.11: "and eleventh, amount sanity and request shape
        (`ERR_INVALID_AMOUNT`, `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/create_account_missing_required_returns_invalid_request
        """
        res = api.create_account({"customer_name": "NoNum"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_account_not_found(self, api):
        """PRD §2.10: "Each resource type has its own not-found error:
        `ERR_ACCOUNT_NOT_FOUND` for a depositor account," and "All eleven
        carry HTTP 404."
        PRD §2.2: error responses carry "response_type": "error".

        Design: Corner/entities/account_not_found_returns_error_envelope
        """
        res = api.get_account(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
        assert res.json()["response_type"] == "error"

    def test_duplicate_account_number_rejected(self, api):
        """PRD §3.1: "an `account_number` that must be unique (duplicates are
        rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER`)"

        Design: Corner/entities/duplicate_account_number_rejected
        """
        validate_success(
            api.create_account(
                {"customer_name": "Uma", "account_number": "A-2001"}, ADMIN
            ),
            201,
        )
        res = api.create_account(
            {"customer_name": "Uma2", "account_number": "A-2001"}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACCOUNT_NUMBER)

    def test_duplicate_routing_number_rejected(self, api):
        """PRD §3.1: "a 9-digit `routing_number` that must be unique across all
        clearing banks (a duplicate is rejected with
        `ERR_DUPLICATE_ROUTING_NUMBER`)"

        Design: Corner/entities/duplicate_routing_number_rejected
        """
        validate_success(
            api.create_clearing_bank(
                {"name": "CB X", "routing_number": "222000010"}, ADMIN
            ),
            201,
        )
        res = api.create_clearing_bank(
            {"name": "CB Y", "routing_number": "222000010"}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ROUTING_NUMBER)


class TestAccountOcc:
    def test_stale_version_on_account_patch_returns_412(self, api):
        """PRD §2.9: "Updating a depositor account requires the request to
        carry `expected_depositor_account_version` holding the account
        `version` the client last observed. If the account's current `version`
        has advanced past that value, the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.1: "per §2.9 this write requires
        `expected_depositor_account_version` and increments the account's
        `version` by one on success."

        Design: Corner/cross_cutting_layers/stale_version_on_account_patch_returns_412
        """
        account = create_account(customer_name="Dee", account_number="A-2038")
        observed_version = account["version"]

        updated = validate_success(
            api.update_account(
                account["id"],
                {
                    "risk_tier": "HIGH_RISK",
                    "expected_depositor_account_version": observed_version,
                },
                ADMIN,
            ),
            200,
        )
        assert updated["version"] == observed_version + 1
        assert updated["risk_tier"] == "HIGH_RISK"

        stale = api.update_account(
            account["id"],
            {
                "reg_cc_eligible": False,
                "expected_depositor_account_version": observed_version,
            },
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestFreezeWindows:
    def test_freeze_touching_window_rejected_as_overlap(self, api):
        """PRD §3.1: "A new freeze is rejected with `ERR_FREEZE_WINDOW_OVERLAP`
        whenever it overlaps an existing freeze on the same account — and under
        closed-interval semantics, two windows that merely touch at a single
        instant do overlap and are rejected."

        Design: Difficulty/resource_temporal_overlap/account_freeze_closed_interval_overlap
        """
        account = create_account(customer_name="Paul", account_number="A-1500")
        validate_success(
            api.create_account_freeze(
                account["id"],
                create_freeze_payload(
                    start_at="2026-05-04T00:00:00Z",
                    end_at="2026-05-08T00:00:00Z",
                    reason="fraud review",
                ),
                OFFICER,
            ),
            201,
        )
        touching = api.create_account_freeze(
            account["id"],
            create_freeze_payload(
                start_at="2026-05-08T00:00:00Z",
                end_at="2026-05-12T00:00:00Z",
                reason="touching extension",
            ),
            OFFICER,
        )
        validate_error(touching, ApiErrorId.ERR_FREEZE_WINDOW_OVERLAP)

    def test_freeze_disjoint_window_accepted(self, api):
        """PRD §3.1: "Freeze windows are **closed intervals**, inclusive of
        both endpoints" and only overlapping windows are rejected: "A new
        freeze is rejected with `ERR_FREEZE_WINDOW_OVERLAP` whenever it
        overlaps an existing freeze on the same account".

        Design: Difficulty/resource_temporal_overlap/account_freeze_closed_interval_overlap
        """
        account = create_account(customer_name="Paul", account_number="A-1501")
        validate_success(
            api.create_account_freeze(
                account["id"],
                create_freeze_payload(
                    start_at="2026-05-04T00:00:00Z",
                    end_at="2026-05-08T00:00:00Z",
                    reason="fraud review",
                ),
                OFFICER,
            ),
            201,
        )
        disjoint = api.create_account_freeze(
            account["id"],
            create_freeze_payload(
                start_at="2026-05-09T00:00:00Z",
                end_at="2026-05-12T00:00:00Z",
                reason="disjoint follow-up",
            ),
            OFFICER,
        )
        freeze = validate_success(disjoint, 201)
        assert freeze["depositor_account_id"] == account["id"]

    def test_active_freeze_window_blocks_deposit(self, api):
        """PRD §3.1: "While any `ACTIVE` freeze window covers an account,
        deposits into that account are rejected with `ERR_ACCOUNT_FROZEN`,
        exactly as if the account itself were `FROZEN`."

        Design: Corner/validations/active_freeze_window_blocks_deposit
        """
        bank = create_clearing_bank(name="CB FB", routing_number="222000036")
        account = create_account(customer_name="Will", account_number="A-2028")
        validate_success(
            api.create_account_freeze(
                account["id"],
                create_freeze_payload(
                    start_at="2026-05-04T00:00:00Z",
                    end_at="2026-05-10T00:00:00Z",
                    reason="court order",
                ),
                OFFICER,
            ),
            201,
        )
        set_clock("2026-05-06T00:00:00Z")

        res = api.create_check_item(
            {
                "depositor_account_id": account["id"],
                "clearing_bank_id": bank["id"],
                "item_reference": "ITM-FB",
                "amount_cents": 5000,
                "encoded_amount_cents": 5000,
                "image_quality_score": 90,
                "capture_channel": "ATM",
            },
            PROCESSOR,
        )
        validate_error(res, ApiErrorId.ERR_ACCOUNT_FROZEN)
        # Account status itself remains ACTIVE — the freeze window does the blocking.
        assert get_account(account["id"])["status"] == "ACTIVE"
