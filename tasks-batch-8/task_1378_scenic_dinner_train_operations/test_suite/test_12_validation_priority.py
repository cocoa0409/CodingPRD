"""Validation priority pairs: when two violations hold simultaneously, the earlier
pipeline tier's error is the one returned (PRD §2.9)."""
import pytest

from test_helpers import (
    SCHED,
    confirm_booking,
    create_held_booking,
    get_booking,
    set_clock,
    setup_draft_excursion,
    setup_issued_rain_check_and_second_excursion,
    create_scheduled_work_order,
    create_car_assignment_payload,
    roster_stock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestStateBeatsFiscalOnRedeemedConfirm:
    """Tier 4 (event/state validity) vs tier 10 (money/capacity): confirming a
    CANCELLED booking while also carrying an already-REDEEMED rain-check must surface
    the state error, not ERR_RAIN_CHECK_INVALID."""

    def _setup_cancelled_booking_with_redeemed_rain_check(self, api, station_agent_headers):
        scenario = setup_issued_rain_check_and_second_excursion(customer_email="sam@x.com")
        rc = scenario["rain_check"]
        excursion_b = scenario["pair"]["b"]["excursion"]

        # Redeem the rain-check on a new booking (paid floored to 0, RC -> REDEEMED)...
        held = create_held_booking(excursion_b["id"], "sam@x.com", "COACH", 1)
        confirmed = confirm_booking(held["id"], redeemed_rain_check_id=rc["id"])
        assert confirmed["paid_cents"] == 0
        # ...then voluntarily cancel that booking (a refund of paid 0 is 0).
        cancelled = validate_success(
            api.booking_event(confirmed["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        return rc, cancelled

    def test_confirm_cancelled_booking_with_redeemed_raincheck_state_error(
            self, api, station_agent_headers):
        """PRD §2.9: "Requests are validated against a fixed priority pipeline, and when
        several checks could fail, the earliest tier's error is the one returned."
        PRD §2.9 (tier 4): "the target entity is in a legal from-state for the requested
        event — events on terminal entities, out-of-order boarding or operation, consist
        edits on a non-`DRAFT` excursion, starting a work order on a unit that is not
        `AVAILABLE`, checking in while the excursion is not `BOARDING`, and creating an
        excursion on a slot that is not `OPEN` all fail here with `ERR_INVALID_STATE`
        (HTTP 409)."
        PRD §2.9 (tier 10): "**Money and capacity rules**, in this exact sub-order: (a)
        conservative class capacity (`ERR_CLASS_FULL`); (b) the dining table pool for the
        requested service (`ERR_DINING_SERVICE_FULL`); (c) rain-check validity
        (`ERR_RAIN_CHECK_INVALID`); (d) provisioning shortfall (`ERR_PROVISION_SHORTFALL`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_redeemed_confirm
        """
        rc, cancelled = self._setup_cancelled_booking_with_redeemed_rain_check(api, station_agent_headers)

        # Two violations hold at once: the booking is in the terminal CANCELLED state
        # (tier 4) and the rain-check is no longer ISSUED (tier 10). Tier 4 wins.
        res = api.booking_event(cancelled["id"],
                                {"event_type": "CONFIRM", "redeemed_rain_check_id": rc["id"]},
                                station_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_rejected_confirm_leaves_raincheck_and_booking_untouched(
            self, api, station_agent_headers):
        """PRD §2.9: "Requests are validated against a fixed priority pipeline, and when
        several checks could fail, the earliest tier's error is the one returned."
        PRD §3.5: "The redeemed rain-check flips `ISSUED → REDEEMED` with its
        `redeemed_booking_id` pointing at the booking that consumed it."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_redeemed_confirm
        """
        rc, cancelled = self._setup_cancelled_booking_with_redeemed_rain_check(api, station_agent_headers)

        res = api.booking_event(cancelled["id"],
                                {"event_type": "CONFIRM", "redeemed_rain_check_id": rc["id"]},
                                station_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

        rc_after = validate_success(api.get_rain_check(rc["id"], station_agent_headers), 200)
        assert rc_after["status"] == "REDEEMED", "the rejected confirm changes nothing"
        booking_after = get_booking(cancelled["id"])
        assert booking_after["status"] == "CANCELLED"


class TestConstraintBeatsTemporalOnCarAssign:
    """Tier 8 (shape/constraint) vs tier 9 (temporal): a car assignment that pairs a
    DINING class_code with a COACH_CAR unit while that unit also has a work-order window
    intersecting the service date must surface ERR_CLASS_STOCK_MISMATCH."""

    def _setup(self):
        coach = roster_stock("COACH-1", "COACH_CAR", 40, 0)
        # Maintenance window intersecting the excursion's service date (2026-10-15).
        create_scheduled_work_order(coach["id"], window_start="2026-10-15T07:00:00Z",
                                    window_end="2026-10-15T09:00:00Z", scope="INSPECTION")
        scenario = setup_draft_excursion(car_specs=[], with_crew=False)
        return coach, scenario["excursion"]

    def test_class_mismatch_beats_maintenance_window_conflict(self, api, scheduler_headers):
        """PRD §2.9: "Requests are validated against a fixed priority pipeline, and when
        several checks could fail, the earliest tier's error is the one returned."
        PRD §3.3: "The `class_code` must agree with the unit's `stock_type`: a
        `LOCOMOTIVE` maps to `LOCO`, a `COACH_CAR` to `COACH`, a `FIRST_CLASS_CAR` to
        `FIRST_CLASS`, and a `DINING_CAR` to `DINING`, with any other pairing rejected as
        `ERR_CLASS_STOCK_MISMATCH`."
        PRD §2.9 (tier 8 lead-in): "**Shape and constraint rules**, evaluated in this
        exact sub-order: (a) surge bounds by `event_type` (`ERR_SURGE_MULTIPLIER_INVALID`);
        (b) `class_code` versus `stock_type` compatibility (`ERR_CLASS_STOCK_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_car_assign
        """
        coach, excursion = self._setup()

        # DINING on a COACH_CAR violates tier 8(b); the same unit's intersecting
        # work-order window would violate tier 9(d). Tier 8 wins.
        res = api.create_car_assignment(
            create_car_assignment_payload(excursion["id"], coach["id"], "DINING", 1),
            scheduler_headers)
        validate_error(res, ApiErrorId.ERR_CLASS_STOCK_MISMATCH.value, expected_status=422)

    def test_rejected_car_assign_creates_nothing(self, api, scheduler_headers):
        """PRD §2.9: "Requests are validated against a fixed priority pipeline, and when
        several checks could fail, the earliest tier's error is the one returned."
        PRD §3.3: "with any other pairing rejected as `ERR_CLASS_STOCK_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_car_assign
        """
        coach, excursion = self._setup()

        res = api.create_car_assignment(
            create_car_assignment_payload(excursion["id"], coach["id"], "DINING", 1),
            scheduler_headers)
        validate_error(res, ApiErrorId.ERR_CLASS_STOCK_MISMATCH.value, expected_status=422)

        data, meta = validate_paginated(
            api.list_car_assignments(scheduler_headers, params={"excursion_id": excursion["id"]}))
        assert data == [], "a rejected consist edit persists no assignment"
        assert meta["total_count"] == 0
