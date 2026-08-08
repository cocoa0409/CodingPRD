"""Motions, the roll-call vote, the SIMPLE/ABSOLUTE passage variants, the tabled
reconsideration cycle, and ballot-upsert conservation (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_motion_payload, assert_vote_tally_invariant,
    setup_open_action_item, setup_open_motion, setup_convened_meeting,
    open_agenda_item, move_motion, cast, close_motion, get_success_data,
)


# ===========================================================================
# Dual-variant passage rule: SIMPLE vs ABSOLUTE majority
# ===========================================================================

def test_simple_majority_carries_two_yea_one_nay(api):
    """PRD §3.5: "Under the `SIMPLE` variant the motion carries when `yea_count` is
    strictly greater than `nay_count`, and fails otherwise; abstentions and
    recusals are excluded from this comparison."

    2 YEA vs 1 NAY -> CARRIED.

    Design: Difficulty/dual_variant_calc/motion_simple_vs_absolute_majority
    """
    ctx = setup_open_motion(api, vote_threshold="SIMPLE", seat_count=5, quorum_size=3,
                            num_members=3, num_present=3)
    mo = ctx["motion"]["id"]
    m1, m2, m3 = [m["id"] for m in ctx["members"]]
    cast(api, ctx, mo, m1, "YEA")
    cast(api, ctx, mo, m2, "YEA")
    cast(api, ctx, mo, m3, "NAY")
    closed = close_motion(api, ctx, mo)
    assert closed["outcome"] == "CARRIED"
    assert closed["status"] == "CARRIED"


def test_absolute_majority_fails_two_yea_five_seats(api):
    """PRD §3.5: "Under the `ABSOLUTE` variant the motion carries when twice
    `yea_count` is strictly greater than the body's `seat_count` — a majority of the
    full authorized membership — and fails otherwise".

    Identical ballots (2 YEA, 1 NAY) on a 5-seat body: 2*2=4 is not > 5 -> FAILED.

    Design: Difficulty/dual_variant_calc/motion_simple_vs_absolute_majority
    """
    ctx = setup_open_motion(api, vote_threshold="ABSOLUTE", seat_count=5, quorum_size=3,
                            num_members=3, num_present=3)
    mo = ctx["motion"]["id"]
    m1, m2, m3 = [m["id"] for m in ctx["members"]]
    cast(api, ctx, mo, m1, "YEA")
    cast(api, ctx, mo, m2, "YEA")
    cast(api, ctx, mo, m3, "NAY")
    closed = close_motion(api, ctx, mo)
    assert closed["outcome"] == "FAILED"
    assert closed["status"] == "FAILED"


# ===========================================================================
# Non-linear state machine: OPEN -> TABLED -> OPEN reconsideration cycle
# ===========================================================================

def test_motion_reconsider_returns_to_open(api):
    """PRD §3.5: "The presiding officer may instead table an open motion
    `OPEN → TABLED`, then later reconsider it `TABLED → OPEN` (which again requires
    the meeting be `IN_SESSION`)".

    Design: Difficulty/non_linear_state_machine/motion_tabled_reconsider_cycle
    """
    ctx = setup_open_motion(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    mo = ctx["motion"]["id"]
    ph = ctx["presiding_headers"]
    validate_success(api.transition_motion(mo, {"to_status": "TABLED"}, ph))
    reopened = validate_success(api.transition_motion(mo, {"to_status": "OPEN"}, ph))
    assert reopened["status"] == "OPEN"


def test_motion_reconsider_retains_ballots(api):
    """PRD §3.5: "reconsideration retains the existing ballots."

    A ballot cast before tabling is still present after the TABLED -> OPEN cycle.

    Design: Difficulty/non_linear_state_machine/motion_tabled_reconsider_cycle
    """
    ctx = setup_open_motion(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    mo = ctx["motion"]["id"]
    ph = ctx["presiding_headers"]
    cast(api, ctx, mo, ctx["members"][0]["id"], "YEA")
    validate_success(api.transition_motion(mo, {"to_status": "TABLED"}, ph))
    reopened = validate_success(api.transition_motion(mo, {"to_status": "OPEN"}, ph))
    assert reopened["yea_count"] == 1
    assert reopened["ballot_count"] == 1


# ===========================================================================
# Compensating invariant: ballot upsert conserves ballot_count
# ===========================================================================

def test_recast_ballot_upserts_not_duplicates(api):
    """PRD §3.5: "Ballots are upserted one per member — re-casting replaces that
    member's prior ballot rather than adding a second."

    m1 casts YEA then re-casts NAY (upsert), then m2 casts YEA: yea 1, nay 1,
    ballot_count 2 (never 3).

    Design: Difficulty/compensating_invariant/vote_tally_conservation_ballots
    """
    ctx = setup_open_motion(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    mo = ctx["motion"]["id"]
    m1, m2 = ctx["members"][0]["id"], ctx["members"][1]["id"]
    cast(api, ctx, mo, m1, "YEA")
    cast(api, ctx, mo, m1, "NAY")
    final = cast(api, ctx, mo, m2, "YEA")
    assert final["yea_count"] == 1
    assert final["nay_count"] == 1
    assert final["ballot_count"] == 2


def test_ballot_count_equals_sum_of_value_counts(api):
    """PRD §3.5: "`ballot_count` is their sum" (of yea_count, nay_count,
    abstain_count, and recused_count).

    Design: Difficulty/compensating_invariant/vote_tally_conservation_ballots
    """
    ctx = setup_open_motion(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    mo = ctx["motion"]["id"]
    m1, m2 = ctx["members"][0]["id"], ctx["members"][1]["id"]
    cast(api, ctx, mo, m1, "YEA")
    cast(api, ctx, mo, m1, "NAY")
    final = cast(api, ctx, mo, m2, "YEA")
    assert_vote_tally_invariant(final)
    assert final["ballot_count"] == 2


# ===========================================================================
# Corner: motion validation errors
# ===========================================================================

def test_motion_mover_equals_seconder_rejected(api):
    """PRD §3.5: "the seconder must be distinct from the mover, else
    `ERR_MOVER_SECONDER_SAME`".

    Design: Corner/errors/motion_mover_equals_seconder_rejected
    """
    ctx = setup_open_action_item(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    m1 = ctx["members"][0]["id"]
    resp = api.create_motion(ctx["item"]["id"],
                             create_motion_payload(m1, m1, text="Self-second"),
                             ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_MOVER_SECONDER_SAME.value)


def test_motion_on_discussion_item_not_actionable(api):
    """PRD §3.5: "Only an `ACTION` item may carry motions; moving a motion under a
    non-`ACTION` item is rejected with `ERR_ITEM_NOT_ACTIONABLE`."

    Design: Corner/errors/motion_on_discussion_item_not_actionable
    """
    ctx = setup_convened_meeting(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    ctx["item"] = open_agenda_item(api, ctx, item_type="DISCUSSION")
    m1, m2 = ctx["members"][0]["id"], ctx["members"][1]["id"]
    resp = api.create_motion(ctx["item"]["id"],
                             create_motion_payload(m1, m2, text="Illegal motion"),
                             ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ACTIONABLE.value)


def test_motion_mover_not_present_rejected(api):
    """PRD §3.5: "The mover and seconder must each be present members of the meeting
    — each must appear in the meeting's `present_member_ids`, else
    `ERR_MEMBER_NOT_PRESENT`".

    Design: Corner/errors/motion_mover_not_present_rejected
    """
    ctx = setup_open_action_item(api, seat_count=5, quorum_size=2, num_members=3, num_present=2)
    m1 = ctx["members"][0]["id"]
    m3_absent = ctx["members"][2]["id"]
    resp = api.create_motion(ctx["item"]["id"],
                             create_motion_payload(m3_absent, m1, text="Absent mover"),
                             ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_PRESENT.value)
