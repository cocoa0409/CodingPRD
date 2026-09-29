"""Declared constants, input-set filters and inclusive thresholds in the maths."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success
from test_helpers import factories as f, fixtures as fx
from test_helpers.test_users import (
    make_energy_analyst_headers,
    make_energy_manager_headers,
    make_maintenance_tech_headers,
)

RATCHET_RATES = {
    "utility_name": "Statewide Power",
    "rate_schedule_code": "GS-3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
    "ratchet_peak_kw": 1500.0,
}

RATCHET_INTERVALS = [
    f.demand_interval("2026-06-15T14:00:00Z", 900.0, True),
    f.demand_interval("2026-06-16T14:00:00Z", 850.0, True),
    f.demand_interval("2026-06-16T02:00:00Z", 1100.0, False),
]

RATCHET_BILL = {
    "period_start_iso": "2026-06-01T00:00:00Z",
    "period_end_iso": "2026-07-01T00:00:00Z",
    "on_peak_kwh": 60000,
    "off_peak_kwh": 120000,
    "billed_kwh": 180000,
    "billed_peak_kw": 900.0,
    "billed_amount_usd": 37294.33,
}


def _bill_whose_peak_is_below_the_ratchet_floor(api):
    """A TOU account whose observed on-peak peak of 900.0 kW loses to the floor."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-RT")
    account = fx.create_account(api, store["id"], **RATCHET_RATES)
    fx.ingest_intervals(api, account["id"], RATCHET_INTERVALS)
    bill = fx.create_bill(api, account["id"], **RATCHET_BILL)
    return {"store_id": store["id"], "account_id": account["id"], "bill_id": bill["id"]}


class TestRatchetFloorAndSurchargeExcess:
    def test_the_ratchet_floor_beats_the_observed_coincident_peak(self, api):
        """Eighty percent of the trailing peak becomes billable demand.

        The PRD states: "Whichever variant applied, a ratchet floor is then
        computed as eighty percent of the account's `ratchet_peak_kw`, rounded
        half up to one decimal place, and `billable_demand_kw` becomes the greater
        of the observed peak and that floor, at one decimal place."

        Design: Corner/calculations/bill_recompute_applies_ratchet_floor_and_surcharge_excess
        """
        ctx = _bill_whose_peak_is_below_the_ratchet_floor(api)

        recomputed = get_success_data(
            api.recompute_utility_bill(
                ctx["bill_id"], make_energy_analyst_headers("u_analyst_rt")
            )
        )

        assert recomputed["peak_basis"] == "COINCIDENT_PEAK"
        assert recomputed["billable_demand_kw"] == pytest.approx(1200.0, abs=0.05)
        assert recomputed["recomputed_demand_cost_usd"] == pytest.approx(17400.00, abs=0.01)
        assert recomputed["recomputed_by_user_id"] == "u_analyst_rt"

    def test_the_off_peak_interval_is_ignored_on_a_time_of_use_account(self, api):
        """The 1100.0 kW off-peak row never enters the coincident candidate set.

        The PRD states: "On a `TOU_DEMAND` account the system takes the
        **coincident peak**: it narrows that set to intervals whose `is_on_peak`
        is true, ranks them by `kw_demand` descending, breaking ties by earlier
        `interval_start_iso` and then by earlier `created_at`, takes the
        `kw_demand` of the first ranked interval as the observed peak, and records
        `peak_basis` as `COINCIDENT_PEAK`."

        Design: Corner/calculations/bill_recompute_applies_ratchet_floor_and_surcharge_excess
        """
        ctx = _bill_whose_peak_is_below_the_ratchet_floor(api)

        recomputed = fx.recompute_bill(api, ctx["bill_id"])

        assert recomputed["billable_demand_kw"] != pytest.approx(1100.0, abs=0.05)
        assert recomputed["recomputed_energy_cost_usd"] == pytest.approx(18300.00, abs=0.01)
        rows, meta = fx.list_intervals(api, ctx["account_id"])
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_the_surcharge_is_charged_on_the_excess_alone(self, api):
        """Rider, surcharge and total land on their pinned literals.

        The PRD states: "The seventh step applies the high-usage surcharge: when
        the pre-surcharge total is below twenty thousand dollars the surcharge is
        0.00, and otherwise it is one and a half percent — 0.015 — of the amount
        by which the pre-surcharge total *exceeds* twenty thousand dollars, rounded
        half up to two decimal places; the surcharge is never charged on the whole
        subtotal."

        Design: Corner/calculations/bill_recompute_applies_ratchet_floor_and_surcharge_excess
        """
        ctx = _bill_whose_peak_is_below_the_ratchet_floor(api)

        recomputed = fx.recompute_bill(api, ctx["bill_id"])

        assert recomputed["recomputed_rider_cost_usd"] == pytest.approx(1338.75, abs=0.01)
        assert recomputed["recomputed_surcharge_usd"] == pytest.approx(255.58, abs=0.01)
        # A surcharge charged on the whole pre-surcharge total would be 555.58.
        assert recomputed["recomputed_surcharge_usd"] != pytest.approx(555.58, abs=0.01)
        assert recomputed["recomputed_amount_usd"] == pytest.approx(37294.33, abs=0.01)
        assert recomputed["variance_pct"] == pytest.approx(0.00, abs=0.01)
        assert recomputed["validation_state"] == "VALIDATED"


