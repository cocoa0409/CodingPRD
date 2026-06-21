"""Entity assertions and domain invariant checkers.

assert_{entity}(data) validates the shape and field domains of each resource.
Domain invariant helpers verify cross-field rules that must hold after any
operation (apportionment conservation, non-negative arrears).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_community(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["state_code"] in ["CA", "OR", "FL", "TX"]
    assert data["ownership_model"] in ["PARK_OWNED", "RESIDENT_OWNED"]
    assert data["utility_apportionment_method"] in ["PER_CAPITA", "SUB_METER"]
    assert isinstance(data["occupied_lot_count"], int)
    assert data["occupied_lot_count"] >= 0


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["lot_number"], str) and len(data["lot_number"]) > 0
    assert isinstance(data["base_rent_cents"], int)
    assert data["status"] in ["VACANT", "OCCUPIED", "EVICTING", "FROZEN"]
    assert isinstance(data["current_rent_cents"], int)


def assert_resident(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["standing"] in ["GOOD", "DELINQUENT", "EVICTED"]
    assert isinstance(data["arrears_cents"], int) and data["arrears_cents"] >= 0


def assert_lease(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["resident_id"])
    assert data["status"] in ["PENDING", "ACTIVE", "TERMINATED", "TRANSFERRED"]


def assert_rent_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["proposed_rent_cents"], int)
    assert isinstance(data["new_rent_cents"], int)
    assert isinstance(data["cap_applied"], bool)
    assert data["status"] in [
        "PROPOSED", "ACCEPTED", "CONTESTED", "EFFECTIVE", "WITHDRAWN"
    ]


def assert_utility_bill(data: dict):
    _assert_common(data)
    assert data["utility_type"] in ["WATER", "ELECTRIC", "SEWER"]
    assert isinstance(data["master_charge_cents"], int)
    assert data["status"] in ["DRAFT", "APPORTIONED"]


def assert_eviction_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["reason"] in ["NONPAYMENT", "LEASE_VIOLATION"]
    assert data["status"] in ["NOTICE_SERVED", "CURED", "ADJUDICATED", "DISMISSED"]


def assert_conversion_vote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["community_id"])
    assert 0 < data["quorum_threshold_pct"] <= 1
    assert isinstance(data["yes_count"], int)
    assert data["status"] in ["OPEN", "PASSED", "FAILED"]


def assert_utility_charge(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["amount_cents"], int)


def assert_utility_reading(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["lot_id"])


def assert_conversion_ballot(data: dict):
    _assert_append_only_common(data)
    assert data["choice"] in ["YES", "NO"]


def assert_ledger_entry(data: dict):
    _assert_append_only_common(data)
    assert data["entry_type"] in ["RENT_CHARGE", "UTILITY_CHARGE", "PAYMENT"]
    assert isinstance(data["amount_cents"], int)


# ─── Domain invariant checkers ─────────────────────────────────

def assert_apportionment_conserved(bill: dict, charges: list):
    """Apportioned shares sum exactly to the master charge (no cent lost)."""
    total = sum(c["amount_cents"] for c in charges)
    assert total == bill["master_charge_cents"], (
        f"conservation broken: charges sum {total} != master "
        f"{bill['master_charge_cents']}"
    )
    assert bill["apportioned_total_cents"] == bill["master_charge_cents"], (
        f"apportioned_total_cents {bill['apportioned_total_cents']} != master "
        f"{bill['master_charge_cents']}"
    )


def assert_arrears_non_negative(resident: dict):
    assert resident["arrears_cents"] >= 0, "arrears must be floored at zero"
