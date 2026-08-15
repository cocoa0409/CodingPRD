"""Exam registration lifecycle: initial parallel state, cycle-open gate,
duplicate uniqueness scoped to non-cancelled rows, cancellation terminality,
and the register/cancel compensating invariant on money (PRD §3.3).
"""
from test_helpers import (
    COORD,
    ApiErrorId,
    assert_exam_registration,
    cancel_registration,
    create_registration_payload,
    get_cycle,
    get_registration,
    get_statement,
    make_course,
    make_cycle,
    make_open_cycle,
    make_registration,
    make_student,
    make_student_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestRegistrationCreation:
    def test_new_registration_initial_states_and_fee_snapshot(self, api):
        """PRD §3.3: "The new registration's `cycle_id` is copied from the
        course's cycle, its `registration_status` starts at `REGISTERED`, and
        a parallel score record opens with `score_status` at `PENDING` and a
        null `score`."
        PRD §3.3: "The `fee_cents` field snapshots the course's
        `exam_fee_cents` at that moment, so later course edits never reprice
        existing registrations."
        PRD §3.3: "When `is_late` is true, `late_fee_applied_cents` equals the
        cycle's `late_fee_cents`; otherwise it is 0."
        PRD §2.4: "Before any client advances it, the logical clock reads
        exactly `2026-08-01T00:00:00Z`."

        Design: Corner/state_machines/new_registration_initial_states
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        res = api.create_registration(
            create_registration_payload(student["id"], course["id"]),
            make_student_headers(student["id"]),
        )
        registration = validate_success(res, 201)
        assert_exam_registration(registration)
        assert registration["registration_status"] == "REGISTERED"
        assert registration["score_status"] == "PENDING"
        assert registration["score"] is None
        assert registration["cycle_id"] == cycle["id"]
        # Default clock (2026-08-01) precedes the registration deadline.
        assert registration["fee_cents"] == 9800
        assert registration["is_late"] is False
        assert registration["late_fee_applied_cents"] == 0
        assert registration["subsidy_cents"] == 0
        assert registration["net_fee_cents"] == 9800

    def test_accommodation_type_defaults_to_none(self, api):
        """PRD §3.3: "optionally an `accommodation_type` of `NONE`,
        `EXTENDED_TIME`, or `SEPARATE_ROOM` (omitting it defaults to `NONE`)"

        Design: Corner/entities/accommodation_type_defaults_to_none
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        student = make_student()
        registration = make_registration(student["id"], course["id"])
        assert registration["accommodation_type"] == "NONE"

    def test_registration_requires_open_cycle(self, api):
        """PRD §3.1: "While a cycle is in `SETUP`, no registrations, exam
        orders, or exam sessions may be created for it"
        PRD §3.1: "Attempts to create registrations, orders, or sessions
        against a cycle that is not `OPEN` are rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/registration_requires_open_cycle
        """
        cycle = make_cycle()  # stays SETUP
        course = make_course(cycle["id"])
        student = make_student()
        res = api.create_registration(
            create_registration_payload(student["id"], course["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        # Opening the cycle lifts the gate.
        validate_success(api.open_exam_cycle(cycle["id"], COORD), 200)
        res = api.create_registration(
            create_registration_payload(student["id"], course["id"]),
            make_student_headers(student["id"]),
        )
        registration = validate_success(res, 201)
        assert registration["registration_status"] == "REGISTERED"


class TestRegistrationUniquenessAndCancel:
    def test_duplicate_registration_rejected_then_allowed_after_cancel(self, api):
        """PRD §3.3: "at most one non-cancelled registration may exist for a
        student-and-course pair — a duplicate attempt is rejected with
        `ERR_DUPLICATE_REGISTRATION`, while a previously cancelled registration
        does not block re-registering."

        Design: Corner/validations/duplicate_registration_rejected_then_allowed_after_cancel
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        student = make_student()
        first = make_registration(student["id"], course["id"])
        res = api.create_registration(
            create_registration_payload(student["id"], course["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION, 409)
        cancel_registration(first["id"])
        res = api.create_registration(
            create_registration_payload(student["id"], course["id"]),
            make_student_headers(student["id"]),
        )
        second = validate_success(res, 201)
        assert second["registration_status"] == "REGISTERED"
        assert second["id"] != first["id"]

    def test_cancelled_registration_cannot_be_cancelled_again(self, api):
        """PRD §3.3: "Either the owning student or the coordinator may cancel a
        registration, but only while its `registration_status` is `REGISTERED`;
        cancellation moves it to `CANCELLED`, a terminal state, and moves the
        parallel `score_status` to `VOID`."
        PRD §2.8: "The target entity is in a valid from-state for the requested
        transition: registrations cancel only from `REGISTERED`"

        Design: Corner/state_machines/cancelled_registration_cannot_be_cancelled_again
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        registration = make_registration(student["id"], course["id"])
        cancel_registration(registration["id"])
        res = api.cancel_registration(registration["id"], COORD)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        # No double-decrement: the terminal registration contributes nothing.
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 0
        assert statement["projected_balance_cents"] == 0

    def test_cancel_response_reflects_cascade_immediately(self, api):
        """PRD §1: "the system follows an immediate-consistency model: every
        mutation is atomic, every derived figure is reconciled as part of the
        mutation that affects it, and the response to any write reflects the
        post-mutation state."
        PRD §3.3: "cancellation moves it to `CANCELLED`, a terminal state, and
        moves the parallel `score_status` to `VOID`."

        Design: Corner/consistency_model/cancel_response_reflects_cascade_immediately
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        registration = make_registration(student["id"], course["id"])
        # The owning student cancels (shared cancel pathway).
        res = api.cancel_registration(
            registration["id"], make_student_headers(student["id"])
        )
        cancelled = validate_success(res, 200)
        assert cancelled["registration_status"] == "CANCELLED"
        assert cancelled["score_status"] == "VOID"
        # The very next read already shows the reconciled balances.
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 0
        assert statement["projected_balance_cents"] == 0


class TestRegisterCancelMoneyInvariant:
    def test_register_cancel_pair_conserves_balance_and_rebate(self, api):
        """PRD §3.3: "The `balance_cents` is the provisional, bill-now figure:
        the sum of `net_fee_cents` over the student's registrations whose
        `registration_status` is `REGISTERED`, `SAT`, or `NO_SHOW` — cancelled
        registrations are excluded"
        PRD §3.3: "The cycle's `rebate_cents` is the sum, over every
        registration in the cycle whose `registration_status` is not
        `CANCELLED`, of that registration's rebate line"

        Design: Difficulty/compensating_invariant/register_cancel_conserves_student_balance
        """
        cycle = make_open_cycle()
        course_a = make_course(
            cycle["id"], subject_code="AP_CALC_BC", exam_fee_cents=9800
        )
        course_b = make_course(
            cycle["id"], subject_code="AP_BIOLOGY", exam_fee_cents=9800
        )
        student = make_student()
        make_registration(student["id"], course_a["id"])
        # Pre-pair figures: balance 9800, rebate round_half_up(9800 * 0.09).
        assert get_statement(student["id"])["balance_cents"] == 9800
        assert get_cycle(cycle["id"])["rebate_cents"] == 882
        second = make_registration(student["id"], course_b["id"])
        cancel_registration(second["id"])
        # The pair must leave both figures bit-identical to pre-pair values.
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 9800
        assert statement["projected_balance_cents"] == 9800
        assert get_cycle(cycle["id"])["rebate_cents"] == 882
        undone = get_registration(second["id"])
        assert undone["registration_status"] == "CANCELLED"
        assert undone["score_status"] == "VOID"

    def test_late_register_cancel_pair_returns_to_zero(self, api):
        """PRD §3.3: "The `balance_cents` is the provisional, bill-now figure:
        the sum of `net_fee_cents` over the student's registrations whose
        `registration_status` is `REGISTERED`, `SAT`, or `NO_SHOW` — cancelled
        registrations are excluded"
        PRD §3.3: "The `is_late` flag is true when the registration's creation
        time on the logical clock is strictly after the cycle's
        `registration_deadline_at`."

        Design: Difficulty/compensating_invariant/register_cancel_conserves_student_balance
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        # Late registration: balance 9800 + 4000 late fee.
        set_clock("2026-11-10T00:00:00Z")
        registration = make_registration(student["id"], course["id"])
        assert registration["is_late"] is True
        assert registration["net_fee_cents"] == 13800
        assert get_statement(student["id"])["balance_cents"] == 13800
        assert get_cycle(cycle["id"])["rebate_cents"] == 1242  # 13800 * 0.09
        cancel_registration(registration["id"])
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 0
        assert statement["projected_balance_cents"] == 0
        assert get_cycle(cycle["id"])["rebate_cents"] == 0
