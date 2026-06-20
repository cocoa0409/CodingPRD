"""Surgeon-block and surgical-day state machines: branching-with-revert block
lifecycle, day lock/reopen/close transitions, and their guards.

Difficulty queue: non_linear_state_machine / block_branching_with_revert_held_to_released;
                  boundary_precision_check / lock_empty_day_rejected_empty_set_edge.
Corner queue: state_machines section (block release idempotency, day reopen cycle,
              close-with-unfinished rejection).
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine / block_branching_with_revert_held_to_released
# ===========================================================================
def test_block_confirm_then_release_reaches_released_via_confirmed_branch():
    """PRD §3.4: "A `Scheduler` confirms a block, advancing `HELD → CONFIRMED`, only when
    the block is currently `HELD` (otherwise `ERR_BLOCK_NOT_HELD`), the owning surgeon is
    active (otherwise `ERR_SURGEON_INACTIVE`), and the owning day is not `CLOSED`
    (otherwise `ERR_DAY_CLOSED`); confirmation increments the block's `version` by 1."
    PRD §3.4: "A `Scheduler` releases a block, advancing it to `RELEASED` from either
    `HELD` or `CONFIRMED`."

    Confirm a HELD empty block, then release it: it reaches RELEASED via the CONFIRMED branch.

    Design: Difficulty/non_linear_state_machine/block_branching_with_revert_held_to_released
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    confirmed = validate_success(api_client.confirm_block(block["id"], SCHED), 200)
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]
    released = validate_success(api_client.release_block(block["id"], SCHED), 200)
    assert released["status"] == "RELEASED", released["status"]


def test_block_held_directly_to_released():
    """PRD §3.4: "A block advances through `HELD → CONFIRMED → RELEASED`, and may also go
    `HELD → RELEASED` directly."
    PRD §3.4: "A `Scheduler` releases a block, advancing it to `RELEASED` from either
    `HELD` or `CONFIRMED`."

    A HELD empty block released without confirming reaches RELEASED directly (the other branch).

    Design: Difficulty/non_linear_state_machine/block_branching_with_revert_held_to_released
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    released = validate_success(api_client.release_block(block["id"], SCHED), 200)
    assert released["status"] == "RELEASED", released["status"]


# ===========================================================================
# Difficulty / boundary_precision_check / lock_empty_day_rejected_empty_set_edge
# ===========================================================================
def test_lock_empty_day_rejected():
    """PRD §3.3: "Locking requires that the day is currently `OPEN` (otherwise
    `ERR_DAY_NOT_OPEN`) and that at least one non-cancelled case already exists on the day
    (otherwise `ERR_DAY_EMPTY`)."

    A fresh day with zero cases cannot be locked -> ERR_DAY_EMPTY; posture stays OPEN.

    Design: Difficulty/boundary_precision_check/lock_empty_day_rejected_empty_set_edge
    """
    facility = fixtures.create_facility()
    day = fixtures.create_surgical_day(facility["id"])
    resp = api_client.lock_day(day["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_DAY_EMPTY.value)
    after = get_success_data(api_client.get_surgical_day(day["id"], SCHED))
    assert after["posture"] == "OPEN", after["posture"]


def test_lock_day_with_one_case_succeeds():
    """PRD §3.3: "Locking requires that the day is currently `OPEN` (otherwise
    `ERR_DAY_NOT_OPEN`) and that at least one non-cancelled case already exists on the day
    (otherwise `ERR_DAY_EMPTY`)."

    A day with exactly one non-cancelled case (the non-empty boundary) locks successfully
    to posture LOCKED.

    Design: Difficulty/boundary_precision_check/lock_empty_day_rejected_empty_set_edge
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    locked = validate_success(api_client.lock_day(world["day"]["id"], SCHED), 200)
    assert locked["posture"] == "LOCKED", locked["posture"]


