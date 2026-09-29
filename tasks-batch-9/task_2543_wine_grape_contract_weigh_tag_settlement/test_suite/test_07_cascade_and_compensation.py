"""Two long cascades in opposite directions: a grading that fills the cap and empties
the crush-pad lane, and a dispute that gives the capacity back."""
from test_helpers import (
    dispute_grading,
    list_gradings,
    list_settlement_lines,
    move_clock,
    read_appointment,
    read_contract,
    read_lane,
    read_pick_call,
    read_weigh_tag,
    record_grading,
    setup_cap_cascade_pad,
)

DISPUTE_AT = "2026-08-26T09:00:00Z"


def _capping_grade(ctx: dict) -> dict:
    """Grade the second load at Brix 21.5, taking the contract to exactly 40.000 tons."""
    return record_grading(ctx["tag2"]["id"], brix=21.5, ta_gl=6.5, ph=3.30, rot_pct=1.0, mog_pct=0.5)


def test_capping_grade_prices_the_load_and_fills_the_soft_cap():
    """The second 18.000-ton load is priced at its own 2.0 point penalty and takes the
    contract's delivered contract tonnage to exactly `committed_tons`.

    PRD: "`CAP_REACHED` once `delivered_contract_tons` reaches or exceeds
    `contract_cap_tons`"

    Design: Difficulty/transitive_cascade/grading_cap_reached_cascade_to_lane_committed_tons
    """
    ctx = setup_cap_cascade_pad()
    _capping_grade(ctx)

    lines = list_settlement_lines(weigh_tag_id=ctx["tag2"]["id"])
    assert len(lines) == 1
    assert lines[0]["bucket"] == "CONTRACT"
    assert float(lines[0]["tons"]) == 18.000
    assert lines[0]["price_per_ton_cents"] == 441000
    assert lines[0]["provisional_amount_cents"] == 4762800

    contract = read_contract(ctx["contract"]["id"])
    assert float(contract["delivered_contract_tons"]) == 40.000
    assert float(contract["delivered_over_tons"]) == 0.000
    assert contract["tonnage_status"] == "CAP_REACHED"
    assert contract["provisional_settlement_cents"] == 11178000


def test_capping_grade_suspends_the_acknowledged_call_short_of_fulfilment():
    """The call asked for 45.000 tons and only 40.000 could be taken, so the fulfilment
    edge cannot fire and the cap suspension does.

    PRD: "If the posture leaves `OPEN`, every pick call of the contract in `ISSUED` or
    `ACKNOWLEDGED` is suspended to `SUSPENDED_CAP`"

    Design: Difficulty/transitive_cascade/grading_cap_reached_cascade_to_lane_committed_tons
    """
    ctx = setup_cap_cascade_pad()
    _capping_grade(ctx)

    pick_call = read_pick_call(ctx["pick_call"]["id"])
    assert pick_call["status"] == "SUSPENDED_CAP"
    assert float(pick_call["delivered_net_tons"]) == 40.000
    assert float(pick_call["fulfillment_pct"]) == 88.9


def test_cap_suspension_cancels_the_reserved_slot_and_closes_the_weighed_one():
    """The third slot was never weighed, so the suspension cancels it; the slot whose
    only load has just been graded closes instead.

    PRD: "the `SCHEDULED` appointments of those suspended calls are cancelled"

    Design: Difficulty/transitive_cascade/grading_cap_reached_cascade_to_lane_committed_tons
    """
    ctx = setup_cap_cascade_pad()
    _capping_grade(ctx)

    assert read_appointment(ctx["appointments"][2]["id"])["status"] == "CANCELLED"
    assert read_appointment(ctx["appointments"][1]["id"])["status"] == "CLOSED"


def test_cap_cascade_empties_a_lane_the_request_never_mentioned():
    """The grading request names only a weigh tag, yet the lane's committed load and
    appointment count fall to zero five hops later.

    PRD: "each affected lane's `committed_tons` and `scheduled_appointment_count` are
    recomputed"

    Design: Difficulty/transitive_cascade/grading_cap_reached_cascade_to_lane_committed_tons
    """
    ctx = setup_cap_cascade_pad()

    before = read_lane(ctx["lane"]["id"])
    assert float(before["committed_tons"]) == 43.000
    assert before["scheduled_appointment_count"] == 2

    _capping_grade(ctx)

    after = read_lane(ctx["lane"]["id"])
    assert float(after["committed_tons"]) == 0.000
    assert after["scheduled_appointment_count"] == 0
    assert float(read_pick_call(ctx["pick_call"]["id"])["appointed_tons"]) == 0.000


