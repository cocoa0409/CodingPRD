"""Chairs, shifts, and their scheduling geometry (PRD §3.3, §3.4).

Covers half-open appointment overlap vs closed-buffer shift overlap, the shift
OCC stale-version guard, and shift cancellation preconditions.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_shop_with_barber_chair_shift,
    set_clock,
    create_shop,
    create_active_barber,
    create_chair,
    shop_version,
    book_appointment,
    create_appointment_payload,
    create_shift_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_appointment_touching_endpoint_allowed_half_open(api):
    """PRD §3.4: "here the overlap test is half-open, so two slots that merely
    touch at an endpoint — one ending exactly when the next begins — do not
    conflict, while any true overlap is refused with `ERR_CHAIR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/appointment_chair_overlap_half_open
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Overlap Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")  # A: [10:00, 10:30)
    # Touching at 10:30 == A.end -> allowed.
    touch = validate_success(
        api.create_appointment(
            create_appointment_payload(
                ctx["shop"]["id"], ctx["customer"]["id"], ctx["barber"]["id"],
                ctx["chair"]["id"], ctx["service"]["id"], "2026-06-10T10:30:00Z"),
            RECEPTION,
        ),
        201,
    )
    assert touch["status"] == "BOOKED", touch


def test_appointment_true_overlap_rejected(api):
    """PRD §3.4: "any true overlap is refused with `ERR_CHAIR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/appointment_chair_overlap_half_open
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Overlap Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")  # A: [10:00, 10:30)
    # 10:15 falls inside A's slot -> true overlap.
    res = api.create_appointment(
        create_appointment_payload(
            ctx["shop"]["id"], ctx["customer"]["id"], ctx["barber"]["id"],
            ctx["chair"]["id"], ctx["service"]["id"], "2026-06-10T10:15:00Z"),
        RECEPTION,
    )
    validate_error(res, "ERR_CHAIR_DOUBLE_BOOKED")


def test_shift_closed_buffer_touching_rejected(api):
    """PRD §3.3: "Back-to-back shifts that merely touch — a gap of exactly zero —
    are therefore rejected, since the buffer is closed rather than half-open. A
    violation yields `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/shift_chair_closed_buffer_overlap
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="Buffer Shop", tax_rate_pct=0, late_grace_minutes=10)
    barber = create_active_barber(shop["id"])
    chair = create_chair(shop["id"])
    v1 = shop_version(shop["id"])
    get_success_data(api.create_shift(
        create_shift_payload(shop["id"], barber["id"], chair["id"],
                             "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z", v1), OWNER))
    v2 = shop_version(shop["id"])
    # Back-to-back at 12:00 (gap 0 < grace 10m) -> rejected.
    res = api.create_shift(
        create_shift_payload(shop["id"], barber["id"], chair["id"],
                             "2026-06-10T12:00:00Z", "2026-06-10T15:00:00Z", v2), OWNER)
    validate_error(res, "ERR_SHIFT_OVERLAP")


def test_shift_with_sufficient_buffer_allowed(api):
    """PRD §3.3: "the system requires a closed buffer of at least
    `late_grace_minutes` between them, meaning the earlier shift's `end_utc` plus
    the grace window must be no later than the later shift's `start_utc`."

    Design: Difficulty/resource_temporal_overlap/shift_chair_closed_buffer_overlap
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="Buffer Shop", tax_rate_pct=0, late_grace_minutes=10)
    barber = create_active_barber(shop["id"])
    chair = create_chair(shop["id"])
    v1 = shop_version(shop["id"])
    get_success_data(api.create_shift(
        create_shift_payload(shop["id"], barber["id"], chair["id"],
                             "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z", v1), OWNER))
    v2 = shop_version(shop["id"])
    # Gap exactly 10m: 12:00 + 10m == 12:10 == next start -> allowed.
    ok = validate_success(
        api.create_shift(
            create_shift_payload(shop["id"], barber["id"], chair["id"],
                                 "2026-06-10T12:10:00Z", "2026-06-10T15:00:00Z", v2), OWNER),
        201,
    )
    assert ok["status"] == "SCHEDULED", ok


def test_shift_create_stale_shop_version_rejected(api):
    """PRD §2.7: "If `expected_shop_version` does not equal the shop's current
    `version` — for example because another writer reopened the shop or scheduled
    a shift that bumped the shop in the interim — the create is rejected with
    `ERR_STALE_SHOP_VERSION` at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shop_version_on_shift_create
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="S", tax_rate_pct=0)
    barber = create_active_barber(shop["id"])
    chair = create_chair(shop["id"])
    stale_v = shop_version(shop["id"])
    # First shift bumps Shop.version, making stale_v stale.
    get_success_data(api.create_shift(
        create_shift_payload(shop["id"], barber["id"], chair["id"],
                             "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z", stale_v), OWNER))
    res = api.create_shift(
        create_shift_payload(shop["id"], barber["id"], chair["id"],
                             "2026-06-10T13:00:00Z", "2026-06-10T16:00:00Z", stale_v), OWNER)
    validate_error(res, "ERR_STALE_SHOP_VERSION")


def test_cancel_shift_with_booked_appointment_rejected(api):
    """PRD §3.3: "The cancellation is refused if any `BOOKED` or `CHECKED_IN`
    appointment still falls within that shift's window on the same chair, in which
    case the system returns `ERR_SHIFT_HAS_APPOINTMENTS`".

    Design: Corner/state_machines/cancel_shift_with_booked_appointment_returns_shift_has_appointments
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    res = api.cancel_shift(ctx["shift"]["id"], OWNER)
    validate_error(res, "ERR_SHIFT_HAS_APPOINTMENTS")


def test_get_shift_nonexistent_returns_not_found(api):
    """PRD §2.8: "returning that identifier's specific not-found error —
    `ERR_SHOP_NOT_FOUND`, `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or
    `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/errors/get_shift_nonexistent_returns_shift_not_found
    """
    res = api.get_shift(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_SHIFT_NOT_FOUND")
