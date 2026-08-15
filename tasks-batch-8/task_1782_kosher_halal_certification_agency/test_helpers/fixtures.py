"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(each test runs against a freshly restarted server with an empty database).
Setup calls use the lenient get_success_data validator so a setup failure
surfaces as a clear "Setup step failed" message.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_certificate_payload,
    create_client_payload,
    create_equipment_line_payload,
    create_facility_payload,
    create_finding_payload,
    create_holiday_window_payload,
    create_ingredient_payload,
    create_product_payload,
    create_visit_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_manager_headers,
    make_client_contact_headers,
    make_officer_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AM = TEST_USERS["account_manager_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
OFFICER = TEST_USERS["officer_headers"]

# Default operator ids. The fee payer and the certificate issuer must differ
# (issuance segregation of duties, PRD section 2.9).
DEFAULT_PAYER_ID = "am-1"
DEFAULT_ISSUER_ID = "co-1"
DEFAULT_INSPECTOR_ID = "sup-1"

# Canonical chain timing: the initial site visit runs 2026-06-01 morning and
# the rest of the chain follows at the same logical instant, so later clock
# moves in tests only go forward.
DEFAULT_VISIT_START = "2026-06-01T09:00:00Z"
DEFAULT_VISIT_END = "2026-06-01T12:00:00Z"
DEFAULT_CHAIN_CLOCK = "2026-06-01T10:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------
def create_prospect_client(**overrides):
    """Register a client (PROSPECT). Returns the client dict."""
    resp = api_client.create_client(create_client_payload(**overrides), AM)
    return get_success_data(resp)


def create_applicant_client(**overrides):
    """Client registered and application submitted (APPLICANT)."""
    client = create_prospect_client(**overrides)
    resp = api_client.submit_application(
        client["id"], make_client_contact_headers(client["id"]))
    return get_success_data(resp)


def get_client(client_id):
    return get_success_data(api_client.get_client(client_id, AM))


def get_client_version(client_id):
    return get_client(client_id)["version"]


def create_facility_for(client_id, **overrides):
    resp = api_client.create_facility(
        create_facility_payload(client_id, **overrides),
        make_client_contact_headers(client_id))
    return get_success_data(resp)


def create_equipment_line_for(client_id, facility_id, **overrides):
    resp = api_client.create_equipment_line(
        create_equipment_line_payload(facility_id, **overrides),
        make_client_contact_headers(client_id))
    return get_success_data(resp)


def assess_line(line_id, dedication_status="DEDICATED"):
    resp = api_client.assess_equipment_line(line_id, dedication_status, REVIEWER)
    return get_success_data(resp)


def create_assessed_line(client_id, facility_id, dedication_status="DEDICATED",
                         **overrides):
    line = create_equipment_line_for(client_id, facility_id, **overrides)
    return assess_line(line["id"], dedication_status)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: visits and facility approval
# ---------------------------------------------------------------------------
def schedule_visit(facility_id, visit_type="ROUTINE",
                   inspector_user_id=DEFAULT_INSPECTOR_ID,
                   scheduled_start=DEFAULT_VISIT_START,
                   scheduled_end=DEFAULT_VISIT_END, as_reviewer=False):
    headers = REVIEWER if as_reviewer else AM
    resp = api_client.create_visit(
        create_visit_payload(
            facility_id, visit_type=visit_type,
            inspector_user_id=inspector_user_id,
            scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        headers)
    return get_success_data(resp)


def run_visit_to_completed(visit_id, inspector_user_id=DEFAULT_INSPECTOR_ID,
                           clock_into_window=DEFAULT_CHAIN_CLOCK):
    """Clock into the visit window, start, complete. Returns COMPLETED visit."""
    set_clock(clock_into_window)
    sup = make_supervisor_headers(inspector_user_id)
    get_success_data(api_client.start_visit(visit_id, sup))
    resp = api_client.complete_visit(visit_id, sup)
    return get_success_data(resp)


def complete_initial_visit(facility_id, inspector_user_id=DEFAULT_INSPECTOR_ID,
                           start=DEFAULT_VISIT_START, end=DEFAULT_VISIT_END,
                           clock_into_window=DEFAULT_CHAIN_CLOCK):
    """Schedule an INITIAL visit and drive it to COMPLETED."""
    visit = schedule_visit(facility_id, visit_type="INITIAL",
                           inspector_user_id=inspector_user_id,
                           scheduled_start=start, scheduled_end=end)
    return run_visit_to_completed(visit["id"], inspector_user_id,
                                  clock_into_window)


def create_approved_facility(client_id, dedication_status="DEDICATED",
                             **facility_overrides):
    """Facility + one assessed line + COMPLETED INITIAL visit + approval.

    Returns (facility, line). The default DEDICATED assessment leaves
    kosherization NONE, which passes the approval equipment gate.
    """
    facility = create_facility_for(client_id, **facility_overrides)
    line = create_assessed_line(client_id, facility["id"], dedication_status)
    complete_initial_visit(facility["id"])
    resp = api_client.approve_facility(facility["id"], REVIEWER)
    return get_success_data(resp), line


# ---------------------------------------------------------------------------
# Tier 2: ingredients and products
# ---------------------------------------------------------------------------
def create_submitted_ingredient(client_id, **overrides):
    resp = api_client.create_ingredient(
        create_ingredient_payload(client_id, **overrides),
        make_client_contact_headers(client_id))
    return get_success_data(resp)


def create_approved_ingredient(client_id, **overrides):
    ingredient = create_submitted_ingredient(client_id, **overrides)
    get_success_data(api_client.start_ingredient_review(ingredient["id"], REVIEWER))
    resp = api_client.approve_ingredient(ingredient["id"], REVIEWER)
    return get_success_data(resp)


def create_draft_product(client_id, ingredient_ids=(), **overrides):
    resp = api_client.create_product(
        create_product_payload(client_id, list(ingredient_ids), **overrides),
        make_client_contact_headers(client_id))
    return get_success_data(resp)


def create_certifiable_product(client_id, ingredient_ids, **overrides):
    """Product DRAFT -> IN_REVIEW -> CERTIFIABLE."""
    product = create_draft_product(client_id, ingredient_ids, **overrides)
    cc = make_client_contact_headers(client_id)
    get_success_data(api_client.submit_product_review(product["id"], cc))
    resp = api_client.certify_product_eligible(product["id"], REVIEWER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: agreements and invoices
# ---------------------------------------------------------------------------
def create_draft_agreement(client_id, **overrides):
    """Create an agreement with a fresh OCC read of the client version."""
    version = get_client_version(client_id)
    resp = api_client.create_agreement(
        create_agreement_payload(client_id, version, **overrides), AM)
    return get_success_data(resp)


def create_active_agreement(client_id, **overrides):
    agreement = create_draft_agreement(client_id, **overrides)
    resp = api_client.activate_agreement(agreement["id"], AM)
    return get_success_data(resp)


def create_annual_invoice(client_id, agreement_id):
    resp = api_client.create_invoice(
        {"client_id": client_id, "invoice_type": "ANNUAL_CERTIFICATION",
         "agreement_id": agreement_id}, AM)
    return get_success_data(resp)


def create_paid_annual_invoice(client_id, agreement_id,
                               payer_id=DEFAULT_PAYER_ID):
    invoice = create_annual_invoice(client_id, agreement_id)
    payer = make_account_manager_headers(payer_id)
    resp = api_client.record_payment(invoice["id"], payer)
    return get_success_data(resp)


def list_all_invoices():
    """All invoices in the system (fresh server per test keeps this small)."""
    data, _meta = validate_paginated(api_client.list_invoices(AM, {"limit": 100}))
    return data


def find_invoices(invoice_type=None, related_certificate_id=None,
                  agreement_id=None):
    rows = list_all_invoices()
    if invoice_type is not None:
        rows = [r for r in rows if r["invoice_type"] == invoice_type]
    if related_certificate_id is not None:
        rows = [r for r in rows
                if r.get("related_certificate_id") == related_certificate_id]
    if agreement_id is not None:
        rows = [r for r in rows if r.get("agreement_id") == agreement_id]
    return rows


# ---------------------------------------------------------------------------
# Tier 4/5: the full certification chain
# ---------------------------------------------------------------------------
def setup_certified_client(scheme="KOSHER", billing_cycle="ANNIVERSARY",
                           term_start_date="2026-04-01",
                           per_product_fee_cents=73000, num_products=1,
                           issue_clock=None, issuer_id=DEFAULT_ISSUER_ID,
                           payer_id=DEFAULT_PAYER_ID,
                           legal_name="Certified Co"):
    """Full chain: APPLICANT client -> APPROVED facility -> ACTIVE agreement
    -> PAID annual invoice -> APPROVED ingredient(s) -> CERTIFIABLE product(s)
    -> certificate issued ACTIVE (client CERTIFIED).

    Returns a context dict with every created entity. `issue_clock`, when
    given, fixes the logical instant (and thus issued_at / valid_until).
    """
    client = create_applicant_client(
        legal_name=legal_name, certification_scheme=scheme)
    cid = client["id"]
    facility, line = create_approved_facility(cid)
    agreement = create_active_agreement(
        cid, scheme=scheme, billing_cycle=billing_cycle,
        term_start_date=term_start_date,
        per_product_fee_cents=per_product_fee_cents)
    annual_invoice = create_paid_annual_invoice(cid, agreement["id"], payer_id)
    ingredients = []
    products = []
    for idx in range(num_products):
        ing = create_approved_ingredient(
            cid, name=f"Ingredient-{idx + 1}", manufacturer="M")
        ingredients.append(ing)
        products.append(create_certifiable_product(
            cid, [ing["id"]], name=f"Product-{idx + 1}", brand="B"))
    certificate = get_success_data(api_client.create_certificate(
        create_certificate_payload(cid, [facility["id"]],
                                   [p["id"] for p in products], scheme=scheme),
        OFFICER))
    if issue_clock is not None:
        set_clock(issue_clock)
    certificate = get_success_data(api_client.issue_certificate(
        certificate["id"], make_officer_headers(issuer_id)))
    return {
        "client": get_client(cid),
        "facility": facility,
        "line": line,
        "agreement": agreement,
        "annual_invoice": annual_invoice,
        "ingredients": ingredients,
        "products": products,
        "certificate": certificate,
    }


def issue_additional_certificate(ctx, term_type="ANNUAL",
                                 holiday_window_id=None, scheme=None,
                                 issuer_id=DEFAULT_ISSUER_ID):
    """Draft and issue another certificate for an already-certified client."""
    payload = create_certificate_payload(
        ctx["client"]["id"], [ctx["facility"]["id"]],
        [p["id"] for p in ctx["products"]],
        scheme=scheme or ctx["certificate"]["scheme"], term_type=term_type)
    if holiday_window_id is not None:
        payload["holiday_window_id"] = holiday_window_id
    cert = get_success_data(api_client.create_certificate(payload, OFFICER))
    return get_success_data(api_client.issue_certificate(
        cert["id"], make_officer_headers(issuer_id)))


def request_holiday_window(client_id, facility_id, holiday_code="PASSOVER",
                           window_start="2026-09-20T00:00:00Z",
                           window_end="2026-09-30T00:00:00Z"):
    resp = api_client.create_holiday_window(
        create_holiday_window_payload(
            facility_id, holiday_code=holiday_code,
            window_start=window_start, window_end=window_end),
        make_client_contact_headers(client_id))
    return get_success_data(resp)


def confirm_window(window_id, assigned_supervisor_id="sup-9"):
    resp = api_client.confirm_holiday_window(
        window_id, assigned_supervisor_id, REVIEWER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Findings helpers
# ---------------------------------------------------------------------------
def start_routine_visit(facility_id, inspector_user_id="sup-2",
                        start="2026-08-03T09:00:00Z", end="2026-08-03T12:00:00Z",
                        clock_into_window="2026-08-03T10:00:00Z"):
    """ROUTINE visit driven to IN_PROGRESS (started, not completed)."""
    visit = schedule_visit(facility_id, visit_type="ROUTINE",
                           inspector_user_id=inspector_user_id,
                           scheduled_start=start, scheduled_end=end)
    set_clock(clock_into_window)
    get_success_data(api_client.start_visit(
        visit["id"], make_supervisor_headers(inspector_user_id)))
    return visit


def raise_finding(visit_id, inspector_user_id, severity="MINOR",
                  description="observation",
                  remediation_deadline="2026-12-31T00:00:00Z"):
    resp = api_client.create_finding(
        visit_id,
        create_finding_payload(severity=severity, description=description,
                               remediation_deadline=remediation_deadline),
        make_supervisor_headers(inspector_user_id))
    return get_success_data(resp)


__all__ = [name for name in dir() if not name.startswith("_")] + [
    "NON_EXISTENT_UUID",
]
