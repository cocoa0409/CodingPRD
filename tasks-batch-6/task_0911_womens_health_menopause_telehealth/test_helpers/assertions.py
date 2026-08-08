"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_patient(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["billing_mode"] in ("CASH", "INSURANCE")
    assert data["menopause_stage"] in ("PERIMENOPAUSE", "MENOPAUSE", "POSTMENOPAUSE", "UNKNOWN")


def assert_provider(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["specialty"] in ("GYNECOLOGY", "ENDOCRINOLOGY", "FAMILY_MEDICINE")
    assert isinstance(data["visit_fee_cents"], int)


def assert_insurance_policy(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["deductible_cents"], int)
    assert isinstance(data["remaining_deductible_cents"], int)
    assert isinstance(data["consumed_deductible_cents"], int)
    assert isinstance(data["out_of_pocket_max_cents"], int)
    assert isinstance(data["oop_accumulated_cents"], int)
    assert_deductible_conservation(data)


def assert_intake(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["status"] in ("DRAFT", "CLEARED", "FLAGGED")
    assert isinstance(data["symptom_ratings"], list)
    assert isinstance(data["reported_conditions"], list)


def assert_visit(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_prescription(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DISCONTINUED", "EXPIRED")
    assert isinstance(data["refills_remaining"], int)
    assert isinstance(data["total_refills_authorized"], int)


def assert_lab_order(data: dict):
    _common(data)
    assert is_valid_uuid(data["prescription_id"])
    assert data["panel_type"] in ("LIPID", "HORMONE", "LIVER", "MAMMOGRAM")
    assert data["status"] in ("PENDING", "REVIEWED", "CANCELLED")


def assert_refill(data: dict):
    _common(data)
    assert is_valid_uuid(data["prescription_id"])
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "FULFILLED", "REVERSED")


def assert_subscription(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["plan_tier"] in ("ESSENTIAL", "PLUS")
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED", "SUPERSEDED")


def assert_charge(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["billable_kind"] in ("VISIT", "REFILL")
    assert data["billing_mode"] in ("CASH", "INSURANCE")
    assert isinstance(data["allowed_amount_cents"], int)
    assert data["status"] in ("ESTIMATED", "ADJUDICATED", "VOID", "REVERSED")


def assert_care_plan(data: dict):
    _common(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["prescription_id"])
    assert data["adherence_status"] in ("NON_ADHERENT", "AT_RISK", "ADHERENT")


def assert_care_plan_message(data: dict):
    # Append-only log: carries ONLY id + created_at (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CarePlanMessage must not carry updated_at"
    assert "version" not in data, "CarePlanMessage must not carry version"
    assert data["message_type"] in ("GENERAL", "ADHERENCE_OUTREACH", "SUSPENSION_NOTICE", "DENIAL_NOTICE")
    assert data["author_kind"] in ("PATIENT", "PROVIDER", "CARE_COORDINATOR", "SYSTEM")


# --------------------------------------------------------------------------
# Domain invariant checkers (PRD §2.11)
# --------------------------------------------------------------------------
def assert_deductible_conservation(policy: dict):
    """remaining_deductible_cents + consumed_deductible_cents == deductible_cents."""
    assert (policy["remaining_deductible_cents"] + policy["consumed_deductible_cents"]
            == policy["deductible_cents"]), (
        "deductible conservation violated: "
        f"{policy['remaining_deductible_cents']} + {policy['consumed_deductible_cents']} "
        f"!= {policy['deductible_cents']}")


def assert_refill_count_invariant(prescription: dict, fulfilled_count: int):
    """refills_remaining + count(FULFILLED) == total_refills_authorized."""
    assert (prescription["refills_remaining"] + fulfilled_count
            == prescription["total_refills_authorized"]), (
        "refill count invariant violated: "
        f"{prescription['refills_remaining']} + {fulfilled_count} "
        f"!= {prescription['total_refills_authorized']}")
