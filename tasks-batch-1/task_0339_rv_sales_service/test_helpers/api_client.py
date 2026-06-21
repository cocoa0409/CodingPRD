"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- deterministic clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---- Dealership ----
    def create_dealership(self, payload, headers):
        return self._request("POST", "/dealerships", payload, headers=headers)

    def list_dealerships(self, headers, params=None):
        return self._request("GET", "/dealerships", headers=headers, params=params)

    def get_dealership(self, dealership_id, headers):
        return self._request("GET", f"/dealerships/{dealership_id}", headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Unit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def return_consignment(self, unit_id, headers, payload=None):
        return self._request("POST", f"/units/{unit_id}/return-consignment", payload or {}, headers=headers)

    # ---- Deal ----
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def get_equity_summary(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}/equity-summary", headers=headers)

    def quote_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/quote", payload or {}, headers=headers)

    def request_finance(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/request-finance", payload or {}, headers=headers)

    def finance_decision(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/finance-decision", payload, headers=headers)

    def start_pdi(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/start-pdi", payload or {}, headers=headers)

    def deliver_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/deliver", payload or {}, headers=headers)

    def cancel_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/cancel", payload or {}, headers=headers)

    def appraise_trade(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/appraise-trade", payload, headers=headers)

    # ---- PdiInspection ----
    def create_pdi_inspection(self, payload, headers):
        return self._request("POST", "/pdi-inspections", payload, headers=headers)

    def list_pdi_inspections(self, headers, params=None):
        return self._request("GET", "/pdi-inspections", headers=headers, params=params)

    def get_pdi_inspection(self, pdi_id, headers):
        return self._request("GET", f"/pdi-inspections/{pdi_id}", headers=headers)

    # ---- ServiceBay ----
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/service-bays", payload, headers=headers)

    def list_service_bays(self, headers, params=None):
        return self._request("GET", "/service-bays", headers=headers, params=params)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"/service-bays/{bay_id}", headers=headers)

    # ---- ServiceOrder ----
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def get_service_order(self, so_id, headers):
        return self._request("GET", f"/service-orders/{so_id}", headers=headers)

    def start_service_order(self, so_id, headers, payload=None):
        return self._request("POST", f"/service-orders/{so_id}/start", payload or {}, headers=headers)

    def await_parts(self, so_id, headers, payload=None):
        return self._request("POST", f"/service-orders/{so_id}/await-parts", payload or {}, headers=headers)

    def resume_service_order(self, so_id, headers, payload=None):
        return self._request("POST", f"/service-orders/{so_id}/resume", payload or {}, headers=headers)

    def complete_service_order(self, so_id, headers, payload=None):
        return self._request("POST", f"/service-orders/{so_id}/complete", payload or {}, headers=headers)

    def cancel_service_order(self, so_id, headers, payload=None):
        return self._request("POST", f"/service-orders/{so_id}/cancel", payload or {}, headers=headers)

    # ---- PartReservation ----
    def create_part_reservation(self, payload, headers):
        return self._request("POST", "/part-reservations", payload, headers=headers)

    def list_part_reservations(self, headers, params=None):
        return self._request("GET", "/part-reservations", headers=headers, params=params)

    def get_part_reservation(self, res_id, headers):
        return self._request("GET", f"/part-reservations/{res_id}", headers=headers)

    # ---- PartItem ----
    def create_part_item(self, payload, headers):
        return self._request("POST", "/part-items", payload, headers=headers)

    def list_part_items(self, headers, params=None):
        return self._request("GET", "/part-items", headers=headers, params=params)

    def get_part_item(self, part_id, headers):
        return self._request("GET", f"/part-items/{part_id}", headers=headers)

    # ---- WarrantyPlan ----
    def create_warranty_plan(self, payload, headers):
        return self._request("POST", "/warranty-plans", payload, headers=headers)

    def list_warranty_plans(self, headers, params=None):
        return self._request("GET", "/warranty-plans", headers=headers, params=params)

    def get_warranty_plan(self, plan_id, headers):
        return self._request("GET", f"/warranty-plans/{plan_id}", headers=headers)

    def cancel_warranty_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/warranty-plans/{plan_id}/cancel", payload or {}, headers=headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appt_id, headers):
        return self._request("GET", f"/appointments/{appt_id}", headers=headers)

    def check_in_appointment(self, appt_id, headers, payload=None):
        return self._request("POST", f"/appointments/{appt_id}/check-in", payload or {}, headers=headers)

    def close_appointment(self, appt_id, headers, payload=None):
        return self._request("POST", f"/appointments/{appt_id}/close", payload or {}, headers=headers)

    def cancel_appointment(self, appt_id, headers, payload=None):
        return self._request("POST", f"/appointments/{appt_id}/cancel", payload or {}, headers=headers)

    # ---- StorageSlot ----
    def create_storage_slot(self, payload, headers):
        return self._request("POST", "/storage-slots", payload, headers=headers)

    def list_storage_slots(self, headers, params=None):
        return self._request("GET", "/storage-slots", headers=headers, params=params)

    def get_storage_slot(self, slot_id, headers):
        return self._request("GET", f"/storage-slots/{slot_id}", headers=headers)

    def activate_storage_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"/storage-slots/{slot_id}/activate", payload or {}, headers=headers)

    def release_storage_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/storage-slots/{slot_id}/release", payload, headers=headers)

    def cancel_storage_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"/storage-slots/{slot_id}/cancel", payload or {}, headers=headers)

    # ---- RecallCampaign / RecallRemedy ----
    def create_recall_campaign(self, payload, headers):
        return self._request("POST", "/recall-campaigns", payload, headers=headers)

    def list_recall_campaigns(self, headers, params=None):
        return self._request("GET", "/recall-campaigns", headers=headers, params=params)

    def get_recall_campaign(self, rc_id, headers):
        return self._request("GET", f"/recall-campaigns/{rc_id}", headers=headers)

    def close_recall_campaign(self, rc_id, headers, payload=None):
        return self._request("POST", f"/recall-campaigns/{rc_id}/close", payload or {}, headers=headers)

    def list_recall_remedies(self, headers, params=None):
        return self._request("GET", "/recall-remedies", headers=headers, params=params)

    def get_recall_remedy(self, remedy_id, headers):
        return self._request("GET", f"/recall-remedies/{remedy_id}", headers=headers)


api_client = ApiClient()
