"""Two-variant derivations: the service rate card and the two point standings."""

from test_helpers import (
    ApiClient,
    PriorityTier,
    RateVariant,
    ServiceOrderStatus,
    ShowStatus,
    SpaceContractStatus,
    assert_service_order,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
B200 = f.booth_payload("B200", 30, 20, location_class="ISLAND",
                       premium_zone="ENTRANCE", max_height_ft=20)


def _signed_freight_setup(client: ApiClient) -> dict:
    """A signed 400 sqft contract on an edition whose advance deadline is known."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    offered = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    env["contract"] = fx.sign_contract(client, offered, 400000)
    return env


def test_advance_freight_order_prices_at_the_discounted_rate(client: ApiClient):
    """
    A six-hundredweight freight order placed on or before the advance deadline.

    "`rate_variant` is decided by the calendar: `ADVANCE` when the date of
    `ordered_at` is on or before the show's `advance_order_deadline`, and `FLOOR`
    when it falls after it."  "Under `ADVANCE`, `line_total_cents` is the product
    of `billable_quantity`, `unit_rate_cents` and the quantity (one hundred minus
    the venue agreement's `advance_order_discount_pct`) divided by one hundred,
    rounded half up to whole cents; no expedite fee applies."

    Design: Difficulty/dual_variant_calc/service_order_advance_versus_floor_variant_divergence
    """
    env = _signed_freight_setup(client)
    show = fx.read_show(client, env["show"]["id"])
    assert show["advance_order_deadline"] == "2027-02-08"

    order = validate_success(
        client.create_service_order(
            env["contract"]["id"],
            f.service_order_payload("MATERIAL_HANDLING", 6, "2027-02-01T09:00:00Z"),
            env["exhibitor_headers"],
        ),
        201,
    )
    assert_service_order(order, ServiceOrderStatus.SUBMITTED, RateVariant.ADVANCE)
    assert order["billable_quantity"] == 6
    assert order["unit_rate_cents"] == 8800
    assert order["line_total_cents"] == 42240


def test_floor_freight_order_adds_the_expedite_fee_after_rounding(client: ApiClient):
    """
    The same six-hundredweight order placed after the advance deadline.

    "Under `FLOOR`, the product of `billable_quantity`, `unit_rate_cents` and one
    point three five is rounded half up first, and a flat seventy-five dollars —
    7500 cents — is added to that rounded figure afterwards."

    Design: Difficulty/dual_variant_calc/service_order_advance_versus_floor_variant_divergence
    """
    env = _signed_freight_setup(client)

    order = validate_success(
        client.create_service_order(
            env["contract"]["id"],
            f.service_order_payload("MATERIAL_HANDLING", 6, "2027-03-02T09:00:00Z"),
            env["exhibitor_headers"],
        ),
        201,
    )
    assert_service_order(order, ServiceOrderStatus.SUBMITTED, RateVariant.FLOOR)
    assert order["unit_rate_cents"] == 8800
    assert order["line_total_cents"] == 78780


def test_identical_freight_orders_diverge_on_the_order_date_alone(client: ApiClient):
    """
    Both variants side by side on one contract, differing only in `ordered_at`.

    "Because the multiplier exceeds one and the fee is strictly positive, the same
    order always costs strictly more on the floor than it would have in advance,
    for every positive rate."

    Design: Difficulty/dual_variant_calc/service_order_advance_versus_floor_variant_divergence
    """
    env = _signed_freight_setup(client)
    headers = env["exhibitor_headers"]

    advance = validate_success(
        client.create_service_order(
            env["contract"]["id"],
            f.service_order_payload("MATERIAL_HANDLING", 6, "2027-02-01T09:00:00Z"),
            headers,
        ),
        201,
    )
    floor = validate_success(
        client.create_service_order(
            env["contract"]["id"],
            f.service_order_payload("MATERIAL_HANDLING", 6, "2027-03-02T09:00:00Z"),
            headers,
        ),
        201,
    )
    assert floor["line_total_cents"] - advance["line_total_cents"] == 36540

    rows, meta = validate_paginated(
        client.list_service_orders(env["contract"]["id"], headers)
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert all(row["status"] == ServiceOrderStatus.SUBMITTED for row in rows)


def test_signing_credits_the_provisional_standing_only(client: ApiClient):
    """
    A signed 1000 sqft contract on a still-open edition.

    "The provisional variant looks at live business. Its contract set is the
    exhibitor's space contracts whose `status` is `OFFERED`, `COUNTERED` or
    `SIGNED` and whose show is in `PLANNING`, `SPACE_SELECTION`, `SELLING` or
    `ON_SITE`."  "The certified variant looks only at history ... Its contract set
    is the exhibitor's space contracts whose `status` is `CLOSED_OUT` and whose
    show is `CLOSED`."

    Design: Difficulty/dual_variant_calc/exhibitor_priority_points_provisional_versus_certified_divergence
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, B200])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    validate_success(
        client.adjust_priority_points(
            exhibitor["id"],
            f.point_adjustment_payload(500, "Loyalty carry-over from the 2026 edition"),
            fx.DIRECTOR_HEADERS,
        )
    )
    booths = env["booth_by_number"]
    offered = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 1000,
        [booths["A100"]["id"], booths["B200"]["id"]],
        premium_placement_requested=True,
    )

    signed = fx.sign_contract(client, offered, 1100000)
    assert signed["points_awarded"] == 20

    row = fx.read_exhibitor(client, exhibitor["id"])
    assert row["space_points_provisional"] == 20
    assert row["provisional_priority_points"] == 520
    assert row["space_points_certified"] == 0
    assert row["certified_priority_points"] == 500
    assert row["priority_tier"] == PriorityTier.SILVER


def test_closing_the_edition_swaps_the_contract_to_the_certified_standing(
    client: ApiClient,
):
    """
    The same contract after the edition closes: the two standings trade places.

    "Because the two variants filter contracts differently, the same exhibitor's
    two standings diverge whenever any of its contracts is still open"  "The
    whole ledger is recomputed on every event that can move a point: a space
    contract signing, cancelling, or closing out at show close".

    Design: Difficulty/dual_variant_calc/exhibitor_priority_points_provisional_versus_certified_divergence
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, B200])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    validate_success(
        client.adjust_priority_points(
            exhibitor["id"],
            f.point_adjustment_payload(500, "Loyalty carry-over from the 2026 edition"),
            fx.DIRECTOR_HEADERS,
        )
    )
    booths = env["booth_by_number"]
    offered = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 1000,
        [booths["A100"]["id"], booths["B200"]["id"]],
        premium_placement_requested=True,
    )
    contract = fx.sign_contract(client, offered, 1100000)

    show_id = env["show"]["id"]
    fx.transition(client, show_id, ShowStatus.SELLING)
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    fx.transition(client, show_id, ShowStatus.CLOSED)

    assert (
        fx.read_contract(client, contract["id"])["status"]
        == SpaceContractStatus.CLOSED_OUT
    )
    row = fx.read_exhibitor(client, exhibitor["id"])
    assert row["provisional_priority_points"] == 500
    assert row["certified_priority_points"] == 520
    assert row["ledger_points"] == 500
