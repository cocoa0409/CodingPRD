"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- GalaEvent ---
    def create_gala_event(self, payload, headers):
        return self._request("POST", "/gala-events", payload, headers)

    def get_gala_event(self, event_id, headers):
        return self._request("GET", f"/gala-events/{event_id}", headers=headers)

    def update_gala_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/gala-events/{event_id}", payload, headers)

    def advance_gala_event(self, event_id, headers):
        return self._request("POST", f"/gala-events/{event_id}/advance",
                             {}, headers)

    def reconcile_gala_event(self, event_id, headers):
        return self._request("POST", f"/gala-events/{event_id}/reconcile",
                             {}, headers)

    def get_event_summary(self, event_id, headers):
        return self._request("GET", f"/gala-events/{event_id}/summary",
                             headers=headers)

    # --- Donor ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    # --- Bidder ---
    def create_bidder(self, payload, headers):
        return self._request("POST", "/bidders", payload, headers)

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def set_bidder_status(self, bidder_id, payload, headers):
        return self._request("POST", f"/bidders/{bidder_id}/status",
                             payload, headers)

    def list_event_bidders(self, event_id, headers, params=None):
        return self._request("GET", f"/gala-events/{event_id}/bidders",
                             headers=headers, params=params)

    # --- Solicitation ---
    def create_solicitation(self, payload, headers):
        return self._request("POST", "/solicitations", payload, headers)

    def get_solicitation(self, solicitation_id, headers):
        return self._request("GET", f"/solicitations/{solicitation_id}",
                             headers=headers)

    def list_donor_solicitations(self, donor_id, headers, params=None):
        return self._request("GET", f"/donors/{donor_id}/solicitations",
                             headers=headers, params=params)

    def list_event_solicitations(self, event_id, headers, params=None):
        return self._request("GET", f"/gala-events/{event_id}/solicitations",
                             headers=headers, params=params)

    def send_solicitation(self, solicitation_id, headers):
        return self._request("POST", f"/solicitations/{solicitation_id}/send",
                             {}, headers)

    def revise_solicitation(self, solicitation_id, payload, headers):
        return self._request("POST",
                             f"/solicitations/{solicitation_id}/revise",
                             payload, headers)

    def record_solicitation_response(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/record-response",
            payload, headers)

    # --- Item / Valuation / BlackoutWindow ---
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", headers=headers, params=params)

    def submit_valuation(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/valuations",
                             payload, headers)

    def list_item_valuations(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/valuations",
                             headers=headers, params=params)

    def approve_valuation(self, valuation_id, headers):
        return self._request("POST", f"/valuations/{valuation_id}/approve",
                             {}, headers)

    def reject_valuation(self, valuation_id, headers):
        return self._request("POST", f"/valuations/{valuation_id}/reject",
                             {}, headers)

    def create_blackout_window(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/blackout-windows",
                             payload, headers)

    def list_blackout_windows(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/blackout-windows",
                             headers=headers, params=params)

    # --- Bundle / Bid ---
    def create_bundle(self, payload, headers):
        return self._request("POST", "/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/bundles/{bundle_id}", headers=headers)

    def list_event_bundles(self, event_id, headers, params=None):
        return self._request("GET", f"/gala-events/{event_id}/bundles",
                             headers=headers, params=params)

    def attach_item(self, bundle_id, payload, headers):
        return self._request("POST", f"/bundles/{bundle_id}/items",
                             payload, headers)

    def detach_item(self, bundle_id, item_id, headers):
        return self._request("DELETE",
                             f"/bundles/{bundle_id}/items/{item_id}",
                             headers=headers)

    def publish_bundle(self, bundle_id, headers):
        return self._request("POST", f"/bundles/{bundle_id}/publish",
                             {}, headers)

    def override_min_bid(self, bundle_id, payload, headers):
        return self._request("PATCH", f"/bundles/{bundle_id}/min-bid",
                             payload, headers)

    def place_bid(self, bundle_id, payload, headers):
        return self._request("POST", f"/bundles/{bundle_id}/bids",
                             payload, headers)

    def list_bundle_bids(self, bundle_id, headers, params=None):
        return self._request("GET", f"/bundles/{bundle_id}/bids",
                             headers=headers, params=params)

    def list_bidder_bids(self, bidder_id, headers, params=None):
        return self._request("GET", f"/bidders/{bidder_id}/bids",
                             headers=headers, params=params)

    # --- Invoice / Payment / Certificate ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers,
                             params=params)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments",
                             payload, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments",
                             headers=headers, params=params)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers)

    def refund_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/refund",
                             {}, headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/write-off",
                             {}, headers)

    def fulfill_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/fulfill",
                             {}, headers)

    def list_invoice_certificates(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/certificates",
                             headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}",
                             headers=headers)

    def redeem_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/certificates/{certificate_id}/redeem",
                             payload, headers)

    # --- Disposition / DonorAcknowledgment ---
    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/dispositions/{disposition_id}",
                             headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/dispositions", headers=headers,
                             params=params)

    def decide_disposition(self, disposition_id, payload, headers):
        return self._request("POST", f"/dispositions/{disposition_id}/decide",
                             payload, headers)

    def respond_to_disposition(self, disposition_id, payload, headers):
        return self._request(
            "POST", f"/dispositions/{disposition_id}/donor-response",
            payload, headers)

    def get_acknowledgment(self, acknowledgment_id, headers):
        return self._request("GET", f"/acknowledgments/{acknowledgment_id}",
                             headers=headers)

    def list_acknowledgments(self, headers, params=None):
        return self._request("GET", "/acknowledgments", headers=headers,
                             params=params)

    def issue_acknowledgment(self, acknowledgment_id, headers):
        return self._request(
            "POST", f"/acknowledgments/{acknowledgment_id}/issue", {}, headers)

    def void_acknowledgment(self, acknowledgment_id, headers):
        return self._request(
            "POST", f"/acknowledgments/{acknowledgment_id}/void", {}, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload,
                             headers)


api_client = ApiClient()
