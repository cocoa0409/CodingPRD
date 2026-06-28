"""Cyclic state machines: the visit dispute -> rework -> re-complete reissue
loop, and the repair diagnosed -> awaiting-parts -> diagnosed back-edge.
"""
from test_helpers import (
    validate_success,
    make_field_tech_headers,
    make_customer_owner_headers,
    create_completed_visit,
    create_diagnosed_repair,
)


def test_visit_dispute_rework_reissues_a_fresh_invoice(api):
    """PRD §3.3: "A disputed visit is reworked by a FieldTech, who must again be
    the assigned tech (the same ERR_TECH_MISMATCH guard applies), moving it
    DISPUTED → IN_PROGRESS; rework clears the visit's invoice_id and resets
    total_cents to zero, so that the next completion issues a fresh invoice."
    PRD §3.3: "Disputing voids the visit's invoice — the Invoice.status becomes
    VOID and the contract's account_balance_cents is recomputed to drop that
    invoice's contribution."

    Design: Difficulty/non_linear_state_machine/visit_dispute_rework_reissue_cycle
    """
    base = create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                                  tech_user_id="tech-1", labor_minutes=30,
                                  scheduled_start="2026-02-06T09:00:00Z",
                                  scheduled_end="2026-02-06T10:00:00Z")
    visit_id = base["visit"]["id"]
    first_invoice = base["visit"]["invoice_id"]
    assert first_invoice is not None

    owner_headers = make_customer_owner_headers("owner-1")
    tech_headers = make_field_tech_headers("tech-1")

    validate_success(api.dispute_visit(visit_id, owner_headers))

    reworked = validate_success(api.rework_visit(visit_id, tech_headers))
    assert reworked["status"] == "IN_PROGRESS", (
        f"Expected IN_PROGRESS after rework, got {reworked['status']}")
    assert reworked["invoice_id"] is None, (
        f"Expected invoice_id cleared after rework, got {reworked['invoice_id']}")

    recompleted = validate_success(
        api.complete_visit(visit_id, {"labor_minutes": 30}, tech_headers))
    assert recompleted["status"] == "COMPLETED", (
        f"Expected COMPLETED after second complete, got {recompleted['status']}")
    second_invoice = recompleted["invoice_id"]
    assert second_invoice is not None
    assert second_invoice != first_invoice, (
        "Second completion must issue a fresh invoice distinct from the first")


def test_dispute_voids_invoice_then_rework_resets_total(api):
    """PRD §3.3: "Disputing voids the visit's invoice — the Invoice.status becomes
    VOID and the contract's account_balance_cents is recomputed to drop that
    invoice's contribution."
    PRD §3.3: "rework clears the visit's invoice_id and resets total_cents to
    zero, so that the next completion issues a fresh invoice."

    Design: Difficulty/non_linear_state_machine/visit_dispute_rework_reissue_cycle
    """
    from test_helpers import TEST_USERS
    am = TEST_USERS["account_manager_headers"]

    base = create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                                  tech_user_id="tech-1", labor_minutes=30,
                                  scheduled_start="2026-02-16T09:00:00Z",
                                  scheduled_end="2026-02-16T10:00:00Z")
    visit_id = base["visit"]["id"]
    invoice_id = base["visit"]["invoice_id"]
    owner_headers = make_customer_owner_headers("owner-1")
    tech_headers = make_field_tech_headers("tech-1")

    validate_success(api.dispute_visit(visit_id, owner_headers))
    invoice = validate_success(api.get_invoice(invoice_id, am))
    assert invoice["status"] == "VOID", (
        f"Expected invoice VOID after dispute, got {invoice['status']}")

    reworked = validate_success(api.rework_visit(visit_id, tech_headers))
    assert reworked["total_cents"] == 0, (
        f"Expected total_cents reset to 0 after rework, got {reworked['total_cents']}")


def test_repair_parts_arrived_returns_to_diagnosed_back_edge(api):
    """PRD §3.7: "From DIAGNOSED, if parts_needed is true on the repair, the tech
    may order parts, moving it DIAGNOSED → AWAITING_PARTS".
    PRD §3.7: "When parts arrive, the tech moves it AWAITING_PARTS → DIAGNOSED,
    which forms the parts-backorder cycle and may loop if re-diagnosis turns up
    further parts."

    Design: Difficulty/non_linear_state_machine/repair_awaiting_parts_rediagnose_cycle
    """
    base = create_diagnosed_repair(tech_user_id="tech-1", device_kind="FILTER",
                                   parts_needed=True)
    repair_id = base["repair"]["id"]
    tech_headers = make_field_tech_headers("tech-1")

    awaiting = validate_success(api.order_parts_repair(repair_id, tech_headers))
    assert awaiting["status"] == "AWAITING_PARTS", (
        f"Expected AWAITING_PARTS, got {awaiting['status']}")

    back = validate_success(api.parts_arrived_repair(repair_id, tech_headers))
    assert back["status"] == "DIAGNOSED", (
        f"Expected DIAGNOSED after parts-arrived back-edge, got {back['status']}")


def test_repair_can_loop_order_parts_again_after_back_edge(api):
    """PRD §3.7: "From DIAGNOSED, if parts_needed is true on the repair, the tech
    may order parts, moving it DIAGNOSED → AWAITING_PARTS".
    PRD §3.7: "When parts arrive, the tech moves it AWAITING_PARTS → DIAGNOSED,
    which forms the parts-backorder cycle and may loop if re-diagnosis turns up
    further parts."

    After one DIAGNOSED -> AWAITING_PARTS -> DIAGNOSED cycle, ordering parts again
    is still a valid transition (the back-edge truly returned to DIAGNOSED).

    Design: Difficulty/non_linear_state_machine/repair_awaiting_parts_rediagnose_cycle
    """
    base = create_diagnosed_repair(tech_user_id="tech-1", device_kind="FILTER",
                                   parts_needed=True)
    repair_id = base["repair"]["id"]
    tech_headers = make_field_tech_headers("tech-1")

    validate_success(api.order_parts_repair(repair_id, tech_headers))
    validate_success(api.parts_arrived_repair(repair_id, tech_headers))
    # Second loop: order parts again from the re-reached DIAGNOSED state.
    second = validate_success(api.order_parts_repair(repair_id, tech_headers))
    assert second["status"] == "AWAITING_PARTS", (
        f"Expected AWAITING_PARTS on the second loop, got {second['status']}")
