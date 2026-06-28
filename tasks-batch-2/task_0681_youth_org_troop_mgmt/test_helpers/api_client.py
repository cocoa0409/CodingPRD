"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Council ----
    def create_council(self, payload, headers):
        return self._request("POST", "/councils", payload, headers)

    def get_council(self, council_id, headers):
        return self._request("GET", f"/councils/{council_id}", headers=headers)

    def list_council_ledger(self, council_id, headers, params=None):
        return self._request("GET", f"/councils/{council_id}/ledger", headers=headers, params=params)

    def get_council_report(self, council_id, headers):
        return self._request("GET", f"/councils/{council_id}/report", headers=headers)

    # ---- Troop ----
    def create_troop(self, council_id, payload, headers):
        return self._request("POST", f"/councils/{council_id}/troops", payload, headers)

    def get_troop(self, troop_id, headers):
        return self._request("GET", f"/troops/{troop_id}", headers=headers)

    def list_troops(self, headers, params=None):
        return self._request("GET", "/troops", headers=headers, params=params)

    def list_troop_ledger(self, troop_id, headers, params=None):
        return self._request("GET", f"/troops/{troop_id}/ledger", headers=headers, params=params)

    def recharter_troop(self, troop_id, payload, headers):
        return self._request("POST", f"/troops/{troop_id}/recharter", payload, headers)

    def lapse_troop(self, troop_id, headers):
        return self._request("POST", f"/troops/{troop_id}/lapse", {}, headers)

    def drop_troop(self, troop_id, headers):
        return self._request("POST", f"/troops/{troop_id}/drop", {}, headers)

    # ---- Member ----
    def create_member(self, troop_id, payload, headers):
        return self._request("POST", f"/troops/{troop_id}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    def drop_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/drop", {}, headers)

    # ---- Dues invoices & payments ----
    def create_dues_invoice(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/dues-invoices", payload, headers)

    def get_dues_invoice(self, invoice_id, headers):
        return self._request("GET", f"/dues-invoices/{invoice_id}", headers=headers)

    def list_dues_invoices(self, headers, params=None):
        return self._request("GET", "/dues-invoices", headers=headers, params=params)

    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---- Leader credentials ----
    def create_leader_credential(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/leader-credentials", payload, headers)

    def get_leader_credential(self, credential_id, headers):
        return self._request("GET", f"/leader-credentials/{credential_id}", headers=headers)

    def list_leader_credentials(self, headers, params=None):
        return self._request("GET", "/leader-credentials", headers=headers, params=params)

    def start_bgcheck(self, credential_id, headers):
        return self._request("POST", f"/leader-credentials/{credential_id}/start-bgcheck", {}, headers)

    def resolve_bgcheck(self, credential_id, payload, headers):
        return self._request("POST", f"/leader-credentials/{credential_id}/resolve-bgcheck", payload, headers)

    def complete_training(self, credential_id, headers):
        return self._request("POST", f"/leader-credentials/{credential_id}/complete-training", {}, headers)

    # ---- Advancement ----
    def create_advancement(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/advancements", payload, headers)

    def get_advancement(self, advancement_id, headers):
        return self._request("GET", f"/advancements/{advancement_id}", headers=headers)

    def list_advancements(self, headers, params=None):
        return self._request("GET", "/advancements", headers=headers, params=params)

    def sign_requirement(self, advancement_id, headers):
        return self._request("POST", f"/advancements/{advancement_id}/sign-requirement", {}, headers)

    def submit_advancement(self, advancement_id, headers):
        return self._request("POST", f"/advancements/{advancement_id}/submit", {}, headers)

    def return_advancement(self, advancement_id, headers):
        return self._request("POST", f"/advancements/{advancement_id}/return", {}, headers)

    def approve_advancement(self, advancement_id, headers):
        return self._request("POST", f"/advancements/{advancement_id}/approve", {}, headers)

    # ---- Events & registrations ----
    def create_event(self, troop_id, payload, headers):
        return self._request("POST", f"/troops/{troop_id}/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def lock_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/lock", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    def create_event_registration(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/registrations", payload, headers)

    def get_event_registration(self, registration_id, headers):
        return self._request("GET", f"/event-registrations/{registration_id}", headers=headers)

    def list_event_registrations(self, headers, params=None):
        return self._request("GET", "/event-registrations", headers=headers, params=params)

    def sign_permission(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/sign-permission", {}, headers)

    def file_health(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/file-health", {}, headers)

    def confirm_registration(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/confirm", {}, headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/cancel", {}, headers)

    # ---- Fundraiser, orders, booths ----
    def create_fundraiser(self, council_id, payload, headers):
        return self._request("POST", f"/councils/{council_id}/fundraisers", payload, headers)

    def get_fundraiser(self, fundraiser_id, headers):
        return self._request("GET", f"/fundraisers/{fundraiser_id}", headers=headers)

    def list_fundraisers(self, headers, params=None):
        return self._request("GET", "/fundraisers", headers=headers, params=params)

    def go_live_fundraiser(self, fundraiser_id, headers):
        return self._request("POST", f"/fundraisers/{fundraiser_id}/go-live", {}, headers)

    def close_fundraiser(self, fundraiser_id, headers):
        return self._request("POST", f"/fundraisers/{fundraiser_id}/close", {}, headers)

    def create_fundraiser_order(self, payload, headers):
        return self._request("POST", "/fundraiser-orders", payload, headers)

    def get_fundraiser_order(self, order_id, headers):
        return self._request("GET", f"/fundraiser-orders/{order_id}", headers=headers)

    def list_fundraiser_orders(self, headers, params=None):
        return self._request("GET", "/fundraiser-orders", headers=headers, params=params)

    def fill_order(self, order_id, headers):
        return self._request("POST", f"/fundraiser-orders/{order_id}/fill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/fundraiser-orders/{order_id}/cancel", {}, headers)

    def create_booth_reservation(self, fundraiser_id, payload, headers):
        return self._request("POST", f"/fundraisers/{fundraiser_id}/booth-reservations", payload, headers)

    def get_booth_reservation(self, reservation_id, headers):
        return self._request("GET", f"/booth-reservations/{reservation_id}", headers=headers)

    def list_booth_reservations(self, headers, params=None):
        return self._request("GET", "/booth-reservations", headers=headers, params=params)

    def release_booth_reservation(self, reservation_id, headers):
        return self._request("POST", f"/booth-reservations/{reservation_id}/release", {}, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
