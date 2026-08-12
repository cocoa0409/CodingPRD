"""Renewal eligibility tiers, decide/revert/re-decide cycle, and the
active-contract gate (PRD §3.6, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, CLOCK,
    create_approved_school, create_draft_contract, add_standard_targets,
    create_open_school, setup_renewal_ready_school, create_renewal_decision,
    create_intervention, file_school_appeal, schedule_appeal_hearing, rule_appeal,
    set_clock, make_staff_headers, make_board_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestRenewalTermTieredEligibility:
    def test_top_tier_earns_ten_years(self, api):
        """PRD §3.6: "The tiers are then evaluated from the top down and the
        first match wins: an average of at least 90.0 with zero probation-level
        notices and all three standings `GOOD` earns 10 years; failing that, an
        average of at least 75.0 with no standing at `CRITICAL` earns 5 years;
        failing that, an average of at least 60.0 earns 3 years; anything below
        earns 0, which bars renewal outright."
        PRD §3.6: "A successful create produces a `RenewalDecision` in `PENDING`
        status with `decision`, `granted_term_years`, `decided_by_user_id`, and
        `decided_at` all null."

        Design: Difficulty/combinatorial_formula/renewal_term_tiered_eligibility
        """
        ctx = setup_renewal_ready_school(school_name="CF Renewal Academy",
                                         applicant_id="applicant_cf1")
        # indices 90.0 / 90.0 / 91.0 -> avg 90.3; zero probations; all GOOD
        decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
        assert decision["eligible_term_years"] == 10
        assert decision["status"] == "PENDING"
        assert decision["decision"] is None
        assert decision["granted_term_years"] is None
        assert decision["decided_by_user_id"] is None
        assert decision["decided_at"] is None

    def test_in_term_probation_notice_drops_tier_to_five(self, api):
        """PRD §3.6: "Second, the probation count tallies the school's
        intervention notices at level `PROBATION` or `REVOCATION_REVIEW` whose
        `created_at` falls between `term_start` and `term_end` inclusive."
        PRD §3.6: "failing that, an average of at least 75.0 with no standing
        at `CRITICAL` earns 5 years"

        Design: Difficulty/combinatorial_formula/renewal_term_tiered_eligibility
        """
        ctx = setup_renewal_ready_school(school_name="CF Renewal Academy",
                                         applicant_id="applicant_cf1")
        # Clock is inside the contract term window (2032-01-15), so this manual
        # PROBATION notice is created in-term and breaks the top tier.
        notice = create_intervention(ctx["school"]["id"], level="PROBATION",
                                     domain="ACADEMIC", reason="Midterm dip")
        assert notice["created_at"] >= ctx["contract"]["term_start"]
        decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
        assert decision["eligible_term_years"] == 5


class TestRenewalDecidedRevertedRedecidedCycle:
    def _reverted_decision(self):
        ctx = setup_renewal_ready_school(school_name="NL Renewal Academy",
                                         applicant_id="applicant_nl3")
        decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
        validate_success(api_client.decide_renewal(
            decision["id"], {"outcome": "DENIED"}, make_board_headers("board_1")), 200)
        appeal = file_school_appeal(ctx["school"]["id"], "RENEWAL_DENIAL",
                                    decision["id"], grounds="Academic trend ignored")
        schedule_appeal_hearing(appeal["id"], "officer_nl3")
        return ctx, decision, appeal

    def test_overturned_renewal_denial_reverts_decision(self, api):
        """PRD §3.9: "For `RENEWAL_DENIAL`, the renewal decision moves `DECIDED`
        → `REVERTED`, its decided fields retained for audit and re-decision
        enabled per §3.6."

        Design: Difficulty/non_linear_state_machine/renewal_decision_decided_reverted_redecided_cycle
        """
        ctx, decision, appeal = self._reverted_decision()
        ruled = rule_appeal(appeal["id"], "officer_nl3", "OVERTURNED")
        assert ruled["status"] == "RULED_OVERTURNED"
        current = validate_success(
            api.get_renewal_decision(decision["id"], STAFF), 200)
        assert current["status"] == "REVERTED"

    def test_reverted_decision_redecides_with_refreshed_fields(self, api):
        """PRD §3.6: "the `REVERTED` status re-arms the decide transition under
        exactly the same rules as `PENDING`."
        PRD §3.6: "A re-decide after reversion refreshes all four fields."

        Design: Difficulty/non_linear_state_machine/renewal_decision_decided_reverted_redecided_cycle
        """
        ctx, decision, appeal = self._reverted_decision()
        rule_appeal(appeal["id"], "officer_nl3", "OVERTURNED")
        redecided = validate_success(
            api.decide_renewal(decision["id"], {"outcome": "RENEWED"},
                               make_board_headers("board_2")), 200)
        assert redecided["status"] == "DECIDED"
        assert redecided["decision"] == "RENEWED"
        assert redecided["granted_term_years"] == 10
        assert redecided["decided_by_user_id"] == "board_2"
        assert redecided["decided_at"] is not None


class TestRenewalRequiresActiveContract:
    def test_renewal_create_against_draft_contract_rejected(self, api):
        """PRD §3.6: "naming the `contract_id` of the school's `ACTIVE`
        contract — a contract that is not `ACTIVE` is rejected with
        `ERR_CONTRACT_INVALID_STATE`."
        PRD §2.9: "Incoming requests are checked against a fixed sequence of
        validation layers, and the first failing layer determines the error
        returned."

        Design: Difficulty/cross_entity_state_dependency/renewal_requires_active_contract
        """
        _app, school = create_approved_school(school_name="CE RenewalGate Academy",
                                              applicant_id="applicant_ce2")
        school = validate_success(api.get_school(school["id"], STAFF), 200)
        contract = create_draft_contract(school["id"], school["version"])
        assert contract["status"] == "DRAFT"
        res = api.create_renewal_decision(school["id"], {"contract_id": contract["id"]}, STAFF)
        validate_error(res, ApiErrorId.ERR_CONTRACT_INVALID_STATE, expected_status=409)

    def test_renewal_create_after_activation_succeeds_in_window(self, api):
        """PRD §3.6: "The logical clock must fall inside the renewal window,
        which runs from 365 days before the contract's `term_end` through 30
        days before `term_end`, both bounds inclusive; outside that window the
        create is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`."
        PRD §3.6: "A successful create produces a `RenewalDecision` in `PENDING`
        status with `decision`, `granted_term_years`, `decided_by_user_id`, and
        `decided_at` all null."

        Design: Difficulty/cross_entity_state_dependency/renewal_requires_active_contract
        """
        ctx = create_open_school(school_name="CE RenewalGate Academy",
                                 applicant_id="applicant_ce2")
        assert ctx["contract"]["status"] == "ACTIVE"
        set_clock(CLOCK["RENEWAL_OPEN"])
        decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
        assert decision["status"] == "PENDING"
        assert decision["contract_id"] == ctx["contract"]["id"]
