"""Repair tickets: the re-quote loop, terminal lockdown, and per-target RBAC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_ticket,
    make_customer,
    make_repair_ticket,
    validate_error,
    validate_success,
)

TECH_HEADERS = TEST_USERS["service_tech_headers"]
MANAGER_HEADERS = TEST_USERS["branch_manager_headers"]


def _advance(api, ticket_id, to, headers=TECH_HEADERS, quote_cents=None):
    payload = {"to": to}
    if quote_cents is not None:
        payload["quote_cents"] = quote_cents
    return validate_success(api.advance_repair_ticket(ticket_id, payload,
                                                      headers))


class TestRequoteLoop:
    def _rejected_ticket(self, api):
        customer = make_customer(account_no="ACC-RP1", name="Repair Co",
                                 terms="CASH")
        ticket = make_repair_ticket(
            customer["id"], machine_desc="Miller 252 (customer-owned)",
            issue_desc="Wire feed erratic")
        _advance(api, ticket["id"], "DIAGNOSING")
        _advance(api, ticket["id"], "QUOTED", quote_cents=50000)
        _advance(api, ticket["id"], "REJECTED", headers=MANAGER_HEADERS)
        return customer, ticket

    def test_requote_loop_bumps_revision_and_clears_quote(self, api):
        """PRD §3.9: "Rejection is not the end: a `REJECTED` ticket can be
        advanced back to `DIAGNOSING` for another look, and each such re-quote
        loop increments `revision_no` and clears `quote_cents` back to null,
        so the next quote starts clean."

        Design: Difficulty/non_linear_state_machine/repair_quote_revision_cycle
        """
        _customer, ticket = self._rejected_ticket(api)
        assert get_ticket(ticket["id"])["quote_cents"] == 50000
        looped = _advance(api, ticket["id"], "DIAGNOSING")
        assert looped["revision_no"] == 1, "the REJECTED->DIAGNOSING loop"
        assert looped["quote_cents"] is None, "the old quote is cleared"

    def test_second_quote_is_charged_at_close(self, api):
        """PRD §3.9: "Closure settles the money: a ticket closed from
        `READY_FOR_PICKUP` sets `charged_cents` to its `quote_cents`, while a
        ticket closed from `REJECTED` — the customer declined the work — sets
        `charged_cents` to 0; until closure, `charged_cents` is null." After
        the re-quote loop, the second quote (45000) — not the rejected 50000 —
        is what closes out.

        Design: Difficulty/non_linear_state_machine/repair_quote_revision_cycle
        """
        _customer, ticket = self._rejected_ticket(api)
        _advance(api, ticket["id"], "DIAGNOSING")
        _advance(api, ticket["id"], "QUOTED", quote_cents=45000)
        _advance(api, ticket["id"], "APPROVED", headers=MANAGER_HEADERS)
        _advance(api, ticket["id"], "IN_REPAIR")
        _advance(api, ticket["id"], "READY_FOR_PICKUP")
        closed = _advance(api, ticket["id"], "CLOSED")
        assert closed["status"] == "CLOSED"
        assert closed["charged_cents"] == 45000


class TestRepairTerminalLockdown:
    def test_rejected_close_charges_zero_and_locks(self, api):
        """PRD §3.9: "Closure settles the money: a ticket closed from
        `READY_FOR_PICKUP` sets `charged_cents` to its `quote_cents`, while a
        ticket closed from `REJECTED` — the customer declined the work — sets
        `charged_cents` to 0; until closure, `charged_cents` is null.
        `CLOSED` is terminal, and any advance whose from-state and target do
        not form one of the pairs above is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/repair_ticket_terminal_lockdown_and_zero_charge_on_reject_close
        """
        customer = make_customer(account_no="ACC-SM9", name="Fix Co",
                                 terms="CASH")
        ticket = make_repair_ticket(customer["id"],
                                    machine_desc="Lincoln 210",
                                    issue_desc="No arc")
        _advance(api, ticket["id"], "DIAGNOSING")
        _advance(api, ticket["id"], "QUOTED", quote_cents=8000)
        _advance(api, ticket["id"], "REJECTED", headers=MANAGER_HEADERS)
        closed = _advance(api, ticket["id"], "CLOSED")
        assert closed["status"] == "CLOSED"
        assert closed["charged_cents"] == 0, "declined work bills nothing"
        resp = api.advance_repair_ticket(ticket["id"], {"to": "DIAGNOSING"},
                                         TECH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRepairApprovalRbac:
    def test_repair_approve_forbidden_for_service_tech(self, api,
                                                       service_tech_headers):
        """PRD §3.9: "From `QUOTED` the decision is managerial: only a
        `BranchManager` may advance the ticket to `APPROVED` or to `REJECTED`,
        while the other targets are open to a `ServiceTech` or
        `BranchManager`." PRD §2.1: a request that "fails a per-action role
        condition, such as ... the per-target role split on repair-ticket and
        enrollment advancement described in §3 — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/repair_approve_forbidden_for_service_tech
        """
        customer = make_customer(account_no="ACC-RB2", name="Fix Co",
                                 terms="CASH")
        ticket = make_repair_ticket(customer["id"],
                                    machine_desc="Hypertherm 45",
                                    issue_desc="Arc drops")
        _advance(api, ticket["id"], "DIAGNOSING")
        _advance(api, ticket["id"], "QUOTED", quote_cents=8000)
        resp = api.advance_repair_ticket(ticket["id"], {"to": "APPROVED"},
                                         service_tech_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
