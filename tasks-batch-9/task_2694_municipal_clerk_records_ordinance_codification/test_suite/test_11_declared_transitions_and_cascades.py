"""The declared edges of each lifecycle, walked one at a time: the openings, the
refusals, the sweeps that reach into a second aggregate, and the terminal states
that accept nothing further.
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
    ANONYMOUS,
    CITY_CLERK,
    CODIFICATION_EDITOR,
    DEPUTY_CLERK,
    PRESIDING_OFFICER,
    RECORDS_OFFICER,
)

NARRATIVE = "Minutes of 15 September 2026."


def _one_item_draft_packet():
    """A SCHEDULED council meeting on 15 September 2026 behind a DRAFT packet
    carrying a single report."""
    base = fx.scheduled_meeting()
    packet = fx.draft_packet(base["meeting"]["id"])
    fx.add_item(packet["id"], 1, "REPORT", title="Quarterly finance report")
    return {"meeting": fx.read_meeting(base["meeting"]["id"]), "packet": packet}


def test_posting_the_packet_notices_the_meeting_and_raises_the_agenda_notice():
    """One post drives the packet to POSTED and the meeting to NOTICED, mirrors the
    72-hour requirement onto the meeting, advances its version, and raises the
    newspaper paperwork.

    PRD 3.2: "The packet travels `DRAFT → POSTED`, the meeting travels `SCHEDULED
    → NOTICED`, the meeting's `version` advances, and `notice_posted_at`,
    `required_notice_hours` and `notice_compliant` are mirrored from the packet onto
    the meeting."

    Design: Corner/state_machines/posting_the_packet_moves_the_meeting_scheduled_to_noticed
    """
    ctx = _one_item_draft_packet()

    posted = validate_success(
        api_client.post_agenda_packet(ctx["packet"]["id"], CITY_CLERK)
    )

    a.assert_fields(
        posted,
        status="POSTED",
        required_notice_hours=72,
        notice_deadline_at="2026-09-12T18:00:00Z",
        posted_at="2026-08-01T00:00:00Z",
        notice_compliant=True,
    )
    meeting = fx.read_meeting(ctx["meeting"]["id"])
    a.assert_status(meeting, "NOTICED")
    a.assert_meeting_notice_mirror(
        meeting,
        posted_at="2026-08-01T00:00:00Z",
        required_notice_hours=72,
        notice_compliant=True,
    )
    a.assert_version_advanced_by(ctx["meeting"], meeting)
    notices = fx.list_notices_for_meeting(ctx["meeting"]["id"])
    assert len(notices) == 1, f"expected exactly one notice, got {notices}"
    a.assert_fields(
        notices[0],
        notice_type="MEETING_AGENDA",
        status="DRAFT",
        required_publication_count=1,
        publication_deadline_on="2026-09-14",
    )


def test_a_short_house_cannot_be_called_to_order():
    """Notice is compliant, so the only failing precondition is attendance, and the
    refusal leaves the meeting noticed with nobody recorded present.

    PRD 3.3: "Second, the `present_member_count` supplied with the call must be at
    least the meeting's `quorum_required`; a short house is refused with
    `ERR_QUORUM_NOT_MET` (HTTP 409)."

    Design: Corner/state_machines/convene_below_quorum_returns_quorum_not_met
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])
    assert ctx["meeting"]["notice_compliant"] is True

    response = api_client.convene_meeting(
        ctx["meeting"]["id"], f.convene_payload(3), PRESIDING_OFFICER
    )

    validate_error(response, ApiErrorId.QUORUM_NOT_MET.value, 409)
    a.assert_fields(
        fx.read_meeting(ctx["meeting"]["id"]),
        status="NOTICED",
        present_member_count=0,
        quorum_required=4,
    )


def test_adjournment_opens_draft_minutes_and_sweeps_only_the_untallied_motion():
    """The gavel falls once and does three things: it stamps the closing instant,
    opens an empty minutes record, and withdraws the motion nobody voted on while
    leaving the decided one alone.

    PRD 3.3: "The meeting moves to `ADJOURNED`, `adjourned_at` records the logical
    clock instant, a fresh minutes record is opened in `DRAFT` against the meeting
    with `revision_number` 1 and an empty `text_body`, and every motion of that
    meeting still sitting in `SECONDED` is swept to `WITHDRAWN` — its `outcome`
    staying `PENDING`, and no instrument or minutes touched by the sweep."

    Design: Corner/state_machines/adjourning_creates_draft_minutes_and_withdraws_only_the_untallied_motion
    """
    ctx = fx.in_session_meeting(5, ["REPORT"])
    decided = fx.record_motion(ctx["meeting"]["id"])
    fx.tally(decided["id"], 3, 2)
    undecided = fx.record_motion(
        ctx["meeting"]["id"], moved_by_member_id="cm-03", seconded_by_member_id="cm-04"
    )

    adjourned = validate_success(
        api_client.adjourn_meeting(ctx["meeting"]["id"], PRESIDING_OFFICER)
    )

    a.assert_fields(
        adjourned, status="ADJOURNED", adjourned_at="2026-08-01T00:00:00Z"
    )
    minutes, minutes_meta = validate_paginated(
        api_client.list_meeting_minutes(ctx["meeting"]["id"], CITY_CLERK)
    )
    a.assert_pagination_meta(minutes_meta, total_count=1)
    a.assert_fields(
        minutes[0],
        status="DRAFT",
        revision_number=1,
        text_body="",
        correction_count=0,
    )
    a.assert_fields(
        fx.read_motion(undecided["id"]), status="WITHDRAWN", outcome="PENDING"
    )
    settled = fx.read_motion(decided["id"])
    a.assert_status(settled, "TALLIED")
    a.assert_vote_arithmetic(
        settled, effective_base=5, required_yes=3, outcome="PASSED"
    )


def test_a_meeting_with_no_notice_at_all_is_refused_on_its_state_not_its_notice():
    """A meeting that was never noticed has no convene edge to travel, so the state
    error is reported ahead of both notice and quorum, even with a full house
    waiting.

    PRD 3.3: "Only a `PresidingOfficer` may call a meeting to order, and only from
    `NOTICED`."

    Design: Corner/state_machines/convening_a_scheduled_meeting_before_any_notice_is_rejected
    """
    base = fx.scheduled_meeting()

    response = api_client.convene_meeting(
        base["meeting"]["id"], f.convene_payload(7), PRESIDING_OFFICER
    )

    body = validate_error(response, ApiErrorId.INVALID_MEETING_STATE.value, 409)
    assert body["error_id"] != ApiErrorId.NOTICE_DEADLINE_MISSED.value
    assert body["error_id"] != ApiErrorId.QUORUM_NOT_MET.value
    a.assert_status(fx.read_meeting(base["meeting"]["id"]), "SCHEDULED")


def test_meeting_packet_and_motion_each_land_on_their_own_opening_state():
    """Three resources are opened in one run and each answers with its own declared
    starting state; in particular a motion is never recorded before it is seconded.

    PRD 3.1: "The meeting enters the register with `status` `SCHEDULED`, a
    `present_member_count` of 0, and no notice: `notice_posted_at` and
    `required_notice_hours` are null and `notice_compliant` is false."

    Design: Corner/state_machines/a_new_meeting_starts_in_the_declared_initial_state
    """
    venue = fx.create_venue()

    meeting = validate_success(
        api_client.create_meeting(f.meeting_payload(venue["id"]), CITY_CLERK), 201
    )
    packet = fx.draft_packet(meeting["id"])
    fx.add_item(packet["id"], 1, "REPORT", title="Quarterly finance report")
    fx.post_packet(packet["id"])
    validate_success(
        api_client.convene_meeting(meeting["id"], f.convene_payload(5), PRESIDING_OFFICER)
    )
    motion = validate_success(
        api_client.create_motion(f.motion_payload(meeting["id"]), CITY_CLERK), 201
    )

    a.assert_fields(meeting, status="SCHEDULED", present_member_count=0)
    a.assert_no_mirrored_notice(meeting)
    a.assert_fields(packet, status="DRAFT")
    a.assert_nulls(packet, "posted_at")
    a.assert_fields(
        motion,
        status="SECONDED",
        outcome="PENDING",
        tie_break_used=False,
        result_official=False,
    )


def test_an_adjourned_meeting_refuses_both_the_cancel_and_the_reschedule():
    """Adjournment is the end of the line: neither of the two remaining calendar
    operations moves anything, and no reason or new window is recorded.

    PRD 3.1: "`ADJOURNED` and `CANCELLED` are terminal for a meeting; an attempt to
    cancel a meeting that is `IN_SESSION`, already adjourned or already cancelled is
    an invalid meeting state."

    Design: Corner/state_machines/an_adjourned_meeting_cannot_be_cancelled_or_rescheduled
    """
    ctx = fx.adjourned_meeting_with_minutes(5, ["REPORT"])

    cancel = api_client.cancel_meeting(
        ctx["meeting"]["id"],
        f.cancel_payload(cancelled_reason="Called off after the fact"),
        CITY_CLERK,
    )
    reschedule = api_client.reschedule_meeting(
        ctx["meeting"]["id"],
        f.reschedule_payload("2026-10-06T18:00:00Z", "2026-10-06T21:00:00Z"),
        CITY_CLERK,
    )

    validate_error(cancel, ApiErrorId.INVALID_MEETING_STATE.value, 409)
    validate_error(reschedule, ApiErrorId.INVALID_MEETING_STATE.value, 409)
    meeting = fx.read_meeting(ctx["meeting"]["id"])
    a.assert_fields(
        meeting, status="ADJOURNED", scheduled_start="2026-09-15T18:00:00Z"
    )
    a.assert_nulls(meeting, "cancelled_reason")


def test_the_second_submit_of_one_minutes_record_is_refused_and_the_version_holds():
    """Submission is a one-way door rather than a replayable act: the repeat is
    refused and the record's version stands exactly where the first submit left it.

    PRD 3.4: "Attempting to write or submit a record that is not in `DRAFT` is
    `ERR_INVALID_MINUTES_STATE` (HTTP 409)."

    Design: Corner/state_machines/submitting_the_same_minutes_twice_returns_invalid_minutes_state
    """
    ctx = fx.adjourned_meeting_with_minutes(5, ["REPORT"])
    minutes_id = ctx["minutes"]["id"]
    validate_success(
        api_client.update_minutes(
            minutes_id, f.minutes_narrative_payload(NARRATIVE), CITY_CLERK
        )
    )

    first = validate_success(api_client.submit_minutes(minutes_id, CITY_CLERK))
    second = api_client.submit_minutes(minutes_id, CITY_CLERK)

    a.assert_status(first, "SUBMITTED")
    validate_error(second, ApiErrorId.INVALID_MINUTES_STATE.value, 409)
    a.assert_fields(
        fx.read_minutes(minutes_id),
        status="SUBMITTED",
        version=first["version"],
        revision_number=1,
        text_body=NARRATIVE,
    )


def test_cancelling_a_noticed_meeting_reaches_the_packet_and_both_notices():
    """One cancel withdraws the posted packet, voids the agenda notice, clears the
    mirrored notice state and raises a fresh cancellation notice that may still run
    on the morning of the meeting.

    PRD 3.1: "Cancelling drives the meeting to `CANCELLED` and fans out: every
    agenda packet of that meeting whose `status` is `DRAFT` or `POSTED` moves to
    `WITHDRAWN`; every meeting-agenda publication notice of that meeting whose
    `status` is `DRAFT` or `ORDERED` moves to `VOID`; and a fresh publication notice
    of type `CANCELLATION` is created in `DRAFT` against that meeting."

    Design: Corner/state_machines/cancelling_a_noticed_meeting_cascades_down_to_packet_and_notices
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])

    cancelled = validate_success(
        api_client.cancel_meeting(
            ctx["meeting"]["id"],
            f.cancel_payload(cancelled_reason="Loss of quorum expected"),
            CITY_CLERK,
        )
    )

    a.assert_fields(
        cancelled,
        status="CANCELLED",
        cancelled_reason="Loss of quorum expected",
        notice_compliant=False,
    )
    a.assert_nulls(cancelled, "notice_posted_at")
    a.assert_status(fx.read_packet(ctx["packet"]["id"]), "WITHDRAWN")
    a.assert_status(fx.read_notice(ctx["agenda_notice"]["id"]), "VOID")
    notices = fx.list_notices_for_meeting(ctx["meeting"]["id"])
    assert len(notices) == 2, f"expected the agenda and cancellation notices, got {notices}"
    cancellation = [n for n in notices if n["notice_type"] == "CANCELLATION"]
    assert len(cancellation) == 1, f"expected one cancellation notice, got {notices}"
    a.assert_fields(
        cancellation[0],
        status="DRAFT",
        required_publication_count=1,
        publication_deadline_on="2026-09-15",
    )


def test_closing_the_request_supplies_the_series_its_retention_anchor():
    """The close is a transition on the request, yet what moves is the retention
    schedule: an anchor that did not exist appears, and the eligibility date lands
    five years after the closing date.

    PRD 3.8: "On success `fulfillment_status` becomes `CLOSED` and `closed_on`
    records the logical clock date — and if the request names a `target_series_id`
    whose series runs its retention from request closure, that closure has just
    supplied the series' retention anchor, so the series' eligibility date is
    recomputed on the spot."

    Design: Corner/state_machines/closing_a_records_request_reaches_across_to_recompute_the_series_retention_date
    """
    series = fx.create_record_series(
        retention_years=5, retention_trigger="REQUEST_CLOSURE"
    )
    validate_success(
        api_client.create_accession(
            series["id"], f.accession_payload(40, "2019-06-15"), RECORDS_OFFICER
        )
    )
    request = fx.create_records_request(
        ANONYMOUS,
        subject_description="Council correspondence 2019",
        target_series_id=series["id"],
    )
    validate_success(api_client.begin_review(request["id"], CITY_CLERK))
    validate_success(
        api_client.record_disposition(
            request["id"], f.disposition_payload("FULL_RELEASE"), CITY_CLERK
        )
    )
    a.assert_nulls(fx.read_record_series(series["id"]), "eligible_through_on")
    fx.set_clock("2026-08-20T00:00:00Z")

    closed = validate_success(api_client.close_records_request(request["id"], CITY_CLERK))

    a.assert_fields(closed, closed_on="2026-08-20")
    a.assert_axes(closed, fulfillment_status="CLOSED", fee_status="NOT_ASSESSED")
    after = fx.read_record_series(series["id"])
    a.assert_fields(after, eligible_through_on="2031-08-20")
    a.assert_custody_triple(after, total=40, active=40, destroyed=0)


def test_two_accessions_keep_the_ledger_balanced_and_walk_the_anchor_forward():
    """Custody reconciles at both observations, and the later accession date drags
    the eligibility calculation forward with it.

    PRD 3.9: "The accession advances `total_accessioned_count` by that count and
    `active_item_count` by the same count, and sets `last_accessioned_on` to the
    later of its existing value and the supplied date, so the anchor only ever moves
    forward."

    Design: Corner/state_machines/accessions_keep_the_series_custody_ledger_and_retention_anchor_in_sync
    """
    series = fx.create_record_series(
        series_code="CC-02", name="Building permit files", retention_years=5
    )

    first = validate_success(
        api_client.create_accession(
            series["id"], f.accession_payload(100, "2019-06-15"), RECORDS_OFFICER
        )
    )
    second = validate_success(
        api_client.create_accession(
            series["id"], f.accession_payload(50, "2019-07-20"), DEPUTY_CLERK
        )
    )

    a.assert_custody_triple(first, total=100, active=100, destroyed=0)
    a.assert_fields(
        first, last_accessioned_on="2019-06-15", eligible_through_on="2024-06-15"
    )
    a.assert_custody_triple(second, total=150, active=150, destroyed=0)
    a.assert_fields(
        second, last_accessioned_on="2019-07-20", eligible_through_on="2024-07-20"
    )


def test_locking_advances_the_pending_row_and_leaves_the_conflict_pair_where_it_stands():
    """The lock sweep is conditional on child state: the reviewable filing moves on
    while the two rows holding each other are deliberately passed over.

    PRD 3.7: "The editor may lock only from `OPEN` and only when the cycle holds at
    least one submission; the cycle moves `OPEN → LOCKED` and every submission of
    that cycle sitting in `PENDING` moves to `IN_REVIEW`."

    Design: Corner/state_machines/locking_a_cycle_advances_only_the_pending_submissions_and_leaves_the_conflict_pair_held
    """
    number_series = fx.create_number_series()
    pair = fx.code_title_with_open_cycle()
    title_id = pair["code_title"]["id"]
    cycle_id = pair["cycle"]["id"]
    contested = [
        fx.create_code_amendment(
            number_series["id"],
            title_id,
            "12.04.030",
            title=f"Amending 12.04.030 ({label})",
            full_text_length=length,
        )
        for label, length in (("first", 1800), ("second", 1900))
    ]
    uncontested = fx.create_code_amendment(
        number_series["id"],
        title_id,
        "12.04.040",
        title="Adding 12.04.040",
        full_text_length=1200,
    )
    held_one = fx.file_submission(cycle_id, contested[0]["id"], title_id, "12.04.030")
    held_two = fx.file_submission(cycle_id, contested[1]["id"], title_id, "12.04.030")
    pending = fx.file_submission(cycle_id, uncontested["id"], title_id, "12.04.040")

    locked = validate_success(
        api_client.lock_supplement_cycle(cycle_id, CODIFICATION_EDITOR)
    )

    a.assert_fields(
        locked,
        status="LOCKED",
        submission_count=3,
        client_submission_count=3,
        conflict_count=1,
    )
    a.assert_status(fx.read_submission(pending["id"]), "IN_REVIEW")
    first_held = fx.read_submission(held_one["id"])
    second_held = fx.read_submission(held_two["id"])
    a.assert_fields(
        first_held, status="CONFLICT_HELD", conflict_with_submission_id=held_two["id"]
    )
    a.assert_fields(
        second_held, status="CONFLICT_HELD", conflict_with_submission_id=held_one["id"]
    )
