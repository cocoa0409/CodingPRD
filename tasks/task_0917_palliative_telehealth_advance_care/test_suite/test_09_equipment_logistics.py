"""Durable medical equipment: reservation, scheduling and the conserved ledger."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_dme_inventory,
    assert_inventory_conserved,
    assert_same_instant,
    is_valid_uuid,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN,
    NURSE,
    authorize_equipment,
    deliver_equipment,
    enroll_patient,
    read_inventory,
    request_equipment,
    schedule_equipment,
    set_clock,
    stock_inventory,
)


def _prior_auth_scenario():
    """A prior-auth line with one scheduled order and a second, overlapping one."""
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Jun Alvarado")
    inventory = stock_inventory(
        device_type="HOSPITAL_BED", total_units=5, prior_auth_required=True
    )
    first = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T09:00:00Z",
        delivery_window_end="2026-06-10T11:00:00Z",
    )
    authorize_equipment(first["id"], "PA-2026-0001")
    schedule_equipment(first["id"])
    second = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T10:00:00Z",
        delivery_window_end="2026-06-10T12:00:00Z",
    )
    return patient, inventory, first, second


# ---------------------------------------------------------------------------
# Prior authorisation pre-empts the overlap check
# ---------------------------------------------------------------------------
def test_prior_authorisation_is_reported_before_the_overlapping_window(api):
    """PRD 2.5: "**Prior authorisation.** A fulfillment `event` of `SCHEDULED`
    against an order still sitting in `PENDING_AUTH` is rejected until the
    authorisation endpoint has recorded a `prior_auth_reference`. Otherwise
    `ERR_PRIOR_AUTH_REQUIRED` (422). Applies to the equipment fulfillment
    endpoint."
    PRD 3.9: "The order's opening state forks on the inventory line, not on
    anything in the request: it opens in `PENDING_AUTH` when the named line has
    `prior_auth_required` true, and in `REQUESTED` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/prior_auth_preempts_delivery_window_overlap_on_dme_fulfillment
    """
    _, inventory, _, second = _prior_auth_scenario()
    assert second["status"] == "PENDING_AUTH"

    rejected = api.fulfill_dme_order(second["id"], {"event": "SCHEDULED"}, NURSE)
    validate_error(rejected, ApiErrorId.ERR_PRIOR_AUTH_REQUIRED.value, 422)

    unchanged = validate_success(api.get_dme_order(second["id"], NURSE))
    assert unchanged["status"] == "PENDING_AUTH"
    assert_inventory_conserved(read_inventory(inventory["id"]))


def test_authorising_the_order_then_exposes_the_overlapping_window(api):
    """PRD 3.9: "An order sitting in `PENDING_AUTH` is released by a
    `ProgramAdmin` recording a `prior_auth_reference`, which stores that reference
    and moves the order `PENDING_AUTH → REQUESTED`."
    PRD 3.9: "Scheduling also checks the calendar of the inventory line: the
    requested window must not intersect the window of any other order on the same
    `inventory_item_id` whose `status` is `REQUESTED`, `PENDING_AUTH`, `SCHEDULED`
    or `DELIVERED`."

    Design: Difficulty/priority_pair_validation_conflict/prior_auth_preempts_delivery_window_overlap_on_dme_fulfillment
    """
    _, inventory, _, second = _prior_auth_scenario()

    validate_error(
        api.fulfill_dme_order(second["id"], {"event": "SCHEDULED"}, NURSE),
        ApiErrorId.ERR_PRIOR_AUTH_REQUIRED.value,
        422,
    )

    authorised = validate_success(
        api.authorize_dme_order(second["id"], {"prior_auth_reference": "PA-2026-0002"}, ADMIN)
    )
    assert authorised["status"] == "REQUESTED"
    assert authorised["prior_auth_reference"] == "PA-2026-0002"

    rejected = api.fulfill_dme_order(second["id"], {"event": "SCHEDULED"}, NURSE)
    validate_error(rejected, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)

    final_order = validate_success(api.get_dme_order(second["id"], NURSE))
    assert final_order["status"] == "REQUESTED"

    line = read_inventory(inventory["id"])
    assert line["available_units"] == 3
    assert line["reserved_units"] == 2
    assert_inventory_conserved(line)


# ---------------------------------------------------------------------------
# Half-open delivery windows
# ---------------------------------------------------------------------------
def test_a_window_starting_where_another_ends_is_accepted(api):
    """PRD 3.9: "The interval is half-open — it includes its start instant and
    excludes its end instant — so two windows that meet exactly at one instant,
    one ending where the next begins, are both accepted; a genuine intersection is
    refused with `ERR_SCHEDULE_CONFLICT`."
    PRD 3.9: "Scheduling moves the order `REQUESTED → SCHEDULED`, retains the
    existing reservation and moves no units at all."

    Design: Difficulty/resource_temporal_overlap/dme_delivery_window_is_half_open_so_touching_windows_are_allowed
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Priya Raghavan")
    inventory = stock_inventory(
        device_type="WHEELCHAIR", total_units=5, prior_auth_required=False
    )
    first = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T09:00:00Z",
        delivery_window_end="2026-06-10T11:00:00Z",
    )
    schedule_equipment(first["id"])

    touching = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T11:00:00Z",
        delivery_window_end="2026-06-10T13:00:00Z",
    )
    scheduled = validate_success(
        api.fulfill_dme_order(touching["id"], {"event": "SCHEDULED"}, NURSE)
    )

    assert scheduled["status"] == "SCHEDULED"
    line = read_inventory(inventory["id"])
    assert line["available_units"] == 3
    assert line["reserved_units"] == 2
    assert line["delivered_units"] == 0


