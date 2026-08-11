"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, *, versioned: bool = True):
    assert is_valid_uuid(str(data.get("id", ""))), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(str(data.get("updated_at", ""))), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"
    else:
        assert "updated_at" not in data, "append-only record must not carry updated_at"
        assert "version" not in data, "append-only record must not carry version"


def assert_formulation(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["chemistry_family"] in ("EPOXY", "POLYURETHANE", "SILICONE", "ACRYLIC")
    assert isinstance(data["moisture_sensitive"], bool)
    assert data["status"] in ("DRAFT", "EFFECTIVE", "WITHDRAWN")


def assert_vessel(data: dict):
    _assert_common(data)
    assert isinstance(data["vessel_code"], str) and data["vessel_code"]
    assert isinstance(data["capacity_liters"], int)


def assert_dry_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert isinstance(data["max_concurrent_runs"], int)


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("MIXING", "MIXED", "PACKING", "PACKED", "EXPIRED", "VOID")
    assert isinstance(data["batch_volume_ml"], int)
    assert isinstance(data["remaining_bulk_volume_ml"], int)
    assert isinstance(data["written_off_volume_ml"], int)


def assert_packaging_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SEALED", "HOLD", "VOID")
    assert data["pack_format"] in ("CARTRIDGE", "PAIL", "DRUM")
    assert isinstance(data["unit_volume_ml"], int)


def assert_exposure_event(data: dict):
    _assert_common(data, versioned=False)
    assert isinstance(data["exposure_minutes"], int)
    assert isinstance(data["packaging_run_id"], str)


def assert_lot(data: dict):
    _assert_common(data)
    assert data["qa_status"] in ("AWAITING_TEST", "TESTING", "UNDER_REVIEW", "RELEASED", "REJECTED")
    assert data["hold_status"] in ("CLEAR", "QUARANTINE_HOLD")
    for f in ("units_filled", "units_quarantined", "units_condemned", "units_shipped", "retest_count"):
        assert isinstance(data[f], int), f"{f} must be an int"


def assert_cure_test(data: dict):
    _assert_common(data)
    assert data["method"] in ("QUICK", "FULL")
    assert data["status"] in ("RECORDED", "ACCEPTED", "SUPERSEDED", "VOIDED")
    assert isinstance(data["specimens"], list)


def assert_formulation_request(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "TECH_REVIEW", "NEEDS_INFO", "APPROVED",
        "IN_DEVELOPMENT", "CONVERTED", "DECLINED",
    )


def assert_distributor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["max_consigned_value_cents"], int)


def assert_consignment_stock(data: dict):
    _assert_common(data)
    for f in ("qty_shipped", "qty_consumed", "qty_returned", "qty_on_hand"):
        assert isinstance(data[f], int), f"{f} must be an int"


def assert_consumption_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "SETTLED", "DISPUTED", "VOID")
    assert isinstance(data["consumed_units"], int)


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["shipment_kind"] in ("SALE", "CONSIGNMENT", "CONSIGNMENT_REPLENISHMENT")
    assert data["transport_mode"] in ("ROAD", "AIR", "SEA")
    assert data["status"] in ("DRAFT", "PLANNED", "CONFIRMED", "DISPATCHED", "EXCEPTION", "CANCELLED")
    assert isinstance(data["lines"], list)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_batch_volume_invariant(batch: dict):
    """Batch volume is conserved: remaining never negative, never above the
    original volume, and written-off never negative."""
    assert batch["remaining_bulk_volume_ml"] >= 0
    assert batch["written_off_volume_ml"] >= 0
    assert batch["remaining_bulk_volume_ml"] + batch["written_off_volume_ml"] <= batch["batch_volume_ml"]


def assert_consignment_units_invariant(stock: dict):
    """Consignment units are conserved: shipped - consumed - returned == on hand."""
    assert (
        stock["qty_shipped"] - stock["qty_consumed"] - stock["qty_returned"] == stock["qty_on_hand"]
    ), (
        f"qty_on_hand {stock['qty_on_hand']} != "
        f"{stock['qty_shipped']} - {stock['qty_consumed']} - {stock['qty_returned']}"
    )
