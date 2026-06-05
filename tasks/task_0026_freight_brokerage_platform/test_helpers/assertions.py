"""Entity assertions and domain invariant checkers.

Each assert_<entity> validates the fields the PRD §2.4 (common resource
properties) and §3.x narratives say must be present on the wire. Append-only
resources (Accessorial, SmartWayAudit) intentionally do NOT assert
`updated_at` or `version` because PRD §2.4 says those two types carry only
`id` and `created_at`.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Common helpers ───────────────────────────────────────────────


def _assert_common_mutable(data: dict) -> None:
    """PRD §2.4: every mutable resource carries id, created_at, updated_at,
    version. Versions are non-negative integers."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int: {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"version must start at >=1: {data['version']}"


def _assert_common_append_only(data: dict) -> None:
    """PRD §2.4: Accessorial and SmartWayAudit carry ONLY id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )


# ─── Entity-specific shape assertions ─────────────────────────────


def assert_shipper(data: dict) -> None:
    _assert_common_mutable(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["open_ar_cents"], int)
    assert data["open_ar_cents"] >= 0
    assert data["status"] in ("ACTIVE", "ON_HOLD")


def assert_carrier(data: dict) -> None:
    _assert_common_mutable(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["mc_number"], str)
    assert isinstance(data["usdot_number"], str)
    assert data["smartway_tier"] in ("NONE", "BRONZE", "SILVER", "GOLD")
    assert is_iso8601_timestamp(data["insurance_expiry_utc"])
    assert data["qualification_status"] in (
        "PENDING", "QUALIFIED", "REJECTED", "SUSPENDED",
    )
    assert isinstance(data["safety_score"], (int, float))
    assert 0.0 <= float(data["safety_score"]) <= 100.0


def assert_contract_rate(data: dict) -> None:
    _assert_common_mutable(data)
    assert is_valid_uuid(data["shipper_id"])
    assert isinstance(data["lane_origin"], str) and len(data["lane_origin"]) == 5
    assert isinstance(data["lane_destination"], str) and len(data["lane_destination"]) == 5
    assert isinstance(data["rate_per_mile_cents"], int) and data["rate_per_mile_cents"] > 0
    assert isinstance(data["fuel_surcharge_per_mile_cents"], int)
    assert data["fuel_surcharge_per_mile_cents"] >= 0
    assert isinstance(data["detention_free_minutes"], int)
    assert data["detention_free_minutes"] >= 0
    assert isinstance(data["detention_rate_per_hour_cents"], int)
    assert data["detention_rate_per_hour_cents"] >= 0
    assert is_iso8601_timestamp(data["effective_from_utc"])
    assert is_iso8601_timestamp(data["effective_until_utc"])
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")


def assert_quote_request(data: dict) -> None:
    _assert_common_mutable(data)
    assert is_valid_uuid(data["shipper_id"])
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] > 0
    assert data["requested_equipment"] in ("DRY_VAN", "REEFER", "FLATBED")
    assert data["rate_mode"] in ("SPOT", "CONTRACT")
    assert isinstance(data["quoted_total_cents"], int)
    assert data["quoted_total_cents"] >= 0
    assert data["status"] in ("OPEN", "AWARDED", "EXPIRED", "WITHDRAWN")
    assert is_iso8601_timestamp(data["pickup_window_start_utc"])
    assert is_iso8601_timestamp(data["pickup_window_end_utc"])
    assert is_iso8601_timestamp(data["expires_at_utc"])


def assert_load(data: dict) -> None:
    _assert_common_mutable(data)
    assert is_valid_uuid(data["quote_request_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["agreed_rate_cents"], int)
    assert data["agreed_rate_cents"] >= 0
    assert isinstance(data["detention_charge_cents"], int)
    assert data["detention_charge_cents"] >= 0
    assert isinstance(data["accessorial_total_cents"], int)
    assert data["accessorial_total_cents"] >= 0
    assert data["status"] in (
        "AWARDED", "IN_TRANSIT", "DELIVERED", "INVOICED", "CLOSED", "CANCELLED",
    )


def assert_accessorial(data: dict) -> None:
    _assert_common_append_only(data)
    assert is_valid_uuid(data["load_id"])
    assert data["code"] in (
        "LUMPER", "TARPS", "EXTRA_STOP", "REWEIGH", "LAYOVER", "DETENTION",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_invoice(data: dict) -> None:
    _assert_common_mutable(data)
    assert is_valid_uuid(data["load_id"])
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0
    assert isinstance(data["factored"], bool)
    assert isinstance(data["amount_paid_cents"], int)
    assert data["amount_paid_cents"] >= 0
    assert data["status"] in (
        "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "WRITTEN_OFF",
    )


def assert_factoring_request(data: dict) -> None:
    _assert_common_mutable(data)
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["factoring_fee_pct"], (int, float))
    assert 0.0 < float(data["factoring_fee_pct"]) <= 10.0
    assert isinstance(data["advance_cents"], int)
    assert data["advance_cents"] >= 0
    assert data["status"] in (
        "REQUESTED", "APPROVED", "ADVANCED", "REJECTED", "RECOURSE",
    )


def assert_dispute_claim(data: dict) -> None:
    _assert_common_mutable(data)
    assert is_valid_uuid(data["invoice_id"])
    assert data["claim_type"] in (
        "OVERCHARGE", "DAMAGED_GOODS", "LATE_DELIVERY", "MISSING_POD",
    )
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0
    assert data["status"] in ("OPEN", "RESOLVED", "WITHDRAWN")


def assert_smartway_audit(data: dict) -> None:
    _assert_common_append_only(data)
    assert is_valid_uuid(data["shipper_id"])
    assert isinstance(data["quarter_label"], str) and data["quarter_label"]
    assert isinstance(data["total_loads"], int) and data["total_loads"] >= 0
    assert isinstance(data["smartway_loads"], int) and data["smartway_loads"] >= 0
    assert data["smartway_loads"] <= data["total_loads"]
    assert isinstance(data["smartway_ratio"], (int, float))
    assert 0.0 <= float(data["smartway_ratio"]) <= 1.0
    assert data["compliance_status"] in ("PASSING", "AT_RISK", "FAILING")


# ─── Domain invariants ────────────────────────────────────────────


def assert_invoice_total_matches_components(invoice: dict, load: dict,
                                            partial_credits_total_cents: int = 0) -> None:
    """PRD §3.6: Invoice.total_cents = Load.agreed + Load.detention +
    Load.accessorial_total - sum(PARTIAL resolution_amount_cents). The PRD
    states the same components in §2.9 as the load-accessorial-conservation
    invariant.
    """
    expected = (
        load["agreed_rate_cents"]
        + load["detention_charge_cents"]
        + load["accessorial_total_cents"]
        - partial_credits_total_cents
    )
    assert invoice["total_cents"] == expected, (
        f"Invoice.total_cents={invoice['total_cents']} but expected {expected} "
        f"(agreed={load['agreed_rate_cents']}, detention={load['detention_charge_cents']}, "
        f"accessorial={load['accessorial_total_cents']}, "
        f"partial_credits={partial_credits_total_cents})"
    )
