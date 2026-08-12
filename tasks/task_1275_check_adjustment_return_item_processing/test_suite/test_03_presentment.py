"""Presentment: duplicate detection, encoding-error and image-defect cascades,
suspended clearing banks, and item state guards on pay/return."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_account,
    create_check_item,
    create_clearing_bank,
    setup_presented_item,
    sum_ledger_entries,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    PROCESSOR,
    get_account,
    get_check_item,
    get_first_case_for_item,
    get_first_claim_for_case,
    list_cases_for_item,
    list_ledger_entries,
    list_notifications,
)


class TestStateGuards:
    def test_pay_from_received_returns_invalid_state(self, api):
        """PRD §3.4: "A `PRESENTED` item that clears is marked paid" — payment
        is defined only from PRESENTED.
        PRD §2.11: "sixth, state-machine preconditions for the requested
        transition (`ERR_INVALID_STATE`, ...)"

        Design: Corner/state_machines/pay_from_received_returns_invalid_state
        """
        bank = create_clearing_bank(name="CB Pay", routing_number="222000012")
        account = create_account(customer_name="Xena", account_number="A-2004")
        item = create_check_item(account["id"], bank["id"], item_reference="ITM-PAY",
                                 amount_cents=1000, capture_channel="ATM")
        res = api.pay_check_item(item["id"], PROCESSOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        # Rejected transition posts no ledger entries for the item beyond intake.
        entries = list_ledger_entries(check_item_id=item["id"])
        assert [e["entry_type"] for e in entries] == ["DEPOSIT_CREDIT"]

    def test_return_on_paid_item_returns_invalid_state(self, api):
        """PRD §3.4: "`PAID` is terminal."
        PRD §2.11: "sixth, state-machine preconditions for the requested
        transition (`ERR_INVALID_STATE`, `ERR_ACCOUNT_FROZEN`,
        `ERR_CLEARING_BANK_SUSPENDED`, `ERR_MAX_PRESENTMENTS_EXCEEDED`,
        `ERR_RE_PRESENTMENT_NOT_ELIGIBLE`)"

        Design: Corner/state_machines/terminal_lockdown_return_on_paid_item
        """
        ctx = setup_presented_item(
            amount_cents=5000, image_quality_score=90,
            bank_overrides={"name": "CB TL", "routing_number": "222000014"},
            item_reference="ITM-TL",
        )
        validate_success(api.pay_check_item(ctx["item"]["id"], PROCESSOR), 200)
        res = api.create_return_event(ctx["item"]["id"], PROCESSOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestDuplicatePresentment:
    def test_duplicate_presentment_detection_credit(self, api):
        """PRD §3.3: "the new item transitions from `RECEIVED` to
        `DUPLICATE_REJECTED`. Its `duplicate_of_item_id` is set to the matching
        item — the one in `PRESENTED` or `PAID` status with the earliest
        `created_at` among same-reference items. To make the customer whole,
        the system posts a `DUPLICATE_REVERSAL_CREDIT` ledger entry for the
        negative of the item's `amount_cents`, marked provisional, reversing
        the provisional deposit credit posted at intake. It also opens an
        adjustment case of `case_type` `DUPLICATE_PRESENTMENT` in `OPEN`
        status and raises a `DUPLICATE_NOTICE` customer notification in
        `PENDING` status."

        Design: Corner/calculations/duplicate_presentment_detection_credit
        """
        bank = create_clearing_bank(name="CB Dup", routing_number="222000019")
        account = create_account(customer_name="Elle", account_number="A-2011",
                                 opening_balance_cents=0)
        item_a = create_check_item(account["id"], bank["id"], item_reference="ITM-DUP",
                                   amount_cents=30000)
        validate_success(api.present_check_item(item_a["id"], PROCESSOR), 200)
        item_b = create_check_item(account["id"], bank["id"], item_reference="ITM-DUP",
                                   amount_cents=30000, capture_channel="RDC")

        rejected = validate_success(api.present_check_item(item_b["id"], PROCESSOR), 200)
        assert rejected["status"] == "DUPLICATE_REJECTED"
        assert rejected["duplicate_of_item_id"] == item_a["id"]

        # Item B's ledger footprint nets to zero (DEPOSIT_CREDIT +30000,
        # DUPLICATE_REVERSAL_CREDIT -30000).
        entries = list_ledger_entries(check_item_id=item_b["id"])
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type.get("DEPOSIT_CREDIT") == 30000
        assert by_type.get("DUPLICATE_REVERSAL_CREDIT") == -30000
        assert sum(e["amount_cents"] for e in entries) == 0

        dup_case = get_first_case_for_item(item_b["id"], case_type="DUPLICATE_PRESENTMENT")
        assert dup_case["status"] == "OPEN"

        notices = list_notifications(depositor_account_id=account["id"])
        assert any(
            n["notification_type"] == "DUPLICATE_NOTICE" and n["status"] == "PENDING"
            for n in notices
        )

        # Only item A's provisional deposit credit remains in the balance.
        assert get_account(account["id"])["available_balance_cents"] == 30000


class TestDefectDetectionAtPresentment:
    def test_encoding_mismatch_creates_case_and_draft_claim(self, api):
        """PRD §3.3: "If `encoded_amount_cents` differs from `amount_cents`,
        the system opens an `ENCODING_ERROR` adjustment case in `OPEN` status
        and, alongside it, a `DRAFT` adjustment claim whose
        `claimed_amount_cents` is the absolute difference between the encoded
        and face amounts and whose `created_by_user_id` is recorded as the
        literal string `system`."

        Design: Corner/calculations/encoding_mismatch_creates_case_and_draft_claim
        """
        ctx = setup_presented_item(
            amount_cents=100000, encoded_amount_cents=95000,
            bank_overrides={"name": "CB EM", "routing_number": "222000024"},
            item_reference="ITM-EM",
        )
        case = get_first_case_for_item(ctx["item"]["id"], case_type="ENCODING_ERROR")
        assert case["status"] == "OPEN"

        claim = get_first_claim_for_case(case["id"])
        assert claim["claimed_amount_cents"] == 5000
        assert claim["status"] == "DRAFT"
        assert claim["created_by_user_id"] == "system"

    def test_image_quality_case_created_at_present(self, api):
        """PRD §3.3: "Independently, if the item's `image_quality_score` is
        below 60, the system opens an `IMAGE_WARRANTY` adjustment case in
        `OPEN` status — the foundation for the warranty claim workflow of
        §3.6."

        Design: Corner/endpoints/image_quality_case_created_at_present
        """
        bank = create_clearing_bank(name="CB IQ", routing_number="222000038")
        account = create_account(customer_name="Zoe", account_number="A-2030")
        bad = create_check_item(account["id"], bank["id"], item_reference="ITM-IQ1",
                                amount_cents=5000, encoded_amount_cents=5000,
                                image_quality_score=50, capture_channel="MOBILE")
        good = create_check_item(account["id"], bank["id"], item_reference="ITM-IQ2",
                                 amount_cents=5000, encoded_amount_cents=5000,
                                 image_quality_score=90, capture_channel="MOBILE")
        validate_success(api.present_check_item(bad["id"], PROCESSOR), 200)
        validate_success(api.present_check_item(good["id"], PROCESSOR), 200)

        bad_cases = list_cases_for_item(bad["id"])
        assert len(bad_cases) == 1
        assert bad_cases[0]["case_type"] == "IMAGE_WARRANTY"
        assert bad_cases[0]["status"] == "OPEN"

        assert list_cases_for_item(good["id"]) == []


class TestSuspendedClearingBank:
    def _suspended_bank_with_received_item(self):
        bank = create_clearing_bank(
            name="CB Susp", routing_number="111000037", status="SUSPENDED"
        )
        account = create_account(customer_name="Nina", account_number="A-1300")
        item = create_check_item(
            account["id"], bank["id"], item_reference="ITM-SUS", amount_cents=10000
        )
        assert item["status"] == "RECEIVED"
        return bank, account, item

    def test_present_rejected_when_clearing_bank_suspended(self, api):
        """PRD §3.3: "The bank must be `ACTIVE`; presenting against a
        `SUSPENDED` bank is rejected with `ERR_CLEARING_BANK_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/present_requires_clearing_bank_active
        """
        _bank, _account, item = self._suspended_bank_with_received_item()
        res = api.present_check_item(item["id"], PROCESSOR)
        validate_error(res, ApiErrorId.ERR_CLEARING_BANK_SUSPENDED)

    def test_rejected_present_leaves_item_received_and_retry_still_rejected(self, api):
        """PRD §3.3: "When no duplicate exists, the item transitions from
        `RECEIVED` to `PRESENTED`; `presented_at` is set to the current
        logical time and `presentment_count` increments by one." A rejected
        presentment performs none of that transition.
        PRD §3.3: "The bank must be `ACTIVE`; presenting against a
        `SUSPENDED` bank is rejected with `ERR_CLEARING_BANK_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/present_requires_clearing_bank_active
        """
        _bank, _account, item = self._suspended_bank_with_received_item()
        validate_error(
            api.present_check_item(item["id"], PROCESSOR),
            ApiErrorId.ERR_CLEARING_BANK_SUSPENDED,
        )
        after = get_check_item(item["id"])
        assert after["status"] == "RECEIVED"
        assert after["presentment_count"] == 0
        # The bank is still SUSPENDED, so a retry fails the same way.
        validate_error(
            api.present_check_item(item["id"], PROCESSOR),
            ApiErrorId.ERR_CLEARING_BANK_SUSPENDED,
        )
