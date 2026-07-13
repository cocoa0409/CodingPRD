"""Production-booking intervals, overlap, priority, and booked-days accounting."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_narrator_headers,
    create_booking_payload,
    onboard_author, onboard_narrator, new_title,
)


def _author_narrator_title(api):
    author = onboard_author(api)
    narrator = onboard_narrator(api)
    title = new_title(api, author["id"])
    return narrator, title


def _book(api, narrator_id, title_id, start_date, end_date):
    return api.create_booking(create_booking_payload(title_id, start_date, end_date), make_narrator_headers(narrator_id))


def test_adjacent_booking_allowed(api):
    """PRD §3.4: "two bookings that merely touch at an endpoint — where one's
    `end_date` equals the next one's `start_date` — do not conflict; only a true
    interior overlap is forbidden."

    Design: Difficulty/resource_temporal_overlap/booking_halfopen_adjacency_allowed_overlap_rejected
    """
    narrator, title = _author_narrator_title(api)
    validate_success(_book(api, narrator["id"], title["id"], "2026-04-01", "2026-04-10"), 201)
    adj = validate_success(_book(api, narrator["id"], title["id"], "2026-04-10", "2026-04-15"), 201)
    assert adj["status"] == "ACTIVE"


def test_interior_overlap_booking_rejected(api):
    """PRD §3.4: "A new `ACTIVE` booking that interior-overlaps an existing
    `ACTIVE` booking for the same narrator is rejected with `ERR_BOOKING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/booking_halfopen_adjacency_allowed_overlap_rejected
    """
    narrator, title = _author_narrator_title(api)
    validate_success(_book(api, narrator["id"], title["id"], "2026-04-01", "2026-04-10"), 201)
    resp = _book(api, narrator["id"], title["id"], "2026-04-09", "2026-04-12")
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP.value)


def test_invalid_range_masks_overlap(api):
    """PRD §2.9: the validation order places "(10) date, window, and quantity
    validity (`ERR_INVALID_DATE_RANGE`, ...)" before "(11) temporal overlap for
    bookings and listing gaps (`ERR_BOOKING_OVERLAP`, ...)"; "An earlier check
    always masks a later one".
    PRD §3.4: "a booking whose `start_date` is not strictly before its `end_date`
    is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Difficulty/priority_pair_validation_conflict/booking_range_beats_overlap
    """
    narrator, title = _author_narrator_title(api)
    validate_success(_book(api, narrator["id"], title["id"], "2026-04-01", "2026-04-10"), 201)
    # start 2026-04-05 >= end 2026-04-03 (bad range) whose span also overlaps.
    resp = _book(api, narrator["id"], title["id"], "2026-04-05", "2026-04-03")
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_overlap_surfaces_when_range_is_valid(api):
    """PRD §2.9: "An earlier check always masks a later one" — with a valid date
    range the priority-11 overlap check is what surfaces.
    PRD §3.4: "A new `ACTIVE` booking that interior-overlaps an existing `ACTIVE`
    booking for the same narrator is rejected with `ERR_BOOKING_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/booking_range_beats_overlap
    """
    narrator, title = _author_narrator_title(api)
    validate_success(_book(api, narrator["id"], title["id"], "2026-04-01", "2026-04-10"), 201)
    resp = _book(api, narrator["id"], title["id"], "2026-04-05", "2026-04-08")
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP.value)


def test_active_booked_days_reflects_created_booking(api):
    """PRD §3.4: "The narrator's `active_booked_days` is the sum, over that
    narrator's `ACTIVE` bookings only, of each booking's whole-day span — the end
    date minus the start date, which because the end is exclusive equals the
    number of days in the `[start_date, end_date)` interval."

    Design: Difficulty/compensating_invariant/booking_days_create_then_cancel_conserves_days
    """
    narrator, title = _author_narrator_title(api)
    validate_success(_book(api, narrator["id"], title["id"], "2026-04-01", "2026-04-10"), 201)
    reread = validate_success(api.get_narrator(narrator["id"], make_narrator_headers(narrator["id"])), 200)
    assert reread["active_booked_days"] == 9


def test_booking_cancel_releases_days(api):
    """PRD §3.4: "A narrator cancels an `ACTIVE` booking it owns, moving it
    `ACTIVE → CANCELLED`, releasing its days back (the `active_booked_days` total
    is recomputed downward) and bumping the booking's version."

    Design: Difficulty/compensating_invariant/booking_days_create_then_cancel_conserves_days
    """
    narrator, title = _author_narrator_title(api)
    booking = validate_success(_book(api, narrator["id"], title["id"], "2026-04-01", "2026-04-10"), 201)
    cancelled = validate_success(api.cancel_booking(booking["id"], make_narrator_headers(narrator["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    reread = validate_success(api.get_narrator(narrator["id"], make_narrator_headers(narrator["id"])), 200)
    assert reread["active_booked_days"] == 0
