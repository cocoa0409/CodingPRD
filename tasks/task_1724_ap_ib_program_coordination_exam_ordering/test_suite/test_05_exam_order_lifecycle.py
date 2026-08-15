"""Exam order lifecycle: OCC-guarded adjustment edits, estimate/final invoice
variants and their divergence, submit deadline boundary, budget cap, lock
staffing gate, and validation priority on the edit path (PRD §2.7, §2.8,
§3.4).
"""
from test_helpers import (
    COORD,
    ApiErrorId,
    administer_session,
    approve_application,
    assert_exam_order,
    cancel_registration,
    create_exam_order_payload,
    get_course,
    get_cycle,
    get_order,
    get_registration,
    lock_order,
    make_active_course,
    make_application,
    make_authorization,
    make_course,
    make_open_cycle,
    make_order,
    make_registration,
    make_session,
    make_student,
    make_submitted_order,
    make_teacher,
    authorize_teacher,
    complete_training,
    patch_order,
    reconcile_order,
    set_clock,
    submit_order,
    validate_error,
)


def _line_for(order, course_id):
    """The order carries one line per course (PRD §3.4)."""
    lines = [line for line in order["lines"] if line["course_id"] == course_id]
    assert len(lines) == 1, f"expected exactly one line for course {course_id}"
    return lines[0]


