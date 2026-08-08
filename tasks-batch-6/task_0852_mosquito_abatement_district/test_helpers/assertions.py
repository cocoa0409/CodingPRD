"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MS_TIMESTAMP_LENGTH = len("2026-06-05T09:00:00.000Z")


def assert_rendered_instant(value: str, field: str = "timestamp") -> None:
    """Every server-rendered datetime carries exactly three fractional digits and a Z."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not ISO 8601 UTC: {value!r}"
    assert len(value) == MS_TIMESTAMP_LENGTH and value.endswith("Z") and value[19] == ".", (
        f"{field} must be rendered with exactly three fractional digits: {value!r}"
    )


def assert_calendar_date(value: str, field: str = "date") -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a plain YYYY-MM-DD calendar date: {value!r}"
    )


def assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert_rendered_instant(data.get("created_at", ""), f"{entity}.created_at")
    assert_rendered_instant(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, entity: str) -> None:
    """Append-only evidence records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert_rendered_instant(data.get("created_at", ""), f"{entity}.created_at")
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_service_area(data: dict) -> None:
    assert_common_fields(data, "ServiceArea")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert_calendar_date(data["season_start_date"], "ServiceArea.season_start_date")
    assert isinstance(data["population"], int) and data["population"] >= 0
    assert data["risk_posture"] in ("NORMAL", "ELEVATED", "EMERGENCY")
    assert data["posture_source"] in ("NO_ASSESSMENT", "INDEX", "POSITIVE_OVERRIDE")
    assert data["latest_confirmed_vector_index"] >= 0
    assert data["seasonal_application_count"] >= 0
    assert_request_count_partition(data)


def assert_request_count_partition(area: dict) -> None:
    """request_open + request_resolved + request_closed always equals request_total."""
    total = area["request_total_count"]
    parts = (
        area["request_open_count"]
        + area["request_resolved_count"]
        + area["request_closed_count"]
    )
    assert parts == total, (
        f"Complaint partition broken: open {area['request_open_count']} + resolved "
        f"{area['request_resolved_count']} + closed {area['request_closed_count']} "
        f"!= total {total}"
    )


def assert_sensitive_site(data: dict) -> None:
    assert_common_fields(data, "SensitiveSite")
    assert data["site_type"] in ("APIARY", "ORGANIC_FARM", "AQUACULTURE", "SCHOOL")
    assert isinstance(data["operator_name"], str) and 1 <= len(data["operator_name"]) <= 120
    assert "@" in data["contact_email"]
    assert isinstance(data["buffer_meters"], int) and data["buffer_meters"] >= 0
    assert_calendar_date(data["registered_on"], "SensitiveSite.registered_on")


def assert_trap_site(data: dict) -> None:
    assert_common_fields(data, "TrapSite")
    assert data["trap_type"] in ("CDC_LIGHT", "GRAVID", "BG_SENTINEL")
    assert data["habitat"] in ("URBAN", "WETLAND", "AGRICULTURAL", "STORMWATER")
    assert isinstance(data["is_active"], bool)
    assert data["season_positive_count"] >= 0


def assert_trap_collection(data: dict) -> None:
    assert_common_fields(data, "TrapCollection")
    assert data["status"] in ("LOGGED", "SUBMITTED", "POOLED", "VOIDED")
    assert data["trap_nights"] >= 1
    assert data["female_count"] >= 0
    assert data["species"] in (
        "CULEX_PIPIENS", "CULEX_TARSALIS", "AEDES_AEGYPTI", "AEDES_ALBOPICTUS", "OTHER",
    )
    assert data["pooled_mosquito_count"] >= 0
    assert data["positive_pool_count"] >= 0
    assert data["wnv_detected"] is (data["positive_pool_count"] >= 1), (
        "wnv_detected is true precisely when positive_pool_count is 1 or more"
    )


def assert_lab_pool(data: dict) -> None:
    assert_common_fields(data, "LabPool")
    assert data["status"] in (
        "CREATED", "IN_TESTING", "RESULT_POSITIVE", "RESULT_NEGATIVE", "INVALID", "DISCARDED",
    )
    assert 1 <= data["pool_size"] <= 50
    assert data["assay"] in ("RT_PCR", "VECTEST")
    assert 0 <= data["retest_count"] <= 2


def assert_risk_assessment(data: dict) -> None:
    assert_common_fields(data, "RiskAssessment")
    assert data["status"] in ("OPEN", "CONFIRMED", "SUPERSEDED")
    assert_calendar_date(data["as_of_date"], "RiskAssessment.as_of_date")
    assert isinstance(data["is_stale"], bool)
    assert data["stale_reason"] in (None, "LAB_RESULT", "NEW_COLLECTION")
    assert data["abundance_index"] >= 0
    assert data["larval_index"] >= 0
    assert data["degree_days"] >= 0
    assert data["mir_provisional"] >= 0
    assert 0 <= data["vector_index_provisional"] <= 100


