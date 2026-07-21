"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/api/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/api/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/api/properties", headers=headers, params=params)

    def set_property_integration(self, property_id, payload, headers):
        return self._request("PATCH", f"/api/properties/{property_id}/integration",
                             payload, headers)

    def list_property_remittances(self, property_id, headers):
        return self._request("GET", f"/api/properties/{property_id}/remittances",
                             headers=headers)

    # ---- Renter ----
    def create_renter(self, payload, headers):
        return self._request("POST", "/api/renters", payload, headers)

    def get_renter(self, renter_id, headers):
        return self._request("GET", f"/api/renters/{renter_id}", headers=headers)

    def list_renters(self, headers, params=None):
        return self._request("GET", "/api/renters", headers=headers, params=params)

    # ---- Application ----
    def submit_application(self, renter_id, payload, headers):
        return self._request("POST", f"/api/renters/{renter_id}/applications",
                             payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/api/applications/{application_id}", headers=headers)

    def list_renter_applications(self, renter_id, headers):
        return self._request("GET", f"/api/renters/{renter_id}/applications",
                             headers=headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/decision",
                             payload, headers)

    # ---- Autopay ----
    def get_renter_mandate(self, renter_id, headers):
        return self._request("GET", f"/api/renters/{renter_id}/autopay-mandate",
                             headers=headers)

    def get_mandate(self, mandate_id, headers):
        return self._request("GET", f"/api/autopay-mandates/{mandate_id}", headers=headers)

    def update_mandate(self, mandate_id, payload, headers):
        return self._request("PATCH", f"/api/autopay-mandates/{mandate_id}",
                             payload, headers)

    # ---- BillingCycle ----
    def create_billing_cycle(self, payload, headers):
        return self._request("POST", "/api/billing-cycles", payload, headers)

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/api/billing-cycles", headers=headers, params=params)

    def reschedule_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/api/billing-cycles/{cycle_id}/reschedule",
                             payload, headers)

    def remit_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/billing-cycles/{cycle_id}/remit", {}, headers)

    def settle_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/billing-cycles/{cycle_id}/settle", {}, headers)

    def cancel_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/billing-cycles/{cycle_id}/cancel", {}, headers)

    def assess_delinquency(self, cycle_id, headers):
        return self._request("POST", f"/api/billing-cycles/{cycle_id}/assess-delinquency",
                             {}, headers)

    def list_cycle_installments(self, cycle_id, headers):
        return self._request("GET", f"/api/billing-cycles/{cycle_id}/installments",
                             headers=headers)

    def list_cycle_remittances(self, cycle_id, headers):
        return self._request("GET", f"/api/billing-cycles/{cycle_id}/remittances",
                             headers=headers)

    def list_cycle_ledger(self, cycle_id, headers):
        return self._request("GET", f"/api/billing-cycles/{cycle_id}/ledger",
                             headers=headers)

    def list_cycle_reminders(self, cycle_id, headers):
        return self._request("GET", f"/api/billing-cycles/{cycle_id}/reminders",
                             headers=headers)

    def get_cycle_summary(self, cycle_id, headers):
        return self._request("GET", f"/api/billing-cycles/{cycle_id}/summary",
                             headers=headers)

    # ---- Installment ----
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/api/installments/{installment_id}", headers=headers)

    def charge_installment(self, installment_id, payload, headers):
        return self._request("POST", f"/api/installments/{installment_id}/charge",
                             payload, headers)

    def retry_installment(self, installment_id, headers):
        return self._request("POST", f"/api/installments/{installment_id}/retry",
                             {}, headers)

    def defer_installment(self, installment_id, payload, headers):
        return self._request("POST", f"/api/installments/{installment_id}/defer",
                             payload, headers)

    # ---- Remittance ----
    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/api/remittances/{remittance_id}", headers=headers)

    def reverse_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/reverse",
                             {}, headers)

    # ---- DelinquencyCase / recovery ----
    def get_delinquency_case(self, case_id, headers):
        return self._request("GET", f"/api/delinquency-cases/{case_id}", headers=headers)

    def list_delinquency_cases(self, headers, params=None):
        return self._request("GET", "/api/delinquency-cases", headers=headers, params=params)

    def record_recovery_action(self, case_id, payload, headers):
        return self._request("POST", f"/api/delinquency-cases/{case_id}/recovery-actions",
                             payload, headers)

    def list_recovery_actions(self, case_id, headers):
        return self._request("GET", f"/api/delinquency-cases/{case_id}/recovery-actions",
                             headers=headers)

    def assess_case(self, case_id, headers):
        return self._request("POST", f"/api/delinquency-cases/{case_id}/assess",
                             {}, headers)

    def charge_off_case(self, case_id, headers):
        return self._request("POST", f"/api/delinquency-cases/{case_id}/charge-off",
                             {}, headers)

    def resolve_case(self, case_id, headers):
        return self._request("POST", f"/api/delinquency-cases/{case_id}/resolve",
                             {}, headers)

    # ---- Reminder ----
    def list_renter_reminders(self, renter_id, headers):
        return self._request("GET", f"/api/renters/{renter_id}/reminders", headers=headers)


api_client = ApiClient()
