"""Composite setup helpers.

Multi-step arrangement sequences used across the suite: license-type policy,
role-requirement matrix rows, employees, licenses walked to ACTIVE via primary-
source verification, validated CE activity tallies, renewal requests in mid-
pipeline states, disciplinary suspensions, exclusion screenings, audit packages,
and logical-clock positioning.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PE_TYPE_PAYLOAD, RN_TYPE_PAYLOAD
from .factories import (
    create_audit_package_payload,
    create_ce_activity_payload,
    create_disciplinary_event_payload,
    create_employee_payload,
    create_exclusion_screening_payload,
    create_license_payload,
    create_license_type_payload,
    create_renewal_request_payload,
    create_role_requirement_payload,
    create_verification_payload,
)
from .test_users import TEST_USERS, make_officer_headers

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER2 = TEST_USERS["officer2_headers"]
HR = TEST_USERS["hr_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_license_type(payload=None, **overrides):
    """Create a license type. Defaults to the RN RECEIPT_BASED policy."""
    if payload is None:
        payload = create_license_type_payload(**overrides)
    resp = api_client.create_license_type(payload, ADMIN)
    return get_success_data(resp, 201)


def create_pe_license_type(**overrides):
    """Create a PE FLAT_SCHEDULE license type."""
    resp = api_client.create_license_type(
        create_license_type_payload(**{**PE_TYPE_PAYLOAD, **overrides}), ADMIN)
    return get_success_data(resp, 201)


def create_employee(**overrides):
    resp = api_client.create_employee(create_employee_payload(**overrides), HR)
    return get_success_data(resp, 201)


def create_role_requirement(license_type_id, role_code="STAFF_NURSE",
                            state_code="CA", is_required=True):
    resp = api_client.create_role_requirement(
        create_role_requirement_payload(
            role_code=role_code, license_type_id=license_type_id,
            state_code=state_code, is_required=is_required),
        ADMIN)
    return get_success_data(resp, 201)


def create_license(employee_id, license_type_id, state_code="CA",
                   license_number=None, issued_on="2026-01-01",
                   expires_on="2027-06-30"):
    payload = create_license_payload(
        employee_id=employee_id, license_type_id=license_type_id,
        state_code=state_code, issued_on=issued_on, expires_on=expires_on)
    if license_number is not None:
        payload["license_number"] = license_number
    resp = api_client.create_license(payload, OFFICER)
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 2: verification / state progression
# ---------------------------------------------------------------------------

def verify_license(license_id, verified_on="2026-08-01", source="STATE_BOARD_API",
                   outcome="VERIFIED", headers=None, **extra):
    payload = create_verification_payload(
        verified_on=verified_on, source=source, outcome=outcome, **extra)
    resp = api_client.verify_license(license_id, payload, headers or OFFICER)
    return get_success_data(resp, 200)


def create_active_license(employee_id, license_type_id, state_code="CA",
                          license_number=None, issued_on="2026-01-01",
                          expires_on="2027-06-30", verified_on="2026-08-01",
                          source="STATE_BOARD_API"):
    """Register a license and promote it to ACTIVE via a VERIFIED event."""
    lic = create_license(employee_id, license_type_id, state_code=state_code,
                         license_number=license_number, issued_on=issued_on,
                         expires_on=expires_on)
    verify_license(lic["id"], verified_on=verified_on, source=source)
    return get_success_data(api_client.get_license(lic["id"], OFFICER))


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 2: CE activities and tallies
# ---------------------------------------------------------------------------

def create_ce_activity(license_id, headers=None, **overrides):
    resp = api_client.create_ce_activity(
        license_id, create_ce_activity_payload(**overrides), headers or OFFICER)
    return get_success_data(resp, 201)


def create_validated_ce_activity(license_id, headers=None, **overrides):
    """Log an activity and validate it so it accrues to the tallies."""
    activity = create_ce_activity(license_id, headers=headers, **overrides)
    resp = api_client.validate_ce_activity(activity["id"], OFFICER)
    return get_success_data(resp, 200)


def setup_license_with_cycle_hours(employee_id, license_type_id,
                                   hour_triples, state_code="CA",
                                   issued_on="2026-01-01",
                                   expires_on="2026-12-31",
                                   verified_on="2026-08-01",
                                   completed_on="2026-06-01"):
    """ACTIVE license carrying exactly sum(round(h)) VALIDATED cycle hours.

    hour_triples: iterable of raw hour values, one activity each.
    Returns the license dict (re-read after the last validation).
    """
    lic = create_active_license(
        employee_id, license_type_id, state_code=state_code,
        issued_on=issued_on, expires_on=expires_on, verified_on=verified_on)
    for hours in hour_triples:
        create_validated_ce_activity(lic["id"], hours=hours,
                                     completed_on=completed_on)
    return get_success_data(api_client.get_license(lic["id"], OFFICER))


# ---------------------------------------------------------------------------
# Tier 3: renewal-request lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_renewal_request(license_id, claimed_amount_cents=50_000,
                           headers=None, license_version=None):
    """Create a DRAFT renewal request under the OCC guard.

    When license_version is not supplied, the live version is re-read first.
    Returns the created request dict.
    """
    if license_version is None:
        license_version = get_success_data(
            api_client.get_license(license_id, OFFICER))["version"]
    payload = create_renewal_request_payload(
        claimed_amount_cents=claimed_amount_cents,
        expected_license_version=license_version)
    resp = api_client.create_renewal_request(license_id, payload,
                                             headers or OFFICER)
    return get_success_data(resp, 201)


def submit_renewal_request(request_id, headers=None):
    resp = api_client.submit_renewal_request(request_id, headers or OFFICER)
    return get_success_data(resp, 200)


def create_submitted_request(license_id, claimed_amount_cents=50_000,
                             submitter_headers=None, create_headers=None):
    """DRAFT -> SUBMITTED. Returns the submitted request dict."""
    rr = create_renewal_request(license_id, claimed_amount_cents,
                                headers=create_headers)
    return submit_renewal_request(rr["id"], headers=submitter_headers or OFFICER)


def approve_renewal_request(request_id, approver_headers=None):
    resp = api_client.approve_renewal_request(
        request_id, approver_headers or make_officer_headers("officer-2"))
    return get_success_data(resp, 200)


def create_approved_request(license_id, claimed_amount_cents=50_000,
                            submitter_headers=None, approver_headers=None):
    """DRAFT -> SUBMITTED -> APPROVED with SoD-compliant distinct officers."""
    rr = create_submitted_request(
        license_id, claimed_amount_cents,
        submitter_headers=submitter_headers or make_officer_headers("officer-1"))
    return approve_renewal_request(
        rr["id"], approver_headers or make_officer_headers("officer-2"))


def create_paid_request(license_id, claimed_amount_cents=50_000,
                        submitter_headers=None, approver_headers=None,
                        payment_ref="PAY-1"):
    """DRAFT -> SUBMITTED -> APPROVED -> PAID. Returns the paid request dict."""
    rr = create_approved_request(license_id, claimed_amount_cents,
                                 submitter_headers=submitter_headers,
                                 approver_headers=approver_headers)
    resp = api_client.mark_paid_renewal_request(rr["id"], payment_ref, HR)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 3: disciplinary events and license sanctions
# ---------------------------------------------------------------------------

def create_disciplinary_event(license_id, headers=None, **overrides):
    resp = api_client.create_disciplinary_event(
        license_id, create_disciplinary_event_payload(**overrides),
        headers or OFFICER)
    return get_success_data(resp, 201)


def confirm_disciplinary_event(event_id, headers=None):
    resp = api_client.confirm_disciplinary_event(
        event_id, headers or make_officer_headers("officer-2"))
    return get_success_data(resp, 200)


def create_confirmed_suspension(license_id, board_case_number="B-SUSP",
                                effective_on="2026-08-01",
                                recorder_headers=None, confirmer_headers=None):
    """Record + confirm a SUSPENSION; the license drops ACTIVE -> SUSPENDED."""
    event = create_disciplinary_event(
        license_id,
        headers=recorder_headers or make_officer_headers("officer-1"),
        board_case_number=board_case_number, event_type="SUSPENSION",
        effective_on=effective_on)
    confirm_disciplinary_event(
        event["id"], headers=confirmer_headers or make_officer_headers("officer-2"))
    return event


def create_revoked_license(employee_id, license_type_id, state_code="CA",
                           board_case_number="B-REV", **license_kwargs):
    """ACTIVE license driven to REVOKED via a confirmed REVOCATION event."""
    lic = create_active_license(employee_id, license_type_id,
                                state_code=state_code, **license_kwargs)
    event = create_disciplinary_event(
        lic["id"], headers=make_officer_headers("officer-1"),
        board_case_number=board_case_number, event_type="REVOCATION",
        effective_on="2026-08-01")
    confirm_disciplinary_event(event["id"],
                               headers=make_officer_headers("officer-2"))
    return get_success_data(api_client.get_license(lic["id"], OFFICER))


# ---------------------------------------------------------------------------
# Tier 3: exclusion screenings
# ---------------------------------------------------------------------------

def create_exclusion_screening(employee_id, headers=None, **overrides):
    resp = api_client.create_exclusion_screening(
        employee_id, create_exclusion_screening_payload(**overrides),
        headers or OFFICER)
    return get_success_data(resp, 201)


def create_confirmed_match_screening(employee_id, list_source="OIG_LEIE",
                                     screened_on="2026-08-01",
                                     creator_headers=None, resolver_headers=None):
    """FLAGGED screening confirmed to CONFIRMED_MATCH (posture FLAGGED)."""
    scr = create_exclusion_screening(
        employee_id,
        headers=creator_headers or make_officer_headers("officer-1"),
        list_source=list_source, screened_on=screened_on, outcome="FLAGGED")
    resp = api_client.confirm_match_exclusion_screening(
        scr["id"], resolver_headers or make_officer_headers("officer-2"))
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 4: audit packages
# ---------------------------------------------------------------------------

def create_audit_package(employee_id, period_start="2026-08-01",
                         period_end="2026-09-01"):
    resp = api_client.create_audit_package(
        employee_id,
        create_audit_package_payload(period_start=period_start,
                                     period_end=period_end),
        AUDITOR)
    return get_success_data(resp, 201)


def seal_audit_package(package_id):
    resp = api_client.seal_audit_package(package_id, AUDITOR)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 5: composite scenarios shared across multiple tests
# ---------------------------------------------------------------------------

def setup_rn_type_with_staff_nurse_requirement(state_code="CA"):
    """RN license type + a mandatory STAFF_NURSE/RN/<state> requirement row."""
    lt = create_license_type()
    create_role_requirement(lt["id"], role_code="STAFF_NURSE",
                            state_code=state_code, is_required=True)
    return lt


def setup_nurse_with_active_license(requirement=True, email=None,
                                    expires_on="2027-06-30",
                                    issued_on="2026-01-01",
                                    verified_on="2026-08-01",
                                    license_number=None):
    """RN type, optional STAFF_NURSE/RN/CA requirement, employee, ACTIVE license.

    Returns (license_type, employee, license) with the license re-read after
    verification.
    """
    lt = create_license_type()
    if requirement:
        create_role_requirement(lt["id"], role_code="STAFF_NURSE",
                                state_code="CA", is_required=True)
    emp_kwargs = {"role_code": "STAFF_NURSE"}
    if email:
        emp_kwargs["work_email"] = email
    emp = create_employee(**emp_kwargs)
    lic = create_active_license(emp["id"], lt["id"], state_code="CA",
                                license_number=license_number,
                                issued_on=issued_on, expires_on=expires_on,
                                verified_on=verified_on)
    return lt, emp, lic
