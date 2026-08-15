"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints,
using get_success_data() for lenient setup validation.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employee_payload,
    create_candidate_payload,
    create_requisition_payload,
    create_policy_payload,
    create_campaign_payload,
    create_referral_payload,
    create_payroll_batch_payload,
)
from .test_users import TEST_USERS, make_employee_headers, make_recruiter_headers, make_hiring_manager_headers


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_active_policy(**overrides):
    """Create + activate a policy version. Returns the activated policy dict."""
    ta = TEST_USERS["talent_admin_headers"]
    payload = create_policy_payload(**overrides)
    pol = get_success_data(api_client.create_policy_version(payload, ta))
    return get_success_data(api_client.activate_policy_version(pol["id"], ta))


def create_employee(**overrides):
    """Create an employee. Returns the employee dict."""
    pa = TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.create_employee(create_employee_payload(**overrides), pa))


def create_recruiter_employee(**overrides):
    """Create the standard TALENT recruiter actor (is_recruiter=true)."""
    overrides.setdefault("department", "TALENT")
    overrides.setdefault("is_recruiter", True)
    overrides.setdefault("email", "rec@corp.com")
    overrides.setdefault("employee_number", "E900")
    overrides.setdefault("full_name", "Rec Ru")
    return create_employee(**overrides)


def create_hiring_manager_employee(**overrides):
    """Create the standard PRODUCT hiring-manager actor."""
    overrides.setdefault("department", "PRODUCT")
    overrides.setdefault("job_level", "MANAGER")
    overrides.setdefault("email", "hm@corp.com")
    overrides.setdefault("employee_number", "E901")
    overrides.setdefault("full_name", "Hm Ha")
    return create_employee(**overrides)


def create_open_requisition(**overrides):
    """Create + open a requisition. Returns the OPEN requisition dict."""
    ta = TEST_USERS["talent_admin_headers"]
    req = get_success_data(api_client.create_requisition(create_requisition_payload(**overrides), ta))
    return get_success_data(api_client.open_requisition(req["id"], ta))


def create_candidate(**overrides):
    """Create a candidate. Returns the candidate dict."""
    ta = TEST_USERS["talent_admin_headers"]
    return get_success_data(api_client.create_candidate(create_candidate_payload(**overrides), ta))


def create_active_campaign(requisition_id, **overrides):
    """Create + activate a campaign over the given requisition. Returns the ACTIVE campaign."""
    ta = TEST_USERS["talent_admin_headers"]
    payload = create_campaign_payload(job_requisition_id=requisition_id, **overrides)
    camp = get_success_data(api_client.create_campaign(payload, ta))
    return get_success_data(api_client.activate_campaign(camp["id"], ta))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — program baseline
# ---------------------------------------------------------------------------

def setup_program(policy_overrides=None, req_overrides=None):
    """Active policy + recruiter + hiring-manager employees + one OPEN requisition.

    Returns dict with keys: policy, rec (recruiter employee), hm (hiring-manager
    employee), req (OPEN requisition).
    """
    policy = create_active_policy(**(policy_overrides or {}))
    rec = create_recruiter_employee()
    hm = create_hiring_manager_employee()
    req = create_open_requisition(**(req_overrides or {}))
    return {"policy": policy, "rec": rec, "hm": hm, "req": req}


def setup_verified_tax_profile(employee_id, **overrides):
    """PUT a tax profile as the employee + verify it. Returns the VERIFIED profile."""
    pp = TEST_USERS["payroll_processor_headers"]
    get_success_data(
        api_client.put_tax_profile(
            employee_id, create_profile_payload_or_default(**overrides), make_employee_headers(employee_id)
        )
    )
    return get_success_data(api_client.verify_tax_profile(employee_id, pp))


