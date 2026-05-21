"""The annual review cycle: submission window, recertification variant
of adjusted income + TTP, approve/deny/deficient cascades.

PRD §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_by_days,
    advance_clock_to,
    add_days,
    approve_review,
    assert_hap_plus_ttp_equals_gross_rent,
    current_clock,
    deny_review,
    find_due_annual_review_id,
    get_annual_review,
    get_tenancy,
    get_voucher,
    iso_utc,
    mark_deficient_payload,
    make_applicant_headers,
    make_case_worker_headers,
    new_case_worker_id,
    parse_iso,
    resubmit_annual_review_payload,
    setup_active_tenancy,
    submit_annual_review_payload,
    sweep_reviews,
    take_active_tenancy_to_abated,
    validate_error,
    validate_success,
)


def _open_review_window_and_get_ar_id(state) -> str:
    """Advance the clock into the AR window and return the AR id."""
    lease_start = parse_iso(state["tenancy"]["lease_start"])
    advance_clock_to(add_days(lease_start, 365))
    return find_due_annual_review_id(state["tenancy"]["id"])


class TestAnnualReviewSubmissionWindow:

    def test_submission_outside_window_rejected(self, api):
        """PRD §3.9: "the submission timestamp must lie within 30 days
        before or after review_due_date, or it is rejected with
        ERR_REVIEW_WINDOW_CLOSED."

        Advance well past review_due_date + 30 days, then try to submit.
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        ar_id = _open_review_window_and_get_ar_id(state)
        # Advance further so we are well past the window.
        advance_clock_by_days(60)
        applicant_id = state["applicant"]["id"]
        headers = make_applicant_headers(applicant_id)
        resp = api.submit_annual_review(
            ar_id,
            submit_annual_review_payload(3_000_000, 3),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED.value)


class TestRecertificationVariantDivergesFromInitial:
    """Difficulty Design rule 1: dual-variant calc across entity
    domains. Same gross income, different declared household_size →
    different new_adjusted_income on the AR while the Applicant
    snapshot stays put."""

    def test_recertification_diverges_from_applicant_snapshot(self, api):
        """PRD §3.9: "(2) the dependent count for the dependent-allowance
        step is derived from the recertification's declared_household_size
        minus 1 (subtracting the head of household) — this is the pinned
        recertification heuristic and produces a different
        dependent-allowance figure than the initial variant whenever the
        household has grown or shrunk since application."
        PRD §3.9: "(4) the result is written to new_adjusted_income_cents
        on the AnnualReview rather than being written back to the
        Applicant."

        Setup: Applicant gross=3_000_000, household=3, dependents=1 →
        Applicant.adjusted = 3_000_000 - 48_000 = 2_952_000.
        Recertify with declared_household_size=4 → recert dependents = 3
        → new_adjusted = 3_000_000 - 144_000 = 2_856_000.
        # difficulty: dual_variant_calc/ttp_initial_vs_recertification_diverge_on_tenancy
        # difficulty: dual_variant_calc/adjusted_income_initial_vs_recertification_diverge_on_applicant_household
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        ar_id = _open_review_window_and_get_ar_id(state)
        applicant_id = state["applicant"]["id"]
        headers = make_applicant_headers(applicant_id)
        resp = api.submit_annual_review(
            ar_id,
            submit_annual_review_payload(
                declared_gross_annual_income_cents=3_000_000,
                declared_household_size=4,
            ),
            headers,
        )
        ar = validate_success(resp)
        # recert dep_count = 4 - 1 = 3 → 144_000 deduction.
        assert ar["new_adjusted_income_cents"] == 2_856_000
        # Applicant snapshot unchanged.
        from test_helpers import get_applicant
        applicant_after = get_applicant(applicant_id)
        assert applicant_after["adjusted_annual_income_cents"] == 2_952_000
        # And the recert TTP divergence.
        # monthly_adjusted = floor(2_856_000/12) = 238_000.
        # 30% ceil = 71_400; 10% ceil of monthly_gross 250_000 = 25_000.
        # TTP = max(71_400, 25_000, 0, 5_000) = 71_400.
        assert ar["new_total_tenant_payment_cents"] == 71_400

    def test_approve_cascades_new_ttp_and_hap_into_tenancy(self, api):
        """PRD §3.9: "If the review is approved, the new TTP and HAP
        cascade into the tenancy: current_total_tenant_payment_cents
        becomes new_total_tenant_payment_cents, current_hap_cents
        becomes new_hap_cents".
        # difficulty: compensating_invariant/hap_plus_ttp_equals_gross_rent_per_tenancy_month
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=110_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            comparable_rents_cents=[110_000, 120_000, 130_000, 140_000],
        )
        ar_id = _open_review_window_and_get_ar_id(state)
        applicant_id = state["applicant"]["id"]
        headers = make_applicant_headers(applicant_id)
        # Recertify with declared_household_size=1 (smaller household).
        # Recert dep_count = 0 → adjusted = 2_400_000 - 0 = 2_400_000.
        # monthly_adjusted = 200_000. 30% ceil = 60_000. min_rent 5_000.
        # TTP_new = max(60_000, 25_000_or_less, 5_000) → 60_000 (when
        # gross = 2_400_000 monthly_gross 200_000 10% ceil 20_000).
        validate_success(
            api.submit_annual_review(
                ar_id,
                submit_annual_review_payload(2_400_000, 1),
                headers,
            ),
        )
        ar_after = approve_review(ar_id)
        assert ar_after["status"] == "APPROVED"
        # Cascaded into Tenancy.current_*.
        t = get_tenancy(state["tenancy"]["id"])
        assert (
            t["current_total_tenant_payment_cents"]
            == ar_after["new_total_tenant_payment_cents"]
        )
        assert t["current_hap_cents"] == ar_after["new_hap_cents"]
        assert_hap_plus_ttp_equals_gross_rent(t)


