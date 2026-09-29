"""
API client: one method per endpoint of the Precision Spring & Wire Form
Manufacturing API (PRD 4). Every method returns the raw response so tests can
assert both the envelope and the HTTP status.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]
Headers = Dict[str, str]


class ApiClient(GenericApiClient):
    # ── Customer programs ────────────────────────────────────────────────────
    def create_program(self, payload: Json, headers: Headers):
        return self._request("POST", "/customer-programs", payload, headers)

    def get_program(self, program_id: str, headers: Headers):
        return self._request("GET", f"/customer-programs/{program_id}", headers=headers)

    def list_programs(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/customer-programs", headers=headers, params=params)

    def quote_program(self, program_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/customer-programs/{program_id}/quote", payload, headers
        )

    def get_tooling_amortization(
        self, program_id: str, headers: Headers, params: Optional[Json] = None
    ):
        return self._request(
            "GET",
            f"/customer-programs/{program_id}/tooling-amortization",
            headers=headers,
            params=params,
        )

    # ── Material specifications ──────────────────────────────────────────────
    def create_material_spec(self, payload: Json, headers: Headers):
        return self._request("POST", "/material-specs", payload, headers)

    def get_material_spec(self, spec_id: str, headers: Headers):
        return self._request("GET", f"/material-specs/{spec_id}", headers=headers)

    def list_material_specs(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/material-specs", headers=headers, params=params)

    # ── Spring designs ───────────────────────────────────────────────────────
    def create_design(self, payload: Json, headers: Headers):
        return self._request("POST", "/spring-designs", payload, headers)

    def get_design(self, design_id: str, headers: Headers):
        return self._request("GET", f"/spring-designs/{design_id}", headers=headers)

    def list_designs(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/spring-designs", headers=headers, params=params)

    def add_characteristic(self, design_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/spring-designs/{design_id}/critical-characteristics", payload, headers
        )

    def list_characteristics(
        self, design_id: str, headers: Headers, params: Optional[Json] = None
    ):
        return self._request(
            "GET",
            f"/spring-designs/{design_id}/critical-characteristics",
            headers=headers,
            params=params,
        )

    def submit_design_for_review(self, design_id: str, headers: Headers):
        return self._request(
            "POST", f"/spring-designs/{design_id}/submit-for-review", {}, headers
        )

    def review_design(self, design_id: str, payload: Json, headers: Headers):
        return self._request("POST", f"/spring-designs/{design_id}/review", payload, headers)

    def revise_design(self, design_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/spring-designs/{design_id}/revisions", payload, headers
        )

    def obsolete_design(self, design_id: str, headers: Headers):
        return self._request("POST", f"/spring-designs/{design_id}/obsolete", {}, headers)

    def get_fatigue_analysis(self, design_id: str, headers: Headers):
        return self._request(
            "GET", f"/spring-designs/{design_id}/fatigue-analysis", headers=headers
        )

    # ── Tooling assets ───────────────────────────────────────────────────────
    def create_tooling_asset(self, payload: Json, headers: Headers):
        return self._request("POST", "/tooling-assets", payload, headers)

    def get_tooling_asset(self, tooling_id: str, headers: Headers):
        return self._request("GET", f"/tooling-assets/{tooling_id}", headers=headers)

    def list_tooling_assets(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/tooling-assets", headers=headers, params=params)

    # ── Wire lots ────────────────────────────────────────────────────────────
    def create_wire_lot(self, payload: Json, headers: Headers):
        return self._request("POST", "/wire-lots", payload, headers)

    def get_wire_lot(self, wire_lot_id: str, headers: Headers):
        return self._request("GET", f"/wire-lots/{wire_lot_id}", headers=headers)

    def list_wire_lots(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/wire-lots", headers=headers, params=params)

    def certify_wire_lot(self, wire_lot_id: str, payload: Json, headers: Headers):
        return self._request("POST", f"/wire-lots/{wire_lot_id}/certify", payload, headers)

    # ── Coiling machines ─────────────────────────────────────────────────────
    def create_machine(self, payload: Json, headers: Headers):
        return self._request("POST", "/coiling-machines", payload, headers)

    def get_machine(self, machine_id: str, headers: Headers):
        return self._request("GET", f"/coiling-machines/{machine_id}", headers=headers)

    def list_machines(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/coiling-machines", headers=headers, params=params)

    # ── Machine setups ───────────────────────────────────────────────────────
    def create_setup(self, payload: Json, headers: Headers):
        return self._request("POST", "/machine-setups", payload, headers)

    def get_setup(self, setup_id: str, headers: Headers):
        return self._request("GET", f"/machine-setups/{setup_id}", headers=headers)

    def list_setups(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/machine-setups", headers=headers, params=params)

    def activate_setup(self, setup_id: str, headers: Headers):
        return self._request("POST", f"/machine-setups/{setup_id}/activate", {}, headers)

    def abort_setup(self, setup_id: str, headers: Headers):
        return self._request("POST", f"/machine-setups/{setup_id}/abort", {}, headers)

    # ── Stress relief ovens ──────────────────────────────────────────────────
    def create_oven(self, payload: Json, headers: Headers):
        return self._request("POST", "/stress-relief-ovens", payload, headers)

    def get_oven(self, oven_id: str, headers: Headers):
        return self._request("GET", f"/stress-relief-ovens/{oven_id}", headers=headers)

    # ── Production runs ──────────────────────────────────────────────────────
    def create_run(self, payload: Json, headers: Headers):
        return self._request("POST", "/production-runs", payload, headers)

    def get_run(self, run_id: str, headers: Headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_runs(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def record_fai(self, run_id: str, payload: Json, headers: Headers):
        return self._request("POST", f"/production-runs/{run_id}/fai", payload, headers)

    def dispose_fai(self, run_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/production-runs/{run_id}/fai-disposition", payload, headers
        )

    def record_inspection(self, run_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/production-runs/{run_id}/inspections", payload, headers
        )

    def quality_disposition(self, run_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/production-runs/{run_id}/quality-disposition", payload, headers
        )

    def complete_run(self, run_id: str, payload: Json, headers: Headers):
        return self._request("POST", f"/production-runs/{run_id}/complete", payload, headers)

    def cancel_run(self, run_id: str, headers: Headers):
        return self._request("POST", f"/production-runs/{run_id}/cancel", {}, headers)

    # ── Inspection records ───────────────────────────────────────────────────
    def get_inspection_record(self, record_id: str, headers: Headers):
        return self._request("GET", f"/inspection-records/{record_id}", headers=headers)

    def list_inspection_records(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/inspection-records", headers=headers, params=params)

    # ── Heat treat batches ───────────────────────────────────────────────────
    def create_batch(self, payload: Json, headers: Headers):
        return self._request("POST", "/heat-treat-batches", payload, headers)

    def get_batch(self, batch_id: str, headers: Headers):
        return self._request("GET", f"/heat-treat-batches/{batch_id}", headers=headers)

    def list_batches(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/heat-treat-batches", headers=headers, params=params)

    def start_batch(self, batch_id: str, headers: Headers):
        return self._request("POST", f"/heat-treat-batches/{batch_id}/start", {}, headers)

    def complete_batch(self, batch_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/heat-treat-batches/{batch_id}/complete", payload, headers
        )

    def cancel_batch(self, batch_id: str, headers: Headers):
        return self._request("POST", f"/heat-treat-batches/{batch_id}/cancel", {}, headers)

    # ── Qualification submissions ────────────────────────────────────────────
    def create_submission(self, payload: Json, headers: Headers):
        return self._request("POST", "/qualification-submissions", payload, headers)

    def get_submission(self, submission_id: str, headers: Headers):
        return self._request(
            "GET", f"/qualification-submissions/{submission_id}", headers=headers
        )

    def list_submissions(self, headers: Headers, params: Optional[Json] = None):
        return self._request(
            "GET", "/qualification-submissions", headers=headers, params=params
        )

    def review_submission(self, submission_id: str, payload: Json, headers: Headers):
        return self._request(
            "POST", f"/qualification-submissions/{submission_id}/review", payload, headers
        )

    def resubmit_submission(self, submission_id: str, headers: Headers):
        return self._request(
            "POST", f"/qualification-submissions/{submission_id}/resubmit", {}, headers
        )

    # ── Shipment lots ────────────────────────────────────────────────────────
    def create_lot(self, payload: Json, headers: Headers):
        return self._request("POST", "/shipment-lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Headers):
        return self._request("GET", f"/shipment-lots/{lot_id}", headers=headers)

    def list_lots(self, headers: Headers, params: Optional[Json] = None):
        return self._request("GET", "/shipment-lots", headers=headers, params=params)

    def pack_lot(self, lot_id: str, payload: Json, headers: Headers):
        return self._request("POST", f"/shipment-lots/{lot_id}/pack", payload, headers)

    def ship_lot(self, lot_id: str, headers: Headers):
        return self._request("POST", f"/shipment-lots/{lot_id}/ship", {}, headers)

    def return_lot(self, lot_id: str, headers: Headers):
        return self._request("POST", f"/shipment-lots/{lot_id}/return", {}, headers)

    def quarantine_lot(self, lot_id: str, payload: Json, headers: Headers):
        return self._request("POST", f"/shipment-lots/{lot_id}/quarantine", payload, headers)

    def release_lot_from_quarantine(self, lot_id: str, headers: Headers):
        return self._request(
            "POST", f"/shipment-lots/{lot_id}/release-from-quarantine", {}, headers
        )

    # ── The logical shop clock ───────────────────────────────────────────────
    def set_clock(self, payload: Json, headers: Headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
