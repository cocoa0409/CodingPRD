"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) walks the field set declared in PRD §2.4 and
§3 for that entity. Common-fields entities carry id + created_at +
updated_at + version (PRD §2.4); the three append-only / join entities
(OperatingAgreement, BOIOwnership, ComplianceEvent) carry ONLY id and
created_at.

All assertions take a single dict argument — the resource payload as
returned in `data` of a 2xx response.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields envelope checks — PRD §2.4
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Most resources in this registry carry the common-field
    set: a server-minted id (a UUID with no type prefix), created_at and
    updated_at ... and version (an integer that increments by exactly
    one on every mutation)."
    """
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: OperatingAgreement, BOIOwnership, and ComplianceEvent
    "carry only id and created_at; they have neither updated_at nor
    version."
    """
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.4: "version increments by exactly one on every mutation
    that the system regards as a stateful change to that resource."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# BusinessEntity — PRD §3.1, §3.10
# ---------------------------------------------------------------------------
def assert_business_entity(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str)
    assert 1 <= len(data["legal_name"]) <= 200
    assert data["entity_type"] in {"LLC", "CORP", "LP"}
    home = data.get("home_state")
    assert isinstance(home, str) and len(home) == 2 and home.isupper(), (
        f"home_state must be 2 uppercase letters, got {home!r}"
    )
    assert data["formation_status"] in {
        "PENDING_FORMATION", "ACTIVE", "DISSOLVED",
        "ADMINISTRATIVELY_DISSOLVED",
    }
    cs = data.get("compliance_status")
    assert cs in {None, "GOOD_STANDING",
                  "NOT_IN_GOOD_STANDING", "DELINQUENT"}, (
        f"compliance_status must be one of "
        f"{{None, GOOD_STANDING, NOT_IN_GOOD_STANDING, DELINQUENT}}, "
        f"got {cs!r}"
    )
    # PRD §3.1: formation_status null compliance while PENDING_FORMATION;
    # PRD §3.11: compliance_status null after DISSOLVED or ADMIN_DISSOLVED.
    if data["formation_status"] == "PENDING_FORMATION":
        assert cs is None, (
            f"PENDING_FORMATION must carry null compliance_status; "
            f"got {cs!r}"
        )
    if data["formation_status"] in {"DISSOLVED",
                                     "ADMINISTRATIVELY_DISSOLVED"}:
        assert cs is None, (
            f"{data['formation_status']} must carry null "
            f"compliance_status; got {cs!r}"
        )
    # EIN format when set
    if data.get("ein") is not None:
        ein = data["ein"]
        assert isinstance(ein, str) and len(ein) == 10 and ein[2] == "-", (
            f"ein must match XX-XXXXXXX, got {ein!r}"
        )
    # Credit balance — PRD §2.6 cents-only.
    bal = data.get("credit_balance_cents")
    assert isinstance(bal, int) and bal >= 0, (
        f"credit_balance_cents must be a non-negative int, got {bal!r}"
    )


def assert_registered_agent(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("agent_name"), str)
    addr = data.get("physical_address")
    assert isinstance(addr, str) and 1 <= len(addr) <= 300
    state = data.get("service_state")
    assert isinstance(state, str) and len(state) == 2 and state.isupper()
    assert data["status"] in {"ACTIVE", "RESIGNED"}


def assert_operating_agreement(data: Dict[str, Any]) -> None:
    """PRD §3.3: "An OperatingAgreement row carries only id and
    created_at — it has neither updated_at nor version."""
    assert_append_only_fields(data)
    assert "business_entity_id" in data
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert data["template_code"] in {
        "LLC_MM", "LLC_MGR", "CORP_BYLAWS", "LP_AGREEMENT",
    }
    assert isinstance(data.get("template_version"), str)
    # PRD §3.3: locked_template_hash recorded at attachment time.
    assert isinstance(data.get("locked_template_hash"), str)
    assert len(data["locked_template_hash"]) > 0


