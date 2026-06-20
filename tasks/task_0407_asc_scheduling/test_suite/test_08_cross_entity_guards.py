"""Cross-entity guards and the intra-operative progression preconditions: start
requires day-locked + cleared + anesthesia + available OR; confirm requires an
active surgeon; to-recovery requires an assigned available bay; complete requires
actual_minutes and settled implants.

Difficulty queue: cross_entity_state_dependency (case_start_requires_day_locked,
                  block_confirm_requires_surgeon_active).
Corner queue: errors section (case_not_cleared, anesthesia_not_assigned, or_offline,
              recovery_not_assigned, actual_minutes_required, implant_not_settled).
"""
from test_helpers import validate_success, validate_error, get_success_data, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


def _booked_cleared_on_open_day():
    """Facility world (clock set, MD anesthesia) + block + booked case w/ anesthesia,
    cleared, day still OPEN. Returns (world, block, case)."""
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        assign_anesthesia=True,
        world_kwargs={"with_clock": "2026-07-01T00:00:00.000Z"})
    fixtures.clear_case_full(case["id"])
    return world, block, case


# ===========================================================================
# Difficulty / cross_entity_state_dependency / case_start_requires_day_locked
# ===========================================================================
def test_start_on_open_day_rejected():
    """PRD §3.11: "Starting requires that the case is `SCHEDULED` (otherwise
    `ERR_CASE_NOT_SCHEDULED`), that the case's `clearance_status` is `CLEARED` (otherwise
    `ERR_CASE_NOT_CLEARED` — the cross-dimension guard), that the assigned operating room's
    `status` is `AVAILABLE` (otherwise `ERR_OR_OFFLINE`), that an `anesthesiologist_id` is
    set and that anesthesiologist is active (otherwise `ERR_ANESTHESIA_NOT_ASSIGNED`), and
    that the owning day's `posture` is `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED` — a day must
    be locked before any case enters the OR)."

    A CLEARED, anesthesia-assigned case on an OPEN (not LOCKED) day cannot start ->
    ERR_DAY_NOT_LOCKED; case_status stays SCHEDULED. The parent day's posture is the gate.

    Design: Difficulty/cross_entity_state_dependency/case_start_requires_day_locked
    """
    world, block, case = _booked_cleared_on_open_day()
    resp = api_client.start_case(case["id"], ORMGR)
    validate_error(resp, "ERR_DAY_NOT_LOCKED")
    after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after["case_status"] == "SCHEDULED", after["case_status"]


def test_start_on_locked_day_succeeds():
    """PRD §3.11: "that the owning day's `posture` is `LOCKED` (otherwise
    `ERR_DAY_NOT_LOCKED` — a day must be locked before any case enters the OR). A successful
    start advances the case to `IN_OR`."

    Once the parent day is LOCKED, the same CLEARED + anesthesia-assigned case starts
    successfully into IN_OR — confirming the day-posture gate is what was blocking it.

    Design: Difficulty/cross_entity_state_dependency/case_start_requires_day_locked
    """
    world, block, case = _booked_cleared_on_open_day()
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    started = validate_success(api_client.start_case(case["id"], ORMGR), 200)
    assert started["case_status"] == "IN_OR", started["case_status"]


# ===========================================================================
# Difficulty / cross_entity_state_dependency / block_confirm_requires_surgeon_active
# ===========================================================================
def test_confirm_block_with_inactive_surgeon_rejected():
    """PRD §3.4: "A `Scheduler` confirms a block, advancing `HELD → CONFIRMED`, only when the
    block is currently `HELD` (otherwise `ERR_BLOCK_NOT_HELD`), the owning surgeon is active
    (otherwise `ERR_SURGEON_INACTIVE`), and the owning day is not `CLOSED` (otherwise
    `ERR_DAY_CLOSED`); confirmation increments the block's `version` by 1."

    A HELD block whose owning surgeon was deactivated cannot be confirmed ->
    ERR_SURGEON_INACTIVE; block stays HELD. The gate is the linked Surgeon's active flag.

    Design: Difficulty/cross_entity_state_dependency/block_confirm_requires_surgeon_active
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    get_success_data(api_client.update_surgeon(world["surgeon"]["id"], {"active": False}, SCHED))
    resp = api_client.confirm_block(block["id"], SCHED)
    validate_error(resp, "ERR_SURGEON_INACTIVE")
    after = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert after["status"] == "HELD", after["status"]


def test_confirm_block_with_active_surgeon_succeeds():
    """PRD §3.4: "A `Scheduler` confirms a block, advancing `HELD → CONFIRMED`, only when the
    block is currently `HELD` (otherwise `ERR_BLOCK_NOT_HELD`), the owning surgeon is active
    (otherwise `ERR_SURGEON_INACTIVE`), and the owning day is not `CLOSED` (otherwise
    `ERR_DAY_CLOSED`); confirmation increments the block's `version` by 1."

    With the owning surgeon active (the default), the HELD block confirms successfully to
    CONFIRMED — isolating the active-surgeon precondition as the difference from the rejection.

    Design: Difficulty/cross_entity_state_dependency/block_confirm_requires_surgeon_active
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    confirmed = validate_success(api_client.confirm_block(block["id"], SCHED), 200)
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]