class TestAdjustmentEditingAndOcc:
    def test_occ_stale_version_rejected_and_version_increments(self, api):
        """PRD §2.7: "If the presented value does not match the order's current
        `version` — because another adjustment edit or a lifecycle action has
        advanced the order since the client's view was taken — the edit is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must
        re-read the order and re-apply its adjustments against the fresh
        version."
        PRD §3.4: "Each applied edit increments the order's `version` by 1 and
        recomputes the estimate."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_and_version_increments
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_order(cycle["id"])
        observed_version = order["version"]
        # First edit against the observed version applies.
        edited = patch_order(
            order["id"],
            observed_version,
            adjustments=[{"course_id": course["id"], "delta": 2}],
        )
        assert edited["version"] == observed_version + 1
        assert _line_for(edited, course["id"])["ordered_count"] == 3
        assert edited["estimate_total_cents"] == 3 * 9800
        # Replaying the stale version is rejected and writes nothing.
        res = api.patch_exam_order(
            order["id"],
            {
                "expected_exam_order_version": observed_version,
                "adjustments": [{"course_id": course["id"], "delta": 3}],
            },
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)
        final = get_order(order["id"])
        assert final["version"] == observed_version + 1
        assert _line_for(final, course["id"])["ordered_count"] == 3

    def test_negative_quantity_adjustment_rejected(self, api):
        """PRD §3.4: "any entry whose `delta` would drive its course's
        `ordered_count` below zero is rejected with `ERR_NEGATIVE_QUANTITY`."
        PRD §3.4: "Each course's `ordered_count` is the count of the course's
        registrations whose `registration_status` is not `CANCELLED`, plus the
        course's adjustment delta (zero when no adjustment exists)."

        Design: Corner/validations/negative_quantity_adjustment_rejected
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_order(cycle["id"])
        # 1 registered + delta -2 drives ordered_count to -1.
        res = api.patch_exam_order(
            order["id"],
            {
                "expected_exam_order_version": order["version"],
                "adjustments": [{"course_id": course["id"], "delta": -2}],
            },
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_NEGATIVE_QUANTITY, 422)

    def test_patch_on_submitted_order_state_beats_constraint(self, api):
        """PRD §2.8: "Every request is validated against a fixed, ordered
        cascade. Earlier failures mask later ones: a request that fails an
        earlier check is rejected with that check's error and never evaluated
        against later checks." State gates (step 6) precede uniqueness and
        quota gates (step 9).
        PRD §3.4: "Adjustments are editable only while the order is in `DRAFT`
        status; an edit against a submitted, locked, or reconciled order is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_order_patch
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_submitted_order(cycle["id"])
        # The edit would ALSO drive ordered_count negative (1 - 5 = -4), but
        # the state gate fires first: the response is never ERR_NEGATIVE_QUANTITY.
        res = api.patch_exam_order(
            order["id"],
            {
                "expected_exam_order_version": order["version"],
                "adjustments": [{"course_id": course["id"], "delta": -5}],
            },
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_order(order["id"])
        assert after["status"] == "SUBMITTED"
        assert after["version"] == order["version"], "rejected edit must not mutate"

    def test_patch_on_locked_order_state_beats_constraint(self, api):
        """PRD §3.4: "Adjustments are editable only while the order is in
        `DRAFT` status; an edit against a submitted, locked, or reconciled
        order is rejected with `ERR_INVALID_STATE`."
        PRD §2.8: "Earlier failures mask later ones: a request that fails an
        earlier check is rejected with that check's error and never evaluated
        against later checks."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_order_patch
        """
        cycle = make_open_cycle()
        course, teacher, _ = make_active_course(cycle["id"])
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_submitted_order(cycle["id"])
        locked = lock_order(order["id"])
        assert locked["status"] == "LOCKED"
        res = api.patch_exam_order(
            order["id"],
            {
                "expected_exam_order_version": locked["version"],
                "adjustments": [{"course_id": course["id"], "delta": -5}],
            },
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_order(order["id"])["status"] == "LOCKED"


class TestSubmitGates:
    def test_second_order_for_cycle_rejected(self, api):
        """PRD §3.4: "At most one order exists per cycle; a second create
        attempt is rejected with `ERR_ORDER_ALREADY_EXISTS`"

        Design: Corner/validations/second_order_for_cycle_rejected
        """
        cycle = make_open_cycle()
        make_order(cycle["id"])
        res = api.create_exam_order(create_exam_order_payload(cycle["id"]), COORD)
        validate_error(res, ApiErrorId.ERR_ORDER_ALREADY_EXISTS, 409)

    def test_submit_over_budget_returns_budget_exceeded(self, api):
        """PRD §3.4: "The coordinator submits the order, transitioning it from
        `DRAFT` to `SUBMITTED`, which requires the cycle to still be `OPEN` and
        requires the `estimate_total_cents` to be less than or equal to the
        cycle's `budget_cap_cents` — an estimate that exceeds the cap is
        rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Corner/validations/order_submit_over_budget_returns_budget_exceeded
        """
        cycle = make_open_cycle(budget_cap_cents=20000)
        course = make_course(cycle["id"], exam_fee_cents=9800)
        for i in range(3):
            student = make_student(full_name=f"Stu {i}")
            make_registration(student["id"], course["id"])
        order = make_order(cycle["id"])
        assert order["estimate_total_cents"] == 3 * 9800  # 29400 > 20000
        res = api.submit_exam_order(order["id"], COORD)
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED, 422)
        assert get_order(order["id"])["status"] == "DRAFT"


class TestSubmitDeadlineBoundary:
    def test_submit_exactly_at_deadline_is_on_time(self, api):
        """PRD §3.4: "resolves `submitted_late`: true when `submitted_at` is
        strictly after the cycle's `order_deadline_at`, false when it is at or
        before it."

        Design: Difficulty/boundary_precision_check/order_submit_deadline_exact_equality_not_late
        """
        # Cycle A submits exactly AT the deadline: on time.
        cycle_a = make_open_cycle(name="CYCLE-A")
        course_a = make_course(cycle_a["id"], exam_fee_cents=9800)
        student_a = make_student(full_name="Stu A")
        make_registration(student_a["id"], course_a["id"])
        order_a = make_order(cycle_a["id"])
        # Cycle B submits one second past: late.
        cycle_b = make_open_cycle(name="CYCLE-B")
        course_b = make_course(cycle_b["id"], exam_fee_cents=9800)
        student_b = make_student(full_name="Stu B")
        make_registration(student_b["id"], course_b["id"])
        order_b = make_order(cycle_b["id"])

        set_clock("2026-11-15T12:00:00Z")  # exactly the order deadline
        submitted_a = submit_order(order_a["id"])
        assert submitted_a["submitted_late"] is False
        assert submitted_a["estimate_total_cents"] == 9800

        set_clock("2026-11-15T12:00:01Z")  # one second strictly after
        submitted_b = submit_order(order_b["id"])
        assert submitted_b["submitted_late"] is True
        # Late: every ordered exam is billed the 4000 late fee.
        assert submitted_b["estimate_total_cents"] == 9800 + 4000

    def test_late_submit_folds_late_fee_into_frozen_lines(self, api):
        """PRD §3.4: "When `submitted_late` is true, every ordered exam is
        billed the cycle's `late_fee_cents`, folded into the frozen lines'
        `late_fee_total_cents`."
        PRD §3.4: "Submission freezes the `lines` as a snapshot of each
        course's `ordered_count` at that instant, freezes the
        `estimate_total_cents`"

        Design: Difficulty/boundary_precision_check/order_submit_deadline_exact_equality_not_late
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_order(cycle["id"])
        set_clock("2026-11-15T12:00:01Z")  # one second past the deadline
        submitted = submit_order(order["id"])
        assert submitted["submitted_late"] is True
        line = _line_for(submitted, course["id"])
        assert line["ordered_count"] == 1
        assert line["fee_cents"] == 9800
        assert line["late_fee_total_cents"] == 4000
        assert submitted["estimate_total_cents"] == 13800


