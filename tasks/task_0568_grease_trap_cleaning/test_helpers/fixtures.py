"""Composite setup helpers for multi-step test prerequisites (FOG Compliance Service).

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

The logical clock resets to 2026-05-01T00:00:00Z on every server restart (which happens
before each test), so fixtures only advance it when a test needs a specific "now".

Identity threading: the Technician role is entity_backed. Every ownership-gated call
(start / complete / file manifest / void / certify) uses make_technician_headers(tech_id)
with the real Technician.id, never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_site_payload, create_equipment_payload,
    create_service_contract_payload, create_technician_payload, create_work_order_payload,
    create_manifest_payload, create_hood_certificate_payload, create_invoice_payload,
)
from .test_users import TEST_USERS, make_technician_headers
from .constants import DEFAULT_CLOCK

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ─────────────────────── Clock ───────────────────────
def set_clock(iso=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─────────────────────── Low-level creators ───────────────────────
def new_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def new_site(customer_id, **overrides):
    return get_success_data(
        api_client.create_site(create_site_payload(customer_id, **overrides), ADMIN))


def new_equipment(site_id, **overrides):
    return get_success_data(
        api_client.create_equipment(create_equipment_payload(site_id, **overrides), ADMIN))


def new_technician(certification_level="BASIC", **overrides):
    return get_success_data(api_client.create_technician(
        create_technician_payload(certification_level=certification_level, **overrides), ADMIN))


def new_contract(customer_id, **overrides):
    return get_success_data(api_client.create_service_contract(
        create_service_contract_payload(customer_id, **overrides), ADMIN))


def new_active_contract(customer_id, **overrides):
    contract = new_contract(customer_id, **overrides)
    return get_success_data(api_client.transition_service_contract(
        contract["id"], {"to_status": "ACTIVE"}, ADMIN))


def new_work_order(site_id, equipment_id, **overrides):
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(site_id, equipment_id, **overrides), DISPATCHER))


def dispatch_work_order(work_order_id, technician_id):
    return get_success_data(api_client.transition_work_order(
        work_order_id, {"to_status": "DISPATCHED", "technician_id": technician_id}, DISPATCHER))


def start_work_order(work_order_id, technician_id):
    return get_success_data(api_client.transition_work_order(
        work_order_id, {"to_status": "IN_PROGRESS"}, make_technician_headers(technician_id)))


def file_manifest(work_order_id, technician_id, **overrides):
    return get_success_data(api_client.create_manifest(
        create_manifest_payload(work_order_id, **overrides), make_technician_headers(technician_id)))


def customer_version(customer_id):
    return get_success_data(api_client.get_customer(customer_id, BILLING))["version"]


def new_draft_invoice(customer_id, contract_id=None, **overrides):
    version = customer_version(customer_id)
    payload = create_invoice_payload(customer_id, version, **overrides)
    if contract_id is not None:
        payload["contract_id"] = contract_id
    return get_success_data(api_client.create_invoice(payload, BILLING))


# ─────────────────────── Composite: in-progress work orders ───────────────────────
def setup_inprogress_grease_work_order(equipment_overrides=None, wo_overrides=None):
    """Customer -> Site -> ACTIVE grease-trap Equipment -> Technician -> WorkOrder
    dispatched and started (IN_PROGRESS) and owned by that technician.

    Returns a context dict: customer, site, equipment, technician, work_order, plus
    convenience ids and the owning technician's headers.
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"], **(equipment_overrides or {"equipment_type": "GREASE_TRAP"}))
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"], **(wo_overrides or {}))
    dispatch_work_order(wo["id"], tech["id"])
    wo = start_work_order(wo["id"], tech["id"])
    return {
        "customer": cust, "site": site, "equipment": eq, "technician": tech,
        "work_order": wo,
        "cust_id": cust["id"], "site_id": site["id"], "eq_id": eq["id"],
        "tech_id": tech["id"], "wo_id": wo["id"],
        "tech_headers": make_technician_headers(tech["id"]),
    }