def assert_ein_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert isinstance(data.get("responsible_party_name"), str)
    ssn4 = data.get("responsible_party_ssn_last4")
    assert isinstance(ssn4, str) and len(ssn4) == 4 and ssn4.isdigit(), (
        f"responsible_party_ssn_last4 must be 4 digits, got {ssn4!r}"
    )
    assert data["status"] in {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED"}
    if data.get("assigned_ein") is not None:
        ein = data["assigned_ein"]
        assert (isinstance(ein, str) and len(ein) == 10
                and ein[2] == "-"
                and ein.replace("-", "").isdigit()), (
            f"assigned_ein must match XX-XXXXXXX, got {ein!r}"
        )


def assert_annual_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert isinstance(data.get("report_year"), int)
    assert isinstance(data.get("principal_office_address"), str)
    assert isinstance(data.get("officer_director_count"), int)
    assert data["officer_director_count"] >= 1
    assert data["status"] in {"DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_franchise_tax_assessment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert isinstance(data.get("tax_year"), int)
    assert data["calculation_method"] in {
        "FLAT", "AUTHORIZED_SHARES", "ASSUMED_PAR_VALUE",
    }
    assert isinstance(data.get("base_tax_cents"), int)
    assert data["base_tax_cents"] >= 0
    assert isinstance(data.get("late_fee_cents"), int)
    assert data["late_fee_cents"] >= 0
    assert isinstance(data.get("total_due_cents"), int)
    assert data["total_due_cents"] >= 0
    assert is_iso8601_timestamp(str(data.get("due_date", "")))
    assert data["status"] in {"ASSESSED", "PAID", "OVERDUE", "DELINQUENT"}


def assert_foreign_qualification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    fs = data.get("foreign_state")
    assert isinstance(fs, str) and len(fs) == 2 and fs.isupper()
    assert is_valid_uuid(str(data["foreign_registered_agent_id"]))
    assert is_iso8601_timestamp(
        str(data.get("certificate_of_good_standing_date", "")),
    )
    assert data["status"] in {
        "PENDING", "REJECTED", "QUALIFIED", "WITHDRAWN", "REVOKED",
    }


def assert_boi_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert data["filing_type"] in {"INITIAL", "UPDATE", "CORRECTION"}
    assert data["status"] in {
        "DRAFT", "FILED", "CURRENT", "STALE", "CORRECTED",
    }
    assert isinstance(data.get("penalty_cents", 0), int)


def assert_beneficial_owner(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_legal_name"), str)
    assert is_iso8601_timestamp(str(data.get("date_of_birth", "")))
    assert isinstance(data.get("residential_address"), str)
    assert data["identifying_document_type"] in {
        "US_PASSPORT", "STATE_DRIVERS_LICENSE",
        "STATE_ID", "FOREIGN_PASSPORT",
    }
    doc = data.get("identifying_document_number")
    assert isinstance(doc, str) and 1 <= len(doc) <= 50


def assert_boi_ownership(data: Dict[str, Any]) -> None:
    """PRD §2.4: BOIOwnership "are mutated only by soft-delete which
    writes terminated_at"; PRD §2.4 lists it among the rows carrying
    "only id and created_at" — no updated_at, no version."""
    assert_append_only_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert is_valid_uuid(str(data["beneficial_owner_id"]))
    bps = data.get("ownership_percent_basis_points")
    assert isinstance(bps, int) and 0 <= bps <= 10000, (
        f"ownership_percent_basis_points must be in [0,10000], got {bps!r}"
    )


def assert_compliance_event(data: Dict[str, Any]) -> None:
    """PRD §2.4 / §2.9: compliance events are append-only.
    PRD §2.9: every event carries event_type, occurred_at, payload."""
    assert_append_only_fields(data)
    assert is_valid_uuid(str(data["business_entity_id"]))
    assert data["event_type"] in {
        "FORMED", "ANNUAL_REPORT_ACCEPTED", "ANNUAL_REPORT_REJECTED",
        "TAX_ASSESSED", "TAX_PAID", "TAX_OVERDUE", "TAX_DELINQUENT",
        "BOI_FILED", "BOI_STALE", "BOI_CORRECTED",
        "FOREIGN_QUALIFIED", "FOREIGN_REVOKED",
        "ADMIN_DISSOLVED", "VOLUNTARILY_DISSOLVED",
        "AGENT_RESIGNED", "COMPLIANCE_STATUS_CHANGED",
    }
    assert is_iso8601_timestamp(str(data.get("occurred_at", "")))


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_event_types_present(events: List[Dict[str, Any]],
                               expected: Iterable[str]) -> None:
    """Check that the list of ComplianceEvent rows contains each
    expected event_type at least once."""
    seen = {e.get("event_type") for e in events}
    expected_set = set(expected)
    missing = expected_set - seen
    assert not missing, (
        f"Missing compliance events: {sorted(missing)}. "
        f"Saw: {sorted(seen)}"
    )


def assert_events_in_chronological_order(
    events: List[Dict[str, Any]], expected_sequence: List[str],
) -> None:
    """Check that the given event types appear in this order (other
    events may interleave). PRD §2.9: "the audit trail readable through
    the compliance-events listing", and PRD §4 (events list) declares
    sort by occurred_at ascending.
    """
    sequence_iter = iter(expected_sequence)
    target = next(sequence_iter, None)
    for evt in events:
        if target is None:
            break
        if evt.get("event_type") == target:
            target = next(sequence_iter, None)
    assert target is None, (
        f"Expected event sequence {expected_sequence} not satisfied; "
        f"failed waiting for {target!r} in events="
        f"{[e.get('event_type') for e in events]}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    "assert_business_entity",
    "assert_registered_agent",
    "assert_operating_agreement",
    "assert_ein_application",
    "assert_annual_report",
    "assert_franchise_tax_assessment",
    "assert_foreign_qualification",
    "assert_boi_report",
    "assert_beneficial_owner",
    "assert_boi_ownership",
    "assert_compliance_event",
    "assert_event_types_present",
    "assert_events_in_chronological_order",
]
