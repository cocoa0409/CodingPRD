"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (§2.8) --------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Cases -----------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def list_case_jobs(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/jobs", headers=headers, params=params)

    # ---- Attorneys -------------------------------------------------------
    def create_attorney(self, payload, headers):
        return self._request("POST", "/attorneys", payload, headers)

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/attorneys/{attorney_id}", headers=headers)

    def list_attorneys(self, headers, params=None):
        return self._request("GET", "/attorneys", headers=headers, params=params)

    # ---- Resources -------------------------------------------------------
    def create_resource(self, payload, headers):
        return self._request("POST", "/resources", payload, headers)

    def get_resource(self, resource_id, headers):
        return self._request("GET", f"/resources/{resource_id}", headers=headers)

    def list_resources(self, headers, params=None):
        return self._request("GET", "/resources", headers=headers, params=params)

    def deactivate_resource(self, resource_id, headers):
        return self._request("POST", f"/resources/{resource_id}/deactivate", headers=headers)

    def list_resource_assignments(self, resource_id, headers, params=None):
        return self._request(
            "GET", f"/resources/{resource_id}/assignments", headers=headers, params=params
        )

    # ---- Jobs ------------------------------------------------------------
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def create_assignment(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/assignments", payload, headers)

    def list_job_assignments(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/jobs/{job_id}/assignments", headers=headers, params=params
        )

    def confirm_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/confirm", payload, headers)

    def start_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/start", payload, headers)

    def adjourn_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/adjourn", payload, headers)

    def cancel_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", payload, headers)

    def get_appearance_estimate(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}/appearance-estimate", headers=headers)

    # ---- Assignments (peer) ----------------------------------------------
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/release", headers=headers)

    # ---- Realtime streams ------------------------------------------------
    def create_realtime_stream(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/realtime-streams", payload, headers)

    def list_job_realtime_streams(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/jobs/{job_id}/realtime-streams", headers=headers, params=params
        )

    def get_realtime_stream(self, stream_id, headers):
        return self._request("GET", f"/realtime-streams/{stream_id}", headers=headers)

    def list_realtime_streams(self, headers, params=None):
        return self._request("GET", "/realtime-streams", headers=headers, params=params)

    def go_live_stream(self, stream_id, headers):
        return self._request("POST", f"/realtime-streams/{stream_id}/go-live", headers=headers)

    def stop_stream(self, stream_id, headers):
        return self._request("POST", f"/realtime-streams/{stream_id}/stop", headers=headers)

    # ---- Transcript orders -----------------------------------------------
    def create_transcript_order(self, payload, headers):
        return self._request("POST", "/transcript-orders", payload, headers)

    def get_transcript_order(self, to_id, headers):
        return self._request("GET", f"/transcript-orders/{to_id}", headers=headers)

    def list_transcript_orders(self, headers, params=None):
        return self._request("GET", "/transcript-orders", headers=headers, params=params)

    def get_transcript_quote(self, to_id, headers):
        return self._request("GET", f"/transcript-orders/{to_id}/quote", headers=headers)

    def deliver_rough(self, to_id, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/deliver-rough", headers=headers)

    def certify_transcript(self, to_id, payload, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/certify", payload, headers)

    def open_read_sign(self, to_id, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/open-read-sign", headers=headers)

    def file_errata(self, to_id, payload, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/errata", payload, headers)

    def sign_transcript(self, to_id, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/sign", headers=headers)

    def finalize_deadline(self, to_id, headers):
        return self._request(
            "POST", f"/transcript-orders/{to_id}/finalize-deadline", headers=headers
        )

    def deliver_transcript(self, to_id, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/deliver", headers=headers)

    def cancel_transcript(self, to_id, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/cancel", headers=headers)

    # ---- Exhibits --------------------------------------------------------
    def create_exhibit(self, to_id, payload, headers):
        return self._request("POST", f"/transcript-orders/{to_id}/exhibits", payload, headers)

    def list_exhibits(self, to_id, headers, params=None):
        return self._request(
            "GET", f"/transcript-orders/{to_id}/exhibits", headers=headers, params=params
        )

    def get_exhibit(self, exhibit_id, headers):
        return self._request("GET", f"/exhibits/{exhibit_id}", headers=headers)

    # ---- Errata ----------------------------------------------------------
    def list_errata(self, to_id, headers, params=None):
        return self._request(
            "GET", f"/transcript-orders/{to_id}/errata", headers=headers, params=params
        )

    def get_errata(self, errata_id, headers):
        return self._request("GET", f"/errata/{errata_id}", headers=headers)

    # ---- Invoices --------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)


api_client = ApiClient()
