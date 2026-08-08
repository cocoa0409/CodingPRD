"""Sessions and the authorization visit ledger: the reserved/used dual variant,
parallel clinical/billing dimensions, the visit-cap boundary, reservation
compensation on cancel, the therapist double-booking buffer, validation-priority
conflicts on session create, isolated window checks, and list pagination.

Queue A: dual_variant_visit_ledger_reserved_vs_used, nonlinear_session_parallel_dimensions,
boundary_visit_cap_reached_exact, compensating_visit_release_conserves_available,
overlap_therapist_within_buffer, priority_state_beats_fiscal_on_session_create,
priority_referential_beats_temporal_on_session_create.
Queue B: error_session_outside_auth_window_isolated, pagination_sessions_list.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_patient,
    create_finalized_evaluation,
    create_approved_authorization,
    create_active_plan,
    create_therapist,
    create_scheduled_session,
    setup_active_plan_scenario,
    setup_scheduled_session_scenario,
    setup_exhausted_auth_and_held_plan,
)

CLINICIAN = TEST_USERS["clinician_headers"]
AUTHORIZER = TEST_USERS["authorizer_headers"]


# ---- Queue A: dual_variant_visit_ledger_reserved_vs_used (>=2 tests) ----

def test_scheduled_session_counts_as_reserved_not_used(api):
    """PRD §2.8: "visits_reserved is the count of sessions on the authorization whose
    clinical_status is SCHEDULED or CHECKED_IN. visits_used is the count of sessions
    whose clinical_status is COMPLETED or NO_SHOW."

    Design: Difficulty/dual_variant_calc/dual_variant_visit_ledger_reserved_vs_used
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    auth = get_success_data(api.get_authorization(s["authorization"]["id"], AUTHORIZER))
    assert auth["visits_reserved"] == 1
    assert auth["visits_used"] == 0
    assert auth["visits_remaining"] == 4


def test_completed_session_moves_reserved_to_used(api):
    """PRD §3.5: "the authorization's visits_used increases by one and visits_reserved
    decreases by one, with visits_remaining recomputed."

    Design: Difficulty/dual_variant_calc/dual_variant_visit_ledger_reserved_vs_used
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    sess_id = s["session"]["id"]
    get_success_data(api.check_in_session(sess_id, CLINICIAN))
    get_success_data(api.complete_session(sess_id, CLINICIAN))
    auth = get_success_data(api.get_authorization(s["authorization"]["id"], AUTHORIZER))
    assert auth["visits_reserved"] == 0
    assert auth["visits_used"] == 1
    assert auth["visits_remaining"] == 4
    sess = get_success_data(api.get_session(sess_id, CLINICIAN))
    assert sess["clinical_status"] == "COMPLETED"
    assert sess["billing_status"] == "BILLED"


# ---- Queue A: nonlinear_session_parallel_dimensions (>=2 tests) ----

def test_session_check_in_advances_clinical_only(api):
    """PRD §3.5: "Check-in requires SCHEDULED and advances the session to CHECKED_IN;
    the visit remains reserved (still counted in visits_reserved), and billing stays
    RESERVED."

    Design: Difficulty/non_linear_state_machine/nonlinear_session_parallel_dimensions
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    assert s["session"]["clinical_status"] == "SCHEDULED"
    assert s["session"]["billing_status"] == "RESERVED"
    checked = validate_success(api.check_in_session(s["session"]["id"], CLINICIAN))
    assert checked["clinical_status"] == "CHECKED_IN"
    assert checked["billing_status"] == "RESERVED"


