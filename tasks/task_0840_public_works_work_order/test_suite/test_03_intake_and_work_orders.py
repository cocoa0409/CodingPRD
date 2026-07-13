"""311 intake plus the work-order lifecycle: priority/SLA, triage, hold/resume,
cancellation cascade, and role/state guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_same_instant,
    set_clock, make_asset, make_crew, make_work_order,
    schedule_work_order, reserve_crew,
    supervisor_headers, dispatcher_headers, crewlead_headers, coordinator_headers,
)

CLOCK = "2026-06-01T00:00:00Z"
DISP = dispatcher_headers()
CREW = crewlead_headers()


# --- Corner: 311 intake -------------------------------------------------

def test_service_request_priority_and_sla_computed(api):
    """PRD §3.2: "The `priority` is assigned by category: a `SIGNAL_OUTAGE` is `EMERGENCY`, a `POTHOLE` is `HIGH`, and `SIGN_DAMAGE` is `MEDIUM`. From the resulting priority the system computes the service-level deadline `sla_due_at` as the request's `created_at` plus a fixed whole-hour offset: 4 hours for `EMERGENCY`, 48 hours (two days) for `HIGH`, 120 hours (five days) for `MEDIUM`, and 240 hours (ten days) for `LOW`."

    Design: Corner/entities/service_request_priority_and_sla_computed
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="SIGNAL", gis_segment_id="SEG-A3")
    payload = {
        "asset_id": asset["id"], "channel": "PHONE", "category": "SIGNAL_OUTAGE",
        "reported_by": "Jane", "location_desc": "Main & 1st",
    }
    sr = validate_success(api.create_service_request(payload, DISP), expected_status=201)
    assert sr["priority"] == "EMERGENCY", f"expected EMERGENCY, got {sr['priority']}"
    assert_same_instant(sr["sla_due_at"], "2026-06-01T04:00:00Z", "sla_due_at")


