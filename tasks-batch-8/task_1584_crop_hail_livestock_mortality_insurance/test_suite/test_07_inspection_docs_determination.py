"""Field inspections, veterinary documentation, loss determinations, and their
cascades (PRD §3.7, §3.8, §2.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    assert_loss_determination,
    assign_adjuster,
    create_adjuster,
    create_determination_payload,
    create_federal_policy,
    create_hail_inspection_payload,
    file_hail_claim,
    issue_determination,
    link_dual_coverage,
    make_adjuster_headers,
    make_approver_headers,
    make_policyholder_headers,
    read_claim,
    read_grower,
    read_policy,
    read_unit,
    setup_active_paid_crop_hail_policy,
    setup_active_paid_livestock_policy,
    setup_hail_claim_under_review,
    setup_livestock_claim_under_review,
    submit_initial_head_report,
    submit_planting_report,
    submit_veterinary_report,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]
APPROVER = TEST_USERS["claims_approver_headers"]


def _setup_crop_hail_dual_coverage_scenario(api):
    """Crop-hail policy (100 acres CORN in county 06001 at rate 333 -> premium
    133_200, reserve 79_920), ACTIVE and PAID_IN_FULL, with an ACTIVE federal
    policy (liability 200_000, matching crop/county) linked via dual coverage,
    and a hail claim walked to UNDER_REVIEW.

    Dual-coverage linking is a crop-hail-only construct: PRD §3.3 defines the
    link as "a private crop-hail policy to a federal crop policy" whose "crop
    and county match the private policy's coverage units", and §4 describes the
    endpoint the same way — livestock units carry no crop/county to match."""
    ctx = setup_hail_claim_under_review(acres=100)
    cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
    federal = create_federal_policy(cid, gid, liability_cents=200_000)
    link_dual_coverage(cid, pid, federal["id"])
    ctx["federal"] = federal
    return ctx


class TestProvisionalVsFinalIndemnity:
    def test_provisional_indemnity_uses_min_appraisal_and_band_cap(self, api):
        """PRD §3.7: "For livestock, the appraisal basis is the lesser of the
        adjuster's `observed_appraisal_cents` and the grower's claimed
        `appraisal_value_cents`; that basis is then capped at the rating row's
        `value_band_ceiling_cents` multiplied by the adjuster's
        `observed_deceased_count`, and the capped figure is scaled down by the
        latest late head report's `coverage_reduction_pct`."
        PRD §3.7: "In both branches the result is finally scaled down by the
        claim's `late_notification_penalty_pct`, and the outcome is rounded half
        up to whole cents at this final step only, with no intermediate
        truncation."
        min(95_000 observed, 100_000 claimed) = 95_000; cap 250_000 × 1 head;
        no reductions → provisional 95_000. (The provisional computation at
        inspection time involves no dual-coverage offset — the offset only
        enters the final-indemnity waterfall of §3.8 — so this scenario needs
        no federal policy or link.)

        Design: Difficulty/dual_variant_calc/provisional_vs_final_indemnity_divergence_on_claim
        """
        ctx = setup_livestock_claim_under_review(
            head_count=10, per_head_value=200_000,
            appraisal_value_cents=100_000, deceased_head_count=1,
            observed_appraisal_cents=95_000, observed_deceased_count=1,
        )
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["provisional_indemnity_cents"] == 95_000
        assert claim["claim_state"] == "UNDER_REVIEW"

    def test_partial_determination_waterfall_applies_dual_coverage_offset(self, api):
        """PRD §3.8: "The base is the `approved_indemnity_cents`: for a straight
        approval this equals the claim's provisional indemnity, while a partial
        decision substitutes the approver's own figure, which may be lower than
        the provisional."
        PRD §3.8: "Third, when a dual-coverage link exists on the policy, the
        dual-coverage offset — twenty percent of the federal policy's
        `liability_cents`, capped at the amount remaining at that step — is
        subtracted and recorded as `applied_dual_coverage_offset_cents`."
        PARTIAL base 90_000; no coverage or late-notice reductions; offset
        min(90_000, 20% × 200_000) = 40_000; final = 50_000. The scenario is
        crop-hail because PRD §3.3 limits dual-coverage linking to "a private
        crop-hail policy"; the PARTIAL base substitutes the approver's figure,
        so the assertion arithmetic is policy-kind independent.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_indemnity_divergence_on_claim
        """
        ctx = _setup_crop_hail_dual_coverage_scenario(api)
        version = read_policy(ctx["carrier_id"], ctx["policy_id"])["version"]
        res = issue_determination(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            "PARTIAL", 90_000, version,
        )
        determination = validate_success(res, 201)
        assert_loss_determination(determination)
        assert determination["applied_coverage_reduction_pct"] == 0
        assert determination["applied_late_notification_penalty_pct"] == 0
        assert determination["applied_dual_coverage_offset_cents"] == 40_000
        assert determination["final_indemnity_cents"] == 50_000
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["final_indemnity_cents"] == 50_000
        assert claim["claim_state"] == "APPROVED"


class TestDocumentationGate:
    def test_approve_blocked_with_docs_pending(self, api):
        """PRD §3.8: "For livestock claims the documentation gate follows:
        `doc_posture` must read `DOCS_COMPLETE` or `DOCS_WAIVED`, else the
        decision is rejected with `ERR_DOCS_INCOMPLETE` (HTTP 422)."
        No veterinary reports have been submitted, so the claim sits in
        DOCS_PENDING and the APPROVE is refused; the claim stays UNDER_REVIEW.

        Design: Difficulty/cross_entity_state_dependency/claim_determination_blocked_when_docs_incomplete
        """
        ctx = setup_livestock_claim_under_review(
            head_count=10, per_head_value=200_000,
            appraisal_value_cents=100_000, deceased_head_count=1,
            observed_appraisal_cents=95_000,
        )
        version = read_policy(ctx["carrier_id"], ctx["policy_id"])["version"]
        res = issue_determination(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            "APPROVE", 90_000, version,
        )
        validate_error(res, ApiErrorId.ERR_DOCS_INCOMPLETE)
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["claim_state"] == "UNDER_REVIEW"

    def test_approve_succeeds_after_veterinary_certificate(self, api):
        """PRD §3.7: "Every submission recomputes the claim's `doc_posture`: it
        reads `DOCS_COMPLETE` when a veterinary certificate is on file and — for
        claims whose appraised value exceeds $5,000 — a necropsy report with
        `necropsy_performed` true is also on file, and it otherwise remains
        `DOCS_PENDING`."
        PRD §3.8: "The base is the `approved_indemnity_cents`: for a straight
        approval this equals the claim's provisional indemnity, while a partial
        decision substitutes the approver's own figure, which may be lower than
        the provisional."
        The claimed appraisal is 100_000 cents (under $5,000), so the
        certificate alone completes the documentation; a PARTIAL decision at
        90_000 then settles the claim.

        Design: Difficulty/cross_entity_state_dependency/claim_determination_blocked_when_docs_incomplete
        """
        ctx = setup_livestock_claim_under_review(
            head_count=10, per_head_value=200_000,
            appraisal_value_cents=100_000, deceased_head_count=1,
            observed_appraisal_cents=95_000,
        )
        submit_veterinary_report(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            ctx["grower_id"], report_kind="VETERINARY_CERTIFICATE",
            death_date="2026-08-04T00:00:00Z",
        )
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["doc_posture"] == "DOCS_COMPLETE"

        version = read_policy(ctx["carrier_id"], ctx["policy_id"])["version"]
        res = issue_determination(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            "PARTIAL", 90_000, version,
        )
        determination = validate_success(res, 201)
        assert determination["final_indemnity_cents"] == 90_000
        claim = read_claim(ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"])
        assert claim["claim_state"] == "APPROVED"


class TestApprovalCascade:
    def _setup(self, api):
        """10-acre crop-hail policy (premium 13_320; reserve 7_992), ACTIVE and
        PAID_IN_FULL, with a claim in UNDER_REVIEW (provisional 40_000)."""
        ctx = setup_hail_claim_under_review(acres=10, observed_percent_damage_pct=10)
        policy = read_policy(ctx["carrier_id"], ctx["policy_id"])
        assert policy["premium_cents"] == 13_320
        assert policy["premium_reserve_cents"] == 7_992
        return ctx

    def test_approve_cascades_to_grower_policy_and_coverage_unit(self, api):
        """PRD §3.8: "Approval cascades widely. The claim moves from
        `UNDER_REVIEW` to `APPROVED`; the coverage unit settles, moving from
        `UNDER_CLAIM` to `SETTLED`; the grower's `prior_claims_count` increments
        by one, which can lift the surcharge tier on future applications; and the
        policy's `premium_reserve_cents` is recomputed as sixty percent of
        `premium_cents` rounded down to a whole cent, less the sum of
        `final_indemnity_cents` across the policy's `APPROVED` and `PAID` claims,
        floored at zero — with the policy's `version` incrementing as the cascade
        lands."
        PARTIAL at 5_000: reserve 7_992 − 5_000 = 2_992.

        Design: Difficulty/transitive_cascade/claim_approve_cascades_to_grower_policy_and_coverage_unit
        """
        ctx = self._setup(api)
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        grower_before = read_grower(cid, gid)
        reserve_before = read_policy(cid, pid)["premium_reserve_cents"]

        determination = approve_claim(cid, pid, ctx["claim"]["id"], 5_000,
                                      decision="PARTIAL")
        assert determination["final_indemnity_cents"] == 5_000

        claim = read_claim(cid, pid, ctx["claim"]["id"])
        assert claim["claim_state"] == "APPROVED"
        assert claim["final_indemnity_cents"] == 5_000
        unit = read_unit(cid, pid, ctx["units"][0]["id"])
        assert unit["status"] == "SETTLED"
        policy = read_policy(cid, pid)
        assert policy["premium_reserve_cents"] == reserve_before - 5_000 == 2_992
        grower = read_grower(cid, gid)
        assert grower["prior_claims_count"] == grower_before["prior_claims_count"] + 1

    def test_approve_increments_policy_version(self, api):
        """PRD §2.4: "Updates to derived fields — a policy's billing posture, a
        claim's documentation posture, a recomputed premium reserve — count as
        mutations: they refresh `updated_at` and increment `version`."
        PRD §3.8: "Approval cascades widely. The claim moves from `UNDER_REVIEW`
        to `APPROVED`; the coverage unit settles, moving from `UNDER_CLAIM` to
        `SETTLED`; the grower's `prior_claims_count` increments by one, which can
        lift the surcharge tier on future applications; and the policy's
        `premium_reserve_cents` is recomputed as sixty percent of `premium_cents`
        rounded down to a whole cent, less the sum of `final_indemnity_cents`
        across the policy's `APPROVED` and `PAID` claims, floored at zero — with
        the policy's `version` incrementing as the cascade lands."

        Design: Difficulty/transitive_cascade/claim_approve_cascades_to_grower_policy_and_coverage_unit
        """
        ctx = self._setup(api)
        cid, pid = ctx["carrier_id"], ctx["policy_id"]
        version_before = read_policy(cid, pid)["version"]
        approve_claim(cid, pid, ctx["claim"]["id"], 5_000, decision="PARTIAL")
        policy = read_policy(cid, pid)
        assert policy["version"] == version_before + 1, (
            f"the approval cascade increments the policy version exactly once "
            f"({version_before} → {policy['version']})"
        )


class TestNecropsyGate:
    def test_necropsy_required_for_high_value_livestock_claim(self, api):
        """PRD §3.7: "One safety gate guards livestock inspections: when the
        grower's claimed appraisal exceeds $5,000 — 500,000 cents — at least one
        veterinary report with `necropsy_performed` true must already exist on
        the claim, or the inspection submission is rejected with
        `ERR_NECROPSY_REQUIRED` (HTTP 422)."
        The claim's appraised value is 600_000 cents and no veterinary report
        exists, so the inspection cannot be submitted.

        Design: Corner/errors/necropsy_required_for_high_value_livestock_claim
        """
        ctx = setup_active_paid_livestock_policy(head_count=10,
                                                 per_head_value=200_000)
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        submit_initial_head_report(cid, pid, ctx["units"][0]["id"], gid,
                                   reported_head_count=10)
        claim = validate_success(
            api.create_claim(
                cid, pid,
                {"coverage_unit_id": ctx["units"][0]["id"],
                 "loss_date": "2026-08-04T00:00:00Z",
                 "appraisal_value_cents": 600_000, "deceased_head_count": 3},
                make_policyholder_headers(gid),
            ),
            201,
        )
        assign_adjuster(cid, pid, claim["id"], ctx["adjuster_id"])
        res = api.create_field_inspection(
            cid, pid, claim["id"],
            {"adjuster_id": ctx["adjuster_id"],
             "scheduled_for": "2026-08-04T12:00:00Z",
             "observed_appraisal_cents": 590_000, "observed_deceased_count": 3,
             "notes": "no necropsy"},
            make_adjuster_headers(ctx["adjuster_id"]),
        )
        validate_error(res, ApiErrorId.ERR_NECROPSY_REQUIRED)


class TestDeterminationRbacAndOcc:
    def test_adjuster_cannot_approve_determination(self, api):
        """PRD §3.8: "The loss-determination board acts through a
        `ClaimsApprover`, who submits a `decision` of `APPROVE`, `DENY`, or
        `PARTIAL`, an `approved_indemnity_cents`, a `denial_reason_code` when
        denying, and the concurrency field `expected_policy_version` described in
        §2.8."
        PRD §2.1: "Once the identity headers are accepted, the caller's role must
        appear in the target endpoint's authorized role list; otherwise the
        request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        The Adjuster role is not authorized for the determinations endpoint.

        Design: Corner/rbac/adjuster_cannot_approve_determination
        """
        ctx = setup_hail_claim_under_review(acres=1)
        version = read_policy(ctx["carrier_id"], ctx["policy_id"])["version"]
        res = api.create_determination(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            create_determination_payload("APPROVE", 5_000, version),
            make_adjuster_headers(ctx["adjuster_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_underwriter_cannot_submit_field_inspection(self, api):
        """PRD §3.7: "The assigned adjuster — and only that adjuster — then
        submits the field inspection."
        PRD §2.1: "Once the identity headers are accepted, the caller's role must
        appear in the target endpoint's authorized role list; otherwise the
        request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        The Underwriter role is not authorized for the field-inspections
        endpoint.

        Design: Corner/rbac/underwriter_cannot_submit_field_inspection
        """
        ctx = setup_active_paid_crop_hail_policy(acres_list=(1,))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid)
        submit_planting_report(cid, pid, ctx["units"][0]["id"], gid,
                               reported_acres=1)
        claim = file_hail_claim(cid, pid, gid, ctx["units"][0]["id"])
        assign_adjuster(cid, pid, claim["id"], adjuster["id"])
        res = api.create_field_inspection(
            cid, pid, claim["id"],
            create_hail_inspection_payload(adjuster["id"]),
            UW,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_segregation_of_duties_blocks_adjuster_self_approval_via_approver_role(self, api):
        """PRD §3.8: "Segregation of duties comes next: the approver's
        `X-User-ID` must differ from the claim's `adjuster_id` — the adjuster who
        inspected a loss can never approve it — and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."
        The caller acts in the authorized ClaimsApprover capacity but reuses the
        assigned adjuster's id, so the segregation rule fires.

        Design: Corner/rbac/segregation_of_duties_blocks_adjuster_self_approval_via_approver_role
        """
        ctx = setup_hail_claim_under_review(acres=1)
        version = read_policy(ctx["carrier_id"], ctx["policy_id"])["version"]
        res = api.create_determination(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            create_determination_payload("APPROVE", 5_000, version),
            make_approver_headers(ctx["adjuster_id"]),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_occ_stale_version_on_determination_returns_412(self, api):
        """PRD §2.8: "Issuing a loss determination requires the request to carry
        `expected_policy_version`, holding the `version` of the claim's parent
        policy as the approver last observed it. If the policy's `version` has
        advanced since that read — for example because a premium payment, a
        cancellation, or a renewal cascaded a version bump between the approver's
        read and the determination write — the determination is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_determination_returns_412
        """
        ctx = setup_hail_claim_under_review(acres=10)
        current_version = read_policy(ctx["carrier_id"], ctx["policy_id"])["version"]
        res = issue_determination(
            ctx["carrier_id"], ctx["policy_id"], ctx["claim"]["id"],
            "APPROVE", 5_000, current_version - 1,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
