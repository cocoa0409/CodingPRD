"""Investor support tickets: state legality, investor self-service scoping,
SLA windows, and clock-driven escalation."""
import pytest
from datetime import timedelta

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_investor_headers,
    create_fund, create_partner, create_ticket, create_ticket_payload,
    set_clock, parse_instant, assert_investor_ticket,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
REP = TEST_USERS["investor_services_rep_headers"]


class TestTicketStateMachine:
    def test_ticket_reopen_from_open_returns_invalid_state(self, api):
        """PRD §2.8: "State-transition legality — the requested transition is
        declared from the resource’s current state, else
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.9: "Reopening, done by an `InvestorServicesRep` or by the owning
        `Investor` — whose `X-User-ID` must equal the ticket’s `partner_id`,
        else `ERR_FORBIDDEN_FOR_ROLE`, with an optional `reason` — moves an
        `ANSWERED` ticket to `REOPENED`, and escalation is recomputed against
        the original `due_at`."

        Design: Corner/state_machines/ticket_reopen_from_open_returns_invalid_state
        """
        fund = create_fund()
        partner = create_partner(fund["id"], legal_name="P")
        ticket = create_ticket(partner["id"], category="ALLOCATION_QUESTION", subject="Q")
        assert ticket["status"] == "OPEN"
        resp = api.reopen_ticket(ticket["id"], REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_ticket(ticket["id"], REP), 200)
        assert after["status"] == "OPEN"


class TestInvestorTicketSelfService:
    def test_investor_ticket_self_service(self, api):
        """PRD §3.9: "An `Investor` may open tickets only for their own account
        — the `partner_id` must equal their `X-User-ID`, else
        `ERR_FORBIDDEN_FOR_ROLE` — and the referenced partner and tax year must
        belong to the same fund."
        PRD §3.9: "Each ticket’s `due_at` is its `created_at` plus a
        service-level window of twenty-four hours for `AMENDED_K1_QUESTION`
        tickets and seventy-two hours for every other category."

        Design: Corner/rbac/investor_ticket_self_service
        """
        fund = create_fund()
        p1 = create_partner(fund["id"], legal_name="P1", ownership_pct_bps=5000)
        p2 = create_partner(
            fund["id"], legal_name="P2", partner_type="US_ENTITY",
            residency_state="DE", ownership_pct_bps=5000,
        )
        investor_p1 = make_investor_headers(p1["id"])
        resp_cross = api.create_ticket(
            create_ticket_payload(p2["id"], category="DELIVERY_ISSUE", subject="not mine"),
            investor_p1,
        )
        validate_error(resp_cross, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp_self = api.create_ticket(
            create_ticket_payload(p1["id"], category="DELIVERY_ISSUE", subject="where is my K1"),
            investor_p1,
        )
        ticket = validate_success(resp_self, 201)
        assert_investor_ticket(ticket)
        assert ticket["status"] == "OPEN"
        created = parse_instant(ticket["created_at"])
        due = parse_instant(ticket["due_at"])
        assert due - created == timedelta(hours=72), (
            f"DELIVERY_ISSUE carries the 72h SLA: created {ticket['created_at']}, due {ticket['due_at']}"
        )


class TestTicketEscalationClock:
    def test_ticket_escalation_derives_from_clock(self, api):
        """PRD §3.9: "A ticket’s `is_escalated` flag starts false and becomes
        true when the current clock passes `due_at` while the ticket stands
        `OPEN` or `REOPENED`."
        PRD §2.5: "Every server-stamped timestamp — `created_at`, `updated_at`,
        `delivered_at`, `filed_at`, and `computed_at` — and every clock-derived
        computation — ticket `due_at` and `is_escalated`, K-1 `is_late`,
        withholding months-late, and the day-of-year used by provisional
        projections — reads this logical clock. After the clock moves,
        clock-derived fields are recomputed lazily on the next read."

        Design: Corner/complexity_layers/ticket_escalation_derives_from_clock
        """
        fund = create_fund()
        partner = create_partner(fund["id"], legal_name="P")
        ticket = create_ticket(partner["id"], category="ALLOCATION_QUESTION", subject="explain my allocation")
        before = validate_success(api.get_ticket(ticket["id"], REP), 200)
        assert before["is_escalated"] is False
        created = parse_instant(before["created_at"])
        due = parse_instant(before["due_at"])
        assert due - created == timedelta(hours=72), "ALLOCATION_QUESTION carries the 72h SLA"
        set_clock("2026-08-05T00:00:00Z")
        after = validate_success(api.get_ticket(ticket["id"], REP), 200)
        assert after["is_escalated"] is True, (
            "clock past due_at with the ticket still OPEN must escalate"
        )
