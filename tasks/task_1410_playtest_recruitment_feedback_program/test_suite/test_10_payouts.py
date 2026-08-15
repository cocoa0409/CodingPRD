"""Incentive payouts: dual-variant amounts, tier boundaries, fiscal and
segregation-of-duties gates."""
from test_helpers import (
    ApiErrorId,
    approve_payout,
    assign_moderator,
    book_session,
    close_study,
    create_draft_payout,
    create_moderator,
    create_payout_payload,
    create_remote_session,
    enroll_participant,
    get_payout,
    get_study,
    get_success_data,
    issue_payout,
    make_officer_headers,
    OFFICER_1,
    OFFICER_2,
    OFFICER_3,
    register_participant,
    run_session_at_midpoint,
    SESSION_SLOTS,
    set_clock,
    setup_enrolled_participant,
    setup_participant_session_history,
    setup_payout_ready,
    setup_study_with_published_nda,
    submit_payout,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


class TestProvisionalVsFinalRecompute:
    """2 ATTENDED + 1 NO_SHOW + 1 passed survey: provisional 13500, final 11500."""

    def _setup_pending_payout(self, api):
        ctx = setup_payout_ready(outcomes=["attended", "attended", "no_show"],
                                 passed_surveys=1, budget=1000000)
        payout = create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                                     officer_id=OFFICER_1)
        submit_payout(payout["id"], officer_id=OFFICER_1)
        return ctx, payout

    def test_final_recompute_subtracts_no_show_penalty(self, api):
        """PRD §3.8: "The **provisional** amount is the scaled base, rounded
        half-up to whole cents, plus the survey bonus, with no penalty term.
        The **final** amount is recomputed live at approval from the same
        ingredients — late attendance, no-show, and survey changes flow in —
        and then reduced by 2,000 cents per no-show, floored at zero so a heavy
        no-show record can never drive a payout negative. Identical underlying
        data therefore yields a final amount at most equal to the provisional
        one, and strictly less whenever any no-show exists."

        Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_recompute
        """
        ctx, payout = self._setup_pending_payout(api)
        # provisional: round(2 * 5000 * 1.25) + 1 * 1000 = 13500, penalty-free.
        assert payout["amount_provisional_cents"] == 13500
        approved = approve_payout(payout["id"], officer_id=OFFICER_2)
        # final: 13500 - 1 * 2000 = 11500, recomputed live.
        assert approved["amount_final_cents"] == 11500
        assert approved["amount_final_cents"] < payout["amount_provisional_cents"]

    def test_provisional_stays_frozen_and_budget_commits_final(self, api):
        """PRD §3.8: "Creation computes the provisional variant of the
        incentive amount and freezes it into `amount_provisional_cents` —
        never recomputed for that payout again"
        PRD §3.8: "on success the payout's `amount_final_cents` is stored and
        the same amount is added to `budget_committed_cents`, and
        `approved_by_user_id` records the approving officer."

        Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_recompute
        """
        ctx, payout = self._setup_pending_payout(api)
        assert payout["amount_provisional_cents"] == 13500
        approve_payout(payout["id"], officer_id=OFFICER_2)
        after = get_payout(payout["id"])
        assert after["status"] == "APPROVED"
        assert after["amount_provisional_cents"] == 13500, (
            "the provisional snapshot is frozen at creation")
        assert after["amount_final_cents"] == 11500
        assert after["approved_by_user_id"] == OFFICER_2
        assert get_study(ctx["study"]["id"])["budget_committed_cents"] == 11500


class TestTieredMultiplierThreeInputs:
    """3 ATTENDED + 1 passed survey: provisional round(3*5000*1.5) + 1000."""

    def test_three_attended_plus_survey_computes_23500(self, api):
        """PRD §3.8: "The base is the attended count multiplied by 5,000 cents.
        A tier multiplier scales that base: one and a half when the attended
        count is at least 3 — exactly three attended sessions enters the top
        tier — one and a quarter when it is exactly 2, and one otherwise. The
        survey bonus adds 1,000 cents per passed survey. The **provisional**
        amount is the scaled base, rounded half-up to whole cents, plus the
        survey bonus, with no penalty term."

        Design: Difficulty/combinatorial_formula/incentive_tiered_multiplier_three_inputs
        """
        ctx = setup_payout_ready(outcomes=["attended", "attended", "attended"],
                                 passed_surveys=1)
        payout = create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                                     officer_id=OFFICER_1)
        # round(3 * 5000 * 1.5) + 1 * 1000 = 22500 + 1000.
        assert payout["amount_provisional_cents"] == 23500

    def test_draft_records_creator_and_leaves_final_null(self, api):
        """PRD §3.8: "Creation computes the provisional variant of the
        incentive amount and freezes it into `amount_provisional_cents` —
        never recomputed for that payout again — records the drafting officer
        in `created_by_user_id`, and leaves `amount_final_cents` null until
        approval. A new payout is `DRAFT`"

        Design: Difficulty/combinatorial_formula/incentive_tiered_multiplier_three_inputs
        """
        ctx = setup_payout_ready(outcomes=["attended", "attended", "attended"],
                                 passed_surveys=1)
        payout = create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                                     officer_id=OFFICER_1)
        assert payout["status"] == "DRAFT"
        assert payout["amount_provisional_cents"] == 23500
        assert payout["amount_final_cents"] is None
        assert payout["created_by_user_id"] == OFFICER_1


