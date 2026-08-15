"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: PrimeContact is entity-backed by Supplier, so tier-2
report calls use make_prime_contact_headers(supplier["id"]). The opaque roles
are threaded as the fixed numbered identities from test_users (admin-1 vs
admin-2 for goal segregation of duties, analyst-1 vs admin-1 for certification
segregation of duties, auditor-9 as the default audit owner, lead-1 as the
default business-unit lead).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_audit_case_payload,
    create_business_unit_payload,
    create_certification_payload,
    create_engagement_payload,
    create_goal_payload,
    create_invitation_payload,
    create_sourcing_event_payload,
    create_spend_record_payload,
    create_supplier_payload,
    create_tier2_report_payload,
    generate_scorecard_payload,
    record_outcome_payload,
    respond_invitation_payload,
    resubmit_certification_payload,
    tier2_line,
)
from .test_users import TEST_USERS, make_prime_contact_headers

ADMIN1 = TEST_USERS["admin_1_headers"]
ADMIN2 = TEST_USERS["admin_2_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]
ANALYST2 = TEST_USERS["analyst_2_headers"]
LEAD1 = TEST_USERS["lead_1_headers"]
LEAD2 = TEST_USERS["lead_2_headers"]
AUDITOR8 = TEST_USERS["auditor_8_headers"]
AUDITOR9 = TEST_USERS["auditor_9_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_business_unit(name="Aerospace", code="AERO", lead_user_id="lead-1",
                         inclusion_min_diverse_bidders=None, headers=None):
    """Create a business unit (DiversityAdmin only). Returns the unit."""
    payload = create_business_unit_payload(
        name=name, code=code, lead_user_id=lead_user_id)
    if inclusion_min_diverse_bidders is not None:
        payload["inclusion_min_diverse_bidders"] = inclusion_min_diverse_bidders
    return get_success_data(
        api_client.create_business_unit(payload, headers or ADMIN1))


def create_supplier(legal_name="Diverse Parts Co", tax_id="T-100",
                    kind="DIVERSE", contact_email="d@x.com", headers=None):
    """Register a supplier (born REGISTERED). Returns the supplier."""
    payload = create_supplier_payload(
        legal_name=legal_name, tax_id=tax_id, kind=kind,
        contact_email=contact_email)
    return get_success_data(
        api_client.create_supplier(payload, headers or ANALYST1))


def submit_certification(supplier_id, cert_type="MBE",
                         certificate_number="C-100",
                         valid_from="2026-01-01", valid_to="2026-12-31",
                         headers=None):
    """Submit a certification (born SUBMITTED). Default submitter analyst-1."""
    payload = create_certification_payload(
        cert_type=cert_type, certificate_number=certificate_number,
        valid_from=valid_from, valid_to=valid_to)
    return get_success_data(api_client.create_certification(
        supplier_id, payload, headers or ANALYST1))


def begin_review_certification(cert_id, headers=None):
    return get_success_data(
        api_client.begin_review_certification(cert_id, headers or ANALYST1))


def verify_certification(cert_id, headers=None):
    """Verify an UNDER_REVIEW certification. Default verifier admin-1 (never
    the default submitter analyst-1, so segregation of duties holds)."""
    return get_success_data(
        api_client.verify_certification(cert_id, headers or ADMIN1))


def import_spend(supplier_id, business_unit_id, amount_cents,
                 transaction_date="2026-02-01", payment_date="2026-02-01",
                 headers=None):
    """Import a POSTED spend record (DiversityAnalyst only)."""
    payload = create_spend_record_payload(
        supplier_id, business_unit_id, amount_cents=amount_cents,
        transaction_date=transaction_date, payment_date=payment_date)
    return get_success_data(
        api_client.create_spend_record(payload, headers or ANALYST1))


def set_clock(to_iso8601, headers=None):
    """Advance the logical clock (DiversityAdmin only); fires the expiration
    and activation sweeps at the new date."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or ADMIN1))


# ---------------------------------------------------------------------------
# Tier 2: certified suppliers (supplier + verified certification chain)
# ---------------------------------------------------------------------------

def create_supplier_with_verified_cert(
        legal_name="Diverse Parts Co", tax_id="T-100", kind="DIVERSE",
        cert_type="MBE", certificate_number="C-100",
        valid_from="2026-01-01", valid_to="2026-12-31",
        submitter_headers=None, verifier_headers=None):
    """Supplier + certification submitted by analyst-1, reviewed, verified by
    admin-1. With the default full-year window the supplier ends ACTIVE and
    diverse_eligible at the startup clock date. Returns (supplier, cert)."""
    supplier = create_supplier(legal_name=legal_name, tax_id=tax_id, kind=kind)
    cert = submit_certification(
        supplier["id"], cert_type=cert_type,
        certificate_number=certificate_number,
        valid_from=valid_from, valid_to=valid_to,
        headers=submitter_headers or ANALYST1)
    begin_review_certification(cert["id"], headers=submitter_headers or ANALYST1)
    cert = verify_certification(cert["id"], headers=verifier_headers or ADMIN1)
    supplier = get_success_data(api_client.get_supplier(supplier["id"], ADMIN1))
    return supplier, cert


def create_prime_supplier(legal_name="Prime Build Inc", tax_id="T-200"):
    """A PRIME-kind supplier (may file tier-2 reports). Returns the supplier."""
    return create_supplier(legal_name=legal_name, tax_id=tax_id, kind="PRIME",
                           contact_email="p@x.com")


# ---------------------------------------------------------------------------
# Tier 2: sourcing events and invitations
# ---------------------------------------------------------------------------

def create_sourcing_event(business_unit_id, title="Sourcing event",
                          estimated_value_cents=100000,
                          required_diverse_bidders=None, headers=None):
    """Create a DRAFT sourcing event. The default caller is lead-1, matching
    the default business unit's lead_user_id."""
    payload = create_sourcing_event_payload(
        business_unit_id, title=title,
        estimated_value_cents=estimated_value_cents)
    if required_diverse_bidders is not None:
        payload["required_diverse_bidders"] = required_diverse_bidders
    return get_success_data(
        api_client.create_sourcing_event(payload, headers or LEAD1))


def open_sourcing_event(event_id, headers=None):
    return get_success_data(
        api_client.open_sourcing_event(event_id, headers or LEAD1))


def invite_supplier(event_id, supplier_id, headers=None):
    """Invite a supplier to an OPEN event (born INVITED)."""
    return get_success_data(api_client.create_invitation(
        event_id, create_invitation_payload(supplier_id), headers or LEAD1))


def respond_invitation(invitation_id, response="BID_SUBMITTED", headers=None):
    return get_success_data(api_client.respond_invitation(
        invitation_id, respond_invitation_payload(response), headers or LEAD1))


def create_open_event_with_bidder(business_unit_id, supplier_id,
                                  title="Sourcing event",
                                  estimated_value_cents=100000,
                                  required_diverse_bidders=0, headers=None):
    """OPEN event + the supplier invited and BID_SUBMITTED.
    Returns (event, invitation)."""
    event = create_sourcing_event(
        business_unit_id, title=title,
        estimated_value_cents=estimated_value_cents,
        required_diverse_bidders=required_diverse_bidders, headers=headers)
    open_sourcing_event(event["id"], headers=headers)
    invitation = invite_supplier(event["id"], supplier_id, headers=headers)
    respond_invitation(invitation["id"], "BID_SUBMITTED", headers=headers)
    event = get_success_data(
        api_client.get_sourcing_event(event["id"], headers or LEAD1))
    return event, invitation


# ---------------------------------------------------------------------------
# Tier 2: tier-2 reports
# ---------------------------------------------------------------------------

def create_tier2_report(prime_supplier_id, business_unit_id,
                        reporting_period="2026-Q1", lines=None,
                        line_supplier_id=None, gross_subcontract_cents=100000,
                        diverse_share_pct=100.00):
    """Prime files a DRAFT tier-2 report for itself (ownership: X-User-ID is
    the prime supplier's id). Returns the report."""
    if lines is None:
        lines = [tier2_line(line_supplier_id or prime_supplier_id,
                            gross_subcontract_cents, diverse_share_pct)]
    payload = create_tier2_report_payload(
        prime_supplier_id, business_unit_id,
        reporting_period=reporting_period, lines=lines)
    return get_success_data(api_client.create_tier2_report(
        payload, make_prime_contact_headers(prime_supplier_id)))


def submit_tier2_report(report_id, prime_supplier_id):
    return get_success_data(api_client.submit_tier2_report(
        report_id, make_prime_contact_headers(prime_supplier_id)))


def approve_tier2_report(report_id, headers=None):
    return get_success_data(
        api_client.approve_tier2_report(report_id, headers or ADMIN1))


def create_approved_tier2_report(prime_supplier_id, business_unit_id,
                                 reporting_period="2026-Q1", lines=None,
                                 line_supplier_id=None,
                                 gross_subcontract_cents=100000,
                                 diverse_share_pct=100.00):
    """DRAFT -> SUBMITTED -> APPROVED. Returns the APPROVED report."""
    report = create_tier2_report(
        prime_supplier_id, business_unit_id, reporting_period=reporting_period,
        lines=lines, line_supplier_id=line_supplier_id,
        gross_subcontract_cents=gross_subcontract_cents,
        diverse_share_pct=diverse_share_pct)
    submit_tier2_report(report["id"], prime_supplier_id)
    return approve_tier2_report(report["id"])


# ---------------------------------------------------------------------------
# Tier 2: program goals and scorecards
# ---------------------------------------------------------------------------

def create_draft_goal(business_unit, fiscal_year=2026, cert_category="ALL",
                      goal_type="PERCENT_OF_SPEND", target_value=50.00,
                      include_tier2=None, headers=None):
    """Create a DRAFT goal, threading the business unit's current version into
    the OCC field. Default creator admin-1. Returns the goal."""
    payload = create_goal_payload(
        business_unit["version"], fiscal_year=fiscal_year,
        cert_category=cert_category, goal_type=goal_type,
        target_value=target_value)
    if include_tier2 is not None:
        payload["include_tier2"] = include_tier2
    return get_success_data(
        api_client.create_goal(business_unit["id"], payload,
                               headers or ADMIN1))


def create_and_publish_goal(business_unit, fiscal_year=2026,
                            cert_category="ALL", goal_type="PERCENT_OF_SPEND",
                            target_value=50.00, include_tier2=None):
    """DRAFT goal created by admin-1 and published by admin-2 (segregation of
    duties: publisher must differ from creator). Returns the PUBLISHED goal."""
    goal = create_draft_goal(
        business_unit, fiscal_year=fiscal_year, cert_category=cert_category,
        goal_type=goal_type, target_value=target_value,
        include_tier2=include_tier2, headers=ADMIN1)
    return get_success_data(api_client.publish_goal(goal["id"], ADMIN2))


def generate_scorecard(business_unit_id, reporting_period="2026-Q1",
                       attribution_basis="ACCRUAL", headers=None):
    """Generate a GENERATED scorecard snapshot for one quarter."""
    payload = generate_scorecard_payload(
        reporting_period=reporting_period, attribution_basis=attribution_basis)
    return get_success_data(api_client.generate_scorecard(
        business_unit_id, payload, headers or ANALYST1))


# ---------------------------------------------------------------------------
# Tier 2: development engagements and audit cases
# ---------------------------------------------------------------------------

def enroll_engagement(supplier_id, track="MENTORING", start_date="2026-03-01",
                      end_date="2026-06-30", mentor_name="Mentor A",
                      capacity_score_before=40, headers=None):
    """Enroll a supplier in a development track (born ENROLLED)."""
    payload = create_engagement_payload(
        track=track, start_date=start_date, end_date=end_date,
        mentor_name=mentor_name, capacity_score_before=capacity_score_before)
    return get_success_data(api_client.create_engagement(
        supplier_id, payload, headers or ANALYST1))


def open_audit_case(supplier_id, certification_id, reason="RANDOM_SAMPLE",
                    headers=None):
    """Open an OPEN audit case on a VERIFIED SELF_CERT certification. Default
    auditor auditor-9 (never the default verifier admin-1)."""
    payload = create_audit_case_payload(supplier_id, certification_id,
                                        reason=reason)
    return get_success_data(
        api_client.create_audit_case(payload, headers or AUDITOR9))


def record_audit_outcome(case_id, outcome, headers=None):
    return get_success_data(api_client.record_audit_outcome(
        case_id, record_outcome_payload(outcome), headers or AUDITOR9))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycles
# ---------------------------------------------------------------------------

def create_failed_audit_supplier(legal_name="Self Cert Co", tax_id="T-SCC",
                                 cert_valid_from="2026-01-01",
                                 cert_valid_to="2026-12-31"):
    """Supplier with a VERIFIED SELF_CERT certification plus an audit case
    recorded FAILED by auditor-9: the certification is REVOKED and the
    supplier is SUSPENDED by the revocation cascade.
    Returns (supplier, certification, audit_case)."""
    supplier, cert = create_supplier_with_verified_cert(
        legal_name=legal_name, tax_id=tax_id, cert_type="SELF_CERT",
        certificate_number="SC-1", valid_from=cert_valid_from,
        valid_to=cert_valid_to)
    case = open_audit_case(supplier["id"], cert["id"])
    record_audit_outcome(case["id"], "FAILED")
    supplier = get_success_data(api_client.get_supplier(supplier["id"], ADMIN1))
    return supplier, cert, case
