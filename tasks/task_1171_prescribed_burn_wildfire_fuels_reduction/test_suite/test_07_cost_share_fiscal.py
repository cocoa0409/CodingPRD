"""Cost-share estimates, disbursements, effectiveness scoring, and fiscal gates
(PRD §2.9, §2.10, §3.8)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_cost_share_payload,
    ctx_add_agreement,
    ctx_add_landowner,
    ctx_add_parcel,
    ctx_add_plan,
    ctx_author,
    ctx_brief,
    ctx_complete_ignition,
    ctx_disburse,
    ctx_go_no_go,
    ctx_ignite,
    ctx_landowner,
    ctx_patrol_mopup_close,
    ctx_reports,
    ctx_reviewer,
    ctx_set_burn_day,
    make_admin_headers,
    make_landowner_headers,
    set_clock_payload,
    setup_adjudicated_claim_ctx,
    setup_approved_plan_ctx,
    setup_burn_ready_ctx,
    setup_partially_disbursed_ctx,
    setup_registry,
    setup_thirty_day_accepted_ctx,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

LEGACY_TRAP_LINES = [
    {"category": "BROADCAST", "rate_class": "GRASS", "acres": 12},
    {"category": "UNDERSTORY", "rate_class": "BRUSH", "acres": 3},
]
LEGACY_ACTUAL_LINES = [
    {"category": "BROADCAST", "rate_class": "GRASS", "acres": 11},
    {"category": "UNDERSTORY", "rate_class": "BRUSH", "acres": 3},
]


class TestProvisionalVsFinalReimbursement:
    def test_provisional_estimate_and_first_installment(self, api):
        """PRD §3.8: "it pays out half of `provisional_estimate_cents`, rounded half-up to
        a whole cent, adds the installment to `disbursed_cents`, debits the fund by the
        same amount, and moves the agreement to `PARTIALLY_DISBURSED`."

        Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_reimbursement
        """
        ctx = setup_burn_ready_ctx()
        agr = validate_success(api.create_cost_share_agreement(
            create_cost_share_payload(ctx["landowner"]["id"], ctx["plan"]["id"],
                                      funding_tier="LEGACY",
                                      treatment_lines=LEGACY_TRAP_LINES),
            ctx_landowner(ctx)), 201)
        # round_half_up(12*15327*0.65)=119551 + round_half_up(3*28750*0.65)=56063
        assert agr["provisional_estimate_cents"] == 175614
        validate_success(api.begin_agreement_review(agr["id"], ADMIN), 200)
        validate_success(api.approve_agreement(agr["id"], ADMIN), 200)
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        ctx_complete_ignition(ctx, 14)
        ctx_patrol_mopup_close(ctx, LEGACY_ACTUAL_LINES)
        disbursed = validate_success(api.disburse_agreement(agr["id"], ADMIN), 200)
        assert disbursed["disbursed_cents"] == 87807  # round_half_up(175614 * 0.5)
        assert disbursed["status"] == "PARTIALLY_DISBURSED"

    def test_final_reimbursement_differs_from_provisional(self, api):
        """PRD §3.8: "Its size is `final_reimbursement_cents` minus the already-paid
        `disbursed_cents`."
        PRD §3.8: "The recomputed `final_reimbursement_cents` applies an effectiveness
        factor — 1.00 when the accepted report's `effectiveness_score` is at least 80,
        0.75 when it is at least 50 but below 80, and 0.00 when below 50, the bounds at 80
        and 50 inclusive"

        Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_reimbursement
        """
        ctx = setup_thirty_day_accepted_ctx()  # score 93 -> factor 1.00
        final = validate_success(api.disburse_agreement(ctx["agreement"]["id"], ADMIN), 200)
        # round_half_up(11*15327*0.65)=109588 + round_half_up(3*28750*0.65)=56063
        assert final["final_reimbursement_cents"] == 165651
        assert final["disbursed_cents"] == 165651  # 87807 + final installment 77844
        assert final["status"] == "FULLY_DISBURSED"
        assert final["provisional_estimate_cents"] == 175614
        assert final["provisional_estimate_cents"] != final["final_reimbursement_cents"]


class TestPerLineRoundingOrder:
    def test_cost_share_per_line_rounding_then_sum(self, api):
        """PRD §2.9: "In particular, cost-share estimates and final reimbursements follow
        a pinned rounding order: each treatment line is rounded to whole cents first, and
        only then are the rounded line amounts summed. Summing unrounded line values and
        rounding once at the end is a different computation — it diverges by cents — and
        is not permitted."
        PRD §3.8: "the line's `acres` multiplied by the per-acre rate for its `rate_class`
        — 15,327 cents for `GRASS`, 28,750 for `BRUSH`, 46,000 for `TIMBER` — and by the
        tier's share percentage — 0.50 for `STANDARD`, 0.75 for `PRIORITY`, 0.65 for
        `LEGACY`"

        Design: Difficulty/combinatorial_formula/cost_share_per_line_rounding_then_sum
        """
        ctx = setup_approved_plan_ctx()
        agr = validate_success(api.create_cost_share_agreement(
            create_cost_share_payload(ctx["landowner"]["id"], ctx["plan"]["id"],
                                      funding_tier="LEGACY",
                                      treatment_lines=LEGACY_TRAP_LINES),
            ctx_landowner(ctx)), 201)
        # per-line round-then-sum: 119551 + 56063 = 175614 (sum-then-round gives 175613)
        assert agr["provisional_estimate_cents"] == 175614

    def test_cost_share_per_line_rounding_priority_tier(self, api):
        """PRD §2.9: "each treatment line is rounded to whole cents first, and only then
        are the rounded line amounts summed."

        Design: Difficulty/combinatorial_formula/cost_share_per_line_rounding_then_sum
        """
        ctx = setup_approved_plan_ctx()
        agr = validate_success(api.create_cost_share_agreement(
            create_cost_share_payload(ctx["landowner"]["id"], ctx["plan"]["id"],
                                      funding_tier="PRIORITY",
                                      treatment_lines=LEGACY_TRAP_LINES),
            ctx_landowner(ctx)), 201)
        # round_half_up(12*15327*0.75)=137943 + round_half_up(3*28750*0.75)=64688
        assert agr["provisional_estimate_cents"] == 202631


class TestFinalInstallmentMonitoringGate:
    def test_final_disbursement_blocked_while_report_submitted(self, api):
        """PRD §3.8: "The final installment requires `PARTIALLY_DISBURSED`
        (`ERR_AGREEMENT_NOT_PARTIALLY_DISBURSED`), an `ACCEPTED` `THIRTY_DAY` monitoring
        report (`ERR_MONITORING_NOT_ACCEPTED`), and an unexpired agreement."

        Design: Difficulty/cross_entity_state_dependency/final_disbursement_requires_thirty_day_accepted
        """
        ctx = setup_partially_disbursed_ctx()
        report = ctx_reports(ctx)[2]  # THIRTY_DAY
        submitted = validate_success(api.submit_monitoring_report(
            report["id"], {"actual_treatment_lines": LEGACY_ACTUAL_LINES}, ctx_author(ctx)), 200)
        assert submitted["status"] == "SUBMITTED"
        validate_error(api.disburse_agreement(ctx["agreement"]["id"], ADMIN),
                       ApiErrorId.ERR_MONITORING_NOT_ACCEPTED)

    def test_final_disbursement_succeeds_after_report_accepted(self, api):
        """PRD §3.8: "acceptance of the `THIRTY_DAY` report recomputes the linked
        agreement's `final_reimbursement_cents`."
        PRD §3.8: "A positive final installment still requires the fund to cover it
        (`ERR_INSUFFICIENT_ASSOCIATION_FUNDS`), and paying it moves the agreement to
        `FULLY_DISBURSED`."

        Design: Difficulty/cross_entity_state_dependency/final_disbursement_requires_thirty_day_accepted
        """
        ctx = setup_partially_disbursed_ctx()
        assert ctx["agreement"]["disbursed_cents"] == 87807
        report = ctx_reports(ctx)[2]
        validate_success(api.submit_monitoring_report(
            report["id"], {"actual_treatment_lines": LEGACY_ACTUAL_LINES}, ctx_author(ctx)), 200)
        validate_success(api.accept_monitoring_report(report["id"], ctx_reviewer(ctx)), 200)
        final = validate_success(api.disburse_agreement(ctx["agreement"]["id"], ADMIN), 200)
        assert final["disbursed_cents"] == 165651
        assert final["status"] == "FULLY_DISBURSED"


class TestTemporalBeatsFiscal:
    def _setup_expired_underfunded_agreement(self, api):
        """Fund 50000; STANDARD agreement {BROADCAST/BRUSH/100} APPROVED at the startup
        clock (expires 2027-05-01); burn CLOSED; clock advanced to 2027-05-02."""
        ctx = setup_burn_ready_ctx(fund=50_000)
        ctx_add_agreement(ctx, tier="STANDARD",
                          lines=[{"category": "BROADCAST", "rate_class": "BRUSH", "acres": 100}])
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        ctx_complete_ignition(ctx, 95)
        ctx_patrol_mopup_close(ctx, [{"category": "BROADCAST", "rate_class": "BRUSH", "acres": 95}])
        validate_success(api.set_clock(set_clock_payload("2027-05-02T00:00:00Z"), ADMIN), 200)
        return ctx

    def test_disbursement_temporal_beats_fiscal(self, api):
        """PRD §2.7: "twelfth temporal windows and deadlines; thirteenth fiscal
        sufficiency"
        PRD §3.8: "Approval stamps `approved_at` with the clock and sets `expires_at` to
        exactly 365 days after `approved_at`; disbursements attempted after that moment
        are rejected with `ERR_AGREEMENT_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/disbursement_temporal_beats_fiscal
        """
        ctx = self._setup_expired_underfunded_agreement(api)
        # Both gates fail: expired (temporal) AND fund 50000 < installment 718750
        # (fiscal). The temporal layer fires first.
        validate_error(api.disburse_agreement(ctx["agreement"]["id"], ADMIN),
                       ApiErrorId.ERR_AGREEMENT_EXPIRED)
        after = validate_success(
            api.get_cost_share_agreement(ctx["agreement"]["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "APPROVED" and after["disbursed_cents"] == 0

    def test_disbursement_expired_with_solvent_fund_still_rejected(self, api):
        """PRD §3.8: "Approval stamps `approved_at` with the clock and sets `expires_at`
        to exactly 365 days after `approved_at`; disbursements attempted after that moment
        are rejected with `ERR_AGREEMENT_EXPIRED`."
        PRD §3.1: "The administrator may later top the fund up with a deposit carrying an
        `amount_cents`, which is added to `fund_balance_cents`"

        Design: Difficulty/priority_pair_validation_conflict/disbursement_temporal_beats_fiscal
        """
        ctx = self._setup_expired_underfunded_agreement(api)
        # Cover the installment so only the temporal gate can fail
        validate_success(api.deposit_fund(ctx["assoc"]["id"], {"amount_cents": 1_000_000}, ADMIN), 200)
        validate_error(api.disburse_agreement(ctx["agreement"]["id"], ADMIN),
                       ApiErrorId.ERR_AGREEMENT_EXPIRED)


class TestDisbursementConservation:
    def test_disbursement_sequence_conserves_entitlement(self, api):
        """PRD §3.8: "after the final disbursement `disbursed_cents` equals
        `final_reimbursement_cents` exactly."

        Design: Difficulty/compensating_invariant/disbursement_sequence_conserves_entitlement
        """
        ctx = setup_partially_disbursed_ctx()
        first = ctx["agreement"]["disbursed_cents"]
        assert first == 87807  # provisional installment
        report = ctx_reports(ctx)[2]
        validate_success(api.submit_monitoring_report(
            report["id"], {"actual_treatment_lines": LEGACY_ACTUAL_LINES}, ctx_author(ctx)), 200)
        validate_success(api.accept_monitoring_report(report["id"], ctx_reviewer(ctx)), 200)
        final = validate_success(api.disburse_agreement(ctx["agreement"]["id"], ADMIN), 200)
        assert final["disbursed_cents"] == final["final_reimbursement_cents"] == 165651
        assert 165651 - first == 77844  # the final installment implied by the two reads

    def test_fund_ledger_reconciles_with_agreement_ledger(self, api):
        """PRD §2.10: "The fund opens at the `initial_fund_cents` supplied when the
        association is created, and its balance is a pure ledger: the initial amount, plus
        every deposit, minus the `fund_payout_cents` of every liability payout that has
        not been reversed, minus every cost-share installment disbursed."

        Design: Difficulty/compensating_invariant/disbursement_sequence_conserves_entitlement
        """
        ctx = setup_thirty_day_accepted_ctx()
        ctx_disburse(ctx)  # final installment
        assoc = validate_success(api.get_association(ctx["assoc"]["id"], ANY_READER_HEADERS), 200)
        # 10_000_000 - 87_807 (provisional) - 77_844 (final)
        assert assoc["fund_balance_cents"] == 9_834_349


class TestEffectivenessPartialBandClawback:
    def test_effectiveness_partial_band_applies_075_with_clawback(self, api):
        """PRD §3.8: "The recomputed `final_reimbursement_cents` applies an effectiveness
        factor — 1.00 when the accepted report's `effectiveness_score` is at least 80,
        0.75 when it is at least 50 but below 80, and 0.00 when below 50, the bounds at 80
        and 50 inclusive"
        PRD §3.8: "A negative final installment is a lawful clawback: `disbursed_cents`
        decreases and the fund is credited by the same magnitude, and the fund-sufficiency
        check is skipped for non-positive installments"

        Design: Corner/calculations/effectiveness_partial_band_applies_075_with_clawback
        """
        ctx = setup_burn_ready_ctx(
            parcel_overrides={"fuel_model": "GRASS", "slope_class": "FLAT"},
            plan_overrides={"planned_acres": 40,
                            "treatment_lines": [{"category": "BROADCAST",
                                                 "rate_class": "GRASS", "acres": 40}]})
        agr = validate_success(api.create_cost_share_agreement(
            create_cost_share_payload(ctx["landowner"]["id"], ctx["plan"]["id"],
                                      funding_tier="STANDARD",
                                      treatment_lines=[{"category": "BROADCAST",
                                                        "rate_class": "GRASS", "acres": 40}]),
            ctx_landowner(ctx)), 201)
        assert agr["provisional_estimate_cents"] == 306540  # round(40*15327*0.5)
        validate_success(api.begin_agreement_review(agr["id"], ADMIN), 200)
        validate_success(api.approve_agreement(agr["id"], ADMIN), 200)
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        ctx_complete_ignition(ctx, 20)
        ctx_patrol_mopup_close(ctx, [{"category": "BROADCAST", "rate_class": "GRASS", "acres": 20}])
        first = validate_success(api.disburse_agreement(agr["id"], ADMIN), 200)
        assert first["disbursed_cents"] == 153270  # provisional half
        report = ctx_reports(ctx)[2]
        submitted = validate_success(api.submit_monitoring_report(
            report["id"],
            {"actual_treatment_lines": [{"category": "BROADCAST", "rate_class": "GRASS", "acres": 20}]},
            ctx_author(ctx)), 200)
        assert submitted["effectiveness_score"] == 50  # inclusive partial-band floor
        validate_success(api.accept_monitoring_report(report["id"], ctx_reviewer(ctx)), 200)
        final = validate_success(api.disburse_agreement(agr["id"], ADMIN), 200)
        # round_half_up(20*15327*0.5*0.75) = round_half_up(114952.5) = 114953
        assert final["final_reimbursement_cents"] == 114953
        assert final["disbursed_cents"] == 114953  # clawback of 38317 applied
        assert final["status"] == "FULLY_DISBURSED"
        assoc = validate_success(api.get_association(ctx["assoc"]["id"], ANY_READER_HEADERS), 200)
        assert assoc["fund_balance_cents"] == 10_000_000 - 153_270 + 38_317


class TestCostShareApplicationGates:
    def test_disburse_rejected_without_closed_execution(self, api):
        """PRD §3.8: "The provisional installment requires an `APPROVED` agreement
        (`ERR_AGREEMENT_NOT_APPROVED`), an execution of the plan in `CLOSED` phase
        (`ERR_NO_CLOSED_EXECUTION`)"

        Design: Corner/errors/disburse_rejected_without_closed_execution
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_agreement(ctx)  # APPROVED; the plan never burned
        validate_error(api.disburse_agreement(ctx["agreement"]["id"], ADMIN),
                       ApiErrorId.ERR_NO_CLOSED_EXECUTION)
        after = validate_success(
            api.get_cost_share_agreement(ctx["agreement"]["id"], ANY_READER_HEADERS), 200)
        assert after["disbursed_cents"] == 0

    def test_disburse_rejected_when_fund_insufficient(self, api):
        """PRD §3.8: "an unexpired agreement, and a fund balance that covers it
        (`ERR_INSUFFICIENT_ASSOCIATION_FUNDS`)"

        Design: Corner/errors/disburse_rejected_when_fund_insufficient
        """
        ctx = setup_burn_ready_ctx(fund=1_000)
        ctx_add_agreement(ctx, tier="STANDARD",
                          lines=[{"category": "BROADCAST", "rate_class": "BRUSH", "acres": 100}])
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        ctx_complete_ignition(ctx, 95)
        ctx_patrol_mopup_close(ctx, [{"category": "BROADCAST", "rate_class": "BRUSH", "acres": 95}])
        # installment round(1437500*0.5) = 718750 > fund 1000; every other gate passes
        validate_error(api.disburse_agreement(ctx["agreement"]["id"], ADMIN),
                       ApiErrorId.ERR_INSUFFICIENT_ASSOCIATION_FUNDS, expected_status=402)
        after = validate_success(
            api.get_cost_share_agreement(ctx["agreement"]["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "APPROVED" and after["disbursed_cents"] == 0

    def test_agreement_rejected_on_parcel_ownership_mismatch(self, api):
        """PRD §3.8: "the applicant must actually own the parcel the plan targets
        (`ERR_PARCEL_OWNERSHIP_MISMATCH`)"

        Design: Corner/errors/agreement_rejected_on_parcel_ownership_mismatch
        """
        ctx = setup_approved_plan_ctx()
        other = ctx_add_landowner(ctx)
        validate_error(api.create_cost_share_agreement(
            create_cost_share_payload(other["id"], ctx["plan"]["id"]),
            make_landowner_headers(other["id"])),
            ApiErrorId.ERR_PARCEL_OWNERSHIP_MISMATCH)

    def test_agreement_create_rejected_when_plan_not_approved(self, api):
        """PRD §3.8: "The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`)"

        Design: Corner/errors/agreement_create_rejected_when_plan_not_approved
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)  # SUBMITTED, never approved
        validate_error(api.create_cost_share_agreement(
            create_cost_share_payload(ctx["landowner"]["id"], plan["id"]),
            ctx_landowner(ctx)), ApiErrorId.ERR_PLAN_NOT_APPROVED)

    def test_suspended_landowner_cannot_apply_costshare(self, api):
        """PRD §3.1: "`standing`, which is `GOOD_STANDING` normally and flips to
        `SUSPENDED` while any claim adjudicated `LANDOWNER_LIABLE` against them still has
        an outstanding balance more than thirty days after its `adjudicated_at`."
        PRD §3.8: "the applicant must be in `GOOD_STANDING`
        (`ERR_LANDOWNER_NOT_IN_GOOD_STANDING`)"

        Design: Corner/errors/suspended_landowner_cannot_apply_costshare
        """
        # Adjudicated LANDOWNER_LIABLE (negligence) on 2026-05-12, never paid
        ctx = setup_adjudicated_claim_ctx(outcome="LANDOWNER_LIABLE", negligence=True)
        validate_success(api.set_clock(set_clock_payload("2026-06-20T00:00:00Z"), ADMIN), 200)
        landowner = validate_success(api.get_landowner(ctx["landowner"]["id"], ANY_READER_HEADERS), 200)
        assert landowner["standing"] == "SUSPENDED"
        assert landowner["outstanding_liability_cents"] == 2_250_000
        # A second parcel + approved plan, then the application is rejected on standing
        ctx_add_parcel(ctx, key="parcel2", name="P2", acreage=80, fuel_model="GRASS",
                       slope_class="FLAT", airshed_id="ASH-2", drought_index=5)
        plan2 = ctx_add_plan(ctx, key="plan2", parcel_key="parcel2", approve=True,
                             planned_acres=50,
                             planned_window_start="2026-06-21", planned_window_end="2026-06-30",
                             treatment_lines=[{"category": "BROADCAST", "rate_class": "GRASS",
                                               "acres": 50}])
        validate_error(api.create_cost_share_agreement(
            create_cost_share_payload(ctx["landowner"]["id"], plan2["id"],
                                      treatment_lines=[{"category": "BROADCAST",
                                                        "rate_class": "GRASS", "acres": 50}]),
            ctx_landowner(ctx)),
            ApiErrorId.ERR_LANDOWNER_NOT_IN_GOOD_STANDING, expected_status=403)

    def test_costshare_approver_must_not_be_applicant(self, api):
        """PRD §3.8: "or approves it — never when the approver is the applying landowner,
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION`"

        Design: Corner/rbac/costshare_approver_must_not_be_applicant
        """
        ctx = setup_approved_plan_ctx()
        agr = ctx_add_agreement(ctx, approve=False)
        validate_success(api.begin_agreement_review(agr["id"], ADMIN), 200)
        # An AssociationAdmin whose opaque identifier equals the applicant's id
        validate_error(api.approve_agreement(
            agr["id"], make_admin_headers(ctx["landowner"]["id"])),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        after = validate_success(api.get_cost_share_agreement(agr["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "UNDER_REVIEW"
