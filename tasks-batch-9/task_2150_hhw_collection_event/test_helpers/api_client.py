"""API client: one method per endpoint published by the contract.

Every path is mounted under the `/hhw` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/hhw"


class ApiClient(GenericApiClient):
    # ─── Program ──────────────────────────────────────

    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}", headers=headers)

    def get_cost_summary(self, program_id, headers):
        return self._request(
            "GET", f"{PREFIX}/programs/{program_id}/cost-summary", headers=headers
        )

    def set_posture_override(self, program_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/posture-override", payload, headers
        )

    # ─── Site ─────────────────────────────────────────

    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def site_transition(self, site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sites/{site_id}/transitions", payload, headers
        )

    # ─── MaterialCategory ─────────────────────────────

    def create_material_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/material-categories", payload, headers)

    def list_material_categories(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/material-categories", headers=headers, params=params
        )

    def get_material_category(self, category_id, headers):
        return self._request(
            "GET", f"{PREFIX}/material-categories/{category_id}", headers=headers
        )

    # ─── Resident ─────────────────────────────────────

    def create_resident(self, payload, headers):
        return self._request("POST", f"{PREFIX}/residents", payload, headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/residents", headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"{PREFIX}/residents/{resident_id}", headers=headers)

    def resident_eligibility_action(self, resident_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/residents/{resident_id}/eligibility-actions",
            payload,
            headers,
        )

    # ─── CollectionEvent ──────────────────────────────

    def create_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/events/{event_id}", headers=headers)

    def event_transition(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/transitions", payload, headers
        )

    def file_containment_inspection(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/events/{event_id}/containment-inspections", payload, headers
        )

    # ─── Staffer ──────────────────────────────────────

    def create_staffer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/staffers", payload, headers)

    def list_staffers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/staffers", headers=headers, params=params)

    def get_staffer(self, staffer_id, headers):
        return self._request("GET", f"{PREFIX}/staffers/{staffer_id}", headers=headers)

    # ─── LaneAssignment ───────────────────────────────

    def create_lane_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lane-assignments", payload, headers)

    def list_lane_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lane-assignments", headers=headers, params=params
        )

    def get_lane_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lane-assignments/{assignment_id}", headers=headers
        )

    def release_lane_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lane-assignments/{assignment_id}/release", payload, headers
        )

    # ─── Appointment ──────────────────────────────────

    def create_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/appointments", headers=headers, params=params
        )

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/appointments/{appointment_id}", headers=headers
        )

    def appointment_transition(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/appointments/{appointment_id}/transitions", payload, headers
        )

    # ─── DropoffLine ──────────────────────────────────

    def create_dropoff_line(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dropoff-lines", payload, headers)

    def list_dropoff_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dropoff-lines", headers=headers, params=params
        )

    def get_dropoff_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/dropoff-lines/{line_id}", headers=headers)

    # ─── PackedContainer ──────────────────────────────

    def create_container(self, payload, headers):
        return self._request("POST", f"{PREFIX}/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"{PREFIX}/containers/{container_id}", headers=headers)

    def pack_line(self, container_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/containers/{container_id}/lines", payload, headers
        )

    def container_transition(self, container_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/containers/{container_id}/transitions", payload, headers
        )

    # ─── Manifest ─────────────────────────────────────

    def create_manifest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"{PREFIX}/manifests/{manifest_id}", headers=headers)

    def manifest_transition(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/manifests/{manifest_id}/transitions", payload, headers
        )

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