def assert_pesticide_product(data: dict) -> None:
    assert_common_fields(data, "PesticideProduct")
    assert data["active_ingredient"] in (
        "BTI", "METHOPRENE", "PERMETHRIN", "MALATHION", "NALED",
    )
    assert data["application_method"] in ("LARVICIDE", "ADULTICIDE", "AERIAL")
    assert data["label_rate_ml_per_acre"] > 0
    assert data["reentry_interval_hours"] >= 0
    assert isinstance(data["cost_cents_per_liter"], int) and data["cost_cents_per_liter"] >= 0
    assert_inventory_partition(data)


def assert_inventory_partition(product: dict) -> None:
    """on_hand_ml + committed_ml + applied_ml always equals received_total_ml."""
    total = product["on_hand_ml"] + product["committed_ml"] + product["applied_ml"]
    assert total == pytest.approx(product["received_total_ml"], abs=0.005), (
        f"Material partition broken: on_hand {product['on_hand_ml']} + committed "
        f"{product['committed_ml']} + applied {product['applied_ml']} != received "
        f"{product['received_total_ml']}"
    )
    assert product["on_hand_ml"] >= -0.005, "on_hand_ml must never go negative"
    assert product["committed_ml"] >= -0.005, "committed_ml must never go negative"
    assert product["applied_ml"] >= -0.005, "applied_ml must never go negative"


def assert_applicator(data: dict) -> None:
    assert_common_fields(data, "Applicator")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["license_category"] in ("LARVICIDE_ONLY", "ADULTICIDE", "AERIAL")
    assert_calendar_date(data["license_expires_on"], "Applicator.license_expires_on")
    assert data["assigned_route_count"] >= 0


def assert_treatment_plan(data: dict) -> None:
    assert_common_fields(data, "TreatmentPlan")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "SCHEDULED",
        "IN_PROGRESS", "SUSPENDED", "COMPLETED", "CANCELLED",
    )
    assert data["treatment_type"] in ("LARVICIDE", "ADULTICIDE", "AERIAL")
    assert data["required_approvals"] in (1, 2)
    assert isinstance(data["approver_user_ids"], list)
    assert isinstance(data["notification_required"], bool)
    assert data["revision_count"] >= 0
    for money_field in (
        "material_cost_cents", "labor_cost_cents", "subtotal_cents",
        "admin_fee_cents", "total_cost_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"TreatmentPlan.{money_field} must be whole integer cents"
        )
    assert data["subtotal_cents"] == data["material_cost_cents"] + data["labor_cost_cents"]
    assert data["total_cost_cents"] == data["subtotal_cents"] + data["admin_fee_cents"]


def assert_treatment_route(data: dict) -> None:
    assert_common_fields(data, "TreatmentRoute")
    assert data["status"] in (
        "PLANNED", "COMMITTED", "EXECUTED", "VERIFIED", "VOIDED", "RELEASED",
    )
    assert data["duration_minutes"] >= 1
    assert data["planned_acres"] > 0
    assert data["swath_radius_m"] >= 0
    assert_rendered_instant(data["window_start"], "TreatmentRoute.window_start")
    assert_rendered_instant(data["window_end"], "TreatmentRoute.window_end")


def assert_notification(data: dict) -> None:
    assert_common_fields(data, "Notification")
    assert data["status"] in (
        "QUEUED", "SENT", "ACKNOWLEDGED", "FAILED", "EXPIRED", "UNDELIVERABLE",
    )
    assert data["channel"] in ("EMAIL", "SMS", "PHONE")
    assert 0 <= data["attempt_count"] <= 3


def assert_service_request(data: dict) -> None:
    assert_common_fields(data, "ServiceRequest")
    assert data["handling_status"] in (
        "RECEIVED", "TRIAGED", "ASSIGNED", "INSPECTED", "RESOLVED", "CLOSED",
    )
    assert data["verification_status"] in ("UNVERIFIED", "FIELD_CONFIRMED", "UNFOUNDED")
    assert data["priority"] in ("ROUTINE", "PRIORITY", "URGENT")
    assert data["category"] in (
        "STANDING_WATER", "ADULT_ACTIVITY", "DEAD_BIRD", "SPRAY_CONCERN",
    )
    assert data["reopen_count"] >= 0


def assert_larval_inspection(data: dict) -> None:
    assert_append_only_fields(data, "LarvalInspection")
    assert data["dips"] >= 1
    assert data["larvae_count"] >= 0
    assert data["habitat"] in ("CATCH_BASIN", "DITCH", "MARSH", "CONTAINER")


def assert_weather_observation(data: dict) -> None:
    assert_append_only_fields(data, "WeatherObservation")
    assert_calendar_date(data["obs_date"], "WeatherObservation.obs_date")
    assert data["tmin_c"] <= data["tmax_c"]
    assert data["degree_day"] >= 0


def assert_index(actual, expected, field: str = "index") -> None:
    """Surveillance indices and volumes are exact decimals; compare tightly."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {field} {expected}, got {actual}"
    )
