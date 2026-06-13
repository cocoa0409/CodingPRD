"""API client: one method per endpoint defined in the PRD (Locksmith & Lockout Dispatch)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── ServiceJob ──────────────────────────────────────────────────────────
    def create_service_job(self, payload, headers):
        return self._request("POST", "/service-jobs", payload, headers)

    def list_service_jobs(self, headers, params=None):
        return self._request("GET", "/service-jobs", headers=headers, params=params)

    def get_service_job(self, job_id, headers):
        return self._request("GET", f"/service-jobs/{job_id}", headers=headers)

    def cancel_service_job(self, job_id, headers):
        return self._request("POST", f"/service-jobs/{job_id}/cancel", {}, headers)

    def complete_work(self, job_id, headers):
        return self._request("POST", f"/service-jobs/{job_id}/complete-work", {}, headers)

    def close_service_job(self, job_id, headers):
        return self._request("POST", f"/service-jobs/{job_id}/close", {}, headers)

    def capture_payment(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/payments", payload, headers)

    def list_payments(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/payments", headers=headers, params=params)

    def file_key_authorization(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/key-authorizations", payload, headers)

    def list_key_authorizations(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/key-authorizations", headers=headers, params=params)

    def file_warranty_claim(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/warranty-claims", payload, headers)

    def list_warranty_claims(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/warranty-claims", headers=headers, params=params)

    # ─── Dispatch ────────────────────────────────────────────────────────────
    def create_dispatch(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/dispatches", payload, headers)

    def list_job_dispatches(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/dispatches", headers=headers, params=params)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def depart_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/depart", {}, headers)

    def arrive_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/arrive", payload, headers)

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/cancel", {}, headers)

    # ─── Technician ──────────────────────────────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def set_technician_off_duty(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/set-off-duty", {}, headers)

    def set_technician_on_duty(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/set-on-duty", {}, headers)

    # ─── JobBay & BayBooking ─────────────────────────────────────────────────
    def create_job_bay(self, payload, headers):
        return self._request("POST", "/job-bays", payload, headers)

    def list_job_bays(self, headers, params=None):
        return self._request("GET", "/job-bays", headers=headers, params=params)

    def get_job_bay(self, bay_id, headers):
        return self._request("GET", f"/job-bays/{bay_id}", headers=headers)

    def close_bay_for_maint(self, bay_id, headers):
        return self._request("POST", f"/job-bays/{bay_id}/close-for-maint", {}, headers)

    def reopen_bay(self, bay_id, headers):
        return self._request("POST", f"/job-bays/{bay_id}/reopen", {}, headers)

    def create_bay_booking(self, payload, headers):
        return self._request("POST", "/bay-bookings", payload, headers)

    def list_bay_bookings(self, headers, params=None):
        return self._request("GET", "/bay-bookings", headers=headers, params=params)

    def get_bay_booking(self, booking_id, headers):
        return self._request("GET", f"/bay-bookings/{booking_id}", headers=headers)

    def release_bay_booking(self, booking_id, headers):
        return self._request("POST", f"/bay-bookings/{booking_id}/release", {}, headers)

    # ─── OnSiteQuote ─────────────────────────────────────────────────────────
    def create_quote(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/quotes", payload, headers)

    def list_job_quotes(self, job_id, headers, params=None):
        return self._request("GET", f"/service-jobs/{job_id}/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/submit", {}, headers)

    def approve_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/approve", {}, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", {}, headers)

    def request_quote_revision(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/request-revision", {}, headers)

    def reopen_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reopen", {}, headers)

    def update_quote(self, quote_id, payload, headers):
        return self._request("PUT", f"/quotes/{quote_id}", payload, headers)

    # ─── LockPart & PartReservation ──────────────────────────────────────────
    def create_lock_part(self, payload, headers):
        return self._request("POST", "/lock-parts", payload, headers)

    def list_lock_parts(self, headers, params=None):
        return self._request("GET", "/lock-parts", headers=headers, params=params)

    def get_lock_part(self, part_id, headers):
        return self._request("GET", f"/lock-parts/{part_id}", headers=headers)

    def update_lock_part(self, part_id, payload, headers):
        return self._request("PUT", f"/lock-parts/{part_id}", payload, headers)

    def create_part_reservation(self, payload, headers):
        return self._request("POST", "/part-reservations", payload, headers)

    def list_part_reservations(self, headers, params=None):
        return self._request("GET", "/part-reservations", headers=headers, params=params)

    def get_part_reservation(self, reservation_id, headers):
        return self._request("GET", f"/part-reservations/{reservation_id}", headers=headers)

    # ─── WarrantyClaim actions ───────────────────────────────────────────────
    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", {}, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", {}, headers)


api_client = ApiClient()