BASELINE_LOOKBACK = [
    f.demand_interval("2026-08-05T14:00:00Z", 1200.0, True),
    f.demand_interval("2026-08-06T14:00:00Z", 1290.5, True),
    f.demand_interval("2026-08-07T14:00:00Z", 1275.0, True),
    f.demand_interval("2026-08-08T14:00:00Z", 1245.0, True),
    f.demand_interval("2026-08-09T14:00:00Z", 1310.0, True),
    f.demand_interval("2026-08-09T15:00:00Z", 1500.0, True, is_dr_event_day=True),
    f.demand_interval("2026-08-09T03:00:00Z", 1400.0, False),
    f.demand_interval("2026-08-10T15:00:00Z", 1450.0, True),
]


def _event_over_a_decoy_laden_lookback(api):
    """Five eligible on-peak intervals plus three decoys the filters must drop."""
    fx.set_clock(api, "2026-08-09T20:00:00Z")
    store = fx.create_store(api, code="STR-BL")
    account = fx.create_account(api, store["id"])
    fx.ingest_intervals(api, account["id"], BASELINE_LOOKBACK)
    event = fx.create_event(
        api, account["id"], program_code="DR-PEAK-A",
        curtailment_start_iso="2026-08-10T14:00:00Z",
        curtailment_end_iso="2026-08-10T18:00:00Z", target_reduction_kw=200.0,
    )
    return {"account_id": account["id"], "event_id": event["id"]}


class TestBaselineTopThreeOfTheEligibleLookback:
    def test_the_baseline_is_the_mean_of_the_three_highest_eligible_intervals(self, api):
        """Only the top three of the eligible pool are averaged.

        The PRD states: "The candidate pool is every demand interval of the
        event's account whose `is_on_peak` is true, whose `is_dr_event_day` is
        false, and whose `interval_start_iso` is strictly before the event's
        `curtailment_start_iso` — event days are excluded precisely because they
        are already depressed by curtailment. The first pass takes recency:
        candidates are ordered by `interval_start_iso` descending, breaking ties
        by the later `created_at`, and the first ten are retained. The second pass
        takes severity: those retained candidates are ranked by `kw_demand`
        descending, breaking ties by earlier `interval_start_iso` and then by
        earlier `created_at`, and the first three are kept — or however many
        exist, if fewer than three survived the first pass."

        Design: Corner/calculations/dr_baseline_uses_top_three_of_the_eligible_lookback
        """
        ctx = _event_over_a_decoy_laden_lookback(api)

        notified = get_success_data(api.notify_demand_response_event(ctx["event_id"], fx.MANAGER))

        assert notified["event_state"] == "NOTIFIED"
        assert notified["notified_at_iso"].startswith("2026-08-09T20:00:00")
        assert notified["baseline_kw"] == pytest.approx(1291.83, abs=0.01)
        # Averaging all five eligible rows instead of the top three gives 1264.10.
        assert notified["baseline_kw"] != pytest.approx(1264.10, abs=0.01)

    def test_the_three_decoy_intervals_never_reach_the_candidate_pool(self, api):
        """An event-day row, an off-peak row and a post-start row are all excluded.

        The PRD states: "`is_dr_event_day`, which defaults to false and marks
        intervals that fall on a demand-response event day so they can be excluded
        from baseline candidacy."

        Design: Corner/calculations/dr_baseline_uses_top_three_of_the_eligible_lookback
        """
        ctx = _event_over_a_decoy_laden_lookback(api)

        notified = get_success_data(api.notify_demand_response_event(ctx["event_id"], fx.MANAGER))

        # Any decoy entering the pool would lift the mean above 1291.83.
        assert notified["baseline_kw"] < 1300.0
        assert notified["settlement_state"] == "PENDING"
        assert notified["total_reduction_kwh"] is None
        assert notified["performance_pct"] is None
        assert notified["incentive_usd"] == pytest.approx(0.00, abs=0.01)
        assert notified["penalty_usd"] == pytest.approx(0.00, abs=0.01)

    def test_notification_consumes_the_intervals_without_mutating_them(self, api):
        """All eight rows survive the notification untouched.

        The PRD states: "Ingestion never triggers a bill recompute; validation is
        always an explicit act."

        Design: Corner/calculations/dr_baseline_uses_top_three_of_the_eligible_lookback
        """
        ctx = _event_over_a_decoy_laden_lookback(api)

        get_success_data(api.notify_demand_response_event(ctx["event_id"], fx.MANAGER))

        rows, meta = fx.list_intervals(api, ctx["account_id"])
        assert meta["total_count"] == 8
        assert len(rows) == 8
        assert sorted(row["kw_demand"] for row in rows) == [
            1200.0, 1245.0, 1275.0, 1290.5, 1310.0, 1400.0, 1450.0, 1500.0
        ]


