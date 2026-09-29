"""API client: one method per endpoint defined in the PRD.

Every method returns the raw ``requests.Response`` so tests can assert status
codes and envelope contents through the framework validators.  All collections
are mounted flat at the top level of the URL space — there is no shared API
prefix — and the two nested collections (validation runs under a qualification,
CCP records under a cycle) take their parent identifier from the path.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ customers --
    def create_customer(self, payload: dict, headers: dict):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: dict):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ----------------------------------------------------- product families --
    def create_product_family(self, payload: dict, headers: dict):
        return self._request("POST", "/product-families", payload, headers)

    def get_product_family(self, family_id: str, headers: dict):
        return self._request("GET", f"/product-families/{family_id}", headers=headers)

    # -------------------------------------------------------------- vessels --
    def create_vessel(self, payload: dict, headers: dict):
        return self._request("POST", "/vessels", payload, headers)

    def patch_vessel(self, vessel_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/vessels/{vessel_id}", payload, headers)

    def get_vessel(self, vessel_id: str, headers: dict):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    # ------------------------------------------------------------ cold rooms --
    def create_cold_room(self, payload: dict, headers: dict):
        return self._request("POST", "/cold-rooms", payload, headers)

    def get_cold_room(self, room_id: str, headers: dict):
        return self._request("GET", f"/cold-rooms/{room_id}", headers=headers)

    # ------------------------------------------------- product qualifications --
    def create_qualification(self, payload: dict, headers: dict):
        return self._request("POST", "/product-qualifications", payload, headers)

    def supersede_qualification(
        self, qualification_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/product-qualifications/{qualification_id}/supersede",
            payload,
            headers,
        )

    def submit_qualification(
        self, qualification_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/product-qualifications/{qualification_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def append_validation_run(
        self, qualification_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/product-qualifications/{qualification_id}/validation-runs",
            payload,
            headers,
        )

    def list_validation_runs(
        self, qualification_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/product-qualifications/{qualification_id}/validation-runs",
            headers=headers,
            params=params,
        )

    def decide_qualification(
        self, qualification_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/product-qualifications/{qualification_id}/decision",
            payload,
            headers,
        )

    def get_qualification(self, qualification_id: str, headers: dict):
        return self._request(
            "GET", f"/product-qualifications/{qualification_id}", headers=headers
        )

    def list_qualifications(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/product-qualifications", headers=headers, params=params
        )

    # ---------------------------------------------------- capacity contracts --
    def create_contract(self, payload: dict, headers: dict):
        return self._request("POST", "/capacity-contracts", payload, headers)

    def activate_contract(
        self, contract_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/capacity-contracts/{contract_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def close_contract(
        self, contract_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/capacity-contracts/{contract_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def get_contract(self, contract_id: str, headers: dict):
        return self._request(
            "GET", f"/capacity-contracts/{contract_id}", headers=headers
        )

    def list_contracts(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/capacity-contracts", headers=headers, params=params
        )

    # ------------------------------------------------------- lots (pallets) --
    def create_lot(self, payload: dict, headers: dict):
        return self._request("POST", "/lots", payload, headers)

    def inspect_lot(self, lot_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/lots/{lot_id}/inspect", payload, headers)

    def record_release_decision(self, lot_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/lots/{lot_id}/release-decision", payload, headers
        )

    def ship_lot(self, lot_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/lots/{lot_id}/ship", payload, headers)

    def get_lot(self, lot_id: str, headers: dict):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # --------------------------------------------------------- vessel cycles --
    def create_vessel_cycle(self, payload: dict, headers: dict):
        return self._request("POST", "/vessel-cycles", payload, headers)

    def create_cycle_load(self, cycle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/vessel-cycles/{cycle_id}/loads", payload, headers
        )

    def start_cycle(
        self, cycle_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/vessel-cycles/{cycle_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def create_cycle_log(self, cycle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/vessel-cycles/{cycle_id}/cycle-logs", payload, headers
        )

    def list_cycle_logs(
        self, cycle_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/vessel-cycles/{cycle_id}/cycle-logs",
            headers=headers,
            params=params,
        )

    def terminate_cycle(self, cycle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/vessel-cycles/{cycle_id}/terminate", payload, headers
        )

    def disposition_cycle(
        self, cycle_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/vessel-cycles/{cycle_id}/disposition",
            payload if payload is not None else {},
            headers,
        )

    def get_vessel_cycle(self, cycle_id: str, headers: dict):
        return self._request("GET", f"/vessel-cycles/{cycle_id}", headers=headers)

    def list_vessel_cycles(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/vessel-cycles", headers=headers, params=params)

    # ----------------------------------------------------------- cycle loads --
    def record_load_inspection(self, load_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/cycle-loads/{load_id}/inspection", payload, headers
        )

    def get_cycle_load(self, load_id: str, headers: dict):
        return self._request("GET", f"/cycle-loads/{load_id}", headers=headers)

    def list_cycle_loads(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/cycle-loads", headers=headers, params=params)

    # ------------------------------------------------------------ deviations --
    def adjudicate_deviation(self, deviation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/deviations/{deviation_id}/adjudicate", payload, headers
        )

    def get_deviation(self, deviation_id: str, headers: dict):
        return self._request("GET", f"/deviations/{deviation_id}", headers=headers)

    def list_deviations(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/deviations", headers=headers, params=params)

    # ------------------------------------------------------ chargeback lines --
    def waive_chargeback_line(self, line_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/chargeback-lines/{line_id}/waive", payload, headers
        )

    def get_chargeback_line(self, line_id: str, headers: dict):
        return self._request("GET", f"/chargeback-lines/{line_id}", headers=headers)

    def list_chargeback_lines(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/chargeback-lines", headers=headers, params=params
        )

    # ------------------------------------------------------------ operations --
    def run_day_close(self, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            "/operations/day-close",
            payload if payload is not None else {},
            headers,
        )

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


# A single shared client instance for the whole suite.
api_client = ApiClient()
