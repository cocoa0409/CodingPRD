"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/_clock/set_current_utc", payload, headers
        )

    # ---- Carrier ----
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    # ---- Growers ----
    def create_grower(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/growers", payload, headers)

    def get_grower(self, carrier_id, grower_id, headers):
        return self._request(
            "GET", f"/carriers/{carrier_id}/growers/{grower_id}", headers=headers
        )

    def list_growers(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/carriers/{carrier_id}/growers", headers=headers, params=params
        )

    def debar_grower(self, carrier_id, grower_id, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/growers/{grower_id}/debar", {}, headers
        )

    # ---- Adjusters ----
    def create_adjuster(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/adjusters", payload, headers)

    def get_adjuster(self, carrier_id, adjuster_id, headers):
        return self._request(
            "GET", f"/carriers/{carrier_id}/adjusters/{adjuster_id}", headers=headers
        )

    # ---- Rate tables ----
    def create_rate_table(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/rate-tables", payload, headers)

    def list_rate_tables(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/carriers/{carrier_id}/rate-tables", headers=headers, params=params
        )

    def get_rate_table(self, carrier_id, rate_table_id, headers):
        return self._request(
            "GET", f"/carriers/{carrier_id}/rate-tables/{rate_table_id}", headers=headers
        )

    def publish_rate_table(self, carrier_id, rate_table_id, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/rate-tables/{rate_table_id}/publish", {}, headers
        )

    def supersede_rate_table(self, carrier_id, rate_table_id, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/rate-tables/{rate_table_id}/supersede", {}, headers
        )

    # ---- Federal crop policies ----
    def create_federal_crop_policy(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/federal-crop-policies", payload, headers
        )

    def get_federal_crop_policy(self, carrier_id, fci_id, headers):
        return self._request(
            "GET", f"/carriers/{carrier_id}/federal-crop-policies/{fci_id}", headers=headers
        )

    def list_federal_crop_policies(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/carriers/{carrier_id}/federal-crop-policies", headers=headers, params=params
        )

    def cancel_federal_crop_policy(self, carrier_id, fci_id, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/federal-crop-policies/{fci_id}/cancel", {}, headers
        )

    # ---- Policies ----
    def create_policy(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/policies", payload, headers)

    def get_policy(self, carrier_id, policy_id, headers):
        return self._request(
            "GET", f"/carriers/{carrier_id}/policies/{policy_id}", headers=headers
        )

    def list_policies(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/carriers/{carrier_id}/policies", headers=headers, params=params
        )

    def bind_policy(self, carrier_id, policy_id, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/policies/{policy_id}/bind", {}, headers
        )

    def cancel_policy(self, carrier_id, policy_id, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/policies/{policy_id}/cancel", {}, headers
        )

    # ---- Coverage units ----
    def create_coverage_unit(self, carrier_id, policy_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units",
            payload,
            headers,
        )

    def list_coverage_units(self, carrier_id, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units",
            headers=headers,
            params=params,
        )

    def get_coverage_unit(self, carrier_id, policy_id, unit_id, headers):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units/{unit_id}",
            headers=headers,
        )

    # ---- Acreage reports ----
    def create_acreage_report(self, carrier_id, policy_id, unit_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units/{unit_id}/acreage-reports",
            payload,
            headers,
        )

    def list_acreage_reports(self, carrier_id, policy_id, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units/{unit_id}/acreage-reports",
            headers=headers,
            params=params,
        )

    # ---- Head reports ----
    def create_head_report(self, carrier_id, policy_id, unit_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units/{unit_id}/head-reports",
            payload,
            headers,
        )

    def list_head_reports(self, carrier_id, policy_id, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/coverage-units/{unit_id}/head-reports",
            headers=headers,
            params=params,
        )

    # ---- Claims ----
    def create_claim(self, carrier_id, policy_id, payload, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/policies/{policy_id}/claims", payload, headers
        )

    def get_claim(self, carrier_id, policy_id, claim_id, headers):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}",
            headers=headers,
        )

    def list_claims(self, carrier_id, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims",
            headers=headers,
            params=params,
        )

    def assign_adjuster(self, carrier_id, policy_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/assign-adjuster",
            payload,
            headers,
        )

    def withdraw_claim(self, carrier_id, policy_id, claim_id, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/withdraw",
            {},
            headers,
        )

    # ---- Field inspections ----
    def create_field_inspection(self, carrier_id, policy_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/field-inspections",
            payload,
            headers,
        )

    def list_field_inspections(self, carrier_id, policy_id, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/field-inspections",
            headers=headers,
            params=params,
        )

    def submit_for_review(self, carrier_id, policy_id, claim_id, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/submit-for-review",
            {},
            headers,
        )

    # ---- Veterinary reports ----
    def create_veterinary_report(self, carrier_id, policy_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/veterinary-reports",
            payload,
            headers,
        )

    def list_veterinary_reports(self, carrier_id, policy_id, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/veterinary-reports",
            headers=headers,
            params=params,
        )

    # ---- Loss determinations ----
    def create_determination(self, carrier_id, policy_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/determinations",
            payload,
            headers,
        )

    def list_determinations(self, carrier_id, policy_id, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/determinations",
            headers=headers,
            params=params,
        )

    # ---- Indemnity payments ----
    def create_indemnity_payment(self, carrier_id, policy_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/indemnity-payments",
            payload,
            headers,
        )

    def list_indemnity_payments(self, carrier_id, policy_id, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/indemnity-payments",
            headers=headers,
            params=params,
        )

    def clear_indemnity_payment(self, carrier_id, policy_id, claim_id, payment_id, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/indemnity-payments/{payment_id}/clear",
            {},
            headers,
        )

    def void_indemnity_payment(self, carrier_id, policy_id, claim_id, payment_id, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/claims/{claim_id}/indemnity-payments/{payment_id}/void",
            {},
            headers,
        )

    # ---- Dual coverage links ----
    def create_dual_coverage_link(self, carrier_id, policy_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/dual-coverage-links",
            payload,
            headers,
        )

    def list_dual_coverage_links(self, carrier_id, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/dual-coverage-links",
            headers=headers,
            params=params,
        )

    # ---- Renewals ----
    def create_renewal(self, carrier_id, policy_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/renewals",
            payload,
            headers,
        )

    def list_renewals(self, carrier_id, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/renewals",
            headers=headers,
            params=params,
        )

    # ---- Premium payments ----
    def create_premium_payment(self, carrier_id, policy_id, payload, headers):
        return self._request(
            "POST",
            f"/carriers/{carrier_id}/policies/{policy_id}/premium-payments",
            payload,
            headers,
        )

    def list_premium_payments(self, carrier_id, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/policies/{policy_id}/premium-payments",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
