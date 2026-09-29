"""The two deep cascades: an unsafe surface unwinding a schedule, and a positive sample unwinding results."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.fixtures import (
    build_judge_and_steward,
    build_posted_class,
    build_scheduled_class,
    card_judge_and_steward,
    get_class,
    get_class_entry,
    get_official,
    get_ring,
    get_show,
    get_slot,
    open_compliance_case,
    record_finding,
    record_footing_maintenance,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

SLOT_START = "2026-09-10T14:00:00Z"
HOLD_START = "2026-09-10T18:00:00Z"


def _empty_class_booked_with_two_officials():
    """An OPEN class with no entries booked at 14:00, judged and stewarded."""
    ctx = build_scheduled_class(entry_count=0, slot_start_utc=SLOT_START)
    ctx.update(build_judge_and_steward())
    ctx["assignments"] = card_judge_and_steward(ctx["slot_id"], ctx["judge_id"], ctx["steward_id"])
    return ctx


def _ring_slots(ring_id):
    body = api_client.list_ring_slots(
        TEST_USERS["ring_master_headers"], params={"ring_id": ring_id}
    ).json()
    return body["data"]


def test_unsafe_footing_pre_empts_the_whole_ring_down_four_cascade_links():
    """A pass that drops the surface to 45 fires every link in order. The ring goes on
    MAINTENANCE_HOLD; the 14:00-14:20 class occupancy is CANCELLED even though the 18:00-19:00
    hold window never touches it; the class falls back to OPEN with its estimate cleared; and
    both official assignments are RELEASED, each official's load decremented by the full
    50 warm-up-inclusive minutes from 13:30 to 14:20 rather than by the 20-minute ride window.

    PRD §3.3: "**The footing cascade.** A pass that drops an `AVAILABLE` ring's surface below 60 fires the deepest cascade in the system, because an unsafe surface pre-empts whatever was booked on it."
    PRD §3.3: "The maintenance occupancy is created for the hold window *without* the overlap check — deliberately, since the point is to displace existing bookings."
    PRD §3.3: "Then, in order: the ring moves `AVAILABLE → MAINTENANCE_HOLD`; every class occupancy on that ring whose `status` is `SCHEDULED` moves `SCHEDULED → CANCELLED`; for each occupancy so cancelled, its class reverts `SCHEDULED → OPEN` and that class's `estimated_minutes` is set back to null; and for each occupancy so cancelled, every official assignment on it whose `status` is `ACTIVE` moves `ACTIVE → RELEASED`, with that official's `assigned_minutes` decremented by exactly the whole minutes from the released occupancy's `warmup_start_utc` to its `end_utc`."
    PRD §3.3: "What differs is the posture the ring lands in, and the threshold is a footing score of 60."
    PRD §3.3: "`RELEASED` is terminal for an assignment."

    Design: Difficulty/transitive_cascade/footing_hold_unwinds_schedule_and_official_load
    """
    ctx = _empty_class_booked_with_two_officials()

    before = get_slot(ctx["slot_id"])
    assert before["duration_minutes"] == 20
    assert before["end_utc"] == "2026-09-10T14:20:00Z"
    assert before["warmup_start_utc"] == "2026-09-10T13:30:00Z"
    assert before["status"] == "SCHEDULED"
    assert get_official(ctx["judge_id"])["assigned_minutes"] == 50
    assert get_official(ctx["steward_id"])["assigned_minutes"] == 50

    validate_success(
        api_client.record_footing_maintenance(
            ctx["ring_id"],
            {
                "start_utc": HOLD_START,
                "duration_minutes": 60,
                "new_footing_condition_score": 45,
            },
            TEST_USERS["grounds_manager_headers"],
        )
    )

    ring = get_ring(ctx["ring_id"])
    assert ring["status"] == "MAINTENANCE_HOLD"
    assert ring["footing_condition_score"] == 45

    assert get_slot(ctx["slot_id"])["status"] == "CANCELLED"

    reverted = get_class(ctx["class_id"])
    assert reverted["status"] == "OPEN"
    assert reverted["estimated_minutes"] is None

    assert ctx["assignments"]["judge_assignment"]["status"] == "ACTIVE"
    for key in ("judge_assignment", "steward_assignment"):
        assignment_id = ctx["assignments"][key]["id"]
        released = validate_success(
            api_client.get_official_assignment(
                assignment_id, TEST_USERS["show_secretary_headers"]
            )
        )
        assert released["status"] == "RELEASED"

    assert get_official(ctx["judge_id"])["assigned_minutes"] == 0
    assert get_official(ctx["steward_id"])["assigned_minutes"] == 0


def test_maintenance_occupancy_replaces_the_cancelled_slot_and_repair_resurrects_nothing():
    """The synthesised hold occupancy is a real 18:00-19:00 booking: the ring's occupancy set
    now counts one slot for 60 minutes, because the CANCELLED class slot has left it entirely,
    and the surviving occupancy is re-indexed to first place. Repairing the surface to 80
    returns the ring to AVAILABLE, but the cancelled slot and the reopened class stay where the
    cascade left them.

    PRD §3.3: "Every footing pass, whatever the resulting score, does three things: it synthesises a maintenance occupancy on the ring for the requested window with the requested length, it rewrites `footing_condition_score` to `new_footing_condition_score`, and it recomputes the ring's `scheduled_minutes_total`, `slot_count` and the `order_index` of every occupancy on the ring, incrementing the ring's `version`."
    PRD §3.6: "The occupancies that count are those whose `status` is `SCHEDULED`, `RUNNING` or `COMPLETED`; they are sorted by `start_utc` ascending, with `created_at` ascending as the sole tie-break (`id` is never consulted), and each is assigned a 1-based `order_index` equal to its position in that sorted list."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."
    PRD §3.3: "A pass that leaves the surface at 60 or above from a ring already on `MAINTENANCE_HOLD` returns it `MAINTENANCE_HOLD → AVAILABLE`."
    PRD §3.3: "Slots cancelled during the hold are not resurrected by that return; they must be booked again from scratch."

    Design: Difficulty/transitive_cascade/footing_hold_unwinds_schedule_and_official_load
    """
    ctx = _empty_class_booked_with_two_officials()
    record_footing_maintenance(
        ctx["ring_id"],
        start_utc=HOLD_START,
        duration_minutes=60,
        new_footing_condition_score=45,
    )

    held = get_ring(ctx["ring_id"])
    assert held["slot_count"] == 1
    assert held["scheduled_minutes_total"] == 60

    slots = _ring_slots(ctx["ring_id"])
    assert len(slots) == 2
    maintenance = [row for row in slots if row["slot_type"] == "MAINTENANCE"]
    assert len(maintenance) == 1
    assert maintenance[0]["start_utc"] == HOLD_START
    assert maintenance[0]["end_utc"] == "2026-09-10T19:00:00Z"
    assert maintenance[0]["status"] == "SCHEDULED"
    assert maintenance[0]["order_index"] == 1

    repaired = record_footing_maintenance(
        ctx["ring_id"],
        start_utc="2026-09-10T20:00:00Z",
        duration_minutes=30,
        new_footing_condition_score=80,
    )
    assert repaired["status"] == "AVAILABLE"
    assert repaired["footing_condition_score"] == 80

    assert get_slot(ctx["slot_id"])["status"] == "CANCELLED"
    assert get_class(ctx["class_id"])["status"] == "OPEN"


def test_positive_sample_disqualifies_reverts_the_class_and_releases_the_prize_money():
    """A posted four-ribbon class with 38382 cents allocated is unwound by one positive drug
    finding. The winner's horse is suspended and only that horse; the winner's row is
    disqualified with its prize and placing cleared; the class walks backwards out of
    RESULTS_POSTED to JUDGED with nothing awarded and three placed rows left; and the money
    returns to the unallocated side of the pool in full. A drug test is not a welfare matter,
    so the show's strike count never moves.

    PRD §3.9: "A `POSITIVE` finding moves the case `OPEN → SUBSTANTIATED`, records `finding` as `POSITIVE`, and fires the second deep cascade in the system."
    PRD §3.9: "In order: the entry's horse has its `eligibility_status` set to `SUSPENDED`; then every class entry anywhere in the system whose parent entry names that same horse, whose own `status` is `ENTERED`, `CONFIRMED` or `COMPLETED`, and whose class is not `VOIDED`, moves to `DISQUALIFIED` with its `prize_cents` reset to 0 and its `placing` set back to null; then every class touched by those disqualifications whose `status` was `RESULTS_POSTED` reverts `RESULTS_POSTED → JUDGED` with its `awarded_prize_cents` reset to 0 and its `placed_count`, `entry_count`, `confirmed_entry_count` and `point_eligible` recomputed; and then the show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed per the prize ledger, so the money released by the reverted classes returns to the unallocated side."
    PRD §3.9: "Its consequence is a strike, not a suspension: the show's `welfare_strike_count` is recomputed as the number of that show's substantiated welfare citations — counted over cases whose `case_type` is `WELFARE_CITATION` and whose `status` is `SUBSTANTIATED`, reached through each case's entry — and no horse is suspended."
    PRD §3.9: "A new case has `status` of `OPEN` and `finding` of null."

    Design: Difficulty/transitive_cascade/positive_drug_finding_unwinds_results_and_prize_ledger
    """
    ctx = build_posted_class(entry_count=4, actual_minutes=26)
    winner, runner_up = ctx["field"][0], ctx["field"][1]

    posted = get_class(ctx["class_id"])
    assert posted["status"] == "RESULTS_POSTED"
    assert posted["awarded_prize_cents"] == 38382
    assert get_class_entry(winner["class_entry_id"])["prize_cents"] == 16688
    assert get_show(ctx["show_id"])["allocated_prize_cents"] == 38382

    case = open_compliance_case(
        winner["entry_id"], ctx["steward_id"], "DRUG_TEST", sample_code="DT-77104"
    )
    assert case["status"] == "OPEN"
    assert case["finding"] is None

    adjudicated = validate_success(
        api_client.record_case_finding(
            case["id"], {"finding": "POSITIVE"}, TEST_USERS["federation_officer_headers"]
        )
    )
    assert adjudicated["status"] == "SUBSTANTIATED"
    assert adjudicated["finding"] == "POSITIVE"

    suspended = validate_success(
        api_client.get_horse(winner["horse"]["id"], TEST_USERS["show_secretary_headers"])
    )
    assert suspended["eligibility_status"] == "SUSPENDED"
    untouched_horse = validate_success(
        api_client.get_horse(runner_up["horse"]["id"], TEST_USERS["show_secretary_headers"])
    )
    assert untouched_horse["eligibility_status"] == "ELIGIBLE"

    disqualified = get_class_entry(winner["class_entry_id"])
    assert disqualified["status"] == "DISQUALIFIED"
    assert disqualified["prize_cents"] == 0
    assert disqualified["placing"] is None

    second = get_class_entry(runner_up["class_entry_id"])
    assert second["status"] == "COMPLETED"
    assert second["placing"] == 2

    reverted = get_class(ctx["class_id"])
    assert reverted["status"] == "JUDGED"
    assert reverted["awarded_prize_cents"] == 0
    assert reverted["placed_count"] == 3

    show = get_show(ctx["show_id"])
    assert show["allocated_prize_cents"] == 0
    assert show["unallocated_prize_cents"] == 750000
    assert show["prize_money_pool_cents"] == 750000
    assert show["welfare_strike_count"] == 0


def test_adjudicated_case_cannot_replay_and_the_reverted_class_can_no_longer_be_voided():
    """The cascade runs once. A second finding on the substantiated case is refused, and the
    voiding path that was open while the class sat in RESULTS_POSTED is now closed, because
    link three already carried the class back to JUDGED. Neither refusal touches the ledger the
    cascade restored.

    PRD §3.9: "Only a case in `OPEN` may be adjudicated; otherwise `ERR_CASE_ALREADY_ADJUDICATED`."
    PRD §3.9: "`SUBSTANTIATED` and `DISMISSED` are terminal case states."
    PRD §3.8: "It moves the class `RESULTS_POSTED → VOIDED`, and only from `RESULTS_POSTED` — otherwise `ERR_CLASS_RESULTS_NOT_POSTED`."

    Design: Difficulty/transitive_cascade/positive_drug_finding_unwinds_results_and_prize_ledger
    """
    ctx = build_posted_class(entry_count=4, actual_minutes=26)
    winner = ctx["field"][0]
    set_clock("2026-09-10T13:30:00Z")

    case = open_compliance_case(
        winner["entry_id"], ctx["steward_id"], "DRUG_TEST", sample_code="DT-77104"
    )
    record_finding(case["id"], "POSITIVE")

    validate_error(
        api_client.record_case_finding(
            case["id"], {"finding": "NEGATIVE"}, TEST_USERS["federation_officer_headers"]
        ),
        "ERR_CASE_ALREADY_ADJUDICATED",
        409,
    )
    validate_error(
        api_client.void_class_results(ctx["class_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_CLASS_RESULTS_NOT_POSTED",
        409,
    )

    assert validate_success(
        api_client.get_compliance_case(case["id"], TEST_USERS["show_secretary_headers"])
    )["finding"] == "POSITIVE"
    assert get_class(ctx["class_id"])["status"] == "JUDGED"
    assert get_class(ctx["class_id"])["awarded_prize_cents"] == 0
    assert get_show(ctx["show_id"])["unallocated_prize_cents"] == 750000
