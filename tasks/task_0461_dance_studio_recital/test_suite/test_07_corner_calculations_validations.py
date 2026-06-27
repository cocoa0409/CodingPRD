"""Corner coverage — calculations (credit waterfall, ticket allotment, chaperone boundary)
and validations (level, age band, duplicate invoice, instructor overload, makeup ineligibility,
costume not-enrolled).

Queue B (Corner): sections `calculations` and `validations`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]


# =========================================================================
# calculations
# =========================================================================
def test_invoice_credit_waterfall_partial(api):
    """PRD §3.9: "`credit_applied_cents` is the smaller of the family's `account_credit_cents` and
    that gross, and the family's `account_credit_cents` is decremented by the amount applied at
    generation. Finally, `amount_due_cents` is the gross minus the applied credit, floored at zero
    so it is never negative."

    Family with 3000 credit, one CONFIRMED enrollment tuition 8000: credit_applied 3000,
    amount_due 5000.

    Design: Corner/calculations/invoice_credit_waterfall_partial
    """
    env = fx.setup_confirmed_enrollment()
    fx.grant_credit(env["family"]["id"], 3000)
    invoice = validate_success(api.generate_invoice(
        f.generate_invoice_payload(env["family"]["id"], env["term"]["id"], "2026-02"), ADMIN_H),
        expected_status=201)
    assert invoice["tuition_cents"] == 8000
    assert invoice["credit_applied_cents"] == 3000
    assert invoice["amount_due_cents"] == 5000


def test_ticket_allotment_first_free_then_paid(api):
    """PRD §3.8: "count the holding family's seats already in `HELD` or `PURCHASED` status for this
    recital; if that count is below the recital's `free_tickets_per_family`, the seat's
    `is_complimentary` is true and its `price_cents` is 0, otherwise `is_complimentary` is false
    and `price_cents` is the recital's `ticket_price_cents`."

    free_tickets_per_family=1: the family's 1st held seat is complimentary (0); the 2nd is paid (2000).

    Design: Corner/calculations/ticket_comp_then_paid_allotment
    """
    base = fx.setup_recital_on_sale(recital_overrides={
        "total_seats": 5, "ticket_price_cents": 2000, "free_tickets_per_family": 1})
    family = fx.create_family()
    seat1 = validate_success(api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], "A-1", base["recital_version"]), ADMIN_H),
        expected_status=201)
    rec_v2 = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))["version"]
    seat2 = validate_success(api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], "A-2", rec_v2), ADMIN_H), expected_status=201)
    assert seat1["is_complimentary"] is True
    assert seat1["price_cents"] == 0
    assert seat2["is_complimentary"] is False
    assert seat2["price_cents"] == 2000


def test_chaperone_boundary_one_over_multiple_rejected(api):
    """PRD §3.7: "the number of chaperones required is the `participant_count` divided by the
    `chaperone_ratio` and rounded up to the next whole number, and this required count must be at
    most the `chaperone_count`. A participant count exactly divisible by the ratio needs exactly
    that quotient; one participant over a multiple bumps the requirement up by one. Failing this is
    rejected with `ERR_INSUFFICIENT_CHAPERONES`."

    9 participants, ratio 4, 2 chaperones: ceil(9/4)=3 > 2 -> rejected (one over the 8 multiple).

    Design: Corner/calculations/chaperone_boundary_one_over_multiple
    """
    setup = fx.setup_proposed_trip(num_participants=9, chaperone_ratio=4, chaperone_count=2,
                                   per_member_cost_cents=30000, min_level="NOVICE")
    resp = api.confirm_trip(setup["trip"]["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CHAPERONES.value)
    trip_after = validate_success(api.get_trip(setup["trip"]["id"], ADMIN_H))
    assert trip_after["status"] == "PROPOSED"
    assert trip_after["participant_count"] == 9


# =========================================================================
# validations
# =========================================================================
def test_level_too_low_blocks_enrollment(api):
    """PRD §3.3: "The student's `level` must be at least the section's `required_level` on the
    ordinal ladder — a level below the requirement is rejected with `ERR_LEVEL_TOO_LOW`."

    A PETITE student into a required_level ADVANCED section -> ERR_LEVEL_TOO_LOW.

    Design: Corner/validations/level_too_low_blocks_enrollment
    """
    env = fx.setup_open_term_with_section(section_overrides={
        "discipline": "BALLET", "required_level": "ADVANCED",
        "min_age": 5, "max_age": 18, "monthly_tuition_cents": 9000})
    family = fx.create_family()
    student = fx.create_student(family["id"], level="PETITE")
    resp = api.create_enrollment(
        f.create_enrollment_payload(student["id"], env["section"]["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_LEVEL_TOO_LOW.value)


def test_age_out_of_band_blocks_enrollment(api):
    """PRD §3.3: "the student's `age_as_of_cutoff` must fall within the section's inclusive
    `min_age`-to-`max_age` band — an age below `min_age` or above `max_age` is rejected with
    `ERR_AGE_OUT_OF_BAND`."

    A student born 2013-06-01 (age 12 as of 2026-02-01 cutoff) into a min 5 / max 8 section ->
    ERR_AGE_OUT_OF_BAND.

    Design: Corner/validations/age_out_of_band_blocks_enrollment
    """
    env = fx.setup_open_term_with_section(
        section_overrides={"discipline": "BALLET", "required_level": "PETITE",
                           "min_age": 5, "max_age": 8, "monthly_tuition_cents": 5000},
        term_overrides={"age_cutoff_date": "2026-02-01"})
    family = fx.create_family()
    student = fx.create_student(family["id"], birth_date="2013-06-01", level="ELITE")
    resp = api.create_enrollment(
        f.create_enrollment_payload(student["id"], env["section"]["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_BAND.value)


def test_duplicate_invoice_rejected(api):
    """PRD §3.9: "At most one non-`VOID` invoice may exist per family, term, and billing month; a
    duplicate is rejected with `ERR_DUPLICATE_INVOICE`."

    Design: Corner/validations/duplicate_invoice_rejected
    """
    env = fx.setup_confirmed_enrollment()
    fx.generate_invoice(env["family"]["id"], env["term"]["id"], "2026-02")
    resp = api.generate_invoice(
        f.generate_invoice_payload(env["family"]["id"], env["term"]["id"], "2026-02"), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE.value)


def test_instructor_overloaded_rejected(api):
    """PRD §3.2: "the assignment must not push the instructor's total session count across all
    sections above their `max_weekly_sessions`, which is rejected with `ERR_INSTRUCTOR_OVERLOADED`."

    An instructor with max_weekly_sessions=1 already teaching one session: a 2nd session on
    another (non-conflicting) section -> ERR_INSTRUCTOR_OVERLOADED.

    Design: Corner/validations/instructor_overloaded_rejected
    """
    term = fx.create_term()
    room1 = fx.create_room(capacity=10)
    room2 = fx.create_room(capacity=10)
    instructor = fx.create_instructor(email="ovi@x.com", max_weekly_sessions=1)
    secA = fx.create_section(term["id"], room1["id"], instructor["id"], discipline="JAZZ")
    fx.add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room2["id"], instructor["id"], discipline="TAP")
    resp = api.create_session(secB["id"], f.create_session_payload(
        day_of_week=1, start_minute=600, end_minute=660), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_OVERLOADED.value)


def test_makeup_citing_present_attendance_rejected(api):
    """PRD §3.5: "A makeup placement is an enrollment that cites such an attendance: it is allowed
    only when the cited attendance is `makeup_eligible` (that is, `ABSENT_EXCUSED` and not yet
    consumed) ... A citation that fails either condition is rejected with `ERR_MAKEUP_INELIGIBLE`."

    Booking a makeup citing a PRESENT (not ABSENT_EXCUSED) attendance -> ERR_MAKEUP_INELIGIBLE.

    Design: Corner/validations/makeup_ineligible_when_present
    """
    env = fx.setup_open_term_two_sections(
        secA_overrides={"discipline": "JAZZ", "monthly_tuition_cents": 8000},
        secB_overrides={"discipline": "TAP", "monthly_tuition_cents": 8000},
    )
    # secA session created at 600-660 day 0 by the two-section fixture.
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")
    enr = fx.create_enrollment(student["id"], env["secA"]["id"])
    sessions = validate_paginated_sessions(api, env["secA"]["id"])
    sess_id = sessions[0]["id"]
    from test_helpers import make_instructor_headers
    instr_headers = make_instructor_headers(env["instructor"]["id"])
    att = get_success_data(api.mark_attendance(
        enr["id"], f.mark_attendance_payload(sess_id, "2026-02-02", "PRESENT"), instr_headers))
    resp = api.create_enrollment(
        f.create_enrollment_payload(student["id"], env["secB"]["id"],
                                    makeup_for_attendance_id=att["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_MAKEUP_INELIGIBLE.value)


def test_costume_order_for_unenrolled_section_rejected(api):
    """PRD §3.6: "The cited enrollment must be `CONFIRMED` or `WAITLIST_PROMOTED` in the costume's
    own section, or the order is rejected with `ERR_NOT_ENROLLED_IN_SECTION`."

    A costume on sectionA, but the cited enrollment is for sectionB -> ERR_NOT_ENROLLED_IN_SECTION.

    Design: Corner/validations/costume_order_not_enrolled_rejected
    """
    env = fx.setup_open_term_two_sections(
        secA_overrides={"discipline": "BALLET", "monthly_tuition_cents": 9000},
        secB_overrides={"discipline": "TAP", "monthly_tuition_cents": 7000},
    )
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")
    enr_b = fx.create_enrollment(student["id"], env["secB"]["id"])
    costume_a = get_success_data(api.create_costume(
        env["secA"]["id"],
        f.create_costume_payload(name="Tutu A", unit_price_cents=4000,
                                 size_window_close_date="2026-05-01"), ADMIN_H))
    resp = api.create_costume_order(
        f.create_costume_order_payload(costume_a["id"], enr_b["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_NOT_ENROLLED_IN_SECTION.value)


def validate_paginated_sessions(api, section_id):
    data, _ = validate_paginated(api.list_section_sessions(section_id, ADMIN_H))
    return data
