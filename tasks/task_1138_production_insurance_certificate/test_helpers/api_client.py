"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/productions/{production_id}", headers=headers)

    def activate_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/activate",
                             headers=headers)

    def wrap_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/wrap",
                             headers=headers)

    def cancel_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/cancel",
                             headers=headers)

    # --- Policies ---
    def create_policy(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/policies",
                             payload, headers)

    def list_policies(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/policies",
                             headers=headers, params=params)

    def get_policy(self, production_id, policy_id, headers):
        return self._request("GET", f"/productions/{production_id}/policies/{policy_id}",
                             headers=headers)

    def bind_policy(self, production_id, policy_id, payload, headers):
        return self._request("POST",
                             f"/productions/{production_id}/policies/{policy_id}/bind",
                             payload, headers)

    def cancel_policy(self, production_id, policy_id, headers):
        return self._request("POST",
                             f"/productions/{production_id}/policies/{policy_id}/cancel",
                             headers=headers)

    # --- Cast members ---
    def create_cast_member(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/cast-members",
                             payload, headers)

    def list_cast_members(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/cast-members",
                             headers=headers, params=params)

    def get_cast_member(self, production_id, cast_member_id, headers):
        return self._request(
            "GET", f"/productions/{production_id}/cast-members/{cast_member_id}",
            headers=headers)

    def record_physical_exam(self, production_id, cast_member_id, payload, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/cast-members/{cast_member_id}/physical-exam",
            payload, headers)

    def retake_physical_exam(self, production_id, cast_member_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/cast-members/{cast_member_id}/physical-exam-retake",
            headers=headers)

    # --- Cast endorsements ---
    def create_cast_endorsement(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/cast-endorsements",
                             payload, headers)

    def list_cast_endorsements(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/cast-endorsements",
                             headers=headers, params=params)

    def get_cast_endorsement(self, production_id, endorsement_id, headers):
        return self._request(
            "GET", f"/productions/{production_id}/cast-endorsements/{endorsement_id}",
            headers=headers)

    def issue_cast_endorsement(self, production_id, endorsement_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/cast-endorsements/{endorsement_id}/issue",
            headers=headers)

    def revoke_cast_endorsement(self, production_id, endorsement_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/cast-endorsements/{endorsement_id}/revoke",
            headers=headers)

    def list_all_cast_endorsements(self, headers, params=None):
        return self._request("GET", "/cast-endorsements", headers=headers, params=params)

    def get_cast_endorsement_by_id(self, endorsement_id, headers):
        return self._request("GET", f"/cast-endorsements/{endorsement_id}",
                             headers=headers)

    # --- Certificates ---
    def create_certificate(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/certificates",
                             payload, headers)

    def list_certificates(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/certificates",
                             headers=headers, params=params)

    def get_certificate(self, production_id, certificate_id, headers):
        return self._request("GET",
                             f"/productions/{production_id}/certificates/{certificate_id}",
                             headers=headers)

    def issue_certificate(self, production_id, certificate_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/certificates/{certificate_id}/issue",
            payload, headers)

    def void_certificate(self, production_id, certificate_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/certificates/{certificate_id}/void",
            headers=headers)

    # --- Claims ---
    def create_claim(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/claims",
                             payload, headers)

    def list_claims(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/claims",
                             headers=headers, params=params)

    def get_claim(self, production_id, claim_id, headers):
        return self._request("GET", f"/productions/{production_id}/claims/{claim_id}",
                             headers=headers)

    def acknowledge_claim(self, production_id, claim_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/claims/{claim_id}/acknowledge",
            headers=headers)

    def adjust_claim(self, production_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/claims/{claim_id}/adjust",
            payload, headers)

    def deny_claim(self, production_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/claims/{claim_id}/deny",
            payload, headers)

    def settle_claim(self, production_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/claims/{claim_id}/settle",
            payload, headers)

    def close_claim(self, production_id, claim_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/claims/{claim_id}/close",
            headers=headers)

    def list_claim_events(self, production_id, claim_id, headers, params=None):
        return self._request(
            "GET", f"/productions/{production_id}/claims/{claim_id}/events",
            headers=headers, params=params)

    def list_all_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim_by_id(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_all_claim_events(self, headers, params=None):
        return self._request("GET", "/claim-events", headers=headers, params=params)

    def get_claim_event_by_id(self, event_id, headers):
        return self._request("GET", f"/claim-events/{event_id}", headers=headers)

    # --- Clearance items ---
    def create_clearance_item(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/clearance-items",
                             payload, headers)

    def list_clearance_items(self, production_id, headers, params=None):
        return self._request("GET", f"/productions/{production_id}/clearance-items",
                             headers=headers, params=params)

    def get_clearance_item(self, production_id, item_id, headers):
        return self._request(
            "GET", f"/productions/{production_id}/clearance-items/{item_id}",
            headers=headers)

    def resolve_clearance_item(self, production_id, item_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/clearance-items/{item_id}/resolve",
            payload, headers)

    # --- Completion bond ---
    def apply_completion_bond(self, production_id, payload, headers):
        return self._request("POST", f"/productions/{production_id}/completion-bond",
                             payload, headers)

    def get_completion_bond(self, production_id, headers):
        return self._request("GET", f"/productions/{production_id}/completion-bond",
                             headers=headers)

    def underwrite_bond(self, production_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/completion-bond/underwrite",
            headers=headers)

    def issue_bond(self, production_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/completion-bond/issue",
            headers=headers)

    def claim_bond(self, production_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/completion-bond/claim",
            headers=headers)

    def lapse_bond(self, production_id, headers):
        return self._request(
            "POST", f"/productions/{production_id}/completion-bond/lapse",
            headers=headers)

    # --- Foreign travel extensions ---
    def create_travel_extension(self, production_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/foreign-travel-extensions",
            payload, headers)

    def list_travel_extensions(self, production_id, headers, params=None):
        return self._request(
            "GET", f"/productions/{production_id}/foreign-travel-extensions",
            headers=headers, params=params)

    def get_travel_extension(self, production_id, extension_id, headers):
        return self._request(
            "GET",
            f"/productions/{production_id}/foreign-travel-extensions/{extension_id}",
            headers=headers)

    def approve_travel_extension(self, production_id, extension_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/foreign-travel-extensions/{extension_id}/approve",
            headers=headers)

    def deny_travel_extension(self, production_id, extension_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/foreign-travel-extensions/{extension_id}/deny",
            headers=headers)

    # --- Payroll audits ---
    def create_payroll_audit(self, production_id, policy_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/policies/{policy_id}/payroll-audits",
            payload, headers)

    def list_payroll_audits(self, production_id, policy_id, headers, params=None):
        return self._request(
            "GET", f"/productions/{production_id}/policies/{policy_id}/payroll-audits",
            headers=headers, params=params)

    def get_payroll_audit(self, production_id, policy_id, audit_id, headers):
        return self._request(
            "GET",
            f"/productions/{production_id}/policies/{policy_id}/payroll-audits/{audit_id}",
            headers=headers)

    def submit_payroll_audit(self, production_id, policy_id, audit_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/policies/{policy_id}/payroll-audits/{audit_id}/submit",
            headers=headers)

    def post_payroll_audit(self, production_id, policy_id, audit_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/policies/{policy_id}/payroll-audits/{audit_id}/post",
            headers=headers)

    def dispute_payroll_audit(self, production_id, policy_id, audit_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/policies/{policy_id}/payroll-audits/{audit_id}/dispute",
            headers=headers)

    def list_all_payroll_audits(self, headers, params=None):
        return self._request("GET", "/payroll-audits", headers=headers, params=params)

    def get_payroll_audit_by_id(self, audit_id, headers):
        return self._request("GET", f"/payroll-audits/{audit_id}", headers=headers)

    # --- Renewal offers ---
    def create_renewal_offer(self, production_id, policy_id, payload, headers):
        return self._request(
            "POST", f"/productions/{production_id}/policies/{policy_id}/renewal-offers",
            payload, headers)

    def list_renewal_offers(self, production_id, policy_id, headers, params=None):
        return self._request(
            "GET", f"/productions/{production_id}/policies/{policy_id}/renewal-offers",
            headers=headers, params=params)

    def get_renewal_offer(self, production_id, policy_id, offer_id, headers):
        return self._request(
            "GET",
            f"/productions/{production_id}/policies/{policy_id}/renewal-offers/{offer_id}",
            headers=headers)

    def accept_renewal_offer(self, production_id, policy_id, offer_id, payload, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/policies/{policy_id}/renewal-offers/{offer_id}/accept",
            payload, headers)

    def decline_renewal_offer(self, production_id, policy_id, offer_id, headers):
        return self._request(
            "POST",
            f"/productions/{production_id}/policies/{policy_id}/renewal-offers/{offer_id}/decline",
            headers=headers)

    def list_all_renewal_offers(self, headers, params=None):
        return self._request("GET", "/renewal-offers", headers=headers, params=params)

    def get_renewal_offer_by_id(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)


api_client = ApiClient()
