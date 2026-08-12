"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Retailer ---
    def create_retailer(self, payload, headers):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, rid, headers):
        return self._request("GET", f"/retailers/{rid}", headers=headers)

    # --- Category (nested) ---
    def create_category(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories", payload, headers)

    def list_categories(self, rid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/categories", headers=headers, params=params)

    def get_category(self, rid, cid, headers):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}", headers=headers)

    def lock_category(self, rid, cid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/lock", {}, headers)

    def unlock_category(self, rid, cid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/unlock", {}, headers)

    def archive_category(self, rid, cid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/archive", {}, headers)

    def get_space_to_sales(self, rid, cid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/space-to-sales", headers=headers, params=params)

    # --- Supplier ---
    def create_supplier(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/suppliers", payload, headers)

    def list_suppliers(self, rid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/suppliers", headers=headers, params=params)

    def get_supplier(self, rid, sid, headers):
        return self._request("GET", f"/retailers/{rid}/suppliers/{sid}", headers=headers)

    def appoint_captain(self, rid, sid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/suppliers/{sid}/appoint-captain", payload, headers)

    # --- Product ---
    def create_product(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/products", payload, headers)

    def list_products(self, rid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/products", headers=headers, params=params)

    def get_product(self, rid, pid, headers):
        return self._request("GET", f"/retailers/{rid}/products/{pid}", headers=headers)

    def list_product_cut_in(self, rid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/products/{pid}/list", {}, headers)

    def discontinue_product(self, rid, pid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/products/{pid}/discontinue", payload, headers)

    def cancel_discontinuation(self, rid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/products/{pid}/cancel-discontinuation", {}, headers)

    def relist_product(self, rid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/products/{pid}/relist", {}, headers)

    # --- Planogram ---
    def create_planogram(self, rid, cid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms", payload, headers)

    def list_planograms(self, rid, cid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/planograms", headers=headers, params=params)

    def get_planogram(self, rid, cid, pid, headers):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/planograms/{pid}", headers=headers)

    def submit_planogram(self, rid, cid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/submit", {}, headers)

    def approve_planogram(self, rid, cid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/approve", {}, headers)

    def reject_planogram(self, rid, cid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/reject", {}, headers)

    def return_planogram_to_draft(self, rid, cid, pid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/return-to-draft", {}, headers)

    def activate_planogram(self, rid, cid, pid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/activate", payload, headers)

    # --- PlanogramLine ---
    def create_planogram_line(self, rid, cid, pid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/lines", payload, headers)

    def list_planogram_lines(self, rid, cid, pid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/lines", headers=headers, params=params)

    def get_planogram_line(self, rid, cid, pid, lid, headers):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/lines/{lid}", headers=headers)

    def delete_planogram_line(self, rid, cid, pid, lid, headers):
        return self._request("DELETE", f"/retailers/{rid}/categories/{cid}/planograms/{pid}/lines/{lid}", headers=headers)

    # --- Store ---
    def create_store(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/stores", payload, headers)

    def list_stores(self, rid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/stores", headers=headers, params=params)

    def get_store(self, rid, sid, headers):
        return self._request("GET", f"/retailers/{rid}/stores/{sid}", headers=headers)

    # --- Audit ---
    def create_audit(self, rid, sid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/stores/{sid}/audits", payload, headers)

    def list_audits(self, rid, sid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/stores/{sid}/audits", headers=headers, params=params)

    def get_audit(self, rid, sid, aid, headers):
        return self._request("GET", f"/retailers/{rid}/stores/{sid}/audits/{aid}", headers=headers)

    def score_audit(self, rid, sid, aid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/stores/{sid}/audits/{aid}/score", payload, headers)

    def reject_audit(self, rid, sid, aid, headers):
        return self._request("POST", f"/retailers/{rid}/stores/{sid}/audits/{aid}/reject", {}, headers)

    # --- Funding deal ---
    def create_funding_deal(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/funding-deals", payload, headers)

    def list_funding_deals(self, rid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/funding-deals", headers=headers, params=params)

    def get_funding_deal(self, rid, fdid, headers):
        return self._request("GET", f"/retailers/{rid}/funding-deals/{fdid}", headers=headers)

    def approve_funding_deal(self, rid, fdid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/funding-deals/{fdid}/approve", payload, headers)

    def reject_funding_deal(self, rid, fdid, headers):
        return self._request("POST", f"/retailers/{rid}/funding-deals/{fdid}/reject", {}, headers)

    # --- Reset project ---
    def create_reset_project(self, rid, cid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/reset-projects", payload, headers)

    def list_reset_projects(self, rid, cid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/reset-projects", headers=headers, params=params)

    def get_reset_project(self, rid, cid, rpid, headers):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}", headers=headers)

    def schedule_reset_project(self, rid, cid, rpid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/schedule", payload, headers)

    def complete_reset_project(self, rid, cid, rpid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/complete", {}, headers)

    def cancel_reset_project(self, rid, cid, rpid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/cancel", {}, headers)

    # --- Reset crew ---
    def create_reset_crew(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/reset-crews", payload, headers)

    def list_reset_crews(self, rid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/reset-crews", headers=headers, params=params)

    def get_reset_crew(self, rid, rcid, headers):
        return self._request("GET", f"/retailers/{rid}/reset-crews/{rcid}", headers=headers)

    # --- Reset assignment ---
    def create_reset_assignment(self, rid, cid, rpid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/assignments", payload, headers)

    def list_reset_assignments(self, rid, cid, rpid, headers, params=None):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/assignments", headers=headers, params=params)

    def get_reset_assignment(self, rid, cid, rpid, raid, headers):
        return self._request("GET", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/assignments/{raid}", headers=headers)

    def release_reset_assignment(self, rid, cid, rpid, raid, headers):
        return self._request("POST", f"/retailers/{rid}/categories/{cid}/reset-projects/{rpid}/assignments/{raid}/release", {}, headers)

    # --- Flat collection endpoints (FK reverse reachability) ---
    def flat_list_categories(self, headers, params=None):
        return self._request("GET", "/categories", headers=headers, params=params)

    def flat_list_suppliers(self, headers, params=None):
        return self._request("GET", "/suppliers", headers=headers, params=params)

    def flat_list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def flat_list_planograms(self, headers, params=None):
        return self._request("GET", "/planograms", headers=headers, params=params)

    def flat_list_planogram_lines(self, headers, params=None):
        return self._request("GET", "/planogram-lines", headers=headers, params=params)

    def flat_list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def flat_list_audits(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    def flat_list_funding_deals(self, headers, params=None):
        return self._request("GET", "/funding-deals", headers=headers, params=params)

    def flat_list_reset_projects(self, headers, params=None):
        return self._request("GET", "/reset-projects", headers=headers, params=params)

    def flat_list_reset_crews(self, headers, params=None):
        return self._request("GET", "/reset-crews", headers=headers, params=params)

    def flat_list_reset_assignments(self, headers, params=None):
        return self._request("GET", "/reset-assignments", headers=headers, params=params)

    def flat_get_category(self, cid, headers):
        return self._request("GET", f"/categories/{cid}", headers=headers)

    def flat_get_supplier(self, sid, headers):
        return self._request("GET", f"/suppliers/{sid}", headers=headers)

    def flat_get_product(self, pid, headers):
        return self._request("GET", f"/products/{pid}", headers=headers)

    def flat_get_planogram(self, pid, headers):
        return self._request("GET", f"/planograms/{pid}", headers=headers)

    def flat_get_planogram_line(self, lid, headers):
        return self._request("GET", f"/planogram-lines/{lid}", headers=headers)

    def flat_get_store(self, sid, headers):
        return self._request("GET", f"/stores/{sid}", headers=headers)

    def flat_get_audit(self, aid, headers):
        return self._request("GET", f"/audit-events/{aid}", headers=headers)

    def flat_get_funding_deal(self, fdid, headers):
        return self._request("GET", f"/funding-deals/{fdid}", headers=headers)

    def flat_get_reset_project(self, rpid, headers):
        return self._request("GET", f"/reset-projects/{rpid}", headers=headers)

    def flat_get_reset_crew(self, rcid, headers):
        return self._request("GET", f"/reset-crews/{rcid}", headers=headers)

    def flat_get_reset_assignment(self, raid, headers):
        return self._request("GET", f"/reset-assignments/{raid}", headers=headers)

    # --- Logical clock ---
    def set_current_utc(self, rid, payload, headers):
        return self._request("POST", f"/retailers/{rid}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
