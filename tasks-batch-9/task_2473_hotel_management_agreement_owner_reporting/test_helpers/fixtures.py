"""Composite scenario builders.

Every test starts against an empty store, so all state is built from scratch
through the declared endpoints. ``Scenario`` wraps the client with the canonical
chains: register -> activate -> budget -> submit -> approve -> report package ->
benchmark / charges -> submit -> owner review -> distribution -> execute.

Setup helpers use the lenient ``get_success_data`` extractor: a broken setup
call surfaces as a KeyError in the test body rather than as a misleading
assertion inside the fixture.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    BudgetDecision,
    ClaimAction,
    ReviewDecision,
    ReviewDimension,
)
from . import factories as f
from .test_users import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    MANAGER_HEADERS,
    OWNER_HEADERS,
)


class Scenario:
    """Chain builder over one API client."""

    def __init__(self, api: ApiClient):
        self.api = api

    # -- clock --------------------------------------------------------------

    def set_clock(self, to_iso8601: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(to_iso8601, ADMIN_HEADERS))

    # -- agreements ---------------------------------------------------------

    def register(self, payload: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
        body = payload if payload is not None else f.agreement_payload(**overrides)
        return get_success_data(self.api.create_agreement(body, ADMIN_HEADERS))

    def register_expert(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_agreement(f.expert_agreement_payload(**overrides), ADMIN_HEADERS)
        )

    def activate(self, agreement_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.activate_agreement(agreement_id, ADMIN_HEADERS))

    def active_agreement(self, **overrides: Any) -> Dict[str, Any]:
        agreement = self.register(**overrides)
        return self.activate(agreement["id"])

    def active_expert_agreement(self, **overrides: Any) -> Dict[str, Any]:
        agreement = self.register_expert(**overrides)
        return self.activate(agreement["id"])

    def read_agreement(self, agreement_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_agreement(agreement_id, ADMIN_HEADERS))

    def agreement_version(self, agreement_id: str) -> int:
        return self.read_agreement(agreement_id)["version"]

    # -- budgets ------------------------------------------------------------

    def budget(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = f.budget_payload(self.agreement_version(agreement_id), **overrides)
        return get_success_data(self.api.create_budget(agreement_id, payload, MANAGER_HEADERS))

    def submit_budget(self, budget_id: str, headers: Optional[Dict[str, str]] = None, **amounts: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.submit_budget(budget_id, headers or MANAGER_HEADERS, f.budget_submit_payload(**amounts))
        )

    def decide_budget(
        self,
        budget_id: str,
        decision: str = BudgetDecision.APPROVE,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_budget(
                budget_id, f.budget_decision_payload(decision), headers or OWNER_HEADERS
            )
        )

    def approved_budget(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        budget = self.budget(agreement_id, **overrides)
        self.submit_budget(budget["id"])
        return self.decide_budget(budget["id"], BudgetDecision.APPROVE)

    def read_budget(self, budget_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_budget(budget_id, MANAGER_HEADERS))

    def budgets(self, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_budgets(MANAGER_HEADERS, params or None))

    # -- variance requests --------------------------------------------------

    def variance(self, budget_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_variance_request(
                budget_id, f.variance_payload(**overrides), headers or MANAGER_HEADERS
            )
        )

    def variances(self, budget_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_variance_requests(budget_id, MANAGER_HEADERS, params or None))

    # -- report packages ----------------------------------------------------

    def package(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_report_package(agreement_id, f.package_payload(**overrides), MANAGER_HEADERS)
        )

    def expert_package(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_report_package(
                agreement_id, f.expert_package_payload(**overrides), MANAGER_HEADERS
            )
        )

    def read_package(self, package_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_report_package(package_id, MANAGER_HEADERS))

    def packages(self, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_report_packages(agreement_id, MANAGER_HEADERS, params or None))

    def submit_package(self, package_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.submit_report_package(package_id, MANAGER_HEADERS))

    def review_package(
        self,
        package_id: str,
        dimension: str = ReviewDimension.FINANCIAL,
        decision: str = ReviewDecision.ACCEPT,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.review_report_package(
                package_id, f.owner_review_payload(dimension, decision), OWNER_HEADERS
            )
        )

    def accepted_package(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        """Open a period, freeze it and have the owner accept the profit-and-loss."""
        package = self.package(agreement_id, **overrides)
        self.submit_package(package["id"])
        return self.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

    # -- benchmarks and charges --------------------------------------------

    def benchmark(self, package_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_benchmark(package_id, f.benchmark_payload(**overrides), MANAGER_HEADERS)
        )

    def benchmarks(self, package_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_benchmarks(package_id, MANAGER_HEADERS, params or None))

    def charge(self, package_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_centralized_charge(package_id, f.charge_payload(**overrides), MANAGER_HEADERS)
        )

    def charges(self, package_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_centralized_charges(package_id, MANAGER_HEADERS, params or None)
        )

    def contest_charge(self, charge_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.review_centralized_charge(charge_id, f.contest_payload(), ASSET_HEADERS)
        )

    def reaffirm_charge(self, charge_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.review_centralized_charge(charge_id, f.reaffirm_payload(), MANAGER_HEADERS)
        )

    def adjust_charge(self, charge_id: str, adjusted_amount_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.review_centralized_charge(
                charge_id, f.adjust_payload(adjusted_amount_cents), MANAGER_HEADERS
            )
        )

    # -- accruals, distributions, ledger -----------------------------------

    def accruals(self, package_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_fee_accruals(package_id, MANAGER_HEADERS, params or None))

    def distributions(self, package_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_distributions(package_id, MANAGER_HEADERS, params or None))

    def only_distribution(self, package_id: str) -> Dict[str, Any]:
        rows = self.distributions(package_id)
        assert len(rows) == 1, rows
        return rows[0]

    def execute_distribution(self, distribution_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.execute_distribution(distribution_id, MANAGER_HEADERS))

    def ledger(self, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_reserve_ledger(agreement_id, MANAGER_HEADERS, params or None))

    # -- working capital calls ---------------------------------------------

    def call(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_working_capital_call(
                agreement_id, f.working_capital_call_payload(**overrides), MANAGER_HEADERS
            )
        )

    def calls(self, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_working_capital_calls(agreement_id, MANAGER_HEADERS, params or None)
        )

    def only_call(self, agreement_id: str) -> Dict[str, Any]:
        rows = self.calls(agreement_id)
        assert len(rows) == 1, rows
        return rows[0]

    def fund_call(self, call_id: str, funded_amount_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.fund_working_capital_call(call_id, f.fund_payload(funded_amount_cents), OWNER_HEADERS)
        )

    # -- true-up and performance tests -------------------------------------

    def true_up(self, agreement_id: str, fiscal_year: int = 2026) -> Dict[str, Any]:
        payload = f.true_up_payload(self.agreement_version(agreement_id), fiscal_year)
        return get_success_data(self.api.run_annual_true_up(agreement_id, payload, MANAGER_HEADERS))

    def performance_test(self, agreement_id: str, fiscal_year: int = 2026) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_performance_test(
                agreement_id, f.performance_test_payload(fiscal_year), ADMIN_HEADERS
            )
        )

    def performance_tests(self, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_performance_tests(agreement_id, MANAGER_HEADERS, params or None)
        )

    def elect_cure(self, test_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.cure_performance_test(test_id, f.elect_cure_payload(), MANAGER_HEADERS)
        )

    def pay_cure(self, test_id: str, payment_amount_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.cure_performance_test(
                test_id, f.pay_cure_payload(payment_amount_cents), MANAGER_HEADERS
            )
        )

    def terminate_test(self, test_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.terminate_performance_test(test_id, OWNER_HEADERS, f.terminate_payload())
        )

    # -- brand disputes -----------------------------------------------------

    def dispute(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_brand_dispute(
                agreement_id, f.brand_dispute_payload(**overrides), ASSET_HEADERS
            )
        )

    def disputes(self, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_brand_disputes(agreement_id, MANAGER_HEADERS, params or None)
        )

    def dispute_round(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Dict[str, Any]:
        return get_success_data(self.api.advance_brand_dispute(dispute_id, payload, headers))

    def manager_response(self, dispute_id: str, cost_estimate_cents: int) -> Dict[str, Any]:
        return self.dispute_round(
            dispute_id, f.manager_response_payload(cost_estimate_cents), MANAGER_HEADERS
        )

    def owner_counter(self, dispute_id: str, cost_estimate_cents: int) -> Dict[str, Any]:
        return self.dispute_round(
            dispute_id, f.owner_counter_payload(cost_estimate_cents), ASSET_HEADERS
        )

    def escalate(self, dispute_id: str) -> Dict[str, Any]:
        return self.dispute_round(dispute_id, f.escalate_payload(), MANAGER_HEADERS)

    def resolve_owner_funds(self, dispute_id: str, funding_source: str) -> Dict[str, Any]:
        return self.dispute_round(
            dispute_id, f.resolve_owner_funds_payload(funding_source), OWNER_HEADERS
        )

    def resolve_waived(self, dispute_id: str) -> Dict[str, Any]:
        return self.dispute_round(dispute_id, f.resolve_waived_payload(), OWNER_HEADERS)

    def rescind(self, dispute_id: str) -> Dict[str, Any]:
        return self.dispute_round(dispute_id, f.rescind_payload(), OWNER_HEADERS)

    # -- employment claims --------------------------------------------------

    def claim(self, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_employment_claim(
                agreement_id, f.employment_claim_payload(**overrides), MANAGER_HEADERS
            )
        )

    def claims(self, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_employment_claims(agreement_id, MANAGER_HEADERS, params or None)
        )

    def allocate_claim(self, claim_id: str, action: str = ClaimAction.ALLOCATE) -> Dict[str, Any]:
        return get_success_data(
            self.api.allocate_employment_claim(claim_id, f.claim_allocation_payload(action), ASSET_HEADERS)
        )


__all__ = ["Scenario"]
