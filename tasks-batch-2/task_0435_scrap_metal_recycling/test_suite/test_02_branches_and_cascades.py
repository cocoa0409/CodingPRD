"""State-machine branches and transitive cascades.

Difficulty queue: non_linear_state_machine + transitive_cascade instances.
"""
from test_helpers import fixtures, validate_success
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_weighed_ticket,
    create_released_ticket,
    WM, PC, SA, CO,
)


# ---------------------------------------------------------------------------
# Rule 3 — non_linear_state_machine / ticket_branch_released_vs_reported
# ---------------------------------------------------------------------------
def test_weighed_ticket_release_branch(api):
    """PRD §3.4: "If the `WeighMaster` decides the material is legitimate, the ticket
    is released, moving `WEIGHED → RELEASED`."
    PRD §3.4: "On a successful release the ticket is assigned to the container and
    the container's `loaded_weight_lb` increases by the ticket's `net_weight_lb`."

    The release branch loads a container and leaves the seller ACTIVE.

    Design: Difficulty/non_linear_state_machine/ticket_branch_released_vs_reported
    """
    built = create_weighed_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                                  spot=11, mill=14, weight_lb=100)
    container = stage_container("FERROUS", capacity_lb=5000)
    data = validate_success(
        api.release_ticket(built["ticket"]["id"], {"container_id": container["id"]}, WM)
    )
    assert data["status"] == "RELEASED", f"expected RELEASED, got {data['status']}"
    assert data["container_id"] == container["id"], "ticket must be assigned to the container"
    seller = validate_success(api.get_seller(built["seller_id"], WM))
    assert seller["status"] == "ACTIVE", \
        f"release branch must leave seller ACTIVE, got {seller['status']}"


def test_weighed_ticket_report_branch(api):
    """PRD §3.4: "If instead the `WeighMaster` concludes the material is stolen, the
    ticket is reported, moving `WEIGHED → REPORTED` — a terminal state."
    PRD §3.4: "As a cross-entity cascade it creates a `TheftReport` in `OPEN` status
    for the ticket's `seller_id`, sets that seller's `status` to `FLAGGED`, and
    increments the seller's `open_theft_reports` by 1."

    The report branch (disjoint side effects from release) freezes the seller.

    Design: Difficulty/non_linear_state_machine/ticket_branch_released_vs_reported
    """
    publish_price("CAT_CONV", "NON_FERROUS", spot=50000, mill=52000)
    seller = register_seller(legal_name="Susp Co", id_type="PASSPORT", id_number="P-6")
    ticket = open_ticket(seller["id"], gross_weight_lb=50)
    add_line(ticket["id"], "CAT_CONV", 5)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 10}, WM))
    data = validate_success(
        api.report_ticket(ticket["id"], {"reason": "serial match"}, WM)
    )
    assert data["status"] == "REPORTED", f"expected REPORTED, got {data['status']}"
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["status"] == "FLAGGED", \
        f"report branch must FLAG the seller, got {seller_after['status']}"


# ---------------------------------------------------------------------------
# Rule 3 — non_linear_state_machine / payout_branch_settled_vs_void
# ---------------------------------------------------------------------------
def test_payout_void_branch_leaves_ticket_released(api):
    """PRD §3.5: "A `PayoutClerk` may instead void a `PENDING` payout, moving it
    `PENDING → VOID`. Voiding closes the payout without disbursement; because no
    cash was ever added, there is no ledger movement to reverse, and the ticket
    stays `RELEASED`."

    Design: Difficulty/non_linear_state_machine/payout_branch_settled_vs_void
    """
    built = fixtures.create_pending_payout(method="CASH", grade_code="SHRED_STEEL",
                                           category="FERROUS", spot=11, weight_lb=100)
    data = validate_success(api.void_payout(built["payout"]["id"], PC))
    assert data["status"] == "VOID", f"expected VOID, got {data['status']}"
    ticket = validate_success(api.get_ticket(built["ticket"]["id"], WM))
    assert ticket["status"] == "RELEASED", \
        f"voided payout must leave ticket RELEASED, got {ticket['status']}"
    seller = validate_success(api.get_seller(built["seller_id"], WM))
    assert seller["ytd_cash_paid_cents"] == 0, \
        f"void must not move the cash ledger, got {seller['ytd_cash_paid_cents']}"


def test_payout_settle_branch_pays_ticket_and_moves_ledger(api):
    """PRD §3.5: "A successful cash settlement thus performs a coordinated ledger
    sync — incrementing `ytd_cash_paid_cents`, recomputing `requires_1099`, and
    setting `form_1099_issued` — and as its final cross-entity effect transitions
    the underlying ticket `RELEASED → PAID`, the ticket's terminal paid state."

    The settle branch (disjoint from void) disburses, advances the cash ledger, and
    PAIDs the ticket.

    Design: Difficulty/non_linear_state_machine/payout_branch_settled_vs_void
    """
    built = fixtures.create_pending_payout(method="CASH", grade_code="SHRED_STEEL",
                                           category="FERROUS", spot=11, weight_lb=100)
    data = validate_success(api.settle_payout(built["payout"]["id"], PC))
    assert data["status"] == "SETTLED", f"expected SETTLED, got {data['status']}"
    ticket = validate_success(api.get_ticket(built["ticket"]["id"], WM))
    assert ticket["status"] == "PAID", \
        f"settled payout must PAY the ticket, got {ticket['status']}"
    seller = validate_success(api.get_seller(built["seller_id"], WM))
    assert seller["ytd_cash_paid_cents"] == 1100, \
        f"settle must move the cash ledger to 1100, got {seller['ytd_cash_paid_cents']}"


