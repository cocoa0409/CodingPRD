"""Two deliberately incompatible interval conventions.

A collection centre's slots are half-open minute-precision instant intervals
widened by a ninety-minute turnaround buffer and counted against an aggregate
capacity, so a slot that begins exactly at a buffered interval's end instant is
admitted.  A donor's calendar windows are closed inclusive whole-day intervals
with a capacity of one and no buffer, so a single shared calendar day is a
conflict while a window ending the day before another begins is not.
"""
from test_helpers import (
    ApiErrorId,
    assertions as A,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared preconditions
# ---------------------------------------------------------------------------

def _two_cleared_cases_at_one_center():
    """Two independent workup cases competing for one capacity-1 centre.

    A single domestic registry holds two donors and a single collection centre
    with `concurrent_collection_capacity` 1.  Each donor is engaged for its own
    patient, so two separate workup cases reach `CLEARED` with the `PBSC` method
    and a conditioning start date of 2026-10-05, opening the collection dates
    2026-10-11 through 2026-10-13 for both.
    """
    ctx_a = fixtures.setup_primary_candidate(num_donors=2)
    fixtures.engage_candidate(ctx_a)
    fixtures.advance_to_workup_open(ctx_a)

    # The first donor is now tied up in a WORKUP_OPEN candidate row, so the
    # second patient's search materialises the second donor alone.
    patient_b = fixtures.create_patient()
    search_b = fixtures.open_search(patient_b["id"])
    candidates_b = fixtures.list_candidates(search_b["id"])
    assert len(candidates_b) == 1, (
        f"Setup failed: expected the second search to materialise exactly the "
        f"one remaining donor, got {len(candidates_b)} candidates"
    )

    ctx_b = dict(ctx_a)
    ctx_b.update(
        {
            "patient": patient_b,
            "patient_id": patient_b["id"],
            "patient_version": patient_b["version"],
            "search": search_b,
            "search_id": search_b["id"],
            "candidates": candidates_b,
            "candidate": candidates_b[0],
            "candidate_id": candidates_b[0]["id"],
            "donor_id": candidates_b[0]["donor_id"],
        }
    )
    fixtures.engage_candidate(ctx_b)
    fixtures.advance_to_workup_open(ctx_b)

    for ctx in (ctx_a, ctx_b):
        fixtures.advance_to_cleared(ctx)
        fixtures.advance_to_method_set(ctx, method="PBSC")
        fixtures.advance_to_conditioning_scheduled(ctx)
    return ctx_a, ctx_b


def _booking_payload_for(ctx, start_at):
    """A booking payload quoting the case's freshly read `version`."""
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    return f.create_booking_payload(
        case["id"], ctx["center_id"], start_at, case["version"]
    )


# ---------------------------------------------------------------------------
# Collection-centre slots: half-open minute intervals plus a 90-minute buffer
# ---------------------------------------------------------------------------

def test_slot_inside_the_buffered_interval_is_refused_at_capacity_one(api):
    """PRD §3.7: "Every existing booking of the same centre whose `status` is `HELD`, `CONFIRMED` or `COMPLETED` is expanded into a buffered half-open interval running from 90 minutes before its `start_at` up to but not including 90 minutes after its `end_at` — an hour and a half of cleaning and turnaround at each end."
    PRD §3.7: "The requested slot overlaps such a buffered interval when the requested start is strictly before the buffered end and the buffered start is strictly before the requested end."
    PRD §3.7: "Count the overlapping bookings; if that count has reached or passed the centre's `concurrent_collection_capacity`, the request is refused with `ERR_CENTER_SLOT_CONFLICT`, and only when the count is strictly below capacity does the booking succeed."
    PRD §3.7: "From the method it derives `duration_minutes` — 300 minutes for `PBSC`, 240 minutes for `MARROW` — then `end_at` as `start_at` advanced by that many minutes, and `collection_date` as the UTC calendar date of `start_at`."
    PRD §3.7: "Creating it adds its `duration_minutes` to the centre's `committed_slot_minutes`, moves the case `METHOD_SET → BOOKED` on the logistics dimension, and increments the case's `version` by one."

    Design: Difficulty/resource_temporal_overlap/center_slot_overlap_uses_buffered_half_open_minute_intervals
    """
    ctx_a, ctx_b = _two_cleared_cases_at_one_center()

    booking_a = fixtures.advance_to_booking_held(ctx_a, start_at="2026-10-11T08:00:00Z")
    assert booking_a["duration_minutes"] == 300, (
        f"a PBSC slot lasts 300 minutes, got {booking_a['duration_minutes']}"
    )
    A.assert_same_instant(
        booking_a["end_at"], "2026-10-11T13:00:00Z",
        "08:00 advanced by 300 minutes ends at 2026-10-11T13:00",
    )
    center = fixtures.read_center(ctx_a["center_id"])
    assert center["committed_slot_minutes"] == 300, (
        f"only case A holds a slot, so the centre commits 300 minutes, got "
        f"{center['committed_slot_minutes']}"
    )

    # 14:00 still sits inside the buffered interval [06:30, 14:30).
    case_b_before = fixtures.read_workup_case(
        ctx_b["workup_case_id"], ctx_b["coordinator_headers"]
    )
    resp = api.create_collection_booking(
        _booking_payload_for(ctx_b, "2026-10-11T14:00:00Z"),
        ctx_b["center_ops_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_SLOT_CONFLICT.value)

    bookings, _meta = validate_paginated(
        api.list_collection_bookings(
            ctx_b["center_ops_headers"],
            params={"workup_case_id": ctx_b["workup_case_id"], "limit": 100},
        )
    )
    assert bookings == [], (
        f"the refused request must create no booking row, found {bookings}"
    )
    center = fixtures.read_center(ctx_a["center_id"])
    assert center["committed_slot_minutes"] == 300, (
        f"a refused booking commits no minutes, got {center['committed_slot_minutes']}"
    )
    case_b_after = fixtures.read_workup_case(
        ctx_b["workup_case_id"], ctx_b["coordinator_headers"]
    )
    assert case_b_after["logistics_status"] == "METHOD_SET", (
        f"case B never reached BOOKED, so its logistics dimension stays "
        f"METHOD_SET, got {case_b_after['logistics_status']}"
    )
    assert case_b_after["version"] == case_b_before["version"], (
        f"a refused booking increments no case version: expected "
        f"{case_b_before['version']}, got {case_b_after['version']}"
    )


def test_slot_starting_exactly_at_the_buffer_edge_is_admitted(api):
    """PRD §2.6: "Collection-centre slot intervals are half-open minute-precision instant intervals: a slot occupies the time from its start instant up to but not including its end instant, so a slot beginning exactly at the instant another interval ends does not overlap it."
    PRD §3.7: "Because the intervals are half-open, a slot beginning exactly at a buffered interval's end instant does not overlap it and is admitted."
    PRD §2.10: "`CollectionCenter.committed_slot_minutes` is the sum of `duration_minutes` over that centre's bookings whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/center_slot_overlap_uses_buffered_half_open_minute_intervals
    """
    ctx_a, ctx_b = _two_cleared_cases_at_one_center()
    fixtures.advance_to_booking_held(ctx_a, start_at="2026-10-11T08:00:00Z")

    # The existing 08:00-13:00 slot buffers out to [06:30, 14:30); a request
    # starting exactly at 14:30 touches that edge without overlapping it.
    resp = api.create_collection_booking(
        _booking_payload_for(ctx_b, "2026-10-11T14:30:00Z"),
        ctx_b["center_ops_headers"],
    )
    booking_b = validate_success(resp, 201)
    A.assert_same_instant(
        booking_b["start_at"], "2026-10-11T14:30:00Z",
        "start_at must be stored as requested",
    )
    A.assert_same_instant(
        booking_b["end_at"], "2026-10-11T19:30:00Z",
        "14:30 advanced by 300 minutes ends at 2026-10-11T19:30",
    )
    assert booking_b["status"] == "HELD", (
        f"a new booking opens in HELD, got {booking_b['status']}"
    )
    assert booking_b["collection_date"] == "2026-10-11", (
        f"collection_date is the UTC calendar date of start_at, got "
        f"{booking_b['collection_date']}"
    )

    center = fixtures.read_center(ctx_a["center_id"])
    assert center["committed_slot_minutes"] == 600, (
        f"two HELD 300-minute slots aggregate to 600 committed minutes, got "
        f"{center['committed_slot_minutes']}"
    )
    for label, ctx in (("A", ctx_a), ("B", ctx_b)):
        case = fixtures.read_workup_case(
            ctx["workup_case_id"], ctx["coordinator_headers"]
        )
        assert case["logistics_status"] == "BOOKED", (
            f"case {label} holds a slot, so its logistics dimension is BOOKED, "
            f"got {case['logistics_status']}"
        )


# ---------------------------------------------------------------------------
# Donor calendars: closed inclusive whole-day intervals, adjacency legal
# ---------------------------------------------------------------------------

def _held_booking_with_adjacent_personal_window():
    """A held 2026-10-11 PBSC slot plus a manual PERSONAL window 10-13..10-20.

    The slot's derived collection window will span 2026-10-07 through
    2026-10-12, ending exactly one day before the manual window begins.
    """
    ctx = fixtures.setup_pipeline("booking_held")
    personal = fixtures.block_calendar(ctx, "2026-10-13", "2026-10-20", "PERSONAL")
    return ctx, personal


def test_manual_window_day_count_is_the_closed_inclusive_span(api):
    """PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."
    PRD §2.6: "Donor calendar windows, by contrast, are closed inclusive whole-day intervals: a window spanning two dates blocks both of those dates and every date between them, and two windows conflict as soon as they share a single calendar day."
    PRD §3.7: "Confirmation stamps `confirmed_at` from the logical clock and creates the donor's collection window: an `ACTIVE` calendar window with `reason` `COLLECTION_WINDOW` and `source_booking_id` pointing back at this booking, spanning from a number of days before `collection_date` through a number of days after it."
    PRD §3.7: "Those offsets are method-specific and asymmetric, reflecting how the two procedures actually burden a volunteer: a `PBSC` collection blocks the four days before the collection date and the one day after it, because mobilisation injections precede apheresis, while a `MARROW` harvest blocks the one day before and the six days after, because recovery from general anaesthesia and aspiration takes far longer."
    PRD §2.6: "Adjacency is legal on the calendar: a window ending the day before another window begins is not a conflict."

    Design: Difficulty/resource_temporal_overlap/donor_calendar_overlap_uses_closed_whole_day_intervals_with_legal_adjacency
    """
    ctx, personal = _held_booking_with_adjacent_personal_window()
    assert personal["day_count"] == 8, (
        f"2026-10-13 through 2026-10-20 inclusive spans 8 days, got "
        f"{personal['day_count']}"
    )
    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 8, (
        f"the manual window alone blocks 8 days, got {donor['blocked_day_count']}"
    )

    # The derived collection window ends 2026-10-12, one day before the manual
    # window begins, so adjacency lets the confirmation through.
    booking = validate_success(
        api.confirm_collection_booking(ctx["booking_id"], ctx["center_ops_headers"])
    )
    assert booking["status"] == "CONFIRMED", (
        f"a confirmed slot leaves HELD, got {booking['status']}"
    )

    windows = fixtures.find_booking_windows(ctx["booking_id"])
    assert len(windows) == 1, (
        f"confirmation creates exactly one collection window, got {len(windows)}"
    )
    window = windows[0]
    assert window["reason"] == "COLLECTION_WINDOW", (
        f"the derived window's reason is COLLECTION_WINDOW, got {window['reason']}"
    )
    assert window["status"] == "ACTIVE", (
        f"the derived window opens ACTIVE, got {window['status']}"
    )
    assert window["date_from"] == "2026-10-07", (
        f"a PBSC window opens four days before 2026-10-11, got {window['date_from']}"
    )
    assert window["date_to"] == "2026-10-12", (
        f"a PBSC window closes one day after 2026-10-11, got {window['date_to']}"
    )
    assert window["day_count"] == 6, (
        f"2026-10-07 through 2026-10-12 inclusive spans 6 days, got "
        f"{window['day_count']}"
    )
    assert window["source_booking_id"] == ctx["booking_id"], (
        f"source_booking_id points back at the booking that generated the "
        f"window, got {window['source_booking_id']}"
    )

    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 14, (
        f"8 manual days plus 6 collection days block 14 days in total, got "
        f"{donor['blocked_day_count']}"
    )


def test_window_sharing_a_single_day_with_the_collection_window_is_refused(api):
    """PRD §3.2: "Donor calendars have a capacity of exactly one, with no buffer: a requested window that shares even a single calendar day with any of the donor's other `ACTIVE` windows is rejected with `ERR_DONOR_CALENDAR_CONFLICT`."
    PRD §3.2: "Two windows conflict precisely when the first begins on or before the second ends and the second begins on or before the first ends."
    PRD §2.10: "`DonorProfile.blocked_day_count` is the sum of `day_count` over that donor's calendar windows whose `status` is `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/donor_calendar_overlap_uses_closed_whole_day_intervals_with_legal_adjacency
    """
    ctx, _personal = _held_booking_with_adjacent_personal_window()
    fixtures.advance_to_booking_confirmed(ctx)

    before = fixtures.find_windows(ctx["donor_id"])
    assert len(before) == 2, (
        f"the donor carries the manual window and the derived collection "
        f"window, got {len(before)}"
    )

    # 2026-10-12 is the collection window's last day and 2026-10-13..14 fall
    # inside the manual window: a single shared day is already a conflict.
    resp = api.create_unavailability_window(
        ctx["donor_id"],
        f.create_unavailability_window_payload(
            "2026-10-12", "2026-10-14", "MEDICAL_HOLD"
        ),
        ctx["liaison_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_CALENDAR_CONFLICT.value)

    after = fixtures.find_windows(ctx["donor_id"])
    assert len(after) == len(before), (
        f"the refused window must create no row: had {len(before)} windows, "
        f"now {len(after)}"
    )
    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 14, (
        f"a refused window blocks no days, so the count stays at 14, got "
        f"{donor['blocked_day_count']}"
    )


def test_window_starting_the_day_after_an_active_window_ends_is_admitted(api):
    """PRD §3.2: "Adjacency remains legal: a window that ends on the day immediately before another begins is not a conflict."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."
    PRD §3.2: "A new window starts with `status` `ACTIVE` and `released_at` null."

    Design: Difficulty/resource_temporal_overlap/donor_calendar_overlap_uses_closed_whole_day_intervals_with_legal_adjacency
    """
    ctx, _personal = _held_booking_with_adjacent_personal_window()
    fixtures.advance_to_booking_confirmed(ctx)

    # The manual PERSONAL window's last day is 2026-10-20, so a window opening
    # on 2026-10-21 is merely adjacent to it.
    resp = api.create_unavailability_window(
        ctx["donor_id"],
        f.create_unavailability_window_payload(
            "2026-10-21", "2026-10-23", "MEDICAL_HOLD"
        ),
        ctx["liaison_headers"],
    )
    window = validate_success(resp, 201)
    assert window["date_from"] == "2026-10-21", (
        f"date_from must be stored as requested, got {window['date_from']}"
    )
    assert window["date_to"] == "2026-10-23", (
        f"date_to must be stored as requested, got {window['date_to']}"
    )
    assert window["day_count"] == 3, (
        f"2026-10-21 through 2026-10-23 inclusive spans 3 days, got "
        f"{window['day_count']}"
    )
    assert window["status"] == "ACTIVE", (
        f"a new window opens ACTIVE, got {window['status']}"
    )
    assert window["released_at"] is None, (
        f"released_at stays null on a new window, got {window['released_at']}"
    )

    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 17, (
        f"8 manual days plus 6 collection days plus 3 new days block 17 days, "
        f"got {donor['blocked_day_count']}"
    )
