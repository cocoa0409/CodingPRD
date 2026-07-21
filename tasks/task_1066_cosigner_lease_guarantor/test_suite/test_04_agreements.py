"""Landlord agreements: unit-coverage buffer and countersign precondition
(PRD §3.3)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_portfolio, create_landlord, create_verified_applicant, create_applicant,
    create_quoted_guarantee, create_agreement_payload,
    make_underwriter_headers, make_landlord_headers,
)


def _unit_with_active_agreement(api, unit_id="U-BUF"):
    """Build a portfolio + landlord + verified applicant + an APPROVED guarantee G1
    whose agreement on `unit_id` (window 2026-08-01..2027-08-01) has been countersigned
    to ACTIVE. Returns (pf, ll, ap)."""
    pf = create_portfolio(api, exposure_cap_cents=100_000_000)
    ll = create_landlord(api)
    ap = create_verified_applicant(api, credit_score=740, annual_income_cents=12_000_000,
                                   monthly_obligations_cents=200_000)
    g1 = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id=unit_id,
                                monthly_rent_cents=249_999, coverage_months=6, term_months=12,
                                lease_start_date="2026-08-01T00:00:00Z",
                                lease_end_date="2027-08-01T00:00:00Z")
    get_success_data(api.approve_guarantee(g1["id"], make_underwriter_headers("uw1")))
    ll_headers = make_landlord_headers(ll["id"])
    ag1 = get_success_data(api.create_agreement(
        create_agreement_payload(g1["id"], ll["id"], unit_id,
                                 coverage_start_date="2026-08-01T00:00:00Z",
                                 coverage_end_date="2027-08-01T00:00:00Z"),
        ll_headers))
    get_success_data(api.sign_agreement(ag1["id"], ll_headers))
    get_success_data(api.countersign_agreement(ag1["id"], make_underwriter_headers("uw1")))
    return pf, ll, ap


class TestUnitCoverageBuffer:
    """Same unit_id: coverage windows must be >= 30 days (UNIT_BUFFER_DAYS) apart."""

    def test_window_within_buffer_rejected(self, api):
        """PRD §3.3: "a new agreement whose window is within 30 days of an existing
        `ACTIVE` agreement on the same unit is rejected with `ERR_UNIT_COVERAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/unit_agreement_buffer_gap_overlap
        """
        pf, ll, ap = _unit_with_active_agreement(api, "U-BUF")
        g2 = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id="U-BUF",
                                    monthly_rent_cents=249_999, coverage_months=6,
                                    term_months=12,
                                    lease_start_date="2027-08-15T00:00:00Z",
                                    lease_end_date="2028-08-15T00:00:00Z")
        resp = api.create_agreement(
            create_agreement_payload(g2["id"], ll["id"], "U-BUF",
                                     coverage_start_date="2027-08-15T00:00:00Z",
                                     coverage_end_date="2028-08-15T00:00:00Z"),
            make_landlord_headers(ll["id"]))
        validate_error(resp, ApiErrorId.ERR_UNIT_COVERAGE_OVERLAP.value)

    def test_window_exactly_full_buffer_apart_accepted(self, api):
        """PRD §3.3: "For agreements naming the same `unit_id`, the closed coverage
        windows must be separated by a gap of at least 30 days".
        PRD §3.3: "only windows that stand at least the full buffer apart are accepted."

        Design: Difficulty/resource_temporal_overlap/unit_agreement_buffer_gap_overlap
        """
        pf, ll, ap = _unit_with_active_agreement(api, "U-BUF")
        # ag1 ends 2027-08-01; new window starts 2027-08-31 → gap is exactly 30 days.
        g2 = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id="U-BUF",
                                    monthly_rent_cents=249_999, coverage_months=6,
                                    term_months=12,
                                    lease_start_date="2027-08-31T00:00:00Z",
                                    lease_end_date="2028-08-31T00:00:00Z")
        created = validate_success(api.create_agreement(
            create_agreement_payload(g2["id"], ll["id"], "U-BUF",
                                     coverage_start_date="2027-08-31T00:00:00Z",
                                     coverage_end_date="2028-08-31T00:00:00Z"),
            make_landlord_headers(ll["id"])), expected_status=201)
        assert created["status"] == "DRAFT"


class TestCountersignPrecondition:
    def test_countersign_quoted_guarantee_rejected(self, api):
        """PRD §3.3: "An `Underwriter` then countersigns, advancing it from `SIGNED` to
        `ACTIVE`, but only if the referenced guarantee is currently in `APPROVED` — a
        countersign against a guarantee in any other state is rejected with
        `ERR_GUARANTEE_NOT_APPROVED`."

        Design: Corner/validations/countersign_unapproved_guarantee_returns_409
        """
        pf = create_portfolio(api, exposure_cap_cents=100_000_000)
        ll = create_landlord(api)
        ap = create_applicant(api)  # applicant need not be verified for quoting
        g = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id="U-CN1")
        ll_headers = make_landlord_headers(ll["id"])
        ag = get_success_data(api.create_agreement(
            create_agreement_payload(g["id"], ll["id"], "U-CN1"), ll_headers))
        get_success_data(api.sign_agreement(ag["id"], ll_headers))
        resp = api.countersign_agreement(ag["id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_APPROVED.value)
