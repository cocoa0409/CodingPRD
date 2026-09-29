"""Two finite resources booked by time window, with opposite semantics.

A fabrication line uses half-open windows widened by a paint changeover buffer;
a job site uses closed windows with no buffer and an aggregate count. Neither is
interchangeable with the other.
"""

from test_helpers import (
    LOGISTICS,
    PLANNER,
    assert_order_dimensions,
    assert_pounds_ledger_conserved,
    assert_weight,
    chain_released_order,
    connection_component_payload,
    create_production_line,
    create_production_lot_payload,
    create_shipment_load_payload,
    get_order,
    get_production_lot,
    member_component_payload,
    minimal_bom,
    plan_load,
    schedule_lot,
    validate_error,
    validate_paginated,
)

#: The primary frame, the secondary frame and the anchorage, so three different
#: erection stages can be trucked to one job site.
MULTI_STAGE_BILL = [
    member_component_payload(
        mark="C-1", member_type="COLUMN", quantity=10, length_ft=24.5, weight_per_ft=62.35
    ),
    member_component_payload(
        mark="P-1",
        component_class="SECONDARY_MEMBER",
        member_type="PURLIN",
        erection_stage="SECONDARY_FRAME",
        quantity=40,
        length_ft=25.083,
        weight_per_ft=3.375,
    ),
    member_component_payload(
        mark="AB-1",
        component_class="ANCHOR_PACKAGE",
        member_type="ANCHOR_BOLT",
        erection_stage="ANCHORAGE",
        quantity=10,
        length_ft=1.5,
        weight_per_ft=2.2,
    ),
    connection_component_payload(
        mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
    ),
    connection_component_payload(
        mark="B-1", connection_type="BASE", capacity_moment_kip_ft=900,
        erection_stage="ANCHORAGE",
    ),
]


