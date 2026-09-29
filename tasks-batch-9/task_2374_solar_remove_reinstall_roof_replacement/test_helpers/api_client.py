"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/reroof"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- parties
    def create_party(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parties", payload, headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parties", headers=headers, params=params)

    def get_party(self, party_id, headers):
        return self._request("GET", f"{PREFIX}/parties/{party_id}", headers=headers)

    # ---------------------------------------------------------- jurisdictions
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/jurisdictions", headers=headers, params=params
        )

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/jurisdictions/{jurisdiction_id}", headers=headers
        )

    # --------------------------------------------------------------- projects
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def get_downtime_summary(self, project_id, headers):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/downtime-summary", headers=headers
        )

    def file_warranty_notice(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/warranty-notice", payload, headers
        )

    def settle_credit(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/credit-settlement", payload, headers
        )

    # -------------------------------------------------------- party approvals
    def create_party_approval(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/party-approvals", payload, headers
        )

    def get_party_approval(self, approval_id, headers):
        return self._request(
            "GET", f"{PREFIX}/party-approvals/{approval_id}", headers=headers
        )

    def list_party_approvals(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/party-approvals", headers=headers, params=params
        )

    def decide_party_approval(self, approval_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/party-approvals/{approval_id}/decision", payload, headers
        )

    # --------------------------------------------------------- array circuits
    def create_array_circuit(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/array-circuits", payload, headers
        )

    def get_array_circuit(self, circuit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/array-circuits/{circuit_id}", headers=headers
        )

    def list_project_array_circuits(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/projects/{project_id}/array-circuits",
            headers=headers,
            params=params,
        )

    def set_circuit_energization(self, circuit_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/array-circuits/{circuit_id}/energization",
            payload,
            headers,
        )

    # ----------------------------------------------------------- storage bins
    def create_storage_bin(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/storage-bins", payload, headers
        )

    def get_storage_bin(self, bin_id, headers):
        return self._request("GET", f"{PREFIX}/storage-bins/{bin_id}", headers=headers)

    def list_project_storage_bins(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/projects/{project_id}/storage-bins",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------- hardware units
    def create_hardware_unit(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/hardware-units", payload, headers
        )

    def get_hardware_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/hardware-units/{unit_id}", headers=headers)

    def list_hardware_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hardware-units", headers=headers, params=params
        )

    def remove_hardware_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/hardware-units/{unit_id}/removal", payload or {}, headers
        )

    def store_hardware_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardware-units/{unit_id}/storage", payload, headers
        )

    def grade_hardware_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardware-units/{unit_id}/condition-grade", payload, headers
        )

    def reinstall_hardware_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/hardware-units/{unit_id}/reinstall",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------- deck findings
    def create_deck_finding(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/deck-findings", payload, headers
        )

    def get_deck_finding(self, finding_id, headers):
        return self._request(
            "GET", f"{PREFIX}/deck-findings/{finding_id}", headers=headers
        )

    def list_deck_findings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/deck-findings", headers=headers, params=params
        )

    def upgrade_deck_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deck-findings/{finding_id}/upgrade", payload, headers
        )

    # ----------------------------------------------------- permit applications
    def create_permit_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permit-applications", payload, headers)

    def get_permit_application(self, permit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/permit-applications/{permit_id}", headers=headers
        )

    def list_permit_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permit-applications", headers=headers, params=params
        )

    def submit_permit_application(self, permit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/permit-applications/{permit_id}/submission",
            payload or {},
            headers,
        )

    def decide_permit_application(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/permit-applications/{permit_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------ inspections
    def create_inspection(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/permit-applications/{permit_id}/inspections",
            payload,
            headers,
        )

    def list_permit_inspections(self, permit_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/permit-applications/{permit_id}/inspections",
            headers=headers,
            params=params,
        )

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/result", payload, headers
        )

    # ----------------------------------------------------------- work windows
    def create_work_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-windows", payload, headers)

    def get_work_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/work-windows/{window_id}", headers=headers)

    def list_work_windows(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/work-windows", headers=headers, params=params
        )

    def set_work_window_status(self, window_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-windows/{window_id}/status", payload, headers
        )

    def reschedule_work_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-windows/{window_id}/reschedule", payload, headers
        )

    # -------------------------------------------------------- sourcing orders
    def create_sourcing_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sourcing-orders", payload, headers)

    def get_sourcing_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sourcing-orders/{order_id}", headers=headers
        )

    def list_sourcing_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sourcing-orders", headers=headers, params=params
        )

    def review_sourcing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sourcing-orders/{order_id}/review", payload, headers
        )

    def receive_sourcing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sourcing-orders/{order_id}/receipt", payload, headers
        )

    # ------------------------------------------------- test-driving endpoints
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def perturb_ledger(self, project_id, released_delta_cents, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_ledger/perturb",
            {"project_id": project_id, "released_delta_cents": released_delta_cents},
            headers,
        )


api_client = ApiClient()
