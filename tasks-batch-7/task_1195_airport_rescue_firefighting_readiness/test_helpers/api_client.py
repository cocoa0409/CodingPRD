"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/arff/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Airport profile ----
    def create_profile(self, payload, headers):
        return self._request("POST", "/arff/airport-profile", payload, headers)

    def get_profile(self, headers):
        return self._request("GET", "/arff/airport-profile", headers=headers)

    def get_readiness(self, headers):
        return self._request(
            "GET", "/arff/airport-profile/readiness", headers=headers,
        )

    # ---- Aircraft ----
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/arff/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/arff/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request(
            "GET", f"/arff/aircraft/{aircraft_id}", headers=headers,
        )

    def patch_aircraft(self, aircraft_id, payload, headers):
        return self._request(
            "PATCH", f"/arff/aircraft/{aircraft_id}", payload, headers,
        )

    def list_aircraft_index_determinations(self, aircraft_id, headers, params=None):
        return self._request(
            "GET", f"/arff/aircraft/{aircraft_id}/index-determinations",
            headers=headers, params=params,
        )

    def list_aircraft_incidents(self, aircraft_id, headers, params=None):
        return self._request(
            "GET", f"/arff/aircraft/{aircraft_id}/incidents",
            headers=headers, params=params,
        )

    # ---- Vehicles ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/arff/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/arff/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/arff/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_readiness_checks(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/arff/vehicles/{vehicle_id}/readiness-checks",
            headers=headers, params=params,
        )

    def list_vehicle_oos_events(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/arff/vehicles/{vehicle_id}/out-of-service-events",
            headers=headers, params=params,
        )

    # ---- Readiness checks ----
    def create_readiness_check(self, payload, headers):
        return self._request("POST", "/arff/readiness-checks", payload, headers)

    # ---- Firefighters ----
    def create_firefighter(self, payload, headers):
        return self._request("POST", "/arff/firefighters", payload, headers)

    def list_firefighters(self, headers, params=None):
        return self._request("GET", "/arff/firefighters", headers=headers, params=params)

    def get_firefighter(self, firefighter_id, headers):
        return self._request(
            "GET", f"/arff/firefighters/{firefighter_id}", headers=headers,
        )

    def list_firefighter_training_records(self, firefighter_id, headers, params=None):
        return self._request(
            "GET", f"/arff/firefighters/{firefighter_id}/training-records",
            headers=headers, params=params,
        )

    def suspend_firefighter(self, firefighter_id, headers):
        return self._request(
            "POST", f"/arff/firefighters/{firefighter_id}/suspend", headers=headers,
        )

    def reactivate_firefighter(self, firefighter_id, headers):
        return self._request(
            "POST", f"/arff/firefighters/{firefighter_id}/reactivate", headers=headers,
        )

    # ---- Live-fire training records ----
    def create_training_record(self, payload, headers):
        return self._request(
            "POST", "/arff/live-fire-training-records", payload, headers,
        )

    # ---- Response drills ----
    def create_response_drill(self, payload, headers):
        return self._request("POST", "/arff/response-drills", payload, headers)

    def list_response_drills(self, headers, params=None):
        return self._request(
            "GET", "/arff/response-drills", headers=headers, params=params,
        )

    def get_response_drill(self, drill_id, headers):
        return self._request(
            "GET", f"/arff/response-drills/{drill_id}", headers=headers,
        )

    def execute_response_drill(self, drill_id, payload, headers):
        return self._request(
            "POST", f"/arff/response-drills/{drill_id}/execute", payload, headers,
        )

    def certify_response_drill(self, drill_id, headers):
        return self._request(
            "POST", f"/arff/response-drills/{drill_id}/certify", headers=headers,
        )

    def fail_response_drill(self, drill_id, headers):
        return self._request(
            "POST", f"/arff/response-drills/{drill_id}/fail", headers=headers,
        )

    # ---- Index determinations ----
    def create_index_determination(self, payload, headers):
        return self._request("POST", "/arff/index-determinations", payload, headers)

    # ---- Incidents ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/arff/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/arff/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/arff/incidents/{incident_id}", headers=headers)

    def respond_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/arff/incidents/{incident_id}/respond", headers=headers,
        )

    def control_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/arff/incidents/{incident_id}/control", headers=headers,
        )

    def close_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/arff/incidents/{incident_id}/close", headers=headers,
        )

    def patch_incident_alert_level(self, incident_id, payload, headers):
        return self._request(
            "PATCH", f"/arff/incidents/{incident_id}/alert-level", payload, headers,
        )

    def list_incident_mutual_aid_requests(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/arff/incidents/{incident_id}/mutual-aid-requests",
            headers=headers, params=params,
        )

    def list_incident_reports(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/arff/incidents/{incident_id}/reports",
            headers=headers, params=params,
        )

    def create_incident_report(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/arff/incidents/{incident_id}/reports", payload, headers,
        )

    # ---- Mutual aid ----
    def create_mutual_aid_agreement(self, payload, headers):
        return self._request(
            "POST", "/arff/mutual-aid-agreements", payload, headers,
        )

    def list_mutual_aid_agreements(self, headers, params=None):
        return self._request(
            "GET", "/arff/mutual-aid-agreements", headers=headers, params=params,
        )

    def get_mutual_aid_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/arff/mutual-aid-agreements/{agreement_id}", headers=headers,
        )

    def activate_mutual_aid_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/arff/mutual-aid-agreements/{agreement_id}/activate",
            headers=headers,
        )

    def terminate_mutual_aid_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/arff/mutual-aid-agreements/{agreement_id}/terminate",
            headers=headers,
        )

    def list_agreement_mutual_aid_requests(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/arff/mutual-aid-agreements/{agreement_id}/mutual-aid-requests",
            headers=headers, params=params,
        )

    def create_mutual_aid_request(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/arff/incidents/{incident_id}/mutual-aid-requests",
            payload, headers,
        )

    def deploy_mutual_aid_request(self, request_id, headers):
        return self._request(
            "POST", f"/arff/mutual-aid-requests/{request_id}/deploy", headers=headers,
        )

    def release_mutual_aid_request(self, request_id, headers):
        return self._request(
            "POST", f"/arff/mutual-aid-requests/{request_id}/release", headers=headers,
        )

    def decline_mutual_aid_request(self, request_id, headers):
        return self._request(
            "POST", f"/arff/mutual-aid-requests/{request_id}/decline", headers=headers,
        )

    # ---- Out-of-service & notifications ----
    def create_out_of_service_event(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/arff/vehicles/{vehicle_id}/out-of-service-events",
            payload, headers,
        )

    def restore_out_of_service_event(self, event_id, headers):
        return self._request(
            "POST", f"/arff/out-of-service-events/{event_id}/restore", headers=headers,
        )

    def list_index_downgrade_notifications(self, headers, params=None):
        return self._request(
            "GET", "/arff/index-downgrade-notifications",
            headers=headers, params=params,
        )

    def get_index_downgrade_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/arff/index-downgrade-notifications/{notification_id}",
            headers=headers,
        )

    def acknowledge_index_downgrade_notification(self, notification_id, headers):
        return self._request(
            "POST",
            f"/arff/index-downgrade-notifications/{notification_id}/acknowledge",
            headers=headers,
        )

    # ---- Incident reports / reviews ----
    def get_incident_report(self, report_id, headers):
        return self._request(
            "GET", f"/arff/incident-reports/{report_id}", headers=headers,
        )

    def patch_incident_report(self, report_id, payload, headers):
        return self._request(
            "PATCH", f"/arff/incident-reports/{report_id}", payload, headers,
        )

    def submit_incident_report(self, report_id, headers):
        return self._request(
            "POST", f"/arff/incident-reports/{report_id}/submit", headers=headers,
        )

    def accept_incident_report(self, report_id, headers):
        return self._request(
            "POST", f"/arff/incident-reports/{report_id}/accept", headers=headers,
        )

    def return_incident_report(self, report_id, headers):
        return self._request(
            "POST", f"/arff/incident-reports/{report_id}/return", headers=headers,
        )

    def create_post_incident_review(self, report_id, payload, headers):
        return self._request(
            "POST", f"/arff/incident-reports/{report_id}/post-incident-reviews",
            payload, headers,
        )

    def list_post_incident_reviews(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/arff/incident-reports/{report_id}/post-incident-reviews",
            headers=headers, params=params,
        )

    def patch_post_incident_review(self, review_id, payload, headers):
        return self._request(
            "PATCH", f"/arff/post-incident-reviews/{review_id}", payload, headers,
        )

    def close_post_incident_review(self, review_id, headers):
        return self._request(
            "POST", f"/arff/post-incident-reviews/{review_id}/close", headers=headers,
        )

    # ---- FAA inspections ----
    def create_faa_inspection(self, payload, headers):
        return self._request("POST", "/arff/faa-inspections", payload, headers)

    def list_faa_inspections(self, headers, params=None):
        return self._request(
            "GET", "/arff/faa-inspections", headers=headers, params=params,
        )

    def get_faa_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/arff/faa-inspections/{inspection_id}", headers=headers,
        )

    def begin_faa_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/arff/faa-inspections/{inspection_id}/begin", headers=headers,
        )

    def issue_findings_faa_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/arff/faa-inspections/{inspection_id}/issue-findings",
            payload, headers,
        )

    def conclude_faa_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/arff/faa-inspections/{inspection_id}/conclude",
            payload, headers,
        )


api_client = ApiClient()
