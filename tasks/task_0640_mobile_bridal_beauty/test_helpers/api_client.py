"""API client: one method per endpoint defined in the Bridal Beauty PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/bridal-beauty"


class ApiClient(GenericApiClient):
    # ---- Artist roster & portfolio ----
    def create_artist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"{PREFIX}/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/artists", headers=headers, params=params)

    def patch_artist(self, artist_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/artists/{artist_id}", payload, headers)

    def create_portfolio_item(self, artist_id, payload, headers):
        return self._request("POST", f"{PREFIX}/artists/{artist_id}/portfolio", payload, headers)

    def publish_portfolio_item(self, item_id, headers):
        return self._request("POST", f"{PREFIX}/portfolio/{item_id}/publish", {}, headers)

    def list_portfolio(self, artist_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/artists/{artist_id}/portfolio", headers=headers, params=params)

    # ---- Bridal events & faces ----
    def create_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/events", headers=headers, params=params)

    def add_face(self, event_id, payload, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/faces", payload, headers)

    def confirm_face(self, face_id, headers):
        return self._request("POST", f"{PREFIX}/faces/{face_id}/confirm", {}, headers)

    def remove_face(self, face_id, headers):
        return self._request("POST", f"{PREFIX}/faces/{face_id}/remove", {}, headers)

    def list_faces(self, event_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/events/{event_id}/faces", headers=headers, params=params)

    def quote_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/quote", {}, headers)

    def request_revision(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/request-revision", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, payload, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/cancel", payload, headers)

    def list_cancellations(self, event_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/events/{event_id}/cancellation", headers=headers, params=params)

    # ---- Trials ----
    def create_trial(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trials", payload, headers)

    def get_trial(self, trial_id, headers):
        return self._request("GET", f"{PREFIX}/trials/{trial_id}", headers=headers)

    def list_trials(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/trials", headers=headers, params=params)

    def complete_trial(self, trial_id, headers):
        return self._request("POST", f"{PREFIX}/trials/{trial_id}/complete", {}, headers)

    def no_show_trial(self, trial_id, headers):
        return self._request("POST", f"{PREFIX}/trials/{trial_id}/no-show", {}, headers)

    def cancel_trial(self, trial_id, headers):
        return self._request("POST", f"{PREFIX}/trials/{trial_id}/cancel", {}, headers)

    # ---- Contracts ----
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    # ---- Assignments & add-ons ----
    def create_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments", headers=headers, params=params)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/start", {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/complete", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/cancel", {}, headers)

    def add_addon(self, assignment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/addons", payload, headers)

    def list_addons(self, assignment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}/addons", headers=headers, params=params)

    # ---- Invoices & payments ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/payments", payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}/payments", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
