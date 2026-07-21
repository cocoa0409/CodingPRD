"""Claim approval: payout variants, pinned rounding order, cascade side effects, the
deny fork, segregation of duties, and coverage exhaustion (PRD §3.6, §3.5, §2.8)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_active_guarantee, setup_reviewed_claim, file_claim,
    make_underwriter_headers, make_landlord_headers, make_claims_adjuster_headers,
    make_recovery_agent_headers, TEST_USERS,
)


class TestPayoutVariants:
    """Accelerated (full term) vs chronological (missed months) payout divergence."""

    def test_accelerated_payout_uses_full_coverage_term(self, api):
        """PRD §3.6: "The `payout_variant` is set to `ACCELERATED` when
        `acceleration_requested` was true and to `CHRONOLOGICAL` otherwise."
        PRD §3.6: "Under the `ACCELERATED` variant the covered month count is the
        guarantee's full `coverage_months` — the entire remaining term, brought forward."

        Design: Difficulty/dual_variant_calc/claim_payout_accelerated_vs_chronological_diverge
        """
        ctx = setup_reviewed_claim(api, missed_months=12, acceleration_requested=True)
        approved = validate_success(api.approve_claim(ctx["cl_id"],
                                                     make_claims_adjuster_headers("ca1")))
        assert approved["payout_variant"] == "ACCELERATED"
        assert approved["payout_amount_cents"] == 1349994, \
            f"expected 1349994, got {approved['payout_amount_cents']}"

    def test_accelerated_payout_drains_remaining_coverage(self, api):
        """PRD §3.6: "The guarantee's `remaining_coverage_cents` is reduced by the payout".
        PRD §3.6: "the actual `payout_amount_cents` is the smaller of that gross figure
        and the guarantee's current `remaining_coverage_cents`".

        Design: Difficulty/dual_variant_calc/claim_payout_accelerated_vs_chronological_diverge
        """
        ctx = setup_reviewed_claim(api, missed_months=12, acceleration_requested=True)
        get_success_data(api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers("ca1")))
        g = get_success_data(api.get_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        assert g["remaining_coverage_cents"] == 0, \
            f"expected 0 remaining, got {g['remaining_coverage_cents']}"


class TestPayoutRoundingOrder:
    """Round-per-month-then-sum: 224999 * 5 = 1124995 (not sum-then-round 1124996)."""

    def test_chronological_payout_rounds_per_month_then_sums(self, api):
        """PRD §3.6: "The payout is then computed on a round-per-month-then-sum basis
        using the guarantee's `per_month_coverage_cents`, which was rounded to whole cents
        just once, back at guarantee creation."
        PRD §3.6: "The alternative of multiplying rent by the covered fraction and the
        month count and rounding only at the end is explicitly not used, since it can
        differ by a cent."

        Design: Difficulty/combinatorial_formula/claim_payout_round_per_month_then_sum
        """
        ctx = setup_reviewed_claim(api, missed_months=5, acceleration_requested=False)
        approved = validate_success(api.approve_claim(ctx["cl_id"],
                                                     make_claims_adjuster_headers("ca1")))
        assert approved["payout_variant"] == "CHRONOLOGICAL"
        assert approved["payout_amount_cents"] == 1124995, \
            f"expected 1124995, got {approved['payout_amount_cents']}"

    def test_chronological_payout_leaves_expected_remaining(self, api):
        """PRD §3.6: "The gross payout is `per_month_coverage_cents` multiplied by that
        month count, and the actual `payout_amount_cents` is the smaller of that gross
        figure and the guarantee's current `remaining_coverage_cents`".

        Design: Difficulty/combinatorial_formula/claim_payout_round_per_month_then_sum
        """
        ctx = setup_reviewed_claim(api, missed_months=5, acceleration_requested=False)
        get_success_data(api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers("ca1")))
        g = get_success_data(api.get_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        assert g["remaining_coverage_cents"] == 224999, \
            f"expected 224999 remaining, got {g['remaining_coverage_cents']}"


class TestClaimApproveCascade:
    """Depth-3 chain: Claim -> Guarantee coverage -> RecoveryPlan -> Applicant."""

    def test_approve_debits_guarantee_coverage(self, api):
        """PRD §3.6: "The guarantee's `remaining_coverage_cents` is reduced by the payout
        and its `paid_out_cents` increased by the payout."

        Design: Difficulty/transitive_cascade/claim_approve_cascades_coverage_recovery_applicant
        """
        ctx = setup_reviewed_claim(api, missed_months=5, acceleration_requested=False)
        get_success_data(api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers("ca1")))
        g = get_success_data(api.get_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        assert g["remaining_coverage_cents"] == 224999
        assert g["paid_out_cents"] == 1124995

    def test_approve_creates_recovery_plan_and_bumps_open_count(self, api):
        """PRD §3.6: "A `RecoveryPlan` is created in `ACTIVE` status with its
        `principal_cents` set to the payout and its `applicant_id` set to the guarantee's
        `applicant_id`, and the applicant's `open_recovery_count` is incremented by one to
        reflect that new plan."

        Design: Difficulty/transitive_cascade/claim_approve_cascades_coverage_recovery_applicant
        """
        ctx = setup_reviewed_claim(api, missed_months=5, acceleration_requested=False)
        get_success_data(api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers("ca1")))
        plans, meta = validate_paginated(api.list_recovery_plans(
            TEST_USERS["recovery_agent_headers"], params={"claim_id": ctx["cl_id"]}))
        assert meta["total_count"] == 1, f"expected one plan, got {meta['total_count']}"
        assert plans[0]["principal_cents"] == 1124995
        applicant = get_success_data(api.get_applicant(ctx["ap_id"],
                                                      TEST_USERS["underwriter_headers"]))
        assert applicant["open_recovery_count"] == 1


class TestDenyFork:
    """UNDER_REVIEW -> DENIED leaves coverage untouched and creates no recovery plan."""

    def test_deny_leaves_coverage_untouched(self, api):
        """PRD §3.6: "Denial moves the claim to the terminal `DENIED` state with no
        coverage debit and no recovery plan."

        Design: Difficulty/non_linear_state_machine/claim_fork_denied_branch_has_no_side_effects
        """
        ctx = setup_reviewed_claim(api, missed_months=3, acceleration_requested=False)
        denied = validate_success(api.deny_claim(ctx["cl_id"],
                                                make_claims_adjuster_headers("ca1")))
        assert denied["status"] == "DENIED"
        g = get_success_data(api.get_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        assert g["remaining_coverage_cents"] == 1349994, \
            f"coverage must be untouched, got {g['remaining_coverage_cents']}"

    def test_deny_creates_no_recovery_plan(self, api):
        """PRD §3.6: "Denial moves the claim to the terminal `DENIED` state with no
        coverage debit and no recovery plan."

        Design: Difficulty/non_linear_state_machine/claim_fork_denied_branch_has_no_side_effects
        """
        ctx = setup_reviewed_claim(api, missed_months=3, acceleration_requested=False)
        get_success_data(api.deny_claim(ctx["cl_id"], make_claims_adjuster_headers("ca1")))
        _plans, meta = validate_paginated(api.list_recovery_plans(
            TEST_USERS["recovery_agent_headers"], params={"claim_id": ctx["cl_id"]}))
        assert meta["total_count"] == 0, f"no plan should exist, got {meta['total_count']}"


class TestAccelerationDefault:
    def test_omitted_acceleration_defaults_to_chronological_payout(self, api):
        """PRD §3.6: "an optional `acceleration_requested` flag that defaults to false".
        PRD §3.6: "The `payout_variant` is set to `ACCELERATED` when
        `acceleration_requested` was true and to `CHRONOLOGICAL` otherwise."

        Design: Corner/entities/claim_acceleration_requested_defaults_false
        """
        ctx = setup_active_guarantee(api)
        # File a claim WITHOUT the acceleration_requested field.
        created = validate_success(api.create_claim(
            ctx["g_id"],
            {"expected_guarantee_version": ctx["g_version"],
             "default_date": "2026-09-01T00:00:00Z", "missed_months": 5},
            make_landlord_headers(ctx["ll_id"])), expected_status=201)
        assert created["acceleration_requested"] is False
        get_success_data(api.review_claim(created["id"], make_claims_adjuster_headers("ca1")))
        approved = validate_success(api.approve_claim(created["id"],
                                                     make_claims_adjuster_headers("ca1")))
        assert approved["payout_variant"] == "CHRONOLOGICAL"
        assert approved["payout_amount_cents"] == 1124995


class TestClaimApproveSegregationOfDuties:
    def test_underwriter_of_record_cannot_approve_claim(self, api):
        """PRD §3.6: "the acting adjuster's `X-User-ID` must differ from the guarantee's
        `underwritten_by_user_id` — the same operator cannot both underwrite the guarantee
        and approve a claim against it, and a match is rejected with
        `ERR_SEGREGATION_OF_DUTIES`".

        Design: Corner/validations/claim_approved_by_underwriter_of_record_returns_403_sod
        """
        ctx = setup_reviewed_claim(api, missed_months=2, acceleration_requested=False)
        # Guarantee was underwritten by uw1; adjuster acting as uw1 violates SoD.
        resp = api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestCoverageExhaustion:
    def test_accelerated_payout_exhausts_guarantee_and_terminates_agreement(self, api):
        """PRD §3.6: "if the payout has driven the guarantee's `remaining_coverage_cents`
        to exactly zero, the guarantee is auto-transitioned from `ACTIVE` to `EXHAUSTED`".
        PRD §3.5: "terminates any `ACTIVE` `LandlordAgreement` for it."

        Design: Corner/state_machines/accelerated_claim_exhausts_guarantee_and_terminates_agreement
        """
        ctx = setup_reviewed_claim(api, missed_months=12, acceleration_requested=True)
        get_success_data(api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers("ca1")))
        g = get_success_data(api.get_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        assert g["status"] == "EXHAUSTED", f"expected EXHAUSTED, got {g['status']}"
        ag = get_success_data(api.get_agreement(ctx["ag_id"], make_underwriter_headers("uw1")))
        assert ag["status"] == "TERMINATED", f"expected TERMINATED, got {ag['status']}"

    def test_second_claim_approve_on_exhausted_coverage_rejected(self, api):
        """PRD §3.6: "the guarantee must have coverage left, its `remaining_coverage_cents`
        strictly greater than zero, else the approval is rejected with
        `ERR_COVERAGE_EXHAUSTED`."

        Design: Corner/state_machines/second_claim_approve_on_exhausted_coverage_returns_409
        """
        ctx = setup_active_guarantee(api)
        adj = make_claims_adjuster_headers("ca1")
        # File claim1 (accelerated, drains all) and claim2 (chronological) while ACTIVE.
        cl1 = file_claim(api, ctx, missed_months=12, acceleration_requested=True,
                        expected_version=ctx["g_version"])
        v2 = get_success_data(api.get_guarantee(ctx["g_id"],
                                               make_underwriter_headers("uw1")))["version"]
        cl2 = file_claim(api, ctx, missed_months=1, acceleration_requested=False,
                        expected_version=v2)
        get_success_data(api.review_claim(cl1["id"], adj))
        get_success_data(api.approve_claim(cl1["id"], adj))  # drains coverage -> EXHAUSTED
        get_success_data(api.review_claim(cl2["id"], adj))
        resp = api.approve_claim(cl2["id"], adj)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_EXHAUSTED.value)
