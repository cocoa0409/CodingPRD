"""Enrollment activation (sweep), ledger emission, completion and
entitlement counter — PRD §3.8, §3.9."""
from __future__ import annotations

import pytest

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    ENTITLEMENT_CAP,
    TEST_USERS,
    advance_clock_to,
    certify_enrollment,
    create_enrollment,
    create_school,
    create_veteran,
    current_clock,
    get_enrollment,
    get_veteran,
    grant_claim_for_veteran,
    iso_utc,
    make_veteran_headers,
    post_housing_payment,
    run_sweep,
    setup_active_enrollment,
    setup_certified_enrollment,
    setup_completed_enrollment_with_months,
    setup_veteran_with_granted_claim,
    utc_midnight,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)


# ===========================================================================
# CERTIFIED -> ACTIVE — PRD §3.8
# ===========================================================================
class TestActivationGate:

    def test_certified_without_combined_rating_not_promoted(self, api):
        """PRD §3.8: "The combined-rating gate is the system's
        enforcement of service connection — a veteran with no granted
        disability claim cannot draw GI Bill benefits".

        # difficulty: cross_entity_state_dependency/enrollment_activate_requires_claim_granted
        """
        # Build a Veteran (HONORABLE, tier 100) WITHOUT any granted claim.
        vet = create_veteran(
            aggregate_active_duty_days=1100,
            discharge_status="HONORABLE",
        )
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        enrollment = create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=iso_utc(utc_midnight(base)),
            term_end=iso_utc(utc_midnight(base + timedelta(days=120))),
            tuition_charged=5000.00,
        )
        certify_enrollment(enrollment["id"])
        # Advance to term_start and sweep.
        advance_clock_to(utc_midnight(base))
        run_sweep()
        # Enrollment should remain CERTIFIED because combined_rating == 0.
        e_now = get_enrollment(enrollment["id"])
        assert e_now["status"] == "CERTIFIED", (
            f"expected CERTIFIED (combined_rating=0 blocks activation), "
            f"got {e_now['status']}"
        )

    def test_certified_with_granted_claim_activates_on_sweep(self, api):
        """PRD §3.8: "The sweep is the mechanism: it scans every
        CERTIFIED enrollment and promotes those whose term_start is at
        or before the current server clock AND whose owning veteran's
        combined_rating is strictly greater than 0."

        # difficulty: cross_entity_state_dependency/enrollment_activate_requires_claim_granted
        """
        bundle = setup_active_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        assert bundle["enrollment"]["status"] == "ACTIVE"


# ===========================================================================
# Ledger emission on activation — PRD §3.8 + §2.10
# ===========================================================================
class TestActivationLedger:

    def test_activation_emits_tuition_payment_ledger_entry(self, api):
        """PRD §3.8: "On activation two ledger entries are journaled: a
        TUITION_PAYMENT entry with positive amount_dollars equal to
        certified_tuition_payable and source_id equal to the
        enrollment's id".
        """
        bundle = setup_active_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        veteran_id = bundle["veteran"]["id"]
        resp = api.list_ledger(
            veteran_id, TEST_USERS["platform_admin_headers"],
            params={"source_entity": "TUITION_PAYMENT"},
        )
        entries, _ = validate_paginated(resp)
        relevant = [e for e in entries
                    if e.get("source_id") == bundle["enrollment"]["id"]]
        assert len(relevant) == 1, (
            f"expected exactly one TUITION_PAYMENT for the activated "
            f"enrollment, got {len(relevant)}"
        )
        e = relevant[0]
        assert e["source_entity"] == "TUITION_PAYMENT"
        assert e["amount_dollars"] == pytest.approx(
            bundle["enrollment"]["certified_tuition_payable"], abs=0.01,
        )


