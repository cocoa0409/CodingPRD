"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, entity_label: str = "entity"):
    """PRD §2.4: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1"
    )


def assert_crossing(data: dict):
    assert_common_fields(data, "Crossing")
    for field in (
        "dot_crossing_number",
        "railroad_code",
        "road_authority_locality_id",
        "highway_functional_class",
        "warning_device_class",
    ):
        assert isinstance(data.get(field), str) and data[field], (
            f"Crossing.{field} must be a non-empty string"
        )
    assert data["highway_functional_class"] in ("ARTERIAL", "COLLECTOR", "LOCAL")
    for field in ("annual_train_count", "aadt", "school_bus_count"):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"Crossing.{field} must be a non-negative integer"
        )
    assert 1 <= data["train_speed_max_mph"] <= 110
    assert 1 <= data["sight_distance_rating"] <= 5
    assert data["warning_device_class"] in (
        "PASSIVE_CROSSBUCK",
        "FLASHING_LIGHTS",
        "GATES",
        "FOUR_QUADRANT_GATES",
    )
    assert data["status"] in ("ACTIVE", "CLOSURE_PENDING", "CLOSED")
    assert isinstance(data.get("exposure_index"), (int, float))
    assert isinstance(data.get("projected_exposure_index"), (int, float))
    assert isinstance(data.get("incident_count_5yr"), int)
    assert isinstance(data.get("hazard_score"), (int, float))
    assert isinstance(data.get("diagnostic_review_due"), bool)


def assert_locality(data: dict):
    """PRD §2.4: Locality carries only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "Locality.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Locality.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "Locality must not expose updated_at (PRD §2.4)"
    assert "version" not in data, "Locality must not expose version (PRD §2.4)"
    assert isinstance(data.get("locality_name"), str) and data["locality_name"]
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]


def assert_diagnostic_team(data: dict):
    assert_common_fields(data, "DiagnosticTeam")
    assert isinstance(data.get("team_name"), str) and data["team_name"]
    assert isinstance(data.get("lead_agency"), str) and data["lead_agency"]


def assert_diagnostic_review(data: dict):
    assert_common_fields(data, "DiagnosticReview")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert is_valid_uuid(data.get("team_id", ""))
    assert isinstance(data.get("scheduled_date"), str) and data["scheduled_date"]
    assert data["status"] in (
        "SCHEDULED",
        "IN_SESSION",
        "RECOMMENDATIONS_ISSUED",
        "ACCEPTED",
        "SUPERSEDED",
        "CANCELLED",
    )


def assert_incident_report(data: dict):
    assert_common_fields(data, "IncidentReport")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert data["severity"] in ("CASUALTY", "INJURY", "PROPERTY_DAMAGE", "NEAR_MISS")
    for field in ("fatalities", "injuries", "property_damage_cents"):
        assert isinstance(data.get(field), int) and data[field] >= 0
    assert isinstance(data.get("fra_reportable"), bool)
    assert data["status"] in (
        "REPORTED",
        "SCREENED",
        "FIELD_INVESTIGATION",
        "DESK_REVIEW",
        "FINDINGS_ISSUED",
        "FRA_SUBMITTED",
        "CLOSED",
        "REJECTED",
    )


def assert_funding_program(data: dict):
    assert_common_fields(data, "FundingProgram")
    assert isinstance(data.get("fiscal_year"), int)
    assert isinstance(data.get("apportionment_cents"), int)
    assert data["allocation_method"] in ("WATERFALL_BY_RANK", "PROPORTIONAL_SHARE")
    assert data["status"] in ("OPEN", "ALLOCATION_LOCKED", "CLOSED")
    for field in ("available_cents", "encumbered_cents", "eligible_demand_cents"):
        assert isinstance(data.get(field), int), f"FundingProgram.{field} must be int"


def assert_program_pool_invariant(data: dict):
    """PRD §3.4: available_cents + encumbered_cents == apportionment_cents."""
    assert data["available_cents"] + data["encumbered_cents"] == data[
        "apportionment_cents"
    ], (
        f"pool invariant broken: {data['available_cents']} + "
        f"{data['encumbered_cents']} != {data['apportionment_cents']}"
    )


