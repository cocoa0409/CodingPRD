"""Eligibility audits, honor designation variants, appeals, and readiness
lifecycle terminal behavior."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_ceremony, import_graduate, audit_graduate, import_and_audit,
    create_reader_card, get_graduate, get_ceremony, set_clock,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def _setup_dual_variant_graduate():
    """AUDIT_OPEN ceremony; one graduate whose COMBINED tier (transfer credits
    counted) diverges from the INSTITUTIONAL tier for identical stored data."""
    ctx = setup_ceremony(open_audit=True)
    graduate = import_graduate(
        ctx["ceremony"]["id"], full_name="Dana Dual", email="dana@x.edu",
        institutional_gpa_credits=45, institutional_quality_points=162.0,
        transfer_gpa_credits=30, transfer_quality_points=118.2,
        credits_completed=120, credits_required=120, outstanding_hold_count=0)
    return ctx, graduate


class TestHonorDualVariant:
    def test_provisional_combined_tier_at_audit(self, api):
        """PRD §3.2: "The **COMBINED** variant — the provisional designation —
        divides the sum of `institutional_quality_points` and
        `transfer_quality_points` by the sum of `institutional_gpa_credits` and
        `transfer_gpa_credits`, so transfer work counts; it is computed at
        audit creation, on audit reopening, and on appeal approval."
        PRD §3.2: "At audit time the provisional COMBINED tier is written to
        the graduate's `honor_tier` with `honor_basis` `COMBINED`, and
        snapshotted onto the audit as `provisional_honor_tier`"

        Design: Difficulty/dual_variant_calc/honor_provisional_combined_vs_final_institutional
        """
        ctx, graduate = _setup_dual_variant_graduate()
        audit = validate_success(api.create_audit(graduate["id"], {}, REGISTRAR), 201)
        # COMBINED: (162.0 + 118.2) / (45 + 30) = 280.2 / 75 = 3.736 >= 3.700
        assert audit["result"] == "PASS"
        assert audit["provisional_honor_tier"] == "MAGNA_CUM_LAUDE"
        after = get_graduate(graduate["id"])
        assert after["honor_tier"] == "MAGNA_CUM_LAUDE"
        assert after["honor_basis"] == "COMBINED"

    def test_final_institutional_tier_at_lock(self, api):
        """PRD §3.2: "The **INSTITUTIONAL** variant — the final designation —
        divides `institutional_quality_points` by `institutional_gpa_credits`
        alone, excluding transfer work; it is computed when the audit locks and
        when grades are revised, and it is the variant printed on diplomas and
        consumed by the ticket honor bonus."
        PRD §3.2: "Locking the audit recomputes the FINAL INSTITUTIONAL variant
        for every graduate in `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED`,
        updating each graduate's `honor_tier` and setting `honor_basis` to
        `INSTITUTIONAL`."

        Design: Difficulty/dual_variant_calc/honor_provisional_combined_vs_final_institutional
        """
        ctx, graduate = _setup_dual_variant_graduate()
        audit_graduate(graduate["id"])
        validate_success(api.lock_audit(ctx["ceremony"]["id"], CHAIR), 200)
        # INSTITUTIONAL: 162.0 / 45 = 3.600 -> >= 3.500 but < 3.700
        after = get_graduate(graduate["id"])
        assert after["honor_tier"] == "CUM_LAUDE"
        assert after["honor_basis"] == "INSTITUTIONAL"


class TestHonorGpaThresholdBoundary:
    def test_gpa_rounds_half_up_to_exactly_3_900_admits_summa(self, api):
        """PRD §2.8: "Grade-point averages are carried to exactly 3 decimal
        places, rounded half up, and the rounding is applied **before** any
        threshold comparison; all threshold comparisons are inclusive of the
        boundary."
        PRD §3.2: "a GPA of at least 3.900 earns `SUMMA_CUM_LAUDE`, at least
        3.700 earns `MAGNA_CUM_LAUDE`, at least 3.500 earns `CUM_LAUDE`, and
        anything below earns `NONE`."

        Design: Difficulty/boundary_precision_check/honor_gpa_threshold_exact_after_rounding
        """
        ctx = setup_ceremony(open_audit=True)
        graduate = import_graduate(
            ctx["ceremony"]["id"], full_name="H1 Edge", email="h1@x.edu",
            institutional_gpa_credits=60, institutional_quality_points=233.97,
            credits_completed=120, credits_required=120)
        audit = validate_success(api.create_audit(graduate["id"], {}, REGISTRAR), 201)
        # 233.97 / 60 = 3.8995 -> round half up -> 3.900 -> >= 3.900 admits SUMMA
        assert audit["provisional_honor_tier"] == "SUMMA_CUM_LAUDE"
        assert get_graduate(graduate["id"])["honor_tier"] == "SUMMA_CUM_LAUDE"

    def test_gpa_rounding_3_8994_stays_magna(self, api):
        """PRD §2.8: "Grade-point averages are carried to exactly 3 decimal
        places, rounded half up, and the rounding is applied **before** any
        threshold comparison; all threshold comparisons are inclusive of the
        boundary."
        PRD §3.2: "a GPA of at least 3.900 earns `SUMMA_CUM_LAUDE`, at least
        3.700 earns `MAGNA_CUM_LAUDE`, at least 3.500 earns `CUM_LAUDE`, and
        anything below earns `NONE`."

        Design: Difficulty/boundary_precision_check/honor_gpa_threshold_exact_after_rounding
        """
        ctx = setup_ceremony(open_audit=True)
        graduate = import_graduate(
            ctx["ceremony"]["id"], full_name="H2 Edge", email="h2@x.edu",
            institutional_gpa_credits=60, institutional_quality_points=233.964,
            credits_completed=120, credits_required=120)
        audit = validate_success(api.create_audit(graduate["id"], {}, REGISTRAR), 201)
        # 233.964 / 60 = 3.8994 -> 3.899 -> < 3.900, >= 3.700
        assert audit["provisional_honor_tier"] == "MAGNA_CUM_LAUDE"
        assert get_graduate(graduate["id"])["honor_tier"] == "MAGNA_CUM_LAUDE"


class TestHonorVariantCoincidence:
    def test_honor_variants_equal_without_transfer_credits(self, api):
        """PRD §3.2: "The **INSTITUTIONAL** variant — the final designation —
        divides `institutional_quality_points` by `institutional_gpa_credits`
        alone, excluding transfer work".
        PRD §3.2: "Locking the audit recomputes the FINAL INSTITUTIONAL variant
        for every graduate in `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED`,
        updating each graduate's `honor_tier` and setting `honor_basis` to
        `INSTITUTIONAL`."

        Design: Corner/calculations/honor_variants_equal_without_transfer_credits
        """
        ctx = setup_ceremony(open_audit=True)
        graduate, audit = import_and_audit(
            ctx["ceremony"]["id"], full_name="Steady Steve", email="steve@x.edu",
            institutional_gpa_credits=45, institutional_quality_points=171.0,
            transfer_gpa_credits=0, transfer_quality_points=0)
        # 171.0 / 45 = 3.800 -> MAGNA under both variants when transfer is zero
        assert audit["provisional_honor_tier"] == "MAGNA_CUM_LAUDE"
        validate_success(api.lock_audit(ctx["ceremony"]["id"], CHAIR), 200)
        after = get_graduate(graduate["id"])
        assert after["honor_tier"] == "MAGNA_CUM_LAUDE"
        assert after["honor_basis"] == "INSTITUTIONAL"


class TestEligibilityBoundaries:
    def test_eligibility_exact_credits_and_hold_boundary(self, api):
        """PRD §3.2: "the graduate **passes** when `credits_completed` is at
        least `credits_required` — meeting the requirement exactly passes —
        **and** `outstanding_hold_count` is exactly zero **and**
        `institutional_gpa_credits` is strictly greater than zero."
        PRD §3.2: "the `fail_reasons` array accumulates the applicable subset
        of `INSUFFICIENT_CREDITS` (credits short of the requirement),
        `OUTSTANDING_HOLD` (an unresolved hold), and `NO_INSTITUTIONAL_CREDITS`
        (no institutional GPA credits)".

        Design: Corner/calculations/eligibility_exact_credits_and_hold_boundary
        """
        ctx = setup_ceremony(open_audit=True)
        ceremony_id = ctx["ceremony"]["id"]
        ok = import_graduate(ceremony_id, full_name="Ok Olive", email="ok@x.edu",
                             credits_completed=120, credits_required=120,
                             outstanding_hold_count=0)
        short = import_graduate(ceremony_id, full_name="Short Shaw", email="short@x.edu",
                                credits_completed=119, credits_required=120,
                                outstanding_hold_count=0)
        hold = import_graduate(ceremony_id, full_name="Hold Holly", email="hold@x.edu",
                               credits_completed=120, credits_required=120,
                               outstanding_hold_count=1)

        audit_ok = validate_success(api.create_audit(ok["id"], {}, REGISTRAR), 201)
        assert audit_ok["result"] == "PASS"
        assert audit_ok["fail_reasons"] == []

        audit_short = validate_success(api.create_audit(short["id"], {}, REGISTRAR), 201)
        assert audit_short["result"] == "FAIL"
        assert audit_short["fail_reasons"] == ["INSUFFICIENT_CREDITS"]
        assert get_graduate(short["id"])["status"] == "INELIGIBLE"

        audit_hold = validate_success(api.create_audit(hold["id"], {}, REGISTRAR), 201)
        assert audit_hold["result"] == "FAIL"
        assert audit_hold["fail_reasons"] == ["OUTSTANDING_HOLD"]
        assert get_graduate(hold["id"])["status"] == "INELIGIBLE"


class TestReopenAuditRestoresProvisional:
    def test_reopen_audit_restores_provisional_honor(self, api):
        """PRD §3.2: "Reopening the audit recomputes the PROVISIONAL COMBINED
        variant for every audited, non-`WITHDRAWN` graduate in the eligible
        family, setting `honor_basis` back to `COMBINED`".
        PRD §3.1: "Reopening the audit returns `AUDIT_LOCKED` to `AUDIT_OPEN`,
        but only while no print batch for the ceremony stands in `RELEASED` or
        `PRINTED` status".

        Design: Corner/state_machines/reopen_audit_restores_provisional_honor
        """
        ctx, graduate = _setup_dual_variant_graduate()
        audit_graduate(graduate["id"])
        validate_success(api.lock_audit(ctx["ceremony"]["id"], CHAIR), 200)
        locked = get_graduate(graduate["id"])
        assert locked["honor_tier"] == "CUM_LAUDE"      # INSTITUTIONAL 3.600
        assert locked["honor_basis"] == "INSTITUTIONAL"

        ceremony = validate_success(api.reopen_audit(ctx["ceremony"]["id"], CHAIR), 200)
        assert ceremony["readiness_posture"] == "AUDIT_OPEN"
        reopened = get_graduate(graduate["id"])
        assert reopened["honor_tier"] == "MAGNA_CUM_LAUDE"  # COMBINED 280.2/75 = 3.736
        assert reopened["honor_basis"] == "COMBINED"


class TestAppealWindow:
    def test_appeal_window_closed_returns_error(self, api):
        """PRD §2.10: "An appeal filed strictly after fourteen days from the
        audit's `created_at` is rejected with `ERR_APPEAL_WINDOW_CLOSED`".

        Design: Corner/validations/appeal_window_closed_returns_error
        """
        ctx = setup_ceremony(open_audit=True)
        graduate = import_graduate(
            ctx["ceremony"]["id"], full_name="Appeal Andy", email="andy@x.edu",
            credits_completed=119, credits_required=120, outstanding_hold_count=0)
        audit = validate_success(api.create_audit(graduate["id"], {}, REGISTRAR), 201)
        assert audit["result"] == "FAIL"
        assert get_graduate(graduate["id"])["status"] == "INELIGIBLE"

        set_clock("2026-05-20T00:00:00Z")  # audit created at the 2026-05-01 default
        res = api.appeal_audit(audit["id"], headers={
            "X-User-ID": graduate["id"], "X-User-Role": "Graduate",
            "Content-Type": "application/json"})
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
        assert res.status_code == 422

        audits = validate_success(api.list_graduate_audits(graduate["id"], REGISTRAR), 200)
        assert audits[0]["appeal_status"] == "NONE"


class TestReadinessTerminalState:
    def test_ceremony_commence_after_complete_returns_invalid_state(self, api):
        """PRD §3.1: "Commencing moves `READY` to `COMMENCED`, and completing
        moves `COMMENCED` to the terminal `COMPLETED`."
        PRD §2.11: "The target entity's own state machine permits the
        transition from its current state, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ceremony_commence_after_complete_returns_invalid_state
        """
        ctx = setup_ceremony(open_audit=True)
        ceremony = ctx["ceremony"]
        graduate, _ = import_and_audit(ceremony["id"], full_name="Term Tina",
                                       email="tina@x.edu")
        validate_success(api.lock_audit(ceremony["id"], CHAIR), 200)
        create_reader_card(graduate["id"], "TUR-mee-nuh TEE-nuh")
        validate_success(api.mark_ready(ceremony["id"], CHAIR), 200)
        validate_success(api.commence_ceremony(ceremony["id"], CHAIR), 200)
        completed = validate_success(api.complete_ceremony(ceremony["id"], CHAIR), 200)
        assert completed["readiness_posture"] == "COMPLETED"

        res = api.commence_ceremony(ceremony["id"], CHAIR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409
        assert get_ceremony(ceremony["id"])["readiness_posture"] == "COMPLETED"
