"""Entity assertions and domain invariant checkers (PRD §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

POSTURES = [
    "PLANNING", "APPLICATION_OPEN", "JURY_REVIEW", "SCHEDULING", "LIVE",
    "WEATHER_HOLD", "SETTLEMENT", "CLOSED", "CANCELLED",
]
WEATHER_FLAGS = ["CLEAR", "ADVISORY", "SEVERE"]
WEATHER_EXPOSURES = ["INDOOR", "COVERED", "OPEN_AIR"]
CRAFT_CATEGORIES = ["CERAMICS", "TEXTILES", "JEWELRY", "WOODWORK", "FOOD", "MIXED"]
BOOTH_TIERS = ["STANDARD", "CORNER", "ANCHOR"]
VENDOR_STATUSES = ["ACTIVE", "SUSPENDED"]
APPLICATION_STATUSES = [
    "DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED", "WAITLISTED", "REJECTED",
    "WITHDRAWN", "CONFIRMED", "CANCELLED",
]
ASSIGNMENT_STATUSES = ["PENDING_PAYMENT", "ACTIVE", "RELEASED", "FORFEITED"]
CHARGE_KINDS = ["PROVISIONAL", "FINAL", "SURCHARGE", "REFUND"]
SLOT_KINDS = ["LOAD_IN", "LOAD_OUT"]
SLOT_BAYS = ["NORTH", "SOUTH"]
TICKET_KINDS = ["GA", "EARLY_BIRD", "VIP"]
TICKET_STATES = ["ISSUED", "REDEEMED", "REFUNDED", "VOIDED"]
SETTLEMENT_STATUSES = ["PENDING", "COMPUTED", "APPROVED", "PAID", "DISPUTED", "CANCELLED"]


def _assert_common_fields(data: dict):
    """Primary-resource common fields (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only records carry id + created_at only; updated_at/version absent (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_maker_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["posture"] in POSTURES
    assert data["weather_flag"] in WEATHER_FLAGS
    assert isinstance(data["venue_capacity"], int)
    assert isinstance(data["jury_quorum"], int)


def assert_booth_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert data["weather_exposure"] in WEATHER_EXPOSURES
    assert data["category"] in CRAFT_CATEGORIES
    assert isinstance(data["category_cap"], int)


def assert_booth(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["tier"] in BOOTH_TIERS
    assert isinstance(data["footprint_sqm"], int)
    assert isinstance(data["price_cents"], int)


def assert_vendor_profile(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in VENDOR_STATUSES


def assert_vendor_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in APPLICATION_STATUSES
    assert data["requested_category"] in CRAFT_CATEGORIES
    assert data["requested_tier"] in BOOTH_TIERS


def assert_jury_score(data: dict):
    _assert_append_only_fields(data)
    for field in ("craftsmanship", "originality", "booth_presentation"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert 0 <= data[field] <= 10, f"{field} must be within 0..10"
    assert isinstance(data["total"], int)
    assert data["total"] == (
        data["craftsmanship"] + data["originality"] + data["booth_presentation"]
    ), "total must be the sum of the three criteria"


def assert_booth_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_booth_fee_charge(data: dict):
    _assert_common_fields(data)
    assert data["charge_kind"] in CHARGE_KINDS
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer cents"


def assert_load_in_slot(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in SLOT_KINDS
    assert data["bay"] in SLOT_BAYS
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))


def assert_ticket(data: dict):
    _assert_common_fields(data)
    assert data["state"] in TICKET_STATES
    assert data["kind"] in TICKET_KINDS
    assert isinstance(data["price_cents"], int)


def assert_attendance(data: dict):
    _assert_append_only_fields(data)
    assert is_iso8601_timestamp(data.get("entered_at", ""))


def assert_sales_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["gross_cents"], int), "gross_cents must be integer cents"


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in SETTLEMENT_STATUSES
    for field in ("gross_sales_cents", "commission_cents", "net_payout_cents"):
        if field in data and data[field] is not None:
            assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_settlement_figures_invariant(data: dict):
    """Domain invariant after compute: net == gross - commission - outstanding fee,
    with the outstanding booth fee never below zero (PRD §3.7). When the booth fee
    was already paid in full, outstanding is zero and net == gross - commission."""
    gross = data["gross_sales_cents"]
    commission = data["commission_cents"]
    net = data["net_payout_cents"]
    assert gross >= 0, "gross_sales_cents is floored at zero"
    assert commission >= 0
    assert net <= gross - commission, (
        f"net_payout_cents ({net}) must not exceed gross - commission ({gross - commission})"
    )
