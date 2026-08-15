"""Composite setup helpers for the AP vendor-master domain.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so nothing carries over).
Setup steps use get_success_data() so failures surface as clear "Setup failed"
assertion errors. OCC-guarded writes re-read the vendor to obtain its current
version, so callers never hand-track version numbers.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    create_vendor_payload,
    create_bank_account_payload,
    create_document_payload,
    create_watchlist_entry_payload,
    create_matrix_rule_payload,
    create_invoice_payload,
    create_payment_run_payload,
)
from .test_users import TEST_USERS, TIER_APPROVER_HEADERS

SYS = TEST_USERS["system_admin_headers"]
VS1 = TEST_USERS["vendor_specialist_headers"]
VS2 = TEST_USERS["vendor_specialist_2_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
VM2 = TEST_USERS["vendor_manager_2_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
SUP1 = TEST_USERS["ap_supervisor_headers"]
MGR = TEST_USERS["ap_manager_headers"]
CTL = TEST_USERS["controller_headers"]
TA = TEST_USERS["treasury_analyst_headers"]
TM1 = TEST_USERS["treasury_manager_headers"]
TM2 = TEST_USERS["treasury_manager_2_headers"]
BFP = TEST_USERS["bank_file_processor_headers"]
AUD = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Ops / clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Set the server logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, SYS))


def run_vendor_sweep() -> dict:
    """Run the four-pass ops sweep; returns the four counters (PRD §2.4)."""
    return get_success_data(api_client.run_vendor_sweep(SYS))


# ---------------------------------------------------------------------------
# Approval matrix
# ---------------------------------------------------------------------------

def create_matrix_rule(
    cost_center: str = "GLOBAL",
    min_amount_cents: int = 0,
    max_amount_cents: Optional[int] = 500000,
    tier: int = 1,
    headers=None,
) -> dict:
    payload = create_matrix_rule_payload(
        cost_center=cost_center,
        min_amount_cents=min_amount_cents,
        max_amount_cents=max_amount_cents,
        tier=tier,
    )
    if max_amount_cents is None:
        payload.pop("max_amount_cents", None)
    return get_success_data(api_client.create_matrix_rule(payload, headers or CTL))


# ---------------------------------------------------------------------------
# Vendors: registration, documents, lifecycle
# ---------------------------------------------------------------------------

def create_vendor(headers=None, **overrides) -> dict:
    """POST /vendors expecting success; returns the DRAFT vendor."""
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(**overrides), headers or VS1))


def attach_document(
    vendor_id: str,
    doc_type: str = "W9",
    valid_from: str = "2026-01-01",
    valid_until: str = "2027-12-31",
    headers=None,
) -> dict:
    payload = create_document_payload(
        doc_type=doc_type, valid_from=valid_from, valid_until=valid_until)
    return get_success_data(api_client.create_document(vendor_id, payload, headers or VS1))


def get_vendor(vendor_id: str) -> dict:
    return get_success_data(api_client.get_vendor(vendor_id, AUD))


def onboard_vendor_to_active(
    w9_window: Tuple[str, str] = ("2025-01-01", "2027-12-31"),
    creator=None,
    approver=None,
    **vendor_overrides,
) -> dict:
    """Create -> attach W9 -> submit -> approve. Returns the ACTIVE vendor.

    Default creator is vendor specialist u-vs-01 and approver is vendor manager
    u-vm-01, so SoD-1 (creator may not approve) is respected.
    """
    creator = creator or VS1
    approver = approver or VM1
    vendor = create_vendor(headers=creator, **vendor_overrides)
    attach_document(vendor["id"], valid_from=w9_window[0], valid_until=w9_window[1])
    get_success_data(api_client.submit_vendor(vendor["id"], creator))
    return get_success_data(api_client.approve_vendor(vendor["id"], approver))


def suspend_vendor(vendor_id: str, reason: str = "audit hold", headers=None) -> dict:
    return get_success_data(api_client.suspend_vendor(vendor_id, {"reason": reason}, headers or VM1))


def reinstate_vendor(vendor_id: str, headers=None) -> dict:
    return get_success_data(api_client.reinstate_vendor(vendor_id, headers or VM1))


# ---------------------------------------------------------------------------
# Bank accounts and callback verification
# ---------------------------------------------------------------------------

def add_bank_account(vendor_id: str, requester=None, **overrides) -> dict:
    """Add a bank account under the vendor's CURRENT version (OCC, PRD §2.8)."""
    vendor = get_vendor(vendor_id)
    payload = create_bank_account_payload(
        expected_vendor_version=vendor["version"], **overrides)
    return get_success_data(api_client.create_bank_account(
        vendor_id, payload, requester or VS1))


