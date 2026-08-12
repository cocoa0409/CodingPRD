"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Agency bootstrap & logical clock
    # ------------------------------------------------------------------
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Homes
    # ------------------------------------------------------------------
    def create_home(self, payload, headers):
        return self._request("POST", "/homes", payload, headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/homes", headers=headers, params=params)

    def get_home(self, home_id, headers):
        return self._request("GET", f"/homes/{home_id}", headers=headers)

    def suspend_home(self, home_id, headers):
        return self._request("POST", f"/homes/{home_id}/suspend", headers=headers)

    def reinstate_home(self, home_id, headers):
        return self._request("POST", f"/homes/{home_id}/reinstate", headers=headers)

    def close_home(self, home_id, headers):
        return self._request("POST", f"/homes/{home_id}/close", headers=headers)

    def get_home_census(self, home_id, headers, as_of_date):
        return self._request(
            "GET", f"/homes/{home_id}/census",
            headers=headers, params={"as_of_date": as_of_date},
        )

    def get_home_staffing_check(self, home_id, headers, shift_date, shift_type):
        return self._request(
            "GET", f"/homes/{home_id}/staffing-check",
            headers=headers,
            params={"shift_date": shift_date, "shift_type": shift_type},
        )

    # ------------------------------------------------------------------
    # Individuals
    # ------------------------------------------------------------------
    def create_individual(self, payload, headers):
        return self._request("POST", "/individuals", payload, headers)

    def list_individuals(self, headers, params=None):
        return self._request("GET", "/individuals", headers=headers, params=params)

    def get_individual(self, individual_id, headers):
        return self._request("GET", f"/individuals/{individual_id}", headers=headers)

    def enroll_individual(self, individual_id, headers):
        return self._request(
            "POST", f"/individuals/{individual_id}/enroll", headers=headers,
        )

    def discharge_individual(self, individual_id, headers):
        return self._request(
            "POST", f"/individuals/{individual_id}/discharge", headers=headers,
        )

    def get_med_adherence(self, individual_id, headers, as_of):
        return self._request(
            "GET", f"/individuals/{individual_id}/med-adherence",
            headers=headers, params={"as_of": as_of},
        )

    # ------------------------------------------------------------------
    # ISPs
    # ------------------------------------------------------------------
    def create_isp(self, payload, headers):
        return self._request("POST", "/isps", payload, headers)

    def list_isps(self, headers, params=None):
        return self._request("GET", "/isps", headers=headers, params=params)

    def get_isp(self, isp_id, headers):
        return self._request("GET", f"/isps/{isp_id}", headers=headers)

    def submit_isp_review(self, isp_id, headers):
        return self._request("POST", f"/isps/{isp_id}/submit-review", headers=headers)

    def approve_isp(self, isp_id, headers):
        return self._request("POST", f"/isps/{isp_id}/approve", headers=headers)

    def return_isp(self, isp_id, headers, payload=None):
        return self._request("POST", f"/isps/{isp_id}/return", payload, headers)

    def activate_isp(self, isp_id, headers):
        return self._request("POST", f"/isps/{isp_id}/activate", headers=headers)

    def amend_isp(self, isp_id, payload, headers):
        return self._request("POST", f"/isps/{isp_id}/amend", payload, headers)

    # ------------------------------------------------------------------
    # Service authorizations
    # ------------------------------------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", "/authorizations", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def get_authorization(self, auth_id, headers):
        return self._request("GET", f"/authorizations/{auth_id}", headers=headers)

    def approve_authorization(self, auth_id, headers):
        return self._request(
            "POST", f"/authorizations/{auth_id}/approve", headers=headers,
        )

    def cancel_authorization(self, auth_id, headers):
        return self._request(
            "POST", f"/authorizations/{auth_id}/cancel", headers=headers,
        )

    def resume_authorization(self, auth_id, headers):
        return self._request(
            "POST", f"/authorizations/{auth_id}/resume", headers=headers,
        )

    # ------------------------------------------------------------------
    # Staff
    # ------------------------------------------------------------------
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def terminate_staff(self, staff_id, headers):
        return self._request("POST", f"/staff/{staff_id}/terminate", headers=headers)

    # ------------------------------------------------------------------
    # Shifts
    # ------------------------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def confirm_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/confirm", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # Bed assignments
    # ------------------------------------------------------------------
    def create_bed_assignment(self, payload, headers):
        return self._request("POST", "/bed-assignments", payload, headers)

    def get_bed_assignment(self, ba_id, headers):
        return self._request("GET", f"/bed-assignments/{ba_id}", headers=headers)

    def list_bed_assignments(self, headers, params=None):
        return self._request("GET", "/bed-assignments", headers=headers, params=params)

    def move_in_bed_assignment(self, ba_id, headers):
        return self._request(
            "POST", f"/bed-assignments/{ba_id}/move-in", headers=headers,
        )

    def move_out_bed_assignment(self, ba_id, headers, payload=None):
        return self._request(
            "POST", f"/bed-assignments/{ba_id}/move-out", payload, headers,
        )

    def cancel_bed_assignment(self, ba_id, headers):
        return self._request(
            "POST", f"/bed-assignments/{ba_id}/cancel", headers=headers,
        )

    # ------------------------------------------------------------------
    # Medication orders & MAR events
    # ------------------------------------------------------------------
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/medication-orders", payload, headers)

    def list_medication_orders(self, headers, params=None):
        return self._request(
            "GET", "/medication-orders", headers=headers, params=params,
        )

    def get_medication_order(self, mo_id, headers):
        return self._request("GET", f"/medication-orders/{mo_id}", headers=headers)

    def discontinue_medication_order(self, mo_id, headers):
        return self._request(
            "POST", f"/medication-orders/{mo_id}/discontinue", headers=headers,
        )

    def create_admin_event(self, payload, headers):
        return self._request("POST", "/admin-events", payload, headers)

    def get_admin_event(self, event_id, headers):
        return self._request("GET", f"/admin-events/{event_id}", headers=headers)

    def list_admin_events(self, headers, params=None):
        return self._request("GET", "/admin-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Behavior support plans
    # ------------------------------------------------------------------
    def create_behavior_plan(self, payload, headers):
        return self._request("POST", "/behavior-plans", payload, headers)

    def get_behavior_plan(self, bp_id, headers):
        return self._request("GET", f"/behavior-plans/{bp_id}", headers=headers)

    def list_behavior_plans(self, headers, params=None):
        return self._request("GET", "/behavior-plans", headers=headers, params=params)

    def submit_behavior_plan_hrc(self, bp_id, headers):
        return self._request(
            "POST", f"/behavior-plans/{bp_id}/submit-hrc", headers=headers,
        )

    def hrc_approve_behavior_plan(self, bp_id, headers):
        return self._request(
            "POST", f"/behavior-plans/{bp_id}/hrc-approve", headers=headers,
        )

    def hrc_reject_behavior_plan(self, bp_id, headers):
        return self._request(
            "POST", f"/behavior-plans/{bp_id}/hrc-reject", headers=headers,
        )

    def activate_behavior_plan(self, bp_id, headers):
        return self._request(
            "POST", f"/behavior-plans/{bp_id}/activate", headers=headers,
        )

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def submit_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/submit", headers=headers,
        )

    def start_incident_review(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/start-review", headers=headers,
        )

    def request_incident_info(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/request-info", headers=headers,
        )

    def resubmit_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/resubmit", headers=headers,
        )

    def close_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/close", headers=headers,
        )

    # ------------------------------------------------------------------
    # EVV visits
    # ------------------------------------------------------------------
    def create_evv_visit(self, payload, headers):
        return self._request("POST", "/evv-visits", payload, headers)

    def get_evv_visit(self, visit_id, headers):
        return self._request("GET", f"/evv-visits/{visit_id}", headers=headers)

    def list_evv_visits(self, headers, params=None):
        return self._request("GET", "/evv-visits", headers=headers, params=params)

    def verify_evv_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/evv-visits/{visit_id}/verify", headers=headers,
        )

    def flag_evv_exception(self, visit_id, headers):
        return self._request(
            "POST", f"/evv-visits/{visit_id}/flag-exception", headers=headers,
        )

    def resolve_evv_exception(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/evv-visits/{visit_id}/resolve-exception", payload, headers,
        )

    def reject_evv_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/evv-visits/{visit_id}/reject", payload, headers,
        )

    # ------------------------------------------------------------------
    # Transport trips
    # ------------------------------------------------------------------
    def create_transport_trip(self, payload, headers):
        return self._request("POST", "/transport-trips", payload, headers)

    def get_transport_trip(self, trip_id, headers):
        return self._request("GET", f"/transport-trips/{trip_id}", headers=headers)

    def list_transport_trips(self, headers, params=None):
        return self._request(
            "GET", "/transport-trips", headers=headers, params=params,
        )

    def cancel_transport_trip(self, trip_id, headers):
        return self._request(
            "POST", f"/transport-trips/{trip_id}/cancel", headers=headers,
        )

    # ------------------------------------------------------------------
    # Billing claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", headers=headers)

    def post_claim_payment(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/post-payment", payload, headers,
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def correct_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/correct", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/void", headers=headers)


api_client = ApiClient()
