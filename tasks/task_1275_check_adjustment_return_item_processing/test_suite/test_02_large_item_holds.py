"""Deposits, large-item review classification, hold windows, and the hold sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    analyst,
    create_account,
    create_check_item,
    create_clearing_bank,
    list_hold_decisions,
    set_clock,
    setup_large_item_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    PROCESSOR,
    get_account,
    get_check_item,
    list_cases_for_item,
    list_notifications,
)


class TestLargeItemThreshold:
    def test_large_item_at_threshold_triggers_review(self, api):
        """PRD §3.2: "An item whose `amount_cents` is at least 500000 cents —
        the boundary is inclusive, so exactly 500000 qualifies — is classified
        `is_large_item` and never rests in `RECEIVED`."
        PRD §3.2: "Creation cascades it straight into `UNDER_REVIEW` with
        three companions: a hold decision whose `source` is `AUTO_LARGE_ITEM`,
        in `PENDING` status, whose window runs from the item's `created_at`
        to that same time-of-day two business days later"

        Design: Difficulty/boundary_precision_check/large_item_threshold_exact
        """
        bank = create_clearing_bank(name="CB LI", routing_number="111000035")
        account = create_account(customer_name="Liam", account_number="A-1100")

        item = validate_success(
            api.create_check_item(
                {
                    "depositor_account_id": account["id"],
                    "clearing_bank_id": bank["id"],
                    "item_reference": "ITM-AT",
                    "amount_cents": 500000,
                    "encoded_amount_cents": 500000,
                    "image_quality_score": 90,
                    "capture_channel": "BRANCH",
                },
                PROCESSOR,
            ),
            201,
        )
        assert item["status"] == "UNDER_REVIEW"
        assert item["is_large_item"] is True

        holds = list_hold_decisions(item["id"])
        assert len(holds) == 1
        assert holds[0]["source"] == "AUTO_LARGE_ITEM"
        assert holds[0]["status"] == "PENDING"

    def test_below_large_item_threshold_stays_received(self, api):
        """PRD §3.2: "An item whose `amount_cents` is at least 500000 cents —
        the boundary is inclusive, so exactly 500000 qualifies — is classified
        `is_large_item` and never rests in `RECEIVED`."
        PRD §3.2: "On acceptance the item starts in `RECEIVED` status with
        `presentment_count` at zero"

        Design: Difficulty/boundary_precision_check/large_item_threshold_exact
        """
        bank = create_clearing_bank(name="CB LI", routing_number="111000035")
        account = create_account(customer_name="Liam", account_number="A-1101")

        item = validate_success(
            api.create_check_item(
                {
                    "depositor_account_id": account["id"],
                    "clearing_bank_id": bank["id"],
                    "item_reference": "ITM-BELOW",
                    "amount_cents": 499999,
                    "encoded_amount_cents": 499999,
                    "image_quality_score": 90,
                    "capture_channel": "BRANCH",
                },
                PROCESSOR,
            ),
            201,
        )
        assert item["status"] == "RECEIVED"
        assert item["is_large_item"] is False
        assert list_hold_decisions(item["id"]) == []


class TestItemInitialState:
    def test_check_item_initial_state_received(self, api):
        """PRD §3.2: "On acceptance the item starts in `RECEIVED` status with
        `presentment_count` at zero"

        Design: Corner/state_machines/check_item_initial_state_received
        """
        bank = create_clearing_bank(name="CB Init", routing_number="222000011")
        account = create_account(customer_name="Walt", account_number="A-2003")
        item = validate_success(
            api.create_check_item(
                {
                    "depositor_account_id": account["id"],
                    "clearing_bank_id": bank["id"],
                    "item_reference": "ITM-INIT",
                    "amount_cents": 1000,
                    "encoded_amount_cents": 1000,
                    "image_quality_score": 90,
                    "capture_channel": "ATM",
                },
                PROCESSOR,
            ),
            201,
        )
        assert item["status"] == "RECEIVED"
        assert item["presentment_count"] == 0


class TestHoldDecisions:
    def test_hold_return_item_decision_cascades(self, api):
        """PRD §3.2: "`RETURN_ITEM` drives the item from `UNDER_REVIEW` to
        `DEPOSIT_REJECTED`: the system posts a `PROVISIONAL_REVERSAL` ledger
        entry for the negative of the item's `amount_cents`, marked
        provisional, which nets the item's ledger footprint to zero; it raises
        a `DEPOSIT_REJECTED_NOTICE` customer notification in `PENDING` status;
        and the linked `LARGE_ITEM_REVIEW` case auto-transitions from `OPEN`
        to `RESOLVED` with disposition `NO_ACTION`."

        Design: Corner/state_machines/hold_return_item_decision_cascades
        """
        ctx = setup_large_item_under_review(
            amount_cents=600000, customer_name="Abby", account_number="A-2007"
        )
        decided = validate_success(
            api.decide_hold(ctx["hold"]["id"], {"decision": "RETURN_ITEM"}, analyst("analyst-1")),
            200,
        )
        assert decided["status"] == "DECIDED"
        assert decided["decision"] == "RETURN_ITEM"

        item = get_check_item(ctx["item"]["id"])
        assert item["status"] == "DEPOSIT_REJECTED"

        # Provisional deposit credit reversed: account available back to zero.
        assert get_account(ctx["account"]["id"])["available_balance_cents"] == 0

        notices = list_notifications(depositor_account_id=ctx["account"]["id"])
        assert any(
            n["notification_type"] == "DEPOSIT_REJECTED_NOTICE" and n["status"] == "PENDING"
            for n in notices
        ), f"expected a PENDING DEPOSIT_REJECTED_NOTICE, got {notices}"

        review_cases = [
            c for c in list_cases_for_item(ctx["item"]["id"])
            if c["case_type"] == "LARGE_ITEM_REVIEW"
        ]
        assert len(review_cases) == 1
        assert review_cases[0]["status"] == "RESOLVED"
        assert review_cases[0]["disposition"] == "NO_ACTION"

    def test_extend_hold_requires_later_until(self, api):
        """PRD §3.2: "`EXTEND_HOLD` moves `hold_until` to a supplied
        `extend_until`, which must be strictly later than the current
        `hold_until`; a missing or non-later `extend_until` is rejected with
        `ERR_INVALID_REQUEST`, and the item remains `UNDER_REVIEW`."

        Design: Corner/validations/extend_hold_requires_later_until
        """
        ctx = setup_large_item_under_review(
            amount_cents=600000, customer_name="Vera", account_number="A-2027"
        )
        # Auto hold: [2026-05-01T00:00:00Z, +2 business days) → 2026-05-05T00:00:00Z.
        res = api.decide_hold(
            ctx["hold"]["id"],
            {"decision": "EXTEND_HOLD", "extend_until": "2026-05-04T00:00:00Z"},
            analyst("analyst-1"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_manual_hold_overlapping_auto_hold_rejected(self, api):
        """PRD §3.2: "The new window is rejected with `ERR_HOLD_WINDOW_OVERLAP`
        when the same item already carries a hold whose `status` is not
        `EXPIRED` and whose `decision` is either still unset or anything other
        than `RELEASE_FUNDS`, and whose window intersects the new one"

        Design: Difficulty/resource_temporal_overlap/hold_window_half_open_adjacency
        """
        ctx = setup_large_item_under_review(
            amount_cents=600000, customer_name="Quinn", account_number="A-1600"
        )
        assert ctx["item"]["status"] == "UNDER_REVIEW"
        # Auto hold [2026-05-01T00:00:00Z, 2026-05-05T00:00:00Z); new window
        # [2026-05-01T00:00:00Z, 2026-05-04T12:00:00Z) intersects it.
        res = api.create_hold_decision(
            ctx["item"]["id"],
            {"hold_until": "2026-05-04T12:00:00Z", "reason": "supplementary review"},
            analyst("analyst-1"),
        )
        validate_error(res, ApiErrorId.ERR_HOLD_WINDOW_OVERLAP)

    def test_manual_hold_touching_auto_hold_accepted(self, api):
        """PRD §3.2: "because the windows are half-open, two windows that
        merely touch — one ending exactly when the other begins — do not count
        as overlapping."

        Design: Difficulty/resource_temporal_overlap/hold_window_half_open_adjacency
        """
        ctx = setup_large_item_under_review(
            amount_cents=600000, customer_name="Quinn", account_number="A-1601"
        )
        # Auto hold ends (exclusive) at 2026-05-05T00:00:00Z; advance the clock
        # so the new window starts exactly at the old window's end.
        set_clock("2026-05-05T00:00:00Z")
        res = api.create_hold_decision(
            ctx["item"]["id"],
            {"hold_until": "2026-05-07T00:00:00Z", "reason": "adjacent follow-up hold"},
            analyst("analyst-1"),
        )
        hold = validate_success(res, 201)
        assert hold["source"] == "MANUAL"
        assert hold["status"] == "PENDING"


class TestHoldExpirySweep:
    def test_hold_expiry_sweep_releases_item(self, api):
        """PRD §3.9: "it expires every `PENDING` hold decision whose
        `hold_until` is at or before the current time, moving the hold to
        `EXPIRED`; when the expired hold's item is still `UNDER_REVIEW`, the
        item auto-transitions back to `RECEIVED` and its funds are released
        for presentment."

        Design: Corner/calculations/hold_expiry_sweep_releases_item
        """
        ctx = setup_large_item_under_review(
            amount_cents=600000, customer_name="Fred", account_number="A-2012"
        )
        # Auto hold window [2026-05-01, 2026-05-05): "at or before" means the
        # sweep at exactly hold_until expires it.
        set_clock("2026-05-05T00:00:00Z")
        report = validate_success(api.run_daily_ops(ADMIN), 200)
        assert report["holds_expired"] == 1

        holds = list_hold_decisions(ctx["item"]["id"])
        assert holds[0]["status"] == "EXPIRED"
        assert holds[0]["hold_until"].startswith("2026-05-05T00:00:00")

        item = get_check_item(ctx["item"]["id"])
        assert item["status"] == "RECEIVED"
