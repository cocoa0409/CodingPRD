"""One method per endpoint published by the API."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every documented route."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[dict] = None):
        """The one route that does not require an acting principal."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers or {"Content-Type": "application/json"},
        )

    def set_clock_raw(self, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload,
            headers or {"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    # Staff users
    # ------------------------------------------------------------------
    def create_staff_user(self, payload, headers):
        return self._request("POST", "/staff-users", payload, headers)

    def list_staff_users(self, headers, params=None):
        return self._request("GET", "/staff-users", headers=headers, params=params)

    def get_staff_user(self, staff_user_id, headers):
        return self._request("GET", f"/staff-users/{staff_user_id}", headers=headers)

    # ------------------------------------------------------------------
    # Consumers
    # ------------------------------------------------------------------
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    def list_consumers(self, headers, params=None):
        return self._request("GET", "/consumers", headers=headers, params=params)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    def update_consumer(self, consumer_id, payload, headers):
        return self._request("PATCH", f"/consumers/{consumer_id}", payload, headers)

    def get_consumer_sentiment(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/consumers/{consumer_id}/sentiment", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Plants, lines, products
    # ------------------------------------------------------------------
    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/plants", headers=headers, params=params)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def create_production_line(self, payload, headers):
        return self._request("POST", "/production-lines", payload, headers)

    def list_plant_production_lines(self, plant_id, headers, params=None):
        return self._request(
            "GET", f"/plants/{plant_id}/production-lines", headers=headers, params=params
        )

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/production-lines/{line_id}", headers=headers)

    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ------------------------------------------------------------------
    # Production lots
    # ------------------------------------------------------------------
    def create_production_lot(self, payload, headers):
        return self._request("POST", "/production-lots", payload, headers)

    def list_production_lots(self, headers, params=None):
        return self._request("GET", "/production-lots", headers=headers, params=params)

    def get_production_lot(self, lot_id, headers):
        return self._request("GET", f"/production-lots/{lot_id}", headers=headers)

    def get_lot_complaint_rate(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/production-lots/{lot_id}/complaint-rate", headers=headers, params=params
        )

    def hold_production_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/production-lots/{lot_id}/hold", payload, headers)

    def release_production_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/production-lots/{lot_id}/release", payload, headers)

    def withdraw_production_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/production-lots/{lot_id}/withdraw", payload, headers)

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------
    def create_contact(self, payload, headers):
        return self._request("POST", "/contacts", payload, headers)

    def list_contacts(self, headers, params=None):
        return self._request("GET", "/contacts", headers=headers, params=params)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/contacts/{contact_id}", headers=headers)

    def close_contact_no_complaint(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/contacts/{contact_id}/close-no-complaint", payload, headers
        )

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def identify_complaint_product(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/identify-product", payload, headers
        )

    def triage_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/triage", payload, headers)

    def respond_to_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/respond", payload, headers)

    def mark_complaint_duplicate(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/mark-duplicate", payload, headers
        )

    def unmark_complaint_duplicate(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/unmark-duplicate", payload, headers
        )

    def quality_hold_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/quality-hold", payload, headers
        )

    def release_complaint_hold(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/release-hold", payload, headers
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers)

    def close_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/close", payload, headers)

    def list_complaint_signal_memberships(self, complaint_id, headers, params=None):
        return self._request(
            "GET",
            f"/complaints/{complaint_id}/signal-memberships",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Sample kits and custody
    # ------------------------------------------------------------------
    def create_sample_kit(self, payload, headers):
        return self._request("POST", "/sample-kits", payload, headers)

    def list_sample_kits(self, headers, params=None):
        return self._request("GET", "/sample-kits", headers=headers, params=params)

    def get_sample_kit(self, kit_id, headers):
        return self._request("GET", f"/sample-kits/{kit_id}", headers=headers)

    def ship_sample_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/sample-kits/{kit_id}/ship", payload, headers)

    def receive_sample_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/sample-kits/{kit_id}/receive", payload, headers)

    def lab_accept_sample_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/sample-kits/{kit_id}/lab-accept", payload, headers)

    def cancel_sample_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/sample-kits/{kit_id}/cancel", payload, headers)

    def append_custody_event(self, kit_id, payload, headers):
        return self._request(
            "POST", f"/sample-kits/{kit_id}/custody-events", payload, headers
        )

    def list_custody_events(self, kit_id, headers, params=None):
        return self._request(
            "GET", f"/sample-kits/{kit_id}/custody-events", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Remedies
    # ------------------------------------------------------------------
    def create_remedy(self, payload, headers):
        return self._request("POST", "/remedies", payload, headers)

    def list_remedies(self, headers, params=None):
        return self._request("GET", "/remedies", headers=headers, params=params)

    def get_remedy(self, remedy_id, headers):
        return self._request("GET", f"/remedies/{remedy_id}", headers=headers)

    def submit_remedy(self, remedy_id, payload, headers):
        return self._request("POST", f"/remedies/{remedy_id}/submit", payload, headers)

    def decide_remedy(self, remedy_id, payload, headers):
        return self._request("POST", f"/remedies/{remedy_id}/decide", payload, headers)

    def fulfill_remedy(self, remedy_id, payload, headers):
        return self._request("POST", f"/remedies/{remedy_id}/fulfill", payload, headers)

    def void_remedy(self, remedy_id, payload, headers):
        return self._request("POST", f"/remedies/{remedy_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Regulatory reports
    # ------------------------------------------------------------------
    def create_regulatory_report(self, payload, headers):
        return self._request("POST", "/regulatory-reports", payload, headers)

    def list_regulatory_reports(self, headers, params=None):
        return self._request("GET", "/regulatory-reports", headers=headers, params=params)

    def get_regulatory_report(self, report_id, headers):
        return self._request("GET", f"/regulatory-reports/{report_id}", headers=headers)

    def determine_regulatory_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-reports/{report_id}/determine", payload, headers
        )

    def submit_regulatory_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-reports/{report_id}/submit", payload, headers
        )

    def withdraw_regulatory_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/regulatory-reports/{report_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Trend signals
    # ------------------------------------------------------------------
    def create_trend_signal(self, payload, headers):
        return self._request("POST", "/trend-signals", payload, headers)

    def list_trend_signals(self, headers, params=None):
        return self._request("GET", "/trend-signals", headers=headers, params=params)

    def get_trend_signal(self, signal_id, headers):
        return self._request("GET", f"/trend-signals/{signal_id}", headers=headers)

    def list_signal_memberships(self, signal_id, headers, params=None):
        return self._request(
            "GET", f"/trend-signals/{signal_id}/memberships", headers=headers, params=params
        )

    def open_signal_investigation(self, signal_id, payload, headers):
        return self._request(
            "POST", f"/trend-signals/{signal_id}/open-investigation", payload, headers
        )

    def dismiss_trend_signal(self, signal_id, payload, headers):
        return self._request("POST", f"/trend-signals/{signal_id}/dismiss", payload, headers)

    def escalate_recall_evaluation(self, signal_id, payload, headers):
        return self._request(
            "POST", f"/trend-signals/{signal_id}/escalate-recall-evaluation", payload, headers
        )

    def initiate_recall(self, signal_id, payload, headers):
        return self._request(
            "POST", f"/trend-signals/{signal_id}/initiate-recall", payload, headers
        )

    def close_signal_no_action(self, signal_id, payload, headers):
        return self._request(
            "POST", f"/trend-signals/{signal_id}/close-no-action", payload, headers
        )

    # ------------------------------------------------------------------
    # Response templates
    # ------------------------------------------------------------------
    def create_response_template(self, payload, headers):
        return self._request("POST", "/response-templates", payload, headers)

    def list_response_templates(self, headers, params=None):
        return self._request("GET", "/response-templates", headers=headers, params=params)

    def get_response_template(self, template_id, headers):
        return self._request("GET", f"/response-templates/{template_id}", headers=headers)

    def activate_response_template(self, template_id, payload, headers):
        return self._request(
            "POST", f"/response-templates/{template_id}/activate", payload, headers
        )

    def retire_response_template(self, template_id, payload, headers):
        return self._request(
            "POST", f"/response-templates/{template_id}/retire", payload, headers
        )

    # ------------------------------------------------------------------
    # Operations checkpoint
    # ------------------------------------------------------------------
    def create_quality_ops_run(self, payload, headers):
        return self._request("POST", "/quality-ops-runs", payload, headers)


api_client = ApiClient()
