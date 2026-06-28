"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Homeowner ---
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers=headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers=headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # --- ChargerProduct ---
    def create_charger_product(self, payload, headers):
        return self._request("POST", "/charger-products", payload, headers=headers)

    def get_charger_product(self, charger_id, headers):
        return self._request("GET", f"/charger-products/{charger_id}", headers=headers)

    # --- Electrician ---
    def create_electrician(self, payload, headers):
        return self._request("POST", "/electricians", payload, headers=headers)

    def get_electrician(self, electrician_id, headers):
        return self._request("GET", f"/electricians/{electrician_id}", headers=headers)

    def set_electrician_status(self, electrician_id, payload, headers):
        return self._request("POST", f"/_electricians/{electrician_id}/set-status",
                             payload, headers=headers)

    # --- InstallJob ---
    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers=headers)

    def get_install_job(self, job_id, headers):
        return self._request("GET", f"/install-jobs/{job_id}", headers=headers)

    def list_install_jobs(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def scope_install_job(self, job_id, payload, headers):
        return self._request("PATCH", f"/install-jobs/{job_id}/scope", payload, headers=headers)

    def activate_install_job(self, job_id, payload, headers):
        return self._request("POST", f"/install-jobs/{job_id}/activate", payload, headers=headers)

    def cancel_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/cancel", headers=headers)

    def close_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/close", headers=headers)

    # --- SiteAssessment ---
    def create_site_assessment(self, payload, headers):
        return self._request("POST", "/site-assessments", payload, headers=headers)

    def get_site_assessment(self, assessment_id, headers):
        return self._request("GET", f"/site-assessments/{assessment_id}", headers=headers)

    def list_site_assessments(self, headers, params=None):
        return self._request("GET", "/site-assessments", headers=headers, params=params)

    def accept_site_assessment(self, assessment_id, headers):
        return self._request("POST", f"/site-assessments/{assessment_id}/accept", headers=headers)

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers=headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", headers=headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers=headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", headers=headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/revise", payload, headers=headers)

    # --- PermitApplication ---
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers=headers)

    def get_permit_application(self, permit_id, headers):
        return self._request("GET", f"/permit-applications/{permit_id}", headers=headers)

    def list_permit_applications(self, headers, params=None):
        return self._request("GET", "/permit-applications", headers=headers, params=params)

    def approve_permit_application(self, permit_id, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/approve", headers=headers)

    def request_corrections_permit_application(self, permit_id, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/request-corrections",
                             headers=headers)

    def resubmit_permit_application(self, permit_id, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/resubmit", headers=headers)

    # --- InterconnectionRequest ---
    def create_interconnection_request(self, payload, headers):
        return self._request("POST", "/interconnection-requests", payload, headers=headers)

    def get_interconnection_request(self, ic_id, headers):
        return self._request("GET", f"/interconnection-requests/{ic_id}", headers=headers)

    def list_interconnection_requests(self, headers, params=None):
        return self._request("GET", "/interconnection-requests", headers=headers, params=params)

    def start_review_interconnection_request(self, ic_id, headers):
        return self._request("POST", f"/interconnection-requests/{ic_id}/start-review",
                             headers=headers)

    def approve_interconnection_request(self, ic_id, headers):
        return self._request("POST", f"/interconnection-requests/{ic_id}/approve", headers=headers)

    def deny_interconnection_request(self, ic_id, headers):
        return self._request("POST", f"/interconnection-requests/{ic_id}/deny", headers=headers)

    # --- DispatchAssignment ---
    def create_dispatch_assignment(self, payload, headers):
        return self._request("POST", "/dispatch-assignments", payload, headers=headers)

    def get_dispatch_assignment(self, da_id, headers):
        return self._request("GET", f"/dispatch-assignments/{da_id}", headers=headers)

    def list_dispatch_assignments(self, headers, params=None):
        return self._request("GET", "/dispatch-assignments", headers=headers, params=params)

    def depart_dispatch_assignment(self, da_id, headers):
        return self._request("POST", f"/dispatch-assignments/{da_id}/depart", headers=headers)

    def complete_dispatch_assignment(self, da_id, headers):
        return self._request("POST", f"/dispatch-assignments/{da_id}/complete", headers=headers)

    def cancel_dispatch_assignment(self, da_id, headers):
        return self._request("POST", f"/dispatch-assignments/{da_id}/cancel", headers=headers)

    # --- IncentiveClaim ---
    def create_incentive_claim(self, payload, headers):
        return self._request("POST", "/incentive-claims", payload, headers=headers)

    def get_incentive_claim(self, claim_id, headers):
        return self._request("GET", f"/incentive-claims/{claim_id}", headers=headers)

    def list_incentive_claims(self, headers, params=None):
        return self._request("GET", "/incentive-claims", headers=headers, params=params)

    def submit_incentive_claim(self, claim_id, headers):
        return self._request("POST", f"/incentive-claims/{claim_id}/submit", headers=headers)

    def pay_incentive_claim(self, claim_id, headers):
        return self._request("POST", f"/incentive-claims/{claim_id}/pay", headers=headers)

    def reverse_incentive_claim(self, claim_id, headers):
        return self._request("POST", f"/incentive-claims/{claim_id}/reverse", headers=headers)

    # --- PanelUpgradeReferral ---
    def get_panel_upgrade_referral(self, referral_id, headers):
        return self._request("GET", f"/panel-upgrade-referrals/{referral_id}", headers=headers)

    def list_panel_upgrade_referrals(self, headers, params=None):
        return self._request("GET", "/panel-upgrade-referrals", headers=headers, params=params)

    def accept_panel_upgrade_referral(self, referral_id, headers):
        return self._request("POST", f"/panel-upgrade-referrals/{referral_id}/accept",
                             headers=headers)

    def decline_panel_upgrade_referral(self, referral_id, headers):
        return self._request("POST", f"/panel-upgrade-referrals/{referral_id}/decline",
                             headers=headers)

    def complete_panel_upgrade_referral(self, referral_id, headers):
        return self._request("POST", f"/panel-upgrade-referrals/{referral_id}/complete",
                             headers=headers)

    # --- WarrantyTicket ---
    def create_warranty_ticket(self, payload, headers):
        return self._request("POST", "/warranty-tickets", payload, headers=headers)

    def get_warranty_ticket(self, ticket_id, headers):
        return self._request("GET", f"/warranty-tickets/{ticket_id}", headers=headers)

    def list_warranty_tickets(self, headers, params=None):
        return self._request("GET", "/warranty-tickets", headers=headers, params=params)

    def diagnose_warranty_ticket(self, ticket_id, headers):
        return self._request("POST", f"/warranty-tickets/{ticket_id}/diagnose", headers=headers)

    def order_parts_warranty_ticket(self, ticket_id, headers):
        return self._request("POST", f"/warranty-tickets/{ticket_id}/order-parts", headers=headers)

    def parts_received_warranty_ticket(self, ticket_id, headers):
        return self._request("POST", f"/warranty-tickets/{ticket_id}/parts-received",
                             headers=headers)

    def resolve_warranty_ticket(self, ticket_id, headers):
        return self._request("POST", f"/warranty-tickets/{ticket_id}/resolve", headers=headers)

    def reopen_warranty_ticket(self, ticket_id, headers):
        return self._request("POST", f"/warranty-tickets/{ticket_id}/reopen", headers=headers)

    def close_warranty_ticket(self, ticket_id, headers):
        return self._request("POST", f"/warranty-tickets/{ticket_id}/close", headers=headers)


api_client = ApiClient()
