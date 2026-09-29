"""Non-linear state machines: the order's two parallel dimensions and the
shipment's IN_TRANSIT -> EXCEPTION -> IN_TRANSIT cycle.

Both families exercise transitions that are *not* a straight line: a cascade that
is conditioned on the dimension it does not move, and a shipment that re-enters a
status it has already left.
"""

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_instant_equals,
    assert_liters,
    assert_order_dimensions,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_TOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
    CLOCK_STARTUP_DEFAULT,
)
from test_helpers.fixtures import build_in_transit_order


# ---------------------------------------------------------------------------
# Local arrangements
# ---------------------------------------------------------------------------
def _two_orders_one_in_transit_one_unfulfilled(api):
    """Two identical canonical TX orders that differ only on the fulfillment axis.

    Order 1 is CLEARED, labelled and picked up, so it sits at IN_TRANSIT.
    Order 2 is CLEARED and never labelled, so it stays at UNFULFILLED.  Their
    combined 9.000 L is well inside the 27.000 L TX per-consumer limit, so the
    second screen clears on volume as well.
    """
    scape, first_order, first_shipment = build_in_transit_order(api)
    second_order = scape.create_order()
    scape.screen(second_order["id"])
    return scape, first_order, first_shipment, second_order


def _in_transit_shipment(api):
    """A CLEARED canonical TX order whose shipment has been picked up."""
    return build_in_transit_order(api)


# ---------------------------------------------------------------------------
# Instance: order_parallel_dimensions_compliance_and_fulfillment_independent
# ---------------------------------------------------------------------------
def test_revocation_suspends_only_the_unfulfilled_order_on_the_compliance_axis(api):
    """Revocation's first tier is conditioned on the *other* status dimension.

    PRD §3.2: "**First**, every order of that winery bound for that state whose
    `compliance_status` is `CLEARED` and whose `fulfillment_status` is still
    `UNFULFILLED` is moved `CLEARED` -> `SUSPENDED_PERMIT`, with
    `ERR_PERMIT_NOT_ACTIVE` written into its `rejection_error_id`."
    PRD §3.2: "Orders that have already been labelled, picked up, delivered or
    returned are left alone — the wine is already gone."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_compliance_and_fulfillment_independent
    """
    scape, first_order, _, second_order = _two_orders_one_in_transit_one_unfulfilled(api)

    scape.revoke_permit()

    permit = scape.read_permit()
    assert permit["status"] == "REVOKED"

    # The picked-up order is untouched: tier one never reaches it.
    reread_first = scape.read_order(first_order["id"])
    assert_order_dimensions(reread_first, compliance_status="CLEARED")
    assert reread_first["rejection_error_id"] is None

    # The unfulfilled order is frozen on the compliance axis only.
    reread_second = scape.read_order(second_order["id"])
    assert_order_dimensions(reread_second, compliance_status="SUSPENDED_PERMIT")
    assert reread_second["rejection_error_id"] == "ERR_PERMIT_NOT_ACTIVE"


def test_revocation_moves_neither_order_on_the_fulfillment_axis(api):
    """The fulfillment dimension does not follow the compliance dimension.

    PRD §2.11: "An `Order` row carries two status fields that are read and moved
    independently."
    PRD §2.11: "Neither dimension restricts the other's reachable values except
    where a rule in §3 says so in as many words."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_compliance_and_fulfillment_independent
    """
    scape, first_order, _, second_order = _two_orders_one_in_transit_one_unfulfilled(api)

    scape.revoke_permit()

    reread_first = scape.read_order(first_order["id"])
    assert_order_dimensions(
        reread_first, compliance_status="CLEARED", fulfillment_status="IN_TRANSIT"
    )

    reread_second = scape.read_order(second_order["id"])
    assert_order_dimensions(
        reread_second,
        compliance_status="SUSPENDED_PERMIT",
        fulfillment_status="UNFULFILLED",
    )


def test_suspension_leaves_frozen_money_and_finds_no_subscription_to_suspend(api):
    """Tiers two and three find nothing, and the frozen money is untouched.

    PRD §3.5: "Every monetary and volumetric field on the order and on each of its
    lines is computed exactly once, at creation, from the governing state rule and
    the winery, and then **frozen**."
    PRD §3.2: "**Third**, because those subscriptions changed status, the winery's
    `suspended_subscription_count` is recomputed as the number of that winery's
    subscriptions now sitting in `SUSPENDED_COMPLIANCE`, and `Winery.version`
    increments by 1."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_compliance_and_fulfillment_independent
    """
    scape, _, _, second_order = _two_orders_one_in_transit_one_unfulfilled(api)

    scape.revoke_permit()

    reread_second = scape.read_order(second_order["id"])
    assert_order_dimensions(reread_second, compliance_status="SUSPENDED_PERMIT")
    assert_charge_chain(
        reread_second,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )

    # Neither order names a club subscription, so tier two has no row to move and
    # the recomputed winery counter stays at its documented zero value.
    winery = scape.read_winery()
    assert winery["suspended_subscription_count"] == 0, (
        "no subscription exists, so the recomputed counter must stay at 0, got "
        f"{winery['suspended_subscription_count']}"
    )


