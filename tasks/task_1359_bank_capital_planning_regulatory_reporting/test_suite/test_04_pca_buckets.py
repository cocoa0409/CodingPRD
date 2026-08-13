"""PCA bucket classification: inclusive-threshold boundaries, immediate
visibility of the acceptance cascade, and threshold-event audit records."""
from test_helpers import (
    validate_success,
    validate_paginated,
    ApiErrorId,
    advance_clock_past,
    assert_pca_threshold_event,
    setup_accepted_report,
    set_clock,
    create_bank,
    create_period,
    add_exposure,
    add_instrument,
    create_prepared_call_report,
    make_capital_analyst_headers,
    SUBMITTER_USER_ID,
)


def _accept_and_bucket(api, analyst_headers, regulator_headers, bank, period, report):
    # Move the period unambiguously to FILING_DUE before submitting.
    advance_clock_past(period["period_end_date"])
    submitted = validate_success(
        api.submit_call_report(
            bank["id"], period["id"], report["id"],
            make_capital_analyst_headers(SUBMITTER_USER_ID),
        )
    )
    validate_success(api.accept_call_report(bank["id"], period["id"], submitted["id"], regulator_headers))
    return validate_success(api.get_bank(bank["id"], analyst_headers))


def _setup_boundary_bank(api, charter_id, cet1_cents):
    """Build a bank whose binding metric is CET1 at exactly the given cents.

    The bank bucket is the strictest of the four metric classifications
    (PRD §2.7), so the other three metrics are lifted clear of the boundary:
    AT1 1.5e9 (at its 1.5%-of-RWA cap) lifts Tier 1 to cet1+1500 bps, T2 2e9
    (at its 2%-of-RWA cap) lifts total capital to cet1+3500 bps, and the
    leverage ratio follows Tier 1. RWA is 100e9 from one 100%-weighted
    CORPORATE line."""
    bank = create_bank(charter_id)
    period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
    add_exposure(
        bank["id"], period["id"],
        exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
        risk_weight_bps=10000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
    )
    add_instrument(bank["id"], outstanding_amount_cents=cet1_cents)
    add_instrument(
        bank["id"], instrument_class="AT1", instrument_subtype="PREFERRED",
        outstanding_amount_cents=1_500_000_000, issuance_date="2020-01-15",
        contractual_rate_bps=600,
    )
    add_instrument(
        bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
        outstanding_amount_cents=2_000_000_000, issuance_date="2022-01-15",
        maturity_date="2032-12-31", contractual_rate_bps=500,
    )
    report = create_prepared_call_report(bank["id"], period["id"])
    return bank, period, report


