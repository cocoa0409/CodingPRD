"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database and
the logical clock at its fixed default, so these helpers rebuild complete
precondition chains out of PRD-declared endpoints only.

Identity threading: Producer calls are entity-backed by ProductionCompany and
CreditBuyer calls by CreditBuyer. Ownership-gated calls always use
make_producer_headers(company["id"]) / make_buyer_headers(buyer["id"]) built
from the real entity ids — never the shared fallback constants.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    attest_payload,
    create_application_payload,
    create_audit_package_payload,
    create_clawback_case_payload,
    create_credit_buyer_payload,
    create_production_company_payload,
    create_production_payload,
    create_program_payload,
    create_spend_entry_payload,
    create_transfer_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_cpa_headers,
    make_producer_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER1 = TEST_USERS["reviewer1_headers"]
REVIEWER2 = TEST_USERS["reviewer2_headers"]
REVIEWER3 = TEST_USERS["reviewer3_headers"]
CPA1 = TEST_USERS["cpa1_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601):
    """Move the server-side logical clock (admin-only test capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create a program (starts DRAFT, allocated zero, remaining == annual cap)."""
    return get_success_data(
        api_client.create_jurisdiction_program(create_program_payload(**overrides), ADMIN))


def transition_program(program, to_state):
    return get_success_data(
        api_client.transition_jurisdiction_program(program["id"], to_state, ADMIN))


def open_program(**overrides):
    """Create a program and transition it DRAFT -> OPEN."""
    program = create_program(**overrides)
    return transition_program(program, "OPEN")


def get_program(program):
    return get_success_data(api_client.get_jurisdiction_program(program["id"], ADMIN))


# ---------------------------------------------------------------------------
# Parties
# ---------------------------------------------------------------------------

def register_company(**overrides):
    """Self-register a production company; the response id is the caller identity."""
    return get_success_data(api_client.create_production_company(
        create_production_company_payload(**overrides), TEST_USERS["producer_headers"]))


def register_buyer(**overrides):
    """Self-register a credit buyer; the response id is the caller identity."""
    return get_success_data(api_client.create_credit_buyer(
        create_credit_buyer_payload(**overrides), TEST_USERS["buyer_headers"]))


def create_production(company, **overrides):
    headers = make_producer_headers(company["id"])
    return get_success_data(api_client.create_production(
        create_production_payload(company["id"], **overrides), headers))


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def create_application(production, program, estimated_qualified_spend_cents=250_000_000):
    """Create a DRAFT application (caller must own the production's company)."""
    headers = make_producer_headers(production["production_company_id"])
    return get_success_data(api_client.create_application(
        create_application_payload(
            production["id"], program["id"],
            estimated_qualified_spend_cents=estimated_qualified_spend_cents),
        headers))


def submit_application(application, company):
    return get_success_data(api_client.submit_application(
        application["id"], make_producer_headers(company["id"])))


def withdraw_application(application, company):
    return get_success_data(api_client.withdraw_application(
        application["id"], make_producer_headers(company["id"])))


def claim_application(application, reviewer_user_id="reviewer-1"):
    return get_success_data(api_client.claim_review(
        application["id"], make_reviewer_headers(reviewer_user_id)))


def request_corrections(application, reviewer_user_id="reviewer-1", notes="needs work"):
    return get_success_data(api_client.request_corrections(
        application["id"], make_reviewer_headers(reviewer_user_id), notes=notes))


def resubmit_application(application, company):
    return get_success_data(api_client.resubmit_application(
        application["id"], make_producer_headers(company["id"])))


def approve_application(application, approver_user_id="reviewer-2"):
    return get_success_data(api_client.approve_application(
        application["id"], make_reviewer_headers(approver_user_id)))


def deny_application(application, denier_user_id="reviewer-2", reason=None):
    return get_success_data(api_client.deny_application(
        application["id"], make_reviewer_headers(denier_user_id), reason=reason))


def get_application(application, headers=None):
    return get_success_data(api_client.get_application(
        application["id"], headers or REVIEWER1))


def setup_approved_application(program=None, *, program_overrides=None,
                               estimated_qualified_spend_cents=250_000_000,
                               company=None, **production_overrides):
    """OPEN program + company + production + application walked DRAFT ->
    SUBMITTED -> UNDER_REVIEW -> APPROVED. Returns a namespace."""
    if program is None:
        program = open_program(**(program_overrides or {}))
    if company is None:
        company = register_company()
    production = create_production(company, **production_overrides)
    application = create_application(
        production, program,
        estimated_qualified_spend_cents=estimated_qualified_spend_cents)
    submit_application(application, company)
    claim_application(application)
    application = approve_application(application)
    return SimpleNamespace(program=program, company=company, production=production,
                           application=application)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

def register_vendor(production, company=None, **overrides):
    """Register a vendor on a production (starts UNVERIFIED)."""
    company_id = (company or {}).get("id") or production["production_company_id"]
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(production["id"], **overrides),
        make_producer_headers(company_id)))