# ===========================================================================
# Corner / state_machines / block_release_already_released_invalid
# ===========================================================================
def test_release_already_released_block_rejected():
    """PRD §3.4: "Release requires that the block is currently `HELD` or `CONFIRMED`
    (otherwise `ERR_BLOCK_NOT_RELEASABLE`) and that the owning day is not `CLOSED`
    (otherwise `ERR_DAY_CLOSED`)."

    Releasing an already-RELEASED block (second release) -> ERR_BLOCK_NOT_RELEASABLE.

    Design: Corner/state_machines/block_release_already_released_invalid
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    get_success_data(api_client.release_block(block["id"], SCHED))
    resp = api_client.release_block(block["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_RELEASABLE.value)


# ===========================================================================
# Corner / state_machines / reopen_locked_day_back_to_open_cycle
# ===========================================================================
def test_reopen_locked_day_returns_to_open():
    """PRD §3.3: "A `Scheduler` may reverse a lock, advancing posture `LOCKED → OPEN`,
    provided the day is currently `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED`) and no case
    on the day has yet reached `IN_OR`, `IN_RECOVERY`, or `COMPLETED` (otherwise
    `ERR_DAY_HAS_ACTIVE_CASES`)."

    A LOCKED day with only a SCHEDULED case can be reopened -> posture OPEN.

    Design: Corner/state_machines/reopen_locked_day_back_to_open_cycle
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    reopened = validate_success(api_client.reopen_day(world["day"]["id"], SCHED), 200)
    assert reopened["posture"] == "OPEN", reopened["posture"]


# ===========================================================================
# Corner / state_machines / close_day_with_unfinished_case_rejected
# ===========================================================================
def test_close_day_with_unfinished_case_rejected():
    """PRD §3.3: "an `ORManager` closes a day, advancing posture `LOCKED → CLOSED`, which
    requires the day to be `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED`) and every non-cancelled
    case on it to have reached `COMPLETED` (otherwise `ERR_DAY_HAS_UNFINISHED_CASES`)."

    Closing a LOCKED day whose only case is still IN_OR -> ERR_DAY_HAS_UNFINISHED_CASES;
    posture stays LOCKED.

    Design: Corner/state_machines/close_day_with_unfinished_case_rejected
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        assign_anesthesia=True,
        world_kwargs={"with_clock": "2026-07-01T00:00:00.000Z"})
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))  # IN_OR
    resp = api_client.close_day(world["day"]["id"], ORMGR)
    validate_error(resp, ApiErrorId.ERR_DAY_HAS_UNFINISHED_CASES.value)
    after = get_success_data(api_client.get_surgical_day(world["day"]["id"], SCHED))
    assert after["posture"] == "LOCKED", after["posture"]


# ===========================================================================
# Corner / state_machines / complete_case_from_scheduled_invalid_transition
# ===========================================================================
def test_complete_scheduled_case_invalid():
    """PRD §3.11: "Completing a case advances `IN_RECOVERY → COMPLETED` and is where the case
    settles. It requires the case to be `IN_RECOVERY` (otherwise `ERR_CASE_NOT_IN_RECOVERY`),
    an `actual_minutes` value that is supplied and positive (otherwise
    `ERR_ACTUAL_MINUTES_REQUIRED`), and every `CaseImplant` on the case to already have its
    `consumed_qty` recorded (otherwise `ERR_IMPLANT_NOT_SETTLED`)."
    PRD §3.11: "Until a case is completed, both `actual_cost_cents` and `cms_payment_cents`
    are null."

    Completing a SCHEDULED case (not IN_RECOVERY) -> ERR_CASE_NOT_IN_RECOVERY; no cost computed.

    Design: Corner/state_machines/complete_case_from_scheduled_invalid_transition
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 60}, ORMGR)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_RECOVERY.value)
    after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after["actual_cost_cents"] is None, after["actual_cost_cents"]


# ===========================================================================
# Corner / state_machines / cancel_completed_case_terminal_lockdown
# ===========================================================================
def test_cancel_completed_case_rejected():
    """PRD §3.10: "Cancellation is permitted only for a `SCHEDULED` case (otherwise
    `ERR_CASE_NOT_CANCELLABLE`)."

    Cancelling a COMPLETED (terminal) case -> ERR_CASE_NOT_CANCELLABLE; stays COMPLETED.

    Design: Corner/state_machines/cancel_completed_case_terminal_lockdown
    """
    world, block, completed, _ = fixtures.setup_completed_case(
        actual_minutes=60, start_min=480, block_start=480, block_end=600)
    resp = api_client.cancel_case(completed["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_CANCELLABLE.value)
    after = get_success_data(api_client.get_surgical_case(completed["id"], SCHED))
    assert after["case_status"] == "COMPLETED", after["case_status"]


# ===========================================================================
# Corner / state_machines / case_initial_states_on_creation
# ===========================================================================
def test_booked_case_starts_scheduled_and_pending_clearance():
    """PRD §3.4: "A successful booking creates a `SurgicalCase` whose `case_status` is
    `SCHEDULED` and whose `clearance_status` is `PENDING_CLEARANCE`."

    Design: Corner/state_machines/case_initial_states_on_creation
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    assert case["case_status"] == "SCHEDULED", case["case_status"]
    assert case["clearance_status"] == "PENDING_CLEARANCE", case["clearance_status"]
