"""Resource overlap conflicts and compensating-action invariants.

Difficulty queue: resource_temporal_overlap + compensating_invariant instances.
Corner stub owned here: validations/container_capacity_violation_excluded.
"""
from test_helpers import fixtures, validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    open_hedge,
    create_shipped_shipment,
    dispatch_container,
    WM, PC, SA, CO, YM,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Rule 8 — resource_temporal_overlap / container_capacity_aggregate_overflow
#   (also owns Corner stub validations/container_capacity_violation_excluded)
# ---------------------------------------------------------------------------
def test_container_capacity_aggregate_overflow_rejected(api):
    """PRD §3.4: "Finally the load must fit: the container's current
    `loaded_weight_lb` plus the ticket's `net_weight_lb` must be at most the
    container's `capacity_lb`, or the release is rejected with
    `ERR_CONTAINER_CAPACITY_EXCEEDED` (HTTP 409)."

    A container of capacity 1000 already loaded to 800 by ticket A rejects ticket B
    (net 300) because 800+300 > 1000.

    Design: Difficulty/resource_temporal_overlap/container_capacity_aggregate_overflow
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Cap Co", id_type="STATE_ID", id_number="SID-13")
    container = stage_container("FERROUS", capacity_lb=1000)
    # Ticket A: gross 1000, tare 200 -> net 800, loads container to 800.
    tkt_a = open_ticket(seller["id"], gross_weight_lb=1000)
    add_line(tkt_a["id"], "SHRED_STEEL", 100)
    validate_success(api.weigh_out(tkt_a["id"], {"tare_weight_lb": 200}, WM))
    validate_success(api.release_ticket(tkt_a["id"], {"container_id": container["id"]}, WM))
    # Ticket B: gross 500, tare 200 -> net 300; 800+300 > 1000.
    tkt_b = open_ticket(seller["id"], gross_weight_lb=500)
    add_line(tkt_b["id"], "SHRED_STEEL", 100)
    validate_success(api.weigh_out(tkt_b["id"], {"tare_weight_lb": 200}, WM))
    resp = api.release_ticket(tkt_b["id"], {"container_id": container["id"]}, WM)
    validate_error(resp, ApiErrorId.ERR_CONTAINER_CAPACITY_EXCEEDED.value)
    cont_after = validate_success(api.get_container(container["id"], YM))
    assert cont_after["loaded_weight_lb"] == 800, \
        f"loaded_weight_lb must stay 800, got {cont_after['loaded_weight_lb']}"


def test_container_capacity_aggregate_exact_fit_allowed(api):
    """PRD §3.4: "the container's current `loaded_weight_lb` plus the ticket's
    `net_weight_lb` must be at most the container's `capacity_lb`."

    Boundary: a second release that brings the total to exactly capacity (800+200=1000
    for capacity 1000) is allowed.

    Design: Difficulty/resource_temporal_overlap/container_capacity_aggregate_overflow
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Cap Co", id_type="STATE_ID", id_number="SID-13B")
    container = stage_container("FERROUS", capacity_lb=1000)
    tkt_a = open_ticket(seller["id"], gross_weight_lb=1000)
    add_line(tkt_a["id"], "SHRED_STEEL", 100)
    validate_success(api.weigh_out(tkt_a["id"], {"tare_weight_lb": 200}, WM))
    validate_success(api.release_ticket(tkt_a["id"], {"container_id": container["id"]}, WM))
    # Ticket B: gross 400, tare 200 -> net 200; 800+200 == 1000 (exact fit).
    tkt_b = open_ticket(seller["id"], gross_weight_lb=400)
    add_line(tkt_b["id"], "SHRED_STEEL", 100)
    validate_success(api.weigh_out(tkt_b["id"], {"tare_weight_lb": 200}, WM))
    data = validate_success(api.release_ticket(tkt_b["id"], {"container_id": container["id"]}, WM))
    assert data["status"] == "RELEASED", f"exact fit must release, got {data['status']}"
    cont_after = validate_success(api.get_container(container["id"], YM))
    assert cont_after["loaded_weight_lb"] == 1000, \
        f"loaded_weight_lb must reach 1000, got {cont_after['loaded_weight_lb']}"


# ---------------------------------------------------------------------------
# Rule 8 — resource_temporal_overlap / hedge_over_realization_remaining_capacity
# ---------------------------------------------------------------------------
def _release_dispatch_ship(seller_id, hedge_id, tare, gross=1000):
    """Helper: weighed -> release -> dispatch -> ship linked to hedge. Returns shipment."""
    container = stage_container("FERROUS", capacity_lb=5000)
    tkt = open_ticket(seller_id, gross_weight_lb=gross)
    add_line(tkt["id"], "SHRED_STEEL", 100)
    validate_success(api_client.weigh_out(tkt["id"], {"tare_weight_lb": tare}, WM))
    validate_success(api_client.release_ticket(tkt["id"], {"container_id": container["id"]}, WM))
    dispatch_container(container["id"])
    ship = validate_success(
        api_client.create_mill_shipment(
            {"container_id": container["id"], "hedge_position_id": hedge_id}, SA), 201
    )
    return ship


