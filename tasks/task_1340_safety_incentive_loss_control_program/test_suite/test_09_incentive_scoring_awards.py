"""Incentive scoring and awards: scoring-variant divergence, per-employee
rounding order, tier boundaries, the withheld claims-free bonus, budget
conservation, disbursement authorization, and close-out consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_claim_record,
    add_control,
    assert_incentive_award,
    assert_program_budget_invariant,
    assess_hazard,
    close_hazard_via_single_control,
    create_active_program,
    create_claim_record,
    create_hazard_record,
    create_observation_record,
    get_program,
    implement_control,
    list_awards,
    list_events,
    make_supervisor_headers,
    set_clock,
    setup_closed_program_with_40_point_award,
    setup_closed_program_with_meeting_awards,
    setup_dual_variant_scenario,
    setup_hazard_with_controls,
    setup_roster,
    triage_observation_link,
    validate_error,
    validate_success,
    verify_control,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestScoringVariantDivergence:
    def test_incentive_leading_only_vs_balanced_payout(self, api):
        """PRD §3.8: "Under `LEADING_ONLY`, `CLAIMS_FREE_BONUS` events are never
        created — all points come from leading indicators, so payouts can never
        reward suppressed reporting. Under `BALANCED`, closing the program adds
        one `CLAIMS_FREE_BONUS` event for every employee holding at least one
        existing event in the program, but only when the program closed
        claims-free — zero claims in `ACCEPTED` or `CLOSED` — and the
        `integrity_flag` is false; when claims exist or the near-miss floor
        failed, the bonus is simply withheld, never negative."

        Design: Difficulty/dual_variant_calc/incentive_leading_only_vs_balanced_payout
        """
        scenario = setup_dual_variant_scenario()
        leading, balanced = scenario["leading"], scenario["balanced"]

        leading_award = leading["award"]
        assert_incentive_award(leading_award)
        assert leading_award["points_earned"] == 34, \
            "10 observation + 19 on-time control + 5 meeting"
        assert leading_award["tier"] == "BRONZE"
        assert leading_award["payout_cents"] == 5100, \
            "34 * 150 / 100 = 51.00 whole dollars"

        balanced_award = balanced["award"]
        assert_incentive_award(balanced_award)
        assert balanced_award["points_earned"] == 84, \
            "34 leading points + 50 claims-free bonus"
        assert balanced_award["tier"] == "SILVER", "the bonus flips the tier"
        assert balanced_award["payout_cents"] == 16800, "84 * 200 / 100 = 168.00"
        assert leading_award["payout_cents"] != balanced_award["payout_cents"], \
            "identical activity pays differently under the two variants"

        assert list_events(program_id=leading["program"]["id"],
                           source_type="CLAIMS_FREE_BONUS") == [], \
            "LEADING_ONLY never creates CLAIMS_FREE_BONUS events"
        bonus_events = list_events(program_id=balanced["program"]["id"],
                                   source_type="CLAIMS_FREE_BONUS")
        assert len(bonus_events) == 1
        assert bonus_events[0]["points_awarded"] == 50
        assert bonus_events[0]["employee_id"] == scenario["a"]["id"]


class TestAwardPayoutRounding:
    def test_award_payout_rounding_order(self, api):
        """PRD §3.8: "`payout_cents` is the points total multiplied by the
        tier's per-point value (150 cents for `BRONZE`, 200 for `SILVER`, 250
        for `GOLD`, 300 for `PLATINUM`), divided by 100, rounded half-up, and
        multiplied back by 100 — in other words, each employee's payout is
        rounded to whole dollars individually, and program totals are sums of
        those rounded per-employee payouts, never a rounding of the
        program-level sum."

        Design: Difficulty/combinatorial_formula/award_payout_rounding_order
        """
        fixture = setup_closed_program_with_meeting_awards(member_count=2)
        awards = fixture["awards"]
        assert len(awards) == 2
        for award in awards:
            assert_incentive_award(award)
            assert award["points_earned"] == 5
            assert award["tier"] == "BRONZE"
            assert award["payout_cents"] == 800, \
                "5 * 150 = 750 cents rounds half-up to $8.00 per employee"
        total = sum(award["payout_cents"] for award in awards)
        assert total == 1600, \
            "per-employee-first rounding totals $16.00; sum-then-round would " \
            "produce $15.00"

    def test_award_tier_boundary_exactly_50_silver(self, api):
        """PRD §3.8: "The award sums the employee's `points_awarded` into
        `points_earned`, bands a `tier` — `BRONZE` from 1 to 49 points,
        `SILVER` from 50 to 99, `GOLD` from 100 to 199, `PLATINUM` at 200 or
        more — and prices the payout"
        PRD §3.8: "The `timeliness_multiplier` rewards prompt remediation: it
        is 1.25 for a `CONTROL_VERIFIED` event whose `verified_at` falls on or
        before the control's `due_date`, and 1.0 in every other case —
        including every other source type."

        Design: Corner/calculations/award_tier_boundary_exactly_50_silver
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(
            plain_names=("Ann A", "Ike I", "Vera V"))
        ann, ike, vera = (employees["Ann A"], employees["Ike I"],
                          employees["Vera V"])
        hazard = create_hazard_record(program["id"], vera["id"],
                                      identified_by=ann["id"],
                                      description="Noise")
        hazard = assess_hazard(hazard["id"], vera["id"], severity=3,
                               probability=2)
        control = add_control(hazard["id"], ike["id"], vera["id"],
                              description="Enclosure",
                              due_date="2026-06-20T00:00:00Z")
        for i in range(1, 6):
            observation = create_observation_record(
                program["id"], ann["id"], kind="OBSERVATION",
                description=f"N{i}")
            triage_observation_link(observation["id"], hazard["id"],
                                    vera["id"])
        implement_control(control["id"], ike["id"], role="Supervisor")
        verify_control(control["id"], vera["id"], outcome="PASS")
        program = validate_success(api.close_program(program["id"], ADMIN))
        assert program["status"] == "CLOSED"

        ann_award = list_awards(program_id=program["id"],
                                employee_id=ann["id"])[0]
        assert ann_award["points_earned"] == 50, \
            "five OBSERVATION_VALIDATED events at 10 points each"
        assert ann_award["tier"] == "SILVER", \
            "50 sits on the inclusive SILVER lower edge"
        assert ann_award["payout_cents"] == 10_000, "50 * 200 / 100 = 100.00"

        ike_award = list_awards(program_id=program["id"],
                                employee_id=ike["id"])[0]
        assert ike_award["points_earned"] == 19, \
            "on-time CONTROL_VERIFIED: round_half_up(15 * 1.0 * 1.25)"
        assert ike_award["tier"] == "BRONZE"
        assert ike_award["payout_cents"] == 2900, \
            "19 * 150 = 2850 cents rounds half-up to $29.00"


