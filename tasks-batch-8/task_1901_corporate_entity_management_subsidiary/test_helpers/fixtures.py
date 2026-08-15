"""Composite setup helpers for the Corporate Entity Governance API tests.

Every test runs against an empty database (the harness restarts the server per
test), so each helper builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use the lenient `get_success_data`
validator so a broken precondition surfaces as a clear "Setup failed" error.

Canonical environment (shared by most helpers):
  J1 "US-DE" jurisdiction + agent AG1; entity formed 2025-06-15 in J1; the
  logical clock starts at 2026-08-01T00:00:00Z (PRD 3.15). Formation confirm
  then generates the period-2026 ANNUAL_REPORT and FRANCHISE_TAX filings due
  2026-12-31 (PRD 3.2, 3.6).
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agent_appointment_payload,
    create_certificate_request_payload,
    create_entity_payload,
    create_grant_payload,
    create_jurisdiction_ca_payload,
    create_jurisdiction_nv_payload,
    create_jurisdiction_payload,
    create_officer_payload,
    create_ownership_record_payload,
    create_qualification_payload,
    create_registered_agent_payload,
    create_resolution_payload,
)
from .test_users import TEST_USERS

SEC1 = TEST_USERS["secretary_1_headers"]
SEC2 = TEST_USERS["secretary_2_headers"]
FC1 = TEST_USERS["filing_coordinator_headers"]
AUD1 = TEST_USERS["compliance_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — clock, sweep, and primitive creators
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (CorporateSecretary only, PRD 3.15)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, SEC1))


def run_sweep() -> Dict[str, Any]:
    """Materialize all time-driven transitions (PRD 3.15). Returns the sweep report."""
    return get_success_data(api_client.run_sweep(SEC1))


def create_jurisdiction_j1(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), SEC1)
    )


def create_jurisdiction_ca(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_ca_payload(**overrides), SEC1)
    )


def create_jurisdiction_nv(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_nv_payload(**overrides), SEC1)
    )


def create_agent(jurisdiction_id: str, name: str = "DE Agent Co", address: str = "1 Agent Way") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_registered_agent(
            create_registered_agent_payload(jurisdiction_id, name=name, address=address), SEC1
        )
    )


def create_officer(full_name: str = "Olivia Ortiz", email: str = "oo@example.com") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_officer(
            create_officer_payload(full_name=full_name, email=email), SEC1
        )
    )


def create_draft_entity(
    jurisdiction_id: str,
    legal_name: str = "Acme Holdings Inc",
    entity_type: str = "CORPORATION",
    formation_date: str = "2025-06-15",
    authorized_shares: Optional[int] = 10000,
    fiscal_year_end_month: Optional[int] = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "legal_name": legal_name,
        "entity_type": entity_type,
        "formation_date": formation_date,
    }
    if authorized_shares is not None:
        overrides["authorized_shares"] = authorized_shares
    if fiscal_year_end_month is not None:
        overrides["fiscal_year_end_month"] = fiscal_year_end_month
    return get_success_data(
        api_client.create_entity(create_entity_payload(jurisdiction_id, **overrides), SEC1)
    )


def fetch_entity(entity_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_entity(entity_id, SEC1))


def fetch_entity_version(entity_id: str) -> int:
    return fetch_entity(entity_id)["version"]


def appoint_agent(
    entity_id: str, agent_id: str, jurisdiction_id: str, start_date: str = "2025-06-15"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_agent_appointment(
            entity_id,
            create_agent_appointment_payload(agent_id, jurisdiction_id, start_date=start_date),
            SEC1,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — resolution pipeline and entity state progression
# ---------------------------------------------------------------------------


def draft_resolution(
    entity_id: str,
    resolution_type: str,
    payload: Dict[str, Any],
    effective_date: str,
    drafter: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft a resolution (DRAFT). Default drafter is the filing coordinator."""
    return get_success_data(
        api_client.create_resolution(
            entity_id,
            create_resolution_payload(resolution_type, payload, effective_date),
            drafter or FC1,
        )
    )


