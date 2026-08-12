"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BurnPermitStatus,
    BurnPlanStatus,
    ContingencyPlanStatus,
    CostShareStatus,
    CrewAssignmentStatus,
    ExecutionPhase,
    IgnitionPlanStatus,
    IncidentBillingStatus,
    IncidentResponseStatus,
    MonitoringReportStatus,
    NotificationStatus,
    ResourceOrderStatus,
    SmokeApprovalStatus,
)


def _assert_common_fields(data: dict, entity: str):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_association(data: dict):
    _assert_common_fields(data, "BurnAssociation")
    assert isinstance(data["name"], str) and data["name"]
    for field in ("airshed_daily_acres_cap", "single_claim_cap_cents",
                  "landowner_liability_cap_cents", "fund_balance_cents"):
        assert isinstance(data[field], int), f"BurnAssociation.{field} must be int"
    assert data["fund_posture"] in ("FUND_NORMAL", "FUND_RESTRICTED")


def assert_landowner(data: dict):
    _assert_common_fields(data, "Landowner")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["liability_waiver_signed"], bool)
    assert data["standing"] in ("GOOD_STANDING", "SUSPENDED")
    assert isinstance(data["outstanding_liability_cents"], int)


def assert_parcel(data: dict):
    _assert_common_fields(data, "Parcel")
    assert is_valid_uuid(data.get("landowner_id", ""))
    assert isinstance(data["acreage"], int) and data["acreage"] > 0
    assert data["fuel_model"] in ("GRASS", "BRUSH", "TIMBER")
    assert data["slope_class"] in ("FLAT", "MODERATE", "STEEP")
    assert isinstance(data["wui_adjacent"], bool)
    assert isinstance(data["hazard_score"], int)
    assert 0 <= data["hazard_score"] <= 120, "hazard_score ranges 0..120 (PRD §3.1)"


def assert_burn_boss(data: dict):
    _assert_common_fields(data, "BurnBoss")
    assert isinstance(data["name"], str) and data["name"]
    assert data["certification_tier"] in ("RXB1", "RXB2", "RXB3")


def assert_contractor(data: dict):
    _assert_common_fields(data, "Contractor")
    assert data["resource_type"] in ("ENGINE", "HAND_CREW", "DOZER", "WATER_TENDER")
    assert isinstance(data["capacity_units"], int)
    assert isinstance(data["no_show_count"], int)
    assert data["standing"] in ("GOOD_STANDING", "SUSPENDED")
    assert isinstance(data["available_units"], int)


def assert_burn_plan(data: dict):
    _assert_common_fields(data, "BurnPlan")
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert is_valid_uuid(data.get("author_boss_id", ""))
    assert isinstance(data["planned_acres"], int) and data["planned_acres"] > 0
    assert data["status"] in {s.value for s in BurnPlanStatus}
    assert isinstance(data["treatment_lines"], list) and data["treatment_lines"]


def assert_burn_permit(data: dict):
    _assert_common_fields(data, "BurnPermit")
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    assert isinstance(data["notifications_required"], int)
    assert isinstance(data["notifications_completed"], int)
    assert data["status"] in {s.value for s in BurnPermitStatus}


def assert_permit_notification(data: dict):
    _assert_common_fields(data, "PermitNotification")
    assert data["channel"] in ("MAIL", "PHONE", "IN_PERSON")
    assert data["status"] in {s.value for s in NotificationStatus}


def assert_smoke_approval(data: dict):
    _assert_common_fields(data, "SmokeApproval")
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    assert isinstance(data["requested_acres"], int) and data["requested_acres"] > 0
    assert data["status"] in {s.value for s in SmokeApprovalStatus}


def assert_contingency_plan(data: dict):
    _assert_common_fields(data, "ContingencyPlan")
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    assert data["status"] in {s.value for s in ContingencyPlanStatus}


def assert_ignition_plan(data: dict):
    _assert_common_fields(data, "IgnitionPlan")
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    assert data["ignition_method"] in ("DRIP_TORCH", "AERIAL", "HAND_LINE")
    assert data["status"] in {s.value for s in IgnitionPlanStatus}
    assert isinstance(data["steps"], list) and data["steps"]


