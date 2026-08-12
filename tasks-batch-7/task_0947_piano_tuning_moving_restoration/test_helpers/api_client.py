"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Clock and ops ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers, payload=None):
        return self._request("POST", "/_ops/daily-sweep", payload or {}, headers)

    # ---------------- Clients ----------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def update_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}", payload, headers)

    def create_credit_adjustment(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/credit-adjustments", payload, headers
        )

    # ---------------- Locations ----------------
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def update_location(self, location_id, payload, headers):
        return self._request("PATCH", f"/locations/{location_id}", payload, headers)

    # ---------------- Climate readings ----------------
    def create_climate_reading(self, payload, headers):
        return self._request("POST", "/climate-readings", payload, headers)

    def list_climate_readings(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/locations/{location_id}/climate-readings",
            headers=headers, params=params,
        )

    # ---------------- Instruments ----------------
    def create_instrument(self, payload, headers):
        return self._request("POST", "/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/instruments/{instrument_id}", headers=headers)

    def update_instrument(self, instrument_id, payload, headers):
        return self._request("PATCH", f"/instruments/{instrument_id}", payload, headers)

    def create_pitch_assessment(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/instruments/{instrument_id}/pitch-assessments", payload, headers
        )

    def create_custody_transition(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/instruments/{instrument_id}/custody-transitions", payload, headers
        )

    def create_condition_transition(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/instruments/{instrument_id}/condition-transitions", payload, headers
        )

    # ---------------- Tuning recalls ----------------
    def create_tuning_recall(self, payload, headers):
        return self._request("POST", "/tuning-recalls", payload, headers)

    def list_tuning_recalls(self, instrument_id, headers, params=None):
        return self._request(
            "GET", f"/instruments/{instrument_id}/tuning-recalls",
            headers=headers, params=params,
        )

    def notify_tuning_recall(self, recall_id, headers, payload=None):
        return self._request(
            "POST", f"/tuning-recalls/{recall_id}/notify", payload or {}, headers
        )

    # ---------------- Technicians ----------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def update_technician(self, technician_id, payload, headers):
        return self._request("PATCH", f"/technicians/{technician_id}", payload, headers)

    # ---------------- Route days ----------------
    def create_route_day(self, payload, headers):
        return self._request("POST", "/route-days", payload, headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/route-days", headers=headers, params=params)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/route-days/{route_day_id}", headers=headers)

    def create_route_day_status_transition(self, route_day_id, payload, headers):
        return self._request(
            "POST", f"/route-days/{route_day_id}/status-transitions", payload, headers
        )

    # ---------------- Appointments ----------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/confirm", payload or {}, headers
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/reschedule", payload, headers
        )

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", payload or {}, headers
        )

    def start_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/start", payload or {}, headers
        )

    def complete_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/complete", payload or {}, headers
        )

    def no_show_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", payload or {}, headers
        )

    # ---------------- Quotes ----------------
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def issue_quote(self, quote_id, headers, payload=None):
        return self._request("POST", f"/quotes/{quote_id}/issue", payload or {}, headers)

    def approve_quote(self, quote_id, headers, payload=None):
        return self._request("POST", f"/quotes/{quote_id}/approve", payload or {}, headers)

    def decline_quote(self, quote_id, headers, payload=None):
        return self._request("POST", f"/quotes/{quote_id}/decline", payload or {}, headers)

    def reissue_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/reissue", payload, headers)

    # ---------------- Service orders ----------------
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def get_service_order(self, service_order_id, headers):
        return self._request("GET", f"/service-orders/{service_order_id}", headers=headers)

    def start_service_order(self, service_order_id, headers, payload=None):
        return self._request(
            "POST", f"/service-orders/{service_order_id}/start", payload or {}, headers
        )

    def resume_service_order(self, service_order_id, headers, payload=None):
        return self._request(
            "POST", f"/service-orders/{service_order_id}/resume", payload or {}, headers
        )

    def complete_service_order(self, service_order_id, headers, payload=None):
        return self._request(
            "POST", f"/service-orders/{service_order_id}/complete", payload or {}, headers
        )

    def cancel_service_order(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"/service-orders/{service_order_id}/cancel", payload or {}, headers
        )

    def list_service_order_milestones(self, service_order_id, headers, params=None):
        return self._request(
            "GET", f"/service-orders/{service_order_id}/milestones",
            headers=headers, params=params,
        )

    def create_parts_allocation(self, service_order_id, payload, headers):
        return self._request(
            "POST", f"/service-orders/{service_order_id}/parts-allocations", payload, headers
        )

    # ---------------- Milestones ----------------
    def release_milestone(self, milestone_id, headers, payload=None):
        return self._request(
            "POST", f"/milestones/{milestone_id}/release", payload or {}, headers
        )

    def accept_milestone(self, milestone_id, headers, payload=None):
        return self._request(
            "POST", f"/milestones/{milestone_id}/accept", payload or {}, headers
        )

    def reject_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/milestones/{milestone_id}/reject", payload or {}, headers
        )

    # ---------------- Move jobs ----------------
    def create_move_job(self, payload, headers):
        return self._request("POST", "/move-jobs", payload, headers)

    def list_move_jobs(self, headers, params=None):
        return self._request("GET", "/move-jobs", headers=headers, params=params)

    def get_move_job(self, move_job_id, headers):
        return self._request("GET", f"/move-jobs/{move_job_id}", headers=headers)

    def create_move_job_status_transition(self, move_job_id, payload, headers):
        return self._request(
            "POST", f"/move-jobs/{move_job_id}/status-transitions", payload, headers
        )

    # ---------------- Warranties ----------------
    def list_warranties(self, headers, params=None):
        return self._request("GET", "/warranties", headers=headers, params=params)

    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def void_warranty(self, warranty_id, payload, headers):
        return self._request("POST", f"/warranties/{warranty_id}/void", payload, headers)

    # ---------------- Warranty claims ----------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def review_warranty_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/review", payload or {}, headers
        )

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/adjudicate", payload, headers
        )

    # ---------------- Consignment agreements ----------------
    def create_consignment_agreement(self, payload, headers):
        return self._request("POST", "/consignment-agreements", payload, headers)

    def list_consignment_agreements(self, headers, params=None):
        return self._request(
            "GET", "/consignment-agreements", headers=headers, params=params
        )

    def get_consignment_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/consignment-agreements/{agreement_id}", headers=headers
        )

    def activate_consignment_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/consignment-agreements/{agreement_id}/activate",
            payload or {}, headers,
        )

    def list_showroom_consignment_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/consignment-agreements/{agreement_id}/list-showroom",
            payload or {}, headers,
        )

    def record_consignment_sale(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/consignment-agreements/{agreement_id}/record-sale", payload, headers
        )

    def withdraw_consignment_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/consignment-agreements/{agreement_id}/withdraw",
            payload or {}, headers,
        )

    # ---------------- Parts ----------------
    def create_parts_lot(self, payload, headers):
        return self._request("POST", "/parts-lots", payload, headers)

    def get_parts_lot(self, parts_lot_id, headers):
        return self._request("GET", f"/parts-lots/{parts_lot_id}", headers=headers)

    def list_parts_allocations(self, headers, params=None):
        return self._request("GET", "/parts-allocations", headers=headers, params=params)

    def get_parts_allocation(self, allocation_id, headers):
        return self._request("GET", f"/parts-allocations/{allocation_id}", headers=headers)

    def consume_parts_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/parts-allocations/{allocation_id}/consume", payload or {}, headers
        )

    def release_parts_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/parts-allocations/{allocation_id}/release", payload or {}, headers
        )

    # ---------------- Ledger ----------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ---------------- Raw escape hatch ----------------
    def raw(self, method, path, payload=None, headers=None, params=None):
        """Send an arbitrary request; used by auth-header tests that must omit headers."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
