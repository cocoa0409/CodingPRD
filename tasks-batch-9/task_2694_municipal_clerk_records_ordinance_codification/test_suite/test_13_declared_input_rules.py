"""The declared input rules, each read from both sides: the pairings that must
hold, the comparison that is inclusive, the aggregate cap, the window that closes
a filing out, and the check that runs ahead of the arithmetic it protects.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CITY_CLERK,
    CODIFICATION_EDITOR,
    DEPUTY_CLERK,
    PRESIDING_OFFICER,
    make_requester_headers,
)


def test_the_category_pairing_is_refused_from_both_directions():
    """A resolution declaring an ordinance category and an ordinance declaring none
    are the same single shape failure, and neither instrument reaches the register.

    PRD 3.5: "`ordinance_category` is required for an ordinance and must be one of
    `GENERAL`, `ZONING`, `CODE_AMENDMENT` or `EMERGENCY`; it must be null for a
    resolution."

    Design: Corner/validations/a_resolution_carrying_an_ordinance_category_is_an_invalid_request
    """
    resolution_series = fx.create_number_series(instrument_class="RESOLUTION")
    ordinance_series = fx.create_number_series(instrument_class="ORDINANCE")

    resolution_with_category = api_client.create_instrument(
        f.resolution_payload(resolution_series["id"], ordinance_category="GENERAL"),
        CITY_CLERK,
    )
    ordinance_without_category = api_client.create_instrument(
        {
            "instrument_class": "ORDINANCE",
            "title": "Amending the noise ordinance",
            "full_text_length": 3000,
            "number_series_id": ordinance_series["id"],
        },
        CITY_CLERK,
    )

    validate_error(resolution_with_category, ApiErrorId.INVALID_REQUEST.value, 422)
    validate_error(ordinance_without_category, ApiErrorId.INVALID_REQUEST.value, 422)
    for series in (resolution_series, ordinance_series):
        _, meta = validate_paginated(
            api_client.list_instruments(CITY_CLERK, {"number_series_id": series["id"]})
        )
        a.assert_pagination_meta(meta, total_count=0)


def test_attendance_exactly_at_quorum_opens_the_sitting():
    """Four members against a quorum of four is enough, and the stored count becomes
    the base the meeting's votes will be measured against.

    PRD 3.3: "On success the supplied count is stored as the meeting's
    `present_member_count`, and that stored number — not the count on any later
    request — is the denominator every vote at this meeting is measured against."

    Design: Corner/validations/convening_with_attendance_exactly_at_quorum_succeeds
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])

    convened = validate_success(
        api_client.convene_meeting(
            ctx["meeting"]["id"], f.convene_payload(4), PRESIDING_OFFICER
        )
    )

    a.assert_fields(
        convened,
        status="IN_SESSION",
        present_member_count=4,
        quorum_required=4,
        notice_compliant=True,
    )


def test_an_instrument_is_judged_by_the_series_it_points_at():
    """A resolution pointed at the ordinance book and one pointed at last year's book
    are both refused; the same resolution against the matching book is admitted
    unnumbered.

    PRD 3.5: "The chosen series' `instrument_class` must match the instrument's own,
    and the series' `series_year` must equal the calendar year of the logical clock
    date at introduction — a 2026 ordinance cannot be numbered out of the 2025 book,
    and an ordinance cannot be numbered out of a resolution series; either mismatch
    is `ERR_SERIES_CLASS_MISMATCH` (HTTP 422)."

    Design: Corner/validations/an_instrument_must_draw_from_a_series_of_its_own_class_and_year
    """
    ordinance_2026 = fx.create_number_series(instrument_class="ORDINANCE")
    resolution_2025 = fx.create_number_series(
        series_year=2025, instrument_class="RESOLUTION"
    )
    resolution_2026 = fx.create_number_series(instrument_class="RESOLUTION")

    wrong_class = api_client.create_instrument(
        f.resolution_payload(ordinance_2026["id"]), CITY_CLERK
    )
    wrong_year = api_client.create_instrument(
        f.resolution_payload(resolution_2025["id"]), CITY_CLERK
    )
    admitted = validate_success(
        api_client.create_instrument(
            f.resolution_payload(resolution_2026["id"]), CITY_CLERK
        ),
        201,
    )

    validate_error(wrong_class, ApiErrorId.SERIES_CLASS_MISMATCH.value, 422)
    validate_error(wrong_year, ApiErrorId.SERIES_CLASS_MISMATCH.value, 422)
    a.assert_fields(admitted, status="INTRODUCED", requires_publication=False)
    a.assert_nulls(admitted, "assigned_number")