def assert_upgrade_project(data: dict):
    assert_common_fields(data, "UpgradeProject")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["target_device_class"] in (
        "PASSIVE_CROSSBUCK",
        "FLASHING_LIGHTS",
        "GATES",
        "FOUR_QUADRANT_GATES",
    )
    assert isinstance(data.get("estimated_cost_cents"), int)
    assert data["status"] in (
        "PROPOSED",
        "ELIGIBLE",
        "SELECTED",
        "AWARDED",
        "IN_PROGRESS",
        "COMPLETED",
        "WITHDRAWN",
    )


def assert_closure_agreement(data: dict):
    assert_common_fields(data, "ClosureAgreement")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert is_valid_uuid(data.get("locality_id", ""))
    assert data["closure_type"] in ("CLOSURE", "CONSOLIDATION")
    assert isinstance(data.get("computed_incentive_cents"), int)
    assert isinstance(data.get("current_offer_cents"), int)
    assert isinstance(data.get("negotiation_round"), int)
    assert data.get("created_by_party") in ("DOT", "LOCALITY")
    assert data["status"] in (
        "DRAFT",
        "PROPOSED",
        "COUNTERED",
        "DOT_ACCEPTED",
        "LOCALITY_RATIFIED",
        "EXECUTED",
        "REJECTED",
        "WITHDRAWN",
    )


def assert_quiet_zone_application(data: dict):
    assert_common_fields(data, "QuietZoneApplication")
    assert is_valid_uuid(data.get("locality_id", ""))
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "SUPPLEMENT_REQUIRED",
        "REJECTED",
        "EFFECTIVE",
        "SUSPENDED",
        "WITHDRAWN",
    )


def assert_quiet_zone_crossing(data: dict):
    """PRD §2.4: membership rows carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "QuietZoneCrossing.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "QuietZoneCrossing.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, (
        "QuietZoneCrossing must not expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "QuietZoneCrossing must not expose version (PRD §2.4)"
    )
    assert is_valid_uuid(data.get("quiet_zone_application_id", ""))
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert isinstance(data.get("ssm_codes"), list)
    assert data["membership_status"] in ("MEMBER", "REMOVED")


def assert_maintenance_assignment(data: dict):
    assert_common_fields(data, "MaintenanceResponsibilityAssignment")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert data["category"] in ("SIGNAL", "SURFACE", "VEGETATION", "STRIPING")
    assert data["responsible_party"] in ("RAILROAD", "ROAD_AUTHORITY")
    assert isinstance(data.get("effective_from"), str) and data["effective_from"]
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "REVOKED")


def assert_maintenance_work_order(data: dict):
    assert_common_fields(data, "MaintenanceWorkOrder")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert data["category"] in ("SIGNAL", "SURFACE", "VEGETATION", "STRIPING")
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data.get("fouls_track"), bool)
    assert data.get("responsible_party") in ("RAILROAD", "ROAD_AUTHORITY")
    assert data["status"] in (
        "PLANNED",
        "FLAGGING_CONFIRMED",
        "IN_WORK",
        "COMPLETED",
        "CANCELLED",
    )


def assert_preemption_interconnection(data: dict):
    assert_common_fields(data, "PreemptionInterconnection")
    assert is_valid_uuid(data.get("crossing_id", ""))
    assert isinstance(data.get("traffic_signal_ref"), str) and data["traffic_signal_ref"]
    for field in (
        "track_approach_distance_ft",
        "design_train_speed_mph",
        "clear_storage_distance_ft",
        "advance_preemption_seconds",
        "track_clearance_green_seconds",
        "approach_seconds",
        "required_clearance_green_seconds",
        "required_advance_preemption_seconds",
    ):
        assert isinstance(data.get(field), int), (
            f"PreemptionInterconnection.{field} must be an integer"
        )
    assert isinstance(data.get("timing_check_pass"), bool)
    assert data["status"] in (
        "DRAFT",
        "TIMING_VERIFIED",
        "COMMISSIONED",
        "DECOMMISSIONED",
    )
