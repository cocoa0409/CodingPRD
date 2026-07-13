"""Artist production windows (half-open overlap, capacity, count conservation),
occasion-reminder window spacing, bulk import boundary, and the gift-quantity
guard.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    build_pipeline, holder, TEST_USERS,
    new_account, new_contact, new_card, new_artist, new_order, new_gift_item,
    reserve_artist, create_order_payload, import_row,
)

STUDIO = TEST_USERS["studio_operator_headers"]


# --------------------------------------------------------------------------
# Half-open production window overlap vs adjacency
# --------------------------------------------------------------------------
def _three_orders_one_reserved(api, capacity=5):
    account = new_account()
    contact = new_contact(account["id"])
    card = new_card()
    artist = new_artist(daily_capacity=capacity)
    ah_account_id = account["id"]
    orders = [new_order(ah_account_id, contact["id"], card["id"], message_text=m) for m in ("a", "b", "c")]
    reserve_artist(orders[0]["id"], artist["id"], "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z")
    return artist, orders


def test_artist_window_true_overlap_rejected(api):
    """PRD §3.6: "the requested window must not overlap any existing `RESERVED`
    window for the same artist; because the intervals are half-open, two windows
    that merely touch at an endpoint do not conflict, but any true overlap is
    rejected with `ERR_ARTIST_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/artist_window_half_open_overlap_vs_adjacent
    """
    artist, orders = _three_orders_one_reserved(api)
    validate_error(
        api.assign_artist(orders[1]["id"], {
            "artist_id": artist["id"],
            "window_start": "2026-04-01T10:00:00Z",  # overlaps [09:00,11:00)
            "window_end": "2026-04-01T12:00:00Z",
        }, STUDIO),
        ApiErrorId.ERR_ARTIST_WINDOW_CONFLICT.value,
    )


def test_artist_window_touching_endpoint_accepted(api):
    """PRD §3.6: "because the intervals are half-open, two windows that merely
    touch at an endpoint do not conflict".

    Design: Difficulty/resource_temporal_overlap/artist_window_half_open_overlap_vs_adjacent
    """
    artist, orders = _three_orders_one_reserved(api)
    assignment = validate_success(
        api.assign_artist(orders[2]["id"], {
            "artist_id": artist["id"],
            "window_start": "2026-04-01T11:00:00Z",  # touches prior end, no overlap
            "window_end": "2026-04-01T13:00:00Z",
        }, STUDIO),
        201,
    )
    assert assignment["status"] == "RESERVED"


# --------------------------------------------------------------------------
# Reminder window spacing (closed intervals, same occasion_type)
# --------------------------------------------------------------------------
def _contact_with_birthday_reminder(api):
    account = new_account()
    contact = new_contact(account["id"])
    ah = holder(account["id"])
    validate_success(api.create_important_date(contact["id"], {
        "occasion_type": "BIRTHDAY",
        "event_date": "2026-05-10T00:00:00Z",
        "lead_days": 5,               # window 2026-05-05 .. 2026-05-10
        "recurrence": "NONE",
    }, ah), 201)
    return contact, ah


def test_same_type_reminder_within_buffer_rejected(api):
    """PRD §3.2: "requires it to sit at least two days clear of the reminder
    window of every existing `ACTIVE` important date of the same `occasion_type`
    on the same contact. Windows that touch, overlap, or fall within that two-day
    buffer conflict, and the create is rejected with
    `ERR_REMINDER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/reminder_window_closed_buffer_overlap
    """
    contact, ah = _contact_with_birthday_reminder(api)
    validate_error(
        api.create_important_date(contact["id"], {
            "occasion_type": "BIRTHDAY",
            "event_date": "2026-05-12T00:00:00Z",  # window 2026-05-09 .. 2026-05-12 overlaps
            "lead_days": 3,
            "recurrence": "NONE",
        }, ah),
        ApiErrorId.ERR_REMINDER_WINDOW_OVERLAP.value,
    )


def test_different_type_reminder_overlap_accepted(api):
    """PRD §3.2: "requires it to sit at least two days clear of the reminder
    window of every existing `ACTIVE` important date of the same `occasion_type`
    on the same contact."

    Design: Difficulty/resource_temporal_overlap/reminder_window_closed_buffer_overlap
    """
    contact, ah = _contact_with_birthday_reminder(api)
    # An ANNIVERSARY reminder overlapping the BIRTHDAY window is a different
    # occasion_type, so the spacing rule does not apply.
    created = validate_success(
        api.create_important_date(contact["id"], {
            "occasion_type": "ANNIVERSARY",
            "event_date": "2026-05-12T00:00:00Z",
            "lead_days": 3,
            "recurrence": "NONE",
        }, ah),
        201,
    )
    assert created["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Artist reservation-count conservation across assign/cancel
# --------------------------------------------------------------------------
def test_artist_count_returns_to_zero_after_cancel(api):
    """PRD §3.3: "exposes a computed `reserved_assignment_count` that tracks how
    many of the artist's assignments are currently `RESERVED`; this count is
    recomputed whenever an assignment is created, released, or completed."

    Design: Difficulty/compensating_invariant/artist_capacity_conserved_across_assign_then_cancel
    """
    ctx = build_pipeline("assigned", tier="PRO")
    before = validate_success(api.get_artist(ctx["artist_id"], STUDIO), 200)
    assert before["reserved_assignment_count"] == 1
    validate_success(api.cancel_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    after = validate_success(api.get_artist(ctx["artist_id"], STUDIO), 200)
    assert after["reserved_assignment_count"] == 0, "assign(0->1) then release(1->0) conserves the count"


def test_assignment_released_on_cancel(api):
    """PRD §3.8: "If the order still holds a `RESERVED` artist assignment, that
    assignment is released — moved from `RESERVED` to `RELEASED` — and the
    artist's `reserved_assignment_count` is recomputed."

    Design: Difficulty/compensating_invariant/artist_capacity_conserved_across_assign_then_cancel
    """
    ctx = build_pipeline("assigned", tier="PRO")
    reserved = validate_success(api.get_artist_assignment(ctx["assignment_id"], STUDIO), 200)
    assert reserved["status"] == "RESERVED"
    validate_success(api.cancel_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    released = validate_success(api.get_artist_assignment(ctx["assignment_id"], STUDIO), 200)
    assert released["status"] == "RELEASED"


# --------------------------------------------------------------------------
# Bulk import empty-collection boundary
# --------------------------------------------------------------------------
def test_bulk_import_empty_rows_rejected(api):
    """PRD §3.2: "A bulk import whose `rows` array is empty is rejected with
    `ERR_EMPTY_IMPORT`."

    Design: Difficulty/boundary_precision_check/bulk_import_empty_rows_boundary
    """
    account = new_account()
    validate_error(
        api.bulk_import_contacts(account["id"], {"source": "CSV", "rows": []}, holder(account["id"])),
        ApiErrorId.ERR_EMPTY_IMPORT.value,
    )


def test_bulk_import_nonempty_rows_imports_each(api):
    """PRD §3.2: "each well-formed row becomes one `UNVERIFIED` contact, rows
    missing required address fields are skipped, and the response reports
    `imported_count`, `skipped_count`, and the created `contact_ids`."

    Design: Difficulty/boundary_precision_check/bulk_import_empty_rows_boundary
    """
    account = new_account()
    payload = {"source": "CSV", "rows": [import_row(full_name="One"), import_row(full_name="Two")]}
    data = validate_success(api.bulk_import_contacts(account["id"], payload, holder(account["id"])), 201)
    assert data["imported_count"] == 2, "each well-formed row becomes one contact"


# --------------------------------------------------------------------------
# Corner: capacity exceeded, gift-quantity guard
# --------------------------------------------------------------------------
def test_assign_artist_over_daily_capacity_rejected(api):
    """PRD §3.6: "adding the reservation must not push the artist's number of
    `RESERVED` assignments whose window starts on the same calendar date as this
    window's start above the artist's `daily_capacity`; exceeding it is rejected
    with `ERR_ARTIST_CAPACITY_EXCEEDED`."

    Design: Corner/validations/assign_artist_over_daily_capacity_returns_error
    """
    account = new_account()
    contact = new_contact(account["id"])
    card = new_card()
    artist = new_artist(daily_capacity=1)
    order_a = new_order(account["id"], contact["id"], card["id"], message_text="a")
    order_b = new_order(account["id"], contact["id"], card["id"], message_text="b")
    reserve_artist(order_a["id"], artist["id"], "2026-04-01T09:00:00Z", "2026-04-01T10:00:00Z")
    validate_error(
        api.assign_artist(order_b["id"], {
            "artist_id": artist["id"],
            "window_start": "2026-04-01T11:00:00Z",  # non-overlapping but same date
            "window_end": "2026-04-01T12:00:00Z",
        }, STUDIO),
        ApiErrorId.ERR_ARTIST_CAPACITY_EXCEEDED.value,
    )


def test_order_gift_without_quantity_rejected(api):
    """PRD §3.4: "whenever a `gift_item_id` is present the `gift_quantity` must be
    at least one, failing with `ERR_GIFT_QUANTITY_INVALID` (a bare draft with no
    gift carries a quantity of zero)."

    Design: Corner/validations/order_gift_without_quantity_returns_invalid
    """
    account = new_account()
    contact = new_contact(account["id"])
    card = new_card()
    gift = new_gift_item()
    payload = create_order_payload(account["id"], contact["id"], card["id"],
                                   gift_item_id=gift["id"], gift_quantity=0)
    validate_error(api.create_order(payload, holder(account["id"])), ApiErrorId.ERR_GIFT_QUANTITY_INVALID.value)
