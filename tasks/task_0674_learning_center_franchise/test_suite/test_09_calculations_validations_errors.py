"""Calculation corners (placement band boundary, mid-chain advancement, royalty
percentage path), validation corners (territory conflict, prereq rank, payment
mismatch, ratio caps), and error corners (diagnostic missing, score range, royalty rate).

Queue B — Corner/calculations, Corner/validations, Corner/errors.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_center, create_subject, create_level,
    create_and_activate_center, setup_operating_center_with_subject,
    setup_active_enrollment_with_worksheet,
    create_family, create_student, create_enrollment, create_and_place_enrollment,
    create_and_issue_invoice, create_invoice, create_and_open_session, book_seat,
    make_franchise_admin_headers, make_center_director_headers,
    make_instructor_headers, make_parent_headers,
)
from test_helpers import api_client as api

ADMIN = make_franchise_admin_headers()
DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ---------------------------- calculations -------------------------------
def test_diagnostic_placement_strict_band_boundary_score_25():
    """PRD §3.3: "Compute a band width as 100 divided by N, rounded up to the next whole
    number. Compute a target index as the score divided by that band width, rounded down
    to a whole number"

    4 levels -> band 25; STRICT score=25 -> floor(25/25)=1 -> rank-2 level (L2).

    Design: Corner/calculations/diagnostic_placement_strict_band_boundary_score_25
    """
    center, _ag, subject, levels = setup_operating_center_with_subject(num_levels=4)
    family = create_family(center["id"])
    student = create_student(family["id"])
    placed = create_and_place_enrollment(center["id"], student["id"], subject["id"],
                                         diagnostic_raw_score=25)
    assert placed["current_level_id"] == levels[1]["id"], \
        f"score 25, band 25 -> index 1 (L2), got {placed['current_level_id']}"


def test_advancement_mid_chain_promotes_to_next_rank_level():
    """PRD §3.4: "If such a next level exists, set `current_level_id` to it and then
    re-run the first step against the new level, so `mastered_sets_in_level` becomes the
    count of distinct mastered sets already sitting in the new level."

    Two levels, each worksheets_to_master=1: mastering set #1 at rank-1 advances
    current_level_id to the rank-2 level, resets mastered_sets_in_level to 0, enrollment
    stays ACTIVE.

    Design: Corner/calculations/advancement_mid_chain_promotes_to_next_rank_level
    """
    center, _ag, subject, levels = setup_operating_center_with_subject(
        num_levels=2, worksheets_to_master=1, mastery_score_threshold=80)
    family = create_family(center["id"])
    student = create_student(family["id"])
    enrollment = create_and_place_enrollment(center["id"], student["id"], subject["id"])
    ws = validate_success(api.create_worksheet(
        {"enrollment_id": enrollment["id"], "level_id": levels[0]["id"], "set_number": 1},
        INSTRUCTOR), expected_status=201)

    graded = validate_success(api.grade_worksheet(ws["id"], {"score": 85}, INSTRUCTOR))
    assert graded["status"] == "MASTERED"
    fresh = validate_success(api.get_enrollment(enrollment["id"], DIRECTOR))
    assert fresh["current_level_id"] == levels[1]["id"], "advanced to rank-2 level"
    assert fresh["mastered_sets_in_level"] == 0, "reset against new level"
    assert fresh["status"] == "ACTIVE", "not COMPLETED (a higher level existed)"


def test_royalty_percentage_path_when_above_minimum():
    """PRD §3.7: "Under `ROYALTY_FLOOR`, the floor applies to the percentage royalty
    alone: `royalty_owed_cents` is the greater of the percentage royalty and
    `minimum_monthly_royalty_cents`, plus the marketing amount."

    tuition 600000, rate 1000bps -> pct 60000 > min 50000 -> 60000; marketing 200bps ->
    12000; royalty_owed = 60000 + 12000 = 72000 (floor never binds). Parent pays own
    family's invoice.

    Design: Corner/calculations/royalty_percentage_path_when_above_minimum
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=600000, enrollment_fee_cents=0,
        agreement_overrides={"royalty_rate_bps": 1000, "marketing_fee_bps": 200,
                             "minimum_monthly_royalty_cents": 50000,
                             "royalty_basis": "ROYALTY_FLOOR"})
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    invoice = create_and_issue_invoice(family["id"], center["id"], "2026-05")

    parent = make_parent_headers(family["id"])
    paid = validate_success(api.pay_invoice(invoice["id"], {"amount_cents": 600000}, parent))
    assert paid["royalty_owed_cents"] == 72000, \
        f"60000 + 12000 = 72000, got {paid['royalty_owed_cents']}"


