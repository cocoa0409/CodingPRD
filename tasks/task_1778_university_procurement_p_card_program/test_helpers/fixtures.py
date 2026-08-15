"""Composite setup helpers (multi-step preconditions built from PRD endpoints).

Every helper builds state from scratch (the server is restarted between tests)
and uses get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_contract_payload,
    create_department_payload,
    create_elevation_payload,
    create_grant_payload,
    create_invoice_payload,
    create_pcard_payload,
    create_quote_payload,
    create_requisition_payload,
    create_surplus_asset_payload,
    create_transaction_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_cardholder_headers, make_requester_headers

ADMIN = TEST_USERS["admin_headers"]
BUYER = TEST_USERS["buyer_headers"]
DIRECTOR = TEST_USERS["director_headers"]
CONTRACT_OFFICER = TEST_USERS["contract_officer_headers"]
GRANT_OFFICER = TEST_USERS["grant_officer_headers"]
AP_CLERK = TEST_USERS["ap_clerk_headers"]
RECEIVING = TEST_USERS["receiving_clerk_headers"]
DEPT_APPROVER = TEST_USERS["department_approver_headers"]
SURPLUS_MANAGER = TEST_USERS["surplus_manager_headers"]

# Chain step code -> headers of the role that decides it (PRD §3.3).
STEP_ROLE_HEADERS = {
    "DEPARTMENT": DEPT_APPROVER,
    "GRANT_COMPLIANCE": GRANT_OFFICER,
    "SOLE_SOURCE": DIRECTOR,
    "PURCHASING": BUYER,
    "DIRECTOR": DIRECTOR,
    "CONTRACT_REVIEW": CONTRACT_OFFICER,
}


# --- Clock -------------------------------------------------------------------

def set_clock(to_iso8601: str):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


# --- Tier 1: single-resource creation ----------------------------------------

def create_department(**overrides) -> dict:
    return get_success_data(
        api_client.create_department(create_department_payload(**overrides), ADMIN)
    )


def create_vendor(**overrides) -> dict:
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(**overrides), BUYER)
    )


def create_grant(**overrides) -> dict:
    return get_success_data(
        api_client.create_grant(create_grant_payload(**overrides), GRANT_OFFICER)
    )


def create_pcard(**overrides) -> dict:
    return get_success_data(
        api_client.create_pcard(create_pcard_payload(**overrides), ADMIN)
    )


def create_surplus_asset(**overrides) -> dict:
    return get_success_data(
        api_client.create_surplus_asset(
            create_surplus_asset_payload(**overrides), SURPLUS_MANAGER
        )
    )


# --- Tier 1b: contract lifecycle ---------------------------------------------

def create_contract_draft(vendor_id, **overrides) -> dict:
    payload = create_contract_payload(vendor_id=vendor_id, **overrides)
    return get_success_data(api_client.create_contract(payload, CONTRACT_OFFICER))


def create_executed_contract(vendor_id=None, **overrides) -> dict:
    """DRAFT -> UNDER_REVIEW -> REVIEW_APPROVED -> EXECUTED. Returns contract."""
    vendor = vendor_id or create_vendor()["id"]
    contract = create_contract_draft(vendor, **overrides)
    cid = contract["id"]
    get_success_data(api_client.submit_contract_review(cid, CONTRACT_OFFICER))
    get_success_data(api_client.approve_contract_review(cid, CONTRACT_OFFICER))
    return get_success_data(api_client.execute_contract(cid, DIRECTOR))


# --- Tier 2: requisition pipeline --------------------------------------------

def create_requisition_draft(department_id=None, requester_id="req-user-1",
                             **overrides) -> dict:
    dept = department_id or create_department()["id"]
    payload = create_requisition_payload(
        department_id=dept, requester_id=requester_id, **overrides
    )
    return get_success_data(
        api_client.create_requisition(payload, make_requester_headers(requester_id))
    )


def submit_requisition_ok(requisition_id: str, requester_id="req-user-1") -> dict:
    return get_success_data(
        api_client.submit_requisition(
            requisition_id, make_requester_headers(requester_id)
        )
    )


def create_and_submit_requisition(department_id=None, vendor_id=None,
                                  requester_id="req-user-1", **overrides) -> dict:
    """Draft + submit. Returns the submitted requisition (chain pinned)."""
    req = create_requisition_draft(
        department_id=department_id, vendor_id=vendor_id,
        requester_id=requester_id, **overrides
    )
    return submit_requisition_ok(req["id"], requester_id)


def walk_approval_chain(requisition_id: str) -> dict:
    """Approve every step of the pinned chain with the step's owning role.

    Reads the live requisition, then approves required_chain[0..n] in order.
    Returns the final requisition (status APPROVED) data payload.
    """
    req = get_success_data(api_client.get_requisition(requisition_id, ADMIN))
    chain = req["required_chain"]
    data = req
    for step in chain:
        data = get_success_data(
            api_client.approve_requisition_step(
                requisition_id, {}, STEP_ROLE_HEADERS[step]
            )
        )
    return data


def create_approved_requisition(department_id=None, vendor_id=None,
                                requester_id="req-user-1", **overrides) -> dict:
    """Draft + submit + full chain walk. Returns APPROVED requisition."""
    req = create_and_submit_requisition(
        department_id=department_id, vendor_id=vendor_id,
        requester_id=requester_id, **overrides
    )
    return walk_approval_chain(req["id"])


# --- Tier 3: purchase orders / receipts / invoices ---------------------------

def issue_po_ok(requisition_id: str) -> dict:
    return get_success_data(api_client.issue_po(requisition_id, BUYER))


def create_po(lines=None, department_id=None, vendor_id=None,
              requester_id="req-user-1", **req_overrides) -> dict:
    """Approved requisition + issued PO. Returns the PurchaseOrder."""
    req = create_approved_requisition(
        department_id=department_id, vendor_id=vendor_id,
        requester_id=requester_id, lines=lines, **req_overrides
    )
    return issue_po_ok(req["id"])


def post_receipt(po_id: str, lines) -> dict:
    return get_success_data(
        api_client.create_receipt(po_id, {"lines": lines}, RECEIVING)
    )


def post_invoice(po_id: str, lines, invoice_number=None) -> dict:
    payload = create_invoice_payload(lines=lines)
    if invoice_number:
        payload["invoice_number"] = invoice_number
    return get_success_data(api_client.create_invoice(po_id, payload, AP_CLERK))


def create_po_fully_received(lines=None, **req_overrides) -> dict:
    """PO with every line fully received. Returns (po, receipt)."""
    po = create_po(lines=lines, **req_overrides)
    receipt_lines = [
        {"line_no": i, "quantity": line["quantity"]}
        for i, line in enumerate(po["lines"])
    ]
    receipt = post_receipt(po["id"], receipt_lines)
    return po, receipt


def create_payable_invoice(lines=None, invoice_lines=None, **req_overrides):
    """PO fully received + exact-price invoice (lands PAYABLE).
    Returns (po, receipt, invoice)."""
    po, receipt = create_po_fully_received(lines=lines, **req_overrides)
    if invoice_lines is None:
        invoice_lines = [
            {
                "line_no": i,
                "quantity": line["quantity"],
                "unit_price_cents": line["unit_price_cents"],
            }
            for i, line in enumerate(po["lines"])
        ]
    invoice = post_invoice(po["id"], invoice_lines)
    return po, receipt, invoice


# --- Tier 4: solicitations ----------------------------------------------------

def create_competitive_requisition(total_cents=3000000, department_id=None,
                                   vendor_id=None, requester_id="req-user-1",
                                   cost_category="SERVICES") -> dict:
    """Requisition >= the competitive threshold, submitted, DEPARTMENT-approved.

    Returns the SUBMITTED requisition sitting at its PURCHASING step; a
    solicitation may be opened on it (PRD §3.4 creation preconditions).
    """
    dept = department_id or create_department()["id"]
    vendor = vendor_id or create_vendor()["id"]
    req = create_and_submit_requisition(
        department_id=dept, vendor_id=vendor, requester_id=requester_id,
        lines=[{
            "commodity_code": "COMP",
            "description": "competitive work",
            "quantity": 1,
            "unit_price_cents": total_cents,
            "cost_category": cost_category,
        }],
    )
    # First step is always DEPARTMENT.
    get_success_data(api_client.approve_requisition_step(req["id"], {}, DEPT_APPROVER))
    return get_success_data(api_client.get_requisition(req["id"], ADMIN))


def create_open_solicitation(requisition_id: str, deadline="2026-08-08T00:00:00Z",
                             min_quotes=None) -> dict:
    payload = {"response_deadline": deadline}
    if min_quotes is not None:
        payload["min_quotes"] = min_quotes
    return get_success_data(
        api_client.create_solicitation(requisition_id, payload, BUYER)
    )


def submit_quote(solicitation_id: str, vendor_id: str, price_cents: int) -> dict:
    return get_success_data(
        api_client.create_quote(
            solicitation_id, create_quote_payload(
                vendor_id=vendor_id, price_cents=price_cents
            ),
            BUYER,
        )
    )


# --- Tier 4b: p-card helpers --------------------------------------------------

def post_debit(pcard_id: str, amount_cents: int, mcc_code="5942",
               merchant="Merchant") -> dict:
    """Post a DEBIT as the card's own holder (identity == PCard id)."""
    return get_success_data(
        api_client.create_pcard_transaction(
            pcard_id,
            create_transaction_payload(
                amount_cents=amount_cents, entry_type="DEBIT",
                merchant_name=merchant, mcc_code=mcc_code,
            ),
            make_cardholder_headers(pcard_id),
        )
    )


