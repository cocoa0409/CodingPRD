"""Opaque bundle assembly, tiered discounting and the floor-plus-remainder allocation."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers.assertions import (
    assert_discount_allocation_exact,
    assert_instant_equals,
    assert_offer_money,
    assert_pct,
)
from test_helpers.fixtures import (
    DEFAULT_INSTANT,
    two_leg_package,
)
from test_helpers.test_users import (
    COMMERCIAL_MANAGER,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
)

# The two published legs of the 341113-cent bundle that earns the nine percent tier.
NINE_PCT_HOTEL_NET = 185053
NINE_PCT_HOTEL_TAX = 0.07


def _nine_percent_package(b, **overrides):
    return two_leg_package(
        b,
        hotel_net_rate_cents=NINE_PCT_HOTEL_NET,
        hotel_tax_fee_pct=NINE_PCT_HOTEL_TAX,
        **overrides,
    )


def test_package_pricing_floors_the_discount_then_hands_out_the_remainder_cent(b, client):
    """The package discount floors at 30700 and the odd cent goes to the larger fraction.

    PRD 3.7: "`discount_cents` is the subtotal multiplied by `discount_pct`,
    **rounded down** to a whole cent at the package level" and "One extra cent is
    handed to each of the components with the largest retained fractional parts".

    Design: Difficulty/combinatorial_formula/package_discount_floor_then_largest_remainder_allocation
    """
    ctx = _nine_percent_package(b)

    priced = b.price_package(ctx.package["id"])

    assert priced["components_subtotal_cents"] == 341113
    assert_pct(priced["discount_pct"], 0.09)
    assert priced["discount_cents"] == 30700
    assert priced["package_total_cents"] == 310413
    assert priced["status"] == "PRICED"
    assert priced["component_count"] == 2

    hotel = b.read_component(ctx.hotel_component["id"])
    air = b.read_component(ctx.air_component["id"])
    assert hotel["display_total_snapshot_cents"] == 198007
    assert hotel["discount_alloc_cents"] == 17821
    assert hotel["allocated_cents"] == 180186
    assert air["display_total_snapshot_cents"] == 143106
    assert air["discount_alloc_cents"] == 12879
    assert air["allocated_cents"] == 130227


def test_the_package_allocation_identities_close_over_the_merchant_leg(b, client):
    """The merchant leg grosses up before tax, and both stored identities close exactly.

    PRD 3.7: "the sum of the components' `allocated_cents` equals
    `package_total_cents`, and the sum of their `discount_alloc_cents` equals
    `discount_cents`."

    Design: Difficulty/combinatorial_formula/package_discount_floor_then_largest_remainder_allocation
    """
    ctx = _nine_percent_package(b)

    assert_offer_money(
        ctx.air_offer,
        gross_cents=136291,
        taxes_fees_cents=6815,
        display_total_cents=143106,
        marketplace_margin_cents=16355,
        supplier_payable_cents=119936,
    )

    priced = b.price_package(ctx.package["id"])
    components = b.components_of(ctx.package["id"])

    assert len(components) == 2
    assert_discount_allocation_exact(priced, components)
    assert sum(c["discount_alloc_cents"] for c in components) == 30700
    assert sum(c["allocated_cents"] for c in components) == 310413


def test_a_subtotal_exactly_at_the_three_hundred_thousand_threshold_earns_nine_percent(b, client):
    """The tier threshold is inclusive, so exactly 300000 cents earns nine percent.

    PRD 3.7: "The `discount_pct` is then chosen from four tiers by taking the
    highest tier whose threshold is less than or equal to the subtotal: ... at least
    300,000 cents earns nine percent".

    Design: Difficulty/boundary_precision_check/package_discount_tier_exactly_at_the_300000_threshold
    """
    ctx = two_leg_package(
        b,
        hotel_net_rate_cents=200000,
        hotel_tax_fee_pct=0.0,
        air_net_rate_cents=80000,
        air_tax_fee_pct=0.0,
        air_markup_pct=0.20,
    )
    assert ctx.offer["display_total_cents"] == 200000
    assert_offer_money(
        ctx.air_offer,
        gross_cents=100000,
        taxes_fees_cents=0,
        display_total_cents=100000,
        marketplace_margin_cents=20000,
    )

    priced = b.price_package(ctx.package["id"])

    assert priced["components_subtotal_cents"] == 300000
    assert_pct(priced["discount_pct"], 0.09)
    assert priced["discount_cents"] == 27000
    assert priced["package_total_cents"] == 273000


def test_an_exact_tier_boundary_allocates_without_any_remainder_cent(b, client):
    """Both component shares are whole cents, so no remainder cent is handed out.

    PRD 3.7: "the shortfall as the package-level `discount_cents` minus the sum of
    all the component floors; that shortfall is at least zero and strictly less than
    the number of components."

    Design: Difficulty/boundary_precision_check/package_discount_tier_exactly_at_the_300000_threshold
    """
    ctx = two_leg_package(
        b,
        hotel_net_rate_cents=200000,
        hotel_tax_fee_pct=0.0,
        air_net_rate_cents=80000,
        air_tax_fee_pct=0.0,
        air_markup_pct=0.20,
    )

    priced = b.price_package(ctx.package["id"])
    hotel = b.read_component(ctx.hotel_component["id"])
    air = b.read_component(ctx.air_component["id"])

    assert hotel["discount_alloc_cents"] == 18000
    assert hotel["allocated_cents"] == 182000
    assert air["discount_alloc_cents"] == 9000
    assert air["allocated_cents"] == 91000
    assert_discount_allocation_exact(priced, [hotel, air])


def test_suppressing_a_leg_de_prices_the_package_it_belongs_to(b, client):
    """Suppression walks straight through to the priced bundle and clears its money.

    PRD 3.4: "every `PRICED` package holding it returns to `DRAFT` with its frozen
    pricing cleared."

    Design: Difficulty/cross_entity_state_dependency/package_price_blocked_when_a_component_offer_is_suppressed
    """
    ctx = _nine_percent_package(b, price=True)
    assert ctx.package["package_total_cents"] == 310413

    suppressed = validate_success(
        client.suppress_offer(
            ctx.air_offer["id"],
            {"suppression_reason": "schedule change withdrawn by the airline"},
            COMPLIANCE_OFFICER,
        )
    )
    assert suppressed["status"] == "SUPPRESSED"
    assert suppressed["suppression_reason"] == "schedule change withdrawn by the airline"

    package = b.read_package(ctx.package["id"])
    assert package["status"] == "DRAFT"
    assert package["priced_at"] is None
    assert package["package_total_cents"] is None
    assert package["discount_cents"] is None


def test_repricing_a_package_whose_leg_is_no_longer_live_is_rejected(b, client):
    """With a fresh token the refusal is about the dead leg, not about concurrency.

    PRD 3.7: pricing "requires every component offer to still be `LIVE` with a
    `travel_date` equal to the package's, otherwise `ERR_COMPONENT_NOT_LIVE`."

    Design: Difficulty/cross_entity_state_dependency/package_price_blocked_when_a_component_offer_is_suppressed
    """
    ctx = _nine_percent_package(b, price=True)
    b.suppress_offer(ctx.air_offer["id"], reason="schedule change withdrawn by the airline")

    current_version = b.read_package(ctx.package["id"])["version"]
    refused = client.price_package(
        ctx.package["id"],
        {"expected_package_version": current_version},
        COMMERCIAL_MANAGER,
    )
    body = validate_error(refused, E.ERR_COMPONENT_NOT_LIVE, 422)
    assert body["error_id"] != E.ERR_STALE_VERSION

    package = b.read_package(ctx.package["id"])
    assert package["status"] == "DRAFT"
    assert package["package_total_cents"] is None


def test_package_pricing_applies_the_six_percent_tier(b, client):
    """A 167346-cent subtotal earns six percent and both legs keep whole-cent shares.

    PRD 3.7: "at least 100,000 cents earns six percent" and "`priced_at` is stamped
    from the logical clock."

    Design: Corner/calculations/package_pricing_applies_the_six_percent_tier_and_floor_allocation
    """
    ctx = two_leg_package(b)

    priced = b.price_package(ctx.package["id"])

    assert priced["components_subtotal_cents"] == 167346
    assert_pct(priced["discount_pct"], 0.06)
    assert priced["discount_cents"] == 10040
    assert priced["package_total_cents"] == 157306
    assert priced["status"] == "PRICED"
    assert_instant_equals(priced["priced_at"], DEFAULT_INSTANT)

    hotel = b.read_component(ctx.hotel_component["id"])
    air = b.read_component(ctx.air_component["id"])
    assert hotel["discount_alloc_cents"] == 1454
    assert hotel["allocated_cents"] == 22786
    assert air["discount_alloc_cents"] == 8586
    assert air["allocated_cents"] == 134520
    assert_discount_allocation_exact(priced, [hotel, air])


def test_a_package_component_links_offers_from_two_different_suppliers(b, client):
    """Each leg snapshots its own offer's display total and only counts the package up.

    PRD 3.7: "Attachment snapshots the offer's `display_total_cents` into the
    component's `display_total_snapshot_cents`, increments the package's
    `component_count` by 1".

    Design: Corner/entities/package_component_junction_links_offers_from_two_suppliers
    """
    ctx = two_leg_package(b)

    assert ctx.hotel_component["offer_id"] == ctx.offer["id"]
    assert ctx.hotel_component["component_type"] == "HOTEL"
    assert ctx.hotel_component["display_total_snapshot_cents"] == 24240
    assert ctx.air_component["offer_id"] == ctx.air_offer["id"]
    assert ctx.air_component["component_type"] == "AIR"
    assert ctx.air_component["display_total_snapshot_cents"] == 143106
    assert ctx.supplier["id"] != ctx.air_supplier["id"]

    package = b.read_package(ctx.package["id"])
    assert package["component_count"] == 2
    assert package["status"] == "DRAFT"

    _rows, by_package = validate_paginated(
        client.list_package_components(
            PLATFORM_ADMIN, params={"package_id": ctx.package["id"]}
        )
    )
    assert by_package["total_count"] == 2

    by_offer_rows, by_offer = validate_paginated(
        client.list_package_components(
            PLATFORM_ADMIN, params={"offer_id": ctx.air_offer["id"]}
        )
    )
    assert by_offer["total_count"] == 1
    assert by_offer_rows[0]["id"] == ctx.air_component["id"]


def test_pricing_a_package_with_a_stale_version_token_is_rejected(b, client):
    """Attaching the second leg invalidates the token read before it.

    PRD 2.7: "If that value does not equal the package's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)", and PRD 3.7 has
    attachment increment "the package's `version` by 1".

    Design: Corner/cross_cutting_layers/package_price_with_a_stale_expected_package_version_is_rejected
    """
    ctx = two_leg_package(b)
    # The token as it stood after the hotel leg was attached but before the air leg.
    stale_version = ctx.package["version"] + 1

    refused = client.price_package(
        ctx.package["id"], {"expected_package_version": stale_version}, COMMERCIAL_MANAGER
    )
    validate_error(refused, E.ERR_STALE_VERSION, 412)

    after = b.read_package(ctx.package["id"])
    assert after["status"] == "DRAFT"
    assert after["package_total_cents"] is None
    assert after["discount_cents"] is None
    assert after["priced_at"] is None
    assert after["version"] == stale_version + 1

    priced = validate_success(
        client.price_package(
            ctx.package["id"],
            {"expected_package_version": after["version"]},
            COMMERCIAL_MANAGER,
        )
    )
    assert priced["status"] == "PRICED"
    assert priced["components_subtotal_cents"] == 167346
    assert priced["discount_cents"] == 10040
    assert priced["package_total_cents"] == 157306


def test_publishing_an_opaque_package_with_names_revealed_is_rejected(b, client):
    """Opacity is absolute, and the same call succeeds once the reveal is dropped.

    PRD 3.7: "when the package's `opaque` flag is true, `reveal_supplier_names` must
    be false, and an attempt to publish an opaque package with supplier names
    revealed is rejected with `ERR_OPAQUE_DISCLOSURE_FORBIDDEN`."

    Design: Corner/errors/publishing_an_opaque_package_with_supplier_names_revealed_is_rejected
    """
    ctx = two_leg_package(b, price=True)
    assert ctx.package["package_total_cents"] == 157306

    refused = client.publish_package(
        ctx.package["id"],
        {"reveal_supplier_names": True, "note": "reveal for transparency"},
        COMMERCIAL_MANAGER,
    )
    validate_error(refused, E.ERR_OPAQUE_DISCLOSURE_FORBIDDEN, 422)
    assert b.read_package(ctx.package["id"])["status"] == "PRICED"

    published = validate_success(
        client.publish_package(
            ctx.package["id"], {"note": "keep it opaque"}, COMMERCIAL_MANAGER
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["reveal_supplier_names"] is False
    assert published["package_total_cents"] == 157306
    assert published["opaque"] is True


def test_pricing_and_its_cascade_are_visible_without_any_settling_delay(b, client):
    """Both the write response and the next read show the committed state at once.

    PRD 2.11: "each hop must be applied in full", and PRD 3.7 stores the pricing on
    the row itself, where "`priced_at` is stamped from the logical clock".

    Design: Corner/consistency_model/pricing_and_cascade_results_are_visible_in_the_same_response
    """
    ctx = two_leg_package(b)

    priced = validate_success(
        client.price_package(
            ctx.package["id"],
            {"expected_package_version": b.read_package(ctx.package["id"])["version"]},
            COMMERCIAL_MANAGER,
        )
    )
    assert priced["package_total_cents"] == 157306
    assert_pct(priced["discount_pct"], 0.06)
    assert_instant_equals(priced["priced_at"], DEFAULT_INSTANT)

    read_back = b.read_package(ctx.package["id"])
    for field in (
        "components_subtotal_cents",
        "discount_pct",
        "discount_cents",
        "package_total_cents",
        "priced_at",
        "status",
    ):
        assert read_back[field] == priced[field], field

    suppressed = validate_success(
        client.suppress_offer(
            ctx.offer["id"], {"suppression_reason": "content audit"}, COMPLIANCE_OFFICER
        )
    )
    assert suppressed["status"] == "SUPPRESSED"

    after = b.read_package(ctx.package["id"])
    assert after["status"] == "DRAFT"
    assert after["package_total_cents"] is None
    assert after["discount_cents"] is None
    assert after["priced_at"] is None
