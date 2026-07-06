"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Config / actors ----
    def create_investigator(self, payload, headers):
        return self._request("POST", "/investigators", payload, headers)

    def get_investigator(self, investigator_id, headers):
        return self._request("GET", f"/investigators/{investigator_id}", headers=headers)

    def create_pathologist(self, payload, headers):
        return self._request("POST", "/pathologists", payload, headers)

    def get_pathologist(self, pathologist_id, headers):
        return self._request("GET", f"/pathologists/{pathologist_id}", headers=headers)

    def create_cooler_unit(self, payload, headers):
        return self._request("POST", "/cooler-units", payload, headers)

    def get_cooler_unit(self, cooler_id, headers):
        return self._request("GET", f"/cooler-units/{cooler_id}", headers=headers)

    def update_cooler_unit(self, cooler_id, payload, headers):
        return self._request("PATCH", f"/cooler-units/{cooler_id}", payload, headers)

    def cooler_occupancy_report(self, cooler_id, headers):
        return self._request("GET", f"/cooler-units/{cooler_id}/occupancy-report", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Case intake & triage ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def triage_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/triage", payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/close", headers=headers)

    # ---- Body & cooler inventory ----
    def create_body(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/bodies", payload, headers)

    def list_case_bodies(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/bodies", headers=headers)

    def get_body(self, body_id, headers):
        return self._request("GET", f"/bodies/{body_id}", headers=headers)

    def list_bodies(self, headers, params=None):
        return self._request("GET", "/bodies", headers=headers, params=params)

    def store_body(self, body_id, payload, headers):
        return self._request("POST", f"/bodies/{body_id}/store", payload, headers)

    def release_body(self, body_id, headers):
        return self._request("POST", f"/bodies/{body_id}/release", headers=headers)

    # ---- Autopsy ----
    def create_autopsy_exam(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/autopsy-exams", payload, headers)

    def list_case_autopsy_exams(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/autopsy-exams", headers=headers)

    def get_autopsy_exam(self, exam_id, headers):
        return self._request("GET", f"/autopsy-exams/{exam_id}", headers=headers)

    def list_autopsy_exams(self, headers, params=None):
        return self._request("GET", "/autopsy-exams", headers=headers, params=params)

    def complete_autopsy_exam(self, exam_id, payload, headers):
        return self._request("POST", f"/autopsy-exams/{exam_id}/complete", payload, headers)

    def cancel_autopsy_exam(self, exam_id, headers):
        return self._request("POST", f"/autopsy-exams/{exam_id}/cancel", headers=headers)

    # ---- Specimen & toxicology ----
    def create_specimen(self, body_id, payload, headers):
        return self._request("POST", f"/bodies/{body_id}/specimens", payload, headers)

    def list_body_specimens(self, body_id, headers):
        return self._request("GET", f"/bodies/{body_id}/specimens", headers=headers)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/specimens/{specimen_id}", headers=headers)

    def send_specimen_to_lab(self, specimen_id, headers):
        return self._request("POST", f"/specimens/{specimen_id}/send-to-lab", headers=headers)

    def discard_specimen(self, specimen_id, headers):
        return self._request("POST", f"/specimens/{specimen_id}/discard", headers=headers)

    def create_tox_screen(self, specimen_id, payload, headers):
        return self._request("POST", f"/specimens/{specimen_id}/tox-screens", payload, headers)

    def list_specimen_tox_screens(self, specimen_id, headers):
        return self._request("GET", f"/specimens/{specimen_id}/tox-screens", headers=headers)

    def get_tox_screen(self, tox_id, headers):
        return self._request("GET", f"/tox-screens/{tox_id}", headers=headers)

    def result_tox_screen(self, tox_id, payload, headers):
        return self._request("POST", f"/tox-screens/{tox_id}/result", payload, headers)

    def amend_tox_screen(self, tox_id, payload, headers):
        return self._request("POST", f"/tox-screens/{tox_id}/amend", payload, headers)

    # ---- Death certificate ----
    def create_death_certificate(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/death-certificate", payload, headers)

    def list_case_death_certificate(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/death-certificate", headers=headers)

    def get_death_certificate(self, cert_id, headers):
        return self._request("GET", f"/death-certificates/{cert_id}", headers=headers)

    def list_death_certificates(self, headers, params=None):
        return self._request("GET", "/death-certificates", headers=headers, params=params)

    def sign_death_certificate(self, cert_id, payload, headers):
        return self._request("POST", f"/death-certificates/{cert_id}/sign", payload, headers)

    def amend_death_certificate(self, cert_id, payload, headers):
        return self._request("POST", f"/death-certificates/{cert_id}/amend", payload, headers)

    def void_death_certificate(self, cert_id, headers):
        return self._request("POST", f"/death-certificates/{cert_id}/void", headers=headers)

    # ---- Next of kin ----
    def create_next_of_kin(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/next-of-kin", payload, headers)

    def list_case_next_of_kin(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/next-of-kin", headers=headers)

    def get_next_of_kin(self, kin_id, headers):
        return self._request("GET", f"/next-of-kin/{kin_id}", headers=headers)

    def verify_next_of_kin(self, kin_id, headers):
        return self._request("POST", f"/next-of-kin/{kin_id}/verify", headers=headers)

    # ---- Property ----
    def create_property_item(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/property-items", payload, headers)

    def list_case_property_items(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/property-items", headers=headers)

    def get_property_item(self, item_id, headers):
        return self._request("GET", f"/property-items/{item_id}", headers=headers)

    def create_property_release(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/property-releases", payload, headers)

    def list_case_property_releases(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/property-releases", headers=headers, params=params)

    def get_property_release(self, release_id, headers):
        return self._request("GET", f"/property-releases/{release_id}", headers=headers)

    def list_property_releases(self, headers, params=None):
        return self._request("GET", "/property-releases", headers=headers, params=params)

    def approve_property_release(self, release_id, headers):
        return self._request("POST", f"/property-releases/{release_id}/approve", headers=headers)

    def deny_property_release(self, release_id, headers):
        return self._request("POST", f"/property-releases/{release_id}/deny", headers=headers)

    # ---- Indigent disposition ----
    def create_indigent_disposition(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/indigent-disposition", payload, headers)

    def list_case_indigent_disposition(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/indigent-disposition", headers=headers)

    def get_indigent_disposition(self, disposition_id, headers):
        return self._request("GET", f"/indigent-dispositions/{disposition_id}", headers=headers)

    def approve_indigent_disposition(self, disposition_id, headers):
        return self._request("POST", f"/indigent-dispositions/{disposition_id}/approve", headers=headers)

    def bury_indigent_disposition(self, disposition_id, headers):
        return self._request("POST", f"/indigent-dispositions/{disposition_id}/bury", headers=headers)


api_client = ApiClient()
