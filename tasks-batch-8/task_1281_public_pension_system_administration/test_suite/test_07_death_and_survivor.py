"""Member death cascade and beneficiary / survivor claim processing."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_purchase,
    adjudicate_survivor_claim,
    assert_beneficiary,
    create_beneficiary,
    create_disability_app,
    create_member,
    create_purchase,
    decide_disability_app,
    file_survivor_claim,
    five_year_line_specs,
    get_purchase,
    list_payments_sorted,
    make_member_headers,
    make_survivor_claimant_headers,
    pay_installment,
    quote_purchase,
    record_death,
    set_clock,
    setup_fund_and_employer,
    setup_retiree_with_designation,
    setup_vested_member,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, APPROVER


def _setup_retired_via_disability_with_plan(api):
    """Member retired via NON_DUTY disability approval (benefit 275,000),
    then a PRIOR_SERVICE purchase opened afterwards and paid twice."""
    ctx = setup_vested_member(full_name="Cascade Carol")
    member = ctx["member"]
    app = create_disability_app(member["id"], "NON_DUTY")
    decide_disability_app(app["id"], "APPROVE", "reviewer-1")
    purchase = create_purchase(member["id"], "PRIOR_SERVICE",
                               "2005-01-01", "2006-12-31", 2.0,
                               filed_by_analyst=True)
    purchase = quote_purchase(purchase["id"])
    assert purchase["quoted_cost_cents"] == 2_640_000, (
        f"ACTUARIAL at age 60: 6,000,000 * 2.0 * 0.22 = 2,640,000, "
        f"got {purchase['quoted_cost_cents']}")
    purchase = accept_purchase(purchase["id"], member["id"], 12,
                               by_analyst=True)
    payments = list_payments_sorted(purchase["id"])
    purchase = pay_installment(purchase["id"], payments[0]["id"],
                               purchase["version"], by_analyst=True)
    purchase = pay_installment(purchase["id"], payments[1]["id"],
                               purchase["version"], by_analyst=True)
    return ctx, purchase, payments


class TestMemberDeathCascade:
    def test_death_cancels_plan_and_refunds_applied_payments(self, api):
        """PRD §3.7: "Every ServicePurchase of the member in `REQUESTED`,
        `QUOTED`, or `PLAN_ACTIVE` is cancelled, and each such cancellation of
        a plan-active purchase runs the refund cascade: its `APPLIED` payments
        become `REFUNDED`, `refunded_total_cents` is set to the sum of the
        applied amounts, and `balance_due_cents` zeroes."
        PRD §3.1: "Setting `deceased_at` records the member's death and moves
        the member to `DECEASED` from `ACTIVE`, `INACTIVE`, `RETIRED`, or
        `SUSPENDED_RTW`"

        Design: Difficulty/transitive_cascade/member_death_cascade_terminates_benefit_and_refunds_purchase
        """
        ctx, purchase, payments = \
            _setup_retired_via_disability_with_plan(api)
        member = ctx["member"]
        deceased = record_death(member["id"], "2026-08-01")
        assert deceased["status"] == "DECEASED"

        purchase_after = get_purchase(purchase["id"])
        assert purchase_after["status"] == "CANCELLED"
        assert purchase_after["balance_due_cents"] == 0
        assert purchase_after["refunded_total_cents"] == 440_000, (
            f"the two APPLIED installments (2 x 220,000) must be refunded, "
            f"got {purchase_after['refunded_total_cents']}")
        payments_after = list_payments_sorted(purchase["id"])
        assert payments_after[0]["status"] == "REFUNDED"
        assert payments_after[1]["status"] == "REFUNDED"
        assert all(p["status"] == "PENDING" for p in payments_after[2:])

    def test_death_terminates_benefit_and_plan_rejects_payments(self, api):
        """PRD §3.7: "Every Benefit of the member in `ACTIVE` or `SUSPENDED`
        moves to `TERMINATED`."
        PRD §3.4: "Payment is only possible while the purchase is in
        `PLAN_ACTIVE`; paying against a purchase in any other state is
        `ERR_PLAN_NOT_ACTIVE` (HTTP 409)"

        Design: Difficulty/transitive_cascade/member_death_cascade_terminates_benefit_and_refunds_purchase
        """
        ctx, purchase, payments = \
            _setup_retired_via_disability_with_plan(api)
        member = ctx["member"]
        benefits, _meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        benefit_id = benefits[0]["id"]

        record_death(member["id"], "2026-08-01")
        benefit = validate_success(api.get_benefit(benefit_id, ANALYST), 200)
        assert benefit["status"] == "TERMINATED"
        assert benefit["benefit_kind"] == "DISABILITY"

        version = get_purchase(purchase["id"])["version"]
        res = api.apply_payment(
            purchase["id"],
            {"payment_id": payments[2]["id"],
             "expected_purchase_version": version},
            ANALYST)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


class TestClaimRequiresBenefitTerminated:
    def test_claim_while_benefit_active_rejected(self, api):
        """PRD §3.8: "The member's benefit must be `TERMINATED`; filing while
        it is in any other state is `ERR_BENEFIT_NOT_TERMINATED` (HTTP 409)."
        PRD §3.8: "Filing is the SurvivorClaimant's act — `X-User-ID` must
        equal the Beneficiary designation's own `id`, else `ERR_FORBIDDEN`"

        Design: Difficulty/cross_entity_state_dependency/claim_requires_benefit_terminated
        """
        ctx = setup_retiree_with_designation(option_election="JOINT_100")
        designation = ctx["beneficiary"]
        res = api.file_claim(designation["id"],
                             make_survivor_claimant_headers(designation["id"]))
        validate_error(res, ApiErrorId.ERR_BENEFIT_NOT_TERMINATED)
        after = validate_success(
            api.list_member_beneficiaries(ctx["member"]["id"], ANALYST), 200)
        found = [b for b in after if b["id"] == designation["id"]][0]
        assert found["status"] == "DESIGNATED"
        assert found.get("claim_filed_at") is None

    def test_claim_after_death_terminates_benefit_succeeds(self, api):
        """PRD §3.8: "A successful filing moves the designation `DESIGNATED →
        CLAIM_FILED` and stamps `claim_filed_at`."
        PRD §3.7: "Every Benefit of the member in `ACTIVE` or `SUSPENDED`
        moves to `TERMINATED`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_benefit_terminated
        """
        ctx = setup_retiree_with_designation(option_election="JOINT_100")
        designation = ctx["beneficiary"]
        record_death(ctx["member"]["id"], "2026-08-01")
        filed = validate_success(
            api.file_claim(designation["id"],
                           make_survivor_claimant_headers(designation["id"])),
            200)
        assert_beneficiary(filed)
        assert filed["status"] == "CLAIM_FILED"
        assert filed.get("claim_filed_at") is not None


class TestClaimWindowsAndEntitlement:
    def test_claim_filed_after_365_day_deadline_rejected(self, api):
        """PRD §3.8: "And the claim must be filed within 365 days of the
        member's `deceased_at`, measured against the logical clock; later
        filings are `ERR_CLAIM_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/claim_filed_after_deadline_returns_error
        """
        ctx = setup_retiree_with_designation(
            option_election="JOINT_100",
            set_clock_to="2024-08-01T00:00:00Z",
            date_of_birth="1964-01-01",
            line_specs_fn=five_year_line_specs)
        designation = ctx["beneficiary"]
        set_clock("2025-01-10T00:00:00Z")
        record_death(ctx["member"]["id"], "2025-01-10")
        set_clock("2026-01-11T00:00:00Z")  # 366 days after death
        res = api.file_claim(designation["id"],
                             make_survivor_claimant_headers(designation["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_DEADLINE_PASSED)
        found = [b for b in validate_success(
            api.list_member_beneficiaries(ctx["member"]["id"], ANALYST),
            200) if b["id"] == designation["id"]][0]
        assert found["status"] == "DESIGNATED"
        assert found.get("claim_filed_at") is None

    def test_claim_on_revoked_designation_rejected(self, api):
        """PRD §3.8: "The designation must be live: filing on a `REVOKED`
        designation is `ERR_DESIGNATION_REVOKED` (HTTP 422)."

        Design: Corner/validations/file_claim_on_revoked_designation_returns_error
        """
        ctx = setup_retiree_with_designation(
            option_election="JOINT_100",
            set_clock_to="2024-08-01T00:00:00Z",
            date_of_birth="1964-01-01",
            line_specs_fn=five_year_line_specs)
        designation = ctx["beneficiary"]
        revoked = validate_success(api.revoke_beneficiary(
            designation["id"], make_member_headers(ctx["member"]["id"])), 200)
        assert revoked["status"] == "REVOKED"
        set_clock("2025-01-10T00:00:00Z")
        record_death(ctx["member"]["id"], "2025-01-10")
        res = api.file_claim(designation["id"],
                             make_survivor_claimant_headers(designation["id"]))
        validate_error(res, ApiErrorId.ERR_DESIGNATION_REVOKED)
        found = [b for b in validate_success(
            api.list_member_beneficiaries(ctx["member"]["id"], ANALYST),
            200) if b["id"] == designation["id"]][0]
        assert found["status"] == "REVOKED"

    def test_single_life_election_bars_survivor_claim(self, api):
        """PRD §3.8: "The originating retirement application's
        `option_election` must entitle survivors — a claim under a
        `SINGLE_LIFE` election is `ERR_NO_SURVIVOR_ENTITLEMENT` (HTTP 422)."

        Design: Corner/validations/file_claim_single_life_returns_no_survivor_entitlement
        """
        ctx = setup_retiree_with_designation(
            option_election="SINGLE_LIFE",
            set_clock_to="2024-08-01T00:00:00Z",
            date_of_birth="1964-01-01",
            line_specs_fn=five_year_line_specs)
        designation = ctx["beneficiary"]
        set_clock("2025-01-10T00:00:00Z")
        record_death(ctx["member"]["id"], "2025-01-10")
        res = api.file_claim(designation["id"],
                             make_survivor_claimant_headers(designation["id"]))
        validate_error(res, ApiErrorId.ERR_NO_SURVIVOR_ENTITLEMENT)


class TestSurvivorClaimHappyPath:
    def test_joint_100_claim_approved_at_full_amount(self, api):
        """PRD §3.8: "On approval the survivor benefit is computed: the
        survivor percentage is 0.50 when the originating election was
        `JOINT_50` and 1.00 when it was `JOINT_100`, and
        `survivor_monthly_cents` is the member's terminated benefit's
        `monthly_amount_cents` — its COLA-adjusted current amount at
        termination — times that percentage, rounded half-up to whole cents.
        The designation moves to `PAYABLE`."
        PRD §3.5: "`JOINT_100` uses 0.90 when `age_diff` is at most 10 and
        0.82 otherwise."

        Design: Corner/endpoints/survivor_claim_happy_path_payable_amount
        """
        ctx = setup_retiree_with_designation(option_election="JOINT_100",
                                             beneficiary_dob="1968-01-01")
        benefit = ctx["benefit"]
        assert benefit["monthly_amount_cents"] == 42_075, (
            f"JOINT_100 with age_diff 2: 46,750 * 0.90 = 42,075, "
            f"got {benefit['monthly_amount_cents']}")
        designation = ctx["beneficiary"]
        record_death(ctx["member"]["id"], "2026-08-01")
        terminated = validate_success(api.get_benefit(benefit["id"], ANALYST),
                                      200)
        assert terminated["status"] == "TERMINATED"
        validate_success(
            api.file_claim(designation["id"],
                           make_survivor_claimant_headers(designation["id"])),
            200)
        payable = adjudicate_survivor_claim(designation["id"], "APPROVE")
        assert_beneficiary(payable)
        assert payable["status"] == "PAYABLE"
        assert payable["survivor_monthly_cents"] == 42_075, (
            f"JOINT_100 survivor pct 1.00 x 42,075 = 42,075, "
            f"got {payable['survivor_monthly_cents']}")


class TestRevocationTerminal:
    def test_revoke_revoked_beneficiary_returns_invalid_state(self, api):
        """PRD §3.8: "Revocation moves it `DESIGNATED → REVOKED` and is
        available only while the member is not `DECEASED` — designations
        freeze at death (`ERR_MEMBER_DECEASED`)."
        PRD §3.8: "`REVOKED`, `PAYABLE`, and `DENIED` are all terminal for a
        designation."

        Design: Corner/state_machines/revoke_revoked_beneficiary_returns_invalid_state
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Revoke Rhonda")
        designation = create_beneficiary(member["id"], full_name="Kid Ken",
                                         relationship="child",
                                         date_of_birth="1995-01-01")
        assert designation["status"] == "DESIGNATED"
        revoked = validate_success(api.revoke_beneficiary(
            designation["id"], make_member_headers(member["id"])), 200)
        assert revoked["status"] == "REVOKED"
        res = api.revoke_beneficiary(designation["id"],
                                     make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