class TestTierBoundaryAtThreeAttended:
    def _setup_two_histories(self, api):
        """A attends all three sessions; B attends the first two."""
        set_clock("2026-08-01T00:00:00Z")
        study, _nda = setup_study_with_published_nda(code="BP2")
        pa = register_participant(email="bp2-a@x.com")
        enroll_participant(study["id"], pa)
        pb = register_participant(email="bp2-b@x.com", age_years=27)
        enroll_participant(study["id"], pb)
        moderator = create_moderator(display_name="Mod BP2")
        sessions, bk_a, bk_b = [], [], []
        for i, (start, end) in enumerate(SESSION_SLOTS[:3]):
            session = create_remote_session(study["id"], start, end,
                                            seat_capacity=2 if i < 2 else 1)
            assign_moderator(session["id"], moderator["id"])
            sessions.append(session)
            bk_a.append(book_session(session["id"], pa["id"]))
            if i < 2:
                bk_b.append(book_session(session["id"], pb["id"]))
        close_study(study["id"])
        for i, session in enumerate(sessions):
            attend = [bk_a[i]["id"]] + ([bk_b[i]["id"]] if i < 2 else [])
            run_session_at_midpoint(session, moderator["id"],
                                    attend_booking_ids=attend)
        return study, pa, pb

    def test_three_attended_enters_top_tier(self, api):
        """PRD §3.8: "A tier multiplier scales that base: one and a half when
        the attended count is at least 3 — exactly three attended sessions
        enters the top tier — one and a quarter when it is exactly 2, and one
        otherwise."

        Design: Difficulty/boundary_precision_check/incentive_tier_boundary_at_three_attended
        """
        study, pa, _pb = self._setup_two_histories(api)
        payout_a = create_draft_payout(study["id"], pa["id"], officer_id=OFFICER_1)
        # Boundary inclusive: attended == 3 exactly -> round(3 * 5000 * 1.5).
        assert payout_a["amount_provisional_cents"] == 22500

    def test_two_attended_stays_in_mid_tier(self, api):
        """PRD §3.8: "one and a half when the attended count is at least 3 —
        exactly three attended sessions enters the top tier — one and a quarter
        when it is exactly 2, and one otherwise."

        Design: Difficulty/boundary_precision_check/incentive_tier_boundary_at_three_attended
        """
        study, pa, pb = self._setup_two_histories(api)
        payout_a = create_draft_payout(study["id"], pa["id"], officer_id=OFFICER_1)
        payout_b = create_draft_payout(study["id"], pb["id"], officer_id=OFFICER_1)
        # attended == 2 -> round(2 * 5000 * 1.25) = 12500.
        assert payout_b["amount_provisional_cents"] == 12500
        assert payout_a["amount_provisional_cents"] == 22500
        assert (payout_a["amount_provisional_cents"]
                - payout_b["amount_provisional_cents"]) == 10000, (
            "crossing the attended==3 boundary is discontinuous")


class TestPayoutApproveStateBeatsFiscal:
    """DRAFT payout on a study whose budget (100) cannot cover the final
    amount (5000): state and fiscal checks both fail; state wins."""

    def _setup_draft_on_tiny_budget(self, api):
        ctx = setup_payout_ready(outcomes=["attended"], passed_surveys=0, budget=100)
        payout = create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                                     officer_id=OFFICER_1)
        assert payout["status"] == "DRAFT"  # never submitted
        return ctx, payout

    def test_draft_approve_returns_invalid_state_not_budget(self, api):
        """PRD §3.8: "The payout must be `PENDING_APPROVAL` — this state check
        outranks the budget gate, and a payout in any other state fails with
        `ERR_INVALID_STATE`."
        PRD §3.8: "And the budget check runs last — state and compliance
        failures always win over budget failures"

        Design: Difficulty/priority_pair_validation_conflict/payout_approve_state_beats_fiscal
        """
        _ctx, payout = self._setup_draft_on_tiny_budget(api)
        resp = api.approve_payout(payout["id"], make_officer_headers(OFFICER_2))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] != "ERR_BUDGET_EXCEEDED", (
            "both violations were present; the fiscal error must not surface")

    def test_rejected_approve_mutates_nothing(self, api):
        """PRD §3.8: "an excess rejects the approval with `ERR_BUDGET_EXCEEDED`
        and changes nothing"
        PRD §3.8: "leaves `amount_final_cents` null until approval"

        Design: Difficulty/priority_pair_validation_conflict/payout_approve_state_beats_fiscal
        """
        ctx, payout = self._setup_draft_on_tiny_budget(api)
        validate_error(api.approve_payout(payout["id"], make_officer_headers(OFFICER_2)),
                       ApiErrorId.ERR_INVALID_STATE)
        after = get_payout(payout["id"])
        assert after["status"] == "DRAFT"
        assert after["amount_final_cents"] is None
        assert get_study(ctx["study"]["id"])["budget_committed_cents"] == 0


