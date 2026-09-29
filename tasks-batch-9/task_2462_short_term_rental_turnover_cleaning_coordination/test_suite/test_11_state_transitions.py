"""Initial states, terminal lockdowns, supersedes and the derived parent status."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_turnover_payload,
    cleaner_status_payload,
    complete_repair_payload,
    create_issue_report_payload,
    create_turnover_payload,
    dispatch_payload,
    fixtures as fx,
    restock_entry,
    review_task_payload,
    same_instant,
    schedule_change_payload,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
REVIEWER_USER_ID = "coord-2"


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def unit_and_cleaner(api):
    """P1 and Cleaner C at the initial clock, with nothing else created yet."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    cc = fx.seed_cleaner(api)
    return {"p1": p1, "cc": cc}


@pytest.fixture
def cancelled_stay(api):
    """OUT-1 already driven to the terminal CANCELLED occupancy state."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    b_out = fx.seed_booking(
        api, p1["id"], external_ref="OUT-1", guest_name="Guest Out",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    cancelled = validate_success(api.cancel_booking(
        b_out["id"], {"cancellation_reason": "guest cancelled"}, COORDINATOR))
    return {"p1": p1, "b_out": b_out, "cancelled": cancelled}


@pytest.fixture
def verified_strip_linens(api):
    """A running clean whose STRIP_LINENS row has been submitted and approved."""
    world = fx.world_in_progress(api, supply=None)
    row = fx.tasks_by_code(world["tasks"])["STRIP_LINENS"]
    validate_success(api.submit_checklist_task(
        row["id"], submit_task_payload(note="stripped"), world["cleaner_headers"]))
    world["row"] = validate_success(api.review_checklist_task(
        row["id"], review_task_payload("APPROVE"), REVIEWER))
    return world


@pytest.fixture
def offered_world(api):
    """T1 carrying one OFFERED assignment against the two LINEN par lines."""
    return fx.world_offered(api, supply="pair")


@pytest.fixture
def two_cleaner_world(api):
    """T1 in PENDING_ASSIGNMENT with two eligible cleaners available."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    c1 = fx.seed_cleaner(api, name="Cleaner C1")
    c2 = fx.seed_cleaner(
        api, name="Cleaner C2", skill_level=3, initial_quality_score=88.00)
    b_out, b_in = fx.seed_stay_pair(api, p1["id"])
    t1 = fx.seed_turnover(api, b_out["id"], b_in["id"])
    return {"p1": p1, "c1": c1, "c2": c2, "t1": t1}


@pytest.fixture
def running_clean(api):
    """T1 IN_PROGRESS on a unit whose notification floor is the default 5000."""
    return fx.world_in_progress(api, supply=None)


@pytest.fixture
def dispatched_repair(api):
    """A MEDIUM finding on a running clean with a vendor already dispatched."""
    world = fx.world_in_progress(api, supply=None)
    issue = validate_success(api.create_issue_report(
        create_issue_report_payload(
            world["t1"]["id"], issue_type="MAINTENANCE", severity="MEDIUM",
            description="dishwasher not draining", estimated_cost_cents=7500),
        world["cleaner_headers"]), 201)
    order = validate_success(api.dispatch_issue_report(
        issue["id"],
        dispatch_payload(vendor_name="Austin Appliance Co",
                         scheduled_at="2026-08-09T15:00:00Z",
                         blocks_checkin=False),
        COORDINATOR), 201)
    world["issue"] = issue
    world["order"] = order
    return world


