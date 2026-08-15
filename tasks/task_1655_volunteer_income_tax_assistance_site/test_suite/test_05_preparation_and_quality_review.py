"""Preparation and quality review: the cyclic rework loop, reviewer
certification and segregation gates, validation-tier ordering, preparer
caseload conservation, and the final refund determination."""
from test_helpers import (
    ApiErrorId,
    add_preparer,
    add_reviewer,
    begin_preparation,
    create_intake_return,
    create_preparation_ready_return,
    create_verified_taxpayer,
    get_return,
    get_volunteer,
    patch_return,
    record_certification,
    register_volunteer,
    review_fail,
    setup_staffed_site,
    submit_for_review,
    transition_return,
    transition_volunteer,
    validate_error,
)
from test_helpers.test_users import (
    make_preparer_headers,
    make_quality_reviewer_headers,
)


def _prep_ready(ctx, ssn, name, **patch_overrides):
    """Verified taxpayer + preparation-ready INTAKE_STARTED return."""
    tp = create_verified_taxpayer(ctx.scr_headers, full_name=name, ssn_token=ssn,
                                  phone="555-5000")
    appt, ret = create_preparation_ready_return(ctx, tp["id"],
                                                patch_overrides=patch_overrides)
    return tp, appt, ret


def _pending_qr(ctx, ssn, name, **patch_overrides):
    tp, appt, ret = _prep_ready(ctx, ssn, name, **patch_overrides)
    ret = begin_preparation(ret)
    ret = submit_for_review(ret)
    assert ret["status"] == "PENDING_QR"
    return tp, appt, ret


class TestQrReworkCycle:
    def test_first_rework_cycle(self, api):
        """PRD §3.5: "A failed review routes the return back to its owner:
        from `QR_FAILED` the owning preparer returns it to `IN_PREPARATION`
        with no further preconditions, and the preparer's `active_case_count`
        rises by one. The return may cycle through review repeatedly, each
        failed pass counted in `qr_failure_count`, until it passes or exits
        through referral or withdrawal (§3.8)."

        Design: Difficulty/non_linear_state_machine/return_qr_rework_cycle
        """
        ctx = setup_staffed_site()
        tp, appt, ret = _pending_qr(ctx, "SSN-004", "Taxpayer Four")

        ret = review_fail(ret, ctx.reviewer["id"], "Missing W-2 wage match")
        assert ret["status"] == "QR_FAILED"
        assert ret["qr_failure_count"] == 1

        ret = transition_return(ret["id"], "IN_PREPARATION", ctx.prep_headers)
        assert ret["status"] == "IN_PREPARATION", (
            "the owner pulls the failed return back into preparation"
        )
        assert ret["qr_failure_count"] == 1

    def test_second_rework_cycle_accumulates(self, api):
        """PRD §3.5: "The return may cycle through review repeatedly, each
        failed pass counted in `qr_failure_count`, until it passes or exits
        through referral or withdrawal (§3.8)."

        Design: Difficulty/non_linear_state_machine/return_qr_rework_cycle
        """
        ctx = setup_staffed_site()
        tp, appt, ret = _pending_qr(ctx, "SSN-004", "Taxpayer Four")

        # First traversal: PENDING_QR -> QR_FAILED -> IN_PREPARATION.
        ret = review_fail(ret, ctx.reviewer["id"], "Missing W-2 wage match")
        ret = transition_return(ret["id"], "IN_PREPARATION", ctx.prep_headers)
        assert ret["status"] == "IN_PREPARATION"
        assert ret["qr_failure_count"] == 1

        # Second traversal of the same cycle.
        ret = submit_for_review(ret)
        ret = review_fail(ret, ctx.reviewer["id"], "Withholding mismatch persists")
        ret = transition_return(ret["id"], "IN_PREPARATION", ctx.prep_headers)
        assert ret["status"] == "IN_PREPARATION"
        assert ret["qr_failure_count"] == 2, (
            "each failed pass is counted across repeated cycles"
        )


