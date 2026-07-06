"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints
(the server database is empty at the start of every test). Helpers use
get_success_data() internally so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Role choice: most case/hold/impound/citation/rabies operations are shared
between FieldOfficer and Supervisor, and a Supervisor is exempt from the
officer-ownership comparison (PRD 2.1), so these helpers act as Supervisor for
brevity. The two dispatch actions that are FieldOfficer-exclusive
(accept / clear) MUST be driven with make_field_officer_headers(officer_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_field_officer_headers
from . import factories as F

_DISPATCHER = TEST_USERS["dispatcher_headers"]
_SUPERVISOR = TEST_USERS["supervisor_headers"]
_LIAISON = TEST_USERS["health_dept_liaison_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Set the server logical clock (Supervisor-only)."""
    return get_success_data(api.set_clock(iso, _SUPERVISOR))


# --------------------------------------------------------------------------
# Single-entity creators
# --------------------------------------------------------------------------
def make_complaint(api, **overrides):
    """Intake a complaint as a Dispatcher. Returns the created Complaint."""
    return get_success_data(api.create_complaint(F.create_complaint_payload(**overrides), _DISPATCHER))


def make_officer(api, **overrides):
    """Register an officer as a Supervisor. Returns the created Officer."""
    return get_success_data(api.create_officer(F.create_officer_payload(**overrides), _SUPERVISOR))


def make_kennel(api, **overrides):
    """Create a kennel as a Supervisor. Returns the created Kennel."""
    return get_success_data(api.create_kennel(F.create_kennel_payload(**overrides), _SUPERVISOR))


# --------------------------------------------------------------------------
# Case state-progression helpers
# --------------------------------------------------------------------------
def open_case(api, case_type="BITE", complaint_overrides=None, officer_overrides=None, **case_overrides):
    """Create complaint + officer + a case in OPEN state.

    Returns dict: {complaint, officer, case}.
    """
    complaint = make_complaint(api, **(complaint_overrides or {}))
    officer = make_officer(api, **(officer_overrides or {}))
    case = get_success_data(api.create_case(
        F.create_case_payload(complaint["id"], officer["id"], case_type, **case_overrides),
        _SUPERVISOR,
    ))
    return {"complaint": complaint, "officer": officer, "case": case}


def investigating_case(api, case_type="BITE", complaint_overrides=None, officer_overrides=None, **case_overrides):
    """Create complaint + officer + case, then move the case to
    UNDER_INVESTIGATION (provisional risk set).

    Returns dict: {complaint, officer, case, case_version}, where case is the
    investigated Case and case_version is its version at that point (used for
    the impound OCC field).
    """
    ctx = open_case(api, case_type, complaint_overrides, officer_overrides, **case_overrides)
    case = get_success_data(api.investigate_case(ctx["case"]["id"], _SUPERVISOR))
    ctx["case"] = case
    ctx["case_version"] = case["version"]
    return ctx


def substantiated_case(api, case_type="BITE", complaint_overrides=None, officer_overrides=None, **case_overrides):
    """Create complaint + officer + case, investigate, then resolve
    SUBSTANTIATED (final risk set, substantiated_at stamped).

    Returns dict: {complaint, officer, case, case_version}.
    """
    ctx = investigating_case(api, case_type, complaint_overrides, officer_overrides, **case_overrides)
    case = get_success_data(api.resolve_case(ctx["case"]["id"], {"resolution": "SUBSTANTIATED"}, _SUPERVISOR))
    ctx["case"] = case
    ctx["case_version"] = case["version"]
    return ctx


# --------------------------------------------------------------------------
# Child-entity creators (case must already be actionable)
# --------------------------------------------------------------------------
def issue_citation(api, case_id, **overrides):
    """Issue a citation against an actionable case (Supervisor). Returns Citation."""
    return get_success_data(api.create_citation(F.create_citation_payload(case_id, **overrides), _SUPERVISOR))


def pay_citation(api, citation_id):
    """Record payment of a citation (Dispatcher). Returns Citation."""
    return get_success_data(api.pay_citation(citation_id, _DISPATCHER))


def make_impound(api, case_id, kennel_id, expected_case_version, **overrides):
    """Impound an animal into a kennel (Supervisor). Returns Impound."""
    return get_success_data(api.create_impound(
        F.create_impound_payload(case_id, kennel_id, expected_case_version, **overrides), _SUPERVISOR))


def make_quarantine_hold(api, case_id, **overrides):
    """Place a quarantine hold on an eligible case (Supervisor). Returns QuarantineHold."""
    return get_success_data(api.create_quarantine_hold(
        F.create_quarantine_hold_payload(case_id, **overrides), _SUPERVISOR))


def make_rabies_report(api, case_id, quarantine_hold_id, **overrides):
    """Submit a rabies report (Supervisor). Returns RabiesReport."""
    return get_success_data(api.create_rabies_report(
        F.create_rabies_report_payload(case_id, quarantine_hold_id, **overrides), _SUPERVISOR))


# --------------------------------------------------------------------------
# Dispatch lifecycle helpers
# --------------------------------------------------------------------------
def make_pending_dispatch(api, complaint_id, officer_id, **overrides):
    """Assign an officer to a complaint (Dispatcher). Returns the PENDING Dispatch."""
    return get_success_data(api.create_dispatch(
        F.create_dispatch_payload(complaint_id, officer_id, **overrides), _DISPATCHER))


def accept_dispatch(api, dispatch_id, officer_id):
    """Accept a dispatch as its assigned FieldOfficer (ownership threaded)."""
    return get_success_data(api.accept_dispatch(dispatch_id, make_field_officer_headers(officer_id)))


def clear_dispatch(api, dispatch_id, officer_id, field_outcome="RESOLVED_ON_SCENE"):
    """Clear an EN_ROUTE dispatch as its assigned FieldOfficer (ownership threaded)."""
    return get_success_data(api.clear_dispatch(
        dispatch_id, {"field_outcome": field_outcome}, make_field_officer_headers(officer_id)))


def setup_en_route_dispatch(api, clock="2026-03-01T00:00:00Z", complaint_overrides=None,
                            officer_overrides=None, **dispatch_overrides):
    """Clock set, complaint intaken, officer registered, dispatch created and
    accepted (dispatch EN_ROUTE, complaint DISPATCHED).

    Returns dict: {complaint, officer, dispatch}.
    """
    if clock is not None:
        set_clock(api, clock)
    complaint = make_complaint(api, **(complaint_overrides or {}))
    officer = make_officer(api, **(officer_overrides or {}))
    dispatch = make_pending_dispatch(api, complaint["id"], officer["id"], **dispatch_overrides)
    accept_dispatch(api, dispatch["id"], officer["id"])
    return {"complaint": complaint, "officer": officer, "dispatch": dispatch}
