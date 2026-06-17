"""Application lifecycle, priority computation, and the lottery offer engine."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_application,
    create_application_payload,
    make_officer_headers, make_student_headers,
    create_student, create_building, create_room, create_cycle,
    create_draft_application, create_submitted_application,
    run_lottery, open_assignment, accept_offer,
)

OFFICER = make_officer_headers()


# ─── Application creation & lifecycle (corner) ────────────────────────────────

def test_create_application_missing_required_field_rejected(api):
    """PRD §2.8: "Request well-formedness comes fourth: a missing required field,
    an invalid enum member, or an out-of-range integer yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_application_missing_required_field_rejected
    """
    student = create_student(full_name="Req R", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=200)
    cycle = create_cycle(term_label="REQ_T")
    payload = {"cycle_id": cycle["id"], "student_id": student["id"],
               "preferred_building_type": "NO_PREFERENCE"}  # preferred_room_type omitted
    res = api.create_application(payload, make_student_headers(student["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_new_application_starts_in_draft(api):
    """PRD §3.3: "A new application is created in `status` `DRAFT` with no
    `priority_rank` yet."

    Design: Corner/state_machines/new_application_starts_in_draft
    """
    student = create_student(full_name="Init I", class_year="SOPHOMORE",
                             gender_identity="NONBINARY", lottery_number=240)
    cycle = create_cycle(term_label="INIT_T")
    res = api.create_application(
        create_application_payload(cycle["id"], student["id"]),
        make_student_headers(student["id"]))
    app = validate_success(res, 201)
    assert_application(app)
    assert app["status"] == "DRAFT"
    assert app["priority_rank"] is None


def test_duplicate_application_same_cycle_rejected(api):
    """PRD §3.3: "a second such application in the same cycle is rejected with
    `ERR_DUPLICATE_APPLICATION` (HTTP 409)."

    Design: Corner/validations/duplicate_application_same_cycle_rejected
    """
    student = create_student(full_name="Dup D", class_year="JUNIOR",
                             gender_identity="MALE", lottery_number=350)
    cycle = create_cycle(term_label="DUP_T")
    create_draft_application(cycle["id"], student["id"], preferred_room_type="SINGLE")
    res = api.create_application(
        create_application_payload(cycle["id"], student["id"], preferred_room_type="DOUBLE"),
        make_student_headers(student["id"]))
    validate_error(res, "ERR_DUPLICATE_APPLICATION", expected_status=409)


def test_accept_on_draft_application_invalid_state(api):
    """PRD §3.6: "A non-`ASSIGNMENT_OPEN` phase or a wrong source status fails
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/accept_on_draft_application_invalid_state
    """
    student = create_student(full_name="Draft D", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=210)
    cycle = create_cycle(term_label="DRAFT_T")
    app = create_draft_application(cycle["id"], student["id"], preferred_room_type="SINGLE")
    res = api.accept_application(
        app["id"], {"expected_application_version": app["version"]},
        make_student_headers(student["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_application(app["id"], OFFICER), 200)
    assert after["status"] == "DRAFT"


def test_withdraw_after_assignment_open_invalid_state(api):
    """PRD §3.3: "A submitted application may be withdrawn while the cycle is in
    `APPLICATION_OPEN` or `LOTTERY_RUN`, moving it from `SUBMITTED` to the
    terminal `WITHDRAWN`; attempting this in another phase fails with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/withdraw_after_assignment_open_invalid_state
    """
    student = create_student(full_name="Withdraw W", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=260)
    building = create_building(name="Withdraw Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="WH1", room_type="SINGLE")
    cycle = create_cycle(term_label="WD_T")
    app = create_submitted_application(cycle["id"], student["id"],
                                       preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    res = api.withdraw_application(app["id"], make_student_headers(student["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_application(app["id"], OFFICER), 200)
    assert after["status"] == "OFFERED"


# ─── Priority & lottery ordering (corner) ─────────────────────────────────────

def test_priority_rank_senior_computed_on_submit(api):
    """PRD §3.3: "Submitting a draft moves it from `DRAFT` to `SUBMITTED` and
    computes its `priority_rank` from the applicant's class year by the priority
    rule: a `SENIOR` ranks 1, a `JUNIOR` ranks 2, a `SOPHOMORE` ranks 3, and a
    `FRESHMAN` ranks 4, where a lower rank is a better priority."

    Design: Corner/calculations/priority_rank_senior_computed_on_submit
    """
    student = create_student(full_name="Senior Pri", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=300)
    cycle = create_cycle(term_label="PRI_T")
    app = create_draft_application(cycle["id"], student["id"])
    res = api.submit_application(app["id"], make_student_headers(student["id"]))
    submitted = validate_success(res, 200)
    assert submitted["priority_rank"] == 1
    assert submitted["status"] == "SUBMITTED"


def test_lottery_priority_order_senior_beats_freshman_for_scarce_room(api):
    """PRD §3.3: "It then performs the offer selection over every application in
    `SUBMITTED` status in this cycle, processing them in a strict order: by
    `priority_rank` ascending first, then by the student's `lottery_number`
    ascending, then by `created_at` ascending."

    Design: Corner/calculations/lottery_priority_order_senior_beats_freshman_for_scarce_room
    """
    freshman = create_student(full_name="Frosh First", class_year="FRESHMAN",
                              gender_identity="MALE", lottery_number=310)
    senior = create_student(full_name="Senior Second", class_year="SENIOR",
                            gender_identity="MALE", lottery_number=311)
    building = create_building(name="Scarce Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="SC1", room_type="SINGLE")
    cycle = create_cycle(term_label="SCARCE_T")
    fr_app = create_submitted_application(cycle["id"], freshman["id"],
                                          preferred_room_type="SINGLE")
    sr_app = create_submitted_application(cycle["id"], senior["id"],
                                          preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    sr_after = validate_success(api.get_application(sr_app["id"], OFFICER), 200)
    fr_after = validate_success(api.get_application(fr_app["id"], OFFICER), 200)
    assert sr_after["status"] == "OFFERED"
    assert fr_after["status"] == "WAITLISTED"


def test_lottery_tie_break_by_lottery_number(api):
    """PRD §3.3: "processing them in a strict order: by `priority_rank` ascending
    first, then by the student's `lottery_number` ascending, then by `created_at`
    ascending."

    Design: Corner/calculations/lottery_tie_break_by_lottery_number_then_created_at
    """
    # Two SENIORs (same priority_rank). lottery_number 2 created FIRST, 1 second.
    lot2 = create_student(full_name="Lot Two", class_year="SENIOR",
                          gender_identity="FEMALE", lottery_number=2)
    lot1 = create_student(full_name="Lot One", class_year="SENIOR",
                          gender_identity="FEMALE", lottery_number=1)
    building = create_building(name="Tie Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="TIE1", room_type="SINGLE",
                gender_inclusivity="SINGLE_GENDER")
    cycle = create_cycle(term_label="TIE_T")
    l2_app = create_submitted_application(cycle["id"], lot2["id"],
                                          preferred_room_type="SINGLE")
    l1_app = create_submitted_application(cycle["id"], lot1["id"],
                                          preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    l1_after = validate_success(api.get_application(l1_app["id"], OFFICER), 200)
    l2_after = validate_success(api.get_application(l2_app["id"], OFFICER), 200)
    assert l1_after["status"] == "OFFERED", "smaller lottery_number wins the room"
    assert l2_after["status"] == "WAITLISTED"


# ─── Difficulty: dual-variant strict vs open preference ───────────────────────

def test_lottery_strict_preference_waitlists_when_open_offers(api):
    """PRD §3.3: "A candidate who states any non-`NO_PREFERENCE` preference is
    matched only against rooms satisfying every stated preference, and if no such
    room exists the candidate is waitlisted even though other open rooms remain;
    a candidate stating `NO_PREFERENCE` for both fields is matched against any
    open room with a free bed."

    Design: Difficulty/dual_variant_calc/lottery_strict_vs_open_preference_on_application
    """
    strict = create_student(full_name="Strict Stu", class_year="JUNIOR",
                            gender_identity="FEMALE", lottery_number=5)
    openst = create_student(full_name="Open Ollie", class_year="FRESHMAN",
                            gender_identity="FEMALE", lottery_number=6)
    building = create_building(name="West Hall", building_type="TRADITIONAL")
    dbl = create_room(building["id"], room_number="D1", room_type="DOUBLE",
                      gender_inclusivity="SINGLE_GENDER")
    cycle = create_cycle(term_label="SPRING_2027")
    strict_app = create_submitted_application(
        cycle["id"], strict["id"], preferred_room_type="SUITE_DOUBLE")
    open_app = create_submitted_application(
        cycle["id"], openst["id"], preferred_room_type="NO_PREFERENCE")
    run_lottery(cycle["id"])
    strict_after = validate_success(api.get_application(strict_app["id"], OFFICER), 200)
    open_after = validate_success(api.get_application(open_app["id"], OFFICER), 200)
    # strict_preference: no SUITE_DOUBLE room exists -> WAITLISTED despite the OPEN DOUBLE.
    assert strict_after["status"] == "WAITLISTED"
    # open_preference: matched against the same DOUBLE -> OFFERED.
    assert open_after["status"] == "OFFERED"
    assert open_after["offered_room_id"] == dbl["id"]


def test_lottery_no_preference_offered_same_double(api):
    """PRD §3.3: "a candidate stating `NO_PREFERENCE` for both fields is matched
    against any open room with a free bed."

    Design: Difficulty/dual_variant_calc/lottery_strict_vs_open_preference_on_application
    """
    openst = create_student(full_name="Open Only", class_year="SENIOR",
                            gender_identity="FEMALE", lottery_number=8)
    building = create_building(name="OpenOnly Hall", building_type="TRADITIONAL")
    dbl = create_room(building["id"], room_number="OD1", room_type="DOUBLE",
                      gender_inclusivity="SINGLE_GENDER")
    cycle = create_cycle(term_label="SPRING_OPEN")
    open_app = create_submitted_application(
        cycle["id"], openst["id"], preferred_building_type="NO_PREFERENCE",
        preferred_room_type="NO_PREFERENCE")
    run_lottery(cycle["id"])
    after = validate_success(api.get_application(open_app["id"], OFFICER), 200)
    assert after["status"] == "OFFERED"
    assert after["offered_room_id"] == dbl["id"]


# ─── Difficulty: tightest-fit multi-input branch ──────────────────────────────

def test_lottery_tightest_fit_picks_double_over_empty_triple(api):
    """PRD §3.3: "Among matching rooms the engine picks the tightest fit first —
    the room with the fewest free beds (the smallest difference of `bed_capacity`
    minus `occupied_bed_count`), breaking ties by the room's `created_at`
    ascending."

    Design: Difficulty/combinatorial_formula/lottery_tightest_fit_multi_input_branch_mode_a
    """
    # Seed a DOUBLE to hold 1 occupant (1 free bed) while an empty TRIPLE has 3 free.
    occ = create_student(full_name="Seed Occupant", class_year="SENIOR",
                         gender_identity="MALE", lottery_number=1)
    tight = create_student(full_name="Tight Fit", class_year="SENIOR",
                           gender_identity="MALE", lottery_number=2)
    building = create_building(name="East Hall", building_type="TRADITIONAL")
    d9 = create_room(building["id"], room_number="D9", room_type="DOUBLE",
                     gender_inclusivity="ALL_GENDER")
    create_room(building["id"], room_number="T9", room_type="TRIPLE",
                gender_inclusivity="ALL_GENDER")
    # Cycle 1: seed one occupant into the DOUBLE.
    cyc1 = create_cycle(term_label="FALL_2026B")
    occ_app = create_submitted_application(cyc1["id"], occ["id"],
                                           preferred_room_type="DOUBLE")
    run_lottery(cyc1["id"])
    open_assignment(cyc1["id"])
    accept_offer(occ_app["id"], occ["id"])
    # Cycle 2: the NO_PREFERENCE candidate should take the tightest-fit DOUBLE.
    cyc2 = create_cycle(term_label="FALL_2026C")
    tight_app = create_submitted_application(cyc2["id"], tight["id"],
                                             preferred_room_type="NO_PREFERENCE")
    run_lottery(cyc2["id"])
    after = validate_success(api.get_application(tight_app["id"], OFFICER), 200)
    assert after["status"] == "OFFERED"
    assert after["offered_room_id"] == d9["id"], "tightest fit is the partly-filled DOUBLE"


def test_lottery_tightest_fit_double_status_restricted_when_full(api):
    """PRD §3.3: "the reservation increments the room's `occupied_bed_count`,
    which may flip the room from `OPEN` to `RESTRICTED` once it reaches
    `bed_capacity`."

    Design: Difficulty/combinatorial_formula/lottery_tightest_fit_multi_input_branch_mode_a
    """
    occ = create_student(full_name="Seed2 Occ", class_year="SENIOR",
                         gender_identity="MALE", lottery_number=3)
    tight = create_student(full_name="Tight2 Fit", class_year="SENIOR",
                           gender_identity="MALE", lottery_number=4)
    building = create_building(name="East2 Hall", building_type="TRADITIONAL")
    d = create_room(building["id"], room_number="D2", room_type="DOUBLE",
                    gender_inclusivity="ALL_GENDER")
    create_room(building["id"], room_number="T2", room_type="TRIPLE",
                gender_inclusivity="ALL_GENDER")
    cyc1 = create_cycle(term_label="FALL_TF1")
    occ_app = create_submitted_application(cyc1["id"], occ["id"],
                                           preferred_room_type="DOUBLE")
    run_lottery(cyc1["id"])
    open_assignment(cyc1["id"])
    accept_offer(occ_app["id"], occ["id"])
    cyc2 = create_cycle(term_label="FALL_TF2")
    tight_app = create_submitted_application(cyc2["id"], tight["id"],
                                             preferred_room_type="NO_PREFERENCE")
    run_lottery(cyc2["id"])
    offered = validate_success(api.get_application(tight_app["id"], OFFICER), 200)
    assert offered["offered_room_id"] == d["id"]
    room = validate_success(api.get_room(d["id"], OFFICER), 200)
    assert room["occupied_bed_count"] == 2
    assert room["status"] == "RESTRICTED"


# ─── Difficulty: room-full boundary on accept (capacity equals) ───────────────

def test_room_full_boundary_occupied_equals_capacity(api):
    """PRD §2.5: "A room's `occupied_bed_count` is the number of applications
    currently in `OFFERED` status whose `offered_room_id` is this room (offer
    reservations) plus the number of assignments on this room whose status is
    either `ACTIVE` or `SWAP_PENDING` (live residents — a swap-pending assignment
    still counts because its `room_id` does not change until the swap confirms)."

    Design: Difficulty/boundary_precision_check/room_full_boundary_on_accept_capacity_equals
    """
    first = create_student(full_name="First Win", class_year="SENIOR",
                           gender_identity="MALE", lottery_number=90)
    second = create_student(full_name="Second Lose", class_year="SENIOR",
                            gender_identity="MALE", lottery_number=91)
    building = create_building(name="Full Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="FH1", room_type="DOUBLE",
                       gender_inclusivity="ALL_GENDER")
    cycle = create_cycle(term_label="FALL_2026K")
    a1 = create_submitted_application(cycle["id"], first["id"],
                                      preferred_room_type="DOUBLE")
    a2 = create_submitted_application(cycle["id"], second["id"],
                                      preferred_room_type="DOUBLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    accept_offer(a1["id"], first["id"])
    accept_offer(a2["id"], second["id"])
    after = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert after["occupied_bed_count"] == 2
    assert after["bed_capacity"] == 2


def test_room_full_boundary_flips_to_restricted(api):
    """PRD §2.5: "A room is `RESTRICTED` when it is fully booked (its
    `occupied_bed_count` has reached its `bed_capacity`) or when it carries an
    open safety incident, as detailed in §3.7."

    Design: Difficulty/boundary_precision_check/room_full_boundary_on_accept_capacity_equals
    """
    first = create_student(full_name="Fill A", class_year="SENIOR",
                           gender_identity="MALE", lottery_number=92)
    second = create_student(full_name="Fill B", class_year="SENIOR",
                            gender_identity="MALE", lottery_number=93)
    building = create_building(name="Full2 Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="FH2", room_type="DOUBLE",
                       gender_inclusivity="ALL_GENDER")
    cycle = create_cycle(term_label="FALL_FULL2")
    a1 = create_submitted_application(cycle["id"], first["id"],
                                      preferred_room_type="DOUBLE")
    a2 = create_submitted_application(cycle["id"], second["id"],
                                      preferred_room_type="DOUBLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    accept_offer(a1["id"], first["id"])
    accept_offer(a2["id"], second["id"])
    after = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert after["occupied_bed_count"] == after["bed_capacity"]
    assert after["status"] == "RESTRICTED"