BENCH_RATES = {
    "rate_schedule_code": "GS-3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
}

# code, on-peak kWh, off-peak kWh, billed kWh, peak kW, exact recomputed total.
BENCH_SPECS = [
    ("1", 36000, 54000, 90000, 300.0, 14410.88),
    ("2", 40000, 60000, 100000, 330.0, 15961.94),
    ("3", 144000, 216000, 360000, 1200.0, 58208.15),
    ("4", 52000, 78000, 130000, 420.0, 20624.36),
]


def _benchmark_peer_group(api, prefix, climate_zone, store_format, utility_name,
                          recompute_codes):
    """Four 40000 sqft stores of one peer group, each with a single June bill whose
    billed_amount_usd already equals its exact recomputed total."""
    fx.set_clock(api)
    store_ids = {}
    for suffix, on_peak, off_peak, billed, peak, amount in BENCH_SPECS:
        code = prefix + suffix
        store = fx.create_store(
            api, code=code, climate_zone=climate_zone, store_format=store_format,
            floor_area_sqft=40000,
        )
        account = fx.create_account(
            api, store["id"], utility_name=utility_name, **BENCH_RATES
        )
        fx.ingest_intervals(
            api, account["id"],
            [f.demand_interval("2026-06-15T14:00:00Z", peak, True)],
        )
        bill = fx.create_bill(
            api, account["id"], period_start_iso="2026-06-01T00:00:00Z",
            period_end_iso="2026-07-01T00:00:00Z", on_peak_kwh=on_peak,
            off_peak_kwh=off_peak, billed_kwh=billed, billed_peak_kw=peak,
            billed_amount_usd=amount,
        )
        if code in recompute_codes:
            recomputed = fx.recompute_bill(api, bill["id"])
            assert recomputed["validation_state"] == "VALIDATED"
            assert recomputed["variance_pct"] == pytest.approx(0.00, abs=0.01)
        else:
            assert bill["validation_state"] == "RECEIVED"
        store_ids[code] = store["id"]
    return store_ids


def _row_for(report, store_id):
    matches = [row for row in report["stores"] if row["store_id"] == store_id]
    assert len(matches) == 1
    return matches[0]


ALL_BM = ["STR-BM1", "STR-BM2", "STR-BM3", "STR-BM4"]


def _mixed_supercenter_group(api):
    return _benchmark_peer_group(
        api, "STR-BM", "MIXED", "SUPERCENTER", "Statewide Power", ALL_BM
    )


