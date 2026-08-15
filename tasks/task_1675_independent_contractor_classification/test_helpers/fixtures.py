"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls use get_success_data() (lenient)
so a setup failure surfaces as a clear "Setup failed" error, not a confusing
assertion failure deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import APPROVAL_SEQUENCE, TEST_DEFAULTS
from .factories import (
    FAVORABLE_ANSWERS,
    create_amendment_payload,
    create_audit_payload,
    create_contract_payload,
    create_contractor_payload,
    create_conversion_payload,
    create_engagement_payload,
    create_exception_payload,
    create_filing_payload,
    create_inquiry_payload,
    create_jurisdiction_payload,
    create_remediation_action_payload,
    create_review_payload,
    make_answers,
)
from .test_users import APPROVER_USER_IDS, TEST_USERS

_ADMIN = TEST_USERS["platform_admin_headers"]
_MANAGER = TEST_USERS["engagement_manager_headers"]
_ANALYST = TEST_USERS["classification_analyst_headers"]
_OFFICER = TEST_USERS["compliance_officer_headers"]
_TAX = TEST_USERS["tax_reporting_specialist_headers"]
_LIAISON = TEST_USERS["agency_liaison_headers"]


def _setup_failed(step: str, res) -> AssertionError:
    return AssertionError(f"Setup failed at {step}: {res.status_code} {res.text}")


# ─── Atomic steps ───────────────────────────────────

def create_jurisdiction(**overrides) -> dict:
    res = api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("create_jurisdiction", res)
    return get_success_data(res)


def create_contractor(**overrides) -> dict:
    res = api_client.create_contractor(create_contractor_payload(**overrides), _MANAGER)
    if res.status_code >= 400:
        raise _setup_failed("create_contractor", res)
    return get_success_data(res)


def verify_contractor(contractor_id: str, outcome: str = "VERIFIED") -> dict:
    res = api_client.verify_contractor(contractor_id, {"outcome": outcome}, _OFFICER)
    if res.status_code >= 400:
        raise _setup_failed(f"verify_contractor({outcome})", res)
    return get_success_data(res)


def create_verified_contractor(**overrides) -> dict:
    contractor = create_contractor(**overrides)
    return verify_contractor(contractor["id"], "VERIFIED")


def create_engagement(contractor_id: str, jurisdiction_id: str, **overrides) -> dict:
    res = api_client.create_engagement(
        create_engagement_payload(contractor_id, jurisdiction_id, **overrides), _MANAGER
    )
    if res.status_code >= 400:
        raise _setup_failed("create_engagement", res)
    return get_success_data(res)