def list_callback_verifications(account_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_callback_verifications(account_id, AUD))
    return data


def get_callback_code(account_id: str) -> str:
    """The simulated callback exposes the server-minted code on read (PRD §3.3)."""
    verifications = list_callback_verifications(account_id)
    assert len(verifications) >= 1, "expected a callback verification row"
    return verifications[0]["verification_code"]


def confirm_bank_account(account_id: str, confirmer=None) -> dict:
    """Confirm with the minted code; default confirmer differs from requester."""
    code = get_callback_code(account_id)
    return get_success_data(api_client.confirm_bank_verification(
        account_id, {"verification_code": code}, confirmer or VM1))


def add_verified_primary_bank_account(vendor_id: str, requester=None, confirmer=None,
                                      **overrides) -> dict:
    """Add an is_primary account and confirm the callback -> VERIFIED primary."""
    account = add_bank_account(vendor_id, requester=requester,
                               is_primary=True, **overrides)
    return confirm_bank_account(account["id"], confirmer=confirmer)


def onboard_payable_vendor(**vendor_overrides) -> Tuple[dict, dict]:
    """ACTIVE vendor + VERIFIED primary bank account. Returns (vendor, account)."""
    vendor = onboard_vendor_to_active(**vendor_overrides)
    account = add_verified_primary_bank_account(vendor["id"])
    return get_vendor(vendor["id"]), account


def wrong_verification_codes(real_code: str, count: int) -> list:
    """Six-digit codes guaranteed different from the minted one."""
    codes = []
    candidate = 0
    while len(codes) < count:
        value = f"{candidate:06d}"
        candidate += 1
        if value != real_code:
            codes.append(value)
    return codes


# ---------------------------------------------------------------------------
# Watchlist / sanctions
# ---------------------------------------------------------------------------

def create_watchlist_entry(name_pattern: str, severity: str,
                           list_source: str = "OFAC_SDN", headers=None) -> dict:
    payload = create_watchlist_entry_payload(
        name_pattern=name_pattern, severity=severity, list_source=list_source)
    return get_success_data(api_client.create_watchlist_entry(payload, headers or CO))


def list_open_cases_for_vendor(vendor_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_sanctions_cases(
        AUD, params={"vendor_id": vendor_id, "status": "OPEN"}))
    return data


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def create_invoice(vendor_id: str, amount_cents: int = 100000,
                   cost_center: str = "CC-100", received_date: Optional[str] = None,
                   invoice_number: Optional[str] = None, headers=None) -> dict:
    overrides = {"vendor_id": vendor_id, "amount_cents": amount_cents,
                 "cost_center": cost_center}
    if received_date is not None:
        overrides["received_date"] = received_date
    if invoice_number is not None:
        overrides["invoice_number"] = invoice_number
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(**overrides), headers or CLERK))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, AUD))


def submit_invoice(invoice_id: str, headers=None) -> dict:
    return get_success_data(api_client.submit_invoice(invoice_id, headers or CLERK))


def approve_invoice_fully(invoice_id: str) -> dict:
    """Approve tiers 1..required_tier in order with the tier-designated roles.

    Uses three distinct operators (u-sup-01 / u-mgr-01 / u-ctl-01); the fixture
    submitter is always u-ap-01, so SoD-2 and SoD-5 are both satisfied.
    """
    invoice = get_invoice(invoice_id)
    for tier in range(1, invoice["required_tier"] + 1):
        get_success_data(api_client.approve_invoice(
            invoice_id, {"tier": tier}, TIER_APPROVER_HEADERS[tier]))
    return get_invoice(invoice_id)