class TestPeerMedianIsComputedPerStore:
    def test_the_low_and_high_stores_see_different_leave_one_out_medians(self, api):
        """Each store's median is taken over the other peers, not the whole group.

        The PRD states: "The comparison set, however, excludes the subject: the
        peer median reported as `peer_median_eui` is the central value of the other
        peers sorted by intensity ascending with ties broken by earlier
        `created_at`, and where the number of other peers is even it is the mean of
        the two central values rounded half up to two decimal places."

        Design: Corner/calculations/benchmark_eui_percentile_and_per_store_outlier_threshold
        """
        stores = _mixed_supercenter_group(api)

        report = get_success_data(
            api.get_benchmark_report(
                make_energy_analyst_headers("u_analyst_bm"),
                {"climate_zone": "MIXED", "store_format": "SUPERCENTER"},
            )
        )

        assert report["climate_zone"] == "MIXED"
        assert report["store_format"] == "SUPERCENTER"
        assert len(report["stores"]) == 4
        bm1 = _row_for(report, stores["STR-BM1"])
        bm3 = _row_for(report, stores["STR-BM3"])
        assert bm1["code"] == "STR-BM1"
        assert bm1["eui_kbtu_per_sqft"] == pytest.approx(7.68, abs=0.01)
        assert bm1["peer_median_eui"] == pytest.approx(11.09, abs=0.01)
        assert bm1["outlier_threshold_eui"] == pytest.approx(14.42, abs=0.01)
        assert bm1["benchmark_outlier_flag"] is False
        assert bm3["eui_kbtu_per_sqft"] == pytest.approx(30.71, abs=0.01)
        assert bm3["peer_median_eui"] == pytest.approx(8.53, abs=0.01)
        assert bm3["outlier_threshold_eui"] == pytest.approx(11.09, abs=0.01)
        assert bm3["benchmark_outlier_flag"] is True

    def test_the_borderline_store_on_its_own_threshold_is_an_outlier(self, api):
        """An intensity exactly equal to the threshold counts as an outlier.

        The PRD states: "`outlier_threshold_eui` is 1.30 times that median,
        rounded half up to two decimal places, and `benchmark_outlier_flag` is true
        when the store's own intensity is at or above that threshold — the boundary
        counts as an outlier."

        Design: Corner/calculations/benchmark_eui_percentile_and_per_store_outlier_threshold
        """
        stores = _mixed_supercenter_group(api)

        report = get_success_data(
            api.get_benchmark_report(
                make_energy_analyst_headers("u_analyst_bm"),
                {"climate_zone": "MIXED", "store_format": "SUPERCENTER"},
            )
        )

        bm4 = _row_for(report, stores["STR-BM4"])
        assert bm4["eui_kbtu_per_sqft"] == pytest.approx(11.09, abs=0.01)
        assert bm4["outlier_threshold_eui"] == pytest.approx(11.09, abs=0.01)
        assert bm4["benchmark_outlier_flag"] is True
        assert report["outlier_count"] == 2

    def test_the_whole_group_median_is_context_only_and_differs_again(self, api):
        """The group median is a fourth number and gates nothing.

        The PRD states: "the report echoes the requested `climate_zone` and
        `store_format` and adds `peer_group_count`, `outlier_count`, and
        `peer_group_median_eui`, which is the median over the whole group including
        every member and is reported for context only rather than used in any
        threshold."

        Design: Corner/calculations/benchmark_eui_percentile_and_per_store_outlier_threshold
        """
        stores = _mixed_supercenter_group(api)

        report = get_success_data(
            api.get_benchmark_report(
                make_energy_analyst_headers("u_analyst_bm"),
                {"climate_zone": "MIXED", "store_format": "SUPERCENTER"},
            )
        )

        assert report["peer_group_count"] == 4
        assert report["peer_group_median_eui"] == pytest.approx(9.81, abs=0.01)
        for code, expected_percentile in (
            ("STR-BM1", 25.0), ("STR-BM2", 50.0), ("STR-BM3", 100.0), ("STR-BM4", 75.0)
        ):
            row = _row_for(report, stores[code])
            assert row["benchmark_percentile"] == pytest.approx(expected_percentile, abs=0.05)
        # No store's threshold was taken from the whole-group median.
        thresholds = sorted(row["outlier_threshold_eui"] for row in report["stores"])
        assert thresholds == pytest.approx([11.09, 11.09, 14.42, 14.42], abs=0.01)


def _marine_group_with_one_unvalidated_bill(api):
    """The same four-store portfolio except that STR-BF2's bill is never
    recomputed, so it stays in RECEIVED."""
    return _benchmark_peer_group(
        api, "STR-BF", "MARINE", "NEIGHBORHOOD", "Coastal Power",
        ["STR-BF1", "STR-BF3", "STR-BF4"],
    )


MARINE_QUERY = {"climate_zone": "MARINE", "store_format": "NEIGHBORHOOD"}


