"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/recovery/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Members (PRD §3.1, §3.6)
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/recovery/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/recovery/members/{member_id}", headers=headers)

    def mark_deceased(self, member_id, payload, headers):
        return self._request(
            "POST", f"/recovery/members/{member_id}/mark-deceased", payload, headers
        )

    # ------------------------------------------------------------------
    # TPL cases (PRD §3.2)
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/recovery/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/recovery/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/recovery/cases", headers=headers, params=params)

    def notify_attorney(self, case_id, headers):
        return self._request(
            "POST", f"/recovery/cases/{case_id}/notify-attorney", {}, headers
        )

    def add_expense_claim(self, case_id, payload, headers):
        return self._request(
            "POST", f"/recovery/cases/{case_id}/expense-claims", payload, headers
        )

    def list_expense_claims(self, case_id, headers):
        return self._request(
            "GET", f"/recovery/cases/{case_id}/expense-claims", headers=headers
        )

    def record_litigation(self, case_id, litigation_event, headers):
        return self._request(
            "POST", f"/recovery/cases/{case_id}/litigation",
            {"litigation_event": litigation_event}, headers,
        )

    def close_case(self, case_id, headers):
        return self._request("POST", f"/recovery/cases/{case_id}/close", {}, headers)

    def get_accounting_summary(self, case_id, headers):
        return self._request(
            "GET", f"/recovery/cases/{case_id}/accounting-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Liens (PRD §3.3)
    # ------------------------------------------------------------------
    def file_lien(self, case_id, headers):
        return self._request("POST", f"/recovery/cases/{case_id}/liens", {}, headers)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/recovery/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/recovery/liens", headers=headers, params=params)

    def amend_lien(self, lien_id, payload, headers):
        return self._request(
            "POST", f"/recovery/liens/{lien_id}/amend", payload, headers
        )

    def release_lien(self, lien_id, headers):
        return self._request("POST", f"/recovery/liens/{lien_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Settlements (PRD §3.4)
    # ------------------------------------------------------------------
    def create_settlement(self, case_id, payload, headers):
        return self._request(
            "POST", f"/recovery/cases/{case_id}/settlements", payload, headers
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/recovery/settlements/{settlement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", "/recovery/settlements", headers=headers, params=params
        )

    def counter_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/recovery/settlements/{settlement_id}/counter", payload, headers
        )

    def accept_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/recovery/settlements/{settlement_id}/accept", {}, headers
        )

    def reject_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/recovery/settlements/{settlement_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Recovery postings (PRD §3.5)
    # ------------------------------------------------------------------
    def create_posting(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/recovery/settlements/{settlement_id}/postings", payload, headers
        )

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"/recovery/postings/{posting_id}", headers=headers)

    def list_postings(self, headers, params=None):
        return self._request("GET", "/recovery/postings", headers=headers, params=params)

    def post_posting(self, posting_id, headers):
        return self._request(
            "POST", f"/recovery/postings/{posting_id}/post", {}, headers
        )

    def reverse_posting(self, posting_id, headers):
        return self._request(
            "POST", f"/recovery/postings/{posting_id}/reverse", {}, headers
        )

    # ------------------------------------------------------------------
    # Estate cases (PRD §3.6)
    # ------------------------------------------------------------------
    def get_estate_case(self, estate_case_id, headers):
        return self._request(
            "GET", f"/recovery/estate-cases/{estate_case_id}", headers=headers
        )

    def list_estate_cases(self, headers, params=None):
        return self._request(
            "GET", "/recovery/estate-cases", headers=headers, params=params
        )

    def file_estate_claim(self, estate_case_id, payload, headers):
        return self._request(
            "POST", f"/recovery/estate-cases/{estate_case_id}/file-claim",
            payload, headers,
        )

    def record_estate_payment(self, estate_case_id, payload, headers):
        return self._request(
            "POST", f"/recovery/estate-cases/{estate_case_id}/record-payment",
            payload, headers,
        )

    def create_waiver(self, estate_case_id, payload, headers):
        return self._request(
            "POST", f"/recovery/estate-cases/{estate_case_id}/waivers",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Hardship waivers (PRD §3.7)
    # ------------------------------------------------------------------
    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/recovery/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/recovery/waivers", headers=headers, params=params)

    def approve_waiver(self, waiver_id, headers):
        return self._request(
            "POST", f"/recovery/waivers/{waiver_id}/approve", {}, headers
        )

    def deny_waiver(self, waiver_id, headers):
        return self._request("POST", f"/recovery/waivers/{waiver_id}/deny", {}, headers)

    def appeal_waiver(self, waiver_id, headers):
        return self._request(
            "POST", f"/recovery/waivers/{waiver_id}/appeal", {}, headers
        )

    def rescind_waiver(self, waiver_id, headers):
        return self._request(
            "POST", f"/recovery/waivers/{waiver_id}/rescind", {}, headers
        )

    # ------------------------------------------------------------------
    # Communication notices (PRD §3.8)
    # ------------------------------------------------------------------
    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/recovery/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/recovery/notices", headers=headers, params=params)

    def send_notice(self, notice_id, delivery_outcome, headers):
        return self._request(
            "POST", f"/recovery/notices/{notice_id}/send",
            {"delivery_outcome": delivery_outcome}, headers,
        )


api_client = ApiClient()