def setup_inprogress_hood_work_order(certification_level="NFPA96_CERTIFIED"):
    """Customer -> Site -> ACTIVE HOOD Equipment -> Technician (NFPA96 by default) ->
    WorkOrder dispatched and started (IN_PROGRESS) owned by that technician."""
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"], equipment_type="HOOD", capacity_gallons=0, nominal_frequency_days=90)
    tech = new_technician(certification_level)
    wo = new_work_order(site["id"], eq["id"], planned_end="2026-05-10T12:00:00Z")
    dispatch_work_order(wo["id"], tech["id"])
    wo = start_work_order(wo["id"], tech["id"])
    return {
        "customer": cust, "site": site, "equipment": eq, "technician": tech,
        "work_order": wo,
        "cust_id": cust["id"], "site_id": site["id"], "eq_id": eq["id"],
        "tech_id": tech["id"], "wo_id": wo["id"],
        "tech_headers": make_technician_headers(tech["id"]),
    }


# ─────────────────────── Composite: billing ───────────────────────
def setup_issued_invoice(credit_limit_cents=1000000, base_rate_cents=12500, tax_rate_bps=0):
    """Customer + ACTIVE base-rate contract + a DRAFT invoice ISSUED for the May period.
    Returns dict with customer, contract, invoice (post-issue), and total_amount_cents."""
    cust = new_customer(credit_limit_cents=credit_limit_cents)
    contract = new_active_contract(cust["id"], base_rate_cents=base_rate_cents, tax_rate_bps=tax_rate_bps)
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    inv = get_success_data(api_client.issue_invoice(inv["id"], BILLING))
    return {
        "customer": cust, "contract": contract, "invoice": inv,
        "cust_id": cust["id"], "contract_id": contract["id"], "inv_id": inv["id"],
        "total_amount_cents": inv["total_amount_cents"],
    }


def setup_draft_invoice_base_rate(credit_limit_cents=1000000, base_rate_cents=12500, tax_rate_bps=0):
    """Customer + ACTIVE base-rate contract + a DRAFT invoice (not yet issued)."""
    cust = new_customer(credit_limit_cents=credit_limit_cents)
    contract = new_active_contract(cust["id"], base_rate_cents=base_rate_cents, tax_rate_bps=tax_rate_bps)
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    return {
        "customer": cust, "contract": contract, "invoice": inv,
        "cust_id": cust["id"], "contract_id": contract["id"], "inv_id": inv["id"],
    }


# ─────────────────────── Composite: compliance report ───────────────────────
def setup_draft_report(site_overrides=None, report_overrides=None):
    """Customer + Site (no equipment => COMPLIANT) + a DRAFT ComplianceReport."""
    cust = new_customer()
    site = new_site(cust["id"], **(site_overrides or {"municipality_code": "MUNI-B"}))
    from .factories import create_compliance_report_payload
    rep = get_success_data(api_client.create_compliance_report(
        create_compliance_report_payload(site["id"], **(report_overrides or {"municipality_code": "MUNI-B"})),
        COMPLIANCE))
    return {"customer": cust, "site": site, "report": rep,
            "cust_id": cust["id"], "site_id": site["id"], "rep_id": rep["id"]}


# ─────────────────────── Composite: suspended customer via overdue equipment ───────────────────────
def setup_suspended_customer_overdue_equipment(nominal_frequency_days=30):
    """Clock at 2026-05-01. Customer -> Site -> one never-serviced grease-trap Equipment.
    The never-serviced equipment is OVERDUE -> Site NON_COMPLIANT -> Customer auto-SUSPENDED
    by the create-time cascade. No work orders exist yet. Returns context ids."""
    set_clock(DEFAULT_CLOCK)
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"], nominal_frequency_days=nominal_frequency_days)
    return {"customer": cust, "site": site, "equipment": eq,
            "cust_id": cust["id"], "site_id": site["id"], "eq_id": eq["id"]}
