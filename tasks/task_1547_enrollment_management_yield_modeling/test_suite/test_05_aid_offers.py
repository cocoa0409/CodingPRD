"""Financial-aid leveraging: award computation, OCC guard, exclusivity,
budget guards, the negotiation cycle, and the scholarship ledger."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_aid_offer,
    advance_cycle_to_decisions_released,
    assert_scholarship_ledger_conserved,
    create_admitted_application,
    create_aid_offer,
    create_aid_offer_payload,
    list_interventions_for,
    make_applicant_headers,
    pay_deposit,
    refresh_application,
    refresh_program,
    set_clock,
    setup_open_cycle_with_program,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]
AID_OFFICER = TEST_USERS["financial_aid_officer_headers"]


def _admitted(name, *, academic_score=80, efc_cents=5_000_000,
              budget=10_000_000, capacity=5, target=3, distance_band="LOCAL"):
    setup = setup_open_cycle_with_program(
        name=name, capacity_seats=capacity, target_enrollment=target,
        scholarship_budget_cents=budget)
    pair = create_admitted_application(
        setup["cycle"]["id"], setup["program"]["id"],
        academic_score=academic_score, efc_cents=efc_cents,
        distance_band=distance_band)
    return setup, pair


class TestNeedBasedBudgetCap:
    def test_need_based_award_capped_by_remaining_budget(self, api):
        """PRD 3.5: "For a `NEED_BASED` offer, the need base is the amount by
        which `tuition_cents` exceeds the application's `efc_cents`, floored
        at zero; the base is the lesser of that need base and sixty percent
        of tuition, rounded half-up to whole cents, and then capped at
        3,000,000 cents — thirty thousand dollars — per offer."
        PRD 3.5: "The awarded amount is the lesser of the computed base and
        the program's currently available scholarship funds, so an award can
        be partially clipped by the remaining budget but never exceeds it."

        Design: Difficulty/combinatorial_formula/aid_award_need_based_budget_capped_branch
        """
        setup, pair = _admitted("ECO", academic_score=75,
                                efc_cents=1_200_000, budget=2_000_000,
                                capacity=5, target=3)
        offer = create_aid_offer(pair["application"], "NEED_BASED")
        assert offer["amount_cents"] == 2_000_000, (
            "base = min(max(0, 5000000-1200000), 0.60*5000000, 3000000) "
            "= 3000000, clipped by the remaining budget 2000000")

    def test_need_based_award_updates_scholarship_ledger(self, api):
        """PRD 2.6: "The scholarship ledger tracks
        `scholarship_committed_cents`, the sum of `amount_cents` over all aid
        offers of the program's applications currently in `OFFERED` or
        `ACCEPTED` status, and `scholarship_available_cents`, defined as
        `scholarship_budget_cents` minus `scholarship_committed_cents`."

        Design: Difficulty/combinatorial_formula/aid_award_need_based_budget_capped_branch
        """
        setup, pair = _admitted("ECO", academic_score=75,
                                efc_cents=1_200_000, budget=2_000_000,
                                capacity=5, target=3)
        offer = create_aid_offer(pair["application"], "NEED_BASED")
        assert offer["status"] == "OFFERED"

        program = refresh_program(setup["program"]["id"])
        assert program["scholarship_committed_cents"] == 2_000_000
        assert program["scholarship_available_cents"] == 0
        assert_scholarship_ledger_conserved(program)


class TestMeritTierBoundary:
    def test_score_exactly_90_hits_mid_tier(self, api):
        """PRD 3.5: "one-half of tuition when the score is at least 95, 0.35
        when the score is at least 90 but below 95, 0.20 when the score is at
        least 80 but below 90, and zero when the score is below 80; the merit
        base is the tier rate multiplied by tuition, rounded half-up to whole
        cents, and then capped at 2,500,000 cents — twenty-five thousand
        dollars — per offer."

        Design: Difficulty/boundary_precision_check/merit_tier_score_90_boundary_inclusive
        """
        setup, pair = _admitted("STA", academic_score=90.0, budget=10_000_000,
                                capacity=5, target=4)
        offer = create_aid_offer(pair["application"], "MERIT")
        assert offer["amount_cents"] == 1_750_000, \
            "Score exactly 90 is inside the 0.35 tier (>= boundary inclusive)"

    def test_score_just_below_90_falls_to_low_tier(self, api):
        """PRD 3.5: "one-half of tuition when the score is at least 95, 0.35
        when the score is at least 90 but below 95, 0.20 when the score is at
        least 80 but below 90, and zero when the score is below 80"

        Design: Difficulty/boundary_precision_check/merit_tier_score_90_boundary_inclusive
        """
        setup, pair = _admitted("STA", academic_score=89.99,
                                budget=10_000_000, capacity=5, target=4)
        offer = create_aid_offer(pair["application"], "MERIT")
        assert offer["amount_cents"] == 1_000_000, \
            "Score 89.99 falls to the 0.20 tier (0.20 * 5000000)"


class TestRevisionReofferCycle:
    def test_revision_request_releases_committed_funds(self, api):
        """PRD 2.6: "An offer in `REVISION_REQUESTED` contributes nothing to
        the committed total — its funds are treated as released while the
        applicant negotiates — and offers in `DECLINED`, `REVOKED`, or
        `SUPERSEDED` contribute nothing either."

        Design: Difficulty/non_linear_state_machine/aid_offer_revision_reoffer_recomputes_amount
        """
        setup, pair = _admitted("PHY", academic_score=96, budget=3_000_000)
        offer = create_aid_offer(pair["application"], "MERIT")
        assert offer["amount_cents"] == 2_500_000, (
            "min(0.50*5000000, merit cap 2500000, available 3000000)")

        revised = validate_success(api.transition_aid_offer(
            offer["id"], "REVISION_REQUESTED",
            make_applicant_headers(pair["applicant"]["id"])))
        assert revised["status"] == "REVISION_REQUESTED"

        program = refresh_program(setup["program"]["id"])
        assert program["scholarship_committed_cents"] == 0, \
            "REVISION_REQUESTED releases the funds from committed"
        assert program["scholarship_available_cents"] == 3_000_000
        assert_scholarship_ledger_conserved(program)

    def test_reoffer_recomputes_against_current_budget(self, api):
        """PRD 3.5: "A `FinancialAidOfficer` may re-offer, moving the offer
        back to `OFFERED`: the award formula runs again in full against the
        program's current `scholarship_available_cents` — the offer itself
        contributes nothing to committed while it sits in
        `REVISION_REQUESTED`, so its prior amount does not block its own
        recomputation"
        PRD 3.5: "The awarded amount is the lesser of the computed base and
        the program's currently available scholarship funds"

        Design: Difficulty/non_linear_state_machine/aid_offer_revision_reoffer_recomputes_amount
        """
        setup, pair = _admitted("PHY", academic_score=96, budget=3_000_000)
        offer = create_aid_offer(pair["application"], "MERIT")
        assert offer["amount_cents"] == 2_500_000

        validate_success(api.transition_aid_offer(
            offer["id"], "REVISION_REQUESTED",
            make_applicant_headers(pair["applicant"]["id"])))

        program = refresh_program(setup["program"]["id"])
        patched = validate_success(api.patch_program(
            program["id"],
            {"scholarship_budget_cents": 1_000_000,
             "expected_program_version": program["version"]},
            MANAGER))
        assert patched["scholarship_budget_cents"] == 1_000_000

        reoffered = validate_success(api.transition_aid_offer(
            offer["id"], "OFFERED", AID_OFFICER))
        assert reoffered["id"] == offer["id"], "Same offer row re-offered"
        assert reoffered["status"] == "OFFERED"
        assert reoffered["amount_cents"] == 1_000_000, \
            "Re-offer recomputes to min(2500000 base, 1000000 available)"
        assert reoffered["amount_cents"] != offer["amount_cents"]


class TestScholarshipLedgerRoundTrip:
    def test_offer_create_commits_funds(self, api):
        """PRD 2.6: "The scholarship ledger tracks
        `scholarship_committed_cents`, the sum of `amount_cents` over all aid
        offers of the program's applications currently in `OFFERED` or
        `ACCEPTED` status, and `scholarship_available_cents`, defined as
        `scholarship_budget_cents` minus `scholarship_committed_cents`."

        Design: Difficulty/compensating_invariant/scholarship_ledger_offer_revoke_round_trip
        """
        setup, pair = _admitted("ECO", academic_score=96, budget=3_000_000)
        before = refresh_program(setup["program"]["id"])
        assert before["scholarship_committed_cents"] == 0
        assert before["scholarship_available_cents"] == 3_000_000
        assert_scholarship_ledger_conserved(before)

        offer = create_aid_offer(pair["application"], "MERIT")
        mid = refresh_program(setup["program"]["id"])
        assert mid["scholarship_committed_cents"] == 2_500_000
        assert mid["scholarship_available_cents"] == 500_000
        assert_scholarship_ledger_conserved(mid), \
            "The ledger identity holds mid-flight"

    def test_revoke_restores_ledger_exactly(self, api):
        """PRD 3.5: "in each case the offer's `amount_cents` is subtracted
        from `scholarship_committed_cents` and added back to
        `scholarship_available_cents`, and the application's
        `aid_accepted_cents`, `aid_gap_cents`, and `melt_risk_score`
        recompute."

        Design: Difficulty/compensating_invariant/scholarship_ledger_offer_revoke_round_trip
        """
        setup, pair = _admitted("ECO", academic_score=96, budget=3_000_000)
        before = refresh_program(setup["program"]["id"])
        offer = create_aid_offer(pair["application"], "MERIT")

        revoked = validate_success(api.transition_aid_offer(
            offer["id"], "REVOKED", AID_OFFICER))
        assert revoked["status"] == "REVOKED"

        after = refresh_program(setup["program"]["id"])
        assert after["scholarship_committed_cents"] == \
            before["scholarship_committed_cents"] == 0
        assert after["scholarship_available_cents"] == \
            before["scholarship_available_cents"] == 3_000_000
        assert_scholarship_ledger_conserved(after)


class TestRevokeCascadeMeltRisk:
    def test_revoke_recomputes_aid_fields_and_melt_risk(self, api):
        """PRD 3.5: "in each case the offer's `amount_cents` is subtracted
        from `scholarship_committed_cents` and added back to
        `scholarship_available_cents`, and the application's
        `aid_accepted_cents`, `aid_gap_cents`, and `melt_risk_score`
        recompute."
        PRD 3.7: "The aid-gap factor is the application's `aid_gap_cents`
        divided by its program's `tuition_cents`, capped at 1 and rounded
        half-up to four decimals"

        Design: Difficulty/transitive_cascade/aid_revoke_cascade_recomputes_melt_risk
        """
        setup, pair = _admitted("ENG", academic_score=96, budget=3_000_000,
                                capacity=3, target=2, distance_band="NATIONAL")
        offer = create_aid_offer(pair["application"], "MERIT")
        accept_aid_offer(offer["id"], pair["applicant"]["id"])
        program = refresh_program(setup["program"]["id"])
        assert program["scholarship_committed_cents"] == 2_500_000
        assert program["scholarship_available_cents"] == 500_000

        advance_cycle_to_decisions_released(setup["cycle"]["id"])
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair["application"], pair["applicant"])

        validate_success(api.transition_aid_offer(offer["id"], "REVOKED",
                                                  AID_OFFICER))
        revoked = validate_success(api.get_aid_offer(offer["id"], AID_OFFICER))
        assert revoked["status"] == "REVOKED"

        program = refresh_program(setup["program"]["id"])
        assert program["scholarship_committed_cents"] == 0
        assert program["scholarship_available_cents"] == 3_000_000

        app = refresh_application(pair["application"]["id"])
        assert app["aid_accepted_cents"] == 0
        assert app["aid_gap_cents"] == 5_000_000
        assert app["melt_risk_score"] == pytest.approx(0.75, abs=1e-6), (
            "0.40*1.0 (aid gap) + 0.25*0.6 (NATIONAL) + 0.20*1.0 "
            "(engagement) + 0.15*0.0 (time) = 0.7500")

    def test_revoke_crossing_threshold_auto_creates_intervention(self, api):
        """PRD 3.7: "Every recompute carries a threshold side effect: if the
        application is currently `DEPOSITED`, the fresh score is at least
        0.70, and no melt intervention of the application is presently in
        `SCHEDULED`, the system automatically schedules one —
        `trigger_source` of `AUTO_THRESHOLD`, `intervention_type` of
        `EMAIL_CAMPAIGN`, `advisor_id` set to the reserved identifier
        `AUTO_QUEUE`, and a window running from the current clock instant to
        exactly seven days later."

        Design: Difficulty/transitive_cascade/aid_revoke_cascade_recomputes_melt_risk
        """
        setup, pair = _admitted("ENG", academic_score=96, budget=3_000_000,
                                capacity=3, target=2, distance_band="NATIONAL")
        offer = create_aid_offer(pair["application"], "MERIT")
        accept_aid_offer(offer["id"], pair["applicant"]["id"])
        advance_cycle_to_decisions_released(setup["cycle"]["id"])
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(pair["application"], pair["applicant"])
        assert list_interventions_for(pair["application"]["id"]) == [], \
            "With aid accepted the risk is 0.5500 — below the threshold"

        validate_success(api.transition_aid_offer(offer["id"], "REVOKED",
                                                  AID_OFFICER))
        interventions = list_interventions_for(pair["application"]["id"])
        assert len(interventions) == 1, \
            "Crossing 0.70 on the revoke recompute auto-creates one row"
        auto = interventions[0]
        assert auto["trigger_source"] == "AUTO_THRESHOLD"
        assert auto["intervention_type"] == "EMAIL_CAMPAIGN"
        assert auto["advisor_id"] == "AUTO_QUEUE"
        assert auto["status"] == "SCHEDULED"


class TestAidGuards:
    def test_aid_already_accepted_blocks_new_offer(self, api):
        """PRD 3.5: "One exclusivity rule applies: an application that
        already holds an offer in `ACCEPTED` rejects any new offer with
        `ERR_AID_ALREADY_ACCEPTED`."

        Design: Corner/validations/aid_already_accepted_blocks_new_offer
        """
        setup, pair = _admitted("ACC", academic_score=96, budget=10_000_000,
                                capacity=4, target=2)
        offer = create_aid_offer(pair["application"], "MERIT")
        accept_aid_offer(offer["id"], pair["applicant"]["id"])

        fresh = refresh_application(pair["application"]["id"])
        resp = api.create_aid_offer(
            create_aid_offer_payload(fresh["id"], "NEED_BASED",
                                     fresh["version"]),
            AID_OFFICER)
        validate_error(resp, ApiErrorId.ERR_AID_ALREADY_ACCEPTED)

    def test_no_aid_eligibility_zero_base_rejected(self, api):
        """PRD 3.5: "If the base computes to zero the create is rejected with
        `ERR_NO_AID_ELIGIBILITY`; eligibility is evaluated first, and only a
        positive base proceeds to the budget check"
        PRD 3.5: "0.20 when the score is at least 80 but below 90, and zero
        when the score is below 80"

        Design: Corner/validations/no_aid_eligibility_zero_base_rejected
        """
        setup, pair = _admitted("ELG", academic_score=79, budget=1_000_000,
                                capacity=4, target=2)
        resp = api.create_aid_offer(
            create_aid_offer_payload(pair["application"]["id"], "MERIT",
                                     pair["application"]["version"]),
            AID_OFFICER)
        validate_error(resp, ApiErrorId.ERR_NO_AID_ELIGIBILITY)

    def test_scholarship_budget_exhausted_rejected(self, api):
        """PRD 3.5: "If the base computes to zero the create is rejected with
        `ERR_NO_AID_ELIGIBILITY`; eligibility is evaluated first, and only a
        positive base proceeds to the budget check, where a program whose
        `scholarship_available_cents` is zero rejects the create with
        `ERR_SCHOLARSHIP_BUDGET_EXCEEDED`."
        PRD 3.5: "The awarded amount is the lesser of the computed base and
        the program's currently available scholarship funds"

        Design: Corner/validations/scholarship_budget_exhausted_rejected
        """
        setup = setup_open_cycle_with_program(
            name="EXH", capacity_seats=5, target_enrollment=3,
            scholarship_budget_cents=2_000_000)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        first = create_admitted_application(cycle_id, program_id,
                                            academic_score=96)
        offer_one = create_aid_offer(first["application"], "MERIT")
        assert offer_one["amount_cents"] == 2_000_000, \
            "The 2500000 base is clipped by the 2000000 budget"

        second = create_admitted_application(cycle_id, program_id,
                                             academic_score=90)
        resp = api.create_aid_offer(
            create_aid_offer_payload(second["application"]["id"], "MERIT",
                                     second["application"]["version"]),
            AID_OFFICER)
        validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_BUDGET_EXCEEDED)

    def test_budget_below_committed_rejected(self, api):
        """PRD 3.2: "the new `scholarship_budget_cents` may not fall below
        the program's current `scholarship_committed_cents`, and an attempt
        to set it lower is rejected with `ERR_BUDGET_BELOW_COMMITTED`."

        Design: Corner/validations/budget_below_committed_rejected
        """
        setup, pair = _admitted("BUD", academic_score=96, budget=3_000_000,
                                capacity=4, target=2)
        create_aid_offer(pair["application"], "MERIT")  # 2500000 OFFERED
        program = refresh_program(setup["program"]["id"])
        assert program["scholarship_committed_cents"] == 2_500_000

        resp = api.patch_program(
            program["id"],
            {"scholarship_budget_cents": 2_000_000,
             "expected_program_version": program["version"]},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_BUDGET_BELOW_COMMITTED)

        after = refresh_program(program["id"])
        assert after["scholarship_budget_cents"] == 3_000_000, \
            "The rejected patch leaves the budget unchanged"
        assert after["version"] == program["version"], \
            "A rejected guarded write does not bump the version"

    def test_occ_aid_offer_create_stale_rejected(self, api):
        """PRD 2.8: "A request to `POST /enrollment/aid-offers` must carry
        `expected_application_version`, the client's last observed `version`
        of the target application, as a non-optional field. If the
        application's current `version` has advanced since that observation —
        for example because a transition or a prior offer bumped it — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD 3.5: "Because this supersede semantics makes creation destructive
        to existing state, a successful create also increments the parent
        application's `version` by one"

        Design: Corner/cross_cutting_layers/occ_aid_offer_create_stale_rejected
        """
        setup, pair = _admitted("OCC2", academic_score=90, budget=5_000_000,
                                capacity=4, target=2)
        observed = pair["application"]["version"]

        stale = api.create_aid_offer(
            create_aid_offer_payload(pair["application"]["id"], "MERIT",
                                     observed - 1),
            AID_OFFICER)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        offer = validate_success(api.create_aid_offer(
            create_aid_offer_payload(pair["application"]["id"], "MERIT",
                                     observed),
            AID_OFFICER), 201)
        assert offer["status"] == "OFFERED"
        assert offer["amount_cents"] == 1_750_000, "0.35 tier at score 90"

        after = refresh_application(pair["application"]["id"])
        assert after["version"] == observed + 1, \
            "A successful create increments the parent application's version"
