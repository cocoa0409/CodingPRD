"""Difficulty rule: non_linear_state_machine.

  (A) Hearing SCHEDULED -> SCHEDULED self-cycle via adjourn (cyclic machine);
  (B) Citation CONTESTED fork to {UPHELD, DISMISSED} with divergent effects.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_scheduled_hearing,
)

ADMIN = TEST_USERS["admin_headers"]
HEARING = TEST_USERS["hearing_officer_headers"]


class TestHearingAdjournCycle:
    def test_adjourn_keeps_scheduled_and_increments_count(self, api):
        """PRD §3.6: "A successful adjournment replaces the hearing's
        `scheduled_start` and `scheduled_end` with the new values and increases
        `adjournment_count` by 1, leaving the hearing in `SCHEDULED` — a self-cycle
        that may repeat."

        Design: Difficulty/non_linear_state_machine/hearing_adjourn_reschedule_cycle
        """
        ctx = setup_scheduled_hearing()
        hearing = ctx["hearing"]
        adj = validate_success(api.adjourn_hearing(
            hearing["id"],
            {"scheduled_start": "2026-03-06T09:00:00Z",
             "scheduled_end": "2026-03-06T10:00:00Z"}, HEARING))
        assert adj["status"] == "SCHEDULED", \
            f"adjourn must keep hearing SCHEDULED, got {adj['status']}"
        assert adj["adjournment_count"] == 1, \
            f"adjournment_count must become 1, got {adj['adjournment_count']}"

    def test_adjourn_replaces_scheduled_window(self, api):
        """PRD §3.6: "A successful adjournment replaces the hearing's
        `scheduled_start` and `scheduled_end` with the new values and increases
        `adjournment_count` by 1, leaving the hearing in `SCHEDULED` — a self-cycle
        that may repeat."

        Design: Difficulty/non_linear_state_machine/hearing_adjourn_reschedule_cycle
        """
        ctx = setup_scheduled_hearing()
        hearing = ctx["hearing"]
        adj = validate_success(api.adjourn_hearing(
            hearing["id"],
            {"scheduled_start": "2026-03-06T09:00:00Z",
             "scheduled_end": "2026-03-06T10:00:00Z"}, HEARING))
        assert adj["scheduled_start"].startswith("2026-03-06T09:00:00"), \
            f"scheduled_start must be replaced, got {adj['scheduled_start']}"


class TestCitationContestFork:
    def test_dismissed_branch_zeroes_due_and_is_terminal(self, api):
        """PRD §3.6: "On a `DISMISSED` decision, the contest moves from
        `HEARING_SCHEDULED` to `CLOSED_DISMISSED` and the citation moves from
        `CONTESTED` to `DISMISSED`; a dismissed citation's `amount_due_cents` becomes
        0 and it is terminal, so the recomputed balance and scofflaw tier may
        de-escalate."

        Design: Difficulty/non_linear_state_machine/citation_contest_fork_uphold_dismiss
        """
        ctx = setup_scheduled_hearing(base_fine_cents=15000, code="HYDRANT")
        validate_success(api.decide_hearing(
            ctx["hearing"]["id"], {"decision": "DISMISSED"}, HEARING))

        cit = validate_success(api.get_citation(ctx["citation"]["id"], ADMIN))
        assert cit["status"] == "DISMISSED"
        assert cit["amount_due_cents"] == 0, \
            f"dismissed citation amount_due must be 0, got {cit['amount_due_cents']}"
        contest = validate_success(api.get_contest(ctx["contest"]["id"], ADMIN))
        assert contest["status"] == "CLOSED_DISMISSED"
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["unpaid_citation_count"] == 0, \
            f"dismissed citation leaves the unpaid set, got {veh['unpaid_citation_count']}"

    def test_upheld_branch_returns_citation_to_payable_set(self, api):
        """PRD §3.6: "On an `UPHELD` decision, the contest moves from
        `HEARING_SCHEDULED` to `CLOSED_UPHELD` and the citation moves from
        `CONTESTED` to `UPHELD`, returning it to the vehicle's payable unpaid set —
        the citation remains owed, so the vehicle balance and scofflaw tier are
        recomputed and may re-escalate."

        Design: Difficulty/non_linear_state_machine/citation_contest_fork_uphold_dismiss
        """
        ctx = setup_scheduled_hearing(base_fine_cents=15000, code="HYDRANT")
        validate_success(api.decide_hearing(
            ctx["hearing"]["id"], {"decision": "UPHELD"}, HEARING))

        cit = validate_success(api.get_citation(ctx["citation"]["id"], ADMIN))
        assert cit["status"] == "UPHELD"
        contest = validate_success(api.get_contest(ctx["contest"]["id"], ADMIN))
        assert contest["status"] == "CLOSED_UPHELD"
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["unpaid_citation_count"] == 1, \
            f"upheld citation returns to unpaid set, got {veh['unpaid_citation_count']}"
        assert veh["outstanding_balance_cents"] == 15000, \
            f"upheld citation still owed 15000, got {veh['outstanding_balance_cents']}"
