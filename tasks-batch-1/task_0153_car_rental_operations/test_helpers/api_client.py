"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Location ----
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_location_vehicles(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/vehicles", headers=headers, params=params)

    # ---- VehicleClass ----
    def create_vehicle_class(self, payload, headers):
        return self._request("POST", "/vehicle-classes", payload, headers)

    def get_vehicle_class(self, class_id, headers):
        return self._request("GET", f"/vehicle-classes/{class_id}", headers=headers)

    def list_class_vehicles(self, class_id, headers, params=None):
        return self._request("GET", f"/vehicle-classes/{class_id}/vehicles", headers=headers, params=params)

    # ---- RatePlan ----
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/rate-plans", payload, headers)

    def list_rate_plans(self, headers, params=None):
        return self._request("GET", "/rate-plans", headers=headers, params=params)

    def get_rate_plan(self, plan_id, headers):
        return self._request("GET", f"/rate-plans/{plan_id}", headers=headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def hold_vehicle(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/hold", payload, headers)

    def release_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/release", {}, headers)

    def return_vehicle_to_service(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/return-to-service", {}, headers)

    def retire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/retire", {}, headers)

    # ---- LoyaltyMember ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_member_reservations(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/reservations", headers=headers, params=params)

    def list_member_loyalty_accruals(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/loyalty-accruals", headers=headers, params=params)

    def redeem_points(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/redeem", payload, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservation_rental_agreements(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/rental-agreements", headers=headers, params=params)

    def upgrade_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/upgrade", payload, headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/no-show", {}, headers)

    def expire_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/expire", {}, headers)

    # ---- RentalAgreement ----
    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request("GET", f"/rental-agreements/{agreement_id}", headers=headers)

    def list_agreement_loyalty_accruals(self, agreement_id, headers, params=None):
        return self._request("GET", f"/rental-agreements/{agreement_id}/loyalty-accruals", headers=headers, params=params)

    def list_agreement_ledger_entries(self, agreement_id, headers, params=None):
        return self._request("GET", f"/rental-agreements/{agreement_id}/ledger-entries", headers=headers, params=params)

    def list_agreement_incident_reports(self, agreement_id, headers, params=None):
        return self._request("GET", f"/rental-agreements/{agreement_id}/incident-reports", headers=headers, params=params)

    def close_rental_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/close", payload, headers)

    def write_off_rental_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/write-off", payload, headers)

    # ---- IncidentReport ----
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def resolve_incident_report(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/resolve", {}, headers)

    def void_incident_report(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/void", {}, headers)

    # ---- Test-driving capabilities ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_member_loyalty(self, member_id, payload, headers):
        return self._request("POST", f"/_members/{member_id}/set_loyalty", payload, headers)


api_client = ApiClient()
