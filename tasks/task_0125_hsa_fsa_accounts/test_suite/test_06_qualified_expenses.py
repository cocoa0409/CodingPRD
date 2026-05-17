"""QualifiedExpense catalog — PRD §3.4.

Coverage targets:
- Each category enum value can be seeded.
- requires_dependent: claim creation/submit enforces dependent_id when
  the expense's flag is true.
- eligible_account_types must include Account.account_type at /submit.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_qualified_expense,
    create_claim,
    create_dependent,
    create_qualified_expense_payload,
    iso_datetime_utc,
    seed_qualified_expense,
    setup_funded_plan_year,
    setup_submitted_claim,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Catalog seeding — PRD §3.4
# ===========================================================================
class TestQualifiedExpenseSeed:

    @pytest.mark.parametrize(
        "category",
        ["MEDICAL", "VISION", "DENTAL", "OTC_MEDICATION",
         "DEPENDENT_CARE", "NON_QUALIFIED"],
    )
    def test_each_category_accepted(
        self, api, plan_admin_headers, category,
    ):
        """PRD §3.4: "each row carrying a unique code, a category (one
        of MEDICAL, VISION, DENTAL, OTC_MEDICATION, DEPENDENT_CARE, or
        NON_QUALIFIED)".

        Claim: each category enum value is accepted on POST
        /qualified-expenses.
        """
        payload = create_qualified_expense_payload(category=category)
        resp = api.create_qualified_expense(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_qualified_expense(data)
        assert data["category"] == category


# ===========================================================================
# Eligibility — PRD §3.5
# ===========================================================================
class TestExpenseEligibility:

    def test_submit_rejected_when_account_type_not_eligible(self, api):
        """PRD §3.5: "a QualifiedExpense with the cited expense_code
        exists and its eligible_account_types includes the account's
        account_type (otherwise ERR_EXPENSE_NOT_ELIGIBLE)".

        Claim: submitting a claim where the expense's
        eligible_account_types does NOT include the account's
        account_type -> ERR_EXPENSE_NOT_ELIGIBLE.
        """
        # Account is HSA; expense allows only HEALTH_FSA.
        holder, acct, py = setup_funded_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE", calendar_year=2025,
            contribution_cents=100_000,
        )
        qe = seed_qualified_expense(
            category="MEDICAL",
            eligible_account_types=["HEALTH_FSA"],
            requires_dependent=False,
        )
        service_date = iso_datetime_utc(2025, 6, 15)
        # Creation also enforces ERR_EXPENSE_NOT_ELIGIBLE per PRD §3.5:
        # "The same expense-eligibility and dependent-required checks
        # also run at claim creation time."
        from test_helpers import (
            create_claim_payload,
            make_account_holder_headers,
        )
        payload = create_claim_payload(
            service_date=service_date,
            expense_code=qe["code"],
            amount_cents=10_000,
        )
        resp = api.create_claim(
            acct["id"], payload,
            make_account_holder_headers(holder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXPENSE_NOT_ELIGIBLE.value)


# ===========================================================================
# Dependent requirement — PRD §3.5
# ===========================================================================
class TestDependentRequirement:

    def test_dependent_required_when_flag_set(self, api):
        """PRD §3.5: "if the cited expense's requires_dependent is
        true ... the request supplied a non-null dependent_id resolving
        to a Dependent owned by the same AccountHolder
        (ERR_DEPENDENT_REQUIRED if not)".

        Claim: creating a DCFSA claim against a requires_dependent=true
        expense WITHOUT dependent_id -> ERR_DEPENDENT_REQUIRED.
        """
        from test_helpers import (
            create_claim_payload,
            make_account_holder_headers,
        )

        holder, acct, py = setup_funded_plan_year(
            account_type="DEPENDENT_CARE_FSA",
            coverage_tier=None, year_end_policy="NONE",
            calendar_year=2025, contribution_cents=100_000,
        )
        qe = seed_qualified_expense(
            category="DEPENDENT_CARE",
            eligible_account_types=["DEPENDENT_CARE_FSA"],
            requires_dependent=True,
        )
        service_date = iso_datetime_utc(2025, 6, 15)
        payload = create_claim_payload(
            service_date=service_date,
            expense_code=qe["code"],
            amount_cents=10_000,
            # dependent_id omitted
        )
        resp = api.create_claim(
            acct["id"], payload,
            make_account_holder_headers(holder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_REQUIRED.value)
