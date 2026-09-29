"""The three version-guarded writes, each replayed from a reading the caller no
longer holds; the version column read as a counter of accepted writes; the
packet counters re-derived on every item change; and a fan-out that is complete
in the response that reports it.
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
)

CORRECTED = "The finance report was received, filed and referred to committee."


def test_a_packet_revision_quoting_the_pre_posting_meeting_version_is_refused():
    """The reading the clerk took when the meeting was booked is two writes behind by
    the time the packet has been filed and posted, so the replay is turned away
    before it can supersede a notice the caller never saw.

    PRD 2.7: "Creating the next agenda packet revision for a meeting —
    `POST /clerk/meetings/{meeting_id}/agenda-packets` — requires
    `expected_meeting_version` carrying the client's last observed `version` of that
    `Meeting`. If it does not equal the meeting's current `version`, the request is
    rejected with `ERR_STALE_MEETING_VERSION` (HTTP 412)."

    PRD 3.2: "Creating a revision supersedes what came before: every prior packet of
    the meeting still in `DRAFT` or `POSTED` moves to `SUPERSEDED`, and if the
    superseded packet was the posted one, the meeting travels `NOTICED → SCHEDULED`
    and its mirrored notice fields are cleared — the packet-revision loop that lets a
    clerk re-notice a meeting with a corrected agenda." and "Either way the meeting's
    `version` advances, which is exactly why the operation is version-guarded."

    Design: Corner/cross_cutting_complexity_layers/filing_a_revision_against_the_pre_posting_meeting_version_is_rejected_as_stale
    """
    base = fx.scheduled_meeting()
    meeting_id = base["meeting"]["id"]
    version_at_booking = base["meeting"]["version"]
    first = fx.draft_packet(meeting_id, expected_meeting_version=version_at_booking)
    fx.add_item(first["id"], 1, "REPORT", title="Quarterly finance report")
    fx.post_packet(first["id"])

    replayed = api_client.create_agenda_packet(
        meeting_id, f.agenda_packet_payload(version_at_booking), CITY_CLERK
    )

    validate_error(replayed, ApiErrorId.STALE_MEETING_VERSION.value, 412)
    noticed = fx.read_meeting(meeting_id)
    a.assert_status(noticed, "NOTICED")
    assert noticed["version"] == version_at_booking + 2, (
        "the filing and the posting should each have advanced the meeting past "
        f"{version_at_booking}, got {noticed['version']}"
    )
    _, meta = validate_paginated(
        api_client.list_agenda_packets(CITY_CLERK, {"meeting_id": meeting_id})
    )
    a.assert_pagination_meta(meta, total_count=1)

    second = validate_success(
        api_client.create_agenda_packet(
            meeting_id, f.agenda_packet_payload(noticed["version"]), CITY_CLERK
        ),
        201,
    )

    a.assert_fields(second, revision_number=2, status="DRAFT", item_count=0)
    a.assert_fields(fx.read_packet(first["id"]), status="SUPERSEDED", item_count=1)
    reverted = fx.read_meeting(meeting_id)
    a.assert_status(reverted, "SCHEDULED")
    a.assert_no_mirrored_notice(reverted)
    assert reverted["version"] == noticed["version"] + 1, (
        "the accepted revision should have advanced the meeting once more, got "
        f"{reverted['version']}"
    )


def test_a_second_filing_quoting_the_first_filings_code_title_version_is_refused():
    """Nothing about the second submission is wrong except the reading it quotes: the
    first filing moved the title on by one, so the number the editor still holds from
    the title's registration is a version behind.

    PRD 2.7: "Filing a codification submission — `POST /clerk/codification-submissions`
    — requires `expected_code_title_version` carrying the client's last observed
    `version` of the `CodeTitle` the submission's cycle belongs to. A mismatch with the
    code title's current `version` is rejected with `ERR_STALE_CODE_TITLE_VERSION`
    (HTTP 412)."

    PRD 3.7: "The submission is stamped with `origin` `CLIENT`, enters at `status`
    `PENDING`, and advances both the cycle's `submission_count` and its
    `client_submission_count` by 1; the code title's `version` advances too, which is
    why the filing is version-guarded."

    Design: Corner/cross_cutting_complexity_layers/a_second_submission_carrying_the_first_submissions_code_title_version_is_rejected_as_stale
    """
    number_series = fx.create_number_series()
    title = fx.create_code_title(title_number=12)
    title_id = title["id"]
    version_at_registration = title["version"]
    cycle = fx.create_supplement_cycle(
        title_id,
        supplement_number=10,
        window_open_on="2026-07-01",
        window_close_on="2026-09-30",
    )
    first_instrument = fx.create_code_amendment(
        number_series["id"], title_id, "12.04.030",
        title="Amending 12.04.030", full_text_length=1500,
    )
    second_instrument = fx.create_code_amendment(
        number_series["id"], title_id, "12.04.040",
        title="Adding 12.04.040", full_text_length=1200,
    )
    first_submission = fx.file_submission(
        cycle["id"], first_instrument["id"], title_id, "12.04.030"
    )

    stale = api_client.create_codification_submission(
        f.codification_submission_payload(
            cycle["id"],
            second_instrument["id"],
            version_at_registration,
            "12.04.040",
            "ADD",
        ),
        CODIFICATION_EDITOR,
    )

    validate_error(stale, ApiErrorId.STALE_CODE_TITLE_VERSION.value, 412)
    a.assert_fields(
        fx.read_cycle(cycle["id"]),
        submission_count=1,
        client_submission_count=1,
        conflict_count=0,
    )
    current_version = fx.code_title_version(title_id)
    assert current_version == version_at_registration + 1, (
        "the first filing should have advanced the title exactly once past "
        f"{version_at_registration}, got {current_version}"
    )

    refiled = validate_success(
        api_client.create_codification_submission(
            f.codification_submission_payload(
                cycle["id"],
                second_instrument["id"],
                current_version,
                "12.04.040",
                "ADD",
            ),
            CODIFICATION_EDITOR,
        ),
        201,
    )

    a.assert_fields(
        refiled, status="PENDING", origin="CLIENT", code_section_ref="12.04.040"
    )
    a.assert_fields(
        fx.read_cycle(cycle["id"]),
        submission_count=2,
        client_submission_count=2,
        conflict_count=0,
    )
    assert fx.code_title_version(title_id) == current_version + 1, (
        "the accepted refiling should have advanced the title once more"
    )
    a.assert_status(fx.read_submission(first_submission["id"]), "PENDING")


def test_a_correction_quoting_the_version_the_minutes_were_born_with_is_refused():
    """By approval day the narrative write, the submission and the approval have each
    moved the record on, so the version stamped on it at adjournment is at least three
    behind and the parked text never lands.

    PRD 2.7: "Opening a correction against approved minutes —
    `POST /clerk/minutes/{minutes_id}/corrections` — requires
    `expected_minutes_version` carrying the client's last observed `version` of that
    `MinutesRecord`. A mismatch with the record's current `version` is rejected with
    `ERR_STALE_MINUTES_VERSION` (HTTP 412), because a correction replaces the approved
    narrative outright and a second author working from a stale reading would silently
    discard a correction or approval that landed after that reading."

    PRD 3.4: "The record moves `APPROVED → CORRECTION_PENDING`, the proposed
    replacement narrative is parked in `pending_correction_text`, `correction_count`
    advances by 1 — counting every correction ever opened against the record, including
    ones the body later refuses — and the record's `version` advances."

    Design: Corner/cross_cutting_complexity_layers/opening_a_correction_against_a_pre_approval_minutes_version_is_rejected_as_stale
    """
    ctx = fx.approved_minutes_ready_for_correction(6)
    minutes_id = ctx["minutes"]["id"]
    version_at_adjournment = ctx["minutes_at_creation"]["version"]

    stale = api_client.open_minutes_correction(
        minutes_id, f.minutes_correction_payload(version_at_adjournment, CORRECTED),
        DEPUTY_CLERK,
    )

    validate_error(stale, ApiErrorId.STALE_MINUTES_VERSION.value, 412)
    untouched = fx.read_minutes(minutes_id)
    a.assert_status(untouched, "APPROVED")
    a.assert_nulls(untouched, "pending_correction_text")
    a.assert_fields(untouched, correction_count=0, revision_number=1)
    assert untouched["version"] >= version_at_adjournment + 3, (
        "the narrative write, the submission and the approval should each have "
        f"advanced the record past {version_at_adjournment}, got {untouched['version']}"
    )

    opened = validate_success(
        api_client.open_minutes_correction(
            minutes_id, f.minutes_correction_payload(untouched["version"], CORRECTED),
            DEPUTY_CLERK,
        )
    )

    a.assert_fields(
        opened,
        status="CORRECTION_PENDING",
        correction_count=1,
        revision_number=1,
        pending_correction_text=CORRECTED,
    )
    assert opened["version"] == untouched["version"] + 1, (
        "opening the correction should have advanced the record exactly once, got "
        f"{opened['version']}"
    )


def test_every_accepted_write_moves_the_version_and_every_read_leaves_it_alone():
    """Two revisions of one room take its version 1 to 2 to 3 while the read between
    them changes nothing, and the meeting booked into that room is moved on by the
    packet filing and again by the posting.

    PRD 2.5: "Most resources additionally carry `updated_at`, in the same timestamp
    format, and `version`, an integer that begins at 1 when the record is created and
    increases by exactly 1 on every mutation of that record." and "Whenever a workflow
    in section 3 says a field is written, cleared or recomputed on a resource, that
    resource's `updated_at` is refreshed and its `version` advances — including when
    the write arrives as a cascade from an operation performed against a different
    resource."

    PRD 3.1: "The clerk may later revise a venue's `capacity`,
    `teardown_buffer_minutes` or `status`; each such revision advances the venue's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/every_accepted_write_advances_the_version_of_the_row_it_touched
    """
    registered = validate_success(
        api_client.create_venue(f.venue_payload(), CITY_CLERK), 201
    )
    venue_id = registered["id"]

    read_only = validate_success(api_client.get_venue(venue_id, DEPUTY_CLERK))
    wider = validate_success(
        api_client.update_venue(venue_id, {"capacity": 140}, CITY_CLERK)
    )
    slower = validate_success(
        api_client.update_venue(
            venue_id, {"teardown_buffer_minutes": 45}, CITY_CLERK
        )
    )

    a.assert_initial_version(registered)
    assert read_only["version"] == registered["version"], (
        f"the read advanced the version to {read_only['version']}"
    )
    assert wider["version"] == 2, f"expected version 2, got {wider['version']}"
    assert slower["version"] == 3, f"expected version 3, got {slower['version']}"
    a.assert_fields(slower, capacity=140, teardown_buffer_minutes=45)

    meeting = fx.create_meeting(venue_id)
    meeting_id = meeting["id"]
    packet = fx.draft_packet(meeting_id)
    after_filing = fx.read_meeting(meeting_id)
    fx.add_item(packet["id"], 1, "REPORT", title="Quarterly finance report")
    fx.post_packet(packet["id"])
    after_posting = fx.read_meeting(meeting_id)

    a.assert_initial_version(meeting)
    assert after_filing["version"] == 2, (
        f"the packet filing should have left the meeting at 2, got {after_filing['version']}"
    )
    assert after_posting["version"] == 3, (
        f"the posting should have left the meeting at 3, got {after_posting['version']}"
    )
    a.assert_status(after_posting, "NOTICED")


def test_the_packet_counters_are_re_derived_on_each_item_and_reset_by_a_new_revision():
    """The packet reads 0 and false, then 1 and false, then 2 and true; posting turns
    the hearing into a 240-hour requirement mirrored onto the meeting; and a fresh
    revision hands back an empty packet and an unnoticed meeting.

    PRD 3.2: "The new packet's `revision_number` is 1 plus the highest
    `revision_number` among the packets already filed for that meeting, and it enters
    in `DRAFT` with `item_count` 0, `contains_public_hearing` false, `notice_compliant`
    false and `posted_at` null." and "Each addition advances the packet's `item_count`
    by 1, and adding an item of type `PUBLIC_HEARING` turns `contains_public_hearing`
    true." and "The packet travels `DRAFT → POSTED`, the meeting travels `SCHEDULED →
    NOTICED`, the meeting's `version` advances, and `notice_posted_at`,
    `required_notice_hours` and `notice_compliant` are mirrored from the packet onto
    the meeting."

    Design: Corner/cross_cutting_complexity_layers/the_packets_derived_counters_are_recomputed_on_every_item_change_and_mirrored_at_posting
    """
    base = fx.scheduled_meeting()
    meeting_id = base["meeting"]["id"]
    packet = fx.draft_packet(meeting_id)

    a.assert_fields(packet, item_count=0, contains_public_hearing=False)
    fx.add_item(
        packet["id"], 1, "REPORT", headers=DEPUTY_CLERK,
        title="Quarterly finance report",
    )
    after_report = fx.read_packet(packet["id"])
    a.assert_fields(after_report, item_count=1, contains_public_hearing=False)
    fx.add_item(
        packet["id"], 2, "PUBLIC_HEARING", headers=DEPUTY_CLERK,
        title="Hearing on the Elm Street rezoning",
    )
    after_hearing = fx.read_packet(packet["id"])
    a.assert_fields(after_hearing, item_count=2, contains_public_hearing=True)

    posted = validate_success(api_client.post_agenda_packet(packet["id"], CITY_CLERK))

    a.assert_fields(
        posted,
        status="POSTED",
        required_notice_hours=240,
        notice_deadline_at="2026-09-05T18:00:00Z",
        notice_compliant=True,
    )
    noticed = fx.read_meeting(meeting_id)
    a.assert_meeting_notice_mirror(
        noticed,
        posted_at="2026-08-01T00:00:00Z",
        required_notice_hours=240,
        notice_compliant=True,
    )

    revision = fx.draft_packet(meeting_id)

    a.assert_fields(
        revision, revision_number=2, item_count=0, contains_public_hearing=False,
        notice_compliant=False,
    )
    a.assert_fields(
        fx.read_packet(packet["id"]),
        status="SUPERSEDED",
        item_count=2,
        contains_public_hearing=True,
    )
    reverted = fx.read_meeting(meeting_id)
    a.assert_status(reverted, "SCHEDULED")
    a.assert_no_mirrored_notice(reverted)


def test_the_cancellation_response_already_carries_every_change_it_caused():
    """The cancel response reports the cleared notice state itself, and the reads that
    follow it with no intervening write already show the packet withdrawn, the agenda
    notice void and the cancellation notice on file.

    PRD 3.1: "Cancelling drives the meeting to `CANCELLED` and fans out: every agenda
    packet of that meeting whose `status` is `DRAFT` or `POSTED` moves to `WITHDRAWN`;
    every meeting-agenda publication notice of that meeting whose `status` is `DRAFT`
    or `ORDERED` moves to `VOID`; and a fresh publication notice of type `CANCELLATION`
    is created in `DRAFT` against that meeting." and "When the cancelled meeting was in
    `NOTICED`, the cancellation additionally clears the mirrored notice state, setting
    `notice_posted_at` back to null and `notice_compliant` back to false."

    PRD 3.6: "For a `CANCELLATION` notice it is the calendar date of the meeting's
    `scheduled_start` itself, since a cancellation is still useful on the morning of
    the meeting it cancels."

    Design: Corner/consistency_model/a_cancellation_reports_every_downstream_change_in_the_same_response_it_returns
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])
    meeting_id = ctx["meeting"]["id"]
    agenda_notice_id = ctx["agenda_notice"]["id"]

    cancelled = validate_success(
        api_client.cancel_meeting(meeting_id, f.cancel_payload(), CITY_CLERK)
    )

    a.assert_fields(
        cancelled,
        status="CANCELLED",
        notice_compliant=False,
        cancelled_reason="Loss of quorum expected",
    )
    a.assert_nulls(cancelled, "notice_posted_at")
    a.assert_status(fx.read_packet(ctx["packet"]["id"], DEPUTY_CLERK), "WITHDRAWN")
    a.assert_status(fx.read_notice(agenda_notice_id, DEPUTY_CLERK), "VOID")
    drafts, draft_meta = validate_paginated(
        api_client.list_publication_notices(
            DEPUTY_CLERK, {"meeting_id": meeting_id, "status": "DRAFT"}
        )
    )
    a.assert_pagination_meta(draft_meta, total_count=1)
    a.assert_fields(
        drafts[0],
        notice_type="CANCELLATION",
        required_publication_count=1,
        publication_deadline_on="2026-09-15",
        meeting_id=meeting_id,
    )
    a.assert_nulls(drafts[0], "instrument_id")
    _, all_meta = validate_paginated(
        api_client.list_publication_notices(DEPUTY_CLERK, {"meeting_id": meeting_id})
    )
    a.assert_pagination_meta(all_meta, total_count=2)