# ===========================================================================
# Corner / errors / error_case_not_cleared_on_start
# ===========================================================================
def test_start_uncleared_case_rejected():
    """PRD §3.11: "Starting requires that the case is `SCHEDULED` (otherwise
    `ERR_CASE_NOT_SCHEDULED`), that the case's `clearance_status` is `CLEARED` (otherwise
    `ERR_CASE_NOT_CLEARED` — the cross-dimension guard)..."

    A case still PENDING_CLEARANCE on a LOCKED day with anesthesia assigned cannot start ->
    ERR_CASE_NOT_CLEARED.

    Design: Corner/errors/error_case_not_cleared_on_start
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600, assign_anesthesia=True)
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    resp = api_client.start_case(case["id"], ORMGR)
    validate_error(resp, "ERR_CASE_NOT_CLEARED")


# ===========================================================================
# Corner / errors / error_anesthesia_not_assigned_on_start
# ===========================================================================
def test_start_without_anesthesia_rejected():
    """PRD §3.11: "...that an `anesthesiologist_id` is set and that anesthesiologist is
    active (otherwise `ERR_ANESTHESIA_NOT_ASSIGNED`)..."

    A CLEARED case on a LOCKED day with no anesthesiologist assigned -> ERR_ANESTHESIA_NOT_ASSIGNED.

    Design: Corner/errors/error_anesthesia_not_assigned_on_start
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    resp = api_client.start_case(case["id"], ORMGR)
    validate_error(resp, "ERR_ANESTHESIA_NOT_ASSIGNED")


# ===========================================================================
# Corner / errors / error_or_offline_on_start
# ===========================================================================
def test_start_with_offline_or_rejected():
    """PRD §3.11: "...that the assigned operating room's `status` is `AVAILABLE` (otherwise
    `ERR_OR_OFFLINE`)..."

    A CLEARED, anesthesia-assigned case on a LOCKED day whose OR was set OFFLINE ->
    ERR_OR_OFFLINE.

    Design: Corner/errors/error_or_offline_on_start
    """
    world, block, case = _booked_cleared_on_open_day()
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.set_operating_room_status(world["room"]["id"], {"status": "OFFLINE"}, ORMGR))
    resp = api_client.start_case(case["id"], ORMGR)
    validate_error(resp, "ERR_OR_OFFLINE")


# ===========================================================================
# Corner / errors / error_recovery_not_assigned_on_to_recovery
# ===========================================================================
def test_to_recovery_without_bay_rejected():
    """PRD §3.11: "Moving a case to recovery advances `IN_OR → IN_RECOVERY` and requires the
    case to be `IN_OR` (otherwise `ERR_CASE_NOT_IN_OR`) and a `recovery_bay_id` to be set on
    a bay whose `status` is `AVAILABLE` (otherwise `ERR_RECOVERY_NOT_ASSIGNED`)."

    An IN_OR case with no recovery_bay_id assigned cannot move to recovery ->
    ERR_RECOVERY_NOT_ASSIGNED.

    Design: Corner/errors/error_recovery_not_assigned_on_to_recovery
    """
    world, block, case = _booked_cleared_on_open_day()
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))  # IN_OR, no bay assigned
    resp = api_client.case_to_recovery(case["id"], ORMGR)
    validate_error(resp, "ERR_RECOVERY_NOT_ASSIGNED")


# ===========================================================================
# Corner / errors / error_actual_minutes_required_on_complete
# ===========================================================================
def test_complete_with_nonpositive_actual_minutes_rejected():
    """PRD §3.11: "It requires the case to be `IN_RECOVERY` (otherwise
    `ERR_CASE_NOT_IN_RECOVERY`), an `actual_minutes` value that is supplied and positive
    (otherwise `ERR_ACTUAL_MINUTES_REQUIRED`), and every `CaseImplant` on the case to already
    have its `consumed_qty` recorded (otherwise `ERR_IMPLANT_NOT_SETTLED`)."

    Completing an IN_RECOVERY case with actual_minutes 0 (non-positive) ->
    ERR_ACTUAL_MINUTES_REQUIRED.

    Design: Corner/errors/error_actual_minutes_required_on_complete
    """
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=600)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 0}, ORMGR)
    validate_error(resp, "ERR_ACTUAL_MINUTES_REQUIRED")


# ===========================================================================
# Corner / errors / error_implant_not_settled_on_complete
# ===========================================================================
def test_complete_with_unsettled_implant_rejected():
    """PRD §3.11: "...and every `CaseImplant` on the case to already have its `consumed_qty`
    recorded (otherwise `ERR_IMPLANT_NOT_SETTLED`)."

    An IN_RECOVERY case carrying a RESERVED implant whose consumed_qty was never recorded
    cannot be completed -> ERR_IMPLANT_NOT_SETTLED.

    Design: Corner/errors/error_implant_not_settled_on_complete
    """
    world = fixtures.setup_facility_world(
        with_clock="2026-07-01T00:00:00.000Z", with_bay=True, with_anesthesia=True)
    item = fixtures.create_supply_item(world["facility"]["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=5)
    block = fixtures.setup_block(world, 480, 600)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480,
                              anesthesiologist_id=world["anesthesiologist"]["id"],
                              recovery_bay_id=world["bay"]["id"])
    fixtures.attach_implant(case["id"], item["id"], 2)  # consumed_qty NOT recorded
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))
    get_success_data(api_client.case_to_recovery(case["id"], ORMGR))
    resp = api_client.complete_case(case["id"], {"actual_minutes": 60}, ORMGR)
    validate_error(resp, "ERR_IMPLANT_NOT_SETTLED")
