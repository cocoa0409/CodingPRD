"""Composite setup helpers.

The harness restarts the API server before every individual test, so each
fixture below builds its preconditions from scratch through the endpoints the
PRD declares. Every helper uses the lenient success reader so a broken
precondition surfaces as a setup failure rather than as a confusing assertion.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    california_profile_payload,
    coventure_promotion_payload,
    disclosure_statement_payload,
    enforcement_action_payload,
    extension_request_payload,
    financial_statement_payload,
    fundraiser_registration_payload,
    fundraising_contract_payload,
    officer_disclosure_payload,
    organization_payload,
    professional_fundraiser_payload,
    registration_document_payload,
    solicitation_activity_payload,
    state_profile_payload,
    state_registration_payload,
)
from .test_users import (
    TEST_USERS,
    make_certifying_officer_headers,
    make_fundraiser_agent_headers,
)
from .types import (
    ActionType,
    AssuranceLevel,
    DocType,
    RegistrationType,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def move_clock_to(instant: str) -> Dict[str, Any]:
    """Move the server's logical clock to `instant` and return the echoed data."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


# --------------------------------------------------------------------------
# Tier 1 — single-row seeds
# --------------------------------------------------------------------------


def seed_state_profile(state_code: str = "CA", **overrides) -> Dict[str, Any]:
    """Seed a jurisdiction carrying only the six required fields plus overrides."""
    payload = state_profile_payload(state_code, **overrides)
    return get_success_data(api_client.create_state_profile(payload, ADMIN))


def seed_california_profile(**overrides) -> Dict[str, Any]:
    """Seed the fully-parameterised jurisdiction most filing scenarios use."""
    payload = california_profile_payload(**overrides)
    return get_success_data(api_client.create_state_profile(payload, ADMIN))


def create_organization(**overrides) -> Dict[str, Any]:
    payload = organization_payload(**overrides)
    return get_success_data(api_client.create_organization(payload, COMPLIANCE))


def read_organization(organization_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_organization(organization_id, COMPLIANCE))


def read_registration(registration_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_state_registration(registration_id, COMPLIANCE)
    )


def read_enforcement_action(action_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_enforcement_action(action_id, REGULATOR))


def read_promotion(promotion_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_coventure_promotion(promotion_id, COMPLIANCE))


def read_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_fundraising_contract(contract_id, COMPLIANCE))


def read_fundraiser(fundraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_professional_fundraiser(fundraiser_id, ADMIN)
    )