class TestClaimsFreeBonusWithheld:
    def test_claims_free_bonus_withheld_when_claim_exists(self, api):
        """PRD §3.8: "Under `BALANCED`, closing the program adds one
        `CLAIMS_FREE_BONUS` event for every employee holding at least one
        existing event in the program, but only when the program closed
        claims-free — zero claims in `ACCEPTED` or `CLOSED` — and the
        `integrity_flag` is false; when claims exist or the near-miss floor
        failed, the bonus is simply withheld, never negative."

        Design: Corner/calculations/claims_free_bonus_withheld_when_claim_exists
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program(scoring_variant="BALANCED")
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        claim = create_claim_record(program["id"], manager["id"],
                                    occurred_on="2026-03-01", kind="INDEMNITY",
                                    incurred_cents=100_000)
        accept_claim_record(claim["id"], manager["id"])
        hazard, _controls = setup_hazard_with_controls(
            program["id"], ann["id"], manager["id"], control_count=1,
            implementer_id=ann["id"], severity=3, probability=2)
        observation = create_observation_record(program["id"], ann["id"],
                                                kind="OBSERVATION",
                                                description="Loud bang")
        triage_observation_link(observation["id"], hazard["id"], manager["id"])
        implement_control(_controls[0]["id"], ann["id"], role="Supervisor")
        verify_control(_controls[0]["id"], manager["id"], outcome="PASS")
        program = validate_success(api.close_program(program["id"], ADMIN))
        assert program["status"] == "CLOSED"

        assert list_events(program_id=program["id"],
                           source_type="CLAIMS_FREE_BONUS") == [], \
            "one ACCEPTED claim withholds the bonus entirely"
        award = list_awards(program_id=program["id"], employee_id=ann["id"])[0]
        assert award["points_earned"] == 29, \
            "10 observation + 19 on-time control; the withheld bonus is never negative"
        assert award["tier"] == "BRONZE"
        assert award["payout_cents"] == 4400, \
            "29 * 150 = 4350 cents rounds half-up to $44.00"


class TestAwardApproveOrdering:
    def test_award_approve_state_beats_fiscal(self, api):
        """PRD §2.6: "Business guards run after state checks, in a fixed
        relative order."
        PRD §2.6: "Fiscal guards run last: the incentive budget check
        (`ERR_INCENTIVE_BUDGET_EXCEEDED`) and the payroll completeness check
        (`ERR_PAYROLL_INCOMPLETE`)."

        Design: Difficulty/priority_pair_validation_conflict/award_approve_state_beats_fiscal
        """
        fixture = setup_closed_program_with_40_point_award(
            incentive_budget_cents=9_000)
        program, award = fixture["program"], fixture["award"]
        assert award["payout_cents"] == 6000, \
            "40 BRONZE points: 40 * 150 / 100 = 60.00 whole dollars"

        approved = validate_success(api.approve_award(award["id"], ADMIN))
        assert approved["status"] == "APPROVED"
        assert get_program(program["id"])["remaining_budget_cents"] == 3000

        resp = api.approve_award(award["id"], ADMIN)
        # The state gate fires even though remaining 3000 < payout 6000 would
        # also fail the fiscal guard.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_program(program["id"])["remaining_budget_cents"] == 3000, \
            "the rejected second approve leaves no budget drift"


class TestBudgetConservation:
    def test_incentive_budget_approve_void_conservation(self, api):
        """PRD §3.8: "Disbursement is the `EHSAdmin`'s three-step ledger
        against `remaining_budget_cents`, which at all times equals the
        `incentive_budget_cents` less the payouts of awards in `APPROVED` or
        `PAID`."
        PRD §3.8: "Voiding — which requires a `void_reason`
        (`ERR_INVALID_REQUEST` when absent) — moves either a `CALCULATED` or an
        `APPROVED` award to `VOIDED`; voiding from `APPROVED` restores the
        reservation, adding the payout back to `remaining_budget_cents`."

        Design: Difficulty/compensating_invariant/incentive_budget_approve_void_conservation
        """
        fixture = setup_closed_program_with_40_point_award(
            incentive_budget_cents=9_000)
        program, award = fixture["program"], fixture["award"]
        assert_program_budget_invariant(get_program(program["id"]), 0)

        validate_success(api.approve_award(award["id"], ADMIN))
        assert_program_budget_invariant(get_program(program["id"]), 6000)

        voided = validate_success(api.void_award(
            award["id"], {"void_reason": "duplicate award"}, ADMIN))
        assert voided["status"] == "VOIDED"
        assert_program_budget_invariant(get_program(program["id"]), 0), \
            "voiding from APPROVED is the compensating action"

        # VOIDED is terminal: a third approve is a plain state violation.
        resp = api.approve_award(award["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReconcileAndDisbursementGates:
    def test_reconcile_blocked_by_unpaid_awards(self, api):
        """PRD §3.8: "Once every award of the program stands in `PAID` or
        `VOIDED` — anything left in `CALCULATED` or `APPROVED` is rejected with
        `ERR_UNPAID_AWARDS_REMAIN` — the `EHSAdmin` reconciles, moving the
        program `CLOSED → RECONCILED`"

        Design: Corner/validations/reconcile_blocked_by_unpaid_awards
        """
        fixture = setup_closed_program_with_meeting_awards(member_count=1)
        program = fixture["program"]
        assert fixture["awards"][0]["status"] == "CALCULATED"

        resp = api.reconcile_program(program["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNPAID_AWARDS_REMAIN)
        assert get_program(program["id"])["status"] == "CLOSED", \
            "the rejected reconcile leaves the program CLOSED"

    def test_supervisor_cannot_approve_award_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint — or that fails an entity-backed
        ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.8: "Disbursement is the `EHSAdmin`'s three-step ledger against
        `remaining_budget_cents`"

        Design: Corner/rbac/supervisor_cannot_approve_award_returns_unauthorized
        """
        fixture = setup_closed_program_with_meeting_awards(member_count=1)
        award = fixture["awards"][0]

        resp = api.approve_award(
            award["id"], make_supervisor_headers(fixture["manager"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        unchanged = validate_success(api.get_incentive_award(award["id"], ADMIN))
        assert unchanged["status"] == "CALCULATED"


class TestCloseImmediateConsistency:
    def test_close_immediately_reflects_awards(self, api):
        """PRD §3.8: "Once clear, the close runs the bonus pass for `BALANCED`
        programs and then computes an **IncentiveAward** for every employee
        holding at least one incentive event in the program."
        PRD §3.8: "Awards arrive in `CALCULATED`, and the close increments the
        program's `version`."

        Design: Corner/consistency_model/close_immediately_reflects_awards
        """
        fixture = setup_closed_program_with_meeting_awards(member_count=1)
        assert fixture["program"]["status"] == "CLOSED"

        awards = fixture["awards"]
        assert len(awards) == 1, \
            "the very next read after close shows the computed award"
        award = awards[0]
        assert_incentive_award(award)
        assert award["status"] == "CALCULATED"
        assert award["points_earned"] == 5
        assert award["tier"] == "BRONZE"
        assert award["payout_cents"] == 800, \
            "5 * 150 = 750 cents rounds half-up to $8.00"