# ===========================================================================
# Cancellation compensation — PRD §3.7
# ===========================================================================
class TestCancellationCompensation:

    def test_cancel_certified_without_prior_payment_emits_no_ledger_entry(
        self, api,
    ):
        """PRD §3.7: "A clerk may cancel a certified enrollment.
        Cancellation moves it from CERTIFIED to CANCELED. If a
        tuition-payment ledger entry was already emitted for this
        enrollment (i.e., the enrollment had advanced to ACTIVE and the
        ledger had paid out), a compensating ledger entry with
        source_entity TUITION_PAYMENT and a negative amount_dollars
        equal to the prior certified_tuition_payable is journaled; if
        no prior tuition entry exists, no ledger entry is emitted."

        # difficulty: compensating_invariant/enrollment_cancel_zeroes_ledger_for_tuition
        """
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        enrollment_id = bundle["enrollment"]["id"]
        veteran_id = bundle["veteran"]["id"]
        # Cancel while still CERTIFIED.
        resp = api.cancel_enrollment(
            enrollment_id, TEST_USERS["va_clerk_headers"],
        )
        canceled = validate_success(resp)
        assert canceled["status"] == "CANCELED"
        # Verify zero TUITION_PAYMENT entries for this enrollment_id.
        resp = api.list_ledger(
            veteran_id, TEST_USERS["platform_admin_headers"],
            params={"source_entity": "TUITION_PAYMENT"},
        )
        entries, _ = validate_paginated(resp)
        for_this = [e for e in entries
                    if e.get("source_id") == enrollment_id]
        total = sum(e["amount_dollars"] for e in for_this)
        assert total == pytest.approx(0.00, abs=0.01), (
            f"sum(TUITION_PAYMENT for cancelled-from-CERTIFIED "
            f"enrollment) must be 0.00, got {total}"
        )


# ===========================================================================
# Completion + entitlement counter — PRD §3.9
# ===========================================================================
class TestCompletion:

    def test_completed_enrollment_updates_months_consumed_and_used(
        self, api,
    ):
        """PRD §3.9: "For a completed enrollment the days-in-program is
        the count of UTC days from term_start to term_end ... In both
        cases Enrollment.months_consumed is set to days-in-program
        divided by 30, rounded half-up to two decimal places."
        """
        bundle = setup_completed_enrollment_with_months(
            months_to_consume=3.00,
            granted_rating=10,
            aggregate_active_duty_days=1100,
        )
        enrollment = bundle["enrollment"]
        # 90 days / 30 = 3.00
        assert enrollment["months_consumed"] == pytest.approx(
            3.00, abs=0.01,
        )
        v = get_veteran(bundle["veteran"]["id"])
        assert v["months_entitlement_used"] == pytest.approx(
            3.00, abs=0.01,
        )

    def test_completion_emits_entitlement_debit_ledger_entry(self, api):
        """PRD §3.9: "Each successful completion or withdrawal also
        journals a single PaymentLedgerEntry with source_entity
        ENTITLEMENT_DEBIT and amount_dollars equal to the negative of
        months_consumed for this enrollment".
        """
        bundle = setup_completed_enrollment_with_months(
            months_to_consume=3.00,
        )
        resp = api.list_ledger(
            bundle["veteran"]["id"], TEST_USERS["platform_admin_headers"],
            params={"source_entity": "ENTITLEMENT_DEBIT"},
        )
        entries, _ = validate_paginated(resp)
        debit = [e for e in entries
                 if e.get("source_id") == bundle["enrollment"]["id"]]
        assert len(debit) == 1
        # months_consumed = 3.00, debit is -3.00.
        assert debit[0]["amount_dollars"] == pytest.approx(-3.00, abs=0.01)


