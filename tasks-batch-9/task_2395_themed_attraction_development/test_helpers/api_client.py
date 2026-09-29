"""API client: one method per endpoint the PRD defines.

All resources are served at the API root; there is no shared URL prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── AttractionProject ────────────────────────────

    def create_project(self, payload, headers):
        return self._request("POST", "/attraction-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/attraction-projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/attraction-projects/{project_id}", headers=headers)

    def patch_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/attraction-projects/{project_id}", payload, headers)

    def advance_phase(self, project_id, payload, headers):
        return self._request(
            "POST", f"/attraction-projects/{project_id}/advance-phase", payload, headers
        )

    def get_capacity_summary(self, project_id, headers):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/capacity-summary", headers=headers
        )

    def get_budget_position(self, project_id, headers):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/budget-position", headers=headers
        )

    def list_project_ride_systems(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/ride-systems",
            headers=headers, params=params,
        )

    def list_project_queue_segments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/queue-segments",
            headers=headers, params=params,
        )

    def list_project_value_engineering_items(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/value-engineering-items",
            headers=headers, params=params,
        )

    def list_project_rehearsal_runs(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/rehearsal-runs",
            headers=headers, params=params,
        )

    def list_project_ledger_entries(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/budget-ledger-entries",
            headers=headers, params=params,
        )

    def list_project_maintenance_items(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/attraction-projects/{project_id}/maintenance-items",
            headers=headers, params=params,
        )

    # ─── RideSystem ───────────────────────────────────

    def create_ride_system(self, payload, headers):
        return self._request("POST", "/ride-systems", payload, headers)

    def get_ride_system(self, ride_system_id, headers):
        return self._request("GET", f"/ride-systems/{ride_system_id}", headers=headers)

    def patch_ride_system(self, ride_system_id, payload, headers):
        return self._request("PATCH", f"/ride-systems/{ride_system_id}", payload, headers)

    def select_ride_system(self, ride_system_id, payload, headers):
        return self._request(
            "POST", f"/ride-systems/{ride_system_id}/select", payload, headers
        )

    def mark_ride_system_engineered(self, ride_system_id, payload, headers):
        return self._request(
            "POST", f"/ride-systems/{ride_system_id}/mark-engineered", payload, headers
        )

    def commission_ride_system(self, ride_system_id, payload, headers):
        return self._request(
            "POST", f"/ride-systems/{ride_system_id}/commission", payload, headers
        )

    # ─── QueueSegment ─────────────────────────────────

    def create_queue_segment(self, payload, headers):
        return self._request("POST", "/queue-segments", payload, headers)

    def get_queue_segment(self, segment_id, headers):
        return self._request("GET", f"/queue-segments/{segment_id}", headers=headers)

    def accept_queue_segment(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/queue-segments/{segment_id}/accept", payload, headers
        )

    def retire_queue_segment(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/queue-segments/{segment_id}/retire", payload, headers
        )

    # ─── ShowScene ────────────────────────────────────

    def create_show_scene(self, payload, headers):
        return self._request("POST", "/show-scenes", payload, headers)

    def list_show_scenes(self, headers, params=None):
        return self._request("GET", "/show-scenes", headers=headers, params=params)

    def get_show_scene(self, scene_id, headers):
        return self._request("GET", f"/show-scenes/{scene_id}", headers=headers)

    def sequence_show_scene(self, scene_id, payload, headers):
        return self._request("POST", f"/show-scenes/{scene_id}/sequence", payload, headers)

    def program_show_scene(self, scene_id, payload, headers):
        return self._request("POST", f"/show-scenes/{scene_id}/program", payload, headers)

    def validate_show_scene(self, scene_id, payload, headers):
        return self._request("POST", f"/show-scenes/{scene_id}/validate", payload, headers)

    def list_scene_effect_cues(self, scene_id, headers, params=None):
        return self._request(
            "GET", f"/show-scenes/{scene_id}/effect-cues", headers=headers, params=params
        )

    # ─── EffectCue ────────────────────────────────────

    def create_effect_cue(self, payload, headers):
        return self._request("POST", "/effect-cues", payload, headers)

    def get_effect_cue(self, cue_id, headers):
        return self._request("GET", f"/effect-cues/{cue_id}", headers=headers)

    def verify_effect_cue(self, cue_id, payload, headers):
        return self._request("POST", f"/effect-cues/{cue_id}/verify", payload, headers)

    # ─── DesignPackage ────────────────────────────────

    def create_design_package(self, payload, headers):
        return self._request("POST", "/design-packages", payload, headers)

    def list_design_packages(self, headers, params=None):
        return self._request("GET", "/design-packages", headers=headers, params=params)

    def get_design_package(self, package_id, headers):
        return self._request("GET", f"/design-packages/{package_id}", headers=headers)

    def submit_design_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/design-packages/{package_id}/submit", payload, headers
        )

    def request_package_revision(self, package_id, payload, headers):
        return self._request(
            "POST", f"/design-packages/{package_id}/request-revision", payload, headers
        )

    def revise_design_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/design-packages/{package_id}/revise", payload, headers
        )

    def approve_design_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/design-packages/{package_id}/approve", payload, headers
        )

    def list_package_safety_reviews(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/design-packages/{package_id}/safety-reviews",
            headers=headers, params=params,
        )

    # ─── SafetyReview ─────────────────────────────────

    def create_safety_review(self, payload, headers):
        return self._request("POST", "/safety-reviews", payload, headers)

    def get_safety_review(self, review_id, headers):
        return self._request("GET", f"/safety-reviews/{review_id}", headers=headers)

    def clear_safety_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/safety-reviews/{review_id}/clear", payload, headers
        )

    def list_review_findings(self, review_id, headers, params=None):
        return self._request(
            "GET", f"/safety-reviews/{review_id}/findings", headers=headers, params=params
        )

    # ─── SafetyFinding ────────────────────────────────

    def create_safety_finding(self, payload, headers):
        return self._request("POST", "/safety-findings", payload, headers)

    def get_safety_finding(self, finding_id, headers):
        return self._request("GET", f"/safety-findings/{finding_id}", headers=headers)

    def resolve_safety_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/safety-findings/{finding_id}/resolve", payload, headers
        )

    def close_safety_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/safety-findings/{finding_id}/close", payload, headers
        )

    def waive_safety_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/safety-findings/{finding_id}/waive", payload, headers
        )

    # ─── ValueEngineeringItem / VEBallot ──────────────

    def create_value_engineering_item(self, payload, headers):
        return self._request("POST", "/value-engineering-items", payload, headers)

    def get_value_engineering_item(self, item_id, headers):
        return self._request(
            "GET", f"/value-engineering-items/{item_id}", headers=headers
        )

    def open_value_engineering_review(self, item_id, payload, headers):
        return self._request(
            "POST", f"/value-engineering-items/{item_id}/open-review", payload, headers
        )

    def list_value_engineering_ballots(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/value-engineering-items/{item_id}/ballots",
            headers=headers, params=params,
        )

    def create_ve_ballot(self, payload, headers):
        return self._request("POST", "/ve-ballots", payload, headers)

    # ─── RehearsalRun ─────────────────────────────────

    def create_rehearsal_run(self, payload, headers):
        return self._request("POST", "/rehearsal-runs", payload, headers)

    def get_rehearsal_run(self, run_id, headers):
        return self._request("GET", f"/rehearsal-runs/{run_id}", headers=headers)

    def complete_rehearsal_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/rehearsal-runs/{run_id}/complete", payload, headers
        )

    # ─── MaintenanceItem ──────────────────────────────

    def create_maintenance_item(self, payload, headers):
        return self._request("POST", "/maintenance-items", payload, headers)

    def get_maintenance_item(self, item_id, headers):
        return self._request("GET", f"/maintenance-items/{item_id}", headers=headers)

    def approve_maintenance_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-items/{item_id}/approve", payload, headers
        )

    def hand_over_maintenance_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-items/{item_id}/hand-over", payload, headers
        )

    # ─── BudgetLedgerEntry ────────────────────────────

    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/budget-ledger-entries", payload, headers)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/budget-ledger-entries/{entry_id}", headers=headers)

    def reverse_ledger_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/budget-ledger-entries/{entry_id}/reverse", payload, headers
        )


api_client = ApiClient()
