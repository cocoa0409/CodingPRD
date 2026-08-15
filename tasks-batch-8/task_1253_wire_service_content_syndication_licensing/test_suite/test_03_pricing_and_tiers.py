"""Circulation-based pricing: tier resolution boundaries, basis-points
multiplication with round-half-up, member discount branch, and the provisional
vs final invoice pricing variants."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_subscription,
    create_draft_invoice,
    create_draft_subscription,
    create_package,
    create_subscriber,
    create_tier,
    get_subscriber,
    set_clock,
    setup_active_subscription,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["salesops_headers"]


class TestProvisionalVsFinalPricing:
    """Same pricing inputs, two variants: the final variant (activation) applies
    the tier multiplier AND member discount; the provisional variant (draft
    invoice preview) applies the tier multiplier but ignores the member
    discount and the credit balance."""

    def _setup_member_pricing(self, api):
        return setup_active_subscription(
            package_overrides={
                "code": "NAT",
                "display_name": "National",
                "media_rights": "TEXT_AND_PHOTO",
                "base_monthly_fee_cents": 100000,
            },
            tier_overrides={
                "code": "METRO",
                "min_audience": 10000,
                "max_audience": 100000,
                "circulation_multiplier_basis_points": 15000,
                "monthly_republish_quota": 10,
                "overage_per_article_cents": 250,
                "member_discount_pct": 20,
            },
            subscriber_overrides={
                "legal_name": "Metro Daily",
                "billing_email": "b@m.com",
                "declared_audience": 50000,
                "is_member": True,
            },
        )

    def test_activation_applies_final_variant_with_member_discount(self, api):
        """PRD §3.3: "The gross amount is the package's
        `base_monthly_fee_cents` multiplied by the tier's
        `circulation_multiplier_basis_points` and divided by 10000, rounded
        half up to the nearest cent. If the subscriber `is_member` and the
        tier's `member_discount_pct` is greater than zero, the discount is the
        gross amount multiplied by `member_discount_pct` and divided by 100,
        again rounded half up to the nearest cent; otherwise the discount is
        zero. The subscription's `monthly_price_cents` is the gross amount
        minus the discount."

        gross = 100000 * 15000 / 10000 = 150000; discount = 150000 * 20 / 100
        = 30000; monthly_price_cents = 150000 - 30000 = 120000.

        Design: Difficulty/dual_variant_calc/subscription_pricing_provisional_vs_final_member_discount
        """
        ctx = self._setup_member_pricing(api)
        sub = ctx["subscription"]
        assert sub["status"] == "ACTIVE"
        assert sub["tier_id"] == ctx["tier"]["id"]
        assert sub["monthly_price_cents"] == 120000

    def test_draft_invoice_provisional_ignores_member_discount(self, api):
        """PRD §3.7: "`provisional_total_due_cents` is the provisional pricing
        variant: the gross monthly figure is recomputed from the package's
        `base_monthly_fee_cents` multiplied by the tier's
        `circulation_multiplier_basis_points` and divided by 10000, rounded
        half up to the nearest cent, deliberately ignoring both the tier's
        `member_discount_pct` and the subscriber's credit balance, then added
        to the accrued overage."
        PRD §3.7: "`base_fee_cents` is the subscription's
        `monthly_price_cents`, snapshotted as it stands at generation time."

        provisional = 100000 * 15000 / 10000 + 0 = 150000; base fee snapshot =
        120000; the two differ because the subscriber is a member with
        member_discount_pct = 20.

        Design: Difficulty/dual_variant_calc/subscription_pricing_provisional_vs_final_member_discount
        """
        ctx = self._setup_member_pricing(api)
        inv = create_draft_invoice(ctx["subscription"]["id"], "2026-05")
        assert inv["base_fee_cents"] == 120000
        assert inv["overage_cents"] == 0
        assert inv["provisional_total_due_cents"] == 150000
        assert inv["provisional_total_due_cents"] != inv["base_fee_cents"]


class TestPricingFormulaMemberBranch:
    def test_member_discount_applied_at_activation(self, api):
        """PRD §3.3: "If the subscriber `is_member` and the tier's
        `member_discount_pct` is greater than zero, the discount is the gross
        amount multiplied by `member_discount_pct` and divided by 100, again
        rounded half up to the nearest cent; otherwise the discount is zero.
        The subscription's `monthly_price_cents` is the gross amount minus the
        discount."

        gross = 100000 * 12000 / 10000 = 120000; discount = 120000 * 25 / 100
        = 30000; monthly_price_cents = 90000.

        Design: Difficulty/combinatorial_formula/pricing_formula_tiered_with_member_discount_mode_a
        """
        ctx = setup_active_subscription(
            package_overrides={"media_rights": "TEXT_ONLY", "base_monthly_fee_cents": 100000},
            tier_overrides={
                "min_audience": 10000,
                "max_audience": 50000,
                "circulation_multiplier_basis_points": 12000,
                "monthly_republish_quota": 5,
                "overage_per_article_cents": 300,
                "member_discount_pct": 25,
            },
            subscriber_overrides={"declared_audience": 20000, "is_member": True},
        )
        assert ctx["subscription"]["monthly_price_cents"] == 90000

    def test_non_member_gets_zero_discount(self, api):
        """PRD §3.3: "If the subscriber `is_member` and the tier's
        `member_discount_pct` is greater than zero, the discount is the gross
        amount multiplied by `member_discount_pct` and divided by 100, again
        rounded half up to the nearest cent; otherwise the discount is zero.
        The subscription's `monthly_price_cents` is the gross amount minus the
        discount."

        Same configuration with is_member=false: discount branch is off, so
        monthly_price_cents = gross = 100000 * 12000 / 10000 = 120000.

        Design: Difficulty/combinatorial_formula/pricing_formula_tiered_with_member_discount_mode_a
        """
        ctx = setup_active_subscription(
            package_overrides={"media_rights": "TEXT_ONLY", "base_monthly_fee_cents": 100000},
            tier_overrides={
                "min_audience": 10000,
                "max_audience": 50000,
                "circulation_multiplier_basis_points": 12000,
                "monthly_republish_quota": 5,
                "overage_per_article_cents": 300,
                "member_discount_pct": 25,
            },
            subscriber_overrides={"declared_audience": 20000, "is_member": False},
        )
        assert ctx["subscription"]["monthly_price_cents"] == 120000


class TestTierAudienceBoundary:
    def _two_tier_catalogue(self):
        pkg = create_package(media_rights="TEXT_ONLY", base_monthly_fee_cents=100000)
        tier_a = create_tier(
            code="TA",
            min_audience=1,
            max_audience=10000,
            circulation_multiplier_basis_points=10000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
            member_discount_pct=0,
        )
        tier_b = create_tier(
            code="TB",
            min_audience=10000,
            max_audience=50000,
            circulation_multiplier_basis_points=15000,
            monthly_republish_quota=10,
            overage_per_article_cents=200,
            member_discount_pct=0,
        )
        return pkg, tier_a, tier_b

    def test_audience_at_min_audience_selects_that_tier(self, api):
        """PRD §3.1: "A tier's audience window includes its `min_audience`
        boundary and excludes its `max_audience` boundary."
        PRD §3.3: "Tier resolution must succeed unambiguously: the candidates
        are the `ACTIVE` subscriber tiers whose `min_audience` is no greater
        than the subscriber's `declared_audience` and whose `max_audience` is
        either null or strictly greater than `declared_audience`; zero
        candidates is `ERR_NO_MATCHING_TIER` (HTTP 422), more than one is
        `ERR_AMBIGUOUS_TIER` (HTTP 422), and exactly one becomes the
        subscription's `tier_id`."

        declared_audience = 10000 sits exactly on tier B's inclusive lower
        bound: tier B is selected and monthly_price_cents = 100000 * 15000 /
        10000 = 150000.

        Design: Difficulty/boundary_precision_check/tier_min_audience_inclusive_boundary
        """
        set_clock("2026-05-10T00:00:00Z")
        pkg, tier_a, tier_b = self._two_tier_catalogue()
        ctx = setup_active_subscription(
            package=pkg,
            tier=tier_b,
            clock_to=None,
            subscriber_overrides={"declared_audience": 10000},
        )
        assert ctx["subscription"]["tier_id"] == tier_b["id"]
        assert ctx["subscription"]["monthly_price_cents"] == 150000

    def test_audience_one_below_min_audience_selects_lower_tier(self, api):
        """PRD §3.1: "A tier's audience window includes its `min_audience`
        boundary and excludes its `max_audience` boundary."

        declared_audience = 9999 is below tier B's inclusive lower bound and
        below tier A's exclusive upper bound (10000), so tier A is selected and
        monthly_price_cents = 100000 * 10000 / 10000 = 100000.

        Design: Difficulty/boundary_precision_check/tier_min_audience_inclusive_boundary
        """
        set_clock("2026-05-10T00:00:00Z")
        pkg, tier_a, tier_b = self._two_tier_catalogue()
        ctx = setup_active_subscription(
            package=pkg,
            tier=tier_b,
            clock_to=None,
            subscriber_overrides={"declared_audience": 9999},
        )
        assert ctx["subscription"]["tier_id"] == tier_a["id"]
        assert ctx["subscription"]["monthly_price_cents"] == 100000


class TestRoundingAndTierResolutionErrors:
    def test_tier_multiplier_rounding_half_up(self, api):
        """PRD §2.6: "Wherever a multiplication or division would produce a
        fractional cent — applying a tier's `circulation_multiplier_basis_points`
        to a package's base fee, or applying a `member_discount_pct` to a gross
        amount — the result is rounded half up to the nearest integer cent at
        that step, and subsequent steps operate on the rounded figure."

        gross = round_half_up(33333 * 15000 / 10000) = round_half_up(49999.5)
        = 50000 (not 49999); no member discount.

        Design: Corner/calculations/tier_multiplier_rounding_half_up
        """
        ctx = setup_active_subscription(
            package_overrides={"media_rights": "TEXT_ONLY", "base_monthly_fee_cents": 33333},
            tier_overrides={
                "min_audience": 1,
                "max_audience": 10000,
                "circulation_multiplier_basis_points": 15000,
                "monthly_republish_quota": 5,
                "overage_per_article_cents": 100,
                "member_discount_pct": 0,
            },
            subscriber_overrides={"declared_audience": 5000},
        )
        assert ctx["subscription"]["monthly_price_cents"] == 50000

    def test_no_matching_tier_returns_error(self, api):
        """PRD §3.3: "Tier resolution must succeed unambiguously: the
        candidates are the `ACTIVE` subscriber tiers whose `min_audience` is no
        greater than the subscriber's `declared_audience` and whose
        `max_audience` is either null or strictly greater than
        `declared_audience`; zero candidates is `ERR_NO_MATCHING_TIER`
        (HTTP 422), more than one is `ERR_AMBIGUOUS_TIER` (HTTP 422), and
        exactly one becomes the subscription's `tier_id`."

        Design: Corner/calculations/no_matching_tier_returns_error
        """
        set_clock("2026-05-10T00:00:00Z")
        pkg = create_package(media_rights="TEXT_ONLY", base_monthly_fee_cents=10000)
        create_tier(
            min_audience=1,
            max_audience=10000,
            circulation_multiplier_basis_points=10000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
        )
        sub = create_subscriber(legal_name="NM", declared_audience=999999)
        subp = create_draft_subscription(sub["id"], pkg["id"])
        res = api.activate_subscription(
            subp["id"], {"expected_subscriber_version": sub["version"]}, SALES
        )
        validate_error(res, ApiErrorId.ERR_NO_MATCHING_TIER.value, expected_status=422)

    def test_ambiguous_tier_overlap_returns_error(self, api):
        """PRD §3.3: "Tier resolution must succeed unambiguously: the
        candidates are the `ACTIVE` subscriber tiers whose `min_audience` is no
        greater than the subscriber's `declared_audience` and whose
        `max_audience` is either null or strictly greater than
        `declared_audience`; zero candidates is `ERR_NO_MATCHING_TIER`
        (HTTP 422), more than one is `ERR_AMBIGUOUS_TIER` (HTTP 422), and
        exactly one becomes the subscription's `tier_id`."

        Tier A [1, 10000) and tier B [5000, 20000) are both ACTIVE and both
        cover declared_audience = 5000.

        Design: Corner/calculations/ambiguous_tier_overlap_returns_error
        """
        set_clock("2026-05-10T00:00:00Z")
        pkg = create_package(media_rights="TEXT_ONLY", base_monthly_fee_cents=10000)
        create_tier(
            code="TA",
            min_audience=1,
            max_audience=10000,
            circulation_multiplier_basis_points=10000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
        )
        create_tier(
            code="TB",
            min_audience=5000,
            max_audience=20000,
            circulation_multiplier_basis_points=11000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
        )
        sub = create_subscriber(legal_name="AMB", declared_audience=5000)
        subp = create_draft_subscription(sub["id"], pkg["id"])
        res = api.activate_subscription(
            subp["id"], {"expected_subscriber_version": sub["version"]}, SALES
        )
        validate_error(res, ApiErrorId.ERR_AMBIGUOUS_TIER.value, expected_status=422)