def test_budget_exceeded_on_approve(api):
    """PRD §3.8: "first the final amount is computed; then the study's
    `budget_committed_cents` plus that final amount is compared against
    `incentive_budget_cents`, and an excess rejects the approval with
    `ERR_BUDGET_EXCEEDED` and changes nothing; on success the payout's
    `amount_final_cents` is stored and the same amount is added to
    `budget_committed_cents`"

    Design: Corner/validations/budget_exceeded_on_approve
    """
    ctx = setup_payout_ready(outcomes=["attended"], passed_surveys=0, budget=4000)
    payout = create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                                 officer_id=OFFICER_1)
    submit_payout(payout["id"], officer_id=OFFICER_1)
    # committed 0 + final 5000 > budget 4000.
    resp = api.approve_payout(payout["id"], make_officer_headers(OFFICER_2))
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
    after = get_payout(payout["id"])
    assert after["status"] == "PENDING_APPROVAL"
    assert after["amount_final_cents"] is None, "the rejection changed nothing"
    assert get_study(ctx["study"]["id"])["budget_committed_cents"] == 0


def test_payout_create_without_attendance_rejected(api):
    """PRD §3.8: "Drafting requires at least one `ATTENDED` booking by that
    participant in that study (`ERR_NO_COMPENSABLE_ACTIVITY`)"

    Design: Corner/validations/payout_create_without_attendance_rejected
    """
    ctx = setup_enrolled_participant(email="nca-p@x.com")
    resp = api.create_incentive_payout(
        create_payout_payload(ctx["study"]["id"], ctx["participant"]["id"]),
        make_officer_headers(OFFICER_1))
    validate_error(resp, ApiErrorId.ERR_NO_COMPENSABLE_ACTIVITY)


def test_duplicate_payout_rejected(api):
    """PRD §3.8: "at most one payout per pair may exist outside `VOID` — a
    payout in `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, or `ISSUED`
    blocks a second with `ERR_DUPLICATE_PAYOUT`."

    Design: Corner/validations/duplicate_payout_rejected
    """
    ctx = setup_payout_ready(outcomes=["attended"], passed_surveys=0)
    create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                        officer_id=OFFICER_1)
    resp = api.create_incentive_payout(
        create_payout_payload(ctx["study"]["id"], ctx["participant"]["id"]),
        make_officer_headers(OFFICER_1))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYOUT)


def test_payout_segregation_of_duties_chain(api):
    """PRD §2.10: "The officer who drafts a payout may not approve it, and the
    officer who approves it may not issue it — three distinct
    `IncentiveOfficer` identities are required across the lifecycle, recorded
    as `created_by_user_id`, `approved_by_user_id`, and `issued_by_user_id`."
    PRD §3.8: "Segregation of duties forbids the officer recorded in
    `created_by_user_id` from approving their own draft
    (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §3.8: "Issuance moves `APPROVED` → `ISSUED`: the issuing officer must
    differ from the officer in `approved_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`), the study's `budget_spent_cents` increases
    by `amount_final_cents`, and `issued_by_user_id` records the issuer."

    Design: Corner/validations/payout_segregation_of_duties_chain
    """
    ctx = setup_payout_ready(outcomes=["attended"], passed_surveys=0)
    payout = create_draft_payout(ctx["study"]["id"], ctx["participant"]["id"],
                                 officer_id=OFFICER_1)
    submit_payout(payout["id"], officer_id=OFFICER_1)
    # The creator cannot approve their own draft.
    validate_error(api.approve_payout(payout["id"], make_officer_headers(OFFICER_1)),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    approved = approve_payout(payout["id"], officer_id=OFFICER_2)
    assert approved["status"] == "APPROVED"
    assert approved["amount_final_cents"] == 5000, (
        "1 attended -> 5000 * 1.0, no surveys, no no-shows")
    assert approved["approved_by_user_id"] == OFFICER_2
    # The approver cannot issue.
    validate_error(api.issue_payout(payout["id"], make_officer_headers(OFFICER_2)),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    issued = issue_payout(payout["id"], officer_id=OFFICER_3)
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == OFFICER_3
    study = get_study(ctx["study"]["id"])
    assert study["budget_committed_cents"] == 5000
    assert study["budget_spent_cents"] == 5000
