"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # Per-test-server isolation SIGKILLs and respawns the server before
        # every test. A keep-alive pool would hold connections to the killed
        # process; the next request on a stale socket races the RST and
        # intermittently fails with ECONNRESET. Closing every connection
        # sidesteps the whole class without touching any assertion.
        self.session.headers["Connection"] = "close"

    # --- Generator sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/hazwaste/generator-sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/hazwaste/generator-sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/hazwaste/generator-sites/{site_id}", headers=headers)

    # --- Waste streams ---
    def create_stream(self, payload, headers):
        return self._request("POST", "/hazwaste/waste-streams", payload, headers)

    def list_streams(self, headers, params=None):
        return self._request("GET", "/hazwaste/waste-streams", headers=headers, params=params)

    def get_stream(self, stream_id, headers):
        return self._request("GET", f"/hazwaste/waste-streams/{stream_id}", headers=headers)

    def characterize_stream(self, stream_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/waste-streams/{stream_id}/characterize", payload, headers)

    def activate_stream(self, stream_id, headers):
        return self._request(
            "POST", f"/hazwaste/waste-streams/{stream_id}/activate", headers=headers)

    def retire_stream(self, stream_id, headers):
        return self._request(
            "POST", f"/hazwaste/waste-streams/{stream_id}/retire", headers=headers)

    # --- Accumulation areas ---
    def create_area(self, payload, headers):
        return self._request("POST", "/hazwaste/accumulation-areas", payload, headers)

    def list_areas(self, headers, params=None):
        return self._request("GET", "/hazwaste/accumulation-areas", headers=headers, params=params)

    def get_area(self, area_id, headers):
        return self._request("GET", f"/hazwaste/accumulation-areas/{area_id}", headers=headers)

    # --- Containers ---
    def create_container(self, payload, headers):
        return self._request("POST", "/hazwaste/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/hazwaste/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/hazwaste/containers/{container_id}", headers=headers)

    def move_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/containers/{container_id}/move", payload, headers)

    def label_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/containers/{container_id}/label", payload, headers)

    def stage_container(self, container_id, headers):
        return self._request(
            "POST", f"/hazwaste/containers/{container_id}/stage", headers=headers)

    def void_container(self, container_id, headers):
        return self._request(
            "POST", f"/hazwaste/containers/{container_id}/void", headers=headers)

    def create_inspection(self, container_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/containers/{container_id}/inspections", payload, headers)

    def list_inspections(self, container_id, headers, params=None):
        return self._request(
            "GET", f"/hazwaste/containers/{container_id}/inspections",
            headers=headers, params=params)

    # --- Waste partners ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/hazwaste/waste-partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/hazwaste/waste-partners/{partner_id}", headers=headers)

    def update_partner(self, partner_id, payload, headers):
        return self._request("PUT", f"/hazwaste/waste-partners/{partner_id}", payload, headers)

    def set_partner_status(self, partner_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/waste-partners/{partner_id}/status", payload, headers)

    def create_audit(self, partner_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/waste-partners/{partner_id}/audits", payload, headers)

    def list_audits(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"/hazwaste/waste-partners/{partner_id}/audits",
            headers=headers, params=params)

    # --- Manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/hazwaste/manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/hazwaste/manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/hazwaste/manifests/{manifest_id}", headers=headers)

    def create_ldr_notification(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/ldr-notifications", payload, headers)

    def list_ldr_notifications(self, manifest_id, headers):
        return self._request(
            "GET", f"/hazwaste/manifests/{manifest_id}/ldr-notifications", headers=headers)

    def sign_manifest_generator(self, manifest_id, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/sign-generator", headers=headers)

    def sign_manifest_transporter(self, manifest_id, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/sign-transporter", headers=headers)

    def receive_manifest(self, manifest_id, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/receive", headers=headers)

    def raise_discrepancy(self, manifest_id, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/raise-discrepancy", headers=headers)

    def resolve_discrepancy(self, manifest_id, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/resolve-discrepancy", headers=headers)

    def confirm_manifest_return(self, manifest_id, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/confirm-return", headers=headers)

    def file_exception_report(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/manifests/{manifest_id}/file-exception-report",
            payload, headers)

    # --- Biennial reports ---
    def create_biennial_report(self, payload, headers):
        return self._request("POST", "/hazwaste/biennial-reports", payload, headers)

    def list_biennial_reports(self, headers, params=None):
        return self._request("GET", "/hazwaste/biennial-reports", headers=headers, params=params)

    def get_biennial_report(self, report_id, headers):
        return self._request("GET", f"/hazwaste/biennial-reports/{report_id}", headers=headers)

    def submit_biennial_report(self, report_id, headers):
        return self._request(
            "POST", f"/hazwaste/biennial-reports/{report_id}/submit", headers=headers)

    def review_biennial_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/hazwaste/biennial-reports/{report_id}/review", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/hazwaste/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
