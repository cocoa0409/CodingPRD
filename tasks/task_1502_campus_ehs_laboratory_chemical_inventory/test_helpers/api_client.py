"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ehs/_clock/set_current_utc", payload, headers)

    # --- labs ---
    def create_lab(self, payload, headers):
        return self._request("POST", "/ehs/labs", payload, headers)

    def list_labs(self, headers, params=None):
        return self._request("GET", "/ehs/labs", headers=headers, params=params)

    def get_lab(self, lab_id, headers):
        return self._request("GET", f"/ehs/labs/{lab_id}", headers=headers)

    def closeout_lab(self, lab_id, headers):
        return self._request("POST", f"/ehs/labs/{lab_id}/closeout", {}, headers)

    def decommission_lab(self, lab_id, headers):
        return self._request("POST", f"/ehs/labs/{lab_id}/decommission", {}, headers)

    # --- workers ---
    def create_worker(self, payload, headers):
        return self._request("POST", "/ehs/workers", payload, headers)

    def list_lab_workers(self, lab_id, headers, params=None):
        return self._request("GET", f"/ehs/labs/{lab_id}/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/ehs/workers/{worker_id}", headers=headers)

    # --- containers ---
    def create_container(self, payload, headers):
        return self._request("POST", "/ehs/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/ehs/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/ehs/containers/{container_id}", headers=headers)

    def tag_waste(self, container_id, payload, headers):
        return self._request("POST", f"/ehs/containers/{container_id}/tag-waste", payload, headers)

    def untag_waste(self, container_id, headers):
        return self._request("POST", f"/ehs/containers/{container_id}/untag-waste", {}, headers)

    # --- accumulation areas ---
    def create_accumulation_area(self, payload, headers):
        return self._request("POST", "/ehs/accumulation-areas", payload, headers)

    def list_accumulation_areas(self, lab_id, headers, params=None):
        return self._request(
            "GET", f"/ehs/labs/{lab_id}/accumulation-areas", headers=headers, params=params
        )

    # --- waste pickup requests ---
    def create_pickup_request(self, payload, headers):
        return self._request("POST", "/ehs/waste-pickup-requests", payload, headers)

    def list_pickup_requests(self, headers, params=None):
        return self._request("GET", "/ehs/waste-pickup-requests", headers=headers, params=params)

    def get_pickup_request(self, pickup_id, headers):
        return self._request("GET", f"/ehs/waste-pickup-requests/{pickup_id}", headers=headers)

    def add_pickup_item(self, pickup_id, payload, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/add-item", payload, headers
        )

    def remove_pickup_item(self, pickup_id, payload, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/remove-item", payload, headers
        )

    def submit_pickup_request(self, pickup_id, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/submit", {}, headers
        )

    def reject_pickup_request(self, pickup_id, payload, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/reject", payload, headers
        )

    def schedule_pickup_request(self, pickup_id, payload, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/schedule", payload, headers
        )

    def complete_pickup_request(self, pickup_id, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/complete", {}, headers
        )

    def cancel_pickup_request(self, pickup_id, headers):
        return self._request(
            "POST", f"/ehs/waste-pickup-requests/{pickup_id}/cancel", {}, headers
        )

    # --- inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/ehs/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/ehs/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/ehs/inspections/{inspection_id}", headers=headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/ehs/inspections/{inspection_id}/complete", payload, headers
        )

    # --- corrective actions ---
    def list_lab_corrective_actions(self, lab_id, headers, params=None):
        return self._request(
            "GET", f"/ehs/labs/{lab_id}/corrective-actions", headers=headers, params=params
        )

    def list_inspection_corrective_actions(self, inspection_id, headers, params=None):
        return self._request(
            "GET",
            f"/ehs/inspections/{inspection_id}/corrective-actions",
            headers=headers,
            params=params,
        )

    def submit_corrective_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/ehs/corrective-actions/{action_id}/submit", payload, headers
        )

    def verify_corrective_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/ehs/corrective-actions/{action_id}/verify", payload, headers
        )

    # --- training assignments ---
    def create_training_assignment(self, payload, headers):
        return self._request("POST", "/ehs/training-assignments", payload, headers)

    def list_lab_training_assignments(self, lab_id, headers, params=None):
        return self._request(
            "GET", f"/ehs/labs/{lab_id}/training-assignments", headers=headers, params=params
        )

    def list_worker_training_assignments(self, worker_id, headers, params=None):
        return self._request(
            "GET",
            f"/ehs/workers/{worker_id}/training-assignments",
            headers=headers,
            params=params,
        )

    def complete_training_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/ehs/training-assignments/{assignment_id}/complete", {}, headers
        )

    # --- incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/ehs/incidents", payload, headers)

    def list_lab_incidents(self, lab_id, headers, params=None):
        return self._request(
            "GET", f"/ehs/labs/{lab_id}/incidents", headers=headers, params=params
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/ehs/incidents/{incident_id}/close", payload, headers)

    # --- registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/ehs/registrations", payload, headers)

    def list_lab_registrations(self, lab_id, headers, params=None):
        return self._request(
            "GET", f"/ehs/labs/{lab_id}/registrations", headers=headers, params=params
        )

    def activate_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/ehs/registrations/{registration_id}/activate", {}, headers
        )

    def suspend_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/ehs/registrations/{registration_id}/suspend", {}, headers
        )

    def surrender_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/ehs/registrations/{registration_id}/surrender", {}, headers
        )


api_client = ApiClient()
