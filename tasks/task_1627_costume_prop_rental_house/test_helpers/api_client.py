"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The runner SIGKILLs and re-spawns the server before every test
        # (per-test-server isolation) while this session-scoped client lives on.
        # A pooled keep-alive connection to the killed server can then be reused
        # by the next test's first request and fail with ECONNRESET. Forcing
        # "Connection: close" makes every request open a fresh TCP connection,
        # so no stale pooled socket can ever be reused across a restart.
        self.session.headers["Connection"] = "close"

    # --- Logical clock / operations checkpoint ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/rental-house/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_daily_ops(self, headers):
        return self._request("POST", "/rental-house/run_daily_ops", {}, headers)

    # --- Renters ---
    def create_renter(self, payload, headers):
        return self._request("POST", "/rental-house/renters", payload, headers)

    def list_renters(self, headers, params=None):
        return self._request("GET", "/rental-house/renters", headers=headers, params=params)

    def get_renter(self, renter_id, headers):
        return self._request("GET", f"/rental-house/renters/{renter_id}", headers=headers)

    def update_renter(self, renter_id, payload, headers):
        return self._request("PATCH", f"/rental-house/renters/{renter_id}", payload, headers)

    # --- Insurance certificates ---
    def submit_certificate(self, renter_id, payload, headers):
        return self._request(
            "POST", f"/rental-house/renters/{renter_id}/insurance-certificates",
            payload, headers,
        )

    def list_certificates(self, renter_id, headers, params=None):
        return self._request(
            "GET", f"/rental-house/renters/{renter_id}/insurance-certificates",
            headers=headers, params=params,
        )

    def get_certificate(self, cert_id, headers):
        return self._request(
            "GET", f"/rental-house/insurance-certificates/{cert_id}", headers=headers,
        )

    def decide_certificate(self, cert_id, decision, headers):
        return self._request(
            "POST", f"/rental-house/insurance-certificates/{cert_id}/decide",
            {"decision": decision}, headers,
        )

    # --- Rate cards ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rental-house/rate-cards", payload, headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rental-house/rate-cards", headers=headers, params=params)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rental-house/rate-cards/{rate_card_id}", headers=headers)

    # --- Items ---
    def create_item(self, payload, headers):
        return self._request("POST", "/rental-house/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/rental-house/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/rental-house/items/{item_id}", headers=headers)

    def request_deaccession(self, item_id, headers):
        return self._request(
            "POST", f"/rental-house/items/{item_id}/request-deaccession", {}, headers,
        )

    def cancel_deaccession(self, item_id, headers):
        return self._request(
            "POST", f"/rental-house/items/{item_id}/cancel-deaccession", {}, headers,
        )

    def complete_deaccession(self, item_id, headers):
        return self._request(
            "POST", f"/rental-house/items/{item_id}/complete-deaccession", {}, headers,
        )

    # --- Item units ---
    def create_unit(self, item_id, payload, headers):
        return self._request("POST", f"/rental-house/items/{item_id}/units", payload, headers)

    def list_units(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/rental-house/items/{item_id}/units", headers=headers, params=params,
        )

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/rental-house/units/{unit_id}", headers=headers)

    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/rental-house/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/rental-house/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/rental-house/productions/{production_id}", headers=headers)

    def confirm_production(self, production_id, headers):
        return self._request(
            "POST", f"/rental-house/productions/{production_id}/confirm", {}, headers,
        )

    def cancel_production(self, production_id, headers):
        return self._request(
            "POST", f"/rental-house/productions/{production_id}/cancel", {}, headers,
        )

    # --- Reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/rental-house/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/rental-house/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/rental-house/reservations/{reservation_id}", headers=headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/rental-house/reservations/{reservation_id}/confirm", {}, headers,
        )

    def release_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/rental-house/reservations/{reservation_id}/release", {}, headers,
        )

    def amend_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/rental-house/reservations/{reservation_id}/amend", payload, headers,
        )

    # --- Pull lists ---
    def create_pull_list(self, payload, headers):
        return self._request("POST", "/rental-house/pull-lists", payload, headers)

    def list_pull_lists(self, headers, params=None):
        return self._request("GET", "/rental-house/pull-lists", headers=headers, params=params)

    def get_pull_list(self, pull_list_id, headers):
        return self._request("GET", f"/rental-house/pull-lists/{pull_list_id}", headers=headers)

    def submit_pull_list(self, pull_list_id, headers):
        return self._request(
            "POST", f"/rental-house/pull-lists/{pull_list_id}/submit", {}, headers,
        )

    def dispatch_pull_list(self, pull_list_id, headers):
        return self._request(
            "POST", f"/rental-house/pull-lists/{pull_list_id}/dispatch", {}, headers,
        )

    def cancel_pull_list(self, pull_list_id, headers):
        return self._request(
            "POST", f"/rental-house/pull-lists/{pull_list_id}/cancel", {}, headers,
        )

    # --- Pull list lines ---
    def list_lines(self, headers, params=None):
        return self._request("GET", "/rental-house/pull-list-lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/rental-house/pull-list-lines/{line_id}", headers=headers)

    def pick_line(self, line_id, headers):
        return self._request(
            "POST", f"/rental-house/pull-list-lines/{line_id}/pick", {}, headers,
        )

    def check_in_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/rental-house/pull-list-lines/{line_id}/check-in", payload, headers,
        )

    def report_lost(self, line_id, headers):
        return self._request(
            "POST", f"/rental-house/pull-list-lines/{line_id}/report-lost", {}, headers,
        )

    def get_line_assessment(self, line_id, headers):
        return self._request(
            "GET", f"/rental-house/pull-list-lines/{line_id}/assessment", headers=headers,
        )

    # --- Fitting authorizations ---
    def create_fitting(self, payload, headers):
        return self._request("POST", "/rental-house/fitting-authorizations", payload, headers)

    def list_fittings(self, headers, params=None):
        return self._request(
            "GET", "/rental-house/fitting-authorizations", headers=headers, params=params,
        )

    def get_fitting(self, fitting_id, headers):
        return self._request(
            "GET", f"/rental-house/fitting-authorizations/{fitting_id}", headers=headers,
        )

    def decide_fitting(self, fitting_id, decision, headers):
        return self._request(
            "POST", f"/rental-house/fitting-authorizations/{fitting_id}/decide",
            {"decision": decision}, headers,
        )

    # --- Damage claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/rental-house/damage-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/rental-house/damage-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/rental-house/damage-claims/{claim_id}", headers=headers)

    def post_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/rental-house/damage-claims/{claim_id}/post", {}, headers,
        )

    def dispute_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/rental-house/damage-claims/{claim_id}/dispute", {}, headers,
        )

    def waive_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/rental-house/damage-claims/{claim_id}/waive", {}, headers,
        )

    # --- Cleaning tickets ---
    def list_unit_tickets(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/rental-house/units/{unit_id}/cleaning-tickets",
            headers=headers, params=params,
        )

    def advance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/rental-house/cleaning-tickets/{ticket_id}/advance", {}, headers,
        )

    # --- Invoices ---
    def generate_invoice(self, production_id, headers):
        return self._request(
            "POST", "/rental-house/invoices/generate", {"production_id": production_id}, headers,
        )

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/rental-house/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/rental-house/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/rental-house/invoices/{invoice_id}/issue", {}, headers,
        )

    def record_payment(self, invoice_id, amount_cents, headers):
        return self._request(
            "POST", f"/rental-house/invoices/{invoice_id}/record-payment",
            {"amount_cents": amount_cents}, headers,
        )

    def credit_note(self, invoice_id, amount_cents, headers, reason=None):
        payload = {"amount_cents": amount_cents}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"/rental-house/invoices/{invoice_id}/credit-note", payload, headers,
        )


api_client = ApiClient()