def test_a_window_that_genuinely_intersects_is_a_schedule_conflict(api):
    """PRD 2.5: "(a) For equipment: the requested interval from
    `delivery_window_start` up to `delivery_window_end` must not intersect the
    interval of any other equipment order on the same `inventory_item_id` whose
    `status` is `REQUESTED`, `PENDING_AUTH`, `SCHEDULED` or `DELIVERED`; the
    interval is half-open, so two windows that merely touch at a single instant —
    one ending exactly when the next begins — do not conflict."
    PRD 3.9: "The interval is half-open — it includes its start instant and
    excludes its end instant — so two windows that meet exactly at one instant,
    one ending where the next begins, are both accepted; a genuine intersection is
    refused with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/dme_delivery_window_is_half_open_so_touching_windows_are_allowed
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Priya Raghavan")
    inventory = stock_inventory(
        device_type="WHEELCHAIR", total_units=5, prior_auth_required=False
    )
    first = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T09:00:00Z",
        delivery_window_end="2026-06-10T11:00:00Z",
    )
    schedule_equipment(first["id"])
    touching = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T11:00:00Z",
        delivery_window_end="2026-06-10T13:00:00Z",
    )
    schedule_equipment(touching["id"])

    overlapping = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-10T10:00:00Z",
        delivery_window_end="2026-06-10T12:00:00Z",
    )
    rejected = api.fulfill_dme_order(overlapping["id"], {"event": "SCHEDULED"}, NURSE)
    validate_error(rejected, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)

    unchanged = validate_success(api.get_dme_order(overlapping["id"], NURSE))
    assert unchanged["status"] == "REQUESTED"

    line = read_inventory(inventory["id"])
    assert line["available_units"] == 2
    assert line["reserved_units"] == 3
    assert line["delivered_units"] == 0
    assert_inventory_conserved(line)


# ---------------------------------------------------------------------------
# The conserved equipment ledger
# ---------------------------------------------------------------------------
def test_a_reservation_compensated_by_cancellation_leaves_no_drift(api):
    """PRD 2.9: "Creating an order moves `quantity` units out of `available_units`
    and into `reserved_units`. Recording delivery moves `quantity` units out of
    `reserved_units` and into `delivered_units`. Closing with `CANCELLED` moves
    `quantity` units out of `reserved_units` back into `available_units`."
    PRD 2.9: "A create followed by its compensating cancellation leaves all three
    counters exactly where they started."

    Design: Difficulty/compensating_invariant/dme_reserve_deliver_and_close_conserve_total_units
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Rosa Lindqvist")
    inventory = stock_inventory(
        device_type="OXYGEN_CONCENTRATOR", total_units=5, prior_auth_required=False
    )
    assert inventory["available_units"] == 5
    assert inventory["reserved_units"] == 0
    assert inventory["delivered_units"] == 0

    order = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=2,
        delivery_window_start="2026-06-05T08:00:00Z",
        delivery_window_end="2026-06-05T10:00:00Z",
    )
    reserved = read_inventory(inventory["id"])
    assert reserved["available_units"] == 3
    assert reserved["reserved_units"] == 2
    assert_inventory_conserved(reserved)

    closed = validate_success(
        api.close_dme_order(order["id"], {"closed_reason": "CANCELLED"}, NURSE)
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == "CANCELLED"

    restored = read_inventory(inventory["id"])
    assert restored["available_units"] == 5
    assert restored["reserved_units"] == 0
    assert restored["delivered_units"] == 0
    assert restored["total_units"] == 5
    assert_inventory_conserved(restored)


def test_a_delivery_compensated_by_a_return_leaves_no_drift(api):
    """PRD 2.9: "Closing with `RETURNED` or `PICKED_UP_ON_DISCHARGE` moves
    `quantity` units out of `delivered_units` back into `available_units`."
    PRD 3.9: "A `DELIVERED` event applies to an order in `SCHEDULED`, moves it to
    `DELIVERED`, stamps `delivered_at` from the logical clock, and moves
    `quantity` units out of `reserved_units` and into `delivered_units`, leaving
    `total_units` untouched."

    Design: Difficulty/compensating_invariant/dme_reserve_deliver_and_close_conserve_total_units
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Rosa Lindqvist")
    inventory = stock_inventory(
        device_type="OXYGEN_CONCENTRATOR", total_units=5, prior_auth_required=False
    )

    order = request_equipment(
        patient["id"],
        inventory["id"],
        quantity=2,
        delivery_window_start="2026-06-06T08:00:00Z",
        delivery_window_end="2026-06-06T10:00:00Z",
    )
    schedule_equipment(order["id"])
    delivered = deliver_equipment(order["id"])
    assert delivered["status"] == "DELIVERED"
    assert_same_instant(
        delivered["delivered_at"], "2026-06-01T00:00:00Z", "DmeOrder.delivered_at"
    )

    mid = read_inventory(inventory["id"])
    assert mid["available_units"] == 3
    assert mid["reserved_units"] == 0
    assert mid["delivered_units"] == 2
    assert_inventory_conserved(mid)

    closed = validate_success(
        api.close_dme_order(order["id"], {"closed_reason": "RETURNED"}, NURSE)
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == "RETURNED"

    restored = read_inventory(inventory["id"])
    assert restored["available_units"] == 5
    assert restored["reserved_units"] == 0
    assert restored["delivered_units"] == 0
    assert restored["total_units"] == 5
    assert_inventory_conserved(restored)


# ---------------------------------------------------------------------------
# Inventory line creation and availability
# ---------------------------------------------------------------------------
def test_a_stocked_inventory_line_seeds_its_three_counters(api):
    """PRD 3.9: "A `ProgramAdmin` creates an inventory line with a `device_type`
    of `OXYGEN_CONCENTRATOR`, `HOSPITAL_BED`, `WHEELCHAIR` or `SUCTION_MACHINE`, a
    `total_units` count that is an integer from 1 to 500 inclusive and never
    changes afterwards, and an optional `prior_auth_required` flag defaulting to
    false. The line is created with `available_units` equal to `total_units`,
    `reserved_units` 0 and `delivered_units` 0."
    PRD 2.4: "`id` (string): a server-minted UUID. It carries no type prefix and
    is never derived from any business field."

    Design: Corner/entities/dme_inventory_system_fields_are_server_minted
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.create_dme_inventory(
        f.dme_inventory_payload(
            device_type="SUCTION_MACHINE", total_units=4, prior_auth_required=False
        ),
        ADMIN,
    )
    line = validate_success(response, 201)
    assert_dme_inventory(line)

    assert is_valid_uuid(line["id"]), f"id must be a bare UUID, got {line['id']!r}"
    assert_same_instant(
        line["created_at"], "2026-06-01T00:00:00Z", "DmeInventoryItem.created_at"
    )
    assert line["version"] == 1
    assert line["available_units"] == 4
    assert line["reserved_units"] == 0
    assert line["delivered_units"] == 0


def test_the_availability_gate_is_inclusive_at_the_remaining_units(api):
    """PRD 3.9: "The request is admitted only when the line's `available_units` is
    greater than or equal to `quantity` — asking for exactly the remaining units
    succeeds, asking for one more is refused with `ERR_INSUFFICIENT_INVENTORY`. On
    acceptance `quantity` units move out of `available_units` and into
    `reserved_units`."
    PRD 2.5: "**Inventory availability.** The inventory line's `available_units`
    is greater than or equal to the requested `quantity`; a request for exactly
    the remaining units succeeds. Otherwise `ERR_INSUFFICIENT_INVENTORY` (409).
    Applies to equipment order creation."

    Design: Corner/validations/dme_order_exceeding_available_units_returns_insufficient_inventory
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Mati Rossi")
    inventory = stock_inventory(
        device_type="HOSPITAL_BED", total_units=2, prior_auth_required=False
    )

    too_many = api.create_dme_order(
        f.dme_order_payload(
            patient["id"],
            inventory["id"],
            quantity=3,
            delivery_window_start="2026-06-05T08:00:00Z",
            delivery_window_end="2026-06-05T10:00:00Z",
        ),
        NURSE,
    )
    validate_error(too_many, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, 409)

    exact = validate_success(
        api.create_dme_order(
            f.dme_order_payload(
                patient["id"],
                inventory["id"],
                quantity=2,
                delivery_window_start="2026-06-05T08:00:00Z",
                delivery_window_end="2026-06-05T10:00:00Z",
            ),
            NURSE,
        ),
        201,
    )
    assert exact["status"] == "REQUESTED"

    depleted = api.create_dme_order(
        f.dme_order_payload(
            patient["id"],
            inventory["id"],
            quantity=1,
            delivery_window_start="2026-06-07T08:00:00Z",
            delivery_window_end="2026-06-07T10:00:00Z",
        ),
        NURSE,
    )
    validate_error(depleted, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, 409)

    line = read_inventory(inventory["id"])
    assert line["available_units"] == 0
    assert line["reserved_units"] == 2
    assert_inventory_conserved(line)
