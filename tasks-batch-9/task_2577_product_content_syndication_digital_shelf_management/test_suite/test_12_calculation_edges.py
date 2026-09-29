"""The edges of the five stored calculations: which requirement rows enter the
completeness denominator, which side of a retailer ceiling withholds credit, the
feed fee at its cheapest tier, the penalty band a sixth blocking row selects, and
the projection, health, rank and lift arithmetic that hangs off the crawl log."""
import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_completeness_diagnostic,
    assert_shelf_observation,
    assert_shelf_summary,
    assert_slot_ledger,
)
from test_helpers.constants import CLOCK_BASE
from test_helpers.factories import (
    create_observation_payload,
    create_syndication_job_payload,
    resolve_alert_payload,
)
from test_helpers.fixtures import (
    BIGBOX_DESCRIPTION,
    BIGBOX_TITLE,
    accept_job,
    define_attribute,
    ingest_observation,
    move_clock,
    open_listing,
    pin_revision,
    queue_job,
    read_retailer_version,
    register_product,
    register_retailer,
    reject_job,
    require_attribute,
    set_attribute_value,
    start_revision,
    transmit_job,
    upload_approved_asset,
)
from test_helpers.test_users import (
    make_account_team_headers,
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

SIX_BLOCKING_ROWS = [
    {
        "retailer_error_code": "E-01",
        "attribute_key": "brand",
        "severity": "BLOCKING",
        "message": "brand missing",
    },
    {
        "retailer_error_code": "E-02",
        "attribute_key": "title",
        "severity": "BLOCKING",
        "message": "title casing",
    },
    {
        "retailer_error_code": "E-03",
        "attribute_key": "description",
        "severity": "BLOCKING",
        "message": "description too short",
    },
    {"retailer_error_code": "E-04", "severity": "BLOCKING", "message": "taxonomy node missing"},
    {"retailer_error_code": "E-05", "severity": "BLOCKING", "message": "hero image aspect ratio"},
    {
        "retailer_error_code": "E-06",
        "severity": "BLOCKING",
        "message": "shipping dimensions missing",
    },
]

ONE_BLOCKING_ROW = [
    {
        "retailer_error_code": "E-BRAND-MISSING",
        "attribute_key": "brand",
        "severity": "BLOCKING",
        "message": "brand attribute is required",
    }
]


def _build_filter_world():
    """FilterMart declares one REQUIRED row, one RECOMMENDED row and one OPTIONAL
    row, and the product populates the OPTIONAL key while leaving the RECOMMENDED
    one empty."""
    move_clock(CLOCK_BASE)
    define_attribute("title", "STRING", "CORE", 200, 40.00, True)
    define_attribute("description", "STRING", "MARKETING", 500, 30.00, False)
    define_attribute("color", "STRING", "VARIANT", 60, 25.00, False)
    retailer = register_retailer("FilterMart", "RETF", min_image_count=1)
    require_attribute(retailer["id"], "title", "REQUIRED")
    require_attribute(retailer["id"], "description", "RECOMMENDED")
    require_attribute(retailer["id"], "color", "OPTIONAL")
    product = register_product("SKU-F-1", "00012345678943")
    listing = open_listing(product["id"], retailer["id"], "acct_filter_1")
    revision = start_revision(product["id"], 1)
    set_attribute_value(revision["id"], "title", BIGBOX_TITLE)
    set_attribute_value(revision["id"], "color", "Graphite")
    return {"retailer": retailer, "product": product, "listing": listing, "revision": revision}


def _build_override_world():
    """OverrideMart carries a 40-character ceiling on description, tighter than the
    taxonomy's own 500, and the pinned revision's description is 51 characters."""
    move_clock(CLOCK_BASE)
    define_attribute("title", "STRING", "CORE", 200, 40.00, True)
    define_attribute("description", "STRING", "MARKETING", 500, 30.00, False)
    retailer = register_retailer("OverrideMart", "RETO", min_image_count=1)
    require_attribute(retailer["id"], "title", "REQUIRED")
    require_attribute(retailer["id"], "description", "REQUIRED", max_chars_override=40)
    product = register_product("SKU-O-1", "00012345678950")
    listing = open_listing(product["id"], retailer["id"], "acct_override_1")
    upload_approved_asset(product["id"], "HERO_IMAGE", "s3://brand/o/hero.jpg", retailer["id"])
    revision = start_revision(product["id"], 1)
    set_attribute_value(revision["id"], "title", BIGBOX_TITLE)
    set_attribute_value(revision["id"], "description", BIGBOX_DESCRIPTION)
    pin_revision(product["id"], retailer["id"], revision["id"], "pin revision 1 on OverrideMart")
    return {"retailer": retailer, "product": product, "listing": listing, "revision": revision}


def _take_simplemart_live(world):
    """Two slots queued into a far window, transmitted and accepted, which is what
    admits the listing to the product's health input set."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        2,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    accept_job(job["id"], world["retailer"]["id"])
    return job


def _shelf_summary(product_id, params=None):
    return validate_success(
        api_client.get_shelf_summary(product_id, make_account_team_headers(), params=params)
    )


def test_an_optional_requirement_row_leaves_both_numerator_and_denominator(clock_at_base):
    """The populated OPTIONAL colour key cannot raise the score: it is discarded from
    the scoring set, so the denominator is the REQUIRED and RECOMMENDED weights plus
    the fixed image weight, and the empty RECOMMENDED description is the only thing
    holding the declared score down.

    PRD 3.4: "Both variants begin by assembling the scoring set: every requirement row belonging to the listing's retailer whose `requirement_level` is `REQUIRED` or `RECOMMENDED`, with `OPTIONAL` rows discarded."
    Design: Corner/calculations/optional_requirement_rows_are_excluded_from_numerator_and_denominator
    """
    world = _build_filter_world()

    diagnostic = validate_success(
        api_client.get_listing_completeness(
            world["listing"]["id"], make_content_author_headers()
        )
    )
    assert_completeness_diagnostic(diagnostic)
    assert float(diagnostic["requirement_weight_total"]) == pytest.approx(90.00, abs=0.01)
    assert float(diagnostic["declared_image_component"]) == pytest.approx(20.00, abs=0.01)
    assert float(diagnostic["declared_score"]) == pytest.approx(66.67, abs=0.01)
    assert float(diagnostic["certified_score"]) == pytest.approx(0.00, abs=0.01)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["completeness_score_declared"]) == pytest.approx(66.67, abs=0.01)


def test_the_certified_variant_withholds_credit_under_a_tighter_retailer_ceiling(
    clock_at_base,
):
    """The 51-character description was perfectly legal to write against a taxonomy
    ceiling of 500, but OverrideMart only certifies 40 characters, so the certified
    view withholds the whole description weight and names the key in over_limit_keys
    while the declared view — which never applies an override — reads a clean 100.00.

    PRD 3.4: "A requirement row earns credit only when the pinned revision carries an attribute value on that key with `char_count` at least 1, **and** that row's `type_valid` is true, **and** its `char_count` is at most the effective retailer ceiling for the key — the requirement row's `max_chars_override` when that is present, and the taxonomy attribute's `max_chars` otherwise."
    Design: Corner/calculations/certified_variant_withholds_credit_when_the_retailer_ceiling_is_tighter
    """
    world = _build_override_world()
    assert len(BIGBOX_DESCRIPTION) == 51

    diagnostic = validate_success(
        api_client.get_listing_completeness(
            world["listing"]["id"], make_content_author_headers()
        )
    )
    assert float(diagnostic["declared_score"]) == pytest.approx(100.00, abs=0.01)
    assert float(diagnostic["certified_score"]) == pytest.approx(66.67, abs=0.01)
    assert diagnostic["over_limit_keys"] == ["description"]
    assert float(diagnostic["certified_image_component"]) == pytest.approx(20.00, abs=0.01)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["completeness_score_certified"]) == pytest.approx(66.67, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(40.00, abs=0.01)

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "PINNED"


def test_a_single_slot_job_is_priced_at_exactly_the_per_slot_rate(bigbox_world):
    """One slot puts the subtotal below the first discount boundary and the window
    opens ten days out, so no discount and no surcharge apply and the fee is the bare
    per-slot rate; a three-slot job in a disjoint window then crosses into the 5
    percent tier.

    PRD 3.6: "First, the subtotal in cents is the per-slot rate of 2500 cents — that is, 25 dollars per feed slot — multiplied by `slot_count`."
    Design: Corner/calculations/per_sku_rate_constant_applied_with_no_discount_and_no_rush
    """
    world = bigbox_world
    first = validate_success(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                1,
                "2026-08-20T00:00:00Z",
                "2026-08-21T00:00:00Z",
                read_retailer_version(world["retailer"]["id"]),
            ),
            make_syndication_operator_headers(),
        ),
        201,
    )
    assert first["service_fee_cents"] == 2500
    assert float(first["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)

    second = validate_success(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                3,
                "2026-08-25T00:00:00Z",
                "2026-08-26T00:00:00Z",
                read_retailer_version(world["retailer"]["id"]),
            ),
            make_syndication_operator_headers(),
        ),
        201,
    )
    assert second["service_fee_cents"] == 7125

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 4)
    assert retailer["version"] == 3


def test_a_sixth_blocking_row_selects_the_heaviest_penalty_tier(bigbox_world):
    """Six open blocking complaints arrive in one response, so the readiness penalty
    jumps past the 12-point band into the 25-point one and the listing presents
    26.00 rather than the 39.00 a three-to-five count would have cost it.

    PRD 3.7: "It selects the readiness penalty described in §3.4 in four bands: no penalty at all when the count is zero, 5 points when the count is 1 or 2, 12 points when the count is 3, 4 or 5, and 25 points once the count reaches 6 or more."
    Design: Corner/calculations/readiness_penalty_selects_the_six_row_tier_not_the_three_to_five_tier
    """
    world = bigbox_world
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        "2026-08-15T00:00:00Z",
        "2026-08-16T00:00:00Z",
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    reject_job(job["id"], world["retailer"]["id"], SIX_BLOCKING_ROWS)

    _rows, meta = validate_paginated(
        api_client.list_rejection_errors(
            job["id"],
            make_syndication_operator_headers(),
            params={"severity": "BLOCKING", "state": "OPEN"},
        )
    )
    assert meta["total_count"] == 6

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["open_blocking_error_count"] == 6
    assert float(listing["readiness_score"]) == pytest.approx(26.00, abs=0.01)
    assert listing["syndication_state"] == "ERROR_HOLD"

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 0)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(20.00, abs=0.01)


def test_a_late_arriving_observation_does_not_move_the_projection(simplemart_world):
    """The backfilled crawl is older than the one already on file, so the listing's
    snapshot keeps the newer row's rank and accuracy even though the older row is
    stored and readable — insertion order does not decide the projection.

    PRD 3.9: "The consequence for backfill is deliberate: a late-arriving observation whose `observed_at` is older than the current latest updates nothing at all on the listing, yet it still participates fully in the conversion-lift analysis below."
    Design: Corner/calculations/late_arriving_observation_does_not_move_the_listing_projection
    """
    world = simplemart_world
    _take_simplemart_live(world)
    ingest_observation(
        world["listing"]["id"],
        "2026-08-12T00:00:00Z",
        in_stock=True,
        content_accuracy_pct=96.00,
        rating_avg=4.50,
        rating_count=120,
        unauthorized_seller_count=0,
        conversion_rate_pct=3.00,
        units_sold=40,
        search_rank=4,
    )

    backfill = validate_success(
        api_client.create_observation(
            world["listing"]["id"],
            create_observation_payload(
                observed_at="2026-08-11T00:00:00Z",
                in_stock=True,
                content_accuracy_pct=50.00,
                rating_avg=2.00,
                rating_count=10,
                unauthorized_seller_count=0,
                conversion_rate_pct=1.00,
                units_sold=5,
                search_rank=40,
            ),
            make_shelf_admin_headers(),
        ),
        201,
    )
    assert_shelf_observation(backfill)

    _rows, meta = validate_paginated(
        api_client.list_observations(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert meta["total_count"] == 2

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["search_rank_latest"] == 4
    assert float(listing["content_accuracy_pct"]) == pytest.approx(96.00, abs=0.01)
    assert float(listing["rating_avg"]) == pytest.approx(4.50, abs=0.01)
    assert listing["in_stock"] is True
    assert listing["shelf_state"] == "OK"
    assert float(listing["readiness_score"]) == pytest.approx(98.40, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(93.45, abs=0.01)


def test_only_the_live_listing_contributes_to_the_health_index(simplemart_world):
    """The product is carried by two retailers but only the accepted-feed listing is
    inside the health input set, so the index equals that single subscore instead of
    being halved by the never-syndicated one, and the breakdown carries one row.

    PRD 3.9: "The product's `shelf_health_index` aggregates only those of its listings whose `syndication_state` is `LIVE` or `ERROR_HOLD`; `NOT_SYNDICATED` and `PENDING` listings are excluded, and when no listing qualifies the index is 0.00 and the per-retailer breakdown is empty."
    Design: Corner/calculations/shelf_health_index_counts_only_live_and_error_hold_listings
    """
    world = simplemart_world
    _take_simplemart_live(world)

    second_retailer = register_retailer("MaxMart", "RETX", min_image_count=1)
    require_attribute(second_retailer["id"], "title", "REQUIRED")
    second_listing = open_listing(
        world["product"]["id"], second_retailer["id"], "acct_maxmart_1"
    )

    ingest_observation(
        world["listing"]["id"],
        "2026-08-12T00:00:00Z",
        in_stock=True,
        content_accuracy_pct=96.00,
        rating_avg=4.50,
        rating_count=120,
        unauthorized_seller_count=0,
        conversion_rate_pct=3.00,
        units_sold=40,
        search_rank=3,
    )

    summary = _shelf_summary(world["product"]["id"])
    assert_shelf_summary(summary)
    assert summary["qualifying_listing_count"] == 1
    assert len(summary["retailer_subscores"]) == 1
    assert float(summary["shelf_health_index"]) == pytest.approx(94.70, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(94.70, abs=0.01)

    excluded = validate_success(
        api_client.get_retailer_listing(second_listing["id"], make_shelf_admin_headers())
    )
    assert excluded["syndication_state"] == "NOT_SYNDICATED"


def test_an_empty_base_group_makes_the_lift_fall_back_to_zero(simplemart_world):
    """Both crawls landed after the pin and both are above the quality threshold, so
    under either variant every row is in HIGH and BASE is empty: the lift is the
    documented 0.00 fallback rather than the HIGH group's own mean.

    PRD 3.9: "If either group is empty the lift is 0.00."
    Design: Corner/calculations/conversion_lift_falls_back_to_zero_when_the_base_group_is_empty
    """
    world = simplemart_world
    _take_simplemart_live(world)
    ingest_observation(
        world["listing"]["id"],
        "2026-08-12T00:00:00Z",
        content_accuracy_pct=94.00,
        conversion_rate_pct=2.00,
        rating_avg=4.50,
        rating_count=90,
        units_sold=20,
        search_rank=3,
    )
    ingest_observation(
        world["listing"]["id"],
        "2026-08-14T00:00:00Z",
        content_accuracy_pct=96.00,
        conversion_rate_pct=3.00,
        rating_avg=4.50,
        rating_count=100,
        units_sold=30,
        search_rank=3,
    )

    default_view = _shelf_summary(world["product"]["id"])
    assert default_view["lift_variant"] == "post_pin_window"
    assert default_view["high_group_size"] == 2
    assert default_view["base_group_size"] == 0
    assert float(default_view["conversion_lift_pct"]) == pytest.approx(0.00, abs=0.01)

    quality_view = _shelf_summary(
        world["product"]["id"], params={"lift_variant": "quality_split"}
    )
    assert quality_view["high_group_size"] == 2
    assert quality_view["base_group_size"] == 0
    assert float(quality_view["conversion_lift_pct"]) == pytest.approx(0.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["conversion_lift_pct"]) == pytest.approx(0.00, abs=0.01)


def test_a_rank_past_position_twenty_one_floors_the_rank_component_at_zero(simplemart_world):
    """Rank 25 would compute to a negative rank term, and the clamp turns it into
    zero rather than letting it drag the other three components down: a listing
    perfect on accuracy, availability and rating still lands on exactly 75.00.

    PRD 3.9: "Its rank component is 0 when `search_rank_latest` is null, and otherwise 100 reduced by 5 points for every position below the first — so rank 1 scores 100, rank 6 scores 75, rank 11 scores 50 — with the result clamped to the range 0 to 100, meaning rank 21 and everything worse scores 0."
    Design: Corner/calculations/rank_score_floors_at_zero_for_a_rank_past_position_twenty_one
    """
    world = simplemart_world
    _take_simplemart_live(world)

    validate_success(
        api_client.create_observation(
            world["listing"]["id"],
            create_observation_payload(
                observed_at="2026-08-14T00:00:00Z",
                in_stock=True,
                content_accuracy_pct=100.00,
                rating_avg=5.00,
                rating_count=400,
                unauthorized_seller_count=0,
                conversion_rate_pct=4.00,
                units_sold=90,
                search_rank=25,
            ),
            make_shelf_admin_headers(),
        ),
        201,
    )

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["search_rank_latest"] == 25
    assert float(listing["readiness_score"]) == pytest.approx(100.00, abs=0.01)

    summary = _shelf_summary(world["product"]["id"])
    assert float(summary["shelf_health_index"]) == pytest.approx(75.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(75.00, abs=0.01)


def test_the_governance_flag_precedence_prefers_listing_risk(bigbox_world):
    """With a health alert and an unauthorized-seller alert both open the flag reads
    LISTING_RISK; resolving only the unauthorized row drops it to CONTENT_AT_RISK
    rather than to NONE, because the precedence is read top to bottom over whatever
    is still open — and neither shelf nor syndication dimension moves.

    PRD 3.9: "Its `governance_flag` is derived from that same set under a pinned precedence, evaluated top to bottom: it is `LISTING_RISK` when any alert in the set has `alert_type` `UNAUTHORIZED_LISTING`; otherwise `CONTENT_AT_RISK` when the count is 1 or more; otherwise `NONE`."
    Design: Corner/calculations/governance_flag_precedence_prefers_listing_risk_over_content_at_risk
    """
    world = bigbox_world
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        "2026-08-15T00:00:00Z",
        "2026-08-16T00:00:00Z",
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    reject_job(job["id"], world["retailer"]["id"], ONE_BLOCKING_ROW)
    ingest_observation(
        world["listing"]["id"],
        "2026-08-12T00:00:00Z",
        in_stock=True,
        content_accuracy_pct=96.00,
        rating_avg=4.50,
        rating_count=120,
        unauthorized_seller_count=1,
        conversion_rate_pct=3.00,
        units_sold=40,
        search_rank=3,
    )

    before = validate_success(
        api_client.get_product(world["product"]["id"], make_account_team_headers())
    )
    assert before["open_alert_count"] == 2
    assert before["governance_flag"] == "LISTING_RISK"

    alerts, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(),
            params={
                "retailer_listing_id": world["listing"]["id"],
                "alert_type": "UNAUTHORIZED_LISTING",
            },
        )
    )
    assert meta["total_count"] == 1

    resolved = validate_success(
        api_client.resolve_shelf_alert(
            alerts[0]["id"],
            resolve_alert_payload("unauthorized seller delisted by the account team"),
            make_account_team_headers("acct_bigbox_1"),
        )
    )
    assert resolved["state"] == "RESOLVED"

    after = validate_success(
        api_client.get_product(world["product"]["id"], make_account_team_headers())
    )
    assert after["open_alert_count"] == 1
    assert after["governance_flag"] == "CONTENT_AT_RISK"

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["shelf_state"] == "UNAUTHORIZED"
    assert listing["syndication_state"] == "ERROR_HOLD"
