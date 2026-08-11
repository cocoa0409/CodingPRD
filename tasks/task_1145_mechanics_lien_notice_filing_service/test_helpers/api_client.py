"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Company ---
    def create_company(self, payload, headers):
        return self._request("POST", "/lien/companies", payload, headers)

    def get_company(self, company_id, headers):
        return self._request("GET", f"/lien/companies/{company_id}", headers=headers)

    def create_balance_adjustment(self, company_id, payload, headers):
        return self._request(
            "POST", f"/lien/companies/{company_id}/balance-adjustments", payload, headers
        )

    def list_company_projects(self, company_id, headers, params=None):
        return self._request(
            "GET", f"/lien/companies/{company_id}/projects", headers=headers, params=params
        )

    # --- JurisdictionRule ---
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/lien/jurisdiction-rules", payload, headers)

    def supersede_jurisdiction_rule(self, rule_id, payload, headers):
        return self._request(
            "POST", f"/lien/jurisdiction-rules/{rule_id}/supersede", payload, headers
        )

    def get_jurisdiction_rule(self, rule_id, headers):
        return self._request("GET", f"/lien/jurisdiction-rules/{rule_id}", headers=headers)

    def list_rule_successors(self, rule_id, headers, params=None):
        return self._request(
            "GET", f"/lien/jurisdiction-rules/{rule_id}/successors",
            headers=headers, params=params,
        )

    def list_rule_lien_claims(self, rule_id, headers, params=None):
        return self._request(
            "GET", f"/lien/jurisdiction-rules/{rule_id}/lien-claims",
            headers=headers, params=params,
        )

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/lien/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/lien/projects/{project_id}", headers=headers)

    def research_advance(self, project_id, headers):
        return self._request(
            "POST", f"/lien/projects/{project_id}/research-advance", {}, headers
        )

    def get_deadline_calendar(self, project_id, headers):
        return self._request(
            "GET", f"/lien/projects/{project_id}/deadline-calendar", headers=headers
        )

    def list_project_parties(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/parties", headers=headers, params=params
        )

    def list_project_furnishing_spans(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/furnishing-spans",
            headers=headers, params=params,
        )

    def list_project_notices(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/notices", headers=headers, params=params
        )

    def list_project_lien_claims(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/lien-claims", headers=headers, params=params
        )

    def list_project_waivers(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/waivers", headers=headers, params=params
        )

    def list_project_payments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/payments", headers=headers, params=params
        )

    def list_project_stop_notices(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/stop-notices", headers=headers, params=params
        )

    def list_project_bond_claims(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/lien/projects/{project_id}/bond-claims", headers=headers, params=params
        )

    # --- Party ---
    def create_party(self, payload, headers):
        return self._request("POST", "/lien/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/lien/parties/{party_id}", headers=headers)

    def decide_party(self, party_id, payload, headers):
        return self._request("POST", f"/lien/parties/{party_id}/decide", payload, headers)

    def list_party_notices(self, party_id, headers, params=None):
        return self._request(
            "GET", f"/lien/parties/{party_id}/notices", headers=headers, params=params
        )

    def list_party_bonding_requests(self, party_id, headers, params=None):
        return self._request(
            "GET", f"/lien/parties/{party_id}/bonding-requests", headers=headers, params=params
        )

    def list_party_bond_claims(self, party_id, headers, params=None):
        return self._request(
            "GET", f"/lien/parties/{party_id}/bond-claims", headers=headers, params=params
        )

    # --- FurnishingSpan ---
    def create_furnishing_span(self, payload, headers):
        return self._request("POST", "/lien/furnishing-spans", payload, headers)

    # --- NoticeOrder ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/lien/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/lien/notices/{notice_id}", headers=headers)

    def serve_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/lien/notices/{notice_id}/serve", payload, headers)

    def record_notice_proof(self, notice_id, payload, headers):
        return self._request("POST", f"/lien/notices/{notice_id}/proof", payload, headers)

    def reprepare_notice(self, notice_id, headers):
        return self._request("POST", f"/lien/notices/{notice_id}/reprepare", {}, headers)

    # --- LienClaim ---
    def create_lien_claim(self, payload, headers):
        return self._request("POST", "/lien/lien-claims", payload, headers)

    def get_lien_claim(self, claim_id, headers):
        return self._request("GET", f"/lien/lien-claims/{claim_id}", headers=headers)

    def lock_lien_claim(self, claim_id, headers):
        return self._request("POST", f"/lien/lien-claims/{claim_id}/lock", {}, headers)

    def unlock_lien_claim(self, claim_id, headers):
        return self._request("POST", f"/lien/lien-claims/{claim_id}/unlock", {}, headers)

    def file_lien_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/lien/lien-claims/{claim_id}/file", payload, headers)

    def release_lien_claim(self, claim_id, headers):
        return self._request("POST", f"/lien/lien-claims/{claim_id}/release", {}, headers)

    def list_claim_payments(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/lien/lien-claims/{claim_id}/payments", headers=headers, params=params
        )

    def list_claim_bonding_requests(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/lien/lien-claims/{claim_id}/bonding-requests",
            headers=headers, params=params,
        )

    def list_claim_foreclosure_referrals(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/lien/lien-claims/{claim_id}/foreclosure-referrals",
            headers=headers, params=params,
        )

    # --- Waiver ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/lien/waivers", payload, headers)

    def apply_waiver(self, waiver_id, headers):
        return self._request("POST", f"/lien/waivers/{waiver_id}/apply", {}, headers)

    def void_waiver(self, waiver_id, headers):
        return self._request("POST", f"/lien/waivers/{waiver_id}/void", {}, headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/lien/payments", payload, headers)

    def verify_payment(self, payment_id, headers):
        return self._request("POST", f"/lien/payments/{payment_id}/verify", {}, headers)

    # --- BondingRequest ---
    def create_bonding_request(self, payload, headers):
        return self._request("POST", "/lien/bonding-requests", payload, headers)

    def record_bonding_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/lien/bonding-requests/{request_id}/record", payload, headers
        )

    def reject_bonding_request(self, request_id, headers):
        return self._request(
            "POST", f"/lien/bonding-requests/{request_id}/reject", {}, headers
        )

    # --- ForeclosureReferral ---
    def create_foreclosure_referral(self, payload, headers):
        return self._request("POST", "/lien/foreclosure-referrals", payload, headers)

    def send_foreclosure_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/lien/foreclosure-referrals/{referral_id}/send", payload, headers
        )

    def respond_foreclosure_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/lien/foreclosure-referrals/{referral_id}/respond", payload, headers
        )

    def mark_suit_filed(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/lien/foreclosure-referrals/{referral_id}/mark-suit-filed",
            payload, headers,
        )

    # --- StopNotice ---
    def create_stop_notice(self, payload, headers):
        return self._request("POST", "/lien/stop-notices", payload, headers)

    def serve_stop_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/lien/stop-notices/{notice_id}/serve", payload, headers)

    def release_stop_notice(self, notice_id, headers):
        return self._request("POST", f"/lien/stop-notices/{notice_id}/release", {}, headers)

    # --- BondClaim ---
    def create_bond_claim(self, payload, headers):
        return self._request("POST", "/lien/bond-claims", payload, headers)

    def submit_bond_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/lien/bond-claims/{claim_id}/submit", payload, headers)

    def resolve_bond_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/lien/bond-claims/{claim_id}/resolve", payload, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