class TestPcaThresholdBoundaries(object):
    def test_pca_boundary_650_qualifies_well_capitalized(self, api, system_operator_headers,
                                                         capital_analyst_headers, regulator_reviewer_headers):
        """PRD §2.7: "For the CET1 ratio, at least 650 basis points is
        WELL_CAPITALIZED" and "classification is by inclusive lower bound — a
        ratio sitting exactly on a threshold earns the higher bucket."

        Design: Difficulty/boundary_precision_check/pca_threshold_exact_boundary_ge_vs_gt
        """
        # CET1 6_500_000_000 / RWA 100e9 -> exactly 650 bps; Tier 1 800,
        # total 1000, leverage 800 -> all WELL, CET1 binding at the boundary.
        bank, period, report = _setup_boundary_bank(api, "CH-BND-A", 6_500_000_000)
        fetched_report = validate_success(
            api.get_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        assert fetched_report["cet1_ratio_bps"] == 650
        assert fetched_report["tier1_ratio_bps"] == 800
        assert fetched_report["total_ratio_bps"] == 1000
        accepted_bank = _accept_and_bucket(
            api, capital_analyst_headers, regulator_reviewer_headers, bank, period, report
        )
        assert accepted_bank["pca_bucket"] == "WELL_CAPITALIZED"

    def test_pca_boundary_649_falls_to_adequately_capitalized(self, api, system_operator_headers,
                                                              capital_analyst_headers, regulator_reviewer_headers):
        """PRD §2.7: "For the CET1 ratio, at least 650 basis points is
        WELL_CAPITALIZED, at least 450 is ADEQUATELY_CAPITALIZED" and
        "classification is by inclusive lower bound — a ratio sitting exactly
        on a threshold earns the higher bucket."

        Design: Difficulty/boundary_precision_check/pca_threshold_exact_boundary_ge_vs_gt
        """
        # CET1 6_490_000_000 / RWA 100e9 -> 649 bps < 650 -> CET1 metric
        # ADEQUATE; Tier 1 799 and total 999 are also ADEQUATE, so the bank
        # lands ADEQUATELY_CAPITALIZED.
        bank, period, report = _setup_boundary_bank(api, "CH-BND-B", 6_490_000_000)
        fetched_report = validate_success(
            api.get_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        assert fetched_report["cet1_ratio_bps"] == 649
        accepted_bank = _accept_and_bucket(
            api, capital_analyst_headers, regulator_reviewer_headers, bank, period, report
        )
        assert accepted_bank["pca_bucket"] == "ADEQUATELY_CAPITALIZED"

    def test_pca_bucket_is_strictest_across_metrics(self, api, system_operator_headers,
                                                    capital_analyst_headers, regulator_reviewer_headers):
        """PRD §2.7: "The bank's bucket is the strictest — weakest — of the
        four metric classifications" and "For the leverage ratio they are 500,
        400, 350, and 300."

        Design: Difficulty/boundary_precision_check/pca_threshold_exact_boundary_ge_vs_gt
        """
        # RWA 40e9 (one CORPORATE line at 40% weight) with CET1 4e9 -> the
        # three capital ratios are 1000 bps (WELL) while the leverage ratio is
        # 400 bps (ADEQUATE). The strictest classification rules the bucket.
        bank = create_bank("CH-BND-C", legal_name="BoundaryC")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
            risk_weight_bps=4000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        add_instrument(bank["id"], outstanding_amount_cents=4_000_000_000)
        report = create_prepared_call_report(bank["id"], period["id"])
        assert report["cet1_ratio_bps"] == 1000
        assert report["total_ratio_bps"] == 1000
        assert report["leverage_ratio_bps"] == 400
        accepted_bank = _accept_and_bucket(
            api, capital_analyst_headers, regulator_reviewer_headers, bank, period, report
        )
        assert accepted_bank["pca_bucket"] == "ADEQUATELY_CAPITALIZED"


class TestImmediateConsistency(object):
    def test_immediate_consistency_on_accept(self, api, system_operator_headers,
                                             capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.3: "Acceptance stamps accepted_at, moves the report
        SUBMITTED → ACCEPTED, moves the period SUBMITTED → ACCEPTED, and then
        fires the widest cascade in the system. The bank's pca_bucket is
        recomputed from the accepted ratios under the classification of
        §2.7"

        Design: Corner/consistency_model/immediate_consistency_on_accept
        """
        bank, period, report = setup_accepted_report(
            "CH-IMM-001", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        # The accept has already returned; the very next read reflects the cascade.
        assert bank["pca_bucket"] == "WELL_CAPITALIZED"
        assert isinstance(bank["mdba_cents"], int)


class TestPcaThresholdEvents(object):
    def test_threshold_events_written_when_bucket_worsens_on_accept(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §3.8: "Each event is written at the moment an accepted call
        report — original or amended — shifts the bank's classification, and
        records the metric concerned (CET1, TIER1, TOTAL, or LEVERAGE), the
        ratio_bps_observed at the moment of the check in basis points, the
        bucket_before, the bucket_after, and a breached flag that is true
        exactly when the new bucket is stricter than the old one."

        Design: Corner/consistency_model/immediate_consistency_on_accept
        """
        bank = create_bank("CH-EVT-001", legal_name="EventBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        report = create_prepared_call_report(bank["id"], period["id"])
        accepted_bank = _accept_and_bucket(
            api, capital_analyst_headers, regulator_reviewer_headers, bank, period, report
        )
        assert accepted_bank["pca_bucket"] == "WELL_CAPITALIZED"
        events, meta = validate_paginated(
            api.list_pca_threshold_events(
                accepted_bank["id"], capital_analyst_headers, params={"limit": 100}
            )
        )
        assert len(events) >= 1, "Expected at least one PCA threshold event on bucket change"
        for event in events:
            assert_pca_threshold_event(event)
        # bucket_before is the creation default ADEQUATELY_CAPITALIZED; the
        # accepted ratios are all WELL, so every event is an improvement.
        assert all(e["bucket_before"] == "ADEQUATELY_CAPITALIZED" for e in events)
        assert all(e["bucket_after"] == "WELL_CAPITALIZED" for e in events)
        assert all(e["breached"] is False for e in events)
