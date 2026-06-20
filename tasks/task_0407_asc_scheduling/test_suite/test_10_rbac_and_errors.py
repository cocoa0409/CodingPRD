"""RBAC enforcement and the remaining error-catalogue corners.

Corner queue: rbac section (peer roles, missing header) and errors section
(facility-not-found, block-released, block-not-held, day-not-open, consumed-qty-invalid,
case-not-in-or, day-has-active-cases, block-has-active-cases, day-closed,
anesthesiologist-inactive, recovery-phase2-required, implant-not-reserved x2).
"""
import pytest
from test_helpers import validate_success, validate_error, get_success_data, build_user_headers, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
NURSE = TEST_USERS["preop_nurse_headers"]
ORMGR = TEST_USERS["or_manager_headers"]
BILL = TEST_USERS["billing_analyst_headers"]


# ===========================================================================
# Corner / rbac / preopnurse_cannot_create_procedure
# ===========================================================================
def test_preopnurse_cannot_create_procedure():
    """PRD §2.1: "When the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "A `BillingAnalyst` owns the CMS procedure catalog and the cost-and-payment
    reporting surfaces, and is read-only on every operational entity."

    Creating a procedure is BillingAnalyst-exclusive; a PreOpNurse attempt ->
    ERR_INSUFFICIENT_PERMISSIONS.

    Design: Corner/rbac/preopnurse_cannot_create_procedure
    """
    fac = fixtures.create_facility()
    resp = api_client.create_procedure({
        "facility_id": fac["id"], "cpt_code": "29881", "description": "X",
        "scheduled_minutes": 60, "cms_payment_indicator": "COVERED_ASC",
        "cms_base_rate_cents": 150000, "anesthesia_class": "MAC"}, NURSE)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS")


