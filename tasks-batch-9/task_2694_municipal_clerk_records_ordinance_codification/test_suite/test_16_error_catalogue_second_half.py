"""The second half of the error catalogue: the two retention refusals, the four
uniqueness keys, the room that is closed rather than busy, the two referential
gates on a sitting, the number book that runs out mid-cascade, and the three ways
one publication run can be malformed.
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
    RECORDS_OFFICER,
)

ANNEX = {
    "name": "Annex Hearing Room",
    "address": "9 Civic Plaza",
    "capacity": 40,
    "teardown_buffer_minutes": 30,
    "status": "CLOSED",
}
BOARD_SITTING = {
    "body_type": "BOARD_OF_ADJUSTMENT",
    "meeting_type": "SPECIAL",
    "scheduled_start": "2026-09-15T18:00:00Z",
    "scheduled_end": "2026-09-15T20:00:00Z",
    "quorum_required": 3,
}


def test_a_permanent_series_and_an_unelapsed_one_are_refused_for_different_reasons():
    """Both classes hold forty items accessioned under the same trigger, so both
    proposals reach the retention gates; the permanent one is stopped before the
    anchor is ever consulted, while the other is merely too young.

    PRD 3.9: "The series must not be under a hold, or the proposal is
    `ERR_SERIES_UNDER_LEGAL_HOLD` (HTTP 409), and it must not be flagged permanent,
    or the proposal is `ERR_SERIES_PERMANENT_RETENTION` (HTTP 409). Then the
    retention clock: `eligible_through_on` must be resolvable at all, or the
    proposal is `ERR_RETENTION_ANCHOR_UNRESOLVED` (HTTP 409), and it must have
    elapsed — it must fall at or before the logical clock date, and `cutoff_on` must
    fall at or before it — or the proposal is `ERR_RETENTION_PERIOD_NOT_ELAPSED`
    (HTTP 409)." and "Where the series is flagged `permanent`, or where the anchor
    is unresolved, `eligible_through_on` is null."

    Design: Corner/errors/permanent_and_unelapsed_series_both_refuse_a_destruction_proposal
    """
    permanent = fx.create_record_series(
        series_code="CC-06",
        name="Ordinance originals",
        retention_years=0,
        retention_trigger="CREATION",
        permanent=True,
    )
    validate_success(
        api_client.create_accession(
            permanent["id"], f.accession_payload(40, "2019-06-15"), RECORDS_OFFICER
        )
    )
    young = fx.create_record_series(
        series_code="CC-07",
        name="Utility billing files",
        retention_years=5,
        retention_trigger="CREATION",
    )
    validate_success(
        api_client.create_accession(
            young["id"], f.accession_payload(40, "2026-06-15"), RECORDS_OFFICER
        )
    )

    permanent_refusal = api_client.create_destruction_batch(
        f.destruction_batch_payload(permanent["id"], 10, "2019-06-15"), RECORDS_OFFICER
    )
    young_refusal = api_client.create_destruction_batch(
        f.destruction_batch_payload(young["id"], 10, "2026-06-15"), DEPUTY_CLERK
    )

    body = validate_error(
        permanent_refusal, ApiErrorId.SERIES_PERMANENT_RETENTION.value, 409
    )
    assert body["error_id"] != ApiErrorId.RETENTION_ANCHOR_UNRESOLVED.value
    validate_error(young_refusal, ApiErrorId.RETENTION_PERIOD_NOT_ELAPSED.value, 409)
    kept_for_ever = fx.read_record_series(permanent["id"])
    a.assert_fields(kept_for_ever, permanent=True, last_accessioned_on="2019-06-15")
    a.assert_nulls(kept_for_ever, "eligible_through_on")
    a.assert_fields(
        fx.read_record_series(young["id"]), eligible_through_on="2031-06-15"
    )
    _, meta = validate_paginated(
        api_client.list_destruction_batches(
            RECORDS_OFFICER, {"series_id": permanent["id"]}
        )
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_four_different_uniqueness_keys_each_answer_with_their_own_code():
    """A number book, a code title, a schedule item and a supplement cycle each
    already exist; each duplicate names a different caption or window, so only the
    key itself can be what is being rejected.

    PRD 3.5: "Only one series may exist for a given combination of `series_year` and
    `instrument_class`; a duplicate is refused with `ERR_DUPLICATE_NUMBER_SERIES`
    (HTTP 422)."

    PRD 3.7: "A `CodificationEditor` creates one with its `title_number`, which must
    be at least 1 and unique across the code — a duplicate is
    `ERR_DUPLICATE_CODE_TITLE` (HTTP 422) — and its `name`, the caption such as
    `Zoning`." and "The editor opens a cycle with its `supplement_number` — at least
    1, and unique within its title, a duplicate being
    `ERR_DUPLICATE_SUPPLEMENT_NUMBER` (HTTP 422) —"

    PRD 3.9: "A `RecordsOfficer` adds one with its `series_code`, the schedule item
    code, which must be unique across the schedule — a duplicate is
    `ERR_DUPLICATE_SERIES_CODE` (HTTP 422) —"

    Design: Corner/errors/every_uniqueness_key_rejects_its_duplicate
    """
    fx.create_number_series(series_year=2026, instrument_class="ORDINANCE")
    title = fx.create_code_title(title_number=12)
    fx.create_record_series(series_code="CC-01", retention_years=5)
    fx.create_supplement_cycle(
        title["id"],
        supplement_number=7,
        window_open_on="2026-07-01",
        window_close_on="2026-07-31",
    )

    duplicate_book = api_client.create_number_series(
        f.number_series_payload(2026, "ORDINANCE", prefix="ORDN"), CITY_CLERK
    )
    duplicate_title = api_client.create_code_title(
        f.code_title_payload(12, name="A different caption for title 12"),
        CODIFICATION_EDITOR,
    )
    duplicate_schedule_item = api_client.create_record_series(
        f.record_series_payload(
            "CC-01",
            retention_years=7,
            retention_trigger="FISCAL_YEAR_END",
            name="A different caption for CC-01",
        ),
        RECORDS_OFFICER,
    )
    duplicate_cycle = api_client.create_supplement_cycle(
        title["id"],
        f.supplement_cycle_payload(
            7, window_open_on="2026-09-01", window_close_on="2026-09-30"
        ),
        CODIFICATION_EDITOR,
    )

    validate_error(duplicate_book, ApiErrorId.DUPLICATE_NUMBER_SERIES.value, 422)
    validate_error(duplicate_title, ApiErrorId.DUPLICATE_CODE_TITLE.value, 422)
    validate_error(
        duplicate_schedule_item, ApiErrorId.DUPLICATE_SERIES_CODE.value, 422
    )
    body = validate_error(
        duplicate_cycle, ApiErrorId.DUPLICATE_SUPPLEMENT_NUMBER.value, 422
    )
    assert body["error_id"] != ApiErrorId.SUPPLEMENT_WINDOW_CONFLICT.value
    _, meta = validate_paginated(
        api_client.list_title_supplement_cycles(title["id"], CODIFICATION_EDITOR)
    )
    a.assert_pagination_meta(meta, total_count=1)


def test_a_closed_room_refuses_a_booking_that_collides_with_nothing():
    """The annex holds no meetings at all, so the two-hour window is entirely free
    and the only objection is the room's own availability; reopening the room lets
    the byte-identical booking through.

    PRD 3.1: "Independently, a room whose `status` is `CLOSED` accepts no bookings at
    all, and an attempt to book one is rejected with `ERR_VENUE_CLOSED` (HTTP 409)."
    and "The clerk may later revise a venue's `capacity`,
    `teardown_buffer_minutes` or `status`; each such revision advances the venue's
    `version`."

    Design: Corner/errors/a_meeting_cannot_be_scheduled_into_a_closed_venue
    """
    closed = validate_success(api_client.create_venue(ANNEX, CITY_CLERK), 201)
    booking = dict(BOARD_SITTING, venue_id=closed["id"])

    refused = api_client.create_meeting(booking, CITY_CLERK)
    reopened = validate_success(
        api_client.update_venue(closed["id"], {"status": "AVAILABLE"}, CITY_CLERK)
    )
    admitted = validate_success(api_client.create_meeting(booking, CITY_CLERK), 201)

    body = validate_error(refused, ApiErrorId.VENUE_CLOSED.value, 409)
    assert body["error_id"] != ApiErrorId.VENUE_WINDOW_CONFLICT.value
    a.assert_status(reopened, "AVAILABLE")
    a.assert_fields(
        admitted,
        status="SCHEDULED",
        body_type="BOARD_OF_ADJUSTMENT",
        meeting_type="SPECIAL",
        quorum_required=3,
        present_member_count=0,
    )
    _, meta = validate_paginated(
        api_client.list_meetings(CITY_CLERK, {"venue_id": closed["id"]})
    )
    a.assert_pagination_meta(meta, total_count=1)


def test_an_empty_agenda_and_an_untargeted_adoption_motion_are_both_refused():
    """One printed item is the difference between a packet that will not post and one
    that notices the meeting; one named instrument is the difference between an
    adoption motion that is recorded and one that is not.

    PRD 3.2: "Posting is only available from `DRAFT`, requires the meeting to still
    be in `SCHEDULED`, and requires the packet to carry at least one item: posting a
    packet whose `item_count` is 0 is rejected with `ERR_EMPTY_AGENDA_PACKET`
    (HTTP 422)."

    PRD 3.3: "An `ORDINANCE_ADOPTION`, `RESOLUTION_ADOPTION` or `VETO_OVERRIDE`
    motion must carry `instrument_id` naming the legislative instrument it acts on,
    and must leave `target_minutes_id` null." and "Any breach of this pairing,
    including a minutes motion aimed at the current meeting's own minutes, is
    rejected with `ERR_MOTION_TARGET_INVALID` (HTTP 422)."

    Design: Corner/errors/an_empty_packet_cannot_be_posted_and_an_untargeted_adoption_motion_cannot_be_moved
    """
    base = fx.scheduled_meeting()
    meeting_id = base["meeting"]["id"]
    packet = fx.draft_packet(meeting_id)

    empty_post = api_client.post_agenda_packet(packet["id"], CITY_CLERK)

    validate_error(empty_post, ApiErrorId.EMPTY_AGENDA_PACKET.value, 422)
    a.assert_fields(fx.read_packet(packet["id"]), status="DRAFT", item_count=0)
    a.assert_status(fx.read_meeting(meeting_id), "SCHEDULED")

    fx.add_item(
        packet["id"], 1, "ORDINANCE_ADOPTION", title="Adoption of the noise ordinance"
    )
    posted = validate_success(api_client.post_agenda_packet(packet["id"], CITY_CLERK))
    validate_success(
        api_client.convene_meeting(
            meeting_id, f.convene_payload(5), PRESIDING_OFFICER
        )
    )
    untargeted = api_client.create_motion(
        f.motion_payload(meeting_id, "ORDINANCE_ADOPTION", "SIMPLE"), CITY_CLERK
    )

    a.assert_fields(posted, status="POSTED", item_count=1)
    a.assert_status(fx.read_meeting(meeting_id), "IN_SESSION")
    validate_error(untargeted, ApiErrorId.MOTION_TARGET_INVALID.value, 422)
    _, meta = validate_paginated(
        api_client.list_motions(CITY_CLERK, {"meeting_id": meeting_id})
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_a_cascade_that_would_run_past_sequence_999_mints_nothing_at_all():
    """The book stands at 999 and the minutes carry two passed adoptions, so the
    cascade could number the first ordinance but not the second; the refusal leaves
    the book, both ordinances, both motions and the minutes exactly as they were.

    PRD 3.4: "**Hop 2** flips `result_official` to true on *every* motion whose
    `meeting_id` is the approved minutes' `meeting_id` — not merely the adoption
    motions, and not merely the passing ones, because the whole record of that
    sitting becomes official at once." and "**Hop 3** reads that flip: each such
    motion whose `motion_type` is `ORDINANCE_ADOPTION` or `RESOLUTION_ADOPTION` and
    whose `outcome` is `PASSED` or `TIE_BROKEN_PASSED` moves its instrument
    `ADOPTED_UNOFFICIAL → ADOPTED`, stamps `adoption_date` with the logical clock
    date, and mints the instrument's `assigned_number` from its numbering series as
    described in section 3.5."

    PRD 3.5: "Two conditions can stop the mint. If the series has been closed in the
    meantime, the cascade fails with `ERR_NUMBER_SERIES_CLOSED`; and no sequence
    above 999 may be minted, so a series standing beyond that limit fails with
    `ERR_NUMBER_SERIES_EXHAUSTED` (HTTP 422)."

    Design: Corner/errors/an_officialization_cascade_that_would_pass_sequence_999_is_refused_without_minting_anything
    """
    series = fx.create_number_series(next_sequence=999)
    ctx = fx.in_session_meeting(7, ["ORDINANCE_ADOPTION", "ORDINANCE_ADOPTION"])
    meeting_id = ctx["meeting"]["id"]
    first = fx.introduced_ordinance_at_first_reading(meeting_id, series["id"])
    second = fx.introduced_ordinance_at_first_reading(
        meeting_id,
        series["id"],
        title="Regulating sidewalk vending",
        full_text_length=2500,
    )
    first_motion = fx.record_motion(
        meeting_id, "ORDINANCE_ADOPTION", "SIMPLE", instrument_id=first["id"]
    )
    fx.tally(first_motion["id"], 5, 2)
    second_motion = fx.record_motion(
        meeting_id,
        "ORDINANCE_ADOPTION",
        "SIMPLE",
        instrument_id=second["id"],
        moved_by_member_id="cm-03",
        seconded_by_member_id="cm-04",
    )
    fx.tally(second_motion["id"], 5, 2)
    fx.adjourn(meeting_id)
    minutes = fx.submitted_minutes(
        fx.sole_minutes_of_meeting(meeting_id)["id"],
        "Two ordinances were adopted on 15 September 2026.",
    )
    later = fx.additional_meeting_in_session(
        scheduled_start="2026-10-06T18:00:00Z",
        scheduled_end="2026-10-06T21:00:00Z",
        post_at="2026-10-03T18:00:00Z",
        convene_at="2026-10-06T18:00:00Z",
        present_member_count=7,
        item_types=["MINUTES"],
        venue_id=ctx["venue"]["id"],
    )
    approval = fx.record_motion(
        later["meeting"]["id"],
        "MINUTES_APPROVAL",
        "SIMPLE",
        target_minutes_id=minutes["id"],
    )

    refused = api_client.tally_motion(approval["id"], f.tally_payload(5, 2), CITY_CLERK)

    validate_error(refused, ApiErrorId.NUMBER_SERIES_EXHAUSTED.value, 422)
    book = validate_success(
        api_client.get_number_series(series["id"], CITY_CLERK)
    )
    a.assert_fields(book, next_sequence=999, minted_count=0, status="OPEN")
    for instrument_id in (first["id"], second["id"]):
        unnumbered = fx.read_instrument(instrument_id)
        a.assert_status(unnumbered, "ADOPTED_UNOFFICIAL")
        a.assert_nulls(unnumbered, "assigned_number", "adoption_date")
    unapproved = fx.read_minutes(minutes["id"])
    a.assert_status(unapproved, "SUBMITTED")
    a.assert_nulls(unapproved, "approved_on")
    a.assert_fields(fx.read_motion(first_motion["id"]), result_official=False)
    a.assert_fields(fx.read_motion(second_motion["id"]), result_official=False)
    standing = fx.read_motion(approval["id"])
    a.assert_fields(standing, status="SECONDED", outcome="PENDING")
    a.assert_nulls(standing, "effective_base")
    _, meta = validate_paginated(
        api_client.list_publication_notices(
            CITY_CLERK, {"instrument_id": first["id"]}
        )
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_one_notice_produces_a_count_failure_an_interval_failure_and_a_dead_handoff():
    """A 3000-character amendment owes two insertions by 21 October: one date is the
    wrong count, two dates four days apart are too close together while both still
    beat the deadline, and the legal pair is accepted only to strand the cascade,
    because the title's one open cycle does not open until November.

    PRD 3.6: "An ordinance of 4,000 characters or fewer takes `ORDINANCE_FULL_TEXT`
    and owes **two** insertions." and "For an ordinance notice it is the instrument's
    `adoption_date` plus 15 days." and "The number of dates must equal the notice's
    `required_publication_count`, or the order is refused with
    `ERR_PUBLICATION_COUNT_MISMATCH` (HTTP 409)." and "And the dates must be strictly
    increasing with each consecutive pair separated by at least 7 days — a full week
    between insertions — or the order is refused with
    `ERR_PUBLICATION_INTERVAL_TOO_SHORT` (HTTP 409)." and "If no cycle qualifies, the
    whole certification fails with `ERR_NO_OPEN_SUPPLEMENT_CYCLE` (HTTP 409)."

    Design: Corner/errors/the_insertion_order_and_the_codification_handoff_each_refuse_a_malformed_publication_run
    """
    pair = fx.code_title_with_open_cycle(
        supplement_number=8,
        window_open_on="2026-11-01",
        window_close_on="2026-11-30",
    )
    cycle_id = pair["cycle"]["id"]
    scenario = fx.officialized_ordinance(
        7,
        instrument_overrides={
            "ordinance_category": "CODE_AMENDMENT",
            "code_title_id": pair["code_title"]["id"],
            "code_section_ref": "12.04.030",
            "title": "Amending 12.04.030",
            "full_text_length": 3000,
        },
    )
    notice_id = scenario["notice"]["id"]

    wrong_count = api_client.order_publication(
        notice_id,
        f.publication_order_payload(["2026-10-09"], 12.0, True),
        CITY_CLERK,
    )
    too_close = api_client.order_publication(
        notice_id,
        f.publication_order_payload(["2026-10-09", "2026-10-13"], 12.0, True),
        CITY_CLERK,
    )
    ordered = validate_success(
        api_client.order_publication(
            notice_id,
            f.publication_order_payload(["2026-10-09", "2026-10-16"], 12.0, True),
            CITY_CLERK,
        )
    )
    stranded = api_client.certify_publication(
        notice_id, f.certify_publication_payload("2026-10-16"), CITY_CLERK
    )

    a.assert_fields(
        scenario["notice"],
        notice_type="ORDINANCE_FULL_TEXT",
        required_publication_count=2,
        publication_deadline_on="2026-10-21",
        status="DRAFT",
    )
    validate_error(wrong_count, ApiErrorId.PUBLICATION_COUNT_MISMATCH.value, 409)
    body = validate_error(
        too_close, ApiErrorId.PUBLICATION_INTERVAL_TOO_SHORT.value, 409
    )
    assert body["error_id"] != ApiErrorId.PUBLICATION_DEADLINE_MISSED.value
    a.assert_status(ordered, "ORDERED")
    validate_error(stranded, ApiErrorId.NO_OPEN_SUPPLEMENT_CYCLE.value, 409)
    unpublished = fx.read_notice(notice_id)
    a.assert_status(unpublished, "ORDERED")
    a.assert_nulls(unpublished, "publication_completed_on")
    instrument = fx.read_instrument(scenario["instrument"]["id"])
    a.assert_status(instrument, "ADOPTED")
    a.assert_nulls(instrument, "effective_date", "publication_completed_on")
    a.assert_fields(fx.read_cycle(cycle_id), status="OPEN", submission_count=0)
    _, meta = validate_paginated(
        api_client.list_codification_submissions(
            CODIFICATION_EDITOR, {"cycle_id": cycle_id}
        )
    )
    a.assert_pagination_meta(meta, total_count=0)
