"""Entity assertions, timestamp helpers and conservation-invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Timestamps: always compared semantically, never as strings.
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 'Z' and any fractional precision."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Compare two ISO 8601 instants at second granularity.

    A server-written stamp may be rendered with three fractional digits while a
    caller-supplied stamp is echoed verbatim; only the instant is contractual.
    """
    a = parse_instant(actual).replace(microsecond=0)
    b = parse_instant(expected).replace(microsecond=0)
    assert a == b, f"{label}: expected instant {expected}, got {actual}"


def assert_date_equals(actual: str, expected: str, label: str = "date"):
    """Compare a calendar date field; accepts a bare date or a full instant."""
    assert isinstance(actual, str) and actual, f"{label}: expected a date, got {actual!r}"
    actual_date = actual[:10]
    assert actual_date == expected[:10], (
        f"{label}: expected date {expected[:10]}, got {actual_date} (raw {actual!r})"
    )


# ---------------------------------------------------------------------------
# Common field shape
# ---------------------------------------------------------------------------
def assert_versioned_resource(data: dict, label: str = "resource"):
    """id + created_at + updated_at + version, per the PRD's resource identity rules."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert "_" not in str(data.get("id", "")), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_append_only_resource(data: dict, label: str = "resource"):
    """id + created_at only — no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_client(data: dict):
    assert_versioned_resource(data, "Client")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert "@" in data["email"], "Client.email must contain an at-sign"
    assert data["client_type"] in ("INDIVIDUAL", "INSTITUTION", "DEALER")
    assert data["home_zone_code"] in ("ZONE_A", "ZONE_B", "ZONE_C")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["account_credit_cents"], int)


def assert_location(data: dict):
    assert_versioned_resource(data, "Location")
    assert data["zone_code"] in ("ZONE_A", "ZONE_B", "ZONE_C")
    assert isinstance(data["stair_flights"], int) and 0 <= data["stair_flights"] <= 8
    assert isinstance(data["out_of_band_flag"], bool)
    assert isinstance(data["readings_in_window"], int)
    assert isinstance(data["out_of_band_count"], int)
    assert data["out_of_band_count"] <= data["readings_in_window"]


def assert_instrument(data: dict):
    assert_versioned_resource(data, "Instrument")
    assert data["instrument_class"] in (
        "UPRIGHT", "CONSOLE", "BABY_GRAND", "GRAND", "CONCERT_GRAND",
    )
    assert data["usage_tier"] in ("HOME", "STUDIO", "INSTITUTIONAL", "PERFORMANCE")
    assert data["condition_status"] in (
        "NEEDS_ASSESSMENT", "SERVICEABLE", "NEEDS_REGULATION",
        "NEEDS_VOICING", "REBUILD_REQUIRED", "RESTORED",
    )
    assert data["custody_status"] in (
        "AT_CLIENT_SITE", "IN_TRANSIT", "IN_SHOP", "SHOWROOM_FLOOR", "SOLD",
    )
    assert isinstance(data["unauthorized_move_flag"], bool)


def assert_quote(data: dict):
    assert_versioned_resource(data, "Quote")
    assert data["status"] in (
        "DRAFT", "ISSUED", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED",
    )
    assert data["service_type"] in (
        "TUNE", "PITCH_RAISE", "REGULATE", "VOICE", "REBUILD",
    )
    assert data["line_count"] in (1, 2)
    for money in (
        "base_price_cents", "line_discount_cents", "zone_surcharge_cents",
        "subtotal_cents", "loyalty_discount_cents", "total_cents",
        "deposit_required_cents",
    ):
        assert isinstance(data[money], int), f"Quote.{money} must be integer cents"


def assert_service_order(data: dict):
    assert_versioned_resource(data, "ServiceOrder")
    assert data["status"] in (
        "PENDING", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED",
        "VOIDED_BY_REBUILD",
    )
    assert isinstance(data["contract_total_cents"], int)
    assert isinstance(data["estimated_minutes"], int)
    assert data["visit_plan_variant"] in ("SINGLE_VISIT", "SPLIT_VISIT")


def assert_milestone(data: dict):
    assert_versioned_resource(data, "Milestone")
    assert data["status"] in (
        "PENDING", "READY", "RELEASED", "REJECTED", "ACCEPTED", "CANCELLED",
    )
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["amount_cents"], int)


def assert_appointment(data: dict):
    assert_versioned_resource(data, "Appointment")
    assert data["scheduling_status"] in (
        "REQUESTED", "SCHEDULED", "CONFIRMED", "RESCHEDULED", "CANCELLED",
    )
    assert data["fulfillment_status"] in (
        "PENDING", "EN_ROUTE", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "ABORTED",
    )
    assert data["total_block_minutes"] == (
        data["service_minutes"] + data["travel_buffer_minutes"]
    ), "total_block_minutes must equal service_minutes plus the travel buffer"


def assert_move_job(data: dict):
    assert_versioned_resource(data, "MoveJob")
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
    )
    assert data["distance_band"] in ("LOCAL", "REGIONAL", "LONG_HAUL")
    assert data["distance_variant"] in ("FLAT_LOCAL", "PER_MILE", "LONG_HAUL_FLAT")
    assert data["total_cents"] == (
        data["base_cents"] + data["stair_cents"] + data["crane_cents"]
        + data["distance_cents"] + data["climate_cents"]
    ), "MoveJob.total_cents must be the plain sum of the five components"