def get_engagement(engagement_id: str) -> dict:
    res = api_client.get_engagement(engagement_id, _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("get_engagement", res)
    return get_success_data(res)


def get_contractor(contractor_id: str) -> dict:
    res = api_client.get_contractor(contractor_id, _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("get_contractor", res)
    return get_success_data(res)


def get_contract(contract_id: str) -> dict:
    res = api_client.get_contract(contract_id, _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("get_contract", res)
    return get_success_data(res)


def get_audit(audit_id: str) -> dict:
    res = api_client.get_audit(audit_id, _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("get_audit", res)
    return get_success_data(res)


def get_filing(filing_id: str) -> dict:
    res = api_client.get_filing(filing_id, _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("get_filing", res)
    return get_success_data(res)


def submit_questionnaire(engagement_id: str, answers: list = None) -> dict:
    res = api_client.submit_questionnaire(
        engagement_id, {"answers": answers if answers is not None else make_answers()}, _MANAGER
    )
    if res.status_code >= 400:
        raise _setup_failed("submit_questionnaire", res)
    return get_success_data(res)


def run_determination(engagement_id: str) -> dict:
    """OCC-guarded classification test run against the engagement's live version."""
    engagement = get_engagement(engagement_id)
    res = api_client.create_determination(
        engagement_id,
        {"expected_engagement_version": engagement["version"]},
        _ANALYST,
    )
    if res.status_code >= 400:
        raise _setup_failed("run_determination", res)
    return get_success_data(res)


def submit_for_review(engagement_id: str) -> dict:
    res = api_client.submit_review(engagement_id, _MANAGER)
    if res.status_code >= 400:
        raise _setup_failed("submit_review", res)
    return get_success_data(res)


def submit_for_approval(engagement_id: str) -> dict:
    res = api_client.submit_approval(engagement_id, _ANALYST)
    if res.status_code >= 400:
        raise _setup_failed("submit_approval", res)
    return get_success_data(res)


def record_approval(engagement_id: str, role: str, user_id: str = None) -> dict:
    from prd_bench_local_runner.testing import build_user_headers

    headers = build_user_headers(user_id or APPROVER_USER_IDS[role], role)
    res = api_client.approve_engagement(engagement_id, headers)
    if res.status_code >= 400:
        raise _setup_failed(f"approve({role})", res)
    return get_success_data(res)


def grant_exception(engagement_id: str, **overrides) -> dict:
    res = api_client.create_exception(
        engagement_id,
        create_exception_payload(**overrides),
        TEST_USERS["compliance_board_member_headers"],
    )
    if res.status_code >= 400:
        raise _setup_failed("grant_exception", res)
    return get_success_data(res)


def create_contract(engagement_id: str, **overrides) -> dict:
    res = api_client.create_contract(
        engagement_id, create_contract_payload(**overrides), _MANAGER
    )
    if res.status_code >= 400:
        raise _setup_failed("create_contract", res)
    return get_success_data(res)


def execute_contract(contract_id: str) -> dict:
    res = api_client.execute_contract(contract_id, _MANAGER)
    if res.status_code >= 400:
        raise _setup_failed("execute_contract", res)
    return get_success_data(res)


def propose_amendment(contract_id: str, **overrides) -> dict:
    """Propose an amendment against the contract's live version (OCC)."""
    contract = get_contract(contract_id)
    res = api_client.create_amendment(
        contract_id,
        create_amendment_payload(contract["version"], **overrides),
        _MANAGER,
    )
    if res.status_code >= 400:
        raise _setup_failed("propose_amendment", res)
    return get_success_data(res)


def activate_engagement(engagement_id: str) -> dict:
    res = api_client.activate_engagement(engagement_id, _MANAGER)
    if res.status_code >= 400:
        raise _setup_failed("activate_engagement", res)
    return get_success_data(res)


def set_clock(to_iso8601: str) -> None:
    res = api_client.set_clock(to_iso8601, _ADMIN)
    if res.status_code >= 400:
        raise _setup_failed("set_clock", res)


# ─── Composite: engagement pipeline ─────────────────

def setup_engagement_at_state(
    target: str = "ACTIVE",
    *,
    jurisdiction_overrides: dict = None,
    contractor_overrides: dict = None,
    engagement_overrides: dict = None,
    answers: list = None,
    with_exception: bool = False,
    exception_overrides: dict = None,
    contract_overrides: dict = None,
    verify: bool = True,
) -> dict:
    """
    Drive one engagement through the pipeline to `target`.

    target in: DRAFT, INTAKE_SUBMITTED, CLASSIFIED, UNDER_REVIEW,
    APPROVAL_PENDING, APPROVED, ACTIVE, SUSPENDED, TERMINATED.

    The approval quorum is read from the engagement after the determination
    (risk_tier fixes required_approval_count per PRD §3.4); when the quorum is
    HIGH (3), an ACTIVE exception grant is created before the final approval
    unless one was already requested via with_exception.

    Returns dict with keys: jurisdiction, contractor, engagement (freshly read
    at `target`), determination, exception (or None), contract (or None).
    """
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    contractor = create_contractor(**(contractor_overrides or {}))
    engagement = create_engagement(
        contractor["id"], jurisdiction["id"], **(engagement_overrides or {})
    )
    result = {
        "jurisdiction": jurisdiction,
        "contractor": contractor,
        "engagement": engagement,
        "questionnaire": None,
        "determination": None,
        "exception": None,
        "contract": None,
    }
    if target == "DRAFT":
        return result

    result["questionnaire"] = submit_questionnaire(engagement["id"], answers)
    if target == "INTAKE_SUBMITTED":
        result["engagement"] = get_engagement(engagement["id"])
        return result

    result["determination"] = run_determination(engagement["id"])
    if target == "CLASSIFIED":
        result["engagement"] = get_engagement(engagement["id"])
        return result

    submit_for_review(engagement["id"])
    if target == "UNDER_REVIEW":
        result["engagement"] = get_engagement(engagement["id"])
        return result

    submit_for_approval(engagement["id"])
    if target == "APPROVAL_PENDING":
        result["engagement"] = get_engagement(engagement["id"])
        return result

    pending = get_engagement(engagement["id"])
    required = pending["required_approval_count"]
    if required == 3 or with_exception:
        result["exception"] = grant_exception(
            engagement["id"], **(exception_overrides or {})
        )
    for role in APPROVAL_SEQUENCE[:required]:
        record_approval(engagement["id"], role)
    if target == "APPROVED":
        result["engagement"] = get_engagement(engagement["id"])
        return result

    if verify:
        verify_contractor(contractor["id"])
    contract = create_contract(engagement["id"], **(contract_overrides or {}))
    result["contract"] = execute_contract(contract["id"])
    result["engagement"] = activate_engagement(engagement["id"])
    if target == "ACTIVE":
        return result

    if target == "SUSPENDED":
        res = api_client.suspend_engagement(engagement["id"], _OFFICER)
        if res.status_code >= 400:
            raise _setup_failed("suspend_engagement", res)
        result["engagement"] = get_success_data(res)
        result["contract"] = get_contract(result["contract"]["id"])
        return result

    if target == "TERMINATED":
        res = api_client.terminate_engagement(engagement["id"], _OFFICER)
        if res.status_code >= 400:
            raise _setup_failed("terminate_engagement", res)
        result["engagement"] = get_success_data(res)
        result["contract"] = get_contract(result["contract"]["id"])
        return result

    raise ValueError(f"Unknown target state: {target}")


def setup_high_tier_engagement(
    target: str = "ACTIVE",
    *,
    jurisdiction_overrides: dict = None,
    contractor_overrides: dict = None,
    engagement_overrides: dict = None,
    exception_overrides: dict = None,
    contract_overrides: dict = None,
) -> dict:
    """HIGH-tier chain: ABC_TEST jurisdiction + CONTROL_METHOD=YES answers.

    The ABC prong A failure flips the outcome to EMPLOYEE_RISK (PRD §3.1),
    which fixes risk_tier HIGH and a three-step quorum (PRD §3.4); an ACTIVE
    exception grant backs the final approval and contract execution (PRD §3.5/§3.6).
    """
    jurisdiction_overrides = {"code": "US-CA", "test_type": "ABC_TEST",
                              "state_filing_threshold_cents": 0,
                              **(jurisdiction_overrides or {})}
    return setup_engagement_at_state(
        target,
        jurisdiction_overrides=jurisdiction_overrides,
        contractor_overrides=contractor_overrides,
        engagement_overrides=engagement_overrides,
        answers=make_answers(CONTROL_METHOD="YES"),
        with_exception=True,
        exception_overrides=exception_overrides,
        contract_overrides=contract_overrides,
    )


# ─── Composite: audits, remediation ─────────────────

def create_audit(contractor_id: str, engagement_id: str = None,
                 audit_type: str = "FIELDWORK") -> dict:
    payload = create_audit_payload(contractor_id, audit_type=audit_type)
    if engagement_id is not None:
        payload["engagement_id"] = engagement_id
    res = api_client.create_audit(payload, _OFFICER)
    if res.status_code >= 400:
        raise _setup_failed("create_audit", res)
    return get_success_data(res)


def finalize_audit(audit_id: str, fieldwork_events: list = None,
                   findings_summary: str = "Findings recorded") -> dict:
    res = api_client.finalize_audit(
        audit_id,
        {"fieldwork_events": fieldwork_events or [],
         "findings_summary": findings_summary},
        _OFFICER,
    )
    if res.status_code >= 400:
        raise _setup_failed("finalize_audit", res)
    return get_success_data(res)


def create_remediation_action(audit_id: str, **overrides) -> dict:
    res = api_client.create_remediation_action(
        audit_id, create_remediation_action_payload(**overrides), _OFFICER
    )
    if res.status_code >= 400:
        raise _setup_failed("create_remediation_action", res)
    return get_success_data(res)


def close_remediation_action(action_id: str, outcome: str = "CLOSED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    res = api_client.close_remediation_action(action_id, payload, _OFFICER)
    if res.status_code >= 400:
        raise _setup_failed("close_remediation_action", res)
    return get_success_data(res)


# ─── Composite: filings ─────────────────────────────

def create_filing(contractor_id: str, jurisdiction_id: str, tax_year: int = None,
                  line_items: list = None, **overrides) -> dict:
    res = api_client.create_filing(
        create_filing_payload(
            contractor_id, jurisdiction_id, tax_year=tax_year,
            payment_line_items=line_items, **overrides,
        ),
        _TAX,
    )
    if res.status_code >= 400:
        raise _setup_failed("create_filing", res)
    return get_success_data(res)


def submit_filing(filing_id: str) -> dict:
    res = api_client.submit_filing(filing_id, _TAX)
    if res.status_code >= 400:
        raise _setup_failed("submit_filing", res)
    return get_success_data(res)


def setup_contractor_with_filing(
    *,
    verify: bool = True,
    line_items: list = None,
    tax_year: int = None,
    jurisdiction_overrides: dict = None,
    contractor_overrides: dict = None,
) -> dict:
    """Contractor (+ optional verification) and one DRAFT 1099 filing."""
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {
        "code": "US-CA", "test_type": "ABC_TEST", "state_filing_threshold_cents": 0,
    }))
    contractor = create_contractor(**(contractor_overrides or {}))
    if verify:
        contractor = verify_contractor(contractor["id"])
    filing = create_filing(
        contractor["id"], jurisdiction["id"], tax_year=tax_year, line_items=line_items
    )
    return {"jurisdiction": jurisdiction, "contractor": contractor, "filing": filing}


# ─── Composite: inquiries & conversions ─────────────

def create_inquiry(engagement_id: str, **overrides) -> dict:
    res = api_client.create_inquiry(
        engagement_id, create_inquiry_payload(**overrides), _LIAISON
    )
    if res.status_code >= 400:
        raise _setup_failed("create_inquiry", res)
    return get_success_data(res)


def create_conversion(engagement_id: str, lookback_quarters: list = None) -> dict:
    res = api_client.create_conversion(
        engagement_id, create_conversion_payload(lookback_quarters), _OFFICER
    )
    if res.status_code >= 400:
        raise _setup_failed("create_conversion", res)
    return get_success_data(res)


def extend_offer(conversion_id: str, offer_salary_cents: int = 12000000) -> dict:
    res = api_client.extend_offer(
        conversion_id, {"offer_salary_cents": offer_salary_cents},
        TEST_USERS["hr_approver_headers"],
    )
    if res.status_code >= 400:
        raise _setup_failed("extend_offer", res)
    return get_success_data(res)
