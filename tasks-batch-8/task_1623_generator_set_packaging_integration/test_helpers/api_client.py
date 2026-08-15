"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/genset-packaging/_clock/set_current_utc", payload, headers)

    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/genset-packaging/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/genset-packaging/customers/{customer_id}", headers=headers)

    # --- EngineModel ---
    def create_engine_model(self, payload, headers):
        return self._request("POST", "/genset-packaging/engine-models", payload, headers)

    def get_engine_model(self, engine_model_id, headers):
        return self._request("GET", f"/genset-packaging/engine-models/{engine_model_id}", headers=headers)

    # --- AlternatorModel ---
    def create_alternator_model(self, payload, headers):
        return self._request("POST", "/genset-packaging/alternator-models", payload, headers)

    def get_alternator_model(self, alternator_model_id, headers):
        return self._request("GET", f"/genset-packaging/alternator-models/{alternator_model_id}", headers=headers)

    # --- PackageOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/genset-packaging/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/genset-packaging/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/genset-packaging/orders", headers=headers, params=params)

    def authorize_order(self, order_id, payload, headers):
        return self._request("POST", f"/genset-packaging/orders/{order_id}/authorize", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/genset-packaging/orders/{order_id}/cancel", {}, headers)

    # --- SizingStudy ---
    def create_sizing_study(self, payload, headers):
        return self._request("POST", "/genset-packaging/sizing-studies", payload, headers)

    def get_sizing_study(self, study_id, headers):
        return self._request("GET", f"/genset-packaging/sizing-studies/{study_id}", headers=headers)

    def list_sizing_studies(self, headers, params=None):
        return self._request("GET", "/genset-packaging/sizing-studies", headers=headers, params=params)

    def submit_sizing_study(self, study_id, headers):
        return self._request("POST", f"/genset-packaging/sizing-studies/{study_id}/submit", {}, headers)

    def approve_sizing_study(self, study_id, headers):
        return self._request("POST", f"/genset-packaging/sizing-studies/{study_id}/approve", {}, headers)

    def reject_sizing_study(self, study_id, payload, headers):
        return self._request("POST", f"/genset-packaging/sizing-studies/{study_id}/reject", payload, headers)

    # --- PackageConfiguration ---
    def create_configuration(self, payload, headers):
        return self._request("POST", "/genset-packaging/configurations", payload, headers)

    def get_configuration(self, configuration_id, headers):
        return self._request("GET", f"/genset-packaging/configurations/{configuration_id}", headers=headers)

    def list_configurations(self, headers, params=None):
        return self._request("GET", "/genset-packaging/configurations", headers=headers, params=params)

    def lock_configuration(self, configuration_id, headers):
        return self._request("POST", f"/genset-packaging/configurations/{configuration_id}/lock", {}, headers)

    def unlock_configuration(self, configuration_id, headers):
        return self._request("POST", f"/genset-packaging/configurations/{configuration_id}/unlock", {}, headers)

    # --- PermitCase ---
    def create_permit_case(self, payload, headers):
        return self._request("POST", "/genset-packaging/permit-cases", payload, headers)

    def get_permit_case(self, permit_id, headers):
        return self._request("GET", f"/genset-packaging/permit-cases/{permit_id}", headers=headers)

    def list_permit_cases(self, headers, params=None):
        return self._request("GET", "/genset-packaging/permit-cases", headers=headers, params=params)

    def submit_permit_case(self, permit_id, headers):
        return self._request("POST", f"/genset-packaging/permit-cases/{permit_id}/submit", {}, headers)

    def request_permit_correction(self, permit_id, headers):
        return self._request("POST", f"/genset-packaging/permit-cases/{permit_id}/request-correction", {}, headers)

    def approve_permit_ahj(self, permit_id, headers):
        return self._request("POST", f"/genset-packaging/permit-cases/{permit_id}/approve-ahj", {}, headers)

    def withdraw_permit_case(self, permit_id, headers):
        return self._request("POST", f"/genset-packaging/permit-cases/{permit_id}/withdraw", {}, headers)

    def expire_check_permit(self, permit_id, headers):
        return self._request("POST", f"/genset-packaging/permit-cases/{permit_id}/expire-check", {}, headers)

    # --- EmissionsCertificate ---
    def create_emissions_certificate(self, payload, headers):
        return self._request("POST", "/genset-packaging/emissions-certificates", payload, headers)

    def get_emissions_certificate(self, certificate_id, headers):
        return self._request("GET", f"/genset-packaging/emissions-certificates/{certificate_id}", headers=headers)

    def list_emissions_certificates(self, headers, params=None):
        return self._request("GET", "/genset-packaging/emissions-certificates", headers=headers, params=params)

    def submit_emissions_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/genset-packaging/emissions-certificates/{certificate_id}/submit", payload, headers)

    def issue_emissions_certificate(self, certificate_id, headers):
        return self._request("POST", f"/genset-packaging/emissions-certificates/{certificate_id}/issue", {}, headers)

    def reject_emissions_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/genset-packaging/emissions-certificates/{certificate_id}/reject", payload, headers)

    # --- ParallelingScheme ---
    def create_paralleling_scheme(self, payload, headers):
        return self._request("POST", "/genset-packaging/paralleling-schemes", payload, headers)

    def get_paralleling_scheme(self, scheme_id, headers):
        return self._request("GET", f"/genset-packaging/paralleling-schemes/{scheme_id}", headers=headers)

    def list_paralleling_schemes(self, headers, params=None):
        return self._request("GET", "/genset-packaging/paralleling-schemes", headers=headers, params=params)

    def add_scheme_position(self, scheme_id, payload, headers):
        return self._request("POST", f"/genset-packaging/paralleling-schemes/{scheme_id}/positions", payload, headers)

    def program_scheme(self, scheme_id, payload, headers):
        return self._request("POST", f"/genset-packaging/paralleling-schemes/{scheme_id}/program", payload, headers)

    def rework_scheme(self, scheme_id, headers):
        return self._request("POST", f"/genset-packaging/paralleling-schemes/{scheme_id}/rework", {}, headers)

    def verify_scheme(self, scheme_id, headers):
        return self._request("POST", f"/genset-packaging/paralleling-schemes/{scheme_id}/verify", {}, headers)

    # --- TestBay ---
    def create_test_bay(self, payload, headers):
        return self._request("POST", "/genset-packaging/test-bays", payload, headers)

    def get_test_bay(self, test_bay_id, headers):
        return self._request("GET", f"/genset-packaging/test-bays/{test_bay_id}", headers=headers)

    # --- FactoryTest ---
    def create_factory_test(self, payload, headers):
        return self._request("POST", "/genset-packaging/factory-tests", payload, headers)

    def get_factory_test(self, test_id, headers):
        return self._request("GET", f"/genset-packaging/factory-tests/{test_id}", headers=headers)

    def list_factory_tests(self, headers, params=None):
        return self._request("GET", "/genset-packaging/factory-tests", headers=headers, params=params)

    def start_factory_test(self, test_id, headers):
        return self._request("POST", f"/genset-packaging/factory-tests/{test_id}/start", {}, headers)

    def record_factory_test(self, test_id, payload, headers):
        return self._request("POST", f"/genset-packaging/factory-tests/{test_id}/record", payload, headers)

    def accept_factory_test(self, test_id, headers):
        return self._request("POST", f"/genset-packaging/factory-tests/{test_id}/accept", {}, headers)

    # --- CraneSlot ---
    def create_crane_slot(self, payload, headers):
        return self._request("POST", "/genset-packaging/crane-slots", payload, headers)

    def get_crane_slot(self, crane_slot_id, headers):
        return self._request("GET", f"/genset-packaging/crane-slots/{crane_slot_id}", headers=headers)

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/genset-packaging/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/genset-packaging/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/genset-packaging/shipments", headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/genset-packaging/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/genset-packaging/shipments/{shipment_id}/deliver", {}, headers)

    def release_shipment(self, shipment_id, headers):
        return self._request("POST", f"/genset-packaging/shipments/{shipment_id}/release", {}, headers)

    # --- CommissioningEvent ---
    def create_commissioning_event(self, payload, headers):
        return self._request("POST", "/genset-packaging/commissioning-events", payload, headers)

    def get_commissioning_event(self, event_id, headers):
        return self._request("GET", f"/genset-packaging/commissioning-events/{event_id}", headers=headers)

    def list_commissioning_events(self, headers, params=None):
        return self._request("GET", "/genset-packaging/commissioning-events", headers=headers, params=params)

    def assign_commissioning_event(self, event_id, payload, headers):
        return self._request("POST", f"/genset-packaging/commissioning-events/{event_id}/assign", payload, headers)

    def start_commissioning_event(self, event_id, headers):
        return self._request("POST", f"/genset-packaging/commissioning-events/{event_id}/start", {}, headers)

    def complete_commissioning_event(self, event_id, payload, headers):
        return self._request("POST", f"/genset-packaging/commissioning-events/{event_id}/complete", payload, headers)

    def accept_commissioning_event(self, event_id, headers):
        return self._request("POST", f"/genset-packaging/commissioning-events/{event_id}/accept", {}, headers)

    # --- ServiceContract ---
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/genset-packaging/service-contracts", payload, headers)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/genset-packaging/service-contracts/{contract_id}", headers=headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/genset-packaging/service-contracts", headers=headers, params=params)

    def bind_service_contract(self, contract_id, headers):
        return self._request("POST", f"/genset-packaging/service-contracts/{contract_id}/bind", {}, headers)

    def activate_service_contract(self, contract_id, headers):
        return self._request("POST", f"/genset-packaging/service-contracts/{contract_id}/activate", {}, headers)

    def cancel_service_contract(self, contract_id, headers):
        return self._request("POST", f"/genset-packaging/service-contracts/{contract_id}/cancel", {}, headers)

    def lapse_check_service_contract(self, contract_id, headers):
        return self._request("POST", f"/genset-packaging/service-contracts/{contract_id}/lapse-check", {}, headers)


api_client = ApiClient()