def assert_warranty(data: dict):
    assert_versioned_resource(data, "Warranty")
    assert data["status"] in ("ACTIVE", "TRANSFERRED", "VOIDED", "EXPIRED")
    assert isinstance(data["term_days"], int)
    assert isinstance(data["claim_count"], int)


def assert_warranty_claim(data: dict):
    assert_versioned_resource(data, "WarrantyClaim")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED_RESERVICE", "APPROVED_CREDIT", "DENIED",
    )
    assert data["resolution_variant"] in ("FREE_RESERVICE", "PRORATED_CREDIT")
    assert isinstance(data["credit_cents"], int)


def assert_consignment_agreement(data: dict):
    assert_versioned_resource(data, "ConsignmentAgreement")
    assert data["status"] in (
        "DRAFT", "ACTIVE", "LISTED", "SOLD", "EXPIRED", "WITHDRAWN",
    )
    assert isinstance(data["reserve_price_cents"], int)


def assert_parts_lot(data: dict):
    assert_versioned_resource(data, "PartsLot")
    assert data["status"] in ("OPEN", "DEPLETED")
    assert data["part_type"] in ("HAMMER_SET", "STRING_SET", "ACTION_PARTS")


def assert_climate_reading(data: dict):
    assert_append_only_resource(data, "ClimateReading")
    assert isinstance(data["in_band"], bool)


def assert_ledger_entry(data: dict):
    assert_append_only_resource(data, "LedgerEntry")
    assert data["entry_type"] in (
        "DEPOSIT_CHARGE", "MILESTONE_CHARGE", "WARRANTY_CREDIT",
        "CONSIGNMENT_PROCEEDS", "DEPOSIT_REFUND", "CANCELLATION_FEE",
        "MANUAL_ADJUSTMENT", "REVERSAL",
    )
    assert isinstance(data["amount_cents"], int)


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.10)
# ---------------------------------------------------------------------------
def assert_parts_conservation(lot: dict):
    """on_hand_qty + allocated_qty + consumed_qty == initial_qty."""
    total = lot["on_hand_qty"] + lot["allocated_qty"] + lot["consumed_qty"]
    assert total == lot["initial_qty"], (
        f"parts conservation broken: {lot['on_hand_qty']} + {lot['allocated_qty']} + "
        f"{lot['consumed_qty']} = {total}, expected initial_qty {lot['initial_qty']}"
    )


def assert_route_minutes_conservation(route_day: dict, appointments: list):
    """committed_minutes == sum of total_block_minutes over live stops of that day."""
    live = [
        a for a in appointments
        if a["route_day_id"] == route_day["id"]
        and a["scheduling_status"] in ("SCHEDULED", "CONFIRMED")
    ]
    expected = sum(a["total_block_minutes"] for a in live)
    assert route_day["committed_minutes"] == expected, (
        f"route minutes conservation broken: committed_minutes "
        f"{route_day['committed_minutes']} != {expected}"
    )
    assert route_day["stop_count"] == len(live), (
        f"stop_count {route_day['stop_count']} != {len(live)} live stops"
    )


def assert_client_money_conservation(client: dict, ledger_rows: list):
    """account_credit_cents == the plain sum of amount_cents over every row."""
    expected = sum(r["amount_cents"] for r in ledger_rows)
    assert client["account_credit_cents"] == expected, (
        f"client money conservation broken: account_credit_cents "
        f"{client['account_credit_cents']} != ledger sum {expected}"
    )


def assert_sale_proceeds_conservation(agreement: dict):
    """sale_price_cents == advance_recovered + shop_commission + consignor_payout."""
    total = (
        agreement["advance_recovered_cents"]
        + agreement["shop_commission_cents"]
        + agreement["consignor_payout_cents"]
    )
    assert total == agreement["sale_price_cents"], (
        f"sale proceeds conservation broken: parts sum to {total}, "
        f"sale_price_cents is {agreement['sale_price_cents']}"
    )


def assert_contracted_value_conservation(order: dict, milestones: Optional[list] = None):
    """billed + unbilled == contract_total; milestone amounts also sum to it."""
    assert order["billed_cents"] + order["unbilled_cents"] == order["contract_total_cents"], (
        f"contracted value broken: {order['billed_cents']} + {order['unbilled_cents']} "
        f"!= {order['contract_total_cents']}"
    )
    if milestones is not None:
        total = sum(m["amount_cents"] for m in milestones)
        assert total == order["contract_total_cents"], (
            f"milestone amounts sum to {total}, contract_total_cents is "
            f"{order['contract_total_cents']}"
        )


def assert_deposit_disposition(order: dict):
    """At a terminal status: held == applied + refunded + forfeited."""
    total = (
        order["deposit_applied_cents"]
        + order["deposit_refunded_cents"]
        + order["deposit_forfeited_cents"]
    )
    assert total == order["deposit_held_cents"], (
        f"deposit disposition broken: applied+refunded+forfeited = {total}, "
        f"deposit_held_cents is {order['deposit_held_cents']}"
    )
