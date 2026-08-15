"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- system / test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_epoch(self, headers):
        return self._request("POST", "/api/_scheduler/run_epoch", {}, headers)

    # --- volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/api/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/api/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/api/volunteers/{volunteer_id}", headers=headers)

    def complete_orientation(self, volunteer_id, headers):
        return self._request(
            "POST", f"/api/volunteers/{volunteer_id}/orientation/complete", {}, headers
        )

    def sign_waiver(self, volunteer_id, headers):
        return self._request(
            "POST", f"/api/volunteers/{volunteer_id}/waiver/sign", {}, headers
        )

    def set_standing(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/api/volunteers/{volunteer_id}/standing", payload, headers
        )

    # --- certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/api/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/api/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"/api/certifications/{certification_id}", headers=headers
        )

    def revoke_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/api/certifications/{certification_id}/revoke", payload, headers
        )

    # --- seasons ---
    def create_season(self, payload, headers):
        return self._request("POST", "/api/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/api/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/api/seasons/{season_id}", headers=headers)

    def patch_season(self, season_id, payload, headers):
        return self._request("PATCH", f"/api/seasons/{season_id}", payload, headers)

    def transition_season(self, season_id, payload, headers):
        return self._request(
            "POST", f"/api/seasons/{season_id}/transition", payload, headers
        )

    # --- beds ---
    def create_bed(self, payload, headers):
        return self._request("POST", "/api/beds", payload, headers)

    def list_beds(self, headers, params=None):
        return self._request("GET", "/api/beds", headers=headers, params=params)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/api/beds/{bed_id}", headers=headers)

    def transition_bed(self, bed_id, payload, headers):
        return self._request("POST", f"/api/beds/{bed_id}/transition", payload, headers)

    # --- crop plans ---
    def create_crop_plan(self, payload, headers):
        return self._request("POST", "/api/crop-plans", payload, headers)

    def list_crop_plans(self, headers, params=None):
        return self._request("GET", "/api/crop-plans", headers=headers, params=params)

    def get_crop_plan(self, crop_plan_id, headers):
        return self._request("GET", f"/api/crop-plans/{crop_plan_id}", headers=headers)

    def transition_crop_plan(self, crop_plan_id, payload, headers):
        return self._request(
            "POST", f"/api/crop-plans/{crop_plan_id}/transition", payload, headers
        )

    # --- shift slots ---
    def create_shift_slot(self, payload, headers):
        return self._request("POST", "/api/shift-slots", payload, headers)

    def list_shift_slots(self, headers, params=None):
        return self._request("GET", "/api/shift-slots", headers=headers, params=params)

    def get_shift_slot(self, slot_id, headers):
        return self._request("GET", f"/api/shift-slots/{slot_id}", headers=headers)

    def patch_shift_slot(self, slot_id, payload, headers):
        return self._request("PATCH", f"/api/shift-slots/{slot_id}", payload, headers)

    def transition_shift_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/api/shift-slots/{slot_id}/transition", payload, headers
        )

    # --- shift signups ---
    def create_shift_signup(self, payload, headers):
        return self._request("POST", "/api/shift-signups", payload, headers)

    def list_shift_signups(self, headers, params=None):
        return self._request("GET", "/api/shift-signups", headers=headers, params=params)

    def get_shift_signup(self, signup_id, headers):
        return self._request("GET", f"/api/shift-signups/{signup_id}", headers=headers)

    def confirm_shift_signup(self, signup_id, headers):
        return self._request(
            "POST", f"/api/shift-signups/{signup_id}/confirm", {}, headers
        )

    def cancel_shift_signup(self, signup_id, headers):
        return self._request(
            "POST", f"/api/shift-signups/{signup_id}/cancel", {}, headers
        )

    def check_in_shift_signup(self, signup_id, headers):
        return self._request(
            "POST", f"/api/shift-signups/{signup_id}/check-in", {}, headers
        )

    def check_out_shift_signup(self, signup_id, headers):
        return self._request(
            "POST", f"/api/shift-signups/{signup_id}/check-out", {}, headers
        )

    # --- group bookings ---
    def create_group_booking(self, payload, headers):
        return self._request("POST", "/api/group-bookings", payload, headers)

    def list_group_bookings(self, headers, params=None):
        return self._request("GET", "/api/group-bookings", headers=headers, params=params)

    def get_group_booking(self, booking_id, headers):
        return self._request("GET", f"/api/group-bookings/{booking_id}", headers=headers)

    def transition_group_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/api/group-bookings/{booking_id}/transition", payload, headers
        )

    # --- shed keys ---
    def create_shed_key(self, payload, headers):
        return self._request("POST", "/api/shed-keys", payload, headers)

    def list_shed_keys(self, headers, params=None):
        return self._request("GET", "/api/shed-keys", headers=headers, params=params)

    def get_shed_key(self, key_id, headers):
        return self._request("GET", f"/api/shed-keys/{key_id}", headers=headers)

    def transition_shed_key(self, key_id, payload, headers):
        return self._request(
            "POST", f"/api/shed-keys/{key_id}/transition", payload, headers
        )

    # --- tools ---
    def create_tool(self, payload, headers):
        return self._request("POST", "/api/tools", payload, headers)

    def list_tools(self, headers, params=None):
        return self._request("GET", "/api/tools", headers=headers, params=params)

    def get_tool(self, tool_id, headers):
        return self._request("GET", f"/api/tools/{tool_id}", headers=headers)

    def restore_tool(self, tool_id, payload, headers):
        return self._request("POST", f"/api/tools/{tool_id}/restore", payload, headers)

    def retire_tool(self, tool_id, headers):
        return self._request("POST", f"/api/tools/{tool_id}/retire", {}, headers)

    # --- tool checkouts ---
    def create_tool_checkout(self, payload, headers):
        return self._request("POST", "/api/tool-checkouts", payload, headers)

    def list_tool_checkouts(self, headers, params=None):
        return self._request("GET", "/api/tool-checkouts", headers=headers, params=params)

    def get_tool_checkout(self, checkout_id, headers):
        return self._request(
            "GET", f"/api/tool-checkouts/{checkout_id}", headers=headers
        )

    def transition_tool_checkout(self, checkout_id, payload, headers):
        return self._request(
            "POST", f"/api/tool-checkouts/{checkout_id}/transition", payload, headers
        )

    # --- harvest logs ---
    def create_harvest_log(self, payload, headers):
        return self._request("POST", "/api/harvest-logs", payload, headers)

    def list_harvest_logs(self, headers, params=None):
        return self._request("GET", "/api/harvest-logs", headers=headers, params=params)

    def get_harvest_log(self, harvest_log_id, headers):
        return self._request(
            "GET", f"/api/harvest-logs/{harvest_log_id}", headers=headers
        )

    def patch_harvest_log(self, harvest_log_id, payload, headers):
        return self._request(
            "PATCH", f"/api/harvest-logs/{harvest_log_id}", payload, headers
        )

    def transition_harvest_log(self, harvest_log_id, payload, headers):
        return self._request(
            "POST", f"/api/harvest-logs/{harvest_log_id}/transition", payload, headers
        )

    # --- donation recipients ---
    def create_donation_recipient(self, payload, headers):
        return self._request("POST", "/api/donation-recipients", payload, headers)

    def list_donation_recipients(self, headers, params=None):
        return self._request(
            "GET", "/api/donation-recipients", headers=headers, params=params
        )

    def get_donation_recipient(self, recipient_id, headers):
        return self._request(
            "GET", f"/api/donation-recipients/{recipient_id}", headers=headers
        )

    def patch_donation_recipient(self, recipient_id, payload, headers):
        return self._request(
            "PATCH", f"/api/donation-recipients/{recipient_id}", payload, headers
        )

    # --- donation allocations ---
    def create_donation_allocation(self, payload, headers):
        return self._request("POST", "/api/donation-allocations", payload, headers)

    def list_donation_allocations(self, headers, params=None):
        return self._request(
            "GET", "/api/donation-allocations", headers=headers, params=params
        )

    def get_donation_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/api/donation-allocations/{allocation_id}", headers=headers
        )

    def transition_donation_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/api/donation-allocations/{allocation_id}/transition", payload, headers
        )

    # --- irrigation schedules ---
    def create_irrigation_schedule(self, payload, headers):
        return self._request("POST", "/api/irrigation-schedules", payload, headers)

    def list_irrigation_schedules(self, headers, params=None):
        return self._request(
            "GET", "/api/irrigation-schedules", headers=headers, params=params
        )

    def get_irrigation_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/api/irrigation-schedules/{schedule_id}", headers=headers
        )

    def log_meter(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/api/irrigation-schedules/{schedule_id}/log-meter", payload, headers
        )

    def transition_irrigation_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST",
            f"/api/irrigation-schedules/{schedule_id}/transition",
            payload,
            headers,
        )


api_client = ApiClient()
