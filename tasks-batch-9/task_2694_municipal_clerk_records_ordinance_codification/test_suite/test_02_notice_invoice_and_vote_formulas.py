"""Three composed formulas: the statutory notice hours a packet owes, the
newspaper invoice an insertion order prices, and the arithmetic that resolves a
motion.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CITY_CLERK


def _two_meetings_sharing_one_start():
    """A planning-commission special meeting and a council regular meeting that
    begin at the same instant in two different rooms."""
    planning_room = fx.create_venue(name="Planning Room", address="2 Civic Plaza", capacity=60)
    chamber = fx.create_venue(name="Council Chamber", address="1 Civic Plaza", capacity=120)
    commission = fx.create_meeting(
        planning_room["id"],
        body_type="PLANNING_COMMISSION",
        meeting_type="SPECIAL",
        scheduled_start="2026-09-15T18:00:00Z",
        scheduled_end="2026-09-15T20:00:00Z",
        quorum_required=3,
    )
    council = fx.create_meeting(chamber["id"])
    hearing_packet = fx.draft_packet(commission["id"], late_addendum=True)
    fx.add_item(
        hearing_packet["id"],
        1,
        "PUBLIC_HEARING",
        title="Public hearing on the Elm Street rezoning",
    )
    plain_packet = fx.draft_packet(council["id"], late_addendum=False)
    fx.add_item(plain_packet["id"], 1, "REPORT", title="Quarterly finance report")
    fx.set_clock("2026-08-25T00:00:00Z")
    return {
        "commission": commission,
        "council": council,
        "hearing_packet": hearing_packet,
        "plain_packet": plain_packet,
    }


def test_hearing_addendum_and_body_multiplier_stack_into_360_notice_hours():
    """A special planning-commission packet carrying a public hearing and flagged
    a late addendum owes (48 + 168 + 24) x 1.5 = 360 hours.

    PRD 3.2: "The three components are summed first, and the sum is then
    multiplied by a multiplier keyed on the governing body: 1.0 for `COUNCIL`,
    and 1.5 for both `PLANNING_COMMISSION` and `BOARD_OF_ADJUSTMENT`."

    Design: Difficulty/combinatorial_formula/notice_hours_combine_meeting_type_hearing_addendum_and_body_multiplier
    """
    ctx = _two_meetings_sharing_one_start()

    posted = validate_success(
        api_client.post_agenda_packet(ctx["hearing_packet"]["id"], CITY_CLERK)
    )

    a.assert_fields(
        posted,
        contains_public_hearing=True,
        required_notice_hours=360,
        notice_deadline_at="2026-08-31T18:00:00Z",
        notice_compliant=True,
    )


def test_a_plain_regular_council_packet_owes_only_the_72_hour_base():
    """The same posting instant on a council regular meeting with neither a
    hearing nor an addendum owes 72 hours, deadline 2026-09-12T18:00:00Z.

    PRD 3.2: "`notice_deadline_at` is then the meeting's `scheduled_start` minus
    `required_notice_hours` hours."

    Design: Difficulty/combinatorial_formula/notice_hours_combine_meeting_type_hearing_addendum_and_body_multiplier
    """
    ctx = _two_meetings_sharing_one_start()

    posted = validate_success(
        api_client.post_agenda_packet(ctx["plain_packet"]["id"], CITY_CLERK)
    )

    a.assert_fields(
        posted,
        contains_public_hearing=False,
        required_notice_hours=72,
        notice_deadline_at="2026-09-12T18:00:00Z",
    )


def test_both_meetings_mirror_their_own_notice_hours_after_posting():
    """Two meetings starting at the same instant end up NOTICED with 360 and 72
    mirrored hours respectively.

    PRD 2.10: "A meeting mirrors the notice arithmetic of whichever of its agenda
    packets is currently posted: `Meeting.notice_posted_at`,
    `Meeting.required_notice_hours` and `Meeting.notice_compliant` reproduce
    `posted_at`, `required_notice_hours` and `notice_compliant` from the packet
    whose `meeting_id` is that meeting and whose `status` is `POSTED`."

    Design: Difficulty/combinatorial_formula/notice_hours_combine_meeting_type_hearing_addendum_and_body_multiplier
    """
    ctx = _two_meetings_sharing_one_start()
    fx.post_packet(ctx["hearing_packet"]["id"])
    fx.post_packet(ctx["plain_packet"]["id"])

    commission = fx.read_meeting(ctx["commission"]["id"])
    council = fx.read_meeting(ctx["council"]["id"])

    a.assert_fields(commission, required_notice_hours=360, status="NOTICED")
    a.assert_fields(council, required_notice_hours=72, status="NOTICED")


def test_the_agenda_notice_owes_one_insertion_by_the_day_before_the_meeting():
    """Posting a council packet raises a MEETING_AGENDA notice owing a single
    insertion no later than 2026-09-14.

    PRD 3.6: "For a `MEETING_AGENDA` notice it is the calendar date of the
    meeting's `scheduled_start` minus one day — the agenda must be in the paper
    before the day of the meeting."

    Design: Difficulty/combinatorial_formula/publication_invoice_combines_rate_tier_and_post_discount_affidavit
    """
    ctx = fx.noticed_meeting()

    notice = ctx["agenda_notice"]

    a.assert_fields(
        notice,
        required_publication_count=1,
        publication_deadline_on="2026-09-14",
        status="DRAFT",
    )


def test_the_volume_tier_is_keyed_on_a_gross_that_excludes_the_affidavit():
    """320.00 column inches on one insertion gross 160000 cents, earn the 0.10
    tier, and bill 146500 once the affidavit is added afterwards.

    PRD 3.6: "Only then is the affidavit added: 2,500 cents per insertion when
    `affidavit_required` is true and nothing when it is false, added **after**
    the discount rather than before it."

    Design: Difficulty/combinatorial_formula/publication_invoice_combines_rate_tier_and_post_discount_affidavit
    """
    ctx = fx.noticed_meeting()
    fx.set_clock("2026-09-12T18:00:00Z")

    ordered = validate_success(
        api_client.order_publication(
            ctx["agenda_notice"]["id"],
            f.publication_order_payload(
                ["2026-09-14"], column_inches=320.00, affidavit_required=True
            ),
            CITY_CLERK,
        )
    )

    a.assert_invoice(
        ordered, gross_cost_cents=160000, discount_pct=0.10, invoice_total_cents=146500
    )
    a.assert_status(ordered, "ORDERED")


def test_a_recusal_shrinks_the_base_while_an_abstention_does_not():
    """Three ayes to two noes with one abstention and one recusal fails under
    SIMPLE on a base of 6 requiring 4.

    PRD 3.3: "`effective_base` is the meeting's `present_member_count` less
    `recused_count` — recusals leave the base, abstentions stay in it."

    Design: Difficulty/combinatorial_formula/vote_outcome_combines_majority_rule_recusal_abstention_and_tie_break
    """
    ctx = fx.in_session_meeting(7)
    motion = fx.record_motion(ctx["meeting"]["id"], "PROCEDURAL", "SIMPLE")

    tallied = validate_success(
        api_client.tally_motion(
            motion["id"], f.tally_payload(3, 2, abstain_count=1, recused_count=1), CITY_CLERK
        )
    )

    a.assert_vote_arithmetic(
        tallied, effective_base=6, required_yes=4, outcome="FAILED", tie_break_used=False
    )
    a.assert_status(tallied, "TALLIED")


def test_two_thirds_of_a_full_house_of_seven_requires_five_ayes():
    """Five ayes to two noes with nobody recused passes under TWO_THIRDS on a
    base of 7 requiring 5.

    PRD 3.3: "`required_yes` is then derived from `majority_rule` on that base:
    under `SIMPLE` it is half the base discarding any remainder, plus one; under
    `TWO_THIRDS` it is two thirds of the base rounded up to a whole member; under
    `FOUR_FIFTHS` it is four fifths of the base rounded up to a whole member; and
    under `UNANIMOUS_CONSENT` it is the whole base."

    Design: Difficulty/combinatorial_formula/vote_outcome_combines_majority_rule_recusal_abstention_and_tie_break
    """
    ctx = fx.in_session_meeting(7)
    motion = fx.record_motion(ctx["meeting"]["id"], "PROCEDURAL", "TWO_THIRDS")

    tallied = validate_success(
        api_client.tally_motion(motion["id"], f.tally_payload(5, 2), CITY_CLERK)
    )

    a.assert_vote_arithmetic(
        tallied, effective_base=7, required_yes=5, outcome="PASSED", tie_break_used=False
    )


def test_the_presiding_tie_break_carries_an_exact_tie_under_simple_majority():
    """Three ayes to three noes with one recusal is an exact tie under SIMPLE, so
    an aye tie-break carries the motion as TIE_BROKEN_PASSED.

    PRD 3.3: "Otherwise, if the ayes exactly equal the nays, the rule in force is
    `SIMPLE`, and a `presiding_tie_break` was supplied, the presiding officer's
    vote decides: the outcome is `TIE_BROKEN_PASSED` when the tie-break is `YES`
    and `TIE_BROKEN_FAILED` when it is `NO`, and `tie_break_used` is set true."

    Design: Difficulty/combinatorial_formula/vote_outcome_combines_majority_rule_recusal_abstention_and_tie_break
    """
    ctx = fx.in_session_meeting(7)
    motion = fx.record_motion(ctx["meeting"]["id"], "PROCEDURAL", "SIMPLE")

    tallied = validate_success(
        api_client.tally_motion(
            motion["id"],
            f.tally_payload(3, 3, recused_count=1, presiding_tie_break="YES"),
            CITY_CLERK,
        )
    )

    a.assert_vote_arithmetic(
        tallied,
        effective_base=6,
        required_yes=4,
        outcome="TIE_BROKEN_PASSED",
        tie_break_used=True,
    )
