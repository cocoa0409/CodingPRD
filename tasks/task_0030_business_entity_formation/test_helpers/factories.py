"""Payload factories — one per writable entity, input fields only (PRD §3.x).

All factories accept **overrides so tests can pin specific values when their
assertions depend on them.
"""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:6].upper()


# ─── BusinessEntity (PRD §3.1) ──────────────────────────────────


def create_business_entity_payload(
    legal_name: str | None = None,
    entity_type: str = "LLC",
    formation_state_code: str = "DE",
    revenue_band: str | None = "ZERO",
    **overrides,
) -> dict:
    """Payload for POST /business-entities.

    PRD §3.1: required fields are legal_name, entity_type, formation_state_code.
    revenue_band is optional and defaults server-side to ZERO when omitted.
    Pass `revenue_band=None` to OMIT the field entirely (for default-testing).
    """
    payload: dict = {
        "legal_name": legal_name if legal_name is not None else f"TEST CO {_suffix()}",
        "entity_type": entity_type,
        "formation_state_code": formation_state_code,
    }
    if revenue_band is not None:
        payload["revenue_band"] = revenue_band
    payload.update(overrides)
    return payload


# ─── RegisteredAgent (PRD §3.3) ─────────────────────────────────


def create_registered_agent_payload(
    expected_business_entity_version: int,
    agent_name: str = "Default Agent",
    agent_type: str = "COMMERCIAL",
    agent_state_code: str = "DE",
    **overrides,
) -> dict:
    """Payload for POST /business-entities/{id}/registered-agents.

    PRD §3.3: required fields are agent_name, agent_type, agent_state_code, and
    the non-optional expected_business_entity_version OCC field.
    """
    payload = {
        "agent_name": agent_name,
        "agent_type": agent_type,
        "agent_state_code": agent_state_code,
        "expected_business_entity_version": expected_business_entity_version,
    }
    payload.update(overrides)
    return payload


# ─── OperatingAgreement (PRD §3.4) ──────────────────────────────


def create_operating_agreement_payload(
    template_type: str = "MEMBER_MANAGED",
    members: list | None = None,
    **overrides,
) -> dict:
    """Payload for POST /business-entities/{id}/operating-agreements.

    PRD §3.4: required fields are template_type and members_json.
    `members` is a list of {name, ownership_pct} dicts; default = single 100% member.
    """
    if members is None:
        members = [{"name": "Member One", "ownership_pct": 100}]
    payload = {
        "template_type": template_type,
        "members_json": members,
    }
    payload.update(overrides)
    return payload


# ─── EINApplication (PRD §3.5) ──────────────────────────────────


def create_ein_application_payload(
    responsible_party_name: str = "Test Responsible Party",
    responsible_party_ssn_last4: str = "1234",
    **overrides,
) -> dict:
    """Payload for POST /business-entities/{id}/ein-applications (PRD §3.5)."""
    payload = {
        "responsible_party_name": responsible_party_name,
        "responsible_party_ssn_last4": responsible_party_ssn_last4,
    }
    payload.update(overrides)
    return payload


def issue_ein_payload(reject: bool = False) -> dict:
    """Payload for POST /ein-applications/{id}/issue (PRD §3.5).

    `reject=True` advances PENDING → REJECTED; default issues an EIN.
    """
    return {"reject": True} if reject else {}


# ─── AnnualReport (PRD §3.7) ────────────────────────────────────


def create_annual_report_payload(period_year: int, **overrides) -> dict:
    """Payload for POST /business-entities/{id}/annual-reports (PRD §3.7)."""
    payload = {"period_year": period_year}
    payload.update(overrides)
    return payload


# ─── ForeignQualification (PRD §3.10) ───────────────────────────


def create_foreign_qualification_payload(
    foreign_state_code: str,
    foreign_registered_agent_id: str,
    **overrides,
) -> dict:
    """Payload for POST /business-entities/{id}/foreign-qualifications (PRD §3.10)."""
    payload = {
        "foreign_state_code": foreign_state_code,
        "foreign_registered_agent_id": foreign_registered_agent_id,
    }
    payload.update(overrides)
    return payload


# ─── BOIDisclosure (PRD §3.11) ──────────────────────────────────


def create_boi_disclosure_payload(
    triggering_event: str = "FORMATION",
    owners: list | None = None,
    **overrides,
) -> dict:
    """Payload for POST /business-entities/{id}/boi-disclosures (PRD §3.11)."""
    if owners is None:
        owners = [
            {
                "name": "Owner One",
                "dob": "1980-01-01",
                "ownership_pct": 100,
                "control_role": "BOTH",
            }
        ]
    payload = {
        "triggering_event": triggering_event,
        "beneficial_owners_json": owners,
    }
    payload.update(overrides)
    return payload


def amend_boi_disclosure_payload(owners: list | None = None, **overrides) -> dict:
    """Payload for POST /boi-disclosures/{id}/amend (PRD §3.11)."""
    if owners is None:
        owners = [
            {
                "name": "Owner One",
                "dob": "1980-01-01",
                "ownership_pct": 100,
                "control_role": "BOTH",
            }
        ]
    payload = {"beneficial_owners_json": owners}
    payload.update(overrides)
    return payload


# ─── Clock (PRD §2.9, §3.7) ────────────────────────────────────


def set_clock_payload(to_iso8601: str) -> dict:
    """Payload for POST /_clock/set_current_utc (PRD §2.9)."""
    return {"to_iso8601": to_iso8601}
