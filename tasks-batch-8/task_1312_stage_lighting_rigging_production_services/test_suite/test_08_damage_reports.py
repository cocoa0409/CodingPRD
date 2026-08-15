"""Damage and loss reconciliation: dual-variant valuation, the depreciation
floor, conditional quote rules, billing cut-off at assessment, and the
one-open-report rule."""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS,
    setup_load_in_production,
    get_pull_list_entry, get_asset,
    file_damage_report, get_damage_report, assess_report,
)

WH = TEST_USERS["warehouse_chief_headers"]


class TestDualVariantValuation:
    def test_damage_depreciated_vs_repair_quote(self, api):
        """PRD §3.8: "Under `DEPRECIATED` — mandatory for `LOSS`, optional for `DAMAGE` — the asset's age is the number of full 365.25-day anniversaries elapsed between `acquired_at` and the logical clock; the depreciation factor is 1.00 reduced by 0.10 per full year of age, never falling below a 0.20 floor; and the `assessed_charge_cents` is the asset's `replacement_cost_cents` multiplied by that factor, rounded half-up to whole cents. Under `REPAIR_QUOTE` — available to `DAMAGE` reports only — the charge is the `repair_quote_cents` uplifted by 15 percent for diminution of value, rounded half-up to whole cents, independent of the asset's age."

        Design: Difficulty/dual_variant_calc/damage_depreciated_vs_repair_quote
        """
        ctx = setup_load_in_production(
            asset_specs=[{"asset_tag": "ML-001"}, {"asset_tag": "ML-002"}])
        e1, e2 = ctx["entries"]  # both OUT at clock 2026-09-01T08:00:00Z
        r1 = file_damage_report(ctx["production"]["id"], e1["id"], "DAMAGE")
        r2 = file_damage_report(ctx["production"]["id"], e2["id"], "DAMAGE")
        # Assets acquired 2024-08-01, clock 2026-09-01: 2 full years -> factor 0.80.
        data = assess_report(r1["id"], "DEPRECIATED")
        assert data["assessed_charge_cents"] == 80000
        # 50000 quote x 1.15 diminution = 57500.
        data = assess_report(r2["id"], "REPAIR_QUOTE", repair_quote_cents=50000)
        assert data["assessed_charge_cents"] == 57500
        entry1 = get_pull_list_entry(e1["id"])
        assert entry1["status"] == "DAMAGED"
        assert entry1["rental_charge_cents"] == 5000, \
            "same-day billing window: 1 day at the full tier"
        assert 80000 - 57500 == 22500

    def test_repair_quote_rounding_half_up(self, api):
        """PRD §3.8: "Under `REPAIR_QUOTE` — available to `DAMAGE` reports only — the charge is the `repair_quote_cents` uplifted by 15 percent for diminution of value, rounded half-up to whole cents, independent of the asset's age."

        Design: Difficulty/dual_variant_calc/damage_depreciated_vs_repair_quote
        """
        ctx = setup_load_in_production()
        report = file_damage_report(ctx["production"]["id"], ctx["entry"]["id"], "DAMAGE")
        # 33333 x 1.15 = 38332.95 -> 38333 whole cents, round half-up.
        data = assess_report(report["id"], "REPAIR_QUOTE", repair_quote_cents=33333)
        assert data["assessed_charge_cents"] == 38333


class TestDepreciationFloor:
    def test_damage_depreciation_floor_applied(self, api):
        """PRD §3.8: "the depreciation factor is 1.00 reduced by 0.10 per full year of age, never falling below a 0.20 floor; and the `assessed_charge_cents` is the asset's `replacement_cost_cents` multiplied by that factor, rounded half-up to whole cents."
        PRD §3.8: "The entry leaves `OUT`: a `DAMAGE` report moves it to `DAMAGED`, a `LOSS` report moves it to `LOST`, and in both cases the entry's `returned_at` is set to the assessment clock time and its `rental_charge_cents` is computed with billing ending at that same moment, per the tiered day-rate rule of §3.6. The asset follows: to `DAMAGED` or to `LOST` respectively."

        Design: Corner/calculations/damage_depreciation_floor_applied
        """
        ctx = setup_load_in_production(
            asset_specs=[{"asset_tag": "OLD-001", "asset_class": "FOLLOWSPOT",
                          "weight_kg": 40, "acquired_at": "2010-08-01T00:00:00Z"}])
        # 16 full years at the 2026-09-01 clock: raw factor 1 - 0.10x16 = -0.60,
        # clamped to the 0.20 floor -> 20000 on a 100000 replacement cost.
        report = file_damage_report(ctx["production"]["id"], ctx["entry"]["id"], "LOSS")
        data = assess_report(report["id"], "DEPRECIATED")
        assert data["assessed_charge_cents"] == 20000
        assert data["status"] == "ASSESSED"
        assert get_pull_list_entry(ctx["entry"]["id"])["status"] == "LOST"
        assert get_asset(ctx["asset"]["id"])["status"] == "LOST"


