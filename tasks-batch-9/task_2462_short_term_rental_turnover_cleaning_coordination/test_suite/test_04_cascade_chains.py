"""Multi-hop cascades: cancelled stays, rejected rows and closed repairs."""

import pytest

from test_helpers import (
    TEST_USERS,
    complete_repair_payload,
    create_issue_report_payload,
    dispatch_payload,
    fixtures as fx,
    review_task_payload,
    same_instant,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def scheduled_world(api):
    """T1 SCHEDULED with a PROVISIONAL pay line of 12554 cents on the ledger."""
    return fx.world_scheduled(api, supply="pair")


@pytest.fixture
def submitted_world(api):
    """Every checklist row SUBMITTED, nothing reviewed, nothing consumed yet."""
    return fx.world_awaiting_verification(api, supply="pair")


@pytest.fixture
def held_unassigned_world(api):
    """T1 never assigned, held by a blocking repair raised from PENDING_ASSIGNMENT."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    b_out, b_in = fx.seed_stay_pair(api, p1["id"])
    t1 = fx.seed_turnover(api, b_out["id"], b_in["id"])
    issue = validate_success(api.create_issue_report(
        create_issue_report_payload(
            t1["id"], issue_type="MAINTENANCE", severity="LOW",
            description="dripping kitchen tap", estimated_cost_cents=2000),
        COORDINATOR), 201)
    open_before = validate_success(
        api.get_property(p1["id"], COORDINATOR))["open_issue_count"]
    repair = validate_success(api.dispatch_issue_report(
        issue["id"],
        dispatch_payload(vendor_name="Zilker Handyman",
                         scheduled_at="2026-08-02T09:00:00Z",
                         blocks_checkin=True),
        COORDINATOR), 201)
    return {"p1": p1, "b_out": b_out, "b_in": b_in, "t1": t1, "issue": issue,
            "repair": repair, "open_before": open_before}


# ─── outgoing_booking_cancel_cascades_booking_to_turnover_to_… ────────────

def test_01_cancelling_the_departing_stay_voids_the_turn_and_revokes_the_offer(
        api, scheduled_world):
    """One cancel request walks booking to turnover to assignment.

    PRD §3.10: "A stay is cancelled by a `Coordinator` with an optional
    `cancellation_reason`, moving the booking `SCHEDULED → CANCELLED`; a
    booking that is not `SCHEDULED` draws `ERR_BOOKING_NOT_SCHEDULED`." PRD
    §3.10: "That turnover moves to `VOID` and its `version` increments by 1 —
    the transition applies identically from `PENDING_ASSIGNMENT`, `SCHEDULED`,
    `IN_PROGRESS`, `AWAITING_VERIFICATION`, `REWORK_REQUIRED` and `ON_HOLD`.
    Its assignments sitting in `OFFERED`, `ACCEPTED` or `ACTIVE` all move to
    `REVOKED` with `revoked_at` stamped; every `PROVISIONAL` pay line among
    them moves to `VOIDED` and the owning cleaner's `pending_payout_cents`
    decreases by that line's `net_cents`; and any audit on that turnover still
    sitting in `SAMPLED` moves to `VOIDED`, which touches neither
    `quality_score` nor money because an unfinalized audit had never moved
    either."

    Design: Difficulty/transitive_cascade/outgoing_booking_cancel_cascades_booking_to_turnover_to_assignment_to_payline_to_ledger
    """
    world = scheduled_world
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 12554, (
        "the accepted offer must have put 12554 cents on the ledger first")

    cancelled = validate_success(api.cancel_booking(
        world["b_out"]["id"],
        {"cancellation_reason": "guest cancelled the stay"}, COORDINATOR))
    assert cancelled["status"] == "CANCELLED", (
        f"the departing stay must reach CANCELLED, got {cancelled['status']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "VOID", (
        f"the work evaporates with the departing stay, got {turnover['status']}")

    assignment = validate_success(
        api.get_assignment(world["a1"]["id"], COORDINATOR))
    assert assignment["status"] == "REVOKED", (
        f"the accepted offer must be revoked, got {assignment['status']}")
    assert same_instant(assignment["revoked_at"], "2026-08-01T00:00:00Z"), (
        f"revoked_at must be stamped from the logical clock, "
        f"got {assignment['revoked_at']}")


def test_02_the_voided_pay_line_is_retained_while_the_ledger_returns_to_zero(
        api, scheduled_world):
    """Hops four and five: the money row survives, the ledger does not count it.

    PRD §3.10: "Its assignments sitting in `OFFERED`, `ACCEPTED` or `ACTIVE`
    all move to `REVOKED` with `revoked_at` stamped; every `PROVISIONAL` pay
    line among them moves to `VOIDED` and the owning cleaner's
    `pending_payout_cents` decreases by that line's `net_cents`; and any audit
    on that turnover still sitting in `SAMPLED` moves to `VOIDED`, which
    touches neither `quality_score` nor money because an unfinalized audit had
    never moved either." PRD §2.8: "Pay lines in `VOIDED` are excluded from the
    sum but are never deleted — the row and its money fields are retained as
    evidence."

    Design: Difficulty/transitive_cascade/outgoing_booking_cancel_cascades_booking_to_turnover_to_assignment_to_payline_to_ledger
    """
    world = scheduled_world
    validate_success(api.cancel_booking(
        world["b_out"]["id"],
        {"cancellation_reason": "guest cancelled the stay"}, COORDINATOR))

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["status"] == "VOIDED", (
        f"the provisional line must be voided, got {pay['status']}")
    assert pay["net_cents"] == 12554, (
        f"the voided row keeps its money fields as evidence, "
        f"got {pay['net_cents']}")

    cleaner = fx.read_cleaner(api, world)
    assert cleaner["pending_payout_cents"] == 0, (
        f"the ledger must exclude the voided line, "
        f"got {cleaner['pending_payout_cents']}")
    assert cleaner["completed_turnover_count"] == 0 and cleaner["decline_count"] == 0, (
        "a revocation is neither a completion nor a refusal")

    arriving = validate_success(api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert arriving["status"] == "SCHEDULED" and arriving["checkin_gate"] == "OPEN", (
        f"the arriving side is not part of this cascade, got "
        f"{arriving['status']} / {arriving['checkin_gate']}")


# ─── checklist_reject_cascades_task_to_turnover_to_payline_to_ledger ─────

def test_03_a_rejected_row_pushes_its_parent_turnover_into_rework(
        api, submitted_world):
    """Hops one and two of a cascade in which nothing reaches a terminal state.

    PRD §3.5: "**Rejection** moves the row `SUBMITTED → REJECTED` and, like
    approval, requires a `SUBMITTED` row and a turnover in one of the three
    underway statuses. It increments the row's `reject_count` by 1 and records
    the supplied `reject_reason`."

    Design: Difficulty/transitive_cascade/checklist_reject_cascades_task_to_turnover_to_payline_to_ledger
    """
    world = submitted_world
    before = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert before["net_cents"] == 12554 and before["photo_pass_bonus_cents"] == 500, (
        f"the untouched provisional line must read 12554 with a 500 bonus, "
        f"got {before['net_cents']} / {before['photo_pass_bonus_cents']}")

    staging = world["tasks"][2]
    rejected = validate_success(api.review_checklist_task(
        staging["id"],
        review_task_payload("REJECT", reject_reason="duvet not straightened"),
        REVIEWER))
    assert rejected["status"] == "REJECTED", (
        f"the reviewed row must land in REJECTED, got {rejected['status']}")
    assert rejected["reject_reason"] == "duvet not straightened", (
        f"the reviewer's reason must be recorded verbatim, "
        f"got {rejected['reject_reason']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "REWORK_REQUIRED", (
        f"the parent must follow its child, got {turnover['status']}")
    assert turnover["rejected_review_count"] == 1, (
        f"the parent's rejection tally must read 1, "
        f"got {turnover['rejected_review_count']}")


def test_04_the_rejection_moves_the_ledger_by_exactly_minus_800_cents(
        api, submitted_world):
    """Hops three and four, with the untouched sibling and the closet unmoved.

    PRD §2.8: "This invariant is re-established after every request that creates
    a pay line, switches its variant, folds in an audit adjustment, or voids it,
    which means an accept-then-revoke pair returns the ledger to its exact
    pre-acceptance value." PRD §3.5: "**No stock moves at submission time**:
    consumption is booked only when a reviewer approves, which is precisely what
    prevents a rejected-then-resubmitted row from double-counting stock."

    Design: Difficulty/transitive_cascade/checklist_reject_cascades_task_to_turnover_to_payline_to_ledger
    """
    world = submitted_world
    staging, restock = world["tasks"][2], world["tasks"][3]
    validate_success(api.review_checklist_task(
        staging["id"],
        review_task_payload("REJECT", reject_reason="duvet not straightened"),
        REVIEWER))

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["photo_penalty_cents"] == 300 and pay["photo_pass_bonus_cents"] == 0, (
        f"the rejection books 300 cents and clears the pass bonus, got "
        f"{pay['photo_penalty_cents']} / {pay['photo_pass_bonus_cents']}")
    assert pay["net_cents"] == 11754, (
        f"12554 less 300 penalty less 500 forfeited bonus, "
        f"got {pay['net_cents']}")
    assert pay["status"] == "PROVISIONAL", (
        f"the line stays provisional through the loop, got {pay['status']}")
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 11754, (
        "the ledger must follow the re-derivation by exactly -800 cents")

    rows = validate_success(api.list_turnover_checklist_tasks(
        world["t1"]["id"], COORDINATOR))
    sibling = {row["id"]: row for row in rows}[restock["id"]]
    assert sibling["status"] == "SUBMITTED", (
        f"an unrelated sibling must not be touched, got {sibling['status']}")

    sl1 = fx.read_supply_line(api, world["supply_lines"][0]["id"])
    assert sl1["on_hand_qty"] == 6, (
        f"nothing left the closet because no row was approved, "
        f"got {sl1['on_hand_qty']}")


# ─── repair_completion_cascades_repair_to_issue_to_property_and_… ────────

def test_05_closing_the_repair_resolves_the_finding_and_reconciles_the_unit(
        api, held_unassigned_world):
    """A LOW-severity finding under the floor stays REPORTED, then resolves.

    PRD §3.7: "Failing both conditions it is created in `REPORTED` with
    `owner_notified_at` left null." PRD §3.7: "Closing the repair is a
    coordinator's act, recording the invoiced `actual_cost_cents` and a
    `completion_note` vendor closeout, moving the order `DISPATCHED →
    COMPLETED` with `completed_at` stamped from the logical clock; an order
    already `COMPLETED` draws `ERR_INVALID_REPAIR_STATE`." PRD §3.7: "Two
    effects always follow: the parent report moves `DISPATCHED → RESOLVED`, and
    the property's `open_issue_count` decreases by 1."

    Design: Difficulty/transitive_cascade/repair_completion_cascades_repair_to_issue_to_property_and_releases_guest_gate
    """
    world = held_unassigned_world
    assert world["issue"]["status"] == "REPORTED", (
        f"a LOW-severity 2000-cent estimate is below the 5000-cent floor, "
        f"got {world['issue']['status']}")
    assert world["open_before"] == 1, (
        f"filing the report must raise the unit's open count to 1, "
        f"got {world['open_before']}")
    assert world["repair"]["status"] == "DISPATCHED", (
        f"the vendor order opens in DISPATCHED, got {world['repair']['status']}")

    closed = validate_success(api.complete_repair_order(
        world["repair"]["id"],
        complete_repair_payload(1800, completion_note="washer replaced"),
        COORDINATOR))
    assert closed["status"] == "COMPLETED", (
        f"the order must close, got {closed['status']}")
    assert same_instant(closed["completed_at"], "2026-08-01T00:00:00Z"), (
        f"completed_at must read the logical clock, got {closed['completed_at']}")

    issue = validate_success(api.get_issue_report(world["issue"]["id"], COORDINATOR))
    assert issue["status"] == "RESOLVED", (
        f"the parent finding must resolve, got {issue['status']}")
    prop = validate_success(api.get_property(world["p1"]["id"], COORDINATOR))
    assert prop["open_issue_count"] == 0, (
        f"the derived count must reconcile to 0, got {prop['open_issue_count']}")


def test_06_the_hold_is_released_back_to_the_status_it_was_placed_from(
        api, held_unassigned_world):
    """A hold taken from PENDING_ASSIGNMENT restores PENDING_ASSIGNMENT.

    PRD §2.10: "**Reversal is compensation, never erasure.** Releasing a hold
    restores the status the turnover was in before the hold rather than
    guessing a status; reversing a verified restock appends negating ledger
    movements rather than deleting the originals; voiding a pay line leaves its
    money fields readable." PRD §3.7: "In that case the status is restored from
    `pre_hold_status`, which may be any of `IN_PROGRESS`,
    `AWAITING_VERIFICATION`, `REWORK_REQUIRED`, `SCHEDULED` or
    `PENDING_ASSIGNMENT`; both `pre_hold_status` and `blocking_repair_order_id`
    are then cleared, and the turnover's `version` increments by 1."

    Design: Difficulty/transitive_cascade/repair_completion_cascades_repair_to_issue_to_property_and_releases_guest_gate
    """
    world = held_unassigned_world
    held = validate_success(api.get_turnover(world["t1"]["id"], COORDINATOR))
    assert held["status"] == "ON_HOLD", (
        f"a blocking dispatch holds even an unassigned turn, "
        f"got {held['status']}")
    assert held["pre_hold_status"] == "PENDING_ASSIGNMENT", (
        f"the captured status must be the one being left, "
        f"got {held['pre_hold_status']}")

    validate_success(api.complete_repair_order(
        world["repair"]["id"],
        complete_repair_payload(1800, completion_note="washer replaced"),
        COORDINATOR))

    released = validate_success(api.get_turnover(world["t1"]["id"], COORDINATOR))
    assert released["status"] == "PENDING_ASSIGNMENT", (
        f"the restored status must be PENDING_ASSIGNMENT rather than a guessed "
        f"IN_PROGRESS, got {released['status']}")
    assert released["pre_hold_status"] is None, (
        f"pre_hold_status must be cleared, got {released['pre_hold_status']}")
    assert released["blocking_repair_order_id"] is None, (
        f"the blocking reference must be cleared, "
        f"got {released['blocking_repair_order_id']}")

    arriving = validate_success(api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert arriving["checkin_gate"] == "RELEASED", (
        f"the guest gate must be released in the same request, "
        f"got {arriving['checkin_gate']}")
    assert arriving["guest_notice_code"] == "NONE", (
        f"the notice must return to NONE, got {arriving['guest_notice_code']}")
