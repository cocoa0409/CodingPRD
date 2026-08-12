"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} must be an object, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_utility_company(data: dict):
    _assert_common(data, "UtilityCompany")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["company_code"], str) and data["company_code"]
    assert data["role_capability"] in ["HOST", "RESPONDING", "BOTH"]
    assert isinstance(data["home_region"], str)


def assert_event(data: dict):
    _assert_common(data, "MutualAidEvent")
    assert isinstance(data["event_name"], str) and data["event_name"]
    assert is_valid_uuid(data.get("host_utility_id", ""))
    assert data["event_type"] in ["STORM", "WILDFIRE", "ICE", "FLOOD"]
    assert data["status"] in ["OPEN", "ACTIVE", "DEMOBILIZING", "CLOSED"]
    assert data["intake_posture"] in ["ACCEPTING", "RESTRICTED", "SEALED"]
    assert isinstance(data["open_request_count"], int) and data["open_request_count"] >= 0


def assert_billing_rate_schedule(data: dict):
    _assert_common(data, "BillingRateSchedule")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("responding_utility_id", ""))
    assert data["status"] in ["DRAFT", "PUBLISHED", "LOCKED", "SUPERSEDED"]
    assert isinstance(data["rate_lines"], list) and data["rate_lines"]
    for line in data["rate_lines"]:
        assert line["crew_type"] in ["LINE", "TREE", "DAMAGE_ASSESS", "SUBSTATION", "SUPPORT"]
        assert isinstance(line["hourly_rate_cents"], int) and line["hourly_rate_cents"] > 0
    assert data["per_diem_method"] in ["STANDARD", "ACTUAL"]
    assert isinstance(data["mobilization_fee_tiers"], list) and data["mobilization_fee_tiers"]


def assert_assistance_request(data: dict):
    _assert_common(data, "AssistanceRequest")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("responding_utility_id", ""))
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "COUNTERED", "ACCEPTED", "DECLINED",
        "CANCELLED", "IN_PROGRESS", "FULFILLED", "RELEASED", "CLOSED",
    ]
    assert isinstance(data["amendment_round"], int) and data["amendment_round"] >= 0
    assert isinstance(data["requested_crews"], list) and data["requested_crews"]
    assert isinstance(data["required_minimum_crews"], int)
    assert isinstance(data["committed_crew_count"], int) and data["committed_crew_count"] >= 0
    assert isinstance(data["deployable_crew_count"], int) and data["deployable_crew_count"] >= 0


def assert_crew(data: dict):
    _assert_common(data, "Crew")
    assert is_valid_uuid(data.get("request_id", ""))
    assert is_valid_uuid(data.get("owning_utility_id", ""))
    assert data["crew_type"] in ["LINE", "TREE", "DAMAGE_ASSESS", "SUBSTATION", "SUPPORT"]
    assert isinstance(data["roster"], list) and data["roster"], "roster must be non-empty"
    assert data["roster_size"] == len(data["roster"])
    assert isinstance(data["equipment_units"], list)
    expected_equip = sum(u["daily_rate_cents"] for u in data["equipment_units"])
    assert data["equipment_daily_total_cents"] == expected_equip
    assert data["mobility_status"] in ["COMMITTED", "ARRIVED", "DEMOBILIZING", "RETURNED", "WITHDRAWN"]
    assert data["readiness_status"] in [
        "AWAITING_BRIEFING", "BRIEFED", "CLEARED_TO_WORK", "SAFETY_HOLD", "RELEASED",
    ]


def assert_safety_briefing(data: dict):
    _assert_common(data, "SafetyBriefing")
    assert is_valid_uuid(data.get("crew_id", ""))
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["conductor_operator_ref"], str) and data["conductor_operator_ref"]
    assert isinstance(data["topics"], list) and data["topics"], "topics must be non-empty"
    assert data["status"] in ["CONDUCTED", "ACKNOWLEDGED"]


def assert_timesheet(data: dict):
    _assert_common(data, "TimeSheet")
    assert is_valid_uuid(data.get("crew_id", ""))
    assert data["day_classification"] in ["TRAVEL", "WORK", "STANDBY", "REST"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "CERTIFIED", "REJECTED", "HELD"]
    assert isinstance(data["reported_work_minutes"], int)
    assert isinstance(data["reported_travel_minutes"], int)


def assert_lodging_block(data: dict):
    _assert_common(data, "LodgingBlock")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["hotel_name"], str) and data["hotel_name"]
    assert isinstance(data["block_code"], str) and data["block_code"]
    assert isinstance(data["total_rooms"], int) and data["total_rooms"] >= 0
    assert isinstance(data["nightly_rate_cents"], int)
    assert isinstance(data["assigned_rooms"], int) and data["assigned_rooms"] >= 0
    assert data["assigned_rooms"] <= data["total_rooms"], \
        "assigned_rooms must never exceed total_rooms"


def assert_lodging_assignment(data: dict):
    _assert_common(data, "LodgingAssignment")
    assert is_valid_uuid(data.get("block_id", ""))
    assert is_valid_uuid(data.get("crew_id", ""))
    assert isinstance(data["room_count"], int) and data["room_count"] > 0
    assert data["status"] in ["RESERVED", "OCCUPIED", "CHECKED_OUT", "CANCELLED"]


def assert_per_diem_claim(data: dict):
    _assert_common(data, "PerDiemClaim")
    assert is_valid_uuid(data.get("crew_id", ""))
    assert isinstance(data["member_count"], int) and data["member_count"] >= 1
    assert isinstance(data["meals_provided_count"], int) and 0 <= data["meals_provided_count"] <= 3
    assert data["day_factor_type"] in ["FULL", "TRAVEL"]
    assert data["method_applied"] in ["STANDARD", "ACTUAL"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "HELD"]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("request_id", ""))
    assert is_valid_uuid(data.get("rate_schedule_id", ""))
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "PAID", "VOID",
        "DISPUTED", "CREDIT_PROPOSED", "ESCALATED",
    ]
    assert isinstance(data["provisional_subtotal_cents"], int)
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert data["provisional_total_cents"] == (
        data["provisional_subtotal_cents"] + data["provisional_fee_cents"]
    ), "provisional total must equal subtotal plus fee"
    if data["status"] not in ("DRAFT", "VOID"):
        assert isinstance(data["final_total_cents"], int)
        assert data["final_total_cents"] == (
            data["labor_subtotal_cents"]
            + data["per_diem_subtotal_cents"]
            + data["mobilization_fee_cents"]
        ), "final total must equal labor + per-diem + fee"
    assert isinstance(data["applied_credit_total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_after_action_report(data: dict):
    _assert_common(data, "AfterActionReport")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["summary"], str) and data["summary"]
    assert data["status"] in ["DRAFTING", "SUBMITTED", "ACCEPTED"]
    if data["status"] in ("SUBMITTED", "ACCEPTED"):
        assert isinstance(data["total_crew_days"], int)
        assert isinstance(data["as_certified_total_cents"], int)
        assert isinstance(data["as_billed_total_cents"], int)
        assert data["variance_cents"] == (
            data["as_billed_total_cents"] - data["as_certified_total_cents"]
        ), "variance must equal as-billed minus as-certified"
