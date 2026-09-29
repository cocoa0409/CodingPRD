"""Bill recompute: the two peak-detection variants and the pinned cost chain."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success
from test_helpers import (
    factories as f,
    fixtures as fx,
)
from test_helpers.test_users import make_energy_analyst_headers

JUNE_INTERVALS = [
    f.demand_interval("2026-06-10T18:00:00Z", 1310.5, True),
    f.demand_interval("2026-06-10T02:00:00Z", 1402.0, False),
    f.demand_interval("2026-06-11T18:00:00Z", 1200.0, True),
]

JUNE_BILL = {
    "period_start_iso": "2026-06-01T00:00:00Z",
    "period_end_iso": "2026-07-01T00:00:00Z",
    "on_peak_kwh": 240000,
    "off_peak_kwh": 518000,
    "billed_kwh": 758000,
    "billed_peak_kw": 1402.0,
    "billed_amount_usd": 102500.00,
}

RATES = {
    "utility_name": "Midland Power",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
    "ratchet_peak_kw": 1500.0,
}


def _account_with_june_data(api, store_id, rate_family, rate_schedule_code):
    """One account on the store, the same three June intervals and the same bill."""
    account = fx.create_account(
        api,
        store_id,
        rate_family=rate_family,
        rate_schedule_code=rate_schedule_code,
        **RATES,
    )
    fx.ingest_intervals(api, account["id"], JUNE_INTERVALS)
    bill = fx.create_bill(api, account["id"], **JUNE_BILL)
    return account, bill


class TestPeakBasisVariantDivergence:
    def test_time_of_use_account_bills_the_coincident_peak(self, api):
        """A TOU_DEMAND recompute ranks only the on-peak intervals.

        The PRD states: "On a `TOU_DEMAND` account the system takes the
        **coincident peak**: it narrows that set to intervals whose `is_on_peak`
        is true, ranks them by `kw_demand` descending, breaking ties by earlier
        `interval_start_iso` and then by earlier `created_at`, takes the
        `kw_demand` of the first ranked interval as the observed peak, and
        records `peak_basis` as `COINCIDENT_PEAK`."

        Design: Difficulty/dual_variant_calc/bill_peak_basis_variant_divergence_on_utility_bill
        """
        ctx = fx.setup_commissioned_store(api, code="STR-DV1")
        _, bill = _account_with_june_data(api, ctx["store_id"], "TOU_DEMAND", "TOU-GS3")

        recomputed = get_success_data(
            api.recompute_utility_bill(bill["id"], make_energy_analyst_headers("u_analyst_dv1"))
        )

        assert recomputed["peak_basis"] == "COINCIDENT_PEAK"
        assert recomputed["billable_demand_kw"] == pytest.approx(1310.5, abs=0.01)
        assert recomputed["recomputed_energy_cost_usd"] == pytest.approx(76240.00, abs=0.01)
        assert recomputed["recomputed_demand_cost_usd"] == pytest.approx(19002.25, abs=0.01)
        assert recomputed["recomputed_rider_cost_usd"] == pytest.approx(3571.58, abs=0.01)
        assert recomputed["recomputed_surcharge_usd"] == pytest.approx(1182.21, abs=0.01)
        assert recomputed["recomputed_amount_usd"] == pytest.approx(99996.04, abs=0.01)
        assert recomputed["variance_pct"] == pytest.approx(2.50, abs=0.01)
        assert recomputed["validation_state"] == "VARIANCE_FLAGGED"
        assert recomputed["recomputed_by_user_id"] == "u_analyst_dv1"

    def test_flat_account_bills_the_anytime_peak_over_the_same_intervals(self, api):
        """A FLAT_DEMAND recompute ranks off-peak intervals too.

        The PRD states: "On a `FLAT_DEMAND` account it takes the **anytime
        peak** instead: the whole candidate set is eligible, on-peak and
        off-peak intervals alike, ranked by the identical three-key ordering,
        and `peak_basis` is recorded as `ANYTIME_PEAK`."

        Design: Difficulty/dual_variant_calc/bill_peak_basis_variant_divergence_on_utility_bill
        """
        ctx = fx.setup_commissioned_store(api, code="STR-DV1")
        _, bill = _account_with_june_data(api, ctx["store_id"], "FLAT_DEMAND", "FLAT-GS3")

        recomputed = get_success_data(
            api.recompute_utility_bill(bill["id"], make_energy_analyst_headers("u_analyst_dv1"))
        )

        assert recomputed["peak_basis"] == "ANYTIME_PEAK"
        assert recomputed["billable_demand_kw"] == pytest.approx(1402.0, abs=0.01)
        assert recomputed["recomputed_energy_cost_usd"] == pytest.approx(76240.00, abs=0.01)
        assert recomputed["recomputed_demand_cost_usd"] == pytest.approx(20329.00, abs=0.01)
        assert recomputed["recomputed_rider_cost_usd"] == pytest.approx(3621.34, abs=0.01)
        assert recomputed["recomputed_surcharge_usd"] == pytest.approx(1202.86, abs=0.01)
        assert recomputed["recomputed_amount_usd"] == pytest.approx(101393.20, abs=0.01)
        assert recomputed["variance_pct"] == pytest.approx(1.09, abs=0.01)
        assert recomputed["validation_state"] == "VALIDATED"

    def test_identical_metering_diverges_by_the_family_alone(self, api):
        """Two accounts differing only in rate_family reach different outcomes.

        The PRD states: "classifies that tariff by `rate_family` — either
        `TOU_DEMAND` for a time-of-use tariff or `FLAT_DEMAND` for a flat one, a
        choice that decides which peak-detection variant every recompute will
        use."

        Design: Difficulty/dual_variant_calc/bill_peak_basis_variant_divergence_on_utility_bill
        """
        ctx = fx.setup_commissioned_store(api, code="STR-DV1")
        _, tou_bill = _account_with_june_data(api, ctx["store_id"], "TOU_DEMAND", "TOU-GS3")
        _, flat_bill = _account_with_june_data(api, ctx["store_id"], "FLAT_DEMAND", "FLAT-GS3")

        analyst = make_energy_analyst_headers("u_analyst_dv1")
        tou = get_success_data(api.recompute_utility_bill(tou_bill["id"], analyst))
        flat = get_success_data(api.recompute_utility_bill(flat_bill["id"], analyst))

        # The same consumption prices identically; only demand diverges.
        assert tou["recomputed_energy_cost_usd"] == pytest.approx(
            flat["recomputed_energy_cost_usd"], abs=0.01
        )
        assert flat["recomputed_amount_usd"] - tou["recomputed_amount_usd"] == pytest.approx(
            1397.16, abs=0.01
        )
        assert tou["validation_state"] == "VARIANCE_FLAGGED"
        assert flat["validation_state"] == "VALIDATED"


class TestRiderThenSurchargeEvaluationOrder:
    def test_rider_is_charged_on_the_base_subtotal_alone(self, api):
        """The rider is 0.0375 of energy plus demand, never of the surcharge.

        The PRD states: "The fifth step applies the regulatory rider at a rate
        of three and three-quarter percent — 0.0375 — of that base subtotal,
        rounded half up to two decimal places and stored as
        `recomputed_rider_cost_usd`; the rider is computed on the base subtotal
        alone and never on the surcharge."

        Design: Difficulty/combinatorial_formula/bill_rider_then_surcharge_evaluation_order_pinned
        """
        ctx = fx.setup_commissioned_store(api, code="STR-CF1")
        account = fx.create_account(
            api, ctx["store_id"], rate_family="TOU_DEMAND",
            rate_schedule_code="TOU-GS3", **RATES,
        )
        fx.ingest_intervals(
            api, account["id"], [f.demand_interval("2026-06-10T18:00:00Z", 1310.5, True)]
        )
        bill = fx.create_bill(
            api, account["id"], **{**JUNE_BILL, "billed_peak_kw": 1310.5,
                                   "billed_amount_usd": 99996.04},
        )

        recomputed = fx.recompute_bill(api, bill["id"])

        base_subtotal = (
            recomputed["recomputed_energy_cost_usd"] + recomputed["recomputed_demand_cost_usd"]
        )
        assert base_subtotal == pytest.approx(95242.25, abs=0.01)
        assert recomputed["recomputed_rider_cost_usd"] == pytest.approx(3571.58, abs=0.01)
        # Charging the rider on the pre-surcharge total would give 3705.52.
        assert recomputed["recomputed_rider_cost_usd"] != pytest.approx(3705.52, abs=0.01)

    def test_surcharge_applies_only_to_the_excess_over_twenty_thousand(self, api):
        """The surcharge is 0.015 of the pre-surcharge total above 20000.00.

        The PRD states: "The seventh step applies the high-usage surcharge: when
        the pre-surcharge total is below twenty thousand dollars the surcharge is
        0.00, and otherwise it is one and a half percent — 0.015 — of the amount
        by which the pre-surcharge total *exceeds* twenty thousand dollars,
        rounded half up to two decimal places; the surcharge is never charged on
        the whole subtotal."

        Design: Difficulty/combinatorial_formula/bill_rider_then_surcharge_evaluation_order_pinned
        """
        ctx = fx.setup_commissioned_store(api, code="STR-CF1")
        account = fx.create_account(
            api, ctx["store_id"], rate_family="TOU_DEMAND",
            rate_schedule_code="TOU-GS3", **RATES,
        )
        fx.ingest_intervals(
            api, account["id"], [f.demand_interval("2026-06-10T18:00:00Z", 1310.5, True)]
        )
        bill = fx.create_bill(
            api, account["id"], **{**JUNE_BILL, "billed_peak_kw": 1310.5,
                                   "billed_amount_usd": 99996.04},
        )

        recomputed = fx.recompute_bill(api, bill["id"])

        pre_surcharge = (
            recomputed["recomputed_energy_cost_usd"]
            + recomputed["recomputed_demand_cost_usd"]
            + recomputed["recomputed_rider_cost_usd"]
        )
        assert pre_surcharge == pytest.approx(98813.83, abs=0.01)
        assert recomputed["recomputed_surcharge_usd"] == pytest.approx(1182.21, abs=0.01)
        # The eighth step: total is the pre-surcharge total plus the surcharge.
        assert recomputed["recomputed_amount_usd"] == pytest.approx(99996.04, abs=0.01)
        assert recomputed["variance_pct"] == pytest.approx(0.00, abs=0.01)
        assert recomputed["validation_state"] == "VALIDATED"

    def test_rider_is_still_charged_when_the_surcharge_is_zero(self, api):
        """Below the threshold the surcharge vanishes but the rider remains.

        The PRD states: "The sixth step adds the rider to the base subtotal to
        form a pre-surcharge total." and "when the pre-surcharge total is below
        twenty thousand dollars the surcharge is 0.00".

        Design: Difficulty/combinatorial_formula/bill_rider_then_surcharge_evaluation_order_pinned
        """
        ctx = fx.setup_commissioned_store(api, code="STR-CF1")
        account = fx.create_account(
            api, ctx["store_id"], rate_family="TOU_DEMAND", rate_schedule_code="TOU-GS3",
            utility_name="Midland Power", demand_charge_per_kw=14.50,
            rate_on_peak=0.1450, rate_off_peak=0.0800, ratchet_peak_kw=0.0,
        )
        fx.ingest_intervals(
            api, account["id"], [f.demand_interval("2026-06-10T18:00:00Z", 500.0, True)]
        )
        bill = fx.create_bill(
            api, account["id"], period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z", on_peak_kwh=40000, off_peak_kwh=60000,
            billed_kwh=100000, billed_peak_kw=500.0, billed_amount_usd=18519.38,
        )

        response = api.recompute_utility_bill(bill["id"], fx.ANALYST)
        recomputed = validate_success(response)

        assert recomputed["recomputed_energy_cost_usd"] == pytest.approx(10600.00, abs=0.01)
        assert recomputed["recomputed_demand_cost_usd"] == pytest.approx(7250.00, abs=0.01)
        assert recomputed["recomputed_rider_cost_usd"] == pytest.approx(669.38, abs=0.01)
        assert recomputed["recomputed_surcharge_usd"] == pytest.approx(0.00, abs=0.01)
        assert recomputed["recomputed_amount_usd"] == pytest.approx(18519.38, abs=0.01)
        assert recomputed["validation_state"] == "VALIDATED"
