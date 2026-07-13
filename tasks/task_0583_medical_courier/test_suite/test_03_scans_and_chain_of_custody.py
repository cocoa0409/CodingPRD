"""Scans: the chain of custody, the stop bubble-up, and the guards on scanning."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    scan_payload,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Delivering a specimen bubbles its dropoff stop up to COMPLETED
# ---------------------------------------------------------------------------
def test_dropoff_scan_delivers_specimen_and_completes_its_stop(api):
    """PRD §3.5: "A dropoff scan advances the specimen `IN_TRANSIT → DELIVERED`; the
    specimen must be `IN_TRANSIT` (else `ERR_SPECIMEN_INVALID_STATE`) and the scanned
    stop must be its `dropoff_stop_id` (else `ERR_SPECIMEN_STOP_MISMATCH`)."
    PRD §3.5: "A stop in `ARRIVED` state advances `ARRIVED → COMPLETED` once every
    specimen whose `pickup_stop_id` is that stop has left `AWAITING_PICKUP`, and every
    specimen whose `dropoff_stop_id` is that stop has reached `DELIVERED`."

    Design: Difficulty/transitive_cascade/dropoff_delivery_depth2_stop_autocomplete
    """
    ctx = fixtures.setup_dispatched_route()
    spec = ctx["specimens"][0]
    fixtures.scan(ctx["stops"][0]["id"], spec["id"], "PICKUP", 5.0, 2.5, ctx["driver"]["id"])

    fixtures.scan(ctx["stops"][1]["id"], spec["id"], "DROPOFF", 5.0, 3.5, ctx["driver"]["id"])

    specimen = validate_success(api.get_specimen(spec["id"], DISPATCHER))
    dropoff_stop = validate_success(api.get_stop(ctx["stops"][1]["id"], DISPATCHER))
    assert specimen["custody_status"] == "DELIVERED"
    assert dropoff_stop["status"] == "COMPLETED", (
        f"The dropoff stop must bubble up to COMPLETED, got {dropoff_stop['status']}"
    )
    assert dropoff_stop["completed_at"] is not None, "A completed stop stamps completed_at"


def test_completing_a_stop_computes_its_leg_charge(api):
    """PRD §3.5: "On completion the stop stamps `completed_at` and computes its
    `leg_charge_cents` as `per_stop_fee_cents` plus the product of its
    `actual_leg_miles` and `per_mile_rate_cents` rounded half-up to whole cents."

    The dropoff stop arrives on a 3.5-mile leg: 500 + round_half_up(3.5 * 133) = 966.

    Design: Difficulty/transitive_cascade/dropoff_delivery_depth2_stop_autocomplete
    """
    ctx = fixtures.setup_served_route()
    dropoff_stop = validate_success(api.get_stop(ctx["stops"][1]["id"], DISPATCHER))
    assert dropoff_stop["status"] == "COMPLETED"
    assert dropoff_stop["actual_leg_miles"] == 3.5
    assert dropoff_stop["leg_charge_cents"] == 966, (
        f"Expected 500 + round_half_up(3.5 * 133) = 966, got {dropoff_stop['leg_charge_cents']}"
    )


# ---------------------------------------------------------------------------
# Scanning is gated by the parent route's state
# ---------------------------------------------------------------------------
def test_scan_on_an_assigned_but_undispatched_route_is_rejected(api):
    """PRD §3.5: "Scans are permitted only while the parent route is `DISPATCHED` (else
    `ERR_ROUTE_INVALID_STATE`), and only when the acting driver's own identity matches
    the route's `driver_id` (else `ERR_UNAUTHORIZED`)."

    Design: Difficulty/cross_entity_state_dependency/scan_requires_route_dispatched
    """
    ctx = fixtures.setup_scenario(assign=True)
    resp = api.scan_stop(
        ctx["stops"][0]["id"],
        scan_payload(ctx["specimens"][0]["id"], "PICKUP", 5.0, 2.5),
        make_driver_headers(ctx["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_INVALID_STATE.value)


def test_scan_rejected_on_undispatched_route_leaves_stop_and_specimen_untouched(api):
    """PRD §3.5: "Scans are permitted only while the parent route is `DISPATCHED` (else
    `ERR_ROUTE_INVALID_STATE`), and only when the acting driver's own identity matches
    the route's `driver_id` (else `ERR_UNAUTHORIZED`)."
    PRD §3.5: "The first scan at a stop moves it `SCHEDULED → ARRIVED`, stamping its
    `arrived_at` with the current clock and recording that first scan's `leg_miles` as
    the stop's `actual_leg_miles`; subsequent scans at the same stop leave
    `actual_leg_miles` untouched."

    A scan the route's state forbids performs none of those effects.

    Design: Difficulty/cross_entity_state_dependency/scan_requires_route_dispatched
    """
    ctx = fixtures.setup_scenario(assign=True)
    resp = api.scan_stop(
        ctx["stops"][0]["id"],
        scan_payload(ctx["specimens"][0]["id"], "PICKUP", 5.0, 2.5),
        make_driver_headers(ctx["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_INVALID_STATE.value)

    stop = validate_success(api.get_stop(ctx["stops"][0]["id"], DISPATCHER))
    specimen = validate_success(api.get_specimen(ctx["specimens"][0]["id"], DISPATCHER))
    assert stop["status"] == "SCHEDULED", "A rejected scan must not move the stop to ARRIVED"
    assert stop["arrived_at"] is None
    assert specimen["custody_status"] == "AWAITING_PICKUP"


# ---------------------------------------------------------------------------
# Custody ordering and stop matching
# ---------------------------------------------------------------------------
def test_dropoff_scan_before_pickup_is_rejected(api):
    """PRD §3.5: "A dropoff scan advances the specimen `IN_TRANSIT → DELIVERED`; the
    specimen must be `IN_TRANSIT` (else `ERR_SPECIMEN_INVALID_STATE`) and the scanned
    stop must be its `dropoff_stop_id` (else `ERR_SPECIMEN_STOP_MISMATCH`)."

    Design: Corner/state_machines/dropoff_scan_before_pickup_returns_409
    """
    ctx = fixtures.setup_dispatched_route()
    resp = api.scan_stop(
        ctx["stops"][1]["id"],
        scan_payload(ctx["specimens"][0]["id"], "DROPOFF", 5.0, 3.5),
        make_driver_headers(ctx["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_INVALID_STATE.value)


def test_pickup_scan_at_the_wrong_stop_is_rejected(api):
    """PRD §3.5: "The specimen must currently be `AWAITING_PICKUP`, else
    `ERR_SPECIMEN_INVALID_STATE`, and the scanned stop must be the specimen's own
    `pickup_stop_id`, else `ERR_SPECIMEN_STOP_MISMATCH`."

    Design: Corner/validations/pickup_scan_wrong_stop_returns_422
    """
    ctx = fixtures.setup_dispatched_route()
    resp = api.scan_stop(
        ctx["stops"][1]["id"],  # the specimen's dropoff stop, not its pickup stop
        scan_payload(ctx["specimens"][0]["id"], "PICKUP", 5.0, 3.5),
        make_driver_headers(ctx["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_STOP_MISMATCH.value)