def test_session_completion_advances_both_dimensions(api):
    """PRD §3.5: "Completion requires CHECKED_IN and advances the session to COMPLETED.
    This triggers the cascade: the billing dimension moves RESERVED → BILLED."

    Design: Difficulty/non_linear_state_machine/nonlinear_session_parallel_dimensions
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    get_success_data(api.check_in_session(s["session"]["id"], CLINICIAN))
    completed = validate_success(api.complete_session(s["session"]["id"], CLINICIAN))
    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "BILLED"


# ---- Queue A: boundary_visit_cap_reached_exact (>=2 tests) ----

def test_session_rejected_when_cap_fully_reserved(api):
    """PRD §3.5: "a new session may reserve a visit only when the sum of visits_reserved
    and visits_used on the authorization is strictly less than visit_cap. If reserving
    would reach or exceed the cap, the create is rejected with ERR_VISIT_CAP_EXCEEDED."

    Design: Difficulty/boundary_precision_check/boundary_visit_cap_reached_exact
    """
    s = setup_scheduled_session_scenario(visit_cap=1)  # reserved==1==cap
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-06-02T09:00:00Z", "scheduled_end": "2026-06-02T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_CAP_EXCEEDED)


def test_session_accepted_when_cap_not_yet_reached(api):
    """PRD §3.5: "a new session may reserve a visit only when the sum of visits_reserved
    and visits_used on the authorization is strictly less than visit_cap."

    Design: Difficulty/boundary_precision_check/boundary_visit_cap_reached_exact
    """
    s = setup_scheduled_session_scenario(visit_cap=2)  # reserved==1 < cap 2
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-06-02T09:00:00Z", "scheduled_end": "2026-06-02T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    validate_success(resp, expected_status=201)


# ---- Queue A: compensating_visit_release_conserves_available (>=2 tests) ----

def test_scheduling_reserves_one_visit(api):
    """PRD §3.5: "it increments the authorization's visits_reserved by one (with
    visits_remaining recomputed accordingly)."

    Design: Difficulty/compensating_invariant/compensating_visit_release_conserves_available
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    auth = get_success_data(api.get_authorization(s["authorization"]["id"], AUTHORIZER))
    assert auth["visits_reserved"] == 1
    assert auth["visits_remaining"] == 4


