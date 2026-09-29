"""Studio bookings, on-sale cadence and the digital / collected release windows."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_date_equals,
    assert_field_sequence,
    assert_ids_in_order,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


def _offer_response(title_id: str, creator_id: str, start: str, end: str):
    """Offer a `SCRIPT` booking window against the title's live `version`."""
    return api_client.create_creative_assignment(
        title_id,
        factories.assignment_payload(
            creator_id,
            fixtures.title_version(title_id),
            craft="SCRIPT",
            royalty_share_bps=500,
            booking_start_date=start,
            booking_end_date=end,
        ),
        TEST_USERS["editor_in_chief_headers"],
    )


def _collected_window_response(issue_id: str, release_date: str):
    return api_client.create_release_window(
        issue_id,
        factories.release_window_payload(
            "COLLECTED", release_date, expected_net_receipts_cents=90000
        ),
        TEST_USERS["sales_director_headers"],
    )


def _digital_window_response(issue_id: str, release_date: str):
    return api_client.create_release_window(
        issue_id,
        factories.release_window_payload(
            "DIGITAL", release_date, expected_net_receipts_cents=56000
        ),
        TEST_USERS["sales_director_headers"],
    )


def _title_with_two_issues() -> dict:
    """A greenlit title whose issues target 2026-10-14 and 2026-12-02."""
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    first = fixtures.schedule_issue(
        title["id"], issue_number=1, target_on_sale_date="2026-10-14"
    )
    second = fixtures.schedule_issue(
        title["id"], issue_number=2, target_on_sale_date="2026-12-02"
    )
    return {"title": title, "first_issue": first, "second_issue": second}


# ─── Creator studio booking intervals ─────────────────

def test_intersecting_contained_and_straddling_studio_windows_are_all_double_booked():
    """A one-day overlap, a contained window and a straddling window are each refused.

    PRD: "A creator's studio time may not be double-sold: the new half-open interval must not intersect any existing booking interval of the same creator on an assignment whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`, and an intersection is refused with `ERR_CREATOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/creator_studio_booking_half_open_intervals_allow_adjacency_but_not_intersection
    """
    fixtures.set_clock()
    creator = fixtures.register_creator(
        full_name="Wanda Writer", crafts=["SCRIPT"], default_page_rate_cents=12000
    )
    title = fixtures.pitch_and_greenlight_title()
    booked = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        royalty_share_bps=500,
        booking_start_date="2026-08-01",
        booking_end_date="2026-09-01",
    )
    version_after_booking = fixtures.title_version(title["id"])

    # One day of intersection, a fully contained window and a straddling window.
    for start, end in (
        ("2026-08-31", "2026-10-01"),
        ("2026-08-10", "2026-08-20"),
        ("2026-07-01", "2026-12-01"),
    ):
        response = api_client.create_creative_assignment(
            title["id"],
            factories.assignment_payload(
                creator["id"],
                version_after_booking,
                craft="SCRIPT",
                royalty_share_bps=500,
                booking_start_date=start,
                booking_end_date=end,
            ),
            TEST_USERS["editor_in_chief_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CREATOR_DOUBLE_BOOKED.value)
        # A refused attempt leaves the title alone, so the same version stays valid.
        assert fixtures.title_version(title["id"]) == version_after_booking

    rows, meta = validate_paginated(
        api_client.list_creator_assignments(
            creator["id"], TEST_USERS["editor_in_chief_headers"]
        )
    )
    assert_ids_in_order(rows, [booked["id"]])
    assert meta["total_count"] == 1
    assert fixtures.read_creator(creator["id"])["active_assignment_count"] == 1


def test_a_booking_that_merely_touches_an_existing_window_is_accepted():
    """Half-open intervals let a new window start where an old one ends, and vice versa.

    PRD: "Because the intervals are half-open, two bookings that merely touch — the earlier one's `booking_end_date` equal to the new one's `booking_start_date` — are permitted."

    Design: Difficulty/resource_temporal_overlap/creator_studio_booking_half_open_intervals_allow_adjacency_but_not_intersection
    """
    fixtures.set_clock()
    creator = fixtures.register_creator(
        full_name="Wanda Writer", crafts=["SCRIPT"], default_page_rate_cents=12000
    )
    title = fixtures.pitch_and_greenlight_title()
    fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        royalty_share_bps=500,
        booking_start_date="2026-08-01",
        booking_end_date="2026-09-01",
    )

    after = validate_success(
        _offer_response(title["id"], creator["id"], "2026-09-01", "2026-10-01"),
        expected_status=201,
    )
    before = validate_success(
        _offer_response(title["id"], creator["id"], "2026-07-01", "2026-08-01"),
        expected_status=201,
    )

    assert_date_equals(after["booking_start_date"], "2026-09-01")
    assert_date_equals(before["booking_end_date"], "2026-08-01")
    assert after["status"] == "PROPOSED"
    assert before["status"] == "PROPOSED"
    assert fixtures.read_creator(creator["id"])["active_assignment_count"] == 3


def test_terminating_an_adjacent_booking_frees_its_studio_window_again():
    """Only live assignments block a window, so a terminated one releases its slot.

    PRD: "A creator's studio time may not be double-sold: the new half-open interval must not intersect any existing booking interval of the same creator on an assignment whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`, and an intersection is refused with `ERR_CREATOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/creator_studio_booking_half_open_intervals_allow_adjacency_but_not_intersection
    """
    fixtures.set_clock()
    creator = fixtures.register_creator(
        full_name="Wanda Writer", crafts=["SCRIPT"], default_page_rate_cents=12000
    )
    title = fixtures.pitch_and_greenlight_title()
    booked = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        royalty_share_bps=500,
        booking_start_date="2026-08-01",
        booking_end_date="2026-09-01",
    )
    adjacent = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        royalty_share_bps=500,
        booking_start_date="2026-09-01",
        booking_end_date="2026-10-01",
    )

    # While the adjacent row is PROPOSED the identical window is double-booked.
    validate_error(
        _offer_response(title["id"], creator["id"], "2026-09-01", "2026-10-01"),
        ApiErrorId.ERR_CREATOR_DOUBLE_BOOKED.value,
    )

    terminated = fixtures.terminate_assignment(adjacent["id"])
    assert terminated["status"] == "TERMINATED"

    rebooked = validate_success(
        _offer_response(title["id"], creator["id"], "2026-09-01", "2026-10-01"),
        expected_status=201,
    )
    assert_date_equals(rebooked["booking_start_date"], "2026-09-01")

    rows, meta = validate_paginated(
        api_client.list_creator_assignments(
            creator["id"], TEST_USERS["editor_in_chief_headers"]
        )
    )
    assert_ids_in_order(rows, [booked["id"], adjacent["id"], rebooked["id"]])
    assert_field_sequence(rows, "status", ["PROPOSED", "TERMINATED", "PROPOSED"])
    assert meta["total_count"] == 3
    assert fixtures.read_creator(creator["id"])["active_assignment_count"] == 2


