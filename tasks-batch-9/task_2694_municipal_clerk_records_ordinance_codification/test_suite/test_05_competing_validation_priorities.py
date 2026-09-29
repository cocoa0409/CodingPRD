"""Requests that break two rules at once. PRD 2.11 fixes the order in which the
service looks, so each of these has exactly one right answer and one wrong one.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CITY_CLERK,
    CODIFICATION_EDITOR,
    RECORDS_OFFICER,
)

FLAT_LINE = [f.fee_line(page_count=60, staff_minutes=45, delivery_medium="PAPER")]


def _request_under_review_owing_1875():
    """A request still on the review desk with a FLAT_SCHEDULE fee of 1875 cents
    assessed and nothing paid against it."""
    fx.set_clock("2026-08-03T09:00:00Z")
    scenario = fx.assessed_request(
        FLAT_LINE,
        fee_schedule_variant="FLAT_SCHEDULE",
        subject_description="Council correspondence 2025",
    )
    return scenario


def test_closing_an_undisposed_request_reports_closability_not_the_balance():
    """A close that breaks both the disclosure precondition and the zero-balance
    precondition answers ERR_REQUEST_NOT_CLOSABLE.

    PRD 3.8: "A request that is neither disposed of nor paid up therefore reports
    the closability failure, not the balance failure."

    Design: Difficulty/priority_pair_validation_conflict/close_violating_both_disclosure_state_and_fee_balance_returns_not_closable
    """
    request = _request_under_review_owing_1875()

    response = api_client.close_records_request(request["id"], CITY_CLERK)

    body = validate_error(response, ApiErrorId.REQUEST_NOT_CLOSABLE.value, 409)
    assert body["error_id"] != ApiErrorId.FEE_BALANCE_OUTSTANDING.value


def test_the_refused_close_leaves_both_axes_and_the_outstanding_balance_intact():
    """Both losing conditions really were present: the request is UNDER_REVIEW and
    still owes 1875 cents, and it never acquires a closed_on.

    PRD 3.8: "Closing is a `CityClerk` act and has two preconditions in a fixed
    order. The request must first be in `RELEASED`, `PARTIALLY_RELEASED` or
    `DENIED`; anything else is `ERR_REQUEST_NOT_CLOSABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/close_violating_both_disclosure_state_and_fee_balance_returns_not_closable
    """
    request = _request_under_review_owing_1875()

    api_client.close_records_request(request["id"], CITY_CLERK)

    after = fx.read_records_request(request["id"])
    a.assert_axes(after, fulfillment_status="UNDER_REVIEW", fee_status="ASSESSED")
    a.assert_cents(after, "fee_balance_cents", 1875)
    a.assert_nulls(after, "closed_on")


def _noticed_meeting_and_an_occupied_earlier_window():
    """A compliant NOTICED meeting on 25 September, and a second meeting already
    holding the same room on the evening of 14 September."""
    venue = fx.create_venue(teardown_buffer_minutes=30)
    earlier = fx.create_meeting(
        venue["id"],
        scheduled_start="2026-09-14T18:00:00Z",
        scheduled_end="2026-09-14T21:00:00Z",
    )
    later = fx.create_meeting(
        venue["id"],
        scheduled_start="2026-09-25T18:00:00Z",
        scheduled_end="2026-09-25T21:00:00Z",
    )
    packet = fx.draft_packet(later["id"])
    fx.add_item(packet["id"], 1, "REPORT", title="Quarterly finance report")
    fx.set_clock("2026-09-12T18:00:00Z")
    fx.post_packet(packet["id"])
    return {"venue": venue, "earlier": earlier, "later": later, "packet": packet}


def test_a_reschedule_that_both_shortens_notice_and_double_books_reports_notice():
    """Moving the meeting to 14 September at 19:00 leaves less notice than the
    statute demands and collides with the earlier booking, and the notice rule
    answers first.

    PRD 3.1: "On a reschedule this notice check runs **before** the venue-overlap
    check, so a move that both shortens the notice and double-books the room
    reports the notice failure."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_violating_both_notice_deadline_and_venue_window_returns_notice_deadline_missed
    """
    ctx = _noticed_meeting_and_an_occupied_earlier_window()

    response = api_client.reschedule_meeting(
        ctx["later"]["id"],
        f.reschedule_payload("2026-09-14T19:00:00Z", "2026-09-14T22:00:00Z"),
        CITY_CLERK,
    )

    body = validate_error(response, ApiErrorId.NOTICE_DEADLINE_MISSED.value, 409)
    assert body["error_id"] != ApiErrorId.VENUE_WINDOW_CONFLICT.value


def test_the_refused_reschedule_leaves_the_original_window_and_its_notice_standing():
    """The meeting keeps its 25 September window and stays NOTICED behind a packet
    whose deadline of 2026-09-22T18:00:00Z was met.

    PRD 3.1: "Moving a meeting that has already been noticed carries a second
    obligation. If a posted packet exists, the move recomputes that packet's notice
    arithmetic against the new start instant and re-mirrors `required_notice_hours`
    and `notice_compliant` onto the meeting; and if the recomputed deadline would
    fall at or before the logical clock — meaning the new date leaves less notice
    than the statute demands, counted from now — the move is refused with
    `ERR_NOTICE_DEADLINE_MISSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_violating_both_notice_deadline_and_venue_window_returns_notice_deadline_missed
    """
    ctx = _noticed_meeting_and_an_occupied_earlier_window()

    api_client.reschedule_meeting(
        ctx["later"]["id"],
        f.reschedule_payload("2026-09-14T19:00:00Z", "2026-09-14T22:00:00Z"),
        CITY_CLERK,
    )

    meeting = fx.read_meeting(ctx["later"]["id"])
    a.assert_fields(
        meeting, scheduled_start="2026-09-25T18:00:00Z", status="NOTICED"
    )
    a.assert_fields(
        fx.read_packet(ctx["packet"]["id"]),
        notice_deadline_at="2026-09-22T18:00:00Z",
        notice_compliant=True,
    )


def _held_series_holding_one_hundred_items():
    """A series whose retention has long elapsed, then placed under litigation
    hold with 100 items still in active custody."""
    series = fx.series_eligible_for_destruction(
        item_count=100, accessioned_on="2019-06-15", retention_years=5
    )
    fx.set_clock("2026-08-01T00:00:00Z")
    fx.place_legal_hold(series["id"], "LITIGATION_HOLD")
    return fx.read_record_series(series["id"])


def test_a_held_and_oversized_destruction_batch_reports_the_legal_hold():
    """Proposing 500 items out of a held series of 100 answers
    ERR_SERIES_UNDER_LEGAL_HOLD with a 409, not the 422 the count rule would give.

    PRD 3.9: "The hold and permanence checks are evaluated **before** the
    item-count check, so a batch that is both held and oversized reports the hold."

    Design: Difficulty/priority_pair_validation_conflict/destruction_batch_violating_both_legal_hold_and_item_count_returns_series_under_legal_hold
    """
    series = _held_series_holding_one_hundred_items()

    response = api_client.create_destruction_batch(
        f.destruction_batch_payload(series["id"], 500, "2024-06-15"), RECORDS_OFFICER
    )

    body = validate_error(response, ApiErrorId.SERIES_UNDER_LEGAL_HOLD.value, 409)
    assert body["error_id"] != ApiErrorId.DESTRUCTION_COUNT_EXCEEDS_ACTIVE.value


def test_the_refused_proposal_records_no_batch_and_conserves_custody():
    """The series really was both eligible on the calendar and too small for the
    proposal, and no batch row survives the refusal.

    PRD 3.9: "Custody is conserved at every observable moment:
    `total_accessioned_count` always equals `active_item_count` plus
    `destroyed_item_count`."

    Design: Difficulty/priority_pair_validation_conflict/destruction_batch_violating_both_legal_hold_and_item_count_returns_series_under_legal_hold
    """
    series = _held_series_holding_one_hundred_items()

    api_client.create_destruction_batch(
        f.destruction_batch_payload(series["id"], 500, "2024-06-15"), RECORDS_OFFICER
    )

    after = fx.read_record_series(series["id"])
    a.assert_fields(after, eligible_through_on="2024-06-15")
    a.assert_custody_triple(after, total=100, active=100, destroyed=0)
    _, meta = validate_paginated(
        api_client.list_destruction_batches(RECORDS_OFFICER, {"series_id": series["id"]})
    )
    a.assert_pagination_meta(meta, total_count=0)


def _cycle_at_the_client_cap():
    """A cycle holding the maximum three client submissions, plus a fourth
    code amendment whose own section is 12.05.050."""
    pair = fx.code_title_with_open_cycle(
        window_open_on="2026-10-01", window_close_on="2026-10-31"
    )
    title_id = pair["code_title"]["id"]
    series = fx.create_number_series()
    sections = ["12.01.010", "12.02.020", "12.03.030"]
    instruments = [
        fx.create_code_amendment(
            series["id"], title_id, section, full_text_length=900,
            title=f"Amendment to {section}",
        )
        for section in sections
    ]
    fourth = fx.create_code_amendment(
        series["id"], title_id, "12.05.050", full_text_length=900,
        title="Amendment to 12.05.050",
    )
    fx.set_clock("2026-10-06T09:00:00Z")
    for instrument, section in zip(instruments, sections):
        fx.file_submission(pair["cycle"]["id"], instrument["id"], title_id, section, "ADD")
    return {**pair, "fourth": fourth}


def test_a_fourth_client_filing_with_a_mismatched_section_reports_the_cap():
    """The cap on client filings is an aggregate constraint and the section
    mismatch is a referential one, so the cap answers first.

    PRD 2.11: "After that come the domain families, in this order: open-meeting and
    records-safety rules; aggregate caps and uniqueness; temporal window rules;
    fiscal rules; and finally referential and configuration consistency."

    Design: Difficulty/priority_pair_validation_conflict/fourth_client_submission_with_wrong_section_returns_cycle_submission_capacity
    """
    ctx = _cycle_at_the_client_cap()

    response = api_client.create_codification_submission(
        f.codification_submission_payload(
            ctx["cycle"]["id"],
            ctx["fourth"]["id"],
            fx.code_title_version(ctx["code_title"]["id"]),
            "12.99.999",
            "ADD",
        ),
        CODIFICATION_EDITOR,
    )

    body = validate_error(response, ApiErrorId.CYCLE_SUBMISSION_CAPACITY.value, 422)
    assert body["error_id"] != ApiErrorId.CODE_SECTION_UNKNOWN.value


def test_the_refused_fourth_filing_leaves_the_cycle_counters_at_three():
    """No row is created for the fourth instrument and the cycle's three counters
    are exactly where the three accepted filings left them.

    PRD 3.7: "At most three client-origin submissions may sit in one cycle,
    counting everything except rows that have been withdrawn; a fourth is
    `ERR_CYCLE_SUBMISSION_CAPACITY` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/fourth_client_submission_with_wrong_section_returns_cycle_submission_capacity
    """
    ctx = _cycle_at_the_client_cap()

    api_client.create_codification_submission(
        f.codification_submission_payload(
            ctx["cycle"]["id"],
            ctx["fourth"]["id"],
            fx.code_title_version(ctx["code_title"]["id"]),
            "12.99.999",
            "ADD",
        ),
        CODIFICATION_EDITOR,
    )

    a.assert_fields(
        fx.read_cycle(ctx["cycle"]["id"]),
        submission_count=3,
        client_submission_count=3,
        conflict_count=0,
    )
    _, meta = validate_paginated(
        api_client.list_codification_submissions(
            CODIFICATION_EDITOR, {"instrument_id": ctx["fourth"]["id"]}
        )
    )
    a.assert_pagination_meta(meta, total_count=0)
