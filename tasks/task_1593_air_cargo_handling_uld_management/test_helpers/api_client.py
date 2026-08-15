"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- flights ---
    def create_flight(self, payload, headers):
        return self._request("POST", "/cargo/flights", payload, headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/cargo/flights", headers=headers, params=params)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/cargo/flights/{flight_id}", headers=headers)

    def open_flight(self, flight_id, headers):
        return self._request("POST", f"/cargo/flights/{flight_id}/open", headers=headers)

    def close_flight(self, flight_id, headers):
        return self._request("POST", f"/cargo/flights/{flight_id}/close", headers=headers)

    def depart_flight(self, flight_id, headers):
        return self._request("POST", f"/cargo/flights/{flight_id}/depart", headers=headers)

    def impose_weight_restriction(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/cargo/flights/{flight_id}/weight-restriction", payload, headers
        )

    def list_flight_bookings(self, flight_id, headers, params=None):
        return self._request(
            "GET", f"/cargo/flights/{flight_id}/bookings", headers=headers, params=params
        )

    def list_flight_build_up_plans(self, flight_id, headers, params=None):
        return self._request(
            "GET",
            f"/cargo/flights/{flight_id}/build-up-plans",
            headers=headers,
            params=params,
        )

    # --- bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/cargo/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/cargo/bookings/{booking_id}", headers=headers)

    def accept_booking(self, booking_id, headers):
        return self._request("POST", f"/cargo/bookings/{booking_id}/accept", headers=headers)

    def reject_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/cargo/bookings/{booking_id}/reject", payload, headers
        )

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/cargo/bookings/{booking_id}/cancel", headers=headers)

    def rebook_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/cargo/bookings/{booking_id}/rebook", payload, headers
        )

    # --- booking sub-resources ---
    def list_booking_dg_declarations(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"/cargo/bookings/{booking_id}/dg-declarations",
            headers=headers,
            params=params,
        )

    def create_dg_declaration(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/cargo/bookings/{booking_id}/dg-declarations", payload, headers
        )

    def list_temperature_logs(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"/cargo/bookings/{booking_id}/temperature-logs",
            headers=headers,
            params=params,
        )

    def create_temperature_log(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/cargo/bookings/{booking_id}/temperature-logs", payload, headers
        )

    def list_customs_holds(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"/cargo/bookings/{booking_id}/customs-holds",
            headers=headers,
            params=params,
        )

    def create_customs_hold(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/cargo/bookings/{booking_id}/customs-holds", payload, headers
        )

    def list_booking_claims(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/cargo/bookings/{booking_id}/claims", headers=headers, params=params
        )

    # --- ULD types and units ---
    def create_uld_type(self, payload, headers):
        return self._request("POST", "/cargo/uld-types", payload, headers)

    def create_uld(self, payload, headers):
        return self._request("POST", "/cargo/ulds", payload, headers)

    def list_ulds(self, headers, params=None):
        return self._request("GET", "/cargo/ulds", headers=headers, params=params)

    def get_uld(self, uld_id, headers):
        return self._request("GET", f"/cargo/ulds/{uld_id}", headers=headers)

    def return_uld(self, uld_id, headers):
        return self._request("POST", f"/cargo/ulds/{uld_id}/return", headers=headers)

    def report_uld_damage(self, uld_id, payload, headers):
        return self._request(
            "POST", f"/cargo/ulds/{uld_id}/report-damage", payload, headers
        )

    def complete_uld_repair(self, uld_id, payload, headers):
        return self._request(
            "POST", f"/cargo/ulds/{uld_id}/complete-repair", payload, headers
        )

    def release_uld(self, uld_id, headers):
        return self._request("POST", f"/cargo/ulds/{uld_id}/release", headers=headers)

    def list_uld_build_up_plans(self, uld_id, headers, params=None):
        return self._request(
            "GET", f"/cargo/ulds/{uld_id}/build-up-plans", headers=headers, params=params
        )

    def list_uld_charges(self, uld_id, headers, params=None):
        return self._request(
            "GET", f"/cargo/ulds/{uld_id}/charges", headers=headers, params=params
        )

    # --- build-up plans ---
    def create_build_up_plan(self, payload, headers):
        return self._request("POST", "/cargo/build-up-plans", payload, headers)

    def get_build_up_plan(self, plan_id, headers):
        return self._request("GET", f"/cargo/build-up-plans/{plan_id}", headers=headers)

    def list_plan_bookings(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/cargo/build-up-plans/{plan_id}/bookings", headers=headers, params=params
        )

    def assign_booking_to_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/cargo/build-up-plans/{plan_id}/assign", payload, headers
        )

    def seal_plan(self, plan_id, headers):
        return self._request("POST", f"/cargo/build-up-plans/{plan_id}/seal", headers=headers)

    def cancel_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/cargo/build-up-plans/{plan_id}/cancel", headers=headers
        )

    # --- DG declarations (checker side) ---
    def accept_dg_declaration(self, declaration_id, headers):
        return self._request(
            "POST", f"/cargo/dg-declarations/{declaration_id}/accept", headers=headers
        )

    def reject_dg_declaration(self, declaration_id, payload, headers):
        return self._request(
            "POST", f"/cargo/dg-declarations/{declaration_id}/reject", payload, headers
        )

    # --- customs holds ---
    def release_customs_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/cargo/customs-holds/{hold_id}/release", payload, headers
        )

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/cargo/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/cargo/claims/{claim_id}", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/cargo/claims/{claim_id}/approve", headers=headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/cargo/claims/{claim_id}/reject", payload, headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/cargo/claims/{claim_id}/settle", payload, headers)

    # --- ULD charges ---
    def get_uld_charge(self, charge_id, headers):
        return self._request("GET", f"/cargo/uld-charges/{charge_id}", headers=headers)

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/cargo/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
