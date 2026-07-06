"""API client — one method per endpoint declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- Ledger admin-adjust -----
    def admin_adjust_ledger(self, payload, headers):
        return self._request("POST", "/_ledger/admin-adjust", payload, headers)

    # ----- Members -----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def list_member_ledger_entries(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/ledger-entries",
                             headers=headers, params=params)

    # ----- Skill offers -----
    def create_skill_offer(self, payload, headers):
        return self._request("POST", "/skill-offers", payload, headers)

    def list_skill_offers(self, headers, params=None):
        return self._request("GET", "/skill-offers", headers=headers, params=params)

    def get_skill_offer(self, offer_id, headers):
        return self._request("GET", f"/skill-offers/{offer_id}", headers=headers)

    def pause_skill_offer(self, offer_id, headers):
        return self._request("POST", f"/skill-offers/{offer_id}/pause", headers=headers)

    def resume_skill_offer(self, offer_id, headers):
        return self._request("POST", f"/skill-offers/{offer_id}/resume", headers=headers)

    def archive_skill_offer(self, offer_id, headers):
        return self._request("POST", f"/skill-offers/{offer_id}/archive", headers=headers)

    # ----- Skill requests -----
    def create_skill_request(self, payload, headers):
        return self._request("POST", "/skill-requests", payload, headers)

    def list_skill_requests(self, headers, params=None):
        return self._request("GET", "/skill-requests", headers=headers, params=params)

    def get_skill_request(self, request_id, headers):
        return self._request("GET", f"/skill-requests/{request_id}", headers=headers)

    def cancel_skill_request(self, request_id, headers):
        return self._request("POST", f"/skill-requests/{request_id}/cancel", headers=headers)

    # ----- Exchanges -----
    def create_exchange(self, payload, headers):
        return self._request("POST", "/exchanges", payload, headers)

    def list_exchanges(self, headers, params=None):
        return self._request("GET", "/exchanges", headers=headers, params=params)

    def get_exchange(self, exchange_id, headers):
        return self._request("GET", f"/exchanges/{exchange_id}", headers=headers)

    def mark_exchange_delivered(self, exchange_id, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/mark-delivered", headers=headers)

    def settle_exchange(self, exchange_id, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/settle", headers=headers)

    def cancel_exchange(self, exchange_id, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/cancel", headers=headers)

    # ----- Ledger entries -----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ----- Redemptions -----
    def create_redemption(self, payload, headers):
        return self._request("POST", "/redemptions", payload, headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/redemptions/{redemption_id}", headers=headers)

    def fulfill_redemption(self, redemption_id, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/fulfill", headers=headers)

    def void_redemption(self, redemption_id, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/void", headers=headers)

    # ----- Verification credentials -----
    def create_credential(self, payload, headers):
        return self._request("POST", "/credentials", payload, headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/credentials", headers=headers, params=params)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def verify_credential(self, credential_id, headers):
        return self._request("POST", f"/credentials/{credential_id}/verify", headers=headers)

    def reject_credential(self, credential_id, headers):
        return self._request("POST", f"/credentials/{credential_id}/reject", headers=headers)

    def request_revision(self, credential_id, headers):
        return self._request("POST", f"/credentials/{credential_id}/request-revision", headers=headers)

    def resubmit_credential(self, credential_id, payload, headers):
        return self._request("POST", f"/credentials/{credential_id}/resubmit", payload, headers)

    # ----- Group projects -----
    def create_group_project(self, payload, headers):
        return self._request("POST", "/group-projects", payload, headers)

    def list_group_projects(self, headers, params=None):
        return self._request("GET", "/group-projects", headers=headers, params=params)

    def get_group_project(self, project_id, headers):
        return self._request("GET", f"/group-projects/{project_id}", headers=headers)

    def publish_group_project(self, project_id, headers):
        return self._request("POST", f"/group-projects/{project_id}/publish", headers=headers)

    def cancel_group_project(self, project_id, headers):
        return self._request("POST", f"/group-projects/{project_id}/cancel", headers=headers)

    def create_project_shift(self, project_id, payload, headers):
        return self._request("POST", f"/group-projects/{project_id}/shifts", payload, headers)

    def list_project_shifts(self, project_id, headers, params=None):
        return self._request("GET", f"/group-projects/{project_id}/shifts",
                             headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def create_shift_assignment(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/assignments", payload, headers)

    def list_shift_assignments(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/assignments",
                             headers=headers, params=params)

    def cancel_shift_assignment(self, shift_id, assignment_id, headers):
        return self._request("DELETE", f"/shifts/{shift_id}/assignments/{assignment_id}",
                             headers=headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", headers=headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    # ----- Disputes -----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", headers=headers)

    # ----- Impact reports -----
    def create_impact_report(self, payload, headers):
        return self._request("POST", "/impact-reports", payload, headers)

    def list_impact_reports(self, headers, params=None):
        return self._request("GET", "/impact-reports", headers=headers, params=params)

    def get_impact_report(self, report_id, headers):
        return self._request("GET", f"/impact-reports/{report_id}", headers=headers)


api_client = ApiClient()
