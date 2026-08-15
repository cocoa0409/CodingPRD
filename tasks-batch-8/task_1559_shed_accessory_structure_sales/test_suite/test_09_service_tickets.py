"""Warranty service tickets: order-completion gate, warranty charge threshold, and the
reopen cycle (PRD §3.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_timestamp_format,
    setup_book, create_draft_order, get_order, drive_order_to_completed,
    create_service_ticket_payload, advance_clock, make_customer_headers,
    DEPOSIT_10X12_WINDOW, SERVICE_CALL_BASE_CENTS,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
CREW = TEST_USERS["install_crew_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


class TestServiceTicketGatedByOrderCompletion:
    def test_ticket_on_draft_order_rejected(self, api):
        """PRD §3.8: "Once an order is `COMPLETED` or `CLOSED`, the owning `Customer` or
        a `SalesRep` can open a `ServiceTicket` by supplying the `order_id` and an
        `issue_description`; opening a ticket against an order that has not reached one
        of those states is rejected with `ERR_ORDER_NOT_COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/service_ticket_gated_by_order_completion
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        res = api.create_service_ticket(
            create_service_ticket_payload(order["id"]), SALES
        )
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_COMPLETED, expected_status=409)
        rows, meta = validate_paginated(api.list_order_service_tickets(order["id"], SALES))
        assert meta["total_count"] == 0, "no ticket persisted"

    def test_ticket_after_completion_succeeds(self, api):
        """PRD §3.8: "Once an order is `COMPLETED` or `CLOSED`, the owning `Customer` or
        a `SalesRep` can open a `ServiceTicket` by supplying the `order_id` and an
        `issue_description`; opening a ticket against an order that has not reached one
        of those states is rejected with `ERR_ORDER_NOT_COMPLETED`. New tickets start
        `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/service_ticket_gated_by_order_completion
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        res = api.create_service_ticket(create_service_ticket_payload(order["id"]), SALES)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_COMPLETED)

        completed = drive_order_to_completed(order, deposit_cents=DEPOSIT_10X12_WINDOW)
        assert completed["status"] == "COMPLETED"
        ticket = validate_success(
            api.create_service_ticket(
                create_service_ticket_payload(order["id"], "door hinge misaligned"), SALES
            ),
            201,
        )
        assert ticket["status"] == "OPEN"
        assert ticket["order_id"] == order["id"]


def _completed_order(api):
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
    completed = drive_order_to_completed(order, deposit_cents=DEPOSIT_10X12_WINDOW)
    return cust, completed


def _scheduled_ticket(api, order_id, issue="window latch sticks"):
    ticket = validate_success(
        api.create_service_ticket(create_service_ticket_payload(order_id, issue), SALES), 201
    )
    scheduled = validate_success(
        api.schedule_service_ticket(
            ticket["id"], {"crew_id": "crew-3", "scheduled_date": "2026-08-04"}, SALES
        ),
        200,
    )
    return scheduled


def test_in_warranty_resolve_zero_charge(api):
    """PRD §3.8: "Resolving stamps `resolved_at` from the logical clock, computes
    `in_warranty` — true when the resolution time is on or before the order's
    `warranty_ends_at`, the boundary inclusive — and sets `charge_cents`: zero while in
    warranty, otherwise a $150.00 service-call base plus the declared parts."
    PRD §2.6: "The server maintains a logical clock whose startup value is exactly
    `2026-08-01T00:00:00Z`"

    Design: Corner/calculations/in_warranty_resolve_zero_charge
    """
    _, completed = _completed_order(api)
    ticket = _scheduled_ticket(api, completed["id"])
    resolved = validate_success(
        api.resolve_service_ticket(ticket["id"], {"parts_cents": 0}, CREW), 200
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["in_warranty"] is True
    assert resolved["charge_cents"] == 0
    assert_timestamp_format(resolved["resolved_at"])
    assert resolved["resolved_at"].startswith("2026-08-01"), "stamped from the logical clock"


def test_out_of_warranty_resolve_charge(api):
    """PRD §3.8: "Resolving stamps `resolved_at` from the logical clock, computes
    `in_warranty` — true when the resolution time is on or before the order's
    `warranty_ends_at`, the boundary inclusive — and sets `charge_cents`: zero while in
    warranty, otherwise a $150.00 service-call base plus the declared parts."
    PRD §3.5: "`warranty_ends_at` is set to exactly twelve months after completion"

    Design: Corner/calculations/out_of_warranty_resolve_charge
    """
    _, completed = _completed_order(api)
    assert str(completed["warranty_ends_at"]).startswith("2027-08-01")
    ticket = _scheduled_ticket(api, completed["id"], issue="roof shingle peeled")
    advance_clock("2027-09-01T00:00:00Z")  # past warranty_ends_at
    resolved = validate_success(
        api.resolve_service_ticket(ticket["id"], {"parts_cents": 5000}, CREW), 200
    )
    assert resolved["in_warranty"] is False
    assert resolved["charge_cents"] == SERVICE_CALL_BASE_CENTS + 5000  # 20000


def test_service_ticket_reopen_cycle(api):
    """PRD §3.8: "The owning `Customer` may reopen a resolved ticket, but only within
    thirty days of `resolved_at` and only while the order's warranty is still running; a
    reopen outside either bound is rejected with `ERR_INVALID_STATE`. Reopening returns
    the ticket from `RESOLVED` to `OPEN`, increments `reopen_count` from its initial
    zero, and increments `version`."

    Design: Corner/state_machines/service_ticket_reopen_cycle
    """
    cust, completed = _completed_order(api)
    owner = make_customer_headers(cust["id"])
    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(completed["id"]), owner
        ),
        201,
    )
    validate_success(
        api.schedule_service_ticket(
            ticket["id"], {"crew_id": "crew-3", "scheduled_date": "2026-08-04"}, SALES
        ),
        200,
    )
    resolved = validate_success(
        api.resolve_service_ticket(ticket["id"], {"parts_cents": 0}, CREW), 200
    )
    assert resolved["reopen_count"] == 0

    reopened = validate_success(api.reopen_service_ticket(ticket["id"], owner), 200)
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    assert reopened["version"] > resolved["version"], "reopen increments the ticket version"
