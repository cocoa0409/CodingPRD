"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/toll-operations/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/toll-operations/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/toll-operations/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/toll-operations/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/toll-operations/customers/{customer_id}/reinstate", {}, headers)

    def terminate_customer(self, customer_id, headers):
        return self._request("POST", f"/toll-operations/customers/{customer_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Pricing agreements
    # ------------------------------------------------------------------
    def create_pricing_agreement(self, customer_id, payload, headers):
        return self._request("POST", f"/toll-operations/customers/{customer_id}/pricing-agreements",
                             payload, headers)

    def list_pricing_agreements(self, customer_id, headers, params=None):
        return self._request("GET", f"/toll-operations/customers/{customer_id}/pricing-agreements",
                             headers=headers, params=params)

    def get_pricing_agreement(self, customer_id, agreement_id, headers):
        return self._request(
            "GET",
            f"/toll-operations/customers/{customer_id}/pricing-agreements/{agreement_id}",
            headers=headers)

    def activate_pricing_agreement(self, customer_id, agreement_id, expected_version, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/pricing-agreements/{agreement_id}/activate",
            {"expected_pricing_agreement_version": expected_version}, headers)

    def terminate_pricing_agreement(self, customer_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/pricing-agreements/{agreement_id}/terminate",
            {}, headers)

    # ------------------------------------------------------------------
    # Raw material lots
    # ------------------------------------------------------------------
    def create_lot(self, customer_id, payload, headers):
        return self._request("POST", f"/toll-operations/customers/{customer_id}/raw-material-lots",
                             payload, headers)

    def list_lots(self, customer_id, headers, params=None):
        return self._request("GET", f"/toll-operations/customers/{customer_id}/raw-material-lots",
                             headers=headers, params=params)

    def get_lot(self, customer_id, lot_id, headers):
        return self._request(
            "GET", f"/toll-operations/customers/{customer_id}/raw-material-lots/{lot_id}",
            headers=headers)

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------
    def create_recipe(self, payload, headers):
        return self._request("POST", "/toll-operations/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/toll-operations/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/toll-operations/recipes/{recipe_id}", headers=headers)

    def approve_recipe(self, recipe_id, headers):
        return self._request("POST", f"/toll-operations/recipes/{recipe_id}/approve", {}, headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/toll-operations/recipes/{recipe_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Tanks
    # ------------------------------------------------------------------
    def create_tank(self, payload, headers):
        return self._request("POST", "/toll-operations/tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/toll-operations/tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/toll-operations/tanks/{tank_id}", headers=headers)

    # ------------------------------------------------------------------
    # Cleaning records
    # ------------------------------------------------------------------
    def create_cleaning_record(self, tank_id, payload, headers):
        return self._request("POST", f"/toll-operations/tanks/{tank_id}/cleaning-records",
                             payload, headers)

    def list_cleaning_records(self, tank_id, headers, params=None):
        return self._request("GET", f"/toll-operations/tanks/{tank_id}/cleaning-records",
                             headers=headers, params=params)

    def get_cleaning_record(self, tank_id, record_id, headers):
        return self._request(
            "GET", f"/toll-operations/tanks/{tank_id}/cleaning-records/{record_id}",
            headers=headers)

    def submit_cleaning_record(self, tank_id, record_id, headers):
        return self._request(
            "POST", f"/toll-operations/tanks/{tank_id}/cleaning-records/{record_id}/submit",
            {}, headers)

    def validate_cleaning_record(self, tank_id, record_id, decision, headers):
        return self._request(
            "POST", f"/toll-operations/tanks/{tank_id}/cleaning-records/{record_id}/validate",
            {"decision": decision}, headers)

    # ------------------------------------------------------------------
    # Batch jobs
    # ------------------------------------------------------------------
    def create_batch_job(self, customer_id, payload, headers):
        return self._request("POST", f"/toll-operations/customers/{customer_id}/batch-jobs",
                             payload, headers)

    def list_batch_jobs(self, customer_id, headers, params=None):
        return self._request("GET", f"/toll-operations/customers/{customer_id}/batch-jobs",
                             headers=headers, params=params)

    def get_batch_job(self, customer_id, batch_job_id, headers):
        return self._request(
            "GET", f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}",
            headers=headers)

    def release_batch_job(self, customer_id, batch_job_id, expected_version, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/release",
            {"expected_batch_job_version": expected_version}, headers)

    def start_charging(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/start-charging",
            {}, headers)

    def start_mixing(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/start-mixing",
            {}, headers)

    def hold_for_qa(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/hold-for-qa",
            {}, headers)

    def complete_batch_job(self, customer_id, batch_job_id, actual_output_kg, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/complete",
            {"actual_output_kg": actual_output_kg}, headers)

    def reject_qa_batch_job(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/reject-qa",
            {}, headers)

    def cancel_batch_job(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Batch charges
    # ------------------------------------------------------------------
    def create_batch_charge(self, customer_id, batch_job_id, payload, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/batch-charges",
            payload, headers)

    def list_batch_charges(self, customer_id, batch_job_id, headers, params=None):
        return self._request(
            "GET",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/batch-charges",
            headers=headers, params=params)

    def get_batch_charge(self, customer_id, batch_job_id, charge_id, headers):
        return self._request(
            "GET",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/batch-charges/{charge_id}",
            headers=headers)

    # ------------------------------------------------------------------
    # SDS documents
    # ------------------------------------------------------------------
    def create_sds(self, customer_id, batch_job_id, payload, headers):
        return self._request(
            "POST", f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/sds",
            payload, headers)

    def list_sds(self, customer_id, batch_job_id, headers):
        return self._request(
            "GET", f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/sds",
            headers=headers)

    def issue_sds(self, customer_id, batch_job_id, sds_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/sds/{sds_id}/issue",
            {}, headers)

    # ------------------------------------------------------------------
    # Package configuration
    # ------------------------------------------------------------------
    def create_package_config(self, customer_id, batch_job_id, payload, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/package-config",
            payload, headers)

    def get_package_config(self, customer_id, batch_job_id, headers):
        return self._request(
            "GET",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/package-config",
            headers=headers)

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def create_shipment(self, customer_id, batch_job_id, payload, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/shipment",
            payload, headers)

    def get_shipment(self, customer_id, batch_job_id, headers):
        return self._request(
            "GET",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/shipment",
            headers=headers)

    def start_loading(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/shipment/start-loading",
            {}, headers)

    def dispatch_shipment(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/shipment/dispatch",
            {}, headers)

    def cancel_shipment(self, customer_id, batch_job_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/shipment/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Heel disposal records
    # ------------------------------------------------------------------
    def create_heel_disposal(self, customer_id, batch_job_id, payload, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/heel-disposals",
            payload, headers)

    def list_heel_disposals(self, customer_id, batch_job_id, headers, params=None):
        return self._request(
            "GET",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/heel-disposals",
            headers=headers, params=params)

    def post_heel_disposal(self, customer_id, batch_job_id, record_id, headers):
        return self._request(
            "POST",
            f"/toll-operations/customers/{customer_id}/batch-jobs/{batch_job_id}/heel-disposals/{record_id}/post",
            {}, headers)

    # ------------------------------------------------------------------
    # Top-level collections (bare-id reachability)
    # ------------------------------------------------------------------
    def get_batch_job_by_id(self, batch_job_id, headers):
        return self._request("GET", f"/toll-operations/batch-jobs/{batch_job_id}", headers=headers)

    def list_all_batch_jobs(self, headers, params=None):
        return self._request("GET", "/toll-operations/batch-jobs", headers=headers, params=params)

    def get_batch_charge_by_id(self, charge_id, headers):
        return self._request("GET", f"/toll-operations/batch-charges/{charge_id}", headers=headers)

    def list_all_batch_charges(self, headers, params=None):
        return self._request("GET", "/toll-operations/batch-charges", headers=headers, params=params)

    def get_sds_document(self, sds_id, headers):
        return self._request("GET", f"/toll-operations/sds-documents/{sds_id}", headers=headers)

    def list_sds_documents(self, headers, params=None):
        return self._request("GET", "/toll-operations/sds-documents", headers=headers, params=params)

    def get_package_config_by_id(self, package_config_id, headers):
        return self._request("GET", f"/toll-operations/package-configs/{package_config_id}",
                             headers=headers)

    def list_package_configs(self, headers, params=None):
        return self._request("GET", "/toll-operations/package-configs", headers=headers,
                             params=params)

    def get_shipment_by_id(self, shipment_id, headers):
        return self._request("GET", f"/toll-operations/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/toll-operations/shipments", headers=headers, params=params)

    def get_heel_disposal_by_id(self, record_id, headers):
        return self._request("GET", f"/toll-operations/heel-disposals/{record_id}", headers=headers)

    def list_heel_disposal_records(self, headers, params=None):
        return self._request("GET", "/toll-operations/heel-disposals", headers=headers,
                             params=params)


api_client = ApiClient()
