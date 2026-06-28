"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- system / test-driving ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def create_catalog_part(self, payload, headers):
        return self._request("POST", "/catalog-parts", payload, headers)

    def get_catalog_part(self, part_id, headers):
        return self._request("GET", f"/catalog-parts/{part_id}", headers=headers)

    # ---- fleet accounts ----
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def get_fleet_account(self, fleet_id, headers):
        return self._request("GET", f"/fleet-accounts/{fleet_id}", headers=headers)

    def suspend_fleet_account(self, fleet_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_id}/suspend", headers=headers)

    def list_fleet_account_payments(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleet-accounts/{fleet_id}/payments",
                             headers=headers, params=params)

    # ---- customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_service_requests(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/service-requests",
                             headers=headers, params=params)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ---- mechanics ----
    def create_mechanic(self, payload, headers):
        return self._request("POST", "/mechanics", payload, headers)

    def get_mechanic(self, mechanic_id, headers):
        return self._request("GET", f"/mechanics/{mechanic_id}", headers=headers)

    def list_mechanic_job_visits(self, mechanic_id, headers, params=None):
        return self._request("GET", f"/mechanics/{mechanic_id}/job-visits",
                             headers=headers, params=params)

    # ---- service requests ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, sr_id, headers):
        return self._request("GET", f"/service-requests/{sr_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def send_quote(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/quotes", payload, headers)

    def list_service_request_quotes(self, sr_id, headers, params=None):
        return self._request("GET", f"/service-requests/{sr_id}/quotes",
                             headers=headers, params=params)

    def dispatch(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/dispatch", payload, headers)

    def source_part_line(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/part-lines", payload, headers)

    def list_service_request_part_lines(self, sr_id, headers, params=None):
        return self._request("GET", f"/service-requests/{sr_id}/part-lines",
                             headers=headers, params=params)

    def get_part_line(self, part_line_id, headers):
        return self._request("GET", f"/part-lines/{part_line_id}", headers=headers)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", "/part-lines", headers=headers, params=params)

    def create_inspection_finding(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/inspection-findings",
                             payload, headers)

    def list_service_request_inspection_findings(self, sr_id, headers, params=None):
        return self._request("GET", f"/service-requests/{sr_id}/inspection-findings",
                             headers=headers, params=params)

    def get_inspection_finding(self, finding_id, headers):
        return self._request("GET", f"/inspection-findings/{finding_id}", headers=headers)

    def list_inspection_findings(self, headers, params=None):
        return self._request("GET", "/inspection-findings", headers=headers, params=params)

    def resolve_addons(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/resolve-addons",
                             payload, headers)

    def cancel_service_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/cancel", headers=headers)

    # ---- quotes ----
    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def approve_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/approve", payload, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", headers=headers)

    def request_revision(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/request-revision", headers=headers)

    # ---- job visits ----
    def get_job_visit(self, visit_id, headers):
        return self._request("GET", f"/job-visits/{visit_id}", headers=headers)

    def list_job_visits(self, headers, params=None):
        return self._request("GET", "/job-visits", headers=headers, params=params)

    def depart(self, visit_id, headers):
        return self._request("POST", f"/job-visits/{visit_id}/depart", headers=headers)

    def start_work(self, visit_id, headers):
        return self._request("POST", f"/job-visits/{visit_id}/start-work", headers=headers)

    def finish(self, visit_id, payload, headers):
        return self._request("POST", f"/job-visits/{visit_id}/finish", payload, headers)

    def abort(self, visit_id, headers):
        return self._request("POST", f"/job-visits/{visit_id}/abort", headers=headers)

    # ---- payments ----
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_service_request_payments(self, sr_id, headers, params=None):
        return self._request("GET", f"/service-requests/{sr_id}/payments",
                             headers=headers, params=params)

    def settle_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/settle", headers=headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", headers=headers)

    # ---- warranty claims ----
    def file_warranty_claim(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/warranty-claims",
                             payload, headers)

    def list_service_request_warranty_claims(self, sr_id, headers, params=None):
        return self._request("GET", f"/service-requests/{sr_id}/warranty-claims",
                             headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def request_info(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/request-info", headers=headers)

    def supply_info(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/supply-info", headers=headers)

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", payload, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", headers=headers)


api_client = ApiClient()
