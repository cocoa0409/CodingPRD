"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Every resource carries id / created_at / updated_at / version (PRD §2.4).
Entity-specific checks pin only what PRD prose states (status vocabularies,
field types, numeric ranges).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_season(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["frost_date"])


def assert_host(data: dict):
    _assert_common(data)
    assert data["status"] in ("APPLICANT", "ACTIVE", "LIMITED", "SUSPENDED")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["reputation_score"], int)
    assert 0 <= data["reputation_score"] <= 100
    assert data["honey_credit_kg"] >= 0
    assert isinstance(data["balance_due_cents"], int)
    assert data["balance_due_cents"] >= 0


def assert_site(data: dict):
    _assert_common(data)
    assert data["status"] in ("CLEAR", "BLOCKED")
    assert isinstance(data["host_id"], str)
    assert isinstance(data["base_capacity_hives"], int)
    assert data["base_capacity_hives"] >= 1
    assert isinstance(data["effective_capacity_hives"], int)
    assert data["effective_capacity_hives"] >= data["base_capacity_hives"]


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_SIGNATURE", "ACTIVE", "AMENDMENT_PENDING", "TERMINATED",
        "EXPIRED",
    )
    assert isinstance(data["host_id"], str)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["host_share_base_bps"], int)
    assert 0 <= data["host_share_base_bps"] <= 6000


def assert_hive(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in (
        "ACTIVE", "QUARANTINED", "DEAD", "REMOVED",
    )
    assert data["posture"] in (
        "THRIVING", "STABLE", "WATCH", "TREATMENT_REQUIRED", "QUARANTINED",
    )
    assert data["provisional_posture"] in (
        "THRIVING", "STABLE", "WATCH", "TREATMENT_REQUIRED", "QUARANTINED",
    )
    assert isinstance(data["site_id"], str)
    assert isinstance(data["agreement_id"], str)


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "VERIFIED")
    assert isinstance(data["hive_id"], str)
    assert isinstance(data["mites_counted"], int) and data["mites_counted"] >= 0
    assert isinstance(data["bees_sampled"], int) and data["bees_sampled"] >= 1
    assert 0 <= data["brood_score"] <= 10
    assert isinstance(data["disease_flag"], bool)
    assert isinstance(data["queen_seen"], bool)
    assert data["stores_kg"] >= 0


def assert_treatment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
    assert data["product"] in ("OXALIC_ACID", "APIVAR", "FORMIC_ACID")
    assert isinstance(data["hive_id"], str)


def assert_harvest(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "APPROVED", "VOIDED", "SETTLED")
    assert isinstance(data["hive_id"], str)
    assert data["gross_kg"] > 0
    assert 0 <= data["moisture_pct"] <= 100
    assert data["net_kg"] >= 0


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROJECTED", "FINALIZED", "DISTRIBUTED")
    assert isinstance(data["season_id"], str)
    assert isinstance(data["hive_id"], str)


def assert_swarm_event(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REPORTED", "DISPATCHED", "CAPTURED", "LOST", "EXPIRED",
    )
    assert isinstance(data["site_id"], str)


def assert_removal_job(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "SCHEDULED", "COMPLETED", "CANCELLED",
        "REJECTED",
    )
    assert data["reason"] in ("RELOCATION", "NUISANCE", "HEALTH", "EXIT")
    assert isinstance(data["hive_id"], str)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED")
    assert data["plan"] in ("BASIC", "PLUS", "PREMIUM")
    assert isinstance(data["host_id"], str)
    assert isinstance(data["monthly_fee_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "OVERDUE", "PAID", "VOID")
    assert isinstance(data["subscription_id"], str)
    for field in (
        "fee_cents", "carried_balance_cents", "late_fee_cents",
        "overwinter_credit_cents", "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["total_cents"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "COMPLETED", "FAILED")
    assert data["course_code"] in ("HOST-101", "ADV-201", "QUEEN-301")
    assert isinstance(data["host_id"], str)


def assert_incident(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REPORTED", "RESOLVED_AT_FAULT", "RESOLVED_NO_FAULT", "DISMISSED",
    )
    assert data["severity"] in ("MINOR", "SEVERE")
    assert isinstance(data["site_id"], str)
    assert isinstance(data["host_id"], str)


def assert_allocation_conservation(data: dict):
    """Honey mass conservation (PRD §3.6): for every finalized allocation,
    host_kg + reserve_kg + operator_kg equals pool_net_kg."""
    total = round(data["host_kg"] + data["reserve_kg"] + data["operator_kg"], 3)
    assert total == round(data["pool_net_kg"], 3), (
        f"conservation violated: {data['host_kg']} + {data['reserve_kg']} + "
        f"{data['operator_kg']} != {data['pool_net_kg']}"
    )
