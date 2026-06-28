"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the envelope and headers.
All paths live under the /birth-center prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/birth-center"


class ApiClient(GenericApiClient):
    # ----- Logical clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ----- Client -----
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients", headers=headers, params=params)

    def archive_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/archive", {}, headers)

    # ----- CarePackage -----
    def create_care_package(self, payload, headers):
        return self._request("POST", f"{PREFIX}/care-packages", payload, headers)

    def get_care_package(self, code, headers):
        return self._request("GET", f"{PREFIX}/care-packages/{code}", headers=headers)

    def list_care_packages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/care-packages", headers=headers, params=params)

    # ----- SupplyKit -----
    def create_supply_kit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supply-kits", payload, headers)

    def get_supply_kit(self, sku, headers):
        return self._request("GET", f"{PREFIX}/supply-kits/{sku}", headers=headers)

    def list_supply_kits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/supply-kits", headers=headers, params=params)

    # ----- Provider -----
    def create_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/providers", headers=headers, params=params)

    # ----- Room -----
    def create_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rooms", headers=headers, params=params)

    def close_room(self, room_id, headers):
        return self._request("POST", f"{PREFIX}/rooms/{room_id}/close", {}, headers)

    # ----- Episode -----
    def create_episode(self, payload, headers):
        return self._request("POST", f"{PREFIX}/episodes", payload, headers)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes", headers=headers, params=params)

    def activate_episode(self, episode_id, headers):
        return self._request("POST", f"{PREFIX}/episodes/{episode_id}/activate", {}, headers)

    def transfer_episode(self, episode_id, headers):
        return self._request("POST", f"{PREFIX}/episodes/{episode_id}/transfer", {}, headers)

    def record_birth(self, episode_id, headers):
        return self._request("POST", f"{PREFIX}/episodes/{episode_id}/record-birth", {}, headers)

    def complete_care(self, episode_id, headers):
        return self._request("POST", f"{PREFIX}/episodes/{episode_id}/complete-care", {}, headers)

    def write_off_episode(self, episode_id, headers):
        return self._request("POST", f"{PREFIX}/episodes/{episode_id}/write-off", {}, headers)

    def list_episode_prenatal_visits(self, episode_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}/prenatal-visits", headers=headers, params=params)

    def list_episode_charges(self, episode_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}/charges", headers=headers, params=params)

    def list_episode_on_call_assignments(self, episode_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}/on-call-assignments", headers=headers, params=params)

    def list_episode_bookings(self, episode_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}/bookings", headers=headers, params=params)

    def list_episode_insurance_claims(self, episode_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}/insurance-claims", headers=headers, params=params)

    def list_episode_payment_plans(self, episode_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/episodes/{episode_id}/payment-plans", headers=headers, params=params)

    # ----- PrenatalVisit -----
    def create_prenatal_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prenatal-visits", payload, headers)

    def get_prenatal_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/prenatal-visits/{visit_id}", headers=headers)

    def complete_prenatal_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/prenatal-visits/{visit_id}/complete", payload, headers)

    def mark_no_show(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/prenatal-visits/{visit_id}/mark-no-show", {}, headers)

    def cancel_prenatal_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/prenatal-visits/{visit_id}/cancel", {}, headers)

    # ----- OnCallAssignment -----
    def create_on_call_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/on-call-assignments", payload, headers)

    def get_on_call_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/on-call-assignments/{assignment_id}", headers=headers)

    def list_on_call_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/on-call-assignments", headers=headers, params=params)

    def name_backup(self, assignment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/on-call-assignments/{assignment_id}/name-backup", payload, headers)

    def go_on_duty(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/on-call-assignments/{assignment_id}/go-on-duty", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/on-call-assignments/{assignment_id}/release", {}, headers)

    # ----- Booking -----
    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/confirm", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/cancel", {}, headers)

    # ----- Charge -----
    def create_charge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/charges", payload, headers)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"{PREFIX}/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/charges", headers=headers, params=params)

    def bill_charge(self, charge_id, headers):
        return self._request("POST", f"{PREFIX}/charges/{charge_id}/bill", {}, headers)

    # ----- InsuranceClaim -----
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/insurance-claims/{claim_id}", headers=headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/insurance-claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims/{claim_id}/adjudicate", payload, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims/{claim_id}/deny", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims/{claim_id}/void", {}, headers)

    # ----- PaymentPlan -----
    def create_payment_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/payment-plans/{plan_id}", headers=headers)

    def apply_payment(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-plans/{plan_id}/payments", payload, headers)

    def default_payment_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/payment-plans/{plan_id}/default", {}, headers)


api_client = ApiClient()
