"""Consignment intake → listing → SOLD/RETURNED fork, auction session lifecycle,
and the side effects each branch does (or deliberately does not) produce.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_listed_consignment,
    create_auction_session,
    TEST_USERS,
)

SALES = TEST_USERS["sales_agent_headers"]


# ─── Rule 3b: LISTED forks to RETURNED (no settlement) ────────────────────

def test_consignment_return_transitions_to_returned_hammer_null(api):
    """PRD §3.6: "a SalesAgent returns an unsold LISTED consignment to the
    consignor: this simply advances the status from LISTED to RETURNED, and — in
    deliberate contrast to the sale branch — no settlement is ever created and no
    proceeds are computed for a returned consignment."

    Design: Difficulty/non_linear_state_machine/consignment_listed_branches_to_returned
    """
    ctx = setup_listed_consignment(room="ROOM-B", customer_name="Consignor Two",
                                   description="Silver bar")
    cons_id = ctx["consignment"]["id"]

    returned = validate_success(api.return_consignment(cons_id, SALES), 200)
    assert returned["status"] == "RETURNED"
    assert returned["hammer_price_cents"] is None


def test_returned_consignment_has_no_settlement(api):
    """PRD §3.6: "a SalesAgent returns an unsold LISTED consignment to the
    consignor: this simply advances the status from LISTED to RETURNED, and — in
    deliberate contrast to the sale branch — no settlement is ever created and no
    proceeds are computed for a returned consignment."

    Design: Difficulty/non_linear_state_machine/consignment_listed_branches_to_returned
    """
    ctx = setup_listed_consignment(room="ROOM-B2", customer_name="Consignor Two B",
                                   description="Silver bar")
    cons_id = ctx["consignment"]["id"]
    validate_success(api.return_consignment(cons_id, SALES), 200)

    data, meta = validate_paginated(
        api.list_settlements(SALES, params={"consignment_id": cons_id}))
    assert meta["total_count"] == 0
    assert data == []


# ─── Corner: LISTED → SOLD records hammer price ───────────────────────────

def test_record_sale_sets_hammer_and_sold_status(api):
    """PRD §3.6: "A successful record-sale stores the hammer_price_cents on the
    consignment, advances its status from LISTED to SOLD, and increments its version."

    Design: Corner/state_machines/consignment_sold_side_effect_records_hammer_price
    """
    ctx = setup_listed_consignment(room="ROOM-SOLD", reserve_price_cents=50_000,
                                   customer_name="Sold Consignor", description="Gold eagle")
    cons_id = ctx["consignment"]["id"]
    sold = validate_success(
        api.record_sale_consignment(
            cons_id, {"hammer_price_cents": 80_000,
                      "expected_consignment_version": ctx["listed_version"]}, SALES), 200)
    assert sold["status"] == "SOLD"
    assert sold["hammer_price_cents"] == 80_000


# ─── Corner: close an already-CLOSED auction session ──────────────────────

def test_close_already_closed_session_invalid_state(api):
    """PRD §3.8: "A session begins with status SCHEDULED and may later be closed by
    a SalesAgent, moving its status from SCHEDULED to CLOSED." PRD §2.7: "state —
    the target resource is in a state from which the requested transition is
    defined, else ERR_INVALID_STATE (409)".

    Design: Corner/state_machines/close_auction_session_from_closed_returns_invalid_state
    """
    session = create_auction_session(room="ROOM-SM", scheduled_start="2026-04-10T10:00:00Z",
                                     scheduled_end="2026-04-10T12:00:00Z")
    validate_success(api.close_auction_session(session["id"], SALES), 200)
    res = api.close_auction_session(session["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")
