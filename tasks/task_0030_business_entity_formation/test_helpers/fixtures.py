"""Composite setup helpers for the business-entity-formation benchmark.

Every fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each test starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so a setup failure surfaces
as a clear "Setup failed" trace rather than a cryptic assertion deep inside a test.

Identity threading (PRD §2.1): the Filer role is entity_backed:BusinessEntity, so
every ownership-gated Filer call uses make_filer_headers(business_entity["id"]),
NOT the shared TEST_USERS["filer_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_business_entity_payload,
    create_registered_agent_payload,
    create_operating_agreement_payload,
    create_ein_application_payload,
    create_annual_report_payload,
    create_foreign_qualification_payload,
    create_boi_disclosure_payload,
    issue_ein_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_filer_headers,
)


_STATE_ADMIN_HEADERS = TEST_USERS["state_admin_headers"]
_COMPLIANCE_OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]
_ANON_HEADERS = TEST_USERS["anonymous_headers"]


# ─── Tier 0: clock control (PRD §2.9) ──────────────────────────


def set_clock(iso8601: str) -> None:
    """Pin server's current clock UTC to the given ISO 8601 string (PRD §2.9)."""
    res = api_client.set_clock(set_clock_payload(iso8601), _STATE_ADMIN_HEADERS)
    get_success_data(res)


# ─── Tier 1: bare BusinessEntity creation ──────────────────────


def create_forming_business_entity(
    legal_name: str | None = None,
    entity_type: str = "LLC",
    formation_state_code: str = "DE",
    revenue_band: str | None = "ZERO",
) -> dict:
    """Create a BusinessEntity in FORMING (PRD §3.1). No prerequisites needed."""
    res = api_client.create_business_entity(
        create_business_entity_payload(
            legal_name=legal_name,
            entity_type=entity_type,
            formation_state_code=formation_state_code,
            revenue_band=revenue_band,
        ),
        _ANON_HEADERS,
    )
    return get_success_data(res)


def _get_business_entity(be_id: str) -> dict:
    """Read-back helper to refresh BusinessEntity (e.g., to observe version drift)."""
    res = api_client.get_business_entity(be_id, _COMPLIANCE_OFFICER_HEADERS)
    return get_success_data(res)


# ─── Tier 2: state-progression helpers ─────────────────────────


def create_registered_agent_for(
    be: dict, agent_state_code: str | None = None, agent_name: str = "DE Agent"
) -> dict:
    """Create a RegisteredAgent on the given BusinessEntity (PRD §3.3).

    Uses the parent BusinessEntity's CURRENT version for the OCC field.
    Defaults agent_state_code to the entity's formation_state_code (so the agent
    counts toward the home-state requirement for FORMING → ACTIVE).
    """
    if agent_state_code is None:
        agent_state_code = be["formation_state_code"]
    be_now = _get_business_entity(be["id"])
    res = api_client.create_registered_agent(
        be["id"],
        create_registered_agent_payload(
            expected_business_entity_version=be_now["version"],
            agent_name=agent_name,
            agent_state_code=agent_state_code,
        ),
        make_filer_headers(be["id"]),
    )
    return get_success_data(res)


def create_and_execute_operating_agreement(be: dict, template_type: str = "MEMBER_MANAGED") -> dict:
    """DRAFT → EXECUTED in two calls (PRD §3.4). Returns the executed agreement."""
    headers = make_filer_headers(be["id"])
    create_res = api_client.create_operating_agreement(
        be["id"],
        create_operating_agreement_payload(template_type=template_type),
        headers,
    )
    oa = get_success_data(create_res)
    exec_res = api_client.execute_operating_agreement(oa["id"], headers)
    return get_success_data(exec_res)


def create_and_issue_ein(be: dict, ssn_last4: str = "1234") -> dict:
    """PENDING → ISSUED in two calls (PRD §3.5). Returns the issued application."""
    create_res = api_client.create_ein_application(
        be["id"],
        create_ein_application_payload(responsible_party_ssn_last4=ssn_last4),
        make_filer_headers(be["id"]),
    )
    ein_app = get_success_data(create_res)
    issue_res = api_client.issue_ein_application(ein_app["id"], _STATE_ADMIN_HEADERS)
    return get_success_data(issue_res)


# ─── Tier 3: full-activation shortcuts ─────────────────────────


def setup_active_llc(
    legal_name: str | None = None,
    formation_state_code: str = "DE",
    revenue_band: str = "ZERO",
) -> tuple[dict, dict]:
    """LLC walked all the way to BusinessEntity.status=ACTIVE (PRD §3.2).

    Sequence:
      1. POST /business-entities → FORMING
      2. POST /business-entities/{id}/registered-agents → ACTIVE agent
      3. POST /business-entities/{id}/operating-agreements + execute → EXECUTED
      4. POST /business-entities/{id}/ein-applications + issue → ISSUED EIN
      Third precondition fires automatic FORMING → ACTIVE per PRD §3.2.

    Returns (business_entity, registered_agent). The returned business_entity is
    re-fetched after EIN issuance so callers see the post-cascade state.
    """
    be = create_forming_business_entity(
        legal_name=legal_name,
        entity_type="LLC",
        formation_state_code=formation_state_code,
        revenue_band=revenue_band,
    )
    ra = create_registered_agent_for(be)
    create_and_execute_operating_agreement(be)
    create_and_issue_ein(be)
    be_active = _get_business_entity(be["id"])
    return be_active, ra


