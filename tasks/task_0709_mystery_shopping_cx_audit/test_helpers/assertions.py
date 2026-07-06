"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() verify the shape and field types of a returned
resource; the invariant checkers verify cross-field rules the PRD guarantees.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_FAMILIES = {"RETAIL", "DINING", "BANKING"}


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for standard resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["fee_per_completed_shop_cents"], int)
    assert data["fee_per_completed_shop_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_shopper(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["home_lat"], (int, float))
    assert isinstance(data["home_lng"], (int, float))
    assert isinstance(data["tax_id_on_file"], bool)
    assert data["status"] in ("REGISTERED", "CERTIFIED", "SUSPENDED")
    assert isinstance(data["certification_score"], int)
    assert 0 <= data["certification_score"] <= 100
    assert isinstance(data["reliability_score"], (int, float))
    assert 0 <= data["reliability_score"] <= 100, "reliability_score must be in [0, 100]"
    assert isinstance(data["ytd_paid_cents"], int) and data["ytd_paid_cents"] >= 0
    assert isinstance(data["open_assignment_count"], int) and data["open_assignment_count"] >= 0


def assert_certification_attempt(data: dict):
    """Immutable append-only record: id + created_at only; no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("shopper_id", "")), "shopper_id must be a valid UUID"
    assert isinstance(data["raw_score"], int) and 0 <= data["raw_score"] <= 100
    assert data["scenario_family"] in _FAMILIES
    assert data["outcome"] in ("PASSED", "FAILED")
    assert isinstance(data["attempt_index"], int) and data["attempt_index"] >= 1


def assert_location(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["label"], str)
    assert isinstance(data["lat"], (int, float))
    assert isinstance(data["lng"], (int, float))
    assert data["scenario_family"] in _FAMILIES
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_scenario_script(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["title"], str)
    assert data["scenario_family"] in _FAMILIES
    assert isinstance(data["required_photo_count"], int) and data["required_photo_count"] >= 0
    assert isinstance(data["receipt_required"], bool)
    assert isinstance(data["reimburse_cap_cents"], int) and data["reimburse_cap_cents"] >= 0
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["weights_json"], dict)
    assert isinstance(data["passing_score"], int) and 0 <= data["passing_score"] <= 100
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")


def assert_shop_wave(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["field_window_start"])
    assert is_iso8601_timestamp(data["field_window_end"])
    assert isinstance(data["rotation_cooldown_days"], int) and data["rotation_cooldown_days"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")
    assert isinstance(data["validated_shop_count"], int) and data["validated_shop_count"] >= 0
    assert isinstance(data["client_billable_cents"], int) and data["client_billable_cents"] >= 0


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("wave_id", "")), "wave_id must be a valid UUID"
    assert is_valid_uuid(data.get("shopper_id", "")), "shopper_id must be a valid UUID"
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert is_valid_uuid(data.get("script_id", "")), "script_id must be a valid UUID"
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["travel_distance_km"], (int, float))
    assert isinstance(data["claimed_out_of_pocket_cents"], int)
    assert isinstance(data["reimbursable_cents"], int)
    assert isinstance(data["shopper_fee_cents"], int)
    assert data["status"] in (
        "ASSIGNED", "IN_FIELD", "SUBMITTED", "VALIDATED",
        "REVISION_REQUESTED", "REJECTED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0


def assert_evidence_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert data["kind"] in ("PHOTO", "RECEIPT")
    assert isinstance(data["object_uri"], str)
    assert isinstance(data["receipt_amount_cents"], int) and data["receipt_amount_cents"] >= 0
    assert data["review_status"] in ("PENDING", "APPROVED", "FLAGGED")


def assert_score_card(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert isinstance(data["section_scores_json"], dict)
    assert isinstance(data["estimated_score"], int) and 0 <= data["estimated_score"] <= 100
    assert data["audit_status"] in ("DRAFT", "AUDITED")
    assert data["fraud_status"] in ("UNCHECKED", "CLEARED", "FRAUD_HOLD")


def assert_reimbursement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert is_valid_uuid(data.get("shopper_id", "")), "shopper_id must be a valid UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("ACCRUED", "BATCHED", "PAID", "REVERSED")


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert data["opened_by_role"] in ("SHOPPER", "CLIENT")
    assert data["reason"] in ("REJECTION_APPEAL", "SCORE_CHALLENGE", "REIMBURSE_SHORTFALL")
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in (
        "UNDER_REVIEW", "COUNTERED", "UPHELD", "OVERTURNED", "WITHDRAWN",
    )


def assert_payout_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shopper_id", "")), "shopper_id must be a valid UUID"
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 0
    assert isinstance(data["requires_1099"], bool)
    assert data["status"] in ("OPEN", "PAID", "VOIDED")


# --- Domain invariant checkers --------------------------------------------
def assert_wave_billable_invariant(wave: dict, fee_per_completed_shop_cents: int):
    """PRD 3.6: client_billable_cents == validated_shop_count * fee (exact integer
    multiply, no rounding, recomputed from scratch on every change)."""
    expected = wave["validated_shop_count"] * fee_per_completed_shop_cents
    assert wave["client_billable_cents"] == expected, (
        f"client_billable_cents drift: expected {expected} "
        f"(= {wave['validated_shop_count']} * {fee_per_completed_shop_cents}), "
        f"got {wave['client_billable_cents']}"
    )
