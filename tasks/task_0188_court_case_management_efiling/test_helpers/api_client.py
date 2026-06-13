"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Court ----
    def create_court(self, payload, headers):
        return self._request("POST", "/courts", payload, headers)

    def get_court(self, court_id, headers):
        return self._request("GET", f"/courts/{court_id}", headers=headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def open_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/open", {}, headers)

    def lift_stay(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/lift-stay", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/close", {}, headers)

    # ---- Party ----
    def create_party(self, payload, headers):
        return self._request("POST", "/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/parties/{party_id}", headers=headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", "/parties", headers=headers, params=params)

    # ---- Filing ----
    def create_filing(self, payload, headers):
        return self._request("POST", "/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def claim_review_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/claim-review", {}, headers)

    def accept_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/accept", {}, headers)

    def reject_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/reject", payload, headers)

    def pay_fee(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/pay-fee", {}, headers)

    # ---- ServiceOfProcess ----
    def create_service_of_process(self, payload, headers):
        return self._request("POST", "/service-of-process", payload, headers)

    def get_service_of_process(self, sop_id, headers):
        return self._request("GET", f"/service-of-process/{sop_id}", headers=headers)

    def list_service_of_process(self, headers, params=None):
        return self._request("GET", "/service-of-process", headers=headers, params=params)

    def complete_service(self, sop_id, headers):
        return self._request("POST", f"/service-of-process/{sop_id}/complete", {}, headers)

    def fail_service(self, sop_id, headers):
        return self._request("POST", f"/service-of-process/{sop_id}/fail", {}, headers)

    # ---- Deadline ----
    def create_deadline(self, payload, headers):
        return self._request("POST", "/deadlines", payload, headers)

    def get_deadline(self, deadline_id, headers):
        return self._request("GET", f"/deadlines/{deadline_id}", headers=headers)

    def list_deadlines(self, headers, params=None):
        return self._request("GET", "/deadlines", headers=headers, params=params)

    def satisfy_deadline(self, deadline_id, payload, headers):
        return self._request("POST", f"/deadlines/{deadline_id}/satisfy", payload, headers)

    def mark_missed_deadline(self, deadline_id, headers):
        return self._request("POST", f"/deadlines/{deadline_id}/mark-missed", {}, headers)

    def vacate_deadline(self, deadline_id, headers):
        return self._request("POST", f"/deadlines/{deadline_id}/vacate", {}, headers)

    # ---- Motion ----
    def create_motion(self, payload, headers):
        return self._request("POST", "/motions", payload, headers)

    def get_motion(self, motion_id, headers):
        return self._request("GET", f"/motions/{motion_id}", headers=headers)

    def list_motions(self, headers, params=None):
        return self._request("GET", "/motions", headers=headers, params=params)

    def submit_motion(self, motion_id, headers):
        return self._request("POST", f"/motions/{motion_id}/submit", {}, headers)

    def rule_motion(self, motion_id, payload, headers):
        return self._request("POST", f"/motions/{motion_id}/rule", payload, headers)

    def withdraw_motion(self, motion_id, headers):
        return self._request("POST", f"/motions/{motion_id}/withdraw", {}, headers)

    # ---- Order ----
    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    # ---- FeeWaiver ----
    def create_fee_waiver(self, payload, headers):
        return self._request("POST", "/fee-waivers", payload, headers)

    def get_fee_waiver(self, waiver_id, headers):
        return self._request("GET", f"/fee-waivers/{waiver_id}", headers=headers)

    def list_fee_waivers(self, headers, params=None):
        return self._request("GET", "/fee-waivers", headers=headers, params=params)

    def request_info_fee_waiver(self, waiver_id, headers):
        return self._request("POST", f"/fee-waivers/{waiver_id}/request-info", {}, headers)

    def resubmit_fee_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/fee-waivers/{waiver_id}/resubmit", payload, headers)

    def approve_fee_waiver(self, waiver_id, headers):
        return self._request("POST", f"/fee-waivers/{waiver_id}/approve", {}, headers)

    def deny_fee_waiver(self, waiver_id, headers):
        return self._request("POST", f"/fee-waivers/{waiver_id}/deny", {}, headers)

    # ---- Hearing ----
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/hold", {}, headers)

    def continue_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/continue", payload, headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/cancel", {}, headers)

    # ---- Judgment ----
    def create_judgment(self, payload, headers):
        return self._request("POST", "/judgments", payload, headers)

    def get_judgment(self, judgment_id, headers):
        return self._request("GET", f"/judgments/{judgment_id}", headers=headers)

    def list_judgments(self, headers, params=None):
        return self._request("GET", "/judgments", headers=headers, params=params)

    def satisfy_judgment(self, judgment_id, headers):
        return self._request("POST", f"/judgments/{judgment_id}/satisfy", {}, headers)

    def vacate_judgment(self, judgment_id, headers):
        return self._request("POST", f"/judgments/{judgment_id}/vacate", {}, headers)

    # ---- Appeal ----
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def prepare_record(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/prepare-record", payload, headers)

    def transmit_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/transmit", {}, headers)

    def dismiss_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/dismiss", {}, headers)


api_client = ApiClient()
