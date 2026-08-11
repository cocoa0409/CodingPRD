"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Each assert_{entity} checks the fields the PRD names on that resource:
presence and type only — specific values are asserted by the tests themselves.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_project(data: dict):
    _assert_common(data, "Project")
    assert isinstance(data["name"], str) and data["name"]
    assert data["measurement_basis"] in ("IN_PLACE", "SCOW")
    assert isinstance(data["base_rate_cents_per_cy"], int)
    assert data["base_rate_cents_per_cy"] > 0
    assert isinstance(data["standby_rate_cents_per_hour"], int)
    assert data["standby_rate_cents_per_hour"] > 0
    assert isinstance(data["liquidated_damages_cents_per_day"], int)
    assert data["liquidated_damages_cents_per_day"] >= 0
    assert data["status"] in ("PLANNED", "ACTIVE", "CLOSED_OUT")
    assert data["compliance_posture"] in ("CLEAR", "RESTRICTED", "SUSPENDED")
    assert isinstance(data["total_certified_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["outstanding_payable_cents"], int)


def assert_project_ledger_invariant(data: dict):
    """PRD §3.1: outstanding payable is always certified minus paid."""
    assert data["outstanding_payable_cents"] == (
        data["total_certified_cents"] - data["total_paid_cents"]
    ), (
        f"outstanding {data['outstanding_payable_cents']} != certified "
        f"{data['total_certified_cents']} - paid {data['total_paid_cents']}"
    )


def assert_permit(data: dict):
    _assert_common(data, "Permit")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert isinstance(data["turbidity_limit_ntu"], int)
    assert data["turbidity_limit_ntu"] > 0
    assert isinstance(data["turbidity_ceiling_ntu"], int)
    assert data["turbidity_ceiling_ntu"] > data["turbidity_limit_ntu"]
    assert isinstance(data["turbidity_averaging_hours"], int)
    assert data["turbidity_averaging_hours"] > 0
    assert isinstance(data["species_standdown_hours"], int)
    assert data["species_standdown_hours"] >= 0
    assert data["status"] in ("ISSUED", "EXPIRED")


def assert_reach(data: dict):
    _assert_common(data, "Reach")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["design_quantity_cy"], int)
    assert data["design_quantity_cy"] > 0
    assert data["required_depth_ft"] > 0
    assert data["allowable_overdepth_ft"] >= 0
    assert isinstance(data["overdepth_allowance_cy"], int)
    assert data["overdepth_allowance_cy"] >= 0
    assert data["status"] in (
        "PENDING",
        "PRE_SURVEYED",
        "DREDGING",
        "POST_SURVEY_SUBMITTED",
        "ACCEPTED",
    )
    assert isinstance(data["removed_in_place_cy"], (int, float))
    assert isinstance(data["cumulative_certified_quantity_cy"], (int, float))


def assert_dredge_plant(data: dict):
    _assert_common(data, "DredgePlant")
    assert isinstance(data["contractor_ref"], str) and data["contractor_ref"]
    assert data["plant_type"] in ("CUTTER_SUCTION", "HOPPER", "CLAMSHELL", "BACKHOE")
    assert isinstance(data["rated_daily_production_cy"], int)
    assert data["rated_daily_production_cy"] > 0
    assert data["status"] in ("REGISTERED", "OUT_OF_SERVICE", "RETIRED")


def assert_dredge_plan(data: dict):
    _assert_common(data, "DredgePlan")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["plant_id"], str)
    assert data["material_class"] in ("SAND", "SILT", "CLAY", "GRAVEL", "ROCK")
    assert is_iso8601_timestamp(data["planned_start_utc"])
    assert is_iso8601_timestamp(data["planned_end_utc"])
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["nominal_daily_production_cy"], (int, float))
    assert isinstance(data["risk_adjusted_daily_production_cy"], (int, float))
    assert isinstance(data["nominal_duration_days"], int)
    assert isinstance(data["risk_adjusted_duration_days"], int)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "CHANGES_REQUESTED",
        "APPROVED",
        "SUPERSEDED",
    )


