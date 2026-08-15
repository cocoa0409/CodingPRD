"""Disorder inspections below the decay threshold, and the seal-time ordering of
the oxygen safety gate over the temporal gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_disorder_inspection,
    assert_same_instant,
    get_success_data,
    record_inspection,
    record_o2_reading,
    seal_payload,
    setup_sealed_storage,
    setup_stored_lot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]


class TestInspectionBelowThreshold:
    def test_inspection_below_threshold_no_cascade(self, api):
        """PRD §3.3: "The inspection's `disorder_index` blends the three samples:
        twenty percent of the scald figure, plus thirty percent of the bitter-pit
        figure, plus fifty percent of the decay figure, rounded half-up to two
        decimal places."
        PRD §3.3: "When an inspection's `decay_pct` reaches at least 5.0 percent —
        the threshold is inclusive — the priority-release cascade fires
        immediately."
        PRD §3.3: "An allocation's `release_priority_score` is the sum of five
        terms: twice the room's `disorder_index`; forty points while the room's
        `atmosphere_alarm` is set; thirty points while the room's
        `priority_release` is set; the whole days the room has been open —
        measured with whole-day floor semantics from `actual_opened_at` to the
        current logical clock, and zero while the room is not `OPENED` — capped at
        twenty; and an urgency term of thirty minus the whole days remaining until
        the allocation's own `must_release_by`"

        decay 4.9 sits below the inclusive 5.0 threshold, so only the blend
        applies: disorder_index 4.15 and, with every conditional branch off and
        the deadline 240 days out (urgency 0), the score is exactly 2 x 4.15.

        Design: Corner/calculations/c_inspection_below_threshold_no_cascade
        """
        ctx = setup_sealed_storage()
        inspection = record_inspection(ctx["room"]["id"], scald_pct=4.0,
                                       bitter_pit_pct=3.0, decay_pct=4.9)
        assert_disorder_inspection(inspection)
        assert inspection["disorder_index"] == pytest.approx(4.15, abs=1e-9), (
            "0.2*4 + 0.3*3 + 0.5*4.9"
        )

        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["priority_release"] is False, "no cascade below the threshold"
        assert room["disorder_index"] == pytest.approx(4.15, abs=1e-9), (
            "the room reflects the latest inspection"
        )
        assert room["status"] == "SEALED"
        assert_same_instant(room["planned_open_date"],
                            ctx["room"]["planned_open_date"],
                            "planned_open_date unchanged without the cascade")

        allocation = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], ADMIN))
        assert allocation["release_priority_score"] == pytest.approx(8.3, abs=1e-6), (
            "2 x 4.15; alarm and priority branches off, room not OPENED, "
            "deadline far out"
        )


class TestSealSafetyBeatsTemporal:
    def test_seal_off_setpoint_and_past_date_reports_safety(self, api):
        """PRD §3.2: "Two further gates apply, in the order of §2.9: the safety
        gate requires the absolute difference between `current_o2_pct` and
        `o2_setpoint_pct` to be no greater than the oxygen tolerance
        `O2_TOLERANCE_PCT`, compared with exact decimal arithmetic — equality is
        within tolerance and passes, while a strictly greater deviation is
        rejected with `ERR_O2_NOT_AT_SETPOINT`; the temporal gate requires the
        supplied `planned_open_date` to lie strictly after the current logical
        clock, else `ERR_OPEN_DATE_NOT_FUTURE`."
        PRD §2.9: "When several checks would fail on a single call, the first
        applicable tier below determines the response."

        The room still reads ambient air (20.9) against a 1.5 setpoint — a
        deviation that exceeds any tolerance the scale admits in practice — and
        the requested open date is in the past; the safety tier reports first.

        Design: Difficulty/priority_pair_validation_conflict/seal_o2_safety_beats_open_date_temporal
        """
        ctx = setup_stored_lot()
        resp = api.seal_ca_room(
            ctx["room"]["id"],
            seal_payload(planned_open_date="2026-07-01T00:00:00Z"), STORAGE)
        validate_error(resp, ApiErrorId.ERR_O2_NOT_AT_SETPOINT)  # 409, not 422

        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["status"] == "FILLING", "no partial seal"
        assert room["sealed_at"] is None

    def test_seal_off_setpoint_alone_reports_safety_then_recovers(self, api):
        """PRD §3.2: "the safety gate requires the absolute difference between
        `current_o2_pct` and `o2_setpoint_pct` to be no greater than the oxygen
        tolerance `O2_TOLERANCE_PCT`, compared with exact decimal arithmetic —
        equality is within tolerance and passes, while a strictly greater
        deviation is rejected with `ERR_O2_NOT_AT_SETPOINT`"
        PRD §3.2: "A successful seal records `sealed_at` from the clock, stores
        `planned_open_date`, and transitions the room `FILLING → SEALED`."

        Design: Difficulty/priority_pair_validation_conflict/seal_o2_safety_beats_open_date_temporal
        """
        ctx = setup_stored_lot()

        # Safety alone fails: ambient reading, future open date.
        resp = api.seal_ca_room(ctx["room"]["id"], seal_payload(), STORAGE)
        validate_error(resp, ApiErrorId.ERR_O2_NOT_AT_SETPOINT)

        # Pull oxygen exactly to the setpoint (deviation zero passes at any
        # tolerance) and the same seal succeeds.
        record_o2_reading(ctx["room"]["id"], ctx["room"]["o2_setpoint_pct"])
        sealed = validate_success(api.seal_ca_room(
            ctx["room"]["id"], seal_payload(), STORAGE))
        assert sealed["status"] == "SEALED"
        assert sealed.get("sealed_at") is not None
