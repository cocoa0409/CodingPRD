"""Entity assertions for the Film/TV Production API.

PRD §2.4 distinguishes entities with all four common system fields (id,
created_at, updated_at, version) from append-only entities (Audition,
EquipmentEvent, AuditLog, Clock) that carry only id + created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# --- Common helpers ---

def _assert_common_fields(data: dict, label: str) -> None:
    """Validate id/created_at/updated_at/version on common-fields entities."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict, label: str) -> None:
    """Validate id/created_at on append-only entities (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"


# --- Production (PRD §3.1, §2.6) ---

def assert_production(data: dict) -> None:
    _assert_common_fields(data, "Production")
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert data["production_type"] in ("FILM", "TV_SERIES", "DOCUMENTARY", "COMMERCIAL")
    assert is_iso8601_timestamp(data["shoot_window_start"])
    assert is_iso8601_timestamp(data["shoot_window_end"])
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] >= 0
    assert isinstance(data["reserve_fund_cents"], int) and 0 <= data["reserve_fund_cents"] <= data["total_budget_cents"]
    assert data["status"] in ("PLANNING", "IN_PRODUCTION", "WRAP_PENDING", "WRAPPED", "CANCELLED")
    assert data["posture"] in ("GREEN", "YELLOW", "RED", "FROZEN")
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert isinstance(data["residual_cents"], int)


# --- Scene (PRD §3.4) ---

def assert_scene(data: dict) -> None:
    _assert_common_fields(data, "Scene")
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["scene_number"], str) and len(data["scene_number"]) > 0
    assert data["int_ext"] in ("INT", "EXT", "INT_EXT")
    assert isinstance(data["planned_duration_minutes"], int)
    assert 1 <= data["planned_duration_minutes"] <= 720
    assert isinstance(data["required_actor_role_ids"], list)
    assert isinstance(data["required_equipment_categories"], list)
    assert isinstance(data["weather_dependent"], bool)
    assert data["status"] in ("BREAKDOWN", "SCHEDULED", "RESCHEDULING", "SHOT", "OMITTED")


# --- Role (PRD §3.2) ---

def assert_role(data: dict) -> None:
    _assert_common_fields(data, "Role")
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["role_name"], str) and len(data["role_name"]) > 0
    assert data["union_tier"] in ("PRINCIPAL", "SUPPORTING", "FEATURED_BACKGROUND")
    assert isinstance(data["day_rate_cents"], int) and data["day_rate_cents"] >= 0
    assert data["casting_status"] in (
        "OPEN", "AUDITIONING", "SHORTLISTED", "OFFERED", "SIGNED", "RECAST"
    )


# --- Actor (PRD §3.2) ---

def assert_actor(data: dict) -> None:
    _assert_common_fields(data, "Actor")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["agency_contact_email"], str)
    assert isinstance(data["travel_origin_zone"], str)
    assert isinstance(data["active"], bool)


# --- Audition (append-only, PRD §3.2) ---

def assert_audition(data: dict) -> None:
    _assert_append_only_fields(data, "Audition")
    assert is_valid_uuid(data["role_id"])
    assert is_valid_uuid(data["actor_id"])
    assert is_iso8601_timestamp(data["audition_at"])
    assert data["outcome"] in ("PASS", "REJECT", "CALLBACK")
    assert "updated_at" not in data, "Audition is append-only and must not carry updated_at"
    assert "version" not in data, "Audition is append-only and must not carry version"


# --- Location (PRD §3.3) ---

def assert_location(data: dict) -> None:
    _assert_common_fields(data, "Location")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["zone"], str)
    assert isinstance(data["requires_permit"], bool)
    assert isinstance(data["max_parallel_units"], int) and data["max_parallel_units"] >= 1


def assert_location_reservation(data: dict) -> None:
    _assert_common_fields(data, "LocationReservation")
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["scene_id"])
    assert isinstance(data["unit_label"], str) and len(data["unit_label"]) > 0
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["permit_status"] in ("NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED", "EXPIRED")
    assert data["weather_status"] in ("UNKNOWN", "ACCEPTABLE", "BLOCKED")
    assert data["status"] in ("HELD", "CONFIRMED", "RESCHEDULING", "RELEASED", "FULFILLED")


# --- BudgetCategory (PRD §2.7) ---

def assert_budget_category(data: dict) -> None:
    _assert_common_fields(data, "BudgetCategory")
    assert is_valid_uuid(data["production_id"])
    assert data["code"] in ("CAST", "CREW", "EQUIPMENT", "LOCATION", "POST", "MISC")
    assert isinstance(data["planned_cents"], int) and data["planned_cents"] >= 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["actual_cents"], int)
    assert data["alert_state"] in ("OK", "WARN", "OVER")


# --- ChangeOrder (PRD §3.7) ---

def assert_change_order(data: dict) -> None:
    _assert_common_fields(data, "ChangeOrder")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["category_id"])
    assert isinstance(data["delta_cents"], int)
    assert isinstance(data["requested_by"], str) and len(data["requested_by"]) > 0
    assert data["source"] in ("REALLOCATION", "RESERVE_DRAW")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "CANCELLED")


# --- Equipment / EquipmentEvent (PRD §3.5) ---

def assert_equipment(data: dict) -> None:
    _assert_common_fields(data, "Equipment")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("CAMERA", "LIGHTING", "SOUND", "GRIP", "WARDROBE", "PROPS", "MISC")
    assert data["acquisition_mode"] in ("RENTAL", "PURCHASE")
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["status"] in (
        "AVAILABLE", "CHECKED_OUT", "DAMAGED", "LOST", "RETURNED", "DECOMMISSIONED"
    )


def assert_equipment_event(data: dict) -> None:
    _assert_append_only_fields(data, "EquipmentEvent")
    assert is_valid_uuid(data["equipment_id"])
    assert is_valid_uuid(data["production_id"])
    assert data["event_type"] in (
        "CHECK_OUT", "CHECK_IN", "REPORT_DAMAGE", "REPORT_LOSS", "RETURN_VERIFIED"
    )
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["damage_charge_cents"], int) and data["damage_charge_cents"] >= 0
    assert "updated_at" not in data, "EquipmentEvent is append-only and must not carry updated_at"
    assert "version" not in data, "EquipmentEvent is append-only and must not carry version"


# --- Crew / Vendor (PRD §3.8, §3.6) ---

def assert_crew_assignment(data: dict) -> None:
    _assert_common_fields(data, "CrewAssignment")
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["crew_user_id"], str)
    assert isinstance(data["role_label"], str)
    assert isinstance(data["day_rate_cents"], int) and data["day_rate_cents"] >= 0
    assert isinstance(data["scheduled_days"], int) and data["scheduled_days"] >= 0
    assert isinstance(data["actual_days"], int) and data["actual_days"] >= 0
    assert isinstance(data["payroll_cents"], int) and data["payroll_cents"] >= 0
    assert data["status"] in ("BOOKED", "ACTIVE", "RELEASED", "SETTLED")


def assert_vendor_invoice(data: dict) -> None:
    _assert_common_fields(data, "VendorInvoice")
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["vendor_id"], str)
    assert data["category_code"] in ("CAST", "CREW", "EQUIPMENT", "LOCATION", "POST", "MISC")
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert isinstance(data["deduction_cents"], int) and data["deduction_cents"] >= 0
    assert isinstance(data["net_cents"], int)
    assert data["status"] in ("SUBMITTED", "RECONCILED", "PAID", "DISPUTED")


# --- AuditLog (append-only, PRD §2.9) ---

def assert_audit_log(data: dict) -> None:
    _assert_append_only_fields(data, "AuditLog")
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["actor_user_id"], str)
    assert data["action"] in (
        "SCHEDULE_CHANGE", "BUDGET_ADJUSTMENT", "RESERVE_DRAW",
        "CONTRACT_SIGNED", "EQUIPMENT_LOSS", "WRAP_CLOSE",
    )
    assert isinstance(data["subject_entity"], str)
    assert isinstance(data["subject_id"], str)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert "updated_at" not in data, "AuditLog is append-only and must not carry updated_at"
    assert "version" not in data, "AuditLog is append-only and must not carry version"
