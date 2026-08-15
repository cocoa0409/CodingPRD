"""Warranty claims: provisional vs final liability, admissibility window boundaries."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_warranty_claim_payload,
    file_warranty_claim,
    get_success_data,
    make_customer_headers,
    make_qa_headers,
    set_clock,
    setup_commissioned_job,
    validate_error,
    validate_success,
)

QA_USER = "qa-900"


def _commissioned_ctx(api, **overrides):
    """Commissioned single-panel job; panel commissioned at 2026-10-01T09:00:00Z."""
    kwargs = dict(
        job_number="J-WC", quoted_price_cents=900000, warranty_months=12,
        panel_tag="P-WC", design_engineer_id="de-wc", qa_user_id=QA_USER,
        technician_id="tt-wc", engineer_id="fe-wc", labor_hours=8,
    )
    kwargs.update(overrides)
    return setup_commissioned_job(**kwargs)


class TestProvisionalVsFinal:
    def _setup_late_claim(self, api):
        """20h claim filed 226 days after commissioning under a 12-month warranty."""
        ctx = _commissioned_ctx(
            api, company_name="Acme Foods", site_state_code="OR",
            warranty_labor_tier="TIER_REGIONAL", job_number="J-1001",
            panel_tag="MCC-01", design_engineer_id="de-001",
            qa_user_id="qa-900", technician_id="tt-100", engineer_id="fe-001",
        )
        # 226 days after commissioning: months_in_service == 7 (floor(226/30)).
        set_clock("2027-05-15T00:00:00Z")
        claim = file_warranty_claim(
            ctx["job"]["id"], ctx["panel"]["id"], ctx["customer"]["id"],
            defect_description="PLC interlock logic drops conveyor permissive",
            claimed_labor_hours=20,
        )
        return ctx, claim

    def test_warranty_provisional_liability_at_triage(self, api):
        """PRD §3.9: "The **provisional variant**, used at triage, is a conservative
        worst-case accrual: liability is the minimum of the subtotal and a cap of
        `500000` cents; no age-decay halving and no deductible subtraction are
        applied."
        PRD §3.9: "The base labor rate is selected by tier: `9500` cents per hour for
        `TIER_LOCAL`, `14500` cents per hour for `TIER_REGIONAL`, and `21000` cents
        per hour for `TIER_NATIONAL`." and "A flat diagnostic parts allowance of
        `25000` cents is added."

        Design: Difficulty/dual_variant_calc/warranty_liability_provisional_vs_final_late_claim
        """
        _ctx, claim = self._setup_late_claim(api)
        triaged = validate_success(
            api.triage_warranty_claim(claim["id"], make_qa_headers(QA_USER)), 200
        )
        assert triaged["status"] == "TRIAGED"
        # min(20 * 14500 + 25000, 500000) = 315000; no decay, no deductible.
        assert triaged["provisional_liability_cents"] == 315000, (
            f"provisional = min(290000 + 25000, 500000), got "
            f"{triaged['provisional_liability_cents']}"
        )

    def test_warranty_final_liability_and_delta_at_acceptance(self, api, pm_headers):
        """PRD §3.9: "The **final variant**, used at acceptance, applies both
        adjustments: first, if twice the months in service exceeds the job's
        `warranty_months` — that is, the claim was filed after half the warranty term
        has elapsed — the labor component is halved (rounded half-up to integer
        cents) and the subtotal is recomputed as halved labor plus the parts
        allowance; then the liability is the minimum of that subtotal and the
        `500000`-cent cap; finally the customer absorbs the first `10000` cents of
        every adjudicated claim, so the deductible is subtracted from the liability
        with the result floored at zero."
        PRD §3.9: "Acceptance by the `QAManager` computes `final_liability_cents`
        using the final variant of the warranty-liability rule, writes
        `liability_delta_cents` as the final liability minus the provisional
        liability — the reconciliation entry for the accrual ledger — and transitions
        the claim to `ACCEPTED`."

        Design: Difficulty/dual_variant_calc/warranty_liability_provisional_vs_final_late_claim
        """
        _ctx, claim = self._setup_late_claim(api)
        get_success_data(api.triage_warranty_claim(claim["id"], make_qa_headers(QA_USER)), 200)
        accepted = validate_success(
            api.accept_warranty_claim(claim["id"], make_qa_headers(QA_USER)), 200
        )
        assert accepted["status"] == "ACCEPTED"
        # months 7 -> 7*2=14 > 12: labor halved to 145000; + parts 25000; - deductible 10000.
        assert accepted["final_liability_cents"] == 160000, (
            f"final = min(145000 + 25000, 500000) - 10000, got "
            f"{accepted['final_liability_cents']}"
        )
        assert accepted["liability_delta_cents"] == -155000, (
            f"delta = 160000 - 315000, got {accepted['liability_delta_cents']}"
        )
        reread = validate_success(api.get_warranty_claim(claim["id"], pm_headers), 200)
        assert reread["final_liability_cents"] == 160000
        assert reread["liability_delta_cents"] == -155000


class TestFilingBoundary:
    def _setup_commissioned_at_boundary(self, api):
        """Job commissioned 2026-10-01T09:00:00Z, warranty 12 months ->
        warranty_expires_at 2027-10-01T09:00:00Z."""
        return _commissioned_ctx(
            api, company_name="Nu Frozen", site_state_code="MN",
            job_number="J-9102", panel_tag="P-E1", design_engineer_id="de-010",
            qa_user_id="qa-907", technician_id="tt-400", engineer_id="fe-030",
            labor_hours=4,
        )

    def test_claim_filed_at_exact_expiry_succeeds(self, api):
        """PRD §3.9: "Filing or later triaging against a job whose
        `warranty_expires_at` is null (not yet commissioned) or already past is
        rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422); concretely, `filed_at` must
        be less than or equal to `warranty_expires_at`."

        Design: Difficulty/boundary_precision_check/warranty_filed_exactly_at_expiry_boundary
        """
        ctx = self._setup_commissioned_at_boundary(api)
        set_clock("2027-10-01T09:00:00Z")  # exactly warranty_expires_at
        claim = file_warranty_claim(
            ctx["job"]["id"], ctx["panel"]["id"], ctx["customer"]["id"],
            defect_description="interlock timing defect at boundary",
            claimed_labor_hours=2,
        )
        assert claim["status"] == "FILED", (
            "filed_at == warranty_expires_at satisfies the inclusive <= bound"
        )

    def test_claim_filed_one_second_after_expiry_rejected(self, api):
        """PRD §3.9: "Filing or later triaging against a job whose
        `warranty_expires_at` is null (not yet commissioned) or already past is
        rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422); concretely, `filed_at` must
        be less than or equal to `warranty_expires_at`."

        Design: Difficulty/boundary_precision_check/warranty_filed_exactly_at_expiry_boundary
        """
        ctx = self._setup_commissioned_at_boundary(api)
        set_clock("2027-10-01T09:00:01Z")  # one second past warranty_expires_at
        resp = api.create_warranty_claim(
            ctx["job"]["id"],
            create_warranty_claim_payload(
                ctx["panel"]["id"], defect_description="one second late",
                claimed_labor_hours=2,
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED, 422)


class TestTriageGatedByWarrantyWindow:
    def _setup_filed_in_window(self, api):
        """Claim filed at 2027-09-01, inside the window expiring 2027-10-01T09:00."""
        ctx = _commissioned_ctx(
            api, company_name="Omicron Steel", site_state_code="IL",
            job_number="J-9202", panel_tag="P-W2", design_engineer_id="de-012",
            qa_user_id="qa-909", technician_id="tt-600", engineer_id="fe-050",
            labor_hours=4,
        )
        set_clock("2027-09-01T00:00:00Z")
        claim = file_warranty_claim(
            ctx["job"]["id"], ctx["panel"]["id"], ctx["customer"]["id"],
            defect_description="timer drift", claimed_labor_hours=3,
        )
        return ctx, claim

    def test_triage_after_warranty_expiry_rejected(self, api, pm_headers):
        """PRD §3.9: "Triage re-checks the admissibility window (so a claim filed
        inside the window but triaged after expiry is rejected with
        `ERR_WARRANTY_EXPIRED`) and records `provisional_liability_cents` computed by
        the provisional variant of the warranty-liability rule".

        Design: Difficulty/cross_entity_state_dependency/warranty_triage_gated_by_job_warranty_window
        """
        _ctx, claim = self._setup_filed_in_window(api)
        set_clock("2027-10-02T00:00:00Z")  # past warranty_expires_at
        resp = api.triage_warranty_claim(claim["id"], make_qa_headers("qa-909"))
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED, 422)

        after = validate_success(api.get_warranty_claim(claim["id"], pm_headers), 200)
        assert after["status"] == "FILED", "rejected triage leaves the claim untouched"
        assert after.get("provisional_liability_cents") is None

    def test_triage_within_window_sets_provisional_liability(self, api):
        """PRD §3.9: "A `QAManager` triages a `FILED` claim, transitioning it to
        `TRIAGED`." and "The **provisional variant**, used at triage, is a
        conservative worst-case accrual: liability is the minimum of the subtotal and
        a cap of `500000` cents; no age-decay halving and no deductible subtraction
        are applied."

        Design: Difficulty/cross_entity_state_dependency/warranty_triage_gated_by_job_warranty_window
        """
        _ctx, claim = self._setup_filed_in_window(api)
        # Clock is still 2027-09-01 (in-window): triage succeeds.
        triaged = validate_success(
            api.triage_warranty_claim(claim["id"], make_qa_headers("qa-909")), 200
        )
        assert triaged["status"] == "TRIAGED"
        # Customer defaults to TIER_REGIONAL: min(3 * 14500 + 25000, 500000) = 68500.
        assert triaged["provisional_liability_cents"] == 68500, (
            f"provisional = min(43500 + 25000, 500000), got "
            f"{triaged['provisional_liability_cents']}"
        )
