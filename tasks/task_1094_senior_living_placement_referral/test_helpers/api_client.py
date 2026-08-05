"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Advisors ---
    def create_advisor(self, payload, headers):
        return self._request("POST", "/advisors", payload, headers=headers)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/advisors/{advisor_id}", headers=headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", "/advisors", headers=headers, params=params)

    def update_advisor(self, advisor_id, payload, headers):
        return self._request("PATCH", f"/advisors/{advisor_id}", payload, headers=headers)

    # --- Communities ---
    def create_community(self, payload, headers):
        return self._request("POST", "/communities", payload, headers=headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}", headers=headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/communities", headers=headers, params=params)

    def update_community(self, community_id, payload, headers):
        return self._request("PATCH", f"/communities/{community_id}", payload, headers=headers)

    # --- Inventories ---
    def create_inventory(self, payload, headers):
        return self._request("POST", "/inventories", payload, headers=headers)

    def get_inventory(self, inventory_id, headers):
        return self._request("GET", f"/inventories/{inventory_id}", headers=headers)

    def list_inventories(self, headers, params=None):
        return self._request("GET", "/inventories", headers=headers, params=params)

    def update_inventory(self, inventory_id, payload, headers):
        return self._request("PATCH", f"/inventories/{inventory_id}", payload, headers=headers)

    # --- Families ---
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers=headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    # --- Inquiries ---
    def create_inquiry(self, payload, headers):
        return self._request("POST", "/inquiries", payload, headers=headers)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/inquiries/{inquiry_id}", headers=headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/inquiries", headers=headers, params=params)

    def assign_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/assign", payload, headers=headers)

    def reassign_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/reassign", payload, headers=headers)

    def hold_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/hold", payload, headers=headers)

    def resume_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/resume", payload, headers=headers)

    def close_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/close", payload, headers=headers)

    # --- Assessments ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers=headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def update_assessment(self, assessment_id, payload, headers):
        return self._request("PATCH", f"/assessments/{assessment_id}", payload, headers=headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/submit", {}, headers=headers)

    def review_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/assessments/{assessment_id}/review", payload, headers=headers)

    # --- Matches ---
    def create_match(self, payload, headers):
        return self._request("POST", "/matches", payload, headers=headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def shortlist_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/shortlist", {}, headers=headers)

    def decline_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/decline", payload, headers=headers)

    def select_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/select", {}, headers=headers)

    # --- Tours ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers=headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/tours", headers=headers, params=params)

    def complete_tour(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/complete", payload, headers=headers)

    def cancel_tour(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/cancel", payload, headers=headers)

    def no_show_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/no-show", {}, headers=headers)

    # --- Placements ---
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers=headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def confirm_move_in(self, placement_id, payload, headers):
        return self._request("POST", f"/placements/{placement_id}/confirm-move-in", payload, headers=headers)

    def confirm_residency(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/confirm-residency", {}, headers=headers)

    def move_out(self, placement_id, payload, headers):
        return self._request("POST", f"/placements/{placement_id}/move-out", payload, headers=headers)

    def cancel_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/placements/{placement_id}/cancel", payload, headers=headers)

    # --- Referral invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/referral-invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/referral-invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/referral-invoices/{invoice_id}/issue", {}, headers=headers)

    def accept_invoice(self, invoice_id, headers):
        return self._request("POST", f"/referral-invoices/{invoice_id}/accept", {}, headers=headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/referral-invoices/{invoice_id}/dispute", payload, headers=headers)

    def adjust_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/referral-invoices/{invoice_id}/adjust", payload, headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/referral-invoices/{invoice_id}/pay", payload, headers=headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/referral-invoices/{invoice_id}/void", payload, headers=headers)

    # --- Ledger entries ---
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # --- Benefit guidances ---
    def create_guidance(self, payload, headers):
        return self._request("POST", "/benefit-guidances", payload, headers=headers)

    def get_guidance(self, guidance_id, headers):
        return self._request("GET", f"/benefit-guidances/{guidance_id}", headers=headers)

    def list_guidances(self, headers, params=None):
        return self._request("GET", "/benefit-guidances", headers=headers, params=params)

    # --- Surveys ---
    def create_survey(self, payload, headers):
        return self._request("POST", "/surveys", payload, headers=headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    # --- Caseload assignments ---
    def list_caseload_assignments(self, headers, params=None):
        return self._request("GET", "/caseload-assignments", headers=headers, params=params)

    def get_caseload_assignment(self, assignment_id, headers):
        return self._request("GET", f"/caseload-assignments/{assignment_id}", headers=headers)

    # --- Reports ---
    def report_advisor_caseload(self, headers, params=None):
        return self._request("GET", "/reports/advisor-caseload", headers=headers, params=params)

    def report_community_referrals(self, headers, params=None):
        return self._request("GET", "/reports/community-referrals", headers=headers, params=params)


api_client = ApiClient()
