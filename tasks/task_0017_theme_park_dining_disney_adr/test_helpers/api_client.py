"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under the `/v1` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Guests ──────────────────────────────────────────────────────
    def create_guest(self, payload, headers):
        return self._request("POST", "/v1/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/v1/guests/{guest_id}", headers=headers)

    # ─── Restaurants ─────────────────────────────────────────────────
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/v1/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/v1/restaurants/{restaurant_id}", headers=headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/v1/restaurants", headers=headers, params=params)

    # ─── Park Sessions ───────────────────────────────────────────────
    def create_park_session(self, payload, headers):
        return self._request("POST", "/v1/park-sessions", payload, headers)

    def get_park_session(self, ps_id, headers):
        return self._request("GET", f"/v1/park-sessions/{ps_id}", headers=headers)

    def list_park_sessions(self, headers, params=None):
        return self._request("GET", "/v1/park-sessions", headers=headers, params=params)

    def activate_park_session(self, ps_id, headers):
        return self._request("POST", f"/v1/park-sessions/{ps_id}/activate", headers=headers)

    def close_park_session(self, ps_id, headers):
        return self._request("POST", f"/v1/park-sessions/{ps_id}/close", headers=headers)

    def cancel_park_session(self, ps_id, headers):
        return self._request("POST", f"/v1/park-sessions/{ps_id}/cancel", headers=headers)

    # ─── Dining Plans ────────────────────────────────────────────────
    def create_dining_plan(self, payload, headers):
        return self._request("POST", "/v1/dining-plans", payload, headers)

    def get_dining_plan(self, dp_id, headers):
        return self._request("GET", f"/v1/dining-plans/{dp_id}", headers=headers)

    def list_dining_plans(self, headers, params=None):
        return self._request("GET", "/v1/dining-plans", headers=headers, params=params)

    # ─── Reservations ────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/v1/reservations", payload, headers)

    def get_reservation(self, res_id, headers):
        return self._request("GET", f"/v1/reservations/{res_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/v1/reservations", headers=headers, params=params)

    def confirm_reservation(self, res_id, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/confirm", headers=headers)

    def cancel_reservation(self, res_id, payload, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/cancel", payload, headers)

    def check_in_reservation(self, res_id, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/check-in", headers=headers)

    def seat_reservation(self, res_id, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/seat", headers=headers)

    def complete_reservation(self, res_id, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/complete", headers=headers)

    def mark_no_show_reservation(self, res_id, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/mark-no-show", headers=headers)

    def patch_party_size(self, res_id, payload, headers):
        return self._request("POST", f"/v1/reservations/{res_id}/party-size", payload, headers)

    # ─── Allergy Meals ───────────────────────────────────────────────
    def create_allergy_meal(self, payload, headers):
        return self._request("POST", "/v1/allergy-meals", payload, headers)

    def get_allergy_meal(self, am_id, headers):
        return self._request("GET", f"/v1/allergy-meals/{am_id}", headers=headers)

    def list_allergy_meals(self, headers, params=None):
        return self._request("GET", "/v1/allergy-meals", headers=headers, params=params)

    def acknowledge_allergy_meal(self, am_id, headers):
        return self._request("POST", f"/v1/allergy-meals/{am_id}/acknowledge", headers=headers)

    def prepare_allergy_meal(self, am_id, headers):
        return self._request("POST", f"/v1/allergy-meals/{am_id}/prepare", headers=headers)

    def serve_allergy_meal(self, am_id, headers):
        return self._request("POST", f"/v1/allergy-meals/{am_id}/serve", headers=headers)

    def revert_allergy_meal(self, am_id, headers):
        return self._request("POST", f"/v1/allergy-meals/{am_id}/revert-to-requested", headers=headers)

    def decline_allergy_meal(self, am_id, payload, headers):
        return self._request("POST", f"/v1/allergy-meals/{am_id}/decline", payload, headers)

    # ─── Lightning Lane Add-ons ──────────────────────────────────────
    def create_lightning_lane(self, payload, headers):
        return self._request("POST", "/v1/lightning-lane-addons", payload, headers)

    def get_lightning_lane(self, ll_id, headers):
        return self._request("GET", f"/v1/lightning-lane-addons/{ll_id}", headers=headers)

    def list_lightning_lanes(self, headers, params=None):
        return self._request("GET", "/v1/lightning-lane-addons", headers=headers, params=params)

    def allocate_lightning_lane(self, ll_id, payload, headers):
        return self._request("POST", f"/v1/lightning-lane-addons/{ll_id}/allocate", payload, headers)

    def redeem_lightning_lane(self, ll_id, headers):
        return self._request("POST", f"/v1/lightning-lane-addons/{ll_id}/redeem", headers=headers)

    def cancel_lightning_lane(self, ll_id, headers):
        return self._request("POST", f"/v1/lightning-lane-addons/{ll_id}/cancel", headers=headers)

    # ─── No-show fee assessments & credit ledger (read-only) ─────────
    def get_no_show_fee_assessment(self, assess_id, headers):
        return self._request("GET", f"/v1/no-show-fee-assessments/{assess_id}", headers=headers)

    def list_no_show_fee_assessments(self, headers, params=None):
        return self._request("GET", "/v1/no-show-fee-assessments", headers=headers, params=params)

    def get_credit_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/v1/credit-ledger-entries/{entry_id}", headers=headers)

    def list_credit_ledger_entries(self, headers, params=None):
        return self._request("GET", "/v1/credit-ledger-entries", headers=headers, params=params)

    # ─── Ops / test-driving endpoints ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    def no_show_sweep(self, headers):
        return self._request("POST", "/v1/_ops/no-show-sweep", headers=headers)

    def lightning_lane_expiry_sweep(self, headers):
        return self._request("POST", "/v1/_ops/lightning-lane-expiry-sweep", headers=headers)


api_client = ApiClient()
