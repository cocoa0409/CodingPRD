"""Entity assertions and the service's conservation invariants."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ─── Common properties every resource carries ─────────────────────────────

def assert_common_fields(data: dict, expect_version: int = None) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expect_version is not None:
        assert data["version"] == expect_version, (
            f"Expected version {expect_version}, got {data['version']}"
        )


def assert_fresh_resource(data: dict) -> None:
    """A just-created resource has version 1 and updated_at equal to created_at."""
    assert_common_fields(data, expect_version=1)
    assert data["updated_at"] == data["created_at"], (
        "At creation updated_at equals created_at, got "
        f"{data['updated_at']} vs {data['created_at']}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_venue(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["seat_capacity"] >= 1, "seat_capacity must be at least 1"
    assert 0 <= data["house_hold_seats"] < data["seat_capacity"]
    assert data["trailer_reel_minutes"] >= 0
    assert data["turnaround_minutes"] >= 0
    assert data["dcp_ingest_lane_count"] >= 1
    assert data["min_useful_gap_minutes"] >= 0
    assert 0 < data["max_first_run_share"] <= 1
    assert data["weekly_repertory_target"] >= 0
    assert data["base_house_nut_weekly_cents"] >= 0
    assert isinstance(data["supported_formats"], list) and data["supported_formats"]
    for fmt in data["supported_formats"]:
        assert fmt in (
            "DCP_2K", "DCP_4K", "PRINT_35MM", "PRINT_16MM", "DIGITAL_FILE_PRORES",
        )


def assert_distributor(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["default_terms_variant"] in (
        "SLIDING_SCALE_90_10", "PERCENTAGE_FLOOR", "FLAT_FEE",
    )
    assert data["default_min_run_days"] >= 1
    assert 0 <= data["default_distributor_share_pct"] <= 1
    assert isinstance(data["requires_advance_guarantee"], bool)


def assert_title(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["title_name"], str) and data["title_name"]
    assert isinstance(data["release_year"], int)
    assert data["runtime_minutes"] >= 1
    assert isinstance(data["is_first_run"], bool)
    assert data["native_format"] in (
        "DCP_2K", "DCP_4K", "PRINT_35MM", "PRINT_16MM", "DIGITAL_FILE_PRORES",
    )
    assert is_valid_uuid(data["rights_holder_distributor_id"])


def assert_booking(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "OFFERED", "COUNTERED", "CONFIRMED", "RUNNING", "CLOSED", "WITHDRAWN",
    )
    assert data["terms_variant"] in (
        "SLIDING_SCALE_90_10", "PERCENTAGE_FLOOR", "FLAT_FEE",
    )
    assert data["house_nut_cents"] >= 0
    assert 0 <= data["distributor_share_pct"] <= 1
    assert data["guarantee_cents"] >= 0
    assert data["min_run_days"] >= 1
    assert data["engagement_start_date"] <= data["engagement_end_date"]
    assert data["round_count"] >= 1
    assert data["scheduled_showtime_count"] >= 0
    assert data["actual_playing_days"] >= 0
    assert isinstance(data["min_run_compliant"], bool)
    assert data["min_run_penalty_cents"] >= 0


def assert_booking_offer(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["round_index"] >= 1
    assert data["proposed_by"] in ("CINEMA", "DISTRIBUTOR")
    assert data["outcome"] in (
        "PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "EXPIRED",
    )
    assert data["proposed_house_nut_cents"] >= 0
    assert 0 <= data["proposed_distributor_share_pct"] <= 1
    assert data["proposed_min_run_days"] >= 1
    assert data["proposed_guarantee_cents"] >= 0
    assert is_iso8601_timestamp(data["expires_at"])


def assert_clearance(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "CHANGES_REQUESTED", "CLEARED", "EXPIRED", "REVOKED",
    )
    assert data["license_fee_cents"] >= 0
    assert data["max_screenings"] >= 1
    assert data["window_start_date"] <= data["window_end_date"]
    assert_screening_allowance_conserved(data)


def assert_dcp_asset(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "IN_TRANSIT", "RECEIVED", "INGESTING", "INGESTED", "RETURNED",
    )
    assert isinstance(data["is_encrypted"], bool)
    assert data["ingest_window_start_at"] < data["ingest_window_end_at"]


def assert_kdm_key(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("ISSUED", "EXPIRED", "REVOKED")
    assert data["valid_from"] < data["valid_until"]
    assert isinstance(data["server_ref"], str) and data["server_ref"]


def assert_showtime(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["sale_status"] in ("DRAFT", "ON_SALE", "SOLD_OUT", "SALES_CLOSED")
    assert data["playback_status"] in (
        "UNVERIFIED", "KEY_PENDING", "PLAYBACK_VERIFIED", "PLAYBACK_FAILED",
    )
    assert data["strand"] in (
        "FIRST_RUN", "REPERTORY_SERIES", "FESTIVAL", "SPECIAL_EVENT",
    )
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert is_iso8601_timestamp(data["blocked_until"])
    assert data["start_at"] < data["end_at"] <= data["blocked_until"]
    assert data["base_price_cents"] >= 0
    assert data["surcharge_cents"] >= 0
    assert data["seats_sold"] >= 0
    assert data["seats_available"] >= 0, "seats_available never falls below zero"
    assert data["gross_cents"] >= 0
    assert data["admissions_count"] >= 0


def assert_special_event(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "CONFIRMED", "CANCELLED")
    assert data["event_type"] in (
        "FILMMAKER_QA", "PANEL", "FESTIVAL_SCREENING", "THEMED_INTRO",
    )
    assert data["extra_minutes"] >= 0
    assert data["surcharge_cents"] >= 0
    assert data["guest_fee_cents"] >= 0
    assert isinstance(data["displaced_showtime_ids"], list)


def assert_ticket_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("RESERVED", "PAID", "REFUNDED", "VOID")
    assert 1 <= data["quantity"] <= 10
    assert 0 <= data["comp_quantity"] <= data["quantity"]
    assert data["unit_price_cents"] >= 0
    assert data["line_subtotal_cents"] >= 0
    assert data["facility_fee_cents"] >= 0
    assert data["applied_credit_cents"] >= 0
    assert data["total_cents"] >= 0, "total_cents never goes negative"
    if data["refund_destination"] is not None:
        assert data["refund_destination"] in ("CASH", "MEMBER_CREDIT")


def assert_member(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACTIVE", "LAPSED")
    for field in ("rolling_tier", "fiscal_tier", "effective_tier"):
        assert data[field] in ("PROSPECT", "BASIC", "SUPPORTER", "DONOR_CIRCLE")
    assert data["rolling_donation_cents"] >= 0
    assert data["fiscal_ytd_donation_cents"] >= 0
    assert 0 <= data["discount_pct"] <= 1
    assert data["advance_access_hours"] >= 0
    assert data["comp_tickets_granted"] >= 0
    assert data["comp_tickets_remaining"] <= data["comp_tickets_granted"]
    assert data["credit_balance_cents"] >= 0
    assert isinstance(data["donations"], list)


def assert_settlement(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RECONCILED", "DISPUTED", "PAID",
    )
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["playing_days"] >= 0
    assert 0 <= data["proration_factor"] <= 1
    assert data["house_nut_applied_cents"] >= 0
    assert data["film_rent_cents"] >= 0
    assert data["adjusted_gross_cents"] == (
        data["box_office_cents"] - data["facility_fee_total_cents"]
    ), "adjusted_gross_cents is box_office_cents less facility_fee_total_cents"
    assert data["cinema_retained_cents"] == (
        data["adjusted_gross_cents"]
        + data["facility_fee_total_cents"]
        - data["film_rent_cents"]
    ), "cinema_retained_cents is adjusted gross plus facility fee less film rent"


# ─── Conservation invariants ──────────────────────────────────────────────

def assert_seat_conservation(showtime: dict, venue: dict) -> None:
    """seats_sold + seats_available + house_hold_seats == seat_capacity."""
    total = (
        showtime["seats_sold"]
        + showtime["seats_available"]
        + venue["house_hold_seats"]
    )
    assert total == venue["seat_capacity"], (
        f"Seat identity broken: {showtime['seats_sold']} sold + "
        f"{showtime['seats_available']} available + {venue['house_hold_seats']} held "
        f"!= {venue['seat_capacity']} capacity"
    )
    assert showtime["seats_available"] >= 0, "seats_available never falls below zero"


def assert_screening_allowance_conserved(clearance: dict) -> None:
    """screenings_used + screenings_remaining == max_screenings."""
    assert clearance["screenings_used"] >= 0
    assert clearance["screenings_remaining"] >= 0, "screenings_remaining never negative"
    assert (
        clearance["screenings_used"] + clearance["screenings_remaining"]
        == clearance["max_screenings"]
    ), (
        f"Allowance identity broken: {clearance['screenings_used']} used + "
        f"{clearance['screenings_remaining']} remaining != "
        f"{clearance['max_screenings']} max_screenings"
    )


def assert_order_pricing(order: dict, unit_price_cents, line_subtotal_cents,
                         facility_fee_cents, total_cents,
                         applied_credit_cents=0) -> None:
    """Pin an order's whole stored price breakdown."""
    assert order["unit_price_cents"] == unit_price_cents, (
        f"unit_price_cents expected {unit_price_cents}, got {order['unit_price_cents']}"
    )
    assert order["line_subtotal_cents"] == line_subtotal_cents, (
        f"line_subtotal_cents expected {line_subtotal_cents}, "
        f"got {order['line_subtotal_cents']}"
    )
    assert order["facility_fee_cents"] == facility_fee_cents, (
        f"facility_fee_cents expected {facility_fee_cents}, "
        f"got {order['facility_fee_cents']}"
    )
    assert order["applied_credit_cents"] == applied_credit_cents, (
        f"applied_credit_cents expected {applied_credit_cents}, "
        f"got {order['applied_credit_cents']}"
    )
    assert order["total_cents"] == total_cents, (
        f"total_cents expected {total_cents}, got {order['total_cents']}"
    )


def assert_screen_block(showtime: dict, expected_end_at, expected_blocked_until) -> None:
    assert showtime["end_at"] == expected_end_at, (
        f"end_at expected {expected_end_at}, got {showtime['end_at']}"
    )
    assert showtime["blocked_until"] == expected_blocked_until, (
        f"blocked_until expected {expected_blocked_until}, "
        f"got {showtime['blocked_until']}"
    )
