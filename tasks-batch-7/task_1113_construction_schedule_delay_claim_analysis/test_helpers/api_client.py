"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ConstructionProject ---
    def create_project(self, payload, headers):
        return self._request("POST", "/construction-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/construction-projects", headers=headers, params=params)

    def get_project(self, pid, headers):
        return self._request("GET", f"/construction-projects/{pid}", headers=headers)

    def activate_project(self, pid, headers):
        return self._request("POST", f"/construction-projects/{pid}/activate", {}, headers)

    def declare_substantial_completion(self, pid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/declare-substantial-completion", {}, headers
        )

    def close_project(self, pid, headers):
        return self._request("POST", f"/construction-projects/{pid}/close", {}, headers)

    # --- ScheduleVersion ---
    def create_schedule_version(self, pid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/schedule-versions", payload, headers
        )

    def list_schedule_versions(self, pid, headers, params=None):
        return self._request(
            "GET", f"/construction-projects/{pid}/schedule-versions", headers=headers, params=params
        )

    def get_schedule_version(self, pid, vid, headers):
        return self._request(
            "GET", f"/construction-projects/{pid}/schedule-versions/{vid}", headers=headers
        )

    def submit_schedule_version(self, pid, vid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/schedule-versions/{vid}/submit", {}, headers
        )

    def accept_schedule_version(self, pid, vid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/schedule-versions/{vid}/accept", payload, headers
        )

    def reject_schedule_version(self, pid, vid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/schedule-versions/{vid}/reject", {}, headers
        )

    def revise_schedule_version(self, pid, vid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/schedule-versions/{vid}/revise", {}, headers
        )

    # --- Activity ---
    def create_activity(self, pid, vid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/activities",
            payload,
            headers,
        )

    def list_activities(self, pid, vid, headers, params=None):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/schedule-versions/{vid}/activities",
            headers=headers,
            params=params,
        )

    def get_activity(self, pid, vid, aid, headers):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/schedule-versions/{vid}/activities/{aid}",
            headers=headers,
        )

    # --- ActivityRelationship ---
    def create_relationship(self, pid, vid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/relationships",
            payload,
            headers,
        )

    def list_relationships(self, pid, vid, headers, params=None):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/schedule-versions/{vid}/relationships",
            headers=headers,
            params=params,
        )

    # --- ProgressUpdate / ProgressEntry ---
    def create_progress_update(self, pid, vid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates",
            payload,
            headers,
        )

    def list_progress_updates(self, pid, vid, headers, params=None):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates",
            headers=headers,
            params=params,
        )

    def get_progress_update(self, pid, vid, puid, headers):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}",
            headers=headers,
        )

    def create_progress_entry(self, pid, vid, puid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/entries",
            payload,
            headers,
        )

    def list_progress_entries(self, pid, vid, puid, headers, params=None):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/entries",
            headers=headers,
            params=params,
        )

    def submit_progress_update(self, pid, vid, puid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/submit",
            {},
            headers,
        )

    def approve_progress_update(self, pid, vid, puid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/approve",
            {},
            headers,
        )

    def reject_progress_update(self, pid, vid, puid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/reject",
            {},
            headers,
        )

    def revise_progress_update(self, pid, vid, puid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/revise",
            {},
            headers,
        )

    # --- DelayEvent ---
    def create_delay_event(self, pid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/delay-events", payload, headers
        )

    def list_delay_events(self, pid, headers, params=None):
        return self._request(
            "GET", f"/construction-projects/{pid}/delay-events", headers=headers, params=params
        )

    def get_delay_event(self, pid, did, headers):
        return self._request(
            "GET", f"/construction-projects/{pid}/delay-events/{did}", headers=headers
        )

    def notice_delay_event(self, pid, did, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/delay-events/{did}/notice", {}, headers
        )

    def submit_tia(self, pid, did, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/delay-events/{did}/tia/submit", {}, headers
        )

    def accept_tia(self, pid, did, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/delay-events/{did}/tia/accept", {}, headers
        )

    def reject_tia(self, pid, did, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/delay-events/{did}/tia/reject", {}, headers
        )

    def resubmit_tia(self, pid, did, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/delay-events/{did}/resubmit", {}, headers
        )

    # --- TimeExtensionRequest ---
    def create_eot_request(self, pid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/eot-requests", payload, headers
        )

    def list_eot_requests(self, pid, headers, params=None):
        return self._request(
            "GET", f"/construction-projects/{pid}/eot-requests", headers=headers, params=params
        )

    def get_eot_request(self, pid, eid, headers):
        return self._request(
            "GET", f"/construction-projects/{pid}/eot-requests/{eid}", headers=headers
        )

    def submit_eot_request(self, pid, eid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/eot-requests/{eid}/submit", {}, headers
        )

    def begin_review_eot_request(self, pid, eid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/eot-requests/{eid}/begin-review", {}, headers
        )

    def approve_eot_request(self, pid, eid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/eot-requests/{eid}/approve", payload, headers
        )

    def partial_approve_eot_request(self, pid, eid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/eot-requests/{eid}/partial-approve",
            payload,
            headers,
        )

    def deny_eot_request(self, pid, eid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/eot-requests/{eid}/deny", {}, headers
        )

    def appeal_eot_request(self, pid, eid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/eot-requests/{eid}/appeal", {}, headers
        )

    # --- AccelerationDirective ---
    def create_acceleration_directive(self, pid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/acceleration-directives", payload, headers
        )

    def list_acceleration_directives(self, pid, headers, params=None):
        return self._request(
            "GET",
            f"/construction-projects/{pid}/acceleration-directives",
            headers=headers,
            params=params,
        )

    def get_acceleration_directive(self, pid, aid, headers):
        return self._request(
            "GET", f"/construction-projects/{pid}/acceleration-directives/{aid}", headers=headers
        )

    def acknowledge_acceleration_directive(self, pid, aid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/acceleration-directives/{aid}/acknowledge",
            {},
            headers,
        )

    def begin_performance_acceleration_directive(self, pid, aid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/acceleration-directives/{aid}/begin-performance",
            {},
            headers,
        )

    def complete_acceleration_directive(self, pid, aid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/acceleration-directives/{aid}/complete",
            payload,
            headers,
        )

    def dispute_acceleration_directive(self, pid, aid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/acceleration-directives/{aid}/dispute",
            {},
            headers,
        )

    def negotiate_acceleration_directive(self, pid, aid, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/acceleration-directives/{aid}/negotiate",
            {},
            headers,
        )

    def resolve_acceleration_directive(self, pid, aid, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{pid}/acceleration-directives/{aid}/resolve",
            payload,
            headers,
        )

    # --- LiquidatedDamagesAssessment ---
    def create_ld_assessment(self, pid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments", payload, headers
        )

    def list_ld_assessments(self, pid, headers, params=None):
        return self._request(
            "GET", f"/construction-projects/{pid}/ld-assessments", headers=headers, params=params
        )

    def get_ld_assessment(self, pid, lid, headers):
        return self._request(
            "GET", f"/construction-projects/{pid}/ld-assessments/{lid}", headers=headers
        )

    def assess_ld_assessment(self, pid, lid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments/{lid}/assess", {}, headers
        )

    def waive_ld_assessment(self, pid, lid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments/{lid}/waive", {}, headers
        )

    def appeal_ld_assessment(self, pid, lid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments/{lid}/appeal", {}, headers
        )

    def uphold_ld_assessment(self, pid, lid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments/{lid}/uphold", {}, headers
        )

    def reduce_ld_assessment(self, pid, lid, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments/{lid}/reduce", payload, headers
        )

    def reverse_ld_assessment(self, pid, lid, headers):
        return self._request(
            "POST", f"/construction-projects/{pid}/ld-assessments/{lid}/reverse", {}, headers
        )

    # --- Flat single-resource GET aliases (PRD §4) ---
    def get_schedule_version_flat(self, vid, headers):
        return self._request(
            "GET", f"/construction-projects/schedule-versions/{vid}", headers=headers
        )

    def get_activity_flat(self, aid, headers):
        return self._request("GET", f"/construction-projects/activities/{aid}", headers=headers)

    def get_relationship_flat(self, rid, headers):
        return self._request(
            "GET", f"/construction-projects/relationships/{rid}", headers=headers
        )

    def get_progress_update_flat(self, puid, headers):
        return self._request(
            "GET", f"/construction-projects/progress-updates/{puid}", headers=headers
        )

    def get_progress_entry_flat(self, peid, headers):
        return self._request(
            "GET", f"/construction-projects/progress-entries/{peid}", headers=headers
        )

    def get_delay_event_flat(self, did, headers):
        return self._request("GET", f"/construction-projects/delay-events/{did}", headers=headers)

    def get_eot_request_flat(self, eid, headers):
        return self._request("GET", f"/construction-projects/eot-requests/{eid}", headers=headers)

    def get_acceleration_directive_flat(self, aid, headers):
        return self._request(
            "GET", f"/construction-projects/acceleration-directives/{aid}", headers=headers
        )

    def get_ld_assessment_flat(self, lid, headers):
        return self._request(
            "GET", f"/construction-projects/ld-assessments/{lid}", headers=headers
        )

    # --- Flat filtered-list GET endpoints (FK reverse-reachability, PRD §4) ---
    def list_schedule_versions_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/schedule-versions", headers=headers, params=params
        )

    def list_activities_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/activities", headers=headers, params=params
        )

    def list_relationships_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/relationships", headers=headers, params=params
        )

    def list_progress_updates_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/progress-updates", headers=headers, params=params
        )

    def list_progress_entries_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/progress-entries", headers=headers, params=params
        )

    def list_delay_events_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/delay-events", headers=headers, params=params
        )

    def list_eot_requests_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/eot-requests", headers=headers, params=params
        )

    def list_acceleration_directives_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/acceleration-directives", headers=headers, params=params
        )

    def list_ld_assessments_flat(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects/ld-assessments", headers=headers, params=params
        )


api_client = ApiClient()