def list_financial_statements(organization_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_organization_financial_statements(
        organization_id, COMPLIANCE, params={"limit": 100}
    )
    return get_success_data(resp)


def create_financial_statement(
    organization: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """File a statement using the organization's currently observed version."""
    current = read_organization(organization["id"])
    payload = financial_statement_payload(
        organization["id"], current["version"], **overrides
    )
    return get_success_data(api_client.create_financial_statement(payload, COMPLIANCE))


def create_solicitation_activity(
    organization_id: str, state_code: str = "CA", **overrides
) -> Dict[str, Any]:
    payload = solicitation_activity_payload(organization_id, state_code, **overrides)
    return get_success_data(
        api_client.create_solicitation_activity(payload, COMPLIANCE)
    )


def create_disclosure_statement(
    organization_id: str, state_code: str = "CA", **overrides
) -> Dict[str, Any]:
    payload = disclosure_statement_payload(organization_id, state_code, **overrides)
    return get_success_data(api_client.create_disclosure_statement(payload, COMPLIANCE))


def create_officer(
    organization_id: str,
    officer_name: str = "Dana Reyes",
    title: str = "PRESIDENT",
    **overrides,
) -> Dict[str, Any]:
    payload = officer_disclosure_payload(
        organization_id, officer_name, title, **overrides
    )
    return get_success_data(api_client.create_officer_disclosure(payload, COMPLIANCE))


def create_officer_pair(organization_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """One certifying officer and one separate preparer, so that certification
    never collides with document preparation."""
    certifier = create_officer(
        organization_id, "Dana Reyes", "PRESIDENT", is_certifying_officer=True
    )
    preparer = create_officer(organization_id, "Sam Okoye", "SECRETARY")
    return certifier, preparer


# --------------------------------------------------------------------------
# Tier 2 — filings and their document sets
# --------------------------------------------------------------------------

REQUIRED_DOCS_BY_ATTESTATION: Dict[str, List[str]] = {
    AssuranceLevel.NONE.value: [
        DocType.GOVERNING_DOCUMENT.value,
        DocType.FINANCIAL_STATEMENT.value,
    ],
    AssuranceLevel.REVIEW.value: [
        DocType.GOVERNING_DOCUMENT.value,
        DocType.FINANCIAL_STATEMENT.value,
        DocType.REVIEW_REPORT.value,
    ],
    AssuranceLevel.AUDIT.value: [
        DocType.GOVERNING_DOCUMENT.value,
        DocType.FINANCIAL_STATEMENT.value,
        DocType.AUDIT_OPINION.value,
    ],
}

_DOC_PAGE_COUNTS: Dict[str, int] = {
    DocType.GOVERNING_DOCUMENT.value: 12,
    DocType.FINANCIAL_STATEMENT.value: 8,
    DocType.REVIEW_REPORT.value: 4,
    DocType.AUDIT_OPINION.value: 6,
}


def attach_document(
    registration_id: str,
    prepared_by_officer_id: str,
    doc_type: str = DocType.GOVERNING_DOCUMENT.value,
    page_count: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = registration_document_payload(
        registration_id,
        prepared_by_officer_id,
        doc_type,
        page_count if page_count is not None else _DOC_PAGE_COUNTS.get(doc_type, 5),
    )
    return get_success_data(
        api_client.create_registration_document(payload, headers or COMPLIANCE)
    )


def attach_required_documents(
    registration_id: str,
    prepared_by_officer_id: str,
    attestation: str = AssuranceLevel.REVIEW.value,
) -> List[Dict[str, Any]]:
    """Attach exactly the document set the filing's attestation requirement demands."""
    return [
        attach_document(registration_id, prepared_by_officer_id, doc_type)
        for doc_type in REQUIRED_DOCS_BY_ATTESTATION[attestation]
    ]


def open_filing(
    organization_id: str,
    financial_statement_id: str,
    state_code: str = "CA",
    registration_type: str = RegistrationType.INITIAL.value,
    **overrides,
) -> Dict[str, Any]:
    payload = state_registration_payload(
        organization_id,
        financial_statement_id,
        state_code,
        registration_type,
        **overrides,
    )
    return get_success_data(api_client.create_state_registration(payload, COMPLIANCE))


def submit_filing(registration_id: str, certifying_officer_id: str, **payload_extras):
    """Submit a packet as the certifying officer that owns it."""
    return api_client.submit_state_registration(
        registration_id,
        dict(payload_extras),
        make_certifying_officer_headers(certifying_officer_id),
    )


def approve_filing(registration_id: str):
    return api_client.review_state_registration(
        registration_id, {"decision": "APPROVE"}, REGULATOR
    )


def reject_filing(registration_id: str, reasons: List[str]):
    return api_client.review_state_registration(
        registration_id, {"decision": "DEFICIENT", "deficiency_reasons": reasons},
        REGULATOR,
    )


def setup_draft_filing(
    state_code: str = "CA",
    attestation: str = AssuranceLevel.REVIEW.value,
    profile_overrides: Optional[Dict[str, Any]] = None,
    organization_overrides: Optional[Dict[str, Any]] = None,
    statement_overrides: Optional[Dict[str, Any]] = None,
    registration_overrides: Optional[Dict[str, Any]] = None,
    attach_documents: bool = True,
) -> Dict[str, Any]:
    """Seed a jurisdiction, a charity, its statement, its officer roster, a DRAFT
    filing and (by default) the document set the filing's attestation demands.

    Returns a context dict with keys: profile, organization, financial_statement,
    certifier, preparer, registration, documents.
    """
    profile = seed_california_profile(
        state_code=state_code, **(profile_overrides or {})
    )
    organization = create_organization(
        domicile_state_code=state_code, **(organization_overrides or {})
    )
    statement = create_financial_statement(organization, **(statement_overrides or {}))
    certifier, preparer = create_officer_pair(organization["id"])
    registration = open_filing(
        organization["id"],
        statement["id"],
        state_code,
        **(registration_overrides or {}),
    )
    documents: List[Dict[str, Any]] = []
    if attach_documents:
        documents = attach_required_documents(
            registration["id"],
            preparer["id"],
            registration.get("required_financial_attestation", attestation),
        )
    return {
        "profile": profile,
        "organization": organization,
        "financial_statement": statement,
        "certifier": certifier,
        "preparer": preparer,
        "registration": registration,
        "documents": documents,
    }


def setup_submitted_filing(**kwargs) -> Dict[str, Any]:
    """setup_draft_filing plus a successful certification and submission."""
    ctx = setup_draft_filing(**kwargs)
    resp = submit_filing(ctx["registration"]["id"], ctx["certifier"]["id"])
    ctx["registration"] = get_success_data(resp)
    return ctx


def setup_registered_filing(**kwargs) -> Dict[str, Any]:
    """setup_submitted_filing plus the regulator's APPROVE decision."""
    ctx = setup_submitted_filing(**kwargs)
    ctx["registration"] = get_success_data(approve_filing(ctx["registration"]["id"]))
    ctx["organization"] = read_organization(ctx["organization"]["id"])
    return ctx


def setup_deficient_filing(
    reasons: Optional[List[str]] = None, **kwargs
) -> Dict[str, Any]:
    """setup_submitted_filing plus the regulator's DEFICIENT decision."""
    ctx = setup_submitted_filing(**kwargs)
    ctx["registration"] = get_success_data(
        reject_filing(ctx["registration"]["id"], reasons or ["MISSING_SCHEDULE_B"])
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 3 — fundraiser registry, contracts and promotions
# --------------------------------------------------------------------------


def create_fundraiser(**overrides) -> Dict[str, Any]:
    payload = professional_fundraiser_payload(**overrides)
    return get_success_data(api_client.create_professional_fundraiser(payload, ADMIN))


def register_fundraiser_in_state(
    fundraiser_id: str, state_code: str = "CA", **overrides
) -> Dict[str, Any]:
    """Register the firm in one state, acting as that firm's own agent."""
    payload = fundraiser_registration_payload(fundraiser_id, state_code, **overrides)
    return get_success_data(
        api_client.create_fundraiser_registration(
            payload, make_fundraiser_agent_headers(fundraiser_id)
        )
    )


def setup_registered_fundraiser(
    state_codes: Optional[List[str]] = None, **fundraiser_overrides
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a firm and give it an ACTIVE registration in each named state."""
    fundraiser = create_fundraiser(**fundraiser_overrides)
    registrations = [
        register_fundraiser_in_state(fundraiser["id"], code)
        for code in (state_codes or ["CA"])
    ]
    return read_fundraiser(fundraiser["id"]), registrations


def draft_contract(
    organization_id: str,
    fundraiser_id: str,
    state_codes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = fundraising_contract_payload(
        organization_id, fundraiser_id, state_codes, **overrides
    )
    return get_success_data(api_client.create_fundraising_contract(payload, COMPLIANCE))


def file_contract(contract_id: str, fundraiser_id: str):
    """File the contract as the firm's own agent."""
    return api_client.file_fundraising_contract(
        contract_id, {}, make_fundraiser_agent_headers(fundraiser_id)
    )


def setup_filed_contract(
    organization_id: str,
    state_codes: Optional[List[str]] = None,
    fundraiser_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Firm + state registrations + a contract driven to FILED.

    Returns a context dict with keys: fundraiser, fundraiser_registrations, contract.
    """
    codes = state_codes or ["CA"]
    fundraiser, registrations = setup_registered_fundraiser(
        codes, **(fundraiser_overrides or {})
    )
    contract = draft_contract(
        organization_id, fundraiser["id"], codes, **(contract_overrides or {})
    )
    contract = get_success_data(file_contract(contract["id"], fundraiser["id"]))
    return {
        "fundraiser": fundraiser,
        "fundraiser_registrations": registrations,
        "contract": contract,
    }


def draft_promotion(
    organization_id: str,
    coventurer_id: str,
    state_codes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = coventure_promotion_payload(
        organization_id, coventurer_id, state_codes, **overrides
    )
    return get_success_data(api_client.create_coventure_promotion(payload, COMPLIANCE))


def file_promotion(promotion_id: str):
    return api_client.file_coventure_promotion(promotion_id, {}, COMPLIANCE)


def activate_promotion(promotion_id: str):
    return api_client.activate_coventure_promotion(promotion_id, {}, COMPLIANCE)


def settle_promotion(
    promotion_id: str, certifying_officer_id: str, actual_units: int, remitted_cents: int
):
    return api_client.settle_coventure_promotion(
        promotion_id,
        {"actual_units": actual_units, "remitted_cents": remitted_cents},
        make_certifying_officer_headers(certifying_officer_id),
    )


def setup_filed_promotion(
    organization_id: str,
    state_codes: Optional[List[str]] = None,
    promotion_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A commercial co-venturer registered in every co-venture state, plus a
    promotion driven DRAFT -> FILED.

    Returns a context dict with keys: coventurer, promotion.
    """
    codes = state_codes or ["CA"]
    coventurer, _ = setup_registered_fundraiser(
        codes,
        legal_name="Sunrise Retail Group",
        fundraiser_type="COMMERCIAL_COVENTURER",
    )
    promotion = draft_promotion(
        organization_id, coventurer["id"], codes, **(promotion_overrides or {})
    )
    promotion = get_success_data(file_promotion(promotion["id"]))
    return {"coventurer": coventurer, "promotion": promotion}


def setup_active_promotion(
    organization_id: str,
    state_codes: Optional[List[str]] = None,
    promotion_overrides: Optional[Dict[str, Any]] = None,
    activate_at: str = "2026-09-15T00:00:00Z",
) -> Dict[str, Any]:
    """setup_filed_promotion, then move the clock inside the window and activate."""
    ctx = setup_filed_promotion(organization_id, state_codes, promotion_overrides)
    move_clock_to(activate_at)
    ctx["promotion"] = get_success_data(activate_promotion(ctx["promotion"]["id"]))
    return ctx


# --------------------------------------------------------------------------
# Tier 4 — enforcement, delinquency sweeps and extensions
# --------------------------------------------------------------------------


def run_sweep(state_code: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if state_code is not None:
        payload["state_code"] = state_code
    return get_success_data(api_client.run_compliance_sweep(payload, ADMIN))


def issue_enforcement_action(
    organization_id: str,
    registration_id: str,
    action_type: str = ActionType.PENALTY_ASSESSMENT.value,
    **overrides,
) -> Dict[str, Any]:
    payload = enforcement_action_payload(
        organization_id, registration_id, action_type, **overrides
    )
    return get_success_data(api_client.create_enforcement_action(payload, REGULATOR))


def remediate_action(action_id: str, note: str = "Corrective packet filed."):
    return api_client.remediate_enforcement_action(
        action_id, {"remediation_note": note}, COMPLIANCE
    )


def decide_action(action_id: str, decision: str):
    return api_client.decide_enforcement_action(action_id, {"decision": decision}, REGULATOR)


def vacate_action(action_id: str, reason: str = "Assessment issued in error."):
    return api_client.vacate_enforcement_action(
        action_id, {"vacate_reason": reason}, REGULATOR
    )


def setup_delinquent_filing(
    sweep_at: str = "2026-11-15T00:00:00Z", **filing_kwargs
) -> Dict[str, Any]:
    """A REGISTERED filing swept into DELINQUENCY at `sweep_at`.

    Returns the registered-filing context plus keys: sweep, enforcement_action.
    """
    ctx = setup_registered_filing(**filing_kwargs)
    move_clock_to(sweep_at)
    sweep = run_sweep()
    ctx["sweep"] = sweep
    ctx["registration"] = read_registration(ctx["registration"]["id"])
    ctx["organization"] = read_organization(ctx["organization"]["id"])
    action_ids = sweep.get("enforcement_action_ids") or []
    ctx["enforcement_action"] = (
        read_enforcement_action(action_ids[0]) if action_ids else None
    )
    return ctx


def setup_ceased_filing(
    sweep_at: str = "2026-11-15T00:00:00Z",
    escalate_at: str = "2026-12-20T00:00:00Z",
    **filing_kwargs,
) -> Dict[str, Any]:
    """A filing swept delinquent, then escalated so the filing sits in CEASED and
    the charity's solicitation posture has moved.

    Returns the delinquent context with `enforcement_action` refreshed.
    """
    ctx = setup_delinquent_filing(sweep_at=sweep_at, **filing_kwargs)
    action = ctx["enforcement_action"]
    move_clock_to(escalate_at)
    ctx["enforcement_action"] = get_success_data(decide_action(action["id"], "ESCALATE"))
    ctx["registration"] = read_registration(ctx["registration"]["id"])
    ctx["organization"] = read_organization(ctx["organization"]["id"])
    return ctx


def request_extension(
    registration_id: str,
    expected_registration_version: int,
    basis: str = "IRS_990_EXTENSION",
    requested_days: int = 5,
    **overrides,
) -> Dict[str, Any]:
    payload = extension_request_payload(
        registration_id, expected_registration_version, basis, requested_days, **overrides
    )
    return get_success_data(api_client.create_extension_request(payload, COMPLIANCE))


def decide_extension(extension_request_id: str, decision: str):
    return api_client.decide_extension_request(
        extension_request_id, {"decision": decision}, REGULATOR
    )


def setup_granted_extension(**filing_kwargs) -> Dict[str, Any]:
    """A DRAFT filing carrying one GRANTED extension request.

    Returns the draft-filing context plus keys: extension_request.
    """
    ctx = setup_draft_filing(**filing_kwargs)
    registration = ctx["registration"]
    request = request_extension(registration["id"], registration["version"])
    ctx["extension_request"] = get_success_data(decide_extension(request["id"], "GRANT"))
    ctx["registration"] = read_registration(registration["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 5 — multi-state and cross-jurisdiction scenarios
# --------------------------------------------------------------------------


def setup_two_state_charity(
    domicile: str = "CA",
    second_state: str = "FL",
    second_profile_overrides: Optional[Dict[str, Any]] = None,
    **filing_kwargs,
) -> Dict[str, Any]:
    """A charity with a REGISTERED filing in its domicile state and a second
    jurisdiction seeded so a second filing can be opened there.

    Returns the registered-filing context plus keys: second_profile.
    """
    ctx = setup_registered_filing(state_code=domicile, **filing_kwargs)
    ctx["second_profile"] = seed_california_profile(
        state_code=second_state, **(second_profile_overrides or {})
    )
    return ctx


def setup_two_registered_filings(
    domicile: str = "CA",
    second_state: str = "NV",
    second_coverage: Tuple[str, str] = ("2025-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    **filing_kwargs,
) -> Dict[str, Any]:
    """Two REGISTERED filings for one charity, one per state.

    Returns the first context plus keys: second_profile, second_registration.
    """
    ctx = setup_two_state_charity(domicile, second_state, **filing_kwargs)
    second = open_filing(
        ctx["organization"]["id"],
        ctx["financial_statement"]["id"],
        second_state,
        coverage_start=second_coverage[0],
        coverage_end=second_coverage[1],
    )
    attach_required_documents(
        second["id"], ctx["preparer"]["id"], second["required_financial_attestation"]
    )
    second = get_success_data(submit_filing(second["id"], ctx["certifier"]["id"]))
    ctx["second_registration"] = get_success_data(approve_filing(second["id"]))
    ctx["organization"] = read_organization(ctx["organization"]["id"])
    return ctx