class TestConditionalValuationRules:
    def test_valuation_method_conditional_errors(self, api):
        """PRD §3.8: "A `LOSS` report accepts only `DEPRECIATED` valuation; assessing a loss as `REPAIR_QUOTE` is rejected with `ERR_VALUATION_METHOD_INVALID` (HTTP 422). Then, quote handling: `REPAIR_QUOTE` valuation requires a positive `repair_quote_cents` in the payload (its absence is `ERR_REPAIR_QUOTE_REQUIRED`, HTTP 422), while `DEPRECIATED` valuation forbids the field entirely (its presence is `ERR_INVALID_REQUEST`)."

        Design: Corner/errors/valuation_method_conditional_errors
        """
        ctx = setup_load_in_production(
            asset_specs=[{"asset_tag": "ML-001"}, {"asset_tag": "ML-002"}])
        e1, e2 = ctx["entries"]
        r1 = file_damage_report(ctx["production"]["id"], e1["id"], "LOSS")
        r2 = file_damage_report(ctx["production"]["id"], e2["id"], "DAMAGE")
        resp = api.assess_damage_report(
            r1["id"], {"valuation_method": "REPAIR_QUOTE", "repair_quote_cents": 50000}, WH)
        validate_error(resp, ApiErrorId.ERR_VALUATION_METHOD_INVALID)
        resp = api.assess_damage_report(r2["id"], {"valuation_method": "REPAIR_QUOTE"}, WH)
        validate_error(resp, ApiErrorId.ERR_REPAIR_QUOTE_REQUIRED)
        data = assess_report(r1["id"], "DEPRECIATED")
        assert data["assessed_charge_cents"] == 80000
        assert data["status"] == "ASSESSED"
        assert get_pull_list_entry(e1["id"])["status"] == "LOST"

    def test_assess_depreciated_with_quote_rejected(self, api):
        """PRD §3.8: "`REPAIR_QUOTE` valuation requires a positive `repair_quote_cents` in the payload (its absence is `ERR_REPAIR_QUOTE_REQUIRED`, HTTP 422), while `DEPRECIATED` valuation forbids the field entirely (its presence is `ERR_INVALID_REQUEST`)."

        Design: Corner/validations/assess_depreciated_with_quote_rejected
        """
        ctx = setup_load_in_production()
        report = file_damage_report(ctx["production"]["id"], ctx["entry"]["id"], "DAMAGE")
        resp = api.assess_damage_report(
            report["id"],
            {"valuation_method": "DEPRECIATED", "repair_quote_cents": 50000}, WH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_damage_report(report["id"])["status"] == "FILED"


class TestDuplicateOpenReport:
    def test_duplicate_open_damage_report_rejected(self, api):
        """PRD §3.8: "Filing requires the entry to still be `OUT` (otherwise `ERR_INVALID_STATE`), and at most one open report may exist per entry: a second filing while a `FILED` or `ASSESSED` report already exists for the same entry is rejected with `ERR_DUPLICATE_DAMAGE_REPORT` (HTTP 409)."

        Design: Corner/errors/duplicate_open_damage_report_rejected
        """
        ctx = setup_load_in_production()
        file_damage_report(ctx["production"]["id"], ctx["entry"]["id"], "DAMAGE")
        resp = api.create_damage_report(
            ctx["production"]["id"],
            {"pull_list_entry_id": ctx["entry"]["id"], "report_type": "LOSS"}, WH)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DAMAGE_REPORT)