# ---------------------------- validations --------------------------------
def test_territory_conflict_on_duplicate_center():
    """PRD §3.1: "The `territory_code` is stored as an uppercase string and must be
    unique across all centers; an attempt to create a center with a `territory_code`
    another center already uses is rejected with `ERR_TERRITORY_CONFLICT`."

    Design: Corner/validations/territory_conflict_on_duplicate_center
    """
    set_clock("2026-05-01T00:00:00Z")
    validate_success(api.create_center({"name": "First", "territory_code": "TER-DUP"}, ADMIN),
                     expected_status=201)
    resp = api.create_center({"name": "Second", "territory_code": "TER-DUP"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT.value)


def test_prereq_higher_rank_rejected_on_curriculum_level():
    """PRD §3.2: "A `prereq_level_id` must reference a level in the same subject whose
    `rank` is strictly lower than the new level's `rank`, and it must not introduce a
    cycle into the prerequisite graph; a violation of either condition is rejected with
    `ERR_PREREQ_CYCLE`."

    A new rank-15 level whose prereq points to a rank-20 level (higher, not lower) ->
    ERR_PREREQ_CYCLE.

    Design: Corner/validations/prereq_higher_rank_rejected_on_curriculum_level
    """
    set_clock("2026-05-01T00:00:00Z")
    center = create_center(name="CPC")
    subject = create_subject(center["id"])
    create_level(subject["id"], 10, label="L1", worksheets_to_master=2, mastery_score_threshold=80)
    lv2 = create_level(subject["id"], 20, label="L2", worksheets_to_master=2, mastery_score_threshold=80)
    resp = api.create_curriculum_level(
        {"subject_id": subject["id"], "rank": 15, "label": "L15",
         "prereq_level_id": lv2["id"], "worksheets_to_master": 2,
         "mastery_score_threshold": 80}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PREREQ_CYCLE.value)


def test_payment_amount_mismatch_rejected():
    """PRD §3.7: "The payment request supplies an `amount_cents` that must equal the
    invoice's pinned `total_due_cents` exactly; any other amount is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    total_due 20000 (tuition 15000 + fee 5000); paying 19999 -> mismatch; stays ISSUED.

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    invoice = create_and_issue_invoice(family["id"], center["id"], "2026-05")
    assert invoice["total_due_cents"] == 20000

    resp = api.pay_invoice(invoice["id"], {"amount_cents": 19999}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
    fresh = validate_success(api.get_invoice(invoice["id"], DIRECTOR))
    assert fresh["status"] == "ISSUED"


def test_seat_cap_exceeds_instructor_ratio_cap_rejected():
    """PRD §3.5: "The `seat_cap` is the maximum number of seats and must be between 1 and
    the center's `instructor_ratio_cap` inclusive; a `seat_cap` exceeding the center's
    `instructor_ratio_cap` is rejected with `ERR_RATIO_EXCEEDED`."

    Center ratio cap 6; creating a session with seat_cap 8 -> ERR_RATIO_EXCEEDED.

    Design: Corner/validations/seat_cap_exceeds_instructor_ratio_cap_rejected
    """
    center, _ag = create_and_activate_center(clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    resp = api.create_session(
        {"center_id": center["id"], "instructor_user_id": "instr-1",
         "start_at": "2026-05-01T09:00:00Z", "end_at": "2026-05-01T10:00:00Z", "seat_cap": 8},
        DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_RATIO_EXCEEDED.value)


def test_booking_exceeds_session_seat_cap_rejected():
    """PRD §3.5: "A booking is refused when it would push `booked_seat_count` above the
    session's `seat_cap`, in which case it is rejected with `ERR_RATIO_EXCEEDED`."

    An OPEN session cap=1 already has one BOOKED record; a second booking ->
    ERR_RATIO_EXCEEDED; booked_seat_count stays 1.

    Design: Corner/validations/booking_exceeds_session_seat_cap_rejected
    """
    from test_helpers import setup_active_enrollment
    center, subject, _level, family, _student, en1 = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    st2 = create_student(family["id"], full_name="K2", birthdate="2017-01-01T00:00:00Z")
    en2 = create_and_place_enrollment(center["id"], st2["id"], subject["id"])
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 1)
    book_seat(session["id"], en1["id"])
    sess = validate_success(api.get_session(session["id"], DIRECTOR))
    resp = api.create_attendance_record(
        {"session_id": session["id"], "enrollment_id": en2["id"],
         "expected_session_version": sess["version"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_RATIO_EXCEEDED.value)
    fresh = validate_success(api.get_session(session["id"], DIRECTOR))
    assert fresh["booked_seat_count"] == 1


# ------------------------------- errors ----------------------------------
def test_diagnostic_missing_on_place_returns_error():
    """PRD §3.3: "a `diagnostic_raw_score` between 0 and 100 is present (otherwise
    `ERR_DIAGNOSTIC_MISSING`)"

    An enrollment created without a diagnostic and placed without one -> ERR_DIAGNOSTIC_MISSING.

    Design: Corner/errors/diagnostic_missing_on_place_returns_error
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(num_levels=1)
    family = create_family(center["id"])
    student = create_student(family["id"])
    en = create_enrollment(center["id"], student["id"], subject["id"])  # no diagnostic
    resp = api.place_enrollment(en["id"], {}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_DIAGNOSTIC_MISSING.value)
    fresh = validate_success(api.get_enrollment(en["id"], DIRECTOR))
    assert fresh["status"] == "PLACEMENT_PENDING"