# ===========================================================================
# Corner / rbac / scheduler_cannot_complete_case
# ===========================================================================
def test_scheduler_cannot_complete_case():
    """PRD §2.1: "When the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "An `ORManager` owns operating rooms, recovery bays, anesthesiologists, supply
    items, the intra-operative progression of a case (start, move-to-recovery, complete),
    implant settlement, and the closing of a day."

    complete is ORManager-exclusive; a Scheduler attempt -> ERR_INSUFFICIENT_PERMISSIONS
    (auth precedes the state check).

    Design: Corner/rbac/scheduler_cannot_complete_case
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 60}, SCHED)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS")


# ===========================================================================
# Corner / rbac / missing_user_context_header_rejected
# ===========================================================================
def test_unknown_role_rejected():
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role the
    system recognizes, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    A request carrying an unknown X-User-Role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    before any business logic.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    intruder = build_user_headers("intruder-1", "Intruder")
    resp = api_client.create_facility({"name": "ASC SS"}, intruder)
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


# ===========================================================================
# Corner / errors / error_facility_not_found_on_create_or
# ===========================================================================
def test_create_or_with_missing_facility_not_found():
    """PRD §2.5: "After path identifiers resolve, any foreign-key identifier supplied in a
    request body must reference a resource that exists and belongs to the same facility; a
    dangling body reference produces the same family of not-found errors at HTTP 404."

    POST /asc/operating-rooms with a non-existent facility_id -> ERR_FACILITY_NOT_FOUND (404).

    Design: Corner/errors/error_facility_not_found_on_create_or
    """
    resp = api_client.create_operating_room({
        "facility_id": "00000000-0000-4000-8000-000000000000", "room_label": "OR-1"}, ORMGR)
    validate_error(resp, "ERR_FACILITY_NOT_FOUND")


# ===========================================================================
# Corner / errors / error_block_released_on_booking
# ===========================================================================
def test_book_into_released_block_rejected():
    """PRD §3.4: "a `RELEASED` block accepts neither bookings nor confirmation, and an attempt
    to use a released block is `ERR_BLOCK_RELEASED`."

    Design: Corner/errors/error_block_released_on_booking
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    released = get_success_data(api_client.release_block(block["id"], SCHED))
    resp = api_client.book_case(block["id"], {
        "expected_block_version": released["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 480}, SCHED)
    validate_error(resp, "ERR_BLOCK_RELEASED")


# ===========================================================================
# Corner / errors / error_block_not_held_on_confirm
# ===========================================================================
def test_confirm_already_confirmed_block_rejected():
    """PRD §3.4: "A `Scheduler` confirms a block, advancing `HELD → CONFIRMED`, only when the
    block is currently `HELD` (otherwise `ERR_BLOCK_NOT_HELD`)..."

    Confirming an already-CONFIRMED block -> ERR_BLOCK_NOT_HELD.

    Design: Corner/errors/error_block_not_held_on_confirm
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    get_success_data(api_client.confirm_block(block["id"], SCHED))
    resp = api_client.confirm_block(block["id"], SCHED)
    validate_error(resp, "ERR_BLOCK_NOT_HELD")


# ===========================================================================
# Corner / errors / error_day_not_open_on_second_lock
# ===========================================================================
def test_lock_already_locked_day_rejected():
    """PRD §3.3: "Locking requires that the day is currently `OPEN` (otherwise
    `ERR_DAY_NOT_OPEN`)..."

    Locking a day already LOCKED -> ERR_DAY_NOT_OPEN.

    Design: Corner/errors/error_day_not_open_on_second_lock
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    resp = api_client.lock_day(world["day"]["id"], SCHED)
    validate_error(resp, "ERR_DAY_NOT_OPEN")


# ===========================================================================
# Corner / errors / error_consumed_qty_invalid_on_patch
# ===========================================================================
def test_consumed_qty_above_planned_rejected():
    """PRD §3.9: "An `ORManager` may record an implant's `consumed_qty` ahead of completion;
    the recorded value must lie between 0 and the implant's `planned_qty` inclusive, and a
    value outside that range is `ERR_CONSUMED_QTY_INVALID`."

    Recording consumed_qty 5 on an implant with planned_qty 2 -> ERR_CONSUMED_QTY_INVALID.

    Design: Corner/errors/error_consumed_qty_invalid_on_patch
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    item = fixtures.create_supply_item(world["facility"]["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=5)
    imp = fixtures.attach_implant(case["id"], item["id"], 2)
    resp = api_client.patch_implant(imp["id"], {"consumed_qty": 5}, ORMGR)
    validate_error(resp, "ERR_CONSUMED_QTY_INVALID")


# ===========================================================================
# Corner / errors / error_case_not_in_or_on_to_recovery
# ===========================================================================
def test_to_recovery_from_scheduled_rejected():
    """PRD §3.11: "Moving a case to recovery advances `IN_OR → IN_RECOVERY` and requires the
    case to be `IN_OR` (otherwise `ERR_CASE_NOT_IN_OR`)..."

    Moving a SCHEDULED case (not IN_OR) to recovery -> ERR_CASE_NOT_IN_OR.

    Design: Corner/errors/error_case_not_in_or_on_to_recovery
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    resp = api_client.case_to_recovery(case["id"], ORMGR)
    validate_error(resp, "ERR_CASE_NOT_IN_OR")


# ===========================================================================
# Corner / errors / error_day_has_active_cases_on_reopen
# ===========================================================================
def test_reopen_day_with_in_or_case_rejected():
    """PRD §3.3: "A `Scheduler` may reverse a lock, advancing posture `LOCKED → OPEN`,
    provided the day is currently `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED`) and no case on the
    day has yet reached `IN_OR`, `IN_RECOVERY`, or `COMPLETED` (otherwise
    `ERR_DAY_HAS_ACTIVE_CASES`)."

    Reopening a LOCKED day while a case is IN_OR -> ERR_DAY_HAS_ACTIVE_CASES; posture stays LOCKED.

    Design: Corner/errors/error_day_has_active_cases_on_reopen
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600, assign_anesthesia=True,
        world_kwargs={"with_clock": "2026-07-01T00:00:00.000Z"})
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))
    resp = api_client.reopen_day(world["day"]["id"], SCHED)
    validate_error(resp, "ERR_DAY_HAS_ACTIVE_CASES")
    after = get_success_data(api_client.get_surgical_day(world["day"]["id"], SCHED))
    assert after["posture"] == "LOCKED", after["posture"]


# ===========================================================================
# Corner / errors / error_block_has_active_cases_on_release
# ===========================================================================
def test_release_block_with_in_or_case_rejected():
    """PRD §3.4: "Release is also refused if any case in the block has already reached
    `IN_OR`, `IN_RECOVERY`, or `COMPLETED` (`ERR_BLOCK_HAS_ACTIVE_CASES`) — an in-flight or
    finished case is never force-cancelled."

    Releasing a block whose case is IN_OR -> ERR_BLOCK_HAS_ACTIVE_CASES; block stays HELD.

    Design: Corner/errors/error_block_has_active_cases_on_release
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600, assign_anesthesia=True,
        world_kwargs={"with_clock": "2026-07-01T00:00:00.000Z"})
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))
    resp = api_client.release_block(block["id"], SCHED)
    validate_error(resp, "ERR_BLOCK_HAS_ACTIVE_CASES")
    after = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert after["status"] == "HELD", after["status"]