def _line_with_a_white_afternoon_lot():
    """A released order and a plate line already running white from 12:00 to 16:00."""
    chain = chain_released_order(
        components=minimal_bom(), package_overrides={"sheet_count": 12}
    )
    chain["line"] = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD",
        changeover_buffer_minutes=120,
    )
    chain["occupant"] = schedule_lot(
        chain["order"]["id"], chain["line"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T12:00:00Z", window_end="2026-08-10T16:00:00Z",
    )
    return chain


def _site_with_two_touching_unload_windows():
    """One job site holding two planned trucks whose windows bracket 12:00 to 16:00."""
    chain = chain_released_order(
        components=MULTI_STAGE_BILL, package_overrides={"sheet_count": 14}
    )
    order_id = chain["order"]["id"]
    chain["load_a"] = plan_load(
        order_id,
        component_marks=["C-1"],
        erection_stage="PRIMARY_FRAME",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    chain["load_d"] = plan_load(
        order_id,
        component_marks=["P-1"],
        erection_stage="SECONDARY_FRAME",
        unload_window_start="2026-09-15T16:00:00Z",
        unload_window_end="2026-09-15T20:00:00Z",
    )
    chain["order"] = get_order(order_id)
    return chain


def test_01_a_colour_change_makes_the_occupied_window_wider_by_the_buffer(api):
    """A red lot starting at the white lot's end still collides through the buffer.

    PRD §3.8: "For each occupant, the applicable buffer is 0 when the occupant's
    ``paint_color`` equals the requested ``paint_color``, and the line's
    ``changeover_buffer_minutes`` when the two colours differ."

    PRD §3.8: "The requested window collides with that occupant when the requested
    ``window_start`` falls strictly before the occupant's ``window_end`` advanced
    by the buffer, **and** the occupant's ``window_start`` falls strictly before
    the requested ``window_end`` advanced by the buffer."

    PRD §3.8: "Any collision is refused with ``ERR_LINE_WINDOW_CONFLICT``."

    Design: Difficulty/resource_temporal_overlap/production_line_half_open_window_with_paint_changeover_buffer
    """
    chain = _line_with_a_white_afternoon_lot()

    response = api.create_production_lot(
        create_production_lot_payload(
            chain["order"]["id"], chain["line"]["id"],
            lot_type="PRIMARY_FRAME_FAB", paint_color="BRIGHT_RED",
            window_start="2026-08-10T16:00:00Z", window_end="2026-08-10T20:00:00Z",
        ),
        PLANNER,
    )

    validate_error(response, "ERR_LINE_WINDOW_CONFLICT", expected_status=409)


def test_02_a_same_colour_lot_may_start_exactly_when_the_occupant_ends():
    """With a zero buffer the half-open window makes the endpoint free.

    PRD §3.8: "Because both comparisons are strict and ``window_end`` is
    exclusive, a same-colour lot may begin at exactly the instant an occupant's
    window ends; a different-colour lot must wait the full changeover, by default
    two hours."

    PRD §3.8: "The buffer is the paint changeover time the line needs between two
    consecutive lots of different colour, and §3.8's window arithmetic below shows
    exactly how it widens an occupied window."

    Design: Difficulty/resource_temporal_overlap/production_line_half_open_window_with_paint_changeover_buffer
    """
    chain = _line_with_a_white_afternoon_lot()

    following = schedule_lot(
        chain["order"]["id"], chain["line"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T16:00:00Z", window_end="2026-08-10T20:00:00Z",
    )

    assert following["status"] == "SCHEDULED"
    assert following["window_start"].startswith("2026-08-10T16:00:00")


def test_03_both_lots_occupy_the_line_and_the_order_moves_into_fabrication(api):
    """Occupants are the SCHEDULED and COMPLETE lots of the line.

    PRD §3.8: "The occupants of a line are its lots whose ``status`` is
    ``SCHEDULED`` or ``COMPLETE``; a ``CANCELLED`` lot frees its window entirely
    and is never an occupant."

    PRD §3.8: "A successfully scheduled lot sets ``status`` to ``SCHEDULED`` and
    then re-runs the production rollup on its order, which typically advances the
    order from ``PROD_RELEASED`` to ``PROD_IN_FABRICATION``; the order's
    ``version`` increments."

    Design: Difficulty/resource_temporal_overlap/production_line_half_open_window_with_paint_changeover_buffer
    """
    chain = _line_with_a_white_afternoon_lot()
    following = schedule_lot(
        chain["order"]["id"], chain["line"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T16:00:00Z", window_end="2026-08-10T20:00:00Z",
    )

    assert get_production_lot(chain["occupant"]["id"])["status"] == "SCHEDULED"
    assert get_production_lot(following["id"])["status"] == "SCHEDULED"
    lots, meta = validate_paginated(
        api.list_production_lots(PLANNER, params={"line_id": chain["line"]["id"]})
    )
    assert meta["total_count"] == 2
    assert all(lot["status"] == "SCHEDULED" for lot in lots)
    assert_order_dimensions(
        get_order(chain["order"]["id"]), "ENG_SEALED", "PROD_IN_FABRICATION"
    )


def test_04_a_touching_unload_window_counts_against_the_site_capacity(api):
    """Closed semantics mean windows that merely touch at an endpoint do meet.

    PRD §3.9: "Among those it counts the ones the new window meets: an existing
    load counts when the new ``unload_window_start`` is at or before that load's
    ``unload_window_end`` and that load's ``unload_window_start`` is at or before
    the new ``unload_window_end``."

    PRD §3.9: "Because both comparisons are inclusive, two windows that merely
    touch at an endpoint do count as meeting."

    PRD §3.9: "If the resulting count is greater than or equal to the target
    order's ``site_delivery_capacity``, the request is refused with
    ``ERR_SITE_UNLOAD_CAPACITY_EXCEEDED``; strictly fewer than the capacity is
    required to proceed."

    Design: Difficulty/resource_temporal_overlap/site_unload_closed_window_aggregate_capacity
    """
    chain = _site_with_two_touching_unload_windows()
    assert chain["order"]["site_delivery_capacity"] == 2

    response = api.create_shipment_load(
        create_shipment_load_payload(
            chain["order"]["id"], chain["order"]["version"],
            component_marks=["AB-1"],
            erection_stage="ANCHORAGE",
            unload_window_start="2026-09-15T12:00:00Z",
            unload_window_end="2026-09-15T16:00:00Z",
        ),
        LOGISTICS,
    )

    validate_error(response, "ERR_SITE_UNLOAD_CAPACITY_EXCEEDED", expected_status=409)


def test_05_the_refused_truck_creates_no_row_and_moves_no_version(api):
    """A capacity refusal is a short-circuit, so the order is left exactly as it was.

    PRD §2.5: "Checks are evaluated in a fixed global precedence, and the first
    failure short-circuits the request: no later check runs and no state
    changes."

    PRD §3.9: "Site capacity is the last constraint, and it is an **aggregate**
    check with **closed** window semantics and no buffer."

    Design: Difficulty/resource_temporal_overlap/site_unload_closed_window_aggregate_capacity
    """
    chain = _site_with_two_touching_unload_windows()

    api.create_shipment_load(
        create_shipment_load_payload(
            chain["order"]["id"], chain["order"]["version"],
            component_marks=["AB-1"],
            erection_stage="ANCHORAGE",
            unload_window_start="2026-09-15T12:00:00Z",
            unload_window_end="2026-09-15T16:00:00Z",
        ),
        LOGISTICS,
    )

    _, meta = validate_paginated(
        api.list_shipment_loads(LOGISTICS, params={"order_id": chain["order"]["id"]})
    )
    assert meta["total_count"] == 2
    after = get_order(chain["order"]["id"])
    assert after["version"] == chain["order"]["version"]


def test_06_the_two_planned_trucks_are_what_the_pounds_ledger_counts():
    """Assigned pounds is the sum of the gross weights of the live loads.

    PRD §3.9: "On success the load's ``gross_weight_lbs`` is computed as the sum
    of ``line_weight_lbs`` over the resolved components, rounded half up to two
    decimal places; its ``stage_sequence`` is set from the erection stage ordering
    of §2.12; its ``status`` is set to ``PLANNED``; the order's pounds ledger is
    recomputed, raising ``assigned_weight_lbs`` and lowering
    ``unassigned_weight_lbs`` by the same amount; and the order's ``version``
    increments."

    PRD §2.9: "Every load creation and every load cancellation recomputes
    ``assigned_weight_lbs`` as the sum of ``gross_weight_lbs`` over the order's
    shipment loads whose ``status`` is ``PLANNED`` or ``DISPATCHED`` — cancelled
    loads are excluded entirely — rounded half up to two decimal places, and then
    recomputes ``unassigned_weight_lbs`` as the total minus the assigned amount,
    also rounded half up to two decimal places."

    Design: Difficulty/resource_temporal_overlap/site_unload_closed_window_aggregate_capacity
    """
    chain = _site_with_two_touching_unload_windows()

    assert_weight(chain["load_a"]["gross_weight_lbs"], 15275.80)
    assert_weight(chain["load_d"]["gross_weight_lbs"], 3386.40)
    order = chain["order"]
    assert_weight(order["assigned_weight_lbs"], 18662.20)
    assert_pounds_ledger_conserved(order)
