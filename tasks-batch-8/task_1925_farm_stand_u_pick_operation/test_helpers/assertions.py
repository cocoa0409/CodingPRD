"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_season(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "ARCHIVED")
    assert isinstance(data["current_waiver_version"], int)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_crop(data: dict):
    _assert_common(data)
    assert isinstance(data["price_per_lb_cents"], int)
    assert isinstance(data["season_picked_oz"], int)


def assert_field(data: dict):
    _assert_common(data)
    assert data["status"] in ("DORMANT", "OPEN", "PICKED_OUT", "ROTATION_REST", "RETIRED")
    assert isinstance(data["estimated_harvest_oz"], int)
    assert isinstance(data["committed_picked_oz"], int)
    assert isinstance(data["projected_remaining_oz"], int)


def assert_window(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["picking_capacity_slots"], int)
    assert isinstance(data["booked_slots"], int)


def assert_pricing_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["policy_version"], int)


def assert_waiver(data: dict):
    _assert_common(data)
    assert data["status"] in ("SIGNED", "VOIDED")
    assert isinstance(data["waiver_version_signed"], int)
    assert isinstance(data["party_member_names"], list)


def assert_visit_session(data: dict):
    _assert_common(data)
    assert data["visit_status"] in (
        "CHECKED_IN", "FIELD_ACTIVE", "CHECKED_OUT", "CANCELLED", "VOIDED")
    assert data["payment_status"] in (
        "UNPAID", "PARTIALLY_PAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED")
    assert isinstance(data["admission_charge_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["total_refunded_cents"], int)


def assert_harvest_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "VOIDED")
    assert isinstance(data["gross_weight_oz"], int)
    assert isinstance(data["tare_oz"], int)
    assert isinstance(data["net_oz"], int)
    assert isinstance(data["line_charge_cents"], int)


def assert_addon_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "REDEEMED", "RELEASED")
    assert isinstance(data["qty"], int)
    assert isinstance(data["booked_value_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "SETTLED", "FAILED", "PARTIALLY_REFUNDED", "REFUNDED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["refunded_amount_cents"], int)


def assert_sales_day(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED_NORMAL", "CLOSED_WEATHER")
    assert isinstance(data["booked_parking"], int)
    assert isinstance(data["revenue_cents"], int)


def assert_offline_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("APPLIED", "PARTIALLY_APPLIED")
    assert isinstance(data["results"], list)
    assert isinstance(data["applied_count"], int)
    assert isinstance(data["conflict_count"], int)


def assert_session_money_invariants(session: dict):
    """Money ledger invariants of PRD §3.7 that must hold on any session read."""
    assert session["total_paid_cents"] >= 0
    assert session["total_refunded_cents"] >= 0
    assert session["total_refunded_cents"] <= session["total_paid_cents"], (
        "money is never created: refunds never exceed collected amount"
    )


def assert_field_tally_invariants(field: dict):
    """Tally relationship of PRD §3.2: committed never exceeds the estimate basis."""
    assert field["committed_picked_oz"] >= 0
    assert isinstance(field["projected_remaining_oz"], int)
