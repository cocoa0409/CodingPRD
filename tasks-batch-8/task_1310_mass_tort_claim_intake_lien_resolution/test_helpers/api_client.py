"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/settlement-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/settlement-programs", headers=headers, params=params)

    def get_program(self, pid, headers):
        return self._request("GET", f"/settlement-programs/{pid}", headers=headers)

    def set_clock(self, pid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/_clock/set_current_utc", payload, headers)

    # --- Tier matrices ---
    def create_tier_matrix(self, pid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/tier-matrices", payload, headers)

    def list_tier_matrices(self, pid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/tier-matrices", headers=headers, params=params)

    def get_tier_matrix(self, pid, tmid, headers):
        return self._request("GET", f"/settlement-programs/{pid}/tier-matrices/{tmid}", headers=headers)

    def publish_tier_matrix(self, pid, tmid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/tier-matrices/{tmid}/publish", {}, headers)

    # --- Claimants ---
    def create_claimant(self, pid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claimants", payload, headers)

    def list_claimants(self, pid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claimants", headers=headers, params=params)

    def get_claimant(self, pid, clid, headers):
        return self._request("GET", f"/settlement-programs/{pid}/claimants/{clid}", headers=headers)

    # --- Claims ---
    def create_claim(self, pid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims", payload, headers)

    def list_claims(self, pid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claims", headers=headers, params=params)

    def get_claim(self, pid, cid, headers):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}", headers=headers)

    def screen_eligibility(self, pid, cid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/screen-eligibility", {}, headers)

    def deny_claim(self, pid, cid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/deny", payload, headers)

    def withdraw_claim(self, pid, cid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/withdraw", {}, headers)

    # --- Medical records ---
    def create_medical_record(self, pid, cid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/medical-records", payload, headers)

    def list_medical_records(self, pid, cid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/medical-records", headers=headers, params=params)

    def get_medical_record(self, pid, cid, rid, headers):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/medical-records/{rid}", headers=headers)

    def accept_medical_record(self, pid, cid, rid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/medical-records/{rid}/accept", {}, headers)

    def reject_medical_record(self, pid, cid, rid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/medical-records/{rid}/reject", {}, headers)

    def verify_injury(self, pid, cid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/verify-injury", {}, headers)

    # --- Tier assignment ---
    def assign_tier(self, pid, cid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/assign-tier", payload, headers)

    # --- Appeals ---
    def create_appeal(self, pid, cid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/appeals", payload, headers)

    def list_appeals(self, pid, cid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/appeals", headers=headers, params=params)

    def get_appeal(self, pid, cid, aid, headers):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/appeals/{aid}", headers=headers)

    def begin_appeal_review(self, pid, cid, aid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/appeals/{aid}/begin-review", {}, headers)

    def uphold_appeal(self, pid, cid, aid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/appeals/{aid}/uphold", payload, headers)

    def deny_appeal(self, pid, cid, aid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/appeals/{aid}/deny", payload, headers)

    def withdraw_appeal(self, pid, cid, aid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/appeals/{aid}/withdraw", {}, headers)

    # --- Liens ---
    def create_lien(self, pid, cid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/liens", payload, headers)

    def list_liens(self, pid, cid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/liens", headers=headers, params=params)

    def get_lien(self, pid, cid, lid, headers):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/liens/{lid}", headers=headers)

    def notify_lien(self, pid, cid, lid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/liens/{lid}/notify", {}, headers)

    def begin_lien_negotiation(self, pid, cid, lid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/liens/{lid}/begin-negotiation", {}, headers)

    def dispute_lien(self, pid, cid, lid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/liens/{lid}/dispute", {}, headers)

    def resolve_lien(self, pid, cid, lid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/liens/{lid}/resolve", payload, headers)

    def waive_lien(self, pid, cid, lid, payload, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/liens/{lid}/waive", payload, headers)

    def finalize_liens(self, pid, cid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/finalize-liens", {}, headers)

    # --- Disbursements ---
    def prepare_disbursement(self, pid, cid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/prepare-disbursement", {}, headers)

    def list_disbursements(self, pid, cid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/disbursements", headers=headers, params=params)

    def get_disbursement(self, pid, cid, did, headers):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/disbursements/{did}", headers=headers)

    def approve_disbursement(self, pid, cid, did, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/disbursements/{did}/approve", {}, headers)

    def release_disbursement(self, pid, cid, did, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/disbursements/{did}/release", {}, headers)

    def void_disbursement(self, pid, cid, did, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/disbursements/{did}/void", {}, headers)

    # --- Closing ---
    def close_claim(self, pid, cid, headers):
        return self._request("POST", f"/settlement-programs/{pid}/claims/{cid}/close", {}, headers)

    def list_closing_statements(self, pid, cid, headers, params=None):
        return self._request("GET", f"/settlement-programs/{pid}/claims/{cid}/closing-statements", headers=headers, params=params)

    # --- Flat aliases (PRD §2.7) ---
    def get_claimant_flat(self, clid, headers):
        return self._request("GET", f"/settlement-programs/claimants/{clid}", headers=headers)

    def get_claim_flat(self, cid, headers):
        return self._request("GET", f"/settlement-programs/claims/{cid}", headers=headers)

    def get_tier_matrix_flat(self, tmid, headers):
        return self._request("GET", f"/settlement-programs/tier-matrices/{tmid}", headers=headers)

    def get_medical_record_flat(self, rid, headers):
        return self._request("GET", f"/settlement-programs/medical-records/{rid}", headers=headers)

    def get_lien_flat(self, lid, headers):
        return self._request("GET", f"/settlement-programs/liens/{lid}", headers=headers)

    def get_appeal_flat(self, aid, headers):
        return self._request("GET", f"/settlement-programs/appeals/{aid}", headers=headers)

    def get_disbursement_flat(self, did, headers):
        return self._request("GET", f"/settlement-programs/disbursements/{did}", headers=headers)

    def get_closing_statement_flat(self, csid, headers):
        return self._request("GET", f"/settlement-programs/closing-statements/{csid}", headers=headers)

    def list_claimants_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/claimants", headers=headers, params=params)

    def list_claims_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/claims", headers=headers, params=params)

    def list_tier_matrices_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/tier-matrices", headers=headers, params=params)

    def list_medical_records_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/medical-records", headers=headers, params=params)

    def list_liens_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/liens", headers=headers, params=params)

    def list_appeals_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/appeals", headers=headers, params=params)

    def list_disbursements_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/disbursements", headers=headers, params=params)

    def list_closing_statements_flat(self, headers, params=None):
        return self._request("GET", "/settlement-programs/closing-statements", headers=headers, params=params)


api_client = ApiClient()
