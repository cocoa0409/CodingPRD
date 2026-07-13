"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CapitalProject ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers=headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def certify_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/certify", payload, headers=headers)

    # ---- Commission ----
    def create_commission(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/commissions", payload, headers=headers)

    def get_commission(self, commission_id, headers):
        return self._request("GET", f"/commissions/{commission_id}", headers=headers)

    def list_commissions(self, headers, params=None):
        return self._request("GET", "/commissions", headers=headers, params=params)

    def award_commission(self, commission_id, payload, headers):
        return self._request("POST", f"/commissions/{commission_id}/award", payload, headers=headers)

    def cancel_commission(self, commission_id, headers, payload=None):
        return self._request("POST", f"/commissions/{commission_id}/cancel", payload, headers=headers)

    def create_contract(self, commission_id, payload, headers):
        return self._request("POST", f"/commissions/{commission_id}/contracts", payload, headers=headers)

    # ---- Contract ----
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request("POST", f"/contracts/{contract_id}/activate", payload, headers=headers)

    def schedule_milestones(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestone-schedule", payload, headers=headers)

    def list_milestones(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/milestones", headers=headers)

    # ---- Milestone ----
    def submit_milestone(self, milestone_id, headers, payload=None):
        return self._request("POST", f"/milestones/{milestone_id}/submit", payload, headers=headers)

    def approve_milestone(self, milestone_id, headers, payload=None):
        return self._request("POST", f"/milestones/{milestone_id}/approve", payload, headers=headers)

    # ---- ArtistCall ----
    def create_call(self, commission_id, payload, headers):
        return self._request("POST", f"/commissions/{commission_id}/calls", payload, headers=headers)

    def get_call(self, call_id, headers):
        return self._request("GET", f"/calls/{call_id}", headers=headers)

    def list_calls(self, headers, params=None):
        return self._request("GET", "/calls", headers=headers, params=params)

    def close_call(self, call_id, headers, payload=None):
        return self._request("POST", f"/calls/{call_id}/close", payload, headers=headers)

    def tabulate_call(self, call_id, headers, payload=None):
        return self._request("POST", f"/calls/{call_id}/tabulate", payload, headers=headers)

    def add_panelist(self, call_id, payload, headers):
        return self._request("POST", f"/calls/{call_id}/panelists", payload, headers=headers)

    def list_panelists(self, call_id, headers):
        return self._request("GET", f"/calls/{call_id}/panelists", headers=headers)

    # ---- Artist ----
    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers=headers)

    # ---- Submission ----
    def create_submission(self, call_id, payload, headers):
        return self._request("POST", f"/calls/{call_id}/submissions", payload, headers=headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def request_revision(self, submission_id, headers, payload=None):
        return self._request("POST", f"/submissions/{submission_id}/request-revision", payload, headers=headers)

    def resubmit_submission(self, submission_id, headers, payload=None):
        return self._request("POST", f"/submissions/{submission_id}/resubmit", payload, headers=headers)

    # ---- Score ----
    def create_score(self, submission_id, payload, headers):
        return self._request("POST", f"/submissions/{submission_id}/scores", payload, headers=headers)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/scores/{score_id}", headers=headers)

    def list_scores(self, headers, params=None):
        return self._request("GET", "/scores", headers=headers, params=params)

    # ---- Site ----
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers=headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # ---- Artwork ----
    def create_artwork(self, payload, headers):
        return self._request("POST", "/artworks", payload, headers=headers)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}", headers=headers)

    def list_artworks(self, headers, params=None):
        return self._request("GET", "/artworks", headers=headers, params=params)

    def install_artwork(self, artwork_id, payload, headers):
        return self._request("POST", f"/artworks/{artwork_id}/install", payload, headers=headers)

    def deaccession_artwork(self, artwork_id, payload, headers):
        return self._request("POST", f"/artworks/{artwork_id}/deaccession", payload, headers=headers)

    def create_conservation_record(self, artwork_id, payload, headers):
        return self._request("POST", f"/artworks/{artwork_id}/conservation-records", payload, headers=headers)

    def list_conservation_records(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}/conservation-records", headers=headers)

    # ---- Loan ----
    def create_loan(self, artwork_id, payload, headers):
        return self._request("POST", f"/artworks/{artwork_id}/loans", payload, headers=headers)

    def list_loans(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}/loans", headers=headers)

    def approve_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"/loans/{loan_id}/approve", payload, headers=headers)

    def return_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"/loans/{loan_id}/return", payload, headers=headers)

    # ---- Test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
