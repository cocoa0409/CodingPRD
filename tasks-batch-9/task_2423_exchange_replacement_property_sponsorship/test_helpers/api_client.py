"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def acquire_property(self, property_id, headers, payload=None):
        return self._request(
            "POST", f"/properties/{property_id}/acquire", payload, headers
        )

    def expire_property_contract(self, property_id, headers, payload=None):
        return self._request(
            "POST", f"/properties/{property_id}/expire-contract", payload, headers
        )

    # ------------------------------------------------------------------
    # Trusts
    # ------------------------------------------------------------------
    def create_trust(self, payload, headers):
        return self._request("POST", "/trusts", payload, headers)

    def get_trust(self, trust_id, headers):
        return self._request("GET", f"/trusts/{trust_id}", headers=headers)

    def list_trusts(self, headers, params=None):
        return self._request("GET", "/trusts", headers=headers, params=params)

    def open_trust_funding(self, trust_id, headers, payload=None):
        return self._request(
            "POST", f"/trusts/{trust_id}/open-funding", payload, headers
        )

    def get_investor_report(self, trust_id, headers):
        return self._request(
            "GET", f"/trusts/{trust_id}/investor-report", headers=headers
        )

    def post_rent(self, trust_id, payload, headers):
        return self._request(
            "POST", f"/trusts/{trust_id}/rent-postings", payload, headers
        )

    def post_debt_service_payment(self, trust_id, payload, headers):
        return self._request(
            "POST", f"/trusts/{trust_id}/debt-service-payments", payload, headers
        )

    # ------------------------------------------------------------------
    # Offerings
    # ------------------------------------------------------------------
    def create_offering(self, payload, headers):
        return self._request("POST", "/offerings", payload, headers)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    def submit_ppm(self, offering_id, payload, headers):
        return self._request(
            "POST", f"/offerings/{offering_id}/submit-ppm", payload, headers
        )

    def return_ppm(self, offering_id, headers, payload=None):
        return self._request(
            "POST", f"/offerings/{offering_id}/return-ppm", payload, headers
        )

    def declare_offering_effective(self, offering_id, payload, headers):
        return self._request(
            "POST", f"/offerings/{offering_id}/declare-effective", payload, headers
        )

    def withdraw_offering(self, offering_id, headers, payload=None):
        return self._request(
            "POST", f"/offerings/{offering_id}/withdraw", payload, headers
        )

    def get_capital_stack(self, offering_id, headers):
        return self._request(
            "GET", f"/offerings/{offering_id}/capital-stack", headers=headers
        )

    # ------------------------------------------------------------------
    # Investors
    # ------------------------------------------------------------------
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def list_investors(self, headers, params=None):
        return self._request("GET", "/investors", headers=headers, params=params)

    def verify_accreditation(self, investor_id, payload, headers):
        return self._request(
            "POST", f"/investors/{investor_id}/verify-accreditation", payload, headers
        )

    def lapse_accreditation(self, investor_id, headers, payload=None):
        return self._request(
            "POST", f"/investors/{investor_id}/lapse-accreditation", payload, headers
        )

    def review_suitability(self, investor_id, payload, headers):
        return self._request(
            "POST", f"/investors/{investor_id}/review-suitability", payload, headers
        )

    # ------------------------------------------------------------------
    # Exchange files
    # ------------------------------------------------------------------
    def create_exchange_file(self, payload, headers):
        return self._request("POST", "/exchange-files", payload, headers)

    def get_exchange_file(self, exchange_file_id, headers):
        return self._request(
            "GET", f"/exchange-files/{exchange_file_id}", headers=headers
        )

    def list_exchange_files(self, headers, params=None):
        return self._request("GET", "/exchange-files", headers=headers, params=params)

    def mark_exchange_file_expired(self, exchange_file_id, headers, payload=None):
        return self._request(
            "POST", f"/exchange-files/{exchange_file_id}/mark-expired", payload, headers
        )

    # ------------------------------------------------------------------
    # Property identifications
    # ------------------------------------------------------------------
    def create_identification(self, payload, headers):
        return self._request("POST", "/property-identifications", payload, headers)

    def get_identification(self, identification_id, headers):
        return self._request(
            "GET", f"/property-identifications/{identification_id}", headers=headers
        )

    def list_identifications(self, headers, params=None):
        return self._request(
            "GET", "/property-identifications", headers=headers, params=params
        )

    def revoke_identification(self, identification_id, headers, payload=None):
        return self._request(
            "POST",
            f"/property-identifications/{identification_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def close_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/close", payload, headers
        )

    def reject_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/reject", payload, headers
        )

    def rescind_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/rescind", payload, headers
        )

    # ------------------------------------------------------------------
    # Loan facilities
    # ------------------------------------------------------------------
    def create_loan_facility(self, payload, headers):
        return self._request("POST", "/loan-facilities", payload, headers)

    def get_loan_facility(self, loan_id, headers):
        return self._request("GET", f"/loan-facilities/{loan_id}", headers=headers)

    def list_loan_facilities(self, headers, params=None):
        return self._request("GET", "/loan-facilities", headers=headers, params=params)

    def reprice_loan_facility(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loan-facilities/{loan_id}/reprice", payload, headers
        )

    def fund_loan_facility(self, loan_id, headers, payload=None):
        return self._request(
            "POST", f"/loan-facilities/{loan_id}/fund", payload, headers
        )

    # ------------------------------------------------------------------
    # Master leases
    # ------------------------------------------------------------------
    def create_master_lease(self, payload, headers):
        return self._request("POST", "/master-leases", payload, headers)

    def get_master_lease(self, lease_id, headers):
        return self._request("GET", f"/master-leases/{lease_id}", headers=headers)

    def list_master_leases(self, headers, params=None):
        return self._request("GET", "/master-leases", headers=headers, params=params)

    def execute_master_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"/master-leases/{lease_id}/execute", payload, headers
        )

    def terminate_master_lease(self, lease_id, headers, payload=None):
        return self._request(
            "POST", f"/master-leases/{lease_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Ledger entries
    # ------------------------------------------------------------------
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request(
            "GET", f"/ledger-entries/{ledger_entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Capital needs
    # ------------------------------------------------------------------
    def create_capital_need(self, payload, headers):
        return self._request("POST", "/capital-needs", payload, headers)

    def get_capital_need(self, capital_need_id, headers):
        return self._request("GET", f"/capital-needs/{capital_need_id}", headers=headers)

    def list_capital_needs(self, headers, params=None):
        return self._request("GET", "/capital-needs", headers=headers, params=params)

    def fund_capital_need(self, capital_need_id, payload, headers):
        return self._request(
            "POST", f"/capital-needs/{capital_need_id}/fund", payload, headers
        )

    def void_capital_need(self, capital_need_id, headers, payload=None):
        return self._request(
            "POST", f"/capital-needs/{capital_need_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Distributions
    # ------------------------------------------------------------------
    def create_distribution(self, payload, headers):
        return self._request("POST", "/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/distributions/{distribution_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/distributions", headers=headers, params=params)

    def pay_distribution(self, distribution_id, headers, payload=None):
        return self._request(
            "POST", f"/distributions/{distribution_id}/pay", payload, headers
        )

    def void_distribution(self, distribution_id, headers, payload=None):
        return self._request(
            "POST", f"/distributions/{distribution_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Distribution allocations
    # ------------------------------------------------------------------
    def get_distribution_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/distribution-allocations/{allocation_id}", headers=headers
        )

    def list_distribution_allocations(self, headers, params=None):
        return self._request(
            "GET", "/distribution-allocations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Tax statements
    # ------------------------------------------------------------------
    def create_tax_statement(self, payload, headers):
        return self._request("POST", "/tax-statements", payload, headers)

    def get_tax_statement(self, tax_statement_id, headers):
        return self._request(
            "GET", f"/tax-statements/{tax_statement_id}", headers=headers
        )

    def list_tax_statements(self, headers, params=None):
        return self._request("GET", "/tax-statements", headers=headers, params=params)

    def issue_tax_statement(self, tax_statement_id, headers, payload=None):
        return self._request(
            "POST", f"/tax-statements/{tax_statement_id}/issue", payload, headers
        )

    # ------------------------------------------------------------------
    # Exit events
    # ------------------------------------------------------------------
    def create_exit_event(self, payload, headers):
        return self._request("POST", "/exit-events", payload, headers)

    def get_exit_event(self, exit_event_id, headers):
        return self._request("GET", f"/exit-events/{exit_event_id}", headers=headers)

    def list_exit_events(self, headers, params=None):
        return self._request("GET", "/exit-events", headers=headers, params=params)

    def tally_consents(self, exit_event_id, headers, payload=None):
        return self._request(
            "POST", f"/exit-events/{exit_event_id}/tally-consents", payload, headers
        )

    def abandon_exit_event(self, exit_event_id, headers, payload=None):
        return self._request(
            "POST", f"/exit-events/{exit_event_id}/abandon", payload, headers
        )

    def close_exit_event(self, exit_event_id, headers, payload=None):
        return self._request(
            "POST", f"/exit-events/{exit_event_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Exit consents
    # ------------------------------------------------------------------
    def create_exit_consent(self, payload, headers):
        return self._request("POST", "/exit-consents", payload, headers)

    def get_exit_consent(self, exit_consent_id, headers):
        return self._request(
            "GET", f"/exit-consents/{exit_consent_id}", headers=headers
        )

    def list_exit_consents(self, headers, params=None):
        return self._request("GET", "/exit-consents", headers=headers, params=params)


api_client = ApiClient()
