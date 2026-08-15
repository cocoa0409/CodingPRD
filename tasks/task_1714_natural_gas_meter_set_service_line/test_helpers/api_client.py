"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.9)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------
    def create_builder(self, payload, headers):
        return self._request("POST", "/builders", payload, headers)

    def get_builder(self, builder_id, headers):
        return self._request("GET", f"/builders/{builder_id}", headers=headers)

    def list_builders(self, headers, params=None):
        return self._request("GET", "/builders", headers=headers, params=params)

    def patch_builder(self, builder_id, payload, headers):
        return self._request("PATCH", f"/builders/{builder_id}", payload, headers)

    # ------------------------------------------------------------------
    # Service applications
    # ------------------------------------------------------------------
    def create_service_application(self, payload, headers):
        return self._request("POST", "/service-applications", payload, headers)

    def get_service_application(self, app_id, headers):
        return self._request("GET", f"/service-applications/{app_id}", headers=headers)

    def list_service_applications(self, headers, params=None):
        return self._request("GET", "/service-applications", headers=headers, params=params)

    def patch_service_application(self, app_id, payload, headers):
        return self._request("PATCH", f"/service-applications/{app_id}", payload, headers)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"/service-applications/{app_id}/submit", {}, headers)

    def confirm_load(self, app_id, headers):
        return self._request("POST", f"/service-applications/{app_id}/confirm-load", {}, headers)

    def reject_application(self, app_id, payload, headers):
        return self._request("POST", f"/service-applications/{app_id}/reject", payload, headers)

    def schedule_construction(self, app_id, headers):
        return self._request(
            "POST", f"/service-applications/{app_id}/schedule-construction", {}, headers
        )

    def energize_application(self, app_id, headers):
        return self._request("POST", f"/service-applications/{app_id}/energize", {}, headers)

    def complete_application(self, app_id, headers):
        return self._request("POST", f"/service-applications/{app_id}/complete", {}, headers)

    def hold_application(self, app_id, payload, headers):
        return self._request("POST", f"/service-applications/{app_id}/hold", payload, headers)

    def resume_application(self, app_id, headers):
        return self._request("POST", f"/service-applications/{app_id}/resume", {}, headers)

    def cancel_application(self, app_id, headers):
        return self._request("POST", f"/service-applications/{app_id}/cancel", {}, headers)

    def get_readiness(self, app_id, headers):
        return self._request(
            "GET", f"/service-applications/{app_id}/readiness", headers=headers
        )

    # ------------------------------------------------------------------
    # Appliance loads
    # ------------------------------------------------------------------
    def create_appliance_load(self, payload, headers):
        return self._request("POST", "/appliance-loads", payload, headers)

    def get_appliance_load(self, load_id, headers):
        return self._request("GET", f"/appliance-loads/{load_id}", headers=headers)

    def list_appliance_loads(self, headers, params=None):
        return self._request("GET", "/appliance-loads", headers=headers, params=params)

    def patch_appliance_load(self, load_id, payload, headers):
        return self._request("PATCH", f"/appliance-loads/{load_id}", payload, headers)

    def delete_appliance_load(self, load_id, headers):
        return self._request("DELETE", f"/appliance-loads/{load_id}", headers=headers)

    # ------------------------------------------------------------------
    # Main extensions
    # ------------------------------------------------------------------
    def create_main_extension(self, payload, headers):
        return self._request("POST", "/main-extensions", payload, headers)

    def get_main_extension(self, me_id, headers):
        return self._request("GET", f"/main-extensions/{me_id}", headers=headers)

    def list_main_extensions(self, headers, params=None):
        return self._request("GET", "/main-extensions", headers=headers, params=params)

    def submit_design(self, me_id, headers):
        return self._request("POST", f"/main-extensions/{me_id}/submit-design", {}, headers)

    def approve_design(self, me_id, headers):
        return self._request("POST", f"/main-extensions/{me_id}/approve-design", {}, headers)

    def accept_quote(self, me_id, headers):
        return self._request("POST", f"/main-extensions/{me_id}/accept-quote", {}, headers)

    def revise_design(self, me_id, payload, headers):
        return self._request("POST", f"/main-extensions/{me_id}/revise", payload, headers)

    def record_as_built(self, me_id, payload, headers):
        return self._request("POST", f"/main-extensions/{me_id}/record-as-built", payload, headers)

    def finalize_main_extension(self, me_id, headers):
        return self._request("POST", f"/main-extensions/{me_id}/finalize", {}, headers)

    # ------------------------------------------------------------------
    # CIAC invoices / payment events
    # ------------------------------------------------------------------
    def get_ciac_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ciac-invoices/{invoice_id}", headers=headers)

    def list_ciac_invoices(self, headers, params=None):
        return self._request("GET", "/ciac-invoices", headers=headers, params=params)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/ciac-invoices/{invoice_id}/payments", payload, headers)

    def record_refund(self, invoice_id, payload, headers):
        return self._request("POST", f"/ciac-invoices/{invoice_id}/refunds", payload, headers)

    def get_ciac_payment(self, payment_id, headers):
        return self._request("GET", f"/ciac-payments/{payment_id}", headers=headers)

    def list_ciac_payments(self, headers, params=None):
        return self._request("GET", "/ciac-payments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def file_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/file", {}, headers)

    def record_permit_decision(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/record-decision", payload, headers
        )

    def amend_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/amend", payload, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Field crews / crew bookings
    # ------------------------------------------------------------------
    def create_field_crew(self, payload, headers):
        return self._request("POST", "/field-crews", payload, headers)

    def get_field_crew(self, crew_id, headers):
        return self._request("GET", f"/field-crews/{crew_id}", headers=headers)

    def list_field_crews(self, headers, params=None):
        return self._request("GET", "/field-crews", headers=headers, params=params)

    def create_crew_booking(self, payload, headers):
        return self._request("POST", "/crew-bookings", payload, headers)

    def get_crew_booking(self, booking_id, headers):
        return self._request("GET", f"/crew-bookings/{booking_id}", headers=headers)

    def list_crew_bookings(self, headers, params=None):
        return self._request("GET", "/crew-bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/crew-bookings/{booking_id}/confirm", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/crew-bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/crew-bookings/{booking_id}/cancel", {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/crew-bookings/{booking_id}/reschedule", payload, headers)

    # ------------------------------------------------------------------
    # Inspectors / inspections
    # ------------------------------------------------------------------
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/record-result", payload, headers
        )

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", {}, headers)

    def reschedule_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/reschedule", payload, headers
        )

    # ------------------------------------------------------------------
    # Meter sets / purge & leak tests
    # ------------------------------------------------------------------
    def create_meter_set(self, payload, headers):
        return self._request("POST", "/meter-sets", payload, headers)

    def get_meter_set(self, meter_set_id, headers):
        return self._request("GET", f"/meter-sets/{meter_set_id}", headers=headers)

    def list_meter_sets(self, headers, params=None):
        return self._request("GET", "/meter-sets", headers=headers, params=params)

    def size_meter_set(self, meter_set_id, headers):
        return self._request("POST", f"/meter-sets/{meter_set_id}/size", {}, headers)

    def mark_meter_ordered(self, meter_set_id, payload, headers):
        return self._request(
            "POST", f"/meter-sets/{meter_set_id}/mark-ordered", payload, headers
        )

    def install_meter_set(self, meter_set_id, headers):
        return self._request("POST", f"/meter-sets/{meter_set_id}/install", {}, headers)

    def mark_meter_repaired(self, meter_set_id, headers):
        return self._request("POST", f"/meter-sets/{meter_set_id}/mark-repaired", {}, headers)

    def create_purge_leak_test(self, payload, headers):
        return self._request("POST", "/purge-leak-tests", payload, headers)

    def get_purge_leak_test(self, test_id, headers):
        return self._request("GET", f"/purge-leak-tests/{test_id}", headers=headers)

    def list_purge_leak_tests(self, headers, params=None):
        return self._request("GET", "/purge-leak-tests", headers=headers, params=params)

    def certify_purge_leak_test(self, test_id, headers):
        return self._request("POST", f"/purge-leak-tests/{test_id}/certify", {}, headers)

    def reject_purge_leak_test(self, test_id, payload, headers):
        return self._request("POST", f"/purge-leak-tests/{test_id}/reject", payload, headers)

    # ------------------------------------------------------------------
    # Turn-on events
    # ------------------------------------------------------------------
    def create_turn_on_event(self, payload, headers):
        return self._request("POST", "/turn-on-events", payload, headers)

    def get_turn_on_event(self, event_id, headers):
        return self._request("GET", f"/turn-on-events/{event_id}", headers=headers)

    def list_turn_on_events(self, headers, params=None):
        return self._request("GET", "/turn-on-events", headers=headers, params=params)

    def complete_turn_on_event(self, event_id, payload, headers):
        return self._request("POST", f"/turn-on-events/{event_id}/complete", payload, headers)

    def retry_turn_on_event(self, event_id, headers):
        return self._request("POST", f"/turn-on-events/{event_id}/retry", {}, headers)

    # ------------------------------------------------------------------
    # Timeline commitments
    # ------------------------------------------------------------------
    def get_timeline_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"/timeline-commitments/{commitment_id}", headers=headers
        )

    def list_timeline_commitments(self, headers, params=None):
        return self._request("GET", "/timeline-commitments", headers=headers, params=params)

    def accept_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/timeline-commitments/{commitment_id}/accept", {}, headers
        )

    def propose_commitment_revision(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/timeline-commitments/{commitment_id}/propose-revision", payload, headers
        )

    def respond_commitment_revision(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/timeline-commitments/{commitment_id}/respond-revision", payload, headers
        )

    def mark_commitment_delayed(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"/timeline-commitments/{commitment_id}/mark-delayed", payload, headers
        )

    # ------------------------------------------------------------------
    # GIS as-builts
    # ------------------------------------------------------------------
    def create_gis_as_built(self, payload, headers):
        return self._request("POST", "/gis-as-builts", payload, headers)

    def get_gis_as_built(self, gis_id, headers):
        return self._request("GET", f"/gis-as-builts/{gis_id}", headers=headers)

    def list_gis_as_builts(self, headers, params=None):
        return self._request("GET", "/gis-as-builts", headers=headers, params=params)

    def validate_gis(self, gis_id, headers):
        return self._request("POST", f"/gis-as-builts/{gis_id}/validate", {}, headers)

    def reject_gis(self, gis_id, payload, headers):
        return self._request("POST", f"/gis-as-builts/{gis_id}/reject", payload, headers)

    def resubmit_gis(self, gis_id, payload, headers):
        return self._request("POST", f"/gis-as-builts/{gis_id}/resubmit", payload, headers)


api_client = ApiClient()
