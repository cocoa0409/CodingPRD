"""API client: one method per endpoint defined in the PRD (all under /sleep-therapy)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and daily operations sweep (OpsAdmin test-driving)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/sleep-therapy/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/sleep-therapy/_ops/run-daily-sweep", {}, headers)

    # ------------------------------------------------------------------
    # Payer policies
    # ------------------------------------------------------------------
    def create_payer_policy(self, payload, headers):
        return self._request("POST", "/sleep-therapy/payer-policies", payload, headers)

    def list_payer_policies(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/payer-policies",
                             headers=headers, params=params)

    def get_payer_policy(self, policy_id, headers):
        return self._request("GET", f"/sleep-therapy/payer-policies/{policy_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/sleep-therapy/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/patients",
                             headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/sleep-therapy/patients/{patient_id}",
                             headers=headers)

    def initiate_discontinuation(self, patient_id, payload, headers):
        return self._request("POST",
                             f"/sleep-therapy/patients/{patient_id}/initiate-discontinuation",
                             payload, headers)

    # ------------------------------------------------------------------
    # Device enrollments
    # ------------------------------------------------------------------
    def create_device_enrollment(self, payload, headers):
        return self._request("POST", "/sleep-therapy/device-enrollments", payload, headers)

    def list_device_enrollments(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/device-enrollments",
                             headers=headers, params=params)

    def get_device_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/sleep-therapy/device-enrollments/{enrollment_id}",
                             headers=headers)

    def begin_setup(self, enrollment_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/device-enrollments/{enrollment_id}/begin-setup",
                             {}, headers)

    def complete_setup(self, enrollment_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/device-enrollments/{enrollment_id}/complete-setup",
                             {}, headers)

    def return_to_payer(self, enrollment_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/device-enrollments/{enrollment_id}/return-to-payer",
                             {}, headers)

    # ------------------------------------------------------------------
    # Component supply plans
    # ------------------------------------------------------------------
    def list_component_supply_plans(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/component-supply-plans",
                             headers=headers, params=params)

    def get_component_supply_plan(self, plan_id, headers):
        return self._request("GET", f"/sleep-therapy/component-supply-plans/{plan_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Resupply orders
    # ------------------------------------------------------------------
    def create_resupply_order(self, payload, headers):
        return self._request("POST", "/sleep-therapy/resupply-orders", payload, headers)

    def list_resupply_orders(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/resupply-orders",
                             headers=headers, params=params)

    def get_resupply_order(self, order_id, headers):
        return self._request("GET", f"/sleep-therapy/resupply-orders/{order_id}",
                             headers=headers)

    def clinical_clear_order(self, order_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/clinical-clear",
                             {}, headers)

    def authorize_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/authorize",
                             payload, headers)

    def deny_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/deny",
                             payload, headers)

    def ship_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/ship",
                             payload, headers)

    def mark_order_delivered(self, order_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/mark-delivered",
                             {}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/invoice",
                             {}, headers)

    def mark_order_returned(self, order_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/mark-returned",
                             {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/resupply-orders/{order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Adherence reports
    # ------------------------------------------------------------------
    def create_adherence_report(self, payload, headers):
        return self._request("POST", "/sleep-therapy/adherence-reports", payload, headers)

    def list_adherence_reports(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/adherence-reports",
                             headers=headers, params=params)

    def get_adherence_report(self, report_id, headers):
        return self._request("GET", f"/sleep-therapy/adherence-reports/{report_id}",
                             headers=headers)

    def begin_review_report(self, report_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/adherence-reports/{report_id}/begin-review",
                             {}, headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/adherence-reports/{report_id}/finalize",
                             {}, headers)

    def reject_report(self, report_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/adherence-reports/{report_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Mask exchanges
    # ------------------------------------------------------------------
    def create_mask_exchange(self, payload, headers):
        return self._request("POST", "/sleep-therapy/mask-exchanges", payload, headers)

    def list_mask_exchanges(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/mask-exchanges",
                             headers=headers, params=params)

    def get_mask_exchange(self, exchange_id, headers):
        return self._request("GET", f"/sleep-therapy/mask-exchanges/{exchange_id}",
                             headers=headers)

    def approve_mask_exchange(self, exchange_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/mask-exchanges/{exchange_id}/approve",
                             {}, headers)

    def ship_mask_exchange(self, exchange_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/mask-exchanges/{exchange_id}/ship",
                             {}, headers)

    def complete_mask_exchange(self, exchange_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/mask-exchanges/{exchange_id}/complete",
                             {}, headers)

    def deny_mask_exchange(self, exchange_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/mask-exchanges/{exchange_id}/deny",
                             {}, headers)

    def cancel_mask_exchange(self, exchange_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/mask-exchanges/{exchange_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Rental contracts
    # ------------------------------------------------------------------
    def list_rental_contracts(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/rental-contracts",
                             headers=headers, params=params)

    def get_rental_contract(self, contract_id, headers):
        return self._request("GET", f"/sleep-therapy/rental-contracts/{contract_id}",
                             headers=headers)

    def bill_rental_month(self, contract_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/rental-contracts/{contract_id}/bill-rental-month",
                             {}, headers)

    # ------------------------------------------------------------------
    # Retrieval cases
    # ------------------------------------------------------------------
    def list_retrieval_cases(self, headers, params=None):
        return self._request("GET", "/sleep-therapy/retrieval-cases",
                             headers=headers, params=params)

    def get_retrieval_case(self, case_id, headers):
        return self._request("GET", f"/sleep-therapy/retrieval-cases/{case_id}",
                             headers=headers)

    def schedule_pickup(self, case_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/retrieval-cases/{case_id}/schedule-pickup",
                             {}, headers)

    def mark_picked_up(self, case_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/retrieval-cases/{case_id}/mark-picked-up",
                             {}, headers)

    def mark_received(self, case_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/retrieval-cases/{case_id}/mark-received",
                             {}, headers)

    def reconcile_case(self, case_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/retrieval-cases/{case_id}/reconcile",
                             {}, headers)

    def close_unrecoverable(self, case_id, headers):
        return self._request("POST",
                             f"/sleep-therapy/retrieval-cases/{case_id}/close-unrecoverable",
                             {}, headers)


api_client = ApiClient()