def test_triage_duplicate_of_self_rejected(api):
    """PRD §3.2: "The referenced `duplicate_of_id` must name an existing service request and must not be the request's own `id` — a self-reference is rejected with `ERR_DUPLICATE_SELF`."

    Design: Corner/state_machines/servicerequest_triage_duplicate_self_rejected
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-B1")
    sr = validate_success(api.create_service_request(
        {"asset_id": asset["id"], "channel": "WEB", "category": "POTHOLE",
         "reported_by": "Al", "location_desc": "x"}, DISP), expected_status=201)
    resp = api.triage_service_request(sr["id"], {"duplicate_of_id": sr["id"]}, DISP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SELF)


# --- Difficulty: hold/resume cycle --------------------------------------

def _in_progress_wo(api):
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="SIGNAL", gis_segment_id="SEG-5", replacement_value_cents=300000)
    crew = make_crew(api, name="Signals A", crew_type="SIGNALS", hourly_rate_cents=7000)
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    get_success_data(api.dispatch_work_order(wo["id"], DISP))
    get_success_data(api.start_work_order(wo["id"], CREW))
    return wo


def test_workorder_hold_transitions_to_on_hold(api):
    """PRD §3.8: "Work may be paused and resumed any number of times: a `CrewLead` puts an in-progress order on hold (`IN_PROGRESS → ON_HOLD`) and resumes it (`ON_HOLD → IN_PROGRESS`)."

    Design: Difficulty/non_linear_state_machine/workorder_hold_resume_cycle
    """
    wo = _in_progress_wo(api)
    held = validate_success(api.hold_work_order(wo["id"], CREW))
    assert held["status"] == "ON_HOLD", f"expected ON_HOLD, got {held['status']}"


def test_workorder_resume_returns_to_in_progress(api):
    """PRD §3.8: "Work may be paused and resumed any number of times: a `CrewLead` puts an in-progress order on hold (`IN_PROGRESS → ON_HOLD`) and resumes it (`ON_HOLD → IN_PROGRESS`)."

    Design: Difficulty/non_linear_state_machine/workorder_hold_resume_cycle
    """
    wo = _in_progress_wo(api)
    validate_success(api.hold_work_order(wo["id"], CREW))
    resumed = validate_success(api.resume_work_order(wo["id"], CREW))
    assert resumed["status"] == "IN_PROGRESS", f"expected IN_PROGRESS after resume, got {resumed['status']}"


# --- Difficulty: cancel a SCHEDULED WO releases dispatch and frees crew --

def _scheduled_wo_with_reserved_dispatch(api):
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-8")
    crew = make_crew(api, name="Paving D")
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    dispatch = reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    return wo, crew, dispatch


def test_cancel_scheduled_workorder_cancels_its_dispatch(api):
    """PRD §3.9: "Cancelling from any of `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` runs the release cascade: every `RESERVED` or `ACTIVE` dispatch for the work order is cancelled (`→ CANCELLED`), returning the crew's `committed_minutes`, flipping the crew back to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and bumping `Crew.version`"

    Design: Difficulty/transitive_cascade/workorder_cancel_releases_dispatch_then_frees_crew
    """
    wo, _crew, dispatch = _scheduled_wo_with_reserved_dispatch(api)
    validate_success(api.cancel_work_order(wo["id"], DISP))
    d = get_success_data(api.get_dispatch(dispatch["id"], DISP))
    assert d["status"] == "CANCELLED", f"expected dispatch CANCELLED, got {d['status']}"


def test_cancel_scheduled_workorder_frees_crew(api):
    """PRD §3.9: "every `RESERVED` or `ACTIVE` dispatch for the work order is cancelled (`→ CANCELLED`), returning the crew's `committed_minutes`, flipping the crew back to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and bumping `Crew.version`"

    Design: Difficulty/transitive_cascade/workorder_cancel_releases_dispatch_then_frees_crew
    """
    wo, crew, _dispatch = _scheduled_wo_with_reserved_dispatch(api)
    validate_success(api.cancel_work_order(wo["id"], DISP))
    c = get_success_data(api.get_crew(crew["id"], DISP))
    assert c["status"] == "AVAILABLE", f"expected crew AVAILABLE, got {c['status']}"
    assert c["committed_minutes"] == 0, f"expected committed_minutes 0, got {c['committed_minutes']}"


# --- Corner: state / terminal / RBAC guards -----------------------------

def test_start_from_draft_returns_invalid_state(api):
    """PRD §3.8: "Starting work advances the order `DISPATCHED → IN_PROGRESS`."
    PRD §2.6: "Legal state — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/workorder_start_from_draft_returns_invalid_state
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-A6")
    wo = make_work_order(api, asset["id"])
    resp = api.start_work_order(wo["id"], CREW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_twice_returns_already_terminal(api):
    """PRD §3.9: "A `Dispatcher` can cancel a work order from any non-terminal state — `DRAFT`, `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` — moving it to `CANCELLED` (a terminal state)."
    PRD §2.10: "attempting any action on a terminal resource returns `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/workorder_cancel_twice_returns_already_terminal
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-A8")
    wo = make_work_order(api, asset["id"])
    validate_success(api.cancel_work_order(wo["id"], DISP))
    resp = api.cancel_work_order(wo["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_crewlead_cannot_dispatch_workorder(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes `POST /work-orders/{id}/dispatch` for `Dispatcher` only.

    Design: Corner/rbac/crewlead_cannot_dispatch_workorder
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-C3")
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    resp = api.dispatch_work_order(wo["id"], CREW)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_coordinator_cannot_complete_workorder(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes `POST /work-orders/{id}/complete` for `CrewLead` only.

    Design: Corner/rbac/coordinator_cannot_complete_workorder
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-C4")
    wo = make_work_order(api, asset["id"])
    resp = api.complete_work_order(wo["id"], coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
