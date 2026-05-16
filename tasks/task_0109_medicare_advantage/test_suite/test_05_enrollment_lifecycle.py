"""Enrollment lifecycle: create, activate, reject, terminate.

Covers PRD §3.4 / §3.9 — state transitions, activation guards, IEP /
non-IEP period consumption, lifecycle bubbling, DrugPhaseLedger
creation on PART_D activation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_enrollment,
    advance_clock_to,
    assert_drug_phase_ledger,
    assert_enrollment,
    create_beneficiary,
    create_enrollment,
    create_enrollment_period,
    create_part_d_plan,
    create_plan,
    get_drug_phase_ledger,
    get_iep_period,
    re_get_beneficiary,
    re_get_enrollment,
    reject_enrollment,
    setup_active_part_d_enrollment,
    setup_clock_at,
    submit_drug_claim,
    terminate_enrollment,
    validate_error,
    validate_success,
)


class TestEnrollmentCreate:
    """PRD §3.4 enrollment creation."""

    def test_enrollment_starts_pending(self, api, counselor_headers):
        """PRD §3.4: "A BenefitsCounselor creates an enrollment in
        PENDING status by submitting beneficiary_id, plan_id,
        enrollment_period_id, and the proposed effective_date."

        Claim: a fresh enrollment has status=PENDING.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=18_000)
        pending = create_enrollment(
            beneficiary=re_b, plan=plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        assert pending["status"] == "PENDING"
        assert pending["part_covered"] == "PART_B"

    def test_part_covered_mirrors_plan_type(self, api, counselor_headers):
        """PRD §3.4: "The system fixes part_covered by mirroring the
        plan's plan_type at this moment of creation (so a Part C plan
        yields a Part C enrollment, etc.;"

        Claim: enrollment.part_covered equals plan.plan_type.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_part_d_plan(plan_year=2026)
        pending = create_enrollment(
            beneficiary=re_b, plan=plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        assert pending["part_covered"] == "PART_D"

    def test_fk_plan_id_must_exist(self, api, counselor_headers):
        """PRD §2.8: "body foreign-key existence on the create
        endpoints for enrollments, drug claims, and Medigap policies
        (ERR_FK_NOT_FOUND)".

        Claim: POST /enrollments with non-existent plan_id ->
        ERR_FK_NOT_FOUND (404).
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        resp = api.create_enrollment(
            {
                "beneficiary_id": re_b["id"],
                "plan_id": "00000000-0000-0000-0000-000000000000",
                "enrollment_period_id": iep["id"],
                "effective_date": "2026-04-01",
            },
            counselor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


class TestEnrollmentActivateGuards:
    """PRD §3.4 activation guard stack."""

    def test_activate_period_not_open_rejected(self, api,
                                               counselor_headers):
        """PRD §3.4: "The referenced EnrollmentPeriod must be in OPEN
        status — a period that is SCHEDULED, CLOSED, or already
        CONSUMED produces ERR_PERIOD_NOT_OPEN."

        Claim: activating against a CLOSED period -> ERR_PERIOD_NOT_OPEN.
        """
        setup_clock_at(2025, 9, 1)
        b = create_beneficiary(date_of_birth="1956-06-15")
        # Open AEP period in the past so it can be advanced past.
        aep = create_enrollment_period(
            beneficiary=b, period_type="AEP",
            window_start="2025-10-15T00:00:00.000Z",
            window_end="2025-12-07T23:59:59.000Z",
        )
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=18_000)
        pending = create_enrollment(
            beneficiary=b, plan=plan, enrollment_period=aep,
            effective_date="2026-01-01",
        )
        # Push clock past window_end so the period becomes CLOSED.
        advance_clock_to("2025-12-08T00:00:00.000Z")
        resp = api.activate_enrollment(pending["id"], {},
                                       counselor_headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    def test_activate_plan_inactive_rejected(self, api,
                                             counselor_headers):
        """PRD §3.4: "The plan must be active (Plan.is_active true) or
        the request is rejected with ERR_PLAN_INACTIVE."

        Claim: activating an enrollment whose plan has is_active=false
        -> ERR_PLAN_INACTIVE.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=18_000,
                           is_active=False)
        pending = create_enrollment(
            beneficiary=re_b, plan=plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        resp = api.activate_enrollment(pending["id"], {},
                                       counselor_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_INACTIVE.value)

    def test_activate_effective_date_outside_period(self, api,
                                                    counselor_headers):
        """PRD §3.4: "The effective_date must fall on or after
        window_start and on or before window_end; an out-of-window
        effective date is rejected with ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD."

        Claim: effective_date past window_end -> ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD.
        """
        setup_clock_at(2025, 10, 20)
        b = create_beneficiary(date_of_birth="1956-06-15")
        aep = create_enrollment_period(
            beneficiary=b, period_type="AEP",
            window_start="2025-10-15T00:00:00.000Z",
            window_end="2025-12-07T23:59:59.000Z",
        )
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=18_000)
        # effective_date outside [2025-10-15, 2025-12-07].
        pending = create_enrollment(
            beneficiary=b, plan=plan, enrollment_period=aep,
            effective_date="2026-02-15",
        )
        resp = api.activate_enrollment(pending["id"], {},
                                       counselor_headers)
        validate_error(
            resp,
            ApiErrorId.ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD.value,
        )

    def test_activate_zero_premium_non_partA_rejected(self, api,
                                                     counselor_headers):
        """PRD §3.4: "for any non-Part-A enrollment, the plan's
        monthly_premium_cents must be strictly greater than zero, or
        the request fails with ERR_INVALID_PREMIUM."

        Claim: Part B plan with monthly_premium_cents=0 -> ERR_INVALID_PREMIUM.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=0)
        pending = create_enrollment(
            beneficiary=re_b, plan=plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        resp = api.activate_enrollment(pending["id"], {},
                                       counselor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PREMIUM.value)


class TestActivationSideEffects:
    """PRD §3.4 activation side effects."""

    def test_iep_period_consumed_on_activation(self, api,
                                               counselor_headers):
        """PRD §3.4: "If the referenced period is of period_type IEP or
        MEDIGAP_GI, its status flips to CONSUMED and its
        consumed_by_enrollment_id is set to this enrollment's id".

        Claim: after activation citing an IEP period, the period's
        status is CONSUMED and consumed_by_enrollment_id == enrollment.id.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=18_000)
        pending = create_enrollment(
            beneficiary=re_b, plan=plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        active = activate_enrollment(pending["id"])
        assert active["status"] == "ACTIVE"
        # IEP period should now be CONSUMED.
        refreshed_iep = get_iep_period(re_b["id"])
        assert refreshed_iep["status"] == "CONSUMED"
        assert refreshed_iep["consumed_by_enrollment_id"] == active["id"]

    def test_part_d_activation_creates_drug_phase_ledger(self, api,
                                                        counselor_headers):
        """PRD §3.4: "And if part_covered is PART_D, a fresh
        DrugPhaseLedger row is created with current_phase DEDUCTIBLE,
        all four counters at zero, and last_adjudicated_claim_id null."

        Claim: PART_D activation creates a DrugPhaseLedger with the
        documented initial state.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        ledger = get_drug_phase_ledger(b["id"], plan_year=2026)
        assert_drug_phase_ledger(ledger)
        assert ledger["current_phase"] == "DEDUCTIBLE"
        assert ledger["deductible_paid_cents"] == 0
        assert ledger["total_drug_spend_cents"] == 0
        assert ledger["troop_cents"] == 0
        assert ledger.get("last_adjudicated_claim_id") is None

    def test_activation_bubbles_lifecycle_to_enrolled(self, api,
                                                     counselor_headers):
        """PRD §3.4: "The Beneficiary.lifecycle_status bubbles to
        ENROLLED (from any of IEP_OPEN, IEP_CLOSED, or COVERAGE_GAP)."

        Claim: after first activation, beneficiary moves IEP_OPEN ->
        ENROLLED.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        re_b = re_get_beneficiary(b["id"])
        assert re_b["lifecycle_status"] == "ENROLLED"


class TestRejectEnrollment:
    """PRD §3.4 reject path."""

    def test_reject_moves_to_rejected_period_stays_open(
        self, api, counselor_headers,
    ):
        """PRD §3.4: "A PlanAdmin can short-circuit a pending
        enrollment with the rejection capability, which moves the
        enrollment from PENDING to the terminal REJECTED state;
        rejection leaves the referenced period in its original status
        (no CONSUMED transition)."

        Claim: reject takes enrollment to REJECTED and leaves the IEP
        period status OPEN (not CONSUMED).
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_plan(plan_type="PART_B", plan_year=2026,
                           monthly_premium_cents=18_000)
        pending = create_enrollment(
            beneficiary=re_b, plan=plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        rejected = reject_enrollment(pending["id"])
        assert rejected["status"] == "REJECTED"
        refreshed_iep = get_iep_period(re_b["id"])
        assert refreshed_iep["status"] == "OPEN", (
            f"reject must NOT consume the period; expected OPEN, got "
            f"{refreshed_iep['status']}"
        )


class TestTerminateEnrollment:
    """PRD §3.9 terminate path."""

    def test_terminate_moves_active_to_terminated(self, api,
                                                  counselor_headers):
        """PRD §3.9: "Termination moves the enrollment ACTIVE ->
        TERMINATED".

        Claim: termination flips status to TERMINATED and stamps
        termination_date.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        terminated = terminate_enrollment(
            active["id"], termination_date="2026-08-15",
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_date"].startswith("2026-08-15")

    def test_terminate_opens_sep_loss_of_coverage_period(
        self, api, counselor_headers,
    ):
        """PRD §3.9: "Termination moves the enrollment ACTIVE ->
        TERMINATED, opens a fresh SEP_LOSS_OF_COVERAGE EnrollmentPeriod
        for the beneficiary whose window_start is the current clock day
        and whose window_end is the current clock day plus sixty-three
        days".

        Claim: a SEP_LOSS_OF_COVERAGE period is created after
        termination.
        """
        from test_helpers import list_enrollment_periods
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        terminate_enrollment(active["id"], termination_date="2026-08-15")
        periods = list_enrollment_periods(b["id"])
        sep_rows = [p for p in periods
                    if p["period_type"] == "SEP_LOSS_OF_COVERAGE"]
        assert len(sep_rows) >= 1, (
            "expected at least one SEP_LOSS_OF_COVERAGE period after "
            "termination"
        )