class TestEstimateContents:
    def test_estimate_excludes_cancelled_registrations(self, api):
        """PRD §3.4: "Each course's `ordered_count` is the count of the
        course's registrations whose `registration_status` is not `CANCELLED`,
        plus the course's adjustment delta (zero when no adjustment exists)."
        PRD §3.3: "The cycle's `registered_exam_count` and the course's
        `registered_count` each count non-cancelled registrations"

        Design: Corner/calculations/order_estimate_excludes_cancelled_registrations
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student_a = make_student(full_name="Stu A")
        student_b = make_student(full_name="Stu B")
        make_registration(student_a["id"], course["id"])
        reg_b = make_registration(student_b["id"], course["id"])
        cancel_registration(reg_b["id"])
        order = make_order(cycle["id"])
        assert_exam_order(order)
        assert _line_for(order, course["id"])["ordered_count"] == 1
        assert order["estimate_total_cents"] == 9800
        assert get_course(course["id"])["registered_count"] == 1
        assert get_cycle(cycle["id"])["registered_exam_count"] == 1

    def test_estimate_frozen_at_submit_ignores_later_registrations(self, api):
        """PRD §3.4: "Submission freezes the `lines` as a snapshot of each
        course's `ordered_count` at that instant, freezes the
        `estimate_total_cents`"
        PRD §3.4: "while it remains a draft it is a living document: its
        `lines` ... and its `estimate_total_cents` are computed live and
        recomputed on every registration creation or cancellation"

        Design: Corner/calculations/estimate_frozen_at_submit_ignores_later_registrations
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student_a = make_student(full_name="Stu A")
        student_b = make_student(full_name="Stu B")
        make_registration(student_a["id"], course["id"])
        order = make_submitted_order(cycle["id"])
        assert order["estimate_total_cents"] == 9800
        # A registration created after submission does not reopen the estimate.
        make_registration(student_b["id"], course["id"])
        frozen = get_order(order["id"])
        assert frozen["estimate_total_cents"] == 9800
        assert _line_for(frozen, course["id"])["ordered_count"] == 1
        # ... while the course's live count keeps tracking registrations.
        assert get_course(course["id"])["registered_count"] == 2


