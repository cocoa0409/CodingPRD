"""Mask fit exchanges: window anchoring, the inclusive window check, the strict
count check, rolling-window capacity, and terminal-state lockdown.

Covers PRD §3.6 (mask fit exchanges and the exchange window).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    complete_mask_exchange_flow,
    get_mask_exchange,
    request_mask_exchange,
    set_clock,
    setup_therapy_patient,
    validate_error,
    validate_success,
)

RT = TEST_USERS["respiratory_therapist_headers"]
IC = TEST_USERS["intake_coordinator_headers"]


class TestExchangeWindowAnchor:
    """First exchange anchors at the enrollment's setup completion date."""

    def test_first_exchange_anchor_is_setup_completion_and_last_day_ok(
            self, api, respiratory_therapist_headers):
        """PRD §3.6: "If no prior exchange exists, the anchor is the
        enrollment's `setup_completed_on`."
        PRD §3.6: "The window check requires the current date to be on or
        before `window_anchor_on` plus `mask_exchange_window_days` —
        inclusive, so with a 30-day window anchored on March 1 the last valid
        approval day is March 31"

        Design: Difficulty/cross_entity_state_dependency/mask_exchange_approve_gated_by_window_anchor_from_device_enrollment
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        mask_plan = ctx["plans"]["MASK"]
        exchange = request_mask_exchange(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"], mask_plan["id"])
        # Setup completed 2026-08-01 -> the first exchange anchors there.
        assert exchange["window_anchor_on"] == "2026-08-01"
        assert exchange["exchange_status"] == "REQUESTED"

        # 2026-08-31 == anchor + 30 days: last valid approval day (inclusive).
        set_clock("2026-08-31T00:00:00Z")
        approved = validate_success(api.approve_mask_exchange(
            exchange["id"], respiratory_therapist_headers))
        assert approved["exchange_status"] == "APPROVED"

    def test_approve_after_window_expiry_rejected(
            self, api, respiratory_therapist_headers):
        """PRD §3.6: "a later date fails with `ERR_EXCHANGE_WINDOW_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/mask_exchange_approve_gated_by_window_anchor_from_device_enrollment
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        exchange = request_mask_exchange(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         ctx["plans"]["MASK"]["id"])
        assert exchange["window_anchor_on"] == "2026-08-01"

        # 2026-09-01 is one day past the last valid day (2026-08-31).
        set_clock("2026-09-01T00:00:00Z")
        res = api.approve_mask_exchange(exchange["id"],
                                        respiratory_therapist_headers)
        validate_error(res, "ERR_EXCHANGE_WINDOW_EXPIRED", expected_status=409)


class TestExchangeWindowAndCountIntersection:
    """Window date check AND strict count check gate the same approve."""

    def _setup_two_exchanges_same_window(self, api):
        """max_exchanges_per_window=1; first exchange COMPLETED in the window
        anchored 2026-08-01; second exchange requested in the same window."""
        ctx = setup_therapy_patient(
            acquisition_type="RENTAL",
            payer_overrides={"mask_exchange_window_days": 30,
                             "max_exchanges_per_window": 1})
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]
        mask_plan = ctx["plans"]["MASK"]

        first = request_mask_exchange(patient["id"], enrollment["id"],
                                      mask_plan["id"], reason_code="FIT_LEAK")
        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.approve_mask_exchange(first["id"], RT))
        validate_success(api.ship_mask_exchange(first["id"], IC))
        set_clock("2026-08-12T00:00:00Z")
        first = validate_success(api.complete_mask_exchange(first["id"], IC))
        assert first["exchange_status"] == "COMPLETED"

        set_clock("2026-08-20T00:00:00Z")
        second = request_mask_exchange(patient["id"], enrollment["id"],
                                       mask_plan["id"], reason_code="WRONG_SIZE")
        return ctx, first, second

    def test_second_exchange_inherits_open_window_anchor(self, api):
        """PRD §3.6: "If a prior exchange exists and its window is still open
        — the current date is on or before the prior anchor plus the payer's
        `mask_exchange_window_days` — the new exchange inherits the prior
        anchor, extending the same window rather than opening a fresh one."

        Design: Difficulty/combinatorial_formula/mask_exchange_window_and_count_intersection
        """
        ctx, first, second = self._setup_two_exchanges_same_window(api)
        assert first["window_anchor_on"] == "2026-08-01"
        assert second["window_anchor_on"] == "2026-08-01"

    def test_second_exchange_rejected_by_strict_count_check(
            self, api, respiratory_therapist_headers):
        """PRD §3.6: "The count check requires that the number of the patient's
        other exchanges already in `COMPLETED` status sharing this exchange's
        `window_anchor_on` be **strictly less than** the payer's
        `max_exchanges_per_window` — so with a limit of one, the first exchange
        in a window is permitted and the second is rejected with
        `ERR_EXCHANGE_LIMIT_REACHED`."

        Design: Difficulty/combinatorial_formula/mask_exchange_window_and_count_intersection
        """
        ctx, first, second = self._setup_two_exchanges_same_window(api)
        # Window is still open on 2026-08-20, so only the count check can fail.
        res = api.approve_mask_exchange(second["id"], respiratory_therapist_headers)
        validate_error(res, "ERR_EXCHANGE_LIMIT_REACHED", expected_status=409)