class TestUnvalidatedBillsNeverInfluenceTheBenchmark:
    def test_a_received_bill_leaves_its_store_out_of_the_peer_group(self, api):
        """The store with only a RECEIVED bill has a null intensity.

        The PRD states: "Bills still `RECEIVED`, `VARIANCE_FLAGGED` or `DISPUTED`
        are excluded — an unvalidated invoice never influences a benchmark."

        Design: Corner/calculations/benchmark_excludes_bills_that_are_not_validated
        """
        stores = _marine_group_with_one_unvalidated_bill(api)

        report = get_success_data(
            api.get_benchmark_report(
                make_energy_manager_headers("u_manager_bf"), MARINE_QUERY
            )
        )

        assert report["peer_group_count"] == 3
        assert report["peer_group_median_eui"] == pytest.approx(11.09, abs=0.01)
        assert report["outlier_count"] == 1
        # All four stores of the peer-group scope are reported; only the three
        # with a non-null intensity are peer-group members.
        assert len(report["stores"]) == 4
        bf2 = _row_for(report, stores["STR-BF2"])
        assert bf2["eui_kbtu_per_sqft"] is None
        assert bf2["benchmark_percentile"] is None
        assert bf2["benchmark_outlier_flag"] is False

    def test_dropping_one_peer_flips_the_borderline_outlier_verdict(self, api):
        """With three peers the borderline store's threshold rises out of reach.

        The PRD states: "The peer group of a store is every store sharing its
        `climate_zone` and `store_format` and having a non-null intensity,
        *including* the subject store itself; a store with a null intensity is in
        nobody's peer group, not even its own group's count."

        Design: Corner/calculations/benchmark_excludes_bills_that_are_not_validated
        """
        stores = _marine_group_with_one_unvalidated_bill(api)

        report = get_success_data(
            api.get_benchmark_report(
                make_energy_manager_headers("u_manager_bf"), MARINE_QUERY
            )
        )

        bf4 = _row_for(report, stores["STR-BF4"])
        assert bf4["eui_kbtu_per_sqft"] == pytest.approx(11.09, abs=0.01)
        assert bf4["peer_median_eui"] == pytest.approx(19.20, abs=0.01)
        assert bf4["outlier_threshold_eui"] == pytest.approx(24.96, abs=0.01)
        assert bf4["benchmark_outlier_flag"] is False
        assert bf4["benchmark_percentile"] == pytest.approx(66.7, abs=0.05)

    def test_the_outliers_only_flag_narrows_the_reported_store_list(self, api):
        """Only the flagged store is reported, with the group figures unchanged.

        The PRD states: "The report is always scoped to one peer group, so it
        requires both `climate_zone` and `store_format` as query parameters, and
        accepts an optional `outliers_only` flag that narrows the reported store
        list to flagged stores only."

        Design: Corner/calculations/benchmark_excludes_bills_that_are_not_validated
        """
        stores = _marine_group_with_one_unvalidated_bill(api)

        report = get_success_data(
            api.get_benchmark_report(
                make_energy_manager_headers("u_manager_bf"),
                {**MARINE_QUERY, "outliers_only": "true"},
            )
        )

        assert report["peer_group_count"] == 3
        assert report["outlier_count"] == 1
        assert len(report["stores"]) == 1
        only = report["stores"][0]
        assert only["store_id"] == stores["STR-BF3"]
        assert only["eui_kbtu_per_sqft"] == pytest.approx(30.71, abs=0.01)
        assert only["peer_median_eui"] == pytest.approx(9.39, abs=0.01)
        assert only["outlier_threshold_eui"] == pytest.approx(12.21, abs=0.01)
        assert only["benchmark_outlier_flag"] is True
        assert only["benchmark_percentile"] == pytest.approx(100.0, abs=0.05)


FAULT_B = {
    "equipment_ref": "CASE-12",
    "equipment_class": "REFRIGERATION",
    "fault_code": "DEFROST-SHORT",
    "severity": "MINOR",
    "occurrence_count": 4,
    "affected_load_kw": 50.0,
}

FAULT_C = {
    "equipment_ref": "RACK-B",
    "equipment_class": "REFRIGERATION",
    "fault_code": "COMP-TRIP",
    "severity": "CRITICAL",
    "occurrence_count": 6,
    "affected_load_kw": 50.0,
}

FAULT_A = {
    "equipment_ref": "AHU-3",
    "equipment_class": "HVAC",
    "fault_code": "VFD-FAULT",
    "severity": "CRITICAL",
    "occurrence_count": 1,
    "affected_load_kw": 0.0,
}