class TestReviewGateOrdering:
    def _uncertified_reviewer(self, ctx):
        """A registered volunteer holding no certifications at all."""
        return register_volunteer(
            ctx.site_id, ctx.coord_headers,
            full_name="Rev Uncertified", email="revu@x.org",
        )

    def test_wrong_state_masks_uncertified_reviewer(self, api):
        """PRD §2.8: "Every request walks a fixed pipeline of validation
        tiers, and a failure in an earlier tier masks every later tier: the
        error a caller observes always comes from the earliest tier its
        request fails."
        PRD §2.8: "5. **State legality**, on every state-driving call, on
        identity verification, on rejection follow-up, on return edits, on
        allocation add and remove, and on appointment rescheduling: the
        requested transition must exist from the resource's current state —
        terminal states accept no transitions — and the editability windows
        must hold."

        Design: Difficulty/priority_pair_validation_conflict/review_wrong_state_and_uncertified_reviewer_rejected
        """
        ctx = setup_staffed_site()
        revu = self._uncertified_reviewer(ctx)
        tp, appt, ret = _prep_ready(ctx, "SSN-005", "Taxpayer Five")
        ret = begin_preparation(ret)
        assert ret["status"] == "IN_PREPARATION"

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "QR_PASSED"},
            make_quality_reviewer_headers(revu["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "IN_PREPARATION"

    def test_uncertified_reviewer_rejected_in_pending_qr(self, api):
        """PRD §3.5: "Both verdicts enforce the same two gates: the reviewer
        must be `ACTIVE` and hold `CURRENT` passed `INTAKE_QR` and `ADVANCED`
        certifications for season 2026 (`ERR_REVIEWER_NOT_CERTIFIED`), and
        the reviewer must not be the return's preparer — the
        segregation-of-duties rule (`ERR_REVIEWER_IS_PREPARER`)."

        Design: Difficulty/priority_pair_validation_conflict/review_wrong_state_and_uncertified_reviewer_rejected
        """
        ctx = setup_staffed_site()
        revu = self._uncertified_reviewer(ctx)
        tp, appt, ret = _pending_qr(ctx, "SSN-005", "Taxpayer Five")

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "QR_PASSED"},
            make_quality_reviewer_headers(revu["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_CERTIFIED)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "PENDING_QR"


class TestReviewerCertificationGate:
    def test_reviewer_missing_advanced_rejected(self, api):
        """PRD §3.5: "Both verdicts enforce the same two gates: the reviewer
        must be `ACTIVE` and hold `CURRENT` passed `INTAKE_QR` and `ADVANCED`
        certifications for season 2026 (`ERR_REVIEWER_NOT_CERTIFIED`), and
        the reviewer must not be the return's preparer — the
        segregation-of-duties rule (`ERR_REVIEWER_IS_PREPARER`)."

        Design: Difficulty/cross_entity_state_dependency/review_requires_certified_reviewer
        """
        ctx = setup_staffed_site()
        weak = add_reviewer(ctx, full_name="Rev Weak", email="revw@x.org",
                            with_advanced=False)
        assert weak["status"] == "ACTIVE"
        tp, appt, ret = _pending_qr(ctx, "SSN-009", "Taxpayer Nine")

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "QR_PASSED"},
            make_quality_reviewer_headers(weak["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_CERTIFIED)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "PENDING_QR"
        assert ret["reviewer_id"] is None

    def test_inactive_reviewer_rejected(self, api):
        """PRD §3.5: "Both verdicts enforce the same two gates: the reviewer
        must be `ACTIVE` and hold `CURRENT` passed `INTAKE_QR` and `ADVANCED`
        certifications for season 2026 (`ERR_REVIEWER_NOT_CERTIFIED`), and
        the reviewer must not be the return's preparer — the
        segregation-of-duties rule (`ERR_REVIEWER_IS_PREPARER`)."

        Design: Difficulty/cross_entity_state_dependency/review_requires_certified_reviewer
        """
        ctx = setup_staffed_site()
        tired = add_reviewer(ctx, full_name="Rev Idle", email="revi@x.org")
        tired = transition_volunteer(tired["id"], "INACTIVE", ctx.coord_headers)
        assert tired["status"] == "INACTIVE"
        tp, appt, ret = _pending_qr(ctx, "SSN-009", "Taxpayer Nine")

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "QR_PASSED"},
            make_quality_reviewer_headers(tired["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_CERTIFIED)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "PENDING_QR"
        assert ret["reviewer_id"] is None


class TestReviewSegregationAndRoles:
    def test_reviewer_is_preparer_rejected(self, api):
        """PRD §3.5: "Both verdicts enforce the same two gates: the reviewer
        must be `ACTIVE` and hold `CURRENT` passed `INTAKE_QR` and `ADVANCED`
        certifications for season 2026 (`ERR_REVIEWER_NOT_CERTIFIED`), and
        the reviewer must not be the return's preparer — the
        segregation-of-duties rule (`ERR_REVIEWER_IS_PREPARER`)."

        Design: Corner/rbac/reviewer_is_preparer_rejected
        """
        ctx = setup_staffed_site()
        # Give the preparer every certification, including the reviewer pair.
        prep = ctx.preparer
        record_certification(prep["id"], ctx.coord_headers,
                             test_type="INTAKE_QR", score=91)
        record_certification(prep["id"], ctx.coord_headers,
                             test_type="ADVANCED", score=86)
        ctx.preparer = get_volunteer(prep["id"], ctx.coord_headers)
        tp, appt, ret = _pending_qr(ctx, "SSN-RB3", "Tp RB3")

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "QR_PASSED"},
            make_quality_reviewer_headers(ctx.preparer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_IS_PREPARER)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "PENDING_QR"
        assert ret["reviewer_id"] is None

    def test_preparer_cannot_review(self, api):
        """PRD §3.5: "Review itself is performed by a `QualityReviewer` and
        ends in one of two verdicts."
        PRD §2.1: "Any action attempted outside the caller's role envelope is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/preparer_cannot_review
        """
        ctx = setup_staffed_site()
        tp, appt, ret = _pending_qr(ctx, "SSN-RB1", "Tp RB1")

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "QR_PASSED"}, ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "PENDING_QR"

    def test_other_preparer_submit_rejected(self, api):
        """PRD §3.5: "Submitting for review — `IN_PREPARATION` to
        `PENDING_QR`, again owner-only (`ERR_NOT_RETURN_OWNER`)"
        PRD §2.1: "Second, preparer-only lifecycle steps on a return compare
        `X-User-ID` against the return's `preparer_id`; a preparer attempting
        such a step on a return it does not own is rejected with
        `ERR_NOT_RETURN_OWNER` (HTTP 403)."

        Design: Corner/rbac/other_preparer_submit_rejected
        """
        ctx = setup_staffed_site()
        # Build the return with the site's original preparer first:
        # add_preparer reassigns ctx.preparer to the volunteer it adds.
        tp, appt, ret = _prep_ready(ctx, "SSN-RB5", "Tp RB5")
        ret = begin_preparation(ret)
        owner_id = ret["preparer_id"]
        other = add_preparer(ctx, full_name="Prep B", email="prepb@x.org",
                             basic_score=89)

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "PENDING_QR"},
            make_preparer_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RETURN_OWNER)
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "IN_PREPARATION"
        assert ret["preparer_id"] == owner_id


class TestPreparerCaseLoadConservation:
    def test_case_load_forward_and_release(self, api):
        """PRD §3.2: "`active_case_count` counts the volunteer's returns
        presently in `IN_PREPARATION`; its ebb and flow through the return
        lifecycle is detailed in §3.4 through §3.8."
        PRD §3.4: "On entry, `reached_preparation` flips to true and is never
        cleared, and the preparer's `active_case_count` increases by one."
        PRD §3.5: "Submission also releases the preparer's caseload:
        `active_case_count` decreases by one."

        Design: Difficulty/compensating_invariant/preparer_case_load_conservation
        """
        ctx = setup_staffed_site()
        tp, appt, ret = _prep_ready(ctx, "SSN-011", "Taxpayer Eleven")

        load = get_volunteer(ctx.preparer["id"], ctx.coord_headers)["active_case_count"]
        assert load == 0, "INTAKE_STARTED does not yet count as an active case"

        ret = begin_preparation(ret)
        load = get_volunteer(ctx.preparer["id"], ctx.coord_headers)["active_case_count"]
        assert load == 1, "entering IN_PREPARATION adds one (+1)"

        ret = submit_for_review(ret)
        load = get_volunteer(ctx.preparer["id"], ctx.coord_headers)["active_case_count"]
        assert load == 0, "submitting for review releases the caseload (-1)"

    def test_case_load_rework_restores(self, api):
        """PRD §3.5: "A failed review routes the return back to its owner:
        from `QR_FAILED` the owning preparer returns it to `IN_PREPARATION`
        with no further preconditions, and the preparer's `active_case_count`
        rises by one."

        Design: Difficulty/compensating_invariant/preparer_case_load_conservation
        """
        ctx = setup_staffed_site()
        tp, appt, ret = _pending_qr(ctx, "SSN-011", "Taxpayer Eleven")
        load = get_volunteer(ctx.preparer["id"], ctx.coord_headers)["active_case_count"]
        assert load == 0

        ret = review_fail(ret, ctx.reviewer["id"], "Figure mismatch")
        ret = transition_return(ret["id"], "IN_PREPARATION", ctx.prep_headers)
        load = get_volunteer(ctx.preparer["id"], ctx.coord_headers)["active_case_count"]
        assert load == 1, (
            "the compensating rework restores the preparer's active case count"
        )


class TestFinalRefundDetermination:
    def test_final_refund_tier_cap_binds(self, api):
        """PRD §3.5: "First, tier selection on `qualifying_children`: with no
        qualifying children the credit rate is 10 percent and its cap is
        $600; with one qualifying child the rate is 20 percent and the cap is
        $4,000; with two or more the rate is 25 percent and the cap is
        $6,500. Second, the final earned-income credit is the lesser of the
        tier rate multiplied by `earned_income_cents` — the multiplication
        rounded half-up to whole cents — and the tier cap. Third, the tax
        liability is 12 percent of the sum of `wages_cents` and
        `other_income_cents`, rounded half-up to whole cents. Finally,
        `final_refund_cents` is the verified withholding plus the final
        credit minus the liability, floored at zero."

        Design: Difficulty/combinatorial_formula/eitc_final_tier_cap_composition
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Taxpayer Two",
                                      ssn_token="SSN-002", phone="555-0102")
        appt, ret = create_preparation_ready_return(
            ctx, tp["id"],
            return_overrides={"filing_status": "HEAD_OF_HOUSEHOLD"},
            patch_overrides={
                "wages_cents": 3000000, "other_income_cents": 500000,
                "earned_income_cents": 3000000, "qualifying_children": 2,
                "withholding_reported_cents": 200000,
                "withholding_verified_cents": 200000,
            },
        )
        ret = begin_preparation(ret)
        ret = submit_for_review(ret)
        # eitc = min(round(0.25 * 3000000) = 750000, 650000) = 650000 (cap binds)
        # liability = round(0.12 * 3500000) = 420000
        # refund = max(0, 200000 + 650000 - 420000)
        assert ret["final_refund_cents"] == 430000

    def test_estimate_uses_provisional_variant_on_same_inputs(self, api):
        """PRD §3.4: "The provisional estimate shown at intake deliberately
        assumes zero tax liability and trusts self-reported withholding:
        `estimated_refund_cents` is the taxpayer-reported
        `withholding_reported_cents` plus an estimated earned-income credit
        equal to the lesser of 15 percent of `earned_income_cents` — the
        multiplication rounded half-up to whole cents — and $6,000."

        Design: Difficulty/combinatorial_formula/eitc_final_tier_cap_composition
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Taxpayer Two",
                                      ssn_token="SSN-002", phone="555-0102")
        appt, ret = create_preparation_ready_return(
            ctx, tp["id"],
            return_overrides={"filing_status": "HEAD_OF_HOUSEHOLD"},
            patch_overrides={
                "wages_cents": 3000000, "other_income_cents": 500000,
                "earned_income_cents": 3000000, "qualifying_children": 2,
                "withholding_reported_cents": 200000,
                "withholding_verified_cents": 200000,
            },
        )
        # 200000 + min(round_half_up(0.15 * 3000000) = 450000, 600000)
        assert ret["estimated_refund_cents"] == 650000

    def test_estimate_cap_binds_at_equality(self, api):
        """PRD §3.4: "`estimated_refund_cents` is the taxpayer-reported
        `withholding_reported_cents` plus an estimated earned-income credit
        equal to the lesser of 15 percent of `earned_income_cents` — the
        multiplication rounded half-up to whole cents — and $6,000."

        Design: Corner/calculations/estimate_cap_binds_at_equality
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp Cap",
                                      ssn_token="SSN-CAP", phone="555-2013")
        appt, ret = create_intake_return(ctx, tp["id"])
        ret = patch_return(
            ret, ctx.prep_headers,
            wages_cents=4000000, earned_income_cents=4000000,
            withholding_reported_cents=100000,
        )
        # 0.15 * 4000000 == 600000 == the cap: min() binds at equality
        assert ret["estimated_refund_cents"] == 700000
