"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4 primary-resource system fields."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only(data: dict, what: str):
    """PRD §2.4 append-only exception: only id + created_at are carried."""
    assert is_valid_uuid(data.get("id", "")), f"{what} id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what} created_at must be ISO 8601 UTC"
    )
    assert "version" not in data, (
        f"{what} must not carry version (append-only)"
    )
    assert "updated_at" not in data, (
        f"{what} must not carry updated_at (append-only)"
    )


def assert_artist(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["agency"], str) and data["agency"]
    assert isinstance(data["guarantee_floor_cents"], int)
    assert isinstance(data["deposit_pct"], (int, float))
    assert 0.0 <= data["deposit_pct"] <= 0.5
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["total_settled_shows"], int)


def assert_show(data: dict):
    assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["room"] in ("MAIN_ROOM", "LOUNGE")
    assert isinstance(data["show_date"], str)
    assert is_iso8601_timestamp(data["doors_at_utc"])
    assert is_iso8601_timestamp(data["curfew_at_utc"])
    assert data["status"] in (
        "HOLD_PENDING", "CONFIRMED", "ON_SALE", "ADVANCED",
        "SHOW_NIGHT", "SETTLED", "CANCELLED", "POSTPONED",
    )
    assert data["hold_priority"] in ("NONE", "P1", "P2", "COURTESY")
    assert isinstance(data["total_capacity"], int)
    assert isinstance(data["tickets_sold"], int)
    assert isinstance(data["gross_ticket_revenue_cents"], int)
    assert is_iso8601_timestamp(data["on_sale_at_utc"])
    assert isinstance(data["weather_or_emergency_flag"], bool)
    assert data["cancellation_reason"] in (
        "NONE", "ARTIST", "VENUE", "FORCE_MAJEURE", "LOW_TICKET_SALES",
    )


def assert_date_hold(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert data["priority"] in ("P1", "P2", "COURTESY")
    assert data["status"] in (
        "ACTIVE", "CHALLENGED", "CONFIRMED", "RELEASED", "EXPIRED",
    )
    assert is_iso8601_timestamp(data["hold_expires_at_utc"])
    assert isinstance(data["booked_by_agent_id"], str)


def assert_booking_agent(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_offer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["proposed_by_role"] in ("BOOKING_AGENT", "VENUE_MANAGER")
    assert data["deal_kind"] in ("FLAT_GUARANTEE", "DOOR_SPLIT", "VERSUS")
    assert data["status"] in (
        "PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "SUPERSEDED",
    )


def assert_deal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["offer_id"], str)
    assert data["deal_kind"] in ("FLAT_GUARANTEE", "DOOR_SPLIT", "VERSUS")
    assert data["status"] in ("ACTIVE", "VOID")


def assert_ticket_tier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["tier_name"], str) and data["tier_name"]
    assert isinstance(data["face_price_cents"], int) and data["face_price_cents"] > 0
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert isinstance(data["refund_count"], int) and data["refund_count"] >= 0
    assert isinstance(data["tier_order"], int)


def assert_ticket_sale(data: dict):
    _assert_append_only(data, "TicketSale")
    assert isinstance(data["show_id"], str)
    assert isinstance(data["tier_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["gross_amount_cents"], int)
    assert is_iso8601_timestamp(data["sold_at_utc"])
    assert data["refund_status"] in ("NONE", "REFUNDED")


def assert_advance_checklist(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    for field in (
        "hospitality_done", "tech_done", "backline_done",
        "production_requirements_done", "insurance_cert_received", "w9_received",
    ):
        assert isinstance(data[field], bool), f"{field} must be bool"
    assert isinstance(data["all_complete"], bool)


def assert_support_act(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["artist_name"], str) and data["artist_name"]
    assert isinstance(data["agreed_fee_cents"], int)
    assert isinstance(data["buyout_fee_cents"], int)
    assert data["status"] in ("CONFIRMED", "PERFORMED", "BOUGHT_OUT", "CANCELLED")
    assert isinstance(data["paid_cents"], int)


def assert_expense_receipt(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert data["category"] in (
        "SOUND", "LIGHTS", "BACKLINE", "HOSPITALITY", "SECURITY", "MARKETING", "MISC",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["receipt_reference"], str)
    assert data["submitted_by_role"] in ("PROMOTER", "VENUE_MANAGER")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(data["is_recoupable"], bool)


def assert_ancillary_revenue(data: dict):
    _assert_append_only(data, "AncillaryRevenue")
    assert isinstance(data["show_id"], str)
    assert data["kind"] in ("BAR", "MERCH")
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] > 0
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert data["recorded_by_role"] in ("PROMOTER", "VENUE_MANAGER")
    assert is_iso8601_timestamp(data["recorded_at_utc"])


def assert_settlement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "PAID", "DISPUTED")
    for field in (
        "gross_ticket_revenue_cents", "recoupable_expenses_cents",
        "net_door_cents", "artist_door_share_cents", "guarantee_paid_cents",
        "bonus_cents", "bar_artist_share_cents", "merch_venue_share_cents",
        "support_payouts_cents", "deposit_credit_cents",
        "artist_total_due_cents", "venue_net_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int cents"


def assert_wire_transfer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["show_id"], str)
    assert data["purpose"] in (
        "ARTIST_DEPOSIT", "ARTIST_BALANCE", "SUPPORT_FEE",
        "SUPPORT_BUYOUT", "REFUND_TO_VENUE",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("INITIATED", "COMPLETED", "FAILED", "RETURNED")
    assert data["initiated_by_role"] == "ACCOUNTANT"
    assert is_iso8601_timestamp(data["initiated_at_utc"])


def assert_cancellation_event(data: dict):
    _assert_append_only(data, "CancellationEvent")
    assert isinstance(data["show_id"], str)
    assert data["reason"] in ("ARTIST", "VENUE", "FORCE_MAJEURE", "LOW_TICKET_SALES")
    assert data["declared_by_role"] in ("BOOKING_AGENT", "VENUE_MANAGER", "PROMOTER")
    assert is_iso8601_timestamp(data["declared_at_utc"])
    assert isinstance(data["days_before_show"], int) and data["days_before_show"] >= 0
    assert isinstance(data["artist_penalty_pct"], (int, float))
    assert isinstance(data["artist_penalty_cents"], int)
    assert isinstance(data["deposit_refundable_cents"], int)
    assert isinstance(data["support_kill_fee_cents"], int)


def assert_settlement_invariants(data: dict):
    """Domain invariants that must hold on any Settlement (PRD §3.7)."""
    assert data["net_door_cents"] >= 0, "net_door_cents floored at 0"
    assert data["artist_total_due_cents"] >= 0, "artist_total_due_cents floored at 0"
    assert data["net_door_cents"] == max(
        0, data["gross_ticket_revenue_cents"] - data["recoupable_expenses_cents"],
    ), "net_door = gross - recoupable, floored at 0"