def assert_survey(data: dict):
    _assert_common(data, "Survey")
    assert isinstance(data["reach_id"], str)
    assert data["kind"] in ("PRE_DREDGE", "POST_DREDGE")
    assert isinstance(data["measured_volume_cy"], int)
    assert data["measured_volume_cy"] >= 0
    assert data["min_sounding_depth_ft"] > 0
    assert isinstance(data["submitted_by_user_id"], str)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def assert_dredge_event(data: dict):
    _assert_common(data, "DredgeEvent")
    assert isinstance(data["reach_id"], str)
    assert isinstance(data["plant_id"], str)
    assert is_iso8601_timestamp(data["started_utc"])
    assert data["status"] in ("ACTIVE", "SHUTDOWN", "COMPLETED")
    assert data["shutdown_reason"] in (None, "SPECIES", "TURBIDITY", "EQUIPMENT", "WINDOW")
    assert isinstance(data["shutdown_accumulated_hours"], (int, float))


def assert_disposal_site(data: dict):
    _assert_common(data, "DisposalSite")
    assert isinstance(data["name"], str) and data["name"]
    assert data["site_type"] in ("UPLAND_CONFINED", "OPEN_WATER", "BEACH_NOURISHMENT")
    assert isinstance(data["capacity_cy"], int)
    assert data["capacity_cy"] > 0
    assert data["bulking_factor"] > 0
    assert isinstance(data["used_cy"], (int, float))
    assert isinstance(data["remaining_cy"], (int, float))
    assert data["status"] in ("OPEN", "FULL", "CLOSED")


def assert_capacity_invariant(site: dict):
    """PRD §3.1/§3.7: at all times used plus remaining equals capacity exactly."""
    assert abs(site["used_cy"] + site["remaining_cy"] - site["capacity_cy"]) < 1e-6, (
        f"used {site['used_cy']} + remaining {site['remaining_cy']} != "
        f"capacity {site['capacity_cy']}"
    )


def assert_placement_ticket(data: dict):
    _assert_common(data, "PlacementTicket")
    assert isinstance(data["dredge_event_id"], str)
    assert isinstance(data["disposal_site_id"], str)
    assert is_iso8601_timestamp(data["placed_utc"])
    assert isinstance(data["declared_volume_cy"], int)
    assert data["declared_volume_cy"] > 0
    assert isinstance(data["reported_by_user_id"], str)
    assert data["status"] in ("REPORTED", "CONFIRMED", "REJECTED", "VOIDED")


def assert_standby_claim(data: dict):
    _assert_common(data, "StandbyClaim")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["plant_id"], str)
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])
    assert data["claimed_hours"] > 0
    assert data["reason"] in (
        "WEATHER",
        "SPECIES_SHUTDOWN",
        "OWNER_DIRECTED",
        "EQUIPMENT_BREAKDOWN",
    )
    assert isinstance(data["payable_hours"], (int, float))
    assert isinstance(data["payable_amount_cents"], int)
    assert isinstance(data["claimed_by_user_id"], str)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "SETTLED")


def assert_species_sighting(data: dict):
    _assert_common(data, "SpeciesSighting")
    assert isinstance(data["project_id"], str)
    assert data["species_class"] in ("FISH", "MAMMAL", "REPTILE", "BIRD")
    assert is_iso8601_timestamp(data["observed_utc"])
    assert isinstance(data["reported_by_user_id"], str)
    assert data["status"] in ("ACTIVE", "CLEARED")


def assert_turbidity_reading(data: dict):
    """Append-only resource (PRD §2.5): id + created_at, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "TurbidityReading.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "TurbidityReading.created_at must be ISO 8601"
    assert "updated_at" not in data, "TurbidityReading must not carry updated_at"
    assert "version" not in data, "TurbidityReading must not carry version"
    assert isinstance(data["project_id"], str)
    assert isinstance(data["value_ntu"], int)
    assert data["value_ntu"] >= 0
    assert is_iso8601_timestamp(data["taken_utc"])
    assert isinstance(data["recorded_by_user_id"], str)


def assert_payment_certificate(data: dict):
    _assert_common(data, "PaymentCertificate")
    assert isinstance(data["project_id"], str)
    assert data["certificate_type"] in ("INTERIM", "FINAL")
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])
    assert isinstance(data["reach_ids"], list)
    assert isinstance(data["submitted_by_user_id"], str)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "AUDIT_HOLD",
        "CERTIFIED",
        "DISPUTED",
        "PAID",
        "VOIDED",
    )


def assert_certificate_amounts(data: dict):
    """PRD §3.9 computed figures exist once a certificate snapshot is frozen."""
    for field in (
        "quantity_cy",
        "quantity_amount_cents",
        "standby_amount_cents",
        "liquidated_damages_cents",
        "reconciliation_delta_pct",
        "survey_derived_total_cy",
        "scow_derived_total_cy",
        "total_amount_cents",
    ):
        assert field in data, f"frozen snapshot must carry {field}"
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