def create_approved_invoice(vendor_id: str, amount_cents: int = 100000,
                            cost_center: str = "CC-100",
                            received_date: Optional[str] = None,
                            invoice_number: Optional[str] = None) -> dict:
    """Create -> submit -> approve every required tier. Returns APPROVED invoice."""
    invoice = create_invoice(
        vendor_id, amount_cents=amount_cents, cost_center=cost_center,
        received_date=received_date, invoice_number=invoice_number)
    submit_invoice(invoice["id"])
    return approve_invoice_fully(invoice["id"])


def list_invoice_approvals(invoice_id: str, params: Optional[dict] = None) -> Tuple[list, dict]:
    return validate_paginated(api_client.list_invoice_approvals(invoice_id, AUD, params=params))


# ---------------------------------------------------------------------------
# Payment runs / payments
# ---------------------------------------------------------------------------

def create_payment_run(scheduled_date: str = "2026-08-05",
                       payment_method: str = "CHECK", headers=None) -> dict:
    return get_success_data(api_client.create_payment_run(
        create_payment_run_payload(scheduled_date=scheduled_date,
                                   payment_method=payment_method),
        headers or TA))


def get_payment_run(run_id: str) -> dict:
    return get_success_data(api_client.get_payment_run(run_id, AUD))


def add_invoice_to_run_ok(run_id: str, invoice_id: str, headers=None) -> dict:
    """Add an APPROVED invoice to a DRAFT run expecting success; returns Payment."""
    return get_success_data(api_client.add_invoice_to_run(
        run_id, {"invoice_id": invoice_id}, headers or TA))


def get_payment(payment_id: str) -> dict:
    return get_success_data(api_client.get_payment(payment_id, AUD))


def list_run_payments(run_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_run_payments(run_id, AUD))
    return data


def compile_run(run_id: str, headers=None) -> dict:
    return get_success_data(api_client.compile_payment_run(run_id, headers or TA))


def approve_run(run_id: str, headers=None) -> dict:
    return get_success_data(api_client.approve_payment_run(run_id, headers or TM1))


def release_run(run_id: str, headers=None) -> dict:
    return get_success_data(api_client.release_payment_run(run_id, headers or TM1))


def build_compiled_run(invoice_id: str, scheduled_date: str = "2026-08-05",
                       payment_method: str = "CHECK", run_creator=None) -> Tuple[dict, dict]:
    """DRAFT run + one payment, compiled. Returns (run, payment)."""
    run = create_payment_run(scheduled_date=scheduled_date,
                             payment_method=payment_method, headers=run_creator)
    payment = add_invoice_to_run_ok(run["id"], invoice_id)
    run = compile_run(run["id"])
    return run, payment


def build_approved_run(invoice_id: str, scheduled_date: str = "2026-08-05",
                       payment_method: str = "CHECK", run_creator=None,
                       approver=None) -> Tuple[dict, dict]:
    """Compiled run approved by a TreasuryManager who did not create it (SoD-4a)."""
    run, payment = build_compiled_run(
        invoice_id, scheduled_date=scheduled_date,
        payment_method=payment_method, run_creator=run_creator)
    run = approve_run(run["id"], headers=approver or TM1)
    return run, payment


def build_released_run(invoice_id: str, scheduled_date: str = "2026-08-05",
                       payment_method: str = "CHECK", run_creator=None,
                       approver=None, releaser=None) -> Tuple[dict, dict]:
    """Approved run released (SoD-4b). Returns (run, payment)."""
    run, payment = build_approved_run(
        invoice_id, scheduled_date=scheduled_date,
        payment_method=payment_method, run_creator=run_creator, approver=approver)
    run = release_run(run["id"], headers=releaser or TM1)
    return run, payment