def test_cancelling_session_releases_reservation(api):
    """PRD §3.5: "Cancellation requires the session to be SCHEDULED or CHECKED_IN and
    advances it to CANCELLED. Billing moves RESERVED → VOID, and the reservation is
    released as compensation: visits_reserved decreases by one, visits_remaining is
    recomputed, and no visits_used debit is recorded."

    Design: Difficulty/compensating_invariant/compensating_visit_release_conserves_available
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    get_success_data(api.cancel_session(s["session"]["id"], CLINICIAN))
    auth = get_success_data(api.get_authorization(s["authorization"]["id"], AUTHORIZER))
    assert auth["visits_reserved"] == 0
    assert auth["visits_used"] == 0
    assert auth["visits_remaining"] == 5


# ---- Queue A: overlap_therapist_within_buffer (>=2 tests) ----

def test_second_session_within_buffer_double_booked(api):
    """PRD §3.5: "the create is rejected with ERR_THERAPIST_DOUBLE_BOOKED if any existing
    session for the same therapist_id whose clinical_status is SCHEDULED, CHECKED_IN, or
    COMPLETED sits within a fifteen-minute buffer of the new interval."

    Design: Difficulty/resource_temporal_overlap/overlap_therapist_within_buffer
    """
    s = setup_scheduled_session_scenario(
        visit_cap=5, scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T10:00:00Z",
    )
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-06-01T10:10:00Z", "scheduled_end": "2026-06-01T11:00:00Z",
         "cdt_component": "EXERCISE"},
        CLINICIAN,
    )
    validate_error(resp, ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED)


def test_second_session_beyond_buffer_allowed(api):
    """PRD §3.5: "The assigned therapist must not be double-booked: the create is
    rejected with ERR_THERAPIST_DOUBLE_BOOKED if any existing session for the same
    therapist_id whose clinical_status is SCHEDULED, CHECKED_IN, or COMPLETED sits within
    a fifteen-minute buffer of the new interval."

    Design: Difficulty/resource_temporal_overlap/overlap_therapist_within_buffer
    """
    s = setup_scheduled_session_scenario(
        visit_cap=5, scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T10:00:00Z",
    )
    # A session hours later is well beyond the 15-minute buffer.
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-06-01T13:00:00Z", "scheduled_end": "2026-06-01T14:00:00Z",
         "cdt_component": "EXERCISE"},
        CLINICIAN,
    )
    validate_success(resp, expected_status=201)


# ---- Queue A: priority_state_beats_fiscal_on_session_create (>=2 tests) ----

def test_state_error_preempts_fiscal_on_session_create(api):
    """PRD §2.5: "This ordering is normative: when more than one condition is violated,
    the lower-numbered category wins."
    PRD §3.5: "The plan must be ACTIVE, otherwise ERR_PLAN_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_session_create
    """
    s = setup_exhausted_auth_and_held_plan()  # plan ON_HOLD and cap fully consumed
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-07-01T09:00:00Z", "scheduled_end": "2026-07-01T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


def test_fiscal_error_not_returned_when_state_also_fails(api):
    """PRD §2.5: "when more than one condition is violated, the lower-numbered category
    wins."
    PRD §3.5: "If reserving would reach or exceed the cap, the create is rejected with
    ERR_VISIT_CAP_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_session_create
    """
    s = setup_exhausted_auth_and_held_plan()
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-07-02T09:00:00Z", "scheduled_end": "2026-07-02T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    err = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
    assert err["error_id"] != ApiErrorId.ERR_VISIT_CAP_EXCEEDED.value


# ---- Queue A: priority_referential_beats_temporal_on_session_create (>=2 tests) ----

def _two_auth_setup():
    patient = create_patient()
    evaluation = create_finalized_evaluation(patient["id"], body_region="LEFT_ARM")
    auth1 = create_approved_authorization(
        patient["id"], body_region="LEFT_ARM", auth_number="AUTH-1",
        effective_start_date="2026-05-01", effective_end_date="2026-12-31",
    )
    auth2 = create_approved_authorization(
        patient["id"], body_region="RIGHT_ARM", auth_number="AUTH-2",
        effective_start_date="2026-05-01", effective_end_date="2026-05-02",
    )
    plan = create_active_plan(patient["id"], evaluation["id"], auth1["id"])
    therapist = create_therapist()
    return plan, auth2, therapist


def test_referential_error_preempts_temporal_on_session_create(api):
    """PRD §3.5: "The session's authorization_id must equal the plan's own
    authorization_id, otherwise ERR_AUTH_PLAN_MISMATCH."

    Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_temporal_on_session_create
    """
    plan, auth2, therapist = _two_auth_setup()
    # auth2 != plan's auth (referential fails) AND 2026-06-01 is outside auth2's window.
    resp = api.create_session(
        {"plan_id": plan["id"], "authorization_id": auth2["id"], "therapist_id": therapist["id"],
         "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_PLAN_MISMATCH)


def test_temporal_error_not_returned_when_referential_also_fails(api):
    """PRD §2.5: "when more than one condition is violated, the lower-numbered category
    wins."
    PRD §3.5: "The session's [scheduled_start, scheduled_end] interval must fall entirely
    within the authorization's [effective_start_date, effective_end_date] window,
    otherwise ERR_SESSION_OUTSIDE_AUTH_WINDOW."

    Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_temporal_on_session_create
    """
    plan, auth2, therapist = _two_auth_setup()
    resp = api.create_session(
        {"plan_id": plan["id"], "authorization_id": auth2["id"], "therapist_id": therapist["id"],
         "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    err = validate_error(resp, ApiErrorId.ERR_AUTH_PLAN_MISMATCH)
    assert err["error_id"] != ApiErrorId.ERR_SESSION_OUTSIDE_AUTH_WINDOW.value


# ---- Queue B: session outside auth window (isolated) ----

def test_session_outside_auth_window_rejected(api):
    """PRD §3.5: "The session's [scheduled_start, scheduled_end] interval must fall
    entirely within the authorization's [effective_start_date, effective_end_date]
    window, otherwise ERR_SESSION_OUTSIDE_AUTH_WINDOW."

    Design: Corner/validations/error_session_outside_auth_window_isolated
    """
    s = setup_active_plan_scenario(visit_cap=5, effective_end_date="2026-05-10")
    resp = api.create_session(
        {"plan_id": s["plan"]["id"], "authorization_id": s["authorization"]["id"],
         "therapist_id": s["therapist"]["id"],
         "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T10:00:00Z",
         "cdt_component": "MLD"},
        CLINICIAN,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OUTSIDE_AUTH_WINDOW)


# ---- Queue B: pagination on session listing ----

def test_session_list_reports_pagination_meta(api):
    """PRD §2.3: "Every list response echoes limit, offset, total_count, and has_more
    inside the meta object."

    Design: Corner/endpoints/pagination_sessions_list
    """
    s = setup_active_plan_scenario(visit_cap=5)
    create_scheduled_session(
        s["plan"]["id"], s["authorization"]["id"], s["therapist"]["id"],
        scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T10:00:00Z",
    )
    create_scheduled_session(
        s["plan"]["id"], s["authorization"]["id"], s["therapist"]["id"],
        scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T10:00:00Z",
        cdt_component="EXERCISE",
    )
    resp = api.list_sessions(CLINICIAN, params={"plan_id": s["plan"]["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
