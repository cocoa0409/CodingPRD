"""Three state machines that do not run in a straight line: the minutes
correction loop travelled twice, a meeting that falls back out of NOTICED and is
re-noticed by a second packet revision, and an ordinance that forks into a veto
and rejoins the publication path through an override.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CITY_CLERK

ORIGINAL_NARRATIVE = "The finance report was received and filed."
REFUSED_REWRITE = "Rejected rewrite that the body declined to adopt."
ADOPTED_REWRITE = "Adopted rewrite reflecting the corrected roll call."


def _approved_minutes_and_a_later_sitting():
    """Minutes approved at a second meeting, plus a third meeting in session at
    which corrections to them can be moved."""
    ctx = fx.approved_minutes_ready_for_correction(7)
    sitting = fx.additional_meeting_in_session(
        scheduled_start="2026-10-27T18:00:00Z",
        scheduled_end="2026-10-27T21:00:00Z",
        post_at="2026-10-24T18:00:00Z",
        convene_at="2026-10-27T18:00:00Z",
        present_member_count=7,
        item_types=["MINUTES"],
        venue_name="Correction Hearing Room",
        venue_address="11 Civic Plaza",
    )
    ctx["correction_meeting"] = sitting["meeting"]
    return ctx


def _move_correction(minutes_id, meeting_id, corrected_text, yes_count, no_count):
    """Park a corrected narrative and put it to the body at the later meeting."""
    fx.open_correction(minutes_id, corrected_text)
    motion = fx.record_motion(
        meeting_id, "MINUTES_CORRECTION", "SIMPLE", target_minutes_id=minutes_id
    )
    return fx.tally(motion["id"], yes_count, no_count)


def test_a_refused_correction_returns_the_record_to_approved_unchanged():
    """A MINUTES_CORRECTION losing two ayes to five discards the parked text, so
    the narrative and the revision number stand while the count still moves.

    PRD 3.4: "On a **failing** tally, `text_body` is left untouched and
    `revision_number` is left untouched."

    Design: Difficulty/non_linear_state_machine/minutes_correction_cycle_traversed_twice_with_divergent_branch_effects
    """
    ctx = _approved_minutes_and_a_later_sitting()
    minutes_id = ctx["minutes"]["id"]

    tallied = _move_correction(
        minutes_id, ctx["correction_meeting"]["id"], REFUSED_REWRITE, 2, 5
    )

    a.assert_vote_arithmetic(
        tallied, effective_base=7, required_yes=4, outcome="FAILED"
    )
    minutes = fx.read_minutes(minutes_id)
    a.assert_fields(
        minutes,
        status="APPROVED",
        text_body=ORIGINAL_NARRATIVE,
        revision_number=1,
        correction_count=1,
        approved_on="2026-10-27",
    )
    a.assert_nulls(minutes, "pending_correction_text")


def test_a_second_correction_carried_after_a_refusal_adopts_the_new_narrative():
    """Travelling the loop twice leaves revision_number at 2 but correction_count
    at 2 as well, because a refused correction is still counted.

    PRD 3.4: "On a **passing** tally, `text_body` is replaced by
    `pending_correction_text` and `revision_number` advances by 1."

    Design: Difficulty/non_linear_state_machine/minutes_correction_cycle_traversed_twice_with_divergent_branch_effects
    """
    ctx = _approved_minutes_and_a_later_sitting()
    minutes_id = ctx["minutes"]["id"]
    correction_meeting_id = ctx["correction_meeting"]["id"]
    _move_correction(minutes_id, correction_meeting_id, REFUSED_REWRITE, 2, 5)

    carried = _move_correction(
        minutes_id, correction_meeting_id, ADOPTED_REWRITE, 6, 1
    )

    a.assert_vote_arithmetic(
        carried, effective_base=7, required_yes=4, outcome="PASSED"
    )
    minutes = fx.read_minutes(minutes_id)
    a.assert_fields(
        minutes,
        status="APPROVED",
        text_body=ADOPTED_REWRITE,
        revision_number=2,
        correction_count=2,
        approved_on="2026-10-27",
    )
    a.assert_nulls(minutes, "pending_correction_text")


def _meeting_noticed_by_its_first_packet():
    """A meeting driven to NOTICED behind revision 1, posted on 2026-09-10."""
    base = fx.scheduled_meeting()
    first_packet = fx.draft_packet(base["meeting"]["id"])
    fx.add_item(first_packet["id"], 1, "REPORT", title="Draft agenda, first issue")
    fx.set_clock("2026-09-10T00:00:00Z")
    fx.post_packet(first_packet["id"])
    return {
        "meeting_id": base["meeting"]["id"],
        "first_packet": first_packet,
        "first_notice": fx.sole_notice_for_meeting(base["meeting"]["id"]),
    }


def test_withdrawing_the_posted_packet_walks_the_meeting_back_to_scheduled():
    """Withdrawal clears the mirrored notice fields and voids the agenda notice
    the posting had raised.

    PRD 3.2: "Withdrawing the packet that was `POSTED` returns the meeting
    `NOTICED → SCHEDULED`, sets `notice_posted_at` and `required_notice_hours`
    back to null and `notice_compliant` back to false, advances the meeting's
    `version`, and voids that meeting's `MEETING_AGENDA` publication notice if it
    sits in `DRAFT` or `ORDERED`."

    Design: Difficulty/non_linear_state_machine/meeting_returns_from_noticed_to_scheduled_and_is_re_noticed_by_revision_two
    """
    ctx = _meeting_noticed_by_its_first_packet()
    fx.set_clock("2026-09-11T00:00:00Z")

    withdrawn = validate_success(
        api_client.withdraw_agenda_packet(ctx["first_packet"]["id"], CITY_CLERK)
    )

    a.assert_fields(withdrawn, status="WITHDRAWN", revision_number=1)
    meeting = fx.read_meeting(ctx["meeting_id"])
    a.assert_status(meeting, "SCHEDULED")
    a.assert_no_mirrored_notice(meeting)
    a.assert_status(fx.read_notice(ctx["first_notice"]["id"]), "VOID")


def test_revision_two_re_notices_the_same_meeting_beside_the_voided_notice():
    """A second packet posted at the deadline instant returns the meeting to
    NOTICED with a fresh DRAFT notice, while the voided first notice stays on the
    meeting's ledger.

    PRD 3.2: "The packet travels `DRAFT → POSTED`, the meeting travels
    `SCHEDULED → NOTICED`, the meeting's `version` advances, and
    `notice_posted_at`, `required_notice_hours` and `notice_compliant` are
    mirrored from the packet onto the meeting."

    Design: Difficulty/non_linear_state_machine/meeting_returns_from_noticed_to_scheduled_and_is_re_noticed_by_revision_two
    """
    ctx = _meeting_noticed_by_its_first_packet()
    fx.set_clock("2026-09-11T00:00:00Z")
    validate_success(
        api_client.withdraw_agenda_packet(ctx["first_packet"]["id"], CITY_CLERK)
    )
    second_packet = fx.draft_packet(ctx["meeting_id"])
    fx.add_item(second_packet["id"], 1, "REPORT", title="Draft agenda, second issue")
    fx.set_clock("2026-09-12T18:00:00Z")

    reposted = fx.post_packet(second_packet["id"])

    a.assert_fields(
        reposted,
        status="POSTED",
        revision_number=2,
        posted_at="2026-09-12T18:00:00Z",
        notice_deadline_at="2026-09-12T18:00:00Z",
        notice_compliant=True,
    )
    meeting = fx.read_meeting(ctx["meeting_id"])
    a.assert_status(meeting, "NOTICED")
    a.assert_meeting_notice_mirror(
        meeting,
        posted_at="2026-09-12T18:00:00Z",
        required_notice_hours=72,
        notice_compliant=True,
    )
    rows, meta = validate_paginated(
        api_client.list_publication_notices(CITY_CLERK, {"meeting_id": ctx["meeting_id"]})
    )
    a.assert_pagination_meta(meta, total_count=2)
    replacement = [row for row in rows if row["status"] == "DRAFT"]
    assert len(replacement) == 1, f"expected exactly one live notice, got {rows}"
    a.assert_fields(replacement[0], publication_deadline_on="2026-09-14")
    assert (
        fx.read_notice(ctx["first_notice"]["id"])["status"] == "VOID"
    ), "the notice raised by revision 1 stays VOID on the meeting's ledger"


VETO_REASON = "The overnight parking restriction exceeds the enabling authority."


def _vetoed_ordinance_and_an_override_sitting():
    """An officialized ordinance vetoed by the presiding officer, plus a third
    meeting in session at which the override can be moved."""
    scenario = fx.vetoed_ordinance(
        veto_reason=VETO_REASON,
        instrument_overrides={
            "full_text_length": 1200,
            "title": "An ordinance restricting overnight parking",
        },
    )
    sitting = fx.additional_meeting_in_session(
        scheduled_start="2026-10-13T18:00:00Z",
        scheduled_end="2026-10-13T21:00:00Z",
        post_at="2026-10-06T19:00:00Z",
        convene_at="2026-10-13T18:00:00Z",
        present_member_count=7,
        item_types=["ORDINANCE_ADOPTION"],
        venue_name="Veto Hearing Room",
        venue_address="13 Civic Plaza",
    )
    scenario["override_meeting"] = sitting["meeting"]
    return scenario


def _carry_the_override(scenario):
    motion = fx.record_motion(
        scenario["override_meeting"]["id"],
        "VETO_OVERRIDE",
        "FOUR_FIFTHS",
        instrument_id=scenario["instrument"]["id"],
    )
    return fx.tally(motion["id"], 6, 1)


def _live_notice_for(instrument_id):
    notices = fx.list_notices_for_instrument(instrument_id)
    live = [row for row in notices if row["status"] != "VOID"]
    assert len(live) == 1, f"expected exactly one live notice, got {notices}"
    return live[0]


def test_the_veto_records_its_reason_and_voids_the_adoption_notice():
    """Vetoing the numbered ordinance leaves it VETOED with the reason on the
    record and kills the DRAFT notice adoption had raised.

    PRD 3.5: "The officer supplies `veto_reason`, which is recorded on the
    instrument and is null on any instrument that was never vetoed; the
    instrument moves `ADOPTED → VETOED` and its publication notice, if one is
    sitting in `DRAFT` or `ORDERED`, is voided."

    Design: Difficulty/non_linear_state_machine/instrument_veto_fork_rejoins_the_publication_path_after_override
    """
    scenario = fx.vetoed_ordinance(
        veto_reason=VETO_REASON,
        instrument_overrides={
            "full_text_length": 1200,
            "title": "An ordinance restricting overnight parking",
        },
    )

    a.assert_fields(
        scenario["instrument"],
        status="VETOED",
        veto_reason=VETO_REASON,
        assigned_number="ORD-2026-001",
    )
    a.assert_status(scenario["first_notice"], "VOID")


def test_a_four_fifths_override_revives_the_ordinance_with_a_replacement_notice():
    """Six ayes of a house of seven clear the four-fifths bar, moving the
    instrument to VETO_OVERRIDDEN and raising a second DRAFT notice.

    PRD 3.5: "A veto is not the end: a `VETO_OVERRIDE` motion carrying that
    instrument's `instrument_id`, tallied under the `FOUR_FIFTHS` rule and
    passing, moves the instrument `VETOED → VETO_OVERRIDDEN` and causes a
    **replacement** publication notice to be created in `DRAFT`, since the
    original was voided."

    Design: Difficulty/non_linear_state_machine/instrument_veto_fork_rejoins_the_publication_path_after_override
    """
    scenario = _vetoed_ordinance_and_an_override_sitting()

    carried = _carry_the_override(scenario)

    a.assert_vote_arithmetic(
        carried, effective_base=7, required_yes=6, outcome="PASSED"
    )
    a.assert_status(fx.read_instrument(scenario["instrument"]["id"]), "VETO_OVERRIDDEN")
    replacement = _live_notice_for(scenario["instrument"]["id"])
    a.assert_fields(
        replacement,
        status="DRAFT",
        notice_type="ORDINANCE_FULL_TEXT",
        required_publication_count=2,
        publication_deadline_on="2026-10-21",
    )
    rows, meta = validate_paginated(
        api_client.list_publication_notices(
            CITY_CLERK, {"instrument_id": scenario["instrument"]["id"]}
        )
    )
    a.assert_pagination_meta(meta, total_count=2)
    assert sorted(row["status"] for row in rows) == ["DRAFT", "VOID"]


def test_the_revived_ordinance_rejoins_publication_and_takes_its_effective_date():
    """Ordering and certifying the replacement notice bills 17500 cents and
    carries the instrument VETO_OVERRIDDEN to PUBLISHED on the ordinary
    publication-plus-thirty basis.

    PRD 3.6: "For an ordinance notice, **hop 2** follows immediately: the
    instrument mirrors `publication_completed_on` from the notice, its
    `effective_date_basis` and `effective_date` are computed by the rules in
    section 3.5, and the instrument moves `ADOPTED → PUBLISHED` or, when it had
    been revived by an override, `VETO_OVERRIDDEN → PUBLISHED`."

    Design: Difficulty/non_linear_state_machine/instrument_veto_fork_rejoins_the_publication_path_after_override
    """
    scenario = _vetoed_ordinance_and_an_override_sitting()
    _carry_the_override(scenario)
    replacement = _live_notice_for(scenario["instrument"]["id"])
    fx.ordered_notice(
        replacement["id"],
        ["2026-10-09", "2026-10-16"],
        column_inches=12.50,
        affidavit_required=True,
    )
    fx.set_clock("2026-10-16T09:00:00Z")

    certified = validate_success(
        api_client.certify_publication(
            replacement["id"], f.certify_publication_payload("2026-10-16"), CITY_CLERK
        )
    )

    a.assert_status(certified, "PUBLISHED")
    a.assert_invoice(
        certified, gross_cost_cents=12500, discount_pct=0.0, invoice_total_cents=17500
    )
    instrument = fx.read_instrument(scenario["instrument"]["id"])
    a.assert_fields(
        instrument,
        status="PUBLISHED",
        veto_reason=VETO_REASON,
        assigned_number="ORD-2026-001",
        publication_completed_on="2026-10-16",
        effective_date_basis="PUBLICATION_PLUS_30",
        effective_date="2026-11-16",
    )