def review_vendor(vendor, decision, reviewer_user_id="reviewer-1", rejection_reason=None):
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api_client.review_vendor_residency(
        vendor["id"], payload, make_reviewer_headers(reviewer_user_id)))


def register_verified_vendor(production, company=None, reviewer_user_id="reviewer-1",
                             **overrides):
    """Register a vendor and verify its residency (VERIFIED at the current clock)."""
    vendor = register_vendor(production, company, **overrides)
    return review_vendor(vendor, "VERIFIED", reviewer_user_id)


# ---------------------------------------------------------------------------
# Spend entries
# ---------------------------------------------------------------------------

def add_spend_entry(application, vendor, company, **overrides):
    """Record a spend entry (starts PENDING_REVIEW, effective amount zero)."""
    return get_success_data(api_client.create_spend_entry(
        create_spend_entry_payload(application["id"], vendor["id"], **overrides),
        make_producer_headers(company["id"])))


def review_spend_entry(entry, decision, reviewer_user_id="reviewer-1",
                       disqualify_reason=None):
    payload = {"decision": decision}
    if disqualify_reason is not None:
        payload["disqualify_reason"] = disqualify_reason
    return get_success_data(api_client.review_spend_entry(
        entry["id"], payload, make_reviewer_headers(reviewer_user_id)))


def qualify_entry(entry, reviewer_user_id="reviewer-1"):
    return review_spend_entry(entry, "QUALIFY", reviewer_user_id)


def disqualify_entry(entry, reason="audit finding", reviewer_user_id="reviewer-1"):
    return review_spend_entry(entry, "DISQUALIFY", reviewer_user_id, reason)


def add_qualified_entries(application, vendor, company, specs, reviewer_user_id="reviewer-1"):
    """Create one spend entry per spec dict and qualify each. Returns entries."""
    entries = []
    for spec in specs:
        entry = add_spend_entry(application, vendor, company, **spec)
        entries.append(qualify_entry(entry, reviewer_user_id))
    return entries


# ---------------------------------------------------------------------------
# Audit packages
# ---------------------------------------------------------------------------

def engage_audit(application, cpa_user_id="cpa-1"):
    """Engage an audit package on an APPROVED application (starts ENGAGED)."""
    return get_success_data(api_client.create_audit_package(
        create_audit_package_payload(application["id"]), make_cpa_headers(cpa_user_id)))


def submit_audit_draft(package, cpa_user_id="cpa-1", documentation_complete=True):
    return get_success_data(api_client.submit_audit_draft(
        package["id"], documentation_complete, make_cpa_headers(cpa_user_id)))


def raise_exceptions(package, notes="exceptions noted", reviewer_user_id="reviewer-1"):
    return get_success_data(api_client.raise_audit_exceptions(
        package["id"], notes, make_reviewer_headers(reviewer_user_id)))


def attest_audit(package, attested_atl_cents, attested_btl_cents, cpa_user_id="cpa-1",
                 documentation_complete=True):
    return get_success_data(api_client.attest_audit_package(
        package["id"],
        attest_payload(attested_atl_cents, attested_btl_cents, documentation_complete),
        make_cpa_headers(cpa_user_id)))


def decide_audit(package, outcome, reviewer_user_id="reviewer-3", decision_reason=None):
    payload = {"outcome": outcome}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(api_client.decide_audit_package(
        package["id"], payload, make_reviewer_headers(reviewer_user_id)))


def run_accepted_audit(application, attested_atl_cents, attested_btl_cents,
                       cpa_user_id="cpa-1", decider_user_id="reviewer-3"):
    """Engage -> submit draft -> attest -> ACCEPT. Returns the ACCEPTED package."""
    package = engage_audit(application, cpa_user_id)
    submit_audit_draft(package, cpa_user_id)
    package = attest_audit(package, attested_atl_cents, attested_btl_cents, cpa_user_id)
    return decide_audit(package, "ACCEPT", decider_user_id)


# ---------------------------------------------------------------------------
# Certificates and issuance
# ---------------------------------------------------------------------------

