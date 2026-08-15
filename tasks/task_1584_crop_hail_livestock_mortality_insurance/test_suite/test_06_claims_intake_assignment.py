"""Claims intake, adjuster assignment, withdrawal, and cancellation gating
(PRD §3.7, §3.9, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_adjuster,
    create_adjuster,
    create_assign_adjuster_payload,
    file_hail_claim,
    make_policyholder_headers,
    pay_premium,
    read_claim,
    read_policy,
    read_unit,
    set_clock,
    setup_active_paid_crop_hail_policy,
    setup_active_paid_livestock_policy,
    setup_bound_crop_hail_policy,
    setup_hail_claim_under_review,
    submit_initial_head_report,
    submit_planting_report,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]
APPROVER = TEST_USERS["claims_approver_headers"]


class TestLossDateCoverageWindow:
    def _setup_reported_unit(self, api):
        ctx = setup_active_paid_crop_hail_policy(acres_list=(1,))
        submit_planting_report(
            ctx["carrier_id"], ctx["policy_id"], ctx["units"][0]["id"],
            ctx["grower_id"], reported_acres=1,
        )
        return ctx

    def test_loss_after_expiration_rejected_out_of_coverage(self, api):
        """PRD §3.7: "First, the loss must fall inside the coverage period — on
        or after the policy's `effective_date` and before its `expiration_date`
        — or the filing is rejected with `ERR_LOSS_DATE_OUT_OF_COVERAGE`
        (HTTP 422)."
        Coverage runs [2026-08-02, 2026-12-31); a 2027-01-15 loss is outside it.

        Design: Difficulty/priority_pair_validation_conflict/temporal_loss_date_trumps_referential_adjuster_county
        """
        ctx = self._setup_reported_unit(api)
        res = api.create_claim(
            ctx["carrier_id"], ctx["policy_id"],
            {"coverage_unit_id": ctx["units"][0]["id"],
             "loss_date": "2027-01-15T00:00:00Z",
             "percent_damage_estimate_pct": 10},
            make_policyholder_headers(ctx["grower_id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOSS_DATE_OUT_OF_COVERAGE)

    def test_coverage_window_check_precedes_late_notice(self, api):
        """PRD §3.7: "First, the loss must fall inside the coverage period — on
        or after the policy's `effective_date` and before its `expiration_date`
        — or the filing is rejected with `ERR_LOSS_DATE_OUT_OF_COVERAGE`
        (HTTP 422). Second, notice given more than thirty days after the loss is
        non-payable by rule and is refused at intake with
        `ERR_LATE_NOTICE_OVER_30D` (HTTP 422); the coverage-window check runs
        first, so an out-of-coverage loss surfaces as
        `ERR_LOSS_DATE_OUT_OF_COVERAGE` rather than being masked by the
        late-notice rule."
        A 2026-06-01 loss violates both rules (before the 2026-08-02 effective
        date and more than thirty days old); the coverage error surfaces.

        Design: Difficulty/priority_pair_validation_conflict/temporal_loss_date_trumps_referential_adjuster_county
        """
        ctx = self._setup_reported_unit(api)
        res = api.create_claim(
            ctx["carrier_id"], ctx["policy_id"],
            {"coverage_unit_id": ctx["units"][0]["id"],
             "loss_date": "2026-06-01T00:00:00Z",
             "percent_damage_estimate_pct": 10},
            make_policyholder_headers(ctx["grower_id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOSS_DATE_OUT_OF_COVERAGE)


class TestAdjusterCapacity:
    def _setup_two_claims(self, api, capacity):
        ctx = setup_active_paid_crop_hail_policy(acres_list=(1, 1))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid, capacity_max_open_claims=capacity)
        claims = []
        for unit in ctx["units"]:
            submit_planting_report(cid, pid, unit["id"], gid, reported_acres=1)
            claims.append(file_hail_claim(cid, pid, gid, unit["id"]))
        return ctx, adjuster, claims

    def test_second_assignment_rejected_at_capacity(self, api):
        """PRD §3.7: "Capacity follows: the adjuster's current open-claim load
        must be below `capacity_max_open_claims` (`ERR_ADJUSTER_CAPACITY_FULL`,
        HTTP 409)."
        PRD §3.1: "An adjuster's open load counts the claims assigned to them
        that sit in `REPORTED`, `INSPECTION_SCHEDULED`, `INSPECTED`, or
        `UNDER_REVIEW`."
        With capacity 1 and one claim already assigned, the second assignment is
        rejected and the claim is left untouched in REPORTED with no adjuster.

        Design: Difficulty/resource_temporal_overlap/adjuster_capacity_aggregate_overlap_distinct_from_interval
        """
        ctx, adjuster, claims = self._setup_two_claims(api, capacity=1)
        assign_adjuster(ctx["carrier_id"], ctx["policy_id"], claims[0]["id"],
                        adjuster["id"])
        res = api.assign_adjuster(
            ctx["carrier_id"], ctx["policy_id"], claims[1]["id"],
            create_assign_adjuster_payload(adjuster["id"]), APPROVER,
        )
        validate_error(res, ApiErrorId.ERR_ADJUSTER_CAPACITY_FULL)
        claim2 = read_claim(ctx["carrier_id"], ctx["policy_id"], claims[1]["id"])
        assert claim2["claim_state"] == "REPORTED"
        assert claim2["adjuster_id"] is None

    def test_adjuster_with_capacity_two_accepts_two_assignments(self, api):
        """PRD §3.7: "Capacity follows: the adjuster's current open-claim load
        must be below `capacity_max_open_claims` (`ERR_ADJUSTER_CAPACITY_FULL`,
        HTTP 409)."
        PRD §3.7: "A successful assignment records the `adjuster_id` on the claim
        and moves it from `REPORTED` to `INSPECTION_SCHEDULED`."
        Capacity 2 with one claim open: the second assignment stays below the
        ceiling and succeeds.

        Design: Difficulty/resource_temporal_overlap/adjuster_capacity_aggregate_overlap_distinct_from_interval
        """
        ctx, adjuster, claims = self._setup_two_claims(api, capacity=2)
        for claim in claims:
            assigned = assign_adjuster(
                ctx["carrier_id"], ctx["policy_id"], claim["id"], adjuster["id"]
            )
            assert assigned["claim_state"] == "INSPECTION_SCHEDULED"
            assert assigned["adjuster_id"] == adjuster["id"]


class TestAssignmentBlockedWhenPolicyRestricted:
    def _setup_delinquent_policy_with_claim(self, api):
        """Bound policy (premium 1_332) with a 600-cent partial payment, a timely
        report, and a REPORTED claim; clock then moved to 2026-09-01 — past the
        thirty-day delinquency mark from the 2026-08-01 binding, but still within
        thirty days of the 2026-08-04 loss so the claim has not auto-closed."""
        ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid)
        pay_premium(cid, pid, gid, 600)
        set_clock(cid, "2026-08-03T00:00:00Z")
        submit_planting_report(cid, pid, ctx["units"][0]["id"], gid,
                               reported_acres=1)
        claim = file_hail_claim(cid, pid, gid, ctx["units"][0]["id"])
        set_clock(cid, "2026-09-01T00:00:00Z")
        ctx.update({"adjuster": adjuster, "claim": claim})
        return ctx

    def test_assignment_rejected_when_billing_delinquent(self, api):
        """PRD §3.7: "Finally the policy's `claims_posture` must be `OPEN`
        (`ERR_POLICY_RESTRICTED`, HTTP 409)."
        PRD §3.6: "Delinquency is the clock's doing: when `current_utc` passes
        thirty days after the binding moment with the premium still underpaid, a
        policy in `BILLED` or `PARTIALLY_PAID` falls to `DELINQUENT`, its
        `claims_posture` flips to `RESTRICTED`, its grower's `status` flips to
        `SUSPENDED`, and the policy's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/adjuster_assignment_blocked_when_policy_restricted
        """
        ctx = self._setup_delinquent_policy_with_claim(api)
        policy = read_policy(ctx["carrier_id"], ctx["policy_id"])
        assert policy["billing_state"] == "DELINQUENT"
        assert policy["claims_posture"] == "RESTRICTED"
        res = api.assign_adjuster(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            create_assign_adjuster_payload(ctx["adjuster"]["id"]), APPROVER,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_RESTRICTED)
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["claim_state"] == "REPORTED", "rejection leaves the claim unchanged"

    def test_assignment_succeeds_after_delinquency_cured(self, api):
        """PRD §3.6: "A delinquent policy that later receives enough in payments
        to reach its full premium returns to `PAID_IN_FULL`; its posture reopens
        to `OPEN`, and the grower returns to `ACTIVE` provided no other policy of
        that grower remains delinquent."
        PRD §3.7: "A successful assignment records the `adjuster_id` on the claim
        and moves it from `REPORTED` to `INSPECTION_SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/adjuster_assignment_blocked_when_policy_restricted
        """
        ctx = self._setup_delinquent_policy_with_claim(api)
        pay_premium(ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"], 732)
        policy = read_policy(ctx["carrier_id"], ctx["policy_id"])
        assert policy["billing_state"] == "PAID_IN_FULL"
        assert policy["claims_posture"] == "OPEN"
        assigned = assign_adjuster(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            ctx["adjuster"]["id"],
        )
        assert assigned["claim_state"] == "INSPECTION_SCHEDULED"
        assert assigned["adjuster_id"] == ctx["adjuster"]["id"]


class TestWithdrawRefileCycle:
    def _setup_withdrawn_first_claim(self, api):
        ctx = setup_active_paid_crop_hail_policy(acres_list=(10,))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid)
        unit = ctx["units"][0]
        submit_planting_report(cid, pid, unit["id"], gid, reported_acres=10)
        claim1 = file_hail_claim(cid, pid, gid, unit["id"])
        assign_adjuster(cid, pid, claim1["id"], adjuster["id"])
        validate_success(
            api.withdraw_claim(cid, pid, claim1["id"],
                               make_policyholder_headers(gid)),
            200,
        )
        ctx.update({"adjuster": adjuster, "claim1": claim1})
        return ctx

    def test_withdraw_releases_unit_and_refile_succeeds(self, api):
        """PRD §3.7: "A policyholder may instead withdraw a claim while it is in
        `REPORTED` or `INSPECTION_SCHEDULED`; withdrawal from any other state is
        rejected with `ERR_CLAIM_NOT_WITHDRAWABLE` (HTTP 409). Withdrawal moves
        the claim to `WITHDRAWN` and releases the unit back to `REPORTED` so it
        can host a future claim."
        PRD §3.7: "The unit must currently be `REPORTED` — filing against a unit
        in any other status is rejected with `ERR_INVALID_STATE` — and filing
        moves the unit from `REPORTED` to `UNDER_CLAIM`."

        Design: Difficulty/non_linear_state_machine/claim_cyclic_withdraw_refile_loop
        """
        ctx = self._setup_withdrawn_first_claim(api)
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        unit_id = ctx["units"][0]["id"]
        claim1 = read_claim(cid, pid, ctx["claim1"]["id"])
        assert claim1["claim_state"] == "WITHDRAWN"

        claim2 = file_hail_claim(
            cid, pid, gid, unit_id, loss_date="2026-08-05T00:00:00Z",
            percent_damage_estimate_pct=30,
        )
        assert claim2["claim_state"] == "REPORTED"
        unit = read_unit(cid, pid, unit_id)
        assert unit["status"] == "UNDER_CLAIM", (
            "the refiled claim re-occupies the released unit"
        )

    def test_refiled_claim_is_a_fresh_resource(self, api):
        """PRD §3.7: "Withdrawal moves the claim to `WITHDRAWN` and releases the
        unit back to `REPORTED` so it can host a future claim."
        The refiled claim is a newly opened first notice of loss, not a
        resurrection of the withdrawn one.

        Design: Difficulty/non_linear_state_machine/claim_cyclic_withdraw_refile_loop
        """
        ctx = self._setup_withdrawn_first_claim(api)
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        claim2 = file_hail_claim(
            cid, pid, gid, ctx["units"][0]["id"],
            loss_date="2026-08-05T00:00:00Z", percent_damage_estimate_pct=30,
        )
        assert claim2["id"] != ctx["claim1"]["id"]
        assert claim2["claim_state"] == "REPORTED"
        stale = read_claim(cid, pid, ctx["claim1"]["id"])
        assert stale["claim_state"] == "WITHDRAWN"


class TestWithdrawAndCancelGuards:
    def test_claim_under_review_cannot_be_withdrawn(self, api):
        """PRD §3.7: "A policyholder may instead withdraw a claim while it is in
        `REPORTED` or `INSPECTION_SCHEDULED`; withdrawal from any other state is
        rejected with `ERR_CLAIM_NOT_WITHDRAWABLE` (HTTP 409)."

        Design: Corner/state_machines/claim_under_review_cannot_be_withdrawn
        """
        ctx = setup_hail_claim_under_review(acres=1)
        res = api.withdraw_claim(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            make_policyholder_headers(ctx["grower_id"]),
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_WITHDRAWABLE)
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["claim_state"] == "UNDER_REVIEW"

    def test_cancel_policy_with_open_claim_returns_open_claims_block_cancel(self, api):
        """PRD §3.9: "A policy in `BOUND` or `ACTIVE` may be cancelled —
        cancellation from any other lifecycle state is rejected with
        `ERR_POLICY_NOT_CANCELLABLE` (HTTP 409) — but not while claims in
        `INSPECTION_SCHEDULED`, `INSPECTED`, `UNDER_REVIEW`, or `APPROVED`
        remain open; open claims block the cancellation with
        `ERR_OPEN_CLAIMS_BLOCK_CANCEL` (HTTP 409)."

        Design: Corner/state_machines/cancel_policy_with_open_claim_returns_open_claims_block_cancel
        """
        ctx = setup_active_paid_crop_hail_policy(acres_list=(1,))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid)
        submit_planting_report(cid, pid, ctx["units"][0]["id"], gid,
                               reported_acres=1)
        claim = file_hail_claim(cid, pid, gid, ctx["units"][0]["id"])
        assign_adjuster(cid, pid, claim["id"], adjuster["id"])

        res = api.cancel_policy(cid, pid, UW)
        validate_error(res, ApiErrorId.ERR_OPEN_CLAIMS_BLOCK_CANCEL)
        policy = read_policy(cid, pid)
        assert policy["lifecycle_state"] == "ACTIVE", (
            "a blocked cancellation leaves the policy unchanged"
        )


class TestAdjusterQualification:
    def test_adjuster_species_mismatch_returns_error(self, api):
        """PRD §3.7: "Territorial and qualification fit come next: for hail
        claims the unit's `county_code` must appear in the adjuster's
        `county_codes` (`ERR_ADJUSTER_COUNTY_MISMATCH`, HTTP 422), and for
        livestock claims the unit's `species` must appear in the adjuster's
        `species_qualified` (`ERR_ADJUSTER_SPECIES_MISMATCH`, HTTP 422)."

        Design: Corner/errors/adjuster_species_mismatch_returns_error
        """
        ctx = setup_active_paid_livestock_policy(
            head_count=5, per_head_value=200_000,
        )
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        swine_adjuster = create_adjuster(
            cid, species_qualified=["SWINE"], license_number="ADJ-T-2",
        )
        unit = ctx["units"][0]
        submit_initial_head_report(cid, pid, unit["id"], gid,
                                   reported_head_count=5)
        claim_res = api.create_claim(
            cid, pid,
            {"coverage_unit_id": unit["id"],
             "loss_date": "2026-08-04T00:00:00Z",
             "appraisal_value_cents": 100_000, "deceased_head_count": 1},
            make_policyholder_headers(gid),
        )
        claim = validate_success(claim_res, 201)
        res = api.assign_adjuster(
            cid, pid, claim["id"],
            create_assign_adjuster_payload(swine_adjuster["id"]), APPROVER,
        )
        validate_error(res, ApiErrorId.ERR_ADJUSTER_SPECIES_MISMATCH)


class TestImmediateConsistency:
    def test_claim_state_visible_immediately_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.7: "A successful assignment records the `adjuster_id` on the claim
        and moves it from `REPORTED` to `INSPECTION_SCHEDULED`."

        Design: Corner/consistency_model/claim_state_visible_immediately_in_same_response
        """
        ctx = setup_active_paid_crop_hail_policy(acres_list=(1,))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid)
        submit_planting_report(cid, pid, ctx["units"][0]["id"], gid,
                               reported_acres=1)
        claim = file_hail_claim(cid, pid, gid, ctx["units"][0]["id"])
        res = api.assign_adjuster(
            cid, pid, claim["id"],
            create_assign_adjuster_payload(adjuster["id"]), APPROVER,
        )
        assigned = validate_success(res, 200)
        assert assigned["claim_state"] == "INSPECTION_SCHEDULED", (
            "the transition is visible in the same response"
        )
        assert assigned["adjuster_id"] == adjuster["id"]
