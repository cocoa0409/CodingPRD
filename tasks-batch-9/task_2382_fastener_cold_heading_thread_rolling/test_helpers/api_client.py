"""API client: one method per endpoint listed in PRD §4."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Fastener Cold Heading & Thread Rolling API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------ part specs
    def create_part_spec(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/part-specs", payload, headers)

    def get_part_spec(self, part_spec_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/part-specs/{part_spec_id}", headers=headers)

    def revise_part_spec(
        self, part_spec_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/part-specs/{part_spec_id}", payload, headers)

    # ----------------------------------------------------------- steel heats
    def create_steel_heat(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/steel-heats", payload, headers)

    def get_steel_heat(self, steel_heat_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/steel-heats/{steel_heat_id}", headers=headers)

    def verify_mill_cert(
        self, steel_heat_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/steel-heats/{steel_heat_id}/verify-mill-cert", payload, headers
        )

    def flag_counterfeit(
        self, steel_heat_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/steel-heats/{steel_heat_id}/flag-counterfeit", payload, headers
        )

    # ------------------------------------------------------------- wire lots
    def create_wire_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wire-lots", payload, headers)

    def get_wire_lot(self, wire_lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/wire-lots/{wire_lot_id}", headers=headers)

    def list_wire_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/wire-lots", headers=headers, params=params)

    def release_wire_lot(self, wire_lot_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/wire-lots/{wire_lot_id}/release", {}, headers
        )

    # --------------------------------------------------------- heading tools
    def create_heading_tool(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/heading-tools", payload, headers)

    def get_heading_tool(self, heading_tool_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/heading-tools/{heading_tool_id}", headers=headers
        )

    def mount_heading_tool(
        self, heading_tool_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/heading-tools/{heading_tool_id}/mount", payload, headers
        )

    def condemn_heading_tool(
        self, heading_tool_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/heading-tools/{heading_tool_id}/condemn", payload, headers
        )

    def regrind_heading_tool(self, heading_tool_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/heading-tools/{heading_tool_id}/regrind", {}, headers
        )

    # -------------------------------------------------------------- furnaces
    def create_furnace(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/furnaces", payload, headers)

    def get_furnace(self, furnace_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/furnaces/{furnace_id}", headers=headers)

    # -------------------------------------------------------- production lots
    def create_production_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/production-lots", payload, headers)

    def get_production_lot(self, production_lot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/production-lots/{production_lot_id}", headers=headers
        )

    def list_production_lots(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/production-lots", headers=headers, params=params)

    def get_lot_traceability(self, production_lot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/production-lots/{production_lot_id}/traceability", headers=headers
        )

    def complete_heading(
        self,
        production_lot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/production-lots/{production_lot_id}/complete-heading",
            payload,
            headers,
        )

    def abort_heading(
        self,
        production_lot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/production-lots/{production_lot_id}/abort-heading",
            payload,
            headers,
        )

    def hold_production_lot(
        self,
        production_lot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/production-lots/{production_lot_id}/hold", payload, headers
        )

    def release_hold(
        self,
        production_lot_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/production-lots/{production_lot_id}/release-hold",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------- secondary operations
    def queue_secondary_operation(
        self,
        production_lot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/production-lots/{production_lot_id}/secondary-operations",
            payload,
            headers,
        )

    def list_secondary_operations(
        self,
        production_lot_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/production-lots/{production_lot_id}/secondary-operations",
            headers=headers,
            params=params,
        )

    def complete_secondary_operation(
        self,
        secondary_operation_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/secondary-operations/{secondary_operation_id}/complete",
            payload,
            headers,
        )

    # -------------------------------------------------------- heat treat runs
    def create_heat_treat_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/heat-treat-runs", payload, headers)

    def get_heat_treat_run(self, heat_treat_run_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/heat-treat-runs/{heat_treat_run_id}", headers=headers
        )

    def list_heat_treat_runs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/heat-treat-runs", headers=headers, params=params)

    def start_heat_treat_run(self, heat_treat_run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/heat-treat-runs/{heat_treat_run_id}/start", {}, headers
        )

    def record_heat_treat_results(
        self,
        heat_treat_run_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/heat-treat-runs/{heat_treat_run_id}/results", payload, headers
        )

    # ----------------------------------------------------------- plating runs
    def create_plating_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plating-runs", payload, headers)

    def list_lot_plating_runs(
        self,
        production_lot_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/production-lots/{production_lot_id}/plating-runs",
            headers=headers,
            params=params,
        )

    def complete_plating(self, plating_run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plating-runs/{plating_run_id}/complete-plating", {}, headers
        )

    def start_bake(
        self, plating_run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/plating-runs/{plating_run_id}/start-bake", payload, headers
        )

    def complete_bake(self, plating_run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plating-runs/{plating_run_id}/complete-bake", {}, headers
        )

    # -------------------------------------------------------------- lot tests
    def create_lot_test(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/lot-tests", payload, headers)

    def list_lot_tests(
        self,
        production_lot_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/production-lots/{production_lot_id}/lot-tests",
            headers=headers,
            params=params,
        )

    def record_lot_test_results(
        self, lot_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/lot-tests/{lot_test_id}/results", payload, headers
        )

    # -------------------------------------------------- certification documents
    def create_certification_document(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/certification-documents", payload, headers)

    def get_certification_document(self, cert_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/certification-documents/{cert_id}", headers=headers
        )

    def list_certification_documents(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/certification-documents", headers=headers, params=params
        )

    def issue_certification_document(self, cert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/certification-documents/{cert_id}/issue", {}, headers
        )

    def revoke_certification_document(
        self, cert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/certification-documents/{cert_id}/revoke", payload, headers
        )

    def reissue_certification_document(
        self, cert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/certification-documents/{cert_id}/reissue", payload, headers
        )

    # ------------------------------------------------------------- pack units
    def create_pack_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pack-units", payload, headers)

    def get_pack_unit(self, pack_unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pack-units/{pack_unit_id}", headers=headers)

    def list_pack_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pack-units", headers=headers, params=params)

    def seal_pack_unit(self, pack_unit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/pack-units/{pack_unit_id}/seal", {}, headers)

    def reopen_pack_unit(
        self, pack_unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/pack-units/{pack_unit_id}/reopen", payload, headers
        )

    def ship_pack_unit(self, pack_unit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/pack-units/{pack_unit_id}/ship", {}, headers)


api_client = ApiClient()
