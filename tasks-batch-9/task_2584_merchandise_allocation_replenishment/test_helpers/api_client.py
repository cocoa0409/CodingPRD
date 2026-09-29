"""API client: one method per endpoint declared by the PRD.

Every path is prefixed with ``/allocation`` except the logical-clock control
endpoint, which the PRD mounts at ``/_clock/set_current_utc``.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/allocation"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- programs
    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/activate", payload or {}, headers
        )

    def lock_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/lock", payload or {}, headers
        )

    def unlock_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/unlock", payload or {}, headers
        )

    def close_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/close", payload or {}, headers
        )

    # ----------------------------------------------------------------- stores
    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stores", headers=headers, params=params)

    def set_store_status(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/status", payload, headers
        )

    # ---------------------------------------------------------- fixture plans
    def create_fixture_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fixture-plans", payload, headers)

    def get_fixture_plan(self, fixture_plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fixture-plans/{fixture_plan_id}", headers=headers
        )

    def list_fixture_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fixture-plans", headers=headers, params=params
        )

    # ----------------------------------------------------------- size profiles
    def create_size_profile(self, payload, headers):
        return self._request("POST", f"{PREFIX}/size-profiles", payload, headers)

    def get_size_profile(self, size_profile_id, headers):
        return self._request(
            "GET", f"{PREFIX}/size-profiles/{size_profile_id}", headers=headers
        )

    def list_size_profiles(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/size-profiles", headers=headers, params=params
        )

    # ------------------------------------------------------------------ items
    def create_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/items", headers=headers, params=params)

    def patch_item(self, item_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/items/{item_id}", payload, headers)

    # -------------------------------------------------------- store positions
    def create_store_position(self, payload, headers):
        return self._request("POST", f"{PREFIX}/store-positions", payload, headers)

    def get_store_position(self, position_id, headers):
        return self._request(
            "GET", f"{PREFIX}/store-positions/{position_id}", headers=headers
        )

    def list_store_positions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/store-positions", headers=headers, params=params
        )

    def patch_store_position(self, position_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/store-positions/{position_id}", payload, headers
        )

    # --------------------------------------------------------------- receipts
    def create_receipt(self, payload, headers):
        return self._request("POST", f"{PREFIX}/receipts", payload, headers)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"{PREFIX}/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/receipts", headers=headers, params=params)

    def close_receipt(self, receipt_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/receipts/{receipt_id}/close", payload or {}, headers
        )

    def adjust_receipt(self, receipt_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipts/{receipt_id}/adjust", payload, headers
        )

    def create_allocation_run(self, receipt_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/receipts/{receipt_id}/allocation-runs", payload, headers
        )

    # --------------------------------------------------------- allocation runs
    def get_allocation_run(self, run_id, headers):
        return self._request(
            "GET", f"{PREFIX}/allocation-runs/{run_id}", headers=headers
        )

    def list_allocation_runs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/allocation-runs", headers=headers, params=params
        )

    def propose_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/allocation-runs/{run_id}/propose", payload or {}, headers
        )

    def revise_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/allocation-runs/{run_id}/revise", payload or {}, headers
        )

    def commit_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/allocation-runs/{run_id}/commit", payload or {}, headers
        )

    def recall_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/allocation-runs/{run_id}/recall", payload or {}, headers
        )

    def cancel_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/allocation-runs/{run_id}/cancel", payload or {}, headers
        )

    # -------------------------------------------------------- allocation lines
    def get_allocation_line(self, line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/allocation-lines/{line_id}", headers=headers
        )

    def list_allocation_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/allocation-lines", headers=headers, params=params
        )

    def ship_line(self, line_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/allocation-lines/{line_id}/ship", payload or {}, headers
        )

    def confirm_line_receipt(self, line_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/allocation-lines/{line_id}/confirm-receipt",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------- promo events
    def create_promo_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/promo-events", payload, headers)

    def get_promo_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/promo-events/{event_id}", headers=headers
        )

    def list_promo_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/promo-events", headers=headers, params=params
        )

    def schedule_promo_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/promo-events/{event_id}/schedule", payload or {}, headers
        )

    def activate_promo_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/promo-events/{event_id}/activate", payload or {}, headers
        )

    def end_promo_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/promo-events/{event_id}/end", payload or {}, headers
        )

    def cancel_promo_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/promo-events/{event_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------ transfer recommendations
    def create_transfer_recommendation(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfer-recommendations", payload, headers
        )

    def get_transfer_recommendation(self, recommendation_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/transfer-recommendations/{recommendation_id}",
            headers=headers,
        )

    def list_transfer_recommendations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transfer-recommendations", headers=headers, params=params
        )

    def approve_transfer(self, recommendation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-recommendations/{recommendation_id}/approve",
            payload or {},
            headers,
        )

    def reject_transfer(self, recommendation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-recommendations/{recommendation_id}/reject",
            payload,
            headers,
        )

    def dispatch_transfer(self, recommendation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-recommendations/{recommendation_id}/dispatch",
            payload or {},
            headers,
        )

    def receive_transfer(self, recommendation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-recommendations/{recommendation_id}/receive",
            payload or {},
            headers,
        )

    def cancel_transfer(self, recommendation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-recommendations/{recommendation_id}/cancel",
            payload or {},
            headers,
        )

    # ----------------------------------------------------- assortment actions
    def run_assortment_detection(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_run-assortment-detection", payload, headers
        )

    def get_assortment_action(self, action_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assortment-actions/{action_id}", headers=headers
        )

    def list_assortment_actions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assortment-actions", headers=headers, params=params
        )

    def execute_assortment_action(self, action_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/assortment-actions/{action_id}/execute",
            payload or {},
            headers,
        )

    def cancel_assortment_action(self, action_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/assortment-actions/{action_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------- performance snapshots
    def create_performance_snapshot(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/performance-snapshots", payload, headers
        )

    def get_performance_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/performance-snapshots/{snapshot_id}", headers=headers
        )

    def list_performance_snapshots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/performance-snapshots", headers=headers, params=params
        )

    # ------------------------------------------------------- transfer expiry
    def run_transfer_expiry(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_run-transfer-expiry", payload, headers
        )


api_client = ApiClient()