def setup_active_corp(
    legal_name: str | None = None,
    formation_state_code: str = "DE",
    revenue_band: str = "ZERO",
) -> tuple[dict, dict]:
    """CORP walked to ACTIVE (PRD §3.2). CORP does NOT need an OperatingAgreement."""
    be = create_forming_business_entity(
        legal_name=legal_name,
        entity_type="CORP",
        formation_state_code=formation_state_code,
        revenue_band=revenue_band,
    )
    ra = create_registered_agent_for(be)
    create_and_issue_ein(be)
    be_active = _get_business_entity(be["id"])
    return be_active, ra


def setup_active_lp(
    legal_name: str | None = None,
    formation_state_code: str = "DE",
    revenue_band: str = "ZERO",
) -> tuple[dict, dict]:
    """LP walked to ACTIVE (PRD §3.2). LP requires the LP_GENERAL_LIMITED template."""
    be = create_forming_business_entity(
        legal_name=legal_name,
        entity_type="LP",
        formation_state_code=formation_state_code,
        revenue_band=revenue_band,
    )
    ra = create_registered_agent_for(be)
    create_and_execute_operating_agreement(be, template_type="LP_GENERAL_LIMITED")
    create_and_issue_ein(be)
    be_active = _get_business_entity(be["id"])
    return be_active, ra


# ─── Tier 4: lifecycle shortcuts for annual reports ───────────


def create_draft_annual_report(be: dict, period_year: int) -> dict:
    """Create AnnualReport in DRAFT for the given (entity, period_year) (PRD §3.7)."""
    res = api_client.create_annual_report(
        be["id"],
        create_annual_report_payload(period_year),
        make_filer_headers(be["id"]),
    )
    return get_success_data(res)


def file_annual_report(be: dict, ar_id: str) -> dict:
    """File an AnnualReport (DRAFT|DELINQUENT → FILED) (PRD §3.7)."""
    res = api_client.file_annual_report(ar_id, make_filer_headers(be["id"]))
    return get_success_data(res)


def void_annual_report(ar_id: str) -> dict:
    """ComplianceOfficer voids a FILED AnnualReport (PRD §3.7)."""
    res = api_client.void_annual_report(ar_id, _COMPLIANCE_OFFICER_HEADERS)
    return get_success_data(res)


# ─── Tier 5: ForeignQualification helpers ──────────────────────


def create_foreign_agent(be: dict, foreign_state_code: str = "CA") -> dict:
    """Create a foreign-state RegisteredAgent under `be` (PRD §3.3 foreign-agent path).

    A foreign-state agent has agent_state_code != formation_state_code and is
    only consumable as FQ.foreign_registered_agent_id (PRD §3.3, §3.10).
    """
    return create_registered_agent_for(
        be, agent_state_code=foreign_state_code, agent_name=f"{foreign_state_code} Agent"
    )


def create_pending_foreign_qualification(
    be: dict, foreign_state_code: str, foreign_agent_id: str
) -> dict:
    """Create a PENDING ForeignQualification (PRD §3.10)."""
    res = api_client.create_foreign_qualification(
        be["id"],
        create_foreign_qualification_payload(
            foreign_state_code=foreign_state_code,
            foreign_registered_agent_id=foreign_agent_id,
        ),
        make_filer_headers(be["id"]),
    )
    return get_success_data(res)


def approve_foreign_qualification(fq_id: str) -> dict:
    """PENDING → QUALIFIED (PRD §3.10). StateAdmin call."""
    res = api_client.approve_foreign_qualification(fq_id, _STATE_ADMIN_HEADERS)
    return get_success_data(res)


def setup_qualified_foreign_qualification(
    be: dict, foreign_state_code: str = "CA"
) -> tuple[dict, dict]:
    """ACTIVE entity → foreign-state agent → PENDING FQ → APPROVED → QUALIFIED.
    Returns (foreign_agent, qualified_fq) (PRD §3.10).
    """
    foreign_agent = create_foreign_agent(be, foreign_state_code=foreign_state_code)
    pending_fq = create_pending_foreign_qualification(
        be, foreign_state_code, foreign_agent["id"]
    )
    qualified_fq = approve_foreign_qualification(pending_fq["id"])
    return foreign_agent, qualified_fq


# ─── Tier 6: BOIDisclosure helpers ─────────────────────────────


def create_draft_boi_disclosure(
    be: dict, triggering_event: str = "FORMATION", owners: list | None = None
) -> dict:
    """Create a DRAFT BOIDisclosure (PRD §3.11)."""
    res = api_client.create_boi_disclosure(
        be["id"],
        create_boi_disclosure_payload(triggering_event=triggering_event, owners=owners),
        make_filer_headers(be["id"]),
    )
    return get_success_data(res)


def submit_boi_disclosure(be: dict, boi_id: str) -> dict:
    """DRAFT|AMENDED → SUBMITTED (PRD §3.11)."""
    res = api_client.submit_boi_disclosure(boi_id, make_filer_headers(be["id"]))
    return get_success_data(res)


# ─── Tier 7: BusinessEntity lifecycle terminal states ──────────


def setup_dissolved_business_entity(
    legal_name: str | None = None, formation_state_code: str = "DE"
) -> dict:
    """Walk a fresh DE LLC all the way through DISSOLVED (PRD §3.12).

    Sequence: setup_active_llc → PATCH /business-entities/{id}/dissolve.
    Returns the post-dissolve BusinessEntity.
    """
    be, _ = setup_active_llc(legal_name=legal_name, formation_state_code=formation_state_code)
    res = api_client.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
    return get_success_data(res)
