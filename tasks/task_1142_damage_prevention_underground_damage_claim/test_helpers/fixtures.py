"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the server is restarted before each test, so nothing carries over).
Setup calls use get_success_data() so failures surface as clear setup errors.

Header threading: entity-backed callers (Excavator / Locator) always use
make_excavator_headers / make_locator_headers with the real entity id; opaque
operator roles use make_*_headers with an explicit operator id where identity
matters (segregation of duties: investigator vs finalizer).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_damage_case_payload,
    create_dispute_payload,
    create_evidence_item_payload,
    create_excavator_payload,
    create_fault_allocation_payload,
    create_cost_line_item_payload,
    create_locate_response_payload,
    create_locate_ticket_payload,
    create_locator_payload,
    create_payment_payload,
    create_regulatory_report_payload,
    create_training_course_payload,
    create_violation_record_payload,
)
from .test_users import (
    make_adjuster_headers,
    make_excavator_headers,
    make_intake_headers,
    make_investigator_headers,
    make_locator_headers,
    make_manager_headers,
)

# Canonical cost pair: LABOR 10x9000 (103500) + MATERIAL 5x3000 (16500)
# -> subtotal 120000 under the PRD §3.5 per-line rules.
STANDARD_COST_LINES = [
    {"category": "LABOR", "description": "crew", "quantity": 10, "unit_cost_cents": 9000},
    {"category": "MATERIAL", "description": "pipe", "quantity": 5, "unit_cost_cents": 3000},
]
STANDARD_SUBTOTAL_CENTS = 120000


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators
# ---------------------------------------------------------------------------
def create_excavator(**overrides) -> dict:
    resp = api_client.create_excavator(create_excavator_payload(**overrides), make_manager_headers())
    return get_success_data(resp)


def create_locator(**overrides) -> dict:
    resp = api_client.create_locator(create_locator_payload(**overrides), make_manager_headers())
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, make_manager_headers())
    return get_success_data(resp)


def create_ticket(excavator_id: str, dig_site_address: str = "1 Test St",
                  work_start_at: str = "2026-06-01T08:00:00Z",
                  work_end_at: str = "2026-06-01T17:00:00Z") -> dict:
    """File a ticket as the owning excavator (ownership-gated endpoint)."""
    payload = create_locate_ticket_payload(
        excavator_id=excavator_id, dig_site_address=dig_site_address,
        work_start_at=work_start_at, work_end_at=work_end_at,
    )
    resp = api_client.create_locate_ticket(payload, make_excavator_headers(excavator_id))
    return get_success_data(resp)


def create_locate_response(ticket_id: str, locator_id: str,
                           response_code: str = "MARKED",
                           marks_completed_at: str = "2026-05-02T07:00:00Z") -> dict:
    """Submit a response as the owning locator (ownership-gated endpoint)."""
    payload = create_locate_response_payload(
        locate_ticket_id=ticket_id, locator_id=locator_id,
        response_code=response_code, marks_completed_at=marks_completed_at,
    )
    resp = api_client.create_locate_response(payload, make_locator_headers(locator_id))
    return get_success_data(resp)


def create_completed_ticket(excavator_id: str, locator_id: str,
                            dig_site_address: str = "1 Test St",
                            work_start_at: str = "2026-05-02T08:00:00Z",
                            work_end_at: str = "2026-05-02T17:00:00Z",
                            marks_completed_at: str = "2026-05-02T07:00:00Z") -> tuple:
    """Ticket + first locate response -> ticket COMPLETED. Returns (ticket, response)."""
    ticket = create_ticket(excavator_id, dig_site_address, work_start_at, work_end_at)
    response = create_locate_response(ticket["id"], locator_id, "MARKED", marks_completed_at)
    return ticket, response


def create_case(excavator_id: str, dig_site_address: str = "1 Test St",
                facility_type: str = "GAS", severity: str = "MAJOR",
                occurred_at: str = "2026-05-02T09:00:00Z",
                locate_ticket_id=None) -> dict:
    payload = create_damage_case_payload(
        excavator_id=excavator_id, dig_site_address=dig_site_address,
        facility_type=facility_type, severity=severity, occurred_at=occurred_at,
    )
    if locate_ticket_id is not None:
        payload["locate_ticket_id"] = locate_ticket_id
    resp = api_client.create_damage_case(payload, make_intake_headers())
    return get_success_data(resp)


def add_evidence(case_id: str, captured_at: str = "2026-05-02T10:00:00Z",
                 evidence_type: str = "PHOTO", description: str = "scene") -> dict:
    payload = create_evidence_item_payload(
        damage_case_id=case_id, evidence_type=evidence_type,
        captured_at=captured_at, description=description,
    )
    resp = api_client.create_evidence_item(payload, make_intake_headers())
    return get_success_data(resp)


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_damage_case(case_id, make_manager_headers()))


def get_excavator(excavator_id: str) -> dict:
    return get_success_data(api_client.get_excavator(excavator_id, make_manager_headers()))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_claim_invoice(invoice_id, make_manager_headers()))


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_fault_allocation(allocation_id, make_manager_headers()))