@pytest.fixture
def started_clean(api):
    """A freshly started clean plus the start response that materialised it."""
    world = fx.build_world(api, supply="pair")
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    fx.reset_clock(api, fx.CHECKOUT_INSTANT)
    validate_success(api.checkout_booking(world["b_out"]["id"], {}, COORDINATOR))
    world["started"] = validate_success(
        api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    world["tasks"] = validate_success(api.list_turnover_checklist_tasks(
        world["t1"]["id"], COORDINATOR))
    return world


# ─── state_machines ───────────────────────────────────────────────────────

def test_01_each_machine_lands_in_its_declared_initial_state(api, unit_and_cleaner):
    """A stay, a turn and an offer are created and none of them skips ahead.

    PRD §3.2: "A fresh reservation lands with `status` `SCHEDULED`,
    `checkin_gate` `OPEN` and `guest_notice_code` `NONE`, and is refused with
    `ERR_BOOKING_OVERLAP` if its half-open occupancy interval collides with
    another `SCHEDULED` or `CHECKED_OUT` stay on the same unit under the
    zero-buffer rule of §2.6." PRD §3.4: "Each offer takes the next
    `sequence_no` within its turnover, starting at 1, and records
    `assigned_by_user_id` from the acting operator's `X-User-ID`." PRD §2.4:
    "Timestamps that record "when something happened" — `accepted_at`,
    `declined_at`, `revoked_at`, `started_at`, `finished_at`, `submitted_at`,
    `owner_notified_at`, `completed_at`, `finalized_at`, `cleanliness_rated_at`,
    `last_turnover_completed_at` — are all readings of that logical clock taken
    at the moment the corresponding transition is applied."

    Design: Corner/state_machines/corner_initial_states_of_booking_turnover_and_assignment
    """
    world = unit_and_cleaner
    b_out = fx.seed_booking(
        api, world["p1"]["id"], external_ref="OUT-1", guest_name="Guest Out",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    assert (b_out["status"], b_out["checkin_gate"],
            b_out["guest_notice_code"]) == ("SCHEDULED", "OPEN", "NONE"), (
        f"the stay must land in all three declared initial values, got "
        f"{b_out['status']} / {b_out['checkin_gate']} / "
        f"{b_out['guest_notice_code']}")
    assert b_out["cleanliness_rating"] is None, (
        f"no review has landed, got {b_out['cleanliness_rating']}")
    assert b_out["actual_checkout_at"] is None, (
        f"no departure has been recorded, got {b_out['actual_checkout_at']}")

    b_in = fx.seed_booking(
        api, world["p1"]["id"], external_ref="IN-1", guest_name="Guest In",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")
    turnover = validate_success(api.create_turnover(
        create_turnover_payload(b_out["id"], b_in["id"]), COORDINATOR), 201)
    assert turnover["status"] == "PENDING_ASSIGNMENT" and turnover["version"] == 1, (
        f"the turn must open unassigned at version 1, got "
        f"{turnover['status']} / {turnover['version']}")
    assert turnover["checklist_task_count"] == 0, (
        f"no checklist row exists before the clean starts, "
        f"got {turnover['checklist_task_count']}")

    offer = validate_success(api.assign_turnover(
        turnover["id"],
        assign_turnover_payload(turnover["version"], world["cc"]["id"]),
        COORDINATOR), 201)
    assert offer["status"] == "OFFERED", (
        f"an offer is not an acceptance, got {offer['status']}")
    assert offer["sequence_no"] == 1, (
        f"the first offer on the turn takes sequence 1, got {offer['sequence_no']}")
    assert (offer["accepted_at"], offer["declined_at"],
            offer["revoked_at"]) == (None, None, None), (
        f"none of the three outcome instants has been reached, got "
        f"{offer['accepted_at']} / {offer['declined_at']} / "
        f"{offer['revoked_at']}")
    assert world["cc"]["status"] == "ACTIVE", (
        f"the crew member starts employable, got {world['cc']['status']}")


def test_02_a_second_cancellation_of_the_same_stay_is_refused(api, cancelled_stay):
    """The terminal state answers 409 and the refusal mutates nothing at all.

    PRD §3.10: "A stay is cancelled by a `Coordinator` with an optional
    `cancellation_reason`, moving the booking `SCHEDULED → CANCELLED`; a booking
    that is not `SCHEDULED` draws `ERR_BOOKING_NOT_SCHEDULED`." PRD §2.5:
    "**Target state.** On every action endpoint, the addressed resource must
    itself be in a state that permits the operation, yielding one of
    `ERR_INVALID_TURNOVER_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`,
    `ERR_INVALID_TASK_STATE`, `ERR_INVALID_ISSUE_STATE`,
    `ERR_INVALID_REPAIR_STATE`, `ERR_INVALID_AUDIT_STATE`,
    `ERR_BOOKING_NOT_SCHEDULED` or `ERR_INVALID_CLEANER_STATE`, each at HTTP
    409."

    Design: Corner/state_machines/corner_cancelling_an_already_cancelled_booking_is_rejected
    """
    world = cancelled_stay
    assert world["cancelled"]["status"] == "CANCELLED", (
        f"the first cancellation must land, got {world['cancelled']['status']}")

    response = api.cancel_booking(
        world["b_out"]["id"], {"cancellation_reason": "duplicate request"},
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_BOOKING_NOT_SCHEDULED.value, 409)

    after = validate_success(api.get_booking(world["b_out"]["id"], COORDINATOR))
    assert after["status"] == "CANCELLED", (
        f"the stay must stay cancelled, got {after['status']}")
    assert after["version"] == world["cancelled"]["version"], (
        f"the refusal was not a replay, so the version must not move: "
        f"{after['version']} against {world['cancelled']['version']}")


def test_03_a_cancelled_stay_accepts_neither_a_departure_nor_a_courtesy(
        api, cancelled_stay):
    """Both occupancy operations answer the same 409 and write no instant.

    PRD §3.2: "Recording the departing guest's actual departure moves the
    booking `SCHEDULED → CHECKED_OUT`, and requires that the booking was in
    `SCHEDULED` to begin with — otherwise `ERR_BOOKING_NOT_SCHEDULED`." PRD
    §3.2: "Both variants require the booking to still be `SCHEDULED`, and both
    leave the gate dimension completely untouched — a granted courtesy is not a
    delay and never blocks an arrival."

    Design: Corner/state_machines/corner_cancelled_booking_rejects_checkout_and_schedule_change
    """
    world = cancelled_stay
    departure = api.checkout_booking(world["b_out"]["id"], {}, COORDINATOR)
    validate_error(departure, ApiErrorId.ERR_BOOKING_NOT_SCHEDULED.value, 409)

    courtesy = api.schedule_change_booking(
        world["b_out"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T18:00:00Z"),
        COORDINATOR)
    validate_error(courtesy, ApiErrorId.ERR_BOOKING_NOT_SCHEDULED.value, 409)

    after = validate_success(api.get_booking(world["b_out"]["id"], COORDINATOR))
    assert after["status"] == "CANCELLED", (
        f"neither refusal may move the occupancy dimension, got {after['status']}")
    assert after["actual_checkout_at"] is None, (
        f"the refused departure recorded nothing, "
        f"got {after['actual_checkout_at']}")
    assert after["late_checkout_until_at"] is None, (
        f"the refused courtesy granted nothing, "
        f"got {after['late_checkout_until_at']}")
    assert after["version"] == world["cancelled"]["version"], (
        f"two refusals leave the version where the cancellation left it: "
        f"{after['version']} against {world['cancelled']['version']}")


def test_04_a_verified_row_cannot_be_submitted_again(api, verified_strip_linens):
    """There is no submit edge out of VERIFIED, so the rework loop stays closed.

    PRD §3.6: "Submission is permitted from `PENDING` and from `REJECTED`, and
    requires that the acting cleaner owns the turnover's `ACTIVE` assignment and
    that the turnover's status is one of `IN_PROGRESS`, `AWAITING_VERIFICATION`
    or `REWORK_REQUIRED`; a task already `VERIFIED` or `WAIVED` cannot be
    submitted and draws `ERR_INVALID_TASK_STATE`." PRD §3.6: "Every review
    records `reviewed_by_user_id` from the acting operator's `X-User-ID` and then
    re-derives the parent turnover."

    Design: Corner/state_machines/corner_submitting_a_verified_checklist_task_is_rejected
    """
    world = verified_strip_linens
    row = world["row"]
    assert row["task_code"] == "STRIP_LINENS" and row["requires_photo"] is False, (
        f"the first template row needs no photograph, got "
        f"{row['task_code']} / {row['requires_photo']}")
    assert row["status"] == "VERIFIED", (
        f"the approval must have verified the row, got {row['status']}")
    assert row["reviewed_by_user_id"] == REVIEWER_USER_ID, (
        f"the reviewing operator must be recorded, "
        f"got {row['reviewed_by_user_id']}")

    response = api.submit_checklist_task(
        row["id"], submit_task_payload(note="resubmitting an approved task"),
        world["cleaner_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_TASK_STATE.value, 409)

    after = fx.tasks_by_code(validate_success(api.list_turnover_checklist_tasks(
        world["t1"]["id"], COORDINATOR)))["STRIP_LINENS"]
    assert after["status"] == "VERIFIED", (
        f"the refused submission changed no state, got {after['status']}")
    assert after["note"] == "stripped", (
        f"the stored evidence must be the approved one, got {after['note']!r}")
    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS", (
        "three children are still PENDING so the parent stays IN_PROGRESS")


def test_05_a_second_acceptance_never_credits_the_ledger_twice(api, offered_world):
    """The refused accept leaves exactly one PROVISIONAL row worth 12554 cents.

    PRD §3.5: "Accepting an offer requires that the offer's `status` is
    `OFFERED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`), that the offer's
    `cleaner_id` equals the acting `X-User-ID`, that the cleaner is `ACTIVE`
    (otherwise `ERR_CLEANER_NOT_ACTIVE`), that the turnover is still in
    `PENDING_ASSIGNMENT` (otherwise `ERR_INVALID_TURNOVER_STATE`), that the
    cleaner is not already at the daily cap
    (`ERR_CLEANER_DAILY_CAP_REACHED`), and that this turnover's window does not
    overlap another of the cleaner's non-terminal assignment windows under the
    zone buffer (`ERR_CLEANER_SCHEDULE_CONFLICT`)." PRD §3.5: "On success the
    offer moves `OFFERED → ACCEPTED` with `accepted_at` stamped from the logical
    clock, the turnover moves `PENDING_ASSIGNMENT → SCHEDULED` and its `version`
    increments by 1, a pay line is created in `status` `PROVISIONAL` under the
    `PROVISIONAL` variant, and the cleaner's `pending_payout_cents` increases by
    that pay line's `net_cents`."

    Design: Corner/state_machines/corner_accepting_an_already_accepted_offer_is_rejected
    """
    world = offered_world
    accepted = validate_success(api.accept_assignment(
        world["a1"]["id"], {}, world["cleaner_headers"]))
    assert accepted["status"] == "ACCEPTED", (
        f"the first acceptance must land, got {accepted['status']}")
    assert same_instant(accepted["accepted_at"], "2026-08-01T00:00:00Z"), (
        f"accepted_at reads the logical clock, got {accepted['accepted_at']}")

    response = api.accept_assignment(
        world["a1"]["id"], {}, world["cleaner_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value, 409)

    rows, meta = validate_paginated(api.list_pay_lines(
        COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert meta["total_count"] == 1, (
        f"only one pay line may exist, got {meta['total_count']}")
    assert rows[0]["status"] == "PROVISIONAL" and rows[0]["net_cents"] == 12554, (
        f"the single line must be the provisional 12554, got "
        f"{rows[0]['status']} / {rows[0]['net_cents']}")
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 12554, (
        "the ledger must be credited once, not twice")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "SCHEDULED" and turnover["version"] == 3, (
        f"create, offer and accept are three writes and the refusal is none, "
        f"got {turnover['status']} / {turnover['version']}")


def test_06_a_fresh_offer_revokes_the_outstanding_one(api, two_cleaner_world):
    """The supersede moves no money because a mere offer has no pay line.

    PRD §3.4: "Because a fresh offer supersedes whatever came before it,
    creating one revokes the turnover's outstanding `OFFERED` assignment — that
    older offer moves `OFFERED → REVOKED` with `revoked_at` stamped from the
    logical clock, and because no pay line exists for a mere offer there is no
    ledger movement attached to that revocation." PRD §3.4: "Offering also
    increments the turnover's `version` by 1, and requires the turnover to be in
    `PENDING_ASSIGNMENT`; any other status draws `ERR_INVALID_TURNOVER_STATE`."

    Design: Corner/state_machines/corner_second_offer_supersedes_and_revokes_the_outstanding_one
    """
    world = two_cleaner_world
    first = validate_success(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(world["t1"]["version"], world["c1"]["id"]),
        COORDINATOR), 201)
    assert first["sequence_no"] == 1 and first["assigned_by_user_id"] == "coord-1", (
        f"the first offer records sequence 1 and its operator, got "
        f"{first['sequence_no']} / {first['assigned_by_user_id']}")
    mid = validate_success(api.get_turnover(world["t1"]["id"], COORDINATOR))
    assert mid["version"] == 2, (
        f"the first offer bumped the turn to version 2, got {mid['version']}")

    second = validate_success(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(mid["version"], world["c2"]["id"]),
        COORDINATOR), 201)
    assert second["sequence_no"] == 2, (
        f"the superseding offer takes the next sequence, "
        f"got {second['sequence_no']}")
    assert second["cleaner_id"] == world["c2"]["id"]
    assert second["status"] == "OFFERED"

    superseded = validate_success(api.get_assignment(first["id"], COORDINATOR))
    assert superseded["status"] == "REVOKED", (
        f"the older offer must be revoked, got {superseded['status']}")
    assert same_instant(superseded["revoked_at"], "2026-08-01T00:00:00Z"), (
        f"revoked_at reads the logical clock, got {superseded['revoked_at']}")

    after = validate_success(api.get_turnover(world["t1"]["id"], COORDINATOR))
    assert after["status"] == "PENDING_ASSIGNMENT" and after["version"] == 3, (
        f"the turn is still unassigned at version 3, got "
        f"{after['status']} / {after['version']}")
    _, meta = validate_paginated(api.list_pay_lines(
        COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no pay line ever existed, got {meta['total_count']}")
    for key in ("c1", "c2"):
        cleaner = validate_success(api.get_cleaner(world[key]["id"], COORDINATOR))
        assert cleaner["pending_payout_cents"] == 0, (
            f"{key} must carry an empty ledger, "
            f"got {cleaner['pending_payout_cents']}")


def test_07_completion_reconciles_the_same_pay_line_instead_of_adding_one(api):
    """One row moves 12554 to 11114 and the ledger follows by exactly -1440.

    PRD §3.8: "The pay line recomputes under the `FINAL` variant, taking
    `status` `FINAL` and `variant` `FINAL`, and the cleaner's
    `pending_payout_cents` moves by the final `net_cents` less the provisional
    `net_cents`." PRD §3.8: "The working offer moves `ACTIVE → COMPLETED` and
    the cleaner's `completed_turnover_count` increases by 1." PRD §3.8: "The
    turnover's `restock_chargeback_cents` is set to the sum of
    `restock_charge_cents` across its `VERIFIED` restock rows — rows still
    `SUBMITTED`, or sitting in `REJECTED` or `WAIVED`, contribute nothing — and
    the property's `last_turnover_completed_at` is stamped from the logical
    clock."

    Design: Corner/state_machines/corner_ledger_sync_completion_switches_payline_provisional_to_final
    """
    world = fx.world_all_verified(api, supply="pair")
    provisional = fx.read_pay_lines(api, world["cc"]["id"])[0]
    assert provisional["variant"] == "PROVISIONAL", (
        f"the line starts on the estimate, got {provisional['variant']}")
    assert provisional["net_cents"] == 12554
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 12554

    finished = fx.complete_clean(api, world, at=None)
    assert finished["status"] == "COMPLETED", (
        f"every row is cleared so the clean closes, got {finished['status']}")
    assert same_instant(finished["finished_at"], "2026-08-08T16:00:00Z"), (
        f"finished_at reads the logical clock, got {finished['finished_at']}")
    assert finished["late_minutes"] == 0, (
        f"the clean finished inside the window, got {finished['late_minutes']}")
    assert finished["restock_chargeback_cents"] == 474, (
        f"280 plus 194 is 474, got {finished['restock_chargeback_cents']}")

    final = validate_success(api.get_pay_line(provisional["id"], COORDINATOR))
    assert final["status"] == "FINAL" and final["variant"] == "FINAL", (
        f"the same row switches variant, got "
        f"{final['status']} / {final['variant']}")
    assert final["linen_units"] == 2, (
        f"actual consumption is two linen units, got {final['linen_units']}")
    assert final["net_cents"] == 11114, (
        f"the final net is 11114, got {final['net_cents']}")

    cleaner = fx.read_cleaner(api, world)
    assert cleaner["pending_payout_cents"] == 11114, (
        f"the ledger moved by exactly 11114 less 12554, "
        f"got {cleaner['pending_payout_cents']}")
    assert cleaner["completed_turnover_count"] == 1, (
        f"one clean is now behind this cleaner, "
        f"got {cleaner['completed_turnover_count']}")
    _, meta = validate_paginated(api.list_pay_lines(
        COORDINATOR, {"cleaner_id": world["cc"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the row was reconciled, not duplicated, got {meta['total_count']}")

    assert validate_success(api.get_assignment(
        world["a1"]["id"], COORDINATOR))["status"] == "COMPLETED", (
        "the working offer must close with the clean")
    assert same_instant(validate_success(api.get_property(
        world["p1"]["id"], ADMIN))["last_turnover_completed_at"],
        "2026-08-08T16:00:00Z"), (
        "the unit records when it was last turned over")


def test_08_the_owner_is_notified_at_the_threshold_and_not_one_cent_below(
        api, running_clean):
    """4999 cents stays quiet while 5000 cents notifies immediately.

    PRD §3.7: "The report is created directly in `OWNER_NOTIFIED`, with
    `owner_notified_at` stamped from the logical clock, when either the
    `severity` is `HIGH` or `CRITICAL`, or the `estimated_cost_cents` is greater
    than or equal to the property's `owner_notify_min_cost_cents` threshold."
    PRD §3.7: "Failing both conditions it is created in `REPORTED` with
    `owner_notified_at` left null." PRD §3.7: "The report copies `property_id`
    from the turnover, records `reported_by_cleaner_id` as the acting cleaner's
    `X-User-ID` — left null when a coordinator filed it — and increases the
    property's `open_issue_count` by 1."

    Design: Corner/state_machines/corner_conditional_cascade_owner_notified_only_at_or_above_the_cost_threshold
    """
    world = running_clean
    assert world["p1"]["owner_notify_min_cost_cents"] == 5000, (
        f"the unit's notification floor must be 5000 cents, "
        f"got {world['p1']['owner_notify_min_cost_cents']}")

    below = validate_success(api.create_issue_report(
        create_issue_report_payload(
            world["t1"]["id"], issue_type="DAMAGE", severity="LOW",
            description="scuffed baseboard", estimated_cost_cents=4999),
        world["cleaner_headers"]), 201)
    assert below["status"] == "REPORTED", (
        f"4999 is below 5000 and LOW is not HIGH, got {below['status']}")
    assert below["owner_notified_at"] is None, (
        f"nobody was notified, got {below['owner_notified_at']}")
    assert below["reported_by_cleaner_id"] == world["cc"]["id"], (
        f"the filing cleaner must be recorded, "
        f"got {below['reported_by_cleaner_id']}")
    assert below["property_id"] == world["p1"]["id"]
    assert below["guest_chargeable"] is False, (
        f"the chargeable flag defaults to false, got {below['guest_chargeable']}")

    at_threshold = validate_success(api.create_issue_report(
        create_issue_report_payload(
            world["t1"]["id"], issue_type="DAMAGE", severity="LOW",
            description="cracked shower pan", estimated_cost_cents=5000),
        world["cleaner_headers"]), 201)
    assert at_threshold["status"] == "OWNER_NOTIFIED", (
        f"the comparison is at-or-above, got {at_threshold['status']}")
    assert same_instant(at_threshold["owner_notified_at"], "2026-08-08T16:00:00Z"), (
        f"owner_notified_at reads the logical clock, "
        f"got {at_threshold['owner_notified_at']}")

    unit = validate_success(api.get_property(world["p1"]["id"], ADMIN))
    assert unit["open_issue_count"] == 2, (
        f"both findings count, notified or not, got {unit['open_issue_count']}")
    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS", (
        "filing a finding does not move the clean")


def test_09_a_repair_order_can_only_be_closed_once(api, dispatched_repair):
    """The second close is refused and the issue count is not decremented twice.

    PRD §3.7: "Closing the repair is a coordinator's act, recording the invoiced
    `actual_cost_cents` and a `completion_note` vendor closeout, moving the order
    `DISPATCHED → COMPLETED` with `completed_at` stamped from the logical clock;
    an order already `COMPLETED` draws `ERR_INVALID_REPAIR_STATE`." PRD §3.7:
    "Two effects always follow: the parent report moves `DISPATCHED →
    RESOLVED`, and the property's `open_issue_count` decreases by 1." PRD §3.7:
    "A third effect is conditional — **only** when some turnover carries this
    very order as its `blocking_repair_order_id` does that turnover leave
    `ON_HOLD`."

    Design: Corner/state_machines/corner_completing_an_already_completed_repair_order_is_rejected
    """
    world = dispatched_repair
    assert world["order"]["status"] == "DISPATCHED", (
        f"the vendor visit must be open, got {world['order']['status']}")

    closed = validate_success(api.complete_repair_order(
        world["order"]["id"],
        complete_repair_payload(8100, completion_note="pump replaced"),
        COORDINATOR))
    assert closed["status"] == "COMPLETED", (
        f"the first close must land, got {closed['status']}")
    assert same_instant(closed["completed_at"], "2026-08-08T16:00:00Z"), (
        f"completed_at reads the logical clock, got {closed['completed_at']}")
    assert closed["actual_cost_cents"] == 8100

    response = api.complete_repair_order(
        world["order"]["id"], complete_repair_payload(9900), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_REPAIR_STATE.value, 409)

    after = validate_success(api.get_repair_order(world["order"]["id"], COORDINATOR))
    assert after["status"] == "COMPLETED" and after["actual_cost_cents"] == 8100, (
        f"the refused close recorded no new invoice, got "
        f"{after['status']} / {after['actual_cost_cents']}")

    unit = validate_success(api.get_property(world["p1"]["id"], ADMIN))
    assert unit["open_issue_count"] == 0, (
        f"the count was decremented once, not twice, "
        f"got {unit['open_issue_count']}")
    assert validate_success(api.get_issue_report(
        world["issue"]["id"], COORDINATOR))["status"] == "RESOLVED", (
        "the parent finding must be resolved by the close")
    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS", (
        "the dispatch never placed a hold, so nothing is restored")


def test_10_reactivation_is_refused_from_active_and_accepted_from_suspended(api):
    """The same action fails and then succeeds purely on the source state.

    PRD §3.10: "Suspension requires the cleaner to be `ACTIVE` and moves it
    `ACTIVE → SUSPENDED`; reactivation requires `SUSPENDED` and moves it
    `SUSPENDED → ACTIVE`; offboarding is reachable from both `ACTIVE` and
    `SUSPENDED`." PRD §3.10: "An action that does not apply from the cleaner's
    current status draws `ERR_INVALID_CLEANER_STATE`, as does an offboarding
    attempt while the cleaner still holds an `ACTIVE` assignment — a cleaner
    mid-clean may not be offboarded out from under the job."

    Design: Corner/state_machines/corner_reactivating_an_active_cleaner_is_rejected
    """
    fx.reset_clock(api)
    cc = fx.seed_cleaner(api)
    assert cc["status"] == "ACTIVE" and cc["version"] == 1, (
        f"the cleaner starts ACTIVE at version 1, got "
        f"{cc['status']} / {cc['version']}")

    response = api.set_cleaner_status(
        cc["id"], cleaner_status_payload("REACTIVATE", reason="no-op"), ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_CLEANER_STATE.value, 409)

    mid = validate_success(api.get_cleaner(cc["id"], COORDINATOR))
    assert mid["status"] == "ACTIVE" and mid["version"] == 1, (
        f"the refusal mutated nothing, got {mid['status']} / {mid['version']}")

    suspended = validate_success(api.set_cleaner_status(
        cc["id"], cleaner_status_payload("SUSPEND", reason="documents expired"),
        ADMIN))
    assert suspended["status"] == "SUSPENDED", (
        f"suspension applies from ACTIVE, got {suspended['status']}")

    reactivated = validate_success(api.set_cleaner_status(
        cc["id"], cleaner_status_payload("REACTIVATE", reason="documents renewed"),
        ADMIN))
    assert reactivated["status"] == "ACTIVE", (
        f"the identical action applies from SUSPENDED, "
        f"got {reactivated['status']}")


def test_11_the_last_submission_bubbles_the_parent_out_of_in_progress(
        api, started_clean):
    """Three of four submitted keeps the parent IN_PROGRESS; the fourth moves it.

    PRD §3.6: "While the clean is underway, and **only** while the turnover's
    current status is one of `IN_PROGRESS`, `AWAITING_VERIFICATION` or
    `REWORK_REQUIRED`, the turnover's status is re-derived after every single
    child change by this ordered rule, first match winning: if any child sits in
    `REJECTED` the turnover is `REWORK_REQUIRED`; otherwise if any child sits in
    `PENDING` the turnover is `IN_PROGRESS`; otherwise — every child being
    `VERIFIED` or `WAIVED` — the turnover is `AWAITING_VERIFICATION`." PRD §3.5:
    "The turnover's `checklist_task_count` is then set to the number of rows
    appended — four for a `STUDIO`, a `ONE_BR` or a `TWO_BR`, and five for a
    `THREE_BR_PLUS`." PRD §3.6: "**No stock moves at submission time**:
    consumption is booked only when a reviewer approves, which is precisely what
    prevents a rejected-then-resubmitted row from double-counting stock."

    Design: Corner/state_machines/corner_bubble_up_last_submission_moves_turnover_out_of_in_progress
    """
    world = started_clean
    started = world["started"]
    assert started["status"] == "IN_PROGRESS", (
        f"the clean is underway, got {started['status']}")
    assert started["checklist_task_count"] == 4, (
        f"a TWO_BR appends four rows, got {started['checklist_task_count']}")
    assert started["version"] == 5, (
        f"create, offer, accept, the departure re-derivation and start are "
        f"five writes, got {started['version']}")

    tasks = world["tasks"]
    for task in tasks[:3]:
        validate_success(api.submit_checklist_task(
            task["id"],
            submit_task_payload(
                photo_uri=(f"https://cdn.example.com/{task['task_code']}.jpg"
                           if task["requires_photo"] else None),
                note=f"{task['task_code']} done"),
            world["cleaner_headers"]))
    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS", (
        "one child is still PENDING, so the second derivation rule wins")

    sheets = world["supply_lines"][0]
    validate_success(api.submit_checklist_task(
        tasks[3]["id"],
        submit_task_payload(
            photo_uri="https://cdn.example.com/restock.jpg",
            restock_entries=[restock_entry(sheets["id"], 1)]),
        world["cleaner_headers"]))
    assert fx.read_turnover(api, world)["status"] == "AWAITING_VERIFICATION", (
        "no child is PENDING or REJECTED, so the parent bubbles up")

    submitted = validate_success(api.list_turnover_checklist_tasks(
        world["t1"]["id"], COORDINATOR, {"status": "SUBMITTED"}))
    assert len(submitted) == 4, (
        f"all four rows are awaiting review, got {len(submitted)}")
    assert fx.read_supply_line(api, sheets["id"])["on_hand_qty"] == 6, (
        "submission records intent only; stock moves on approval")
