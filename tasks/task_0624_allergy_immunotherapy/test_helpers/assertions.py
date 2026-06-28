"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every primary entity (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["epinephrine_on_file"], bool)
    assert isinstance(data["prior_systemic_reaction"], bool)


def assert_panel(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["status"] in ("OPEN", "FINALIZED")
    assert data["recommended_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_allergen_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["panel_id"])
    assert data["method"] in ("SKIN", "BLOOD")
    assert isinstance(data["sensitization_index"], (int, float))
    assert isinstance(data["is_positive"], bool)


def assert_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["panel_id"])
    assert data["starting_vial_color"] in ("GREEN", "YELLOW", "RED", "SILVER")
    assert data["current_vial_color"] in ("GREEN", "YELLOW", "RED", "SILVER")
    assert data["phase"] in ("BUILD_UP", "MAINTENANCE")
    assert data["status"] in (
        "DRAFT",
        "ACTIVE",
        "HELD",
        "COMPLETED",
        "DISCONTINUED",
    )
    assert isinstance(data["current_step_index"], int)


def assert_lot(data: dict):
    _assert_common(data)
    assert data["vial_color"] in ("GREEN", "YELLOW", "RED", "SILVER")
    assert isinstance(data["lot_number"], str) and len(data["lot_number"]) > 0
    assert data["status"] in ("AVAILABLE", "RECALLED")


def assert_vial(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["lot_id"])
    assert data["vial_color"] in ("GREEN", "YELLOW", "RED", "SILVER")
    assert data["status"] in ("IN_USE", "EXHAUSTED", "EXPIRED", "DISCARDED")
    assert isinstance(data["remaining_volume_ml"], (int, float))
    assert isinstance(data["needs_refill"], bool)


def assert_shot_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["vial_id"])
    assert data["status"] in (
        "ADMINISTERED",
        "RELEASED",
        "REACTION_LOCAL",
        "REACTION_SYSTEMIC",
    )
    assert isinstance(data["antigen_units_delivered"], (int, float))


def assert_billing_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["cpt_code"] in ("CPT_95115", "CPT_95117", "CPT_95165")
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("POSTED", "REVERSED", "RECONCILED")
    assert isinstance(data["billed_dose_units"], int)
    assert isinstance(data["charge_cents"], int)