# ===========================================================================
# Corner / errors / error_day_closed_on_confirm_block
# ===========================================================================
def test_confirm_block_on_closed_day_rejected():
    """PRD §3.4: "A `Scheduler` confirms a block, advancing `HELD → CONFIRMED`, only when the
    block is currently `HELD` (otherwise `ERR_BLOCK_NOT_HELD`), the owning surgeon is active
    (otherwise `ERR_SURGEON_INACTIVE`), and the owning day is not `CLOSED` (otherwise
    `ERR_DAY_CLOSED`)..."

    A second HELD block opened on a day that is then CLOSED cannot be confirmed -> ERR_DAY_CLOSED.

    Design: Corner/errors/error_day_closed_on_confirm_block
    """
    world, block, completed, _ = fixtures.setup_completed_case(
        actual_minutes=60, start_min=480, block_start=480, block_end=600)
    day, surg, room = world["day"], world["surgeon"], world["room"]
    block2 = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 700, 760)
    get_success_data(api_client.close_day(day["id"], ORMGR))
    resp = api_client.confirm_block(block2["id"], SCHED)
    validate_error(resp, "ERR_DAY_CLOSED")


# ===========================================================================
# Corner / errors / error_anesthesiologist_inactive_on_assign
# ===========================================================================
def test_assign_inactive_anesthesiologist_rejected():
    """PRD §3.6: "Assigning an anesthesiologist who is not active is rejected with
    `ERR_ANESTHESIOLOGIST_INACTIVE`."

    Design: Corner/errors/error_anesthesiologist_inactive_on_assign
    """
    world = fixtures.setup_facility_world(with_anesthesia=True, anesthesia_active=False)
    block = fixtures.setup_block(world, 480, 600)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480)
    resp = api_client.assign_anesthesia(
        case["id"], {"anesthesiologist_id": world["anesthesiologist"]["id"]}, ORMGR)
    validate_error(resp, "ERR_ANESTHESIOLOGIST_INACTIVE")


# ===========================================================================
# Corner / errors / error_recovery_phase2_required_on_assign
# ===========================================================================
def test_assign_non_phase2_bay_to_phase2_case_rejected():
    """PRD §3.6: "if the case's procedure has `requires_phase2` set, the chosen recovery bay
    must be `phase2_capable`, and a non-capable bay is rejected with
    `ERR_RECOVERY_PHASE2_REQUIRED`."

    Design: Corner/errors/error_recovery_phase2_required_on_assign
    """
    world = fixtures.setup_facility_world(
        with_bay=True, phase2_capable=False, proc_overrides={"requires_phase2": True})
    block = fixtures.setup_block(world, 480, 600)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480)
    resp = api_client.assign_recovery(case["id"], {"recovery_bay_id": world["bay"]["id"]}, ORMGR)
    validate_error(resp, "ERR_RECOVERY_PHASE2_REQUIRED")


# ===========================================================================
# Corner / errors / error_implant_not_reserved_on_second_release
# ===========================================================================
def test_release_already_released_implant_rejected():
    """PRD §3.9: "An `ORManager` may also release a still-`RESERVED` implant, advancing it
    `RESERVED → RELEASED`; release requires the implant to be `RESERVED` (otherwise
    `ERR_IMPLANT_NOT_RESERVED`)..."

    Releasing an already-RELEASED implant -> ERR_IMPLANT_NOT_RESERVED.

    Design: Corner/errors/error_implant_not_reserved_on_second_release
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    item = fixtures.create_supply_item(world["facility"]["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=5)
    imp = fixtures.attach_implant(case["id"], item["id"], 2)
    get_success_data(api_client.release_implant(case["id"], imp["id"], ORMGR))
    resp = api_client.release_implant(case["id"], imp["id"], ORMGR)
    validate_error(resp, "ERR_IMPLANT_NOT_RESERVED")


# ===========================================================================
# Corner / errors / error_case_already_completed_on_implant_release
# ===========================================================================
def test_release_implant_on_completed_case_rejected():
    """PRD §3.9: "(Because a completed case has all of its implants in `CONSUMED` status, the
    same precondition already prevents releasing an implant on a completed case.)"
    PRD §3.9: "release requires the implant to be `RESERVED` (otherwise
    `ERR_IMPLANT_NOT_RESERVED`)..."

    On a COMPLETED case the implant is CONSUMED, so releasing it -> ERR_IMPLANT_NOT_RESERVED.

    Design: Corner/errors/error_case_already_completed_on_implant_release
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
    imp = fixtures.attach_implant(case["id"], item["id"], 2)
    get_success_data(api_client.patch_implant(imp["id"], {"consumed_qty": 2}, ORMGR))
    fixtures.clear_case_full(case["id"])
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))
    get_success_data(api_client.case_to_recovery(case["id"], ORMGR))
    fixtures.complete_case(case["id"], 60)
    resp = api_client.release_implant(case["id"], imp["id"], ORMGR)
    validate_error(resp, "ERR_IMPLANT_NOT_RESERVED")
