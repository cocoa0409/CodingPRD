"""Exhibitor booth bookings: estimated vs actual charge, buffered overlap,
charge conservation, and full-check-in equality.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_convention,
    create_booth,
    create_exhibitor,
    create_booth_booking,
    check_in_booking,
    release_booking,
    get_exhibitor,
    make_exhibitor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_booth_estimated_vs_actual_diverges(api):
    """PRD §3.7: "The forward-looking `estimated_booth_cents` is the sum, over every booking of that exhibitor whose `status` is `RESERVED` or `CHECKED_IN`, of the booking's booth zone daily rate multiplied by the booking's `requested_days`. The chronological `actual_booth_cents` is the sum, over only those bookings whose `status` is `CHECKED_IN`, of the booth zone daily rate multiplied by the booking's `occupied_days`."

    Design: Difficulty/dual_variant_calc/booth_estimated_vs_actual_diverges_on_exhibitor
    """
    conv = create_convention(event_end_utc="2026-09-03T23:59:59Z")
    booth_s = create_booth(conv["id"], booth_code="S1", zone="STANDARD", setup_buffer_hours=0)
    booth_e = create_booth(conv["id"], booth_code="E1", zone="ENDCAP", setup_buffer_hours=0)
    exh = create_exhibitor(conv["id"])
    create_booth_booking(booth_s["id"], exh["id"],
                         occupy_start_utc="2026-09-01T00:00:00Z",
                         occupy_end_utc="2026-09-02T00:00:00Z", requested_days=2)
    bk_e = create_booth_booking(booth_e["id"], exh["id"],
                                occupy_start_utc="2026-09-01T00:00:00Z",
                                occupy_end_utc="2026-09-02T00:00:00Z", requested_days=1)
    set_clock("2026-08-31T00:00:00Z")
    check_in_booking(bk_e["id"], exh["id"])

    after = get_exhibitor(exh["id"])
    # STANDARD(50000)*2 + ENDCAP(200000)*1 = 300000 estimated; only checked-in ENDCAP counts actual.
    assert after["estimated_booth_cents"] == 300000
    assert after["actual_booth_cents"] == 200000
    assert after["actual_booth_cents"] < after["estimated_booth_cents"]


def test_booth_buffered_closed_interval_overlap_rejected(api):
    """PRD §3.7: "the requested window, expanded by the booth's `setup_buffer_hours` on each side (from `occupy_start_utc` minus the buffer to `occupy_end_utc` plus the buffer), must not overlap the similarly buffer-expanded window of any other `RESERVED` or `CHECKED_IN` booking on the same booth; these are treated as closed intervals, so any shared instant counts as overlap, and a conflict is rejected with `ERR_BOOTH_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/booth_buffered_closed_interval_overlap_rejected
    """
    conv = create_convention(event_end_utc="2026-09-05T23:59:59Z")
    booth = create_booth(conv["id"], booth_code="B1", zone="STANDARD", setup_buffer_hours=12)
    exh = create_exhibitor(conv["id"])
    create_booth_booking(booth["id"], exh["id"],
                         occupy_start_utc="2026-09-01T00:00:00Z",
                         occupy_end_utc="2026-09-01T23:59:00Z", requested_days=1)

    # Raw intervals do not overlap, but 12h-buffer-expanded closed intervals touch.
    headers = make_exhibitor_headers(exh["id"])
    res = api.create_booth_booking(
        {"booth_id": booth["id"], "exhibitor_id": exh["id"],
         "occupy_start_utc": "2026-09-02T12:00:00Z",
         "occupy_end_utc": "2026-09-03T12:00:00Z", "requested_days": 1}, headers)
    validate_error(res, "ERR_BOOTH_TIME_CONFLICT", expected_status=409)


def test_estimated_booth_cents_conserved_across_book_then_release(api):
    """PRD §3.7: "Creating a booking recomputes the exhibitor's `estimated_booth_cents`."
    PRD §3.7: "Releasing recomputes the exhibitor's `estimated_booth_cents` with this booking excluded and frees the booth interval so a later booking no longer overlaps it".

    Design: Difficulty/compensating_invariant/estimated_booth_cents_conserved_across_book_then_release
    """
    conv = create_convention(event_end_utc="2026-09-05T23:59:59Z")
    booth = create_booth(conv["id"], booth_code="P1", zone="PREMIUM", setup_buffer_hours=0)
    exh = create_exhibitor(conv["id"])
    bk = create_booth_booking(booth["id"], exh["id"],
                              occupy_start_utc="2026-09-01T00:00:00Z",
                              occupy_end_utc="2026-09-03T00:00:00Z", requested_days=3)

    after_book = get_exhibitor(exh["id"])
    assert after_book["estimated_booth_cents"] == 360000  # PREMIUM(120000) * 3

    release_booking(bk["id"], exh["id"])
    after_release = get_exhibitor(exh["id"])
    assert after_release["estimated_booth_cents"] == 0


def test_booth_actual_equals_estimated_on_full_checkin(api):
    """PRD §3.7: "Because `estimated_booth_cents` bills the full `requested_days` of every still-active booking while `actual_booth_cents` bills only the `occupied_days` of checked-in bookings, an exhibitor with reserved-but-not-yet-checked-in bookings will have an actual charge below its estimate."
    PRD §3.7: "Check-in sets `occupied_days` equal to `requested_days`, recomputes the exhibitor's `actual_booth_cents`, and increments the booking's `version` by one."

    Design: Corner/calculations/booth_actual_equals_estimated_on_full_checkin
    """
    conv = create_convention(event_end_utc="2026-09-05T23:59:59Z")
    booth = create_booth(conv["id"], booth_code="E9", zone="ENDCAP", setup_buffer_hours=0)
    exh = create_exhibitor(conv["id"])
    bk = create_booth_booking(booth["id"], exh["id"],
                              occupy_start_utc="2026-09-01T00:00:00Z",
                              occupy_end_utc="2026-09-02T00:00:00Z", requested_days=1)
    set_clock("2026-08-31T00:00:00Z")
    check_in_booking(bk["id"], exh["id"])

    after = get_exhibitor(exh["id"])
    assert after["estimated_booth_cents"] == 200000
    assert after["actual_booth_cents"] == 200000
