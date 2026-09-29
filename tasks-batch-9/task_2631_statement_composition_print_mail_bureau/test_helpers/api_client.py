"""Typed HTTP client for the Statement Composition & Print-Mail Bureau API.

One method per endpoint. Every method returns the raw ``requests.Response`` so
tests can assert on status codes as well as bodies. Identity headers are always
supplied explicitly by the caller — there is no implicit default actor.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the bureau API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    def create_client(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/bureau/clients", payload, headers)

    def get_client(self, client_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bureau/clients/{client_id}", None, headers)

    def list_clients(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/clients", params, headers)

    def patch_client(
        self, client_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("PATCH", f"/bureau/clients/{client_id}", payload, headers)

    def create_postage_deposit(
        self, client_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/clients/{client_id}/postage-deposits", payload, headers
        )

    def paperless_sync(
        self, client_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/clients/{client_id}/paperless-sync", payload, headers
        )

    def release_address_feedback(
        self, client_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/clients/{client_id}/address-feedback", payload, headers
        )

    def list_client_templates(
        self, client_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/clients/{client_id}/composition-templates", params, headers
        )

    def list_client_data_files(
        self, client_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/clients/{client_id}/data-files", params, headers
        )

    def list_client_enrollments(
        self, client_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/clients/{client_id}/paperless-enrollments", params, headers
        )

    # ------------------------------------------------------------------
    # Composition templates
    # ------------------------------------------------------------------

    def create_template(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/bureau/composition-templates", payload, headers)

    def get_template(self, template_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/bureau/composition-templates/{template_id}", None, headers
        )

    def activate_template(
        self, template_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/composition-templates/{template_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Insert stock
    # ------------------------------------------------------------------

    def create_insert_stock(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/bureau/insert-stocks", payload, headers)

    def get_insert_stock(self, insert_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/bureau/insert-stocks/{insert_id}", None, headers
        )

    def list_insert_stocks(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/insert-stocks", params, headers)

    # ------------------------------------------------------------------
    # Data files and statement records
    # ------------------------------------------------------------------

    def create_data_file(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/bureau/data-files", payload, headers)

    def get_data_file(self, file_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bureau/data-files/{file_id}", None, headers)

    def validate_format(
        self, file_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/data-files/{file_id}/validate-format",
            payload if payload is not None else {},
            headers,
        )

    def control_check(
        self, file_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/data-files/{file_id}/control-check",
            payload if payload is not None else {},
            headers,
        )

    def amend_control_totals(
        self, file_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/data-files/{file_id}/amend-control-totals",
            payload,
            headers,
        )

    def list_file_records(
        self, file_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/data-files/{file_id}/statement-records", params, headers
        )

    def create_statement_record(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/bureau/statement-records", payload, headers)

    def get_statement_record(
        self, record_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/statement-records/{record_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Paperless enrollments
    # ------------------------------------------------------------------

    def create_enrollment(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/bureau/paperless-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/bureau/paperless-enrollments/{enrollment_id}", None, headers
        )

    def revoke_enrollment(
        self, enrollment_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/paperless-enrollments/{enrollment_id}/revoke",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Composition jobs
    # ------------------------------------------------------------------

    def create_composition_job(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/bureau/composition-jobs", payload, headers)

    def get_composition_job(self, job_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/bureau/composition-jobs/{job_id}", None, headers
        )

    def list_composition_jobs(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/composition-jobs", params, headers)

    def presort_job(
        self, job_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/composition-jobs/{job_id}/presort",
            payload if payload is not None else {},
            headers,
        )

    def schedule_job(
        self, job_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/composition-jobs/{job_id}/schedule", payload, headers
        )

    def reconcile_integrity(
        self, job_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/composition-jobs/{job_id}/reconcile-integrity",
            payload if payload is not None else {},
            headers,
        )

    def close_job(
        self, job_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/composition-jobs/{job_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def get_integrity_summary(
        self, job_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/bureau/composition-jobs/{job_id}/integrity-summary",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Mail pieces, scans and reprints
    # ------------------------------------------------------------------

    def get_mail_piece(self, piece_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bureau/mail-pieces/{piece_id}", None, headers)

    def list_mail_pieces(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/mail-pieces", params, headers)

    def create_scan(
        self, piece_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/mail-pieces/{piece_id}/scans", payload, headers
        )

    def create_reprint(
        self, piece_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/mail-pieces/{piece_id}/reprints", payload, headers
        )

    def list_scan_events(
        self, piece_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/mail-pieces/{piece_id}/scan-events", params, headers
        )

    def list_piece_returns(
        self, piece_id: str, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/bureau/mail-pieces/{piece_id}/undeliverable-returns",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Press lines and print runs
    # ------------------------------------------------------------------

    def create_press_line(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/bureau/press-lines", payload, headers)

    def get_press_line(self, line_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bureau/press-lines/{line_id}", None, headers)

    def list_press_lines(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/press-lines", params, headers)

    def get_print_run(self, run_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bureau/print-runs/{run_id}", None, headers)

    def list_print_runs(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/print-runs", params, headers)

    def start_run(
        self, run_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/print-runs/{run_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def complete_run(
        self, run_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/print-runs/{run_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def abort_run(
        self, run_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/print-runs/{run_id}/abort",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Entry facilities and presort batches
    # ------------------------------------------------------------------

    def create_entry_facility(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/bureau/entry-facilities", payload, headers)

    def get_entry_facility(
        self, facility_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/bureau/entry-facilities/{facility_id}", None, headers
        )

    def get_presort_batch(self, batch_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/bureau/presort-batches/{batch_id}", None, headers
        )

    def list_presort_batches(
        self, headers: Headers, params: Payload = None
    ) -> requests.Response:
        return self._request("GET", "/bureau/presort-batches", params, headers)

    def seal_batch(
        self, batch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/presort-batches/{batch_id}/seal", payload, headers
        )

    def unseal_batch(
        self, batch_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/presort-batches/{batch_id}/unseal",
            payload if payload is not None else {},
            headers,
        )

    def manifest_batch(
        self, batch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/presort-batches/{batch_id}/manifest", payload, headers
        )

    # ------------------------------------------------------------------
    # Undeliverable returns
    # ------------------------------------------------------------------

    def create_return(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/bureau/undeliverable-returns", payload, headers)

    def get_return(self, return_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/bureau/undeliverable-returns/{return_id}", None, headers
        )

    def classify_return(
        self, return_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bureau/undeliverable-returns/{return_id}/classify",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Disaster-recovery site
    # ------------------------------------------------------------------

    def create_dr_site(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/bureau/dr-sites", payload, headers)

    def get_dr_site(self, site_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bureau/dr-sites/{site_id}", None, headers)

    def create_drill(
        self, site_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bureau/dr-sites/{site_id}/drills", payload, headers
        )

    def patch_dr_site(
        self, site_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("PATCH", f"/bureau/dr-sites/{site_id}", payload, headers)