def list_case_invoices(case_id: str) -> list:
    """All invoices of a case, selected client-side (robust to list filters)."""
    resp = api_client.list_claim_invoices(make_manager_headers(), params={"damage_case_id": case_id})
    data, _meta = validate_paginated(resp)
    return [inv for inv in data if inv.get("damage_case_id") in (None, case_id)]


def get_single_case_invoice(case_id: str) -> dict:
    invoices = list_case_invoices(case_id)
    assert len(invoices) == 1, f"expected exactly 1 invoice for case, got {len(invoices)}"
    return invoices[0]


def get_case_invoice_for_debtor(case_id: str, debtor_id: str) -> dict:
    matches = [inv for inv in list_case_invoices(case_id) if inv.get("debtor_id") == debtor_id]
    assert len(matches) == 1, f"expected exactly 1 invoice for debtor {debtor_id}, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------
def begin_investigation(case_id: str, investigator_id: str = "inv-1") -> dict:
    """Claim the investigation; returns the updated case (with bumped version)."""
    resp = api_client.begin_investigation(case_id, make_investigator_headers(investigator_id))
    return get_success_data(resp)


def create_allocation(case_id: str, expected_damage_case_version: int,
                      root_cause_code: str = "NO_TICKET", shares=None,
                      investigator_id: str = "inv-1") -> dict:
    payload = create_fault_allocation_payload(
        damage_case_id=case_id, root_cause_code=root_cause_code,
        expected_damage_case_version=expected_damage_case_version,
    )
    if shares is not None:
        payload["shares"] = shares
    resp = api_client.create_fault_allocation(payload, make_investigator_headers(investigator_id))
    return get_success_data(resp)


def propose_allocation(allocation_id: str, investigator_id: str = "inv-1") -> dict:
    resp = api_client.propose_fault_allocation(allocation_id, make_investigator_headers(investigator_id))
    return get_success_data(resp)


def finalize_allocation(allocation_id: str, manager_id: str = "mgr-1",
                        override_authority_cap=None) -> dict:
    payload = {}
    if override_authority_cap is not None:
        payload["override_authority_cap"] = override_authority_cap
    resp = api_client.finalize_fault_allocation(allocation_id, payload, make_manager_headers(manager_id))
    return get_success_data(resp)


def add_cost_line(case_id: str, category: str, quantity, unit_cost_cents: int,
                  description: str = "line") -> dict:
    payload = create_cost_line_item_payload(
        damage_case_id=case_id, category=category, description=description,
        quantity=quantity, unit_cost_cents=unit_cost_cents,
    )
    resp = api_client.create_cost_line_item(payload, make_adjuster_headers())
    return get_success_data(resp)


def add_standard_cost_lines(case_id: str) -> list:
    """LABOR 10x9000 + MATERIAL 5x3000 -> case subtotal 120000."""
    return [add_cost_line(case_id, **line) for line in STANDARD_COST_LINES]


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_claim_invoice(invoice_id, make_adjuster_headers()))


def record_payment(payer_type: str, payer_id: str, amount_cents: int,
                   claim_invoice_id=None, as_manager: bool = False) -> dict:
    payload = create_payment_payload(
        payer_type=payer_type, payer_id=payer_id, amount_cents=amount_cents,
    )
    if claim_invoice_id is not None:
        payload["claim_invoice_id"] = claim_invoice_id
    if as_manager:
        headers = make_manager_headers()
    elif payer_type == "EXCAVATOR":
        headers = make_excavator_headers(payer_id)
    else:
        headers = make_locator_headers(payer_id)
    resp = api_client.create_payment(payload, headers)
    return get_success_data(resp)


def create_violation(excavator_id: str, damage_case_id: str) -> dict:
    payload = create_violation_record_payload(
        excavator_id=excavator_id, damage_case_id=damage_case_id,
    )
    resp = api_client.create_violation_record(payload, make_manager_headers())
    return get_success_data(resp)


def create_course(course_code: str = "P101", required_for_status: str = "PROBATION",
                  title: str = "Probation remediation", credit_hours: int = 8) -> dict:
    payload = create_training_course_payload(
        course_code=course_code, title=title,
        required_for_status=required_for_status, credit_hours=credit_hours,
    )
    resp = api_client.create_training_course(payload, make_manager_headers())
    return get_success_data(resp)


def evaluate_program(excavator_id: str) -> dict:
    return get_success_data(api_client.evaluate_program(excavator_id, make_manager_headers()))


def open_invoice_dispute(invoice_id: str, filer_type: str, filer_id: str,
                         reason: str = "AMOUNT", detail: str = "too high") -> dict:
    payload = create_dispute_payload(
        target_type="CLAIM_INVOICE", target_id=invoice_id, reason=reason, detail=detail,
    )
    if filer_type == "EXCAVATOR":
        headers = make_excavator_headers(filer_id)
    else:
        headers = make_locator_headers(filer_id)
    resp = api_client.create_dispute(payload, headers)
    return get_success_data(resp)