def test_hedge_over_realization_rejected(api):
    """PRD §3.7: "the realization may not push `realized_weight_lb` past
    `hedged_weight_lb`, and a shipment whose weight would over-realize the position
    is rejected with `ERR_HEDGE_OVER_REALIZED` (HTTP 409)."

    Hedge 1000 lb realized once to 600 (remaining 400); a second 600 lb shipment
    would over-realize and is rejected.

    Design: Difficulty/resource_temporal_overlap/hedge_over_realization_remaining_capacity
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Over Co", id_type="STATE_ID", id_number="SID-14")
    hedge = open_hedge(category="FERROUS", hedged_weight_lb=1000, locked_price=90)
    # Shipment A: net 600 (gross 1000, tare 400) realizes 600 against the hedge.
    ship_a = _release_dispatch_ship(seller["id"], hedge["id"], tare=400, gross=1000)
    validate_success(
        api.settle_mill_shipment(
            ship_a["id"],
            {"final_settlement_cents": 50000, "expected_hedge_version": hedge["version"]},
            SA,
        )
    )
    hedge_after_a = validate_success(api.get_hedge(hedge["id"], SA))
    assert hedge_after_a["realized_weight_lb"] == 600
    # Shipment B: net 600 again; remaining capacity is only 400 -> over-realize.
    ship_b = _release_dispatch_ship(seller["id"], hedge["id"], tare=400, gross=1000)
    resp = api.settle_mill_shipment(
        ship_b["id"],
        {"final_settlement_cents": 50000,
         "expected_hedge_version": hedge_after_a["version"]},
        SA,
    )
    validate_error(resp, ApiErrorId.ERR_HEDGE_OVER_REALIZED.value)
    hedge_final = validate_success(api.get_hedge(hedge["id"], SA))
    assert hedge_final["realized_weight_lb"] == 600, \
        f"realized_weight_lb must stay 600, got {hedge_final['realized_weight_lb']}"


# ---------------------------------------------------------------------------
# Rule 9 — compensating_invariant / void_payout_leaves_ytd_cash_unchanged
# ---------------------------------------------------------------------------
def test_void_payout_leaves_ytd_cash_unchanged(api):
    """PRD §3.5: "Voiding closes the payout without disbursement; because no cash was
    ever added, there is no ledger movement to reverse, and the ticket stays
    `RELEASED`."
    PRD §3.5: "The 1099 cash ledger is driven entirely at settlement and only by
    cash."

    Creating then voiding a PENDING CASH payout leaves ytd_cash_paid_cents at its
    pre-payout value (0) and requires_1099 false.

    Design: Difficulty/compensating_invariant/void_payout_leaves_ytd_cash_unchanged
    """
    built = fixtures.create_pending_payout(method="CASH", grade_code="SHRED_STEEL",
                                           category="FERROUS", spot=11, weight_lb=100)
    data = validate_success(api.void_payout(built["payout"]["id"], PC))
    assert data["status"] == "VOID", f"expected VOID, got {data['status']}"
    seller = validate_success(api.get_seller(built["seller_id"], WM))
    assert seller["ytd_cash_paid_cents"] == 0, \
        f"ytd_cash_paid_cents must stay 0, got {seller['ytd_cash_paid_cents']}"
    assert seller["requires_1099"] is False, \
        f"requires_1099 must stay False, got {seller['requires_1099']}"


# ---------------------------------------------------------------------------
# Rule 9 — compensating_invariant / clear_theft_report_restores_open_report_count
# ---------------------------------------------------------------------------
def test_clear_theft_report_restores_open_count_and_status(api):
    """PRD §3.1: "Clearing transitions the report from `OPEN` to `CLEARED`,
    decrements the seller's `open_theft_reports` by 1, and — if that count has
    fallen to 0 and the seller is not `BANNED` — restores the seller's `status` to
    `ACTIVE`."

    Reporting flags the seller (open_theft_reports=1); clearing restores it to 0 and
    the seller to ACTIVE.

    Design: Difficulty/compensating_invariant/clear_theft_report_restores_open_report_count
    """
    publish_price("CAT_CONV", "NON_FERROUS", spot=50000, mill=52000)
    seller = register_seller(legal_name="Clr Co", id_type="PASSPORT", id_number="P-16")
    ticket = open_ticket(seller["id"], gross_weight_lb=50)
    add_line(ticket["id"], "CAT_CONV", 5)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 10}, WM))
    validate_success(api.report_ticket(ticket["id"], {"reason": "serial match"}, WM))
    from test_helpers import validate_paginated
    reports, _ = validate_paginated(
        api.list_theft_reports(CO, params={"seller_id": seller["id"], "status": "OPEN"})
    )
    report_id = reports[0]["id"]
    cleared = validate_success(api.clear_theft_report(report_id, CO))
    assert cleared["status"] == "CLEARED", f"expected CLEARED, got {cleared['status']}"
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["open_theft_reports"] == 0, \
        f"open_theft_reports must return to 0, got {seller_after['open_theft_reports']}"
    assert seller_after["status"] == "ACTIVE", \
        f"seller must be restored to ACTIVE, got {seller_after['status']}"


# ---------------------------------------------------------------------------
# Second tests for ≥2-per-instance difficulty coverage
# ---------------------------------------------------------------------------
def test_hedge_partial_realization_leaves_remaining_capacity(api):
    """PRD §3.7: "The pounds realized on this leg is the smaller of the shipment's
    `shipped_weight_lb` and the hedge's remaining capacity (its `hedged_weight_lb`
    minus its already-`realized_weight_lb`)."
    PRD §3.8: "As mill shipments settle against it, its `realized_weight_lb` and
    `realized_pnl_cents` accumulate per the realization cascade of §3.7, capped so
    realized pounds never exceed `hedged_weight_lb`."

    The first 600 lb leg against a 1000 lb hedge leaves the position OPEN with 600
    realized — the residual-capacity state that the over-realize check later guards.

    Design: Difficulty/resource_temporal_overlap/hedge_over_realization_remaining_capacity
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Over2 Co", id_type="STATE_ID", id_number="SID-14B")
    hedge = open_hedge(category="FERROUS", hedged_weight_lb=1000, locked_price=90)
    ship_a = _release_dispatch_ship(seller["id"], hedge["id"], tare=400, gross=1000)
    validate_success(
        api.settle_mill_shipment(
            ship_a["id"],
            {"final_settlement_cents": 50000, "expected_hedge_version": hedge["version"]},
            SA,
        )
    )
    hedge_after = validate_success(api.get_hedge(hedge["id"], SA))
    assert hedge_after["realized_weight_lb"] == 600, \
        f"first leg must realize 600, got {hedge_after['realized_weight_lb']}"
    assert hedge_after["status"] == "OPEN", \
        f"partially realized hedge must stay OPEN, got {hedge_after['status']}"


