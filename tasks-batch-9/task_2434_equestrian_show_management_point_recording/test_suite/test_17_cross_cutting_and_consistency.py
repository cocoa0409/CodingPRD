"""Cross-cutting layers: ring-version concurrency, a show-wide threshold, and an all-or-nothing saga."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import create_ring_slot_payload
from test_helpers.fixtures import (
    book_slot,
    build_active_coverage,
    build_approved_show,
    build_judge_and_steward,
    build_multi_class_show,
    card_judge_and_steward,
    confirmed_rows_for_class,
    default_placings,
    get_class,
    get_class_entry,
    get_entry,
    get_ring,
    get_show,
    get_slot,
    open_compliance_case,
    record_finding,
    record_results,
    ring_version,
    stage_class_slot,
    start_slot,
    withdraw_entry,
)
from test_helpers.test_users import TEST_USERS

SECRETARY = TEST_USERS["show_secretary_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]


def test_two_bookings_from_one_ring_snapshot_cannot_both_land():
    """The running order is one artifact, so the booking guard is the parent ring's version rather
    than the slot's: two ring masters holding the same read cannot both write. The first booking
    succeeds and moves the ring on; the second, replaying the version it read, is refused as stale
    even though its time is hours clear of the first occupancy and its class is untouched. The
    refusal left nothing behind — the version did not move, the ring still counts one occupancy, and
    the second class is still open with no estimate — and the retry against the fresh version lands.

    PRD §2.7: "Booking a class into a ring — `POST /ring-slots` — requires `expected_ring_version` in the request body, carrying the client's last observed `version` of the target ring."
    PRD §2.7: "The value must equal the target `Ring`'s current `version`; when it does not, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "The reason is that a ring's running order is one ordered artifact: any earlier accepted booking, or a footing-maintenance hold, renumbers `order_index` across the whole ring and legitimately supersedes the layout the current writer was reading."
    PRD §3.1: "A newly created class has `status` of `PLANNED`, `entry_count` and `confirmed_entry_count` of 0, `class_purse_cents` and `awarded_prize_cents` of 0, `placed_count` of 0, `point_eligible` false, and both `estimated_minutes` and `actual_minutes` null."
    PRD §3.6: "Booking increments both the ring's and the class's `version`, and moves the class `OPEN → SCHEDULED`."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_ring_version_blocks_slot_booking
    """
    ctx = build_approved_show(
        class_specs=[
            {"class_number": 101, "name": "Class 101"},
            {"class_number": 102, "name": "Class 102", "class_share_bp": 1000},
        ],
        ring_specs=[{}],
    )
    ring_id = ctx["ring_id"]
    class_101, class_102 = ctx["class_ids"]

    snapshot = ring_version(ring_id)
    assert snapshot == 1

    first = validate_success(
        api_client.create_ring_slot(
            create_ring_slot_payload(ring_id, class_101, "2026-09-10T14:00:00Z", snapshot),
            RING_MASTER,
        ),
        201,
    )
    assert first["duration_minutes"] == 20
    assert get_ring(ring_id)["version"] == 2

    validate_error(
        api_client.create_ring_slot(
            create_ring_slot_payload(ring_id, class_102, "2026-09-10T15:00:00Z", snapshot),
            RING_MASTER,
        ),
        "ERR_STALE_VERSION",
        412,
    )

    stale_refused = get_ring(ring_id)
    assert stale_refused["version"] == 2
    assert stale_refused["slot_count"] == 1
    blocked_class = get_class(class_102)
    assert blocked_class["status"] == "OPEN"
    assert blocked_class["estimated_minutes"] is None

    retried = validate_success(
        api_client.create_ring_slot(
            create_ring_slot_payload(
                ring_id, class_102, "2026-09-10T15:00:00Z", stale_refused["version"]
            ),
            RING_MASTER,
        ),
        201,
    )
    assert retried["duration_minutes"] == 20

    settled_ring = get_ring(ring_id)
    assert settled_ring["version"] == 3
    assert settled_ring["slot_count"] == 2
    assert settled_ring["scheduled_minutes_total"] == 40

    scheduled_class = get_class(class_102)
    assert scheduled_class["status"] == "SCHEDULED"
    assert scheduled_class["estimated_minutes"] == 20


def test_the_second_welfare_strike_stops_a_ring_that_is_otherwise_ready():
    """Welfare strikes accumulate on the show, not on the entry or the ring that earned them. One
    substantiated citation leaves competition running: the first occupancy is called and starts
    normally at a strike count of one, since the gate is a strictly-below comparison. The second
    citation takes the count to two and the second occupancy — same ring, same officials, same
    active coverage, sound footing — can no longer be called. The refused call is a no-op, and
    because a warning is not a positive finding, no horse was touched.

    PRD §3.9: "Its consequence is a strike, not a suspension: the show's `welfare_strike_count` is recomputed as the number of that show's substantiated welfare citations — counted over cases whose `case_type` is `WELFARE_CITATION` and whose `status` is `SUBSTANTIATED`, reached through each case's entry — and no horse is suspended."
    PRD §3.9: "A `WARNING` finding moves the case `OPEN → SUBSTANTIATED`, records `finding` as `WARNING`, and is only permitted when the case's `case_type` is `WELFARE_CITATION`; a warning on a drug test is refused with `ERR_FINDING_NOT_APPLICABLE`."
    PRD §3.7: "Finally the welfare gate: the show's `welfare_strike_count` must be strictly below 2."
    PRD §3.7: "Once a show has accumulated two substantiated welfare strikes, competition may not continue until the federation clears the show, and further calls are refused with `ERR_WELFARE_STRIKE_LIMIT`."
    PRD §3.1: "At creation the show's `license_status` is `DRAFT`, `revision_count` is 0, `allocated_prize_cents` is 0, `unallocated_prize_cents` equals `prize_money_pool_cents`, `reserved_stall_count` is 0, `available_stall_count` equals `stall_capacity`, `division_share_bp_total` is 0 and `welfare_strike_count` is 0."

    Design: Corner/cross_cutting_complexity_layers/welfare_strike_threshold_halts_competition
    """
    ctx = build_multi_class_show(
        class_specs=[
            {"class_number": 101, "name": "Class 101"},
            {"class_number": 102, "name": "Class 102", "class_share_bp": 1000},
        ],
        entry_plan=[{"classes": [], "confirm": False}],
    )
    class_101, class_102 = ctx["class_ids"]
    subject = ctx["field"][0]
    assert get_show(ctx["show_id"])["welfare_strike_count"] == 0

    chairs = build_judge_and_steward()
    slot_a = book_slot(ctx["ring_id"], class_101, "2026-09-10T14:00:00Z")
    slot_b = book_slot(ctx["ring_id"], class_102, "2026-09-10T15:00:00Z")
    assert slot_a["duration_minutes"] == 20
    assert slot_b["duration_minutes"] == 20
    card_judge_and_steward(slot_a["id"], chairs["judge_id"], chairs["steward_id"])
    card_judge_and_steward(slot_b["id"], chairs["judge_id"], chairs["steward_id"])
    build_active_coverage(ctx["show_id"])

    case_one = open_compliance_case(
        subject["entry_id"],
        chairs["steward_id"],
        "WELFARE_CITATION",
        welfare_rule_code="WR-12",
    )
    substantiated = record_finding(case_one["id"], "WARNING")
    assert substantiated["status"] == "SUBSTANTIATED"
    assert substantiated["finding"] == "WARNING"
    assert get_show(ctx["show_id"])["welfare_strike_count"] == 1

    assert start_slot(slot_a["id"])["status"] == "RUNNING"

    case_two = open_compliance_case(
        subject["entry_id"],
        chairs["steward_id"],
        "WELFARE_CITATION",
        welfare_rule_code="WR-19",
    )
    record_finding(case_two["id"], "WARNING")
    assert get_show(ctx["show_id"])["welfare_strike_count"] == 2

    validate_error(
        api_client.start_ring_slot(slot_b["id"], RING_MASTER), "ERR_WELFARE_STRIKE_LIMIT", 409
    )
    assert get_slot(slot_b["id"])["status"] == "SCHEDULED"
    assert get_class(class_102)["status"] == "SCHEDULED"
    untouched_horse = validate_success(
        api_client.get_horse(subject["horse_id"], SECRETARY)
    )
    assert untouched_horse["eligibility_status"] == "ELIGIBLE"


def test_a_posting_that_fails_its_fiscal_check_moves_no_money_at_all():
    """Posting fans money out across three levels at once, so the interesting failure is one that
    trips on the third placed row: the winner's entry is refunded after judging, which leaves it
    placed but unpaid. The withdrawal itself compensates cleanly — full refund, stalls released,
    and the winner's completed result row survives because only live rows are scratched — and then
    the posting is refused. No cent moved: the two innocent rows that would have collected 10430 and
    6675 are still at zero, the class is still JUDGED with its purse computed but unspent, and the
    show's ledger is untouched. Replaying the refused call reproduces it without drift.

    PRD §3.8: "Every class entry on the class carrying a non-null `placing` must belong to an entry whose `settlement_status` is `PAID`; a placed entry that was refunded after judging, or was never paid, blocks the posting with `ERR_UNPAID_PLACED_ENTRY` (HTTP 402)."
    PRD §3.8: "On success, each placed class entry's `prize_cents` is written by the ribbon waterfall of §3.2 — rounded per place, ascending, then summed, with the residual folded into first place only when all five ribbons were filled."
    PRD §3.5: "Notably, a `COMPLETED` class entry on a class that is merely `JUDGED` does *not* block withdrawal — which is precisely how a placed-but-refunded row can come to exist, and why posting results carries the unpaid-placed-entry check of §3.8."
    PRD §3.5: "If `settlement_status` was `PAID`, it moves `PAID → REFUNDED` and `refunded_cents` is set to `total_due_cents`."
    PRD §3.5: "`verification_status` becomes `WITHDRAWN`; `assigned_stall_count` returns to 0 and the show's `reserved_stall_count` and `available_stall_count` are recomputed, restoring `reserved_stall_count` to its exact pre-acceptance value; every class entry of the entry whose `status` is `ENTERED` or `CONFIRMED` moves to `SCRATCHED`, with each affected class's `entry_count`, `confirmed_entry_count` and `point_eligible` recomputed."
    PRD §2.10: "The **prize ledger** on a show maintains `allocated_prize_cents` as the sum of `awarded_prize_cents` across classes of the show whose `status` is `RESULTS_POSTED` or `POINTS_SUBMITTED`, and `unallocated_prize_cents` as `prize_money_pool_cents` minus `allocated_prize_cents`."
    PRD §2.10: "Classes that are merely `JUDGED`, classes that are `VOIDED`, and classes that have not yet been judged all contribute zero."

    Design: Corner/consistency_model/failed_posting_leaves_no_partial_prize_writes
    """
    ctx = build_multi_class_show(
        class_specs=[{"class_number": 101, "name": "Open Jumper 1.20m"}],
        entry_plan=[{"classes": [0], "stalls": 2}, {"classes": [0]}, {"classes": [0]}],
    )
    class_id = ctx["class_id"]
    winner, second, third = ctx["field"]
    assert get_entry(winner["entry_id"])["total_due_cents"] == 45000
    assert get_entry(second["entry_id"])["total_due_cents"] == 30000

    slot = stage_class_slot(ctx, class_id, "2026-09-10T14:00:00Z")
    assert slot["duration_minutes"] == 26
    build_active_coverage(ctx["show_id"])
    start_slot(slot["id"])
    rows = confirmed_rows_for_class(ctx, class_id)
    judged = record_results(class_id, ctx["judge_id"], default_placings(rows), 26)
    assert judged["status"] == "JUDGED"
    assert judged["class_purse_cents"] == 41721
    assert judged["awarded_prize_cents"] == 0

    refunded = withdraw_entry(winner["entry_id"], winner["rider_id"])
    assert refunded["settlement_status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 45000
    assert refunded["assigned_stall_count"] == 0
    released = get_show(ctx["show_id"])
    assert released["reserved_stall_count"] == 0
    assert released["available_stall_count"] == 40

    survivor = get_class_entry(winner["by_class"][class_id])
    assert survivor["status"] == "COMPLETED"
    assert survivor["placing"] == 1

    validate_error(
        api_client.post_class_results(class_id, SECRETARY), "ERR_UNPAID_PLACED_ENTRY", 402
    )

    for row in (winner, second, third):
        assert get_class_entry(row["by_class"][class_id])["prize_cents"] == 0
    after_fail = get_class(class_id)
    assert after_fail["status"] == "JUDGED"
    assert after_fail["awarded_prize_cents"] == 0
    assert after_fail["class_purse_cents"] == 41721
    ledger = get_show(ctx["show_id"])
    assert ledger["allocated_prize_cents"] == 0
    assert ledger["unallocated_prize_cents"] == 750000

    validate_error(
        api_client.post_class_results(class_id, SECRETARY), "ERR_UNPAID_PLACED_ENTRY", 402
    )
    final = get_show(ctx["show_id"])
    assert final["allocated_prize_cents"] == 0
    assert final["reserved_stall_count"] == 0