# ---------------------------------------------------------------------------
# Rule 4 — transitive_cascade / settle_cascade_shipment_hedge_close_depth3
#   (also owns Corner stub: rbac/settlementaccountant_settle_excluded)
# ---------------------------------------------------------------------------
def test_settle_cascade_realizes_and_closes_hedge(api):
    """PRD §3.7: "The hedge's `realized_weight_lb` then increases by the realized
    pounds, its `realized_pnl_cents` increases by the leg's profit and loss, and
    the cascade increments the hedge's `version`. If the realization brings
    `realized_weight_lb` to at least `hedged_weight_lb`, the hedge auto-closes,
    moving `OPEN → CLOSED`."
    PRD §3.7: "The shipment moves `SHIPPED → SETTLED`."

    Depth-3 cascade: settle -> realize hedge weight 1300 -> hedge auto-closes.

    Design: Difficulty/transitive_cascade/settle_cascade_shipment_hedge_close_depth3
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    data = validate_success(
        api.settle_mill_shipment(
            built["shipment"]["id"],
            {"final_settlement_cents": 100000,
             "expected_hedge_version": built["hedge_version"]},
            SA,
        )
    )
    assert data["status"] == "SETTLED", f"expected shipment SETTLED, got {data['status']}"
    hedge_after = validate_success(api.get_hedge(built["hedge"]["id"], SA))
    assert hedge_after["realized_weight_lb"] == 1300, \
        f"expected realized_weight_lb 1300, got {hedge_after['realized_weight_lb']}"
    assert hedge_after["status"] == "CLOSED", \
        f"hedge must auto-close at full realization, got {hedge_after['status']}"


def test_settle_cascade_settlement_accountant_authorized(api):
    """PRD §3.7: "A `SettlementAccountant` settles a `SHIPPED` shipment by supplying
    the `final_settlement_cents` the mill actually remitted, which must be at least
    0. The shipment moves `SHIPPED → SETTLED`."

    Exercises the SettlementAccountant-exclusive settle op through the depth-3
    cascade (owns corner stub rbac/settlementaccountant_settle_excluded).

    Design: Difficulty/transitive_cascade/settle_cascade_shipment_hedge_close_depth3
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    data = validate_success(
        api.settle_mill_shipment(
            built["shipment"]["id"],
            {"final_settlement_cents": 100000,
             "expected_hedge_version": built["hedge_version"]},
            SA,
        )
    )
    assert data["status"] == "SETTLED", \
        f"SettlementAccountant settle must succeed, got {data['status']}"


# ---------------------------------------------------------------------------
# Rule 4 — transitive_cascade / report_cascade_ticket_seller_freeze_depth2
#   (also owns Corner stub: cross_cutting/report_freezes_seller_derived_count)
# ---------------------------------------------------------------------------
def test_report_cascade_freezes_seller_and_increments_count(api):
    """PRD §3.4: "As a cross-entity cascade it creates a `TheftReport` in `OPEN`
    status for the ticket's `seller_id`, sets that seller's `status` to `FLAGGED`,
    and increments the seller's `open_theft_reports` by 1."

    Depth-2 cascade: ticket WEIGHED->REPORTED creates the OPEN report which freezes
    the seller (FLAGGED, open_theft_reports=1).

    Design: Difficulty/transitive_cascade/report_cascade_ticket_seller_freeze_depth2
    """
    publish_price("CAT_CONV", "NON_FERROUS", spot=50000, mill=52000)
    seller = register_seller(legal_name="Susp Co", id_type="PASSPORT", id_number="P-6")
    ticket = open_ticket(seller["id"], gross_weight_lb=50)
    add_line(ticket["id"], "CAT_CONV", 5)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 10}, WM))
    data = validate_success(
        api.report_ticket(ticket["id"], {"reason": "serial match on stolen catalytic converter"}, WM)
    )
    assert data["status"] == "REPORTED", f"expected REPORTED, got {data['status']}"
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["status"] == "FLAGGED", \
        f"expected seller FLAGGED, got {seller_after['status']}"
    assert seller_after["open_theft_reports"] == 1, \
        f"expected open_theft_reports 1, got {seller_after['open_theft_reports']}"


def test_report_cascade_freeze_caused_by_report_row(api):
    """PRD §3.1: "`FLAGGED` means there is at least one open theft report against the
    seller; a flagged seller cannot have a ticket released or a payout settled."
    PRD §3.1: "The `open_theft_reports` field is the live count of theft reports
    against the seller that remain in `OPEN` status."

    The created OPEN TheftReport row is what holds the seller FLAGGED — verified by
    reading the report list for the seller after the cascade.

    Design: Difficulty/transitive_cascade/report_cascade_ticket_seller_freeze_depth2
    """
    publish_price("CAT_CONV", "NON_FERROUS", spot=50000, mill=52000)
    seller = register_seller(legal_name="Susp Co", id_type="PASSPORT", id_number="P-6")
    ticket = open_ticket(seller["id"], gross_weight_lb=50)
    add_line(ticket["id"], "CAT_CONV", 5)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 10}, WM))
    validate_success(api.report_ticket(ticket["id"], {"reason": "serial match"}, WM))
    reports, meta = _list(api.list_theft_reports(CO, params={"seller_id": seller["id"], "status": "OPEN"}))
    assert meta["total_count"] >= 1, "an OPEN theft report must exist for the seller"
    assert any(r["seller_id"] == seller["id"] and r["status"] == "OPEN" for r in reports), \
        "the OPEN report freezing the seller must reference the seller"


def _list(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)
