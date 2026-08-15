"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Facility + attestation/enforcement ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/transparency/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/transparency/facilities/{facility_id}",
                             headers=headers)

    def submit_attestation(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/transparency/facilities/{facility_id}/submit-attestation",
            payload, headers)

    def cms_decision(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/transparency/facilities/{facility_id}/cms-decision",
            payload, headers)

    def submit_plan(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/transparency/facilities/{facility_id}/submit-plan",
            payload, headers)

    # --- Payer ---
    def create_payer(self, payload, headers):
        return self._request("POST", "/transparency/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/transparency/payers/{payer_id}",
                             headers=headers)

    def list_payer_contracts(self, payer_id, headers, params=None):
        return self._request("GET",
                             f"/transparency/payers/{payer_id}/payer-contracts",
                             headers=headers, params=params)

    # --- PayerContract ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/transparency/payer-contracts", payload,
                             headers)

    def list_facility_contracts(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/transparency/facilities/{facility_id}/payer-contracts",
            headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/transparency/payer-contracts/{contract_id}/activate",
            headers=headers)

    def renegotiate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/transparency/payer-contracts/{contract_id}/renegotiate",
            payload, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/transparency/payer-contracts/{contract_id}/terminate",
            headers=headers)

    # --- ServiceItem ---
    def create_service_item(self, payload, headers):
        return self._request("POST", "/transparency/service-items", payload,
                             headers)

    def list_service_items(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/transparency/facilities/{facility_id}/service-items",
            headers=headers, params=params)

    def patch_service_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/transparency/service-items/{item_id}",
                             payload, headers)

    # --- StandardChargeRecord ---
    def create_charge_record(self, payload, headers):
        return self._request("POST", "/transparency/standard-charge-records",
                             payload, headers)

    def get_charge_record(self, record_id, headers):
        return self._request(
            "GET", f"/transparency/standard-charge-records/{record_id}",
            headers=headers)

    def list_charge_records(self, headers, params=None):
        return self._request("GET", "/transparency/standard-charge-records",
                             headers=headers, params=params)

    def validate_charge_record(self, record_id, headers):
        return self._request(
            "POST",
            f"/transparency/standard-charge-records/{record_id}/validate",
            headers=headers)

    # --- PayerNegotiatedRate ---
    def create_rate(self, payload, headers):
        return self._request("POST", "/transparency/payer-negotiated-rates",
                             payload, headers)

    def get_rate(self, rate_id, headers):
        return self._request("GET",
                             f"/transparency/payer-negotiated-rates/{rate_id}",
                             headers=headers)

    def list_rates(self, headers, params=None):
        return self._request("GET", "/transparency/payer-negotiated-rates",
                             headers=headers, params=params)

    def patch_rate(self, rate_id, payload, headers):
        return self._request("PATCH",
                             f"/transparency/payer-negotiated-rates/{rate_id}",
                             payload, headers)

    # --- ShoppableServiceList ---
    def create_shoppable_list(self, payload, headers):
        return self._request("POST", "/transparency/shoppable-service-lists",
                             payload, headers)

    def list_shoppable_lists(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/transparency/facilities/{facility_id}/shoppable-service-lists",
            headers=headers, params=params)

    def certify_list(self, list_id, headers):
        return self._request(
            "POST", f"/transparency/shoppable-service-lists/{list_id}/certify",
            headers=headers)

    def publish_list(self, list_id, headers):
        return self._request(
            "POST", f"/transparency/shoppable-service-lists/{list_id}/publish",
            headers=headers)

    def display_list(self, list_id, headers):
        return self._request(
            "GET", f"/transparency/shoppable-service-lists/{list_id}/display",
            headers=headers)

    # --- PublicationCycle ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/transparency/publication-cycles", payload,
                             headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET",
                             f"/transparency/publication-cycles/{cycle_id}",
                             headers=headers)

    def list_cycles(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/transparency/facilities/{facility_id}/publication-cycles",
            headers=headers, params=params)

    def freeze_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/transparency/publication-cycles/{cycle_id}/freeze",
            headers=headers)

    def publish_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/transparency/publication-cycles/{cycle_id}/publish",
            headers=headers)

    # --- MachineReadableFile ---
    def create_machine_file(self, payload, headers):
        return self._request("POST", "/transparency/machine-readable-files",
                             payload, headers)

    def list_machine_files(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/transparency/publication-cycles/{cycle_id}/machine-readable-files",
            headers=headers, params=params)

    def validate_machine_file(self, file_id, headers):
        return self._request(
            "POST",
            f"/transparency/machine-readable-files/{file_id}/validate",
            headers=headers)

    # --- DiscrepancyReport / correction workflow ---
    def create_discrepancy(self, payload, headers):
        return self._request("POST", "/transparency/discrepancy-reports", payload,
                             headers)

    def get_discrepancy(self, discrepancy_id, headers):
        return self._request(
            "GET", f"/transparency/discrepancy-reports/{discrepancy_id}",
            headers=headers)

    def list_discrepancies(self, headers, params=None):
        return self._request("GET", "/transparency/discrepancy-reports",
                             headers=headers, params=params)

    def triage_discrepancy(self, discrepancy_id, payload, headers):
        return self._request(
            "POST", f"/transparency/discrepancy-reports/{discrepancy_id}/triage",
            payload, headers)

    def propose_correction(self, discrepancy_id, payload, headers):
        return self._request(
            "POST",
            f"/transparency/discrepancy-reports/{discrepancy_id}/propose-correction",
            payload, headers)

    def approve_correction(self, discrepancy_id, headers):
        return self._request(
            "POST",
            f"/transparency/discrepancy-reports/{discrepancy_id}/approve-correction",
            headers=headers)

    def apply_correction(self, discrepancy_id, headers):
        return self._request(
            "POST",
            f"/transparency/discrepancy-reports/{discrepancy_id}/apply-correction",
            headers=headers)


api_client = ApiClient()
# Under per-test-server isolation the runner kills and re-spawns the server on
# the same port before every test. A session-scoped client that pools keep-alive
# connections would otherwise reuse a dead socket against the next process and
# flake with ConnectionResetError/RemoteDisconnected; forcing Connection: close
# sidesteps that race.
api_client.session.headers["Connection"] = "close"
