"""Entity assertions and domain invariant checkers for this API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import TRACKED_UNIT_STATUSES


# --- Shared field-shape helpers ---------------------------------------------


def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    """id + created_at + updated_at + version, per the PRD's identity rules."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO 8601 instant"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be an ISO 8601 instant"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_immutable_row_fields(data: dict, entity_label: str = "row") -> None:
    """An immutable row carries only id and created_at — no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO 8601 instant"
    assert "updated_at" not in data, (
        f"{entity_label} is immutable once written and must not carry updated_at"
    )
    assert "version" not in data, (
        f"{entity_label} is immutable once written and must not carry version"
    )


def assert_instant_equals(actual, expected, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants for the same moment in time."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_envelope_meta(body: dict) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    assert is_iso8601_timestamp(
        meta["api_request_timestamp"]
    ), "api_request_timestamp must be an ISO 8601 instant"


# --- Per-entity assertions ---------------------------------------------------


def assert_installation(data: dict) -> None:
    assert_common_fields(data, "Installation")
    assert isinstance(data["name"], str) and data["name"]
    assert data["branch"] in ("ARMY", "NAVY", "AIR_FORCE", "MARINE_CORPS")
    assert isinstance(data["mha_code"], str) and data["mha_code"]
    assert isinstance(data["bill_of_rights_version"], str)
    assert isinstance(data["turn_buffer_days"], int) and data["turn_buffer_days"] >= 0
    assert isinstance(data["offer_response_hours"], int) and data["offer_response_hours"] >= 1
    assert isinstance(data["decline_limit"], int) and data["decline_limit"] >= 1
    assert isinstance(data["decline_penalty_days"], int) and data["decline_penalty_days"] >= 0
    assert 0 <= data["incentive_base_pct"] <= 1
    for counter in (
        "total_unit_count",
        "available_unit_count",
        "assigned_unit_count",
        "occupied_unit_count",
        "offline_unit_count",
        "hazard_hold_unit_count",
        "pending_application_count",
        "offer_run_epoch",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Installation.{counter} must be a non-negative integer"
        )
    assert_installation_counter_conservation(data)


def assert_installation_counter_conservation(data: dict) -> None:
    """total_unit_count equals the sum of the five per-status counters."""
    per_status_sum = (
        data["available_unit_count"]
        + data["assigned_unit_count"]
        + data["occupied_unit_count"]
        + data["offline_unit_count"]
        + data["hazard_hold_unit_count"]
    )
    assert data["total_unit_count"] == per_status_sum, (
        "total_unit_count must equal the sum of the five tracked status counters: "
        f"{data['total_unit_count']} != {per_status_sum}"
    )


def assert_bah_rate(data: dict) -> None:
    assert_immutable_row_fields(data, "BahRate")
    assert is_valid_uuid(data["installation_id"])
    assert isinstance(data["pay_grade"], str)
    assert isinstance(data["with_dependents"], bool)
    assert isinstance(data["effective_year"], int)
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] > 0
    assert isinstance(data["utility_allowance_cents"], int)
    assert 0 <= data["utility_allowance_cents"] < data["monthly_rate_cents"]


def assert_housing_unit(data: dict) -> None:
    assert_common_fields(data, "HousingUnit")
    assert is_valid_uuid(data["installation_id"])
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert 1 <= data["bedroom_count"] <= 5
    assert data["unit_type"] in ("SFH", "DUPLEX", "TOWNHOME", "APARTMENT")
    assert data["designated_rank_category"] in (
        "JUNIOR_ENLISTED",
        "SENIOR_ENLISTED",
        "WARRANT_OFFICER",
        "JUNIOR_OFFICER",
        "SENIOR_OFFICER",
    )
    assert isinstance(data["historic_flag"], bool)
    assert isinstance(data["accessibility_features"], list)
    assert data["status"] in TRACKED_UNIT_STATUSES


def assert_service_member(data: dict) -> None:
    assert_common_fields(data, "ServiceMember")
    assert isinstance(data["dodid"], str) and data["dodid"]
    assert isinstance(data["last_name"], str)
    assert isinstance(data["first_name"], str)
    assert data["branch"] in ("ARMY", "NAVY", "AIR_FORCE", "MARINE_CORPS")
    assert isinstance(data["pay_grade"], str)
    assert data["rank_category"] in (
        "JUNIOR_ENLISTED",
        "SENIOR_ENLISTED",
        "WARRANT_OFFICER",
        "JUNIOR_OFFICER",
        "SENIOR_OFFICER",
    )
    assert data["deployment_status"] in ("NOT_DEPLOYED", "DEPLOYED", "RETURNED")
    assert isinstance(data["dependent_count"], int) and data["dependent_count"] >= 0


def assert_dependent(data: dict) -> None:
    assert_common_fields(data, "Dependent")
    assert is_valid_uuid(data["service_member_id"])
    assert data["relationship"] in ("SPOUSE", "CHILD", "OTHER_AUTHORIZED")
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) == 10
    assert data["gender"] in ("MALE", "FEMALE")
    assert isinstance(data["is_full_time_custody"], bool)


def assert_waitlist_application(data: dict) -> None:
    assert_common_fields(data, "WaitlistApplication")
    assert is_valid_uuid(data["installation_id"])
    assert is_valid_uuid(data["service_member_id"])
    assert data["status"] in ("PENDING", "OFFERED", "ACCEPTED", "EXPIRED", "HOUSED")
    assert 1 <= data["bedroom_eligibility"] <= 5, (
        "bedroom_eligibility is floored at 1 and capped at 5 bedrooms, got "
        f"{data['bedroom_eligibility']}"
    )
    assert isinstance(data["decline_count"], int) and data["decline_count"] >= 0
    assert isinstance(data["offer_count"], int) and data["offer_count"] >= 0
    assert isinstance(data["effective_control_date"], str)
    assert isinstance(data["dependent_count_at_application"], int)


def assert_lease(data: dict) -> None:
    assert_common_fields(data, "Lease")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["housing_unit_id"])
    assert is_valid_uuid(data["service_member_id"])
    assert data["occupancy_status"] in (
        "PENDING_MOVE_IN",
        "OCCUPIED",
        "NOTICE_GIVEN",
        "TERMINATED",
    )
    assert data["allotment_status"] in ("NOT_STARTED", "ACTIVE", "SUSPENDED", "CLOSED")
    assert data["rent_basis"] in ("OFFER_PROVISIONAL", "MOVE_IN_FINAL")
    assert 1 <= data["term_months"] <= 24
    assert_lease_money_invariants(data)


def assert_lease_money_invariants(data: dict) -> None:
    """Money fields are whole cents and net rent is gross less the allowance."""
    for field in (
        "gross_rent_cents",
        "utility_allowance_cents",
        "net_rent_cents",
        "daily_rent_cents",
        "early_termination_fee_cents",
        "settlement_total_cents",
        "allotment_balance_cents",
        "abatement_total_cents",
    ):
        assert isinstance(data[field], int), (
            f"Lease.{field} must be an integer number of cents, got {data[field]!r}"
        )
    assert data["net_rent_cents"] == data["gross_rent_cents"] - data["utility_allowance_cents"], (
        "net_rent_cents must equal gross_rent_cents less utility_allowance_cents"
    )


def assert_move_in_inspection(data: dict) -> None:
    assert_common_fields(data, "MoveInInspection")
    assert is_valid_uuid(data["lease_id"])
    assert data["status"] in (
        "SCHEDULED",
        "DEFICIENCIES_LOGGED",
        "TENANT_ACKNOWLEDGED",
        "COMPLETED",
    )
    assert isinstance(data["deficiencies"], list)
    assert data["deficiency_count"] == len(data["deficiencies"]), (
        "deficiency_count must equal the length of the deficiency list"
    )
    critical_open = [
        entry
        for entry in data["deficiencies"]
        if entry.get("severity") == "HABITABILITY_CRITICAL"
        and entry.get("status") != "RESOLVED"
    ]
    assert data["critical_open_count"] == len(critical_open), (
        "critical_open_count must count HABITABILITY_CRITICAL entries whose entry "
        "status is anything other than RESOLVED"
    )


def assert_work_order(data: dict) -> None:
    assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data["housing_unit_id"])
    assert data["priority_class"] in ("EMERGENCY", "URGENT", "ROUTINE")
    assert data["status"] in (
        "SUBMITTED",
        "ASSIGNED",
        "IN_PROGRESS",
        "COMPLETED",
        "REOPENED",
        "CLOSED",
    )
    assert isinstance(data["habitability_impact"], bool)
    assert isinstance(data["sla_breached"], bool)
    assert data["escalation_level"] in (0, 1, 2)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert is_iso8601_timestamp(data["reported_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert is_iso8601_timestamp(data["completion_due_at"])


def assert_hazard_case(data: dict) -> None:
    assert_common_fields(data, "HazardCase")
    assert is_valid_uuid(data["housing_unit_id"])
    assert data["hazard_type"] in ("MOLD", "LEAD_PAINT", "LEAD_WATER")
    assert data["status"] in (
        "REPORTED",
        "ASSESSED",
        "REMEDIATION_IN_PROGRESS",
        "DISPLACEMENT_ACTIVE",
        "CLEARANCE_PENDING",
        "CLOSED",
        "VOIDED",
    )
    assert data["assessment_severity"] in (
        None,
        "SEVERITY_1",
        "SEVERITY_2",
        "SEVERITY_3",
    )
    assert isinstance(data["child_under_six_present"], bool)
    assert isinstance(data["displacement_required"], bool)


def assert_displacement_lodging(data: dict) -> None:
    assert_common_fields(data, "DisplacementLodging")
    assert is_valid_uuid(data["hazard_case_id"])
    assert is_valid_uuid(data["lease_id"])
    assert data["status"] in ("AUTHORIZED", "CLOSED")
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] > 0
    assert isinstance(data["occupants_count"], int) and data["occupants_count"] >= 1
    for field in (
        "nights_displaced",
        "per_night_authorized_cents",
        "lodging_authorized_cents",
        "rent_abatement_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert (
        data["lodging_authorized_cents"]
        == data["per_night_authorized_cents"] * data["nights_displaced"]
    ), "lodging_authorized_cents must be per_night_authorized_cents times nights_displaced"


def assert_dispute_case(data: dict) -> None:
    assert_common_fields(data, "DisputeCase")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["service_member_id"])
    assert data["category"] in (
        "RENT_CHARGE",
        "MAINTENANCE_QUALITY",
        "HABITABILITY",
        "DAMAGE_CLAIM",
        "UTILITY_BILLING",
    )
    assert data["status"] in (
        "UNDER_REVIEW",
        "PROPOSED_RESOLUTION",
        "RESIDENT_REJECTED",
        "ESCALATED_INSTALLATION",
        "CLOSED_RESOLVED",
    )
    assert 0 <= data["round_count"] <= 3
    assert isinstance(data["credit_offer_cents"], int)
    assert isinstance(data["credit_award_cents"], int)


def assert_allotment_transaction(data: dict) -> None:
    assert_immutable_row_fields(data, "AllotmentTransaction")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7, (
        "period_month must be a YYYY-MM string"
    )
    assert data["type"] in (
        "CHARGE",
        "ABATEMENT",
        "REFUND",
        "ARREARS_ADJUSTMENT",
        "EARLY_TERMINATION_FEE",
    )
    assert isinstance(data["amount_cents"], int)
    if data["type"] in ("CHARGE", "ARREARS_ADJUSTMENT", "EARLY_TERMINATION_FEE"):
        assert data["amount_cents"] > 0, f"{data['type']} rows carry positive amounts"
    if data["type"] in ("ABATEMENT", "REFUND"):
        assert data["amount_cents"] < 0, f"{data['type']} rows carry negative amounts"
    assert isinstance(data["source_ref"], str) and data["source_ref"]
    assert isinstance(data["running_balance_cents"], int)


def assert_reinvestment_account(data: dict) -> None:
    assert_common_fields(data, "ReinvestmentAccount")
    assert is_valid_uuid(data["installation_id"])
    assert 2024 <= data["fiscal_year"] <= 2030
    assert data["occupancy_basis"] in ("UNIT_DAY_WEIGHTED", "MONTH_END_SNAPSHOT")
    for field in (
        "opening_balance_cents",
        "contributions_cents",
        "expenditures_cents",
        "closing_balance_cents",
        "net_collected_cents",
        "performance_incentive_fee_cents",
    ):
        assert isinstance(data[field], int), f"ReinvestmentAccount.{field} must be cents"
    assert data["closing_balance_cents"] == (
        data["opening_balance_cents"]
        + data["contributions_cents"]
        - data["expenditures_cents"]
    ), (
        "closing_balance_cents must always be opening_balance_cents plus "
        "contributions_cents less expenditures_cents"
    )


# --- Ledger invariants ------------------------------------------------------


def assert_ledger_conservation(rows: list, lease: dict) -> None:
    """Running balances chain from zero and reconcile with the lease's totals."""
    running = 0
    for index, row in enumerate(rows):
        running += row["amount_cents"]
        assert row["running_balance_cents"] == running, (
            f"row {index} running_balance_cents must equal the previous running "
            f"balance plus its own amount_cents: expected {running}, got "
            f"{row['running_balance_cents']}"
        )
    assert lease["allotment_balance_cents"] == running, (
        "Lease.allotment_balance_cents must equal the running balance of the last "
        f"ledger row: expected {running}, got {lease['allotment_balance_cents']}"
    )
    abatement_net = -sum(
        row["amount_cents"]
        for row in rows
        if row["type"] in ("ABATEMENT", "ARREARS_ADJUSTMENT")
    )
    assert lease["abatement_total_cents"] == abatement_net, (
        "Lease.abatement_total_cents must equal the negated sum of ABATEMENT and "
        f"ARREARS_ADJUSTMENT rows: expected {abatement_net}, got "
        f"{lease['abatement_total_cents']}"
    )


def assert_created_at_ascending(rows: list) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered by created_at ascending: {stamps}"
