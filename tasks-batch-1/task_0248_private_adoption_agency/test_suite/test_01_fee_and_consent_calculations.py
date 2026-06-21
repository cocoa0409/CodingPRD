"""Calculation tests: agency-fee sliding scale / combinatorial rounding, and the
consent revocation-deadline dual-variant + inclusive boundary.

Difficulty queue (A): dual_variant_calc, combinatorial_formula, boundary_precision_check.
Corner queue (B): calculations + errors instances on these formulas.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_agency, set_clock, create_case, create_family, create_birth_parent,
    create_approved_home_study, current_case_version,
    create_signed_consent, create_approved_expense,
    create_invoice_payload, create_consent_payload,
    setup_case_with_accepted_match,
    TEST_USERS,
)

FO = TEST_USERS["finance_officer_headers"]
CW = TEST_USERS["caseworker_headers"]
SUP = TEST_USERS["supervisor_headers"]
ADMIN = TEST_USERS["agency_admin_headers"]


# ─── dual_variant_calc / revocation_deadline_calendar_vs_business_days ─────
class TestRevocationDeadlineDualVariant:
    def _two_signed_consents_same_instant(self):
        """Build a case with an ACCEPTED match, sign two consents at the same instant,
        one CALENDAR_DAYS and one BUSINESS_DAYS. Returns (cal_consent, bus_consent)."""
        base = setup_case_with_accepted_match(child_state="NV", family_state="CA",
                                              to_iso8601="2026-06-04T08:00:00.000Z",
                                              birth_state="NV")
        cv = current_case_version(base["case_id"])
        cal = create_signed_consent(base["case_id"], base["bp_id"], cv,
                                    revocation_basis="CALENDAR_DAYS",
                                    child_dob="2026-06-01T08:00:00.000Z")
        cv2 = current_case_version(base["case_id"])
        bus = create_signed_consent(base["case_id"], base["bp_id"], cv2,
                                    revocation_basis="BUSINESS_DAYS",
                                    child_dob="2026-06-01T08:00:00.000Z")
        return cal, bus

    def test_calendar_days_variant_deadline(self):
        """PRD §3.4: "Under the CALENDAR_DAYS variant, the deadline is signed_at
        advanced by ten days of pure wall-clock time — ten times twenty-four hours
        — with weekends and holidays counted normally."

        Design: Difficulty/dual_variant_calc/revocation_deadline_calendar_vs_business_days
        """
        cal, _ = self._two_signed_consents_same_instant()
        assert cal["revocation_deadline"] == "2026-06-14T08:00:00.000Z", \
            f"calendar deadline wrong: {cal['revocation_deadline']}"

    def test_business_days_variant_deadline_differs(self):
        """PRD §3.4: "Under the BUSINESS_DAYS variant, the deadline is the end of the
        fifth business day after signing ... the deadline is 23:59:59.000Z (UTC) of
        the day on which the count reaches zero."

        Design: Difficulty/dual_variant_calc/revocation_deadline_calendar_vs_business_days
        """
        cal, bus = self._two_signed_consents_same_instant()
        assert bus["revocation_deadline"] == "2026-06-11T23:59:59.000Z", \
            f"business deadline wrong: {bus['revocation_deadline']}"
        assert cal["revocation_deadline"] != bus["revocation_deadline"], \
            "same signed_at must yield different deadlines per basis"


# ─── dual_variant_calc / agency_fee_sliding_scale_bands ───────────────────
class TestAgencyFeeSlidingScaleBands:
    def _invoice_for_income(self, income_cents, fee=3_000_000):
        agency = create_agency(fee_schedule_cents=fee)
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        create_family(case["id"], annual_income_cents=income_cents)
        res = api_client.create_invoice(create_invoice_payload(case["id"]), FO)
        return validate_success(res, 201)

    def test_mid_band_zero_pct(self):
        """PRD §3.8: "when the income is at least forty thousand dollars but below
        one hundred twenty thousand dollars (12,000,000 cents), the fraction is zero".

        Design: Difficulty/dual_variant_calc/agency_fee_sliding_scale_bands
        """
        inv = self._invoice_for_income(8_000_000)
        assert inv["sliding_scale_pct"] == 0.0
        assert inv["total_due_cents"] == 3_000_000

    def test_high_band_surcharge_pct(self):
        """PRD §3.8: "when the income is at least one hundred twenty thousand dollars,
        the fraction is positive fifteen hundredths, representing a 15% surcharge."

        Design: Difficulty/dual_variant_calc/agency_fee_sliding_scale_bands
        """
        inv = self._invoice_for_income(15_000_000)
        assert inv["sliding_scale_pct"] == 0.15
        assert inv["total_due_cents"] == 3_450_000


# ─── combinatorial_formula / agency_fee_tiered_min_branch_mode_a ──────────
class TestAgencyFeeCombinatorialModeA:
    def test_reimbursable_clamped_to_cap_mid_band(self):
        """PRD §3.8: "the billable reimbursable amount is the smaller of the case's
        reimbursable expense total and the cap of fifteen thousand dollars (1,500,000
        cents)."

        Design: Difficulty/combinatorial_formula/agency_fee_tiered_min_branch_mode_a
        """
        agency = create_agency(fee_schedule_cents=3_000_000)
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        create_family(case["id"], annual_income_cents=8_000_000)
        # One APPROVED expense of 2,000,000 > cap 1,500,000 -> clamped.
        create_approved_expense(case["id"], amount_cents=2_000_000, category="MEDICAL")
        inv = validate_success(api_client.create_invoice(create_invoice_payload(case["id"]), FO), 201)
        assert inv["base_fee_cents"] == 3_000_000
        # mid band pct 0.0: base 3,000,000 + clamped reimb 1,500,000 = 4,500,000
        assert inv["total_due_cents"] == 4_500_000

    def test_base_fee_captured_at_issuance(self):
        """PRD §3.8: "The invoice's base_fee_cents captures the agency's
        fee_schedule_cents at the moment of issuance".

        Design: Difficulty/combinatorial_formula/agency_fee_tiered_min_branch_mode_a
        """
        agency = create_agency(fee_schedule_cents=3_000_000)
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        create_family(case["id"], annual_income_cents=8_000_000)
        create_approved_expense(case["id"], amount_cents=2_000_000, category="MEDICAL")
        inv = validate_success(api_client.create_invoice(create_invoice_payload(case["id"]), FO), 201)
        assert inv["base_fee_cents"] == 3_000_000


# ─── combinatorial_formula / agency_fee_per_component_rounding_mode_b ──────
class TestAgencyFeePerComponentRoundingModeB:
    def _round_invoice(self):
        agency = create_agency(fee_schedule_cents=30)
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        create_family(case["id"], annual_income_cents=15_000_000)  # high band +0.15
        create_approved_expense(case["id"], amount_cents=10, category="LEGAL")  # reimb 10 < cap
        return validate_success(api_client.create_invoice(create_invoice_payload(case["id"]), FO), 201)

    def test_round_each_component_then_sum(self):
        """PRD §3.8: "the same sliding-scale fraction is applied to both components
        and each is rounded separately ... The rounding order is pinned to
        round-each-component-then-sum; the system must not instead sum the two scaled
        components first and round once".

        Design: Difficulty/combinatorial_formula/agency_fee_per_component_rounding_mode_b
        """
        inv = self._round_invoice()
        # round(30*1.15)=round(34.5)=35 ; round(10*1.15)=round(11.5)=12 ; sum=47
        # (forbidden sum-then-round gives round(46.0)=46)
        assert inv["total_due_cents"] == 47, f"got {inv['total_due_cents']}, expected 47"

    def test_surcharge_pct_applied_high_band(self):
        """PRD §3.8: "when the income is at least one hundred twenty thousand dollars,
        the fraction is positive fifteen hundredths, representing a 15% surcharge."

        Design: Difficulty/combinatorial_formula/agency_fee_per_component_rounding_mode_b
        """
        inv = self._round_invoice()
        assert inv["sliding_scale_pct"] == 0.15


# ─── boundary_precision_check / revocation_deadline_inclusive_boundary ─────
class TestRevocationInclusiveBoundary:
    def _signed_consent_business_basis(self):
        base = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                              to_iso8601="2026-06-04T08:00:00.000Z",
                                              birth_state="CA")
        cv = current_case_version(base["case_id"])
        consent = create_signed_consent(base["case_id"], base["bp_id"], cv,
                                        revocation_basis="BUSINESS_DAYS",
                                        child_dob="2026-06-01T08:00:00.000Z")
        return base["agency_id"], consent

    def test_revoke_allowed_at_exact_deadline_instant(self):
        """PRD §3.4: "revocation requires the consent to be SIGNED and requires the
        agency clock to be at or before the revocation_deadline — the deadline instant
        itself is still revocable."

        Design: Difficulty/boundary_precision_check/revocation_deadline_inclusive_boundary
        """
        agency_id, consent = self._signed_consent_business_basis()
        assert consent["revocation_deadline"] == "2026-06-11T23:59:59.000Z"
        set_clock(agency_id, "2026-06-11T23:59:59.000Z")  # exactly the deadline
        res = api_client.revoke_consent(consent["id"], CW)
        revoked = validate_success(res, 200)
        assert revoked["status"] == "REVOKED"

    def test_revoke_rejected_strictly_after_deadline(self):
        """PRD §3.4: "A revocation attempt strictly after the deadline is rejected with
        ERR_REVOCATION_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/revocation_deadline_inclusive_boundary
        """
        agency_id, consent = self._signed_consent_business_basis()
        set_clock(agency_id, "2026-06-12T00:00:00.000Z")  # one second past 23:59:59
        res = api_client.revoke_consent(consent["id"], CW)
        validate_error(res, "ERR_REVOCATION_WINDOW_CLOSED")


# ─── Corner (B): calculations / agency_fee_low_band_discount ──────────────
def test_agency_fee_low_band_discount():
    """PRD §3.8: "when the family's annual income is below forty thousand dollars
    (4,000,000 cents), the fraction is negative twenty hundredths, representing a 20%
    discount".

    Design: Corner/calculations/agency_fee_low_band_discount
    """
    agency = create_agency(fee_schedule_cents=3_000_000)
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    create_family(case["id"], annual_income_cents=3_000_000)  # low band
    inv = validate_success(api_client.create_invoice(create_invoice_payload(case["id"]), FO), 201)
    assert inv["sliding_scale_pct"] == -0.2
    assert inv["total_due_cents"] == 2_400_000


# ─── Corner (B): calculations / home_study_expiry_constant_applied ────────
def test_home_study_expiry_constant_applied():
    """PRD §3.2: "its expires_at is computed as completed_at plus the validity window
    of 365 days (that is, completed_at advanced by 365 times twenty-four hours of
    wall-clock time)."

    Design: Corner/calculations/home_study_expiry_constant_applied
    """
    agency = create_agency(fee_schedule_cents=3_000_000)
    set_clock(agency["id"], "2026-06-04T08:00:00.000Z")
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    hs = create_approved_home_study(case["id"], family["id"])
    assert hs["completed_at"] == "2026-06-04T08:00:00.000Z"
    assert hs["expires_at"] == "2027-06-04T08:00:00.000Z"


# ─── Corner (B): calculations / reimbursable_total_excludes_logged_and_rejected ──
def test_reimbursable_total_excludes_logged_and_rejected():
    """PRD §3.7: "The reimbursable expense total for a case is the sum of amount_cents
    over the case's expenses whose status is APPROVED or DISBURSED; expenses that are
    LOGGED or REJECTED are excluded".

    Design: Corner/calculations/reimbursable_total_excludes_logged_and_rejected
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    create_approved_expense(case["id"], amount_cents=200_000, category="MEDICAL")  # APPROVED
    # One LOGGED (never approved).
    from test_helpers import create_logged_expense
    create_logged_expense(case["id"], amount_cents=50_000, category="LIVING")
    # One REJECTED.
    rej = create_logged_expense(case["id"], amount_cents=70_000, category="TRAVEL")
    api_client.reject_expense(rej["id"], FO)
    got = validate_success(api_client.get_case(case["id"], FO), 200)
    assert got["reimbursable_expense_cents"] == 200_000
