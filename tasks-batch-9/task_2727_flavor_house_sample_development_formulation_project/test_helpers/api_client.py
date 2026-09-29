"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Flavour house sample development API surface."""

    # ---- Customer briefs -------------------------------------------------

    def create_customer_brief(self, payload, headers):
        return self._request("POST", "/customer-briefs", payload, headers)

    def list_customer_briefs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/customer-briefs", headers=headers, params=params)

    def get_customer_brief(self, brief_id, headers):
        return self._request("GET", f"/customer-briefs/{brief_id}", headers=headers)

    def submit_customer_brief(self, brief_id, headers, payload=None):
        return self._request("POST", f"/customer-briefs/{brief_id}/submit",
                             payload if payload is not None else {}, headers)

    def request_brief_clarification(self, brief_id, payload, headers):
        return self._request("POST", f"/customer-briefs/{brief_id}/clarification-request",
                             payload, headers)

    def decide_customer_brief(self, brief_id, payload, headers):
        return self._request("POST", f"/customer-briefs/{brief_id}/decision",
                             payload, headers)

    def close_customer_brief(self, brief_id, payload, headers):
        return self._request("POST", f"/customer-briefs/{brief_id}/close",
                             payload, headers)

    # ---- Raw materials ---------------------------------------------------

    def create_raw_material(self, payload, headers):
        return self._request("POST", "/raw-materials", payload, headers)

    def list_raw_materials(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/raw-materials", headers=headers, params=params)

    def get_raw_material(self, material_id, headers):
        return self._request("GET", f"/raw-materials/{material_id}", headers=headers)

    def reprice_raw_material(self, material_id, payload, headers):
        return self._request("PATCH", f"/raw-materials/{material_id}", payload, headers)

    # ---- Substantiation records -----------------------------------------

    def create_substantiation_record(self, payload, headers):
        return self._request("POST", "/substantiation-records", payload, headers)

    def list_substantiation_records(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/substantiation-records",
                             headers=headers, params=params)

    def get_substantiation_record(self, record_id, headers):
        return self._request("GET", f"/substantiation-records/{record_id}",
                             headers=headers)

    def verify_substantiation_record(self, record_id, headers, payload=None):
        return self._request("POST", f"/substantiation-records/{record_id}/verify",
                             payload if payload is not None else {}, headers)

    def revoke_substantiation_record(self, record_id, payload, headers):
        return self._request("POST", f"/substantiation-records/{record_id}/revoke",
                             payload, headers)

    # ---- Formulas --------------------------------------------------------

    def create_formula(self, payload, headers):
        return self._request("POST", "/formulas", payload, headers)

    def list_formulas(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/formulas/{formula_id}", headers=headers)

    def get_formula_composition(self, formula_id, headers,
                                grant_id: Optional[str] = None,
                                disclose_full: Optional[bool] = None):
        params: Dict[str, Any] = {}
        if grant_id is not None:
            params["grant_id"] = grant_id
        if disclose_full is not None:
            params["disclose_full"] = "true" if disclose_full else "false"
        return self._request("GET", f"/formulas/{formula_id}/composition",
                             headers=headers, params=params or None)

    def add_formula_component(self, formula_id, payload, headers):
        return self._request("POST", f"/formulas/{formula_id}/components",
                             payload, headers)

    def cost_formula(self, formula_id, headers, payload=None):
        return self._request("POST", f"/formulas/{formula_id}/cost",
                             payload if payload is not None else {}, headers)

    def submit_formula(self, formula_id, headers, payload=None):
        return self._request("POST", f"/formulas/{formula_id}/submit",
                             payload if payload is not None else {}, headers)

    def decide_formula(self, formula_id, payload, headers):
        return self._request("POST", f"/formulas/{formula_id}/decision",
                             payload, headers)

    def create_formula_revision(self, formula_id, payload, headers):
        return self._request("POST", f"/formulas/{formula_id}/revisions",
                             payload, headers)

    # ---- Formula components ---------------------------------------------

    def list_formula_components(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/formula-components",
                             headers=headers, params=params)

    def get_formula_component(self, component_id, headers):
        return self._request("GET", f"/formula-components/{component_id}",
                             headers=headers)

    def delete_formula_component(self, component_id, headers):
        return self._request("DELETE", f"/formula-components/{component_id}",
                             headers=headers)

    # ---- Sample lots -----------------------------------------------------

    def create_sample_lot(self, payload, headers):
        return self._request("POST", "/sample-lots", payload, headers)

    def list_sample_lots(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/sample-lots", headers=headers, params=params)

    def get_sample_lot(self, lot_id, headers):
        return self._request("GET", f"/sample-lots/{lot_id}", headers=headers)

    def record_lot_qc(self, lot_id, payload, headers):
        return self._request("POST", f"/sample-lots/{lot_id}/qc", payload, headers)

    def release_sample_lot(self, lot_id, headers, payload=None):
        return self._request("POST", f"/sample-lots/{lot_id}/release",
                             payload if payload is not None else {}, headers)

    # ---- Retention cabinets ---------------------------------------------

    def create_retention_cabinet(self, payload, headers):
        return self._request("POST", "/retention-cabinets", payload, headers)

    def list_retention_cabinets(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/retention-cabinets",
                             headers=headers, params=params)

    def get_retention_cabinet(self, cabinet_id, headers):
        return self._request("GET", f"/retention-cabinets/{cabinet_id}",
                             headers=headers)

    # ---- Retention samples ----------------------------------------------

    def create_retention_sample(self, payload, headers):
        return self._request("POST", "/retention-samples", payload, headers)

    def list_retention_samples(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/retention-samples",
                             headers=headers, params=params)

    def get_retention_sample(self, retention_id, headers):
        return self._request("GET", f"/retention-samples/{retention_id}",
                             headers=headers)

    def withdraw_retention_sample(self, retention_id, payload, headers):
        return self._request("POST", f"/retention-samples/{retention_id}/withdraw",
                             payload, headers)

    # ---- Application rigs ------------------------------------------------

    def create_application_rig(self, payload, headers):
        return self._request("POST", "/application-rigs", payload, headers)

    def list_application_rigs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/application-rigs", headers=headers, params=params)

    def get_application_rig(self, rig_id, headers):
        return self._request("GET", f"/application-rigs/{rig_id}", headers=headers)

    # ---- Application tests -----------------------------------------------

    def create_application_test(self, payload, headers):
        return self._request("POST", "/application-tests", payload, headers)

    def list_application_tests(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/application-tests",
                             headers=headers, params=params)

    def get_application_test(self, test_id, headers):
        return self._request("GET", f"/application-tests/{test_id}", headers=headers)

    def start_application_test(self, test_id, headers, payload=None):
        return self._request("POST", f"/application-tests/{test_id}/start",
                             payload if payload is not None else {}, headers)

    def record_application_test_result(self, test_id, payload, headers):
        return self._request("POST", f"/application-tests/{test_id}/result",
                             payload, headers)

    # ---- Shipments -------------------------------------------------------

    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def assemble_shipment_packet(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/shipments/{shipment_id}/assemble-packet",
                             payload if payload is not None else {}, headers)

    def dispatch_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch",
                             payload, headers)

    def cancel_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel",
                             payload, headers)

    # ---- Regulatory documents -------------------------------------------

    def list_regulatory_documents(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/regulatory-documents",
                             headers=headers, params=params)

    def get_regulatory_document(self, document_id, headers):
        return self._request("GET", f"/regulatory-documents/{document_id}",
                             headers=headers)

    # ---- Scale-up batches ------------------------------------------------

    def create_scale_up_batch(self, payload, headers):
        return self._request("POST", "/scale-up-batches", payload, headers)

    def list_scale_up_batches(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/scale-up-batches", headers=headers, params=params)

    def get_scale_up_batch(self, batch_id, headers):
        return self._request("GET", f"/scale-up-batches/{batch_id}", headers=headers)

    def set_batch_tolerance(self, batch_id, headers, payload=None):
        return self._request("POST", f"/scale-up-batches/{batch_id}/tolerance",
                             payload if payload is not None else {}, headers)

    def report_batch_pilot_run(self, batch_id, payload, headers):
        return self._request("POST", f"/scale-up-batches/{batch_id}/pilot-run",
                             payload, headers)

    def decide_scale_up_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/scale-up-batches/{batch_id}/decision",
                             payload, headers)

    # ---- Commercialization forecasts ------------------------------------

    def create_commercialization_forecast(self, payload, headers):
        return self._request("POST", "/commercialization-forecasts", payload, headers)

    def list_commercialization_forecasts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/commercialization-forecasts",
                             headers=headers, params=params)

    def get_commercialization_forecast(self, forecast_id, headers):
        return self._request("GET", f"/commercialization-forecasts/{forecast_id}",
                             headers=headers)

    # ---- Disclosure grants -----------------------------------------------

    def create_disclosure_grant(self, payload, headers):
        return self._request("POST", "/disclosure-grants", payload, headers)

    def list_disclosure_grants(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/disclosure-grants", headers=headers, params=params)

    def get_disclosure_grant(self, grant_id, headers):
        return self._request("GET", f"/disclosure-grants/{grant_id}", headers=headers)

    # ---- Logical clock ---------------------------------------------------

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Raw escape hatch for header-less / unknown-role probes ----------

    def raw_request(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
