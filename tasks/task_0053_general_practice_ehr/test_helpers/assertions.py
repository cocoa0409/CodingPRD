"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape and field domains against the
PRD contract. Common-field entities carry id/created_at/updated_at/version; the
CptCode is shared reference configuration and carries only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for first-class records."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["specialty"] in ("FAMILY_MEDICINE", "INTERNAL_MEDICINE", "PEDIATRICS")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["panel_capacity"], int) and data["panel_capacity"] >= 0
    assert isinstance(data["panel_size"], int) and data["panel_size"] >= 0
    assert isinstance(data["controlled_rx_count"], int) and data["controlled_rx_count"] >= 0
    assert isinstance(data["epcs_enrolled"], bool)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["first_name"], str) and len(data["first_name"]) > 0
    assert isinstance(data["last_name"], str) and len(data["last_name"]) > 0
    assert data["sex"] in ("M", "F")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["lifetime_charges_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["active_medication_count"], int)
    assert isinstance(data["open_care_gaps"], int)


def assert_cpt_code(data: dict):
    """CptCode: id + created_at only. NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) == 5
    assert isinstance(data["short_description"], str) and len(data["short_description"]) > 0
    assert data["category"] in ("EM", "PREVENTIVE", "VACCINE_ADMIN", "PROCEDURE")
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0


def assert_visit(data: dict):
    _assert_common(data)
    assert data["visit_type"] in ("CONSULTATION", "PHYSICAL", "VACCINATION")
    assert data["status"] in (
        "SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "CODED",
        "FINALIZED", "CANCELLED", "NO_SHOW",
    )
    assert isinstance(data["billed_total_cents"], int)


def assert_charge_line(data: dict):
    _assert_common(data)
    assert isinstance(data["cpt_code"], str) and len(data["cpt_code"]) == 5
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_prescription(data: dict):
    _assert_common(data)
    assert data["schedule"] in ("NON_CONTROLLED", "C_II", "C_III", "C_IV", "C_V")
    assert data["status"] in (
        "DRAFT", "PENDING_SIGNATURE", "SIGNED", "TRANSMITTED", "DISPENSED", "VOIDED",
    )
    assert isinstance(data["drug_name"], str) and len(data["drug_name"]) > 0


def assert_referral(data: dict):
    _assert_common(data)
    assert data["target_specialty"] in (
        "CARDIOLOGY", "DERMATOLOGY", "ORTHOPEDICS", "ENDOCRINOLOGY",
    )
    assert data["priority"] in ("ROUTINE", "URGENT")
    assert data["status"] in (
        "REQUESTED", "AUTHORIZED", "SCHEDULED", "COMPLETED",
        "DENIED", "EXPIRED", "CANCELLED",
    )


def assert_portal_account(data: dict):
    _assert_common(data)
    assert data["status"] in ("INVITED", "ACTIVE", "SUSPENDED", "DEACTIVATED")
    assert isinstance(data["failed_login_count"], int) and data["failed_login_count"] >= 0


def assert_hedis_measure(data: dict):
    _assert_common(data)
    assert data["measure_type"] in (
        "CIS_FLU", "BCS_MAMMOGRAM", "CBP_BP_CONTROL", "MED_ADHERENCE",
    )
    assert isinstance(data["measurement_year"], int)
    assert data["method"] in ("ADMINISTRATIVE", "HYBRID")
    assert data["status"] in ("GAP", "NUMERATOR_COMPLIANT", "EXCLUDED")
    assert isinstance(data["eligible"], bool)
