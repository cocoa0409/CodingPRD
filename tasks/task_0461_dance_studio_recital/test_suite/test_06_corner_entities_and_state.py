"""Corner coverage — entities (creation, not-found, required fields, type constraints,
computed age, attendance immutability) and state machines (invalid transitions, preconditions,
terminal lockdown, waitlist, void compensation).

Queue B (Corner): sections `entities` and `state_machines`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId,
)
from test_helpers import assertions as asserts
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# =========================================================================
# entities
# =========================================================================
def test_create_family_returns_defaults(api):
    """PRD §3.1: "A new family starts `ACTIVE` with `account_credit_cents` of zero,
    `payment_method_on_file` false, and `autopay_enabled` false."

    Design: Corner/entities/create_family_returns_201_with_defaults
    """
    family = validate_success(
        api.create_family(f.create_family_payload(email="new@x.com", family_name="New"), ADMIN_H),
        expected_status=201)
    asserts.assert_family(family)
    assert family["status"] == "ACTIVE"
    assert family["autopay_enabled"] is False
    assert family["account_credit_cents"] == 0
    assert family["payment_method_on_file"] is False


def test_family_not_found(api):
    """PRD §2.7: "the system validates the identifiers left to right and rejects the first one
    that does not resolve to a live resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/family_not_found_returns_404
    """
    resp = api.get_family(NON_EXISTENT, ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_section_missing_required_field(api):
    """PRD §2.10: "and finally generic request well-formedness (`ERR_INVALID_REQUEST`) for
    malformed bodies, out-of-range enums, and violated numeric bounds."
    PRD §3.2: "the `monthly_tuition_cents` base price for one student before discounts, and a
    `capacity_cap`."

    Design: Corner/entities/create_section_missing_required_field_returns_invalid_request
    """
    term = fx.create_term()
    room = fx.create_room(capacity=10)
    instructor = fx.create_instructor()
    payload = {
        "term_id": term["id"], "room_id": room["id"], "instructor_id": instructor["id"],
        "discipline": "JAZZ", "required_level": "PETITE", "min_age": 5, "max_age": 18,
        "capacity_cap": 20,  # monthly_tuition_cents omitted
    }
    resp = api.create_section(payload, ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_section_invalid_age_band(api):
    """PRD §2.10: "and finally generic request well-formedness (`ERR_INVALID_REQUEST`) for
    malformed bodies, out-of-range enums, and violated numeric bounds."
    PRD §3.2: "an inclusive `min_age` and `max_age` placement band (each a non-negative integer,
    with `max_age` at least `min_age`)."

    Design: Corner/entities/create_section_invalid_age_band_returns_invalid_request
    """
    term = fx.create_term()
    room = fx.create_room(capacity=10)
    instructor = fx.create_instructor()
    resp = api.create_section(
        f.create_section_payload(term["id"], room["id"], instructor["id"],
                                 min_age=12, max_age=8), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_computed_age_as_of_cutoff_floors(api):
    """PRD §3.3: "Take the difference between the cutoff year and the student's `birth_date` year;
    then, if the cutoff's month-and-day falls earlier in the calendar year than the student's
    birth month-and-day, subtract one."

    Student born 2018-06-01 against cutoff 2026-02-01: 2026-2018=8, cutoff (Feb 1) is earlier than
    birth (Jun 1) -> subtract 1 -> 7. The placement into a min 6 / max 8 section confirms.

    Design: Corner/entities/computed_age_as_of_cutoff_floor
    """
    env = fx.setup_open_term_with_section(
        section_overrides={"discipline": "BALLET", "required_level": "PETITE",
                           "min_age": 6, "max_age": 8, "monthly_tuition_cents": 5000},
        term_overrides={"age_cutoff_date": "2026-02-01"})
    family = fx.create_family()
    student = fx.create_student(family["id"], full_name="Young",
                               birth_date="2018-06-01", level="PETITE")
    enr = fx.create_enrollment(student["id"], env["section"]["id"])
    assert enr["placement_status"] == "CONFIRMED"
    student_after = validate_success(api.get_student(student["id"], ADMIN_H))
    assert student_after["age_as_of_cutoff"] == 7


def test_attendance_is_append_only_without_version(api):
    """PRD §2.4: "an `Attendance` record is append-only and carries only `id` and `created_at` —
    it has neither an `updated_at` nor a `version` field."
    PRD §3.5: "An attendance row's `makeup_eligible` is true only when its `result` is
    `ABSENT_EXCUSED` and no makeup has yet been consumed against it."

    Design: Corner/entities/attendance_immutable_no_version_field
    """
    env = fx.setup_confirmed_enrollment()
    from test_helpers import make_instructor_headers
    instr_headers = make_instructor_headers(env["instructor"]["id"])
    att = validate_success(api.mark_attendance(
        env["enrollment"]["id"],
        f.mark_attendance_payload(env["session"]["id"], "2026-02-02", "PRESENT"),
        instr_headers), expected_status=201)
    asserts.assert_attendance(att)
    assert att["result"] == "PRESENT"
    assert att["makeup_eligible"] is False
    assert "version" not in att
    assert "updated_at" not in att


# =========================================================================
# state_machines
# =========================================================================
def test_lock_already_locked_team_invalid_state(api):
    """PRD §3.7: "Once a team is `LOCKED`, further membership adds and releases are rejected with
    `ERR_INVALID_STATE`."
    PRD §3.7: "A team begins `FORMING`, where roster changes are allowed, and may be locked to
    `LOCKED`, which freezes the roster."

    Design: Corner/state_machines/lock_already_locked_team_invalid_state
    """
    team = fx.create_team(min_level="NOVICE", roster_cap=5)
    get_success_data(api.lock_team(team["id"], ADMIN_H))
    resp = api.lock_team(team["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    team_after = validate_success(api.get_team(team["id"], ADMIN_H))
    assert team_after["status"] == "LOCKED"


def test_open_term_requires_scheduled_section(api):
    """PRD §3.2: "a term may move from `DRAFT` to `OPEN` only if it has at least one section in
    `SCHEDULED` status and its `age_cutoff_date` lies within its date window."
    PRD §2.10: "then the legality of the requested state transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/open_term_requires_scheduled_section
    """
    term = fx.create_term()  # no sections at all
    resp = api.open_term(term["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    term_after = validate_success(api.get_term(term["id"], ADMIN_H))
    assert term_after["status"] == "DRAFT"


def test_completed_recital_blocks_further_transition(api):
    """PRD §3.8: "Completing a recital is a `StudioAdmin` action permitted from `ON_SALE` or
    `SOLD_OUT` only once the clock has reached or passed the `show_datetime`. On completion every
    `HELD` seat is released while `PURCHASED` seats are retained, and the recital moves to the
    terminal `COMPLETED`."

    After completion, calling open-sales again is not a legal transition -> ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_recital_complete_blocks_further_transition
    """
    base = fx.setup_recital_on_sale(recital_overrides={
        "name": "Final", "show_datetime": "2026-06-20T19:00:00Z", "total_seats": 5,
        "ticket_price_cents": 2000, "free_tickets_per_family": 0})
    get_success_data(api.set_clock("2026-06-21T00:00:00Z", ADMIN_H))
    get_success_data(api.complete_recital(base["recital"]["id"], ADMIN_H))
    resp = api.open_recital_sales(base["recital"]["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    recital_after = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    assert recital_after["status"] == "COMPLETED"


def test_close_term_blocked_by_open_invoice(api):
    """PRD §3.2: "Closing a term moves it from `OPEN` to the terminal `CLOSED`, and is permitted
    only when every invoice for that term is already `PAID` or `VOID`."
    PRD §2.10: "then the legality of the requested state transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/term_close_blocked_by_unpaid_invoice
    """
    env = fx.setup_confirmed_enrollment()
    fx.generate_invoice(env["family"]["id"], env["term"]["id"], "2026-02")  # OPEN invoice
    resp = api.close_term(env["term"]["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    term_after = validate_success(api.get_term(env["term"]["id"], ADMIN_H))
    assert term_after["status"] == "OPEN"


def test_waitlist_assignment_when_section_full(api):
    """PRD §3.3: "if the section is `FULL`, the enrollment is waitlisted."
    PRD §3.3: "When an enrollment is waitlisted, its `placement_status` becomes `WAITLISTED`, its
    `waitlist_rank` is assigned as one more than the count of enrollments already `WAITLISTED` for
    that section, ordered by `created_at` ascending, and its `billing_status` stays `UNBILLED`."

    Design: Corner/state_machines/waitlist_assignment_when_section_full
    """
    env = fx.setup_open_term_with_section(section_overrides={"capacity_cap": 1})
    family = fx.create_family()
    s1 = fx.create_student(family["id"], full_name="WL One", level="ELITE")
    s2 = fx.create_student(family["id"], full_name="WL Two", level="ELITE")
    fx.create_enrollment(s1["id"], env["section"]["id"])  # fills the slot
    enr2 = fx.create_enrollment(s2["id"], env["section"]["id"])
    assert enr2["placement_status"] == "WAITLISTED"
    assert enr2["waitlist_rank"] == 1


def test_void_open_invoice_restores_applied_credit(api):
    """PRD §3.9: "A `StudioAdmin` may void an `OPEN` or `PAST_DUE` invoice, moving it to the
    terminal `VOID`; any `credit_applied_cents` that had been drawn from the wallet at generation
    is returned to the family's `account_credit_cents`, conserving the credit balance."
    PRD §3.9: "`credit_applied_cents` is the smaller of the family's `account_credit_cents` and
    that gross."

    A family with 1500 credit, one 8000-tuition enrollment: invoice applies 1500 credit;
    voiding returns 1500 to account_credit_cents.

    Design: Corner/state_machines/invoice_void_restores_credit
    """
    env = fx.setup_confirmed_enrollment()
    fx.grant_credit(env["family"]["id"], 1500)
    invoice = fx.generate_invoice(env["family"]["id"], env["term"]["id"], "2026-02")
    assert invoice["credit_applied_cents"] == 1500
    fam_mid = validate_success(api.get_family(env["family"]["id"], ADMIN_H))
    assert fam_mid["account_credit_cents"] == 0
    validate_success(api.void_invoice(invoice["id"], ADMIN_H))
    invoice_after = validate_success(api.get_invoice(invoice["id"], ADMIN_H))
    fam_after = validate_success(api.get_family(env["family"]["id"], ADMIN_H))
    assert invoice_after["status"] == "VOID"
    assert fam_after["account_credit_cents"] == 1500
