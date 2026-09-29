"""Reusable shape and invariant assertions."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict) -> None:
    """Every entity except Jurisdiction carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int), data["version"]
    assert data["version"] >= 1, data["version"]


def assert_has_fields(data: dict, fields) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"missing fields: {missing}"


def assert_party(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        [
            "name",
            "party_type",
            "contact_email",
            "mobilization_buffer_minutes",
            "daily_crew_capacity",
            "license_number",
        ],
    )


def assert_jurisdiction(data: dict) -> None:
    """Jurisdiction is immutable: id + created_at only, no updated_at, no version."""
    assert is_valid_uuid(data["id"]), data["id"]
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert "updated_at" not in data, "Jurisdiction must not expose updated_at"
    assert "version" not in data, "Jurisdiction must not expose version"
    assert_has_fields(
        data,
        [
            "name",
            "code",
            "repermit_required_for_reinstall",
            "reinspection_required",
            "inspection_slots_per_day",
            "backlog_days",
            "permit_review_days",
            "expedite_fee_cents",
        ],
    )


def assert_project(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        [
            "site_address",
            "ownership_model",
            "system_dc_kw",
            "roofer_party_id",
            "solar_owner_party_id",
            "system_owner_party_id",
            "solar_contractor_party_id",
            "baseline_daily_kwh",
            "downtime_days_estimated",
            "upgrade_budget_cents",
            "phase",
            "posture",
            "negotiation_round",
            "required_approval_party_count",
            "provisional_credit_cents",
            "final_credit_cents",
            "credit_authorized_cents",
            "credit_reserved_cents",
            "credit_settled_cents",
            "credit_released_cents",
            "weather_abort_count",
            "warranty_notice_status",
            "warranty_preserved",
            "registered_unit_count",
            "stored_unit_count",
            "reinstalled_unit_count",
            "scrapped_unit_count",
            "damaged_unit_count",
            "open_critical_finding_count",
            "scoped_upgrade_cost_cents",
            "downtime_days_actual",
        ],
    )


def assert_party_approval(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        [
            "project_id",
            "party_id",
            "approval_role",
            "status",
            "round_recorded",
            "veto_flag",
            "change_request_count",
        ],
    )


def assert_array_circuit(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        ["project_id", "circuit_label", "module_count", "dc_kw", "status",
         "interlock_verified"],
    )


def assert_storage_bin(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        ["project_id", "bin_label", "capacity_slots", "climate_controlled",
         "accepts_unit_types", "occupied_slots"],
    )


def assert_hardware_unit(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        [
            "project_id",
            "array_circuit_id",
            "storage_bin_id",
            "unit_type",
            "manufacturer",
            "model_code",
            "serial_number",
            "rated_watts",
            "handling_status",
            "condition_grade",
            "warranty_risk_points",
        ],
    )


def assert_deck_finding(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        [
            "project_id",
            "finding_type",
            "severity",
            "affected_area_sqft",
            "attachment_count_affected",
            "status",
            "upgrade_cost_cents",
            "requires_repermit",
        ],
    )


def assert_permit_application(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        ["project_id", "jurisdiction_id", "scope", "status", "expedited",
         "fee_cents", "revision_count"],
    )


def assert_inspection(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        ["permit_application_id", "inspection_type", "slot_date",
         "window_start_utc", "window_end_utc", "status", "attempt_number"],
    )


def assert_work_window(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        ["project_id", "party_id", "trade", "start_utc", "end_utc", "status",
         "weather_risk_score"],
    )


def assert_sourcing_order(data: dict) -> None:
    assert_common_fields(data)
    assert_has_fields(
        data,
        [
            "project_id",
            "hardware_unit_id",
            "requested_model_code",
            "offered_manufacturer",
            "offered_model_code",
            "offered_rated_watts",
            "unit_cost_cents",
            "watt_delta_pct",
            "tolerance_pct",
            "match_class",
            "status",
        ],
    )


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_credit_ledger_identity(project: dict) -> None:
    """credit_authorized_cents == reserved + settled + released."""
    total = (
        project["credit_reserved_cents"]
        + project["credit_settled_cents"]
        + project["credit_released_cents"]
    )
    assert project["credit_authorized_cents"] == total, (
        f"ledger identity broken: authorized={project['credit_authorized_cents']} "
        f"reserved={project['credit_reserved_cents']} "
        f"settled={project['credit_settled_cents']} "
        f"released={project['credit_released_cents']}"
    )


def assert_unit_population_identity(project: dict, units) -> None:
    """registered_unit_count equals the number of units across all handling states."""
    assert project["registered_unit_count"] == len(units), (
        f"registered_unit_count={project['registered_unit_count']} "
        f"but {len(units)} units exist"
    )
    stored = [u for u in units if u["handling_status"] == "STORED"]
    reinstalled = [u for u in units if u["handling_status"] == "REINSTALLED"]
    scrapped = [u for u in units if u["handling_status"] == "SCRAPPED"]
    assert project["stored_unit_count"] == len(stored), project["stored_unit_count"]
    assert project["reinstalled_unit_count"] == len(reinstalled), (
        project["reinstalled_unit_count"]
    )
    assert project["scrapped_unit_count"] == len(scrapped), (
        project["scrapped_unit_count"]
    )


def assert_bin_occupancy(bin_data: dict, units) -> None:
    """occupied_slots equals the count of STORED units pointing at the bin."""
    occupants = [
        u
        for u in units
        if u.get("storage_bin_id") == bin_data["id"] and u["handling_status"] == "STORED"
    ]
    assert bin_data["occupied_slots"] == len(occupants), (
        f"occupied_slots={bin_data['occupied_slots']} but {len(occupants)} stored units"
    )