# ─── The title's on-sale calendar slot ────────────────

def test_a_twenty_day_gap_is_refused_while_exactly_twenty_one_days_is_scheduled():
    """The cadence bound is inclusive: 20 days collides, 21 days is accepted.

    PRD: "A publisher cannot flood a single shipping week, so the slate must keep its cadence: the absolute difference in calendar days between a new issue's `target_on_sale_date` and that of any sibling issue of the same title whose commercial dimension is not `CANCELLED` must be at least twenty-one days, and a closer date is refused with `ERR_ON_SALE_CADENCE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/on_sale_slot_requires_a_symmetric_21_day_gap_in_both_directions
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    fixtures.schedule_issue(
        title["id"], issue_number=1, target_on_sale_date="2026-10-14"
    )

    response = api_client.create_issue(
        title["id"],
        factories.issue_payload(issue_number=2, target_on_sale_date="2026-11-03"),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ON_SALE_CADENCE_CONFLICT.value)

    second = validate_success(
        api_client.create_issue(
            title["id"],
            factories.issue_payload(issue_number=2, target_on_sale_date="2026-11-04"),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )
    assert_date_equals(second["target_on_sale_date"], "2026-11-04")
    assert second["issue_number"] == 2

    rows, meta = validate_paginated(
        api_client.list_title_issues(
            title["id"], TEST_USERS["managing_editor_headers"]
        )
    )
    assert meta["total_count"] == 2
    assert_field_sequence(rows, "issue_number", [1, 2])


def test_an_on_sale_date_too_soon_before_a_sibling_hits_the_same_symmetric_bound():
    """The 21-day distance is measured with an absolute difference, so it guards both sides.

    PRD: "A publisher cannot flood a single shipping week, so the slate must keep its cadence: the absolute difference in calendar days between a new issue's `target_on_sale_date` and that of any sibling issue of the same title whose commercial dimension is not `CANCELLED` must be at least twenty-one days, and a closer date is refused with `ERR_ON_SALE_CADENCE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/on_sale_slot_requires_a_symmetric_21_day_gap_in_both_directions
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    fixtures.schedule_issue(
        title["id"], issue_number=1, target_on_sale_date="2026-10-14"
    )
    fixtures.schedule_issue(
        title["id"], issue_number=2, target_on_sale_date="2026-11-04"
    )

    # 10 days after issue #1 and 11 days before issue #2: it collides on both sides.
    response = api_client.create_issue(
        title["id"],
        factories.issue_payload(issue_number=3, target_on_sale_date="2026-10-24"),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ON_SALE_CADENCE_CONFLICT.value)

    # 21 days *before* issue #1 clears the same bound, and reuses issue_number 3.
    third = validate_success(
        api_client.create_issue(
            title["id"],
            factories.issue_payload(issue_number=3, target_on_sale_date="2026-09-23"),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )
    assert_date_equals(third["target_on_sale_date"], "2026-09-23")
    assert third["issue_number"] == 3

    rows, meta = validate_paginated(
        api_client.list_title_issues(
            title["id"], TEST_USERS["managing_editor_headers"]
        )
    )
    assert meta["total_count"] == 3
    # Issue numbering is deliberately independent of the on-sale calendar.
    assert_field_sequence(rows, "issue_number", [1, 2, 3])
    for row, expected_date in zip(rows, ["2026-10-14", "2026-11-04", "2026-09-23"]):
        assert_date_equals(row["target_on_sale_date"], expected_date)


# ─── The collected edition's blackout anchor ──────────

def test_adding_a_later_issue_slides_the_collected_blackout_anchor_forward():
    """A newly scheduled issue moves the title-wide anchor and re-closes dates that were legal.

    PRD: "A `COLLECTED` window must fall strictly after ninety calendar days past the latest `target_on_sale_date` among that title's issues whose commercial dimension is not `CANCELLED`; the blackout end date itself is still inside the blackout, so only a date after it qualifies, and a violation is refused with `ERR_CANNIBALIZATION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/collected_edition_blackout_anchor_moves_when_a_later_issue_joins_the_title
    """
    state = _title_with_two_issues()
    title_id = state["title"]["id"]
    issue_id = state["second_issue"]["id"]

    # The anchor is 2026-12-02, so the blackout closes after 2027-03-02.
    validate_error(
        _collected_window_response(issue_id, "2027-02-01"),
        ApiErrorId.ERR_CANNIBALIZATION_WINDOW_CONFLICT.value,
    )
    first_window = validate_success(
        _collected_window_response(issue_id, "2027-03-10"), expected_status=201
    )
    assert_date_equals(first_window["release_date"], "2027-03-10")

    # Issue #3 lands 21 days later, moving the anchor to 2026-12-23.
    fixtures.schedule_issue(
        title_id, issue_number=3, target_on_sale_date="2026-12-23"
    )
    validate_error(
        _collected_window_response(issue_id, "2027-03-15"),
        ApiErrorId.ERR_CANNIBALIZATION_WINDOW_CONFLICT.value,
    )
    second_window = validate_success(
        _collected_window_response(issue_id, "2027-03-24"), expected_status=201
    )
    assert_date_equals(second_window["release_date"], "2027-03-24")

    rows, meta = validate_paginated(
        api_client.list_release_windows(
            issue_id, TEST_USERS["sales_director_headers"], {"channel": "COLLECTED"}
        )
    )
    # The already stored 2027-03-10 row is untouched by the anchor move.
    assert_ids_in_order(rows, [first_window["id"], second_window["id"]])
    assert meta["total_count"] == 2


def test_the_collected_blackout_anchor_is_title_wide_rather_than_issue_wide():
    """A window on the earliest issue is judged against the title's latest on-sale date.

    PRD: "A `COLLECTED` window must fall strictly after ninety calendar days past the latest `target_on_sale_date` among that title's issues whose commercial dimension is not `CANCELLED`; the blackout end date itself is still inside the blackout, so only a date after it qualifies, and a violation is refused with `ERR_CANNIBALIZATION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/collected_edition_blackout_anchor_moves_when_a_later_issue_joins_the_title
    """
    state = _title_with_two_issues()
    title_id = state["title"]["id"]
    first_issue_id = state["first_issue"]["id"]
    fixtures.schedule_issue(
        title_id, issue_number=3, target_on_sale_date="2026-12-23"
    )

    # Issue #1 targets 2026-10-14, but the anchor is issue #3's 2026-12-23.
    validate_error(
        _collected_window_response(first_issue_id, "2027-03-15"),
        ApiErrorId.ERR_CANNIBALIZATION_WINDOW_CONFLICT.value,
    )
    window = validate_success(
        _collected_window_response(first_issue_id, "2027-03-24"), expected_status=201
    )
    assert_date_equals(window["release_date"], "2027-03-24")

    rows, meta = validate_paginated(
        api_client.list_release_windows(
            first_issue_id, TEST_USERS["sales_director_headers"]
        )
    )
    assert_ids_in_order(rows, [window["id"]])
    assert meta["total_count"] == 1


# ─── Digital embargo and collected blackout boundaries ─

def test_the_digital_embargo_admits_the_thirtieth_day_and_refuses_the_day_before():
    """2026-12-31 violates the embargo on a 2026-12-02 issue while 2027-01-01 does not.

    PRD: "A `DIGITAL` window must not land earlier than thirty calendar days after the issue's `target_on_sale_date`, that is, its `release_date` must be on or after that date plus thirty days, and an earlier date is refused with `ERR_DIGITAL_EMBARGO_VIOLATION` at HTTP 422."

    Design: Difficulty/boundary_precision_check/digital_embargo_and_collected_blackout_date_boundaries_differ_by_one_day
    """
    state = _title_with_two_issues()
    issue_id = state["second_issue"]["id"]

    validate_error(
        _digital_window_response(issue_id, "2026-12-31"),
        ApiErrorId.ERR_DIGITAL_EMBARGO_VIOLATION.value,
    )
    window = validate_success(
        _digital_window_response(issue_id, "2027-01-01"), expected_status=201
    )
    assert_date_equals(window["release_date"], "2027-01-01")
    assert window["channel"] == "DIGITAL"

    rows, meta = validate_paginated(
        api_client.list_release_windows(
            issue_id, TEST_USERS["sales_director_headers"], {"channel": "DIGITAL"}
        )
    )
    assert_ids_in_order(rows, [window["id"]])
    assert meta["total_count"] == 1


def test_the_collected_blackout_end_date_is_itself_still_inside_the_blackout():
    """2027-03-02 is refused on a 2026-12-02 anchor while 2027-03-03 is accepted.

    PRD: "A `COLLECTED` window must fall strictly after ninety calendar days past the latest `target_on_sale_date` among that title's issues whose commercial dimension is not `CANCELLED`; the blackout end date itself is still inside the blackout, so only a date after it qualifies, and a violation is refused with `ERR_CANNIBALIZATION_WINDOW_CONFLICT`."

    Design: Difficulty/boundary_precision_check/digital_embargo_and_collected_blackout_date_boundaries_differ_by_one_day
    """
    state = _title_with_two_issues()
    issue_id = state["second_issue"]["id"]

    validate_error(
        _collected_window_response(issue_id, "2027-03-02"),
        ApiErrorId.ERR_CANNIBALIZATION_WINDOW_CONFLICT.value,
    )
    window = validate_success(
        _collected_window_response(issue_id, "2027-03-03"), expected_status=201
    )
    assert_date_equals(window["release_date"], "2027-03-03")
    assert window["channel"] == "COLLECTED"

    rows, meta = validate_paginated(
        api_client.list_release_windows(
            issue_id, TEST_USERS["sales_director_headers"], {"channel": "COLLECTED"}
        )
    )
    assert_ids_in_order(rows, [window["id"]])
    assert meta["total_count"] == 1


def test_one_calendar_day_lands_on_opposite_sides_of_the_two_release_rules():
    """The digital bound is inclusive and the collected bound exclusive, one day apart in sense.

    PRD: "A `COLLECTED` window must fall strictly after ninety calendar days past the latest `target_on_sale_date` among that title's issues whose commercial dimension is not `CANCELLED`; the blackout end date itself is still inside the blackout, so only a date after it qualifies, and a violation is refused with `ERR_CANNIBALIZATION_WINDOW_CONFLICT`."

    Design: Difficulty/boundary_precision_check/digital_embargo_and_collected_blackout_date_boundaries_differ_by_one_day
    """
    state = _title_with_two_issues()
    first_issue_id = state["first_issue"]["id"]
    issue_id = state["second_issue"]["id"]

    validate_error(
        _digital_window_response(issue_id, "2026-12-31"),
        ApiErrorId.ERR_DIGITAL_EMBARGO_VIOLATION.value,
    )
    digital = validate_success(
        _digital_window_response(issue_id, "2027-01-01"), expected_status=201
    )
    validate_error(
        _collected_window_response(issue_id, "2027-03-02"),
        ApiErrorId.ERR_CANNIBALIZATION_WINDOW_CONFLICT.value,
    )
    collected = validate_success(
        _collected_window_response(issue_id, "2027-03-03"), expected_status=201
    )

    # Issue #1's own 2026-10-14 plus ninety days plus one is still inside the
    # title-wide blackout anchored on 2026-12-02.
    validate_error(
        _collected_window_response(first_issue_id, "2027-01-13"),
        ApiErrorId.ERR_CANNIBALIZATION_WINDOW_CONFLICT.value,
    )

    rows, meta = validate_paginated(
        api_client.list_release_windows(
            issue_id, TEST_USERS["sales_director_headers"]
        )
    )
    assert_ids_in_order(rows, [digital["id"], collected["id"]])
    assert_field_sequence(rows, "channel", ["DIGITAL", "COLLECTED"])
    assert meta["total_count"] == 2
    windows, first_meta = validate_paginated(
        api_client.list_release_windows(
            first_issue_id, TEST_USERS["sales_director_headers"]
        )
    )
    assert windows == []
    assert first_meta["total_count"] == 0
