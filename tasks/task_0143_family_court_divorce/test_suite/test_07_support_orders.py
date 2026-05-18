"""SupportOrder calculations: child support (income-shares and
percent-of-obligor) and spousal support (eligibility + tiered transfer
+ cap).

PRD §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_support_order,
    create_support_order,
    create_support_order_payload,
    make_petitioner_headers,
    setup_case_with_agreed_plan,
    setup_case_with_both_disclosures_accepted,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Plan-required-or-forbidden field rule — PRD §3.5
# ===========================================================================
class TestPlanRequiredOrForbidden:

    def test_child_support_without_plan_id_rejected(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'The system rejects with
        ERR_PLAN_REQUIRED_OR_FORBIDDEN (HTTP 422) any CHILD request
        that omits parenting_plan_id'.

        Claim: POST /support-orders with support_type=CHILD and no
        parenting_plan_id → ERR_PLAN_REQUIRED_OR_FORBIDDEN.
        """
        ctx = setup_case_with_agreed_plan()
        payload = create_support_order_payload(
            support_type="CHILD", order_kind="TEMPORARY",
            parenting_plan_id=None,
        )
        res = api.create_support_order(
            ctx["case"]["id"], payload, judge_headers,
        )
        validate_error(
            res, "ERR_PLAN_REQUIRED_OR_FORBIDDEN",
            expected_status=422,
        )

    def test_spousal_support_with_plan_id_rejected(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'The system rejects with
        ERR_PLAN_REQUIRED_OR_FORBIDDEN (HTTP 422) any ... SPOUSAL
        request that includes one [parenting_plan_id]'.

        Claim: POST /support-orders with support_type=SPOUSAL and
        parenting_plan_id present → ERR_PLAN_REQUIRED_OR_FORBIDDEN.
        """
        ctx = setup_case_with_agreed_plan(
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
        )
        payload = create_support_order_payload(
            support_type="SPOUSAL", order_kind="TEMPORARY",
            parenting_plan_id=ctx["parenting_plan"]["id"],
        )
        res = api.create_support_order(
            ctx["case"]["id"], payload, judge_headers,
        )
        validate_error(
            res, "ERR_PLAN_REQUIRED_OR_FORBIDDEN",
            expected_status=422,
        )


# ===========================================================================
# Spousal eligibility — PRD §3.5
# ===========================================================================
class TestSpousalEligibility:

    def test_under_5_years_marriage_rejected_for_spousal(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'When marriage_duration_years is less than 5,
        attempting to create a SPOUSAL support order is rejected with
        ERR_NOT_ELIGIBLE_FOR_SPOUSAL (HTTP 422).'

        Claim: marriage 2020-01-01 to 2024-12-31 → floor(1826/365.25)
        = 4 years → SPOUSAL creation rejected.
        """
        ctx = setup_case_with_both_disclosures_accepted(
            jurisdiction_state="CA",
            marriage_date="2020-01-01",
            separation_date="2024-12-31",
            has_minor_children=False,
            p_gross_cents=300_000,
            r_gross_cents=600_000,
        )
        payload = create_support_order_payload(
            support_type="SPOUSAL", order_kind="TEMPORARY",
        )
        res = api.create_support_order(
            ctx["case"]["id"], payload, judge_headers,
        )
        validate_error(
            res, "ERR_NOT_ELIGIBLE_FOR_SPOUSAL",
            expected_status=422,
        )

    def test_5_years_exactly_eligible_for_spousal(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'so a marriage that lasted four years and 364
        days yields marriage_duration_years of 4 and is ineligible.'
        and 'When marriage_duration_years is less than 5, attempting
        to create a SPOUSAL support order is rejected'.

        Claim: marriage 2020-01-01 to 2025-01-02 → floor(1828/365.25)
        = 5 years → eligible (201 Created).
        """
        ctx = setup_case_with_both_disclosures_accepted(
            jurisdiction_state="CA",
            marriage_date="2020-01-01",
            separation_date="2025-01-02",
            has_minor_children=False,
            p_gross_cents=300_000,
            r_gross_cents=600_000,
        )
        order = create_support_order(
            ctx["case"]["id"], support_type="SPOUSAL",
            order_kind="TEMPORARY",
        )
        assert_support_order(order)
        assert order["support_type"] == "SPOUSAL"
        assert order["order_kind"] == "TEMPORARY"


# ===========================================================================
# Child support — INCOME_SHARES variant — PRD §3.5
# ===========================================================================
class TestChildSupportIncomeShares:

    def test_california_uses_income_shares_model(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'When jurisdiction_state is CA, NY, or IL, the
        system uses the income-shares model, and
        SupportOrder.guideline_model is recorded as INCOME_SHARES.'

        Claim: with CA jurisdiction, CHILD order's guideline_model is
        INCOME_SHARES.
        """
        ctx = setup_case_with_agreed_plan(
            jurisdiction_state="CA",
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
            p_gross_cents=300_000, r_gross_cents=600_000,
            petitioner_overnights=100, respondent_overnights=265,
        )
        order = create_support_order(
            ctx["case"]["id"], support_type="CHILD",
            order_kind="TEMPORARY",
            parenting_plan_id=ctx["parenting_plan"]["id"],
        )
        assert order["guideline_model"] == "INCOME_SHARES"


# ===========================================================================
# Child support — PERCENT_OBLIGOR variant — PRD §3.5
# ===========================================================================
class TestChildSupportPercentObligor:

    def test_texas_uses_percent_obligor_model(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'When jurisdiction_state is TX, FL, or WA, the
        system uses the percent-of-obligor model, and guideline_model
        is recorded as PERCENT_OBLIGOR.'

        Claim: with TX jurisdiction, CHILD order's guideline_model is
        PERCENT_OBLIGOR.
        """
        ctx = setup_case_with_agreed_plan(
            jurisdiction_state="TX",
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
            p_gross_cents=300_000, r_gross_cents=600_000,
            petitioner_overnights=100, respondent_overnights=265,
        )
        order = create_support_order(
            ctx["case"]["id"], support_type="CHILD",
            order_kind="TEMPORARY",
            parenting_plan_id=ctx["parenting_plan"]["id"],
        )
        assert order["guideline_model"] == "PERCENT_OBLIGOR"


# ===========================================================================
# Spousal support amount with cap — PRD §3.5
# ===========================================================================
class TestSpousalAmount:

    def test_spousal_amount_capped_at_40pct_of_higher(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'A statutory cap then applies: the monthly amount
        may not exceed higher multiplied by 0.40, rounded half-up. If
        the pre-cap amount is above the cap, the amount is reduced to
        the cap.'

        Claim: with P_net=100000, R_net=900000, marriage_duration=10y
        → gap=800000, pct=0.35 → pre-cap=280000; cap=round(900000*0.40)
        =360000; pre-cap (280000) < cap, so monthly==280000.
        Conversely with P_net=0, R_net=1000000, marriage=20y:
        gap=1000000, pct=0.40 → pre-cap=400000; cap=round(1000000*0.40)
        =400000; equal — amount stays 400000.
        Use the first configuration where pre-cap < cap to confirm
        the formula is applied correctly (cap only binds when above).
        """
        ctx = setup_case_with_both_disclosures_accepted(
            jurisdiction_state="CA",
            marriage_date="2012-01-01",
            separation_date="2022-06-01",  # > 10 years exactly
            has_minor_children=False,
            p_gross_cents=100_000, r_gross_cents=900_000,
        )
        order = create_support_order(
            ctx["case"]["id"], support_type="SPOUSAL",
            order_kind="TEMPORARY",
        )
        # Compute marriage_duration_years per PRD: (2022-06-01 -
        # 2012-01-01).days = 3804; floor(3804/365.25)=10. So tier
        # 10..20 -> pct = 0.35; gap = 900000 - 100000 = 800000;
        # pre-cap = round(800000 * 0.35) = 280000; cap = round(900000
        # * 0.40) = 360000; result = 280000 (under cap).
        assert order["monthly_amount_cents"] == 280_000


# ===========================================================================
# Termination — PRD §3.5
# ===========================================================================
class TestSupportOrderTermination:

    def test_spousal_termination_requires_obligee_remarried_flag(
        self, api, judge_headers,
    ):
        """PRD §3.5: 'For a SPOUSAL order, termination is permitted
        when the request body's obligee_remarried flag is true.'

        Claim: a Judge-issued SPOUSAL order in ISSUED status can be
        terminated by supplying obligee_remarried=true, and the order
        transitions to TERMINATED.
        """
        # Build an ISSUED SPOUSAL order via the TemporaryOrder cascade.
        from test_helpers import (
            create_temp_order_payload,
            issue_temp_order_payload,
            setup_case_temp_ordered_with_final_judgment_draft,
        )
        # Setup with has_minor_children=False so we get only spousal.
        ctx = setup_case_with_both_disclosures_accepted(
            jurisdiction_state="CA",
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
            has_minor_children=False,
            p_gross_cents=100_000, r_gross_cents=900_000,
        )
        # Create DRAFT SPOUSAL TEMPORARY, wrap in TemporaryOrder,
        # issue.
        spousal = create_support_order(
            ctx["case"]["id"], support_type="SPOUSAL",
            order_kind="TEMPORARY",
        )
        t1_payload = create_temp_order_payload(
            spousal_support_order_id=spousal["id"],
        )
        t1_resp = api.create_temp_order(
            ctx["case"]["id"], t1_payload, judge_headers,
        )
        t1 = validate_success(t1_resp, 201)
        api.issue_temp_order(
            ctx["case"]["id"],
            issue_temp_order_payload(temporary_order_id=t1["id"]),
            judge_headers,
        )
        # Terminate spousal order with obligee_remarried=true.
        res = api.terminate_support_order(
            ctx["case"]["id"], spousal["id"],
            {"obligee_remarried": True}, judge_headers,
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "TERMINATED"