class TestEstimateVsFinalDivergence:
    def _build_order_with_three_registrations(self, api):
        """OPEN cycle, ACTIVE course (fee 9800), three on-time registrations,
        order submitted on time (estimate frozen at 29400), SCHEDULED session."""
        cycle = make_open_cycle()
        course, instructor, _ = make_active_course(
            cycle["id"], subject_code="AP_CALC_BC", exam_fee_cents=9800
        )
        students = [make_student(full_name=f"Stu {i}") for i in range(3)]
        registrations = [
            make_registration(s["id"], course["id"]) for s in students
        ]
        order = make_submitted_order(cycle["id"])
        session = make_session(course["id"], room_capacity=10)
        return cycle, course, registrations, order, session

    def test_no_show_makes_final_diverge_from_estimate(self, api):
        """PRD §3.4: "the sum over courses of each frozen `ordered_count`
        multiplied by the course's `exam_fee_cents`, plus the late component
        (the total frozen ordered count multiplied by `late_fee_cents` when
        `submitted_late` is true, otherwise 0), plus the unused-exam component
        — each course's unused count is the larger of zero and its frozen
        `ordered_count` minus its count of registrations with
        `registration_status` equal to `SAT`"
        PRD §3.4: "the same underlying data yields an estimate and a final that
        differ whenever no-shows or post-submit cancellations exist."

        Design: Difficulty/dual_variant_calc/order_invoice_estimate_vs_final_divergence
        """
        cycle, course, registrations, order, session = (
            self._build_order_with_three_registrations(api)
        )
        assert order["estimate_total_cents"] == 3 * 9800  # 29400, on time
        # r3 does not sit: NO_SHOW leaves one ordered exam unused.
        set_clock("2027-05-05T12:00:00Z")
        administer_session(
            session["id"], [registrations[0]["id"], registrations[1]["id"]]
        )
        lock_order(order["id"])
        reconciled = reconcile_order(order["id"])
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["estimate_total_cents"] == 29400
        # 29400 + 1 unused x 1500 penalty.
        assert reconciled["final_total_cents"] == 30900
        assert reconciled["estimate_total_cents"] != reconciled["final_total_cents"]

    def test_post_submit_cancellation_surfaces_as_unused_exam(self, api):
        """PRD §3.4: "Because ordered counts are the submit-time snapshot,
        cancellations after submission surface as unused exams"
        PRD §3.4: "A locked order transitions from `LOCKED` to `RECONCILED` —
        the order's terminal state — only when every registration in the cycle
        is resolved, meaning each has a `registration_status` of `SAT`,
        `NO_SHOW`, or `CANCELLED`"

        Design: Difficulty/dual_variant_calc/order_invoice_estimate_vs_final_divergence
        """
        cycle, course, registrations, order, session = (
            self._build_order_with_three_registrations(api)
        )
        # r3 cancels AFTER submission: still counts in the frozen line.
        cancel_registration(registrations[2]["id"])
        set_clock("2027-05-05T12:00:00Z")
        administer_session(
            session["id"], [registrations[0]["id"], registrations[1]["id"]]
        )
        lock_order(order["id"])
        reconciled = reconcile_order(order["id"])
        assert reconciled["estimate_total_cents"] == 29400
        assert reconciled["final_total_cents"] == 29400 + 1500


class TestMultibranchEstimate:
    def test_late_submission_with_subsidy_estimate(self, api):
        """PRD §3.4: "The invoice estimate is the sum over courses of each
        `ordered_count` multiplied by the course's `exam_fee_cents`, plus a
        late component — when the current logical-clock reading is strictly
        after the cycle's `order_deadline_at`, the late component is the total
        ordered count across all courses multiplied by the cycle's
        `late_fee_cents`, and otherwise it is 0 — minus a subsidy component
        equal to the sum of `subsidy_cents` over every non-cancelled
        registration in the cycle at evaluation time."

        Design: Difficulty/combinatorial_formula/order_invoice_multibranch_mode_a
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student_a = make_student(full_name="Stu A")
        student_b = make_student(full_name="Stu B")
        student_c = make_student(full_name="Stu C", subgroup_code="FRL")
        make_registration(student_a["id"], course["id"])
        reg_c = make_registration(student_c["id"], course["id"])
        application = make_application(student_c["id"], cycle["id"])
        approve_application(application["id"])
        # Student B registers after the registration deadline: late branch.
        set_clock("2026-11-10T00:00:00Z")
        reg_b = make_registration(student_b["id"], course["id"])
        assert reg_b["is_late"] is True
        assert reg_b["late_fee_applied_cents"] == 4000
        assert get_registration(reg_c["id"])["subsidy_cents"] == 3600
        assert get_registration(reg_c["id"])["net_fee_cents"] == 6200
        order = make_order(cycle["id"])
        # Submit strictly after the order deadline: whole-order late branch.
        set_clock("2026-11-20T00:00:00Z")
        submitted = submit_order(order["id"])
        assert submitted["submitted_late"] is True
        # 3 x 9800 fees + 3 x 4000 late-order component - 3600 subsidy.
        assert submitted["estimate_total_cents"] == 37800

    def test_on_time_submission_with_subsidy_estimate(self, api):
        """PRD §3.4: "plus a late component — when the current logical-clock
        reading is strictly after the cycle's `order_deadline_at`, the late
        component is the total ordered count across all courses multiplied by
        the cycle's `late_fee_cents`, and otherwise it is 0 — minus a subsidy
        component equal to the sum of `subsidy_cents` over every non-cancelled
        registration in the cycle at evaluation time."
        PRD §3.4: "resolves `submitted_late`: true when `submitted_at` is
        strictly after the cycle's `order_deadline_at`, false when it is at or
        before it."

        Design: Difficulty/combinatorial_formula/order_invoice_multibranch_mode_a
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student_a = make_student(full_name="Stu A")
        student_c = make_student(full_name="Stu C", subgroup_code="FRL")
        make_registration(student_a["id"], course["id"])
        make_registration(student_c["id"], course["id"])
        application = make_application(student_c["id"], cycle["id"])
        approve_application(application["id"])
        order = make_order(cycle["id"])
        # Default clock (2026-08-01) precedes the order deadline: on time.
        submitted = submit_order(order["id"])
        assert submitted["submitted_late"] is False
        # 2 x 9800 fees + 0 late - 3600 subsidy.
        assert submitted["estimate_total_cents"] == 16000


