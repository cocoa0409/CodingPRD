"""Entity assertion helpers — one per entity, plus domain invariants.

All assertions verify only what PRD §2.4 / §3.x explicitly guarantees about each
entity's response shape; they tolerate additional fields the implementer may add.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: every primary entity carries id (UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: append-only rows carry id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )


# ─── BusinessEntity ─────────────────────────────────────────────


_BE_STATUSES = {"FORMING", "ACTIVE", "DELINQUENT", "SUSPENDED", "DISSOLVED"}
_POSTURES = {"GOOD_STANDING", "RESTRICTED", "FROZEN"}
_ENTITY_TYPES = {"LLC", "CORP", "LP"}
_REVENUE_BANDS = {"ZERO", "MICRO", "SMALL", "MEDIUM", "LARGE"}
_STATES = {"CA", "DE", "NY", "TX", "FL", "WY"}


def assert_business_entity(data: dict) -> None:
    """Validate BusinessEntity response shape (PRD §3.1, §3.2)."""
    _assert_common_fields(data, "BusinessEntity")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["entity_type"] in _ENTITY_TYPES, (
        f"entity_type must be one of {_ENTITY_TYPES}, got {data['entity_type']!r}"
    )
    assert data["formation_state_code"] in _STATES, (
        f"formation_state_code must be one of {_STATES}, got {data['formation_state_code']!r}"
    )
    assert data["revenue_band"] in _REVENUE_BANDS, (
        f"revenue_band must be one of {_REVENUE_BANDS}, got {data['revenue_band']!r}"
    )
    assert is_iso8601_timestamp(data["formed_at"]), "formed_at must be ISO 8601"
    assert data["status"] in _BE_STATUSES, (
        f"status must be one of {_BE_STATUSES}, got {data['status']!r}"
    )
    assert data["compliance_posture"] in _POSTURES, (
        f"compliance_posture must be one of {_POSTURES}, got {data['compliance_posture']!r}"
    )
    assert isinstance(data["franchise_tax_paid_through_year"], int)
    assert data["franchise_tax_paid_through_year"] >= 0
    assert isinstance(data["cumulative_franchise_tax_paid_cents"], int)
    assert data["cumulative_franchise_tax_paid_cents"] >= 0


# ─── OperatingAgreement ─────────────────────────────────────────


_OA_STATUSES = {"DRAFT", "EXECUTED", "SUPERSEDED"}
_OA_TEMPLATES = {"MEMBER_MANAGED", "MANAGER_MANAGED", "LP_GENERAL_LIMITED"}


def assert_operating_agreement(data: dict) -> None:
    """Validate OperatingAgreement response shape (PRD §3.4)."""
    _assert_common_fields(data, "OperatingAgreement")
    assert is_valid_uuid(data["business_entity_id"]), "business_entity_id must be UUID"
    assert data["template_type"] in _OA_TEMPLATES, (
        f"template_type must be one of {_OA_TEMPLATES}, got {data['template_type']!r}"
    )
    assert data["status"] in _OA_STATUSES, (
        f"status must be one of {_OA_STATUSES}, got {data['status']!r}"
    )
    if data.get("executed_at") is not None:
        assert is_iso8601_timestamp(data["executed_at"]), "executed_at must be ISO 8601"


# ─── EINApplication ─────────────────────────────────────────────


_EIN_STATUSES = {"PENDING", "ISSUED", "REJECTED"}


def assert_ein_application(data: dict) -> None:
    """Validate EINApplication response shape (PRD §3.5)."""
    _assert_common_fields(data, "EINApplication")
    assert is_valid_uuid(data["business_entity_id"]), "business_entity_id must be UUID"
    assert isinstance(data["responsible_party_name"], str)
    assert (
        isinstance(data["responsible_party_ssn_last4"], str)
        and len(data["responsible_party_ssn_last4"]) == 4
    )
    assert data["status"] in _EIN_STATUSES
    if data.get("ein") is not None:
        # PRD §3.5: "nine-digit `ein` in the form `NN-NNNNNNN`".
        s = data["ein"]
        assert isinstance(s, str) and len(s) == 10 and s[2] == "-", (
            f"ein must be NN-NNNNNNN, got {s!r}"
        )
        digits = s.replace("-", "")
        assert digits.isdigit() and len(digits) == 9
    if data.get("issued_at") is not None:
        assert is_iso8601_timestamp(data["issued_at"])


# ─── RegisteredAgent ────────────────────────────────────────────


_RA_STATUSES = {"ACTIVE", "RESIGNED"}
_RA_TYPES = {"INDIVIDUAL", "COMMERCIAL"}


def assert_registered_agent(data: dict) -> None:
    """Validate RegisteredAgent response shape (PRD §3.3)."""
    _assert_common_fields(data, "RegisteredAgent")
    assert is_valid_uuid(data["business_entity_id"]), "business_entity_id must be UUID"
    assert isinstance(data["agent_name"], str) and data["agent_name"]
    assert data["agent_type"] in _RA_TYPES
    assert data["agent_state_code"] in _STATES
    assert data["status"] in _RA_STATUSES
    if data.get("resigned_at") is not None:
        assert is_iso8601_timestamp(data["resigned_at"])


# ─── AnnualReport ───────────────────────────────────────────────


_AR_STATUSES = {"DRAFT", "FILED", "DELINQUENT", "VOIDED"}


def assert_annual_report(data: dict) -> None:
    """Validate AnnualReport response shape (PRD §3.7)."""
    _assert_common_fields(data, "AnnualReport")
    assert is_valid_uuid(data["business_entity_id"]), "business_entity_id must be UUID"
    assert isinstance(data["period_year"], int)
    assert 2020 <= data["period_year"] <= 2099
    assert data["status"] in _AR_STATUSES
    assert isinstance(data["franchise_tax_amount_cents"], int)
    assert data["franchise_tax_amount_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int)
    assert data["late_fee_cents"] >= 0


# ─── ForeignQualification ───────────────────────────────────────


_FQ_STATUSES = {"PENDING", "QUALIFIED", "WITHDRAWN"}


def assert_foreign_qualification(data: dict) -> None:
    """Validate ForeignQualification response shape (PRD §3.10)."""
    _assert_common_fields(data, "ForeignQualification")
    assert is_valid_uuid(data["business_entity_id"]), "business_entity_id must be UUID"
    assert data["foreign_state_code"] in _STATES
    assert is_valid_uuid(data["foreign_registered_agent_id"]), (
        "foreign_registered_agent_id must be UUID"
    )
    assert data["status"] in _FQ_STATUSES


# ─── BOIDisclosure ──────────────────────────────────────────────


_BOI_STATUSES = {"DRAFT", "SUBMITTED", "AMENDED"}
_BOI_TRIGGERS = {"FORMATION", "AMENDMENT", "ANNUAL_REFRESH"}


def assert_boi_disclosure(data: dict) -> None:
    """Validate BOIDisclosure response shape (PRD §3.11)."""
    _assert_common_fields(data, "BOIDisclosure")
    assert is_valid_uuid(data["business_entity_id"])
    assert data["triggering_event"] in _BOI_TRIGGERS
    assert data["status"] in _BOI_STATUSES


# ─── ComplianceEvent (append-only) ──────────────────────────────


_EVENT_TYPES = {
    "POSTURE_CHANGED",
    "STATUS_CHANGED",
    "REPORT_FILED",
    "AGENT_REPLACED",
    "BOI_SUBMITTED",
    "FQ_QUALIFIED",
    "FQ_WITHDRAWN",
    "REPORT_VOIDED",
    "REINSTATED",
    "DELINQUENT_AUTO",
}


def assert_compliance_event(data: dict) -> None:
    """Validate ComplianceEvent (append-only, no updated_at / version) (PRD §2.4, §3.12)."""
    _assert_append_only_fields(data, "ComplianceEvent")
    assert is_valid_uuid(data["business_entity_id"])
    assert data["event_type"] in _EVENT_TYPES
    assert is_iso8601_timestamp(data["event_at"])
    # PRD §3.12: event_payload is a free-form structured object.
    assert "event_payload" in data