# ===========================================================================
# Entitlement cap — PRD §3.9
# ===========================================================================
class TestEntitlementCap:

    def test_completion_pushing_over_36_months_rejected(self, api):
        """PRD §3.9: "if completing or withdrawing this enrollment would
        cause the cumulative sum across all COMPLETED and WITHDRAWN
        enrollments to rise above 36.00 after the rounding, the
        transition is rejected with ERR_ENTITLEMENT_EXCEEDED. The
        check is a sum-then-test boundary, not a per-row test".
        """
        # Pre-consume 35 months via one COMPLETED enrollment.
        bundle = setup_completed_enrollment_with_months(
            months_to_consume=35.00,
        )
        veteran_id = bundle["veteran"]["id"]
        # Now create a second enrollment of 2 months -> would push to 37
        # > 36.00.
        from test_helpers import create_school, create_enrollment, \
            certify_enrollment, advance_clock_to
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        next_term_days = round(2.00 * 30)  # 60 days
        term_start = iso_utc(utc_midnight(base))
        term_end = iso_utc(
            utc_midnight(base + timedelta(days=next_term_days)),
        )
        enr2 = create_enrollment(
            veteran_id=veteran_id, school_id=school["id"],
            term_start=term_start, term_end=term_end,
            tuition_charged=5000.00,
        )
        certify_enrollment(enr2["id"])
        advance_clock_to(utc_midnight(base))
        run_sweep()
        # Now advance to term_end and try /complete.
        advance_clock_to(
            utc_midnight(base + timedelta(days=next_term_days)),
        )
        resp = api.complete_enrollment(
            enr2["id"], TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_EXCEEDED.value)


# ===========================================================================
# Entitlement projection — PRD §3.9
# ===========================================================================
class TestEntitlementProjection:

    def test_projection_excludes_certified_when_include_certified_false(
        self, api,
    ):
        """PRD §3.9: "When include_certified is false the endpoint
        returns the same chronological figure that is written to
        months_entitlement_used — a sum over COMPLETED and WITHDRAWN
        enrollments only."

        # difficulty: dual_variant_calc/entitlement_chronological_vs_forward_looking
        """
        # Veteran with one COMPLETED enrollment of ~6 months and one
        # CERTIFIED-only enrollment.
        bundle = setup_completed_enrollment_with_months(
            months_to_consume=6.03,  # 181 days = 6.03 months
        )
        veteran_id = bundle["veteran"]["id"]
        v = get_veteran(veteran_id)
        # Chronological used is what's written to months_entitlement_used.
        used = v["months_entitlement_used"]
        assert used == pytest.approx(6.03, abs=0.01)

        resp = api.get_entitlement_projection(
            veteran_id, make_veteran_headers(veteran_id),
            params={"include_certified": False},
        )
        proj = validate_success(resp)
        assert proj["chronological_used"] == pytest.approx(6.03, abs=0.01)

    def test_projection_includes_certified_when_include_certified_true(
        self, api,
    ):
        """PRD §3.9: "When include_certified is true the endpoint
        projects forward by ALSO including every CERTIFIED and ACTIVE
        enrollment as if it had been completed for its full term —
        term_end minus term_start divided by 30, rounded half-up. The
        projection result is NOT written back to
        months_entitlement_used".

        # difficulty: dual_variant_calc/entitlement_chronological_vs_forward_looking
        """
        bundle = setup_completed_enrollment_with_months(
            months_to_consume=6.03,
        )
        veteran_id = bundle["veteran"]["id"]
        # Add a second enrollment, CERTIFIED only — 3 months.
        from test_helpers import (
            create_school, create_enrollment, certify_enrollment,
        )
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=60)
        days_term2 = round(3.00 * 30)
        enr2 = create_enrollment(
            veteran_id=veteran_id, school_id=school["id"],
            term_start=iso_utc(utc_midnight(base)),
            term_end=iso_utc(
                utc_midnight(base + timedelta(days=days_term2)),
            ),
            tuition_charged=5000.00,
        )
        certify_enrollment(enr2["id"])
        # Don't advance/sweep — keep in CERTIFIED.

        resp = api.get_entitlement_projection(
            veteran_id, make_veteran_headers(veteran_id),
            params={"include_certified": True},
        )
        proj = validate_success(resp)
        # chronological_used unchanged.
        assert proj["chronological_used"] == pytest.approx(6.03, abs=0.01)
        # projected_used = chronological_used + projected for CERTIFIED.
        assert proj["projected_used"] == pytest.approx(
            6.03 + 3.00, abs=0.05,
        )
        # And: the projection is NOT written back to
        # months_entitlement_used.
        v = get_veteran(veteran_id)
        assert v["months_entitlement_used"] == pytest.approx(
            6.03, abs=0.01,
        )
        assert v["months_entitlement_used"] != proj["projected_used"]
