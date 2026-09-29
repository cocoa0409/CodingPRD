"""HTTP client with one method per endpoint of the facilities capacity API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]

BASE = "/facilities"


class ApiClient(GenericApiClient):
    """Thin wrapper: every method names a single PRD endpoint."""

    # ------------------------------------------------------------ clock
    def set_clock(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/_clock/set_current_utc", json=payload, headers=headers)

    # ------------------------------------------------------------ schools
    def create_school(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/schools", json=payload, headers=headers)

    def get_school(self, school_id: str, headers: Headers = None):
        return self.get(f"{BASE}/schools/{school_id}", headers=headers)

    def get_reliance_report(self, school_id: str, headers: Headers = None):
        return self.get(f"{BASE}/schools/{school_id}/reliance-report", headers=headers)

    def get_reliance_summary(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/reliance-summary", headers=headers, params=params)

    # ------------------------------------------------------------ class size policies
    def create_class_size_policy(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/class-size-policies", json=payload, headers=headers)

    def get_class_size_policy(self, policy_id: str, headers: Headers = None):
        return self.get(f"{BASE}/class-size-policies/{policy_id}", headers=headers)

    # ------------------------------------------------------------ rooms
    def create_room(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/rooms", json=payload, headers=headers)

    def get_room(self, room_id: str, headers: Headers = None):
        return self.get(f"{BASE}/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/rooms", headers=headers, params=params)

    def patch_room(self, room_id: str, payload: Payload = None, headers: Headers = None):
        return self._request(
            "PATCH", f"{BASE}/rooms/{room_id}", payload=payload, headers=headers
        )

    # ------------------------------------------------------------ program set-asides
    def create_program_set_aside(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/program-set-asides", json=payload, headers=headers)

    def get_program_set_aside(self, set_aside_id: str, headers: Headers = None):
        return self.get(f"{BASE}/program-set-asides/{set_aside_id}", headers=headers)

    def list_program_set_asides(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/program-set-asides", headers=headers, params=params)

    # ------------------------------------------------------------ enrollment projections
    def create_enrollment_projection(
        self, payload: Payload = None, headers: Headers = None
    ):
        return self.post(f"{BASE}/enrollment-projections", json=payload, headers=headers)

    def get_enrollment_projection(self, projection_id: str, headers: Headers = None):
        return self.get(
            f"{BASE}/enrollment-projections/{projection_id}", headers=headers
        )

    def list_enrollment_projections(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/enrollment-projections", headers=headers, params=params)

    # ------------------------------------------------------------ capital budgets
    def create_capital_budget(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/capital-budgets", json=payload, headers=headers)

    def get_capital_budget(self, budget_id: str, headers: Headers = None):
        return self.get(f"{BASE}/capital-budgets/{budget_id}", headers=headers)

    # ------------------------------------------------------------ installation crews
    def create_installation_crew(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/installation-crews", json=payload, headers=headers)

    def get_installation_crew(self, crew_id: str, headers: Headers = None):
        return self.get(f"{BASE}/installation-crews/{crew_id}", headers=headers)

    # ------------------------------------------------------------ capacity studies
    def create_capacity_study(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/capacity-studies", json=payload, headers=headers)

    def get_capacity_study(self, study_id: str, headers: Headers = None):
        return self.get(f"{BASE}/capacity-studies/{study_id}", headers=headers)

    def list_capacity_studies(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/capacity-studies", headers=headers, params=params)

    def get_capacity_breakdown(self, study_id: str, headers: Headers = None):
        return self.get(
            f"{BASE}/capacity-studies/{study_id}/capacity-breakdown", headers=headers
        )

    def submit_study(
        self, study_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/capacity-studies/{study_id}/submit", json=payload, headers=headers
        )

    def certify_study(
        self, study_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/capacity-studies/{study_id}/certify", json=payload, headers=headers
        )

    def return_study(
        self, study_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/capacity-studies/{study_id}/return", json=payload, headers=headers
        )

    def reopen_study(
        self, study_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/capacity-studies/{study_id}/reopen", json=payload, headers=headers
        )

    # ------------------------------------------------------------ portable units
    def create_portable_unit(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/portable-units", json=payload, headers=headers)

    def get_portable_unit(self, unit_id: str, headers: Headers = None):
        return self.get(f"{BASE}/portable-units/{unit_id}", headers=headers)

    def list_portable_units(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/portable-units", headers=headers, params=params)

    def record_condition(
        self, unit_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/portable-units/{unit_id}/condition", json=payload, headers=headers
        )

    def record_existing_placement(
        self, unit_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/portable-units/{unit_id}/record-existing-placement",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------ placement sites
    def create_placement_site(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/placement-sites", json=payload, headers=headers)

    def get_placement_site(self, site_id: str, headers: Headers = None):
        return self.get(f"{BASE}/placement-sites/{site_id}", headers=headers)

    def list_placement_sites(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/placement-sites", headers=headers, params=params)

    def assess_placement_site(
        self, site_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-sites/{site_id}/assess", json=payload, headers=headers
        )

    # ------------------------------------------------------------ placement requests
    def create_placement_request(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/placement-requests", json=payload, headers=headers)

    def get_placement_request(self, request_id: str, headers: Headers = None):
        return self.get(f"{BASE}/placement-requests/{request_id}", headers=headers)

    def list_placement_requests(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/placement-requests", headers=headers, params=params)

    def get_cost_model(
        self, request_id: str, headers: Headers = None, params: Params = None
    ):
        return self.get(
            f"{BASE}/placement-requests/{request_id}/cost-model",
            headers=headers,
            params=params,
        )

    def auto_assign_unit(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-requests/{request_id}/auto-assign-unit",
            json=payload,
            headers=headers,
        )

    def assess_site(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-requests/{request_id}/assess-site",
            json=payload,
            headers=headers,
        )

    def submit_permits(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-requests/{request_id}/submit-permits",
            json=payload,
            headers=headers,
        )

    def withdraw_request(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-requests/{request_id}/withdraw",
            json=payload,
            headers=headers,
        )

    def request_decommission(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-requests/{request_id}/request-decommission",
            json=payload,
            headers=headers,
        )

    def complete_decommission(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/placement-requests/{request_id}/complete-decommission",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------ permits
    def get_permit(self, permit_id: str, headers: Headers = None):
        return self.get(f"{BASE}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/permits", headers=headers, params=params)

    def decide_permit(
        self, permit_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/permits/{permit_id}/decision", json=payload, headers=headers
        )

    def resubmit_permit(
        self, permit_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/permits/{permit_id}/resubmit", json=payload, headers=headers
        )

    # ------------------------------------------------------------ installation schedules
    def create_installation_schedule(
        self, payload: Payload = None, headers: Headers = None
    ):
        return self.post(f"{BASE}/installation-schedules", json=payload, headers=headers)

    def get_installation_schedule(self, schedule_id: str, headers: Headers = None):
        return self.get(f"{BASE}/installation-schedules/{schedule_id}", headers=headers)

    def list_installation_schedules(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/installation-schedules", headers=headers, params=params)

    def start_schedule(
        self, schedule_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/installation-schedules/{schedule_id}/start",
            json=payload,
            headers=headers,
        )

    def complete_schedule(
        self, schedule_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/installation-schedules/{schedule_id}/complete",
            json=payload,
            headers=headers,
        )

    def cancel_schedule(
        self, schedule_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"{BASE}/installation-schedules/{schedule_id}/cancel",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------ disposal records
    def create_disposal_record(self, payload: Payload = None, headers: Headers = None):
        return self.post(f"{BASE}/disposal-records", json=payload, headers=headers)

    def get_disposal_record(self, disposal_id: str, headers: Headers = None):
        return self.get(f"{BASE}/disposal-records/{disposal_id}", headers=headers)

    def list_disposal_records(self, headers: Headers = None, params: Params = None):
        return self.get(f"{BASE}/disposal-records", headers=headers, params=params)


api_client = ApiClient()
