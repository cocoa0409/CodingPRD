"""Death cascade and other multi-hop side-effect chains.

Covers PRD §3.9 mark-deceased cascade and PRD §2.8 + §2.9 deceased
guard on subsequent operations.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_enrollment,
    advance_clock_to,
    create_beneficiary,
    create_enrollment,
    create_enrollment_period,
    create_part_d_plan,
    create_plan,
    get_iep_period,
    mark_deceased,
    re_get_beneficiary,
    re_get_drug_claim,
    re_get_enrollment,
    re_get_medigap,
    setup_active_part_d_enrollment,
    setup_clock_at,
    setup_deceased_cascade_target,
    submit_drug_claim,
    validate_error,
)


class TestMarkDeceasedCascade:
    """PRD §3.9 death cascade."""

    def test_marks_lifecycle_deceased(self, api, admin_headers):
        """PRD §3.9: "A PlanAdmin marks a beneficiary deceased ... The
        system stamps deceased_at to the current clock, transitions the
        beneficiary to DECEASED from either ENROLLED or IEP_OPEN".

        Claim: mark-deceased sets lifecycle_status=DECEASED.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        mark_deceased(b["id"])
        re_b = re_get_beneficiary(b["id"])
        assert re_b["lifecycle_status"] == "DECEASED"

    def test_active_enrollments_terminated(self, api, admin_headers):
        """PRD §3.9: "transitions every ACTIVE Enrollment for the
        beneficiary to TERMINATED with termination_date set to the
        current clock".

        Claim: ACTIVE enrollments become TERMINATED after the death
        cascade.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        mark_deceased(b["id"])
        terminated = re_get_enrollment(active["id"])
        assert terminated["status"] == "TERMINATED"

    def test_submitted_drug_claims_reversed(self, api,
                                            counselor_headers,
                                            admin_headers):
        """PRD §3.9: "reverses every SUBMITTED DrugClaim to REVERSED".

        Claim: SUBMITTED drug claims belonging to the beneficiary move
        to REVERSED on mark-deceased.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        submitted = submit_drug_claim(
            beneficiary=b, enrollment=active, tier="TIER_3",
            fill_date="2026-05-10", gross_cost_cents=10_000,
        )
        mark_deceased(b["id"])
        reread = re_get_drug_claim(submitted["id"])
        assert reread["status"] == "REVERSED"


class TestPostDeceasedGuard:
    """PRD §2.8: ERR_BENEFICIARY_DECEASED guards subsequent ops."""

    def test_subsequent_create_enrollment_rejected(self, api,
                                                   counselor_headers):
        """PRD §3.9: "After this cascade, any subsequent operation
        targeting the beneficiary is rejected with
        ERR_BENEFICIARY_DECEASED."

        Claim: after mark-deceased, creating a new enrollment for the
        same beneficiary -> ERR_BENEFICIARY_DECEASED.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        plan = create_plan(plan_type="PART_C", plan_year=2026,
                           monthly_premium_cents=12_000)
        mark_deceased(re_b["id"])
        resp = api.create_enrollment(
            {
                "beneficiary_id": re_b["id"],
                "plan_id": plan["id"],
                "enrollment_period_id": iep["id"],
                "effective_date": "2026-04-01",
            },
            counselor_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_BENEFICIARY_DECEASED.value,
        )

    def test_deceased_then_mark_deceased_again_rejected(
        self, api, admin_headers,
    ):
        """PRD §3.9: "the call requires the beneficiary's
        lifecycle_status to be anything other than DECEASED".
        Combined with PRD §2.8: "Beneficiary.lifecycle_status !=
        DECEASED ... ERR_BENEFICIARY_DECEASED".

        Claim: mark-deceased on a DECEASED beneficiary ->
        ERR_BENEFICIARY_DECEASED.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        mark_deceased(b["id"])
        resp = api.mark_beneficiary_deceased(b["id"], {},
                                             admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_BENEFICIARY_DECEASED.value,
        )


class TestDeceasedFromIepOpen:
    """PRD §3.9: 'transitions the beneficiary to DECEASED from either
    ENROLLED or IEP_OPEN'."""

    def test_iep_open_beneficiary_can_be_marked_deceased(
        self, api, admin_headers,
    ):
        """PRD §3.9: "transitions the beneficiary to DECEASED from
        either ENROLLED or IEP_OPEN".

        Claim: an IEP_OPEN beneficiary (no ACTIVE enrollment yet) can
        also be marked deceased.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        assert re_b["lifecycle_status"] == "IEP_OPEN"
        mark_deceased(re_b["id"])
        after = re_get_beneficiary(re_b["id"])
        assert after["lifecycle_status"] == "DECEASED"


class TestDeceasedCascadeMultipleEntities:
    """PRD §3.9 multi-entity cascade."""

    def test_full_cascade_terminates_and_cancels_and_reverses(
        self, api, admin_headers,
    ):
        """PRD §3.9: "The system stamps deceased_at to the current
        clock, transitions the beneficiary to DECEASED from either
        ENROLLED or IEP_OPEN, transitions every ACTIVE Enrollment for
        the beneficiary to TERMINATED with termination_date set to the
        current clock, cancels every MedigapPolicy in APPLIED,
        UNDERWRITING, or ISSUED to CANCELLED, and reverses every
        SUBMITTED DrugClaim to REVERSED."

        Claim: mark-deceased on a beneficiary with one ACTIVE PART_C,
        one ACTIVE PART_D (with adjudicated claim), and one ISSUED
        MedigapPolicy results in: beneficiary=DECEASED, both
        enrollments=TERMINATED, MedigapPolicy=CANCELLED.
        """
        ctx = setup_deceased_cascade_target()
        mark_deceased(ctx["beneficiary"]["id"])
        b_after = re_get_beneficiary(ctx["beneficiary"]["id"])
        assert b_after["lifecycle_status"] == "DECEASED"
        e_c_after = re_get_enrollment(ctx["part_c_enrollment"]["id"])
        e_d_after = re_get_enrollment(ctx["part_d_enrollment"]["id"])
        assert e_c_after["status"] == "TERMINATED"
        assert e_d_after["status"] == "TERMINATED"
        m_after = re_get_medigap(ctx["medigap_policy"]["id"])
        assert m_after["status"] == "CANCELLED"