def issue_credit(application, headers=None):
    return get_success_data(api_client.issue_credit(application["id"], headers or ADMIN))


def get_certificate(certificate, headers=None):
    return get_success_data(api_client.get_certificate(certificate["id"], headers or ADMIN))


def get_certificate_by_application(application, headers=None):
    """Return the application's certificate (exactly one) or None."""
    data, _meta = validate_paginated(api_client.list_certificates(
        headers or ADMIN, params={"application_id": application["id"]}))
    return data[0] if data else None


def setup_issued_certificate(*, attested_atl=40_000_000, attested_btl=162_500_000,
                             entry_specs=None, program_overrides=None,
                             estimated_qualified_spend_cents=250_000_000,
                             **production_overrides):
    """Full chain through issuance: OPEN program, APPROVED application, the
    given entries verified-and-qualified (if any), audit ACCEPTED, credit
    issued. With the defaults the certificate face is 60,750,000 cents.
    Returns a namespace(program, company, production, application, vendor,
    entries, package, certificate)."""
    scenario = setup_approved_application(
        program_overrides=program_overrides,
        estimated_qualified_spend_cents=estimated_qualified_spend_cents,
        **production_overrides)
    vendor = None
    entries = []
    if entry_specs:
        vendor = register_verified_vendor(scenario.production, scenario.company)
        entries = add_qualified_entries(
            scenario.application, vendor, scenario.company, entry_specs)
    package = run_accepted_audit(scenario.application, attested_atl, attested_btl)
    certificate = issue_credit(scenario.application)
    scenario.vendor = vendor
    scenario.entries = entries
    scenario.package = package
    scenario.certificate = certificate
    scenario.application = get_application(scenario.application)
    return scenario


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------

def propose_transfer(certificate, buyer, company, *, amount_cents=5_000_000,
                     price_cents=4_500_000, expected_certificate_version=None):
    """Propose a transfer as the selling producer. When no expected version is
    given, re-read the certificate and carry its fresh version."""
    if expected_certificate_version is None:
        expected_certificate_version = get_certificate(certificate)["version"]
    return get_success_data(api_client.create_transfer(
        create_transfer_payload(
            certificate["id"], buyer["id"], expected_certificate_version,
            amount_cents=amount_cents, price_cents=price_cents),
        make_producer_headers(company["id"])))


def counter_transfer_by_buyer(transfer, buyer, new_price_cents):
    return get_success_data(api_client.counter_transfer(
        transfer["id"], new_price_cents, make_buyer_headers(buyer["id"])))


def counter_transfer_by_seller(transfer, company, new_price_cents):
    return get_success_data(api_client.counter_transfer(
        transfer["id"], new_price_cents, make_producer_headers(company["id"])))


def accept_transfer_by_buyer(transfer, buyer):
    return get_success_data(api_client.accept_transfer(
        transfer["id"], make_buyer_headers(buyer["id"])))


def accept_transfer_by_seller(transfer, company):
    return get_success_data(api_client.accept_transfer(
        transfer["id"], make_producer_headers(company["id"])))


def settle_transfer(transfer):
    return get_success_data(api_client.settle_transfer(transfer["id"], ADMIN))


def cancel_transfer_by_seller(transfer, company):
    return get_success_data(api_client.cancel_transfer(
        transfer["id"], make_producer_headers(company["id"])))


def get_transfer(transfer, headers=None):
    return get_success_data(api_client.get_transfer(transfer["id"], headers or ADMIN))


# ---------------------------------------------------------------------------
# Clawback cases
# ---------------------------------------------------------------------------

def open_clawback_case(application, *, trigger_reason="SPEND_SHORTFALL",
                       penalty_mode="SIMPLE", shortfall_amount_cents=None):
    payload = create_clawback_case_payload(
        application["id"], trigger_reason=trigger_reason, penalty_mode=penalty_mode)
    if shortfall_amount_cents is not None:
        payload["shortfall_amount_cents"] = shortfall_amount_cents
    return get_success_data(api_client.create_clawback_case(payload, ADMIN))


def send_notice(case):
    return get_success_data(api_client.send_clawback_notice(case["id"], ADMIN))


def resolve_case(case, outcome, settled_amount_cents=None):
    payload = {"outcome": outcome}
    if settled_amount_cents is not None:
        payload["settled_amount_cents"] = settled_amount_cents
    return get_success_data(api_client.resolve_clawback_case(case["id"], payload, ADMIN))


def list_clawback_cases(headers=None, **params):
    return validate_paginated(api_client.list_clawback_cases(headers or ADMIN, params=params))