class TestRollingWindowAggregateCapacity:
    """Anchor rolls to the latest completed_on only after the window expires."""

    def _setup_rolling_windows(self, api):
        """max_exchanges_per_window=2.
        Window 1 (anchor 2026-08-01): A completed 08-10, B completed 08-15.
        Window 2 (anchor rolls to B.completed_on 2026-08-15): C completed 09-06,
        D requested 09-10 in C's window."""
        ctx = setup_therapy_patient(
            acquisition_type="RENTAL",
            payer_overrides={"mask_exchange_window_days": 30,
                             "max_exchanges_per_window": 2})
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]
        mask_plan = ctx["plans"]["MASK"]

        # Exchange A: created at 2026-08-01, completed 2026-08-10.
        a = request_mask_exchange(patient["id"], enrollment["id"],
                                  mask_plan["id"], reason_code="FIT_LEAK")
        validate_success(api.approve_mask_exchange(a["id"], RT))
        validate_success(api.ship_mask_exchange(a["id"], IC))
        set_clock("2026-08-10T00:00:00Z")
        a = validate_success(api.complete_mask_exchange(a["id"], IC))

        # Exchange B: same open window (anchor stays 2026-08-01).
        b = request_mask_exchange(patient["id"], enrollment["id"],
                                  mask_plan["id"], reason_code="WRONG_SIZE")
        validate_success(api.approve_mask_exchange(b["id"], RT))
        validate_success(api.ship_mask_exchange(b["id"], IC))
        set_clock("2026-08-15T00:00:00Z")
        b = validate_success(api.complete_mask_exchange(b["id"], IC))

        # Exchange C: requested 2026-09-05, after window 1 expired
        # (2026-08-31). Anchor rolls forward to B.completed_on.
        set_clock("2026-09-05T00:00:00Z")
        c = request_mask_exchange(patient["id"], enrollment["id"],
                                  mask_plan["id"], reason_code="SKIN_IRRITATION")
        validate_success(api.approve_mask_exchange(c["id"], RT))
        validate_success(api.ship_mask_exchange(c["id"], IC))
        set_clock("2026-09-06T00:00:00Z")
        c = validate_success(api.complete_mask_exchange(c["id"], IC))

        # Exchange D: requested 2026-09-10, inside C's still-open window.
        set_clock("2026-09-10T00:00:00Z")
        d = request_mask_exchange(patient["id"], enrollment["id"],
                                  mask_plan["id"], reason_code="PRESSURE_INTOLERANCE")
        return ctx, a, b, c, d

    def test_anchor_rolls_only_after_window_expires(self, api):
        """PRD §3.6: "If the prior window has expired, the anchor becomes the
        prior exchange's `completed_on`, rolling a new window forward."

        Design: Difficulty/resource_temporal_overlap/mask_exchange_window_rolling_anchor_aggregate_capacity
        """
        ctx, a, b, c, d = self._setup_rolling_windows(api)
        assert a["window_anchor_on"] == "2026-08-01"
        assert b["window_anchor_on"] == "2026-08-01"  # window 1 still open
        assert c["window_anchor_on"] == "2026-08-15"  # rolled to B.completed_on
        assert d["window_anchor_on"] == "2026-08-15"  # same window as C

    def test_supersession_chain_and_fresh_window_capacity(
            self, api, respiratory_therapist_headers):
        """PRD §3.6: "the most recent prior exchange for the patient that has
        not already been superseded is marked by writing this exchange's id
        into its `superseded_by_exchange_id`, forming a chain in which each
        exchange points at its replacement."

        Design: Difficulty/resource_temporal_overlap/mask_exchange_window_rolling_anchor_aggregate_capacity
        """
        ctx, a, b, c, d = self._setup_rolling_windows(api)
        assert get_mask_exchange(a["id"])["superseded_by_exchange_id"] == b["id"]
        assert get_mask_exchange(b["id"])["superseded_by_exchange_id"] == c["id"]

        # D's window (anchor 2026-08-15) holds exactly one prior COMPLETED
        # exchange (C); 1 < max_exchanges_per_window=2, so D may be approved.
        approved = validate_success(api.approve_mask_exchange(
            d["id"], respiratory_therapist_headers))
        assert approved["exchange_status"] == "APPROVED"


class TestExchangeTerminalLockdown:
    def test_denied_exchange_cannot_be_approved(
            self, api, respiratory_therapist_headers):
        """PRD §3.6: "An exchange not in `REQUESTED` cannot be approved at all
        (`ERR_EXCHANGE_NOT_REQUESTED`)."

        Design: Corner/state_machines/mask_exchange_terminal_denied_lockdown
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        exchange = request_mask_exchange(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         ctx["plans"]["MASK"]["id"])
        denied = validate_success(api.deny_mask_exchange(
            exchange["id"], respiratory_therapist_headers))
        assert denied["exchange_status"] == "DENIED"

        res = api.approve_mask_exchange(exchange["id"],
                                        respiratory_therapist_headers)
        validate_error(res, "ERR_EXCHANGE_NOT_REQUESTED", expected_status=409)