def test_grade_score_out_of_range_returns_error():
    """PRD §3.4: "the `score` lies between 0 and 100 inclusive (otherwise
    `ERR_SCORE_OUT_OF_RANGE`)"

    Grading with score 150 (> 100) -> ERR_SCORE_OUT_OF_RANGE; worksheet stays ASSIGNED.

    Design: Corner/errors/grade_score_out_of_range_returns_error
    """
    *_rest, ws = setup_active_enrollment_with_worksheet()
    resp = api.grade_worksheet(ws["id"], {"score": 150}, INSTRUCTOR)
    validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE.value)
    fresh = validate_success(api.get_worksheet(ws["id"], DIRECTOR))
    assert fresh["status"] == "ASSIGNED"


def test_royalty_rate_invalid_on_agreement_activate():
    """PRD §3.1: "Activating a pending agreement moves it from `PENDING` to `ACTIVE`, but
    only when the sum of `royalty_rate_bps` and `marketing_fee_bps` is at most 10000 basis
    points; if the two rates together exceed 10000, activation is rejected with
    `ERR_ROYALTY_RATE_INVALID`."

    royalty 9000 + marketing 2000 = 11000 > 10000 -> rejected; agreement stays PENDING.

    Design: Corner/errors/royalty_rate_invalid_on_agreement_activate
    """
    set_clock("2026-05-01T00:00:00Z")
    center = create_center(name="CRR")
    ag = validate_success(api.create_agreement(
        {"center_id": center["id"], "royalty_rate_bps": 9000, "marketing_fee_bps": 2000,
         "minimum_monthly_royalty_cents": 50000, "royalty_basis": "ROYALTY_FLOOR"}, ADMIN),
        expected_status=201)
    resp = api.activate_agreement(ag["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROYALTY_RATE_INVALID.value)
    fresh = validate_success(api.get_agreement(ag["id"], ADMIN))
    assert fresh["status"] == "PENDING"
