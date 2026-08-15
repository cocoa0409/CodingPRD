"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

_EMPTY = {}


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner restarts the server (SIGKILL + respawn on the same port)
        # before every test. A pooled keep-alive connection from the previous
        # server incarnation intermittently races the RST and fails mid-test
        # with ConnectionResetError/RemoteDisconnected. Sending
        # Connection: close makes every request use a fresh connection, so no
        # stale pool entry can survive a server restart.
        self.session.headers["Connection"] = "close"

    # ---- Syndications ----
    def create_syndication(self, payload, headers):
        return self._request("POST", "/syndications", payload, headers)

    def list_syndications(self, headers, params=None):
        return self._request("GET", "/syndications", headers=headers, params=params)

    def get_syndication(self, syndication_id, headers):
        return self._request("GET", f"/syndications/{syndication_id}", headers=headers)

    def activate_syndication(self, syndication_id, headers, payload=None):
        return self._request("POST", f"/syndications/{syndication_id}/activate",
                             payload if payload is not None else _EMPTY, headers)

    def suspend_syndication(self, syndication_id, headers, payload=None):
        return self._request("POST", f"/syndications/{syndication_id}/suspend",
                             payload if payload is not None else _EMPTY, headers)

    def close_syndication(self, syndication_id, headers, payload=None):
        return self._request("POST", f"/syndications/{syndication_id}/close",
                             payload if payload is not None else _EMPTY, headers)

    # ---- Investors ----
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers)

    def list_investors(self, headers, params=None):
        return self._request("GET", "/investors", headers=headers, params=params)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def suspend_portal(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/suspend-portal",
                             _EMPTY, headers)

    def revoke_portal(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/revoke-portal",
                             _EMPTY, headers)

    # ---- Investor portal sessions ----
    def create_portal_session(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/portal-sessions",
                             _EMPTY, headers)

    def list_investor_portal_sessions(self, investor_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/portal-sessions",
                             headers=headers, params=params)

    # ---- Properties ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ---- Offerings (nested) ----
    def create_offering(self, syndication_id, payload, headers):
        return self._request("POST", f"/syndications/{syndication_id}/offerings",
                             payload, headers)

    def list_offerings(self, syndication_id, headers, params=None):
        return self._request("GET", f"/syndications/{syndication_id}/offerings",
                             headers=headers, params=params)

    def get_offering(self, syndication_id, offering_id, headers):
        return self._request(
            "GET", f"/syndications/{syndication_id}/offerings/{offering_id}",
            headers=headers)

    def open_offering(self, syndication_id, offering_id, headers, payload=None):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/open",
            payload if payload is not None else _EMPTY, headers)

    def close_offering_to_new(self, syndication_id, offering_id, headers, payload=None):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/close-to-new",
            payload if payload is not None else _EMPTY, headers)

    def reopen_offering(self, syndication_id, offering_id, headers, payload=None):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/reopen",
            payload if payload is not None else _EMPTY, headers)

    def final_close_offering(self, syndication_id, offering_id, headers, payload=None):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/final-close",
            payload if payload is not None else _EMPTY, headers)

    def dissolve_offering(self, syndication_id, offering_id, headers, payload=None):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/dissolve",
            payload if payload is not None else _EMPTY, headers)

    # ---- Subscriptions ----
    def create_subscription(self, syndication_id, offering_id, payload, headers):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions",
            payload, headers)

    def list_subscriptions(self, syndication_id, offering_id, headers, params=None):
        return self._request(
            "GET", f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions",
            headers=headers, params=params)

    def get_subscription(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}",
            headers=headers)

    def submit_subscription(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/submit",
            _EMPTY, headers)

    def verify_accreditation(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/verify-accreditation",
            _EMPTY, headers)

    def approve_suitability(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/approve-suitability",
            _EMPTY, headers)

    def reject_suitability(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/reject-suitability",
            _EMPTY, headers)

    def resubmit_subscription(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/resubmit",
            _EMPTY, headers)

    def withdraw_subscription(self, syndication_id, offering_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/withdraw",
            _EMPTY, headers)

    # ---- Subscription documents ----
    def upload_document(self, syndication_id, offering_id, subscription_id, payload, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/documents",
            payload, headers)

    def list_documents(self, syndication_id, offering_id, subscription_id, headers,
                       params=None):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/documents",
            headers=headers, params=params)

    def get_document(self, syndication_id, offering_id, subscription_id, document_id,
                     headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/documents/{document_id}",
            headers=headers)

    def accept_document(self, syndication_id, offering_id, subscription_id, document_id,
                        headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/documents/{document_id}/accept",
            _EMPTY, headers)

    def reject_document(self, syndication_id, offering_id, subscription_id, document_id,
                        headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/documents/{document_id}/reject",
            _EMPTY, headers)

    # ---- Capital calls ----
    def create_capital_call(self, syndication_id, offering_id, payload, headers):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls",
            payload, headers)

    def list_capital_calls(self, syndication_id, offering_id, headers, params=None):
        return self._request(
            "GET", f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls",
            headers=headers, params=params)

    def get_capital_call(self, syndication_id, offering_id, capital_call_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}",
            headers=headers)

    def issue_capital_call(self, syndication_id, offering_id, capital_call_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}/issue",
            _EMPTY, headers)

    def cancel_capital_call(self, syndication_id, offering_id, capital_call_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}/cancel",
            _EMPTY, headers)

    # ---- Capital call contributions ----
    def list_contributions(self, syndication_id, offering_id, capital_call_id, headers,
                           params=None):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}/contributions",
            headers=headers, params=params)

    def get_contribution(self, syndication_id, offering_id, capital_call_id,
                         contribution_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}/contributions/{contribution_id}",
            headers=headers)

    def receive_escrow(self, syndication_id, offering_id, capital_call_id,
                       contribution_id, payload, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}/contributions/{contribution_id}/receive-escrow",
            payload, headers)

    def release_escrow(self, syndication_id, offering_id, capital_call_id,
                       contribution_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/capital-calls/{capital_call_id}/contributions/{contribution_id}/release-escrow",
            _EMPTY, headers)

    # ---- Quarterly reports ----
    def create_quarterly_report(self, syndication_id, offering_id, payload, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/quarterly-reports",
            payload, headers)

    def list_quarterly_reports(self, syndication_id, offering_id, headers, params=None):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/quarterly-reports",
            headers=headers, params=params)

    def get_quarterly_report(self, syndication_id, offering_id, quarterly_report_id,
                             headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/quarterly-reports/{quarterly_report_id}",
            headers=headers)

    def publish_quarterly_report(self, syndication_id, offering_id, quarterly_report_id,
                                 headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/quarterly-reports/{quarterly_report_id}/publish",
            _EMPTY, headers)

    def amend_quarterly_report(self, syndication_id, offering_id, quarterly_report_id,
                               headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/quarterly-reports/{quarterly_report_id}/amend",
            _EMPTY, headers)

    # ---- Distributions ----
    def create_distribution(self, syndication_id, offering_id, payload, headers):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/distributions",
            payload, headers)

    def list_distributions(self, syndication_id, offering_id, headers, params=None):
        return self._request(
            "GET", f"/syndications/{syndication_id}/offerings/{offering_id}/distributions",
            headers=headers, params=params)

    def get_distribution(self, syndication_id, offering_id, distribution_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}",
            headers=headers)

    def calculate_distribution(self, syndication_id, offering_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}/calculate",
            _EMPTY, headers)

    def approve_distribution(self, syndication_id, offering_id, distribution_id, payload,
                             headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}/approve",
            payload, headers)

    def pay_distribution(self, syndication_id, offering_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}/pay",
            _EMPTY, headers)

    def cancel_distribution(self, syndication_id, offering_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}/cancel",
            _EMPTY, headers)

    # ---- Distribution lines ----
    def list_distribution_lines(self, syndication_id, offering_id, distribution_id,
                                headers, params=None):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}/lines",
            headers=headers, params=params)

    def get_distribution_line(self, syndication_id, offering_id, distribution_id, line_id,
                              headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/distributions/{distribution_id}/lines/{line_id}",
            headers=headers)

    # ---- Capital events ----
    def create_capital_event(self, syndication_id, property_id, payload, headers):
        return self._request(
            "POST", f"/syndications/{syndication_id}/properties/{property_id}/capital-events",
            payload, headers)

    def list_capital_events(self, syndication_id, property_id, headers, params=None):
        return self._request(
            "GET", f"/syndications/{syndication_id}/properties/{property_id}/capital-events",
            headers=headers, params=params)

    def get_capital_event(self, syndication_id, property_id, capital_event_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/properties/{property_id}/capital-events/{capital_event_id}",
            headers=headers)

    def execute_capital_event(self, syndication_id, property_id, capital_event_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/properties/{property_id}/capital-events/{capital_event_id}/execute",
            _EMPTY, headers)

    def cancel_capital_event(self, syndication_id, property_id, capital_event_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/properties/{property_id}/capital-events/{capital_event_id}/cancel",
            _EMPTY, headers)

    # ---- K-1 packages ----
    def create_k1_package(self, syndication_id, offering_id, payload, headers):
        return self._request(
            "POST", f"/syndications/{syndication_id}/offerings/{offering_id}/k1-packages",
            payload, headers)

    def list_k1_packages(self, syndication_id, offering_id, headers, params=None):
        return self._request(
            "GET", f"/syndications/{syndication_id}/offerings/{offering_id}/k1-packages",
            headers=headers, params=params)

    def get_k1_package(self, syndication_id, offering_id, k1_package_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/k1-packages/{k1_package_id}",
            headers=headers)

    def submit_k1_for_review(self, syndication_id, offering_id, k1_package_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/k1-packages/{k1_package_id}/submit-for-review",
            _EMPTY, headers)

    def finalize_k1_package(self, syndication_id, offering_id, k1_package_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/k1-packages/{k1_package_id}/finalize",
            _EMPTY, headers)

    def deliver_k1_package(self, syndication_id, offering_id, k1_package_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/k1-packages/{k1_package_id}/deliver",
            _EMPTY, headers)

    # ---- Transfer requests ----
    def create_transfer_request(self, syndication_id, offering_id, subscription_id,
                                payload, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests",
            payload, headers)

    def list_transfer_requests(self, syndication_id, offering_id, subscription_id, headers,
                               params=None):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests",
            headers=headers, params=params)

    def get_transfer_request(self, syndication_id, offering_id, subscription_id,
                             transfer_request_id, headers):
        return self._request(
            "GET",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}",
            headers=headers)

    def sponsor_approve_transfer(self, syndication_id, offering_id, subscription_id,
                                 transfer_request_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}/sponsor-approve",
            _EMPTY, headers)

    def sponsor_reject_transfer(self, syndication_id, offering_id, subscription_id,
                                transfer_request_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}/sponsor-reject",
            _EMPTY, headers)

    def agent_approve_transfer(self, syndication_id, offering_id, subscription_id,
                               transfer_request_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}/agent-approve",
            _EMPTY, headers)

    def agent_reject_transfer(self, syndication_id, offering_id, subscription_id,
                              transfer_request_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}/agent-reject",
            _EMPTY, headers)

    def settle_transfer(self, syndication_id, offering_id, subscription_id,
                        transfer_request_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}/settle",
            _EMPTY, headers)

    def cancel_transfer_request(self, syndication_id, offering_id, subscription_id,
                                transfer_request_id, headers):
        return self._request(
            "POST",
            f"/syndications/{syndication_id}/offerings/{offering_id}/subscriptions/{subscription_id}/transfer-requests/{transfer_request_id}/cancel",
            _EMPTY, headers)

    # ---- Flat filtered-list reads (PRD §2.5) ----
    def list_offerings_flat(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    def get_offering_flat(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def list_subscriptions_flat(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription_flat(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_documents_flat(self, headers, params=None):
        return self._request("GET", "/documents", headers=headers, params=params)

    def get_document_flat(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def list_capital_calls_flat(self, headers, params=None):
        return self._request("GET", "/capital-calls", headers=headers, params=params)

    def get_capital_call_flat(self, capital_call_id, headers):
        return self._request("GET", f"/capital-calls/{capital_call_id}", headers=headers)

    def list_contributions_flat(self, headers, params=None):
        return self._request("GET", "/contributions", headers=headers, params=params)

    def get_contribution_flat(self, contribution_id, headers):
        return self._request("GET", f"/contributions/{contribution_id}", headers=headers)

    def list_quarterly_reports_flat(self, headers, params=None):
        return self._request("GET", "/quarterly-reports", headers=headers, params=params)

    def get_quarterly_report_flat(self, quarterly_report_id, headers):
        return self._request("GET", f"/quarterly-reports/{quarterly_report_id}",
                             headers=headers)

    def list_distributions_flat(self, headers, params=None):
        return self._request("GET", "/distributions", headers=headers, params=params)

    def get_distribution_flat(self, distribution_id, headers):
        return self._request("GET", f"/distributions/{distribution_id}", headers=headers)

    def list_distribution_lines_flat(self, headers, params=None):
        return self._request("GET", "/distribution-lines", headers=headers, params=params)

    def get_distribution_line_flat(self, line_id, headers):
        return self._request("GET", f"/distribution-lines/{line_id}", headers=headers)

    def list_capital_events_flat(self, headers, params=None):
        return self._request("GET", "/capital-events", headers=headers, params=params)

    def get_capital_event_flat(self, capital_event_id, headers):
        return self._request("GET", f"/capital-events/{capital_event_id}", headers=headers)

    def list_k1_packages_flat(self, headers, params=None):
        return self._request("GET", "/k1-packages", headers=headers, params=params)

    def get_k1_package_flat(self, k1_package_id, headers):
        return self._request("GET", f"/k1-packages/{k1_package_id}", headers=headers)

    def list_transfer_requests_flat(self, headers, params=None):
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def get_transfer_request_flat(self, transfer_request_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_request_id}",
                             headers=headers)

    def list_portal_sessions_flat(self, headers, params=None):
        return self._request("GET", "/portal-sessions", headers=headers, params=params)

    def get_portal_session_flat(self, session_id, headers):
        return self._request("GET", f"/portal-sessions/{session_id}", headers=headers)

    # ---- Logical clock (PRD §2.8) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
