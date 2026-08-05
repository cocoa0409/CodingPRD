"""Entity assertions and domain invariant checkers for the Lymphedema API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert data["status"] == "ACTIVE"


def assert_evaluation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DRAFT", "FINALIZED", "SUPERSEDED"}
    assert data["body_region"] in {
        "LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG", "HEAD_NECK", "TRUNK", "GENITAL",
    }
    assert data["etiology"] in {"PRIMARY", "SECONDARY"}
    assert data["isl_stage"] in {"STAGE_0", "STAGE_I", "STAGE_II", "STAGE_III"}
    assert isinstance(data["circumferences_cm"], list)
    assert isinstance(data["contralateral_circumferences_cm"], list)


def assert_authorization(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DRAFT", "SUBMITTED", "APPROVED", "DENIED", "EXHAUSTED"}
    for f in ("visit_cap", "visits_reserved", "visits_used", "visits_remaining"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert_authorization_ledger_invariant(data)


def assert_authorization_ledger_invariant(data: dict):
    """visits_remaining == visit_cap - visits_reserved - visits_used (PRD §2.8)."""
    expected = data["visit_cap"] - data["visits_reserved"] - data["visits_used"]
    assert data["visits_remaining"] == expected, (
        f"visits_remaining {data['visits_remaining']} != "
        f"visit_cap - reserved - used = {expected}"
    )


def assert_treatment_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DRAFT", "ACTIVE", "ON_HOLD", "COMPLETED"}
    assert data["phase"] in {"PHASE_1_INTENSIVE", "PHASE_2_MAINTENANCE"}


def assert_therapist(data: dict):
    _assert_common_fields(data)
    assert data["credential"] in {"CLT", "OT", "PT"}
    assert data["status"] == "ACTIVE"


def assert_session(data: dict):
    _assert_common_fields(data)
    assert data["clinical_status"] in {
        "SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW",
    }
    assert data["billing_status"] in {"RESERVED", "BILLED", "VOID"}
    assert data["cdt_component"] in {
        "MLD", "COMPRESSION_BANDAGING", "EXERCISE", "SKIN_CARE", "EDUCATION",
    }


def assert_garment_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DRAFT", "APPROVED", "DENIED", "SUPERSEDED"}
    assert data["compression_class"] in {"CLASS_1", "CLASS_2", "CLASS_3", "CLASS_4"}
    assert data["garment_type"] in {
        "SLEEVE", "STOCKING", "CHIN_STRAP", "VEST", "COMPRESSION_SHORT",
    }
    assert isinstance(data["custom_fabrication"], bool)
    assert isinstance(data["l_code"], str) and data["l_code"].startswith("L")


def assert_dme_item(data: dict):
    _assert_common_fields(data)
    assert_dme_stock_invariant(data)


def assert_dme_stock_invariant(data: dict):
    """on_hand_qty + outstanding_dispensed_qty == initial_stock_qty (PRD §3.1)."""
    assert data["on_hand_qty"] + data["outstanding_dispensed_qty"] == data["initial_stock_qty"], (
        f"on_hand {data['on_hand_qty']} + outstanding {data['outstanding_dispensed_qty']} "
        f"!= initial {data['initial_stock_qty']}"
    )


def assert_dispense(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DISPENSED", "RETURNED"}


def assert_reassessment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DRAFT", "FINALIZED"}


def assert_adherence_log_shape(data: dict):
    """AdherenceLog is append-only: id + created_at, no version / updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "AdherenceLog must not carry version"
    assert "updated_at" not in data, "AdherenceLog must not carry updated_at"
