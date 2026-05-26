"""Boundary-precision and temporal-interval tests.

Difficulty/boundary_precision_check + resource_temporal_overlap.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_donor_beneficiary_account,
    set_clock,
    create_and_post_contribution,
    create_draft_withdrawal,
    submit_withdrawal,
    approve_withdrawal,
    disburse_withdrawal,
    create_form_1099q,
    get_account,
    make_tax_authority_headers,
    make_custodian_headers,
)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check
# ---------------------------------------------------------------------------

class TestBoundaryPrecision:
    def test_k12_cap_exact_equality_no_excess(self, api):
        """PRD §3.6: "When the expense_class is K_12_TUITION, the system computes a projected K-12
        running total as the account's current ytd_qualified_k12_cents plus this withdrawal's
        amount_cents, and the k12_excess_cents is the larger of zero and that projected value
        minus the 1,000,000-cent annual cap. The cap is inclusive of equality at the boundary:
        a projected running total of exactly 1,000,000 cents yields k12_excess_cents of zero."

        Design: Difficulty/boundary_precision_check/k12_cap_exact_equality_no_excess
        """
        donor, _ben, account = setup_donor_beneficiary_account(
            donor_email="d9@x.com", beneficiary_tax_id="2222"
        )
        # Beneficiary DOB irrelevant to cap; we use default. Stage account.
        posted = create_and_post_contribution(account["id"], 2_000_000)
        a_v1 = posted["version"]
        # W1 K_12 600000 -> ytd_k12 becomes 600000.
        w1 = create_draft_withdrawal(account["id"], donor["id"], 600_000, "K_12_TUITION")
        submit_withdrawal(w1["id"], donor["id"])
        approve_withdrawal(w1["id"], a_v1)
        disbursed = disburse_withdrawal(w1["id"])
        a_v3 = disbursed["version"]
        # W2 K_12 400000 -> projected ytd = 1000000 (exactly the cap).
        w2 = create_draft_withdrawal(account["id"], donor["id"], 400_000, "K_12_TUITION")
        submit_withdrawal(w2["id"], donor["id"])
        approved = approve_withdrawal(w2["id"], a_v3)
        assert approved["k12_excess_cents"] == 0
        assert approved["penalty_cents"] == 0
        assert approved["status"] == "APPROVED"

    def test_form_1099q_issuance_year_boundary_dec_31_vs_jan_1(self, api):
        """PRD §3.9: "Issuing a DRAFT form drives it to ISSUED and freezes its content. The issue
        step requires the current clock to be at or after January 1 of the year following the
        tax_year — pre-year-end issuance is rejected with ERR_FORM_PREMATURE_ISSUANCE."

        Design: Difficulty/boundary_precision_check/form_1099q_issuance_year_boundary_dec_31_vs_jan_1
        """
        set_clock("2026-05-01T00:00:00.000Z")
        donor, _ben, account = setup_donor_beneficiary_account(
            clock_iso=None, donor_email="d10@x.com"
        )
        posted = create_and_post_contribution(account["id"], 500_000)
        a_v1 = posted["version"]
        w = create_draft_withdrawal(account["id"], donor["id"], 200_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        approve_withdrawal(w["id"], a_v1)
        disburse_withdrawal(w["id"])
        form = create_form_1099q(account["id"], 2026)
        # Clock at 2026-12-31T23:59:59.999Z — before Jan 1 of tax_year+1; issue REJECTED.
        set_clock("2026-12-31T23:59:59.999Z")
        resp1 = api.issue_form_1099q(form["id"], make_tax_authority_headers())
        validate_error(
            resp1, ApiErrorId.ERR_FORM_PREMATURE_ISSUANCE.value, expected_status=422
        )
        # Advance to 2027-01-01 — boundary inclusive; issue ACCEPTED.
        set_clock("2027-01-01T00:00:00.000Z")
        resp2 = api.issue_form_1099q(form["id"], make_tax_authority_headers())
        data = validate_success(resp2, expected_status=200)
        assert data["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap
# ---------------------------------------------------------------------------

class TestResourceTemporalOverlap:
    def test_k12_annual_cap_aggregate_capacity_interval_on_account(self, api):
        """PRD §3.6: "K-12 tuition distributions are capped at $10,000 (1,000,000 cents) per
        beneficiary per calendar year — this is a federal ceiling on the qualified K-12 portion
        of distributions. When the expense_class is K_12_TUITION, the system computes a
        projected K-12 running total as the account's current ytd_qualified_k12_cents plus this
        withdrawal's amount_cents, and the k12_excess_cents is the larger of zero and that
        projected value minus the 1,000,000-cent annual cap."

        Design: Difficulty/resource_temporal_overlap/k12_annual_cap_aggregate_capacity_interval_on_account
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="d13@x.com")
        posted = create_and_post_contribution(account["id"], 2_000_000)
        a_v1 = posted["version"]
        # W1 K_12 800000 -> ytd_k12 = 800000.
        w1 = create_draft_withdrawal(account["id"], donor["id"], 800_000, "K_12_TUITION")
        submit_withdrawal(w1["id"], donor["id"])
        approve_withdrawal(w1["id"], a_v1)
        disbursed = disburse_withdrawal(w1["id"])
        a_v3 = disbursed["version"]
        # W2 K_12 500000 -> projected ytd = 1300000 -> k12_excess = 300000.
        w2 = create_draft_withdrawal(account["id"], donor["id"], 500_000, "K_12_TUITION")
        submit_withdrawal(w2["id"], donor["id"])
        approved = approve_withdrawal(w2["id"], a_v3)
        assert approved["k12_excess_cents"] == 300_000
        assert approved["status"] == "APPROVED"

    def test_contribution_reverse_72h_strict_adjacency_window_on_contribution(self, api):
        """PRD §3.4: "Reversing a posted contribution drives it from POSTED to the terminal
        REVERSED. The reverse is a narrow, time-boxed correction: the clock-time delta between
        the current clock and the contribution's posted_at_utc must be strictly less than 72
        hours, or the request is rejected with ERR_REVERSE_WINDOW_CLOSED."

        Design: Difficulty/resource_temporal_overlap/contribution_reverse_72h_strict_adjacency_window_on_contribution
        """
        # Clock at 2026-03-01, post a contribution, advance exactly 72h, reverse rejected.
        _donor, _ben, account = setup_donor_beneficiary_account(donor_email="d14@x.com")
        posted = create_and_post_contribution(account["id"], 100_000)
        # Advance clock to exactly +72h.
        set_clock("2026-03-04T00:00:00.000Z")
        resp = api.reverse_contribution(posted["id"], make_custodian_headers())
        validate_error(
            resp, ApiErrorId.ERR_REVERSE_WINDOW_CLOSED.value, expected_status=409
        )
        # Status remains POSTED.
        get_resp = api.get_contribution(posted["id"], make_custodian_headers())
        cur = validate_success(get_resp, expected_status=200)
        assert cur["status"] == "POSTED"
