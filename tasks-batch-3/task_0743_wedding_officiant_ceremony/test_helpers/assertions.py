"""Entity assertions and domain invariant checkers (PRD Sections 2.4, 2.6, 3).

Structural checks on the common system-managed fields plus per-entity shape and
the two conserved-quantity invariants (deposit money, hold-slot count).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """The four system-managed fields every entity carries (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_officiant(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["styles"], list) and len(data["styles"]) > 0
    assert isinstance(data["certified_jurisdictions"], list) and len(data["certified_jurisdictions"]) > 0
    assert isinstance(data["active_hold_count"], int) and data["active_hold_count"] >= 0
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["published_review_count"], int) and data["published_review_count"] >= 0
    # displayed_rating / internal_rating are numbers or null
    for f in ("displayed_rating", "internal_rating"):
        assert data[f] is None or isinstance(data[f], (int, float)), f"{f} must be number or null"


def assert_couple(data: dict):
    _assert_common(data)
    assert isinstance(data["partner_one_name"], str) and data["partner_one_name"]
    assert isinstance(data["partner_two_name"], str) and data["partner_two_name"]
    assert isinstance(data["paid_total_cents"], int) and data["paid_total_cents"] >= 0
    assert isinstance(data["refund_credit_cents"], int) and data["refund_credit_cents"] >= 0


def assert_package(data: dict):
    _assert_common(data)
    assert data["tier"] in ("ESSENTIAL", "CLASSIC", "PREMIUM")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert 0 < data["deposit_pct"] <= 1


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["jurisdiction"], str) and len(data["jurisdiction"]) == 2


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INQUIRY", "HOLD", "CONFIRMED", "BACKUP_PENDING",
        "BACKUP_CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED",
    )
    for f in (
        "quoted_subtotal_cents", "quoted_travel_cents", "quoted_rush_cents",
        "quoted_interfaith_cents", "quoted_addons_cents", "quoted_gratuity_cents",
        "quoted_total_cents", "deposit_due_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_date_hold(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED", "EXPIRED")
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_ceremony_script(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "CHANGES_REQUESTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["vow_format"] in ("TRADITIONAL", "PERSONAL", "MIXED")


def assert_rehearsal(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_marriage_license(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "NOT_FILED", "FILED", "SIGNED", "RECORDED", "REJECTED", "VOIDED", "EXPIRED",
    )
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_review(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "PUBLISHED", "REMOVED")
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5


def assert_deposit_conserved(data: dict):
    """PRD Section 3.8: forfeit_retained_cents is the captured deposit minus the
    refund, so the two always sum back to the captured deposit."""
    assert (
        data["deposit_captured_cents"]
        == data["refund_issued_cents"] + data["forfeit_retained_cents"]
    ), (
        "deposit money must be conserved: "
        f"captured={data['deposit_captured_cents']} != "
        f"refund={data['refund_issued_cents']} + forfeit={data['forfeit_retained_cents']}"
    )
