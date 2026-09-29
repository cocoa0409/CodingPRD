"""Typed HTTP client with one method per documented endpoint."""

from prd_bench_local_runner.testing import GenericApiClient

from test_helpers.constants import API_PREFIX

PREFIX = API_PREFIX


class ApiClient(GenericApiClient):
    """One method per endpoint of the family child care network API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------- provider
    def apply_provider(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/providers/apply", payload, headers)

    def verify_license(self, provider_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/license-verification", payload, headers
        )

    def reinstate_provider(self, provider_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/reinstate", payload, headers
        )

    def exit_network(self, provider_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/exit-network", payload, headers
        )

    def complete_exit(self, provider_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/complete-exit", payload, headers
        )

    def list_providers(self, params=None, headers=None):
        return self._request("GET", f"{PREFIX}/providers", params, headers)

    def get_provider(self, provider_id, headers=None):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", None, headers)

    def get_revenue_model(self, provider_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/revenue-model", None, headers
        )

    def list_provider_agreements(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/membership-agreements", params, headers
        )

    def list_provider_contracts(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/subsidy-contracts", params, headers
        )

    def list_provider_food_claims(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/food-program-claims", params, headers
        )

    def list_provider_visits(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/coaching-visits", params, headers
        )

    def list_provider_reviews(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/compliance-reviews", params, headers
        )

    def list_provider_orders(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/group-purchase-orders", params, headers
        )

    def list_provider_assignments(self, provider_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/substitute-assignments", params, headers
        )

    # --------------------------------------------------- membership agreement
    def create_agreement(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/membership-agreements", payload, headers)

    def counter_agreement(self, agreement_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/membership-agreements/{agreement_id}/counter", payload, headers
        )

    def revise_agreement(self, agreement_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/membership-agreements/{agreement_id}/revise", payload, headers
        )

    def execute_agreement(self, agreement_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/membership-agreements/{agreement_id}/execute", payload, headers
        )

    def withdraw_agreement(self, agreement_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/membership-agreements/{agreement_id}/withdraw", payload, headers
        )

    def get_agreement(self, agreement_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/membership-agreements/{agreement_id}", None, headers
        )

    # ----------------------------------------------------------- enrollment
    def create_enrollment(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/enrollments", payload, headers)

    def withdraw_enrollment(self, enrollment_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/withdraw", payload, headers
        )

    def transfer_enrollment(self, enrollment_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/transfer", payload, headers
        )

    def list_enrollments(self, params=None, headers=None):
        return self._request("GET", f"{PREFIX}/enrollments", params, headers)

    def get_enrollment(self, enrollment_id, headers=None):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}", None, headers)

    # ------------------------------------------------------ subsidy contract
    def create_contract(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/subsidy-contracts", payload, headers)

    def get_contract(self, contract_id, headers=None):
        return self._request("GET", f"{PREFIX}/subsidy-contracts/{contract_id}", None, headers)

    def list_contract_claims(self, contract_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/subsidy-contracts/{contract_id}/claims", params, headers
        )

    def list_contract_remittances(self, contract_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/subsidy-contracts/{contract_id}/remittances", params, headers
        )

    # --------------------------------------------------------- subsidy claim
    def create_claim(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/subsidy-claims", payload, headers)

    def submit_claim(self, claim_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/subsidy-claims/{claim_id}/submit", payload, headers
        )

    def advance_claim(self, claim_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/subsidy-claims/{claim_id}/advance", payload, headers
        )

    def reconcile_claim(self, claim_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/subsidy-claims/{claim_id}/reconcile", payload, headers
        )

    def reject_claim(self, claim_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/subsidy-claims/{claim_id}/reject", payload, headers
        )

    def get_claim(self, claim_id, headers=None):
        return self._request("GET", f"{PREFIX}/subsidy-claims/{claim_id}", None, headers)

    # ------------------------------------------------------------ remittance
    def create_remittance(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/remittances", payload, headers)

    def reverse_remittance(self, remittance_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/remittances/{remittance_id}/reverse", payload, headers
        )

    # ----------------------------------------------------- food program claim
    def create_food_claim(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/food-program-claims", payload, headers)

    def approve_food_claim(self, claim_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/food-program-claims/{claim_id}/approve", payload, headers
        )

    def get_food_claim(self, claim_id, headers=None):
        return self._request("GET", f"{PREFIX}/food-program-claims/{claim_id}", None, headers)

    # ------------------------------------------------------------ substitute
    def create_substitute(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/substitutes", payload, headers)

    def record_clearance(self, substitute_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/substitutes/{substitute_id}/clearance", payload, headers
        )

    def get_substitute(self, substitute_id, headers=None):
        return self._request("GET", f"{PREFIX}/substitutes/{substitute_id}", None, headers)

    def list_substitute_assignments(self, substitute_id, params=None, headers=None):
        return self._request(
            "GET", f"{PREFIX}/substitutes/{substitute_id}/assignments", params, headers
        )

    # -------------------------------------------------- substitute assignment
    def create_assignment(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/substitute-assignments", payload, headers)

    def accept_assignment(self, assignment_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/substitute-assignments/{assignment_id}/accept", payload, headers
        )

    def decline_assignment(self, assignment_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/substitute-assignments/{assignment_id}/decline", payload, headers
        )

    def complete_assignment(self, assignment_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/substitute-assignments/{assignment_id}/complete", payload, headers
        )

    def invoice_assignment(self, assignment_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/substitute-assignments/{assignment_id}/invoice", payload, headers
        )

    def get_assignment(self, assignment_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/substitute-assignments/{assignment_id}", None, headers
        )

    # --------------------------------------------------------- coaching visit
    def create_visit(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/coaching-visits", payload, headers)

    def conduct_visit(self, visit_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/coaching-visits/{visit_id}/conduct", payload, headers
        )

    def get_visit(self, visit_id, headers=None):
        return self._request("GET", f"{PREFIX}/coaching-visits/{visit_id}", None, headers)

    # ------------------------------------------------------ compliance review
    def create_review(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/compliance-reviews", payload, headers)

    def submit_cap(self, review_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-reviews/{review_id}/submit-cap", payload, headers
        )

    def reject_cap(self, review_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-reviews/{review_id}/reject-cap", payload, headers
        )

    def close_review(self, review_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-reviews/{review_id}/close", payload, headers
        )

    def escalate_review(self, review_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-reviews/{review_id}/escalate", payload, headers
        )

    def get_review(self, review_id, headers=None):
        return self._request("GET", f"{PREFIX}/compliance-reviews/{review_id}", None, headers)

    # ---------------------------------------------------- group purchase order
    def create_order(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/group-purchase-orders", payload, headers)

    def commit_order(self, order_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/group-purchase-orders/{order_id}/commit", payload, headers
        )

    def get_order(self, order_id, headers=None):
        return self._request("GET", f"{PREFIX}/group-purchase-orders/{order_id}", None, headers)


api_client = ApiClient()