def test_void_payout_marks_status_void_without_ledger_move(api):
    """PRD §3.5: "Voiding closes the payout without disbursement; because no cash was
    ever added, there is no ledger movement to reverse, and the ticket stays
    `RELEASED`."

    A voided CASH payout itself reads back as VOID — the compensating terminal — while
    its seller's cash ledger is untouched.

    Design: Difficulty/compensating_invariant/void_payout_leaves_ytd_cash_unchanged
    """
    built = fixtures.create_pending_payout(method="CASH", grade_code="SHRED_STEEL",
                                           category="FERROUS", spot=11, weight_lb=100)
    validate_success(api.void_payout(built["payout"]["id"], PC))
    payout_after = validate_success(api.get_payout(built["payout"]["id"], PC))
    assert payout_after["status"] == "VOID", \
        f"voided payout must read back VOID, got {payout_after['status']}"
    seller = validate_success(api.get_seller(built["seller_id"], WM))
    assert seller["ytd_cash_paid_cents"] == 0, \
        f"ytd_cash_paid_cents must stay 0 after void, got {seller['ytd_cash_paid_cents']}"


def test_clear_theft_report_marks_report_cleared(api):
    """PRD §3.1: "Clearing transitions the report from `OPEN` to `CLEARED`,
    decrements the seller's `open_theft_reports` by 1."
    PRD §3.1: "A report stays `OPEN` until a `ComplianceOfficer` clears it."

    The report row itself moves OPEN->CLEARED — the conserved-count compensation seen
    from the TheftReport side.

    Design: Difficulty/compensating_invariant/clear_theft_report_restores_open_report_count
    """
    publish_price("CAT_CONV", "NON_FERROUS", spot=50000, mill=52000)
    seller = register_seller(legal_name="Clr2 Co", id_type="PASSPORT", id_number="P-16B")
    ticket = open_ticket(seller["id"], gross_weight_lb=50)
    add_line(ticket["id"], "CAT_CONV", 5)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 10}, WM))
    validate_success(api.report_ticket(ticket["id"], {"reason": "serial match"}, WM))
    from test_helpers import validate_paginated
    reports, _ = validate_paginated(
        api.list_theft_reports(CO, params={"seller_id": seller["id"], "status": "OPEN"})
    )
    report_id = reports[0]["id"]
    cleared = validate_success(api.clear_theft_report(report_id, CO))
    assert cleared["status"] == "CLEARED", \
        f"cleared report must read CLEARED, got {cleared['status']}"
    fetched = validate_success(api.get_theft_report(report_id, CO))
    assert fetched["status"] == "CLEARED", \
        f"GET must confirm report CLEARED, got {fetched['status']}"
