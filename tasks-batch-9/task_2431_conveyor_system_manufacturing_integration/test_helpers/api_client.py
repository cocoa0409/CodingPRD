"""API client: one method per endpoint defined in the PRD.

Endpoints are mounted at the server root — there is no additional API path prefix.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- Projects ----------------------------------------------------------
    def create_project(self, payload: dict, headers: dict):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id: str, headers: dict):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def design_freeze(self, project_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/projects/{project_id}/design-freeze", payload or {}, headers
        )

    def run_simulation(self, project_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/projects/{project_id}/simulations", payload, headers)

    def list_simulation_runs(self, project_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/simulation-runs", headers=headers, params=params
        )

    def run_spares_provisioning(self, project_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/projects/{project_id}/spares-provisioning", payload, headers
        )

    def list_spare_part_lines(self, project_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/spare-part-lines", headers=headers, params=params
        )

    def list_project_segments(self, project_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/segments", headers=headers, params=params
        )

    def list_site_zones(self, project_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/site-zones", headers=headers, params=params
        )

    def list_commissioning_ramps(self, project_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/commissioning-ramps", headers=headers, params=params
        )

    def list_change_orders(self, project_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/change-orders", headers=headers, params=params
        )

    def list_acceptance_certificates(
        self, project_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/projects/{project_id}/acceptance-certificates", headers=headers, params=params
        )

    # -- Conveyor segments -------------------------------------------------
    def create_segment(self, payload: dict, headers: dict):
        return self._request("POST", "/segments", payload, headers)

    def update_segment(self, segment_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/segments/{segment_id}", payload, headers)

    def get_segment(self, segment_id: str, headers: dict):
        return self._request("GET", f"/segments/{segment_id}", headers=headers)

    # -- Flow links --------------------------------------------------------
    def create_flow_link(self, payload: dict, headers: dict):
        return self._request("POST", "/flow-links", payload, headers)

    def get_flow_link(self, flow_link_id: str, headers: dict):
        return self._request("GET", f"/flow-links/{flow_link_id}", headers=headers)

    def list_flow_links(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/flow-links", headers=headers, params=params)

    # -- Staging bays and fabrication lots ---------------------------------
    def create_staging_bay(self, payload: dict, headers: dict):
        return self._request("POST", "/staging-bays", payload, headers)

    def create_fabrication_lot(self, payload: dict, headers: dict):
        return self._request("POST", "/fabrication-lots", payload, headers)

    def get_fabrication_lot(self, lot_id: str, headers: dict):
        return self._request("GET", f"/fabrication-lots/{lot_id}", headers=headers)

    def list_fabrication_lots(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/fabrication-lots", headers=headers, params=params)

    def start_fabrication(self, lot_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/fabrication-lots/{lot_id}/start-fabrication", payload or {}, headers
        )

    def stage_fabrication_lot(self, lot_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/fabrication-lots/{lot_id}/stage", payload or {}, headers
        )

    # -- Factory acceptance tests ------------------------------------------
    def create_fat_test(self, payload: dict, headers: dict):
        return self._request("POST", "/fat-tests", payload, headers)

    def list_fat_tests(self, lot_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fabrication-lots/{lot_id}/fat-tests", headers=headers, params=params
        )

    # -- Site zones and cutover windows ------------------------------------
    def create_site_zone(self, payload: dict, headers: dict):
        return self._request("POST", "/site-zones", payload, headers)

    def create_cutover_window(self, payload: dict, headers: dict):
        return self._request("POST", "/cutover-windows", payload, headers)

    def get_cutover_window(self, window_id: str, headers: dict):
        return self._request("GET", f"/cutover-windows/{window_id}", headers=headers)

    def list_cutover_windows(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/cutover-windows", headers=headers, params=params)

    def start_cutover_window(self, window_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/cutover-windows/{window_id}/start", payload or {}, headers
        )

    def complete_cutover_window(self, window_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/cutover-windows/{window_id}/complete", payload or {}, headers
        )

    def abort_cutover_window(self, window_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/cutover-windows/{window_id}/abort", payload, headers
        )

    # -- Commissioning ramps ------------------------------------------------
    def create_commissioning_ramp(self, payload: dict, headers: dict):
        return self._request("POST", "/commissioning-ramps", payload, headers)

    # -- Change orders ------------------------------------------------------
    def create_change_order(self, payload: dict, headers: dict):
        return self._request("POST", "/change-orders", payload, headers)

    def submit_change_order(self, change_order_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/submit", payload or {}, headers
        )

    def review_change_order(self, change_order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/review-decision", payload, headers
        )

    def get_change_order(self, change_order_id: str, headers: dict):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    # -- Spare part lines ---------------------------------------------------
    def create_spare_part_line(self, payload: dict, headers: dict):
        return self._request("POST", "/spare-part-lines", payload, headers)

    # -- Acceptance certificates and disputes -------------------------------
    def create_acceptance_certificate(self, payload: dict, headers: dict):
        return self._request("POST", "/acceptance-certificates", payload, headers)

    def get_acceptance_certificate(self, certificate_id: str, headers: dict):
        return self._request(
            "GET", f"/acceptance-certificates/{certificate_id}", headers=headers
        )

    def list_certificate_disputes(
        self, certificate_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/acceptance-certificates/{certificate_id}/disputes",
            headers=headers, params=params,
        )

    def create_performance_dispute(self, payload: dict, headers: dict):
        return self._request("POST", "/performance-disputes", payload, headers)

    def joint_retest(self, dispute_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/performance-disputes/{dispute_id}/joint-retest", payload, headers
        )

    # -- Logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
