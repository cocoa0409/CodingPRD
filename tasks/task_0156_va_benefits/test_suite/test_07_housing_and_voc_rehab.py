"""Housing payment posting, Voc Rehab approval / suspension / termination,
and the depth-3 reopen cascade — PRD §3.10, §3.11."""
from __future__ import annotations

import pytest

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    NATIONAL_AVG_BAH,
    TEST_USERS,
    add_active_dependent,
    advance_clock_to,
    approve_voc_rehab_plan,
    certify_enrollment,
    create_enrollment,
    create_school,
    create_veteran,
    create_voc_rehab_plan,
    current_clock,
    delete_dependent,
    get_enrollment,
    get_veteran,
    get_voc_rehab_plan,
    grant_claim_for_veteran,
    iso_utc,
    make_counselor_headers,
    make_veteran_headers,
    post_housing_payment,
    reopen_claim,
    run_sweep,
    setup_active_enrollment,
    setup_active_voc_rehab_plan,
    setup_certified_enrollment,
    setup_veteran_with_granted_claim,
    start_voc_rehab_plan,
    suspend_voc_rehab_plan,
    resume_voc_rehab_plan,
    utc_midnight,
    validate_error,
    validate_success,
)


# ===========================================================================
# Housing payment posting — PRD §3.10
# ===========================================================================
class TestHousingPaymentPosting:

    def test_post_housing_payment_basic(self, api):
        """PRD §3.10: "Each month a VAClerk posts a housing payment for
        an active enrollment by calling the housing-payment endpoint
        and supplying a month_year (a "YYYY-MM" string matching the
        regex of a four-digit year followed by a two-digit month in
        01–12)."
        """
        bundle = setup_active_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            delivery_mode="ONLINE_ONLY",
            training_time="FULL_TIME",
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        # Post payment for the month containing term_start.
        ts = bundle["term_start_date"]
        month_year = f"{ts.year:04d}-{ts.month:02d}"
        resp = api.create_housing_payment(
            bundle["enrollment"]["id"],
            {"month_year": month_year},
            TEST_USERS["va_clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["month_year"] == month_year

    def test_duplicate_housing_payment_rejected(self, api):
        """PRD §3.10: "The pair (enrollment_id, month_year) is unique —
        a duplicate posting is rejected with
        ERR_PAYMENT_ALREADY_POSTED."
        """
        bundle = setup_active_enrollment(
            delivery_mode="ONLINE_ONLY",
            training_time="FULL_TIME",
        )
        ts = bundle["term_start_date"]
        month_year = f"{ts.year:04d}-{ts.month:02d}"
        post_housing_payment(bundle["enrollment"]["id"], month_year)
        resp = api.create_housing_payment(
            bundle["enrollment"]["id"],
            {"month_year": month_year},
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_POSTED.value)

    def test_housing_payment_outside_term_rejected(self, api):
        """PRD §3.10: "The supplied month_year MUST share at least one
        UTC day with the enrollment's half-open term interval; a month
        wholly outside the term (no overlapping day at all) is rejected
        with ERR_PAYMENT_OUTSIDE_TERM."

        # difficulty: resource_temporal_overlap/housing_payment_month_intersects_term
        """
        bundle = setup_active_enrollment(
            delivery_mode="ONLINE_ONLY",
            training_time="FULL_TIME",
            term_months=1,  # ~30-day term
        )
        # Compute a month strictly after term_end.
        te = bundle["term_end_date"]
        far_future = te + timedelta(days=120)
        month_year = f"{far_future.year:04d}-{far_future.month:02d}"
        resp = api.create_housing_payment(
            bundle["enrollment"]["id"],
            {"month_year": month_year},
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_OUTSIDE_TERM.value)


# ===========================================================================
# Online half national — PRD §3.10 (the one BAH branch with a fixed
# numeric we can pin verbatim from PRD)
# ===========================================================================
class TestOnlineHalfNationalBAH:

    def test_online_only_full_time_tier_100_no_deps(self, api):
        """PRD §3.10: "For an online-only enrollment, the base is half
        of a fixed national-average BAH constant of 1789.00 dollars; the
        ZIP is not consulted. To that base the system adds a dependent
        uplift: count the veteran's dependents in ACTIVE status at the
        start of the month; for each dependent beyond the second, add
        50.00 dollars to the monthly rate, capped at a total uplift of
        200.00 dollars. So 0, 1, or 2 active dependents contribute 0.00
        in uplift".

        Online + FULL_TIME + tier 100 + 0 deps + full-month coverage:
            (1789.00 * 0.5 + 0) * 1.00 * 1.00 * 1.00 = 894.50
        """
        # We need the housing-payment month_year to be fully inside the
        # term [term_start, term_end). Build a term that spans an entire
        # calendar month.
        # Choose term_start = next month's day 1, term_end = the
        # following month's day 1 — full calendar month coverage.
        today = current_clock().date()
        # Roll to first day of the month after next, for safety.
        year, month = today.year, today.month
        # Compute first of month after next.
        start_month = month + 2
        start_year = year
        if start_month > 12:
            start_month -= 12
            start_year += 1
        from datetime import date as _date
        term_start_date = _date(start_year, start_month, 1)
        next_month = start_month + 1
        next_year = start_year
        if next_month > 12:
            next_month -= 12
            next_year += 1
        term_end_date = _date(next_year, next_month, 1)

        vet = setup_veteran_with_granted_claim(
            granted_rating=10, aggregate_active_duty_days=1100,
        )
        school = create_school(
            program_type="PUBLIC_IN_STATE",
            zip_bah_code="10001",
        )
        enr = create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=iso_utc(utc_midnight(term_start_date)),
            term_end=iso_utc(utc_midnight(term_end_date)),
            tuition_charged=5000.00,
            training_time="FULL_TIME",
            delivery_mode="ONLINE_ONLY",
        )
        certify_enrollment(enr["id"])
        advance_clock_to(utc_midnight(term_start_date))
        run_sweep()
        month_year = (f"{term_start_date.year:04d}-"
                      f"{term_start_date.month:02d}")
        resp = api.create_housing_payment(
            enr["id"], {"month_year": month_year},
            TEST_USERS["va_clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        # (1789.00 * 0.5) * 1.0 * 1.0 = 894.50.
        assert data["amount"] == pytest.approx(894.50, abs=0.01)
        assert data["computation_basis"] == "ONLINE_HALF_NATIONAL"

    def test_online_only_less_than_half_yields_zero(self, api):
        """PRD §3.10: "LESS_THAN_HALF by 0.00 (so a veteran enrolled
        less than half-time draws no housing allowance regardless of
        tier or dependents)."
        """
        today = current_clock().date()
        from datetime import date as _date
        start_month = today.month + 2
        start_year = today.year
        if start_month > 12:
            start_month -= 12
            start_year += 1
        term_start_date = _date(start_year, start_month, 1)
        next_month = start_month + 1
        next_year = start_year
        if next_month > 12:
            next_month -= 12
            next_year += 1
        term_end_date = _date(next_year, next_month, 1)

        vet = setup_veteran_with_granted_claim(
            granted_rating=10, aggregate_active_duty_days=1100,
        )
        school = create_school(
            program_type="PUBLIC_IN_STATE",
            zip_bah_code="10001",
        )
        enr = create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=iso_utc(utc_midnight(term_start_date)),
            term_end=iso_utc(utc_midnight(term_end_date)),
            tuition_charged=5000.00,
            training_time="LESS_THAN_HALF",
            delivery_mode="ONLINE_ONLY",
        )
        certify_enrollment(enr["id"])
        advance_clock_to(utc_midnight(term_start_date))
        run_sweep()
        month_year = (f"{term_start_date.year:04d}-"
                      f"{term_start_date.month:02d}")
        resp = api.create_housing_payment(
            enr["id"], {"month_year": month_year},
            TEST_USERS["va_clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Voc Rehab approval gate — PRD §3.11
# ===========================================================================
class TestVocRehabApproval:

    def test_approve_with_combined_rating_below_20_rejected(self, api):
        """PRD §3.11: "the counselor moves the plan from DRAFT to
        APPROVED, which requires that the veteran's combined_rating be
        at least 20 (a granted claim of at least 20 percent combined
        disability) — a draft plan whose veteran has a combined rating
        below 20 cannot be approved and the approval is rejected with
        ERR_CROSS_ENTITY_PRECONDITION."

        # difficulty: cross_entity_state_dependency/voc_rehab_approve_requires_claim_combined_rating_20
        """
        vet = setup_veteran_with_granted_claim(granted_rating=10)
        plan = create_voc_rehab_plan(
            veteran_id=vet["id"], training_mode="FULL_TIME_INSTITUTIONAL",
        )
        resp = api.approve_voc_rehab_plan(
            plan["id"], make_counselor_headers("counselor-A"),
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_PRECONDITION.value)

    def test_approve_with_combined_rating_at_least_20_succeeds(self, api):
        """PRD §3.11: "requires that the veteran's combined_rating be at
        least 20 (a granted claim of at least 20 percent combined
        disability)".

        # difficulty: cross_entity_state_dependency/voc_rehab_approve_requires_claim_combined_rating_20
        """
        vet = setup_veteran_with_granted_claim(granted_rating=20)
        plan = create_voc_rehab_plan(
            veteran_id=vet["id"], training_mode="FULL_TIME_INSTITUTIONAL",
        )
        resp = api.approve_voc_rehab_plan(
            plan["id"], make_counselor_headers("counselor-A"),
        )
        data = validate_success(resp)
        assert data["status"] == "APPROVED"
        assert data.get("counselor_id") == "counselor-A"
        # PRD §3.11: "runs the subsistence computation to set
        # monthly_subsistence". FULL_TIME_INSTITUTIONAL base = 883.00,
        # 0 dependents -> uplift 0 -> 883.00.
        assert data["monthly_subsistence"] == pytest.approx(883.00, abs=0.01)

    def test_approve_with_non_honorable_discharge_rejected(self, api):
        """PRD §3.11: "approval is a benefit-producing operation and
        additionally requires the veteran's discharge_status to be
        HONORABLE; any other discharge status is rejected with
        ERR_INELIGIBLE_DISCHARGE."
        """
        # Build veteran with GENERAL discharge AND combined_rating >= 20.
        vet = create_veteran(
            aggregate_active_duty_days=1100,
            discharge_status="GENERAL",
        )
        grant_claim_for_veteran(vet["id"], granted_rating=20)
        plan = create_voc_rehab_plan(
            veteran_id=vet["id"], training_mode="FULL_TIME_INSTITUTIONAL",
        )
        resp = api.approve_voc_rehab_plan(
            plan["id"], make_counselor_headers("counselor-A"),
        )
        # PRD §2.8 priority: cross-entity precondition (priority 6) fires
        # before discharge (priority 8). Both fail here (combined >= 20
        # AND HONORABLE both fail? No — combined IS >= 20 here, so only
        # the discharge check fires). Safer: enforce HONORABLE via
        # combined_rating high enough so we only test discharge.
        validate_error(resp, ApiErrorId.ERR_INELIGIBLE_DISCHARGE.value)


# ===========================================================================
# Voc Rehab subsistence with dependents — PRD §3.11
# ===========================================================================
class TestVocRehabSubsistenceUplift:

    def test_three_dependents_at_approval_adds_65(self, api):
        """PRD §3.11: "if the count exceeds 2, the uplift is 65.00
        dollars per dependent beyond the second (so 3 dependents add
        65.00, 4 add 130.00, 5 add 195.00, with no cap). The base plus
        the uplift is rounded half-up to two decimal places and written
        to monthly_subsistence."

        FULL_TIME_INSTITUTIONAL (883.00) + 3 deps -> 883 + 65 = 948.00.
        """
        vet = setup_veteran_with_granted_claim(granted_rating=20)
        # Add 3 ACTIVE dependents.
        add_active_dependent(vet["id"], relationship="SPOUSE",
                             age_days=365 * 30)
        add_active_dependent(vet["id"], relationship="CHILD",
                             age_days=365 * 10)
        add_active_dependent(vet["id"], relationship="CHILD",
                             age_days=365 * 8)
        plan = create_voc_rehab_plan(
            veteran_id=vet["id"], training_mode="FULL_TIME_INSTITUTIONAL",
        )
        approved = approve_voc_rehab_plan(
            plan["id"], counselor_operator_id="counselor-A",
        )
        assert approved["monthly_subsistence"] == pytest.approx(
            948.00, abs=0.01,
        )

    def test_dependent_removal_recomputes_subsistence(self, api):
        """PRD §3.11: "the dependent count that subsistence sees is the
        count of ACTIVE dependents after the triggering removal has
        been applied — so a removal that takes the count from 3 down
        to 2 must, at the moment subsistence is recomputed, see 2
        dependents, not 3."

        PRD §3.2: "if the veteran has a VocRehabPlan in ACTIVE status,
        monthly subsistence is recomputed against the new active-
        dependent count and monthly_subsistence is rewritten in place."

        # difficulty: transitive_cascade/dependent_removal_depth_two_chain
        """
        vet = setup_veteran_with_granted_claim(granted_rating=20)
        spouse = add_active_dependent(
            vet["id"], relationship="SPOUSE", age_days=365 * 30,
        )
        add_active_dependent(vet["id"], relationship="CHILD",
                             age_days=365 * 10)
        add_active_dependent(vet["id"], relationship="CHILD",
                             age_days=365 * 8)
        plan = create_voc_rehab_plan(
            veteran_id=vet["id"], training_mode="FULL_TIME_INSTITUTIONAL",
        )
        approved = approve_voc_rehab_plan(
            plan["id"], counselor_operator_id="counselor-A",
        )
        # Start so plan is ACTIVE.
        active = start_voc_rehab_plan(
            plan["id"], counselor_operator_id="counselor-A",
        )
        assert active["status"] == "ACTIVE"
        assert active["monthly_subsistence"] == pytest.approx(
            948.00, abs=0.01,
        )
        # Remove the spouse -> 2 ACTIVE deps remain -> uplift 0.
        delete_dependent(spouse["id"])
        refreshed = get_voc_rehab_plan(plan["id"])
        assert refreshed["monthly_subsistence"] == pytest.approx(
            883.00, abs=0.01,
        )


# ===========================================================================
# Voc Rehab cycle: ACTIVE <-> SUSPENDED with terminal at 3rd suspension —
# PRD §3.11
# ===========================================================================
class TestVocRehabSuspendCycle:

    def test_third_suspension_auto_terminates(self, api):
        """PRD §3.11: "The third suspension is auto-terminal: when a
        suspend call raises suspension_count to 3 (i.e., the plan is
        currently ACTIVE with suspension_count already 2, and a third
        suspension fires), the plan transitions in the same request
        from ACTIVE to SUSPENDED and then immediately to TERMINATED."

        # difficulty: non_linear_state_machine/voc_rehab_active_suspended_cycle
        """
        bundle = setup_active_voc_rehab_plan(
            granted_rating=20,
            training_mode="FULL_TIME_INSTITUTIONAL",
            approver_counselor_id="counselor-A",
        )
        plan_id = bundle["plan"]["id"]
        # 1st suspend by C-A
        suspend_voc_rehab_plan(plan_id, counselor_operator_id="counselor-A")
        # Resume by C-B (different counselor) — PRD §3.11 SoD.
        resume_voc_rehab_plan(plan_id, counselor_operator_id="counselor-B")
        # 2nd suspend
        suspend_voc_rehab_plan(plan_id, counselor_operator_id="counselor-A")
        resume_voc_rehab_plan(plan_id, counselor_operator_id="counselor-B")
        # 3rd suspend
        resp = api.suspend_voc_rehab_plan(
            plan_id, make_counselor_headers("counselor-A"),
        )
        data = validate_success(resp)
        assert data["suspension_count"] == 3
        assert data["status"] == "TERMINATED"

    def test_resume_after_terminated_returns_invalid_state(self, api):
        """PRD §3.11: "Once terminated, the plan blocks all further
        VOC_REHAB_SUBSISTENCE ledger entries against it from the
        moment of termination onwards."

        Implication: any state-changing endpoint on a TERMINATED plan
        rejects with ERR_INVALID_STATE (TERMINATED is not a FROM state
        for /resume per PRD §3.11 state machine: resume goes SUSPENDED
        -> ACTIVE, not TERMINATED -> ACTIVE).

        # difficulty: non_linear_state_machine/voc_rehab_active_suspended_cycle
        """
        bundle = setup_active_voc_rehab_plan(
            granted_rating=20,
            training_mode="FULL_TIME_INSTITUTIONAL",
            approver_counselor_id="counselor-A",
        )
        plan_id = bundle["plan"]["id"]
        suspend_voc_rehab_plan(plan_id, counselor_operator_id="counselor-A")
        resume_voc_rehab_plan(plan_id, counselor_operator_id="counselor-B")
        suspend_voc_rehab_plan(plan_id, counselor_operator_id="counselor-A")
        resume_voc_rehab_plan(plan_id, counselor_operator_id="counselor-B")
        suspend_voc_rehab_plan(plan_id, counselor_operator_id="counselor-A")
        # Now TERMINATED. Resume must fail.
        resp = api.resume_voc_rehab_plan(
            plan_id, make_counselor_headers("counselor-B"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_resume_by_same_counselor_as_approver_rejected(self, api):
        """PRD §3.11: "A suspended plan can be resumed (SUSPENDED to
        ACTIVE) by a counselor whose X-User-ID differs from the original
        counselor_id who approved the plan — a same-counselor resume
        is rejected with ERR_SEGREGATION_VIOLATION."
        """
        bundle = setup_active_voc_rehab_plan(
            granted_rating=20,
            training_mode="FULL_TIME_INSTITUTIONAL",
            approver_counselor_id="counselor-A",
        )
        plan_id = bundle["plan"]["id"]
        suspend_voc_rehab_plan(plan_id, counselor_operator_id="counselor-A")
        # Resume attempted by counselor-A (the approver).
        resp = api.resume_voc_rehab_plan(
            plan_id, make_counselor_headers("counselor-A"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


# ===========================================================================
# Depth-3 reopen cascade — PRD §3.3 + §3.11
# ===========================================================================
class TestReopenDepthThreeCascade:

    def test_reopen_invalidates_tuition_payable_and_suspends_voc_rehab(
        self, api,
    ):
        """PRD §3.3: "A reopen re-runs the combined-rating computation
        for the veteran ... invalidates certified_tuition_payable (sets
        it back to null) on every Enrollment of this veteran in
        CERTIFIED or ACTIVE, and auto-suspends any VocRehabPlan of
        this veteran in ACTIVE (advancing it to SUSPENDED exactly as if
        a counselor had explicitly suspended it). All three cascades
        execute in the same atomic request".

        # difficulty: transitive_cascade/claim_reopen_depth_three_chain
        """
        # Build: HONORABLE veteran, GRANTED 30% claim -> combined_rating
        # 30, certified enrollment, ACTIVE voc rehab plan.
        bundle = setup_certified_enrollment(
            granted_rating=30,
            aggregate_active_duty_days=1100,
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        veteran_id = bundle["veteran"]["id"]
        enrollment_id = bundle["enrollment"]["id"]
        assert bundle["enrollment"]["certified_tuition_payable"] is not None
        # Create + approve + start a voc rehab plan.
        plan = create_voc_rehab_plan(
            veteran_id=veteran_id,
            training_mode="FULL_TIME_INSTITUTIONAL",
        )
        approve_voc_rehab_plan(plan["id"],
                               counselor_operator_id="counselor-A")
        plan_active = start_voc_rehab_plan(
            plan["id"], counselor_operator_id="counselor-A",
        )
        assert plan_active["status"] == "ACTIVE"
        # Fetch the original granted claim.
        from test_helpers import (
            api_client as _ac,
            validate_paginated as _vp,
        )
        list_resp = _ac.list_claims(
            veteran_id, TEST_USERS["platform_admin_headers"],
            params={"status": "GRANTED"},
        )
        claims, _ = _vp(list_resp)
        assert len(claims) >= 1
        granted_claim_id = claims[0]["id"]
        # Reopen by a different rater than the recorded rater_id.
        reopen_claim(granted_claim_id, rater_operator_id="rater-Z")
        # Verify cascades.
        enr_after = get_enrollment(enrollment_id)
        assert enr_after.get("certified_tuition_payable") is None, (
            "PRD §3.3: 'invalidates certified_tuition_payable (sets it "
            "back to null) on every Enrollment of this veteran in "
            "CERTIFIED or ACTIVE'"
        )
        plan_after = get_voc_rehab_plan(plan["id"])
        assert plan_after["status"] == "SUSPENDED", (
            "PRD §3.3: 'auto-suspends any VocRehabPlan of this veteran "
            "in ACTIVE (advancing it to SUSPENDED exactly as if a "
            "counselor had explicitly suspended it)'"
        )
        assert plan_after["suspension_count"] == 1, (
            "PRD §3.11: 'Suspension increments suspension_count by "
            "exactly 1'"
        )
        # And the combined rating drops to 0 (only one claim, now
        # UNDER_REVIEW, excluded from input set).
        v_after = get_veteran(veteran_id)
        assert v_after["combined_rating"] == 0
