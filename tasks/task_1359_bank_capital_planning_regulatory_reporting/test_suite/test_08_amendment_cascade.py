"""Acceptance cascades: the depth-3 chain from a call-report acceptance into
PCA bucket, distributable pool, and open distribution requests, plus the
amendment accept cascade that refreshes plan baselines and sub-debt headroom.

Exposure rows can only be recorded while a period is OPEN or FILING_DUE
(PRD §3.2), so adverse ratio moves after an acceptance arrive through later
periods' original reports or through bank-level instrument changes; both
routes exercise the same acceptance-cascade rules (PRD §3.3, §3.4).
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    ApiErrorId,
    add_exposure,
    advance_clock_past,
    add_instrument,
    approve_distribution,
    create_active_scenario,
    create_bank,
    create_draft_plan,
    create_period,
    create_payment_period,
    create_prepared_call_report,
    create_proposed_distribution,
    create_proposed_sub_debt,
    setup_accepted_report,
    setup_distributable_bank,
    setup_plan_approved,
    make_board_approver_headers,
    make_capital_analyst_headers,
    SUBMITTER_USER_ID,
    PREPARER_USER_ID,
)


def _file_and_accept_period(api, analyst_headers, regulator_headers, bank, period):
    report = create_prepared_call_report(bank["id"], period["id"])
    # Move the period unambiguously to FILING_DUE before submitting.
    advance_clock_past(period["period_end_date"])
    submitted = validate_success(
        api.submit_call_report(
            bank["id"], period["id"], report["id"],
            make_capital_analyst_headers(SUBMITTER_USER_ID),
        )
    )
    return validate_success(
        api.accept_call_report(bank["id"], period["id"], submitted["id"], regulator_headers)
    )


class TestAcceptCascadeDepth3(object):
    def test_accept_on_later_period_drops_bucket_and_expires_distribution(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §3.3: "Every distribution request still in
        APPROVED_NOT_EXECUTED has its capacity_reserved_cents re-evaluated
        against the new capacity, and any whose reservation exceeds it is
        moved to EXPIRED with its reservation released."
        PRD §3.6: "In any of the three undercapitalized buckets, mdba_cents is
        zero outright."

        Design: Difficulty/transitive_cascade/amendment_cascade_depth_3
        """
        # EFFECTIVE plan with a positive pool and an APPROVED_NOT_EXECUTED
        # distribution of 75e6 against the Q1 2027 payment period. The
        # adverse Q3 2026 period is created (with its exposure) before the
        # plan-year clock crossing, so its exposures are recorded while it is
        # unambiguously open; the distribution is likewise proposed before
        # the crossing, while the plan is still APPROVED (PRD §3.6 gates
        # proposals to DRAFT…APPROVED).
        created = {}

        def _create_adverse_period(bank_id, plan, pay_period):
            p2 = create_period(bank_id, "2026-09-30", 2026, "Q3")
            add_exposure(bank_id, p2["id"], exposure_at_default_cents=200_000_000_000)
            created["p2"] = p2
            created["dist"] = create_proposed_distribution(
                bank_id, plan["id"], pay_period["id"],
                distribution_kind="DIVIDEND", distribution_amount_cents=75_000_000,
                proposed_payment_date="2027-03-15",
            )

        bank, base_period, pay_period, scenario, plan = setup_distributable_bank(
            "CH-CAS-001", scenario_code="BASE-CAS", pre_cross_hook=_create_adverse_period
        )
        p2 = created["p2"]
        dist = created["dist"]
        approve_distribution(bank["id"], dist["id"])
        # File the adverse quarter: with the topped-up 15e9 stack over RWA
        # 200e9, CET1/Tier1/total/leverage land at 750 bps; the total
        # metric's floor makes the bucket UNDERCAPITALIZED.
        accepted = _file_and_accept_period(
            api, capital_analyst_headers, regulator_reviewer_headers, bank, p2
        )
        assert accepted["rwa_cents"] == 200_000_000_000
        assert accepted["cet1_ratio_bps"] == 750
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert bank_now["pca_bucket"] == "UNDERCAPITALIZED"
        assert bank_now["mdba_cents"] == 0
        # Depth-3: accept -> bucket recompute -> mdba to zero -> the approved
        # distribution's reservation exceeds capacity and it lapses.
        dist_now = validate_success(
            api.get_distribution_request(bank["id"], dist["id"], capital_analyst_headers)
        )
        assert dist_now["status"] == "EXPIRED"
        assert dist_now["capacity_reserved_cents"] == 0

    def test_accept_on_later_period_recomputes_sub_debt_headroom(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §3.3: "Every sub-debt issuance in PROPOSED, APPROVED, or
        PRICED has its t2_capacity_headroom_cents recomputed."
        PRD §3.7: "the cap is 2 percent of the bank's most recently accepted
        RWA — the rwa_cents of its latest ACCEPTED call report"

        Design: Difficulty/transitive_cascade/amendment_cascade_depth_3
        """
        bank, period, report = setup_accepted_report(
            "CH-CAS-002", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        assert bank["pca_bucket"] == "WELL_CAPITALIZED"
        # T2 cap = 2% of 100e9 = 2e9, nothing outstanding.
        sd = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=500,
            maturity_years=10, target_settlement_date="2027-09-01",
        )
        assert sd["t2_capacity_headroom_cents"] == 2_000_000_000
        # Later quarter with RWA 150e9: ratios land at 666 bps (CET1 WELL at
        # 666 >= 650, total 666 SIGNIFICANT) and the T2 cap grows to 3e9.
        p2 = create_period(bank["id"], "2026-09-30", 2026, "Q3")
        add_exposure(bank["id"], p2["id"], exposure_at_default_cents=150_000_000_000)
        accepted = _file_and_accept_period(
            api, capital_analyst_headers, regulator_reviewer_headers, bank, p2
        )
        assert accepted["rwa_cents"] == 150_000_000_000
        sd_now = validate_success(
            api.get_sub_debt_issuance(bank["id"], sd["id"], capital_analyst_headers)
        )
        assert sd_now["t2_capacity_headroom_cents"] == 3_000_000_000
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        # 666 bps: total ratio 666 < 700 -> SIGNIFICANTLY_UNDERCAPITALIZED.
        assert bank_now["pca_bucket"] == "SIGNIFICANTLY_UNDERCAPITALIZED"


class TestAmendmentFullChain(object):
    def _setup_t2_call_amendment_bank(self, api, capital_analyst_headers, regulator_headers,
                                      charter_id):
        """Bank with CET1 7.5e9, AT1 1.5e9, T2 2e9 over RWA 100e9 (all four
        metrics WELL at 750/900/1100/900 bps), a plan APPROVED on the period,
        and an open sub-debt proposal. Returns the pieces."""
        bank = create_bank(charter_id)
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
            risk_weight_bps=10000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        add_instrument(bank["id"], outstanding_amount_cents=7_500_000_000)
        add_instrument(
            bank["id"], instrument_class="AT1", instrument_subtype="PREFERRED",
            outstanding_amount_cents=1_500_000_000, issuance_date="2020-01-15",
            contractual_rate_bps=600,
        )
        t2 = add_instrument(
            bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
            outstanding_amount_cents=2_000_000_000, issuance_date="2022-01-15",
            maturity_date="2032-12-31", contractual_rate_bps=500,
        )
        report = _file_and_accept_period(api, capital_analyst_headers, regulator_headers, bank, period)
        return bank, period, report, t2

    def test_amendment_accept_refreshes_plan_baseline(self, api, system_operator_headers,
                                                      capital_analyst_headers,
                                                      regulator_reviewer_headers):
        """PRD §3.4: "Every capital plan whose baseline_period_id is this
        period and whose status is anything but SUPERSEDED has its baseline
        fields refreshed and its projected and stressed ratios recomputed"
        PRD §3.4: "Accepting an amendment re-runs the acceptance cascade in a
        harsher mode. The PCA bucket is recomputed from the amended ratios —
        it may improve or deteriorate — with threshold events inserted for any
        bucket changes, and mdba_cents is recomputed."

        Design: Corner/cross_cutting_layers/cascading_side_effects_amendment_full_chain
        """
        bank, period, report, t2 = self._setup_t2_call_amendment_bank(
            api, capital_analyst_headers, regulator_reviewer_headers, "CH-FCS-001"
        )
        bank = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert bank["pca_bucket"] == "WELL_CAPITALIZED"
        # Plan on this baseline, approved (stress floor: 750/1.045 -> 717 bps
        # against the 700-bps floor with a zero-loss inventory).
        scenario = create_active_scenario(bank["id"], "BASE-FCS")
        plan = create_draft_plan(bank["id"], period["id"], scenario["id"])
        validate_success(
            api.submit_plan_board(
                bank["id"], plan["id"], make_capital_analyst_headers(PREPARER_USER_ID)
            )
        )
        validate_success(
            api.board_approve_plan(bank["id"], plan["id"], make_board_approver_headers("board-1"))
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        validate_success(
            api.submit_plan_regulator(
                bank["id"], plan["id"], {"expected_bank_version": bank_now["version"]},
                capital_analyst_headers,
            )
        )
        plan = validate_success(
            api.regulator_approve_plan(bank["id"], plan["id"], regulator_reviewer_headers)
        )
        assert plan["baseline_total_capital_cents"] == 11_000_000_000
        # Call the T2 instrument (bank WELL, post-call T2 within cap), then
        # run the amendment cycle: total capital falls 11e9 -> 9e9, the total
        # ratio 1100 -> 900 bps crosses below the 1000-bps WELL floor.
        validate_success(api.call_capital_instrument(bank["id"], t2["id"], capital_analyst_headers))
        amend = validate_success(
            api.open_amendment(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        prepared = validate_success(
            api.prepare_call_report(
                bank["id"], period["id"], amend["id"],
                make_capital_analyst_headers(PREPARER_USER_ID),
            )
        )
        submitted = validate_success(
            api.submit_call_report(
                bank["id"], period["id"], prepared["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        accepted = validate_success(
            api.accept_call_report(bank["id"], period["id"], submitted["id"], regulator_reviewer_headers)
        )
        assert accepted["total_ratio_bps"] == 900
        # Cascade effects after the amendment accept:
        bank_after = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert bank_after["pca_bucket"] == "ADEQUATELY_CAPITALIZED"
        events, _meta = validate_paginated(
            api.list_pca_threshold_events(bank["id"], capital_analyst_headers, params={"limit": 100})
        )
        assert any(e["breached"] is True for e in events), (
            "expected a breached threshold event for the WELL -> ADEQUATE drop"
        )
        plan_after = validate_success(
            api.get_capital_plan(bank["id"], plan["id"], capital_analyst_headers)
        )
        # The plan's baseline snapshot is refreshed from the amended report.
        assert plan_after["baseline_total_capital_cents"] == 9_000_000_000
        assert plan_after["status"] == "APPROVED"

    def test_amendment_accept_recomputes_sub_debt_headroom(self, api, system_operator_headers,
                                                           capital_analyst_headers,
                                                           regulator_reviewer_headers):
        """PRD §3.3: "Every sub-debt issuance in PROPOSED, APPROVED, or
        PRICED has its t2_capacity_headroom_cents recomputed."
        PRD §3.7: "Headroom is recomputed at proposal, at approval, on every
        RWA recomputation, and whenever a Tier 2 instrument is called,
        redeemed, or matures."

        Design: Corner/cross_cutting_layers/cascading_side_effects_amendment_full_chain
        """
        bank, period, report, t2 = self._setup_t2_call_amendment_bank(
            api, capital_analyst_headers, regulator_reviewer_headers, "CH-FCS-002"
        )
        # T2 cap 2e9 fully used by the outstanding 2e9 instrument: headroom 0.
        sd = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=500,
            maturity_years=10, target_settlement_date="2027-09-01",
        )
        assert sd["t2_capacity_headroom_cents"] == 0
        # Calling the T2 row and re-accepting the amended report leaves the
        # T2 line out of OUTSTANDING; headroom on the open proposal is the
        # full 2e9 cap.
        validate_success(api.call_capital_instrument(bank["id"], t2["id"], capital_analyst_headers))
        amend = validate_success(
            api.open_amendment(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        prepared = validate_success(
            api.prepare_call_report(
                bank["id"], period["id"], amend["id"],
                make_capital_analyst_headers(PREPARER_USER_ID),
            )
        )
        submitted = validate_success(
            api.submit_call_report(
                bank["id"], period["id"], prepared["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        validate_success(
            api.accept_call_report(bank["id"], period["id"], submitted["id"], regulator_reviewer_headers)
        )
        sd_now = validate_success(
            api.get_sub_debt_issuance(bank["id"], sd["id"], capital_analyst_headers)
        )
        assert sd_now["t2_capacity_headroom_cents"] == 2_000_000_000
