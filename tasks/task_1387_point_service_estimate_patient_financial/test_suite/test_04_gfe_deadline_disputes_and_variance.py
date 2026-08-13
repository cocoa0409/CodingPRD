"""Good-faith estimate delivery timeline, dispute escalations, and variance records."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_estimate,
    create_case,
    create_charge_item,
    create_contract_with_rates,
    create_estimate,
    create_patient,
    create_snapshot,
    finalize_estimate,
    present_estimate,
    price_estimate,
    set_clock,
    setup_accepted_gfe_estimate,
    setup_accepted_insured_estimate,
    setup_cleared_gfe_case,
    setup_gfe_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSELOR = TEST_USERS["counselor_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestGfeDeliveryDeadline:
    def test_present_draft_past_deadline_reports_state_not_deadline(self, api):
        """PRD §2.8: "then (5) the optimistic-concurrency version check, then
        (6) state-machine legality of the requested transition, then (7)
        segregation of duties, and finally (8) domain business rules in their
        own declared priority."
        PRD §3.5: "`gfe_delivery_deadline` is the end of day — 23:59:59.999
        UTC — of the date reached by adding the applicable number of business
        days to the creation date, skipping weekends."

        Design: Difficulty/priority_pair_validation_conflict/present_draft_state_beats_gfe_deadline
        """
        ctx = setup_gfe_scenario(mrn="MRN-PR-2", cpt_code="27447",
                                 list_price_cents=5000000)
        estimate = ctx["estimate"]
        # Created Monday 2026-08-03 for service 2026-08-20: 13 business days
        # apart -> three-business-day delivery window ending 2026-08-06.
        assert estimate["gfe_required"] is True
        assert estimate["gfe_delivery_deadline"] == "2026-08-06T23:59:59.999Z"
        set_clock("2026-08-07T09:00:00Z")
        res = api.present_estimate(estimate["id"], COUNSELOR)
        # Both the wrong state (DRAFT) and the missed deadline hold; the
        # state-machine legality check outranks the temporal business rule.
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        est = validate_success(api.get_estimate(estimate["id"], COUNSELOR), 200)
        assert est["status"] == "DRAFT"

    def test_present_draft_within_deadline_still_reports_state(self, api):
        """PRD §3.4: "terminal estimates are locked against every further
        transition, and any transition attempted from a state that does not
        offer it is `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.8: "then (6) state-machine legality of the requested transition,
        then (7) segregation of duties, and finally (8) domain business rules
        in their own declared priority."

        Design: Difficulty/priority_pair_validation_conflict/present_draft_state_beats_gfe_deadline
        """
        ctx = setup_gfe_scenario(mrn="MRN-PR-2B", cpt_code="27447",
                                 list_price_cents=5000000)
        # Clock still at creation instant 2026-08-03 — the deadline is not
        # violated here, so only the state check can fire.
        res = api.present_estimate(ctx["estimate"]["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_priced_gfe_present_after_deadline_returns_409(self, api):
        """PRD §3.5: "Presenting an estimate whose good-faith deadline has
        passed is rejected with `ERR_GFE_DEADLINE_MISSED` (HTTP 409)."
        PRD §3.5: "When at least ten business days separate creation from
        service, the estimate must be delivered to the patient within three
        business days".

        Design: Corner/validations/priced_gfe_present_after_deadline_returns_409
        """
        ctx = setup_gfe_scenario(mrn="MRN-V-2", cpt_code="27447",
                                 list_price_cents=5000000)
        estimate = ctx["estimate"]
        assert estimate["gfe_delivery_deadline"] == "2026-08-06T23:59:59.999Z"
        price_estimate(estimate["id"])
        set_clock("2026-08-07T09:00:00Z")
        res = api.present_estimate(estimate["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_GFE_DEADLINE_MISSED)
        est = validate_success(api.get_estimate(estimate["id"], COUNSELOR), 200)
        assert est["status"] == "PRICED"


class TestGfeDisputeBoundary:
    """Dispute threshold on the overage delta; the good-faith total is read
    back from the priced estimate so no discount constant is assumed."""

    def _accepted_gfe_pair(self):
        ctx_a = setup_accepted_gfe_estimate(mrn="MRN-D-1", cpt_code="95999",
                                            list_price_cents=1000000)
        # The charge item is shared between the two cases.
        ctx_b = setup_accepted_gfe_estimate(mrn="MRN-D-2", cpt_code="95999",
                                            list_price_cents=1000000,
                                            with_charge_item=False)
        assert ctx_a["gfe_total_cents"] == ctx_b["gfe_total_cents"]
        return ctx_a, ctx_b

    def test_overage_exactly_at_threshold_is_dispute_eligible(self, api):
        """PRD §3.9: "the estimate's `dispute_eligible` is true when the actual
        billed amount exceeds `gfe_total_cents` by at least forty thousand
        cents — four hundred dollars, with the exact threshold amount
        qualifying"
        PRD §3.9: "When the flag is true, the new variance record triggers the
        system to open a `GFE_DISPUTE` escalation: `OPEN`, opened by `"system"`,
        linked to the finalized estimate, carrying `trigger_amount_cents` equal
        to `variance_vs_accepted_cents`."

        Design: Difficulty/boundary_precision_check/gfe_dispute_delta_exact_vs_one_cent_below
        """
        ctx_a, _ctx_b = self._accepted_gfe_pair()
        gfe_total = ctx_a["gfe_total_cents"]
        finalized = finalize_estimate(ctx_a["estimate"]["id"], gfe_total + 40000)
        assert finalized["dispute_eligible"] is True, (
            "delta exactly 40000 qualifies (>=")
        data, _meta = validate_paginated(
            api.list_case_escalations(ctx_a["case"]["id"], SUPERVISOR))
        disputes = [e for e in data if e["reason"] == "GFE_DISPUTE"]
        assert len(disputes) == 1
        assert disputes[0]["status"] == "OPEN"
        assert disputes[0]["opened_by_user_id"] == "system"
        assert disputes[0]["trigger_amount_cents"] == 40000
        assert disputes[0]["estimate_id"] == ctx_a["estimate"]["id"]

    def test_overage_one_cent_below_threshold_is_not_dispute_eligible(self, api):
        """PRD §3.9: "the estimate's `dispute_eligible` is true when the actual
        billed amount exceeds `gfe_total_cents` by at least forty thousand
        cents — four hundred dollars, with the exact threshold amount
        qualifying"

        Design: Difficulty/boundary_precision_check/gfe_dispute_delta_exact_vs_one_cent_below
        """
        _ctx_a, ctx_b = self._accepted_gfe_pair()
        gfe_total = ctx_b["gfe_total_cents"]
        finalized = finalize_estimate(ctx_b["estimate"]["id"], gfe_total + 39999)
        assert finalized["dispute_eligible"] is False, "delta 39999 < 40000"
        data, _meta = validate_paginated(
            api.list_case_escalations(ctx_b["case"]["id"], SUPERVISOR))
        disputes = [e for e in data if e["reason"] == "GFE_DISPUTE"]
        assert len(disputes) == 0, "no dispute escalation opens below threshold"


class TestFinalizeDisputeCascade:
    """Depth-3 chain: finalize -> variance record -> dispute escalation ->
    case regression."""

    def test_finalize_creates_variance_and_dispute_escalation(self, api):
        """PRD §3.9: "the estimate's `dispute_eligible` is true when the actual
        billed amount exceeds `gfe_total_cents` by at least forty thousand
        cents — four hundred dollars, with the exact threshold amount
        qualifying"
        PRD §3.9: "When the flag is true, the new variance record triggers the
        system to open a `GFE_DISPUTE` escalation: `OPEN`, opened by `"system"`,
        linked to the finalized estimate, carrying `trigger_amount_cents` equal
        to `variance_vs_accepted_cents`."

        Design: Difficulty/transitive_cascade/finalize_gfe_dispute_escalation_regresses_case
        """
        ctx = setup_cleared_gfe_case(mrn="MRN-G-1", cpt_code="27447",
                                     list_price_cents=5000000,
                                     requires_auth_prior=True)
        assert ctx["case"]["status"] == "CLEARED"
        gfe_total = ctx["gfe_total_cents"]
        finalized = finalize_estimate(ctx["estimate"]["id"], gfe_total + 40000)
        assert finalized["status"] == "FINALIZED"
        assert finalized["dispute_eligible"] is True

        records, meta = validate_paginated(
            api.list_estimate_variance_records(ctx["estimate"]["id"], SUPERVISOR))
        assert meta["total_count"] == 1
        record = records[0]
        assert record["variance_vs_accepted_cents"] == 40000
        assert record["dispute_eligible"] is True

        escalations, _m = validate_paginated(
            api.list_case_escalations(ctx["case"]["id"], SUPERVISOR))
        disputes = [e for e in escalations if e["reason"] == "GFE_DISPUTE"]
        assert len(disputes) == 1
        assert disputes[0]["status"] == "OPEN"
        assert disputes[0]["opened_by_user_id"] == "system"
        assert disputes[0]["trigger_amount_cents"] == 40000

    def test_dispute_escalation_regresses_cleared_case_and_applies_deposit(self, api):
        """PRD §3.9: "That fresh `OPEN` escalation flips the case's
        `escalation_cleared` to false, and a `CLEARED` case regresses to
        `IN_REVIEW`."
        PRD §3.9: "Each of the case's `POSTED` deposits, oldest `created_at`
        first, applies up to the remaining actual billed amount: the deposit's
        `applied_amount_cents` is the smaller of its `amount_cents` and the
        bill remaining at its turn."

        Design: Difficulty/transitive_cascade/finalize_gfe_dispute_escalation_regresses_case
        """
        ctx = setup_cleared_gfe_case(mrn="MRN-G-2", cpt_code="27447",
                                     list_price_cents=5000000,
                                     requires_auth_prior=True)
        deposit_amount = ctx["deposit"]["amount_cents"]
        gfe_total = ctx["gfe_total_cents"]
        finalize_estimate(ctx["estimate"]["id"], gfe_total + 40000)

        case = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR), 200)
        assert case["status"] == "IN_REVIEW", "regressed from CLEARED"
        assert case["escalation_cleared"] is False

        deposits, _m = validate_paginated(
            api.list_case_deposits(ctx["case"]["id"], SUPERVISOR))
        deposit = [d for d in deposits if d["id"] == ctx["deposit"]["id"]][0]
        # The deposit (25% of the good-faith total) is smaller than the bill
        # (total + 40000), so it applies in full.
        assert deposit["status"] == "APPLIED"
        assert deposit["applied_amount_cents"] == deposit_amount


class TestVarianceBaselines:
    """One finalize, two accuracy baselines (first-presented vs accepted)."""

    def _setup_revised_case(self):
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000,
                           requires_auth_prior=True)
        create_contract_with_rates(
            bundling_rule="MULTIPLE_PROCEDURE_REDUCTION", reduction_pct=50,
            rates=[{"cpt_code": "27447", "rate_cents": 3000000,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-V-1")
        snapshot1 = create_snapshot(patient["id"], deductible_total_cents=150000,
                                    deductible_met_cents=50000,
                                    oop_max_cents=700000, oop_met_cents=0,
                                    coinsurance_pct=20)
        case = create_case(patient["id"])
        est1 = create_estimate(case["id"], pricing_mode="INSURED",
                               eligibility_snapshot_id=snapshot1["id"],
                               lines=[{"cpt_code": "27447", "quantity": 1}])
        priced1 = price_estimate(est1["id"])
        assert priced1["patient_responsibility_cents"] == 680000
        present_estimate(est1["id"])
        # Re-verification raises deductible_met; the new snapshot supersedes.
        snapshot2 = create_snapshot(patient["id"], deductible_total_cents=150000,
                                    deductible_met_cents=100000,
                                    oop_max_cents=700000, oop_met_cents=0,
                                    coinsurance_pct=20)
        est2 = create_estimate(case["id"], pricing_mode="INSURED",
                               eligibility_snapshot_id=snapshot2["id"],
                               lines=[{"cpt_code": "27447", "quantity": 1}])
        priced2 = price_estimate(est2["id"])
        assert priced2["patient_responsibility_cents"] == 640000
        present_estimate(est2["id"])
        accept_estimate(est2["id"])
        return {"patient": patient, "case": case, "est1": est1, "est2": est2}

    def test_variance_against_first_presented_and_last_accepted(self, api):
        """PRD §3.9: "The signed differences are `variance_vs_first_cents`
        against the first-shown baseline and `variance_vs_accepted_cents`
        against the accepted baseline."
        PRD §3.9: "The percentage `variance_pct` is the absolute value of the
        accepted-baseline difference, expressed as a percentage of the accepted
        baseline, rounded half up to two decimal places".

        Design: Difficulty/dual_variant_calc/variance_first_presented_vs_last_accepted_baseline
        """
        ctx = self._setup_revised_case()
        finalize_estimate(ctx["est2"]["id"], 700000)
        records, meta = validate_paginated(
            api.list_estimate_variance_records(ctx["est2"]["id"], SUPERVISOR))
        assert meta["total_count"] == 1
        record = records[0]
        assert record["variance_vs_first_cents"] == 20000, "700000 - 680000"
        assert record["variance_vs_accepted_cents"] == 60000, "700000 - 640000"
        assert record["variance_vs_first_cents"] != record["variance_vs_accepted_cents"]
        assert record["variance_pct"] == pytest.approx(9.38, abs=0.001), (
            "round_half_up(60000/640000*100, 2)")
        assert record["classification"] == "WITHIN_TOLERANCE", "9.38 <= 10.00"

    def test_variance_record_carries_both_baselines_and_superseded_prior(self, api):
        """PRD §3.9: "`baseline_first_presented_resp_cents` copies the
        case-level pin of what the patient was first shown, and
        `baseline_last_accepted_resp_cents` copies the accepted estimate's
        `patient_responsibility_cents`"
        PRD §3.5: "The first estimate on a case to reach `PRESENTED` also
        writes the case-level pin `first_presented_patient_resp_cents`,
        capturing the patient responsibility the patient was first shown; this
        value is written once and never overwritten by later revisions."

        Design: Difficulty/dual_variant_calc/variance_first_presented_vs_last_accepted_baseline
        """
        ctx = self._setup_revised_case()
        est1_after = validate_success(api.get_estimate(ctx["est1"]["id"], COUNSELOR), 200)
        assert est1_after["status"] == "SUPERSEDED"
        finalize_estimate(ctx["est2"]["id"], 700000)
        records, _meta = validate_paginated(
            api.list_estimate_variance_records(ctx["est2"]["id"], SUPERVISOR))
        record = records[0]
        assert record["baseline_first_presented_resp_cents"] == 680000, (
            "pinned at the first-presented revision, never overwritten")
        assert record["baseline_last_accepted_resp_cents"] == 640000
        assert record["actual_billed_cents"] == 700000
        assert record["estimate_id"] == ctx["est2"]["id"]


class TestVarianceToleranceBoundary:
    def test_variance_tolerance_inclusive_at_10_percent(self, api):
        """PRD §3.9: "The `classification` is `WITHIN_TOLERANCE` when that
        percentage is at most 10.00 — the boundary is inclusive —
        `OVER_TOLERANCE` when the actual exceeded the accepted baseline and the
        percentage is above 10.00, and `UNDER_TOLERANCE` when the actual fell
        short and the percentage is above 10.00."

        Design: Corner/calculations/variance_tolerance_boundary_10pct_within
        """
        ctx_a = setup_accepted_insured_estimate(mrn="MRN-CA-7A")
        case_b = create_case(ctx_a["patient"]["id"], service_date="2026-08-20",
                             service_description="Knee B")
        est_b = create_estimate(case_b["id"], pricing_mode="INSURED",
                                eligibility_snapshot_id=ctx_a["snapshot"]["id"],
                                lines=[{"cpt_code": "27447", "quantity": 1}])
        price_estimate(est_b["id"])
        present_estimate(est_b["id"])
        accept_estimate(est_b["id"])

        finalize_estimate(ctx_a["estimate"]["id"], 550000)
        finalize_estimate(est_b["id"], 560000)

        records_a, _m = validate_paginated(
            api.list_estimate_variance_records(ctx_a["estimate"]["id"], SUPERVISOR))
        assert records_a[0]["variance_vs_accepted_cents"] == 50000
        assert records_a[0]["variance_pct"] == pytest.approx(10.0, abs=0.001)
        assert records_a[0]["classification"] == "WITHIN_TOLERANCE", (
            "10.00 boundary is inclusive")

        records_b, _m = validate_paginated(
            api.list_estimate_variance_records(est_b["id"], SUPERVISOR))
        assert records_b[0]["variance_vs_accepted_cents"] == 60000
        assert records_b[0]["variance_pct"] == pytest.approx(12.0, abs=0.001)
        assert records_b[0]["classification"] == "OVER_TOLERANCE"


class TestFinalizedTerminalLockdown:
    def test_finalize_finalized_estimate_returns_invalid_state(self, api):
        """PRD §3.4: "terminal estimates are locked against every further
        transition, and any transition attempted from a state that does not
        offer it is `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.9: "Exactly one variance record is created per finalize."

        Design: Corner/state_machines/finalize_finalized_estimate_returns_invalid_state
        """
        ctx = setup_accepted_gfe_estimate(mrn="MRN-SM-2", cpt_code="95999",
                                          list_price_cents=1000000)
        finalize_estimate(ctx["estimate"]["id"], 750000)
        res = api.finalize_estimate(ctx["estimate"]["id"],
                                    {"actual_billed_cents": 800000}, COUNSELOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        records, meta = validate_paginated(
            api.list_estimate_variance_records(ctx["estimate"]["id"], SUPERVISOR))
        assert meta["total_count"] == 1, "no second variance record"
        assert records[0]["actual_billed_cents"] == 750000
