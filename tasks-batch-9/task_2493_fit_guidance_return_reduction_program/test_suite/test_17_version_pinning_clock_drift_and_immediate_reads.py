"""Layered scenarios: pinned versions, a strike that ages out, and same-cycle reads.

The first three tests are about writes that name the version they believe a parent row
holds, and what happens when another accepted write moved that version first — once on
an item and once on a shopper profile.  The last three are about time and immediacy:
a strike that nothing changed but that the checkpoint no longer counts because the
clock moved past its trailing window, and reviews that are visible in the item's
counters on the very next read.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    create_return_policy_override_payload,
    create_size_chart_mapping_payload,
    is_iso8601_timestamp,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    size_label_pair,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"

STRAIGHT_PAIRS = [size_label_pair("S", "S"), size_label_pair("M", "M")]

TOPS_THIRTY_DAY_POLICY = {
    "window_days": 30,
    "restocking_applies": True,
    "non_refundable_shipping": False,
    "effective_from": "2026-01-01T00:00:00Z",
}

DELIVERED_LINE = {
    "size_label": "M",
    "quantity": 1,
    "unit_price_cents": 2295,
    "shipping_allocated_cents": 0,
    "delivered_at": "2026-05-20T00:00:00Z",
}


def _build_item_whose_version_moved_under_the_analyst(api: ApiClient) -> dict:
    """An item ready to be mapped, whose version is read and then moved by an
    unrelated product-page write before the mapping is attempted."""
    built = fx.setup_verified_spec(api, SCENARIO_START)
    built["chart"] = fx.setup_standardized_chart(
        api, chart_code="STD-TOPS-X1", category_code="TOPS"
    )
    built["stale_version"] = fx.read_item(api, built["item"]["id"])["version"]
    built["item_after_pdp"] = fx.enhance_pdp(api, built["item"]["id"])
    return built


def test_a_product_page_write_stales_the_version_the_mapping_pinned(api):
    """PRD §2.9: "**Stale parent version.** `expected_item_version` equals the
    `CatalogItem`'s current `version` on mapping creation, and
    `expected_customer_profile_version` equals the `CustomerProfile`'s current `version`
    on override creation, otherwise `ERR_STALE_ITEM_VERSION` or
    `ERR_STALE_CUSTOMER_PROFILE_VERSION` (412)."  The mapping body is otherwise perfect
    — a standardized chart of the right category and two pairs naming labels the
    verified specification really declares — and the intervening write touched only the
    product page, yet the pin is compared against the item as a whole, so the readiness
    axis does not move and no mapping row is written at all.

    Design: Corner/cross_cutting_complexity_layers/mapping_creation_with_a_stale_expected_item_version_returns_412
    """
    built = _build_item_whose_version_moved_under_the_analyst(api)
    assert built["stale_version"] == 2
    assert built["item_after_pdp"]["version"] == 3

    response = api.create_size_chart_mapping(
        create_size_chart_mapping_payload(
            built["item"]["id"],
            built["chart"]["id"],
            built["stale_version"],
            size_label_pairs=[dict(pair) for pair in STRAIGHT_PAIRS],
        ),
        make_fit_analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_STALE_ITEM_VERSION.value, 412)

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "UNVERIFIED"
    assert item["version"] == 3

    _, meta = validate_paginated(
        api.list_size_chart_mappings(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def test_re_reading_the_item_lets_the_identical_mapping_through(api):
    """PRD §3.3: "In every case the item's `version` increments by 1 and its
    `listing_status` is untouched."  Nothing about the mapping needs to change after the
    refusal — only the version it names — and the accepted write then bumps the item a
    second time, which shows the version advances on the mapping write as well as on the
    product-page write that staled it, leaving the item with exactly one mapping that has
    superseded nothing.

    Design: Corner/cross_cutting_complexity_layers/mapping_creation_with_a_stale_expected_item_version_returns_412
    """
    built = _build_item_whose_version_moved_under_the_analyst(api)
    fresh_version = fx.read_item(api, built["item"]["id"])["version"]
    assert fresh_version == 3

    mapping = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        fresh_version,
        size_label_pairs=[dict(pair) for pair in STRAIGHT_PAIRS],
    )
    assert mapping["status"] == "ACTIVE"
    assert mapping["coverage_bp"] == 10000
    assert mapping["superseded_reason"] is None

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "CHART_MAPPED"
    assert item["version"] == 4
    assert item["listing_status"] == "LISTED"

    rows, meta = validate_paginated(
        api.list_size_chart_mappings(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [mapping["id"]]


def test_a_spent_profile_version_cannot_author_a_second_override(api):
    """PRD §3.7: "A customer override is authored against one shopper's profile; the row
    is stamped with `scope` `CUSTOMER_OVERRIDE`, its `customer_profile_id` is set to the
    profile it was authored under, and creating it increments that `CustomerProfile`'s
    `version` by 1 — which is exactly why the override write demands
    `expected_customer_profile_version` per §2.7."  The second override governs a
    different category, so it collides with nothing the first one covers; what refuses it
    is purely the version the first write consumed, and re-reading the profile is enough
    to get it accepted.

    Design: Corner/cross_cutting_complexity_layers/override_creation_with_a_stale_expected_customer_profile_version_returns_412
    """
    fx.set_clock(api, SCENARIO_START)
    customer = fx.create_customer(api, email="shopper-x2@example.com")

    opening = fx.read_customer(api, customer["id"])
    assert opening["version"] == 1
    assert opening["tier"] == "STANDARD"
    assert opening["policy_class"] == "STANDARD_WINDOW"

    tops = fx.create_override(
        api,
        customer["id"],
        opening["version"],
        category_code="TOPS",
        window_days=45,
        restocking_applies=False,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    assert tops["scope"] == "CUSTOMER_OVERRIDE"
    assert tops["customer_profile_id"] == customer["id"]
    assert tops["window_days"] == 45

    bottoms_payload = create_return_policy_override_payload(
        opening["version"],
        category_code="BOTTOMS",
        window_days=60,
        restocking_applies=False,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    response = api.create_return_policy_override(
        customer["id"], bottoms_payload, make_merch_ops_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_STALE_CUSTOMER_PROFILE_VERSION.value, 412)

    after_first = fx.read_customer(api, customer["id"])
    assert after_first["version"] == 2

    bottoms = fx.create_override(
        api,
        customer["id"],
        after_first["version"],
        category_code="BOTTOMS",
        window_days=60,
        restocking_applies=False,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    assert bottoms["scope"] == "CUSTOMER_OVERRIDE"
    assert bottoms["category_code"] == "BOTTOMS"
    assert bottoms["window_days"] == 60

    _, meta = validate_paginated(
        api.list_return_policies(
            make_merch_ops_admin_headers(),
            {
                "customer_profile_id": customer["id"],
                "scope": "CUSTOMER_OVERRIDE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2

    assert fx.read_customer(api, customer["id"])["version"] == 3


def test_the_checkpoint_ages_a_change_of_mind_strike_out_of_the_window(api):
    """PRD §3.8: "`abuse_strike_count` is narrower: it counts only the shopper's cases
    whose `status` is `RESOLVED_REFUNDED`, whose `reason_family` is `CHANGE_OF_MIND`,
    whose `refund_amount_cents` is strictly greater than 0, and whose `requested_at` is
    **strictly later** than the logical clock less the trailing abuse window of 180
    days."  Nothing about the stored case changes between the two reads — the refunded
    change-of-mind case is still there, and the shopper's lifetime refund total and
    change-of-mind tally still record it — but at the later clock the request instant is
    no longer strictly inside the trailing window, so the shopper's standing improves on
    its own and the checkpoint reports the downgrade it performed.

    Design: Corner/cross_cutting_complexity_layers/ops_run_ages_an_abuse_strike_out_of_the_trailing_window
    """
    built = fx.setup_classified_case(
        api,
        "2026-01-10T00:00:00Z",
        "CHANGE_OF_MIND",
        case_overrides={"requested_reason_code": "CHANGE_OF_MIND"},
        policy_overrides=dict(TOPS_THIRTY_DAY_POLICY),
        customer_overrides={"email": "shopper-x3@example.com"},
        line_overrides={
            "size_label": "M",
            "quantity": 1,
            "unit_price_cents": 2295,
            "shipping_allocated_cents": 0,
            "delivered_at": "2026-01-05T00:00:00Z",
        },
    )
    assert is_iso8601_timestamp(built["case"]["requested_at"])
    assert built["case"]["requested_at"].startswith("2026-01-10T00:00:00")
    assert built["case"]["status"] == "COOLING_OFF"

    resolved = fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")
    assert resolved["status"] == "RESOLVED_REFUNDED"
    assert resolved["restocking_fee_cents"] == 0
    assert resolved["refund_amount_cents"] == 2295
    assert resolved["total_cost_cents"] == 1330

    before = fx.read_customer(api, built["customer"]["id"])
    assert before["abuse_strike_count"] == 1
    assert before["abuse_status"] == "WATCH"
    assert before["policy_class"] == "STANDARD_WINDOW"
    assert before["return_rate_bp"] == 10000

    fx.set_clock(api, "2026-07-10T00:00:00Z")
    checkpoint = fx.run_ops_run(api)
    assert checkpoint["abuse_downgrades"] == 1
    assert checkpoint["items_swept"] == 1
    assert checkpoint["watch_flips"] == 0
    assert checkpoint["chronic_flips"] == 0

    after = fx.read_customer(api, built["customer"]["id"])
    assert after["abuse_strike_count"] == 0
    assert after["abuse_status"] == "CLEAR"
    assert after["policy_class"] == "STANDARD_WINDOW"
    assert after["return_rate_bp"] == 10000
    assert after["refunded_total_cents"] == 2295
    assert after["change_of_mind_count"] == 1

    assert fx.read_case(api, built["case"]["id"])["status"] == "RESOLVED_REFUNDED"


def _build_item_with_a_purchaser_and_a_browser(api: ApiClient) -> dict:
    """A listed item, one shopper who took delivery of it and one who never bought
    it, so the two reviewers differ only in ownership."""
    built = fx.setup_listed_item(api, SCENARIO_START)
    built["purchaser"] = fx.create_customer(api, email="purchaser-p@example.com")
    built["browser"] = fx.create_customer(api, email="browser-q@example.com")
    built["order_line"] = fx.create_order_line(
        api, built["purchaser"]["id"], built["item"]["id"], **DELIVERED_LINE
    )
    built["item_before"] = fx.read_item(api, built["item"]["id"])
    return built


def test_a_purchasers_review_counts_double_the_moment_it_is_written(api):
    """PRD §3.5: "`signal_weight` is 200 when the reviewer actually owns the item — that
    is, when the reviewer has an order line on this item whose `status` is `DELIVERED`,
    `RETURN_IN_PROGRESS`, `RETURNED`, or `KEPT` — and 100 otherwise, so verified
    purchasers count double."  The weight is decided from the reviewer's own delivered
    line at the moment the review is written, and no checkpoint stands between the write
    and the item's counters: the read that immediately follows already shows the doubled
    weight in the pool.

    Design: Corner/consistency_model/immediate_consistency_exposes_the_fit_signal_pool_in_the_same_request_cycle
    """
    built = _build_item_with_a_purchaser_and_a_browser(api)
    assert built["order_line"]["status"] == "DELIVERED"
    assert built["item_before"]["fit_signal_weight_total"] == 0
    assert built["item_before"]["active_fit_feedback_count"] == 0

    review = fx.post_feedback(
        api,
        built["item"]["id"],
        built["purchaser"]["id"],
        purchased_size_label="M",
        fit_verdict="SLIGHTLY_LARGE",
        comment="roomy through the chest",
    )
    assert review["signal_weight"] == 200
    assert review["verdict_offset_centi"] == -50
    assert review["status"] == "ACTIVE"

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_signal_weight_total"] == 200
    assert item["active_fit_feedback_count"] == 1


def test_a_second_reviewers_lighter_signal_lands_in_the_same_read_cycle(api):
    """PRD §3.5: "The row opens with `status` `ACTIVE` and `retract_reason` null, and the
    item's pool grows accordingly: `fit_signal_weight_total` increases by exactly this
    row's `signal_weight` and `active_fit_feedback_count` increases by 1."  The second
    reviewer never bought the garment, so the pool grows by 100 rather than 200 and
    reaches 300 on the read taken straight after the write, with both rows visible to the
    analyst as active in the same cycle.

    Design: Corner/consistency_model/immediate_consistency_exposes_the_fit_signal_pool_in_the_same_request_cycle
    """
    built = _build_item_with_a_purchaser_and_a_browser(api)
    purchaser_review = fx.post_feedback(
        api,
        built["item"]["id"],
        built["purchaser"]["id"],
        purchased_size_label="M",
        fit_verdict="SLIGHTLY_LARGE",
        comment="roomy through the chest",
    )
    assert purchaser_review["signal_weight"] == 200

    browser_review = fx.post_feedback(
        api,
        built["item"]["id"],
        built["browser"]["id"],
        purchased_size_label="M",
        fit_verdict="TRUE_TO_SIZE",
    )
    assert browser_review["signal_weight"] == 100
    assert browser_review["verdict_offset_centi"] == 0
    assert browser_review["status"] == "ACTIVE"
    assert browser_review["retract_reason"] is None

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_signal_weight_total"] == 300
    assert item["active_fit_feedback_count"] == 2

    rows, meta = validate_paginated(
        api.list_fit_feedback(
            make_fit_analyst_headers(),
            {
                "item_id": built["item"]["id"],
                "status": "ACTIVE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["signal_weight"] for row in rows) == [100, 200]
    assert {row["id"] for row in rows} == {
        purchaser_review["id"],
        browser_review["id"],
    }

    stored = validate_success(
        api.get_fit_feedback(purchaser_review["id"], make_merch_ops_admin_headers())
    )
    assert stored["status"] == "ACTIVE"