def adopt_resolution(
    entity_id: str,
    resolution_type: str,
    payload: Dict[str, Any],
    effective_date: str,
    drafter: Optional[Dict[str, str]] = None,
    adopter: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Full adoption pipeline: draft -> submit -> adopt with a fresh OCC version.

    Default identities satisfy segregation of duties (PRD 2.9): the filing
    coordinator drafts and the first secretary adopts.
    """
    drafter = drafter or FC1
    adopter = adopter or SEC1
    resolution = draft_resolution(entity_id, resolution_type, payload, effective_date, drafter)
    get_success_data(api_client.submit_resolution(resolution["id"], drafter))
    version = fetch_entity_version(entity_id)
    return get_success_data(
        api_client.adopt_resolution(
            resolution["id"], {"expected_entity_version": version}, adopter
        )
    )


def activate_entity(
    jurisdiction_id: str,
    agent_id: str,
    legal_name: str = "Acme Holdings Inc",
    entity_type: str = "CORPORATION",
    formation_date: str = "2025-06-15",
    authorized_shares: Optional[int] = 10000,
    agent_start_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Full formation chain: DRAFT entity + agent coverage + adopted
    AUTHORIZE_FORMATION resolution -> submit-formation -> confirm-formation.
    Returns the ACTIVE entity (PRD 3.2)."""
    entity = create_draft_entity(
        jurisdiction_id,
        legal_name=legal_name,
        entity_type=entity_type,
        formation_date=formation_date,
        authorized_shares=authorized_shares,
    )
    appoint_agent(
        entity["id"], agent_id, jurisdiction_id, start_date=agent_start_date or formation_date
    )
    adopt_resolution(entity["id"], "AUTHORIZE_FORMATION", {}, formation_date)
    get_success_data(api_client.submit_formation(entity["id"], SEC1))
    get_success_data(api_client.confirm_formation(entity["id"], SEC1))
    return fetch_entity(entity["id"])


def setup_base_entity(
    legal_name: str = "Acme Holdings Inc",
    entity_type: str = "CORPORATION",
    formation_date: str = "2025-06-15",
    authorized_shares: Optional[int] = 10000,
) -> Dict[str, Any]:
    """The canonical environment: J1 + AG1 + one ACTIVE entity.

    Returns a context dict with jurisdiction, agent, and entity keys."""
    j1 = create_jurisdiction_j1()
    ag1 = create_agent(j1["id"])
    entity = activate_entity(
        j1["id"],
        ag1["id"],
        legal_name=legal_name,
        entity_type=entity_type,
        formation_date=formation_date,
        authorized_shares=authorized_shares,
    )
    return {"jurisdiction": j1, "agent": ag1, "entity": entity}


# ---------------------------------------------------------------------------
# Tier 2 — filings
# ---------------------------------------------------------------------------


def find_filing(
    entity_id: str,
    filing_type: Optional[str] = None,
    period_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Locate a single filing via the filtered list endpoint."""
    params: Dict[str, Any] = {"entity_id": entity_id}
    if filing_type is not None:
        params["filing_type"] = filing_type
    if period_year is not None:
        params["period_year"] = period_year
    rows = get_success_data(api_client.list_filings(SEC1, params=params))
    assert isinstance(rows, list) and len(rows) == 1, (
        f"Setup failed: expected exactly 1 filing for {params}, got {rows}"
    )
    return rows[0]


def list_filings(entity_id: str, **filters) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"entity_id": entity_id}
    params.update(filters)
    return get_success_data(api_client.list_filings(SEC1, params=params))


def prepare_filing(filing_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.prepare_filing(filing_id, headers or FC1))


def submit_filing(filing_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.submit_filing(filing_id, headers or FC1))


def find_prepared_franchise_filing(entity_id: str, period_year: int = 2026) -> Dict[str, Any]:
    """Fetch the period FRANCHISE_TAX filing and move it to PREPARED."""
    filing = find_filing(entity_id, filing_type="FRANCHISE_TAX", period_year=period_year)
    return prepare_filing(filing["id"])


# ---------------------------------------------------------------------------
# Tier 3 — officers, appointments, and signature grants
# ---------------------------------------------------------------------------


def find_officer_appointment(entity_id: str, officer_id: str) -> Dict[str, Any]:
    rows = get_success_data(
        api_client.list_officer_appointments(
            SEC1, params={"entity_id": entity_id, "officer_id": officer_id}
        )
    )
    assert isinstance(rows, list) and len(rows) == 1, (
        f"Setup failed: expected exactly 1 appointment for officer {officer_id}, got {rows}"
    )
    return rows[0]


def appoint_officer(
    entity_id: str,
    officer_id: str,
    office_title: str = "PRESIDENT",
    start_date: str = "2026-01-01",
    effective_date: str = "2026-01-01",
) -> Dict[str, Any]:
    """Adopt an APPOINT_OFFICER resolution and sweep it to EFFECTIVE so the
    appointment materializes (PRD 3.4/3.5). Returns the APPOINTED appointment."""
    adopt_resolution(
        entity_id,
        "APPOINT_OFFICER",
        {"officer_id": officer_id, "office_title": office_title, "start_date": start_date},
        effective_date,
    )
    run_sweep()
    return find_officer_appointment(entity_id, officer_id)


def adopt_grant_resolution(
    entity_id: str, officer_id: str, scope: str, effective_date: str = "2026-01-02"
) -> Dict[str, Any]:
    """Adopt a GRANT_SIGNATURE_AUTHORITY resolution for (officer, scope)."""
    return adopt_resolution(
        entity_id,
        "GRANT_SIGNATURE_AUTHORITY",
        {"officer_id": officer_id, "scope": scope},
        effective_date,
    )


def create_grant(
    entity_id: str,
    officer_id: str,
    scope: str = "CONTRACTS",
    max_amount_cents: int = 100000,
    effective_date: str = "2026-01-01",
    expiry_date: str = "2027-01-01",
    delegated_from_grant_id: Optional[str] = None,
    with_resolution: bool = True,
) -> Dict[str, Any]:
    """Create a signature grant; by default first adopts its authorizing
    GRANT_SIGNATURE_AUTHORITY resolution (PRD 3.9)."""
    if with_resolution:
        adopt_grant_resolution(entity_id, officer_id, scope)
    return get_success_data(
        api_client.create_signature_grant(
            entity_id,
            create_grant_payload(
                officer_id,
                scope,
                max_amount_cents,
                effective_date,
                expiry_date,
                delegated_from_grant_id=delegated_from_grant_id,
            ),
            SEC1,
        )
    )


def setup_entity_with_officer_and_grant(
    legal_name: str = "Grant Corp",
    officer_email: str = "oo@example.com",
    scope: str = "CONTRACTS",
    max_amount_cents: int = 100000,
    effective_date: str = "2026-01-01",
    expiry_date: str = "2027-01-01",
) -> Dict[str, Any]:
    """ACTIVE entity + one APPOINTED PRESIDENT + one ACTIVE direct grant.

    Returns {jurisdiction, agent, entity, officer, appointment, grant}."""
    ctx = setup_base_entity(legal_name=legal_name)
    officer = create_officer(email=officer_email)
    appointment = appoint_officer(ctx["entity"]["id"], officer["id"])
    grant = create_grant(
        ctx["entity"]["id"],
        officer["id"],
        scope=scope,
        max_amount_cents=max_amount_cents,
        effective_date=effective_date,
        expiry_date=expiry_date,
    )
    ctx.update({"officer": officer, "appointment": appointment, "grant": grant})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — foreign qualification
# ---------------------------------------------------------------------------


def setup_entity_with_qualification(confirm: bool = True) -> Dict[str, Any]:
    """ACTIVE entity in J1 plus a second jurisdiction J3 with agent coverage
    and an adopted AUTHORIZE_QUALIFICATION resolution; the qualification is
    created (PENDING) and, when confirm=True, confirmed (QUALIFIED), which
    generates the J3 period-2026 ANNUAL_REPORT due 2026-09-30 (PRD 3.8)."""
    ctx = setup_base_entity()
    e1 = ctx["entity"]
    j3 = create_jurisdiction_nv()
    ag3 = create_agent(j3["id"], name="NV Agent Co", address="9 Agent Rd")
    aa3 = appoint_agent(e1["id"], ag3["id"], j3["id"], start_date="2026-06-01")
    adopt_resolution(e1["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j3["id"]}, "2026-06-01")
    qualification = get_success_data(
        api_client.create_qualification(
            e1["id"], create_qualification_payload(j3["id"], aa3["id"]), SEC1
        )
    )
    if confirm:
        qualification = get_success_data(
            api_client.confirm_qualification(qualification["id"], SEC1)
        )
    ctx.update({"j3": j3, "ag3": ag3, "aa3": aa3, "qualification": qualification})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — ownership records and certificates
# ---------------------------------------------------------------------------


def create_ownership_record(
    parent_entity_id: str,
    subsidiary_entity_id: str,
    percentage_bps: int,
    effective_date: str = "2026-01-01",
    supersedes_record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an ownership edge against the subsidiary's CURRENT version
    (OCC rule, PRD 2.7)."""
    version = fetch_entity_version(subsidiary_entity_id)
    return get_success_data(
        api_client.create_ownership_record(
            create_ownership_record_payload(
                parent_entity_id,
                subsidiary_entity_id,
                percentage_bps,
                effective_date,
                version,
                supersedes_record_id=supersedes_record_id,
            ),
            SEC1,
        )
    )


def setup_two_active_entities(
    parent_name: str = "Parent P Inc", subsidiary_name: str = "Sub S Inc"
) -> Dict[str, Any]:
    """J1 + AG1 shared by two ACTIVE entities (parent and subsidiary)."""
    j1 = create_jurisdiction_j1()
    ag1 = create_agent(j1["id"])
    parent = activate_entity(j1["id"], ag1["id"], legal_name=parent_name, authorized_shares=None)
    subsidiary = activate_entity(
        j1["id"], ag1["id"], legal_name=subsidiary_name, authorized_shares=None
    )
    return {"jurisdiction": j1, "agent": ag1, "parent": parent, "subsidiary": subsidiary}


def request_certificate(
    entity_id: str, jurisdiction_id: str, delivery_speed: str = "STANDARD"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_certificate_request(
            entity_id, create_certificate_request_payload(jurisdiction_id, delivery_speed), SEC1
        )
    )


# ---------------------------------------------------------------------------
# Audit trail helpers
# ---------------------------------------------------------------------------


def list_events(entity_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if event_type is not None:
        params["event_type"] = event_type
    return get_success_data(api_client.list_compliance_events(entity_id, SEC1, params=params))


def list_event_types(entity_id: str) -> List[str]:
    return [event["event_type"] for event in list_events(entity_id)]
