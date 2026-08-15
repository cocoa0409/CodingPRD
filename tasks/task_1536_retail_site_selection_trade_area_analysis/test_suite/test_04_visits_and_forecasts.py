"""Site-visit weighted scoring and sales-forecast variant gross models
(PRD §3.4, §3.5), including the cannibalization cap at forecast lock."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_site_visit,
    assert_sales_forecast,
    assert_site_visit,
    create_draft_forecast,
    create_modeled_site,
    create_qualified_market,
    create_scored_site,
    create_stores,
    get_success_data,
    lock_forecast,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestVisitWeightedScore:
    def test_visit_weighted_score_constants(self, api):
        """PRD §3.4: "The visit's `total_score` is the weighted blend of the
        four components — thirty percent visibility, twenty-five percent access,
        fifteen percent parking, thirty percent co-tenancy — rounded half-up to
        two decimal places."
        PRD §3.4: "A passing visit advances a `MODELED` site to `SCORED`."

        Design: Corner/calculations/visit_weighted_score_constants
        """
        market = create_qualified_market(name="Metro VW")
        ctx = create_modeled_site(market["id"])
        visit = add_site_visit(ctx["site"]["id"])
        assert_site_visit(visit)
        # 0.30*80 + 0.25*90 + 0.15*70 + 0.30*85 = 24.00 + 22.50 + 10.50 + 25.50
        assert visit["total_score"] == pytest.approx(82.50, abs=0.001)
        site = validate_success(api.get_site(ctx["site"]["id"], ANALYST))
        assert site["site_status"] == "SCORED"


class TestVisitScoreBoundary:
    def _two_modeled_sites(self, api):
        market = create_qualified_market(name="Metro VS")
        lo = create_modeled_site(market["id"],
                                 site_overrides={"address": "1 Lowscore Dr"})
        hi = create_modeled_site(market["id"],
                                 site_overrides={"address": "2 Passscore Dr"})
        return lo, hi

    def test_visit_just_below_threshold_stays_modeled(self, api):
        """PRD §3.4: "The advance gate compares against the rounded value: a
        total of at least 70.00 passes."
        PRD §3.4: "A failing visit is still accepted and recorded, but it does
        not advance the site — and if the site was `SCORED`, it conditionally
        regresses to `MODELED`, losing its scored standing until a better visit
        or a fresh model restores it."

        Design: Difficulty/boundary_precision_check/visit_score_rounding_boundary
        """
        lo, _hi = self._two_modeled_sites(api)
        visit = add_site_visit(
            lo["site"]["id"], visibility_score=68, access_score=71,
            parking_score=72, cotenancy_score=70,
        )
        assert visit["total_score"] == pytest.approx(69.95, abs=0.001)
        site = validate_success(api.get_site(lo["site"]["id"], ANALYST))
        assert site["site_status"] == "MODELED"

    def test_visit_exactly_at_threshold_advances_to_scored(self, api):
        """PRD §3.4: "The advance gate compares against the rounded value: a
        total of at least 70.00 passes."
        PRD §3.4: "A passing visit advances a `MODELED` site to `SCORED`."

        Design: Difficulty/boundary_precision_check/visit_score_rounding_boundary
        """
        _lo, hi = self._two_modeled_sites(api)
        visit = add_site_visit(
            hi["site"]["id"], visibility_score=70, access_score=70,
            parking_score=70, cotenancy_score=70,
        )
        assert visit["total_score"] == pytest.approx(70.00, abs=0.001)
        site = validate_success(api.get_site(hi["site"]["id"], ANALYST))
        assert site["site_status"] == "SCORED"

    def test_below_threshold_visit_regresses_scored_site(self, api):
        """PRD §3.4: "Only one visit stands per site at a time: recording a new
        visit supersedes the site's prior `SUBMITTED` visit, which moves to
        `SUPERSEDED`, while the new visit begins `SUBMITTED`."
        PRD §3.4: "A failing visit is still accepted and recorded, but it does
        not advance the site — and if the site was `SCORED`, it conditionally
        regresses to `MODELED`, losing its scored standing until a better visit
        or a fresh model restores it."

        Design: Corner/state_machines/below_threshold_visit_regresses_scored_site
        """
        market = create_qualified_market(name="Metro S8")
        ctx = create_scored_site(market["id"])
        first_visit = ctx["visit"]
        assert ctx["site"]["site_status"] == "SCORED"
        failing = add_site_visit(
            ctx["site"]["id"], visited_on="2026-08-08", visibility_score=68,
            access_score=71, parking_score=72, cotenancy_score=70,
        )
        assert failing["total_score"] == pytest.approx(69.95, abs=0.001)
        assert failing["visit_status"] == "SUBMITTED"
        reloaded_first = validate_success(
            api.get_site_visit(first_visit["id"], ANALYST)
        )
        assert reloaded_first["visit_status"] == "SUPERSEDED"
        site = validate_success(api.get_site(ctx["site"]["id"], ANALYST))
        assert site["site_status"] == "MODELED"


class TestForecastVariantDivergence:
    """Identical site, model, and listings under both gross variants."""

    def _setup(self, api):
        market = create_qualified_market(name="Metro G")
        create_stores(market["id"], (
            ("A1", "STANDARD", 1200000000),
            ("A2", "STANDARD", 1000000000),
        ))
        ctx = create_modeled_site(
            market["id"],
            site_overrides={"address": "1 Main St"},
            listings=(
                {"brand_name": "Alpha", "estimated_sqft": 8000,
                 "distance_minutes": 4, "listing_type": "COMPETITOR"},
                {"brand_name": "Beta", "estimated_sqft": 12000,
                 "distance_minutes": 9, "listing_type": "COMPETITOR"},
            ),
        )
        return ctx

    def test_gravity_gross_uses_attraction_share(self, api):
        """PRD §3.5: "Under `GRAVITY`, a share-of-attraction model: the
        candidate's own attraction is its `square_footage` divided by 25 (the
        square of the five-minute self-drive constant). Each `COMPETITOR`
        listing of the pinned model contributes an attraction of its
        `estimated_sqft` divided by the square of its effective distance, where
        the effective distance is the greater of the listing's
        `distance_minutes` and one minute; attractions are computed in exact
        decimal arithmetic."
        PRD §3.5: "Gross annual sales are then the `trade_area_population`
        multiplied by the `per_capita_spend_cents` multiplied by the capture
        rate, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/forecast_gravity_vs_analog_divergence
        """
        ctx = self._setup(api)
        forecast = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="GRAVITY",
        )
        assert_sales_forecast(forecast)
        # capture = 400 / (400 + 500 + 12000/81) = 0.381625 (6dp);
        # gross = 50000 * 300000 * 0.381625.
        assert forecast["gross_annual_sales_cents"] == 5724375000
        assert forecast["forecast_status"] == "DRAFT"

    def test_analog_gross_uses_same_format_store_mean(self, api):
        """PRD §3.5: "Under `ANALOG`, the model ignores competitor geometry:
        the base is the mean of `annual_sales_cents` over the market's
        `OPERATING` existing stores whose `format_type` equals the site's,
        rounded half-up to whole cents before any factor is applied"
        PRD §3.5: "Gross annual sales are the base multiplied by the
        candidate's format factor — 0.85 for `EXPRESS`, 1.00 for `STANDARD`,
        1.20 for `FLAGSHIP` — rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/forecast_gravity_vs_analog_divergence
        """
        ctx = self._setup(api)
        gravity = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="GRAVITY",
        )
        analog = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="ANALOG",
        )
        # mean(1200000000, 1000000000) * 1.00 (STANDARD factor)
        assert analog["gross_annual_sales_cents"] == 1100000000
        assert analog["gross_annual_sales_cents"] != (
            gravity["gross_annual_sales_cents"]
        )
        assert analog["forecast_status"] == "DRAFT"


class TestForecastEdgeResults:
    def test_gravity_empty_competitor_set_capture_one(self, api):
        """PRD §3.5: "The capture rate is the candidate's attraction divided by
        the sum of the candidate's attraction and all competitor attractions,
        rounded half-up to six decimal places — when the model carries no
        `COMPETITOR` listings, the capture rate is exactly 1.000000."

        Design: Corner/calculations/gravity_empty_competitor_set_capture_one
        """
        market = create_qualified_market(name="Metro G0")
        ctx = create_modeled_site(market["id"],
                                  site_overrides={"address": "1 Solo Way"})
        forecast = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="GRAVITY",
        )
        # capture 1.000000 -> gross = 50000 * 300000
        assert forecast["gross_annual_sales_cents"] == 15000000000

    def test_gravity_distance_zero_uses_floor(self, api):
        """PRD §3.5: "Each `COMPETITOR` listing of the pinned model contributes
        an attraction of its `estimated_sqft` divided by the square of its
        effective distance, where the effective distance is the greater of the
        listing's `distance_minutes` and one minute; attractions are computed
        in exact decimal arithmetic."

        Design: Corner/calculations/gravity_distance_zero_uses_floor
        """
        market = create_qualified_market(name="Metro GZ")
        ctx = create_modeled_site(
            market["id"],
            site_overrides={"address": "2 Zero Way"},
            listings=({"brand_name": "CoLoc", "estimated_sqft": 10000,
                       "distance_minutes": 0, "listing_type": "COMPETITOR"},),
        )
        forecast = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="GRAVITY",
        )
        # A_site 400; A_competitor 10000/1^2 = 10000; capture 0.038462 (6dp);
        # gross = 50000 * 300000 * 0.038462.
        assert forecast["gross_annual_sales_cents"] == 576930000

    def test_analog_empty_set_falls_back_to_prototype(self, api):
        """PRD §3.5: "when no such analog store exists, the base is the
        market's `prototype_sales_cents`."
        PRD §3.5: "Gross annual sales are the base multiplied by the
        candidate's format factor — 0.85 for `EXPRESS`, 1.00 for `STANDARD`,
        1.20 for `FLAGSHIP` — rounded half-up to whole cents."

        Design: Corner/calculations/analog_empty_set_falls_back_to_prototype
        """
        market = create_qualified_market(name="Metro AF")
        ctx = create_modeled_site(
            market["id"],
            site_overrides={"address": "3 Proto Pl", "format_type": "EXPRESS",
                            "square_footage": 3000,
                            "build_cost_cents": 200000000},
            model_overrides={"drive_time_minutes": 10,
                             "trade_area_population": 30000,
                             "per_capita_spend_cents": 250000},
        )
        forecast = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="ANALOG",
        )
        # prototype 900000000 * 0.85 (EXPRESS factor)
        assert forecast["gross_annual_sales_cents"] == 765000000


class TestCannibalizationCapAtLock:
    def _setup_cap_fixture(self, api, cannibal_store_sales):
        market = create_qualified_market(name="Metro CB")
        stores = create_stores(market["id"], (
            ("A1", "STANDARD", 400000000),
            ("A2", "STANDARD", 560000000),
            ("C1", "EXPRESS", cannibal_store_sales),
        ))
        ctx = create_scored_site(
            market["id"],
            site_overrides={"address": "4 Cap Ct"},
            store_drive_times=[{"store_id": stores[2]["id"], "drive_minutes": 3}],
        )
        forecast = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="ANALOG",
        )
        return ctx, forecast

    def test_cannibalization_cap_inclusive_boundary(self, api):
        """PRD §3.5: "The cannibalization cap guards dilution: if the computed
        cannibalization exceeds twenty-five percent of the forecast's
        `gross_annual_sales_cents`, the lock is rejected with
        `ERR_CANNIBALIZATION_EXCEEDS_CAP`; cannibalization of exactly
        twenty-five percent passes, as the boundary is inclusive."
        PRD §3.5: "Passing the cap, `net_annual_sales_cents` is fixed as gross
        minus cannibalized"

        Design: Corner/calculations/cannibalization_cap_inclusive_boundary
        """
        ctx, forecast = self._setup_cap_fixture(api, 400000000)
        # gross = mean(400000000, 560000000) = 480000000 (EXPRESS store is not
        # a same-format analog).
        assert forecast["gross_annual_sales_cents"] == 480000000
        locked = lock_forecast(forecast["id"])
        assert_sales_forecast(locked)
        # 0.30 * 400000000 = 120000000 == exactly 25% of gross -> allowed.
        assert locked["cannibalized_sales_cents"] == 120000000
        assert locked["net_annual_sales_cents"] == 360000000
        assert locked["forecast_status"] == "COMMITTEE_LOCKED"
        site = validate_success(api.get_site(ctx["site"]["id"], ANALYST))
        assert site["site_status"] == "FORECAST_LOCKED"

    def test_cannibalization_over_cap_rejected(self, api):
        """PRD §3.5: "The cannibalization cap guards dilution: if the computed
        cannibalization exceeds twenty-five percent of the forecast's
        `gross_annual_sales_cents`, the lock is rejected with
        `ERR_CANNIBALIZATION_EXCEEDS_CAP`; cannibalization of exactly
        twenty-five percent passes, as the boundary is inclusive."

        Design: Corner/calculations/cannibalization_over_cap_rejected
        """
        ctx, forecast = self._setup_cap_fixture(api, 410000000)
        # 0.30 * 410000000 = 123000000 > 120000000 cap.
        resp = api.lock_sales_forecast(forecast["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_CANNIBALIZATION_EXCEEDS_CAP)
        reloaded = validate_success(api.get_sales_forecast(forecast["id"], ANALYST))
        assert reloaded["forecast_status"] == "DRAFT"
        site = validate_success(api.get_site(ctx["site"]["id"], ANALYST))
        assert site["site_status"] == "SCORED"

    def test_locked_forecast_immune_to_later_store_close(self, api):
        """PRD §3.5: "At lock, the forecast computes its authoritative
        `cannibalized_sales_cents` from the pinned model's variant and
        `store_drive_times` over the stores `OPERATING` at that moment, using
        exactly the per-store eligibility, factor, rounding, and summation rules
        of §3.3."
        PRD §3.3: "stores that close afterward do not alter the stored
        snapshot."

        Design: Corner/calculations/locked_forecast_immune_to_later_store_close
        """
        market = create_qualified_market(name="Metro VP")
        stores = create_stores(market["id"], (
            ("A1", "STANDARD", 400000000),
            ("A2", "STANDARD", 560000000),
            ("C1", "EXPRESS", 400000000),
        ))
        ctx = create_scored_site(
            market["id"],
            site_overrides={"address": "4 Cap Ct"},
            store_drive_times=[{"store_id": stores[2]["id"], "drive_minutes": 3}],
        )
        forecast = create_draft_forecast(
            ctx["site"]["id"], ctx["model"]["id"], model_variant="ANALOG",
        )
        locked = lock_forecast(forecast["id"])
        assert locked["cannibalized_sales_cents"] == 120000000
        get_success_data(api.close_store(stores[2]["id"], ADMIN))
        reloaded = validate_success(api.get_sales_forecast(forecast["id"], ANALYST))
        assert reloaded["cannibalized_sales_cents"] == 120000000
        assert reloaded["net_annual_sales_cents"] == 360000000