def create_incident_report(case_id: str, payload_notes: str = "filing") -> dict:
    payload = create_regulatory_report_payload(
        report_type="INCIDENT", damage_case_id=case_id, payload_notes=payload_notes,
    )
    resp = api_client.create_regulatory_report(payload, make_adjuster_headers())
    return get_success_data(resp)


def file_report(report_id: str) -> dict:
    return get_success_data(api_client.file_regulatory_report(report_id, make_adjuster_headers()))


# ---------------------------------------------------------------------------
# Tier 2/3: composite lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_case_investigating(severity: str = "MAJOR", occurred_at: str = "2026-05-02T09:00:00Z",
                             dig_site_address: str = "1 Test St", with_evidence: bool = True,
                             investigator_id: str = "inv-1", facility_type: str = "GAS",
                             evidence_captured_at: str = "2026-05-02T10:00:00Z") -> dict:
    """Excavator + case (+ one evidence item) + begin-investigation.

    Returns {"excavator", "case", "case_version"} where case_version is the
    case's current version, ready for an OCC allocation create.
    """
    excavator = create_excavator()
    case = create_case(excavator["id"], dig_site_address, facility_type, severity, occurred_at)
    if with_evidence:
        add_evidence(case["id"], captured_at=evidence_captured_at)
    case = begin_investigation(case["id"], investigator_id)
    return {"excavator": excavator, "case": case, "case_version": case["version"]}


def setup_proposed_allocation(root_cause_code: str = "NO_TICKET", shares=None,
                              with_standard_costs: bool = True,
                              severity: str = "MAJOR",
                              occurred_at: str = "2026-05-02T09:00:00Z",
                              dig_site_address: str = "1 Test St",
                              investigator_id: str = "inv-1",
                              excavator=None, locator=None) -> dict:
    """Case (with evidence) INVESTIGATING + allocation + costs + PROPOSED.

    Returns {"excavator", "locator", "case", "allocation"}.
    """
    if excavator is None:
        excavator = create_excavator()
    case = create_case(excavator["id"], dig_site_address, "GAS", severity, occurred_at)
    add_evidence(case["id"])
    case = begin_investigation(case["id"], investigator_id)
    allocation = create_allocation(
        case["id"], case["version"], root_cause_code=root_cause_code,
        shares=shares, investigator_id=investigator_id,
    )
    if with_standard_costs:
        add_standard_cost_lines(case["id"])
    allocation = propose_allocation(allocation["id"], investigator_id)
    return {"excavator": excavator, "locator": locator, "case": case, "allocation": allocation}


def setup_finalized_case(root_cause_code: str = "NO_TICKET", shares=None,
                         severity: str = "MAJOR", occurred_at: str = "2026-05-02T09:00:00Z",
                         dig_site_address: str = "1 Test St",
                         investigator_id: str = "inv-1", manager_id: str = "mgr-1",
                         with_standard_costs: bool = True, excavator=None) -> dict:
    """Full path through FINAL: case + evidence + allocation + costs + propose + finalize.

    Returns {"excavator", "case", "allocation", "invoices"}.
    """
    ctx = setup_proposed_allocation(
        root_cause_code=root_cause_code, shares=shares,
        with_standard_costs=with_standard_costs, severity=severity,
        occurred_at=occurred_at, dig_site_address=dig_site_address,
        investigator_id=investigator_id, excavator=excavator,
    )
    allocation = finalize_allocation(ctx["allocation"]["id"], manager_id)
    case = get_case(ctx["case"]["id"])
    invoices = list_case_invoices(case["id"])
    ctx.update({"allocation": allocation, "case": case, "invoices": invoices})
    return ctx


def setup_issued_invoice_case(**kwargs) -> dict:
    """Finalized case whose single invoice has been ISSUED.

    Returns setup_finalized_case context plus "invoice".
    """
    ctx = setup_finalized_case(**kwargs)
    invoice = get_single_case_invoice(ctx["case"]["id"])
    invoice = issue_invoice(invoice["id"])
    ctx["invoice"] = invoice
    return ctx


def setup_paid_case(**kwargs) -> dict:
    """Finalized case, invoice issued and paid in full (case RECOVERED).

    Returns setup_issued_invoice_case context plus "payment".
    """
    ctx = setup_issued_invoice_case(**kwargs)
    invoice = ctx["invoice"]
    payment = record_payment(
        "EXCAVATOR", ctx["excavator"]["id"], invoice["invoiced_cents"],
        claim_invoice_id=invoice["id"],
    )
    ctx["payment"] = payment
    ctx["invoice"] = get_invoice(invoice["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_disputed_invoice(reason: str = "AMOUNT", detail: str = "too high", **kwargs) -> dict:
    """Finalized case, invoice ISSUED, dispute OPEN on it (filed by the excavator)."""
    ctx = setup_issued_invoice_case(**kwargs)
    dispute = open_invoice_dispute(
        ctx["invoice"]["id"], "EXCAVATOR", ctx["excavator"]["id"], reason=reason, detail=detail,
    )
    ctx["dispute"] = dispute
    return ctx