def test_capping_load_keeps_its_whole_tonnage_in_the_contract_bucket():
    """The load fits under the cap exactly, so nothing spills into the over-delivery or
    rejected slices.

    PRD: "Whenever a load's tonnage is divided into slices, the slices are guaranteed to
    sum to exactly the load's `net_tons` — no ton is ever created or lost by rounding."

    Design: Difficulty/transitive_cascade/grading_cap_reached_cascade_to_lane_committed_tons
    """
    ctx = setup_cap_cascade_pad()
    _capping_grade(ctx)

    tag = read_weigh_tag(ctx["tag2"]["id"])
    assert tag["disposition"] == "ACCEPTED"
    assert float(tag["contract_slice_tons"]) == 18.000
    assert float(tag["over_slice_tons"]) == 0.000
    assert float(tag["over_rejected_tons"]) == 0.000
    assert float(tag["excess_rejected_tons"]) == 0.000


def _capped_then_disputed() -> dict:
    """The capped pad of the previous instance, then a producer dispute on the load that
    filled the cap."""
    ctx = setup_cap_cascade_pad()
    _capping_grade(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(
        ctx["tag2"]["id"], ctx["grower"]["id"], reason="grower disputes the Brix reading on the second load"
    )
    return ctx


def test_dispute_supersedes_the_active_grade_and_voids_only_its_own_line():
    """The dispute reaches exactly one grading and exactly one line; the first load's
    provisional money is untouched.

    PRD: "The active grading receives `superseded_at` from the logical clock."

    Design: Difficulty/transitive_cascade/grade_dispute_compensating_cascade_reopens_cap_and_pick_call
    """
    ctx = _capped_then_disputed()

    tag = read_weigh_tag(ctx["tag2"]["id"])
    assert tag["disposition"] == "DISPUTED"
    assert tag["weigh_status"] == "NET_FINAL"
    assert float(tag["contract_slice_tons"]) == 0.000
    assert float(tag["over_slice_tons"]) == 0.000
    assert tag["active_adjustment_pct"] is None

    gradings = list_gradings(weigh_tag_id=ctx["tag2"]["id"])
    assert len(gradings) == 1
    assert gradings[0]["superseded_at"] == DISPUTE_AT

    disputed_lines = list_settlement_lines(weigh_tag_id=ctx["tag2"]["id"])
    assert [line["status"] for line in disputed_lines] == ["VOID"]
    assert disputed_lines[0]["voided_at"] == DISPUTE_AT
    untouched_lines = list_settlement_lines(weigh_tag_id=ctx["tag1"]["id"])
    assert [line["status"] for line in untouched_lines] == ["PROVISIONAL"]


def test_dispute_returns_capacity_and_reopens_the_cap_posture():
    """Voided lines are excluded from consumption, so the contract drops back below its
    soft cap and its provisional money falls with it.

    PRD: "In either case, consumption counts only lines whose status is `PROVISIONAL` or
    `FINAL` — voided lines are excluded, which is exactly what returns capacity to a
    contract after a dispute."

    Design: Difficulty/transitive_cascade/grade_dispute_compensating_cascade_reopens_cap_and_pick_call
    """
    ctx = _capped_then_disputed()

    contract = read_contract(ctx["contract"]["id"])
    assert float(contract["delivered_contract_tons"]) == 22.000
    assert float(contract["rejected_tons"]) == 0.000
    assert contract["tonnage_status"] == "OPEN"
    assert contract["provisional_settlement_cents"] == 6415200


def test_dispute_reissues_the_suspended_call_with_fresh_notice_figures():
    """The re-opened cap posture sends the suspended call back to `ISSUED`, and its
    acknowledgement clock restarts from the dispute instant.

    PRD: "Because the cap posture may have returned to `OPEN`, every pick call of the
    contract sitting in `SUSPENDED_CAP` transitions back to `ISSUED` with its notice
    figures re-stamped."

    Design: Difficulty/transitive_cascade/grade_dispute_compensating_cascade_reopens_cap_and_pick_call
    """
    ctx = _capped_then_disputed()

    pick_call = read_pick_call(ctx["pick_call"]["id"])
    assert pick_call["status"] == "ISSUED"
    assert pick_call["acknowledged_at"] is None
    assert pick_call["issued_at"] == DISPUTE_AT
    assert pick_call["ack_deadline_at"] == "2026-08-27T09:00:00Z"


def test_dispute_compensation_leaves_the_cancelled_slot_cancelled():
    """The unwind is deliberately partial: the slot the cap cascade cancelled is not
    resurrected, so the lane stays empty.

    PRD: "`fulfillment_pct` is `delivered_net_tons` divided by `estimated_tons`,
    multiplied by 100, rounded half up to 1 decimal."

    Design: Difficulty/transitive_cascade/grade_dispute_compensating_cascade_reopens_cap_and_pick_call
    """
    ctx = _capped_then_disputed()

    assert read_appointment(ctx["appointments"][2]["id"])["status"] == "CANCELLED"
    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == 0.000
    pick_call = read_pick_call(ctx["pick_call"]["id"])
    assert float(pick_call["appointed_tons"]) == 0.000
    assert float(pick_call["delivered_net_tons"]) == 22.000
    assert float(pick_call["fulfillment_pct"]) == 48.9
