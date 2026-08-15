"""State machine corner coverage: terminal lockdown, invalid transitions,
initial states, idempotency, automatic and cascading transitions, and
compensating void."""
from test_helpers import (
    ApiErrorId,
    api_client,
    arrive_at_stop,
    bring_station_online,
    create_account,
    create_asset,
    create_pending_order,
    create_product,
    create_published_route,
    create_station,
    deliver_and_close_order,
    find_pending_action,
    record_out_of_range_sequence,
    record_result,
    schedule_order,
    set_clock,
    setup_commissioned_asset,
    setup_delivery_ready,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]


def test_terminal_state_lockdown_cancelled_delivery_rejects_actions(api):
    """PRD §3.9: "Cancellation is available from `DRAFT`, `PENDING`, or
    `SCHEDULED` (any other state is `ERR_INVALID_STATE`)". PRD §2.6 tier 6:
    "The target resource must be in a state from which the requested
    transition is declared; failure is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_state_lockdown_cancelled_delivery_rejects_all_actions
    """
    subtree = setup_delivery_ready(account_name="Term Co")
    account, station = subtree["account"], subtree["station"]

    order = validate_success(
        api_client.create_delivery_order(
            {"account_id": account["id"], "station_id": station["id"], "quantity_gal": 55},
            MANAGER,
        ),
        expected_status=201,
    )
    validate_success(api_client.cancel_delivery_order(order["id"], MANAGER))

    # From CANCELLED no declared transition exists; every action is rejected.
    resp_submit = api_client.submit_delivery_order(order["id"], MANAGER)
    validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE)

    resp_schedule = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z", "expected_delivery_order_version": 1},
        MANAGER,
    )
    validate_error(resp_schedule, ApiErrorId.ERR_INVALID_STATE)

    resp_dispatch = api_client.dispatch_delivery_order(order["id"], MANAGER)
    validate_error(resp_dispatch, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    assert after["status"] == "CANCELLED"


def test_invalid_transition_record_result_on_scheduled_stop(api):
    """PRD §3.4: "The stop must be `ARRIVED` (`ERR_INVALID_STATE` on any other
    state)". A SCHEDULED stop has no direct path to SAMPLED.

    Design: Corner/state_machines/invalid_transition_skip_arrive_to_sampled_impossible
    """
    subtree = setup_commissioned_asset(account_name="Skip Co")
    route, stops = create_published_route(
        subtree["account"]["id"],
        subtree["asset"]["id"],
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z")],
    )
    set_clock("2026-08-02T01:00:00Z")

    resp = api_client.record_water_test_result(
        stops[0]["id"],
        {
            "asset_id": subtree["asset"]["id"],
            "ph": 8.0,
            "conductivity_umhos": 2000,
            "calcium_ppm": 300,
            "alkalinity_ppm": 150,
            "temperature_f": 90,
            "inhibitor_residual_ppm": 4,
        },
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_stop(stops[0]["id"], CHEMIST))
    assert after["status"] == "SCHEDULED"


def test_initial_state_new_entities(api):
    """PRD §3.2: "The design's lifecycle is a cycle, not a line:
    `SURVEY_SCHEDULED` → `SURVEYED` → `DRAFTED` → `PROPOSED`".
    PRD §3.7: "A new plan is a `DRAFT`, its `last_validated_at` null."
    PRD §3.9: "An `AccountManager` creates an invoice in `DRAFT` for an
    `account_id` and a half-open billing window".
    PRD §3.3: "A new station is `OFFLINE`".

    Design: Corner/state_machines/initial_state_new_entities
    """
    account = create_account(account_name="Init Co")
    asset = create_asset(account["id"], asset_tag="CT-I3", asset_type="BOILER",
                         recirculation_rate_gpm=100, system_volume_gal=500)

    design = validate_success(
        api_client.create_program_design({"asset_id": asset["id"]}, CHEMIST),
        expected_status=201,
    )
    assert design["status"] == "SURVEY_SCHEDULED"

    plan = validate_success(
        api_client.create_legionella_plan(
            {"asset_id": asset["id"], "plan_text": "p", "validation_interval_days": 30},
            CHEMIST,
        ),
        expected_status=201,
    )
    assert plan["status"] == "DRAFT"

    invoice = validate_success(
        api_client.create_invoice(
            {
                "account_id": account["id"],
                "period_start": "2026-08-01T00:00:00Z",
                "period_end": "2026-09-01T00:00:00Z",
            },
            MANAGER,
        ),
        expected_status=201,
    )
    assert invoice["status"] == "DRAFT"

    product = create_product()
    station = create_station(asset["id"], product["id"])
    assert station["status"] == "OFFLINE"


def test_idempotent_second_bring_online_rejected(api):
    """PRD §3.3: "Bringing a station online moves it from `OFFLINE` to
    `ONLINE`, or from `LOCKED_OUT` back to `ONLINE`; both are refused with
    `ERR_ASSET_DECOMMISSIONED` when the station's asset is `DECOMMISSIONED`,
    and from any other state with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/idempotent_second_transition_rejected
    """
    account = create_account(account_name="Idem Co")
    asset = create_asset(account["id"], asset_type="BOILER", recirculation_rate_gpm=100,
                         system_volume_gal=500)
    product = create_product()
    station = create_station(asset["id"], product["id"])
    bring_station_online(station["id"])

    resp = api_client.bring_station_online(station["id"], CHEMIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_feed_station(station["id"], CHEMIST))
    assert after["status"] == "ONLINE"


def test_route_completed_auto_when_all_stops_terminal(api):
    """PRD §3.4: "From there the route runs itself: when every stop of a
    `PUBLISHED` route has reached `SAMPLED`, `SKIPPED`, or `MISSED`, the route
    transitions automatically to `COMPLETED`."

    Design: Corner/state_machines/route_completed_auto_when_all_stops_terminal
    """
    subtree = setup_commissioned_asset(account_name="Bubble Co")
    account_id, asset_id = subtree["account"]["id"], subtree["asset"]["id"]
    route, stops = create_published_route(
        account_id,
        asset_id,
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
         ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z")],
    )
    set_clock("2026-08-02T01:00:00Z")
    arrive_at_stop(stops[0]["id"])
    record_result(stops[0]["id"], asset_id)  # stop1 -> SAMPLED

    set_clock("2026-08-02T13:00:00Z")  # stop2's window has elapsed
    missed = validate_success(api_client.mark_stop_missed(stops[1]["id"], CHEMIST))
    assert missed["status"] == "MISSED"

    route_after = validate_success(api_client.get_test_route(route["id"], CHEMIST))
    assert route_after["status"] == "COMPLETED"


def test_route_cancel_cascades_scheduled_stops_to_skipped(api):
    """PRD §3.4: "Cancelling is allowed from either `PLANNED` or `PUBLISHED`
    and moves the route to `CANCELLED`, cascading every still-`SCHEDULED` stop
    to `SKIPPED`."

    Design: Corner/state_machines/route_cancel_cascades_scheduled_stops_to_skipped
    """
    subtree = setup_commissioned_asset(account_name="Casc Co")
    account_id, asset_id = subtree["account"]["id"], subtree["asset"]["id"]
    route, stops = create_published_route(
        account_id,
        asset_id,
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
         ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z")],
    )
    set_clock("2026-08-02T01:00:00Z")
    arrive_at_stop(stops[0]["id"])  # stop1 ARRIVED — outside the cascade's condition

    cancelled = validate_success(api_client.cancel_route(route["id"], CHEMIST))
    assert cancelled["status"] == "CANCELLED"

    stop1 = validate_success(api_client.get_stop(stops[0]["id"], CHEMIST))
    stop2 = validate_success(api_client.get_stop(stops[1]["id"], CHEMIST))
    assert stop2["status"] == "SKIPPED"
    assert stop1["status"] == "ARRIVED", "an ARRIVED stop is untouched by the cancel cascade"


def test_account_suspend_cascades_open_orders_to_cancelled(api):
    """PRD §3.1: "Suspending an `ACTIVE` account — any other state is rejected
    with `ERR_INVALID_STATE` — cascades through the account's open logistics:
    every delivery order of the account still in `DRAFT`, `PENDING`, or
    `SCHEDULED` transitions to `CANCELLED`, releasing each scheduled order's
    tote allocation".

    Design: Corner/state_machines/account_suspend_cascades_open_orders_to_cancelled
    """
    subtree = setup_delivery_ready(account_name="Susp Co")
    account, station = subtree["account"], subtree["station"]

    # O1 -> SCHEDULED; O2 stays DRAFT; O3 fully delivered and CLOSED.
    o1 = create_pending_order(account["id"], station["id"], 55)
    o1 = schedule_order(o1["id"], "2026-08-10T00:00:00Z", o1["version"])
    o2 = validate_success(
        api_client.create_delivery_order(
            {"account_id": account["id"], "station_id": station["id"], "quantity_gal": 55},
            MANAGER,
        ),
        expected_status=201,
    )
    o3 = deliver_and_close_order(
        account["id"], station["id"], 55, "2026-08-02T00:00:00Z"
    )
    assert o3["status"] == "CLOSED"

    suspended = validate_success(api_client.suspend_account(account["id"], MANAGER))
    assert suspended["status"] == "SUSPENDED"

    for oid, expected in ((o1["id"], "CANCELLED"), (o2["id"], "CANCELLED"), (o3["id"], "CLOSED")):
        after = validate_success(api_client.get_delivery_order(oid, MANAGER))
        assert after["status"] == expected, f"order {oid}: expected {expected}, got {after['status']}"


def test_water_result_void_compensates_escalation(api):
    """PRD §3.4: "Voiding — `RECORDED` → `VOIDED` — retracts a bad sample and
    compensates everything the result had caused: if the result had
    contributed an `OUT_OF_RANGE` to the asset's counter,
    `consecutive_out_of_range_count` is decremented by one (never below zero)
    and the asset's posture is recomputed, and any corrective action still
    `PENDING` that names this result as its `triggering_result_id` transitions
    to `DECLINED`."

    Design: Corner/state_machines/water_result_void_compensates_escalation
    """
    subtree = setup_commissioned_asset(account_name="Void Co")
    _, _, results = record_out_of_range_sequence(subtree, count=3)
    action = find_pending_action(subtree["asset"]["id"])
    triggering = results[2]

    voided = validate_success(api_client.void_water_test_result(triggering["id"], CHEMIST))
    assert voided["status"] == "VOIDED"

    asset = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset["consecutive_out_of_range_count"] == 2

    action_after = validate_success(api_client.get_corrective_action(action["id"], CHEMIST))
    assert action_after["status"] == "DECLINED"
