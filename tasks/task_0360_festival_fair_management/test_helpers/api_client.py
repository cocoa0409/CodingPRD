"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Festival lifecycle ----
    def create_festival(self, payload, headers):
        return self._request("POST", "/festivals", payload, headers)

    def get_festival(self, festival_id, headers):
        return self._request("GET", f"/festivals/{festival_id}", headers=headers)

    def list_festivals(self, headers, params=None):
        return self._request("GET", "/festivals", headers=headers, params=params)

    def open_sales(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/open-sales", {}, headers)

    def go_live(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/go-live", {}, headers)

    def open_day(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/open-day", payload, headers)

    def weather_hold(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/weather-hold", {}, headers)

    def resume_festival(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/resume", {}, headers)

    def cancel_festival(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/cancel", {}, headers)

    def close_festival(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/close", {}, headers)

    def get_sales_report(self, festival_id, headers):
        return self._request("GET", f"/festivals/{festival_id}/sales-report", headers=headers)

    # ---- Zones / Stages / Lots / Areas ----
    def create_zone(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/zones", payload, headers)

    def list_zones(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def create_stage(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/stages", payload, headers)

    def list_stages(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/stages", headers=headers, params=params)

    def get_stage(self, stage_id, headers):
        return self._request("GET", f"/stages/{stage_id}", headers=headers)

    def create_parking_lot(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/parking-lots", payload, headers)

    def list_parking_lots(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/parking-lots", headers=headers, params=params)

    def get_parking_lot(self, lot_id, headers):
        return self._request("GET", f"/parking-lots/{lot_id}", headers=headers)

    def create_camping_area(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/camping-areas", payload, headers)

    def list_camping_areas(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/camping-areas", headers=headers, params=params)

    def get_camping_area(self, area_id, headers):
        return self._request("GET", f"/camping-areas/{area_id}", headers=headers)

    # ---- Performances ----
    def create_performance(self, stage_id, payload, headers):
        return self._request("POST", f"/stages/{stage_id}/performances", payload, headers)

    def list_stage_performances(self, stage_id, headers, params=None):
        return self._request("GET", f"/stages/{stage_id}/performances", headers=headers, params=params)

    def list_performances(self, headers, params=None):
        return self._request("GET", "/performances", headers=headers, params=params)

    def get_performance(self, performance_id, headers):
        return self._request("GET", f"/performances/{performance_id}", headers=headers)

    # ---- Tickets / Add-ons / Refunds ----
    def create_ticket(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/tickets", payload, headers)

    def list_festival_tickets(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def refund_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/refund", {}, headers)

    def create_addon(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/add-ons", payload, headers)

    def list_ticket_addons(self, ticket_id, headers, params=None):
        return self._request("GET", f"/tickets/{ticket_id}/add-ons", headers=headers, params=params)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/add-ons/{addon_id}", headers=headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_festival_refunds(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/refunds", headers=headers, params=params)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    # ---- Wristbands / Wallet ----
    def create_wristband(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/wristbands", payload, headers)

    def list_festival_wristbands(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/wristbands", headers=headers, params=params)

    def get_wristband(self, wristband_id, headers):
        return self._request("GET", f"/wristbands/{wristband_id}", headers=headers)

    def activate_wristband(self, wristband_id, payload, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/activate", payload, headers)

    def topup_wristband(self, wristband_id, payload, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/topup", payload, headers)

    def spend_wristband(self, wristband_id, payload, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/spend", payload, headers)

    def freeze_wristband(self, wristband_id, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/freeze", {}, headers)

    def unfreeze_wristband(self, wristband_id, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/unfreeze", {}, headers)

    def cashout_wristband(self, wristband_id, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/cashout", {}, headers)

    def void_wristband(self, wristband_id, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/void", {}, headers)

    def list_wristband_wallet_txns(self, wristband_id, headers, params=None):
        return self._request("GET", f"/wristbands/{wristband_id}/wallet-txns", headers=headers, params=params)

    def list_wallet_txns(self, headers, params=None):
        return self._request("GET", "/wallet-txns", headers=headers, params=params)

    def get_wallet_txn(self, txn_id, headers):
        return self._request("GET", f"/wallet-txns/{txn_id}", headers=headers)

    # ---- Gate scans ----
    def gate_scan(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/gate-scan", payload, headers)

    def list_festival_gate_events(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/gate-events", headers=headers, params=params)

    def list_gate_events(self, headers, params=None):
        return self._request("GET", "/gate-events", headers=headers, params=params)

    def get_gate_event(self, event_id, headers):
        return self._request("GET", f"/gate-events/{event_id}", headers=headers)

    # ---- Vendors / Applications ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def create_vendor_application(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/vendor-applications", payload, headers)

    def list_festival_vendor_applications(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/vendor-applications", headers=headers, params=params)

    def get_vendor_application(self, application_id, headers):
        return self._request("GET", f"/vendor-applications/{application_id}", headers=headers)

    def list_vendor_applications(self, headers, params=None):
        return self._request("GET", "/vendor-applications", headers=headers, params=params)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/start-review", {}, headers)

    def approve_application(self, application_id, payload, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/approve", payload, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/reject", {}, headers)

    def return_for_revision(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/return-for-revision", {}, headers)

    def pay_fee(self, application_id, payload, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/pay-fee", payload, headers)

    def confirm_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/confirm", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/withdraw", {}, headers)

    def settle_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/settle", {}, headers)

    # ---- Incidents ----
    def create_incident(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/incidents", payload, headers)

    def list_festival_incidents(self, festival_id, headers, params=None):
        return self._request("GET", f"/festivals/{festival_id}/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/escalate", {}, headers)

    def deescalate_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/deescalate", {}, headers)

    def resolve_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/resolve", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
