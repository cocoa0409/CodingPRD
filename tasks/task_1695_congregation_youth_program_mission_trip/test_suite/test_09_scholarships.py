"""Scholarships: need scoring, the award min-chain, the appeal cycle, fund
exhaustion, fund conservation, decide-time validation ordering, terminal
states, application gates, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    add_donation,
    add_lodging,
    assert_fund_conserved,
    create_approved_application,
    create_approved_registration,
    create_application,
    create_submitted_registration,
    decide_application,
    get_account_for_registration,
    get_application,
    get_program,
    get_registration,
    make_director_headers,
    make_guardian_headers,
    make_reviewer_headers,
    make_treasurer_headers,
    open_trip_registration,
    setup_program_with_open_trip,
    create_program,
    create_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()
REVIEWER = make_reviewer_headers()
TREASURER = make_treasurer_headers()


def _funded_account(registration_id, amount, channel="CASH"):
    account = get_account_for_registration(registration_id)
    add_donation(account["id"], amount, channel)
    return account


class TestNeedScore:
    def _setup_two_siblings(self, api):
        """reg1 (BAND_C, household 2, no fundraising) and reg2 (BAND_A,
        household 8, goal 20000 met by a CASH 20000 donation), same family_key,
        both APPROVED on the same trip."""
        program, trip = setup_program_with_open_trip()
        _, reg1, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"family_key": "fam-1", "first_name": "P",
                                   "last_name": "One",
                                   "annual_income_bracket": "BAND_C",
                                   "household_size": 2})
        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"family_key": "fam-1", "first_name": "P",
                                   "last_name": "Two", "birth_date": "2012-06-01",
                                   "grade": 9, "annual_income_bracket": "BAND_A",
                                   "household_size": 8},
            registration_overrides={"fundraising_goal_cents": 20000})
        _funded_account(reg2["id"], 20000)
        app2 = create_application(reg2["id"], 100000, "guardian-1")
        app1 = create_application(reg1["id"], 100000, "guardian-1")
        return app1, app2

    def test_need_score_caps_sibling_and_fundraising_components(self, api):
        """PRD §3.5: "The income band contributes a base: `BAND_A` 50 points,
        `BAND_B` 35, `BAND_C` 20, `BAND_D` 5, `UNDISCLOSED` 0. Household size
        adds 5 points per person beyond two, capped at 20. Siblings on the same
        trip add 10 points each, capped at 20 — counted as other registrations
        on the same trip whose participant shares this participant's
        `family_key` and whose registration status is `APPROVED` or `CONFIRMED`.
        Fundraising adds 10 points if the account's `goal_cents` is positive and
        `raised_gross_cents` has reached it, else 5 points if any gross amount
        has been raised, else 0."

        Design: Difficulty/combinatorial_formula/need_score_weighted_caps_and_state_filtered_siblings
        """
        _, app2 = self._setup_two_siblings(api)
        data = get_application(app2["id"])
        assert data["need_score"] == 90, (
            "50 income + 20 size (30 capped to 20) + 10 sibling (APPROVED "
            "sibling counts) + 10 fundraising (gross 20000 >= goal 20000)")

    def test_need_score_control_applicant(self, api):
        """PRD §3.5: "The total is capped at 100, with each bonus capped before
        the total cap." and "Siblings on the same trip add 10 points each ...
        whose registration status is `APPROVED` or `CONFIRMED`."

        Design: Difficulty/combinatorial_formula/need_score_weighted_caps_and_state_filtered_siblings
        """
        app1, _ = self._setup_two_siblings(api)
        data = get_application(app1["id"])
        assert data["need_score"] == 30, (
            "20 income (BAND_C) + 0 size (household of 2) + 10 sibling "
            "(symmetric) + 0 fundraising (no donations)")


class TestAwardMinChain:
    def _setup_min_chain(self, api):
        """Trip with lodging 90300 (provisional share 203010); one APPROVED
        registration (BAND_A, household 5, goal 30000 met) -> need 75."""
        program = create_program(scholarship_fund_total_cents=500000)
        trip = create_trip(program["id"])
        add_lodging(trip["id"], room_code="R1", room_capacity=30,
                    cost_cents=90300)
        open_trip_registration(trip["id"])
        _, registration, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_A",
                                   "household_size": 5},
            registration_overrides={"fundraising_goal_cents": 30000})
        _funded_account(registration["id"], 30000)
        application = create_application(registration["id"], 100000,
                                         "guardian-1")
        return program, registration, application

    def test_award_binds_at_need_cap_link(self, api):
        """PRD §3.5: "Third, the need cap is the cost basis multiplied by
        `need_score` hundredths and by `max_award_pct_bp` ten-thousandths,
        rounded half up to the nearest cent. Fourth, `award_cents` is the
        minimum of four values: `requested_cents`, the need cap, the program's
        `per_registration_cap_cents`, and the program's
        `scholarship_available_cents`."
        PRD §3.5: "the cost basis is chosen: the registration's
        `provisional_cost_share_cents` while the trip is in `DRAFT`,
        `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`".

        Design: Difficulty/combinatorial_formula/scholarship_award_min_chain_evaluation_order
        """
        _, registration, application = self._setup_min_chain(api)
        assert get_registration(registration["id"])[
            "provisional_cost_share_cents"] == 203010

        decided = decide_application(application["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        assert decided["need_score"] == 75
        assert decided["award_cents"] == 76129, (
            "min(100000, round_half_up(0.75*0.5*203010)=76129, 150000, 500000) "
            "— the need-cap link binds, not the request, cap, or fund")

    def test_approval_reserves_without_crediting_registration(self, api):
        """PRD §3.5: "On approval, `need_score` and `award_cents` are stored,
        `scholarship_reserved_cents` rises by the award (and available falls
        correspondingly), and `approved_by_user_id` is stamped from the caller."
        PRD §3.5: disbursement "sets the registration's
        `scholarship_awarded_cents` to the award" — approval alone does not.

        Design: Difficulty/combinatorial_formula/scholarship_award_min_chain_evaluation_order
        """
        program, registration, application = self._setup_min_chain(api)
        decide_application(application["id"], "APPROVE")

        program_after = get_program(program["id"])
        assert program_after["scholarship_reserved_cents"] == 76129
        assert program_after["scholarship_available_cents"] == 423871
        assert program_after["scholarship_disbursed_cents"] == 0
        assert_fund_conserved(program_after)

        registration_after = get_registration(registration["id"])
        assert registration_after["scholarship_awarded_cents"] == 0, (
            "approval reserves; only disburse credits the balance")
        approved = get_application(application["id"])
        assert approved["approved_by_user_id"] == "reviewer-1"


class TestAppealCycle:
    def _setup_denied_then_funded(self, api):
        """Approved registration (BAND_A, household 5, goal 30000); application
        requested 100000, decided DENY; then a CASH 30000 donation lands."""
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 500000})
        _, registration, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_A",
                                   "household_size": 5},
            registration_overrides={"fundraising_goal_cents": 30000})
        application = create_application(registration["id"], 100000,
                                         "guardian-1")
        denied = decide_application(application["id"], "DENY",
                                    reason="insufficient documentation")
        _funded_account(registration["id"], 30000)
        return program, registration, application, denied

    def test_appeal_reopens_under_review_and_clears_reason(self, api):
        """PRD §3.5: "With `decision` of `DENY` (optionally with a `reason`),
        the application moves to `DENIED` and `decision_reason` is recorded; the
        family or a director may appeal, returning it to `UNDER_REVIEW` with
        `decision_reason` cleared — an unbounded cycle, requiring the
        registration to still be `APPROVED` or `CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/scholarship_appeal_cycle_recomputes_award
        """
        _, _, application, denied = self._setup_denied_then_funded(api)
        assert denied["status"] == "DENIED"
        assert denied["decision_reason"] == "insufficient documentation"

        appealed = api.appeal_scholarship_application(
            application["id"], make_guardian_headers("guardian-1"))
        data = validate_success(appealed, 200)
        assert data["status"] == "UNDER_REVIEW", "cycle re-entry"
        assert data["decision_reason"] == ""
        assert data["version"] == denied["version"] + 1, (
            "each mutation increments version by exactly 1 (PRD §2.5)")

    def test_second_decide_recomputes_need_from_current_data(self, api):
        """PRD §3.5: "The need score is a weighted sum, recomputed from current
        data both at creation and again inside every decide call — never stored
        stale."

        Design: Difficulty/non_linear_state_machine/scholarship_appeal_cycle_recomputes_award
        """
        program, _, application, _ = self._setup_denied_then_funded(api)
        api.appeal_scholarship_application(application["id"],
                                           make_guardian_headers("guardian-1"))
        approved = decide_application(application["id"], "APPROVE")
        assert approved["need_score"] == 75, (
            "50 + 15 + 0 + 10 — the fundraising bonus did not exist at DENY "
            "time; the second pass recomputes, not reuses the snapshot")
        assert approved["award_cents"] == 75000, (
            "no lodging -> provisional basis 200000; min(100000, "
            "round_half_up(0.75*0.5*200000)=75000, 150000, 500000)")
        assert get_program(program["id"])["scholarship_reserved_cents"] == 75000


class TestFundExhaustionBoundary:
    def _setup_exhaustion(self, api):
        """Fund exactly 75000; reg1 (need 75) requesting 100000; reg2 (BAND_B,
        household 3) requesting 1000."""
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 75000})
        _, reg1, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_A",
                                   "household_size": 5},
            registration_overrides={"fundraising_goal_cents": 30000})
        _funded_account(reg1["id"], 30000)
        app1 = create_application(reg1["id"], 100000, "guardian-1")
        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2"})
        app2 = create_application(reg2["id"], 1000, "guardian-2")
        return program, app1, app2

    def test_award_equal_to_available_succeeds_and_empties_fund(self, api):
        """PRD §3.5: "`award_cents` is the minimum of four values:
        `requested_cents`, the need cap, the program's
        `per_registration_cap_cents`, and the program's
        `scholarship_available_cents`." — equality with the available fund is a
        legal award; "the program's `scholarship_available_cents` must be
        positive (`ERR_SCHOLARSHIP_FUND_EXHAUSTED`, HTTP 402)" applies to the
        next decision.

        Design: Difficulty/boundary_precision_check/scholarship_fund_exact_exhaustion_boundary
        """
        program, app1, _ = self._setup_exhaustion(api)
        approved = decide_application(app1["id"], "APPROVE")
        assert approved["award_cents"] == 75000, (
            "need cap 75000 equals the available fund exactly — the min-chain's "
            "last link binds at equality")
        program_after = get_program(program["id"])
        assert program_after["scholarship_available_cents"] == 0
        assert_fund_conserved(program_after)

    def test_next_approve_at_zero_available_rejected(self, api):
        """PRD §3.5: "the program's `scholarship_available_cents` must be
        positive (`ERR_SCHOLARSHIP_FUND_EXHAUSTED`, HTTP 402)" — the gate trips
        exactly at zero, not below it.

        Design: Difficulty/boundary_precision_check/scholarship_fund_exact_exhaustion_boundary
        """
        _, app1, app2 = self._setup_exhaustion(api)
        decide_application(app1["id"], "APPROVE")
        resp = api.decide_scholarship_application(app2["id"],
                                                  {"decision": "APPROVE"},
                                                  REVIEWER)
        validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_FUND_EXHAUSTED, 402)
        assert get_application(app2["id"])["status"] == "UNDER_REVIEW"


class TestFundConservation:
    def _setup_conservation(self, api):
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 500000})
        _, registration, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_A",
                                   "household_size": 5})
        application = create_application(registration["id"], 100000,
                                         "guardian-1")
        return program, application

    def test_approve_moves_available_into_reserved(self, api):
        """PRD §3.1: "The fund triple is a conserved quantity:
        `scholarship_reserved_cents` is the sum of `award_cents` over all of the
        program's applications in `APPROVED`, `scholarship_disbursed_cents` is
        the sum over applications in `DISBURSED`, and
        `scholarship_available_cents` is always the total pool minus reserved
        minus disbursed."

        Design: Difficulty/compensating_invariant/scholarship_fund_approve_rescind_conservation
        """
        program, application = self._setup_conservation(api)
        before = get_program(program["id"])
        assert (before["scholarship_reserved_cents"],
                before["scholarship_disbursed_cents"],
                before["scholarship_available_cents"]) == (0, 0, 500000)

        approved = decide_application(application["id"], "APPROVE")
        assert approved["award_cents"] == 65000, (
            "need 65 -> round_half_up(0.65*0.5*200000) = 65000")
        mid = get_program(program["id"])
        assert (mid["scholarship_reserved_cents"],
                mid["scholarship_disbursed_cents"],
                mid["scholarship_available_cents"]) == (65000, 0, 435000)
        assert_fund_conserved(mid)

    def test_rescind_restores_the_triple_bit_identically(self, api):
        """PRD §3.5: "A reviewer may rescind an `APPROVED` application
        (optionally with a `reason`), releasing the reservation back to
        available." PRD §3.1: "After every scholarship mutation, the three still
        sum to `scholarship_fund_total_cents`."

        Design: Difficulty/compensating_invariant/scholarship_fund_approve_rescind_conservation
        """
        program, application = self._setup_conservation(api)
        decide_application(application["id"], "APPROVE")
        rescinded = api.rescind_scholarship_application(
            application["id"], REVIEWER,
            payload={"reason": "family withdrew aid request"})
        assert validate_success(rescinded, 200)["status"] == "RESCINDED"

        after = get_program(program["id"])
        assert (after["scholarship_reserved_cents"],
                after["scholarship_disbursed_cents"],
                after["scholarship_available_cents"]) == (0, 0, 500000), (
            "forward+compensating pair leaves the conserved fund triple "
            "bit-identical")
        assert_fund_conserved(after)


class TestStateVsFiscalPriority:
    def _setup_denied_with_empty_fund(self, api):
        """Fund 10000; app1 approved for 10000 (fund now available 0); app2
        decided DENY."""
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 10000})
        _, reg1, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_C",
                                   "household_size": 2})
        app1 = create_application(reg1["id"], 10000, "guardian-1")
        approved1 = decide_application(app1["id"], "APPROVE")
        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2",
                                   "annual_income_bracket": "BAND_C",
                                   "household_size": 2})
        app2 = create_application(reg2["id"], 5000, "guardian-2")
        decide_application(app2["id"], "DENY", reason="criteria")
        return program, app1, app2, approved1

    def test_fiscal_error_fires_when_state_is_valid_control(self, api):
        """PRD §2.8: "an approve-decision against an exhausted scholarship fund
        surfaces `ERR_SCHOLARSHIP_FUND_EXHAUSTED` rather than
        `ERR_AWARD_WOULD_BE_ZERO`, because fund exhaustion is checked first
        within the fiscal gate."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_decide_on_denied_with_empty_fund
        """
        program, _, app2, approved1 = self._setup_denied_with_empty_fund(api)
        assert approved1["award_cents"] == 10000
        assert get_program(program["id"])["scholarship_available_cents"] == 0

        # Appeal restores UNDER_REVIEW (state valid); the fiscal gate then fires.
        api.appeal_scholarship_application(app2["id"],
                                           make_guardian_headers("guardian-2"))
        resp = api.decide_scholarship_application(app2["id"],
                                                  {"decision": "APPROVE"},
                                                  REVIEWER)
        validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_FUND_EXHAUSTED, 402)

    def test_state_error_beats_fiscal_error_when_both_fail(self, api):
        """PRD §2.8: "When a request violates more than one rule, the error
        reported is the one from the earliest applicable check in this
        sequence" — "6. **State preconditions**" precedes "12. **Money gates,
        checked last**", and the decide gate chain requires "the application
        must be `UNDER_REVIEW` (`ERR_APPLICATION_STATE_FORBIDS_ACTION`)" (§3.5).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_decide_on_denied_with_empty_fund
        """
        _, _, app2, _ = self._setup_denied_with_empty_fund(api)
        # app2 is DENIED and the fund is empty: both the state gate and the
        # fiscal gate would fail; the state error must be reported.
        resp = api.decide_scholarship_application(app2["id"],
                                                  {"decision": "APPROVE"},
                                                  REVIEWER)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_FORBIDS_ACTION,
                       409)


class TestScholarshipTerminalStates:
    def test_scholarship_terminal_states_reject_further_actions(self, api):
        """PRD §3.5: disbursement requires "the application must be `APPROVED`";
        "A reviewer may rescind an `APPROVED` application"; appeal returns "a
        `DENIED` application to `UNDER_REVIEW`". Any other source state is
        `ERR_APPLICATION_STATE_FORBIDS_ACTION` (§5).

        Design: Corner/state_machines/scholarship_terminal_states_reject_further_actions
        """
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 500000})
        _, reg1, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_A",
                                   "household_size": 3})
        app1 = create_approved_application(reg1["id"], 30000, "guardian-1")
        assert app1["award_cents"] == 30000

        disbursed = api.disburse_scholarship_application(app1["id"], TREASURER)
        assert validate_success(disbursed, 200)["status"] == "DISBURSED"

        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2"})
        app2 = create_approved_application(reg2["id"], 10000, "guardian-2")
        rescinded = api.rescind_scholarship_application(app2["id"], REVIEWER)
        assert validate_success(rescinded, 200)["status"] == "RESCINDED"

        # DISBURSED is terminal.
        e_dis2 = api.disburse_scholarship_application(app1["id"], TREASURER)
        validate_error(e_dis2, ApiErrorId.ERR_APPLICATION_STATE_FORBIDS_ACTION,
                       409)
        e_resc = api.rescind_scholarship_application(app1["id"], REVIEWER)
        validate_error(e_resc, ApiErrorId.ERR_APPLICATION_STATE_FORBIDS_ACTION,
                       409)
        # RESCINDED cannot be appealed (appeal requires DENIED).
        e_appeal = api.appeal_scholarship_application(
            app2["id"], make_guardian_headers("guardian-2"))
        validate_error(e_appeal,
                       ApiErrorId.ERR_APPLICATION_STATE_FORBIDS_ACTION, 409)

        assert get_program(program["id"])["scholarship_disbursed_cents"] == \
            30000, "failed actions never claw back the fund"


class TestApplicationGates:
    def test_scholarship_application_gates(self, api):
        """PRD §3.5: "A family applies for aid on a registration in `APPROVED`
        or `CONFIRMED` (guardian or director; `ERR_REGISTRATION_STATE_FORBIDS_ACTION`
        otherwise)". "One active application per registration: a second
        application while one exists in `UNDER_REVIEW` or `APPROVED` is rejected
        with `ERR_DUPLICATE_ACTIVE_APPLICATION` (HTTP 409)." "the computed award
        must be positive (`ERR_AWARD_WOULD_BE_ZERO`, HTTP 422)".

        Design: Corner/validations/scholarship_application_gates
        """
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 500000})

        # Gate 1: registration merely SUBMITTED.
        _, reg1, _ = create_submitted_registration(trip["id"], "guardian-1")
        e_state = api.create_scholarship_application(
            {"registration_id": reg1["id"], "requested_cents": 5000},
            make_guardian_headers("guardian-1"))
        validate_error(e_state,
                       ApiErrorId.ERR_REGISTRATION_STATE_FORBIDS_ACTION, 409)

        # Gate 2: a second application while one is UNDER_REVIEW.
        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2"})
        create_application(reg2["id"], 5000, "guardian-2")
        e_dup = api.create_scholarship_application(
            {"registration_id": reg2["id"], "requested_cents": 6000},
            make_guardian_headers("guardian-2"))
        validate_error(e_dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION, 409)

        # Gate 3: UNDISCLOSED income, household of 2 -> need 0 -> award 0.
        _, reg3, _ = create_approved_registration(
            trip["id"], "guardian-3",
            participant_overrides={"family_key": "fam-3",
                                   "annual_income_bracket": "UNDISCLOSED",
                                   "household_size": 2})
        app3 = create_application(reg3["id"], 5000, "guardian-3")
        assert app3["need_score"] == 0
        e_zero = api.decide_scholarship_application(app3["id"],
                                                    {"decision": "APPROVE"},
                                                    REVIEWER)
        validate_error(e_zero, ApiErrorId.ERR_AWARD_WOULD_BE_ZERO, 422)
        assert get_application(app3["id"])["status"] == "UNDER_REVIEW"


class TestDisburseSegregationOfDuties:
    def test_scholarship_disburse_segregation_of_duties(self, api):
        """PRD §3.5: "Disbursement belongs to a `Treasurer` and is segregated:
        the disbursing user's `X-User-ID` must differ from `approved_by_user_id`
        (`ERR_SOD_VIOLATION`)". PRD §2.1: "a user who happens to hold both the
        reviewer and treasurer capacities is still blocked by the identifier
        comparison."
        PRD §3.5: "Disbursing shifts the fund triple — reserved falls by the
        award, disbursed rises by it, available unchanged — sets the
        registration's `scholarship_awarded_cents` to the award, stamps
        `disbursed_by_user_id`, and recomputes coverage and payment status."

        Design: Corner/rbac/scholarship_disburse_segregation_of_duties
        """
        program, trip = setup_program_with_open_trip(program_overrides={"scholarship_fund_total_cents": 500000})
        _, registration, _ = create_approved_registration(
            trip["id"], "guardian-1",
            participant_overrides={"annual_income_bracket": "BAND_A",
                                   "household_size": 3})
        _funded_account(registration["id"], 1000)  # fundraising branch: +5
        application = create_application(registration["id"], 100000,
                                         "guardian-1")
        approved = decide_application(application["id"], "APPROVE")
        assert approved["award_cents"] == 60000, (
            "need 60 = 50 + 5 size + 0 + 5 fundraising-positive; "
            "need cap round_half_up(0.60*0.5*200000) = 60000")

        # The approver cannot disburse even while presenting Treasurer.
        e_sod = api.disburse_scholarship_application(
            application["id"], make_treasurer_headers("reviewer-1"))
        validate_error(e_sod, ApiErrorId.ERR_SOD_VIOLATION, 403)

        disbursed = api.disburse_scholarship_application(
            application["id"], make_treasurer_headers("treasurer-1"))
        data = validate_success(disbursed, 200)
        assert data["status"] == "DISBURSED"
        assert data["disbursed_by_user_id"] == "treasurer-1"

        program_after = get_program(program["id"])
        assert (program_after["scholarship_reserved_cents"],
                program_after["scholarship_disbursed_cents"],
                program_after["scholarship_available_cents"]) == \
            (0, 60000, 440000), "reserved -> disbursed leaves available unchanged"
        assert_fund_conserved(program_after)

        registration_after = get_registration(registration["id"])
        assert registration_after["scholarship_awarded_cents"] == 60000
        assert registration_after["covered_cents"] == 60000, (
            "coverage now includes the disbursed scholarship")


class TestReviewerNotGuardian:
    def test_reviewer_must_not_be_guardian_sod(self, api):
        """PRD §2.1: "A reviewer of a registration or consent form must not be
        that registration's `guardian_user_id`; ... Each violation is rejected
        with `ERR_SOD_VIOLATION` (HTTP 403)."
        PRD §2.8: "a registration review issued by the household's own guardian
        surfaces `ERR_SOD_VIOLATION` before any consideration of whether the
        forms are verified".

        Design: Corner/rbac/reviewer_must_not_be_guardian_sod
        """
        program, trip = setup_program_with_open_trip()
        _, registration, _ = create_submitted_registration(trip["id"],
                                                           "guardian-1")

        # ProgramDirector is an authorized role for review, but this operator
        # id IS the registration's guardian.
        e_sod = api.review_registration(registration["id"],
                                        {"decision": "APPROVE"},
                                        make_director_headers("guardian-1"))
        validate_error(e_sod, ApiErrorId.ERR_SOD_VIOLATION, 403)

        ok = api.review_registration(registration["id"], {"decision": "APPROVE"},
                                     make_director_headers("director-1"))
        assert validate_success(ok, 200)["registration_status"] == "APPROVED"
