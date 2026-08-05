"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_property(data: dict):
    _common(data)
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert data["zoning_type"] in ["RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "MIXED"]
    assert isinstance(data["substantiated_violation_count"], int)
    assert data["chronic_status"] in ["NONE", "WATCH", "DESIGNATED"]
    assert data["abatement_status"] in ["NONE", "UNDER_ABATEMENT", "ABATED"]


def assert_noise_policy(data: dict):
    _common(data)
    assert data["zoning_type"] in ["RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "MIXED"]
    for f in ("day_limit_db", "night_limit_db", "day_start_hour", "night_start_hour"):
        assert f in data


def assert_variance_permit(data: dict):
    _common(data)
    assert data["permit_type"] in ["CONSTRUCTION", "EVENT"]
    assert data["status"] in ["UNDER_REVIEW", "ISSUED", "DENIED", "REVOKED"]
    assert isinstance(data["fee_estimate_cents"], int)


def assert_complaint(data: dict):
    _common(data)
    assert data["noise_type"] in [
        "CONSTRUCTION", "AMPLIFIED_MUSIC", "MACHINERY", "ANIMAL", "VEHICLE", "OTHER"
    ]
    assert data["status"] in ["RECEIVED", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED"]
    assert data["source"] in ["PHONE", "ONLINE", "OFFICER"]


def assert_enforcement(data: dict):
    _common(data)
    assert data["tier"] in ["WARNING", "CITATION"]
    assert isinstance(data["escalation_level"], int)
    assert isinstance(data["assessed_fine_cents"], int)
    assert isinstance(data["effective_fine_cents"], int)
    assert isinstance(data["late_penalty_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_outstanding_cents"], int)
    assert data["status"] in [
        "ISSUED", "CONTESTED", "HEARING_SCHEDULED", "UPHELD", "REDUCED", "DISMISSED", "PAID"
    ]


def assert_hearing(data: dict):
    _common(data)
    assert data["outcome"] in ["PENDING", "UPHELD", "REDUCED", "DISMISSED", "REMANDED"]
    assert "enforcement_id" in data
    assert "hearing_officer_id" in data


def assert_abatement_order(data: dict):
    _common(data)
    assert data["trigger_source"] in ["CHRONIC_DESIGNATION", "DELINQUENT_CITATION"]
    assert data["status"] in ["PENDING", "COMPLIED", "ESCALATED", "VACATED"]


def assert_referral(data: dict):
    _common(data)
    assert data["agency"] in ["POLICE", "BUILDING", "HEALTH", "ANIMAL_CONTROL"]
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "CLOSED"]


def assert_inspection(data: dict):
    """Inspection is an append-only record: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Inspection is append-only: must not carry a version"
    assert "updated_at" not in data, "Inspection is append-only: must not carry updated_at"
    assert isinstance(data["exceeds_limit"], bool)


def assert_payment(data: dict):
    """Payment is an append-only ledger row: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment is append-only: must not carry a version"
    assert "updated_at" not in data, "Payment is append-only: must not carry updated_at"
    assert data["kind"] in ["PAYMENT", "REFUND"]
    assert data["status"] == "CLEARED"


def assert_money_conservation(enf: dict):
    """PRD §3.7 money invariant:
    amount_paid_cents + amount_outstanding_cents == effective_fine_cents + late_penalty_cents.
    """
    lhs = enf["amount_paid_cents"] + enf["amount_outstanding_cents"]
    rhs = enf["effective_fine_cents"] + enf["late_penalty_cents"]
    assert lhs == rhs, f"money conservation broken: {lhs} != {rhs}"
