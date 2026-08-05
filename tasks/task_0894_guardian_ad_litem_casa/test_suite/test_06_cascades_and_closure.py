"""Multi-resource cascades: the three-level volunteer-deactivation chain and the
two-level case-close chain, plus the empty-visit-set closure gate.

Queue A (Difficulty): transitive_cascade (deactivate depth-3, close depth-2) and
boundary_precision_check (close with zero logged visits).
Queue B (Corner): terminal-state lockdown on a re-close.
"""
from test_helpers import (
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_active_volunteer_assigned_case,
    setup_case_with_hearing,
    setup_draft_report,
    log_visit,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _assignment_status(api, base, assignment_id):
    data, _ = validate_paginated(api.list_case_assignments(base["case_id"], base["supervisor_headers"]))
    match = [a for a in data if a["id"] == assignment_id]
    assert match, "assignment must be listed on the case"
    return match[0]["status"]


# ---------------------- Difficulty: 3-level volunteer-deactivation cascade
def test_deactivate_ends_assignment_and_zeroes_count(api):
    """PRD 3.9: "At the first level, every `CaseAssignment` of this volunteer whose
    `status` is `ACTIVE` is moved `ACTIVE → ENDED` with `ended_reason`
    `VOLUNTEER_DEACTIVATED`, and the volunteer's `active_case_count` is decremented
    accordingly to 0."

    Design: Difficulty/transitive_cascade/volunteer_deactivate_cascade_depth3
    """
    base = setup_draft_report(api)
    vol = get_success_data(api.deactivate_volunteer(
        base["volunteer_id"], {"reason": "relocated"}, ADMIN))
    assert vol["status"] == "INACTIVE"
    assert vol["active_case_count"] == 0
    assert _assignment_status(api, base, base["assignment_id"]) == "ENDED"


def test_deactivate_unassigns_case_and_voids_draft_report(api):
    """PRD 3.9: "At the second level, each case whose active assignment just ended
    and which was in `ASSIGNED` is moved `ASSIGNED → UNASSIGNED`. At the third
    level, for each case now `UNASSIGNED`, every `CourtReport` still in `DRAFT` or
    `RETURNED` is moved to `VOIDED`."

    Design: Difficulty/transitive_cascade/volunteer_deactivate_cascade_depth3
    """
    base = setup_draft_report(api)
    get_success_data(api.deactivate_volunteer(base["volunteer_id"], {"reason": "relocated"}, ADMIN))
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["status"] == "UNASSIGNED"
    report = get_success_data(api.get_court_report(base["report_id"], base["supervisor_headers"]))
    assert report["status"] == "VOIDED"


# ------------------------------- Difficulty: 2-level case-close cascade
def test_close_case_records_outcome(api):
    """PRD 3.8: "The case's owning supervisor closes the case with a permanency
    outcome of REUNIFICATION, ADOPTION, GUARDIANSHIP, or APPEAL, advancing the case
    to CLOSED from either ASSIGNED or UNASSIGNED (any other state is
    ERR_INVALID_STATE)."

    Design: Difficulty/transitive_cascade/case_close_cascade_depth2
    """
    base = setup_case_with_hearing(api, hearing_type="PERMANENCY")
    log_visit(api, base, contact_start="2026-06-05T10:00:00Z", contact_end="2026-06-05T11:00:00Z")
    closed = get_success_data(api.close_case(base["case_id"], {"outcome": "ADOPTION"}, base["supervisor_headers"]))
    assert closed["status"] == "CLOSED"
    assert closed["outcome"] == "ADOPTION"


def test_close_case_cancels_scheduled_hearings(api):
    """PRD 3.8: "cancels every hearing on the case still in SCHEDULED, moving each
    SCHEDULED → CANCELLED; and increments the case's version by one."

    Design: Difficulty/transitive_cascade/case_close_cascade_depth2
    """
    base = setup_case_with_hearing(api, hearing_type="PERMANENCY")
    log_visit(api, base, contact_start="2026-06-05T10:00:00Z", contact_end="2026-06-05T11:00:00Z")
    get_success_data(api.close_case(base["case_id"], {"outcome": "ADOPTION"}, base["supervisor_headers"]))
    hearings, _ = validate_paginated(api.list_case_hearings(base["case_id"], base["supervisor_headers"]))
    target = [h for h in hearings if h["id"] == base["hearing_id"]]
    assert target and target[0]["status"] == "CANCELLED"


# ---------------------- Difficulty: empty logged-visit set blocks closure
def test_close_with_zero_logged_visits_rejected(api):
    """PRD 3.8: "Closure requires that at least one `Visit` with status `LOGGED`
    exists on the case, else `ERR_NO_VISITS_LOGGED`."

    Design: Difficulty/boundary_precision_check/close_zero_logged_visits_empty_set_boundary
    """
    base = setup_active_volunteer_assigned_case(api)
    resp = api.close_case(base["case_id"], {"outcome": "APPEAL"}, base["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_VISITS_LOGGED.value)


def test_close_with_zero_visits_leaves_case_assigned(api):
    """PRD 3.8: "Closure requires that at least one `Visit` with status `LOGGED`
    exists on the case, else `ERR_NO_VISITS_LOGGED`."

    Design: Difficulty/boundary_precision_check/close_zero_logged_visits_empty_set_boundary
    """
    base = setup_active_volunteer_assigned_case(api)
    api.close_case(base["case_id"], {"outcome": "APPEAL"}, base["supervisor_headers"])
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["status"] == "ASSIGNED", "a rejected close must leave the case in ASSIGNED"


# ------------------------------------- Corner: re-closing a CLOSED case
def test_close_already_closed_case_rejected(api):
    """PRD 3.8: "advancing the case to `CLOSED` from either `ASSIGNED` or
    `UNASSIGNED` (any other state is `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/close_already_closed_case_returns_invalid_state
    """
    base = setup_active_volunteer_assigned_case(api)
    log_visit(api, base, contact_start="2026-06-05T10:00:00Z", contact_end="2026-06-05T11:00:00Z")
    get_success_data(api.close_case(base["case_id"], {"outcome": "REUNIFICATION"}, base["supervisor_headers"]))
    resp = api.close_case(base["case_id"], {"outcome": "ADOPTION"}, base["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
