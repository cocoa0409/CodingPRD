"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Parties ---
    def create_party(self, payload, headers):
        return self._request("POST", "/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/parties/{party_id}", headers=headers)

    # --- Fairs ---
    def create_fair(self, payload, headers):
        return self._request("POST", "/fairs", payload, headers)

    def list_fairs(self, headers, params=None):
        return self._request("GET", "/fairs", headers=headers, params=params)

    def get_fair(self, fair_id, headers):
        return self._request("GET", f"/fairs/{fair_id}", headers=headers)

    def schedule_fair(self, fair_id, headers):
        return self._request("POST", f"/fairs/{fair_id}/schedule", {}, headers)

    def open_stocking(self, fair_id, headers):
        return self._request("POST", f"/fairs/{fair_id}/open-stocking", {}, headers)

    def open_fair(self, fair_id, headers):
        return self._request("POST", f"/fairs/{fair_id}/open", {}, headers)

    def close_sales(self, fair_id, headers):
        return self._request("POST", f"/fairs/{fair_id}/close-sales", {}, headers)

    def settle_fair(self, fair_id, headers):
        return self._request("POST", f"/fairs/{fair_id}/settle", {}, headers)

    def cancel_fair(self, fair_id, headers, payload=None):
        return self._request("POST", f"/fairs/{fair_id}/cancel", payload or {}, headers)

    # --- Venue slots ---
    def create_venue_slot(self, payload, headers):
        return self._request("POST", "/venue-slots", payload, headers)

    def list_venue_slots(self, headers, params=None):
        return self._request("GET", "/venue-slots", headers=headers, params=params)

    def get_venue_slot(self, slot_id, headers):
        return self._request("GET", f"/venue-slots/{slot_id}", headers=headers)

    def confirm_venue_slot(self, slot_id, headers):
        return self._request("POST", f"/venue-slots/{slot_id}/confirm", {}, headers)

    def release_venue_slot(self, slot_id, headers):
        return self._request("POST", f"/venue-slots/{slot_id}/release", {}, headers)

    # --- Consignment agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/consignment-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/consignment-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/consignment-agreements/{agreement_id}", headers=headers)

    def counter_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/consignment-agreements/{agreement_id}/counter", payload, headers)

    def accept_agreement(self, agreement_id, headers):
        return self._request("POST", f"/consignment-agreements/{agreement_id}/accept", {}, headers)

    def decline_agreement(self, agreement_id, headers):
        return self._request("POST", f"/consignment-agreements/{agreement_id}/decline", {}, headers)

    # --- Stock lines ---
    def create_stock_line(self, payload, headers):
        return self._request("POST", "/stock-lines", payload, headers)

    def list_stock_lines(self, headers, params=None):
        return self._request("GET", "/stock-lines", headers=headers, params=params)

    def get_stock_line(self, line_id, headers):
        return self._request("GET", f"/stock-lines/{line_id}", headers=headers)

    def commit_stock_line(self, line_id, headers):
        return self._request("POST", f"/stock-lines/{line_id}/commit", {}, headers)

    def deliver_stock_line(self, line_id, payload, headers):
        return self._request("POST", f"/stock-lines/{line_id}/deliver", payload, headers)

    def damage_stock_line(self, line_id, payload, headers):
        return self._request("POST", f"/stock-lines/{line_id}/damage", payload, headers)

    # --- Author bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/author-bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/author-bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/author-bookings/{booking_id}", headers=headers)

    def counter_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/author-bookings/{booking_id}/counter", payload, headers)

    def accept_booking(self, booking_id, headers):
        return self._request("POST", f"/author-bookings/{booking_id}/accept", {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/author-bookings/{booking_id}/decline", {}, headers)

    def book_travel(self, booking_id, payload, headers):
        return self._request("POST", f"/author-bookings/{booking_id}/book-travel", payload, headers)

    def settle_booking(self, booking_id, headers):
        return self._request("POST", f"/author-bookings/{booking_id}/settle", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/author-bookings/{booking_id}/cancel", {}, headers)

    # --- Signing sessions ---
    def create_session(self, payload, headers):
        return self._request("POST", "/signing-sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/signing-sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/signing-sessions/{session_id}", headers=headers)

    def open_signing(self, session_id, headers):
        return self._request("POST", f"/signing-sessions/{session_id}/open-signing", {}, headers)

    def close_signing(self, session_id, headers):
        return self._request("POST", f"/signing-sessions/{session_id}/close-signing", {}, headers)

    def reconcile_session(self, session_id, headers):
        return self._request("POST", f"/signing-sessions/{session_id}/reconcile", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/signing-sessions/{session_id}/cancel", {}, headers)

    # --- Signing tickets ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/signing-tickets", payload, headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/signing-tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/signing-tickets/{ticket_id}", headers=headers)

    def admit_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/signing-tickets/{ticket_id}/admit", payload, headers)

    def redeem_ticket(self, ticket_id, headers):
        return self._request("POST", f"/signing-tickets/{ticket_id}/redeem", {}, headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/signing-tickets/{ticket_id}/void", {}, headers)

    # --- Preorders ---
    def create_preorder(self, payload, headers):
        return self._request("POST", "/preorders", payload, headers)

    def list_preorders(self, headers, params=None):
        return self._request("GET", "/preorders", headers=headers, params=params)

    def get_preorder(self, preorder_id, headers):
        return self._request("GET", f"/preorders/{preorder_id}", headers=headers)

    def fulfill_preorder(self, preorder_id, headers):
        return self._request("POST", f"/preorders/{preorder_id}/fulfill", {}, headers)

    def cancel_preorder(self, preorder_id, headers):
        return self._request("POST", f"/preorders/{preorder_id}/cancel", {}, headers)

    # --- Sales ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def tender_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/tender", payload, headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers)

    # --- Reconciliations ---
    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/reconciliations", headers=headers, params=params)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/reconciliations/{recon_id}", headers=headers)

    def post_counts(self, recon_id, payload, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/counts", payload, headers)

    def submit_review(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/submit-review", {}, headers)

    def approve_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/approve", {}, headers)

    def submit_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/submit", {}, headers)

    def accept_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/accept", {}, headers)

    def dispute_reconciliation(self, recon_id, payload, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/dispute", payload, headers)

    # --- Return authorizations ---
    def create_return_authorization(self, payload, headers):
        return self._request("POST", "/return-authorizations", payload, headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request("GET", "/return-authorizations", headers=headers, params=params)

    def get_return_authorization(self, ra_id, headers):
        return self._request("GET", f"/return-authorizations/{ra_id}", headers=headers)

    def approve_return(self, ra_id, headers):
        return self._request("POST", f"/return-authorizations/{ra_id}/approve", {}, headers)

    def reject_return(self, ra_id, headers):
        return self._request("POST", f"/return-authorizations/{ra_id}/reject", {}, headers)

    def ship_return(self, ra_id, headers):
        return self._request("POST", f"/return-authorizations/{ra_id}/ship", {}, headers)

    def confirm_credit_return(self, ra_id, headers):
        return self._request("POST", f"/return-authorizations/{ra_id}/confirm-credit", {}, headers)

    # --- Profit share payouts ---
    def create_payout(self, payload, headers):
        return self._request("POST", "/profit-share-payouts", payload, headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/profit-share-payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/profit-share-payouts/{payout_id}", headers=headers)

    def calculate_payout(self, payout_id, headers):
        return self._request("POST", f"/profit-share-payouts/{payout_id}/calculate", {}, headers)

    def recalculate_payout(self, payout_id, headers):
        return self._request("POST", f"/profit-share-payouts/{payout_id}/recalculate", {}, headers)

    def approve_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/profit-share-payouts/{payout_id}/approve", payload, headers)

    def pay_payout(self, payout_id, headers):
        return self._request("POST", f"/profit-share-payouts/{payout_id}/pay", {}, headers)

    # --- Media blasts ---
    def create_media_blast(self, payload, headers):
        return self._request("POST", "/media-blasts", payload, headers)

    def list_media_blasts(self, headers, params=None):
        return self._request("GET", "/media-blasts", headers=headers, params=params)

    def get_media_blast(self, blast_id, headers):
        return self._request("GET", f"/media-blasts/{blast_id}", headers=headers)

    def submit_media_blast(self, blast_id, headers):
        return self._request("POST", f"/media-blasts/{blast_id}/submit", {}, headers)

    def approve_media_blast(self, blast_id, headers):
        return self._request("POST", f"/media-blasts/{blast_id}/approve", {}, headers)

    def reject_media_blast(self, blast_id, headers):
        return self._request("POST", f"/media-blasts/{blast_id}/reject", {}, headers)

    def publish_media_blast(self, blast_id, headers):
        return self._request("POST", f"/media-blasts/{blast_id}/publish", {}, headers)


api_client = ApiClient()
