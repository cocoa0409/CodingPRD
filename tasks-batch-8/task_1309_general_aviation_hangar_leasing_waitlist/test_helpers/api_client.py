"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Airports ---
    def create_airport(self, payload, headers):
        return self._request("POST", "/airports", payload, headers)

    def list_airports(self, headers, params=None):
        return self._request("GET", "/airports", headers=headers, params=params)

    def get_airport(self, airport_id, headers):
        return self._request("GET", f"/airports/{airport_id}", headers=headers)

    def suspend_airport(self, airport_id, headers):
        return self._request("POST", f"/airports/{airport_id}/suspend", {}, headers)

    def resume_airport(self, airport_id, headers):
        return self._request("POST", f"/airports/{airport_id}/resume", {}, headers)

    def list_airport_hangars(self, airport_id, headers, params=None):
        return self._request("GET", f"/airports/{airport_id}/hangars", headers=headers, params=params)

    # --- Rate schedules ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/rate-schedules/{schedule_id}", headers=headers)

    # --- Hangars ---
    def create_hangar(self, payload, headers):
        return self._request("POST", "/hangars", payload, headers)

    def list_hangars(self, headers, params=None):
        return self._request("GET", "/hangars", headers=headers, params=params)

    def get_hangar(self, hangar_id, headers):
        return self._request("GET", f"/hangars/{hangar_id}", headers=headers)

    def decommission_hangar(self, hangar_id, headers):
        return self._request("POST", f"/hangars/{hangar_id}/decommission", {}, headers)

    # --- Waitlist applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/reject", {}, headers)

    # --- Hangar offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", {}, headers)

    # --- Leases ---
    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def create_payment(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/payments", payload, headers)

    def terminate_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/terminate", payload, headers)

    # --- Lease aircraft ---
    def add_aircraft(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/aircraft", payload, headers)

    def list_aircraft(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/aircraft", headers=headers, params=params)

    def remove_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/aircraft/{aircraft_id}/remove", {}, headers)

    # --- Insurance certificates ---
    def create_insurance_certificate(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/insurance-certificates", payload, headers)

    def list_insurance_certificates(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/insurance-certificates", headers=headers, params=params)

    # --- Environmental compliance records ---
    def create_environmental_record(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/environmental-records", payload, headers)

    def list_environmental_records(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/environmental-records", headers=headers, params=params)

    def approve_environmental_record(self, record_id, payload, headers):
        return self._request("POST", f"/environmental-records/{record_id}/approve", payload, headers)

    def reject_environmental_record(self, record_id, payload, headers):
        return self._request("POST", f"/environmental-records/{record_id}/reject", payload, headers)

    # --- Hangar condition inspections ---
    def create_inspection(self, hangar_id, payload, headers):
        return self._request("POST", f"/hangars/{hangar_id}/inspections", payload, headers)

    def list_hangar_inspections(self, hangar_id, headers, params=None):
        return self._request("GET", f"/hangars/{hangar_id}/inspections", headers=headers, params=params)

    def list_lease_inspections(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/inspections", headers=headers, params=params)

    def close_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/close", payload, headers)

    # --- Use audit findings ---
    def file_audit_finding(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/audit-findings", payload, headers)

    def list_audit_findings(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/audit-findings", headers=headers, params=params)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/audit-findings/{finding_id}", headers=headers)

    def cure_audit_finding(self, finding_id, headers):
        return self._request("POST", f"/audit-findings/{finding_id}/cure", {}, headers)

    # --- Eviction cases ---
    def file_eviction_case(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/eviction-cases", payload, headers)

    def list_lease_eviction_cases(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/eviction-cases", headers=headers, params=params)

    def list_eviction_cases(self, headers, params=None):
        return self._request("GET", "/eviction-cases", headers=headers, params=params)

    def get_eviction_case(self, case_id, headers):
        return self._request("GET", f"/eviction-cases/{case_id}", headers=headers)

    def execute_eviction_case(self, case_id, payload, headers):
        return self._request("POST", f"/eviction-cases/{case_id}/execute", payload, headers)

    # --- Rent charges ---
    def list_rent_charges(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/rent-charges", headers=headers, params=params)

    def get_rent_charge(self, charge_id, headers):
        return self._request("GET", f"/rent-charges/{charge_id}", headers=headers)


api_client = ApiClient()
