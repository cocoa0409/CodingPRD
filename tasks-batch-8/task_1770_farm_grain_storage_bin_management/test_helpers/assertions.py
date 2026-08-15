"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_instant_equal(actual, expected):
    """Compare two ISO 8601 timestamps by instant value, not string form.

    The PRD pins the *instant* of fields such as `lockout_until`,
    `cleared_at`, and echoed inputs like `cert_expires_at`, but pins the
    three-fractional-digit serialization only for `created_at`,
    `updated_at`, and the envelope timestamp (sections 2.2/2.5). An
    implementation may therefore serialize the same instant as
    "2026-08-04T00:00:00Z" or "2026-08-04T00:00:00.000Z".
    """
    assert actual is not None, f"expected an ISO 8601 instant, got None"
    assert is_iso8601_timestamp(str(actual)), (
        f"actual must be ISO 8601, got {actual!r}"
    )

    def _parse(s):
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))

    assert _parse(actual) == _parse(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int), (
            f"version must be an int, got {data.get('version')!r}"
        )


def assert_bin(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["capacity_bu"] > 0
    assert data["crop"] in ("CORN", "SOYBEAN", "WHEAT")
    assert data["posture"] in ("SOUND", "WATCH", "ALERT", "FUMIGATION_LOCKOUT")
    assert isinstance(data["current_inventory_bu"], (int, float))
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["insect_activity"], bool)


def assert_lot(data: dict):
    _assert_common(data)
    assert data["crop"] in ("CORN", "SOYBEAN", "WHEAT")
    assert data["grade"] in ("GRADE_1", "GRADE_2", "GRADE_3")
    assert data["status"] in ("STORED", "PARTIALLY_DRAWN", "SUSPENDED", "DEPLETED")
    assert data["original_bu"] > 0
    assert isinstance(data["current_bu"], (int, float))
    assert isinstance(data["provisional_shrink_bu"], (int, float))
    assert isinstance(data["drawn_bu"], (int, float))
    assert isinstance(data["cumulative_invisible_loss_bu"], (int, float))
    assert isinstance(data["cumulative_storage_charge_cents"], int)
    assert isinstance(data["months_assessed"], int)


def assert_reading(data: dict):
    # append-only log: no updated_at / version
    _assert_common(data, with_version=False)
    assert isinstance(data["cable_temps_f"], list) and 1 <= len(data["cable_temps_f"]) <= 12
    assert isinstance(data["hotspot_triggered"], bool)
    assert isinstance(data["score_after"], (int, float))


def assert_alert(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "CONFIRMED_LOSS")


def assert_fumigation(data: dict):
    _assert_common(data)
    assert data["product"] in ("PHOSPHINE", "SULFURYL_FLUORIDE")
    assert data["status"] in ("ACTIVE", "CLEARED")


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "VOIDED", "EXPIRED")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["crop"] in ("CORN", "SOYBEAN", "WHEAT")
    assert data["status"] in ("OPEN", "DELIVERING", "FULFILLED", "DEFAULTED")
    assert isinstance(data["committed_bu"], (int, float))
    assert isinstance(data["delivered_bu"], (int, float))
    assert isinstance(data["settled_value_cents"], int)
    assert isinstance(data["fulfillment_ratio"], (int, float))
    assert isinstance(data["contract_unit_price_cents"], int)


def assert_loadout(data: dict):
    _assert_common(data)
    assert data["transport_status"] in (
        "SCHEDULED", "HELD", "DISPATCHED", "DELIVERED", "EXPIRED"
    )
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "VOIDED")


def assert_applicator(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["license_no"], str)


def assert_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED")
    assert data["valuation_clause"] in ("SPOT", "CONTRACT_AVG")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED")


def assert_assessment(data: dict):
    # append-only log
    _assert_common(data, with_version=False)
    assert isinstance(data["period"], str)
    for k in (
        "lots_assessed",
        "total_storage_charge_cents",
        "contracts_defaulted",
        "contracts_fulfilled",
        "permits_expired",
        "loadouts_expired",
        "policies_expired",
    ):
        assert isinstance(data[k], int), f"{k} must be int, got {data.get(k)!r}"
    assert isinstance(data["total_invisible_loss_bu"], (int, float))


def assert_shrink_event(data: dict):
    # append-only log
    _assert_common(data, with_version=False)
    assert data["kind"] in ("PROVISIONAL", "INVISIBLE_LOSS")
    assert isinstance(data["shrink_bu"], (int, float))
