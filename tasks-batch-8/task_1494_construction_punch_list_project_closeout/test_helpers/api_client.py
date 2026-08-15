"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/closeout/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/closeout/projects/{project_id}", headers=headers)

    def begin_punch(self, project_id, headers):
        return self._request("POST", f"/closeout/projects/{project_id}/begin-punch", headers=headers)

    def request_sc_review(self, project_id, headers):
        return self._request("POST", f"/closeout/projects/{project_id}/request-sc-review", headers=headers)

    def determine_substantial_completion(self, project_id, payload, headers):
        return self._request(
            "POST", f"/closeout/projects/{project_id}/determine-substantial-completion", payload, headers
        )

    def register_beneficial_occupancy(self, project_id, payload, headers):
        return self._request(
            "POST", f"/closeout/projects/{project_id}/register-beneficial-occupancy", payload, headers
        )

    def start_closeout(self, project_id, headers):
        return self._request("POST", f"/closeout/projects/{project_id}/start-closeout", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/closeout/projects/{project_id}/close", headers=headers)

    # --- TradePackage ---
    def create_trade_package(self, payload, headers):
        return self._request("POST", "/closeout/trade-packages", payload, headers)

    def get_trade_package(self, trade_package_id, headers):
        return self._request("GET", f"/closeout/trade-packages/{trade_package_id}", headers=headers)

    def list_trade_packages(self, headers, params=None):
        return self._request("GET", "/closeout/trade-packages", headers=headers, params=params)

    def submit_lien_waiver(self, trade_package_id, payload, headers):
        return self._request(
            "POST", f"/closeout/trade-packages/{trade_package_id}/lien-waiver-submission", payload, headers
        )

    def decide_lien_waiver(self, trade_package_id, payload, headers):
        return self._request(
            "POST", f"/closeout/trade-packages/{trade_package_id}/lien-waiver-decision", payload, headers
        )

    # --- PunchWalk ---
    def create_punch_walk(self, payload, headers):
        return self._request("POST", "/closeout/punch-walks", payload, headers)

    def get_punch_walk(self, walk_id, headers):
        return self._request("GET", f"/closeout/punch-walks/{walk_id}", headers=headers)

    def list_punch_walks(self, headers, params=None):
        return self._request("GET", "/closeout/punch-walks", headers=headers, params=params)

    def complete_punch_walk(self, walk_id, headers):
        return self._request("POST", f"/closeout/punch-walks/{walk_id}/complete", headers=headers)

    # --- PunchItem ---
    def create_punch_item(self, payload, headers):
        return self._request("POST", "/closeout/punch-items", payload, headers)

    def get_punch_item(self, item_id, headers):
        return self._request("GET", f"/closeout/punch-items/{item_id}", headers=headers)

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/closeout/punch-items", headers=headers, params=params)

    def mark_punch_item_ready(self, item_id, headers):
        return self._request("POST", f"/closeout/punch-items/{item_id}/mark-ready", headers=headers)

    def verify_punch_item(self, item_id, headers):
        return self._request("POST", f"/closeout/punch-items/{item_id}/verify", headers=headers)

    def reject_punch_item(self, item_id, payload, headers):
        return self._request("POST", f"/closeout/punch-items/{item_id}/reject", payload, headers)

    def void_punch_item(self, item_id, headers):
        return self._request("POST", f"/closeout/punch-items/{item_id}/void", headers=headers)

    # --- CloseoutDocument ---
    def create_closeout_document(self, payload, headers):
        return self._request("POST", "/closeout/closeout-documents", payload, headers)

    def get_closeout_document(self, doc_id, headers):
        return self._request("GET", f"/closeout/closeout-documents/{doc_id}", headers=headers)

    def list_closeout_documents(self, headers, params=None):
        return self._request("GET", "/closeout/closeout-documents", headers=headers, params=params)

    def approve_closeout_document(self, doc_id, headers):
        return self._request("POST", f"/closeout/closeout-documents/{doc_id}/approve", headers=headers)

    def reject_closeout_document(self, doc_id, payload, headers):
        return self._request("POST", f"/closeout/closeout-documents/{doc_id}/reject", payload, headers)

    # --- TrainingSession ---
    def create_training_session(self, payload, headers):
        return self._request("POST", "/closeout/training-sessions", payload, headers)

    def get_training_session(self, session_id, headers):
        return self._request("GET", f"/closeout/training-sessions/{session_id}", headers=headers)

    def list_training_sessions(self, headers, params=None):
        return self._request("GET", "/closeout/training-sessions", headers=headers, params=params)

    def reschedule_training_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/closeout/training-sessions/{session_id}/reschedule", payload, headers
        )

    def conduct_training_session(self, session_id, payload, headers):
        return self._request("POST", f"/closeout/training-sessions/{session_id}/conduct", payload, headers)

    # --- RetainageRelease ---
    def create_retainage_release(self, payload, headers):
        return self._request("POST", "/closeout/retainage-releases", payload, headers)

    def get_retainage_release(self, release_id, headers):
        return self._request("GET", f"/closeout/retainage-releases/{release_id}", headers=headers)

    def list_retainage_releases(self, headers, params=None):
        return self._request("GET", "/closeout/retainage-releases", headers=headers, params=params)

    def approve_retainage_release(self, release_id, headers):
        return self._request("POST", f"/closeout/retainage-releases/{release_id}/approve", headers=headers)

    def void_retainage_release(self, release_id, headers):
        return self._request("POST", f"/closeout/retainage-releases/{release_id}/void", headers=headers)

    # --- WarrantyCase ---
    def create_warranty_case(self, payload, headers):
        return self._request("POST", "/closeout/warranty-cases", payload, headers)

    def get_warranty_case(self, case_id, headers):
        return self._request("GET", f"/closeout/warranty-cases/{case_id}", headers=headers)

    def list_warranty_cases(self, headers, params=None):
        return self._request("GET", "/closeout/warranty-cases", headers=headers, params=params)

    def triage_warranty_case(self, case_id, payload, headers):
        return self._request("POST", f"/closeout/warranty-cases/{case_id}/triage", payload, headers)

    def resolve_warranty_case(self, case_id, payload, headers):
        return self._request("POST", f"/closeout/warranty-cases/{case_id}/resolve", payload, headers)

    def deny_warranty_case(self, case_id, payload, headers):
        return self._request("POST", f"/closeout/warranty-cases/{case_id}/deny", payload, headers)

    # --- Logical clock (test-driving) ---
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/closeout/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
