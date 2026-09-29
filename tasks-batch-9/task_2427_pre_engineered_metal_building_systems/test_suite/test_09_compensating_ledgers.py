"""Compensating actions and the ledgers they must restore exactly.

Both conserved quantities have a compensating operation, and in both cases the
requirement is not merely that the ledger stays self-consistent but that it
returns to the precise value it held before the action being compensated.
"""

from test_helpers import (
    STANDARD_KITS,
    assert_credit_ledger_conserved,
    assert_order_dimensions,
    assert_pounds_ledger_conserved,
    assert_weight,
    cancel_load,
    cancel_order_release,
    chain_released_order,
    chain_sealed_order,
    full_bom,
    get_builder,
    get_order,
    get_quote,
    get_shipment_load,
    plan_load,
    release_order,
)


def _released_order_with_two_trucks():
    """A released order whose frame and secondary steel are on two planned trucks."""
    chain = chain_released_order(kits=STANDARD_KITS, components=full_bom())
    order_id = chain["order"]["id"]
    chain["load_a"] = plan_load(
        order_id,
        component_marks=["C-1", "R-1"],
        erection_stage="PRIMARY_FRAME",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    chain["load_b"] = plan_load(
        order_id,
        component_marks=["P-1"],
        erection_stage="SECONDARY_FRAME",
        unload_window_start="2026-09-16T08:00:00Z",
        unload_window_end="2026-09-16T12:00:00Z",
    )
    return chain


def test_01_release_opens_the_pounds_ledger_with_everything_unassigned():
    """The total is the design's shippable steel plus every kit's extended weight.

    PRD §3.8: "It opens the pounds ledger: ``total_shippable_weight_lbs`` is set
    to the design's ``shippable_weight_lbs`` plus the sum of
    ``extended_weight_lbs`` over every accessory kit of the order's configuration,
    rounded half up to two decimal places; ``assigned_weight_lbs`` is set to 0;
    and ``unassigned_weight_lbs`` is set equal to the total."

    PRD §2.9: "At release to fabrication an order's
    ``total_shippable_weight_lbs`` is fixed, ``assigned_weight_lbs`` is set to 0
    and ``unassigned_weight_lbs`` is set equal to the total."

    Design: Difficulty/compensating_invariant/load_cancel_restores_shippable_pounds_ledger
    """
    chain = chain_released_order(kits=STANDARD_KITS, components=full_bom())

    order = chain["order"]
    # 47323.92 of shippable steel plus 1281.00 and 264.75 of kit weight.
    assert_weight(order["total_shippable_weight_lbs"], 48869.67)
    assert_weight(order["assigned_weight_lbs"], 0)
    assert_weight(order["unassigned_weight_lbs"], 48869.67)
    assert_pounds_ledger_conserved(order)


def test_02_cancelling_a_truck_returns_exactly_its_gross_weight_to_unassigned():
    """A plan-then-cancel round trip shows zero drift.

    PRD §3.9: "The load's ``status`` becomes ``CANCELLED``, its marks are released
    so they may be assigned to another load, and the order's pounds ledger is
    recomputed — ``assigned_weight_lbs`` decreases by the cancelled load's
    ``gross_weight_lbs`` and ``unassigned_weight_lbs`` increases by the same
    amount, so a plan-then-cancel round trip shows zero drift."

    PRD §2.9: "The invariant is that assigned plus unassigned equals the total at
    all times."

    Design: Difficulty/compensating_invariant/load_cancel_restores_shippable_pounds_ledger
    """
    chain = _released_order_with_two_trucks()
    order_id = chain["order"]["id"]

    before_cancel = get_order(order_id)
    # 40234.60 on the frame truck plus 3386.40 on the secondary truck.
    assert_weight(before_cancel["assigned_weight_lbs"], 43621.00)
    assert_weight(before_cancel["unassigned_weight_lbs"], 5248.67)
    assert_pounds_ledger_conserved(before_cancel)

    cancel_load(chain["load_b"]["id"])

    after_cancel = get_order(order_id)
    assert_weight(after_cancel["assigned_weight_lbs"], 40234.60)
    assert_weight(after_cancel["unassigned_weight_lbs"], 8635.07)
    assert_pounds_ledger_conserved(after_cancel)


def test_03_cancelling_both_trucks_returns_the_ledger_to_its_release_state():
    """Cancelled loads are excluded entirely, yet keep their own gross weight.

    PRD §2.9: "Every load creation and every load cancellation recomputes
    ``assigned_weight_lbs`` as the sum of ``gross_weight_lbs`` over the order's
    shipment loads whose ``status`` is ``PLANNED`` or ``DISPATCHED`` — cancelled
    loads are excluded entirely — rounded half up to two decimal places, and then
    recomputes ``unassigned_weight_lbs`` as the total minus the assigned amount,
    also rounded half up to two decimal places."

    PRD §3.9: "**Cancelling a load** is the compensating action for planning."

    Design: Difficulty/compensating_invariant/load_cancel_restores_shippable_pounds_ledger
    """
    chain = _released_order_with_two_trucks()
    order_id = chain["order"]["id"]

    cancel_load(chain["load_b"]["id"])
    cancel_load(chain["load_a"]["id"])

    final = get_order(order_id)
    assert_weight(final["assigned_weight_lbs"], 0)
    assert_weight(final["unassigned_weight_lbs"], 48869.67)
    assert_weight(final["total_shippable_weight_lbs"], 48869.67)
    assert_pounds_ledger_conserved(final)
    assert_order_dimensions(final, "ENG_SEALED", "PROD_RELEASED")

    cancelled_a = get_shipment_load(chain["load_a"]["id"])
    assert cancelled_a["status"] == "CANCELLED"
    assert_weight(cancelled_a["gross_weight_lbs"], 40234.60)
    assert get_shipment_load(chain["load_b"]["id"])["status"] == "CANCELLED"


def test_04_cancel_release_restores_the_credit_ledger_to_its_accepted_value():
    """The negated delta puts committed credit back exactly where acceptance left it.

    PRD §2.9: "After a release followed by a cancellation of that release, the
    ledger must show zero drift."

    PRD §3.8: "On success the builder's ``credit_used_cents`` moves by the negation
    of ``price_delta_cents``, restoring exactly the value the ledger held
    immediately after quote acceptance; ``final_price_cents`` and
    ``price_delta_cents`` are cleared to null; ``total_shippable_weight_lbs``,
    ``assigned_weight_lbs`` and ``unassigned_weight_lbs`` all reset to 0;
    ``released_at`` is cleared to null; ``production_status`` returns to
    ``PROD_NOT_RELEASED``; and both the order's and the builder's ``version``
    increment."

    Design: Difficulty/compensating_invariant/cancel_release_restores_builder_credit_cents_ledger
    """
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    builder_id = chain["builder"]["id"]

    after_accept = get_builder(builder_id)
    assert after_accept["credit_used_cents"] == 9719236
    assert after_accept["credit_available_cents"] == 190280764
    assert_credit_ledger_conserved(after_accept)

    released = release_order(chain["order"]["id"], chain["order"]["version"])
    after_release = get_builder(builder_id)
    assert after_release["credit_used_cents"] == 9458205
    assert after_release["credit_available_cents"] == 190541795
    assert_credit_ledger_conserved(after_release)

    cancel_order_release(released["id"], get_order(released["id"])["version"])

    restored = get_builder(builder_id)
    assert restored["credit_used_cents"] == 9719236
    assert restored["credit_available_cents"] == 190280764
    assert_credit_ledger_conserved(restored)


def test_05_cancel_release_clears_the_price_fields_and_zeroes_the_pounds_ledger():
    """Every field the release wrote is unwritten by its compensation.

    PRD §3.8: "**Cancelling a release** is the exact compensating action, again
    performed by a ``ProductionPlanner`` with ``expected_order_version``."

    PRD §2.9: "Cancelling a release resets all three fields to 0."

    Design: Difficulty/compensating_invariant/cancel_release_restores_builder_credit_cents_ledger
    """
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    released = release_order(chain["order"]["id"], chain["order"]["version"])
    assert released["final_price_cents"] == 9458205
    assert released["price_delta_cents"] == -261031
    assert released["released_at"] is not None

    cancelled = cancel_order_release(
        released["id"], get_order(released["id"])["version"]
    )

    assert cancelled["final_price_cents"] is None
    assert cancelled["price_delta_cents"] is None
    assert cancelled["released_at"] is None
    assert_weight(cancelled["total_shippable_weight_lbs"], 0)
    assert_weight(cancelled["assigned_weight_lbs"], 0)
    assert_weight(cancelled["unassigned_weight_lbs"], 0)
    assert_pounds_ledger_conserved(cancelled)


def test_06_cancel_release_rewinds_production_only_and_leaves_the_quote_alone():
    """Engineering stays sealed and the originating quote keeps its price.

    PRD §2.11: "An order does not have one status; it has two, and they advance
    independently."

    PRD §3.4: "Under the ``PRELIMINARY`` variant the result is stored as the
    quote's ``quoted_price_cents``; under the ``FINAL`` variant it is stored as the
    order's ``final_price_cents``."

    PRD §3.4: "A quote row always carries ``quote_variant`` equal to
    ``PRELIMINARY``; the ``FINAL`` variant never writes a quote, it writes an
    order."

    Design: Difficulty/compensating_invariant/cancel_release_restores_builder_credit_cents_ledger
    """
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    released = release_order(chain["order"]["id"], chain["order"]["version"])

    cancelled = cancel_order_release(
        released["id"], get_order(released["id"])["version"]
    )

    assert_order_dimensions(
        cancelled, "ENG_SEALED", "PROD_NOT_RELEASED",
        permit_hold=False, commercial_hold=False,
    )
    quote = get_quote(chain["quote"]["id"])
    assert quote["quoted_price_cents"] == 9719236
    assert quote["quote_variant"] == "PRELIMINARY"
    assert quote["status"] == "ACCEPTED"
