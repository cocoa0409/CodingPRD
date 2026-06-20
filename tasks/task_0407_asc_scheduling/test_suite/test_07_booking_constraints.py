"""Booking constraints: block-minute capacity boundary, OR turnover overlap,
anesthesia overlap, case-within-block window, supply availability, CRNA-general,
add-on day-posture gating.

Difficulty queue: boundary_precision_check / block_capacity_exact_fill_allowed_one_over_rejected;
                  resource_temporal_overlap (OR turnover buffer, anesthesia no-buffer).
Corner queue: validations section (excluded, day-locked, outside-window, supply, CRNA).
"""
from test_helpers import validate_success, validate_error, get_success_data, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


# ===========================================================================
# Difficulty / boundary_precision_check / block_capacity_exact_fill_allowed_one_over_rejected
# ===========================================================================
def test_block_capacity_exact_fill_allowed():
    """PRD §3.7: "For a non-add-on case, the booking is permitted only when the block's
    current `committed_minutes` plus the procedure's `scheduled_minutes` does not exceed the
    block's `allocated_minutes`. The boundary is inclusive: committed-plus-scheduled landing
    exactly on `allocated_minutes` is allowed, and a single minute beyond it is rejected with
    `ERR_BLOCK_CAPACITY_EXCEEDED`."

    Block allocated 120; case1 60 (committed 60), case2 60 lands committed exactly 120 ==
    allocated -> allowed.

    Design: Difficulty/boundary_precision_check/block_capacity_exact_fill_allowed_one_over_rejected
    """
    world = fixtures.setup_facility_world(turnover_minutes=0)
    fac, room, surg, day, proc = (world["facility"], world["room"], world["surgeon"],
                                  world["day"], world["procedure"])
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 600)  # alloc 120
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 540}, SCHED)
    validate_success(resp, 201)
    blk = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert blk["committed_minutes"] == 120, blk["committed_minutes"]


# NOTE: a "capacity one-over rejected" test was removed here. Per PRD §3.4 the
# booking guards run in a fixed order in which the window check
# ("the case footprint [start_min,end_min) must lie entirely within the block's
# own [start_min,end_min) window", ERR_CASE_OUTSIDE_BLOCK_WINDOW) and the OR
# turnover-conflict check both precede the block-minute capacity check
# (ERR_BLOCK_CAPACITY_EXCEEDED). Because allocated_minutes == (end_min - start_min)
# (PRD §3.4) and a block is bound to a single OR, non-overlapping in-window cases
# tile the window to at most allocated_minutes; any non-add-on booking that would
# push committed_minutes past allocated_minutes must therefore either fall outside
# the window or collide in the OR, tripping one of those higher-precedence errors
# first. The capacity-exceeded outcome is thus not uniquely derivable as a
# first-failing guard from the PRD, so a faithful PRD-only implementation never
# returns ERR_BLOCK_CAPACITY_EXCEEDED in this scenario (it returns
# ERR_CASE_OUTSIDE_BLOCK_WINDOW). The reachable half of the boundary rule
# (exact fill allowed) remains covered by test_block_capacity_exact_fill_allowed.


# ===========================================================================
# Difficulty / resource_temporal_overlap / or_overlap_with_turnover_buffer
# ===========================================================================
def test_or_overlap_within_turnover_buffer_rejected():
    """PRD §3.5: "Turnover time is appended after each case, so two cases are compatible
    only when the later case's `start_min` is at least the earlier case's `end_min` plus the
    facility's `turnover_minutes`."
    PRD §3.5: "Adjacency exactly at `end_min` plus `turnover_minutes` is permitted — that
    boundary is compatible, not a conflict — and anything tighter is rejected with
    `ERR_OR_TIME_CONFLICT`."

    case1 [480,540), turnover 25 -> next compatible start >= 565. start_min 560 < 565
    collides -> ERR_OR_TIME_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/or_overlap_with_turnover_buffer
    """
    world = fixtures.setup_facility_world(turnover_minutes=25)
    fac, room, surg, day, proc = (world["facility"], world["room"], world["surgeon"],
                                  world["day"], world["procedure"])
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 560}, SCHED)
    validate_error(resp, "ERR_OR_TIME_CONFLICT")


