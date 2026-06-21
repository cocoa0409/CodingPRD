"""API client: one method per endpoint defined in the PRD (PRD §4).

Subclasses the framework's `GenericApiClient` to inherit the `_request` HTTP
plumbing; this module supplies only the per-endpoint thin wrappers.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Patient (PRD §3.1, §4) ──────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def list_patient_lab_orders(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/lab-orders", headers=headers, params=params
        )

    # ─── Clinician (PRD §3.1, §4) ────────────────────────────────
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/clinicians", headers=headers, params=params)

    # ─── LabOrder (PRD §3.2, §4) ─────────────────────────────────
    def create_lab_order(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/lab-orders", payload, headers
        )

    def get_lab_order(self, lab_order_id, headers, params=None):
        return self._request(
            "GET", f"/lab-orders/{lab_order_id}", headers=headers, params=params
        )

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/lab-orders", headers=headers, params=params)

    def cancel_lab_order(self, lab_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/lab-orders/{lab_order_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Specimen (PRD §3.3, §4) ─────────────────────────────────
    def create_specimen(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/specimens", payload, headers
        )

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/specimens", headers=headers, params=params)

    def collect_specimen(self, specimen_id, headers, payload=None):
        return self._request(
            "POST",
            f"/specimens/{specimen_id}/collect",
            payload if payload is not None else {},
            headers,
        )

    def transit_specimen(self, specimen_id, headers, payload=None):
        return self._request(
            "POST",
            f"/specimens/{specimen_id}/transit",
            payload if payload is not None else {},
            headers,
        )

    def accession_specimen(self, specimen_id, headers, payload=None):
        return self._request(
            "POST",
            f"/specimens/{specimen_id}/accession",
            payload if payload is not None else {},
            headers,
        )

    def reject_specimen(self, specimen_id, payload, headers):
        return self._request(
            "POST", f"/specimens/{specimen_id}/reject", payload, headers
        )

    # ─── Instrument & InstrumentRun (PRD §3.4, §4) ───────────────
    def create_instrument(self, payload, headers):
        return self._request("POST", "/instruments", payload, headers)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/instruments/{instrument_id}", headers=headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/instruments", headers=headers, params=params)

    def create_instrument_run(self, payload, headers):
        return self._request("POST", "/instrument-runs", payload, headers)

    def get_instrument_run(self, run_id, headers):
        return self._request("GET", f"/instrument-runs/{run_id}", headers=headers)

    def list_instrument_runs(self, headers, params=None):
        return self._request("GET", "/instrument-runs", headers=headers, params=params)

    def complete_instrument_run(self, run_id, headers, payload=None):
        return self._request(
            "POST",
            f"/instrument-runs/{run_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    # ─── Result (PRD §3.5, §3.8, §4) ─────────────────────────────
    def create_result(self, payload, headers):
        return self._request("POST", "/results", payload, headers)

    def get_result(self, result_id, headers):
        return self._request("GET", f"/results/{result_id}", headers=headers)

    def list_results(self, headers, params=None):
        return self._request("GET", "/results", headers=headers, params=params)

    def release_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"/results/{result_id}/release", payload, headers
        )

    def amend_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"/results/{result_id}/amend", payload, headers
        )

    def invalidate_result(self, result_id, headers, payload=None):
        return self._request(
            "POST",
            f"/results/{result_id}/invalidate",
            payload if payload is not None else {},
            headers,
        )

    # ─── CriticalNotification (PRD §3.7, §4) ─────────────────────
    def get_critical_notification(self, notif_id, headers):
        return self._request(
            "GET", f"/critical-notifications/{notif_id}", headers=headers
        )

    def list_critical_notifications(self, headers, params=None):
        return self._request(
            "GET", "/critical-notifications", headers=headers, params=params
        )

    def send_critical_notification(self, notif_id, headers, payload=None):
        return self._request(
            "POST",
            f"/critical-notifications/{notif_id}/send",
            payload if payload is not None else {},
            headers,
        )

    def escalate_critical_notification(self, notif_id, headers, payload=None):
        return self._request(
            "POST",
            f"/critical-notifications/{notif_id}/escalate",
            payload if payload is not None else {},
            headers,
        )

    def create_acknowledgement(self, notif_id, payload, headers):
        return self._request(
            "POST", f"/critical-notifications/{notif_id}/acknowledgements", payload, headers
        )

    def list_acknowledgements_for_notification(self, notif_id, headers, params=None):
        return self._request(
            "GET",
            f"/critical-notifications/{notif_id}/acknowledgements",
            headers=headers,
            params=params,
        )

    # ─── AcknowledgementReceipt (PRD §3.7, §4) ───────────────────
    def get_acknowledgement_receipt(self, receipt_id, headers):
        return self._request(
            "GET", f"/acknowledgement-receipts/{receipt_id}", headers=headers
        )

    def list_acknowledgement_receipts(self, headers, params=None):
        return self._request(
            "GET", "/acknowledgement-receipts", headers=headers, params=params
        )

    # ─── RetestRequest (PRD §3.8, §4) ────────────────────────────
    def create_retest_request(self, result_id, payload, headers):
        return self._request(
            "POST", f"/results/{result_id}/retest-requests", payload, headers
        )

    def get_retest_request(self, retest_id, headers):
        return self._request("GET", f"/retest-requests/{retest_id}", headers=headers)

    def list_retest_requests(self, headers, params=None):
        return self._request("GET", "/retest-requests", headers=headers, params=params)

    def schedule_retest_request(self, retest_id, headers, payload=None):
        return self._request(
            "POST",
            f"/retest-requests/{retest_id}/schedule",
            payload if payload is not None else {},
            headers,
        )

    def cancel_retest_request(self, retest_id, headers, payload=None):
        return self._request(
            "POST",
            f"/retest-requests/{retest_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Test-driving clock (PRD §3.9) ───────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
