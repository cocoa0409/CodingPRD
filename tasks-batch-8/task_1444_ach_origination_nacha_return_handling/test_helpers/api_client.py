"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ach/_clock/set_current_utc", payload, headers)

    # --- Originator ---
    def create_originator(self, payload, headers):
        return self._request("POST", "/ach/originators", payload, headers)

    def get_originator(self, originator_id, headers):
        return self._request("GET", f"/ach/originators/{originator_id}",
                             headers=headers)

    def patch_originator(self, originator_id, payload, headers):
        return self._request("PATCH", f"/ach/originators/{originator_id}",
                             payload, headers)

    def create_return_rate_snapshot(self, originator_id, headers):
        return self._request(
            "POST", f"/ach/originators/{originator_id}/return-rate-snapshots",
            {}, headers)

    def list_return_rate_snapshots(self, originator_id, headers, params=None):
        return self._request(
            "GET", f"/ach/originators/{originator_id}/return-rate-snapshots",
            headers=headers, params=params)

    # --- Risk cases ---
    def create_risk_case(self, originator_id, headers):
        return self._request("POST", f"/ach/originators/{originator_id}/risk-cases",
                             {}, headers)

    def list_risk_cases(self, originator_id, headers, params=None):
        return self._request("GET", f"/ach/originators/{originator_id}/risk-cases",
                             headers=headers, params=params)

    def resolve_risk_case(self, risk_case_id, payload, headers):
        return self._request("POST", f"/ach/risk-cases/{risk_case_id}/resolve",
                             payload, headers)

    # --- ACH files ---
    def create_ach_file(self, payload, headers):
        return self._request("POST", "/ach/ach-files", payload, headers)

    def list_ach_files(self, headers, params=None):
        return self._request("GET", "/ach/ach-files", headers=headers, params=params)

    def get_ach_file(self, file_id, headers):
        return self._request("GET", f"/ach/ach-files/{file_id}", headers=headers)

    def append_entries(self, file_id, payload, headers):
        return self._request("POST", f"/ach/ach-files/{file_id}/entries",
                             payload, headers)

    def list_entries(self, file_id, headers, params=None):
        return self._request("GET", f"/ach/ach-files/{file_id}/entries",
                             headers=headers, params=params)

    def release_file(self, file_id, headers):
        return self._request("POST", f"/ach/ach-files/{file_id}/release",
                             {}, headers)

    def cancel_file(self, file_id, headers):
        return self._request("POST", f"/ach/ach-files/{file_id}/cancel",
                             {}, headers)

    # --- ACH entries ---
    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/ach/ach-entries/{entry_id}", headers=headers)

    def register_return(self, entry_id, payload, headers):
        return self._request("POST", f"/ach/ach-entries/{entry_id}/returns",
                             payload, headers)

    def represent_entry(self, entry_id, headers):
        return self._request("POST", f"/ach/ach-entries/{entry_id}/representments",
                             {}, headers)

    def register_noc(self, entry_id, payload, headers):
        return self._request("POST", f"/ach/ach-entries/{entry_id}/nocs",
                             payload, headers)

    def list_noc_records(self, entry_id, headers, params=None):
        return self._request("GET", f"/ach/ach-entries/{entry_id}/noc-records",
                             headers=headers, params=params)

    def apply_noc(self, noc_id, headers):
        return self._request("POST", f"/ach/noc-records/{noc_id}/apply",
                             {}, headers)

    def create_reversal(self, entry_id, payload, headers):
        return self._request("POST", f"/ach/ach-entries/{entry_id}/reversals",
                             payload, headers)

    def list_reversal_requests(self, entry_id, headers, params=None):
        return self._request("GET",
                             f"/ach/ach-entries/{entry_id}/reversal-requests",
                             headers=headers, params=params)

    def list_return_cases(self, entry_id, headers, params=None):
        return self._request("GET", f"/ach/ach-entries/{entry_id}/return-cases",
                             headers=headers, params=params)

    def close_entry(self, entry_id, headers):
        return self._request("POST", f"/ach/ach-entries/{entry_id}/close",
                             {}, headers)

    # --- Reversal advancement ---
    def advance_reversal(self, reversal_id, payload, headers):
        return self._request("POST", f"/ach/reversal-requests/{reversal_id}/advance",
                             payload, headers)

    # --- Settlement batches ---
    def advance_batch(self, batch_id, payload, headers):
        return self._request("POST",
                             f"/ach/settlement-batches/{batch_id}/advance",
                             payload, headers)

    def reconcile_batch(self, batch_id, headers):
        return self._request("POST",
                             f"/ach/settlement-batches/{batch_id}/reconcile",
                             {}, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/ach/settlement-batches/{batch_id}",
                             headers=headers)

    def list_gl_postings(self, batch_id, headers, params=None):
        return self._request("GET",
                             f"/ach/settlement-batches/{batch_id}/gl-postings",
                             headers=headers, params=params)

    # --- Cutoff windows ---
    def create_cutoff_window(self, payload, headers):
        return self._request("POST", "/ach/cutoff-windows", payload, headers)


api_client = ApiClient()
