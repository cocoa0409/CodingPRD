"""API client: one method per endpoint of the Brand Inspection Board API."""

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/brand-inspection"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Brand Inspection Board API (PRD §4)."""

    # ─── Owners ───────────────────────────────────────────────────────────
    def create_owner(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"{API_PREFIX}/owners/{owner_id}", headers=headers)

    def get_owner_statement(self, owner_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/owners/{owner_id}/statement", headers=headers
        )

    # ─── Territories ──────────────────────────────────────────────────────
    def create_territory(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/territories/{territory_id}", headers=headers
        )

    # ─── Inspectors ───────────────────────────────────────────────────────
    def create_inspector(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/inspectors/{inspector_id}", headers=headers
        )

    def list_inspectors(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/inspectors", headers=headers, params=params
        )

    def set_inspector_status(self, inspector_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspectors/{inspector_id}/status", payload, headers
        )

    # ─── Brand applications ───────────────────────────────────────────────
    def create_brand_application(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/brand-applications", payload, headers
        )

    def create_renewal_application(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-registrations/{registration_id}/renewal-applications",
            payload,
            headers,
        )

    def get_brand_application(self, application_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/brand-applications/{application_id}", headers=headers
        )

    def list_brand_applications(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/brand-applications", headers=headers, params=params
        )

    def begin_examination(self, application_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-applications/{application_id}/begin-examination",
            {},
            headers,
        )

    def return_application(self, application_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-applications/{application_id}/return",
            {},
            headers,
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-applications/{application_id}/resubmit",
            payload,
            headers,
        )

    def record_application(self, application_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-applications/{application_id}/record",
            {},
            headers,
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-applications/{application_id}/reject",
            payload,
            headers,
        )

    # ─── Brand registrations ──────────────────────────────────────────────
    def get_brand_registration(self, registration_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/brand-registrations/{registration_id}",
            headers=headers,
        )

    def list_brand_registrations(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/brand-registrations", headers=headers, params=params
        )

    # ─── Brand conflict claims ────────────────────────────────────────────
    def create_conflict_claim(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/brand-conflict-claims", payload, headers
        )

    def get_conflict_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/brand-conflict-claims/{claim_id}", headers=headers
        )

    def list_conflict_claims(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/brand-conflict-claims", headers=headers, params=params
        )

    def adjudicate_claim(self, claim_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-conflict-claims/{claim_id}/adjudicate",
            {},
            headers,
        )

    def decide_claim(self, claim_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/brand-conflict-claims/{claim_id}/decide",
            payload,
            headers,
        )

    # ─── Bills of sale ────────────────────────────────────────────────────
    def create_bill_of_sale(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bills-of-sale", payload, headers)

    def get_bill_of_sale(self, bill_of_sale_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/bills-of-sale/{bill_of_sale_id}", headers=headers
        )

    def list_bills_of_sale(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/bills-of-sale", headers=headers, params=params
        )

    # ─── Inspection orders ────────────────────────────────────────────────
    def create_inspection_order(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders", payload, headers
        )

    def get_inspection_order(self, order_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/inspection-orders/{order_id}", headers=headers
        )

    def list_inspection_orders(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/inspection-orders", headers=headers, params=params
        )

    def schedule_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders/{order_id}/schedule", payload, headers
        )

    def begin_order(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders/{order_id}/begin", {}, headers
        )

    def create_lot(self, order_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders/{order_id}/lots", payload, headers
        )

    def complete_order(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders/{order_id}/complete", {}, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders/{order_id}/cancel", {}, headers
        )

    def waive_fee(self, order_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inspection-orders/{order_id}/waive-fee", {}, headers
        )

    def void_assessment(self, order_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inspection-orders/{order_id}/void-assessment",
            {},
            headers,
        )

    # ─── Animal lots ──────────────────────────────────────────────────────
    def get_animal_lot(self, lot_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/animal-lots/{lot_id}", headers=headers
        )

    def list_animal_lots(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/animal-lots", headers=headers, params=params
        )

    def record_finding(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/animal-lots/{lot_id}/finding", payload, headers
        )

    # ─── Estray cases ─────────────────────────────────────────────────────
    def get_estray_case(self, case_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/estray-cases/{case_id}", headers=headers
        )

    def list_estray_cases(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/estray-cases", headers=headers, params=params
        )

    def claim_estray(self, case_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/estray-cases/{case_id}/claim", {}, headers
        )

    def decide_estray_claim(self, case_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/estray-cases/{case_id}/claim-decision", payload, headers
        )

    def schedule_auction(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/estray-cases/{case_id}/schedule-auction",
            payload,
            headers,
        )

    def record_sale(self, case_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/estray-cases/{case_id}/record-sale", payload, headers
        )

    def disburse_estray(self, case_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/estray-cases/{case_id}/disburse", {}, headers
        )

    # ─── Theft investigations ─────────────────────────────────────────────
    def get_theft_investigation(self, investigation_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/theft-investigations/{investigation_id}",
            headers=headers,
        )

    def list_theft_investigations(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/theft-investigations", headers=headers, params=params
        )

    def refer_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/theft-investigations/{investigation_id}/refer",
            payload,
            headers,
        )

    def close_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/theft-investigations/{investigation_id}/close",
            payload,
            headers,
        )

    def reopen_investigation(self, investigation_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/theft-investigations/{investigation_id}/reopen",
            {},
            headers,
        )

    # ─── Fee remittances ──────────────────────────────────────────────────
    def create_fee_remittance(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/fee-remittances", payload, headers)

    def get_fee_remittance(self, remittance_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/fee-remittances/{remittance_id}", headers=headers
        )

    def list_fee_remittances(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/fee-remittances", headers=headers, params=params
        )

    def reconcile_remittance(self, remittance_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/fee-remittances/{remittance_id}/reconcile",
            {},
            headers,
        )

    def top_up_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/fee-remittances/{remittance_id}/top-up",
            payload,
            headers,
        )

    # ─── Operational routes ───────────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    def delinquency_sweep(self, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_ops/delinquency-sweep", {}, headers
        )


api_client = ApiClient()
