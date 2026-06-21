"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PRODUCTION_STATES = ["INTAKE", "QUOTED", "IN_PRODUCTION", "READY", "PICKED_UP", "CANCELLED"]
PAYMENT_STATES = ["UNBILLED", "DEPOSIT_DUE", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
LINE_STATES = ["DRAFT", "MEASURED", "VOID"]
TASK_STATES = ["SCHEDULED", "COMPLETED", "RELEASED"]
GLASS_TYPES = ["REGULAR", "CONSERVATION", "MUSEUM"]
MOUNTING_TYPES = ["NONE", "PLAIN", "DRY_MOUNT", "CONSERVATION_HINGE"]
BENCH_TYPES = ["ASSEMBLY", "GLASS_CUTTING"]
LOYALTY_TIERS = ["STANDARD", "PREFERRED", "TRADE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert data["loyalty_tier"] in LOYALTY_TIERS, f"bad loyalty_tier {data['loyalty_tier']}"
    assert isinstance(data["loyalty_discount_pct"], (int, float))
    assert isinstance(data["open_order_count"], int) and data["open_order_count"] >= 0
    assert 0 <= data["no_show_risk_score"] <= 100, "no_show_risk_score in [0,100]"
    assert 0 <= data["settled_reputation_score"] <= 100, "settled_reputation_score in [0,100]"


def assert_workbench(data: dict):
    _assert_common(data)
    assert isinstance(data["bench_name"], str)
    assert data["bench_type"] in BENCH_TYPES, f"bad bench_type {data['bench_type']}"
    assert isinstance(data["clean_buffer_minutes"], int) and data["clean_buffer_minutes"] >= 0


def assert_framing_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["production_status"] in PRODUCTION_STATES, f"bad production_status {data['production_status']}"
    assert data["payment_status"] in PAYMENT_STATES, f"bad payment_status {data['payment_status']}"
    assert isinstance(data["has_fragile_line"], bool)
    assert isinstance(data["rush_requested"], bool)
    for f in ("estimate_total", "deposit_required", "final_invoice_total", "amount_paid", "balance_due"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["turnaround_days"], int)


def assert_frame_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["artwork_label"], str)
    assert data["line_status"] in LINE_STATES, f"bad line_status {data['line_status']}"
    assert data["glass_type"] in GLASS_TYPES, f"bad glass_type {data['glass_type']}"
    assert data["mounting_type"] in MOUNTING_TYPES, f"bad mounting_type {data['mounting_type']}"
    assert data["nominal_width_in"] > 0 and data["nominal_height_in"] > 0
    assert isinstance(data["estimate_subtotal"], (int, float))


def assert_production_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("workbench_id", "")), "workbench_id must be a UUID"
    assert data["task_status"] in TASK_STATES, f"bad task_status {data['task_status']}"
    assert isinstance(data["start_minute"], int) and data["start_minute"] >= 0
    assert isinstance(data["end_minute"], int) and data["end_minute"] > data["start_minute"]


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["kind"] in ["DEPOSIT", "BALANCE", "REFUND"], f"bad kind {data['kind']}"
    assert data["payment_status"] in ["APPLIED", "VOID"]
    assert data["amount"] > 0


def assert_notification(data: dict):
    """Notification is append-only: id + created_at only, NO version, NO updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Notification must NOT carry a version field"
    assert "updated_at" not in data, "Notification must NOT carry an updated_at field"
    assert data["kind"] in ["READY", "DEPOSIT_RECEIPT"], f"bad notification kind {data['kind']}"
    assert data["channel"] in ["EMAIL", "SMS"], f"bad channel {data['channel']}"
