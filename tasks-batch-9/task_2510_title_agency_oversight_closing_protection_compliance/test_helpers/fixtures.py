"""Setup helpers and pytest fixtures.

The harness restarts the server before every individual test, so every fixture
here builds its world from scratch through the PRD's own endpoints. Nothing is
seeded out of band.

The onboarding preamble is the same in almost every workflow, and it has to run
in the PRD's order: an appointment can only be verified once the agency's
financial review is `ACCEPTED` (Section 3.2), and the agency can only be
appointed once it holds at least one `ACTIVE` state appointment (Section 3.1).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories
from .api_client import ApiClient, api_client
from .constants import DEFAULT_CLOCK_UTC
from .test_users import TEST_USERS, make_agency_principal_headers

# ---------------------------------------------------------------------------
# Canonical operator headers used by the setup helpers
# ---------------------------------------------------------------------------

OFFICER = TEST_USERS["compliance_officer_headers"]
ANALYST = TEST_USERS["licensing_analyst_headers"]
AUDITOR = TEST_USERS["escrow_auditor_headers"]
COUNSEL = TEST_USERS["underwriting_counsel_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock. Only a `ComplianceOfficer` may do this."""
    return validate_success(api.set_clock(current_utc, OFFICER))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    return set_clock(api, DEFAULT_CLOCK_UTC)


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------


def create_state_program(api: ApiClient, **overrides) -> Dict[str, Any]:
    payload = factories.create_state_program_payload(**overrides)
    return validate_success(api.create_state_program(payload, OFFICER), 201)


def create_agency(api: ApiClient, **overrides) -> Dict[str, Any]:
    payload = factories.create_agency_payload(**overrides)
    return validate_success(api.create_agency(payload, ANALYST), 201)