# ---------------------------------------------------------------------------
# Instance: shipment_cycle_in_transit_exception_in_transit_via_reroute
# ---------------------------------------------------------------------------
def test_exception_scan_is_carrier_local_and_does_not_move_the_order(api):
    """IN_TRANSIT -> EXCEPTION moves the shipment and nothing else.

    PRD §3.7: "An **`EXCEPTION`** scan moves the shipment `IN_TRANSIT` ->
    `EXCEPTION` and requires an `exception_code` of `WEATHER`,
    `ADDRESS_UNDELIVERABLE`, `ADULT_SIGNATURE_UNAVAILABLE` or `REFUSED`, which is
    recorded on the shipment."
    PRD §3.7: "The order's `fulfillment_status` deliberately **stays**
    `IN_TRANSIT`: an exception is a carrier-visible hiccup, not a change in where
    the wine is."

    Design: Difficulty/non_linear_state_machine/shipment_cycle_in_transit_exception_in_transit_via_reroute
    """
    scape, order, shipment = _in_transit_shipment(api)

    scanned = scape.scan(shipment["id"], f.exception_scan("WEATHER"))

    assert scanned["status"] == "EXCEPTION"
    assert scanned["exception_code"] == "WEATHER"

    reread_order = scape.read_order(order["id"])
    assert_order_dimensions(
        reread_order, compliance_status="CLEARED", fulfillment_status="IN_TRANSIT"
    )


def test_reroute_returns_the_shipment_to_a_status_it_already_left(api):
    """EXCEPTION -> IN_TRANSIT closes the cycle and bumps ``reroute_count`` to 1.

    PRD §3.7: "A **`REROUTE_ACCEPTED`** scan moves the shipment `EXCEPTION` ->
    `IN_TRANSIT`, closing the `IN_TRANSIT` -> `EXCEPTION` -> `IN_TRANSIT` cycle,
    and carries a `reroute_zip` and a `reroute_state_code`."
    PRD §3.7: "On success the shipment's `status` becomes `IN_TRANSIT`,
    `reroute_zip` is recorded, `reroute_count` grows by 1, and `exception_code` is
    cleared to null; on the order, `ship_to_zip` is rewritten to the accepted
    reroute ZIP and `Order.version` increments by 1."

    Design: Difficulty/non_linear_state_machine/shipment_cycle_in_transit_exception_in_transit_via_reroute
    """
    scape, order, shipment = _in_transit_shipment(api)
    scape.scan(shipment["id"], f.exception_scan("WEATHER"))

    rerouted = scape.scan(shipment["id"], f.reroute_scan("78702", "TX"))

    assert rerouted["status"] == "IN_TRANSIT"
    assert rerouted["reroute_count"] == 1
    assert rerouted["reroute_zip"] == "78702"
    assert rerouted["exception_code"] is None

    reread_order = scape.read_order(order["id"])
    # PRD §3.7 rewrites the order's destination ZIP to the accepted reroute ZIP.
    assert reread_order["ship_to_zip"] == "78702"
    assert_order_dimensions(
        reread_order, compliance_status="CLEARED", fulfillment_status="IN_TRANSIT"
    )


def test_reroute_moves_no_liters_and_leaves_the_frozen_tax_basis_alone(api):
    """A same-state reroute changes no money and appends no ledger row.

    PRD §3.7: "There is no ledger movement of any kind — the destination state has
    not changed, so neither tax nor volume attribution changes."
    PRD §3.5: "Nothing later in the order's life recomputes them — not screening,
    not an override, not a return."

    Design: Difficulty/non_linear_state_machine/shipment_cycle_in_transit_exception_in_transit_via_reroute
    """
    scape, order, shipment = _in_transit_shipment(api)
    scape.scan(shipment["id"], f.exception_scan("WEATHER"))

    scape.scan(shipment["id"], f.reroute_scan("78702", "TX"))

    reread_order = scape.read_order(order["id"])
    assert_charge_chain(
        reread_order,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )
    assert_cents(reread_order["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(
        reread_order["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents"
    )

    rows = scape.ledger_rows(order_id=order["id"])
    assert len(rows) == 1, (
        "only the clearance SHIPMENT_ACCEPTED entry may exist after a reroute, "
        f"got {len(rows)} rows"
    )
    assert rows[0]["event_type"] == "SHIPMENT_ACCEPTED"
    assert_liters(rows[0]["liters"], CANONICAL_ORDER_TOTAL_LITERS)


def test_delivery_is_still_legal_after_the_reroute_cycle(api):
    """The re-entered IN_TRANSIT status still admits the DELIVERED transition.

    PRD §3.7: "A **`DELIVERED`** scan moves the shipment `IN_TRANSIT` ->
    `DELIVERED`."
    PRD §3.7: "On success the shipment's `delivered_at` is stamped from the logical
    clock, `signed_by` and `signer_age_verified` are recorded, and the order's
    `fulfillment_status` becomes `DELIVERED` — which is exactly what makes the
    order eligible for a delivery-basis reporting period, as §3.9 explains."

    Design: Difficulty/non_linear_state_machine/shipment_cycle_in_transit_exception_in_transit_via_reroute
    """
    scape, order, shipment = _in_transit_shipment(api)
    scape.scan(shipment["id"], f.exception_scan("WEATHER"))
    scape.scan(shipment["id"], f.reroute_scan("78702", "TX"))

    delivered = scape.scan(
        shipment["id"], f.delivered_scan("Ada Buyer", True)
    )

    assert delivered["status"] == "DELIVERED"
    assert delivered["signed_by"] == "Ada Buyer"
    assert delivered["signer_age_verified"] is True
    assert_instant_equals(delivered["delivered_at"], CLOCK_STARTUP_DEFAULT)
    # The reroute ZIP survives the delivery scan.
    assert delivered["reroute_zip"] == "78702"
    assert delivered["reroute_count"] == 1

    reread_order = scape.read_order(order["id"])
    assert_order_dimensions(
        reread_order, compliance_status="CLEARED", fulfillment_status="DELIVERED"
    )
