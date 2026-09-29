"""API client: one method per endpoint the PRD defines in §4.

Every path is mounted under the `/cpo` service root.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

PREFIX = API_PREFIX


class ApiClient(GenericApiClient):
    """Thin wrapper exposing one named method per PRD endpoint."""

    # ───────────────────────── logical clock ─────────────────────────

    def set_clock(self, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─────────────────────── programme configuration ─────────────────

    def get_program_config(self, headers: dict):
        return self._request("GET", f"{PREFIX}/program-config", headers=headers)

    def update_program_config(self, payload: dict, headers: dict):
        return self._request("PUT", f"{PREFIX}/program-config", payload, headers)

    # ─────────────────────── checklist catalogue ──────────────────────

    def create_checklist_template(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/checklist-templates", payload, headers)

    def get_checklist_template(self, template_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/checklist-templates/{template_id}", headers=headers
        )

    def add_checklist_item(self, template_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/checklist-templates/{template_id}/items", payload, headers
        )

    def list_checklist_items(
        self, template_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/checklist-templates/{template_id}/items",
            headers=headers,
            params=params,
        )

    def publish_checklist_template(
        self, template_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/checklist-templates/{template_id}/publish",
            payload,
            headers,
        )

    # ───────────────────────────── dealers ───────────────────────────

    def create_dealer(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def update_dealer_privilege(self, dealer_id: str, payload: dict, headers: dict):
        return self._request(
            "PATCH", f"{PREFIX}/dealers/{dealer_id}/privilege", payload, headers
        )

    # ─────────────────────────── technicians ─────────────────────────

    def create_technician(self, dealer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/technicians", payload, headers
        )

    def list_technicians(
        self, dealer_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/dealers/{dealer_id}/technicians",
            headers=headers,
            params=params,
        )

    # ───────────────────────────── vehicles ──────────────────────────

    def create_vehicle(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}", headers=headers)

    def create_history_event(self, vehicle_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/vehicles/{vehicle_id}/history-events", payload, headers
        )

    # ──────────────────────────── inspections ────────────────────────

    def create_inspection(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def list_inspections(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/inspections", headers=headers, params=params
        )

    def get_inspection(self, inspection_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def record_results(self, inspection_id: str, payload: dict, headers: dict):
        return self._request(
            "PUT", f"{PREFIX}/inspections/{inspection_id}/results", payload, headers
        )

    def list_results(
        self, inspection_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/inspections/{inspection_id}/results",
            headers=headers,
            params=params,
        )

    def list_reconditioning_items(
        self, inspection_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/inspections/{inspection_id}/reconditioning-items",
            headers=headers,
            params=params,
        )

    def complete_reconditioning_item(self, item_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/reconditioning-items/{item_id}/complete", payload, headers
        )

    def submit_inspection(
        self, inspection_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/submit", payload, headers
        )

    # ─────────────────────────── certifications ──────────────────────

    def create_certification(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/certifications", payload, headers)

    def list_certifications(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/certifications", headers=headers, params=params
        )

    def get_certification(self, certification_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/certifications/{certification_id}", headers=headers
        )

    def list_certification_documents(
        self, certification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/documents",
            headers=headers,
            params=params,
        )

    def adjudicate_certification(
        self, certification_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{PREFIX}/certifications/{certification_id}/approve",
            payload,
            headers,
        )

    def decertify_certification(
        self, certification_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{PREFIX}/certifications/{certification_id}/decertify",
            payload,
            headers,
        )

    # ─────────────────────────── audit sampling ──────────────────────

    def create_audit_run(self, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/audit-runs", payload, headers)

    def list_audit_samples(
        self, certification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/audit-samples",
            headers=headers,
            params=params,
        )

    def record_audit_finding(self, sample_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/audit-samples/{sample_id}/finding", payload, headers
        )

    # ───────────────────────────── listings ──────────────────────────

    def create_listing(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/listings", payload, headers)

    def list_listings(
        self, certification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/listings",
            headers=headers,
            params=params,
        )

    def syndicate_listing(self, listing_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/syndicate", payload, headers
        )

    # ────────────────────────── warranty claims ──────────────────────

    def create_warranty_claim(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def list_warranty_claims(
        self, certification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/warranty-claims",
            headers=headers,
            params=params,
        )

    def adjudicate_warranty_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/adjudicate", payload, headers
        )

    # ───────────────────────────── complaints ────────────────────────

    def create_complaint(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def list_complaints(
        self, certification_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/certifications/{certification_id}/complaints",
            headers=headers,
            params=params,
        )

    def get_complaint(self, complaint_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers
        )


api_client = ApiClient()
