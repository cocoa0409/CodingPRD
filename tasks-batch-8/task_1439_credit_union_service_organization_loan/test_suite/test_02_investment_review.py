"""CUSO investment cap checks and approve/reject state rules (PRD §2.7, §3.2)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_investor, submit_investment, approve_investment,
    make_regulator_headers, TEST_USERS,
)

REG = TEST_USERS["regulator_headers"]


def _investor_50bn():
    """Investor CU: total_assets 50,000,000,000 (base cap 500,000,000; extended cap
    1,500,000,000), net_worth 5,000,000,000 (ratio 0.10)."""
    return setup_investor(total_assets_cents=50_000_000_000, net_worth_cents=5_000_000_000)


class TestInvestmentCapTieredBranching:
    def test_approvals_up_to_base_cap_allowed(self, api):
        """PRD §3.2: "If the aggregate does not exceed the base cap, approval is permitted under either basis."
        PRD §3.2: "On approval the server stamps `post_approval_aggregate_cents` with the credit union's aggregate approved investment including this one, records the clock time in `decided_at`, moves the investment to `APPROVED`, and recomputes the CUSO's `total_approved_investment_cents`."

        Design: Difficulty/combinatorial_formula/investment_cap_tiered_branching
        """
        ctx = _investor_50bn()
        inv_id, cuso_id = ctx["investor"]["id"], ctx["cuso"]["id"]
        i1 = submit_investment(inv_id, cuso_id, 490_000_000)
        i1_approved = approve_investment(i1["id"])
        assert i1_approved["status"] == "APPROVED"

        i2 = submit_investment(inv_id, cuso_id, 10_000_000)
        res = api.approve_cuso_investment(i2["id"], REG)
        i2_approved = validate_success(res, 200)
        assert i2_approved["status"] == "APPROVED"
        assert i2_approved["post_approval_aggregate_cents"] == 500_000_000

    def test_enhanced_basis_within_extended_cap_allowed(self, api):
        """PRD §3.2: "Otherwise, approval is permitted only when all of the following hold: the candidate's `approval_basis` is `ENHANCED`, the credit union's `net_worth_ratio` is at least 0.07, the target CUSO's `open_critical_finding_count` is zero, and the aggregate does not exceed the extended cap."

        Design: Difficulty/combinatorial_formula/investment_cap_tiered_branching
        """
        ctx = _investor_50bn()
        inv_id, cuso_id = ctx["investor"]["id"], ctx["cuso"]["id"]
        approve_investment(submit_investment(inv_id, cuso_id, 490_000_000)["id"])
        approve_investment(submit_investment(inv_id, cuso_id, 10_000_000)["id"])

        i3 = submit_investment(inv_id, cuso_id, 600_000_000, approval_basis="ENHANCED")
        res = api.approve_cuso_investment(i3["id"], REG)
        i3_approved = validate_success(res, 200)
        assert i3_approved["status"] == "APPROVED"
        assert i3_approved["post_approval_aggregate_cents"] == 1_100_000_000

    def test_aggregate_over_extended_cap_rejected_even_enhanced(self, api):
        """PRD §3.2: "and an aggregate above the extended cap is rejected with `ERR_INVESTMENT_CAP_EXCEEDED` regardless of basis."

        Design: Difficulty/combinatorial_formula/investment_cap_tiered_branching
        """
        ctx = _investor_50bn()
        inv_id, cuso_id = ctx["investor"]["id"], ctx["cuso"]["id"]
        approve_investment(submit_investment(inv_id, cuso_id, 490_000_000)["id"])
        approve_investment(submit_investment(inv_id, cuso_id, 10_000_000)["id"])
        approve_investment(submit_investment(inv_id, cuso_id, 600_000_000,
                                             approval_basis="ENHANCED")["id"])

        i4 = submit_investment(inv_id, cuso_id, 400_000_001, approval_basis="ENHANCED")
        res = api.approve_cuso_investment(i4["id"], REG)
        validate_error(res, ApiErrorId.ERR_INVESTMENT_CAP_EXCEEDED)

    def test_standard_basis_over_base_cap_rejected(self, api):
        """PRD §3.2: "When a `STANDARD` candidate breaches the base cap the decision is rejected with `ERR_INVESTMENT_CAP_EXCEEDED`;"

        Design: Difficulty/combinatorial_formula/investment_cap_tiered_branching
        """
        ctx = _investor_50bn()
        inv_id, cuso_id = ctx["investor"]["id"], ctx["cuso"]["id"]
        approve_investment(submit_investment(inv_id, cuso_id, 490_000_000)["id"])
        approve_investment(submit_investment(inv_id, cuso_id, 10_000_000)["id"])
        approve_investment(submit_investment(inv_id, cuso_id, 600_000_000,
                                             approval_basis="ENHANCED")["id"])

        i5 = submit_investment(inv_id, cuso_id, 1)
        res = api.approve_cuso_investment(i5["id"], REG)
        validate_error(res, ApiErrorId.ERR_INVESTMENT_CAP_EXCEEDED)


class TestInvestmentCapEqualityBoundary:
    def _setup_at_40m(self, api):
        """Investor with total_assets 5,000,000,000 (base cap exactly 50,000,000)
        and one APPROVED investment of 40,000,000."""
        ctx = setup_investor(total_assets_cents=5_000_000_000, net_worth_cents=500_000_000)
        inv_id, cuso_id = ctx["investor"]["id"], ctx["cuso"]["id"]
        approve_investment(submit_investment(inv_id, cuso_id, 40_000_000)["id"])
        return inv_id, cuso_id

    def test_aggregate_equal_to_base_cap_allowed(self, api):
        """PRD §3.2: "An aggregate exactly equal to the applicable cap is allowed — rejection requires the aggregate to strictly exceed the cap."

        Design: Difficulty/boundary_precision_check/investment_cap_equality_boundary
        """
        inv_id, cuso_id = self._setup_at_40m(api)
        i2 = submit_investment(inv_id, cuso_id, 10_000_000)
        res = api.approve_cuso_investment(i2["id"], REG)
        approved = validate_success(res, 200)
        assert approved["status"] == "APPROVED"
        assert approved["post_approval_aggregate_cents"] == 50_000_000

    def test_aggregate_one_cent_over_base_cap_rejected(self, api):
        """PRD §3.2: "An aggregate exactly equal to the applicable cap is allowed — rejection requires the aggregate to strictly exceed the cap."
        PRD §3.2: "When a `STANDARD` candidate breaches the base cap the decision is rejected with `ERR_INVESTMENT_CAP_EXCEEDED`;"

        Design: Difficulty/boundary_precision_check/investment_cap_equality_boundary
        """
        inv_id, cuso_id = self._setup_at_40m(api)
        i2 = submit_investment(inv_id, cuso_id, 10_000_000)
        validate_success(api.approve_cuso_investment(i2["id"], REG), 200)

        i3 = submit_investment(inv_id, cuso_id, 1)
        res = api.approve_cuso_investment(i3["id"], REG)
        validate_error(res, ApiErrorId.ERR_INVESTMENT_CAP_EXCEEDED)
        after = validate_success(api.get_cuso_investment(i3["id"], REG), 200)
        assert after["status"] == "PENDING_REVIEW"


class TestStateBeatsSafetyOnInvestmentApprove:
    def _setup_rejected_over_cap(self, api):
        """Investor total_assets 1,000,000,000 (base cap 10,000,000); I1 8,000,000
        APPROVED; I2 5,000,000 still PENDING_REVIEW (approve would breach the cap)."""
        ctx = setup_investor(total_assets_cents=1_000_000_000, net_worth_cents=100_000_000)
        inv_id, cuso_id = ctx["investor"]["id"], ctx["cuso"]["id"]
        approve_investment(submit_investment(inv_id, cuso_id, 8_000_000)["id"])
        i2 = submit_investment(inv_id, cuso_id, 5_000_000)
        return i2

    def test_over_cap_approve_rejected_with_cap_error(self, api):
        """PRD §3.2: "When a `STANDARD` candidate breaches the base cap the decision is rejected with `ERR_INVESTMENT_CAP_EXCEEDED`;"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_investment_approve
        """
        i2 = self._setup_rejected_over_cap(api)
        res = api.approve_cuso_investment(i2["id"], REG)
        validate_error(res, ApiErrorId.ERR_INVESTMENT_CAP_EXCEEDED)
        after = validate_success(api.get_cuso_investment(i2["id"], REG), 200)
        assert after["status"] == "PENDING_REVIEW"

    def test_state_error_beats_cap_error_on_rejected_investment(self, api):
        """PRD §2.7: "The server evaluates request validation in a fixed priority order, so that when several checks would fail, the caller always sees the same error."
        PRD §2.7: "7. **State legality** — the target resource is in a state from which the requested transition exists, else `ERR_INVALID_STATE`. This check applies to all action endpoints."
        PRD §3.2: "Approving or rejecting an investment that is not in `PENDING_REVIEW` is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_investment_approve
        """
        i2 = self._setup_rejected_over_cap(api)
        validate_error(api.approve_cuso_investment(i2["id"], REG),
                       ApiErrorId.ERR_INVESTMENT_CAP_EXCEEDED)
        validate_success(api.reject_cuso_investment(i2["id"], REG), 200)

        res = api.approve_cuso_investment(i2["id"], REG)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestEnhancedBasisEligibility:
    def test_enhanced_basis_low_net_worth_ratio_rejected(self, api):
        """PRD §3.2: "Otherwise, approval is permitted only when all of the following hold: the candidate's `approval_basis` is `ENHANCED`, the credit union's `net_worth_ratio` is at least 0.07, the target CUSO's `open_critical_finding_count` is zero, and the aggregate does not exceed the extended cap."
        PRD §3.2: "when an `ENHANCED` candidate's eligibility conditions fail the rejection is `ERR_ENHANCED_BASIS_NOT_ELIGIBLE`"

        Design: Corner/errors/enhanced_basis_ineligible_low_ratio
        """
        # total_assets 10,000,000,000 -> base cap 100,000,000, extended 300,000,000;
        # net_worth 600,000,000 -> ratio 0.06 < 0.07.
        ctx = setup_investor(total_assets_cents=10_000_000_000, net_worth_cents=600_000_000)
        inv = submit_investment(ctx["investor"]["id"], ctx["cuso"]["id"],
                                150_000_000, approval_basis="ENHANCED")
        res = api.approve_cuso_investment(inv["id"], REG)
        validate_error(res, ApiErrorId.ERR_ENHANCED_BASIS_NOT_ELIGIBLE)
