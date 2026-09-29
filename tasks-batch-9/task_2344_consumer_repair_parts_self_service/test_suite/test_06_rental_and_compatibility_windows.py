"""Two interval resources with deliberately different semantics: the closed,
buffer-extended rental occupation and the half-open compatibility window.
"""
from test_helpers import (
    ADMIN,
    CUSTOMER,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# One rental kit, capacity one, already occupied through the turnaround buffer
# --------------------------------------------------------------------------- #
def _occupied_rental_kit():
    """A kit held by a pending order over 2026-08-05..2026-08-10, plus two empty orders."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9500",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    kit = fixtures.create_part(
        sku="SKU-RENT-KIT",
        part_class="RENTAL_KIT",
        list_price_cents=0,
        rental_deposit_cents=4000,
        concurrent_rental_capacity=1,
    )
    fixtures.create_compatibility(
        kit["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=5
    )
    fixtures.publish_part(kit["id"])
    fixtures.publish_disassembly_guide(model["id"], ["SKU-RENT-KIT"], safety_warning_count=2)

    def _rental_order(window_start, window_end):
        assessment = fixtures.create_assessment(
            model["id"], kit["id"], "US-CA", CUSTOMER
        )
        return fixtures.create_order(
            assessment["id"],
            "US-CA",
            CUSTOMER,
            rental_window_start=window_start,
            rental_window_end=window_end,
        )

    occupant = _rental_order("2026-08-05T00:00:00Z", "2026-08-10T00:00:00Z")
    fixtures.append_line(occupant["id"], kit["id"], 1, CUSTOMER)
    occupant = fixtures.request_disclosure(occupant["id"], CUSTOMER)

    touching = _rental_order("2026-08-12T00:00:00Z", "2026-08-15T00:00:00Z")
    clear = _rental_order("2026-08-13T00:00:00Z", "2026-08-16T00:00:00Z")
    return {"kit": kit, "occupant": occupant, "touching": touching, "clear": clear}


def test_rental_window_starting_on_the_buffered_end_day_is_refused():
    """PRD §3.6: "Each occupant's interval runs from its order's
    `rental_window_start` to its order's `rental_window_end` extended by a two-day
    turnaround buffer for cleaning and inspection."
    PRD §3.6: "Because both intervals are closed, touching endpoints do collide: a
    requested start equal to an occupied end is a conflict."
    PRD §3.6: "The occupied unit count is the sum of the `quantity` of every colliding
    occupant, and when that sum plus the new line's `quantity` exceeds the part's
    `concurrent_rental_capacity`, the append is refused with
    `ERR_RENTAL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/rental_kit_capacity_conflict_counts_the_turnaround_buffer
    """
    bundle = _occupied_rental_kit()

    response = api_client.append_order_line(
        bundle["touching"]["id"],
        factories.order_line_payload(
            bundle["kit"]["id"],
            fixtures.order_version(bundle["touching"]["id"], CUSTOMER),
            1,
        ),
        CUSTOMER,
    )
    validate_error(response, "ERR_RENTAL_CAPACITY_EXCEEDED", 409)

    assert fixtures.list_lines(bundle["touching"]["id"]) == [], (
        "the refused append must leave the order empty"
    )
    occupant = fixtures.read_order(bundle["occupant"]["id"])
    assert occupant["fulfillment_status"] == "PENDING_DISCLOSURE", (
        f"the occupant is unaffected by the refusal, got {occupant['fulfillment_status']}"
    )


def test_rental_window_starting_after_the_buffer_is_accepted():
    """PRD §3.6: "Every line on the same part belonging to a *different* order whose
    `fulfillment_status` is `PENDING_DISCLOSURE`, `CONFIRMED`, or `DELIVERED` counts
    as an occupant; occupations on orders in `DRAFT`, `BLOCKED_SAFETY_HOLD`, `CLOSED`,
    or `CANCELLED` are released and never counted."
    PRD §3.6: "The order's `rental_deposit_cents` is the sum, across lines whose
    part's `part_class` is `RENTAL_KIT`, of that part's `rental_deposit_cents`
    multiplied by the line's `quantity`."

    Design: Difficulty/resource_temporal_overlap/rental_kit_capacity_conflict_counts_the_turnaround_buffer
    """
    bundle = _occupied_rental_kit()

    response = api_client.append_order_line(
        bundle["clear"]["id"],
        factories.order_line_payload(
            bundle["kit"]["id"],
            fixtures.order_version(bundle["clear"]["id"], CUSTOMER),
            1,
        ),
        CUSTOMER,
    )
    line = validate_success(response, 201)
    assert line["quantity"] == 1, line["quantity"]

    order = fixtures.read_order(bundle["clear"]["id"])
    assert order["rental_deposit_cents"] == 4000, (
        f"Expected the kit deposit 4000 on the accepted order, got "
        f"{order['rental_deposit_cents']}"
    )
    assert order["parts_subtotal_cents"] == 0, (
        f"a rental kit is not a component or consumable, got "
        f"{order['parts_subtotal_cents']}"
    )


# --------------------------------------------------------------------------- #
# One compatibility slot whose window ends exactly where the next may begin
# --------------------------------------------------------------------------- #
def _part_with_one_closed_compatibility_window():
    """A draft part fitted to one model over the half-open window 2024-03-01..2025-01-01."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9600",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_B_GUIDED",
    )
    part = fixtures.create_part(sku="SKU-HINGE-2", list_price_cents=1200)
    compatibility = fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-03-01T00:00:00Z",
        effective_until="2025-01-01T00:00:00Z",
        install_minutes=25,
    )
    return {"model": model, "part": part, "compatibility": compatibility}


def test_compatibility_window_opening_inside_the_incumbent_is_refused():
    """PRD §3.3: "Two windows for the same part-and-model pair may not overlap: an
    overlap is refused with `ERR_COMPATIBILITY_WINDOW_OVERLAP`, while abutting
    windows — where one ends exactly when the next begins — are accepted."

    Design: Difficulty/resource_temporal_overlap/abutting_compatibility_windows_are_accepted_under_half_open_semantics
    """
    bundle = _part_with_one_closed_compatibility_window()

    response = api_client.create_part_compatibility(
        factories.part_compatibility_payload(
            bundle["part"]["id"],
            bundle["model"]["id"],
            effective_from="2024-12-01T00:00:00Z",
            install_minutes=25,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_COMPATIBILITY_WINDOW_OVERLAP", 409)

    incumbent = get_success_data(
        api_client.get_part_compatibility(bundle["compatibility"]["id"], ADMIN)
    )
    assert incumbent["effective_until"].startswith("2025-01-01T00:00:00"), (
        f"the refused registration must not touch the incumbent, got "
        f"{incumbent['effective_until']}"
    )


def test_compatibility_window_opening_exactly_at_the_exclusive_end_is_accepted():
    """PRD §3.3: "It carries a `part_id`, a `model_id`, an `effective_from` giving the
    inclusive start of the compatibility window, an optional `effective_until` giving
    the exclusive end — null means open-ended — a `self_service_eligible` flag saying
    whether an unassisted consumer may install this part on this model, an
    `install_minutes` figure between 1 and 600 giving documented bench time for the
    replacement, and an optional `required_tool_part_id` naming the tool or rental kit
    needed to install it, null when no tool is needed."
    PRD §3.3: "`superseded_by_safety_restriction` starts false."

    Design: Difficulty/resource_temporal_overlap/abutting_compatibility_windows_are_accepted_under_half_open_semantics
    """
    bundle = _part_with_one_closed_compatibility_window()
    api_client.create_part_compatibility(
        factories.part_compatibility_payload(
            bundle["part"]["id"],
            bundle["model"]["id"],
            effective_from="2024-12-01T00:00:00Z",
            install_minutes=25,
        ),
        ADMIN,
    )

    response = api_client.create_part_compatibility(
        factories.part_compatibility_payload(
            bundle["part"]["id"],
            bundle["model"]["id"],
            effective_from="2025-01-01T00:00:00Z",
            install_minutes=25,
        ),
        ADMIN,
    )
    abutting = validate_success(response, 201)
    assert abutting["effective_until"] is None, (
        f"the abutting window is open-ended, got {abutting['effective_until']}"
    )
    assert abutting["superseded_by_safety_restriction"] is False, (
        f"a fresh row starts unsuperseded, got "
        f"{abutting['superseded_by_safety_restriction']}"
    )

    rows = get_success_data(
        api_client.list_compatibilities_for_part(bundle["part"]["id"], ADMIN)
    )
    assert len(rows) == 2, (
        f"Expected the incumbent and the abutting row only, got {len(rows)}"
    )
