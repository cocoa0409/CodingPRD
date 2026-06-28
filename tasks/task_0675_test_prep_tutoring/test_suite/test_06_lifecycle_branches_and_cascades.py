"""Depth tests for branching state machines, transitive cascades, and conserved invariants.

Covers difficulty rules: non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_student_headers, TEST_USERS,
    setup_concluded_enrollment_with_scores, setup_active_enrollment,
    setup_seat1_with_holder_and_waitlister, file_and_review_claim,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestGuaranteeClaimBranch:
    def test_retake_branch_grants_retake_no_refund(self, api):
        """PRD §3.7: "On a RETAKE resolution, the enrollment's guarantee_status becomes
        RETAKE_GRANTED, the claim's refund_amount_cents stays 0, and the enrollment's
        materials_expire_at is extended by another materials_access_days days".

        Design: Difficulty/non_linear_state_machine/guarantee_claim_branch_refund_vs_retake
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=((550, 800),), student_email="rt@x.com")  # delta 100 < 200 -> ELIGIBLE
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        assert base["enrollment"]["guarantee_status"] == "ELIGIBLE"
        claim = file_and_review_claim(enr_id, stu_id, "RETAKE")
        approved = validate_success(api.approve_guarantee_claim(claim["id"], REGISTRAR))
        assert approved["status"] == "APPROVED"
        assert approved["refund_amount_cents"] == 0
        enr = validate_success(api.get_enrollment(enr_id, REGISTRAR))
        assert enr["guarantee_status"] == "RETAKE_GRANTED"

    def test_approve_marks_claim_approved(self, api):
        """PRD §3.7: "Approval advances UNDER_REVIEW to APPROVED and branches on the
        claim's resolution."

        Design: Difficulty/non_linear_state_machine/guarantee_claim_branch_refund_vs_retake
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=((550, 800),), student_email="rt2@x.com")
        claim = file_and_review_claim(base["enrollment"]["id"], base["student"]["id"], "RETAKE")
        approved = validate_success(api.approve_guarantee_claim(claim["id"], REGISTRAR))
        assert approved["status"] == "APPROVED"


class TestEnrollmentWaitlistBranchAndPromotion:
    def test_waitlisted_promoted_to_pending_on_cancel(self, api):
        """PRD §3.4: "if the cohort is full it lands in WAITLISTED and is assigned a
        waitlist_seq equal to one plus the highest existing waitlist_seq among waitlisted
        peers on the cohort (or 1 when none are waitlisted yet)".
        PRD §3.4: "the waitlisted enrollment with the lowest waitlist_seq is promoted from
        WAITLISTED back to PENDING_PAYMENT: its waitlist_seq is cleared to null and it now
        occupies a held seat awaiting payment."

        Capacity-1: A holds seat (PENDING_PAYMENT), B WAITLISTED; cancelling A promotes B.

        Design: Difficulty/non_linear_state_machine/enrollment_branch_waitlist_then_promote
        """
        s = setup_seat1_with_holder_and_waitlister()
        # B was waitlisted at creation.
        assert s["enr_b"]["status"] == "WAITLISTED"
        assert s["enr_b"]["waitlist_seq"] == 1
        # Cancel A (PENDING_PAYMENT) with the current cohort version.
        validate_success(api.cancel_enrollment(
            s["enr_a"]["id"], s["cohort_version_latest"], make_student_headers(s["student_a"]["id"])))
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "PENDING_PAYMENT"
        assert enr_b["waitlist_seq"] is None
        enr_a = validate_success(api.get_enrollment(s["enr_a"]["id"], REGISTRAR))
        assert enr_a["status"] == "CANCELLED"

    def test_second_enrollment_waitlisted_when_full(self, api):
        """PRD §3.4: "The cohort is considered full when its seats_committed plus the count
        of outstanding non-waitlisted PENDING_PAYMENT holds already reaches or exceeds
        seat_capacity. If a seat is available the new enrollment lands in PENDING_PAYMENT
        holding that seat; if the cohort is full it lands in WAITLISTED".

        Design: Difficulty/non_linear_state_machine/enrollment_branch_waitlist_then_promote
        """
        s = setup_seat1_with_holder_and_waitlister()
        assert s["enr_a"]["status"] == "PENDING_PAYMENT"
        assert s["enr_b"]["status"] == "WAITLISTED"


class TestDefaultDepth3Cascade:
    def test_default_cancels_enrollment_and_promotes_waitlist(self, api):
        """PRD §3.6: "Defaulting cascades: if the parent enrollment is ACTIVE or
        PENDING_PAYMENT, that enrollment is transitioned to CANCELLED, which in turn
        releases its seat and promotes the waitlist exactly as in §3.4."

        Capacity-1: A ACTIVE (financed, partly paid), B WAITLISTED; default A's plan ->
        A CANCELLED -> B promoted to PENDING_PAYMENT.

        Design: Difficulty/transitive_cascade/default_cascades_cancel_then_promote_depth3
        """
        s = setup_seat1_with_holder_and_waitlister(
            activate_holder=True, financed_holder=True, list_price_cents=80000,
            holder_num_installments=2, holder_first_payment=40000)
        # A is ACTIVE (paid 40000 of 80000), B WAITLISTED.
        assert s["enr_a"]["status"] == "ACTIVE"
        assert s["enr_b"]["status"] == "WAITLISTED"
        plan_a_id = s["plan_a"]["id"]
        # Advance clock past a missed due date so DEFAULT is permitted.
        get_success_data(api.set_clock("2026-07-15T00:00:00Z", REGISTRAR))
        plan = validate_success(api.default_installment_plan(plan_a_id, REGISTRAR))
        assert plan["status"] == "DEFAULTED"
        enr_a = validate_success(api.get_enrollment(s["enr_a"]["id"], REGISTRAR))
        assert enr_a["status"] == "CANCELLED"
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "PENDING_PAYMENT"
        assert enr_b["waitlist_seq"] is None

    def test_default_marks_plan_defaulted(self, api):
        """PRD §3.6: "A Registrar may mark an OPEN plan as DEFAULTED when the logical clock
        has passed a missed installment's due date (asserted by the operator) and the plan's
        amount_paid_cents is still less than its total_financed_cents".

        Design: Difficulty/transitive_cascade/default_cascades_cancel_then_promote_depth3
        """
        s = setup_seat1_with_holder_and_waitlister(
            activate_holder=True, financed_holder=True, list_price_cents=80000,
            holder_num_installments=2, holder_first_payment=40000)
        get_success_data(api.set_clock("2026-07-15T00:00:00Z", REGISTRAR))
        plan = validate_success(api.default_installment_plan(s["plan_a"]["id"], REGISTRAR))
        assert plan["status"] == "DEFAULTED"


class TestCancelDepth2Cascade:
    def test_cancel_active_refunds_open_plan(self, api):
        """PRD §3.4: "Cancelling an `ACTIVE` enrollment moves it to `CANCELLED`, recomputes
        the cohort's `seats_committed` downward by one to release the seat, promotes the
        lowest-`waitlist_seq` waitlisted enrollment on the cohort"
        PRD §3.4: "and — if the enrollment has an `OPEN` installment plan — transitions that
        plan from `OPEN` to `REFUNDED`."

        Design: Difficulty/transitive_cascade/cancel_active_cascades_plan_refund_depth2
        """
        base = setup_active_enrollment(
            exam_type="ACT", fmt="LIVE", baseline_scale_max=36, guarantee_min_delta=3,
            required_attendance_pct=0.5, list_price_cents=80000, seat_capacity=5,
            num_installments=2, first_payment_cents=40000, student_email="cd@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        plan_id = base["plan"]["id"]
        cohort = validate_success(api.get_cohort(base["cohort"]["id"], REGISTRAR))
        validate_success(api.cancel_enrollment(
            enr_id, cohort["version"], make_student_headers(stu_id)))
        enr = validate_success(api.get_enrollment(enr_id, REGISTRAR))
        assert enr["status"] == "CANCELLED"
        plan = validate_success(api.get_installment_plan(plan_id, REGISTRAR))
        assert plan["status"] == "REFUNDED"

    def test_cancel_active_releases_seat(self, api):
        """PRD §3.4: "recomputes the cohort's seats_committed downward by one to release
        the seat".

        Design: Difficulty/transitive_cascade/cancel_active_cascades_plan_refund_depth2
        """
        base = setup_active_enrollment(
            exam_type="ACT", fmt="LIVE", baseline_scale_max=36, guarantee_min_delta=3,
            required_attendance_pct=0.5, list_price_cents=80000, seat_capacity=5,
            num_installments=2, first_payment_cents=40000, student_email="cd2@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        cohort = validate_success(api.get_cohort(base["cohort"]["id"], REGISTRAR))
        assert cohort["seats_committed"] == 1
        validate_success(api.cancel_enrollment(
            enr_id, cohort["version"], make_student_headers(stu_id)))
        cohort = validate_success(api.get_cohort(base["cohort"]["id"], REGISTRAR))
        assert cohort["seats_committed"] == 0


class TestRefundConservesMoney:
    def test_refund_returned_equals_collected(self, api):
        """PRD §3.6: "on refund its status becomes REFUNDED and the money returned equals
        the amount_paid_cents already collected, conserving funds so that money returned
        equals money collected for the enrollment."

        Collected 51000 -> refund_amount_cents 51000 exactly (zero drift).

        Design: Difficulty/compensating_invariant/refund_conserves_money_collected_equals_returned
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, list_price_cents=120000, coupon_code="EARLYBIRD",
            num_installments=2, first_payment_cents=51000,
            diagnostic_raw=50, diagnostic_total=80, practice_specs=((550, 800),),
            student_email="cons@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        plan_id = base["plan"]["id"]
        plan_before = validate_success(api.get_installment_plan(plan_id, REGISTRAR))
        assert plan_before["amount_paid_cents"] == 51000
        claim = file_and_review_claim(enr_id, stu_id, "REFUND")
        approved = validate_success(api.approve_guarantee_claim(claim["id"], REGISTRAR))
        assert approved["refund_amount_cents"] == 51000
        assert approved["refund_amount_cents"] == plan_before["amount_paid_cents"]

    def test_refund_plan_becomes_refunded(self, api):
        """PRD §3.6: "A plan reaches REFUNDED only as a cascade — driven either by its parent
        enrollment being cancelled or by an approved refund guarantee claim".

        Design: Difficulty/compensating_invariant/refund_conserves_money_collected_equals_returned
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, list_price_cents=120000, coupon_code="EARLYBIRD",
            num_installments=2, first_payment_cents=51000,
            diagnostic_raw=50, diagnostic_total=80, practice_specs=((550, 800),),
            student_email="cons2@x.com")
        claim = file_and_review_claim(base["enrollment"]["id"], base["student"]["id"], "REFUND")
        validate_success(api.approve_guarantee_claim(claim["id"], REGISTRAR))
        plan = validate_success(api.get_installment_plan(base["plan"]["id"], REGISTRAR))
        assert plan["status"] == "REFUNDED"


class TestCancelConservesSeatCapacity:
    def test_seats_committed_returns_to_zero_and_promotes(self, api):
        """PRD §3.1: "The seats_committed figure is a derived count of the cohort's
        enrollments in ACTIVE or COMPLETED status, and it never exceeds seat_capacity."
        PRD §3.4: "Cancelling an ACTIVE enrollment moves it to CANCELLED, recomputes the
        cohort's seats_committed downward by one to release the seat, promotes the
        lowest-waitlist_seq waitlisted enrollment on the cohort".

        Capacity-1: A ACTIVE (seats_committed 1), B WAITLISTED; cancel A -> seats 0, B promoted.

        Design: Difficulty/compensating_invariant/cancel_conserves_seat_capacity_invariant
        """
        s = setup_seat1_with_holder_and_waitlister(
            activate_holder=True, financed_holder=True, holder_num_installments=1)
        cohort = validate_success(api.get_cohort(s["cohort"]["id"], REGISTRAR))
        assert cohort["seats_committed"] == 1
        validate_success(api.cancel_enrollment(
            s["enr_a"]["id"], cohort["version"], make_student_headers(s["student_a"]["id"])))
        cohort = validate_success(api.get_cohort(s["cohort"]["id"], REGISTRAR))
        assert cohort["seats_committed"] == 0
        assert cohort["seats_committed"] <= cohort["seat_capacity"]
        enr_a = validate_success(api.get_enrollment(s["enr_a"]["id"], REGISTRAR))
        assert enr_a["status"] == "CANCELLED"
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "PENDING_PAYMENT"

    def test_promoted_enrollment_holds_freed_seat(self, api):
        """PRD §3.4: "Promotion is the bridge that lets a released seat immediately become
        reclaimable by the next student in line."

        Design: Difficulty/compensating_invariant/cancel_conserves_seat_capacity_invariant
        """
        s = setup_seat1_with_holder_and_waitlister(
            activate_holder=True, financed_holder=True, holder_num_installments=1)
        cohort = validate_success(api.get_cohort(s["cohort"]["id"], REGISTRAR))
        validate_success(api.cancel_enrollment(
            s["enr_a"]["id"], cohort["version"], make_student_headers(s["student_a"]["id"])))
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "PENDING_PAYMENT"
        assert enr_b["waitlist_seq"] is None
