"""Composite setup helpers for the ASC Scheduling PRD.

These encapsulate the multi-step API sequences tests need to reach a specific
system state, so tests can focus on assertions, not plumbing.

The harness restarts the server (empty DB) before every test, so each helper
builds its entire world from scratch using only PRD-declared endpoints.

All four roles are opaque (PRD 2.1): X-User-ID is never matched against any
stored entity, so the shared role-constant headers are canonical everywhere.

Fixtures use get_success_data() (lenient) internally so setup failures surface
as clear "Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories

SCHED = TEST_USERS["scheduler_headers"]
NURSE = TEST_USERS["preop_nurse_headers"]
ORMGR = TEST_USERS["or_manager_headers"]
BILL = TEST_USERS["billing_analyst_headers"]


# ---------------------------------------------------------------------------
# Primitives — single-resource creators that return the created entity dict.
# ---------------------------------------------------------------------------
def create_facility(**overrides):
    return get_success_data(api_client.create_facility(factories.create_facility_payload(**overrides), SCHED))


def advance_clock(facility_id, to_iso8601):
    return get_success_data(api_client.advance_clock(facility_id, factories.advance_clock_payload(to_iso8601), SCHED))


def create_operating_room(facility_id, **overrides):
    return get_success_data(api_client.create_operating_room(factories.create_operating_room_payload(facility_id, **overrides), ORMGR))


def create_recovery_bay(facility_id, **overrides):
    return get_success_data(api_client.create_recovery_bay(factories.create_recovery_bay_payload(facility_id, **overrides), ORMGR))


def create_anesthesiologist(facility_id, **overrides):
    return get_success_data(api_client.create_anesthesiologist(factories.create_anesthesiologist_payload(facility_id, **overrides), ORMGR))


def create_surgeon(facility_id, **overrides):
    return get_success_data(api_client.create_surgeon(factories.create_surgeon_payload(facility_id, **overrides), SCHED))


def create_procedure(facility_id, **overrides):
    return get_success_data(api_client.create_procedure(factories.create_procedure_payload(facility_id, **overrides), BILL))


def create_supply_item(facility_id, **overrides):
    return get_success_data(api_client.create_supply_item(factories.create_supply_item_payload(facility_id, **overrides), ORMGR))


def create_patient(facility_id, **overrides):
    return get_success_data(api_client.create_patient(factories.create_patient_payload(facility_id, **overrides), SCHED))


def create_surgical_day(facility_id, **overrides):
    return get_success_data(api_client.create_surgical_day(factories.create_surgical_day_payload(facility_id, **overrides), SCHED))


def create_surgeon_block(surgical_day_id, surgeon_id, operating_room_id, start_min, end_min, **overrides):
    return get_success_data(api_client.create_surgeon_block(
        factories.create_surgeon_block_payload(surgical_day_id, surgeon_id, operating_room_id, start_min, end_min, **overrides), SCHED))


def book_case(block_id, expected_block_version, patient_id, procedure_id, start_min, **overrides):
    return get_success_data(api_client.book_case(
        block_id,
        factories.book_case_payload(expected_block_version, patient_id, procedure_id, start_min, **overrides),
        SCHED))


def attach_implant(case_id, supply_item_id, planned_qty, **overrides):
    return get_success_data(api_client.attach_implant(
        case_id, factories.attach_implant_payload(supply_item_id, planned_qty, **overrides), ORMGR))


def record_check(case_id, check_type, outcome):
    return get_success_data(api_client.record_clearance_check(
        case_id, factories.clearance_check_payload(check_type, outcome), NURSE))


def clear_case(case_id, hp_signed_at):
    return get_success_data(api_client.clear_case(case_id, {"hp_signed_at": hp_signed_at}, NURSE))


# ---------------------------------------------------------------------------
# Tier 2: Entity Hierarchy — an active world ready for booking.
# ---------------------------------------------------------------------------
def setup_facility_world(turnover_minutes=None, hp_validity_days=None,
                         prime_time_start_min=None, prime_time_end_min=None,
                         with_clock=None, with_bay=False, phase2_capable=True,
                         with_anesthesia=False, anesthesia_credential="MD",
                         anesthesia_active=True, proc_overrides=None):
    """Create facility + OR + surgeon + procedure + patient + day, plus optional
    recovery bay / anesthesiologist. Returns a dict of created entities.

    keys: facility, room, surgeon, procedure, patient, day, [bay], [anesthesiologist]
    """
    fac_kwargs = {}
    if turnover_minutes is not None:
        fac_kwargs["turnover_minutes"] = turnover_minutes
    if hp_validity_days is not None:
        fac_kwargs["hp_validity_days"] = hp_validity_days
    facility = create_facility(**fac_kwargs)

    if with_clock is not None:
        advance_clock(facility["id"], with_clock)

    room_kwargs = {}
    if prime_time_start_min is not None:
        room_kwargs["prime_time_start_min"] = prime_time_start_min
    if prime_time_end_min is not None:
        room_kwargs["prime_time_end_min"] = prime_time_end_min
    room = create_operating_room(facility["id"], **room_kwargs)

    surgeon = create_surgeon(facility["id"])
    procedure = create_procedure(facility["id"], **(proc_overrides or {}))
    patient = create_patient(facility["id"])
    day = create_surgical_day(facility["id"])

    world = {
        "facility": facility,
        "room": room,
        "surgeon": surgeon,
        "procedure": procedure,
        "patient": patient,
        "day": day,
    }
    if with_bay:
        world["bay"] = create_recovery_bay(facility["id"], phase2_capable=phase2_capable)
    if with_anesthesia:
        world["anesthesiologist"] = create_anesthesiologist(
            facility["id"], credential=anesthesia_credential, active=anesthesia_active)
    return world


def setup_block(world, start_min=480, end_min=600):
    """Open a HELD block on the world's day/surgeon/room. Returns the block dict."""
    return create_surgeon_block(
        world["day"]["id"], world["surgeon"]["id"], world["room"]["id"], start_min, end_min)


