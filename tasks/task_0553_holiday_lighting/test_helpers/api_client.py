"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ── Customers ────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ── Contracts ────────────────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/sign", {}, headers)

    def renew_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/renew", payload, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/cancel", {}, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    # ── Estimates ────────────────────────────────────────────────────────────
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def quote_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/quote", {}, headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/accept", {}, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    # ── Crews ────────────────────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    # ── Route days ───────────────────────────────────────────────────────────
    def create_route_day(self, payload, headers):
        return self._request("POST", "/route-days", payload, headers)

    def dispatch_route_day(self, route_day_id, headers):
        return self._request("POST", f"/route-days/{route_day_id}/dispatch", {}, headers)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/route-days/{route_day_id}", headers=headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/route-days", headers=headers, params=params)

    # ── Route assignments ────────────────────────────────────────────────────
    def create_route_assignment(self, payload, headers):
        return self._request("POST", "/route-assignments", payload, headers)

    def get_route_assignment(self, route_assignment_id, headers):
        return self._request("GET", f"/route-assignments/{route_assignment_id}",
                             headers=headers)

    def list_route_assignments(self, headers, params=None):
        return self._request("GET", "/route-assignments", headers=headers, params=params)

    # ── Jobs ─────────────────────────────────────────────────────────────────
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def weather_hold_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/weather-hold", {}, headers)

    def reschedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/reschedule", payload, headers)

    def start_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/start", {}, headers)

    def complete_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/complete", payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", {}, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    # ── Service calls ────────────────────────────────────────────────────────
    def create_service_call(self, payload, headers):
        return self._request("POST", "/service-calls", payload, headers)

    def classify_service_call(self, service_call_id, payload, headers):
        return self._request("POST", f"/service-calls/{service_call_id}/classify",
                             payload, headers)

    def schedule_service_call(self, service_call_id, payload, headers):
        return self._request("POST", f"/service-calls/{service_call_id}/schedule",
                             payload, headers)

    def resolve_service_call(self, service_call_id, headers):
        return self._request("POST", f"/service-calls/{service_call_id}/resolve",
                             {}, headers)

    def get_service_call(self, service_call_id, headers):
        return self._request("GET", f"/service-calls/{service_call_id}", headers=headers)

    def list_service_calls(self, headers, params=None):
        return self._request("GET", "/service-calls", headers=headers, params=params)

    # ── Storage ──────────────────────────────────────────────────────────────
    def create_storage_bin(self, payload, headers):
        return self._request("POST", "/storage-bins", payload, headers)

    def create_storage_record(self, payload, headers):
        return self._request("POST", "/storage-records", payload, headers)

    def retrieve_storage_record(self, storage_record_id, headers):
        return self._request("POST", f"/storage-records/{storage_record_id}/retrieve",
                             {}, headers)

    def get_storage_record(self, storage_record_id, headers):
        return self._request("GET", f"/storage-records/{storage_record_id}",
                             headers=headers)

    def list_storage_records(self, headers, params=None):
        return self._request("GET", "/storage-records", headers=headers, params=params)

    # ── Financing ────────────────────────────────────────────────────────────
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/financing-plans", payload, headers)

    def get_payoff_quote(self, financing_plan_id, headers):
        return self._request("GET", f"/financing-plans/{financing_plan_id}/payoff-quote",
                             headers=headers)

    def create_payment(self, financing_plan_id, payload, headers):
        return self._request("POST", f"/financing-plans/{financing_plan_id}/payments",
                             payload, headers)

    def get_financing_plan(self, financing_plan_id, headers):
        return self._request("GET", f"/financing-plans/{financing_plan_id}",
                             headers=headers)

    def list_financing_plans(self, headers, params=None):
        return self._request("GET", "/financing-plans", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ── Invoices ─────────────────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)


api_client = ApiClient()