def test_an_insertion_dated_on_the_meeting_day_is_one_day_too_late():
    """The agenda must be in the paper before the day of the meeting, so a single
    correctly counted insertion dated 15 September is refused and nothing is priced.

    PRD 3.6: "The latest of the dates must fall on or before
    `publication_deadline_on`, or the order is refused with
    `ERR_PUBLICATION_DEADLINE_MISSED` (HTTP 409)."

    Design: Corner/validations/an_insertion_dated_after_the_publication_deadline_is_refused
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])

    response = api_client.order_publication(
        ctx["agenda_notice"]["id"],
        f.publication_order_payload(["2026-09-15"], column_inches=20.0),
        DEPUTY_CLERK,
    )

    validate_error(response, ApiErrorId.PUBLICATION_DEADLINE_MISSED.value, 409)
    notice = fx.read_notice(ctx["agenda_notice"]["id"])
    a.assert_fields(notice, status="DRAFT", publication_deadline_on="2026-09-14")
    a.assert_nulls(notice, "invoice_total_cents")


def test_the_third_revision_is_admitted_and_the_fourth_is_refused_by_the_cap():
    """Each filing is individually valid and quotes the current meeting version; only
    the aggregate ceiling stops the fourth, and the superseded packets stay on file.

    PRD 3.2: "A meeting tolerates at most three packet revisions; an attempt to
    create a fourth is rejected with `ERR_PACKET_REVISION_LIMIT` (HTTP 422)."

    Design: Corner/validations/a_fourth_packet_revision_on_one_meeting_is_refused
    """
    base = fx.scheduled_meeting()
    meeting_id = base["meeting"]["id"]
    first = fx.draft_packet(meeting_id)
    second = fx.draft_packet(meeting_id)
    third = fx.draft_packet(meeting_id)
    version_before = fx.meeting_version(meeting_id)

    response = api_client.create_agenda_packet(
        meeting_id, f.agenda_packet_payload(version_before), CITY_CLERK
    )

    body = validate_error(response, ApiErrorId.PACKET_REVISION_LIMIT.value, 422)
    assert body["error_id"] != ApiErrorId.STALE_MEETING_VERSION.value
    a.assert_fields(third, revision_number=3, status="DRAFT")
    a.assert_status(fx.read_packet(first["id"]), "SUPERSEDED")
    a.assert_status(fx.read_packet(second["id"]), "SUPERSEDED")
    a.assert_status(fx.read_packet(third["id"]), "DRAFT")
    _, meta = validate_paginated(
        api_client.list_agenda_packets(CITY_CLERK, {"meeting_id": meeting_id})
    )
    a.assert_pagination_meta(meta, total_count=3)
    assert fx.meeting_version(meeting_id) == version_before


def test_the_same_filing_is_refused_outside_the_window_and_accepted_inside_it():
    """Nothing about the submission changes between the two attempts except the day
    the clock reports, and the accepted row is stamped as a client filing.

    PRD 3.7: "The logical clock date must fall inside the cycle's inclusive window,
    boundaries included, or the filing is `ERR_OUTSIDE_SUBMISSION_WINDOW`
    (HTTP 409)."

    Design: Corner/validations/the_submission_window_rule_applies_only_to_client_origin_filings
    """
    number_series = fx.create_number_series()
    pair = fx.code_title_with_open_cycle(
        window_open_on="2026-09-01", window_close_on="2026-09-30"
    )
    title_id = pair["code_title"]["id"]
    instrument = fx.create_code_amendment(
        number_series["id"], title_id, "12.04.030", title="Amending 12.04.030"
    )
    payload = f.codification_submission_payload(
        pair["cycle"]["id"],
        instrument["id"],
        fx.code_title_version(title_id),
        "12.04.030",
        "ADD",
    )

    too_early = api_client.create_codification_submission(payload, CODIFICATION_EDITOR)
    fx.set_clock("2026-09-15T00:00:00Z")
    filed = validate_success(
        api_client.create_codification_submission(payload, CODIFICATION_EDITOR), 201
    )

    validate_error(too_early, ApiErrorId.OUTSIDE_SUBMISSION_WINDOW.value, 409)
    a.assert_fields(filed, origin="CLIENT", status="PENDING")
    a.assert_fields(
        fx.read_cycle(pair["cycle"]["id"]),
        submission_count=1,
        client_submission_count=1,
        conflict_count=0,
    )


def test_a_payment_against_an_unassessed_file_never_reaches_the_balance_check():
    """500 cents does exceed a balance of nothing, and the refusal still names the
    missing assessment rather than the overshoot.

    PRD 3.8: "A fee must already have been assessed, or the payment is
    `ERR_FEE_NOT_ASSESSED` (HTTP 422), and the amount may not exceed the current
    `fee_balance_cents`, or it is `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/a_payment_before_assessment_is_refused_by_the_earlier_check
    """
    request = fx.request_under_review(subject_description="Bid tabulations 2026")

    response = api_client.record_payment(
        request["id"], f.payment_payload(500), make_requester_headers(request["id"])
    )

    body = validate_error(response, ApiErrorId.FEE_NOT_ASSESSED.value, 422)
    assert body["error_id"] != ApiErrorId.PAYMENT_EXCEEDS_BALANCE.value
    unpaid = fx.read_records_request(request["id"])
    a.assert_fields(unpaid, fee_status="NOT_ASSESSED")
    a.assert_cents(unpaid, "total_collected_cents", 0)
    a.assert_cents(unpaid, "net_cash_cents", 0)


def test_the_page_size_bounds_are_enforced_at_both_ends():
    """Zero, one hundred and one, and a negative offset are each refused, while a
    page of exactly one hundred is accepted.

    PRD 2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/validations/pagination_arguments_outside_their_declared_bounds_are_rejected
    """
    base = fx.scheduled_meeting()

    too_small = api_client.list_meetings(CITY_CLERK, {"limit": 0, "offset": 0})
    too_large = api_client.list_meetings(CITY_CLERK, {"limit": 101, "offset": 0})
    negative = api_client.list_meetings(CITY_CLERK, {"limit": 10, "offset": -1})
    accepted = api_client.list_meetings(CITY_CLERK, {"limit": 100, "offset": 0})

    validate_error(too_small, ApiErrorId.INVALID_PAGINATION.value, 422)
    validate_error(too_large, ApiErrorId.INVALID_PAGINATION.value, 422)
    validate_error(negative, ApiErrorId.INVALID_PAGINATION.value, 422)
    rows, meta = validate_paginated(accepted)
    a.assert_pagination_meta(meta, total_count=1, has_more=False, limit=100, offset=0)
    a.assert_ids_equal(rows, [base["meeting"]["id"]])