def _store_with_two_scored_refrigeration_faults(api):
    """A commissioned store carrying the persistence-and-load fault and the
    overflowing fault, both still DETECTED."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T08:00:00Z", code="STR-FS", floor_area_sqft=120000
    )
    ctx["fault_b"] = fx.create_fault(api, ctx["store_id"], **FAULT_B)
    ctx["fault_c"] = fx.create_fault(api, ctx["store_id"], **FAULT_C)
    return ctx


class TestFaultScoreWeightingChain:
    def test_the_load_multiplier_takes_its_cap_and_refrigeration_takes_the_premium(self, api):
        """A four-occurrence 50.0 kW refrigeration fault scores 47.5.

        The PRD states: "Affected load contributes a second multiplier: one plus
        the `affected_load_kw` divided by 200.0, rounded half up to four decimal
        places, and then capped at 1.25, so any fault affecting 50.0 kW or more
        takes the cap."

        Design: Corner/calculations/fault_score_weighting_chain_and_inclusive_urgent_threshold
        """
        ctx = _store_with_two_scored_refrigeration_faults(api)

        assert ctx["fault_b"]["state"] == "DETECTED"
        assert ctx["fault_b"]["fault_score"] == pytest.approx(47.5, abs=0.05)

    def test_the_overflowing_score_is_clamped_to_the_ceiling(self, api):
        """A six-occurrence CRITICAL refrigeration fault reports 100.0, not 146.3.

        The PRD states: "Finally `fault_score` is that result rounded half up to
        one decimal place and capped at 100.0."

        Design: Corner/calculations/fault_score_weighting_chain_and_inclusive_urgent_threshold
        """
        ctx = _store_with_two_scored_refrigeration_faults(api)

        assert ctx["fault_c"]["fault_score"] == pytest.approx(100.0, abs=0.05)
        assert ctx["fault_c"]["fault_score"] <= 100.0

    def test_a_score_of_exactly_seventy_raises_an_urgent_order(self, api):
        """The URGENT threshold is inclusive at 70.0 with no rounding cushion.

        The PRD states: "A work order raised from the fault is `URGENT` when
        `fault_score` is at or above 70.0 and `ROUTINE` otherwise, so a score of
        exactly 70.0 is urgent."

        Design: Corner/calculations/fault_score_weighting_chain_and_inclusive_urgent_threshold
        """
        ctx = _store_with_two_scored_refrigeration_faults(api)

        fault_a = get_success_data(
            api.create_fault_diagnostic(
                ctx["store_id"], f.create_fault_diagnostic_payload(**FAULT_A),
                make_maintenance_tech_headers("u_tech_fs"),
            ),
            201,
        )
        triage = get_success_data(
            api.triage_fault(
                fault_a["id"], f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_fs"),
            )
        )

        assert fault_a["state"] == "DETECTED"
        assert fault_a["fault_score"] == pytest.approx(70.0, abs=0.05)
        assert triage["fault_state"] == "TRIAGED"
        assert triage["work_order_priority"] == "URGENT"
        assert triage["urgent_work_order_count"] == 1

    def test_an_hvac_fault_takes_no_premium_and_leaves_the_gateway_active(self, api):
        """No food-safety premium and no degrade for a non-refrigeration class.

        The PRD states: "Refrigeration equipment then attracts a flat food-safety
        premium of 15.00 points added to the loaded figure, while `HVAC` and
        `LIGHTING` faults take no premium."

        Design: Corner/calculations/fault_score_weighting_chain_and_inclusive_urgent_threshold
        """
        ctx = _store_with_two_scored_refrigeration_faults(api)

        fault_a = fx.create_fault(
            api, ctx["store_id"], headers=make_maintenance_tech_headers("u_tech_fs"), **FAULT_A
        )
        triage = get_success_data(
            api.triage_fault(
                fault_a["id"], f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_fs"),
            )
        )

        # With the premium the same fault would have scored 85.0.
        assert fault_a["fault_score"] != pytest.approx(85.0, abs=0.05)
        assert triage["store_bms_status"] == "ACTIVE"
        assert triage["store_energy_posture"] == "CONSTRAINED"


MV_PROJECT = {
    "measure_type": "ECM_MOTORS",
    "capex_usd": 260000.00,
    "projected_annual_savings_kwh": 520000.00,
}

SHORTFALL_MEASUREMENT = {
    "install_completed_iso": "2026-07-01T00:00:00Z",
    "baseline_period_kwh": 300000.00,
    "post_period_kwh": 260000.00,
    "mv_period_days": 90,
}

EXACT_FLOOR_MEASUREMENT = {**SHORTFALL_MEASUREMENT, "post_period_kwh": 221424.66}


def _hot_humid_project_already_in_shortfall(api):
    """An approved project on a HOT_HUMID store whose first measurement realised
    only 0.4991 and credited nothing."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-MV", climate_zone="HOT_HUMID", floor_area_sqft=120000
    )
    project = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_mv", **MV_PROJECT
    )
    ctx["project_id"] = project["id"]
    ctx["proposed"] = project
    ctx["approved"] = fx.decide_retrofit(
        api, project["id"], "APPROVE", approver_user_id="u_mgr_mv"
    )
    ctx["shortfall"] = fx.submit_measurement(
        api, project["id"], **SHORTFALL_MEASUREMENT
    )
    ctx["store_after_shortfall"] = fx.read_store(api, ctx["store_id"])
    return ctx


