"""Spill response: classification boundary, the report cascade, hold/restore,
the recontamination loop, and the report/clear duty split."""
from test_helpers import (
    TEST_USERS,
    advance_spill,
    assert_spill_incident,
    create_isotope,
    create_room,
    create_spill_incident_payload,
    get_appointment,
    get_order,
    get_room,
    get_vial,
    make_radiopharmacist_headers,
    make_rso_headers,
    record_survey,
    set_clock,
    setup_f18_spill_contamination,
    setup_spill_room_only,
    validate_error,
    validate_success,
    work_spill_to_decontaminated,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSpillClassificationBoundary:
    """Inclusive threshold: estimated activity at or above the isotope's
    spill_major_threshold_mbq (37) classifies MAJOR."""

    def test_estimate_equal_to_threshold_is_major(self, api):
        """PRD §3.6: "The `classification` rule is an inclusive threshold
        comparison: an estimated activity at or above the isotope's
        `spill_major_threshold_mbq` classifies the incident `MAJOR`, and
        anything below it classifies the incident `MINOR`."

        37.000 == threshold -> MAJOR.

        Design: Difficulty/boundary_precision_check/spill_threshold_inclusive_major
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        room = create_room(name="Room-A")
        spill = validate_success(
            api.create_spill_incident(
                create_spill_incident_payload(
                    room["id"], iso["id"],
                    estimated_activity_mbq=37, occurred_at="2026-08-01T08:00:00Z",
                ),
                make_radiopharmacist_headers("rp-1"),
            ),
            201,
        )
        assert_spill_incident(spill)
        assert spill["classification"] == "MAJOR"

    def test_estimate_just_below_threshold_is_minor(self, api):
        """PRD §3.6: "The `classification` rule is an inclusive threshold
        comparison: an estimated activity at or above the isotope's
        `spill_major_threshold_mbq` classifies the incident `MAJOR`, and
        anything below it classifies the incident `MINOR`."

        36.999 < threshold -> MINOR.

        Design: Difficulty/boundary_precision_check/spill_threshold_inclusive_major
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        room = create_room(name="Room-B")
        spill = validate_success(
            api.create_spill_incident(
                create_spill_incident_payload(
                    room["id"], iso["id"],
                    estimated_activity_mbq=36.999, occurred_at="2026-08-01T08:00:00Z",
                ),
                make_radiopharmacist_headers("rp-1"),
            ),
            201,
        )
        assert spill["classification"] == "MINOR"


class TestSpillReportCascade:
    """Depth-3 chain from spill creation: room -> CONTAMINATED; BOOKED
    appointments with end_at later than occurred_at -> AUTO_VOIDED; each voided
    appointment's order -> ON_HOLD; that order's PREPARED/CALIBRATED vials ->
    QUARANTINED."""

    def test_room_contaminated_and_appointment_auto_voided(self, api):
        """PRD §3.6: "Creation itself fires the room cascade. The room
        transitions from `OPERATIONAL` to `CONTAMINATED`. Every `BOOKED`
        appointment in that room whose `end_at` is later than the spill's
        `occurred_at` transitions to `AUTO_VOIDED`, with `void_reason` set to
        the incident's id."

        Design: Difficulty/transitive_cascade/spill_report_cascade_depth3
        """
        ctx = setup_f18_spill_contamination()
        assert get_room(ctx["room"]["id"])["status"] == "CONTAMINATED"

        appt = get_appointment(ctx["appointment"]["id"])
        assert appt["status"] == "AUTO_VOIDED"
        assert appt["void_reason"] == ctx["spill"]["id"]

    def test_order_held_and_vial_quarantined(self, api):
        """PRD §3.6: "Each voided appointment's order, if in `ORDERED` or
        `DOSE_PREPARED`, moves to `ON_HOLD` with `hold_reason` set to
        `SPILL_CONTAMINATION` and `hold_previous_status` recording its prior
        status. That order's vials in `PREPARED` or `CALIBRATED` move to
        `QUARANTINED`..."

        Design: Difficulty/transitive_cascade/spill_report_cascade_depth3
        """
        ctx = setup_f18_spill_contamination()
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "ON_HOLD"
        assert order["hold_reason"] == "SPILL_CONTAMINATION"
        assert order["hold_previous_status"] == "DOSE_PREPARED"

        vial = get_vial(ctx["vial"]["id"])
        assert vial["status"] == "QUARANTINED"


class TestHoldRestoreCycle:
    """DoseOrder cycle DOSE_PREPARED -> ON_HOLD -> DOSE_PREPARED via the spill
    cascade and its clearance compensation."""

    def test_hold_records_previous_status(self, api):
        """PRD §3.6: "Each voided appointment's order, if in `ORDERED` or
        `DOSE_PREPARED`, moves to `ON_HOLD` with `hold_reason` set to
        `SPILL_CONTAMINATION` and `hold_previous_status` recording its prior
        status."

        The order was DOSE_PREPARED when the spill fired, so
        hold_previous_status must record DOSE_PREPARED (not ORDERED).

        Design: Difficulty/non_linear_state_machine/dose_order_hold_restore_cycle
        """
        ctx = setup_f18_spill_contamination()
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "ON_HOLD"
        assert order["hold_reason"] == "SPILL_CONTAMINATION"
        assert order["hold_previous_status"] == "DOSE_PREPARED"

    def test_clearance_restores_previous_status(self, api):
        """PRD §3.6: "Every order sitting `ON_HOLD` with `hold_reason` of
        `SPILL_CONTAMINATION` returns to its recorded `hold_previous_status`
        with `hold_reason` cleared, and each such order's `QUARANTINED` vials
        return to `CALIBRATED`."

        Design: Difficulty/non_linear_state_machine/dose_order_hold_restore_cycle
        """
        ctx = setup_f18_spill_contamination()
        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-1")
        record_survey(ctx["room"]["id"], "PASS", "rso-1")
        advance_spill(ctx["spill"]["id"], "CLEARED", "rso-1")

        order = get_order(ctx["order"]["id"])
        assert order["status"] == "DOSE_PREPARED", "restore leg recovers hold_previous_status"
        assert order["hold_reason"] is None

        vial = get_vial(ctx["vial"]["id"])
        assert vial["status"] == "CALIBRATED"
        assert get_room(ctx["room"]["id"])["status"] == "OPERATIONAL"


class TestRecontaminationLoop:
    """SpillIncident cycle DECONTAMINATED -> CONTAINED -> DECONTAMINATED ->
    CLEARED, the loop leg gated by a FAIL survey."""

    def test_loop_leg_succeeds_with_fail_survey(self, api):
        """PRD §3.6: "The recontamination loop runs from `DECONTAMINATED` back to
        `CONTAINED` and is only legal when the latest radiation survey of the
        room recorded at or after `decontaminated_at` has result `FAIL` —
        otherwise the advance is rejected with `ERR_INVALID_STATE`..."

        Design: Difficulty/non_linear_state_machine/spill_recontamination_loop
        """
        ctx = setup_spill_room_only()
        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-1")
        record_survey(ctx["room"]["id"], "FAIL", "rso-1", ambient_dose_rate_usv_h=5.0)

        spill = advance_spill(ctx["spill"]["id"], "CONTAINED", "rso-1")
        assert spill["status"] == "CONTAINED"
        assert get_room(ctx["room"]["id"])["status"] == "CONTAMINATED"

    def test_loop_leg_rejected_without_fail_survey(self, api):
        """PRD §3.6: "The recontamination loop runs from `DECONTAMINATED` back to
        `CONTAINED` and is only legal when the latest radiation survey of the
        room recorded at or after `decontaminated_at` has result `FAIL` —
        otherwise the advance is rejected with `ERR_INVALID_STATE`..."

        The latest survey after decontamination is a PASS, so the loop leg is
        illegal.

        Design: Difficulty/non_linear_state_machine/spill_recontamination_loop
        """
        ctx = setup_spill_room_only()
        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-1")
        record_survey(ctx["room"]["id"], "PASS", "rso-1", ambient_dose_rate_usv_h=0.4)

        res = api.advance_spill_incident(
            ctx["spill"]["id"], {"to_state": "CONTAINED"}, make_rso_headers("rso-1")
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_full_loop_then_clear_restores_room(self, api):
        """PRD §3.6: "Clearance restores the department. Clearing stamps
        `cleared_at` and records `cleared_by_user_id`. If no other non-`CLEARED`
        spill incident references the same room, the room returns to
        `OPERATIONAL`..."

        The loop leg does not re-fire the cascade, and the room posture is
        restored only at clearance.

        Design: Difficulty/non_linear_state_machine/spill_recontamination_loop
        """
        ctx = setup_spill_room_only()
        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-1")
        record_survey(ctx["room"]["id"], "FAIL", "rso-1", ambient_dose_rate_usv_h=5.0)
        advance_spill(ctx["spill"]["id"], "CONTAINED", "rso-1")
        advance_spill(ctx["spill"]["id"], "DECONTAMINATED", "rso-1")
        record_survey(ctx["room"]["id"], "PASS", "rso-1", ambient_dose_rate_usv_h=0.4)

        spill = advance_spill(ctx["spill"]["id"], "CLEARED", "rso-1")
        assert spill["status"] == "CLEARED"
        assert get_room(ctx["room"]["id"])["status"] == "OPERATIONAL"


class TestSpillAdvanceLegality:
    def test_cannot_skip_contained(self, api):
        """PRD §3.6: "Any advance that does not correspond to one of these
        transitions from the incident's current state is rejected with
        `ERR_INVALID_STATE`."

        REPORTED -> DECONTAMINATED skips CONTAINED and is not a declared
        transition.

        Design: Corner/state_machines/spill_advance_cannot_skip_contained
        """
        ctx = setup_spill_room_only()
        res = api.advance_spill_incident(
            ctx["spill"]["id"], {"to_state": "DECONTAMINATED"}, make_rso_headers("rso-1")
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestSpillReporterSegregation:
    def test_reporter_cannot_clear_own_report(self, api):
        """PRD §3.6: "From `DECONTAMINATED`, the incident moves to `CLEARED` only
        when the latest survey of the room recorded at or after
        `decontaminated_at` has result `PASS` (otherwise `ERR_SURVEY_REQUIRED`,
        HTTP 409) and the clearing officer's `X-User-ID` differs from the
        incident's `reported_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

        The spill was reported by rso-1; rso-1's clearance attempt is rejected,
        rso-2's succeeds and the room posture restores.

        Design: Corner/rbac/spill_reporter_cannot_clear_own_report
        """
        ctx = setup_spill_room_only(reporter_headers=make_rso_headers("rso-1"))
        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-2")
        record_survey(ctx["room"]["id"], "PASS", "rso-2", ambient_dose_rate_usv_h=0.4)

        res = api.advance_spill_incident(
            ctx["spill"]["id"], {"to_state": "CLEARED"}, make_rso_headers("rso-1")
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

        spill = advance_spill(ctx["spill"]["id"], "CLEARED", "rso-2")
        assert spill["status"] == "CLEARED"
        assert get_room(ctx["room"]["id"])["status"] == "OPERATIONAL"
