"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    """PRD §2.5: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["demurrage_free_days"], int)
    assert data["credit_status"] in ("GOOD", "SUSPENDED")


def assert_siding(data: dict):
    _assert_common(data, "IndustrySiding")
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["capacity_cars"], int) and data["capacity_cars"] >= 0
    assert data["maintenance_agreement_status"] in ("ACTIVE", "EXPIRED", "SUSPENDED")


def assert_car_order(data: dict):
    _assert_common(data, "CarOrder")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["siding_id"])
    assert data["car_type"] in ("BOX", "HOPPER", "TANK", "FLAT", "GONDOLA")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in (
        "PLACED", "ACCEPTED", "PARTIALLY_FURNISHED", "FURNISHED",
        "RELEASED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["cars_furnished_count"], int) and data["cars_furnished_count"] >= 0


def assert_railcar(data: dict):
    _assert_common(data, "Railcar")
    assert isinstance(data["reporting_mark"], str) and data["reporting_mark"]
    assert data["car_type"] in ("BOX", "HOPPER", "TANK", "FLAT", "GONDOLA")
    assert data["ownership"] in ("HOME", "FOREIGN")
    assert data["status"] in (
        "AVAILABLE", "ASSIGNED", "LOADED", "IN_TRANSIT",
        "INTERCHANGED_OUT", "BAD_ORDER", "HELD",
    )
    assert isinstance(data["hire_rate_per_hour_cents"], int)
    assert isinstance(data["hire_rate_per_mile_cents"], int)


def assert_switch_job(data: dict):
    _assert_common(data, "SwitchJob")
    assert data["status"] in ("PLANNED", "ASSIGNED", "COMPLETED", "ANNULLED")


def assert_train_movement(data: dict):
    _assert_common(data, "TrainMovement")
    assert isinstance(data["symbol"], str) and data["symbol"]
    assert isinstance(data["route_segment_ids"], list)
    assert data["status"] in (
        "PLANNED", "READY", "DEPARTED", "HELD", "ARRIVED", "SETTLED", "ANNULLED",
    )
    assert isinstance(data["max_speed_mph"], int)


def assert_interchange_event(data: dict):
    _assert_common(data, "InterchangeEvent")
    assert data["direction"] in ("RECEIVED", "DELIVERED")
    assert is_valid_uuid(data["railcar_id"])
    assert data["status"] in ("REPORTED", "CONFIRMED", "DISPUTED")


def assert_car_hire_statement(data: dict):
    _assert_common(data, "CarHireStatement")
    assert is_valid_uuid(data["railcar_id"])
    assert isinstance(data["accrued_hours"], int) and data["accrued_hours"] >= 0
    assert isinstance(data["accrued_miles"], int) and data["accrued_miles"] >= 0
    assert data["status"] in ("OPEN", "CLOSED", "SETTLED", "DISPUTED")


def assert_waybill(data: dict):
    _assert_common(data, "Waybill")
    assert is_valid_uuid(data["railcar_id"])
    assert is_valid_uuid(data["origin_customer_id"])
    assert data["commodity"] in ("GRAIN", "LUMBER", "CHEMICALS")
    assert isinstance(data["weight_tons"], int)
    assert data["status"] in ("CREATED", "RATED", "BILLED", "SETTLED")


def assert_revenue_division(data: dict):
    _assert_common(data, "RevenueDivision")
    assert is_valid_uuid(data["waybill_id"])
    assert data["basis"] in ("MILEAGE_PRORATE", "AGREED_PERCENTAGE")
    assert isinstance(data["our_share_cents"], int)
    assert isinstance(data["connecting_share_cents"], int)
    assert data["status"] in ("DRAFT", "AGREED", "DISPUTED", "SETTLED")


def assert_track_segment(data: dict):
    _assert_common(data, "TrackSegment")
    assert data["fra_class"] in (
        "EXCEPTED", "CLASS_1", "CLASS_2", "CLASS_3", "CLASS_4", "CLASS_5",
    )
    assert isinstance(data["effective_speed_mph"], int)
    assert isinstance(data["defect_open"], bool)
    assert isinstance(data["is_overdue"], bool)
    assert data["status"] in ("IN_SERVICE", "RESTRICTED")


def assert_track_inspection(data: dict):
    _assert_common(data, "TrackInspection")
    assert is_valid_uuid(data["segment_id"])
    assert data["status"] in ("SCHEDULED", "FILED", "DEFECT_FILED", "REMEDIATED", "WAIVED")


def assert_crew_member(data: dict):
    _assert_common(data, "CrewMember")
    assert data["craft"] in ("ENGINEER", "CONDUCTOR")
    assert data["status"] in ("AVAILABLE", "ON_DUTY", "RESTING")
    assert isinstance(data["on_duty_minutes_rolling_24h"], int)
    assert isinstance(data["on_duty_minutes_month"], int)
    assert isinstance(data["hos_available_minutes"], int) and data["hos_available_minutes"] >= 0


def assert_crew_call(data: dict):
    _assert_common(data, "CrewCall")
    assert is_valid_uuid(data["crew_member_id"])
    assert data["status"] in ("CALLED", "ACCEPTED", "DECLINED", "ON_DUTY", "RELIEVED", "EXPIRED")


def assert_incident(data: dict):
    _assert_common(data, "Incident")
    assert data["incident_type"] in ("DERAILMENT", "COLLISION", "CROSSING", "HAZMAT", "INJURY")
    assert is_valid_uuid(data["segment_id"])
    assert isinstance(data["estimated_damage_cents"], int)
    assert isinstance(data["fra_reportable"], bool)
    assert data["status"] in ("REPORTED", "INVESTIGATING", "FRA_FILED", "CLOSED", "REOPENED")


def assert_grant_project(data: dict):
    _assert_common(data, "GrantProject")
    assert isinstance(data["award_amount_cents"], int)
    assert data["status"] in ("AWARDED", "ACTIVE", "SUSPENDED", "COMPLETED")
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["drawn_cents"], int)
    assert isinstance(data["remaining_cents"], int)


def assert_grant_milestone(data: dict):
    _assert_common(data, "GrantMilestone")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["milestone_value_cents"], int)
    assert data["status"] in ("PENDING", "SUBMITTED", "APPROVED", "REJECTED", "PAID")


def assert_grant_award_conservation(project: dict):
    """PRD §3.9: award dollars are conserved across committed + drawn + remaining."""
    total = project["committed_cents"] + project["drawn_cents"] + project["remaining_cents"]
    assert total == project["award_amount_cents"], (
        f"committed({project['committed_cents']}) + drawn({project['drawn_cents']}) "
        f"+ remaining({project['remaining_cents']}) must equal "
        f"award({project['award_amount_cents']}), got {total}"
    )


def assert_division_conservation(division: dict):
    """PRD §3.5: our share plus the connecting share must equal the total charge."""
    total = division["our_share_cents"] + division["connecting_share_cents"]
    assert total == division["total_charge_cents"], (
        f"our_share({division['our_share_cents']}) + connecting({division['connecting_share_cents']}) "
        f"must equal total({division['total_charge_cents']}), got {total}"
    )