class TestVerificationFloorIsInclusive:
    def test_the_climate_factor_normalises_the_baseline_before_anything_is_credited(self, api):
        """A HOT_HUMID baseline is lifted by 1.08 and the promise is prorated.

        The PRD states: "A `HOT_HUMID` store with a 300000.00 kWh baseline over a
        ninety-day post period against a 520000.00 kWh annual projection therefore
        has an adjusted baseline of 324000.00 kWh and a prorated expectation of
        128219.18 kWh."

        Design: Corner/calculations/measured_savings_verification_floor_is_inclusive
        """
        ctx = _hot_humid_project_already_in_shortfall(api)

        assert ctx["proposed"]["priority_basis"] == "SIMPLE_PAYBACK"
        assert ctx["proposed"]["priority_score"] == pytest.approx(54.5, abs=0.05)
        assert ctx["approved"]["priority_basis"] == "RISK_ADJUSTED"
        assert ctx["approved"]["priority_score"] == pytest.approx(46.5, abs=0.05)
        assert ctx["shortfall"]["adjusted_baseline_kwh"] == pytest.approx(324000.00, abs=0.01)
        assert ctx["shortfall"]["measured_savings_kwh"] == pytest.approx(64000.00, abs=0.01)
        assert ctx["shortfall"]["realization_rate"] == pytest.approx(0.4991, abs=0.0001)

    def test_a_rate_below_the_floor_credits_nothing_to_the_ledger(self, api):
        """The shortfall branch leaves the ledger at zero.

        The PRD states: "When `realization_rate` falls below 0.8000 the project
        moves to `SHORTFALL_REVIEW` instead and nothing whatsoever is credited to
        the ledger."

        Design: Corner/calculations/measured_savings_verification_floor_is_inclusive
        """
        ctx = _hot_humid_project_already_in_shortfall(api)

        assert ctx["shortfall"]["state"] == "SHORTFALL_REVIEW"
        assert ctx["store_after_shortfall"]["verified_savings_kwh_ytd"] == pytest.approx(
            0.00, abs=0.001
        )
        assert ctx["store_after_shortfall"]["portfolio_realization_rate"] == pytest.approx(
            0.4991, abs=0.0001
        )

    def test_a_rate_of_exactly_the_floor_verifies_and_credits_once(self, api):
        """0.8000 verifies and the ledger carries no residue of the shortfall.

        The PRD states: "When `realization_rate` is at or above 0.8000 the project
        moves to `VERIFIED` and the store's `verified_savings_kwh_ytd` is credited
        by exactly `measured_savings_kwh`; a rate of precisely 0.8000 verifies,
        because the floor is inclusive."

        Design: Corner/calculations/measured_savings_verification_floor_is_inclusive
        """
        ctx = _hot_humid_project_already_in_shortfall(api)

        verified = validate_success(
            api.submit_retrofit_measurement(
                ctx["project_id"], EXACT_FLOOR_MEASUREMENT,
                make_energy_analyst_headers("u_analyst_mv"),
            )
        )
        store = fx.read_store(api, ctx["store_id"])

        assert verified["adjusted_baseline_kwh"] == pytest.approx(324000.00, abs=0.01)
        assert verified["measured_savings_kwh"] == pytest.approx(102575.34, abs=0.01)
        assert verified["realization_rate"] == pytest.approx(0.8000, abs=0.0001)
        assert verified["state"] == "VERIFIED"
        assert store["verified_savings_kwh_ytd"] == pytest.approx(102575.34, abs=0.001)
        assert store["portfolio_realization_rate"] == pytest.approx(0.8000, abs=0.0001)


SALES_FLOOR_OVERRIDE = {
    "zone": "SALES_FLOOR",
    "override_type": "SCHEDULE_EXTEND",
    "start_iso": "2026-08-01T10:00:00Z",
    "end_iso": "2026-08-01T16:00:00Z",
    "zone_load_kw": 25.0,
    "requested_reason": "night inventory count",
}

