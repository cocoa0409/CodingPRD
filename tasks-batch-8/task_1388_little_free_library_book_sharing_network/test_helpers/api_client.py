"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Stewards
    # ------------------------------------------------------------------
    def create_steward(self, payload, headers):
        return self._request("POST", "/library-network/stewards", payload, headers)

    def list_stewards(self, headers, params=None):
        return self._request(
            "GET", "/library-network/stewards", headers=headers, params=params
        )

    def get_steward(self, steward_id, headers):
        return self._request(
            "GET", f"/library-network/stewards/{steward_id}", headers=headers
        )

    def patch_steward(self, steward_id, payload, headers):
        return self._request(
            "PATCH", f"/library-network/stewards/{steward_id}", payload, headers
        )

    def activate_steward(self, steward_id, headers):
        return self._request(
            "POST", f"/library-network/stewards/{steward_id}/activate", {}, headers
        )

    def suspend_steward(self, steward_id, headers):
        return self._request(
            "POST", f"/library-network/stewards/{steward_id}/suspend", {}, headers
        )

    def reinstate_steward(self, steward_id, headers):
        return self._request(
            "POST", f"/library-network/stewards/{steward_id}/reinstate", {}, headers
        )

    def retire_steward(self, steward_id, headers):
        return self._request(
            "POST", f"/library-network/stewards/{steward_id}/retire", {}, headers
        )

    def list_recognition_events(self, steward_id, headers, params=None):
        return self._request(
            "GET",
            f"/library-network/stewards/{steward_id}/recognition-events",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Training modules and completions
    # ------------------------------------------------------------------
    def create_training_module(self, payload, headers):
        return self._request(
            "POST", "/library-network/training-modules", payload, headers
        )

    def list_training_modules(self, headers, params=None):
        return self._request(
            "GET", "/library-network/training-modules", headers=headers, params=params
        )

    def get_training_module(self, module_id, headers):
        return self._request(
            "GET", f"/library-network/training-modules/{module_id}", headers=headers
        )

    def patch_training_module(self, module_id, payload, headers):
        return self._request(
            "PATCH", f"/library-network/training-modules/{module_id}", payload, headers
        )

    def create_training_completion(self, steward_id, payload, headers):
        return self._request(
            "POST",
            f"/library-network/stewards/{steward_id}/training-completions",
            payload,
            headers,
        )

    def list_training_completions(self, headers, params=None):
        return self._request(
            "GET",
            "/library-network/training-completions",
            headers=headers,
            params=params,
        )

    def get_training_completion(self, completion_id, headers):
        return self._request(
            "GET",
            f"/library-network/training-completions/{completion_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Library boxes and inspections
    # ------------------------------------------------------------------
    def create_box(self, payload, headers):
        return self._request("POST", "/library-network/boxes", payload, headers)

    def list_boxes(self, headers, params=None):
        return self._request(
            "GET", "/library-network/boxes", headers=headers, params=params
        )

    def get_box(self, box_id, headers):
        return self._request(
            "GET", f"/library-network/boxes/{box_id}", headers=headers
        )

    def transition_box_status(self, box_id, target_status, headers):
        return self._request(
            "POST",
            f"/library-network/boxes/{box_id}/status",
            {"target_status": target_status},
            headers,
        )

    def create_inspection(self, box_id, payload, headers):
        return self._request(
            "POST", f"/library-network/boxes/{box_id}/inspections", payload, headers
        )

    def list_inspections(self, box_id, headers, params=None):
        return self._request(
            "GET",
            f"/library-network/boxes/{box_id}/inspections",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Book items
    # ------------------------------------------------------------------
    def list_book_items(self, headers, params=None):
        return self._request(
            "GET", "/library-network/book-items", headers=headers, params=params
        )

    def get_book_item(self, item_id, headers):
        return self._request(
            "GET", f"/library-network/book-items/{item_id}", headers=headers
        )

    def grade_book_item(self, item_id, condition_grade, headers):
        return self._request(
            "PATCH",
            f"/library-network/book-items/{item_id}",
            {"condition_grade": condition_grade},
            headers,
        )

    # ------------------------------------------------------------------
    # Maintenance requests
    # ------------------------------------------------------------------
    def create_maintenance_request(self, payload, headers):
        return self._request(
            "POST", "/library-network/maintenance-requests", payload, headers
        )

    def list_maintenance_requests(self, headers, params=None):
        return self._request(
            "GET",
            "/library-network/maintenance-requests",
            headers=headers,
            params=params,
        )

    def get_maintenance_request(self, request_id, headers):
        return self._request(
            "GET",
            f"/library-network/maintenance-requests/{request_id}",
            headers=headers,
        )

    def triage_maintenance_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/library-network/maintenance-requests/{request_id}/triage",
            payload,
            headers,
        )

    def resolve_maintenance_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/library-network/maintenance-requests/{request_id}/resolve",
            payload,
            headers,
        )

    def reopen_maintenance_request(self, request_id, headers):
        return self._request(
            "POST",
            f"/library-network/maintenance-requests/{request_id}/reopen",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/library-network/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request(
            "GET", "/library-network/complaints", headers=headers, params=params
        )

    def get_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"/library-network/complaints/{complaint_id}", headers=headers
        )

    def triage_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/library-network/complaints/{complaint_id}/triage", {}, headers
        )

    def respond_complaint(self, complaint_id, response_text, headers):
        return self._request(
            "POST",
            f"/library-network/complaints/{complaint_id}/respond",
            {"response_text": response_text},
            headers,
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST",
            f"/library-network/complaints/{complaint_id}/resolve",
            payload,
            headers,
        )

    def escalate_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/library-network/complaints/{complaint_id}/escalate", {}, headers
        )

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST",
            f"/library-network/complaints/{complaint_id}/adjudicate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Schools
    # ------------------------------------------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", "/library-network/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request(
            "GET", "/library-network/schools", headers=headers, params=params
        )

    def get_school(self, school_id, headers):
        return self._request(
            "GET", f"/library-network/schools/{school_id}", headers=headers
        )

    def transition_school_status(self, school_id, target_status, headers):
        return self._request(
            "POST",
            f"/library-network/schools/{school_id}/status",
            {"target_status": target_status},
            headers,
        )

    # ------------------------------------------------------------------
    # Book drives
    # ------------------------------------------------------------------
    def create_drive(self, payload, headers):
        return self._request("POST", "/library-network/drives", payload, headers)

    def list_drives(self, headers, params=None):
        return self._request(
            "GET", "/library-network/drives", headers=headers, params=params
        )

    def get_drive(self, drive_id, headers):
        return self._request(
            "GET", f"/library-network/drives/{drive_id}", headers=headers
        )

    def drive_school_decision(self, drive_id, decision, headers):
        return self._request(
            "POST",
            f"/library-network/drives/{drive_id}/school-decision",
            {"decision": decision},
            headers,
        )

    def drive_network_decision(self, drive_id, decision, headers):
        return self._request(
            "POST",
            f"/library-network/drives/{drive_id}/network-decision",
            {"decision": decision},
            headers,
        )

    def transition_drive_status(self, drive_id, target_status, headers):
        return self._request(
            "POST",
            f"/library-network/drives/{drive_id}/status",
            {"target_status": target_status},
            headers,
        )

    # ------------------------------------------------------------------
    # Donation batches and distribution runs
    # ------------------------------------------------------------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/library-network/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request(
            "GET", "/library-network/batches", headers=headers, params=params
        )

    def get_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/library-network/batches/{batch_id}", headers=headers
        )

    def intake_batch_items(self, batch_id, items, headers):
        return self._request(
            "POST",
            f"/library-network/batches/{batch_id}/items",
            {"items": items},
            headers,
        )

    def sort_complete_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/library-network/batches/{batch_id}/sort-complete", {}, headers
        )

    def create_distribution_run(self, batch_id, expected_batch_version, headers):
        return self._request(
            "POST",
            f"/library-network/batches/{batch_id}/distribution-runs",
            {"expected_batch_version": expected_batch_version},
            headers,
        )

    def list_distribution_runs(self, headers, params=None):
        return self._request(
            "GET", "/library-network/distribution-runs", headers=headers, params=params
        )

    def get_distribution_run(self, run_id, headers):
        return self._request(
            "GET", f"/library-network/distribution-runs/{run_id}", headers=headers
        )

    def list_run_allocations(self, run_id, headers, params=None):
        return self._request(
            "GET",
            f"/library-network/distribution-runs/{run_id}/allocations",
            headers=headers,
            params=params,
        )

    def confirm_distribution_run(self, run_id, headers):
        return self._request(
            "POST", f"/library-network/distribution-runs/{run_id}/confirm", {}, headers
        )

    def dispatch_distribution_run(self, run_id, headers):
        return self._request(
            "POST",
            f"/library-network/distribution-runs/{run_id}/dispatch",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Allocations
    # ------------------------------------------------------------------
    def list_allocations(self, headers, params=None):
        return self._request(
            "GET", "/library-network/allocations", headers=headers, params=params
        )

    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/library-network/allocations/{allocation_id}", headers=headers
        )

    def receive_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/library-network/allocations/{allocation_id}/receive", {}, headers
        )

    def cancel_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/library-network/allocations/{allocation_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Ops: map sweep
    # ------------------------------------------------------------------
    def run_map_sweep(self, headers):
        return self._request("POST", "/library-network/map/sweeps", {}, headers)


api_client = ApiClient()
