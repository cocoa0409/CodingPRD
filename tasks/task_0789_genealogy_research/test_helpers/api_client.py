"""API client: one method per endpoint defined in the Genealogy Research PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/genealogy/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/genealogy/clients/{client_id}", headers=headers)

    # ---- Researchers ----
    def create_researcher(self, payload, headers):
        return self._request("POST", "/genealogy/researchers", payload, headers)

    def get_researcher(self, researcher_id, headers):
        return self._request("GET", f"/genealogy/researchers/{researcher_id}", headers=headers)

    # ---- Repositories ----
    def create_repository(self, payload, headers):
        return self._request("POST", "/genealogy/repositories", payload, headers)

    def get_repository(self, repository_id, headers):
        return self._request("GET", f"/genealogy/repositories/{repository_id}", headers=headers)

    # ---- Research Projects ----
    def create_project(self, payload, headers):
        return self._request("POST", "/genealogy/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/genealogy/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/genealogy/projects", headers=headers, params=params)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/genealogy/projects/{project_id}/activate", {}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/genealogy/projects/{project_id}/close", {}, headers)

    def reconfigure_project(self, project_id, payload, headers):
        return self._request("POST", f"/genealogy/projects/{project_id}/reconfigure", payload, headers)

    # ---- Record Searches ----
    def create_record_search(self, payload, headers):
        return self._request("POST", "/genealogy/record-searches", payload, headers)

    def get_record_search(self, search_id, headers):
        return self._request("GET", f"/genealogy/record-searches/{search_id}", headers=headers)

    def list_record_searches(self, headers, params=None):
        return self._request("GET", "/genealogy/record-searches", headers=headers, params=params)

    def complete_record_search(self, search_id, payload, headers):
        return self._request("POST", f"/genealogy/record-searches/{search_id}/complete", payload, headers)

    # ---- Source Citations ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/genealogy/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/genealogy/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/genealogy/citations", headers=headers, params=params)

    def verify_citation(self, citation_id, headers):
        return self._request("POST", f"/genealogy/citations/{citation_id}/verify", {}, headers)

    def dispute_citation(self, citation_id, headers, payload=None):
        return self._request("POST", f"/genealogy/citations/{citation_id}/dispute", payload or {}, headers)

    # ---- Persons ----
    def create_person(self, payload, headers):
        return self._request("POST", "/genealogy/persons", payload, headers)

    def get_person(self, person_id, headers):
        return self._request("GET", f"/genealogy/persons/{person_id}", headers=headers)

    def list_persons(self, headers, params=None):
        return self._request("GET", "/genealogy/persons", headers=headers, params=params)

    def submit_review_person(self, person_id, headers):
        return self._request("POST", f"/genealogy/persons/{person_id}/submit-review", {}, headers)

    def verify_person(self, person_id, headers):
        return self._request("POST", f"/genealogy/persons/{person_id}/verify", {}, headers)

    # ---- DNA Interpretations ----
    def create_dna_interpretation(self, payload, headers):
        return self._request("POST", "/genealogy/dna-interpretations", payload, headers)

    def get_dna_interpretation(self, dna_id, headers):
        return self._request("GET", f"/genealogy/dna-interpretations/{dna_id}", headers=headers)

    def list_dna_interpretations(self, headers, params=None):
        return self._request("GET", "/genealogy/dna-interpretations", headers=headers, params=params)

    def interpret_dna(self, dna_id, payload, headers):
        return self._request("POST", f"/genealogy/dna-interpretations/{dna_id}/interpret", payload, headers)

    # ---- Document Requests ----
    def create_document_request(self, payload, headers):
        return self._request("POST", "/genealogy/document-requests", payload, headers)

    def get_document_request(self, doc_id, headers):
        return self._request("GET", f"/genealogy/document-requests/{doc_id}", headers=headers)

    def list_document_requests(self, headers, params=None):
        return self._request("GET", "/genealogy/document-requests", headers=headers, params=params)

    def update_retrieval(self, doc_id, payload, headers):
        return self._request("POST", f"/genealogy/document-requests/{doc_id}/update-retrieval", payload, headers)

    def update_translation(self, doc_id, payload, headers):
        return self._request("POST", f"/genealogy/document-requests/{doc_id}/update-translation", payload, headers)

    # ---- Heirlooms ----
    def create_heirloom(self, payload, headers):
        return self._request("POST", "/genealogy/heirlooms", payload, headers)

    def get_heirloom(self, heirloom_id, headers):
        return self._request("GET", f"/genealogy/heirlooms/{heirloom_id}", headers=headers)

    def list_heirlooms(self, headers, params=None):
        return self._request("GET", "/genealogy/heirlooms", headers=headers, params=params)

    def advance_heirloom(self, heirloom_id, payload, headers):
        return self._request("POST", f"/genealogy/heirlooms/{heirloom_id}/advance", payload, headers)

    # ---- Deliverables ----
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/genealogy/deliverables", payload, headers)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/genealogy/deliverables/{deliverable_id}", headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/genealogy/deliverables", headers=headers, params=params)

    def submit_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/genealogy/deliverables/{deliverable_id}/submit", {}, headers)

    def accept_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/genealogy/deliverables/{deliverable_id}/accept", {}, headers)

    def request_revision_deliverable(self, deliverable_id, headers, payload=None):
        return self._request("POST", f"/genealogy/deliverables/{deliverable_id}/request-revision", payload or {}, headers)

    # ---- Milestones ----
    def create_milestone(self, payload, headers):
        return self._request("POST", "/genealogy/milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/genealogy/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/genealogy/milestones", headers=headers, params=params)

    def invoice_milestone(self, milestone_id, headers):
        return self._request("POST", f"/genealogy/milestones/{milestone_id}/invoice", {}, headers)

    def record_payment_milestone(self, milestone_id, headers):
        return self._request("POST", f"/genealogy/milestones/{milestone_id}/record-payment", {}, headers)

    def cancel_milestone(self, milestone_id, headers, payload=None):
        return self._request("POST", f"/genealogy/milestones/{milestone_id}/cancel", payload or {}, headers)

    # ---- Time Entries ----
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/genealogy/time-entries", payload, headers)

    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"/genealogy/time-entries/{entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/genealogy/time-entries", headers=headers, params=params)

    def void_time_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/genealogy/time-entries/{entry_id}/void", payload or {}, headers)

    # ---- Repository Appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/genealogy/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/genealogy/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/genealogy/appointments", headers=headers, params=params)

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/genealogy/appointments/{appointment_id}/cancel", payload or {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/genealogy/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
