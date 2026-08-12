"""Difficulty queue A — priority_pair_validation_conflict instances."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_interview_payload,
    make_investigator_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_state_beats_upjohn_safety_on_completed_from_cancelled(api):
    """PRD §2.8: "6. **State machine legality** — the target entity is in a
    from-state that permits the requested transition and the per-transition
    actor role is honored (`ERR_INVALID_STATE`)." precedes "7.
    **Segregation-of-duties and compliance-safety gates** —
    `ERR_SOD_PLAN_APPROVAL`, `ERR_SOD_FINDING_FINALIZATION`,
    `ERR_SOD_DISCIPLINE_APPROVAL`, `ERR_SOD_REMEDIATION_VERIFICATION`,
    `ERR_SOD_DISCLOSURE_OVERRIDE`, `ERR_UPJOHN_REQUIRED`,
    `ERR_PRIVILEGE_PENDING`, `ERR_PRIVILEGED_DISTRIBUTION`,
    `ERR_COOLING_OFF`, `ERR_ORDERED_NOTICE_RESTRICTION`."
    PRD §3.5 declares the COMPLETED transition's from-state to be
    UPJOHN_DELIVERED; from CANCELLED the state check fails first.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_upjohn_safety
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case PV-1", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-08T14:00:00Z",
            scheduled_end="2026-05-08T15:00:00Z",
        ),
        INV,
    ))
    get_success_data(api.transition_interview(interview["id"], {"to_status": "CANCELLED"}, INV))
    resp = api.transition_interview(
        interview["id"], {"to_status": "COMPLETED", "completion_note": "memo"}, INV
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_state_beats_upjohn_safety_state_unchanged(api):
    """PRD §3.5: "Either `SCHEDULED` or `UPJOHN_DELIVERED` may also transition
    to `CANCELLED`; on the latter path `upjohn_delivered_at` is retained for
    audit."
    PRD §2.8 step 6 precedes step 7: a rejected COMPLETED from CANCELLED must
    leave the interview in CANCELLED with no Upjohn stamp.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_upjohn_safety
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case PV-1", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-08T14:00:00Z",
            scheduled_end="2026-05-08T15:00:00Z",
        ),
        INV,
    ))
    get_success_data(api.transition_interview(interview["id"], {"to_status": "CANCELLED"}, INV))
    api.transition_interview(
        interview["id"], {"to_status": "COMPLETED", "completion_note": "memo"}, INV
    )
    after = get_success_data(api.get_interview(interview["id"], INV))
    assert after["status"] == "CANCELLED"
    assert after.get("upjohn_delivered_at") is None


def _setup_constraint_vs_temporal_scene(api):
    """Case FIELDWORK; interviewer inv-9 holds I1 [2026-05-10 14:00-15:00Z]
    SCHEDULED; I2 [2026-05-11 14:00-15:00Z] went NO_SHOW after clock moved
    to 2026-05-12."""
    bundle = create_case_in_fieldwork(
        title="Case PV-2", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    i1 = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    i2 = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-2", interviewer_id="inv-9",
            scheduled_start="2026-05-11T14:00:00Z",
            scheduled_end="2026-05-11T15:00:00Z",
        ),
        INV,
    ))
    reset_clock("2026-05-12T00:00:00Z")
    get_success_data(api.transition_interview(i2["id"], {"to_status": "NO_SHOW"}, INV))
    return {"case": case, "i1": i1, "i2": i2}


def test_constraint_beats_temporal_on_reschedule_error_id(api):
    """PRD §2.8: "8. **Business constraints** — uniqueness, overlap,
    threshold, and aggregate rules: `ERR_PLAN_SUBMITTED_EXISTS`,
    `ERR_DUPLICATE_SUBJECT`, `ERR_DUPLICATE_DESIGNATION`,
    `ERR_INTERVIEWER_OVERLAP`, `ERR_ROOM_OVERLAP`, `ERR_SCOPE_OVERLAP`,
    `ERR_OPEN_RECOMMENDATION_EXISTS`, `ERR_THRESHOLD_NOT_MET`,
    `ERR_EMPTY_COLLECTION`, `ERR_OPEN_COLLECTION_SCOPES`,
    `ERR_PRESERVATION_INCOMPLETE`, `ERR_FINDINGS_NOT_FINAL`,
    `ERR_UNRESOLVED_DISCIPLINE`, `ERR_DISCLOSURE_REQUIRED`,
    `ERR_OPEN_REMEDIATION`, `ERR_SUBJECT_HAS_OPEN_FINDINGS`,
    `ERR_VALIDATION`." precedes "10. **Clock-relative rules** —
    `ERR_INTERVIEW_WINDOW_EXPIRED`, `ERR_NO_SHOW_TOO_EARLY`,
    `ERR_SCHEDULE_IN_PAST`, plus internal window-order checks surfaced as
    `ERR_VALIDATION`."

    A reschedule whose new window overlaps the same interviewer's existing
    booking AND whose new_start is in the past must return
    ERR_INTERVIEWER_OVERLAP.

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_reschedule
    """
    reset_clock()
    bundle = _setup_constraint_vs_temporal_scene(api)
    i2 = bundle["i2"]
    resp = api.transition_interview(
        i2["id"],
        {"to_status": "SCHEDULED",
         "new_start": "2026-05-10T14:30:00Z",
         "new_end": "2026-05-10T15:30:00Z"},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_OVERLAP, expected_status=409)


def test_constraint_beats_temporal_on_reschedule_state_unchanged(api):
    """PRD §3.5: "From `NO_SHOW` the interview may be rescheduled back to
    `SCHEDULED`: the payload must carry `new_start` and `new_end`
    (`ERR_MISSING_REQUIRED_FIELD` when absent), with `new_start` strictly
    before `new_end` (`ERR_VALIDATION` otherwise), `new_start` must be no
    earlier than the current logical clock (`ERR_SCHEDULE_IN_PAST`), the
    interviewer half-open overlap check is re-run on the new window
    (`ERR_INTERVIEWER_OVERLAP`), and the room fifteen-minute-buffer overlap
    check is re-run when `room_ref` is present (`ERR_ROOM_OVERLAP`)."

    A rejected reschedule leaves the interview in NO_SHOW.

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_reschedule
    """
    reset_clock()
    bundle = _setup_constraint_vs_temporal_scene(api)
    i2 = bundle["i2"]
    api.transition_interview(
        i2["id"],
        {"to_status": "SCHEDULED",
         "new_start": "2026-05-10T14:30:00Z",
         "new_end": "2026-05-10T15:30:00Z"},
        INV,
    )
    after = get_success_data(api.get_interview(i2["id"], INV))
    assert after["status"] == "NO_SHOW"
