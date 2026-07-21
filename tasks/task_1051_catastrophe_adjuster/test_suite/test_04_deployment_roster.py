"""Cat-event roster: window overlap, capacity, activation window, seat conservation."""
from test_helpers import (
    validate_error, validate_success, get_success_data,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["licensing_admin_headers"]


# --------------------------------------------------------------------------
# Corner: cat-event close / deployment activation
# --------------------------------------------------------------------------
def test_close_cat_event_with_confirmed_deployment(api):
    """PRD 3.2: "An event is closed by the admin, moving it OPEN -> CLOSED, but only
    when it is OPEN ... and its roster is empty — no deployment for the event remains
    CONFIRMED or ACTIVE (otherwise ERR_ROSTER_NOT_EMPTY)."

    Design: Corner/state_machines/close_cat_event_with_confirmed_deployment
    """
    ctx = fx.setup_confirmed_deployment(api, roster_capacity=3, peril_type="WILDFIRE",
                                        start_at="2026-07-20T09:00:00Z", end_at="2026-07-20T17:00:00Z")
    resp = api.close_cat_event(ctx["ce_id"], ADMIN)
    validate_error(resp, "ERR_ROSTER_NOT_EMPTY")


def test_activate_deployment_before_window_open(api):
    """PRD 3.2: "activation moves it CONFIRMED -> ACTIVE and requires that the
    deployment be CONFIRMED (otherwise ERR_DEPLOYMENT_NOT_CONFIRMED) and that the
    clock satisfy start_at at-or-before now and now strictly before end_at (otherwise
    ERR_DEPLOYMENT_WINDOW_NOT_OPEN)."

    Design: Corner/state_machines/activate_deployment_before_window_open
    """
    # Clock is at the default 2026-07-01; window starts 2026-07-20.
    ctx = fx.setup_confirmed_deployment(api, roster_capacity=3, peril_type="HURRICANE",
                                        start_at="2026-07-20T09:00:00Z", end_at="2026-07-20T17:00:00Z")
    resp = api.activate_deployment(ctx["dep_id"], ADMIN)
    validate_error(resp, "ERR_DEPLOYMENT_WINDOW_NOT_OPEN")


# --------------------------------------------------------------------------
# Difficulty: half-open window overlap on the same adjuster
# --------------------------------------------------------------------------
def _adjuster_event_with_confirmed_d1(api, capacity):
    adj = fx.create_adjuster(api, adjuster_type="CAT")
    ce = fx.create_cat_event(api, peril_type="HURRICANE", roster_capacity=capacity)
    d1 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-11T09:00:00Z", end_at="2026-07-11T17:00:00Z")
    get_success_data(api.confirm_deployment(d1["id"], ADMIN))
    return adj, ce, d1


def test_confirm_overlapping_window_rejected(api):
    """PRD 3.2: "the requested window must not overlap any other CONFIRMED-or-ACTIVE
    deployment for the same adjuster; because windows are half-open, two windows
    conflict only if they share an interior instant, and windows that merely touch
    end-to-start are allowed — an overlap is rejected with ERR_DEPLOYMENT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/deployment_window_overlap_on_adjuster
    """
    adj, ce, _ = _adjuster_event_with_confirmed_d1(api, capacity=5)
    d2 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-11T12:00:00Z", end_at="2026-07-11T14:00:00Z")
    resp = api.confirm_deployment(d2["id"], ADMIN)
    validate_error(resp, "ERR_DEPLOYMENT_WINDOW_OVERLAP")


def test_confirm_overlapping_window_leaves_second_requested(api):
    """PRD 3.2: "the requested window must not overlap any other CONFIRMED-or-ACTIVE
    deployment for the same adjuster ... an overlap is rejected with
    ERR_DEPLOYMENT_WINDOW_OVERLAP." The rejected confirm leaves the deployment REQUESTED.

    Design: Difficulty/resource_temporal_overlap/deployment_window_overlap_on_adjuster
    """
    adj, ce, _ = _adjuster_event_with_confirmed_d1(api, capacity=5)
    d2 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-11T12:00:00Z", end_at="2026-07-11T14:00:00Z")
    api.confirm_deployment(d2["id"], ADMIN)
    data = validate_success(api.get_deployment(d2["id"], ADMIN))
    assert data["status"] == "REQUESTED", "an overlapping confirm must not fill a seat"


def test_confirm_touching_window_allowed(api):
    """PRD 2.4: "deployment and inspection windows are treated as half-open intervals
    [start, end) ... which is why two windows that merely touch (one ending exactly
    when the next begins) do not conflict."

    Design: Difficulty/resource_temporal_overlap/deployment_window_overlap_on_adjuster
    """
    adj, ce, _ = _adjuster_event_with_confirmed_d1(api, capacity=5)
    # D1 ends at 17:00; a window starting exactly at 17:00 touches but does not overlap.
    d2 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-11T17:00:00Z", end_at="2026-07-11T19:00:00Z")
    data = validate_success(api.confirm_deployment(d2["id"], ADMIN))
    assert data["status"] == "CONFIRMED"


# --------------------------------------------------------------------------
# Difficulty: priority — temporal (overlap) beats fiscal (capacity)
# --------------------------------------------------------------------------
def test_confirm_overlap_beats_capacity_error(api):
    """PRD 2.10: "On deployment confirm, the window-overlap check precedes the
    roster-capacity check, so an overlapping window surfaces as
    ERR_DEPLOYMENT_WINDOW_OVERLAP even when the roster is also full."

    Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_beats_fiscal
    """
    # Capacity 1: D1 confirmed fills the roster; D2 both overlaps and would exceed capacity.
    adj, ce, _ = _adjuster_event_with_confirmed_d1(api, capacity=1)
    d2 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-11T12:00:00Z", end_at="2026-07-11T14:00:00Z")
    resp = api.confirm_deployment(d2["id"], ADMIN)
    validate_error(resp, "ERR_DEPLOYMENT_WINDOW_OVERLAP")


def test_confirm_overlap_beats_capacity_roster_unchanged(api):
    """PRD 2.10: "On deployment confirm, the window-overlap check precedes the
    roster-capacity check ..." and PRD 2.8: "roster_filled_count always equals the
    count of CONFIRMED-or-ACTIVE deployments on the event." The rejected D2 fills no seat.

    Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_beats_fiscal
    """
    adj, ce, _ = _adjuster_event_with_confirmed_d1(api, capacity=1)
    d2 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-11T12:00:00Z", end_at="2026-07-11T14:00:00Z")
    api.confirm_deployment(d2["id"], ADMIN)
    data = validate_success(api.get_cat_event(ce["id"], ADMIN))
    assert data["roster_filled_count"] == 1, "only D1 holds a seat"


# --------------------------------------------------------------------------
# Difficulty: seat conservation (confirm +1 then withdraw -1 -> 0)
# --------------------------------------------------------------------------
def test_roster_seat_conservation_count_returns_to_zero(api):
    """PRD 2.8: "Confirming a deployment increments it by 1; ... withdrawing a
    deployment that currently holds a seat (one that was CONFIRMED or ACTIVE)
    decrements it by 1 as a compensating adjustment. The invariant is that
    roster_filled_count always equals the count of CONFIRMED-or-ACTIVE deployments
    on the event."

    Design: Difficulty/compensating_invariant/roster_seat_conservation
    """
    adj = fx.create_adjuster(api, adjuster_type="CAT")
    ce = fx.create_cat_event(api, peril_type="FLOOD", roster_capacity=2)
    d1 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T17:00:00Z")
    get_success_data(api.confirm_deployment(d1["id"], ADMIN))
    get_success_data(api.withdraw_deployment(d1["id"], ADMIN))
    data = validate_success(api.get_cat_event(ce["id"], ADMIN))
    assert data["roster_filled_count"] == 0


def test_roster_seat_conservation_deployment_withdrawn(api):
    """PRD 3.2: "At any point while a deployment is REQUESTED, CONFIRMED, or ACTIVE it
    may be withdrawn to WITHDRAWN ... if the withdrawn deployment had been holding a
    seat — that is, its prior status was CONFIRMED or ACTIVE — the withdrawal applies
    the compensating decrement of roster_filled_count by 1."

    Design: Difficulty/compensating_invariant/roster_seat_conservation
    """
    adj = fx.create_adjuster(api, adjuster_type="CAT")
    ce = fx.create_cat_event(api, peril_type="FLOOD", roster_capacity=2)
    d1 = fx.create_deployment(api, adj["id"], ce["id"],
                              start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T17:00:00Z")
    get_success_data(api.confirm_deployment(d1["id"], ADMIN))
    get_success_data(api.withdraw_deployment(d1["id"], ADMIN))
    data = validate_success(api.get_deployment(d1["id"], ADMIN))
    assert data["status"] == "WITHDRAWN"
