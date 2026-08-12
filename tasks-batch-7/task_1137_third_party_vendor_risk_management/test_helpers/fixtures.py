"""Composite setup helpers (fixtures) for the TPRM test suite.

Every helper builds its preconditions from scratch against a freshly booted
server (the runner restarts the API before every test) and sets the logical
clock to the deterministic boot instant before doing anything else.

Segregation-of-duties threading used throughout:
- DD packages are submitted by the default VendorRelationshipManager user and
  approved by the default RiskOfficer user (different X-User-ID values).
- Remediation plans are owned by the default RiskOfficer user and approved by
  a second RiskOfficer user ("test-ro-approver-1"), so the approver differs
  from both the plan owner and the incident reporter.
- Incident verification/reopen is performed with BusinessUnitOwner headers
  carrying the incident's reported_by_user_id.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BOOT_ISO, SEVERITY_WINDOW_DAYS
from .factories import (
    create_audit_finding_payload,
    create_audit_payload,
    create_bcp_test_payload,
    create_concentration_assessment_payload,
    create_contract_payload,
    create_dd_package_payload,
    create_engagement_payload,
    create_incident_payload,
    create_remediation_plan_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_business_owner_headers, make_risk_officer_headers

VRM = TEST_USERS["vrm_headers"]
RO = TEST_USERS["risk_officer_headers"]
RO_APPROVER = make_risk_officer_headers("test-ro-approver-1")
BUO = TEST_USERS["business_owner_headers"]
AUDITOR = TEST_USERS["internal_auditor_headers"]
DIRECTOR = TEST_USERS["compliance_director_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (accepts trailing 'Z' or offset form)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso_after_days(base_iso: str, days: int) -> datetime:
    return parse_iso_instant(base_iso) + timedelta(days=days)


def reset_clock(iso: str = CLOCK_BOOT_ISO):
    """Pin the logical clock to a deterministic instant."""
    get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: vendors, engagements, DD packages
# ---------------------------------------------------------------------------

def create_vendor(name="Test Vendor", region="NA", category="BPO", **overrides):
    payload = create_vendor_payload(
        legal_name=name, headquarters_region=region, service_category=category, **overrides
    )
    return get_success_data(api_client.create_vendor(payload, VRM))


def get_vendor(vendor_id):
    return get_success_data(api_client.get_vendor(vendor_id, RO))


def tier_change_vendor(vendor_id, to_tier, reason="reclassification"):
    current = get_vendor(vendor_id)
    return get_success_data(
        api_client.tier_change_vendor(
            vendor_id,
            {
                "to_tier": to_tier,
                "reason": reason,
                "expected_vendor_version": current["version"],
            },
            RO,
        )
    )


def create_engagement(vendor_id, code="ENG-001", spend=100_000, sensitivity="INTERNAL", **overrides):
    payload = create_engagement_payload(
        engagement_code=code,
        annual_spend_cents=spend,
        data_sensitivity=sensitivity,
        **overrides,
    )
    return get_success_data(api_client.create_engagement(vendor_id, payload, VRM))


def get_engagement(engagement_id):
    return get_success_data(api_client.get_engagement(engagement_id, RO))


def create_dd_package(engagement_id, fin=90, sec=90, comp=90, reviewer_tag="rev"):
    payload = create_dd_package_payload(
        financial_review_score=fin,
        security_review_score=sec,
        compliance_review_score=comp,
        financial_reviewer_id=f"u_fin_{reviewer_tag}",
        security_reviewer_id=f"u_sec_{reviewer_tag}",
        compliance_reviewer_id=f"u_comp_{reviewer_tag}",
    )
    return get_success_data(api_client.create_dd_package(engagement_id, payload, VRM))


def submit_dd_package(package_id, submitter_headers=None):
    return get_success_data(
        api_client.submit_dd_package(package_id, submitter_headers or VRM)
    )


def approve_dd_package(package_id, engagement_id, approver_headers=None):
    """begin-review + approve with a fresh OCC read of the engagement version."""
    get_success_data(api_client.begin_review_dd_package(package_id, RO))
    engagement = get_engagement(engagement_id)
    return get_success_data(
        api_client.approve_dd_package(
            package_id,
            {"expected_engagement_version": engagement["version"]},
            approver_headers or RO,
        )
    )


def setup_engagement_with_approved_dd(
    vendor_name="DD Vendor",
    region="NA",
    category="BPO",
    engagement_code="DD-E1",
    spend=100_000,
    sensitivity="INTERNAL",
    fin=90,
    sec=90,
    comp=90,
    reviewer_tag="rev",
):
    """Vendor (ONBOARDING) + engagement walked to DD_APPROVED. Returns dict."""
    reset_clock()
    vendor = create_vendor(name=vendor_name, region=region, category=category)
    engagement = create_engagement(
        vendor["id"], code=engagement_code, spend=spend, sensitivity=sensitivity
    )
    package = create_dd_package(engagement["id"], fin=fin, sec=sec, comp=comp, reviewer_tag=reviewer_tag)
    submit_dd_package(package["id"])
    package = approve_dd_package(package["id"], engagement["id"])
    engagement = get_engagement(engagement["id"])
    return {"vendor": vendor, "engagement": engagement, "package": package}


# ---------------------------------------------------------------------------
# Tier 3: contracts and full activation
# ---------------------------------------------------------------------------

def create_contract(engagement_id, reference="CTR-001", **overrides):
    payload = create_contract_payload(contract_reference=reference, **overrides)
    return get_success_data(api_client.create_contract(engagement_id, payload, VRM))


def execute_contract(contract_id, engagement_id):
    engagement = get_engagement(engagement_id)
    return get_success_data(
        api_client.execute_contract(
            contract_id, {"expected_engagement_version": engagement["version"]}, RO
        )
    )


def setup_active_engagement(
    vendor_name="ActiveEng Vendor",
    region="NA",
    category="BPO",
    engagement_code="ACT-E1",
    spend=100_000,
    sensitivity="INTERNAL",
    fin=90,
    sec=90,
    comp=90,
    vendor_tier=None,
    contract_overrides=None,
    reviewer_tag="rev",
):
    """Vendor + engagement walked to ACTIVE (contract EXECUTED).

    The vendor itself remains ONBOARDING (vendor activation is a separate
    RiskOfficer step). Returns dict with vendor, engagement, package, contract.
    """
    reset_clock()
    vendor = create_vendor(name=vendor_name, region=region, category=category)
    if vendor_tier is not None:
        vendor = tier_change_vendor(vendor["id"], vendor_tier)
    engagement = create_engagement(
        vendor["id"], code=engagement_code, spend=spend, sensitivity=sensitivity
    )
    package = create_dd_package(engagement["id"], fin=fin, sec=sec, comp=comp, reviewer_tag=reviewer_tag)
    submit_dd_package(package["id"])
    package = approve_dd_package(package["id"], engagement["id"])
    contract = create_contract(engagement["id"], **(contract_overrides or {}))
    contract = execute_contract(contract["id"], engagement["id"])
    engagement = get_engagement(engagement["id"])
    return {
        "vendor": get_vendor(vendor["id"]),
        "engagement": engagement,
        "package": package,
        "contract": contract,
    }


def setup_active_vendor(**kwargs):
    """setup_active_engagement + vendor activation. Adds first monitoring cycle."""
    ctx = setup_active_engagement(**kwargs)
    vendor = get_success_data(api_client.activate_vendor(ctx["vendor"]["id"], RO))
    ctx["vendor"] = vendor
    cycles, _meta = _list_cycles(vendor["id"])
    ctx["cycles"] = cycles
    return ctx


def _list_cycles(vendor_id):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_monitoring_cycles(vendor_id, RO))


def list_cycles(vendor_id):
    return _list_cycles(vendor_id)


# ---------------------------------------------------------------------------
# Tier 3: incidents and remediation lifecycle
# ---------------------------------------------------------------------------

def file_incident(engagement_id, severity="SEV_3", incident_type="OUTAGE",
                  detected_at="2026-05-02T00:00:00Z", reporter_headers=None):
    payload = create_incident_payload(
        incident_type=incident_type, severity=severity, detected_at=detected_at
    )
    return get_success_data(
        api_client.create_incident(engagement_id, payload, reporter_headers or BUO)
    )


def triage_incident(incident_id):
    return get_success_data(api_client.triage_incident(incident_id, RO))


def get_incident(incident_id):
    return get_success_data(api_client.get_incident(incident_id, RO))


def remediate_incident_to_closed(incident_id, committed="2026-05-05T00:00:00Z",
                                 evidence="s3://evidence/fix"):
    """Drive an incident TRIAGED -> ... -> CLOSED through the full plan flow.

    Plan owner is the default RiskOfficer user; the approver is a second
    RiskOfficer user so the approver differs from both owner and reporter.
    Verification is performed with BusinessUnitOwner headers carrying the
    incident's reported_by_user_id.
    """
    incident = get_incident(incident_id)
    reporter_id = incident["reported_by_user_id"]
    plan = get_success_data(
        api_client.create_remediation_plan(
            incident_id,
            create_remediation_plan_payload(committed_completion_date=committed),
            RO,
        )
    )
    get_success_data(api_client.submit_remediation_plan(plan["id"], RO))
    get_success_data(api_client.approve_remediation_plan(plan["id"], RO_APPROVER))
    get_success_data(
        api_client.submit_verification(plan["id"], {"verification_evidence_uri": evidence}, RO)
    )
    verifier = make_business_owner_headers(reporter_id)
    plan = get_success_data(api_client.verify_remediation_plan(plan["id"], verifier))
    return plan


def setup_closed_incident(severity="SEV_4", vendor_tier=None, committed="2026-05-05T00:00:00Z",
                          contract_overrides=None, vendor_name="ClosedInc Vendor"):
    """Active engagement + one incident driven to CLOSED. Returns context dict."""
    ctx = setup_active_engagement(
        vendor_name=vendor_name, vendor_tier=vendor_tier, contract_overrides=contract_overrides
    )
    incident = file_incident(ctx["engagement"]["id"], severity=severity)
    triage_incident(incident["id"])
    remediate_incident_to_closed(incident["id"], committed=committed)
    ctx["incident"] = get_incident(incident["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: audits
# ---------------------------------------------------------------------------

def setup_audit_in_fieldwork(scope="SECURITY", vendor_name="Audit Vendor"):
    """Active engagement whose contract carries the right-to-audit clause,
    plus one audit walked INITIATED -> FIELDWORK. Returns context dict."""
    ctx = setup_active_engagement(
        vendor_name=vendor_name,
        sensitivity="REGULATED",
        contract_overrides={"has_right_to_audit_clause": True},
    )
    audit = get_success_data(
        api_client.create_audit(ctx["engagement"]["id"], create_audit_payload(scope=scope), AUDITOR)
    )
    get_success_data(api_client.begin_audit_fieldwork(audit["id"], AUDITOR))
    ctx["audit"] = get_success_data(api_client.get_audit(audit["id"], AUDITOR))
    return ctx


def attach_finding(audit_id, severity="SEV_3", description="Finding narrative"):
    return get_success_data(
        api_client.create_audit_finding(
            audit_id, create_audit_finding_payload(severity=severity, description=description), AUDITOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: concentration assessments
# ---------------------------------------------------------------------------

def create_assessment(window_start="2026-05-01T00:00:00Z",
                      window_end="2026-06-01T00:00:00Z",
                      dimension="REGION"):
    return get_success_data(
        api_client.create_concentration_assessment(
            create_concentration_assessment_payload(
                assessment_window_start=window_start,
                assessment_window_end=window_end,
                grouping_dimension=dimension,
            ),
            DIRECTOR,
        )
    )


def publish_assessment(assessment_id):
    return get_success_data(api_client.publish_concentration_assessment(assessment_id, DIRECTOR))


def list_buckets(assessment_id):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_concentration_buckets(assessment_id, DIRECTOR))
