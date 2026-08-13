"""Programs and enrollments: activation dependencies, pinned subsidy order,
fee gates, capacity, and teach-out (PRD §3.8)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    register_client, create_staff_member, open_case,
    create_verified_screening, drive_case_to_active, drive_case_to_planning,
    create_program, apply_to_program, transition_enrollment,
    create_program_payload, create_program_enrollment_payload,
    staff_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]


class TestCaseActiveDependency:
    def test_apply_rejected_while_case_not_active(self):
        """PRD §3.8: "The case must be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`), the
        program must not be `CLOSED` (else `ERR_PROGRAM_CLOSED`), and no live
        enrollment may already exist for the pair — a duplicate in `APPLIED`,
        `ELIGIBLE`, or `ENROLLED` is rejected with `ERR_DUPLICATE_ENROLLMENT`."

        Design: Difficulty/cross_entity_state_dependency/program_enrollment_requires_case_active
        """
        ctx = drive_case_to_planning()  # PLANNING: verified assessment, no ACTIVE plan
        program = create_program(name="ESOL Eve")
        resp = api_client.create_program_enrollment(
            create_program_enrollment_payload(ctx["case"]["id"], program["id"]),
            staff_headers(ctx["manager"]))
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_ACTIVE)

    def test_apply_succeeds_once_case_active(self):
        """PRD §3.8: "The case must be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`)".
        PRD §3.8: "A new enrollment is `APPLIED` with `fee_status` equal to
        `PENDING` and both subsidy fields null."

        Design: Difficulty/cross_entity_state_dependency/program_enrollment_requires_case_active
        """
        ctx = drive_case_to_active()
        program = create_program(name="ESOL Eve")
        enr = validate_success(api_client.create_program_enrollment(
            create_program_enrollment_payload(ctx["case"]["id"], program["id"]),
            staff_headers(ctx["manager"])), expected_status=201)
        assert enr["status"] == "APPLIED"
        assert enr["fee_status"] == "PENDING"
        assert enr["subsidy_pct"] is None
        assert enr["subsidized_fee_cents"] is None


class TestSubsidyPinnedOrder:
    def _setup_eligible_candidate(self, base_fee_cents, income=600000):
        ctx = drive_case_to_active(client=register_client(household_size=2))
        create_verified_screening(ctx["case"], ctx["manager"], income)
        program = create_program(name="ESOL Fee", base_fee_cents=base_fee_cents)
        enrollment = apply_to_program(ctx["case"], program, ctx["manager"])
        return ctx, program, enrollment

    def test_burden_cap_binds_below_provisional_fee(self):
        """PRD §3.8: "Third, the provisional fee is `base_fee_cents` multiplied by
        one minus that percentage, rounded half-up to whole cents. Fourth, the
        client's monthly income is the screening's
        `documented_annual_income_cents` divided by 12 and floored, and the burden
        cap is that monthly income multiplied by 0.05 and floored. Fifth, the
        final fee is the smaller of the provisional fee and the burden cap, never
        below zero. The recorded `subsidy_pct` is always the tier's base
        percentage — even when the burden cap binds and reduces the fee further —
        and `subsidized_fee_cents` is the final fee."

        Design: Difficulty/combinatorial_formula/subsidy_burden_cap_evaluation_order
        """
        ctx, _program, enrollment = self._setup_eligible_candidate(base_fee_cents=30000)
        eligible = transition_enrollment(enrollment["id"], "ELIGIBLE", ctx["manager"])
        # TIER_A (income 600000 <= 2820720): subsidy 0.90 -> provisional 3000;
        # monthly income floor(600000/12)=50000 -> cap floor(50000*0.05)=2500 binds.
        assert eligible["subsidy_pct"] == pytest.approx(0.90, abs=1e-9)
        assert eligible["subsidized_fee_cents"] == 2500
        assert eligible["fee_status"] == "PENDING", "a positive final fee stays PENDING"

    def test_provisional_fee_below_cap_stands(self):
        """PRD §3.8: "Fifth, the final fee is the smaller of the provisional fee
        and the burden cap, never below zero. The recorded `subsidy_pct` is always
        the tier's base percentage — even when the burden cap binds and reduces
        the fee further — and `subsidized_fee_cents` is the final fee."

        Design: Difficulty/combinatorial_formula/subsidy_burden_cap_evaluation_order
        """
        ctx, _program, enrollment = self._setup_eligible_candidate(base_fee_cents=10000)
        eligible = transition_enrollment(enrollment["id"], "ELIGIBLE", ctx["manager"])
        # provisional 1000 < cap 2500, so the provisional fee stands.
        assert eligible["subsidy_pct"] == pytest.approx(0.90, abs=1e-9)
        assert eligible["subsidized_fee_cents"] == 1000
        assert eligible["fee_status"] == "PENDING"


class TestEnrollmentGates:
    def test_subsidy_requires_verified_screening(self):
        """PRD §3.8: "When the program's `base_fee_cents` is greater than zero,
        the case must hold a benefit screening in `SCREENED` or `EXPLAINED` whose
        `variant_used` is `VERIFIED`; without one the transition fails with
        `ERR_SUBSIDY_UNVERIFIED`."

        Design: Corner/errors/subsidy_requires_verified_screening
        """
        ctx = drive_case_to_active(client=register_client(household_size=2))
        # Screening run but never verified: variant_used stays SELF_REPORTED.
        from test_helpers import create_screening, run_screening
        scr = create_screening(ctx["case"], ctx["manager"], stated_income=900000)
        run_screening(scr, ctx["manager"])
        program = create_program(name="Workforce Fee", kind="WORKFORCE",
                                 base_fee_cents=20000)
        enrollment = apply_to_program(ctx["case"], program, ctx["manager"])

        resp = api_client.transition_program_enrollment(
            enrollment["id"], {"to_status": "ELIGIBLE"}, staff_headers(ctx["manager"]))
        validate_error(resp, ApiErrorId.ERR_SUBSIDY_UNVERIFIED)
        after = validate_success(api_client.get_program_enrollment(
            enrollment["id"], staff_headers(ctx["manager"])))
        assert after["status"] == "APPLIED"

    def test_enroll_blocked_until_fee_arranged(self):
        """PRD §3.8: "Enrollment proper moves `ELIGIBLE` to `ENROLLED` and
        requires three things beyond state: the program is not `CLOSED`
        (`ERR_PROGRAM_CLOSED`), the fee is settled with `fee_status` in `ARRANGED`
        or `WAIVED` (`ERR_FEE_NOT_ARRANGED`), and a seat exists with the program's
        `enrolled_count` below its `capacity` (`ERR_PROGRAM_FULL`)."
        PRD §3.8: "Eligibility sets `fee_status` to `WAIVED` when the final fee is
        zero and leaves it `PENDING` otherwise; a `CaseManager` records a fee
        arrangement to move `PENDING` to `ARRANGED`."

        Design: Corner/errors/enroll_blocked_until_fee_arranged
        """
        ctx = drive_case_to_active(client=register_client(household_size=2))
        create_verified_screening(ctx["case"], ctx["manager"], 600000)
        program = create_program(name="ESOL Fee", base_fee_cents=30000)
        enrollment = apply_to_program(ctx["case"], program, ctx["manager"])
        eligible = transition_enrollment(enrollment["id"], "ELIGIBLE", ctx["manager"])
        assert eligible["fee_status"] == "PENDING"

        resp = api_client.transition_program_enrollment(
            enrollment["id"], {"to_status": "ENROLLED"}, staff_headers(ctx["manager"]))
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_ARRANGED)

        arranged = validate_success(api_client.arrange_fee(
            enrollment["id"], staff_headers(ctx["manager"])))
        assert arranged["fee_status"] == "ARRANGED"
        enrolled = transition_enrollment(enrollment["id"], "ENROLLED", ctx["manager"])
        assert enrolled["status"] == "ENROLLED"

    def test_free_program_fee_waived_and_enrolls(self):
        """PRD §3.8: "When the program is free (`base_fee_cents` of zero), no
        screening is required and `subsidized_fee_cents` is simply 0."
        PRD §3.8: "Eligibility sets `fee_status` to `WAIVED` when the final fee is
        zero and leaves it `PENDING` otherwise".

        Design: Corner/errors/enroll_blocked_until_fee_arranged
        """
        ctx = drive_case_to_active()
        program = create_program(name="Free ESOL", base_fee_cents=0)
        enrollment = apply_to_program(ctx["case"], program, ctx["manager"])
        eligible = transition_enrollment(enrollment["id"], "ELIGIBLE", ctx["manager"])
        assert eligible["subsidized_fee_cents"] == 0
        assert eligible["fee_status"] == "WAIVED"
        enrolled = transition_enrollment(enrollment["id"], "ENROLLED", ctx["manager"])
        assert enrolled["status"] == "ENROLLED"


class TestProgramCapacityAndClosure:
    def test_program_full_and_reopen_auto_transitions(self):
        """PRD §3.8: "A new program is `OPEN` with `enrolled_count` at 0; it
        automatically becomes `FULL` the moment `enrolled_count` reaches
        `capacity`, and automatically reopens (`FULL` → `OPEN`) when a withdrawal
        or completion drops the count back below."

        Design: Corner/state_machines/program_full_and_reopen_auto_transitions
        """
        ctx = drive_case_to_active()
        program = create_program(name="ESOL Mini", capacity=1, base_fee_cents=0)
        enrollment = apply_to_program(ctx["case"], program, ctx["manager"])
        transition_enrollment(enrollment["id"], "ELIGIBLE", ctx["manager"])
        transition_enrollment(enrollment["id"], "ENROLLED", ctx["manager"])

        full = validate_success(api_client.get_program(program["id"], staff_headers(ctx["manager"])))
        assert full["status"] == "FULL"
        assert full["enrolled_count"] == 1

        transition_enrollment(enrollment["id"], "WITHDRAWN", ctx["manager"])
        reopened = validate_success(api_client.get_program(program["id"], staff_headers(ctx["manager"])))
        assert reopened["status"] == "OPEN"
        assert reopened["enrolled_count"] == 0

    def test_program_full_blocks_enroll_at_capacity(self):
        """PRD §3.8: "a seat exists with the program's `enrolled_count` below its
        `capacity` (`ERR_PROGRAM_FULL`)" — from: "Enrollment proper moves
        `ELIGIBLE` to `ENROLLED` and requires three things beyond state: the
        program is not `CLOSED` (`ERR_PROGRAM_CLOSED`), the fee is settled with
        `fee_status` in `ARRANGED` or `WAIVED` (`ERR_FEE_NOT_ARRANGED`), and a
        seat exists with the program's `enrolled_count` below its `capacity`
        (`ERR_PROGRAM_FULL`)."

        Design: Corner/errors/program_full_blocks_enroll_at_capacity
        """
        ctx1 = drive_case_to_active()
        ctx2 = drive_case_to_active()
        mgr = ctx1["manager"]
        program = create_program(name="ESOL Full", capacity=1, base_fee_cents=0)
        e1 = apply_to_program(ctx1["case"], program, mgr)
        transition_enrollment(e1["id"], "ELIGIBLE", mgr)
        transition_enrollment(e1["id"], "ENROLLED", mgr)
        e2 = apply_to_program(ctx2["case"], program, mgr)
        transition_enrollment(e2["id"], "ELIGIBLE", mgr)

        resp = api_client.transition_program_enrollment(
            e2["id"], {"to_status": "ENROLLED"}, staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_FULL)
        after = validate_success(api_client.get_program_enrollment(e2["id"], staff_headers(mgr)))
        assert after["status"] == "ELIGIBLE"
        program_now = validate_success(api_client.get_program(program["id"], staff_headers(mgr)))
        assert program_now["status"] == "FULL"

    def test_enrollment_into_closed_program(self):
        """PRD §3.8: "The case must be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`), the
        program must not be `CLOSED` (else `ERR_PROGRAM_CLOSED`)".
        PRD §3.8: "Closing a program — from either `OPEN` or `FULL` — is a
        `CenterAdmin` action with a teach-out rule: enrollments still in `APPLIED`
        or `ELIGIBLE` are denied with `denial_reason` set to `PROGRAM_CLOSED`,
        while `ENROLLED` participants are unaffected and finish their course."

        Design: Corner/errors/enrollment_into_closed_program
        """
        ctx = drive_case_to_active()
        program = create_program(name="ESOL Closed")
        closed = validate_success(api_client.close_program(program["id"], ADMIN))
        assert closed["status"] == "CLOSED"

        resp = api_client.create_program_enrollment(
            create_program_enrollment_payload(ctx["case"]["id"], program["id"]),
            staff_headers(ctx["manager"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED)

    def test_program_close_denies_pending_enrollments_but_spares_enrolled(self):
        """PRD §3.8: "Closing a program — from either `OPEN` or `FULL` — is a
        `CenterAdmin` action with a teach-out rule: enrollments still in `APPLIED`
        or `ELIGIBLE` are denied with `denial_reason` set to `PROGRAM_CLOSED`,
        while `ENROLLED` participants are unaffected and finish their course."

        Design: Corner/errors/enrollment_into_closed_program
        """
        ctx1 = drive_case_to_active()
        ctx2 = drive_case_to_active()
        mgr = ctx1["manager"]
        program = create_program(name="Teach Out", capacity=5, base_fee_cents=0)
        e1 = apply_to_program(ctx1["case"], program, mgr)
        transition_enrollment(e1["id"], "ELIGIBLE", mgr)
        transition_enrollment(e1["id"], "ENROLLED", mgr)
        e2 = apply_to_program(ctx2["case"], program, mgr)
        transition_enrollment(e2["id"], "ELIGIBLE", mgr)

        validate_success(api_client.close_program(program["id"], ADMIN))
        denied = validate_success(api_client.get_program_enrollment(e2["id"], staff_headers(mgr)))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "PROGRAM_CLOSED"
        spared = validate_success(api_client.get_program_enrollment(e1["id"], staff_headers(mgr)))
        assert spared["status"] == "ENROLLED", "ENROLLED participants teach out unaffected"
