"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so every test
starts against an empty database). Internally these helpers use the lenient
get_success_data() validator so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_account_payload,
    create_asset_payload,
    create_blowdown_event_payload,
    create_coupon_payload,
    create_delivery_order_payload,
    create_feed_station_payload,
    create_invoice_payload,
    create_legionella_plan_payload,
    create_program_design_payload,
    create_rack_payload,
    create_route_stop_payload,
    create_test_route_payload,
    create_product_payload,
    design_draft_payload,
    out_of_range_result_payload,
    telemetry_payload,
    water_test_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_contact_headers,
    make_chemist_headers,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]


def _expect(resp, what: str):
    if resp.status_code >= 400:
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return get_success_data(resp)


# --- Tier 0: clock ------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    return _expect(api_client.set_clock(to_iso8601, ADMIN), "set clock")


# --- Tier 1: leaf creators ------------------------------------------------------

def create_account(**overrides):
    resp = api_client.create_account(create_account_payload(**overrides), MANAGER)
    return _expect(resp, "create account")


def create_asset(account_id, **overrides):
    resp = api_client.create_asset(create_asset_payload(account_id, **overrides), CHEMIST)
    return _expect(resp, "create asset")


def create_product(**overrides):
    resp = api_client.create_product(create_product_payload(**overrides), ADMIN)
    return _expect(resp, "create product")


def create_station(asset_id, product_id, **overrides):
    resp = api_client.create_feed_station(
        create_feed_station_payload(asset_id, product_id, **overrides), CHEMIST
    )
    return _expect(resp, "create feed station")


def bring_station_online(station_id):
    return _expect(api_client.bring_station_online(station_id, CHEMIST), "bring station online")


def create_rack(asset_id, **overrides):
    resp = api_client.create_rack(create_rack_payload(asset_id, **overrides), CHEMIST)
    return _expect(resp, "create rack")


def install_coupon(rack_id, position_index, installed_at, **overrides):
    resp = api_client.install_coupon(
        rack_id, create_coupon_payload(position_index, installed_at, **overrides), CHEMIST
    )
    return _expect(resp, "install coupon")


def remove_coupon(coupon_id, post_weight_g):
    return _expect(
        api_client.remove_coupon(coupon_id, {"post_weight_g": post_weight_g}, CHEMIST),
        "remove coupon",
    )


def create_legionella_plan(asset_id, **overrides):
    resp = api_client.create_legionella_plan(
        create_legionella_plan_payload(asset_id, **overrides), CHEMIST
    )
    return _expect(resp, "create legionella plan")


def activate_legionella_plan(plan_id):
    return _expect(api_client.activate_legionella_plan(plan_id, CHEMIST), "activate plan")


def log_blowdown(asset_id, occurred_at, blowdown_gal, makeup_gal):
    resp = api_client.log_blowdown_event(
        asset_id, create_blowdown_event_payload(occurred_at, blowdown_gal, makeup_gal), CHEMIST
    )
    return _expect(resp, "log blowdown event")


# --- Tier 2: program design lifecycle ------------------------------------------

def create_proposed_design(asset_id, **draft_overrides):
    """Create a design and walk it SURVEY_SCHEDULED -> SURVEYED -> DRAFTED -> PROPOSED.

    Returns the PROPOSED design dict (carrying its current version)."""
    design = _expect(
        api_client.create_program_design(create_program_design_payload(asset_id), CHEMIST),
        "create program design",
    )
    _expect(
        api_client.record_survey(design["id"], {"survey_notes": "surveyed"}, CHEMIST),
        "record survey",
    )
    _expect(
        api_client.draft_design(design["id"], design_draft_payload(**draft_overrides), CHEMIST),
        "draft design",
    )
    proposed = _expect(api_client.propose_design(design["id"], CHEMIST), "propose design")
    return proposed


def accept_design(design_id, account_id, expected_version):
    """CustomerContact accept (OCC-guarded). Returns the ACCEPTED design."""
    resp = api_client.accept_design(
        design_id,
        {"expected_program_design_version": expected_version},
        make_customer_contact_headers(account_id),
    )
    return _expect(resp, "accept design")


