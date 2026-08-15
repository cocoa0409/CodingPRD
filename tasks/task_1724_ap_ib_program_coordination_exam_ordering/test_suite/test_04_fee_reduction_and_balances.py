"""Fee-reduction applications, the dual student balance variants, subsidy math
with its floor, and the approval cascade into balances and rebate
(PRD §3.3).
"""
from test_helpers import (
    ApiErrorId,
    approve_application,
    assert_student_statement,
    create_fee_reduction_application_payload,
    deny_application,
    get_cycle,
    get_registration,
    get_statement,
    make_application,
    make_course,
    make_open_cycle,
    make_registration,
    make_student,
    make_student_headers,
    resubmit_application,
    set_clock,
    validate_error,
)


class TestApplicationLifecycle:
    def test_denied_application_resubmit_reapprovable_cycle(self, api):
        """PRD §3.3: "Denial changes nothing financially — the subsidy stays at
        zero — but it is not final: the owning student may resubmit the same
        row, moving it from `DENIED` back to `SUBMITTED`, at which point the
        projected balance once again counts the subsidy as potentially
        approved."

        Design: Corner/state_machines/fee_application_denied_resubmit_reapprovable_cycle
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student(subgroup_code="FRL")
        make_registration(student["id"], course["id"])
        application = make_application(
            student["id"], cycle["id"], eligibility_basis="INCOME"
        )
        denied = deny_application(application["id"])
        assert denied["status"] == "DENIED"
        # Denial moves no money.
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 9800
        assert statement["projected_balance_cents"] == 9800
        # Resubmit re-opens the same row; the optimistic variant returns.
        resubmitted = resubmit_application(application["id"], student["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["id"] == application["id"]
        assert get_statement(student["id"])["projected_balance_cents"] == 6200
        # Re-approval then moves real money: 9800 - 3600 subsidy.
        approved = approve_application(application["id"])
        assert approved["status"] == "APPROVED"
        assert get_statement(student["id"])["balance_cents"] == 6200

    def test_duplicate_application_rejected_even_when_denied(self, api):
        """PRD §3.3: "At most one application row ever exists for a
        student-and-cycle pair; a second filing for the same pair is rejected
        with `ERR_DUPLICATE_APPLICATION`."

        Design: Corner/validations/duplicate_application_rejected
        """
        cycle = make_open_cycle()
        student = make_student(subgroup_code="FRL")
        application = make_application(
            student["id"], cycle["id"], eligibility_basis="INCOME"
        )
        deny_application(application["id"])
        res = api.create_fee_reduction_application(
            create_fee_reduction_application_payload(
                student["id"], cycle["id"], eligibility_basis="FREE_LUNCH"
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_APPLICATION, 409)


class TestDualBalanceVariants:
    def test_submitted_application_diverges_provisional_from_projected(self, api):
        """PRD §3.3: "The `balance_cents` is the provisional, bill-now figure:
        the sum of `net_fee_cents` over the student's registrations whose
        `registration_status` is `REGISTERED`, `SAT`, or `NO_SHOW` — cancelled
        registrations are excluded — with subsidies counted only from
        `APPROVED` applications."
        PRD §3.3: "it is the same sum, except that an application in
        `SUBMITTED` status is treated as if approved, so its full subsidy
        counts."

        Design: Difficulty/dual_variant_calc/student_balance_provisional_vs_projected_divergence
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student(subgroup_code="FRL")
        make_registration(student["id"], course["id"])
        make_application(student["id"], cycle["id"])
        statement = get_statement(student["id"])
        assert_student_statement(statement)
        # Provisional: the undecided application contributes no subsidy.
        assert statement["balance_cents"] == 9800
        # Projected: 9800 - min(3600, 9800).
        assert statement["projected_balance_cents"] == 6200
        assert statement["balance_cents"] != statement["projected_balance_cents"]

    def test_decided_application_makes_variants_coincide(self, api):
        """PRD §3.3: "Whenever an undecided application exists, the two figures
        diverge; once every application is decided, they coincide."

        Design: Difficulty/dual_variant_calc/student_balance_provisional_vs_projected_divergence
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], exam_fee_cents=9800)
        student = make_student(subgroup_code="FRL")
        make_registration(student["id"], course["id"])
        application = make_application(student["id"], cycle["id"])
        approve_application(application["id"])
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 6200
        assert statement["projected_balance_cents"] == 6200


class TestApprovalCascade:
    def test_approval_recomputes_subsidy_balance_and_rebate(self, api):
        """PRD §3.3: "The `subsidy_cents` of each of the student's
        non-cancelled registrations in the cycle is recomputed — registrations
        created at full price gain their subsidy retroactively — and each
        recomputed registration in turn triggers reconciliation of the
        student's `balance_cents` and `projected_balance_cents` and of the
        cycle's `rebate_cents`."

        Design: Difficulty/transitive_cascade/fee_approval_cascade_depth2
        """
        cycle = make_open_cycle()
        course_1 = make_course(cycle["id"], subject_code="AP_CALC_BC")
        course_2 = make_course(cycle["id"], subject_code="AP_BIOLOGY")
        student = make_student(subgroup_code="FRL")
        reg_1 = make_registration(student["id"], course_1["id"])
        make_registration(student["id"], course_2["id"])
        # Pre-approval: full price everywhere.
        assert get_statement(student["id"])["balance_cents"] == 19600
        assert get_cycle(cycle["id"])["rebate_cents"] == 1764  # 2 x 882
        application = make_application(student["id"], cycle["id"])
        approve_application(application["id"])
        # Link 1: each registration gains its subsidy retroactively.
        updated = get_registration(reg_1["id"])
        assert updated["subsidy_cents"] == 3600
        assert updated["net_fee_cents"] == 6200
        # Link 2: balances and rebate reconcile off the mutated registrations.
        assert get_statement(student["id"])["balance_cents"] == 12400
        # 2 x round_half_up(6200 * 900 / 10000) = 2 x 558.
        assert get_cycle(cycle["id"])["rebate_cents"] == 1116

    def test_denial_leaves_subsidy_balance_and_rebate_untouched(self, api):
        """PRD §3.3: "Denial changes nothing financially — the subsidy stays at
        zero"
        PRD §3.3: "applications still `SUBMITTED` or already `DENIED`
        contribute nothing to the subsidy."

        Design: Difficulty/transitive_cascade/fee_approval_cascade_depth2
        """
        cycle = make_open_cycle()
        course_1 = make_course(cycle["id"], subject_code="AP_CALC_BC")
        course_2 = make_course(cycle["id"], subject_code="AP_BIOLOGY")
        student = make_student(subgroup_code="FRL")
        reg_1 = make_registration(student["id"], course_1["id"])
        make_registration(student["id"], course_2["id"])
        application = make_application(student["id"], cycle["id"])
        deny_application(application["id"])
        updated = get_registration(reg_1["id"])
        assert updated["subsidy_cents"] == 0
        assert updated["net_fee_cents"] == 9800
        statement = get_statement(student["id"])
        assert statement["balance_cents"] == 19600
        assert statement["projected_balance_cents"] == 19600
        assert get_cycle(cycle["id"])["rebate_cents"] == 1764


class TestNetFeeMath:
    def test_late_fee_stacks_and_subsidy_floors_at_charge(self, api):
        """PRD §3.3: "The `subsidy_cents` field is the smaller of the cycle's
        `fee_reduction_cents` and the sum of `fee_cents` plus
        `late_fee_applied_cents` when the student holds an `APPROVED`
        fee-reduction application for the cycle, and 0 otherwise"
        PRD §3.3: "The `net_fee_cents` is then `fee_cents` plus
        `late_fee_applied_cents` minus `subsidy_cents`, which is always at
        least 0 because the subsidy is capped by the fee-plus-late total."

        Design: Corner/calculations/net_fee_late_and_subsidy_floor_math
        """
        cycle = make_open_cycle()
        course_full = make_course(
            cycle["id"], subject_code="AP_CALC_BC", exam_fee_cents=9800
        )
        course_cheap = make_course(
            cycle["id"], subject_code="AP_STUDIO", exam_fee_cents=2000
        )
        student = make_student(subgroup_code="FRL")
        application = make_application(student["id"], cycle["id"])
        approve_application(application["id"])
        # On-time registration against the cheap course: subsidy floors at the
        # charge (min(3600, 2000) = 2000), so the net is 0, never negative.
        cheap = make_registration(student["id"], course_cheap["id"])
        assert cheap["is_late"] is False
        assert cheap["subsidy_cents"] == 2000
        assert cheap["net_fee_cents"] == 0
        # Late registration against the full-price course.
        set_clock("2026-11-10T00:00:00Z")
        late = make_registration(student["id"], course_full["id"])
        assert late["is_late"] is True
        assert late["late_fee_applied_cents"] == 4000
        assert late["subsidy_cents"] == 3600
        assert late["net_fee_cents"] == 9800 + 4000 - 3600
        assert get_statement(student["id"])["balance_cents"] == 10200