def read_agency(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    return validate_success(api.get_agency(agency_id, OFFICER))


def agency_version(api: ApiClient, agency_id: str) -> int:
    """The agency's current `version`, for the three OCC-guarded creates."""
    return read_agency(api, agency_id)["version"]


def submit_financial_review(api: ApiClient, agency_id: str, **overrides) -> Dict[str, Any]:
    payload = factories.financial_review_payload(**overrides)
    return validate_success(
        api.submit_financial_review(
            agency_id, payload, make_agency_principal_headers(agency_id)
        )
    )


def decide_financial_review(
    api: ApiClient, agency_id: str, decision: str = "ACCEPT", **overrides
) -> Dict[str, Any]:
    payload = factories.financial_review_decision_payload(decision, **overrides)
    return validate_success(api.decide_financial_review(agency_id, payload, ANALYST))


def accept_financial_review(api: ApiClient, agency_id: str, **overrides) -> Dict[str, Any]:
    """Submit the financial package and accept it, mirroring onto the effective fields."""
    submit_financial_review(api, agency_id, **overrides)
    return decide_financial_review(api, agency_id, "ACCEPT")


def create_appointment(
    api: ApiClient, agency_id: str, state_program_id: str, **overrides
) -> Dict[str, Any]:
    payload = factories.create_appointment_payload(
        agency_id, state_program_id, **overrides
    )
    return validate_success(api.create_appointment(payload, ANALYST), 201)


def verify_license(api: ApiClient, appointment_id: str, **overrides) -> Dict[str, Any]:
    payload = factories.license_verification_payload("VERIFY", **overrides)
    return validate_success(api.verify_license(appointment_id, payload, ANALYST))


def lapse_license(api: ApiClient, appointment_id: str) -> Dict[str, Any]:
    payload = factories.license_verification_payload("LAPSE")
    return validate_success(api.verify_license(appointment_id, payload, ANALYST))


def decide_appointment(
    api: ApiClient, agency_id: str, decision: str, headers=None, **overrides
) -> Dict[str, Any]:
    payload = factories.appointment_decision_payload(decision, **overrides)
    if headers is None:
        headers = OFFICER if decision == "TERMINATE" else ANALYST
    return validate_success(api.decide_appointment(agency_id, payload, headers))


def appoint_agency(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    return decide_appointment(api, agency_id, "APPOINT")


def suspend_agency(api: ApiClient, agency_id: str, reason: str = "escrow concern"):
    return decide_appointment(api, agency_id, "SUSPEND", reason=reason)


def reinstate_agency(api: ApiClient, agency_id: str, reason: str = "cleared"):
    return decide_appointment(api, agency_id, "REINSTATE", reason=reason)


def terminate_agency(
    api: ApiClient,
    agency_id: str,
    termination_reason: str = "FOR_CAUSE",
    transferee_agency_id: Optional[str] = None,
) -> Dict[str, Any]:
    extra: Dict[str, Any] = {"termination_reason": termination_reason}
    if transferee_agency_id is not None:
        extra["transferee_agency_id"] = transferee_agency_id
    return decide_appointment(api, agency_id, "TERMINATE", headers=OFFICER, **extra)


# ---------------------------------------------------------------------------
# The onboarding preamble
# ---------------------------------------------------------------------------


@dataclass
class AgencyEnv:
    """An appointed agency with one verified state appointment."""

    agency: Dict[str, Any]
    state_program: Dict[str, Any]
    appointment: Dict[str, Any] = field(default_factory=dict)

    @property
    def agency_id(self) -> str:
        return self.agency["id"]

    @property
    def state_program_id(self) -> str:
        return self.state_program["id"]

    @property
    def appointment_id(self) -> str:
        return self.appointment["id"]

    @property
    def principal(self) -> Dict[str, str]:
        """Headers whose `X-User-ID` is this agency's own id (PRD §2.1)."""
        return make_agency_principal_headers(self.agency_id)


def onboard_agency(
    api: ApiClient,
    state_program: Optional[Dict[str, Any]] = None,
    agency_overrides: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    appointment_overrides: Optional[Dict[str, Any]] = None,
    verification_overrides: Optional[Dict[str, Any]] = None,
    appoint: bool = True,
) -> AgencyEnv:
    """Register, fund, license and appoint one agency in one state.

    The resulting agency reaches `OPEN` posture when `appoint` is true.
    """
    program = state_program if state_program is not None else create_state_program(api)
    agency = create_agency(api, **(agency_overrides or {}))
    accept_financial_review(api, agency["id"], **(review_overrides or {}))
    appointment = create_appointment(
        api, agency["id"], program["id"], **(appointment_overrides or {})
    )
    appointment = verify_license(
        api, appointment["id"], **(verification_overrides or {})
    )
    if appoint:
        agency = appoint_agency(api, agency["id"])
    else:
        agency = read_agency(api, agency["id"])
    return AgencyEnv(agency=agency, state_program=program, appointment=appointment)


def refresh(api: ApiClient, env: AgencyEnv) -> Dict[str, Any]:
    """Re-read the agency onto the env and return it."""
    env.agency = read_agency(api, env.agency_id)
    return env.agency


# ---------------------------------------------------------------------------
# Closing protection letters
# ---------------------------------------------------------------------------


def request_letter(api: ApiClient, env: AgencyEnv, **overrides) -> Dict[str, Any]:
    payload = factories.request_letter_payload(
        env.agency_id,
        env.state_program_id,
        overrides.pop("expected_agency_version", None)
        or agency_version(api, env.agency_id),
        **overrides,
    )
    return validate_success(api.request_letter(payload, env.principal), 201)


def transition_letter(
    api: ApiClient, cpl_id: str, to_state: str, headers, **overrides
) -> Dict[str, Any]:
    payload = factories.letter_state_payload(to_state, **overrides)
    return validate_success(api.transition_letter(cpl_id, payload, headers))


def issue_letter(api: ApiClient, env: AgencyEnv, **overrides) -> Dict[str, Any]:
    """Request a letter and release it through whichever branch it landed on."""
    letter = request_letter(api, env, **overrides)
    headers = COUNSEL if letter["status"] == "REFERRED" else OFFICER
    return transition_letter(api, letter["id"], "ISSUED", headers)


def void_letter(api: ApiClient, cpl_id: str, void_reason: str = "closing cancelled"):
    return transition_letter(api, cpl_id, "VOIDED", OFFICER, void_reason=void_reason)


# ---------------------------------------------------------------------------
# Policy files
# ---------------------------------------------------------------------------


def create_policy_file(api: ApiClient, env: AgencyEnv, **overrides) -> Dict[str, Any]:
    payload = factories.create_policy_file_payload(
        env.agency_id,
        env.state_program_id,
        overrides.pop("expected_agency_version", None)
        or agency_version(api, env.agency_id),
        **overrides,
    )
    return validate_success(api.create_policy_file(payload, env.principal), 201)


def approve_referral(
    api: ApiClient, policy_file_id: str, approved_liability_cents: int, headers=None
) -> Dict[str, Any]:
    """`PENDING_REFERRAL` to `PENDING`, the counsel's approval (PRD §3.4)."""
    payload = factories.issuance_state_payload(
        "PENDING", approved_liability_cents=approved_liability_cents
    )
    return validate_success(
        api.transition_issuance(policy_file_id, payload, headers or COUNSEL)
    )


def decline_referral(api: ApiClient, policy_file_id: str, headers=None) -> Dict[str, Any]:
    payload = factories.issuance_state_payload("ISSUANCE_DECLINED")
    return validate_success(
        api.transition_issuance(policy_file_id, payload, headers or COUNSEL)
    )


def issue_policy(
    api: ApiClient,
    env: AgencyEnv,
    policy_file_id: str,
    policy_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Move a `PENDING` file to issuance as its own `AgencyPrincipal`."""
    payload = factories.issuance_state_payload(
        "ISSUED", policy_number=policy_number or factories.next_policy_number()
    )
    return validate_success(
        api.transition_issuance(policy_file_id, payload, env.principal)
    )


def create_issued_policy(
    api: ApiClient, env: AgencyEnv, policy_number: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    """Open a file that needs no referral and issue it immediately."""
    policy_file = create_policy_file(api, env, **overrides)
    return issue_policy(api, env, policy_file["id"], policy_number)


def transition_transfer(
    api: ApiClient, policy_file_id: str, to_state: str, **overrides
) -> Dict[str, Any]:
    payload = factories.transfer_state_payload(to_state, **overrides)
    return validate_success(api.transition_transfer(policy_file_id, payload, OFFICER))


# ---------------------------------------------------------------------------
# Remittance
# ---------------------------------------------------------------------------


def create_statement(
    api: ApiClient,
    env: AgencyEnv,
    period_start: str = "2026-07-01",
    period_end: str = "2026-07-31",
    **overrides,
) -> Dict[str, Any]:
    payload = factories.create_statement_payload(
        env.agency_id,
        period_start,
        period_end,
        overrides.pop("expected_agency_version", None)
        or agency_version(api, env.agency_id),
        **overrides,
    )
    return validate_success(api.create_statement(payload, env.principal), 201)


def add_line(
    api: ApiClient,
    env: AgencyEnv,
    statement_id: str,
    policy_file_id: str,
    reported_gross_premium_cents: int,
    **overrides,
) -> Dict[str, Any]:
    payload = factories.create_line_payload(
        policy_file_id, reported_gross_premium_cents, **overrides
    )
    return validate_success(
        api.create_line(statement_id, payload, env.principal), 201
    )


def submit_statement(api: ApiClient, env: AgencyEnv, statement_id: str) -> Dict[str, Any]:
    payload = factories.statement_state_payload("SUBMITTED")
    return validate_success(
        api.transition_statement(statement_id, payload, env.principal)
    )


def reconcile_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    payload = factories.statement_state_payload("RECONCILED")
    return validate_success(api.transition_statement(statement_id, payload, OFFICER))


def settle_statement(
    api: ApiClient, statement_id: str, settled_amount_cents: int
) -> Dict[str, Any]:
    payload = factories.statement_state_payload(
        "SETTLED", settled_amount_cents=settled_amount_cents
    )
    return validate_success(api.transition_statement(statement_id, payload, OFFICER))


def reopen_statement(
    api: ApiClient, statement_id: str, reopen_reason: str = "agency correction"
) -> Dict[str, Any]:
    payload = factories.statement_state_payload("DRAFT", reopen_reason=reopen_reason)
    return validate_success(api.transition_statement(statement_id, payload, OFFICER))


def statement_lines(api: ApiClient, statement_id: str, params=None) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api.list_lines(statement_id, OFFICER, params=params))
    return rows


# ---------------------------------------------------------------------------
# Escrow accounts, audits and findings
# ---------------------------------------------------------------------------


def create_escrow_account(api: ApiClient, env: AgencyEnv, **overrides) -> Dict[str, Any]:
    payload = factories.create_escrow_account_payload(env.agency_id, **overrides)
    return validate_success(api.create_escrow_account(payload, env.principal), 201)


def post_snapshot(
    api: ApiClient, env: AgencyEnv, account_id: str, **overrides
) -> Dict[str, Any]:
    payload = factories.balance_snapshot_payload(**overrides)
    return validate_success(
        api.post_balance_snapshot(account_id, payload, env.principal)
    )


def create_audit(
    api: ApiClient, env: AgencyEnv, account_id: str, headers=None, **overrides
) -> Dict[str, Any]:
    payload = factories.create_escrow_audit_payload(
        env.agency_id, account_id, **overrides
    )
    return validate_success(api.create_escrow_audit(payload, headers or AUDITOR), 201)


def submit_audit(api: ApiClient, audit_id: str, headers=None) -> Dict[str, Any]:
    payload = factories.audit_state_payload("SUBMITTED")
    return validate_success(api.transition_audit(audit_id, payload, headers or AUDITOR))


def review_audit(api: ApiClient, audit_id: str, **overrides) -> Dict[str, Any]:
    payload = factories.audit_state_payload("UNDER_REVIEW", **overrides)
    return validate_success(api.transition_audit(audit_id, payload, OFFICER))


def require_remediation(api: ApiClient, audit_id: str, **overrides) -> Dict[str, Any]:
    payload = factories.audit_state_payload("REMEDIATION_REQUIRED", **overrides)
    return validate_success(api.transition_audit(audit_id, payload, OFFICER))


def close_audit(
    api: ApiClient, audit_id: str, to_state: str, headers=None, **overrides
) -> Dict[str, Any]:
    """Close an audit. SoD-1 forbids the opener, so a distinct actor closes."""
    payload = factories.audit_state_payload(to_state, **overrides)
    return validate_success(api.transition_audit(audit_id, payload, headers or OFFICER))


def create_finding(
    api: ApiClient, audit_id: str, code: str, exposure_cents: int, **overrides
) -> Dict[str, Any]:
    payload = factories.create_finding_payload(code, exposure_cents, **overrides)
    return validate_success(api.create_finding(audit_id, payload, AUDITOR), 201)


def audit_findings(api: ApiClient, audit_id: str, params=None) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api.list_findings(audit_id, OFFICER, params=params))
    return rows


def submit_remediation(
    api: ApiClient,
    env: AgencyEnv,
    finding_id: str,
    remediation_note: str = "funds restored",
    **overrides,
) -> Dict[str, Any]:
    payload = factories.finding_state_payload(
        "REMEDIATION_SUBMITTED", remediation_note=remediation_note, **overrides
    )
    return validate_success(
        api.transition_finding(finding_id, payload, env.principal)
    )


def clear_finding(api: ApiClient, finding_id: str, **overrides) -> Dict[str, Any]:
    payload = factories.finding_state_payload("CLEARED", **overrides)
    return validate_success(api.transition_finding(finding_id, payload, OFFICER))


def escalate_finding(api: ApiClient, finding_id: str, **overrides) -> Dict[str, Any]:
    payload = factories.finding_state_payload("ESCALATED", **overrides)
    return validate_success(api.transition_finding(finding_id, payload, OFFICER))


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def create_claim(
    api: ApiClient, env: AgencyEnv, policy_file_id: str, **overrides
) -> Dict[str, Any]:
    payload = factories.create_claim_payload(env.agency_id, policy_file_id, **overrides)
    return validate_success(api.create_claim(payload, OFFICER), 201)


def transition_claim(
    api: ApiClient, claim_id: str, to_state: str, headers=None, **overrides
) -> Dict[str, Any]:
    payload = factories.claim_state_payload(to_state, **overrides)
    return validate_success(api.transition_claim(claim_id, payload, headers or COUNSEL))


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> ApiClient:
    return api_client


@pytest.fixture
def compliance_officer_headers() -> Dict[str, str]:
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers() -> Dict[str, str]:
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def licensing_analyst_headers() -> Dict[str, str]:
    return TEST_USERS["licensing_analyst_headers"]


@pytest.fixture
def escrow_auditor_headers() -> Dict[str, str]:
    return TEST_USERS["escrow_auditor_headers"]


@pytest.fixture
def second_escrow_auditor_headers() -> Dict[str, str]:
    return TEST_USERS["second_escrow_auditor_headers"]


@pytest.fixture
def underwriting_counsel_headers() -> Dict[str, str]:
    return TEST_USERS["underwriting_counsel_headers"]


@pytest.fixture
def second_underwriting_counsel_headers() -> Dict[str, str]:
    return TEST_USERS["second_underwriting_counsel_headers"]


@pytest.fixture
def unowned_agency_principal_headers() -> Dict[str, str]:
    """An `AgencyPrincipal` identity that owns nothing (probes only)."""
    return TEST_USERS["agency_principal_headers"]


@pytest.fixture
def state_program(api: ApiClient) -> Dict[str, Any]:
    return create_state_program(api)


@pytest.fixture
def env(api: ApiClient, state_program: Dict[str, Any]) -> AgencyEnv:
    """An appointed agency at `OPEN` posture with one `ACTIVE` appointment."""
    return onboard_agency(api, state_program=state_program)


@pytest.fixture
def escrow_env(api: ApiClient, env: AgencyEnv):
    """The appointed agency plus one open escrow account with a clean snapshot."""
    account = create_escrow_account(api, env)
    post_snapshot(api, env, account["id"])
    return env, validate_success(api.get_escrow_account(account["id"], OFFICER))
