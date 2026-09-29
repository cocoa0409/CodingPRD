"""The two completeness variants and the two conversion-lift variants."""
import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_completeness_diagnostic, assert_retailer_listing
from test_helpers.test_users import make_content_author_headers, make_shelf_admin_headers


def test_declared_and_certified_completeness_diverge_on_one_listing(mega_world):
    """The same content, scored under the two inclusion sets, disagrees by 25.92
    points: the declared view reads the latest revision with presence-only credit
    and the claimed image count, the certified view reads only the pinned revision
    under the retailer's character overrides and the approved asset count.

    PRD 3.4: "The heart of the platform is that the same content is scored twice, against the same retailer requirement set but with two different inclusion tests."
    Design: Difficulty/dual_variant_calc/completeness_declared_vs_certified_diverge_on_same_listing
    """
    data = validate_success(
        api_client.get_listing_completeness(
            mega_world["listing"]["id"], make_content_author_headers()
        )
    )
    assert_completeness_diagnostic(data)

    assert float(data["declared_score"]) == pytest.approx(92.59, abs=0.01)
    assert float(data["certified_score"]) == pytest.approx(66.67, abs=0.01)
    assert float(data["declared_score"]) - float(data["certified_score"]) == pytest.approx(
        25.92, abs=0.01
    )
    assert data["declared_source_content_version_id"] == mega_world["revision_2"]["id"]
    assert data["certified_source_content_version_id"] == mega_world["revision_1"]["id"]
    assert float(data["requirement_weight_total"]) == pytest.approx(90.00, abs=0.01), (
        "the OPTIONAL row is excluded from the scoring set, so the shared denominator "
        "is the three scored requirement weights plus the fixed image weight"
    )


def test_certified_view_names_the_over_limit_key_without_calling_it_missing(mega_world):
    """The pinned description is present but 120 characters against MegaMart's
    100-character override, so it appears in over_limit_keys and not in
    missing_required_keys, and both stored listing scores match the diagnostic.

    PRD 3.4: "It also reports two diagnostic arrays, both computed against the certified source and both sorted in ascending alphabetical order of attribute key: `missing_required_keys` lists the keys of `REQUIRED` requirement rows for which the pinned revision carries no attribute value with at least one character, and `over_limit_keys` lists the keys in the scoring set whose pinned value exceeds the effective retailer ceiling."
    Design: Difficulty/dual_variant_calc/completeness_declared_vs_certified_diverge_on_same_listing
    """
    data = validate_success(
        api_client.get_listing_completeness(
            mega_world["listing"]["id"], make_content_author_headers()
        )
    )
    assert data["over_limit_keys"] == ["description"]
    assert data["missing_required_keys"] == []

    listing = validate_success(
        api_client.get_retailer_listing(
            mega_world["listing"]["id"], make_content_author_headers()
        )
    )
    assert_retailer_listing(listing)
    assert float(listing["completeness_score_declared"]) == pytest.approx(92.59, abs=0.01)
    assert float(listing["completeness_score_certified"]) == pytest.approx(66.67, abs=0.01)


def test_post_pin_window_lift_splits_the_observations_on_pin_time(shop_world):
    """Four observations straddle the pin instant: the two crawls at or after
    2026-08-05T00:00:00Z average 2.70 percent conversion against the 1.60 percent
    of the two before it, so the default variant reports 68.75.

    PRD 3.9: "The default variant, named `post_pin_window`, splits on pin time: observations whose `observed_at` is at or after the product's `last_pinned_at` form HIGH, and those strictly before it form BASE."
    Design: Difficulty/dual_variant_calc/conversion_lift_post_pin_window_vs_quality_split_regroup
    """
    data = validate_success(
        api_client.get_shelf_summary(shop_world["product"]["id"], make_shelf_admin_headers())
    )
    assert data["lift_variant"] == "post_pin_window"
    assert float(data["conversion_lift_pct"]) == pytest.approx(68.75, abs=0.01)
    assert data["high_group_size"] == 2
    assert data["base_group_size"] == 2


def test_quality_split_regroups_the_same_rows_on_measured_accuracy(shop_world):
    """The identical four rows regrouped on the 90.00 accuracy threshold move one
    observation into HIGH and one into BASE, giving 38.89, while the product keeps
    storing only the default variant's 68.75.

    PRD 3.9: "The alternative variant, named `quality_split`, ignores pin time entirely and splits on measured accuracy: observations whose `content_accuracy_pct` is at least 90.00 form HIGH and those below 90.00 form BASE."
    Design: Difficulty/dual_variant_calc/conversion_lift_post_pin_window_vs_quality_split_regroup
    """
    data = validate_success(
        api_client.get_shelf_summary(
            shop_world["product"]["id"],
            make_shelf_admin_headers(),
            params={"lift_variant": "quality_split"},
        )
    )
    assert data["lift_variant"] == "quality_split"
    assert float(data["conversion_lift_pct"]) == pytest.approx(38.89, abs=0.01)
    assert data["high_group_size"] == 2
    assert data["base_group_size"] == 2

    product = validate_success(
        api_client.get_product(shop_world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["conversion_lift_pct"]) == pytest.approx(68.75, abs=0.01)


def test_a_not_syndicated_listing_never_enters_the_health_input_set(shop_world):
    """The ShopRight listing was never transmitted, so the health index stays 0.00
    with an empty breakdown even though four observations exist, and the single
    sub-threshold accuracy crawl leaves exactly one open drift alert behind.

    PRD 3.9: "The product's `shelf_health_index` aggregates only those of its listings whose `syndication_state` is `LIVE` or `ERROR_HOLD`; `NOT_SYNDICATED` and `PENDING` listings are excluded, and when no listing qualifies the index is 0.00 and the per-retailer breakdown is empty."
    Design: Difficulty/dual_variant_calc/conversion_lift_post_pin_window_vs_quality_split_regroup
    """
    data = validate_success(
        api_client.get_shelf_summary(shop_world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(data["shelf_health_index"]) == pytest.approx(0.00, abs=0.01)
    assert data["qualifying_listing_count"] == 0
    assert data["retailer_subscores"] == []

    product = validate_success(
        api_client.get_product(shop_world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(0.00, abs=0.01)
    assert product["open_alert_count"] == 1
    assert product["governance_flag"] == "CONTENT_AT_RISK"
