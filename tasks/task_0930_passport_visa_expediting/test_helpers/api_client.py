"""API client: one method per endpoint defined in the PRD.

Every endpoint is mounted under the ``/expediting`` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/expediting"


class ApiClient(GenericApiClient):
    # ---------------- catalogue ----------------
    def create_catalog_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/catalog-items", payload, headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/catalog-items", headers=headers, params=params)

    def get_catalog_item(self, catalog_item_id, headers):
        return self._request("GET", f"{PREFIX}/catalog-items/{catalog_item_id}", headers=headers)

    def create_document_requirement(self, catalog_item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/catalog-items/{catalog_item_id}/document-requirements", payload, headers
        )

    def list_document_requirements(self, catalog_item_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/catalog-items/{catalog_item_id}/document-requirements",
            headers=headers,
            params=params,
        )

    # ---------------- agency forms ----------------
    def create_agency_form(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agency-forms", payload, headers)

    def list_agency_forms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agency-forms", headers=headers, params=params)

    def get_agency_form(self, agency_form_id, headers):
        return self._request("GET", f"{PREFIX}/agency-forms/{agency_form_id}", headers=headers)

    def publish_agency_form(self, agency_form_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/agency-forms/{agency_form_id}/publish", payload or {}, headers
        )

    def list_agency_form_prepared_forms(self, agency_form_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agency-forms/{agency_form_id}/prepared-forms", headers=headers, params=params
        )

    # ---------------- consulates and slots ----------------
    def create_consulate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consulates", payload, headers)

    def list_consulates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/consulates", headers=headers, params=params)

    def get_consulate(self, consulate_id, headers):
        return self._request("GET", f"{PREFIX}/consulates/{consulate_id}", headers=headers)

    def add_consulate_closure(self, consulate_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consulates/{consulate_id}/closures", payload, headers)

    def create_slot(self, consulate_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consulates/{consulate_id}/slots", payload, headers)

    def list_consulate_slots(self, consulate_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consulates/{consulate_id}/slots", headers=headers, params=params
        )

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/slots/{slot_id}", headers=headers)

    # ---------------- orders ----------------
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def create_applicant(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/applicants", payload, headers)

    def list_order_applicants(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/applicants", headers=headers, params=params
        )

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    def quote_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/quote", payload, headers)

    def accept_quote(self, order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/accept-quote", payload or {}, headers)

    def create_payment(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/payments", payload, headers)

    def list_ledger_entries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/ledger-entries", headers=headers, params=params
        )

    def change_service_level(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/service-level", payload, headers)

    def change_travel_dates(self, order_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/orders/{order_id}/travel-dates", payload, headers)

    def get_feasibility(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}/feasibility", headers=headers)

    def acknowledge_feasibility(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/feasibility-acknowledgment", payload or {}, headers
        )

    def submit_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/submit", payload or {}, headers)

    def split_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/split", payload, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/cancel", payload or {}, headers)

    def get_order_summary(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}/summary", headers=headers)

    def tender_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/tender", payload or {}, headers)

    # ---------------- documents ----------------
    def submit_document(self, applicant_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants/{applicant_id}/documents", payload, headers)

    def list_applicant_documents(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applicants/{applicant_id}/documents", headers=headers, params=params
        )

    def get_document(self, document_id, headers):
        return self._request("GET", f"{PREFIX}/documents/{document_id}", headers=headers)

    def review_document(self, document_id, payload, headers):
        return self._request("POST", f"{PREFIX}/documents/{document_id}/review", payload, headers)

    def resubmit_document(self, document_id, payload, headers):
        return self._request("POST", f"{PREFIX}/documents/{document_id}/resubmit", payload, headers)

    def get_required_documents(self, applicant_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applicants/{applicant_id}/required-documents", headers=headers
        )

    # ---------------- photos ----------------
    def upload_photo(self, applicant_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants/{applicant_id}/photos", payload, headers)

    def list_applicant_photos(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applicants/{applicant_id}/photos", headers=headers, params=params
        )

    def run_compliance_check(self, photo_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/photos/{photo_id}/compliance-check", payload or {}, headers
        )

    def retake_photo(self, photo_id, payload, headers):
        return self._request("POST", f"{PREFIX}/photos/{photo_id}/retake", payload, headers)

    # ---------------- prepared forms ----------------
    def create_prepared_form(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applicants/{applicant_id}/prepared-forms", payload, headers
        )

    def list_applicant_prepared_forms(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applicants/{applicant_id}/prepared-forms", headers=headers, params=params
        )

    def sign_prepared_form(self, prepared_form_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/prepared-forms/{prepared_form_id}/sign", payload or {}, headers
        )

    # ---------------- appointments ----------------
    def create_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"{PREFIX}/appointments/{appointment_id}", headers=headers)

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/appointments/{appointment_id}/reschedule", payload, headers
        )

    def record_appointment_outcome(self, appointment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments/{appointment_id}/outcome", payload, headers)

    # ---------------- courier legs and custody ----------------
    def create_courier_leg(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/courier-legs", payload, headers)

    def list_courier_legs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/courier-legs", headers=headers, params=params
        )

    def dispatch_courier_leg(self, courier_leg_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/courier-legs/{courier_leg_id}/dispatch", payload or {}, headers
        )

    def complete_courier_leg(self, courier_leg_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/courier-legs/{courier_leg_id}/complete", payload, headers
        )

    def list_custody_events(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/custody-events", headers=headers, params=params
        )

    # ---------------- evidence requests ----------------
    def create_rfe(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/rfes", payload, headers)

    def list_rfes(self, order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders/{order_id}/rfes", headers=headers, params=params)

    def respond_to_rfe(self, rfe_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/rfes/{rfe_id}/respond", payload or {}, headers)

    def adjudicate_rfe(self, rfe_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rfes/{rfe_id}/adjudicate", payload, headers)

    # ---------------- decision, shipments, delivery ----------------
    def record_agency_decision(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/agency-decision", payload, headers)

    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/shipments", payload, headers)

    def list_shipments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/shipments", headers=headers, params=params
        )

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def record_delivery_attempt(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/delivery-attempt", payload, headers
        )

    def change_shipment_address(self, shipment_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/shipments/{shipment_id}/address", payload, headers)

    def record_pickup(self, shipment_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/shipments/{shipment_id}/pickup", payload or {}, headers)

    # ---------------- SLA and clock ----------------
    def list_sla_segments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/sla-segments", headers=headers, params=params
        )

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---------------- raw escape hatch for header-shape tests ----------------
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