def assert_resource_order(data: dict):
    _assert_common_fields(data, "ResourceOrder")
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    for field in ("required_engines", "required_hand_crews", "required_dozers",
                  "required_water_tenders", "confirmed_engines",
                  "confirmed_hand_crews", "confirmed_dozers", "confirmed_water_tenders"):
        assert isinstance(data[field], int), f"ResourceOrder.{field} must be int"
    assert data["status"] in {s.value for s in ResourceOrderStatus}


def assert_crew_assignment(data: dict):
    _assert_common_fields(data, "CrewAssignment")
    assert is_valid_uuid(data.get("resource_order_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert isinstance(data["units"], int) and data["units"] > 0
    assert data["status"] in {s.value for s in CrewAssignmentStatus}


def assert_burn_execution(data: dict):
    _assert_common_fields(data, "BurnExecution")
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    assert isinstance(data["plan_version_at_schedule"], int)
    assert data["phase"] in {s.value for s in ExecutionPhase}


def assert_weather_observation(data: dict):
    """Audit-record resource: id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "WeatherObservation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "WeatherObservation.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "WeatherObservation must not carry updated_at"
    assert "version" not in data, "WeatherObservation must not carry version"
    for field in ("wind_mph", "fuel_moisture_pct", "rh_pct", "temp_f", "mixing_height_ft"):
        assert isinstance(data[field], int)
    assert isinstance(data["in_prescription"], bool)


def assert_go_no_go_checklist(data: dict):
    """Audit-record resource: id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "GoNoGoChecklist.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "GoNoGoChecklist.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "GoNoGoChecklist must not carry updated_at"
    assert "version" not in data, "GoNoGoChecklist must not carry version"
    assert data["verdict"] in ("GO", "NO_GO")
    assert isinstance(data["answers"], list)


def assert_incident(data: dict):
    _assert_common_fields(data, "Incident")
    assert is_valid_uuid(data.get("burn_execution_id", ""))
    assert data["incident_type"] in ("ESCAPE", "SPOT", "SMOKE_INTRUSION")
    assert data["response_status"] in {s.value for s in IncidentResponseStatus}
    assert data["billing_status"] in {s.value for s in IncidentBillingStatus}


def assert_monitoring_report(data: dict):
    _assert_common_fields(data, "MonitoringReport")
    assert is_valid_uuid(data.get("burn_execution_id", ""))
    assert data["report_type"] in ("FIRST_24H", "SEVEN_DAY", "THIRTY_DAY")
    assert data["status"] in {s.value for s in MonitoringReportStatus}


def assert_cost_share_agreement(data: dict):
    _assert_common_fields(data, "CostShareAgreement")
    assert is_valid_uuid(data.get("landowner_id", ""))
    assert is_valid_uuid(data.get("burn_plan_id", ""))
    assert data["funding_tier"] in ("STANDARD", "PRIORITY", "LEGACY")
    assert isinstance(data["provisional_estimate_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert data["status"] in {s.value for s in CostShareStatus}


def assert_liability_claim(data: dict):
    _assert_common_fields(data, "LiabilityClaim")
    assert is_valid_uuid(data.get("incident_id", ""))
    assert data["outcome"] in ("PENDING", "LANDOWNER_LIABLE", "ASSOCIATION_LIABLE", "NOT_LIABLE")
    assert data["status"] in {
        "FILED", "UNDER_INVESTIGATION", "ADJUDICATED", "DISMISSED",
        "PAID", "PAYMENT_REVERSED", "CLOSED",
    }


def assert_fund_invariants(assoc: dict):
    """Fund posture is derived from the balance (PRD §2.10)."""
    balance = assoc["fund_balance_cents"]
    assert isinstance(balance, int)
    expected = "FUND_RESTRICTED" if balance < 200_000 else "FUND_NORMAL"
    assert assoc["fund_posture"] == expected, (
        f"fund_posture {assoc['fund_posture']} inconsistent with balance {balance}"
    )
