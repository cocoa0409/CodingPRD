"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    # ---- Camera ----
    def create_camera(self, payload, headers):
        return self._request("POST", "/cameras", payload, headers)

    def get_camera(self, camera_id, headers):
        return self._request("GET", f"/cameras/{camera_id}", headers=headers)

    def list_cameras(self, headers, params=None):
        return self._request("GET", "/cameras", headers=headers, params=params)

    def suspend_camera(self, camera_id, headers):
        return self._request("POST", f"/cameras/{camera_id}/suspend", headers=headers)

    def reactivate_camera(self, camera_id, headers):
        return self._request("POST", f"/cameras/{camera_id}/reactivate", headers=headers)

    def decommission_camera(self, camera_id, headers):
        return self._request("POST", f"/cameras/{camera_id}/decommission", headers=headers)

    # ---- CalibrationRecord ----
    def create_calibration(self, camera_id, payload, headers):
        return self._request("POST", f"/cameras/{camera_id}/calibrations", payload, headers)

    def list_calibrations(self, camera_id, headers, params=None):
        return self._request("GET", f"/cameras/{camera_id}/calibrations", headers=headers, params=params)

    # ---- RegisteredOwner ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    # ---- Citation ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def review_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/review", payload, headers)

    def void_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/void", headers=headers)

    # ---- Contest ----
    def create_contest(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/contests", payload, headers)

    def list_citation_contests(self, citation_id, headers, params=None):
        return self._request("GET", f"/citations/{citation_id}/contests", headers=headers, params=params)

    def get_contest(self, contest_id, headers):
        return self._request("GET", f"/contests/{contest_id}", headers=headers)

    def list_owner_contests(self, owner_id, headers, params=None):
        return self._request("GET", f"/owners/{owner_id}/contests", headers=headers, params=params)

    # ---- Hearing ----
    def create_hearing(self, contest_id, payload, headers):
        return self._request("POST", f"/contests/{contest_id}/hearings", payload, headers)

    def list_contest_hearings(self, contest_id, headers, params=None):
        return self._request("GET", f"/contests/{contest_id}/hearings", headers=headers, params=params)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_citation_hearings(self, citation_id, headers, params=None):
        return self._request("GET", f"/citations/{citation_id}/hearings", headers=headers, params=params)

    def rule_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/rule", payload, headers)

    # ---- Payment ----
    def create_payment(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/payments", payload, headers)

    def list_payments(self, citation_id, headers, params=None):
        return self._request("GET", f"/citations/{citation_id}/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", headers=headers)

    # ---- VendorContract ----
    def create_vendor_contract(self, payload, headers):
        return self._request("POST", "/vendor-contracts", payload, headers)

    def list_vendor_contracts(self, headers, params=None):
        return self._request("GET", "/vendor-contracts", headers=headers, params=params)

    def get_vendor_contract(self, contract_id, headers):
        return self._request("GET", f"/vendor-contracts/{contract_id}", headers=headers)

    def terminate_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/vendor-contracts/{contract_id}/terminate", headers=headers)

    # ---- NoticeRecord (append-only audit log) ----
    def list_citation_notices(self, citation_id, headers, params=None):
        return self._request("GET", f"/citations/{citation_id}/notices", headers=headers, params=params)

    def list_owner_notices(self, owner_id, headers, params=None):
        return self._request("GET", f"/owners/{owner_id}/notices", headers=headers, params=params)

    # ---- Owner portal ----
    def list_portal_citations(self, headers, params=None):
        return self._request("GET", "/portal/citations", headers=headers, params=params)

    # ---- Test-driving endpoints (logical clock, settlement, escalation) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def settle_payment(self, payload, headers):
        return self._request("POST", "/_payments/settle", payload, headers)

    def escalation_sweep(self, payload, headers):
        return self._request("POST", "/_escalation/sweep", payload, headers)


api_client = ApiClient()