PARKING_OVERRIDE = {
    "zone": "PARKING",
    "override_type": "OCCUPANCY_DISABLE",
    "start_iso": "2026-08-01T10:00:00Z",
    "end_iso": "2026-08-01T17:30:00Z",
    "zone_load_kw": 40.0,
    "requested_reason": "lot restriping",
}


def _store_with_two_live_overrides(api):
    """A commissioned store on the default 500.00 kWh allowance holding a six-hour
    and a seven-and-a-half-hour override in two different zones."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T12:00:00Z", code="STR-OV", floor_area_sqft=120000
    )
    ctx["override_1"] = fx.create_override(api, ctx["store_id"], **SALES_FLOOR_OVERRIDE)
    ctx["override_2"] = fx.create_override(api, ctx["store_id"], **PARKING_OVERRIDE)
    ctx["store_after_creates"] = fx.read_store(api, ctx["store_id"])
    return ctx


class TestOverrideProjectionChargesAndReleasesTheBudget:
    def test_a_seven_and_a_half_hour_window_keeps_its_exact_elapsed_minutes(self, api):
        """The window length is not rounded to whole hours.

        The PRD states: "Within the cap, the energy the override will consume is
        projected as `projected_kwh`: the exact elapsed minutes of the window
        divided by sixty, kept exact rather than rounded, multiplied by
        `zone_load_kw`, with the product rounded half up to two decimal places."

        Design: Corner/calculations/lighting_override_projection_charges_and_releases_the_budget
        """
        ctx = _store_with_two_live_overrides(api)

        assert ctx["override_1"]["projected_kwh"] == pytest.approx(150.00, abs=0.01)
        assert ctx["override_1"]["state"] == "ACTIVE"
        assert ctx["override_2"]["projected_kwh"] == pytest.approx(300.00, abs=0.01)
        assert ctx["override_2"]["state"] == "ACTIVE"
        # Rounding 7.5 hours up to eight would have projected 320.00.
        assert ctx["override_2"]["projected_kwh"] != pytest.approx(320.00, abs=0.01)

    def test_both_projections_are_charged_against_the_monthly_allowance(self, api):
        """The store's monthly usage accumulates across zones.

        The PRD states: "A store's `override_kwh_used_month` is the sum of
        `projected_kwh` across that store's overrides whose `state` is `SCHEDULED`,
        `ACTIVE` or `EXPIRED` and whose `start_iso` falls inside the calendar month,
        in UTC, of the current logical clock."

        Design: Corner/calculations/lighting_override_projection_charges_and_releases_the_budget
        """
        ctx = _store_with_two_live_overrides(api)

        assert ctx["store_after_creates"]["override_kwh_used_month"] == pytest.approx(
            450.00, abs=0.01
        )
        assert ctx["store_after_creates"]["override_budget_kwh_month"] == pytest.approx(
            500.00, abs=0.01
        )

    def test_a_user_revocation_releases_the_projection_without_zeroing_it(self, api):
        """The revoked row keeps its 150.00 but drops out of the monthly sum.

        The PRD states: "Only `REVOKED` rows drop out of the sum, which is
        precisely how a revocation releases budget."

        Design: Corner/calculations/lighting_override_projection_charges_and_releases_the_budget
        """
        ctx = _store_with_two_live_overrides(api)

        revoked = validate_success(
            api.revoke_lighting_override(
                ctx["override_1"]["id"], make_energy_manager_headers("u_mgr_ov")
            )
        )
        store = fx.read_store(api, ctx["store_id"])
        active_rows, active_meta = fx.list_overrides(api, ctx["store_id"], state="ACTIVE")
        revoked_rows, revoked_meta = fx.list_overrides(api, ctx["store_id"], state="REVOKED")

        assert revoked["state"] == "REVOKED"
        assert revoked["revoke_source"] == "USER"
        assert revoked["revoked_by_user_id"] == "u_mgr_ov"
        assert revoked["projected_kwh"] == pytest.approx(150.00, abs=0.01)
        assert store["override_kwh_used_month"] == pytest.approx(300.00, abs=0.01)
        assert active_meta["total_count"] == 1
        assert active_rows[0]["id"] == ctx["override_2"]["id"]
        assert revoked_meta["total_count"] == 1
        assert revoked_rows[0]["id"] == ctx["override_1"]["id"]
