"""Second-coverage tests for difficulty queue A instances that would otherwise
have only one assertion. Each test here probes a distinct observable of the
same scenario already exercised elsewhere — a complementary field, a comparison
against the "no-conflict" baseline, or a neighbouring boundary point — and is
independently derivable from a verbatim PRD sentence.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_client,
    create_contract,
    activate_contract,
    create_technician,
    create_ticket,
    assign_ticket,
    create_dispatch,
    create_quote,
    send_quote,
    accept_quote,
    create_procurement_order,
    setup_active_contract,
    setup_active_contract_with_tech,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Second test for: priority_pair_validation_conflict /
# dispatch_state_precedes_technician_overlap
# ---------------------------------------------------------------------------

def test_dispatch_on_in_progress_ticket_with_no_conflict_succeeds(api):
    """PRD §3.6: "A `Dispatcher` creates one on a ticket by supplying the
    `technician_id`, a `mode` of `REMOTE` or `ONSITE`, a `scheduled_start`
    (inclusive) and `scheduled_end` (exclusive), and an optional
    `resolves_ticket` flag that defaults to `true`."
    PRD §3.6: "A new dispatch opens in `SCHEDULED`."

    Baseline for the priority-ordering test: when the ticket IS
    IN_PROGRESS and the technician has no earlier dispatch to conflict with,
    the same create succeeds — proving the state check is the discriminator.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_precedes_technician_overlap
    """
    client, contract, tech = setup_active_contract_with_tech()
    ticket = create_ticket(client["id"], contract["id"], priority="P2", subject="ok")
    ticket = assign_ticket(ticket["id"], tech["id"])
    resp = api.create_dispatch(
        ticket["id"],
        {"technician_id": tech["id"], "mode": "ONSITE",
         "scheduled_start": "2026-05-01T08:30:00Z",
         "scheduled_end": "2026-05-01T09:30:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Second test for: priority_pair_validation_conflict /
# place_order_referential_precedes_fiscal
# ---------------------------------------------------------------------------

def test_place_order_with_accepted_quote_within_credit_succeeds(api):
    """PRD §3.7: "On success the order moves `DRAFT` → `PLACED` and the
    client's `credit_available_cents` is recomputed, debited by `total_cents`."

    Baseline for the priority-ordering test: with the referential precondition
    satisfied (quote ACCEPTED) and the fiscal precondition satisfied (credit
    exceeds total), the identical place call succeeds — proving the failing
    referential step in the paired test is the discriminator.

    Design: Difficulty/priority_pair_validation_conflict/place_order_referential_precedes_fiscal
    """
    from test_helpers import make_client_contact_headers
    client = create_client(
        company_name="KappaOK", primary_contact_email="ok@kappa.test",
        credit_limit_cents=10_000_000,
    )
    quote = create_quote(
        client["id"], "PROCUREMENT",
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
    )
    send_quote(quote["id"])
    validate_success(api.accept_quote(
        quote["id"], make_client_contact_headers(client["id"]),
    ))
    order = create_procurement_order(
        client["id"],
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
        quote_id=quote["id"],
    )
    resp = api.place_procurement_order(
        order["id"], TEST_USERS["account_manager_headers"],
    )
    data = validate_success(resp)
    assert data["status"] == "PLACED"