def test_or_adjacency_at_exact_turnover_boundary_allowed():
    """PRD §3.5: "Adjacency exactly at `end_min` plus `turnover_minutes` is permitted — that
    boundary is compatible, not a conflict — and anything tighter is rejected with
    `ERR_OR_TIME_CONFLICT`."

    case1 [480,540), turnover 25 -> compatible at start_min exactly 565; booking case2 at
    565 succeeds (boundary is compatible).

    Design: Difficulty/resource_temporal_overlap/or_overlap_with_turnover_buffer
    """
    world = fixtures.setup_facility_world(turnover_minutes=25)
    fac, room, surg, day, proc = (world["facility"], world["room"], world["surgeon"],
                                  world["day"], world["procedure"])
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 565}, SCHED)
    validate_success(resp, 201)


# ===========================================================================
# Difficulty / resource_temporal_overlap / anesthesia_overlap_no_buffer_strict
# ===========================================================================
def test_anesthesia_overlap_across_two_ors_rejected():
    """PRD §3.5: "No turnover buffer applies here — back-to-back anesthesia coverage is fine
    — so two such cases conflict precisely when one case starts before the other ends and
    that other also starts before the first ends; in plain terms, their `[start_min, end_min)`
    intervals overlap at all."

    Same anesthesiologist on two different ORs: case A [480,540), case B [510,570) overlap ->
    ERR_ANESTHESIA_TIME_CONFLICT (no turnover buffer participates).

    Design: Difficulty/resource_temporal_overlap/anesthesia_overlap_no_buffer_strict
    """
    world = fixtures.setup_facility_world(turnover_minutes=25, with_anesthesia=True)
    fac, surg, day, proc, anes = (world["facility"], world["surgeon"], world["day"],
                                  world["procedure"], world["anesthesiologist"])
    room1 = world["room"]
    room2 = fixtures.create_operating_room(fac["id"], room_label="OR-2")
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block1 = fixtures.create_surgeon_block(day["id"], surg["id"], room1["id"], 480, 720)
    block2 = fixtures.create_surgeon_block(day["id"], surg["id"], room2["id"], 480, 720)
    fixtures.book_case(block1["id"], block1["version"], pat1["id"], proc["id"], 480,
                       anesthesiologist_id=anes["id"])
    resp = api_client.book_case(block2["id"], {
        "expected_block_version": block2["version"], "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 510, "anesthesiologist_id": anes["id"]}, SCHED)
    validate_error(resp, "ERR_ANESTHESIA_TIME_CONFLICT")


def test_anesthesia_back_to_back_no_buffer_allowed():
    """PRD §3.5: "No turnover buffer applies here — back-to-back anesthesia coverage is fine
    — so two such cases conflict precisely when one case starts before the other ends and
    that other also starts before the first ends; in plain terms, their `[start_min, end_min)`
    intervals overlap at all."

    Same anesthesiologist: case A [480,540), case B starting exactly at 540 does not overlap
    (half-open intervals, no buffer) -> booking succeeds.

    Design: Difficulty/resource_temporal_overlap/anesthesia_overlap_no_buffer_strict
    """
    world = fixtures.setup_facility_world(turnover_minutes=0, with_anesthesia=True)
    fac, surg, day, proc, anes = (world["facility"], world["surgeon"], world["day"],
                                  world["procedure"], world["anesthesiologist"])
    room1 = world["room"]
    room2 = fixtures.create_operating_room(fac["id"], room_label="OR-2")
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block1 = fixtures.create_surgeon_block(day["id"], surg["id"], room1["id"], 480, 720)
    block2 = fixtures.create_surgeon_block(day["id"], surg["id"], room2["id"], 480, 720)
    fixtures.book_case(block1["id"], block1["version"], pat1["id"], proc["id"], 480,
                       anesthesiologist_id=anes["id"])
    resp = api_client.book_case(block2["id"], {
        "expected_block_version": block2["version"], "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 540, "anesthesiologist_id": anes["id"]}, SCHED)
    validate_success(resp, 201)


# ===========================================================================
# Corner / validations / book_excluded_procedure_rejected
# ===========================================================================
def test_book_excluded_procedure_rejected():
    """PRD §3.4: "the chosen procedure's `cms_payment_indicator` must not be `EXCLUDED`
    (`ERR_PROCEDURE_EXCLUDED`)..."

    Design: Corner/validations/book_excluded_procedure_rejected
    """
    world = fixtures.setup_facility_world(
        proc_overrides={"cpt_code": "99999", "description": "Excluded",
                        "cms_payment_indicator": "EXCLUDED", "cms_base_rate_cents": 0})
    block = fixtures.setup_block(world, 480, 600)
    resp = api_client.book_case(block["id"], {
        "expected_block_version": block["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 480}, SCHED)
    validate_error(resp, "ERR_PROCEDURE_EXCLUDED")


# ===========================================================================
# Corner / validations / book_non_addon_into_locked_day_rejected
# ===========================================================================
def test_book_non_addon_into_locked_day_rejected():
    """PRD §3.7: "A non-add-on booking, conversely, is rejected whenever the day's `posture`
    is `LOCKED` or `CLOSED`, with `ERR_DAY_LOCKED`."

    Design: Corner/validations/book_non_addon_into_locked_day_rejected
    """
    world = fixtures.setup_facility_world()
    fac, room, surg, day, proc = (world["facility"], world["room"], world["surgeon"],
                                  world["day"], world["procedure"])
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)
    get_success_data(api_client.lock_day(day["id"], SCHED))
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 600}, SCHED)
    validate_error(resp, "ERR_DAY_LOCKED")


# ===========================================================================
# Corner / validations / case_outside_block_window_rejected
# ===========================================================================
def test_case_outside_block_window_rejected():
    """PRD §3.4: "for a non-add-on case, the case footprint `[start_min, end_min)` must lie
    entirely within the block's own `[start_min, end_min)` window
    (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`)..."

    Case start 580 sched 60 -> end 640 exceeds block [480,600) -> ERR_CASE_OUTSIDE_BLOCK_WINDOW.

    Design: Corner/validations/case_outside_block_window_rejected
    """
    world = fixtures.setup_facility_world()
    block = fixtures.setup_block(world, 480, 600)
    resp = api_client.book_case(block["id"], {
        "expected_block_version": block["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 580}, SCHED)
    validate_error(resp, "ERR_CASE_OUTSIDE_BLOCK_WINDOW")


# ===========================================================================
# Corner / validations / insufficient_supply_attach_rejected
# ===========================================================================
def test_insufficient_supply_attach_rejected():
    """PRD §3.9: "the attach is permitted only when the supply item's available quantity
    (its `on_hand_qty` minus `reserved_qty`) is at least `planned_qty`, and otherwise
    rejected with `ERR_SUPPLY_INSUFFICIENT`."

    Item on_hand 2, attach planned_qty 3 -> available 2 < 3 -> ERR_SUPPLY_INSUFFICIENT;
    reserved_qty stays 0.

    Design: Corner/validations/insufficient_supply_attach_rejected
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    item = fixtures.create_supply_item(world["facility"]["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=2)
    resp = api_client.attach_implant(case["id"], {"supply_item_id": item["id"], "planned_qty": 3}, ORMGR)
    validate_error(resp, "ERR_SUPPLY_INSUFFICIENT")
    after = get_success_data(api_client.get_supply_item(item["id"], ORMGR))
    assert after["reserved_qty"] == 0, after["reserved_qty"]


# ===========================================================================
# Corner / validations / crna_cannot_cover_general_assign_rejected
# ===========================================================================
def test_crna_cannot_cover_general_assign_rejected():
    """PRD §3.6: "a `CRNA`-credential anesthesiologist may not solo-cover a case whose
    procedure carries an `anesthesia_class` of `GENERAL`, and such an assignment is rejected
    with `ERR_CRNA_CANNOT_COVER_GENERAL`."

    Design: Corner/validations/crna_cannot_cover_general_assign_rejected
    """
    world = fixtures.setup_facility_world(
        with_anesthesia=True, anesthesia_credential="CRNA",
        proc_overrides={"anesthesia_class": "GENERAL"})
    block = fixtures.setup_block(world, 480, 600)
    case = fixtures.book_case(block["id"], block["version"], world["patient"]["id"],
                              world["procedure"]["id"], 480)
    resp = api_client.assign_anesthesia(
        case["id"], {"anesthesiologist_id": world["anesthesiologist"]["id"]}, ORMGR)
    validate_error(resp, "ERR_CRNA_CANNOT_COVER_GENERAL")
