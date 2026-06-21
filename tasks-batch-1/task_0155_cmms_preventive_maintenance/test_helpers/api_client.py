"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Site ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    # --- SparePart ---
    def create_spare_part(self, payload, headers):
        return self._request("POST", "/spare-parts", payload, headers)

    def get_spare_part(self, part_id, headers):
        return self._request("GET", f"/spare-parts/{part_id}", headers=headers)

    def list_spare_parts(self, headers, params=None):
        return self._request("GET", "/spare-parts", headers=headers, params=params)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, tech_id, headers):
        return self._request("GET", f"/technicians/{tech_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    # --- Asset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def retire_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/retire", payload, headers
        )

    # --- MeterReading (sub-resource of Asset) ---
    def create_meter_reading(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/meter-readings", payload, headers
        )

    def list_meter_readings(self, asset_id, headers, params=None):
        return self._request(
            "GET", f"/assets/{asset_id}/meter-readings", headers=headers, params=params
        )

    # --- PMSchedule ---
    def create_pm_schedule(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/pm-schedules", payload, headers
        )

    def list_pm_schedules(self, asset_id, headers, params=None):
        return self._request(
            "GET", f"/assets/{asset_id}/pm-schedules", headers=headers, params=params
        )

    def get_pm_schedule(self, schedule_id, headers):
        return self._request("GET", f"/pm-schedules/{schedule_id}", headers=headers)

    def generate_due(self, schedule_id, headers):
        return self._request(
            "POST", f"/pm-schedules/{schedule_id}/generate-due", headers=headers
        )

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def release_to_queue(self, wo_id, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/release-to-queue", headers=headers
        )

    def assign_work_order(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/assign", payload, headers
        )

    def schedule_window(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/schedule-window", payload, headers
        )

    def unassign_work_order(self, wo_id, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/unassign", headers=headers
        )

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/start", headers=headers)

    def hold_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/hold", headers=headers)

    def resume_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/resume", headers=headers)

    def close_work_order(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/close", payload, headers
        )

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", headers=headers)

    # --- PartReservation ---
    def create_reservation(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/reservations", payload, headers
        )

    def list_wo_reservations(self, wo_id, headers, params=None):
        return self._request(
            "GET", f"/work-orders/{wo_id}/reservations", headers=headers, params=params
        )

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def release_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/release", headers=headers
        )

    def commit_parts(self, wo_id, headers):
        return self._request(
            "POST", f"/work-orders/{wo_id}/commit-parts", headers=headers
        )

    # --- DowntimeEvent ---
    def create_downtime_event(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/downtime-events", payload, headers
        )

    def list_asset_downtime_events(self, asset_id, headers, params=None):
        return self._request(
            "GET", f"/assets/{asset_id}/downtime-events", headers=headers, params=params
        )

    def get_downtime_event(self, downtime_id, headers):
        return self._request(
            "GET", f"/downtime-events/{downtime_id}", headers=headers
        )

    def list_downtime_events(self, headers, params=None):
        return self._request(
            "GET", "/downtime-events", headers=headers, params=params
        )

    def resolve_downtime_event(self, downtime_id, payload, headers):
        return self._request(
            "POST", f"/downtime-events/{downtime_id}/resolve", payload, headers
        )

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/warranty-claims", headers=headers, params=params
        )

    def approve_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/approve", payload, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/deny", payload, headers
        )


api_client = ApiClient()
