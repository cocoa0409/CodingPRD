"""Non-linear lifecycle paths: rework loops, held turns and the offer fork."""

import pytest

from test_helpers import (
    TEST_USERS,
    complete_repair_payload,
    create_issue_report_payload,
    dispatch_payload,
    fixtures as fx,
    make_cleaner_headers,
    review_task_payload,
    submit_task_payload,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def partly_reviewed_world(api):
    """All four rows SUBMITTED with the first two already APPROVED."""
    world = fx.world_awaiting_verification(api, supply="pair")
    for task in world["tasks"][:2]:
        validate_success(api.review_checklist_task(
            task["id"], review_task_payload("APPROVE"), REVIEWER))
    return world


@pytest.fixture
def blocking_issue_world(api):
    """A running clean carrying a HIGH-severity finding estimated at 12000 cents."""
    world = fx.world_in_progress(api, supply=None)
    world["issue"] = validate_success(api.create_issue_report(
        create_issue_report_payload(
            world["t1"]["id"], issue_type="DAMAGE", severity="HIGH",
            description="cracked shower pan", estimated_cost_cents=12000),
        world["cleaner_headers"]), 201)
    return world


@pytest.fixture
def two_cleaner_world(api):
    """P1 with no stock lines, two interchangeable cleaners and T1 at version 1."""
    world = fx.build_world(api, supply=None)
    world["cd"] = fx.seed_cleaner(api, name="Cleaner CD")
    return world


# ─── turnover_rework_cycle_awaiting_to_rework_and_back ───────────────────

def test_01_one_rejection_pulls_the_turnover_back_out_of_awaiting_verification(
        api, partly_reviewed_world):
    """The parent re-derives to REWORK_REQUIRED and the money follows at once.

    PRD §3.5: "if any child sits in `REJECTED` the turnover is
    `REWORK_REQUIRED`; otherwise if any child sits in `PENDING` the turnover is
    `IN_PROGRESS`; otherwise — every child being `VERIFIED` or `WAIVED` — the
    turnover is `AWAITING_VERIFICATION`." PRD §3.5: "On the parent,
    `rejected_review_count` and `rework_round` each increase by 1, the
    re-derivation rule drives the turnover to `REWORK_REQUIRED` — most visibly
    as the `AWAITING_VERIFICATION → REWORK_REQUIRED` step when the last row had
    just been cleared — and the turnover's `version` increments by 1." PRD §3.5:
    "the turnover's `PROVISIONAL` pay line recomputes `photo_penalty_cents`,
    clears `photo_pass_bonus_cents` to zero, re-derives `net_cents`, and the
    cleaner's `pending_payout_cents` moves by exactly that delta."

    Design: Difficulty/non_linear_state_machine/turnover_rework_cycle_awaiting_to_rework_and_back
    """
    world = partly_reviewed_world
    before = fx.read_turnover(api, world)
    assert before["status"] == "AWAITING_VERIFICATION", (
        f"with every row submitted the turn must await review, "
        f"got {before['status']}")

    staging = world["tasks"][2]
    rejected = validate_success(api.review_checklist_task(
        staging["id"],
        review_task_payload("REJECT", reject_reason="pillows not staged"),
        REVIEWER))
    assert rejected["status"] == "REJECTED" and rejected["reject_count"] == 1, (
        f"the row must land in REJECTED with reject_count 1, "
        f"got {rejected['status']} / {rejected['reject_count']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "REWORK_REQUIRED", (
        f"a single rejected child must pull the parent backwards, "
        f"got {turnover['status']}")
    assert turnover["rework_round"] == 1 and turnover["rejected_review_count"] == 1, (
        f"both history counters must read 1, got rework_round "
        f"{turnover['rework_round']} / rejected {turnover['rejected_review_count']}")

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["photo_penalty_cents"] == 300, (
        f"one rejection costs 300 cents, got {pay['photo_penalty_cents']}")
    assert pay["photo_pass_bonus_cents"] == 0, (
        f"the photo-pass bonus must be cleared, "
        f"got {pay['photo_pass_bonus_cents']}")
    assert pay["net_cents"] == 11754, (
        f"the provisional net must be 11254 + 800 - 300, got {pay['net_cents']}")
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 11754


def test_02_resubmitting_the_rejected_row_re_enters_awaiting_verification(
        api, partly_reviewed_world):
    """The same state is visited twice and the settled net lands at 10314.

    PRD §3.5: "Submitting from `PENDING` is the first pass; submitting again
    from `REJECTED` refreshes `submitted_at` and re-derives the parent, either
    continuing or closing the rework cycle." PRD §3.5: "When `rework_round`
    climbs strictly above 2 — that is, on the third and any subsequent entry
    into rework — the turnover sets `escalation_required` to true and the
    cleaner's `strike_count` increases by 1, once per turnover."

    Design: Difficulty/non_linear_state_machine/turnover_rework_cycle_awaiting_to_rework_and_back
    """
    world = partly_reviewed_world
    staging, restock = world["tasks"][2], world["tasks"][3]
    validate_success(api.review_checklist_task(
        staging["id"],
        review_task_payload("REJECT", reject_reason="pillows not staged"),
        REVIEWER))

    validate_success(api.submit_checklist_task(
        staging["id"],
        submit_task_payload(photo_uri="https://cdn.example.com/bed-fixed.jpg"),
        world["cleaner_headers"]))
    back = fx.read_turnover(api, world)
    assert back["status"] == "AWAITING_VERIFICATION", (
        f"clearing the rejection must re-enter AWAITING_VERIFICATION, "
        f"got {back['status']}")

    for task in (staging, restock):
        validate_success(api.review_checklist_task(
            task["id"], review_task_payload("APPROVE"), REVIEWER))
    final = fx.complete_clean(api, world)

    assert final["status"] == "COMPLETED", (
        f"the turn must still be completable after a rework loop, "
        f"got {final['status']}")
    assert final["rework_round"] == 1, (
        f"one loop must leave rework_round at 1, got {final['rework_round']}")

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["photo_penalty_cents"] == 300, (
        f"the rejection penalty survives completion, "
        f"got {pay['photo_penalty_cents']}")
    assert pay["bonus_cents"] == 800, (
        f"an on-time finish keeps 800 and no photo-pass bonus, "
        f"got {pay['bonus_cents']}")
    assert pay["net_cents"] == 10314, (
        f"the settled net must be 9814 + 800 - 300, got {pay['net_cents']}")
    assert fx.read_cleaner(api, world)["strike_count"] == 0, (
        "a single rework round does not exceed the tolerance, so no strike")


# ─── booking_parallel_dimensions_gate_moves_independently_of_occupancy ───

def test_03_blocking_dispatch_moves_the_gate_while_occupancy_stands_still(
        api, blocking_issue_world):
    """The arriving stay stays SCHEDULED while its gate becomes BLOCKED.

    PRD §3.2: "A booking carries **two independent state dimensions**. The
    occupancy dimension is `status`, which advances from `SCHEDULED` to either
    `CHECKED_OUT` or `CANCELLED`. The arrival-readiness dimension is
    `checkin_gate`, which advances `OPEN` → `BLOCKED` → `RELEASED`." PRD §3.7:
    "When `blocks_checkin` is true and the associated turnover is non-terminal
    — that is, in any of `PENDING_ASSIGNMENT`, `SCHEDULED`, `IN_PROGRESS`,
    `AWAITING_VERIFICATION` or `REWORK_REQUIRED` — the turnover captures the
    status it is leaving into `pre_hold_status`, moves to `ON_HOLD`, records
    the new order in `blocking_repair_order_id`, and increments its `version`
    by 1; in a second hop the arriving stay's `checkin_gate` moves `OPEN →
    BLOCKED` with `guest_notice_code` `CHECKIN_DELAYED` and that booking's own
    `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_gate_moves_independently_of_occupancy
    """
    world = blocking_issue_world
    departed = validate_success(api.get_booking(world["b_out"]["id"], COORDINATOR))
    assert departed["status"] == "CHECKED_OUT", (
        f"the departing stay moved on the occupancy dimension, "
        f"got {departed['status']}")
    assert departed["checkin_gate"] == "OPEN", (
        f"its own gate dimension must not have moved, "
        f"got {departed['checkin_gate']}")
    assert world["issue"]["status"] == "OWNER_NOTIFIED", (
        f"a HIGH-severity finding reaches the owner at creation, "
        f"got {world['issue']['status']}")

    repair = validate_success(api.dispatch_issue_report(
        world["issue"]["id"],
        dispatch_payload(vendor_name="Barton Plumbing", blocks_checkin=True),
        COORDINATOR), 201)

    arriving = validate_success(api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert arriving["status"] == "SCHEDULED", (
        f"blocking arrival readiness must not touch occupancy, "
        f"got {arriving['status']}")
    assert arriving["checkin_gate"] == "BLOCKED", (
        f"the gate must move OPEN to BLOCKED, got {arriving['checkin_gate']}")
    assert arriving["guest_notice_code"] == "CHECKIN_DELAYED", (
        f"the notice rides the gate dimension, "
        f"got {arriving['guest_notice_code']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "ON_HOLD", (
        f"the running clean must be held, got {turnover['status']}")
    assert turnover["pre_hold_status"] == "IN_PROGRESS", (
        f"the status being left must be captured, "
        f"got {turnover['pre_hold_status']}")
    assert turnover["blocking_repair_order_id"] == repair["id"], (
        f"the hold must name the blocking order, "
        f"got {turnover['blocking_repair_order_id']}")


def test_04_closing_the_repair_releases_the_gate_and_restores_the_held_status(
        api, blocking_issue_world):
    """The gate reaches RELEASED and the turn resumes from pre_hold_status.

    PRD §3.7: "In that case the status is restored from `pre_hold_status`,
    which may be any of `IN_PROGRESS`, `AWAITING_VERIFICATION`,
    `REWORK_REQUIRED`, `SCHEDULED` or `PENDING_ASSIGNMENT`; both
    `pre_hold_status` and `blocking_repair_order_id` are then cleared, and the
    turnover's `version` increments by 1. The arriving guest is compensated in
    the same request: that booking's `checkin_gate` moves `BLOCKED →
    RELEASED`, its `guest_notice_code` returns to `NONE`, and its `version`
    increments by 1." PRD §3.7: "Two effects always follow: the parent report
    moves `DISPATCHED → RESOLVED`, and the property's `open_issue_count`
    decreases by 1."

    Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_gate_moves_independently_of_occupancy
    """
    world = blocking_issue_world
    repair = validate_success(api.dispatch_issue_report(
        world["issue"]["id"],
        dispatch_payload(vendor_name="Barton Plumbing", blocks_checkin=True),
        COORDINATOR), 201)

    closed = validate_success(api.complete_repair_order(
        repair["id"],
        complete_repair_payload(11500, completion_note="pan replaced"),
        COORDINATOR))
    assert closed["status"] == "COMPLETED" and closed["actual_cost_cents"] == 11500, (
        f"the order must close at the invoiced cost, got {closed['status']} / "
        f"{closed['actual_cost_cents']}")

    arriving = validate_success(api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert arriving["status"] == "SCHEDULED", (
        f"occupancy is still untouched, got {arriving['status']}")
    assert arriving["checkin_gate"] == "RELEASED", (
        f"the gate must advance BLOCKED to RELEASED, "
        f"got {arriving['checkin_gate']}")
    assert arriving["guest_notice_code"] == "NONE", (
        f"the notice must return to NONE, got {arriving['guest_notice_code']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "IN_PROGRESS", (
        f"the held status must be restored rather than guessed, "
        f"got {turnover['status']}")
    assert turnover["blocking_repair_order_id"] is None, (
        f"the blocking reference must be cleared, "
        f"got {turnover['blocking_repair_order_id']}")

    issue = validate_success(api.get_issue_report(world["issue"]["id"], COORDINATOR))
    assert issue["status"] == "RESOLVED", (
        f"the parent report must resolve, got {issue['status']}")
    prop = validate_success(api.get_property(world["p1"]["id"], ADMIN))
    assert prop["open_issue_count"] == 0, (
        f"the unit's open finding count must fall to 0, "
        f"got {prop['open_issue_count']}")


# ─── assignment_offered_fork_decline_leaves_turnover_version_untouched ───

def test_05_declining_an_offer_leaves_the_parent_turnover_version_untouched(
        api, two_cleaner_world):
    """Assign bumps 1 to 2 and the decline leaves the reading at 2.

    PRD §3.4: "But the turnover is left entirely alone — it stays in
    `PENDING_ASSIGNMENT`, and crucially its `version` is **not** incremented. A
    coordinator holding a version reading taken before a decline can therefore
    still issue a fresh offer without re-reading, whereas the same reading
    taken before an acceptance is stale." PRD §3.4: "It likewise requires an
    `OFFERED` offer owned by the acting cleaner, and it moves the offer
    `OFFERED → DECLINED` with `declined_at` stamped from the logical clock
    while incrementing the cleaner's `decline_count` by 1; an optional
    `decline_reason` may accompany the refusal."

    Design: Difficulty/non_linear_state_machine/assignment_offered_fork_decline_leaves_turnover_version_untouched
    """
    world = two_cleaner_world
    assert world["t1"]["version"] == 1, (
        f"a fresh turnover opens at version 1, got {world['t1']['version']}")

    a1 = fx.offer_turnover(api, world)
    offered = fx.read_turnover(api, world)
    assert offered["version"] == 2, (
        f"creating the offer must bump the turnover to 2, "
        f"got {offered['version']}")
    assert offered["status"] == "PENDING_ASSIGNMENT", (
        f"an offer does not schedule the turn, got {offered['status']}")

    declined = validate_success(api.decline_assignment(
        a1["id"], {"decline_reason": "double booked"}, world["cleaner_headers"]))
    assert declined["status"] == "DECLINED", (
        f"the offer must move to DECLINED, got {declined['status']}")

    after = fx.read_turnover(api, world)
    assert after["version"] == 2, (
        f"a decline touches no parent field so the version stays 2, "
        f"got {after['version']}")
    assert after["status"] == "PENDING_ASSIGNMENT", (
        f"the turn must remain assignable, got {after['status']}")

    cleaner = fx.read_cleaner(api, world)
    assert cleaner["decline_count"] == 1, (
        f"the refusal must be recorded once, got {cleaner['decline_count']}")
    assert cleaner["pending_payout_cents"] == 0, (
        f"a declined offer earns nothing, got {cleaner['pending_payout_cents']}")


def test_06_the_accept_branch_of_the_same_fork_schedules_and_bumps_twice_more(
        api, two_cleaner_world):
    """Re-offer takes the version to 3 and acceptance to 4 with SCHEDULED.

    PRD §3.4: "On success the offer moves `OFFERED → ACCEPTED` with
    `accepted_at` stamped from the logical clock, the turnover moves
    `PENDING_ASSIGNMENT → SCHEDULED` and its `version` increments by 1, a pay
    line is created in `status` `PROVISIONAL` under the `PROVISIONAL` variant,
    and the cleaner's `pending_payout_cents` increases by that pay line's
    `net_cents`."

    Design: Difficulty/non_linear_state_machine/assignment_offered_fork_decline_leaves_turnover_version_untouched
    """
    world = two_cleaner_world
    a1 = fx.offer_turnover(api, world)
    validate_success(api.decline_assignment(
        a1["id"], {"decline_reason": "double booked"}, world["cleaner_headers"]))

    a2 = validate_success(api.assign_turnover(
        world["t1"]["id"],
        {"expected_turnover_version": 2, "cleaner_id": world["cd"]["id"]},
        COORDINATOR), 201)
    assert fx.read_turnover(api, world)["version"] == 3, (
        "the re-offer issued against the pre-decline reading must bump to 3")

    accepted = validate_success(api.accept_assignment(
        a2["id"], {}, make_cleaner_headers(world["cd"]["id"])))
    assert accepted["status"] == "ACCEPTED" and accepted["sequence_no"] == 2, (
        f"the second offer on this turn must be sequence 2 and ACCEPTED, "
        f"got {accepted['status']} / {accepted['sequence_no']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["version"] == 4, (
        f"acceptance must bump the turnover once more, got {turnover['version']}")
    assert turnover["status"] == "SCHEDULED", (
        f"acceptance must schedule the turn, got {turnover['status']}")

    cd = validate_success(api.get_cleaner(world["cd"]["id"], ADMIN))
    assert cd["pending_payout_cents"] == 10874, (
        f"the accepting cleaner holds 8325 + 1249 rush + 0 linen + 1300 bonus, "
        f"got {cd['pending_payout_cents']}")
    assert fx.read_pay_lines(api, world["cc"]["id"]) == [], (
        "the cleaner who declined must have no pay line at all")
