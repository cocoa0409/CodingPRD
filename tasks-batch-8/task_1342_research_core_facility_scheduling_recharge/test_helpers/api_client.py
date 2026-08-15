"""API client: one method per endpoint defined in the PRD (§4 table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Users ---
    def create_user(self, payload, headers):
        return self._request("POST", "/users", payload, headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/users", headers=headers, params=params)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    def suspend_user(self, user_id, headers):
        return self._request("POST", f"/users/{user_id}/suspend", {}, headers)

    def reactivate_user(self, user_id, headers):
        return self._request("POST", f"/users/{user_id}/reactivate", {}, headers)

    # --- Instruments ---
    def create_instrument(self, payload, headers):
        return self._request("POST", "/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/instruments/{instrument_id}", headers=headers)

    def retire_instrument(self, instrument_id, headers):
        return self._request("POST", f"/instruments/{instrument_id}/retire", {}, headers)

    def return_instrument_to_service(self, instrument_id, headers):
        return self._request(
            "POST", f"/instruments/{instrument_id}/return-to-service", {}, headers
        )

    # --- Training records ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    def certify_training_record(self, record_id, headers):
        return self._request(
            "POST", f"/training-records/{record_id}/certify", {}, headers
        )

    def reenroll_training_record(self, record_id, headers):
        return self._request(
            "POST", f"/training-records/{record_id}/re-enroll", {}, headers
        )

    def revoke_training_record(self, record_id, headers):
        return self._request("POST", f"/training-records/{record_id}/revoke", {}, headers)

    # --- Grants ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def amend_grant(self, grant_id, payload, headers):
        return self._request("PUT", f"/grants/{grant_id}", payload, headers)

    def close_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/close", {}, headers)

    # --- Rate sets ---
    def create_rate_set(self, payload, headers):
        return self._request("POST", "/rate-sets", payload, headers)

    def list_rate_sets(self, headers, params=None):
        return self._request("GET", "/rate-sets", headers=headers, params=params)

    def get_rate_set(self, rate_set_id, headers):
        return self._request("GET", f"/rate-sets/{rate_set_id}", headers=headers)

    def edit_rate_set(self, rate_set_id, payload, headers):
        return self._request("PUT", f"/rate-sets/{rate_set_id}", payload, headers)

    def submit_rate_set(self, rate_set_id, headers, payload=None):
        return self._request(
            "POST", f"/rate-sets/{rate_set_id}/submit", payload or {}, headers
        )

    def approve_rate_set(self, rate_set_id, headers):
        return self._request("POST", f"/rate-sets/{rate_set_id}/approve", {}, headers)

    def reject_rate_set(self, rate_set_id, headers, payload=None):
        return self._request(
            "POST", f"/rate-sets/{rate_set_id}/reject", payload or {}, headers
        )

    def activate_rate_set(self, rate_set_id, headers):
        return self._request("POST", f"/rate-sets/{rate_set_id}/activate", {}, headers)

    def get_rate_set_break_even(self, rate_set_id, headers):
        return self._request(
            "GET", f"/rate-sets/{rate_set_id}/break-even", headers=headers
        )

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def approve_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/approve", {}, headers)

    def reject_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/reject", payload or {}, headers
        )

    def cancel_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/cancel", payload or {}, headers
        )

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule", payload, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/no-show", {}, headers)

    # --- Usage logs ---
    def create_usage_log(self, payload, headers):
        return self._request("POST", "/usage-logs", payload, headers)

    def list_usage_logs(self, headers, params=None):
        return self._request("GET", "/usage-logs", headers=headers, params=params)

    def get_usage_log(self, log_id, headers):
        return self._request("GET", f"/usage-logs/{log_id}", headers=headers)

    def edit_usage_log(self, log_id, payload, headers):
        return self._request("PUT", f"/usage-logs/{log_id}", payload, headers)

    def submit_usage_log(self, log_id, headers):
        return self._request("POST", f"/usage-logs/{log_id}/submit", {}, headers)

    def validate_usage_log(self, log_id, headers):
        return self._request("POST", f"/usage-logs/{log_id}/validate", {}, headers)

    def reject_usage_log(self, log_id, headers, payload=None):
        return self._request(
            "POST", f"/usage-logs/{log_id}/reject", payload or {}, headers
        )

    # --- Recharge batches ---
    def create_recharge_batch(self, payload, headers):
        return self._request("POST", "/recharge-batches", payload, headers)

    def list_recharge_batches(self, headers, params=None):
        return self._request("GET", "/recharge-batches", headers=headers, params=params)

    def get_recharge_batch(self, batch_id, headers):
        return self._request("GET", f"/recharge-batches/{batch_id}", headers=headers)

    def finalize_recharge_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/recharge-batches/{batch_id}/finalize", {}, headers
        )

    # --- Recharge entries ---
    def list_recharge_entries(self, headers, params=None):
        return self._request("GET", "/recharge-entries", headers=headers, params=params)

    def get_recharge_entry(self, entry_id, headers):
        return self._request("GET", f"/recharge-entries/{entry_id}", headers=headers)

    def dispute_recharge_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/recharge-entries/{entry_id}/dispute", payload, headers
        )

    def resolve_recharge_entry_dispute(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/recharge-entries/{entry_id}/resolve-dispute", payload, headers
        )

    def mark_recharge_entry_paid(self, entry_id, headers):
        return self._request(
            "POST", f"/recharge-entries/{entry_id}/mark-paid", {}, headers
        )

    # --- Subsidy applications ---
    def create_subsidy_application(self, payload, headers):
        return self._request("POST", "/subsidy-applications", payload, headers)

    def list_subsidy_applications(self, headers, params=None):
        return self._request("GET", "/subsidy-applications", headers=headers, params=params)

    def get_subsidy_application(self, application_id, headers):
        return self._request(
            "GET", f"/subsidy-applications/{application_id}", headers=headers
        )

    def submit_subsidy_application(self, application_id, headers):
        return self._request(
            "POST", f"/subsidy-applications/{application_id}/submit", {}, headers
        )

    def review_subsidy_application(self, application_id, headers):
        return self._request(
            "POST", f"/subsidy-applications/{application_id}/review", {}, headers
        )

    def request_subsidy_application_revision(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/subsidy-applications/{application_id}/request-revision",
            payload or {},
            headers,
        )

    def approve_subsidy_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/subsidy-applications/{application_id}/approve", payload, headers
        )

    def reject_subsidy_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidy-applications/{application_id}/reject", payload or {}, headers
        )

    # --- Subsidy awards ---
    def list_subsidy_awards(self, headers, params=None):
        return self._request("GET", "/subsidy-awards", headers=headers, params=params)

    def get_subsidy_award(self, award_id, headers):
        return self._request("GET", f"/subsidy-awards/{award_id}", headers=headers)

    def revoke_subsidy_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidy-awards/{award_id}/revoke", payload or {}, headers
        )

    # --- Maintenance contracts ---
    def create_maintenance_contract(self, payload, headers):
        return self._request("POST", "/maintenance-contracts", payload, headers)

    def list_maintenance_contracts(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-contracts", headers=headers, params=params
        )

    def get_maintenance_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/maintenance-contracts/{contract_id}", headers=headers
        )

    def terminate_maintenance_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/maintenance-contracts/{contract_id}/terminate",
            payload or {},
            headers,
        )

    # --- Downtime events ---
    def create_downtime_event(self, payload, headers):
        return self._request("POST", "/downtime-events", payload, headers)

    def list_downtime_events(self, headers, params=None):
        return self._request("GET", "/downtime-events", headers=headers, params=params)

    def get_downtime_event(self, event_id, headers):
        return self._request("GET", f"/downtime-events/{event_id}", headers=headers)

    def confirm_downtime_event(self, event_id, headers):
        return self._request("POST", f"/downtime-events/{event_id}/confirm", {}, headers)

    def resolve_downtime_event(self, event_id, headers):
        return self._request("POST", f"/downtime-events/{event_id}/resolve", {}, headers)

    def cancel_downtime_event(self, event_id, headers):
        return self._request("POST", f"/downtime-events/{event_id}/cancel", {}, headers)

    # --- Publications ---
    def create_publication(self, payload, headers):
        return self._request("POST", "/publications", payload, headers)

    def list_publications(self, headers, params=None):
        return self._request("GET", "/publications", headers=headers, params=params)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/publications/{publication_id}", headers=headers)

    def verify_publication(self, publication_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/verify", {}, headers
        )

    def reject_publication(self, publication_id, headers, payload=None):
        return self._request(
            "POST", f"/publications/{publication_id}/reject", payload or {}, headers
        )

    # --- Fiscal years ---
    def create_fiscal_year(self, payload, headers):
        return self._request("POST", "/fiscal-years", payload, headers)

    def list_fiscal_years(self, headers, params=None):
        return self._request("GET", "/fiscal-years", headers=headers, params=params)

    def get_fiscal_year(self, fiscal_year_id, headers):
        return self._request("GET", f"/fiscal-years/{fiscal_year_id}", headers=headers)

    def close_fiscal_year(self, fiscal_year_id, headers):
        return self._request("POST", f"/fiscal-years/{fiscal_year_id}/close", {}, headers)

    # --- Test-driving clock ---
    def set_logical_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
