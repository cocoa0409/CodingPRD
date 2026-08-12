"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_host_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DECOMMISSIONED")
    assert isinstance(data["cage_capacity_cylinders"], int) and data["cage_capacity_cylinders"] > 0
    assert isinstance(data["par_level_full"], int)
    assert 1 <= data["par_level_full"] <= data["cage_capacity_cylinders"]
    assert isinstance(data["reorder_floor_full"], int)
    assert isinstance(data["opening_float_cents"], int)
    assert isinstance(data["commission_rate_bps"], int)
    assert data["commission_basis"] in ("GROSS", "NET")
    assert data["recon_basis"] in ("BOOK", "PHYSICAL")
    for f in ("full_on_hand", "empty_on_hand", "quarantined_on_hand"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    assert data["sales_posture"] in ("SALES_OPEN", "SALES_BLOCKED")
    assert isinstance(data["restock_alert"], bool)


def assert_pricing_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["swap_price_cents"], int) and data["swap_price_cents"] >= 0
    assert isinstance(data["core_deposit_cents"], int) and data["core_deposit_cents"] >= 0
    assert isinstance(data["tax_rate_bps"], int) and 0 <= data["tax_rate_bps"] <= 2000
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["is_current"], bool)


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["dot_medical_expires_on"], str)
    assert isinstance(data["vehicle_max_payload_lbs"], int) and data["vehicle_max_payload_lbs"] > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["cert_level"] in ("VISUAL_ONLY", "FULL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_cylinder(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["owner_kind"] in ("FLEET", "CUSTOMER")
    assert data["cert_status"] in ("CERTIFIED", "RECERT_DUE", "CONDEMNED")
    assert data["cert_method_last"] in ("INITIAL", "VISUAL", "HYDROSTATIC")
    assert data["fill_status"] in ("FULL", "EMPTY", "QUARANTINED")
    assert isinstance(data["manufacture_date"], str)
    assert isinstance(data["certified_on"], str)
    assert isinstance(data["certification_expires_on"], str)


def assert_exchange_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["status"] in ("DRAFT", "COMPLETED", "VOIDED", "REFUNDED")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["core_deposit_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["unit_price_cents"] + data["core_deposit_cents"] + data["tax_cents"], (
        "total must equal unit price + deposit + tax (PRD §3.3)"
    )


def assert_refill_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("cylinder_id", ""))
    assert data["status"] in ("OPEN", "WEIGHED", "FILLED", "CLOSED", "VOIDED")
    assert isinstance(data["max_fill_lbs"], (int, float))


def assert_certification_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cylinder_id", ""))
    assert data["method"] in ("VISUAL", "HYDROSTATIC")
    assert data["outcome"] in ("PASS", "CONDEMN")
    assert data["status"] in ("RECORDED", "PENDING_SECOND", "CONFIRMED", "REJECTED")


def assert_leak_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("REPORTED", "CONFIRMED", "RESOLVED", "FALSE_ALARM")


def assert_restock_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("driver_id", ""))
    assert isinstance(data["planned_date"], str)
    assert data["status"] in ("DRAFT", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "CANCELLED")
    assert isinstance(data["planned_full_count"], int)
    assert isinstance(data["planned_empty_pickup_count"], int)


def assert_commission_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["basis_used"] in ("GROSS", "NET")
    assert data["status"] in ("DRAFT", "FINALIZED", "DISPUTED", "PAID")


def assert_reconciliation_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["business_date"], str)
    assert data["basis"] in ("BOOK", "PHYSICAL")
    assert data["status"] in ("OPEN", "BALANCED", "VARIANCE_FLAGGED", "ESCALATED", "RESOLVED")
    assert isinstance(data["opening_baseline_cents"], int)
    assert isinstance(data["expected_cash_cents"], int)


def assert_site_cage_invariants(site: dict):
    """Cage counts are non-negative and never exceed the physical cage (PRD §2.8)."""
    total = site["full_on_hand"] + site["empty_on_hand"] + site["quarantined_on_hand"]
    assert total <= site["cage_capacity_cylinders"], (
        f"on-hand total {total} exceeds cage capacity {site['cage_capacity_cylinders']}"
    )
    assert site["restock_alert"] == (site["full_on_hand"] <= site["reorder_floor_full"]), (
        "restock_alert must equal (full_on_hand <= reorder_floor_full), inclusive (PRD §2.8)"
    )
