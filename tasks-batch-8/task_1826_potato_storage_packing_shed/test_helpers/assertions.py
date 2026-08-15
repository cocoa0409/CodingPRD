"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CWT_ABS_TOL = 0.005


def assert_cwt_equal(actual, expected, label="cwt value"):
    """Compare a 2dp cwt quantity with cent-level tolerance."""
    assert actual is not None, f"{label} must be present"
    assert abs(float(actual) - float(expected)) <= CWT_ABS_TOL, (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_cents_equal(actual, expected, label="cents value"):
    assert actual is not None, f"{label} must be present"
    assert abs(float(actual) - float(expected)) <= CWT_ABS_TOL, (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_grower(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["grower_code"], str) and len(data["grower_code"]) > 0
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_shed(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["posture"] in ("NORMAL", "RESTRICTED", "QUARANTINED")
    assert isinstance(data["consecutive_wash_failures"], int)
    assert isinstance(data["wash_quarantine_flag"], bool)
    assert isinstance(data["audit_failed_flag"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_bin(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["bin_code"], str) and len(data["bin_code"]) > 0
    assert float(data["capacity_cwt"]) > 0
    assert data.get("variety_lock") in (
        None, "RUSSET_BURBANK", "RUSSET_NORKOTAH", "RANGER_RUSSET", "YUKON_GOLD", "RED_LASODA"
    )
    assert float(data.get("occupied_cwt", 0)) >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_field_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["variety"] in (
        "RUSSET_BURBANK", "RUSSET_NORKOTAH", "RANGER_RUSSET", "YUKON_GOLD", "RED_LASODA"
    )
    assert float(data["original_weight_cwt"]) > 0
    for field in (
        "shrink_cwt", "packed_total_cwt", "cull_total_cwt", "condemned_cwt",
        "processing_credit_cwt", "available_cwt", "reserved_cwt",
    ):
        assert float(data.get(field, -1)) >= 0, f"{field} must be >= 0"
    assert data["storage_status"] in ("INTAKE", "BINNED", "CLOSED")
    assert data["quality_status"] in ("CLEAR", "ON_HOLD", "CONDEMNED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_assessment(data: dict):
    """Append-only record: id + created_at only; NO version, NO updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "assessments must not carry version"
    assert "updated_at" not in data, "assessments must not carry updated_at"
    assert 0 <= float(data["us1_pct"]) <= 100
    assert 0 <= float(data["us2_pct"]) <= 100
    assert 0 <= float(data["cull_pct"]) <= 100
    assert float(data["cumulative_shrink_cwt"]) >= 0


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["variety"] in (
        "RUSSET_BURBANK", "RUSSET_NORKOTAH", "RANGER_RUSSET", "YUKON_GOLD", "RED_LASODA"
    )
    assert float(data["committed_volume_cwt"]) > 0
    assert int(data["price_cents_per_cwt"]) > 0
    assert data["status"] in ("ACTIVE", "FULFILLED", "SHORTFALLED")
    for field in ("remaining_committed_cwt", "allocated_active_cwt", "packed_to_date_cwt"):
        assert float(data.get(field, -1)) >= 0, f"{field} must be >= 0"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pack_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["order_type"] in ("CONTRACT", "OPEN_MARKET")
    assert data["status"] in ("REQUESTED", "ALLOCATED", "PACKING", "SHIPPED", "CANCELLED")
    assert data["allocation_policy"] in ("LOT_ASSESSMENT", "SHED_BLEND")
    assert float(data["requested_packed_cwt"]) > 0
    assert float(data.get("packed_to_date_cwt", -1)) >= 0
    assert isinstance(data.get("reservations"), list)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pack_run(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("SCHEDULED", "COMPLETED", "ABORTED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_wash_check(data: dict):
    """Append-only record: id + created_at only; NO version, NO updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "wash checks must not carry version"
    assert "updated_at" not in data, "wash checks must not carry updated_at"
    assert data["result"] in ("PASS", "FAIL")


def assert_audit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("FIELD_WORK", "PASSED", "FAILED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_settlement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "DISPUTED", "PAID", "SUPERSEDED")
    assert isinstance(data["version"], int) and data["version"] >= 1
    for field in (
        "packed_cwt_basis", "pool_price_cents", "gross_cents", "storage_fees_cents",
        "inhibitor_fees_cents", "processing_credits_cents", "net_payable_cents",
    ):
        assert data.get(field) is not None, f"{field} must be present"


def assert_draw(data: dict):
    """Append-only record: id + created_at only; NO version, NO updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "run draws must not carry version"
    assert "updated_at" not in data, "run draws must not carry updated_at"
    assert data["cull_channel"] in ("PROCESSING", "WASTE")


def assert_lot_weight_conservation(lot: dict):
    """PRD §3.2 / shrink reconciliation: original == available + packed + cull + condemned + shrink."""
    total = (
        float(lot["available_cwt"]) + float(lot["packed_total_cwt"]) + float(lot["cull_total_cwt"])
        + float(lot["condemned_cwt"]) + float(lot["shrink_cwt"])
    )
    assert abs(float(lot["original_weight_cwt"]) - total) <= 0.01, (
        f"weight conservation violated: original {lot['original_weight_cwt']} vs ledger sum {total}"
    )


def assert_contract_commitment_conservation(contract: dict):
    """PRD §3.3: committed == remaining + allocated_active + packed_to_date."""
    total = (
        float(contract["remaining_committed_cwt"]) + float(contract["allocated_active_cwt"])
        + float(contract["packed_to_date_cwt"])
    )
    assert abs(float(contract["committed_volume_cwt"]) - total) <= 0.01, (
        f"commitment conservation violated: committed {contract['committed_volume_cwt']} vs ledger sum {total}"
    )
