"""Concentration assessment: bucket share rounding, the 25.00 breach boundary,
and the per-dimension publish/supersede invariant."""
import pytest

from test_helpers import (
    create_assessment,
    list_buckets,
    publish_assessment,
    setup_active_engagement,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DIRECTOR


def _two_vendor_region_setup(api, emea_spend, na_spend, name_suffix=""):
    setup_active_engagement(
        vendor_name=f"EMEA Vendor {name_suffix}",
        region="EMEA",
        category="BPO",
        engagement_code=f"EMEA-E1-{name_suffix}",
        spend=emea_spend,
    )
    setup_active_engagement(
        vendor_name=f"NA Vendor {name_suffix}",
        region="NA",
        category="CLOUD_INFRA",
        engagement_code=f"NA-E1-{name_suffix}",
        spend=na_spend,
    )


def _bucket_map(api, assessment_id):
    data, _meta = list_buckets(assessment_id)
    return {b["bucket_key"]: b for b in data}, data


class TestConcentrationShareRoundingPerBucket:
    def test_true_share_24996_rounds_to_25_and_breaches(self, api):
        """PRD §3.14: "A bucket is flagged `is_breach` when its rounded
        `share_pct` is at least 25.00; the comparison uses the rounded value,
        so a true share of 24.996 becomes 25.00 after rounding and therefore is
        a breach, while 24.99 is not."
        PRD §3.14: "The assessment's `breach_bucket_keys` collects the
        `bucket_key` of every bucket with `is_breach` true."

        Design: Difficulty/dual_variant_calc/concentration_share_per_bucket_then_total_rounding
        """
        _two_vendor_region_setup(api, 24996, 75004, name_suffix="r1")
        assessment = create_assessment()
        published = publish_assessment(assessment["id"])
        assert "EMEA" in published["breach_bucket_keys"]

        buckets, _ = _bucket_map(api, assessment["id"])
        assert buckets["EMEA"]["share_pct"] == pytest.approx(25.00, abs=1e-9)
        assert buckets["EMEA"]["is_breach"] is True

    def test_true_share_24989_rounds_to_2499_and_does_not_breach(self, api):
        """PRD §3.14: "A bucket is flagged `is_breach` when its rounded
        `share_pct` is at least 25.00; the comparison uses the rounded value,
        so a true share of 24.996 becomes 25.00 after rounding and therefore is
        a breach, while 24.99 is not."

        Design: Difficulty/dual_variant_calc/concentration_share_per_bucket_then_total_rounding
        """
        _two_vendor_region_setup(api, 24989, 75011, name_suffix="r2")
        assessment = create_assessment()
        published = publish_assessment(assessment["id"])
        assert "EMEA" not in published["breach_bucket_keys"]

        buckets, _ = _bucket_map(api, assessment["id"])
        # 24989 / 100000 * 100 = 24.989 -> rounds to 24.99, below the threshold
        assert buckets["EMEA"]["share_pct"] == pytest.approx(24.99, abs=1e-9)
        assert buckets["EMEA"]["is_breach"] is False


class TestConcentrationRoundingOrder:
    def test_round_then_compare_marks_24996_as_breach(self, api):
        """PRD §3.14: "A bucket is flagged `is_breach` when its rounded
        `share_pct` is at least 25.00; the comparison uses the rounded value,
        so a true share of 24.996 becomes 25.00 after rounding and therefore is
        a breach, while 24.99 is not."
        PRD §3.14: "Each bucket's `share_pct` is the bucket's spend divided by
        the grand total spend across all active engagements, multiplied by 100,
        then rounded half-up to two decimal places; if the grand total is zero,
        every bucket's `share_pct` is 0.00."

        Design: Difficulty/combinatorial_formula/concentration_share_rounding_order
        """
        _two_vendor_region_setup(api, 24996, 75004, name_suffix="ro1")
        assessment = create_assessment()
        published = publish_assessment(assessment["id"])
        assert "EMEA" in published["breach_bucket_keys"]

    def test_bucket_values_and_sort_order(self, api):
        """PRD §3.14: "For any downstream iteration, buckets are sorted by
        `share_pct` descending, with ties broken by `bucket_key` ascending in
        string order."
        PRD §3.14: "Each bucket's `total_spend_cents` is the sum of
        `annual_spend_cents` over the engagements in that bucket."

        Design: Difficulty/combinatorial_formula/concentration_share_rounding_order
        """
        _two_vendor_region_setup(api, 24996, 75004, name_suffix="ro2")
        assessment = create_assessment()
        publish_assessment(assessment["id"])

        buckets, ordered = _bucket_map(api, assessment["id"])
        assert buckets["EMEA"]["total_spend_cents"] == 24996
        assert buckets["NA"]["total_spend_cents"] == 75004
        # 75004 / 100000 * 100 = 75.004 -> 75.00 ; EMEA 24.996 -> 25.00
        assert buckets["NA"]["share_pct"] == pytest.approx(75.00, abs=1e-9)
        assert buckets["EMEA"]["share_pct"] == pytest.approx(25.00, abs=1e-9)
        assert [b["bucket_key"] for b in ordered] == ["NA", "EMEA"]


class TestConcentrationBreachBoundary:
    def test_exactly_25_pct_is_a_breach(self, api):
        """PRD §3.14: "A bucket is flagged `is_breach` when its rounded
        `share_pct` is at least 25.00; the comparison uses the rounded value,
        so a true share of 24.996 becomes 25.00 after rounding and therefore is
        a breach, while 24.99 is not."

        Design: Difficulty/boundary_precision_check/concentration_share_at_exactly_25_pct
        """
        _two_vendor_region_setup(api, 25000, 75000, name_suffix="b1")
        assessment = create_assessment()
        published = publish_assessment(assessment["id"])
        assert "EMEA" in published["breach_bucket_keys"]

        buckets, _ = _bucket_map(api, assessment["id"])
        assert buckets["EMEA"]["share_pct"] == pytest.approx(25.00, abs=1e-9)
        assert buckets["EMEA"]["is_breach"] is True

    def test_2499_pct_is_not_a_breach(self, api):
        """PRD §3.14: "A bucket is flagged `is_breach` when its rounded
        `share_pct` is at least 25.00; the comparison uses the rounded value,
        so a true share of 24.996 becomes 25.00 after rounding and therefore is
        a breach, while 24.99 is not."

        Design: Difficulty/boundary_precision_check/concentration_share_at_exactly_25_pct
        """
        _two_vendor_region_setup(api, 24990, 75010, name_suffix="b2")
        assessment = create_assessment()
        published = publish_assessment(assessment["id"])
        assert "EMEA" not in published["breach_bucket_keys"]

        buckets, _ = _bucket_map(api, assessment["id"])
        assert buckets["EMEA"]["share_pct"] == pytest.approx(24.99, abs=1e-9)
        assert buckets["EMEA"]["is_breach"] is False


class TestConcentrationPublishSupersedeInvariant:
    def test_newer_publish_supersedes_prior_on_same_dimension(self, api):
        """PRD §3.14: "When a newer assessment on the same `grouping_dimension`
        reaches `PUBLISHED`, the older one transitions to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/concentration_assessment_publish_supersede_invariant
        """
        setup_active_engagement(vendor_name="Supersede Vendor")
        a1 = create_assessment(window_end="2026-05-15T00:00:00Z")
        a2 = create_assessment(window_start="2026-05-15T00:00:00Z")

        publish_assessment(a1["id"])
        publish_assessment(a2["id"])

        first = validate_success(api.get_concentration_assessment(a1["id"], DIRECTOR), 200)
        second = validate_success(api.get_concentration_assessment(a2["id"], DIRECTOR), 200)
        assert first["status"] == "SUPERSEDED"
        assert second["status"] == "PUBLISHED"

        data, _meta = validate_paginated(api.list_concentration_assessments(DIRECTOR))
        published_region = [
            a for a in data
            if a["grouping_dimension"] == "REGION" and a["status"] == "PUBLISHED"
        ]
        assert len(published_region) == 1
        assert published_region[0]["id"] == a2["id"]

    def test_publish_on_other_dimension_does_not_supersede(self, api):
        """PRD §3.14: "When a newer assessment on the same `grouping_dimension`
        reaches `PUBLISHED`, the older one transitions to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/concentration_assessment_publish_supersede_invariant
        """
        setup_active_engagement(vendor_name="Supersede Vendor 2")
        region_assessment = create_assessment(dimension="REGION")
        category_assessment = create_assessment(dimension="SERVICE_CATEGORY")

        publish_assessment(region_assessment["id"])
        publish_assessment(category_assessment["id"])

        region_after = validate_success(
            api.get_concentration_assessment(region_assessment["id"], DIRECTOR), 200
        )
        category_after = validate_success(
            api.get_concentration_assessment(category_assessment["id"], DIRECTOR), 200
        )
        assert region_after["status"] == "PUBLISHED"
        assert category_after["status"] == "PUBLISHED"