class TestDeficientCycle:

    def test_mark_deficient_then_resubmit_returns_to_submitted(self, api):
        """PRD §3.9: "If the review is marked deficient (with a
        non-empty array of deficiency_codes such as missing pay stubs
        or missing IDs), the review transitions from SUBMITTED to
        DEFICIENT and the applicant has 14 days to resubmit. A resubmit
        within that window clears the deficiency_codes, recomputes
        new_adjusted_income_cents, new_total_tenant_payment_cents, and
        new_hap_cents, and re-enters SUBMITTED (this is the only cycle
        in any state machine in the system)."
        # difficulty: non_linear_state_machine/annual_review_cyclic_submitted_deficient
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        ar_id = _open_review_window_and_get_ar_id(state)
        applicant_id = state["applicant"]["id"]
        ap_headers = make_applicant_headers(applicant_id)
        cw = make_case_worker_headers(new_case_worker_id())
        # Submit.
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3),
                ap_headers,
            ),
        )
        # Mark deficient.
        deficient_resp = validate_success(
            api.mark_deficient_annual_review(
                ar_id, mark_deficient_payload(["missing_paystubs"]), cw,
            ),
        )
        assert deficient_resp["status"] == "DEFICIENT"
        # Resubmit.
        resubmitted = validate_success(
            api.resubmit_annual_review(
                ar_id,
                resubmit_annual_review_payload(3_000_000, 3),
                ap_headers,
            ),
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted.get("deficiency_codes", []) == []


class TestDenyCascade:

    def test_deny_cascades_tenancy_and_voucher_to_terminated(self, api):
        """PRD §3.9: "If the review is denied — for example when
        new_adjusted_income_cents exceeds the HUD low-income limit by
        more than 20 percent or a fraud determination is filed — the
        tenancy cascades to TERMINATED with termination_reason
        ANNUAL_REVIEW_DENIED and the voucher cascades from LEASED to
        TERMINATED."
        # difficulty: transitive_cascade/annual_review_deny_chain_depth_3
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        ar_id = _open_review_window_and_get_ar_id(state)
        applicant_id = state["applicant"]["id"]
        ap_headers = make_applicant_headers(applicant_id)
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3),
                ap_headers,
            ),
        )
        denied = deny_review(ar_id)
        assert denied["status"] == "DENIED"
        t = get_tenancy(state["tenancy"]["id"])
        v = get_voucher(state["voucher"]["id"])
        assert t["status"] == "TERMINATED"
        assert t["termination_reason"] == "ANNUAL_REVIEW_DENIED"
        assert v["status"] == "TERMINATED"


class TestDeficientSweep:

    def test_deficient_past_14_days_swept_to_denied(self, api):
        """PRD §3.9: "If 14 days elapse without a resubmit, the
        deficient-review sweep transitions the review from DEFICIENT to
        DENIED and runs the same cascade as a directly denied review:
        tenancy to TERMINATED with ANNUAL_REVIEW_DENIED, voucher to
        TERMINATED."
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        ar_id = _open_review_window_and_get_ar_id(state)
        applicant_id = state["applicant"]["id"]
        ap_headers = make_applicant_headers(applicant_id)
        cw = make_case_worker_headers(new_case_worker_id())
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3),
                ap_headers,
            ),
        )
        validate_success(
            api.mark_deficient_annual_review(
                ar_id, mark_deficient_payload(["missing_ids"]), cw,
            ),
        )
        # Advance > 14 days.
        advance_clock_by_days(15)
        sweep_reviews()
        ar_after = get_annual_review(ar_id)
        assert ar_after["status"] == "DENIED"
        t = get_tenancy(state["tenancy"]["id"])
        assert t["status"] == "TERMINATED"
        assert t["termination_reason"] == "ANNUAL_REVIEW_DENIED"
