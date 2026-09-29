"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import COST


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Common resource properties (PRD §2.5)
# --------------------------------------------------------------------------

def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at + updated_at + version, the shape most resources carry."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1: {data.get('version')!r}"
    )


def assert_immutable_record_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at only — no updated_at and no version keys at all."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_bargaining_unit(data: dict) -> None:
    assert_common_fields(data, "BargainingUnit")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["local_number"], str) and 1 <= len(data["local_number"]) <= 32
    assert data["status"] in ("ACTIVE", "EXPIRED")
    for field in (
        "step1_response_days", "step2_response_days", "step3_response_days",
        "appeal_window_days", "filing_window_days", "arbitration_demand_days",
    ):
        assert isinstance(data[field], int) and data[field] >= 1, f"{field} must be >= 1"
    assert isinstance(data["tolling_enabled"], bool)
    assert isinstance(data["director_authority_cents"], int)
    assert isinstance(data["negotiator_authority_cents"], int)
    assert data["negotiator_authority_cents"] > data["director_authority_cents"]
    assert isinstance(data["precedent_deviation_tolerance_bps"], int)
    assert isinstance(data["open_grievance_count"], int) and data["open_grievance_count"] >= 0


def assert_contract_clause(data: dict) -> None:
    assert_common_fields(data, "ContractClause")
    assert isinstance(data["clause_number"], str) and data["clause_number"]
    assert data["category"] in (
        "DISCIPLINE", "PAY", "SENIORITY", "SAFETY", "LEAVE", "SUBCONTRACTING"
    )
    assert isinstance(data["is_arbitrable"], bool)
    assert isinstance(data["expedited"], bool)
    assert data["monetary_cap_cents"] is None or data["monetary_cap_cents"] >= 0
    for field in ("filed_count", "sustained_count", "denied_count", "sustain_rate_bps"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"


def assert_employee(data: dict) -> None:
    assert_common_fields(data, "Employee")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert data["classification"] in ("PRODUCTION", "MAINTENANCE", "CLERICAL", "SUPERVISOR")
    assert data["employment_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED", "REINSTATED")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    for field in (
        "open_grievance_count", "closed_grievance_count",
        "sustained_against_count", "adverse_rate_bps",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"
    assert float(data["witness_release_hours_ytd"]) >= 0


def assert_grievance(data: dict) -> None:
    assert_common_fields(data, "Grievance")
    assert isinstance(data["case_number"], str) and data["case_number"].startswith("GR-")
    assert data["current_step"] in (1, 2, 3)
    assert data["status"] in (
        "FILED", "STEP_MEETING_SCHEDULED", "AWAITING_RESPONSE", "ANSWERED", "APPEALED",
        "ARBITRATION_DEMANDED", "AWARDED", "SETTLED", "WITHDRAWN", "CONSOLIDATED", "CLOSED",
    )
    assert data["timeliness_state"] in (
        "TIMELY", "TOLLED", "EMPLOYER_DEFAULT", "UNION_DEFAULT", "BARRED"
    )
    assert data["cost_posture"] in ("COST_OK", "COST_WATCH", "COST_BREACH")
    assert isinstance(data["remedy_requested_cents"], int) and data["remedy_requested_cents"] >= 0
    assert float(data["back_pay_hours_claimed"]) >= 0
    assert isinstance(data["settled_amount_cents"], int) and data["settled_amount_cents"] >= 0
    assert_cost_identity(data)


def assert_grievance_step(data: dict) -> None:
    assert_common_fields(data, "GrievanceStep")
    assert data["step_number"] in (1, 2, 3)
    assert data["status"] in ("SCHEDULED", "HELD", "ANSWERED", "DEEMED_DENIED", "CANCELLED")
    assert isinstance(data["extension_days"], int) and data["extension_days"] >= 0
    assert isinstance(data["late_by_days"], int) and data["late_by_days"] >= 0
    assert data["disposition"] in (None, "GRANTED", "PARTIAL", "DENIED")
    assert isinstance(data["granted_amount_cents"], int) and data["granted_amount_cents"] >= 0


def assert_settlement_offer(data: dict) -> None:
    assert_common_fields(data, "SettlementOffer")
    assert data["offering_party"] in ("UNION", "EMPLOYER")
    assert data["status"] in (
        "DRAFT", "AUTHORIZED", "COUNTERED", "ACCEPTED", "REJECTED", "LAPSED", "VOIDED"
    )
    assert data["authority_tier"] in ("ANALYST", "DIRECTOR", "NEGOTIATOR", "BOARD")
    assert data["remedy_terms"] in (
        "NONE", "RECORD_EXPUNGEMENT", "SENIORITY_RESTORATION", "POLICY_CHANGE", "REINSTATEMENT"
    )
    assert isinstance(data["monetary_cents"], int) and data["monetary_cents"] >= 0
    assert isinstance(data["exposure_cents"], int) and data["exposure_cents"] >= 0
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_precedent_case(data: dict) -> None:
    assert_immutable_record_fields(data, "PrecedentCase")
    assert data["outcome"] in ("SUSTAINED", "DENIED", "SPLIT")
    assert data["binding_scope"] in ("UNIT_WIDE", "DEPARTMENT", "INDIVIDUAL")
    assert isinstance(data["monetary_value_cents"], int) and data["monetary_value_cents"] >= 0
    assert isinstance(data["cited_count"], int) and data["cited_count"] >= 0


def assert_arbitrator(data: dict) -> None:
    assert_common_fields(data, "Arbitrator")
    assert isinstance(data["panel_memberships"], list) and data["panel_memberships"]
    for membership in data["panel_memberships"]:
        assert membership in ("AAA", "FMCS", "PERMANENT_UMPIRE")
    assert isinstance(data["per_diem_cents"], int) and data["per_diem_cents"] > 0
    assert isinstance(data["cancellation_fee_cents"], int) and data["cancellation_fee_cents"] >= 0
    assert isinstance(data["travel_buffer_hours"], int) and data["travel_buffer_hours"] >= 0
    assert isinstance(data["max_concurrent_cases"], int) and data["max_concurrent_cases"] >= 1
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0
    assert data["status"] in ("AVAILABLE", "FULL", "INACTIVE")


def assert_arbitration_demand(data: dict) -> None:
    assert_common_fields(data, "ArbitrationDemand")
    assert data["panel_source"] in ("AAA", "FMCS", "PERMANENT_UMPIRE")
    assert data["panel_size"] in (3, 5, 7)
    assert data["status"] in (
        "DEMANDED", "PANEL_ISSUED", "STRIKING", "ARBITRATOR_SELECTED",
        "HEARING_SCHEDULED", "HEARD", "AWARDED", "WITHDRAWN", "SETTLED_PRE_HEARING",
    )
    assert data["prep_status"] in (
        "PREP_NOT_STARTED", "PREP_DEFICIENT", "EXHIBITS_FILED", "BRIEFS_FILED", "PREP_READY"
    )
    assert data["strike_turn"] in (None, "UNION", "EMPLOYER")
    assert isinstance(data["panel_arbitrator_ids"], list)
    assert isinstance(data["strikes_taken"], int) and data["strikes_taken"] >= 0
    assert 0 <= data["readiness_score"] <= 100
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    assert isinstance(data["actual_cost_cents"], int) and data["actual_cost_cents"] >= 0


def assert_panel_strike(data: dict) -> None:
    assert_immutable_record_fields(data, "PanelStrike")
    assert data["struck_by"] in ("UNION", "EMPLOYER")
    assert isinstance(data["strike_order"], int) and data["strike_order"] >= 1
    assert isinstance(data["struck_by_user_id"], str) and data["struck_by_user_id"]


def assert_witness_assignment(data: dict) -> None:
    assert_common_fields(data, "WitnessAssignment")
    assert data["witness_type"] in ("FACT", "EXPERT", "CHARACTER")
    assert data["called_by"] in ("UNION", "EMPLOYER")
    assert data["status"] in ("INVITED", "CONFIRMED", "TESTIFIED", "EXCUSED", "NO_SHOW")
    assert float(data["release_hours"]) > 0
    assert isinstance(data["release_cost_cents"], int) and data["release_cost_cents"] >= 0
    assert parse_instant(data["slot_end_at"]) > parse_instant(data["slot_start_at"])


def assert_award(data: dict) -> None:
    assert_common_fields(data, "Award")
    assert data["outcome"] in ("SUSTAINED", "DENIED", "SPLIT")
    assert 0 <= data["sustained_fraction_bps"] <= 10_000
    assert data["status"] in (
        "ISSUED", "IMPLEMENTATION_PENDING", "PARTIALLY_IMPLEMENTED",
        "IMPLEMENTED", "COMPLIANCE_DISPUTED",
    )
    assert isinstance(data["gross_remedy_cents"], int) and data["gross_remedy_cents"] >= 0
    assert isinstance(data["net_remedy_cents"], int) and data["net_remedy_cents"] >= 0
    assert isinstance(data["implemented_cents"], int) and data["implemented_cents"] >= 0
    assert isinstance(data["remedy_deadline_days"], int) and data["remedy_deadline_days"] >= 1
    assert isinstance(data["reinstatement_ordered"], bool)


def assert_cost_entry(data: dict) -> None:
    assert_common_fields(data, "CostEntry")
    assert data["category"] in (
        "ARBITRATOR_FEE", "TRANSCRIPT", "COUNSEL", "RELEASE_TIME", "TRAVEL", "FILING"
    )
    assert data["bearing_party"] in ("UNION", "EMPLOYER", "SPLIT")
    assert data["origin"] in ("MANUAL", "SYSTEM")
    assert data["status"] in ("POSTED", "VOIDED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------

def assert_cost_identity(grievance: dict) -> None:
    """total_cost_cents always equals union share plus employer share (PRD §3.9)."""
    assert grievance["total_cost_cents"] == (
        grievance["union_cost_share_cents"] + grievance["employer_cost_share_cents"]
    ), (
        "total_cost_cents must equal union_cost_share_cents + employer_cost_share_cents: "
        f"{grievance['total_cost_cents']} != {grievance['union_cost_share_cents']} + "
        f"{grievance['employer_cost_share_cents']}"
    )


def expected_cost_posture(total_cost_cents: int) -> str:
    """The posture band the grand total falls into (PRD §3.9)."""
    if total_cost_cents <= COST["COST_OK_CEILING_CENTS"]:
        return "COST_OK"
    if total_cost_cents <= COST["COST_WATCH_CEILING_CENTS"]:
        return "COST_WATCH"
    return "COST_BREACH"


def assert_cost_allocation(grievance: dict, total: int, union: int, employer: int) -> None:
    """Assert the three allocation figures and the identity that binds them."""
    assert grievance["union_cost_share_cents"] == union, (
        f"union_cost_share_cents: expected {union}, "
        f"got {grievance['union_cost_share_cents']}"
    )
    assert grievance["employer_cost_share_cents"] == employer, (
        f"employer_cost_share_cents: expected {employer}, "
        f"got {grievance['employer_cost_share_cents']}"
    )
    assert grievance["total_cost_cents"] == total, (
        f"total_cost_cents: expected {total}, got {grievance['total_cost_cents']}"
    )
    assert_cost_identity(grievance)
