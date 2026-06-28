"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Importer ----
    def create_importer(self, payload, headers):
        return self._request("POST", "/importers", payload, headers)

    def get_importer(self, importer_id, headers):
        return self._request("GET", f"/importers/{importer_id}", headers=headers)

    def list_importers(self, headers, params=None):
        return self._request("GET", "/importers", headers=headers, params=params)

    # ---- Bond ----
    def create_bond(self, payload, headers):
        return self._request("POST", "/bonds", payload, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/bonds", headers=headers, params=params)

    def activate_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/activate", {}, headers)

    def terminate_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/terminate", {}, headers)

    # ---- ISF ----
    def create_isf(self, payload, headers):
        return self._request("POST", "/isf-filings", payload, headers)

    def get_isf(self, isf_id, headers):
        return self._request("GET", f"/isf-filings/{isf_id}", headers=headers)

    def list_isf(self, headers, params=None):
        return self._request("GET", "/isf-filings", headers=headers, params=params)

    def file_isf(self, isf_id, headers):
        return self._request("POST", f"/isf-filings/{isf_id}/file", {}, headers)

    def cancel_isf(self, isf_id, headers):
        return self._request("POST", f"/isf-filings/{isf_id}/cancel", {}, headers)

    # ---- CustomsEntry ----
    def create_entry(self, payload, headers):
        return self._request("POST", "/entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/entries", headers=headers, params=params)

    def create_line(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/lines", payload, headers)

    def list_lines(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/entries/{entry_id}/lines", headers=headers, params=params
        )

    def file_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/file", {}, headers)

    def review_entry(self, entry_id, action, headers):
        return self._request(
            "POST", f"/entries/{entry_id}/review", {"action": action}, headers
        )

    def liquidate_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/liquidate", {}, headers)

    def cancel_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/cancel", {}, headers)

    # ---- PGA Review ----
    def create_pga_review(self, payload, headers):
        return self._request("POST", "/pga-reviews", payload, headers)

    def get_pga_review(self, pga_id, headers):
        return self._request("GET", f"/pga-reviews/{pga_id}", headers=headers)

    def list_pga_reviews(self, headers, params=None):
        return self._request("GET", "/pga-reviews", headers=headers, params=params)

    def decide_pga_review(self, pga_id, decision, headers):
        return self._request(
            "POST", f"/pga-reviews/{pga_id}/decide", {"decision": decision}, headers
        )

    # ---- Exam Slot ----
    def create_exam_slot(self, payload, headers):
        return self._request("POST", "/exam-slots", payload, headers)

    def get_exam_slot(self, slot_id, headers):
        return self._request("GET", f"/exam-slots/{slot_id}", headers=headers)

    def list_exam_slots(self, headers, params=None):
        return self._request("GET", "/exam-slots", headers=headers, params=params)

    def cancel_exam_slot(self, slot_id, headers):
        return self._request("POST", f"/exam-slots/{slot_id}/cancel", {}, headers)

    # ---- Monthly Statement ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/monthly-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/monthly-statements/{statement_id}", headers=headers
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", "/monthly-statements", headers=headers, params=params
        )

    def settle_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/monthly-statements/{statement_id}/settle", {}, headers
        )

    # ---- Post-Summary Correction / Protest ----
    def create_psc(self, payload, headers):
        return self._request("POST", "/post-summary-corrections", payload, headers)

    def get_psc(self, psc_id, headers):
        return self._request(
            "GET", f"/post-summary-corrections/{psc_id}", headers=headers
        )

    def list_pscs(self, headers, params=None):
        return self._request(
            "GET", "/post-summary-corrections", headers=headers, params=params
        )

    def grant_psc(self, psc_id, headers):
        return self._request(
            "POST", f"/post-summary-corrections/{psc_id}/grant", {}, headers
        )

    def deny_psc(self, psc_id, headers):
        return self._request(
            "POST", f"/post-summary-corrections/{psc_id}/deny", {}, headers
        )


api_client = ApiClient()
