"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- staff / patients / formulary ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/pharmacy/staff", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/pharmacy/staff/{staff_id}", headers=headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/pharmacy/staff", headers=headers, params=params)

    def create_patient(self, payload, headers):
        return self._request("POST", "/pharmacy/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/pharmacy/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"/pharmacy/patients/{patient_id}", payload, headers)

    def create_drug_product(self, payload, headers):
        return self._request("POST", "/pharmacy/drug-products", payload, headers)

    def get_drug_product(self, drug_id, headers):
        return self._request("GET", f"/pharmacy/drug-products/{drug_id}", headers=headers)

    def list_drug_products(self, headers, params=None):
        return self._request("GET", "/pharmacy/drug-products", headers=headers, params=params)

    def update_drug_product(self, drug_id, payload, headers):
        return self._request("PATCH", f"/pharmacy/drug-products/{drug_id}", payload, headers)

    def list_drug_substitution_protocols(self, drug_id, headers):
        return self._request(
            "GET", f"/pharmacy/drug-products/{drug_id}/substitution-protocols",
            headers=headers,
        )

    def create_hood(self, payload, headers):
        return self._request("POST", "/pharmacy/hoods", payload, headers)

    def get_hood(self, hood_id, headers):
        return self._request("GET", f"/pharmacy/hoods/{hood_id}", headers=headers)

    def list_hoods(self, headers, params=None):
        return self._request("GET", "/pharmacy/hoods", headers=headers, params=params)

    # --- orders ---
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/pharmacy/medication-orders", payload, headers)

    def get_medication_order(self, order_id, headers):
        return self._request("GET", f"/pharmacy/medication-orders/{order_id}", headers=headers)

    def list_medication_orders(self, headers, params=None):
        return self._request("GET", "/pharmacy/medication-orders", headers=headers, params=params)

    def verify_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/medication-orders/{order_id}/verify", payload, headers
        )

    def resume_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/medication-orders/{order_id}/resume", payload, headers
        )

    def discontinue_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/medication-orders/{order_id}/discontinue", payload, headers
        )

    def administer_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/medication-orders/{order_id}/administer", payload, headers
        )

    def create_intervention(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/medication-orders/{order_id}/interventions", payload, headers
        )

    def list_order_interventions(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/pharmacy/medication-orders/{order_id}/interventions",
            headers=headers, params=params,
        )

    def get_intervention(self, intervention_id, headers):
        return self._request("GET", f"/pharmacy/interventions/{intervention_id}", headers=headers)

    def list_interventions(self, headers, params=None):
        return self._request("GET", "/pharmacy/interventions", headers=headers, params=params)

    def substitute_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/medication-orders/{order_id}/substitute", payload, headers
        )

    # --- hood sessions & coverage ---
    def create_hood_session(self, payload, headers):
        return self._request("POST", "/pharmacy/hood-sessions", payload, headers)

    def get_hood_session(self, session_id, headers):
        return self._request("GET", f"/pharmacy/hood-sessions/{session_id}", headers=headers)

    def list_hood_sessions(self, headers, params=None):
        return self._request("GET", "/pharmacy/hood-sessions", headers=headers, params=params)

    def start_hood_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/hood-sessions/{session_id}/start", payload or {}, headers
        )

    def complete_hood_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/hood-sessions/{session_id}/complete", payload or {}, headers
        )

    def cancel_hood_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/hood-sessions/{session_id}/cancel", payload or {}, headers
        )

    def create_coverage_shift(self, payload, headers):
        return self._request("POST", "/pharmacy/coverage-shifts", payload, headers)

    def get_coverage_shift(self, shift_id, headers):
        return self._request("GET", f"/pharmacy/coverage-shifts/{shift_id}", headers=headers)

    def list_coverage_shifts(self, headers, params=None):
        return self._request("GET", "/pharmacy/coverage-shifts", headers=headers, params=params)

    # --- batches & preparations ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/pharmacy/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/pharmacy/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/pharmacy/batches", headers=headers, params=params)

    def start_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/pharmacy/batches/{batch_id}/start", payload or {}, headers)

    def complete_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/pharmacy/batches/{batch_id}/complete", payload, headers)

    def qa_release_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/batches/{batch_id}/qa-release", payload or {}, headers
        )

    def qa_reject_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/pharmacy/batches/{batch_id}/qa-reject", payload, headers)

    def rework_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/pharmacy/batches/{batch_id}/rework", payload or {}, headers)

    def list_batch_preparations(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/pharmacy/batches/{batch_id}/preparations", headers=headers, params=params
        )

    def list_batch_waste_records(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/pharmacy/batches/{batch_id}/waste-records", headers=headers, params=params
        )

    def get_preparation(self, preparation_id, headers):
        return self._request("GET", f"/pharmacy/preparations/{preparation_id}", headers=headers)

    def list_preparations(self, headers, params=None):
        return self._request("GET", "/pharmacy/preparations", headers=headers, params=params)

    # --- ADC stations, pockets, ledger ---
    def create_adc_station(self, payload, headers):
        return self._request("POST", "/pharmacy/adc-stations", payload, headers)

    def get_adc_station(self, station_id, headers):
        return self._request("GET", f"/pharmacy/adc-stations/{station_id}", headers=headers)

    def list_adc_stations(self, headers, params=None):
        return self._request("GET", "/pharmacy/adc-stations", headers=headers, params=params)

    def create_adc_pocket(self, station_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/adc-stations/{station_id}/pockets", payload, headers
        )

    def list_station_pockets(self, station_id, headers, params=None):
        return self._request(
            "GET", f"/pharmacy/adc-stations/{station_id}/pockets", headers=headers, params=params
        )

    def get_adc_pocket(self, pocket_id, headers):
        return self._request("GET", f"/pharmacy/adc-pockets/{pocket_id}", headers=headers)

    def list_adc_pockets(self, headers, params=None):
        return self._request("GET", "/pharmacy/adc-pockets", headers=headers, params=params)

    def restock_pocket(self, pocket_id, payload, headers):
        return self._request("POST", f"/pharmacy/adc-pockets/{pocket_id}/restock", payload, headers)

    def dispense_pocket(self, pocket_id, payload, headers):
        return self._request("POST", f"/pharmacy/adc-pockets/{pocket_id}/dispense", payload, headers)

    def return_pocket(self, pocket_id, payload, headers):
        return self._request("POST", f"/pharmacy/adc-pockets/{pocket_id}/return", payload, headers)

    def waste_pocket(self, pocket_id, payload, headers):
        return self._request("POST", f"/pharmacy/adc-pockets/{pocket_id}/waste", payload, headers)

    def count_pocket(self, pocket_id, payload, headers):
        return self._request("POST", f"/pharmacy/adc-pockets/{pocket_id}/count", payload, headers)

    def quarantine_pocket(self, pocket_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/adc-pockets/{pocket_id}/quarantine", payload or {}, headers
        )

    def release_pocket_quarantine(self, pocket_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/adc-pockets/{pocket_id}/release-quarantine",
            payload or {}, headers,
        )

    def list_pocket_events(self, pocket_id, headers, params=None):
        return self._request(
            "GET", f"/pharmacy/adc-pockets/{pocket_id}/events", headers=headers, params=params
        )

    def list_pocket_discrepancy_cases(self, pocket_id, headers, params=None):
        return self._request(
            "GET", f"/pharmacy/adc-pockets/{pocket_id}/discrepancy-cases",
            headers=headers, params=params,
        )

    def get_inventory_event(self, event_id, headers):
        return self._request("GET", f"/pharmacy/inventory-events/{event_id}", headers=headers)

    def list_inventory_events(self, headers, params=None):
        return self._request("GET", "/pharmacy/inventory-events", headers=headers, params=params)

    # --- discrepancy & diversion ---
    def get_discrepancy_case(self, case_id, headers):
        return self._request("GET", f"/pharmacy/discrepancy-cases/{case_id}", headers=headers)

    def list_discrepancy_cases(self, headers, params=None):
        return self._request("GET", "/pharmacy/discrepancy-cases", headers=headers, params=params)

    def investigate_discrepancy_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/discrepancy-cases/{case_id}/investigate", payload or {}, headers
        )

    def resolve_discrepancy_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/discrepancy-cases/{case_id}/resolve", payload, headers
        )

    def create_diversion_case(self, payload, headers):
        return self._request("POST", "/pharmacy/diversion-cases", payload, headers)

    def get_diversion_case(self, case_id, headers):
        return self._request("GET", f"/pharmacy/diversion-cases/{case_id}", headers=headers)

    def list_diversion_cases(self, headers, params=None):
        return self._request("GET", "/pharmacy/diversion-cases", headers=headers, params=params)

    def review_diversion_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/diversion-cases/{case_id}/review", payload or {}, headers
        )

    def adjudicate_diversion_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/pharmacy/diversion-cases/{case_id}/adjudicate", payload, headers
        )

    def evaluate_diversion_risk(self, payload, headers):
        return self._request("POST", "/pharmacy/diversion-risk/evaluate", payload, headers)

    # --- substitution protocols ---
    def create_substitution_protocol(self, payload, headers):
        return self._request("POST", "/pharmacy/substitution-protocols", payload, headers)

    def get_substitution_protocol(self, protocol_id, headers):
        return self._request(
            "GET", f"/pharmacy/substitution-protocols/{protocol_id}", headers=headers
        )

    def list_substitution_protocols(self, headers, params=None):
        return self._request("GET", "/pharmacy/substitution-protocols", headers=headers, params=params)

    def activate_substitution_protocol(self, protocol_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/substitution-protocols/{protocol_id}/activate",
            payload or {}, headers,
        )

    def revoke_substitution_protocol(self, protocol_id, headers, payload=None):
        return self._request(
            "POST", f"/pharmacy/substitution-protocols/{protocol_id}/revoke",
            payload or {}, headers,
        )

    # --- waste records ---
    def get_waste_record(self, record_id, headers):
        return self._request("GET", f"/pharmacy/waste-records/{record_id}", headers=headers)

    def list_waste_records(self, headers, params=None):
        return self._request("GET", "/pharmacy/waste-records", headers=headers, params=params)

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pharmacy/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
