"""Financial aid: the two-variant award formula, verification, segregation,
appeals, resubmission, and the pacing money gate (PRD §3.4, §3.1)."""
from test_helpers import (
    ApiErrorId,
    accept_aid,
    finalize_aid,
    get_aid,
    get_cycle,
    make_aid_application,
    make_applicant,
    make_application,
    make_fao_headers,
    make_parent_headers,
    resubmit_income,
    run_sweep,
    set_clock,
    setup_finalized_aid,
    setup_issued_contract_world,
    setup_offered_application,
    setup_pacing_boundary_world,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
    verify_aid,
)


class TestDualVariantAward:
    """Difficulty: the same tiered formula runs on reported income (filing,
    resubmission) and on verified income (finalization); divergent inputs
    diverge."""

    def test_provisional_award_computed_at_filing(self, api, director_headers):
        """PRD §3.4: "A new aid application starts with `verification_status`
        `SUBMITTED` and `award_status` `PROVISIONAL`, and its
        `provisional_award_cents` is computed immediately."
        PRD §3.4: "The provisional variant applies this recipe to
        `reported_annual_income_cents` — at filing and on every income
        resubmission — and stores the result in `provisional_award_cents`."

        Design: Difficulty/dual_variant_calc/aid_award_provisional_vs_final_diverge
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        resp = api.create_aid_application(
            {"application_id": ctx["application"]["id"],
             "reported_annual_income_cents": 9_500_000, "household_size": 4},
            make_parent_headers("fam-a"),
        )
        data = validate_success(resp, 201)
        # Allowance 5,500,000; discretionary 4,000,000; EFC 300,000 + 330,000
        # = 630,000; need 2,370,000 (< the 2,700,000 cap).
        assert data["provisional_award_cents"] == 2_370_000
        assert data["verification_status"] == "SUBMITTED"
        assert data["award_status"] == "PROVISIONAL"
        assert data["final_award_cents"] is None

    def test_final_award_diverges_from_provisional(self, api, director_headers):
        """PRD §3.4: "The final variant applies it to
        `verified_annual_income_cents` at finalization and stores the result in
        `final_award_cents`; whenever verified income differs from reported
        income, identical structure yields a different award."

        Design: Difficulty/dual_variant_calc/aid_award_provisional_vs_final_diverge
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a",
                                   9_500_000, 4)
        verify_aid(aid["id"], 12_000_000, officer_id="fao-1")
        finalize_aid(aid["id"], officer_id="fao-2")
        data = get_aid(aid["id"])
        # Verified 12,000,000: discretionary 6,500,000; EFC 300,000 + 880,000
        # = 1,180,000; need 1,820,000.
        assert data["final_award_cents"] == 1_820_000
        assert data["provisional_award_cents"] == 2_370_000
        assert data["final_award_cents"] != data["provisional_award_cents"]
        assert data["verification_status"] == "VERIFIED"
        assert data["award_status"] == "OFFERED"


class TestTieredEfc:
    """Difficulty: three input axes (income, household, tuition) with the
    three-tier progressive EFC; the tier-3 term discriminates."""

    def test_provisional_crosses_all_three_tiers(self, api, director_headers):
        """PRD §3.4: "Third, the expected family contribution is assembled
        from three progressive tiers of discretionary income: twelve percent
        of the first 2,500,000 cents, plus twenty-two percent of the next
        5,000,000 cents, plus thirty percent of whatever discretionary income
        remains beyond the first two tiers combined — that is, beyond the
        first 7,500,000 cents of discretionary income — with each tier's
        contribution rounded half-up to a whole cent before the three are
        summed."

        Design: Difficulty/combinatorial_formula/aid_award_tiered_efc_crossing_tiers
        """
        ctx = setup_submitted_application("fam-b", round_name="REGULAR",
                                          grade_level="G10",
                                          tuition_cents=4_000_000,
                                          with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-b",
                                   11_000_000, 1)
        # Allowance 3,250,000; discretionary 7,750,000; EFC 300,000 +
        # 1,100,000 + 75,000 = 1,475,000; need 2,525,000; cap 3,600,000.
        assert aid["provisional_award_cents"] == 2_525_000

    def test_final_matches_provisional_when_incomes_match(
            self, api, director_headers):
        """PRD §3.4: "The final variant applies it to
        `verified_annual_income_cents` at finalization and stores the result
        in `final_award_cents`; whenever verified income differs from reported
        income, identical structure yields a different award."

        Design: Difficulty/combinatorial_formula/aid_award_tiered_efc_crossing_tiers
        """
        ctx = setup_submitted_application("fam-b", round_name="REGULAR",
                                          grade_level="G10",
                                          tuition_cents=4_000_000,
                                          with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-b",
                                   11_000_000, 1)
        verify_aid(aid["id"], 11_000_000, officer_id="fao-1")
        finalize_aid(aid["id"], officer_id="fao-2")
        data = get_aid(aid["id"])
        assert data["final_award_cents"] == 2_525_000
        assert data["provisional_award_cents"] == 2_525_000


