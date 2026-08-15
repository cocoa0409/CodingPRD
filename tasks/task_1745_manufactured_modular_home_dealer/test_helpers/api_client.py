"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- home models ---
    def create_home_model(self, payload, headers):
        return self._request("POST", "/api/home-models", payload, headers)

    def list_home_models(self, headers, params=None):
        return self._request("GET", "/api/home-models", headers=headers, params=params)

    def get_home_model(self, model_id, headers):
        return self._request("GET", f"/api/home-models/{model_id}", headers=headers)

    # --- communities / lots ---
    def create_community(self, payload, headers):
        return self._request("POST", "/api/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/api/communities/{community_id}", headers=headers)

    def create_lot(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/lots", payload, headers)

    def list_lots(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def reserve_lot(self, lot_id, headers):
        return self._request("POST", f"/api/lots/{lot_id}/reserve", headers=headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/api/lots/{lot_id}/release", headers=headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- home units ---
    def create_home_unit(self, payload, headers):
        return self._request("POST", "/api/home-units", payload, headers)

    def get_home_unit(self, unit_id, headers):
        return self._request("GET", f"/api/home-units/{unit_id}", headers=headers)

    def list_home_units(self, headers, params=None):
        return self._request("GET", "/api/home-units", headers=headers, params=params)

    def mark_ready_home_unit(self, unit_id, headers):
        return self._request("POST", f"/api/home-units/{unit_id}/mark-ready", headers=headers)

    # --- sales orders ---
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/api/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/api/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/api/sales-orders", headers=headers, params=params)

    def add_order_option(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/options", payload, headers)

    def list_order_options(self, order_id, headers, params=None):
        return self._request("GET", f"/api/sales-orders/{order_id}/options", headers=headers, params=params)

    def void_order_option(self, option_id, headers):
        return self._request("POST", f"/api/order-options/{option_id}/void", headers=headers)

    def confirm_sales_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/confirm", payload, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/cancel", headers=headers)

    def close_sales_order(self, order_id, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/close", headers=headers)

    # --- site evaluations ---
    def create_site_evaluation(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/site-evaluations", payload, headers)

    def list_site_evaluations(self, order_id, headers, params=None):
        return self._request("GET", f"/api/sales-orders/{order_id}/site-evaluations", headers=headers, params=params)

    def get_site_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/api/site-evaluations/{evaluation_id}", headers=headers)

    def record_findings(self, evaluation_id, payload, headers):
        return self._request("POST", f"/api/site-evaluations/{evaluation_id}/record-findings", payload, headers)

    def approve_site_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/api/site-evaluations/{evaluation_id}/approve", headers=headers)

    def reject_site_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/api/site-evaluations/{evaluation_id}/reject", headers=headers)

    # --- financing applications ---
    def create_financing_application(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/financing-applications", payload, headers)

    def list_financing_applications(self, order_id, headers, params=None):
        return self._request("GET", f"/api/sales-orders/{order_id}/financing-applications", headers=headers, params=params)

    def get_financing_application(self, application_id, headers):
        return self._request("GET", f"/api/financing-applications/{application_id}", headers=headers)

    def submit_financing_application(self, application_id, headers):
        return self._request("POST", f"/api/financing-applications/{application_id}/submit", headers=headers)

    def decide_financing_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/financing-applications/{application_id}/decide", payload, headers)

    def fund_financing_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/financing-applications/{application_id}/fund", payload, headers)

    # --- transport crews / jobs ---
    def create_transport_crew(self, payload, headers):
        return self._request("POST", "/api/transport-crews", payload, headers)

    def get_transport_crew(self, crew_id, headers):
        return self._request("GET", f"/api/transport-crews/{crew_id}", headers=headers)

    def create_transport_job(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/transport-jobs", payload, headers)

    def list_order_transport_jobs(self, order_id, headers, params=None):
        return self._request("GET", f"/api/sales-orders/{order_id}/transport-jobs", headers=headers, params=params)

    def list_transport_jobs(self, headers, params=None):
        return self._request("GET", "/api/transport-jobs", headers=headers, params=params)

    def get_transport_job(self, job_id, headers):
        return self._request("GET", f"/api/transport-jobs/{job_id}", headers=headers)

    def dispatch_transport_job(self, job_id, headers):
        return self._request("POST", f"/api/transport-jobs/{job_id}/dispatch", headers=headers)

    def delay_transport_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/transport-jobs/{job_id}/delay", payload, headers)

    def reschedule_transport_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/transport-jobs/{job_id}/reschedule", payload, headers)

    def deliver_transport_job(self, job_id, headers):
        return self._request("POST", f"/api/transport-jobs/{job_id}/deliver", headers=headers)

    def complete_set_transport_job(self, job_id, headers):
        return self._request("POST", f"/api/transport-jobs/{job_id}/complete-set", headers=headers)

    def cancel_transport_job(self, job_id, headers):
        return self._request("POST", f"/api/transport-jobs/{job_id}/cancel", headers=headers)

    # --- delay notices ---
    def create_order_delay_notice(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/delay-notices", payload, headers)

    def list_job_delay_notices(self, job_id, headers, params=None):
        return self._request("GET", f"/api/transport-jobs/{job_id}/delay-notices", headers=headers, params=params)

    def list_order_delay_notices(self, order_id, headers, params=None):
        return self._request("GET", f"/api/sales-orders/{order_id}/delay-notices", headers=headers, params=params)

    # --- title records ---
    def create_title_record(self, unit_id, payload, headers):
        return self._request("POST", f"/api/home-units/{unit_id}/title-records", payload, headers)

    def list_title_records(self, unit_id, headers, params=None):
        return self._request("GET", f"/api/home-units/{unit_id}/title-records", headers=headers, params=params)

    def get_title_record(self, title_id, headers):
        return self._request("GET", f"/api/title-records/{title_id}", headers=headers)

    def issue_title_record(self, title_id, headers):
        return self._request("POST", f"/api/title-records/{title_id}/issue", headers=headers)

    def convert_title_record(self, title_id, headers):
        return self._request("POST", f"/api/title-records/{title_id}/convert", headers=headers)

    def surrender_title_record(self, title_id, headers):
        return self._request("POST", f"/api/title-records/{title_id}/surrender", headers=headers)

    # --- warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/api/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/api/warranty-claims/{claim_id}", headers=headers)

    def list_unit_warranty_claims(self, unit_id, headers, params=None):
        return self._request("GET", f"/api/home-units/{unit_id}/warranty-claims", headers=headers, params=params)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/api/warranty-claims", headers=headers, params=params)

    def review_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/review", payload, headers)

    def resubmit_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/resubmit", payload, headers)

    def resolve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/resolve", headers=headers)

    # --- trade-in appraisals ---
    def create_trade_in_appraisal(self, order_id, payload, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/trade-in-appraisals", payload, headers)

    def list_order_trade_in_appraisals(self, order_id, headers, params=None):
        return self._request("GET", f"/api/sales-orders/{order_id}/trade-in-appraisals", headers=headers, params=params)

    def get_trade_in_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/api/trade-in-appraisals/{appraisal_id}", headers=headers)

    def list_trade_in_appraisals(self, headers, params=None):
        return self._request("GET", "/api/trade-in-appraisals", headers=headers, params=params)

    def list_unit_trade_in_appraisals(self, unit_id, headers, params=None):
        return self._request("GET", f"/api/home-units/{unit_id}/trade-in-appraisals", headers=headers, params=params)

    def inspect_trade_in_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/api/trade-in-appraisals/{appraisal_id}/inspect", payload, headers)

    def offer_trade_in_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/api/trade-in-appraisals/{appraisal_id}/offer", headers=headers)

    def decide_trade_in_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/api/trade-in-appraisals/{appraisal_id}/decide", payload, headers)

    def start_reconditioning(self, appraisal_id, headers):
        return self._request("POST", f"/api/trade-in-appraisals/{appraisal_id}/start-reconditioning", headers=headers)

    def complete_reconditioning(self, appraisal_id, headers):
        return self._request("POST", f"/api/trade-in-appraisals/{appraisal_id}/complete-reconditioning", headers=headers)


api_client = ApiClient()