def create_profile_payload_or_default(**overrides):
    payload = {"filing_status": "SINGLE", "withholding_method": "FLAT"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — referral pipeline
# ---------------------------------------------------------------------------

def submit_referral(referrer_id, requisition_id, **overrides):
    """Submit a referral as the given referrer (Employee acting as self).
    Returns the referral dict."""
    payload = create_referral_payload(
        referrer_id=referrer_id, job_requisition_id=requisition_id, **overrides
    )
    return get_success_data(
        api_client.create_referral(payload, make_employee_headers(referrer_id))
    )


def advance_referral_to_offer(referral_id, rec_id, hm_id):
    """Walk a SUBMITTED referral through to OFFER_EXTENDED."""
    rec_h = make_recruiter_headers(rec_id)
    hm_h = make_hiring_manager_headers(hm_id)
    get_success_data(api_client.review_referral(referral_id, rec_h))
    get_success_data(api_client.qualify_referral(referral_id, rec_h))
    get_success_data(api_client.advance_referral(referral_id, {"to_state": "SCREENING"}, rec_h))
    get_success_data(api_client.advance_referral(referral_id, {"to_state": "INTERVIEWING"}, rec_h))
    return get_success_data(
        api_client.advance_referral(referral_id, {"to_state": "OFFER_EXTENDED"}, hm_h)
    )


def hire_referral(referral_id, hm_id, hire_date="2026-08-01T00:00:00Z"):
    """Hire an OFFER_EXTENDED referral. Returns the HIRED referral dict."""
    return get_success_data(
        api_client.hire_referral(referral_id, {"hire_date": hire_date}, make_hiring_manager_headers(hm_id))
    )


def create_hired_referral(program, referrer_id=None, candidate_email=None, req_id=None, hire_date="2026-08-01T00:00:00Z"):
    """Submit + walk a referral all the way to HIRED under the given program.
    Returns the HIRED referral dict."""
    referrer = referrer_id or create_employee()["id"]
    req = req_id or program["req"]["id"]
    payload_overrides = {}
    if candidate_email:
        payload_overrides["candidate_email"] = candidate_email
    ref = submit_referral(referrer, req, **payload_overrides)
    advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
    return hire_referral(ref["id"], program["hm"]["id"], hire_date=hire_date)


def get_hire_milestone(referral_id):
    """Fetch the HIRE milestone for a referral."""
    pp = TEST_USERS["payroll_processor_headers"]
    data = get_success_data(
        api_client.list_milestones(pp, params={"referral_id": referral_id, "kind": "HIRE"})
    )
    assert isinstance(data, list) and len(data) == 1, f"expected 1 HIRE milestone, got {data}"
    return data[0]


def get_retention_milestone(referral_id):
    """Fetch the RETENTION milestone for a referral."""
    pp = TEST_USERS["payroll_processor_headers"]
    data = get_success_data(
        api_client.list_milestones(pp, params={"referral_id": referral_id, "kind": "RETENTION"})
    )
    assert isinstance(data, list) and len(data) == 1, f"expected 1 RETENTION milestone, got {data}"
    return data[0]


def approve_milestone(milestone_id):
    pp = TEST_USERS["payroll_processor_headers"]
    return get_success_data(api_client.approve_milestone(milestone_id, pp))


def create_open_batch(period_label="2026-08A"):
    pp = TEST_USERS["payroll_processor_headers"]
    return get_success_data(api_client.create_payroll_batch(create_payroll_batch_payload(period_label=period_label), pp))


def add_milestone_to_batch(batch_id, milestone_id, batch_version):
    pp = TEST_USERS["payroll_processor_headers"]
    return get_success_data(
        api_client.add_milestone_to_batch(
            batch_id,
            {"milestone_id": milestone_id, "expected_payroll_batch_version": batch_version},
            pp,
        )
    )


def remove_milestone_from_batch(batch_id, milestone_id, batch_version):
    pp = TEST_USERS["payroll_processor_headers"]
    return get_success_data(
        api_client.remove_milestone_from_batch(
            batch_id, milestone_id, {"expected_payroll_batch_version": batch_version}, pp
        )
    )


def set_clock(to_iso8601):
    pa = TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, pa))


def ops_evaluate():
    ta = TEST_USERS["talent_admin_headers"]
    return get_success_data(api_client.ops_evaluate(ta))


def get_campaign(campaign_id):
    ta = TEST_USERS["talent_admin_headers"]
    return get_success_data(api_client.get_campaign(campaign_id, ta))


def get_referral(referral_id):
    ta = TEST_USERS["talent_admin_headers"]
    return get_success_data(api_client.get_referral(referral_id, ta))


def get_employee(employee_id):
    ta = TEST_USERS["talent_admin_headers"]
    return get_success_data(api_client.get_employee(employee_id, ta))


def get_batch(batch_id):
    pp = TEST_USERS["payroll_processor_headers"]
    return get_success_data(api_client.get_payroll_batch(batch_id, pp))


def get_milestone(milestone_id):
    pp = TEST_USERS["payroll_processor_headers"]
    return get_success_data(api_client.get_milestone(milestone_id, pp))


def list_employee_abuse_cases(employee_id):
    ta = TEST_USERS["talent_admin_headers"]
    return get_success_data(api_client.list_employee_abuse_cases(employee_id, ta))


def raise_abuse_case(employee_id, case_type, referral_id=None, raiser_headers=None, note=None):
    """Manually raise an abuse case. Defaults to TalentAdmin raiser 'ta-1'."""
    headers = raiser_headers or TEST_USERS["talent_admin_headers"]
    payload = {"employee_id": employee_id, "case_type": case_type}
    if referral_id is not None:
        payload["referral_id"] = referral_id
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_abuse_case(payload, headers))


def confirm_abuse_case(case_id, officer_headers=None, resolution_note=None):
    headers = officer_headers or TEST_USERS["compliance_officer_headers"]
    payload = {}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return get_success_data(api_client.confirm_abuse_case(case_id, headers, payload or None))


def setup_referrer_with_suspension(case_types=("RESUME_FARM", "DUPLICATE_RING", "MANUAL"), hire_date="2026-01-01T00:00:00Z"):
    """Employee with len(case_types) confirmed abuse cases -> risk high enough to suspend
    for the default weights (50+35+20=105). Returns the employee dict."""
    emp = create_employee(hire_date=hire_date)
    for ct in case_types:
        case = raise_abuse_case(emp["id"], ct)
        confirm_abuse_case(case["id"])
    return get_employee(emp["id"])
