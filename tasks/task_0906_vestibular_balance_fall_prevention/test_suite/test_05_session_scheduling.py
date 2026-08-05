"""Session scheduling constraints: state preconditions, time range, temporal
overlap (clinician + room buffer), the visit cap, and validation precedence."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    register_room,
    setup_finalized_assessment, setup_active_care_plan,
    setup_plan_with_approved_auth, schedule_session,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


# --- B: corner_session_invalid_time_range_rejected ---------------------------

def test_session_equal_start_end_rejected(api):
    """PRD §3.5: "The scheduled_end must be strictly after scheduled_start; an end
    that is equal to or before the start yields ERR_INVALID_TIME_RANGE."

    Design: Corner/validations/corner_session_invalid_time_range_rejected
    """
    ctx = setup_plan_with_approved_auth(api)
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": ctx["room"]["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T10:00:00Z", "scheduled_end": "2026-06-01T10:00:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 400)


# --- B: corner_care_plan_create_requires_finalized_assessment_rejected -------

def test_care_plan_from_draft_assessment_rejected(api):
    """PRD §3.3: "The referenced assessment must be FINALIZED; a plan created from
    an assessment still in DRAFT is rejected with ERR_ASSESSMENT_NOT_FINALIZED."

    Design: Corner/validations/corner_care_plan_create_requires_finalized_assessment_rejected
    """
    ctx = setup_finalized_assessment(api, assessment_overrides={})
    # Build a fresh DRAFT assessment (unfinalized) on the same patient.
    draft = get_success_data(api.create_assessment(
        {"patient_id": ctx["patient"]["id"], "referral_id": ctx["referral"]["id"],
         "clinician_id": ctx["clinician"]["id"], "gait_speed_m_s": 0.55, "tug_seconds": 14.0,
         "berg_balance_score": 18, "medication_count": 5, "self_report_fall_count": 2},
        ctx["clinician_headers"],
    ))
    resp = api.create_care_plan(
        {"patient_id": ctx["patient"]["id"], "assessment_id": draft["id"]}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED, 409)


# --- B: corner_session_requires_auth_approved_rejected -----------------------

def test_schedule_against_pending_authorization_rejected(api):
    """PRD §3.5: "The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and
    the authorization must be `APPROVED` (otherwise `ERR_AUTH_NOT_APPROVED`)."

    Design: Corner/validations/corner_session_requires_auth_approved_rejected
    """
    ctx = setup_active_care_plan(api)
    room = register_room(api)
    auth = get_success_data(api.create_authorization(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "payer_name": "Medicare", "visits_authorized": 5, "allowed_amount_cents": 15000,
         "coinsurance_pct": 0.20},
        INTAKE,
    ))  # left PENDING
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": room["id"], "authorization_id": auth["id"],
         "scheduled_start": "2026-06-01T10:00:00Z", "scheduled_end": "2026-06-01T11:00:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED, 409)


# --- A13: cross_entity_state_dependency / session_requires_care_plan_active ---

def _draft_plan_with_approved_auth(api):
    """FINALIZED assessment -> DRAFT (never activated) plan -> APPROVED auth."""
    ctx = setup_finalized_assessment(api)
    room = register_room(api)
    cp = get_success_data(api.create_care_plan(
        {"patient_id": ctx["patient"]["id"], "assessment_id": ctx["assessment"]["id"]}, INTAKE))
    auth = get_success_data(api.create_authorization(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": cp["id"], "payer_name": "Medicare",
         "visits_authorized": 5, "allowed_amount_cents": 15000, "coinsurance_pct": 0.20}, INTAKE))
    get_success_data(api.decide_authorization(auth["id"], {"decision": "APPROVE"}, SUPER))
    return ctx, cp, room, auth


def test_schedule_on_draft_plan_rejected_even_with_approved_auth(api):
    """PRD §3.3: "Scheduling sessions, linking to community programs, and opening
    reassessments are all permitted only while the plan is ACTIVE; attempting any
    of them against a non-ACTIVE plan is rejected with ERR_PLAN_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/session_requires_care_plan_active
    """
    ctx, cp, room, auth = _draft_plan_with_approved_auth(api)
    resp = api.create_session(
        {"care_plan_id": cp["id"], "clinician_id": ctx["clinician"]["id"], "room_id": room["id"],
         "authorization_id": auth["id"], "scheduled_start": "2026-06-01T10:00:00Z",
         "scheduled_end": "2026-06-01T11:00:00Z", "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE, 409)


def test_schedule_on_draft_plan_returns_409_status(api):
    """PRD §3.3: "Scheduling sessions, linking to community programs, and opening
    reassessments are all permitted only while the plan is `ACTIVE`; attempting any
    of them against a non-`ACTIVE` plan is rejected with `ERR_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/session_requires_care_plan_active
    """
    ctx, cp, room, auth = _draft_plan_with_approved_auth(api)
    resp = api.create_session(
        {"care_plan_id": cp["id"], "clinician_id": ctx["clinician"]["id"], "room_id": room["id"],
         "authorization_id": auth["id"], "scheduled_start": "2026-06-01T10:00:00Z",
         "scheduled_end": "2026-06-01T11:00:00Z", "cpt_code": "97116"},
        INTAKE,
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_PLAN_NOT_ACTIVE"


# --- A11: boundary_precision_check / visit_cap_exact_boundary_on_sessions -----

def test_session_under_cap_accepted(api):
    """PRD §3.5: "a session may be reserved only while the authorization's
    visits_used is strictly below its visits_authorized."

    Design: Difficulty/boundary_precision_check/visit_cap_exact_boundary_on_sessions
    """
    ctx = setup_plan_with_approved_auth(api, auth_overrides={"visits_authorized": 2})
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")  # used -> 1
    s2 = schedule_session(api, ctx, scheduled_start="2026-06-01T11:15:00Z",
                          scheduled_end="2026-06-01T12:15:00Z")  # used 1 < 2 -> accepted
    assert s2["attendance_status"] == "SCHEDULED"
    auth = get_success_data(api.get_authorization(ctx["authorization"]["id"], INTAKE))
    assert auth["visits_used"] == 2


def test_session_at_cap_rejected(api):
    """PRD §3.5: "If reserving another visit would bring visits_used to or beyond
    the cap, the request is rejected with ERR_VISIT_CAP_EXCEEDED."

    Design: Difficulty/boundary_precision_check/visit_cap_exact_boundary_on_sessions
    """
    ctx = setup_plan_with_approved_auth(api, auth_overrides={"visits_authorized": 2})
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")
    schedule_session(api, ctx, scheduled_start="2026-06-01T11:15:00Z",
                     scheduled_end="2026-06-01T12:15:00Z")  # used -> 2 (at cap)
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": ctx["room"]["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T12:30:00Z", "scheduled_end": "2026-06-01T13:30:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_CAP_EXCEEDED, 409)
    auth = get_success_data(api.get_authorization(ctx["authorization"]["id"], INTAKE))
    assert auth["visits_used"] == 2


# --- A15: resource_temporal_overlap / clinician_half_open_overlap ------------

def test_clinician_overlapping_slot_rejected(api):
    """PRD §3.5: "no other non-cancelled session for the same clinician may overlap
    the requested half-open interval; because intervals are half-open, one session
    ending exactly when another begins is allowed, but any true overlap is rejected
    with ERR_CLINICIAN_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/clinician_half_open_overlap
    """
    ctx = setup_plan_with_approved_auth(api)
    room2 = register_room(api, name="Room R2", room_type="GAIT_LAB")
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": room2["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T10:30:00Z", "scheduled_end": "2026-06-01T11:30:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED, 409)


def test_clinician_adjacent_slot_accepted(api):
    """PRD §3.5: "because intervals are half-open, one session ending exactly when
    another begins is allowed".

    Design: Difficulty/resource_temporal_overlap/clinician_half_open_overlap
    """
    ctx = setup_plan_with_approved_auth(api)
    room2 = register_room(api, name="Room R2", room_type="GAIT_LAB")
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")
    s3 = schedule_session(api, ctx, room_id=room2["id"],
                          scheduled_start="2026-06-01T11:00:00Z",
                          scheduled_end="2026-06-01T12:00:00Z")
    assert s3["attendance_status"] == "SCHEDULED"


# --- A16: resource_temporal_overlap / room_buffer_gap_conflict ---------------

def test_room_buffer_10min_gap_rejected(api):
    """PRD §3.5: "sessions sharing a room must respect a fifteen-minute turnover
    buffer: the gap between the earlier session's end and the later session's start
    must be at least fifteen minutes, and any overlap is likewise rejected; a
    violation yields ERR_ROOM_BUFFER_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/room_buffer_gap_conflict
    """
    ctx = setup_plan_with_approved_auth(api)
    # A second clinician so the clinician rule cannot fire; conflict is room-only.
    from test_helpers import register_clinician
    clin2 = register_clinician(api)
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")  # clinician C1, room R
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": clin2["id"],
         "room_id": ctx["room"]["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T11:10:00Z", "scheduled_end": "2026-06-01T12:10:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_BUFFER_CONFLICT, 409)


def test_room_buffer_conflict_fires_with_different_clinician(api):
    """PRD §3.5: "sessions sharing a room must respect a fifteen-minute turnover
    buffer: the gap between the earlier session's end and the later session's start
    must be at least fifteen minutes, and any overlap is likewise rejected; a
    violation yields `ERR_ROOM_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_buffer_gap_conflict
    """
    ctx = setup_plan_with_approved_auth(api)
    from test_helpers import register_clinician
    clin2 = register_clinician(api)
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": clin2["id"],
         "room_id": ctx["room"]["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T11:10:00Z", "scheduled_end": "2026-06-01T12:10:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    # Different clinician => clinician rule cannot fire; the room buffer is the cause.
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_ROOM_BUFFER_CONFLICT"


# --- A9: priority_pair_validation_conflict / plan_state_beats_visit_cap_fiscal

def _plan_at_cap_then_under_reassessment(api):
    ctx = setup_plan_with_approved_auth(api, auth_overrides={"visits_authorized": 1})
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")  # fills the 1-visit cap
    get_success_data(api.create_reassessment(
        ctx["care_plan"]["id"],
        {"clinician_id": ctx["clinician"]["id"], "gait_speed_m_s": 0.55, "tug_seconds": 14.0,
         "berg_balance_score": 18, "medication_count": 5, "self_report_fall_count": 2},
        ctx["clinician_headers"]))  # plan -> UNDER_REASSESSMENT
    return ctx


def test_plan_not_active_preempts_visit_cap(api):
    """PRD §2.8: "an earlier check always pre-empts a later one." PRD §2.8 lists the
    state checks (ERR_PLAN_NOT_ACTIVE) before "the visit-cap check
    (ERR_VISIT_CAP_EXCEEDED)".

    Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_visit_cap_fiscal
    """
    ctx = _plan_at_cap_then_under_reassessment(api)
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": ctx["room"]["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T12:00:00Z", "scheduled_end": "2026-06-01T13:00:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE, 409)


def test_plan_state_conflict_is_not_visit_cap_error(api):
    """PRD §2.8: "the generic state check and its specific siblings (...,
    ERR_PLAN_NOT_ACTIVE, ...)" precede "the visit-cap check
    (ERR_VISIT_CAP_EXCEEDED)".

    Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_visit_cap_fiscal
    """
    ctx = _plan_at_cap_then_under_reassessment(api)
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": ctx["room"]["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T12:00:00Z", "scheduled_end": "2026-06-01T13:00:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    assert resp.json()["data"]["error_id"] != "ERR_VISIT_CAP_EXCEEDED"


# --- A10: priority_pair_validation_conflict / clinician_temporal_beats_visit_cap_fiscal

def _plan_at_cap_with_second_room(api):
    ctx = setup_plan_with_approved_auth(api, auth_overrides={"visits_authorized": 1})
    room2 = register_room(api, name="Room R2", room_type="EXAM")
    schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z")  # fills 1-visit cap, room R1
    return ctx, room2


def test_clinician_double_booked_preempts_visit_cap(api):
    """PRD §2.8: "the two scheduling-conflict checks (`ERR_CLINICIAN_DOUBLE_BOOKED`
    and `ERR_ROOM_BUFFER_CONFLICT`), the visit-cap check (`ERR_VISIT_CAP_EXCEEDED`)"
    — listed in that pre-empting order.

    Design: Difficulty/priority_pair_validation_conflict/clinician_temporal_beats_visit_cap_fiscal
    """
    ctx, room2 = _plan_at_cap_with_second_room(api)
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": room2["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T10:30:00Z", "scheduled_end": "2026-06-01T11:30:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED, 409)


def test_clinician_temporal_conflict_is_not_visit_cap_error(api):
    """PRD §2.8: "Within a single operation, an earlier check always pre-empts a
    later one." (double-booking precedes the visit-cap check).

    Design: Difficulty/priority_pair_validation_conflict/clinician_temporal_beats_visit_cap_fiscal
    """
    ctx, room2 = _plan_at_cap_with_second_room(api)
    resp = api.create_session(
        {"care_plan_id": ctx["care_plan"]["id"], "clinician_id": ctx["clinician"]["id"],
         "room_id": room2["id"], "authorization_id": ctx["authorization"]["id"],
         "scheduled_start": "2026-06-01T10:30:00Z", "scheduled_end": "2026-06-01T11:30:00Z",
         "cpt_code": "97116"},
        INTAKE,
    )
    assert resp.json()["data"]["error_id"] != "ERR_VISIT_CAP_EXCEEDED"
