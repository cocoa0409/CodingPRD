"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP call, envelope parsing, and header injection. Every collection lives
directly beneath /apprenticeship with no nested ownership paths.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Sponsors ----
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/apprenticeship/sponsors", payload, headers=headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/apprenticeship/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/apprenticeship/sponsors/{sponsor_id}", headers=headers)

    # ---- Programs ----
    def create_program(self, payload, headers):
        return self._request("POST", "/apprenticeship/programs", payload, headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/apprenticeship/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/apprenticeship/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/apprenticeship/programs/{program_id}/activate", {}, headers=headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/apprenticeship/programs/{program_id}/archive", {}, headers=headers)

    # ---- Wage Steps ----
    def create_wage_step(self, payload, headers):
        return self._request("POST", "/apprenticeship/wage-steps", payload, headers=headers)

    def list_wage_steps(self, headers, params=None):
        return self._request("GET", "/apprenticeship/wage-steps", headers=headers, params=params)

    def get_wage_step(self, wage_step_id, headers):
        return self._request("GET", f"/apprenticeship/wage-steps/{wage_step_id}", headers=headers)

    # ---- Milestones ----
    def create_milestone(self, payload, headers):
        return self._request("POST", "/apprenticeship/milestones", payload, headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/apprenticeship/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/apprenticeship/milestones/{milestone_id}", headers=headers)

    # ---- Journeyworkers ----
    def create_journeyworker(self, payload, headers):
        return self._request("POST", "/apprenticeship/journeyworkers", payload, headers=headers)

    def list_journeyworkers(self, headers, params=None):
        return self._request("GET", "/apprenticeship/journeyworkers", headers=headers, params=params)

    def get_journeyworker(self, journeyworker_id, headers):
        return self._request("GET", f"/apprenticeship/journeyworkers/{journeyworker_id}", headers=headers)

    def qualify_journeyworker(self, journeyworker_id, headers):
        return self._request("POST", f"/apprenticeship/journeyworkers/{journeyworker_id}/qualify", {}, headers=headers)

    def deactivate_journeyworker(self, journeyworker_id, headers):
        return self._request("POST", f"/apprenticeship/journeyworkers/{journeyworker_id}/deactivate", {}, headers=headers)

    # ---- Apprentices ----
    def create_apprentice(self, payload, headers):
        return self._request("POST", "/apprenticeship/apprentices", payload, headers=headers)

    def list_apprentices(self, headers, params=None):
        return self._request("GET", "/apprenticeship/apprentices", headers=headers, params=params)

    def get_apprentice(self, apprentice_id, headers):
        return self._request("GET", f"/apprenticeship/apprentices/{apprentice_id}", headers=headers)

    # ---- Apprentice Agreements ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/apprenticeship/agreements", payload, headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/apprenticeship/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/apprenticeship/agreements/{agreement_id}", headers=headers)

    def register_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/apprenticeship/agreements/{agreement_id}/register", payload, headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/apprenticeship/agreements/{agreement_id}/activate", {}, headers=headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/apprenticeship/agreements/{agreement_id}/suspend", {}, headers=headers)

    def reinstate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/apprenticeship/agreements/{agreement_id}/reinstate", {}, headers=headers)

    def complete_agreement(self, agreement_id, headers):
        return self._request("POST", f"/apprenticeship/agreements/{agreement_id}/complete", {}, headers=headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/apprenticeship/agreements/{agreement_id}/cancel", {}, headers=headers)

    # ---- OJT Hours Entries ----
    def create_ojt_entry(self, payload, headers):
        return self._request("POST", "/apprenticeship/ojt-entries", payload, headers=headers)

    def list_ojt_entries(self, headers, params=None):
        return self._request("GET", "/apprenticeship/ojt-entries", headers=headers, params=params)

    def get_ojt_entry(self, entry_id, headers):
        return self._request("GET", f"/apprenticeship/ojt-entries/{entry_id}", headers=headers)

    def approve_ojt_entry(self, entry_id, headers):
        return self._request("POST", f"/apprenticeship/ojt-entries/{entry_id}/approve", {}, headers=headers)

    def reject_ojt_entry(self, entry_id, headers):
        return self._request("POST", f"/apprenticeship/ojt-entries/{entry_id}/reject", {}, headers=headers)

    def reopen_ojt_entry(self, entry_id, headers):
        return self._request("POST", f"/apprenticeship/ojt-entries/{entry_id}/reopen", {}, headers=headers)

    # ---- RTI Records ----
    def create_rti_record(self, payload, headers):
        return self._request("POST", "/apprenticeship/rti-records", payload, headers=headers)

    def list_rti_records(self, headers, params=None):
        return self._request("GET", "/apprenticeship/rti-records", headers=headers, params=params)

    def get_rti_record(self, rti_id, headers):
        return self._request("GET", f"/apprenticeship/rti-records/{rti_id}", headers=headers)

    # ---- Milestone Attainments ----
    def create_milestone_attainment(self, payload, headers):
        return self._request("POST", "/apprenticeship/milestone-attainments", payload, headers=headers)

    def list_milestone_attainments(self, headers, params=None):
        return self._request("GET", "/apprenticeship/milestone-attainments", headers=headers, params=params)

    def get_milestone_attainment(self, attainment_id, headers):
        return self._request("GET", f"/apprenticeship/milestone-attainments/{attainment_id}", headers=headers)

    def approve_milestone_attainment(self, attainment_id, headers):
        return self._request("POST", f"/apprenticeship/milestone-attainments/{attainment_id}/approve", {}, headers=headers)

    def reject_milestone_attainment(self, attainment_id, headers):
        return self._request("POST", f"/apprenticeship/milestone-attainments/{attainment_id}/reject", {}, headers=headers)

    def resubmit_milestone_attainment(self, attainment_id, headers):
        return self._request("POST", f"/apprenticeship/milestone-attainments/{attainment_id}/resubmit", {}, headers=headers)

    # ---- Completion Certificates ----
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/apprenticeship/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/apprenticeship/certificates/{certificate_id}", headers=headers)

    # ---- EEO Reports ----
    def create_eeo_report(self, payload, headers):
        return self._request("POST", "/apprenticeship/eeo-reports", payload, headers=headers)

    def list_eeo_reports(self, headers, params=None):
        return self._request("GET", "/apprenticeship/eeo-reports", headers=headers, params=params)

    def get_eeo_report(self, report_id, headers):
        return self._request("GET", f"/apprenticeship/eeo-reports/{report_id}", headers=headers)


api_client = ApiClient()
