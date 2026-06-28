"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base `_request()` is inherited.
GET requests pass filters/pagination via `params`; POST requests pass `payload`
as a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ──────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Gallery ─────────────────────────────────────────────────────────────
    def create_gallery(self, payload, headers):
        return self._request("POST", "/galleries", payload, headers)

    def get_gallery(self, gallery_id, headers):
        return self._request("GET", f"/galleries/{gallery_id}", headers=headers)

    # ─── Artist ──────────────────────────────────────────────────────────────
    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/artists", headers=headers, params=params)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    def suspend_artist(self, artist_id, headers):
        return self._request("POST", f"/artists/{artist_id}/suspend", {}, headers)

    def reinstate_artist(self, artist_id, headers):
        return self._request("POST", f"/artists/{artist_id}/reinstate", {}, headers)

    # ─── Artwork ─────────────────────────────────────────────────────────────
    def create_artwork(self, payload, headers):
        return self._request("POST", "/artworks", payload, headers)

    def list_artworks(self, headers, params=None):
        return self._request("GET", "/artworks", headers=headers, params=params)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}", headers=headers)

    def append_provenance(self, artwork_id, payload, headers):
        return self._request("POST", f"/artworks/{artwork_id}/provenance", payload, headers)

    def return_artwork_to_artist(self, artwork_id, headers):
        return self._request("POST", f"/artworks/{artwork_id}/return-to-artist", {}, headers)

    # ─── Exhibition + wall map ───────────────────────────────────────────────
    def create_exhibition(self, payload, headers):
        return self._request("POST", "/exhibitions", payload, headers)

    def list_exhibitions(self, headers, params=None):
        return self._request("GET", "/exhibitions", headers=headers, params=params)

    def get_exhibition(self, exhibition_id, headers):
        return self._request("GET", f"/exhibitions/{exhibition_id}", headers=headers)

    def open_exhibition(self, exhibition_id, headers):
        return self._request("POST", f"/exhibitions/{exhibition_id}/open", {}, headers)

    def close_exhibition(self, exhibition_id, headers):
        return self._request("POST", f"/exhibitions/{exhibition_id}/close", {}, headers)

    def cancel_exhibition(self, exhibition_id, headers):
        return self._request("POST", f"/exhibitions/{exhibition_id}/cancel", {}, headers)

    def place_wall_slot(self, exhibition_id, payload, headers):
        return self._request("POST", f"/exhibitions/{exhibition_id}/wall-slots", payload, headers)

    def list_exhibition_wall_slots(self, exhibition_id, headers, params=None):
        return self._request("GET", f"/exhibitions/{exhibition_id}/wall-slots",
                             headers=headers, params=params)

    def list_wall_slots(self, headers, params=None):
        return self._request("GET", "/wall-slots", headers=headers, params=params)

    def get_wall_slot(self, wall_slot_id, headers):
        return self._request("GET", f"/wall-slots/{wall_slot_id}", headers=headers)

    # ─── Sale + payments + shipping ──────────────────────────────────────────
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def invoice_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/invoice", {}, headers)

    def post_payment(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/payments", payload, headers)

    def settle_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/settle", {}, headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers)

    def ship_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/ship", {}, headers)

    def deliver_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/deliver", {}, headers)

    # ─── Payment plans ───────────────────────────────────────────────────────
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/payment-plans", payload, headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def sweep_overdue_plan(self, plan_id, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/sweep-overdue", {}, headers)

    # ─── Leases ──────────────────────────────────────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def convert_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/convert", {}, headers)

    def return_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/return", {}, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/terminate", {}, headers)

    # ─── Opening events + RSVP ───────────────────────────────────────────────
    def create_opening_event(self, payload, headers):
        return self._request("POST", "/opening-events", payload, headers)

    def list_opening_events(self, headers, params=None):
        return self._request("GET", "/opening-events", headers=headers, params=params)

    def get_opening_event(self, event_id, headers):
        return self._request("GET", f"/opening-events/{event_id}", headers=headers)

    def close_opening_event(self, event_id, headers):
        return self._request("POST", f"/opening-events/{event_id}/close", {}, headers)

    def cancel_opening_event(self, event_id, headers):
        return self._request("POST", f"/opening-events/{event_id}/cancel", {}, headers)

    def create_rsvp(self, payload, headers):
        return self._request("POST", "/rsvps", payload, headers)

    def list_rsvps(self, headers, params=None):
        return self._request("GET", "/rsvps", headers=headers, params=params)

    def get_rsvp(self, rsvp_id, headers):
        return self._request("GET", f"/rsvps/{rsvp_id}", headers=headers)

    def cancel_rsvp(self, rsvp_id, headers):
        return self._request("POST", f"/rsvps/{rsvp_id}/cancel", {}, headers)

    # ─── Loans ───────────────────────────────────────────────────────────────
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def return_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/return", {}, headers)

    def sweep_overdue_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/sweep-overdue", {}, headers)

    # ─── Payouts + reporting ─────────────────────────────────────────────────
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def complete_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/complete", {}, headers)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/reverse", {}, headers)

    def sales_summary_report(self, headers, params=None):
        return self._request("GET", "/reports/sales-summary", headers=headers, params=params)


api_client = ApiClient()