def setup_world_with_block(start_min=480, end_min=600, **world_kwargs):
    """Convenience: facility world + one HELD block. Returns (world, block)."""
    world = setup_facility_world(**world_kwargs)
    block = setup_block(world, start_min, end_min)
    return world, block


def setup_booked_case(start_min=480, block_start=480, block_end=600,
                      assign_anesthesia=False, assign_recovery=False,
                      world_kwargs=None, book_overrides=None):
    """facility world + HELD block + one SCHEDULED case booked at start_min.

    Returns (world, block, case). If assign_anesthesia/assign_recovery are set
    the corresponding ids are passed in the booking body (so the world must have
    been created with_anesthesia / with_bay).
    """
    world_kwargs = dict(world_kwargs or {})
    if assign_anesthesia:
        world_kwargs.setdefault("with_anesthesia", True)
    if assign_recovery:
        world_kwargs.setdefault("with_bay", True)
    world = setup_facility_world(**world_kwargs)
    block = setup_block(world, block_start, block_end)
    overrides = dict(book_overrides or {})
    if assign_anesthesia:
        overrides.setdefault("anesthesiologist_id", world["anesthesiologist"]["id"])
    if assign_recovery:
        overrides.setdefault("recovery_bay_id", world["bay"]["id"])
    case = book_case(block["id"], block["version"], world["patient"]["id"],
                     world["procedure"]["id"], start_min, **overrides)
    return world, block, case


# ---------------------------------------------------------------------------
# Tier 1 / Tier 3: clearance + lifecycle progression.
# ---------------------------------------------------------------------------
def clear_case_full(case_id, hp_signed_at="2026-07-10T00:00:00.000Z"):
    """Record an HP_REVIEW PASS check, then clear the case (clearance -> CLEARED)."""
    record_check(case_id, "HP_REVIEW", "PASS")
    return clear_case(case_id, hp_signed_at)


def setup_case_in_recovery(actual_world_clock="2026-07-01T00:00:00.000Z",
                           start_min=480, block_start=480, block_end=600,
                           hp_signed_at="2026-07-10T00:00:00.000Z",
                           world_kwargs=None, book_overrides=None,
                           implant=None):
    """Walk a single case through to IN_RECOVERY, ready for completion.

    Sequence: facility world (clock set, with bay + MD anesthesia) -> block ->
    book case (anesthesia + recovery assigned) -> [attach implant] -> HP_REVIEW
    PASS -> clear -> lock day -> start -> to-recovery.

    Returns (world, block, case, implant_dict_or_None).
    """
    wk = dict(world_kwargs or {})
    wk.setdefault("with_clock", actual_world_clock)
    wk.setdefault("with_bay", True)
    wk.setdefault("with_anesthesia", True)
    world, block, case = setup_booked_case(
        start_min=start_min, block_start=block_start, block_end=block_end,
        assign_anesthesia=True, assign_recovery=True,
        world_kwargs=wk, book_overrides=book_overrides)

    implant_dict = None
    if implant is not None:
        # implant = {"item": item_dict, "planned_qty": n, "consumed_qty": m (optional)}
        item = implant["item"]
        implant_dict = attach_implant(case["id"], item["id"], implant["planned_qty"])
        if "consumed_qty" in implant:
            get_success_data(api_client.patch_implant(
                implant_dict["id"], {"consumed_qty": implant["consumed_qty"]}, ORMGR))

    clear_case_full(case["id"], hp_signed_at)
    get_success_data(api_client.lock_day(world["day"]["id"], SCHED))
    get_success_data(api_client.start_case(case["id"], ORMGR))
    get_success_data(api_client.case_to_recovery(case["id"], ORMGR))
    return world, block, case, implant_dict


def complete_case(case_id, actual_minutes):
    """Complete a case in IN_RECOVERY. Returns the completed case dict."""
    return get_success_data(api_client.complete_case(case_id, {"actual_minutes": actual_minutes}, ORMGR))


def setup_completed_case(actual_minutes=60, **kwargs):
    """Full lifecycle through COMPLETED. Returns (world, block, case_completed, implant)."""
    world, block, case, implant = setup_case_in_recovery(**kwargs)
    completed = complete_case(case["id"], actual_minutes)
    return world, block, completed, implant


# ---------------------------------------------------------------------------
# Helpers to read current block version (booking advances version each time).
# ---------------------------------------------------------------------------
def block_version(block_id):
    return get_success_data(api_client.get_surgeon_block(block_id, SCHED))["version"]
