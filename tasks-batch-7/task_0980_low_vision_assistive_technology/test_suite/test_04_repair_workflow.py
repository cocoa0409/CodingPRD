"""Repair tickets: QA rework cycle, repair-loaner cascade, terminal lockdown,
loan gating on QA_PASS, and reverse lookups."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_payload, create_referral_payload, create_evaluation_payload,
    create_device_model_payload, create_device_unit_payload, create_device_order_payload,
    create_repair_ticket_payload,
    create_client_with_accepted_referral, create_finalized_evaluation,
    create_device_model, create_device_unit, place_and_allocate_order,
    create_repair_ticket, advance_ticket, setup_diagnosed_ticket,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
TECH = TEST_USERS["repair_technician_headers"]


def _setup_repair_ticket(api, serial="SN-R1"):
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no=serial, condition="NEW"), ADMIN))
    t = get_success_data(api.create_repair_ticket(create_repair_ticket_payload(
        u["id"], issue_description="flickering backlight"), TECH))
    return m, u, t


def test_repair_qa_fail_loops_back_and_counts_rework(api):
    """PRD §3.9: "From `QA_CHECK`, `QA_FAIL` loops back `QA_CHECK → IN_REPAIR`
    and increments `rework_count` by 1 each time".

    Design: Difficulty/non_linear_state_machine/nsm_repair_qa_rework_cycle
    """
    m, u, t = _setup_repair_ticket(api)
    advance_ticket(t["id"], "DIAGNOSE")
    advance_ticket(t["id"], "START_REPAIR", needs_loaner=False)
    advance_ticket(t["id"], "SUBMIT_QA")
    failed = get_success_data(api.advance_repair_ticket(t["id"], {"action": "QA_FAIL"}, TECH))
    assert failed["rework_count"] == 1, f"exactly one QA_FAIL rework loop, got {failed['rework_count']}"
    assert failed["status"] == "IN_REPAIR", "cycle-back leg returns to IN_REPAIR"


def test_repair_qa_pass_resolves_and_restock_unit(api):
    """PRD §3.9: "`QA_PASS` moves `QA_CHECK → RESOLVED`".
    PRD §3.9: "A successful QA pass returns the repaired unit `IN_REPAIR →
    IN_STOCK` and recomputes the model counters."

    Design: Difficulty/non_linear_state_machine/nsm_repair_qa_rework_cycle
    """
    m, u, t = _setup_repair_ticket(api)
    advance_ticket(t["id"], "DIAGNOSE")
    advance_ticket(t["id"], "START_REPAIR", needs_loaner=False)
    advance_ticket(t["id"], "SUBMIT_QA")
    advance_ticket(t["id"], "QA_FAIL")
    advance_ticket(t["id"], "SUBMIT_QA")
    resolved = get_success_data(api.advance_repair_ticket(t["id"], {"action": "QA_PASS"}, TECH))
    assert resolved["status"] == "RESOLVED"
    unit = get_success_data(api.get_device_unit(u["id"], TECH))
    assert unit["status"] == "IN_STOCK", "unit returned to stock on QA_PASS"


def _setup_repair_loaner_scenario(api):
    """CCTV model with broken NEW unit SN-BRK and LOANER unit SN-LNR; ticket
    DIAGNOSED on the broken unit."""
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    ub = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-BRK", condition="NEW"), ADMIN))
    ul = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-LNR", condition="LOANER"), ADMIN))
    t = get_success_data(api.create_repair_ticket(create_repair_ticket_payload(
        ub["id"], issue_description="no power"), TECH))
    advance_ticket(t["id"], "DIAGNOSE")
    return m, ub, ul, t


def test_repair_start_with_loaner_creates_loan(api):
    """PRD §3.9: "Link 1 creates a **LoanAgreement** for the repair:
    `repair_ticket_id` set, `loaned_at` now, `due_at` exactly 30 days out, status
    `ACTIVE`, and the ticket's `loan_agreement_id` filled in."

    Design: Difficulty/transitive_cascade/tc_repair_loaner_cascade
    """
    m, ub, ul, t = _setup_repair_loaner_scenario(api)
    ticket = get_success_data(api.advance_repair_ticket(
        t["id"], {"action": "START_REPAIR", "needs_loaner": True}, TECH))
    loan_id = ticket["loan_agreement_id"]
    assert loan_id, "advance created the loan"
    loan = get_success_data(api.get_loan_agreement(loan_id, TECH))
    assert loan["repair_ticket_id"] == t["id"]
    assert loan["status"] == "ACTIVE"
    assert loan["device_unit_id"] == ul["id"]


def test_repair_start_with_loaner_moves_unit_and_recomputes_counts(api):
    """PRD §3.9: "Link 3 moves the chosen loaner `IN_STOCK → ON_LOAN` and
    recomputes the model's `in_stock_count`."
    PRD §3.9: "the ticket's own unit moves to `IN_REPAIR` from either `DEPLOYED`
    or `IN_STOCK` (model counters recomputing when it left stock)".

    Design: Difficulty/transitive_cascade/tc_repair_loaner_cascade
    """
    m, ub, ul, t = _setup_repair_loaner_scenario(api)
    get_success_data(api.advance_repair_ticket(
        t["id"], {"action": "START_REPAIR", "needs_loaner": True}, TECH))
    loaner = get_success_data(api.get_device_unit(ul["id"], TECH))
    assert loaner["status"] == "ON_LOAN"
    model = get_success_data(api.get_device_model(m["id"], TECH))
    assert model["in_stock_count"] == 0, (
        f"broken unit IN_REPAIR + loaner ON_LOAN leaves 0 in stock, got {model['in_stock_count']}")
    assert model["total_count"] == 2


def test_resolved_ticket_rejects_further_advance(api):
    """PRD §3.9: "`RESOLVED` is terminal."
    PRD §2.7: "the target entity is in a state from which the requested
    transition exists; terminal states reject everything (`ERR_INVALID_STATE`,
    or `ERR_PLAN_SUSPENDED` when scheduling onto a suspended or completed plan)".

    Design: Corner/state_machines/sm_repair_terminal_resolved_lockdown
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-RL", condition="NEW"), ADMIN))
    t = get_success_data(api.create_repair_ticket(create_repair_ticket_payload(
        u["id"], issue_description="scratched lens"), TECH))
    advance_ticket(t["id"], "DIAGNOSE")
    advance_ticket(t["id"], "START_REPAIR", needs_loaner=False)
    advance_ticket(t["id"], "SUBMIT_QA")
    advance_ticket(t["id"], "QA_PASS")
    resp = api.advance_repair_ticket(t["id"], {"action": "DIAGNOSE"}, TECH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_ticket_in_qa_with_active_loan(api):
    """PURCHASE order allocated; repair on the deployed unit with a loaner loan
    outstanding; ticket in QA_CHECK."""
    c, r = create_client_with_accepted_referral()
    ev = create_finalized_evaluation(c["id"], r["id"], recommended_category="CCTV")
    m = create_device_model(name="CCTV Pro 24", category="CCTV", list_price_cents=100000)
    ub = create_device_unit(m["id"], serial_no="SN-QA1", condition="NEW")
    create_device_unit(m["id"], serial_no="SN-QA2", condition="LOANER")
    order = place_and_allocate_order(c["id"], ev["id"], m["id"], unit_id=ub["id"])
    t = create_repair_ticket(ub["id"], issue_description="dead pixels")
    advance_ticket(t["id"], "DIAGNOSE")
    ticket = get_success_data(api.advance_repair_ticket(
        t["id"], {"action": "START_REPAIR", "needs_loaner": True}, TECH))
    loan_id = ticket["loan_agreement_id"]
    advance_ticket(t["id"], "SUBMIT_QA")
    return t["id"], loan_id


def test_qa_pass_blocked_while_loan_active(api):
    """PRD §3.9: "passing QA with a loan still `ACTIVE` or `OVERDUE` is rejected
    with `ERR_LOAN_STILL_ACTIVE` (HTTP 409)."

    Design: Corner/validations/val_loan_still_active_blocks_qa_pass
    """
    ticket_id, loan_id = _setup_ticket_in_qa_with_active_loan(api)
    resp = api.advance_repair_ticket(ticket_id, {"action": "QA_PASS"}, TECH)
    validate_error(resp, ApiErrorId.ERR_LOAN_STILL_ACTIVE)


def test_qa_pass_succeeds_after_loan_returned(api):
    """PRD §3.9: "`QA_PASS` moves `QA_CHECK → RESOLVED` — but only when the
    linked loan agreement, if one exists, has already reached `RETURNED`".

    Design: Corner/validations/val_loan_still_active_blocks_qa_pass
    """
    ticket_id, loan_id = _setup_ticket_in_qa_with_active_loan(api)
    get_success_data(api.return_loan_agreement(loan_id, TECH))
    resolved = get_success_data(api.advance_repair_ticket(ticket_id, {"action": "QA_PASS"}, TECH))
    assert resolved["status"] == "RESOLVED"


def test_loan_repair_tickets_reverse_lookup(api):
    """PRD §3.9: "A loan's linked tickets are listable through the loan's
    repair-ticket collection".

    Design: Corner/endpoints/ep_fk_reverse_repair_tickets_by_loan
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    ub = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-FK1", condition="NEW"), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-FK2", condition="LOANER"), ADMIN))
    t = get_success_data(api.create_repair_ticket(create_repair_ticket_payload(
        ub["id"], issue_description="no image"), TECH))
    advance_ticket(t["id"], "DIAGNOSE")
    ticket = get_success_data(api.advance_repair_ticket(
        t["id"], {"action": "START_REPAIR", "needs_loaner": True}, TECH))
    loan_id = ticket["loan_agreement_id"]
    tickets = get_success_data(api.list_loan_repair_tickets(loan_id, TECH))
    assert isinstance(tickets, list) and len(tickets) == 1
    assert tickets[0]["id"] == t["id"]


def test_loan_return_allowed_for_technician_and_specialist(api):
    """PRD §3.5: "Return — performed by a `RepairTechnician` or a
    `VisionSpecialist` — moves the agreement from `ACTIVE` or `OVERDUE` to
    `RETURNED`".

    Design: Corner/rbac/rbac_loan_return_shared_by_technician_and_specialist
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    ub1 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-SH1", condition="NEW"), ADMIN))
    ub2 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-SH2", condition="NEW"), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-SH3", condition="LOANER"), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-SH4", condition="LOANER"), ADMIN))
    loans = []
    for ub, issue in ((ub1, "issue one"), (ub2, "issue two")):
        t = get_success_data(api.create_repair_ticket(create_repair_ticket_payload(
            ub["id"], issue_description=issue), TECH))
        advance_ticket(t["id"], "DIAGNOSE")
        ticket = get_success_data(api.advance_repair_ticket(
            t["id"], {"action": "START_REPAIR", "needs_loaner": True}, TECH))
        loans.append(ticket["loan_agreement_id"])
    r1 = get_success_data(api.return_loan_agreement(loans[0], TECH))
    r2 = get_success_data(api.return_loan_agreement(loans[1], SPECIALIST))
    assert r1["status"] == "RETURNED"
    assert r2["status"] == "RETURNED"
