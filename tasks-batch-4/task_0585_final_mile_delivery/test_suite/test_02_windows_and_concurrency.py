"""Window reservation, confirmation, crew eligibility checks, temporal overlap,
and optimistic-concurrency control on the parent order."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    reserve_window_payload,
    make_customer, make_depot, make_team, make_order,
    setup_network, setup_scheduled_order, reserve_order_window,
    make_customer_headers,
    TEST_USERS,
)

PLANNER = TEST_USERS["dispatch_planner_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


# --- Crew eligibility on reserve (corner validations) ---

def test_reserve_window_region_mismatch_rejected(api):
    """PRD §3.3: "The crew's region_code must equal the customer's region_code,
    else ERR_REGION_MISMATCH."

    Design: Corner/validations/reserve_window_region_mismatch
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], region_code="NV")
    cust = make_customer(api, region_code="CA")
    order = make_order(api, cust["id"])
    resp = api.reserve_window(order["id"], reserve_window_payload(team["id"], order["version"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_REGION_MISMATCH.value)


def test_reserve_white_glove_on_uncertified_team_rejected(api):
    """PRD §3.3: "If the order's service_level is WHITE_GLOVE, the crew must be
    white_glove_certified; if the order's assembly_required is true, the crew
    must be assembly_certified; a failure of either certification check yields
    ERR_TEAM_NOT_CERTIFIED."

    Design: Corner/validations/reserve_white_glove_uncertified_team
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], white_glove_certified=False)
    cust = make_customer(api)
    order = make_order(api, cust["id"], service_level="WHITE_GLOVE")
    resp = api.reserve_window(order["id"], reserve_window_payload(team["id"], order["version"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_TEAM_NOT_CERTIFIED.value)


def test_reserve_window_unknown_team_returns_not_found(api):
    """PRD §2.8: "A body foreign key (depot_id, dock_id, team_id, customer_id,
    order_id, window_id, route_id, stop_id) is likewise checked for existence.
    Each missing identifier maps to its own not-found error: ... ERR_TEAM_NOT_FOUND ..."

    Design: Corner/validations/reserve_window_team_not_found
    """
    cust = make_customer(api)
    order = make_order(api, cust["id"])
    resp = api.reserve_window(order["id"], reserve_window_payload(UNKNOWN_UUID, order["version"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_TEAM_NOT_FOUND.value)


def test_reserve_window_end_before_start_rejected(api):
    """PRD §3.3: "the interval window_start_min and window_end_min (minutes from
    midnight, where the end must be strictly greater than the start — otherwise
    ERR_INVALID_WINDOW)."

    Design: Corner/validations/reserve_window_end_before_start_invalid_window
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"])
    cust = make_customer(api)
    order = make_order(api, cust["id"])
    resp = api.reserve_window(
        order["id"],
        reserve_window_payload(team["id"], order["version"], window_start_min=480, window_end_min=480),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# --- Window confirmation (corner state machine) ---

def test_owner_confirms_reserved_window(api):
    """PRD §3.3: "The Customer who owns the order confirms a reserved window,
    transitioning it RESERVED → CONFIRMED. Confirmation requires that the window
    be RESERVED and the owning order be SCHEDULED (otherwise ERR_INVALID_STATE),
    and that the acting Customer be the order's own customer (otherwise
    ERR_NOT_RESOURCE_OWNER)."

    Design: Corner/state_machines/confirm_reserved_window_success
    """
    ns = setup_scheduled_order(api)
    headers = make_customer_headers(ns["customer"]["id"])
    data = validate_success(api.confirm_window(ns["window"]["id"], headers), expected_status=200)
    assert data["status"] == "CONFIRMED"


def test_confirm_released_window_rejected(api):
    """PRD §3.3: "Confirmation requires that the window be RESERVED and the owning
    order be SCHEDULED (otherwise ERR_INVALID_STATE)."
    PRD §3.3: "On the superseding self-loop, the prior active window is first
    moved to RELEASED."

    Design: Corner/state_machines/confirm_released_window_terminal_lockdown
    """
    ns = setup_scheduled_order(api)
    order_id = ns["order"]["id"]
    w1_id = ns["window"]["id"]
    # Supersede window1 with a fresh reservation (window1 -> RELEASED).
    reserve_order_window(api, order_id, ns["team"]["id"], window_start_min=660, window_end_min=780)
    headers = make_customer_headers(ns["customer"]["id"])
    validate_error(api.confirm_window(w1_id, headers), ApiErrorId.ERR_INVALID_STATE.value)


# --- Optimistic concurrency (corner cross-cutting) ---

def test_window_reserve_increments_order_version(api):
    """PRD §3.3: "In all cases the order moves to (or remains) SCHEDULED, its
    version increments by one, and the crew's estimated_liability_points is
    recomputed."
    PRD §2.4: "version — an integer that begins at creation and increments by
    one on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/order_version_increments_on_window_reserve
    """
    net = setup_network(api)
    order = make_order(api, net["customer"]["id"])
    assert order["version"] == 1
    validate_success(
        api.reserve_window(order["id"], reserve_window_payload(net["team"]["id"], order["version"]), PLANNER),
        expected_status=201,
    )
    refreshed = validate_success(api.get_order(order["id"], PLANNER))
    assert refreshed["version"] == 2, f"expected version 2 after one reserve, got {refreshed['version']}"
    assert refreshed["status"] == "SCHEDULED"


def test_window_reserve_with_stale_version_rejected(api):
    """PRD §2.6: "The server compares expected_order_version against the order's
    current version; if they differ — because another writer has advanced the
    order since the client read it — the request is rejected with
    ERR_STALE_VERSION (HTTP 412) and no window is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_window_reserve
    """
    net = setup_network(api)
    order = make_order(api, net["customer"]["id"])
    stale_version = order["version"]  # 1
    # First reserve advances the order to version 2.
    validate_success(
        api.reserve_window(order["id"], reserve_window_payload(net["team"]["id"], stale_version), PLANNER),
        expected_status=201,
    )
    # Second reserve still carrying the pre-supersede version 1 is stale.
    resp = api.reserve_window(
        order["id"],
        reserve_window_payload(net["team"]["id"], stale_version, window_start_min=660, window_end_min=780),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --- Difficulty: half-open team-window overlap ---

def test_team_window_overlap_rejected(api):
    """PRD §3.3: "the new interval must not overlap any window already held by
    that same crew in RESERVED or CONFIRMED status on the same service_date; an
    overlap is rejected with ERR_TEAM_WINDOW_CONFLICT. Two intervals overlap
    when each starts before the other ends, treating each window as the half-open
    interval from its start minute up to (but not including) its end minute."

    Design: Difficulty/resource_temporal_overlap/team_window_overlap_halfopen
    """
    net = setup_network(api)
    order_a = make_order(api, net["customer"]["id"], item_description="A")
    reserve_order_window(api, order_a, net["team"]["id"], window_start_min=480, window_end_min=600)
    order_b = make_order(api, net["customer"]["id"], item_description="B")
    resp = api.reserve_window(
        order_b["id"],
        reserve_window_payload(net["team"]["id"], order_b["version"], window_start_min=540, window_end_min=600),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_TEAM_WINDOW_CONFLICT.value)


def test_team_window_adjacent_boundary_allowed(api):
    """PRD §3.3: "Two intervals overlap when each starts before the other ends,
    treating each window as the half-open interval from its start minute up to
    (but not including) its end minute."

    Design: Difficulty/resource_temporal_overlap/team_window_overlap_halfopen
    """
    net = setup_network(api)
    order_a = make_order(api, net["customer"]["id"], item_description="A")
    reserve_order_window(api, order_a, net["team"]["id"], window_start_min=480, window_end_min=600)
    order_b = make_order(api, net["customer"]["id"], item_description="B")
    # 600-720 abuts 480-600 at the shared boundary 600; half-open intervals do not overlap.
    data = validate_success(
        api.reserve_window(
            order_b["id"],
            reserve_window_payload(net["team"]["id"], order_b["version"], window_start_min=600, window_end_min=720),
            PLANNER,
        ),
        expected_status=201,
    )
    assert data["status"] == "RESERVED"


# --- Difficulty: window reservation depends on crew status ---

def test_reserve_on_out_of_service_team_rejected(api):
    """PRD §3.3: "The referenced crew must exist and its status must be ACTIVE,
    else ERR_TEAM_OUT_OF_SERVICE."

    Design: Difficulty/cross_entity_state_dependency/window_requires_active_team
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], status="OUT_OF_SERVICE")
    cust = make_customer(api)
    order = make_order(api, cust["id"])
    resp = api.reserve_window(order["id"], reserve_window_payload(team["id"], order["version"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_TEAM_OUT_OF_SERVICE.value)


def test_reserve_on_active_team_succeeds(api):
    """PRD §3.3: "A successful reservation creates a DeliveryWindow in RESERVED
    status, records the order's order_id and the reserved team_id, and sets the
    order's active_window_id to the new window."

    Design: Difficulty/cross_entity_state_dependency/window_requires_active_team
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], status="ACTIVE")
    cust = make_customer(api)
    order = make_order(api, cust["id"])
    data = validate_success(
        api.reserve_window(order["id"], reserve_window_payload(team["id"], order["version"]), PLANNER),
        expected_status=201,
    )
    assert data["status"] == "RESERVED"
    refreshed = validate_success(api.get_order(order["id"], PLANNER))
    assert refreshed["status"] == "SCHEDULED"
