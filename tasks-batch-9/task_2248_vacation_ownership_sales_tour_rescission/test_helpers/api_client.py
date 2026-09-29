"""API client: one method per endpoint defined in the PRD (§4).

Every collection is mounted at the top level — there is no shared URL prefix.
"""

import time

import requests

from prd_bench_local_runner.testing import GenericApiClient

# The harness reboots the server before every test (``--isolation
# per-test-server``) by SIGKILLing whatever listens on the port. Process
# teardown is asynchronous, so on a loaded host — the 8-round stability sweep
# runs eight suites in lockstep — a connection can be accepted into the dying
# listener's backlog and then reset when the kernel tears that socket down.
# That surfaces as a transport-level ConnectionError on the first call of a
# test, unrelated to any API behaviour. Retry those, and only those: a server
# that genuinely died stays unreachable and the failure still surfaces.
_TRANSPORT_RETRIES = 3
_TRANSPORT_BACKOFF_SECONDS = 0.4


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        last_error = None
        for attempt in range(_TRANSPORT_RETRIES):
            try:
                return super()._request(method, path, payload, headers, params)
            except requests.ConnectionError as exc:
                last_error = exc
                if attempt + 1 < _TRANSPORT_RETRIES:
                    time.sleep(_TRANSPORT_BACKOFF_SECONDS * (attempt + 1))
        raise last_error

    # ---------------- Platform operations ----------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_rescission_sweep(self, headers):
        return self._request("POST", "/_ops/rescission-sweep", None, headers)

    # ---------------- Tour channels ----------------

    def create_tour_channel(self, payload, headers):
        return self._request("POST", "/tour-channels", payload, headers)

    def reinstate_tour_channel(self, channel_id, headers):
        return self._request(
            "POST", f"/tour-channels/{channel_id}/reinstate", None, headers
        )

    def get_tour_channel(self, channel_id, headers):
        return self._request("GET", f"/tour-channels/{channel_id}", headers=headers)

    def get_channel_no_show_summary(self, channel_id, headers):
        return self._request(
            "GET", f"/tour-channels/{channel_id}/no-show-summary", headers=headers
        )

    # ---------------- Sales galleries ----------------

    def create_sales_gallery(self, payload, headers):
        return self._request("POST", "/sales-galleries", payload, headers)

    def set_gallery_status(self, gallery_id, payload, headers):
        return self._request(
            "POST", f"/sales-galleries/{gallery_id}/set-status", payload, headers
        )

    def get_sales_gallery(self, gallery_id, headers):
        return self._request("GET", f"/sales-galleries/{gallery_id}", headers=headers)

    # ---------------- Sales representatives ----------------

    def create_sales_representative(self, payload, headers):
        return self._request("POST", "/sales-representatives", payload, headers)

    def get_sales_representative(self, rep_id, headers):
        return self._request(
            "GET", f"/sales-representatives/{rep_id}", headers=headers
        )

    def list_sales_representatives(self, headers, params=None):
        return self._request(
            "GET", "/sales-representatives", headers=headers, params=params
        )

    def get_rescission_analysis(self, rep_id, headers):
        return self._request(
            "GET",
            f"/sales-representatives/{rep_id}/rescission-analysis",
            headers=headers,
        )

    # ---------------- Prospects ----------------

    def create_prospect(self, payload, headers):
        return self._request("POST", "/prospects", payload, headers)

    def get_prospect(self, prospect_id, headers):
        return self._request("GET", f"/prospects/{prospect_id}", headers=headers)

    # ---------------- Tour bookings ----------------

    def create_tour_booking(self, payload, headers):
        return self._request("POST", "/tour-bookings", payload, headers)

    def open_reschedule_request(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/tour-bookings/{booking_id}/reschedule-requests", payload, headers
        )

    def commit_reschedule(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/tour-bookings/{booking_id}/reschedule", payload, headers
        )

    def check_in_tour_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/tour-bookings/{booking_id}/check-in", payload, headers
        )

    def mark_tour_booking_no_show(self, booking_id, headers):
        return self._request(
            "POST", f"/tour-bookings/{booking_id}/no-show", None, headers
        )

    def cancel_tour_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/tour-bookings/{booking_id}/cancel", payload, headers
        )

    def get_tour_booking(self, booking_id, headers):
        return self._request("GET", f"/tour-bookings/{booking_id}", headers=headers)

    def list_tour_bookings(self, headers, params=None):
        return self._request("GET", "/tour-bookings", headers=headers, params=params)

    # ---------------- Sales presentations ----------------

    def create_sales_presentation(self, payload, headers):
        return self._request("POST", "/sales-presentations", payload, headers)

    def create_disclosure_acknowledgment(self, payload, headers):
        return self._request("POST", "/disclosure-acknowledgments", payload, headers)

    def create_prohibited_claim_finding(self, payload, headers):
        return self._request("POST", "/prohibited-claim-findings", payload, headers)

    def review_sales_presentation(self, presentation_id, payload, headers):
        return self._request(
            "POST", f"/sales-presentations/{presentation_id}/review", payload, headers
        )

    def complete_sales_presentation(self, presentation_id, headers):
        return self._request(
            "POST", f"/sales-presentations/{presentation_id}/complete", None, headers
        )

    def get_sales_presentation(self, presentation_id, headers):
        return self._request(
            "GET", f"/sales-presentations/{presentation_id}", headers=headers
        )

    def list_sales_presentations(self, headers, params=None):
        return self._request(
            "GET", "/sales-presentations", headers=headers, params=params
        )

    def list_presentation_disclosure_acknowledgments(
        self, presentation_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/sales-presentations/{presentation_id}/disclosure-acknowledgments",
            headers=headers,
            params=params,
        )

    def list_presentation_prohibited_claim_findings(
        self, presentation_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/sales-presentations/{presentation_id}/prohibited-claim-findings",
            headers=headers,
            params=params,
        )

    # ---------------- Purchase agreements ----------------

    def create_purchase_agreement(self, payload, headers):
        return self._request("POST", "/purchase-agreements", payload, headers)

    def fund_purchase_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/purchase-agreements/{agreement_id}/fund", payload, headers
        )

    def get_purchase_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/purchase-agreements/{agreement_id}", headers=headers
        )

    def list_purchase_agreements(self, headers, params=None):
        return self._request(
            "GET", "/purchase-agreements", headers=headers, params=params
        )

    def get_rescission_window(self, agreement_id, headers):
        return self._request(
            "GET",
            f"/purchase-agreements/{agreement_id}/rescission-window",
            headers=headers,
        )

    # ---------------- Financing applications ----------------

    def create_financing_application(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def decide_financing_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/financing-applications/{application_id}/decision",
            payload,
            headers,
        )

    def get_financing_application(self, application_id, headers):
        return self._request(
            "GET", f"/financing-applications/{application_id}", headers=headers
        )

    def list_financing_applications(self, headers, params=None):
        return self._request(
            "GET", "/financing-applications", headers=headers, params=params
        )

    # ---------------- Rescission requests ----------------

    def create_rescission_request(self, payload, headers):
        return self._request("POST", "/rescission-requests", payload, headers)

    def adjudicate_rescission_request(self, request_id, headers):
        return self._request(
            "POST", f"/rescission-requests/{request_id}/adjudicate", None, headers
        )

    def get_rescission_request(self, request_id, headers):
        return self._request(
            "GET", f"/rescission-requests/{request_id}", headers=headers
        )

    def list_rescission_requests(self, headers, params=None):
        return self._request(
            "GET", "/rescission-requests", headers=headers, params=params
        )

    # ---------------- Refund disbursements ----------------

    def create_refund_disbursement(self, payload, headers):
        return self._request("POST", "/refund-disbursements", payload, headers)

    def settle_refund_disbursement(self, disbursement_id, payload, headers):
        return self._request(
            "POST",
            f"/refund-disbursements/{disbursement_id}/settle",
            payload,
            headers,
        )

    def get_refund_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/refund-disbursements/{disbursement_id}", headers=headers
        )

    def list_refund_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/refund-disbursements", headers=headers, params=params
        )

    # ---------------- Closing packages ----------------

    def record_closing_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/closing-packages/{package_id}/record", payload, headers
        )

    def deliver_closing_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/closing-packages/{package_id}/deliver", payload, headers
        )

    def get_closing_package(self, package_id, headers):
        return self._request("GET", f"/closing-packages/{package_id}", headers=headers)

    def list_closing_packages(self, headers, params=None):
        return self._request(
            "GET", "/closing-packages", headers=headers, params=params
        )

    # ---------------- Compliance retraining ----------------

    def create_retraining_assignment(self, payload, headers):
        return self._request("POST", "/retraining-assignments", payload, headers)

    def start_retraining_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/retraining-assignments/{assignment_id}/start", None, headers
        )

    def close_retraining_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/retraining-assignments/{assignment_id}/close",
            payload,
            headers,
        )

    def reassign_retraining_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/retraining-assignments/{assignment_id}/reassign", None, headers
        )

    def get_retraining_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/retraining-assignments/{assignment_id}", headers=headers
        )

    def list_retraining_assignments(self, headers, params=None):
        return self._request(
            "GET", "/retraining-assignments", headers=headers, params=params
        )


api_client = ApiClient()
