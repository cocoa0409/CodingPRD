"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (PRD §2.4) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ---- ContractedFacility ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/api/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/api/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/api/facilities/{facility_id}", headers=headers)

    # ---- MobileImagingUnit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/api/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/api/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/api/units/{unit_id}", headers=headers)

    def send_unit_to_maintenance(self, unit_id, headers):
        return self._request("POST", f"/api/units/{unit_id}/maintenance", {}, headers)

    def return_unit_to_service(self, unit_id, headers):
        return self._request("POST", f"/api/units/{unit_id}/return-to-service", {}, headers)

    # ---- ServiceContract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def get_period_invoice(self, contract_id, month, headers):
        return self._request(
            "GET",
            f"/api/contracts/{contract_id}/period-invoice",
            headers=headers,
            params={"month": month},
        )

    # ---- RoutePlan ----
    def create_route_plan(self, payload, headers):
        return self._request("POST", "/api/route-plans", payload, headers)

    def list_route_plans(self, headers, params=None):
        return self._request("GET", "/api/route-plans", headers=headers, params=params)

    def get_route_plan(self, plan_id, headers):
        return self._request("GET", f"/api/route-plans/{plan_id}", headers=headers)

    def publish_route_plan(self, plan_id, headers):
        return self._request("POST", f"/api/route-plans/{plan_id}/publish", {}, headers)

    def unpublish_route_plan(self, plan_id, headers):
        return self._request("POST", f"/api/route-plans/{plan_id}/unpublish", {}, headers)

    def lock_route_plan(self, plan_id, headers):
        return self._request("POST", f"/api/route-plans/{plan_id}/lock", {}, headers)

    def close_route_plan(self, plan_id, headers):
        return self._request("POST", f"/api/route-plans/{plan_id}/close", {}, headers)

    # ---- SiteDayAssignment ----
    def create_site_day(self, payload, headers):
        return self._request("POST", "/api/site-days", payload, headers)

    def list_site_days(self, headers, params=None):
        return self._request("GET", "/api/site-days", headers=headers, params=params)

    def get_site_day(self, site_day_id, headers):
        return self._request("GET", f"/api/site-days/{site_day_id}", headers=headers)

    def depart_site_day(self, site_day_id, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/depart", {}, headers)

    def begin_setup_site_day(self, site_day_id, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/begin-setup", {}, headers)

    def mark_ready_site_day(self, site_day_id, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/mark-ready", {}, headers)

    def start_service_site_day(self, site_day_id, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/start-service", {}, headers)

    def complete_site_day(self, site_day_id, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/complete", {}, headers)

    def cancel_site_day(self, site_day_id, payload, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/cancel", payload, headers)

    def interrupt_site_day(self, site_day_id, payload, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/interrupt", payload, headers)

    def reschedule_site_day(self, site_day_id, payload, headers):
        return self._request("POST", f"/api/site-days/{site_day_id}/reschedule", payload, headers)

    # ---- PatientAppointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/api/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/api/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/api/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/confirm", {}, headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/check-in", {}, headers)

    def begin_scan_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/begin-scan", {}, headers)

    def complete_scan_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/complete-scan", {}, headers)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/cancel", payload, headers)

    def mark_no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/mark-no-show", {}, headers)

    # ---- Technologist ----
    def create_technologist(self, payload, headers):
        return self._request("POST", "/api/technologists", payload, headers)

    def list_technologists(self, headers, params=None):
        return self._request("GET", "/api/technologists", headers=headers, params=params)

    def get_technologist(self, technologist_id, headers):
        return self._request("GET", f"/api/technologists/{technologist_id}", headers=headers)

    # ---- StaffingAssignment ----
    def create_staffing_assignment(self, payload, headers):
        return self._request("POST", "/api/staffing-assignments", payload, headers)

    def list_staffing_assignments(self, headers, params=None):
        return self._request("GET", "/api/staffing-assignments", headers=headers, params=params)

    def get_staffing_assignment(self, staffing_id, headers):
        return self._request("GET", f"/api/staffing-assignments/{staffing_id}", headers=headers)

    def release_staffing_assignment(self, staffing_id, payload, headers):
        return self._request(
            "POST", f"/api/staffing-assignments/{staffing_id}/release", payload, headers
        )

    # ---- TransportLeg ----
    def create_transport_leg(self, payload, headers):
        return self._request("POST", "/api/transport-legs", payload, headers)

    def list_transport_legs(self, headers, params=None):
        return self._request("GET", "/api/transport-legs", headers=headers, params=params)

    def get_transport_leg(self, leg_id, headers):
        return self._request("GET", f"/api/transport-legs/{leg_id}", headers=headers)

    def arrive_transport_leg(self, leg_id, headers):
        return self._request("POST", f"/api/transport-legs/{leg_id}/arrive", {}, headers)

    # ---- SetupChecklist ----
    def create_setup_checklist(self, payload, headers):
        return self._request("POST", "/api/setup-checklists", payload, headers)

    def list_setup_checklists(self, headers, params=None):
        return self._request("GET", "/api/setup-checklists", headers=headers, params=params)

    def get_setup_checklist(self, checklist_id, headers):
        return self._request("GET", f"/api/setup-checklists/{checklist_id}", headers=headers)

    def record_checklist_item(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/api/setup-checklists/{checklist_id}/record-item", payload, headers
        )

    # ---- BreakdownEvent ----
    def create_breakdown(self, payload, headers):
        return self._request("POST", "/api/breakdowns", payload, headers)

    def list_breakdowns(self, headers, params=None):
        return self._request("GET", "/api/breakdowns", headers=headers, params=params)

    def get_breakdown(self, breakdown_id, headers):
        return self._request("GET", f"/api/breakdowns/{breakdown_id}", headers=headers)

    def resolve_breakdown(self, breakdown_id, payload, headers):
        return self._request("POST", f"/api/breakdowns/{breakdown_id}/resolve", payload, headers)

    # ---- RadiationDoseRecord ----
    def create_dose_record(self, payload, headers):
        return self._request("POST", "/api/dose-records", payload, headers)

    def list_dose_records(self, headers, params=None):
        return self._request("GET", "/api/dose-records", headers=headers, params=params)

    def get_dose_record(self, dose_record_id, headers):
        return self._request("GET", f"/api/dose-records/{dose_record_id}", headers=headers)

    # ---- AccreditationRecord ----
    def create_accreditation(self, payload, headers):
        return self._request("POST", "/api/accreditations", payload, headers)

    def list_accreditations(self, headers, params=None):
        return self._request("GET", "/api/accreditations", headers=headers, params=params)

    def get_accreditation(self, accreditation_id, headers):
        return self._request("GET", f"/api/accreditations/{accreditation_id}", headers=headers)

    def suspend_accreditation(self, accreditation_id, payload, headers):
        return self._request(
            "POST", f"/api/accreditations/{accreditation_id}/suspend", payload, headers
        )

    def reinstate_accreditation(self, accreditation_id, headers):
        return self._request(
            "POST", f"/api/accreditations/{accreditation_id}/reinstate", {}, headers
        )

    # ---- BillingStatement ----
    def list_billing_statements(self, headers, params=None):
        return self._request("GET", "/api/billing-statements", headers=headers, params=params)

    def get_billing_statement(self, statement_id, headers):
        return self._request("GET", f"/api/billing-statements/{statement_id}", headers=headers)

    def finalize_billing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/billing-statements/{statement_id}/finalize", {}, headers
        )

    def dispute_billing_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-statements/{statement_id}/dispute", payload, headers
        )

    def resolve_dispute_billing_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-statements/{statement_id}/resolve-dispute", payload, headers
        )

    def invoice_billing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/billing-statements/{statement_id}/invoice", {}, headers
        )

    def mark_paid_billing_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/api/billing-statements/{statement_id}/mark-paid", payload, headers
        )

    # ---- ImageStudy ----
    def create_image_study(self, payload, headers):
        return self._request("POST", "/api/image-studies", payload, headers)

    def list_image_studies(self, headers, params=None):
        return self._request("GET", "/api/image-studies", headers=headers, params=params)

    def get_image_study(self, study_id, headers):
        return self._request("GET", f"/api/image-studies/{study_id}", headers=headers)

    def transmit_image_study(self, study_id, headers):
        return self._request("POST", f"/api/image-studies/{study_id}/transmit", {}, headers)

    def retry_image_study(self, study_id, headers):
        return self._request("POST", f"/api/image-studies/{study_id}/retry", {}, headers)

    def acknowledge_image_study(self, study_id, payload, headers):
        return self._request("POST", f"/api/image-studies/{study_id}/acknowledge", payload, headers)


api_client = ApiClient()