def reconcile_txn(transaction_id: str, pcard_id: str, receipt_reference="rcpt-1",
                  allocation_type="GENERAL", **extra) -> dict:
    payload = {
        "receipt_reference": receipt_reference,
        "allocation_type": allocation_type,
    }
    payload.update(extra)
    return get_success_data(
        api_client.reconcile_transaction(
            transaction_id, payload, make_cardholder_headers(pcard_id)
        )
    )


def create_pcard_with_debit(amount_cents=40000, department_id=None,
                            **card_overrides):
    """Card + one POSTED debit. Returns (card, transaction)."""
    dept = department_id or create_department()["id"]
    card = create_pcard(department_id=dept, **card_overrides)
    txn = post_debit(card["id"], amount_cents)
    return card, txn


# --- Tier 5: surplus helpers --------------------------------------------------

def create_declared_asset(department_id=None, declared_clock=None, **overrides):
    """Asset declared at the current (or supplied) clock. Returns asset."""
    if declared_clock:
        set_clock(declared_clock)
    dept = department_id or create_department()["id"]
    return create_surplus_asset(department_id=dept, **overrides)


def create_listed_asset(declared_clock="2026-08-01T00:00:00Z",
                        list_clock="2026-08-12T00:00:00Z",
                        department_id=None, **overrides) -> dict:
    """Asset declared, clock advanced past the redistribution window, LISTED."""
    asset = create_declared_asset(
        department_id=department_id, declared_clock=declared_clock, **overrides
    )
    set_clock(list_clock)
    return get_success_data(
        api_client.list_surplus_asset_for_sale(asset["id"], SURPLUS_MANAGER)
    )


# --- Grant ledger read ---------------------------------------------------------

def read_ledger(grant_id: str) -> dict:
    return get_success_data(api_client.get_grant_budget_ledger(grant_id, ADMIN))