class TestLockStaffingGate:
    def test_lock_blocked_until_teacher_authorized(self, api):
        """PRD §3.4: "A submitted order transitions from `SUBMITTED` to
        `LOCKED` only when every course appearing in the frozen lines with an
        `ordered_count` greater than 0 has an `authorized_teacher_count` of at
        least 1; otherwise the lock is rejected with
        `ERR_TEACHER_NOT_AUTHORIZED`."

        Design: Difficulty/cross_entity_state_dependency/order_lock_requires_authorized_teacher
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_submitted_order(cycle["id"])
        # The course's only authorization record is PENDING_TRAINING.
        teacher = make_teacher()
        auth = make_authorization(teacher["id"], course["id"])
        res = api.lock_exam_order(order["id"], COORD)
        validate_error(res, ApiErrorId.ERR_TEACHER_NOT_AUTHORIZED, 422)
        # Once the record flips to AUTHORIZED (count 0 -> 1), the gate lifts.
        complete_training(auth["id"], teacher["id"])
        locked = lock_order(order["id"])
        assert locked["status"] == "LOCKED"
        assert locked["locked_at"] is not None

    def test_lock_blocked_by_any_one_unstaffed_course(self, api):
        """PRD §3.4: "A submitted order transitions from `SUBMITTED` to
        `LOCKED` only when every course appearing in the frozen lines with an
        `ordered_count` greater than 0 has an `authorized_teacher_count` of at
        least 1; otherwise the lock is rejected with
        `ERR_TEACHER_NOT_AUTHORIZED`."

        Design: Difficulty/cross_entity_state_dependency/order_lock_requires_authorized_teacher
        """
        cycle = make_open_cycle()
        course_a, _, _ = make_active_course(
            cycle["id"], subject_code="AP_CALC_BC", exam_fee_cents=9800
        )
        # Second course has registrations but no authorized teacher.
        course_b = make_course(
            cycle["id"], subject_code="AP_BIOLOGY", exam_fee_cents=9800
        )
        student_a = make_student(full_name="Stu A")
        student_b = make_student(full_name="Stu B")
        make_registration(student_a["id"], course_a["id"])
        make_registration(student_b["id"], course_b["id"])
        order = make_submitted_order(cycle["id"])
        res = api.lock_exam_order(order["id"], COORD)
        validate_error(res, ApiErrorId.ERR_TEACHER_NOT_AUTHORIZED, 422)
        assert get_order(order["id"])["status"] == "SUBMITTED"
        # Staffing the second course lifts the gate.
        teacher_b = make_teacher(full_name="T Two", email="t2@x.edu")
        authorize_teacher(teacher_b["id"], course_b["id"])
        locked = lock_order(order["id"])
        assert locked["status"] == "LOCKED"