class TestAwardFormulaBoundaries:
    def test_award_at_allowance_boundary_uses_cap(self, api, director_headers):
        """PRD §3.4: "First, a household allowance is computed as a base of
        2,500,000 cents plus 750,000 cents for each member of
        `household_size`."
        PRD §3.4: "Finally, the award is the smaller of demonstrated need and
        ninety percent of that tuition, with the percentage cap itself rounded
        half-up to a whole cent."

        Design: Corner/calculations/award_at_allowance_boundary_uses_cap
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a",
                                   5_500_000, 4)
        # Income == allowance (2,500,000 + 750,000*4): EFC 0, need 3,000,000,
        # award clamped to the 90% cap of exactly 2,700,000.
        assert aid["provisional_award_cents"] == 2_700_000

    def test_tier1_exact_boundary_and_cap_binding(self, api, director_headers):
        """PRD §3.4: "twelve percent of the first 2,500,000 cents, plus
        twenty-two percent of the next 5,000,000 cents, plus thirty percent of
        whatever discretionary income remains beyond the first two tiers
        combined".
        PRD §3.4: "Finally, the award is the smaller of demonstrated need and
        ninety percent of that tuition".

        Design: Corner/calculations/tier1_exact_boundary_and_cap_binding
        """
        ctx = setup_submitted_application("fam-b", round_name="REGULAR",
                                          grade_level="G10",
                                          tuition_cents=4_000_000,
                                          with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-b",
                                   5_750_000, 1)
        verify_aid(aid["id"], 5_750_000, officer_id="fao-1")
        finalize_aid(aid["id"], officer_id="fao-2")
        # Discretionary 2,500,000 == tier-1 width exactly: EFC 300,000 with no
        # tier-2 spill; need 3,700,000 exceeds the 90% cap -> 3,600,000.
        assert get_aid(aid["id"])["final_award_cents"] == 3_600_000


class TestVerificationAndFinalizationGates:
    def test_verify_already_verified_rejected(self, api, fao_1_headers):
        """PRD §3.4: "Verification is performed by a `FinancialAidOfficer` and
        requires `verification_status` to be `SUBMITTED"
        (`ERR_AID_NOT_SUBMITTED` otherwise)."

        Design: Corner/validations/verify_already_verified_rejected
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a")
        verify_aid(aid["id"], 9_500_000, officer_id="fao-1")
        resp = api.verify_aid(aid["id"], 9_500_000, fao_1_headers)
        validate_error(resp, ApiErrorId.ERR_AID_NOT_SUBMITTED, 409)
        assert get_aid(aid["id"])["verified_annual_income_cents"] == 9_500_000

    def test_finalize_unverified_aid_rejected(self, api, fao_2_headers):
        """PRD §3.4: "Finalizing an award requires `verification_status`
        `VERIFIED` (`ERR_AID_NOT_VERIFIED` otherwise)".
        PRD §3.4: "While the award remains `PROVISIONAL`, `final_award_cents`
        is null."

        Design: Corner/validations/finalize_unverified_aid_rejected
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a")
        resp = api.finalize_award(aid["id"], fao_2_headers)
        validate_error(resp, ApiErrorId.ERR_AID_NOT_VERIFIED, 409)
        data = get_aid(aid["id"])
        assert data["award_status"] == "PROVISIONAL"
        assert data["final_award_cents"] is None

    def test_duplicate_aid_application_rejected(self, api):
        """PRD §3.4: "A family seeking assistance files an `AidApplication` —
        at most one per admission application, ever; a second filing draws
        `ERR_DUPLICATE_AID_APPLICATION`."

        Design: Corner/validations/duplicate_aid_application_rejected
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        make_aid_application(ctx["application"]["id"], "fam-a",
                             9_500_000, 4)
        resp = api.create_aid_application(
            {"application_id": ctx["application"]["id"],
             "reported_annual_income_cents": 4_000_000, "household_size": 3},
            make_parent_headers("fam-a"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AID_APPLICATION, 409)


class TestAppealAndAcceptanceGates:
    def test_appeal_provisional_award_rejected(self, api):
        """PRD §3.4: "Appeal instead requires only `award_status` `OFFERED`
        (`ERR_AWARD_NOT_APPEALABLE` otherwise), stores the family's
        `appeal_reason` — null unless an appeal was filed — and moves the
        award `OFFERED` → `APPEALED`."

        Design: Corner/state_machines/appeal_provisional_award_rejected
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a")
        resp = api.appeal_award(aid["id"], "too early but trying",
                                make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_AWARD_NOT_APPEALABLE, 409)
        assert get_aid(aid["id"])["award_status"] == "PROVISIONAL"

    def test_revise_unappealed_award_rejected(self, api):
        """PRD §3.4: "revises an award in `APPEALED` (`ERR_AWARD_NOT_APPEALED`
        otherwise) by supplying `revised_final_amount_cents`."

        Design: Corner/state_machines/revise_unappealed_award_rejected
        """
        ctx = setup_finalized_aid("fam-a", 12_000_000, 4, 12_000_000)
        resp = api.revise_award(ctx["aid"]["id"], 1_900_000,
                                make_fao_headers("fao-2"))
        validate_error(resp, ApiErrorId.ERR_AWARD_NOT_APPEALED, 409)
        data = get_aid(ctx["aid"]["id"])
        assert data["award_status"] == "OFFERED"
        assert data["final_award_cents"] == 1_820_000

    def test_accept_provisional_award_rejected(self, api):
        """PRD §3.4: "Acceptance requires `award_status` `OFFERED`
        (`ERR_AWARD_NOT_OFFERED` otherwise)".

        Design: Corner/validations/accept_provisional_award_rejected
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a")
        resp = api.accept_award(aid["id"], make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_AWARD_NOT_OFFERED, 409)
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 0

    def test_resubmit_accepted_award_locked_rejected(self, api):
        """PRD §3.4: "Resubmitting income — open to `Parent` callers while the
        award is neither `ACCEPTED` nor `RELEASED` (`ERR_AWARD_LOCKED`
        otherwise)".

        Design: Corner/validations/resubmit_accepted_award_locked_rejected
        """
        ctx = setup_finalized_aid("fam-a", 12_000_000, 4, 12_000_000)
        accept_aid(ctx["aid"]["id"], "fam-a")
        resp = api.resubmit_income(
            ctx["aid"]["id"],
            {"reported_annual_income_cents": 9_000_000, "household_size": 4},
            make_parent_headers("fam-a"),
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_LOCKED, 409)
        data = get_aid(ctx["aid"]["id"])
        assert data["verification_status"] == "VERIFIED"
        assert data["award_status"] == "ACCEPTED"


class TestParallelAidDimensions:
    """Difficulty: verification_status and award_status are two parallel
    cyclic dimensions on one aid application; each loop moves one dimension
    without touching the other."""

    def test_appeal_and_revise_leave_verification_untouched(
            self, api, fao_2_headers):
        """PRD §3.4: "Revision sets `final_award_cents` to the revised amount
        and returns the award `APPEALED` → `OFFERED`, so the `OFFERED` ↔
        `APPEALED` cycle may repeat."

        Design: Difficulty/non_linear_state_machine/aid_verification_and_award_parallel_cycles
        """
        ctx = setup_finalized_aid("fam-a", 9_500_000, 4, 12_000_000)
        aid_id = ctx["aid"]["id"]
        data = validate_success(
            api.appeal_award(aid_id, "parent job loss in October",
                             make_parent_headers("fam-a"))
        )
        # Dimension 1 moves alone: award APPEALED, verification stays VERIFIED.
        assert data["award_status"] == "APPEALED"
        assert data["verification_status"] == "VERIFIED"
        data = validate_success(api.revise_award(aid_id, 1_900_000,
                                                 fao_2_headers))
        assert data["award_status"] == "OFFERED"
        assert data["final_award_cents"] == 1_900_000
        assert data["verification_status"] == "VERIFIED"

    def test_resubmit_and_reverify_leave_award_fields_untouched(
            self, api, fao_1_headers):
        """PRD §3.4: "The `award_status` itself is unchanged: an `OFFERED`
        award stays `OFFERED` but is now stale, since acceptance requires
        `verification_status` `VERIFIED`."
        PRD §3.4: "Verification itself changes neither
        `provisional_award_cents` nor any `final_award_cents`."

        Design: Difficulty/non_linear_state_machine/aid_verification_and_award_parallel_cycles
        """
        ctx = setup_finalized_aid("fam-a", 9_500_000, 4, 12_000_000)
        aid_id = ctx["aid"]["id"]
        validate_success(api.appeal_award(aid_id, "parent job loss in October",
                                          make_parent_headers("fam-a")))
        validate_success(api.revise_award(aid_id, 1_900_000,
                                          make_fao_headers("fao-2")))
        # Dimension 2 moves alone: verification drops, award stays OFFERED.
        data = resubmit_income(aid_id, "fam-a", 11_000_000, 4)
        assert data["verification_status"] == "SUBMITTED"
        assert data["award_status"] == "OFFERED"
        # Recomputed provisional on reported 11,000,000 hh4: EFC 300,000 +
        # 660,000 = 960,000; need 2,040,000.
        assert data["provisional_award_cents"] == 2_040_000
        assert data["final_award_cents"] == 1_900_000
        data = validate_success(api.verify_aid(aid_id, 11_000_000,
                                               fao_1_headers))
        assert data["verification_status"] == "VERIFIED"
        assert data["award_status"] == "OFFERED"
        assert data["final_award_cents"] == 1_900_000  # verify recomputes nothing


def _stale_and_full_pacing_world():
    """Committed exactly at the 7,220,000 OPEN ceiling; fam-x's 2,700,000
    award OFFERED then made stale by a resubmission. Single shared cycle."""
    ctx = setup_pacing_boundary_world()
    accept_aid(ctx["fam3"]["aid"]["id"], "fam-3")  # committed == 7,220,000
    # fam-x files on its own application in the SAME cycle.
    applicant = make_applicant("fam-x", first_name="Xan", last_name="Xu")
    application = make_application(applicant["id"], ctx["cycle"]["id"],
                                   ctx["section"]["id"], "fam-x", "EARLY")
    submit_application(application["id"], "fam-x")
    aid = make_aid_application(application["id"], "fam-x", 5_500_000, 4)
    verify_aid(aid["id"], 5_500_000, officer_id="fao-1")
    finalize_aid(aid["id"], officer_id="fao-2")
    resubmit_income(aid["id"], "fam-x", 6_000_000, 4)  # stale the offer
    ctx["famx"] = {"applicant": applicant, "application": application,
                   "aid": get_aid(aid["id"])}
    return ctx


class TestStaleVerificationBeatsPacing:
    """Difficulty: with both the referential staleness gate and the fiscal
    pacing gate violated, the referential error is reported (the pipeline
    runs money gates last)."""

    def test_stale_verification_wins_over_pacing_cap(self, api):
        """PRD §2.7: "The ordering is observable behavior: ... a money-gate
        violation is reported only after every state, temporal, and constraint
        check has passed."
        PRD §3.4: "a family that resubmitted income after finalization finds
        its offer stale and acceptance blocked with
        `ERR_AWARD_STALE_VERIFICATION` until re-verified."

        Design: Difficulty/priority_pair_validation_conflict/award_accept_stale_verification_beats_pacing
        """
        ctx = _stale_and_full_pacing_world()
        resp = api.accept_award(ctx["famx"]["aid"]["id"],
                                make_parent_headers("fam-x"))
        # 7,220,000 committed + 2,700,000 would also breach the cap (402);
        # the referential 409 must be what surfaces.
        validate_error(resp, ApiErrorId.ERR_AWARD_STALE_VERIFICATION, 409)
        assert get_aid(ctx["famx"]["aid"]["id"])["award_status"] == "OFFERED"
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 7_220_000

    def test_pacing_cap_fires_once_verification_restored(self, api):
        """PRD §3.4: "Acceptance is also the money gate: the cycle's
        `aid_committed_cents` plus this award's `final_award_cents` must be
        less than or equal to the cycle's current `pacing_cap_cents` —
        equality is allowed — or acceptance is rejected with
        `ERR_AID_PACING_CAP_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/award_accept_stale_verification_beats_pacing
        """
        ctx = _stale_and_full_pacing_world()
        verify_aid(ctx["famx"]["aid"]["id"], 6_000_000, officer_id="fao-1")
        resp = api.accept_award(ctx["famx"]["aid"]["id"],
                                make_parent_headers("fam-x"))
        validate_error(resp, ApiErrorId.ERR_AID_PACING_CAP_EXCEEDED, 402)
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 7_220_000


class TestPacingCapBoundary:
    """Difficulty: the accept-award money gate uses '<=' semantics — landing
    exactly on the ceiling succeeds, one cent over is rejected."""

    def test_acceptance_landing_exactly_on_cap_succeeds(self, api):
        """PRD §3.4: "must be less than or equal to the cycle's current
        `pacing_cap_cents` — equality is allowed".
        PRD §3.4: "A successful acceptance moves the award to `ACCEPTED` and
        adds `final_award_cents` to the cycle's `aid_committed_cents`."

        Design: Difficulty/boundary_precision_check/pacing_cap_exact_acceptance_then_overflow
        """
        ctx = setup_pacing_boundary_world()  # 5,400,000 already committed
        accept_aid(ctx["fam3"]["aid"]["id"], "fam-3")  # +1,820,000
        cycle = get_cycle(ctx["cycle"]["id"])
        # 5,400,000 + 1,820,000 == 7,220,000 == the OPEN-phase ceiling.
        assert cycle["aid_committed_cents"] == 7_220_000
        assert cycle["pacing_cap_cents"] == 7_220_000
        assert get_aid(ctx["fam3"]["aid"]["id"])["award_status"] == "ACCEPTED"

    def test_acceptance_one_cent_over_cap_rejected(self, api):
        """PRD §3.4: "or acceptance is rejected with
        `ERR_AID_PACING_CAP_EXCEEDED` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/pacing_cap_exact_acceptance_then_overflow
        """
        ctx = setup_pacing_boundary_world()
        accept_aid(ctx["fam3"]["aid"]["id"], "fam-3")  # cap now fully used
        resp = api.accept_award(ctx["fam4"]["aid"]["id"],
                                make_parent_headers("fam-4"))
        validate_error(resp, ApiErrorId.ERR_AID_PACING_CAP_EXCEEDED, 402)
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 7_220_000
        assert get_aid(ctx["fam4"]["aid"]["id"])["award_status"] == "OFFERED"


class TestBudgetConservation:
    """Difficulty: aid_committed_cents == SUM(final awards of ACCEPTED aid
    applications) — the accept (+) and lapse-release (-) pair conserves it."""

    def test_accept_commits_final_award_to_cycle_budget(self, api):
        """PRD §2.9: "Each `AdmissionCycle` maintains `aid_committed_cents`,
        the sum of `final_award_cents` over the cycle's aid applications whose
        `award_status` is `ACCEPTED`".
        PRD §3.4: "A successful acceptance moves the award to `ACCEPTED` and
        adds `final_award_cents` to the cycle's `aid_committed_cents`."

        Design: Difficulty/compensating_invariant/aid_commit_release_conserves_budget
        """
        ctx = setup_offered_application(
            "fam-a", aid=(12_000_000, 4, 12_000_000), accept_aid_award=True,
        )
        cycle = get_cycle(ctx["cycle"]["id"])
        assert get_aid(ctx["aid"]["id"])["award_status"] == "ACCEPTED"
        assert cycle["aid_committed_cents"] == 1_820_000

    def test_lapse_release_returns_committed_budget_to_zero(self, api):
        """PRD §3.4: "an award in `ACCEPTED` that releases additionally
        subtracts its `final_award_cents` from the cycle's
        `aid_committed_cents` as a compensating release."
        PRD §3.6: "the lapse cascades in one request: the application moves
        `CONTRACT_ISSUED` → `EXPIRED`, its linked aid application releases —
        uncommitting `final_award_cents` from the cycle when the award was
        `ACCEPTED`".

        Design: Difficulty/compensating_invariant/aid_commit_release_conserves_budget
        """
        ctx = setup_issued_contract_world(
            "fam-a", aid=(12_000_000, 4, 12_000_000), accept_aid_award=True,
        )
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 1_820_000
        set_clock("2026-11-17T00:00:00Z")  # past response_due_at 2026-11-16
        run_sweep(ctx["cycle"]["id"])
        assert get_aid(ctx["aid"]["id"])["award_status"] == "RELEASED"
        # 1,820,000 committed then 1,820,000 released: no drift.
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 0