def create_accepted_design(asset_id, account_id, **draft_overrides):
    proposed = create_proposed_design(asset_id, **draft_overrides)
    return accept_design(proposed["id"], account_id, proposed["version"])


# --- Tier 3: commissioned asset subtree ----------------------------------------

def setup_commissioned_asset(
    account_name=None,
    account_overrides=None,
    asset_overrides=None,
    product_overrides=None,
    station_overrides=None,
    design_overrides=None,
    set_initial_clock=True,
):
    """Account + asset + product + ONLINE station + ACCEPTED design + commissioned asset.

    Returns dict(account, asset, product, station, design)."""
    if set_initial_clock:
        set_clock(DEFAULT_CLOCK_ISO)
    account = create_account(**({"account_name": account_name} if account_name else {}),
                               **(account_overrides or {}))
    asset = create_asset(account["id"], **(asset_overrides or {}))
    product = create_product(**(product_overrides or {}))
    station = create_station(asset["id"], product["id"], **(station_overrides or {}))
    design = create_accepted_design(asset["id"], account["id"], **(design_overrides or {}))
    station = bring_station_online(station["id"])
    asset = _expect(api_client.commission_asset(asset["id"], CHEMIST), "commission asset")
    return {
        "account": account,
        "asset": asset,
        "product": product,
        "station": station,
        "design": design,
    }


# --- Tier 3: routes and field results ------------------------------------------

def create_published_route(account_id, asset_id, windows):
    """Create a route with one stop per (window_start, window_end) pair and publish it.

    Returns (route, stops) with stops in sequence order."""
    route = _expect(
        api_client.create_test_route(create_test_route_payload(account_id), CHEMIST),
        "create test route",
    )
    stops = []
    for i, (start, end) in enumerate(windows, start=1):
        stop = _expect(
            api_client.add_route_stop(
                route["id"], create_route_stop_payload(asset_id, start, end, i), CHEMIST
            ),
            f"add stop {i}",
        )
        stops.append(stop)
    route = _expect(api_client.publish_route(route["id"], CHEMIST), "publish route")
    return route, stops


def arrive_at_stop(stop_id):
    return _expect(api_client.arrive_stop(stop_id, CHEMIST), "arrive at stop")


def record_result(stop_id, asset_id, out_of_range=False, user_id=None, **overrides):
    """Record a water test result at an ARRIVED stop. Returns the result."""
    payload = (
        out_of_range_result_payload(asset_id, **overrides)
        if out_of_range
        else water_test_result_payload(asset_id, **overrides)
    )
    headers = make_chemist_headers(user_id) if user_id else CHEMIST
    resp = api_client.record_water_test_result(stop_id, payload, headers)
    return _expect(resp, "record water test result")


def arrive_and_record(stop_id, asset_id, out_of_range=False, user_id=None, **overrides):
    arrive_at_stop(stop_id)
    return record_result(stop_id, asset_id, out_of_range=out_of_range, user_id=user_id, **overrides)


# --- Tier 4: escalation / corrective actions -----------------------------------

