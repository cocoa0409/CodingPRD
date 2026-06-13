"""API client for the Appraisal Management Company (AMC) API.

One method per endpoint defined in the PRD. Subclasses GenericApiClient so the
base _request() (URL construction, session, query-vs-body routing) is inherited.
Every path is mounted under the /amc prefix (PRD §2).
"""
import time

from requests.exceptions import ConnectionError as RequestsConnectionError

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Harden the base request against per-test-server reboots.

        Under ``--isolation per-test-server`` the server is restarted before every
        test, so a keep-alive socket left in the session pool from a prior boot can
        fire a stale-connection error on the first request of the next test. We
        force ``Connection: close`` and retry once on ConnectionError. Pure HTTP
        transport hardening; no request semantics change.
        """
        merged_headers = dict(headers or {})
        merged_headers.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, merged_headers, params)
        except RequestsConnectionError:
            time.sleep(0.25)
            return super()._request(method, path, payload, merged_headers, params)

    # ─── Lenders ──────────────────────────────────────────────────────
    def create_lender(self, payload, headers):
        return self._request("POST", "/amc/lenders", payload, headers)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"/amc/lenders/{lender_id}", headers=headers)

    def set_lender_panel(self, lender_id, payload, headers):
        return self._request("PATCH", f"/amc/lenders/{lender_id}/panel", payload, headers)

    # ─── Appraisers ───────────────────────────────────────────────────
    def create_appraiser(self, payload, headers):
        return self._request("POST", "/amc/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id, headers):
        return self._request("GET", f"/amc/appraisers/{appraiser_id}", headers=headers)

    def set_appraiser_status(self, appraiser_id, payload, headers):
        return self._request("POST", f"/amc/appraisers/{appraiser_id}/status", payload, headers)

    # ─── Properties ───────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/amc/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/amc/properties/{property_id}", headers=headers)

    # ─── Orders ───────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/amc/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/amc/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/amc/orders/{order_id}", headers=headers)

    def create_assignment(self, order_id, payload, headers):
        return self._request("POST", f"/amc/orders/{order_id}/assignments", payload, headers)

    def list_order_assignments(self, order_id, headers, params=None):
        return self._request("GET", f"/amc/orders/{order_id}/assignments", headers=headers, params=params)

    def get_order_fee_split(self, order_id, headers):
        return self._request("GET", f"/amc/orders/{order_id}/fee-split", headers=headers)

    def list_order_reconsiderations(self, order_id, headers, params=None):
        return self._request("GET", f"/amc/orders/{order_id}/reconsiderations", headers=headers, params=params)

    def list_order_firewall_events(self, order_id, headers, params=None):
        return self._request("GET", f"/amc/orders/{order_id}/firewall-events", headers=headers, params=params)

    def complete_order(self, order_id, payload, headers):
        return self._request("POST", f"/amc/orders/{order_id}/complete", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/amc/orders/{order_id}/cancel", payload, headers)

    # ─── Assignments ──────────────────────────────────────────────────
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/amc/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/amc/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/amc/assignments/{assignment_id}/accept", payload, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/amc/assignments/{assignment_id}/decline", headers=headers)

    def submit_report(self, assignment_id, payload, headers):
        return self._request("POST", f"/amc/assignments/{assignment_id}/reports", payload, headers)

    def list_assignment_reports(self, assignment_id, headers, params=None):
        return self._request("GET", f"/amc/assignments/{assignment_id}/reports", headers=headers, params=params)

    # ─── Reports ──────────────────────────────────────────────────────
    def get_report(self, report_id, headers):
        return self._request("GET", f"/amc/reports/{report_id}", headers=headers)

    def open_compliance_review(self, report_id, payload, headers):
        return self._request("POST", f"/amc/reports/{report_id}/compliance-reviews", payload, headers)

    def list_report_compliance_reviews(self, report_id, headers, params=None):
        return self._request("GET", f"/amc/reports/{report_id}/compliance-reviews", headers=headers, params=params)

    def open_revision_request(self, report_id, payload, headers):
        return self._request("POST", f"/amc/reports/{report_id}/revision-requests", payload, headers)

    def list_report_revision_requests(self, report_id, headers, params=None):
        return self._request("GET", f"/amc/reports/{report_id}/revision-requests", headers=headers, params=params)

    # ─── Compliance reviews ───────────────────────────────────────────
    def get_compliance_review(self, review_id, headers):
        return self._request("GET", f"/amc/compliance-reviews/{review_id}", headers=headers)

    def finalize_compliance_review(self, review_id, payload, headers):
        return self._request("POST", f"/amc/compliance-reviews/{review_id}/finalize", payload, headers)

    # ─── Reconsideration of Value ─────────────────────────────────────
    def create_reconsideration(self, order_id, payload, headers):
        return self._request("POST", f"/amc/orders/{order_id}/reconsiderations", payload, headers)

    def get_reconsideration(self, rov_id, headers):
        return self._request("GET", f"/amc/reconsiderations/{rov_id}", headers=headers)

    def start_review_reconsideration(self, rov_id, headers):
        return self._request("POST", f"/amc/reconsiderations/{rov_id}/start-review", headers=headers)

    def resolve_reconsideration(self, rov_id, payload, headers):
        return self._request("POST", f"/amc/reconsiderations/{rov_id}/resolve", payload, headers)

    # ─── Test-driving clock ───────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/amc/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
