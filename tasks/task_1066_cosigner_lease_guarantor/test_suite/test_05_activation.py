"""Guarantee activation preconditions: active agreement, fee paid, compliance hold,
and applicant lease-window overlap (PRD §3.4)."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    setup_preactivation, set_clock, create_portfolio, create_landlord,
    create_verified_applicant, create_quoted_guarantee, create_agreement_payload,
    pay_fee_payload, open_compliance_review,
    make_underwriter_headers, make_landlord_headers, make_applicant_headers,
)


class TestActivateRequiresActiveAgreement:
    """Guarantee->LandlordAgreement dependency: activation needs an ACTIVE agreement."""

    def test_activate_with_signed_but_not_countersigned_agreement_rejected(self, api):
        """PRD §3.4: "An agreement in `ACTIVE` status must exist for this guarantee, else
        `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_agreement_active
        """
        ctx = setup_preactivation(api, pay_fee=True, countersign=False)
        resp = api.activate_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    def test_activate_blocked_leaves_guarantee_approved(self, api):
        """PRD §3.4: "Activation moves the guarantee from `APPROVED` to `ACTIVE`".
        PRD §3.4: "An agreement in `ACTIVE` status must exist for this guarantee, else
        `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_agreement_active
        """
        ctx = setup_preactivation(api, pay_fee=True, countersign=False)
        api.activate_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        fetched = get_success_data(api.get_guarantee(ctx["g_id"],
                                                    make_underwriter_headers("uw1")))
        assert fetched["status"] == "APPROVED"


class TestApplicantLeaseWindowOverlap:
    """Resource=Applicant, half-open [lease_start, lease_end) overlap on activate."""

    def _two_overlapping_guarantees(self, api):
        set_clock(api, "2026-09-15T00:00:00Z")
        pf = create_portfolio(api, exposure_cap_cents=100_000_000)
        ll = create_landlord(api)
        ap = create_verified_applicant(api, credit_score=740, annual_income_cents=20_000_000,
                                       monthly_obligations_cents=200_000)
        ll_headers = make_landlord_headers(ll["id"])
        ap_headers = make_applicant_headers(ap["id"])
        uw_headers = make_underwriter_headers("uw1")

        def build(unit, start, end, activate):
            g = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id=unit,
                                        monthly_rent_cents=200_000, coverage_months=6,
                                        term_months=12, lease_start_date=start,
                                        lease_end_date=end)
            get_success_data(api.approve_guarantee(g["id"], uw_headers))
            get_success_data(api.pay_fee(g["id"], pay_fee_payload(54000), ap_headers))
            ag = get_success_data(api.create_agreement(
                create_agreement_payload(g["id"], ll["id"], unit,
                                         coverage_start_date=start, coverage_end_date=end),
                ll_headers))
            get_success_data(api.sign_agreement(ag["id"], ll_headers))
            get_success_data(api.countersign_agreement(ag["id"], uw_headers))
            if activate:
                get_success_data(api.activate_guarantee(g["id"], uw_headers))
            return g

        build("U-OA", "2026-08-01T00:00:00Z", "2027-08-01T00:00:00Z", activate=True)
        g2 = build("U-OB", "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z", activate=False)
        return g2

    def test_overlapping_window_activation_rejected(self, api):
        """PRD §3.4: "the applicant must not already hold another guarantee in `ACTIVE`
        or `RENEWAL_PENDING` whose lease window overlaps this one; the window is treated
        as half-open over `[lease_start_date, lease_end_date)`, so two windows that merely
        touch at an endpoint are adjacent and allowed, while any genuine overlap is
        rejected with `ERR_APPLICANT_COVERAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/applicant_lease_window_overlap_half_open
        """
        g2 = self._two_overlapping_guarantees(api)
        resp = api.activate_guarantee(g2["id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_APPLICANT_COVERAGE_OVERLAP.value)

    def test_overlap_rejection_leaves_second_guarantee_approved(self, api):
        """PRD §3.4: "any genuine overlap is rejected with
        `ERR_APPLICANT_COVERAGE_OVERLAP`."
        PRD §3.4: "Activation moves the guarantee from `APPROVED` to `ACTIVE`".

        Design: Difficulty/resource_temporal_overlap/applicant_lease_window_overlap_half_open
        """
        g2 = self._two_overlapping_guarantees(api)
        api.activate_guarantee(g2["id"], make_underwriter_headers("uw1"))
        fetched = get_success_data(api.get_guarantee(g2["id"], make_underwriter_headers("uw1")))
        assert fetched["status"] == "APPROVED"


class TestActivateFeeAndComplianceGates:
    def test_activate_without_fee_paid_rejected(self, api):
        """PRD §3.4: "The fee must be paid — `fee_paid` must be true, else
        `ERR_FEE_NOT_PAID`."

        Design: Corner/validations/activate_without_fee_paid_returns_409
        """
        ctx = setup_preactivation(api, pay_fee=False, countersign=True)
        resp = api.activate_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_PAID.value)

    def test_activate_blocked_by_open_compliance_review(self, api):
        """PRD §3.4: "No `ComplianceReview` in `OPEN` status may reference this
        guarantee, else `ERR_COMPLIANCE_HOLD`."

        Design: Corner/validations/activate_blocked_by_open_compliance_hold_returns_409
        """
        ctx = setup_preactivation(api, pay_fee=True, countersign=True)
        open_compliance_review(api, ctx["g_id"], reason="SANCTIONS_HIT", officer_id="co1")
        resp = api.activate_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD.value)