DEFAULT_ESCALATION_WINDOWS = [
    ("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
    ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z"),
    ("2026-08-02T12:00:00Z", "2026-08-02T18:00:00Z"),
]
DEFAULT_ESCALATION_CLOCKS = [
    "2026-08-02T01:00:00Z",
    "2026-08-02T07:00:00Z",
    "2026-08-02T13:00:00Z",
]


def record_out_of_range_sequence(subtree, count=3, recorder_id=None,
                                 windows=None, clocks=None):
    """Record `count` consecutive OUT_OF_RANGE results on the subtree's asset.

    Builds a published route with one stop per window and records one
    OUT_OF_RANGE result per stop, advancing the logical clock between stops.
    Returns (route, stops, results)."""
    windows = windows or DEFAULT_ESCALATION_WINDOWS[:count]
    clocks = clocks or DEFAULT_ESCALATION_CLOCKS[:count]
    route, stops = create_published_route(
        subtree["account"]["id"], subtree["asset"]["id"], windows
    )
    results = []
    for stop, clock in zip(stops, clocks):
        set_clock(clock)
        results.append(
            arrive_and_record(
                stop["id"], subtree["asset"]["id"], out_of_range=True, user_id=recorder_id
            )
        )
    return route, stops, results


def find_pending_action(asset_id):
    data = _expect(
        api_client.list_corrective_actions(
            CHEMIST, params={"asset_id": asset_id, "status": "PENDING"}
        ),
        "list pending corrective actions",
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one PENDING corrective action, got {data}"
    )
    return data[0]


def setup_pending_corrective_action(recorder_id="chemist-recorder-1", **subtree_kwargs):
    """Commissioned asset with 3 consecutive OUT_OF_RANGE results and the
    auto-created PENDING corrective action. Returns dict with the subtree plus
    action, results, and a fresh station version for the OCC-guarded approve."""
    subtree = setup_commissioned_asset(**subtree_kwargs)
    _, _, results = record_out_of_range_sequence(subtree, count=3, recorder_id=recorder_id)
    action = find_pending_action(subtree["asset"]["id"])
    station = _expect(
        api_client.get_feed_station(subtree["station"]["id"], CHEMIST), "get station"
    )
    subtree.update({"results": results, "action": action, "station": station})
    return subtree


# --- Tier 5: delivery orders and invoices --------------------------------------

def setup_delivery_ready(account_name=None, account_overrides=None, **subtree_kwargs):
    """Account + asset + product + ONLINE station + ACCEPTED design (asset NOT
    commissioned — delivery scheduling does not require IN_SERVICE)."""
    set_clock(DEFAULT_CLOCK_ISO)
    account = create_account(**({"account_name": account_name} if account_name else {}),
                               **(account_overrides or {}))
    asset = create_asset(account["id"])
    product = create_product()
    station = create_station(asset["id"], product["id"], **(subtree_kwargs.pop("station_overrides", {}) or {}))
    design = create_accepted_design(asset["id"], account["id"],
                                    **(subtree_kwargs.pop("design_overrides", {}) or {}))
    station = bring_station_online(station["id"])
    return {"account": account, "asset": asset, "product": product,
            "station": station, "design": design}


def create_pending_order(account_id, station_id, quantity_gal):
    """Create + submit a delivery order. Returns the PENDING order."""
    order = _expect(
        api_client.create_delivery_order(
            create_delivery_order_payload(account_id, station_id, quantity_gal), MANAGER
        ),
        "create delivery order",
    )
    return _expect(api_client.submit_delivery_order(order["id"], MANAGER), "submit order")


def schedule_order(order_id, scheduled_for, expected_version):
    return _expect(
        api_client.schedule_delivery_order(
            order_id,
            {"scheduled_for": scheduled_for, "expected_delivery_order_version": expected_version},
            MANAGER,
        ),
        "schedule order",
    )


def deliver_and_close_order(account_id, station_id, quantity_gal, scheduled_for,
                            delivered_gal=None, returned_residual_gal=0):
    """Full order lifecycle through CLOSED at the given scheduled instant.

    create -> submit -> schedule -> (clock := scheduled_for) -> dispatch ->
    confirm-delivery -> close. Returns the CLOSED order."""
    order = create_pending_order(account_id, station_id, quantity_gal)
    order = schedule_order(order["id"], scheduled_for, order["version"])
    set_clock(scheduled_for)
    _expect(api_client.dispatch_delivery_order(order["id"], MANAGER), "dispatch order")
    order = _expect(
        api_client.confirm_delivery(
            order["id"],
            {"delivered_gal": delivered_gal if delivered_gal is not None else quantity_gal},
            CHEMIST,
        ),
        "confirm delivery",
    )
    return _expect(
        api_client.close_delivery_order(
            order["id"], {"returned_residual_gal": returned_residual_gal}, CHEMIST
        ),
        "close order",
    )


def post_telemetry(station_id, **overrides):
    return _expect(
        api_client.post_telemetry(station_id, telemetry_payload(**overrides), CHEMIST),
        "post telemetry",
    )


def create_and_issue_invoice(account_id, period_start, period_end):
    invoice = _expect(
        api_client.create_invoice(
            create_invoice_payload(account_id, period_start, period_end), MANAGER
        ),
        "create invoice",
    )
    return _expect(api_client.issue_invoice(invoice["id"], MANAGER), "issue invoice")
