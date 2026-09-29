"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- obstetric units ---------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", "/obstetric-units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/obstetric-units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/obstetric-units/{unit_id}", headers=headers)

    def patch_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/obstetric-units/{unit_id}", payload, headers)

    def get_capacity_summary(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/capacity-summary",
            headers=headers, params=params,
        )

    def get_coverage_report(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/coverage-report",
            headers=headers, params=params,
        )

    def get_readiness_report(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/readiness-report",
            headers=headers, params=params,
        )

    def capacity_sweep(self, unit_id, headers, payload=None):
        return self._request(
            "POST", f"/obstetric-units/{unit_id}/capacity-sweep", payload or {}, headers
        )

    # ---- staff members -----------------------------------------------------
    def create_staff_member(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/obstetric-units/{unit_id}/staff-members", payload, headers
        )

    def list_unit_staff_members(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/staff-members",
            headers=headers, params=params,
        )

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def patch_staff_member(self, staff_id, payload, headers):
        return self._request("PATCH", f"/staff-members/{staff_id}", payload, headers)

    # ---- shift assignments -------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shift-assignments", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shift-assignments", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shift-assignments/{shift_id}", headers=headers)

    def activate_shift(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"/shift-assignments/{shift_id}/activate", payload or {}, headers
        )

    def relieve_shift(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/shift-assignments/{shift_id}/relieve", payload, headers
        )

    def cancel_shift(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"/shift-assignments/{shift_id}/cancel", payload or {}, headers
        )

    # ---- beds --------------------------------------------------------------
    def create_bed(self, unit_id, payload, headers):
        return self._request("POST", f"/obstetric-units/{unit_id}/beds", payload, headers)

    def list_unit_beds(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/beds", headers=headers, params=params
        )

    def list_beds(self, headers, params=None):
        return self._request("GET", "/beds", headers=headers, params=params)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/beds/{bed_id}", headers=headers)

    def patch_bed(self, bed_id, payload, headers):
        return self._request("PATCH", f"/beds/{bed_id}", payload, headers)

    def delete_bed(self, bed_id, headers):
        return self._request("DELETE", f"/beds/{bed_id}", headers=headers)

    # ---- labor encounters --------------------------------------------------
    def create_encounter(self, payload, headers):
        return self._request("POST", "/labor-encounters", payload, headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/labor-encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/labor-encounters/{encounter_id}", headers=headers)

    def get_encounter_coverage_summary(self, encounter_id, headers):
        return self._request(
            "GET", f"/labor-encounters/{encounter_id}/coverage-summary", headers=headers
        )

    def assign_bed(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/labor-encounters/{encounter_id}/assign-bed", payload, headers
        )

    def advance_phase(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/labor-encounters/{encounter_id}/advance-phase", payload, headers
        )

    def discharge_encounter(self, encounter_id, headers, payload=None):
        return self._request(
            "POST", f"/labor-encounters/{encounter_id}/discharge", payload or {}, headers
        )

    def transfer_out_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/labor-encounters/{encounter_id}/transfer-out", payload, headers
        )

    # ---- care assignments --------------------------------------------------
    def create_care_assignment(self, payload, headers):
        return self._request("POST", "/care-assignments", payload, headers)

    def list_care_assignments(self, headers, params=None):
        return self._request("GET", "/care-assignments", headers=headers, params=params)

    def get_care_assignment(self, assignment_id, headers):
        return self._request("GET", f"/care-assignments/{assignment_id}", headers=headers)

    def release_care_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/care-assignments/{assignment_id}/release", payload or {}, headers
        )

    # ---- induction bookings ------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/induction-bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/induction-bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/induction-bookings/{booking_id}", headers=headers)

    def hold_capacity(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/induction-bookings/{booking_id}/hold-capacity", payload, headers
        )

    def confirm_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-bookings/{booking_id}/confirm", payload or {}, headers
        )

    def admit_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-bookings/{booking_id}/admit", payload or {}, headers
        )

    def bump_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-bookings/{booking_id}/bump", payload or {}, headers
        )

    def requeue_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-bookings/{booking_id}/requeue", payload or {}, headers
        )

    def cancel_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-bookings/{booking_id}/cancel", payload or {}, headers
        )

    # ---- safety bundle activations ----------------------------------------
    def create_activation(self, payload, headers):
        return self._request("POST", "/bundle-activations", payload, headers)

    def list_activations(self, headers, params=None):
        return self._request("GET", "/bundle-activations", headers=headers, params=params)

    def get_activation(self, activation_id, headers):
        return self._request("GET", f"/bundle-activations/{activation_id}", headers=headers)

    def list_checklist_items(self, activation_id, headers, params=None):
        return self._request(
            "GET", f"/bundle-activations/{activation_id}/checklist-items",
            headers=headers, params=params,
        )

    def get_checklist_item(self, activation_id, item_id, headers):
        return self._request(
            "GET", f"/bundle-activations/{activation_id}/checklist-items/{item_id}",
            headers=headers,
        )

    def get_timeliness_report(self, activation_id, headers):
        return self._request(
            "GET", f"/bundle-activations/{activation_id}/timeliness-report", headers=headers
        )

    def complete_checklist_item(self, activation_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/bundle-activations/{activation_id}/checklist-items/{item_id}/complete",
            payload, headers,
        )

    def escalate_stage(self, activation_id, payload, headers):
        return self._request(
            "POST", f"/bundle-activations/{activation_id}/escalate-stage", payload, headers
        )

    def resolve_activation(self, activation_id, payload, headers):
        return self._request(
            "POST", f"/bundle-activations/{activation_id}/resolve", payload, headers
        )

    def close_debrief(self, activation_id, payload, headers):
        return self._request(
            "POST", f"/bundle-activations/{activation_id}/close-debrief", payload, headers
        )

    def rescind_activation(self, activation_id, payload, headers):
        return self._request(
            "POST", f"/bundle-activations/{activation_id}/rescind", payload, headers
        )

    def list_all_checklist_items(self, headers, params=None):
        return self._request(
            "GET", "/bundle-checklist-items", headers=headers, params=params
        )

    def get_checklist_item_direct(self, item_id, headers):
        return self._request("GET", f"/bundle-checklist-items/{item_id}", headers=headers)

    # ---- fetal monitoring assessments -------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/fetal-monitoring-assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request(
            "GET", "/fetal-monitoring-assessments", headers=headers, params=params
        )

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/fetal-monitoring-assessments/{assessment_id}", headers=headers
        )

    def escalate_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/fetal-monitoring-assessments/{assessment_id}/escalate",
            payload, headers,
        )

    def resolve_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/fetal-monitoring-assessments/{assessment_id}/resolve",
            payload, headers,
        )

    # ---- emergency cesareans ----------------------------------------------
    def create_cesarean(self, payload, headers):
        return self._request("POST", "/emergency-cesareans", payload, headers)

    def list_cesareans(self, headers, params=None):
        return self._request("GET", "/emergency-cesareans", headers=headers, params=params)

    def get_cesarean(self, event_id, headers):
        return self._request("GET", f"/emergency-cesareans/{event_id}", headers=headers)

    def mobilize_team(self, event_id, payload, headers):
        return self._request(
            "POST", f"/emergency-cesareans/{event_id}/mobilize-team", payload, headers
        )

    def record_incision(self, event_id, payload, headers):
        return self._request(
            "POST", f"/emergency-cesareans/{event_id}/record-incision", payload, headers
        )

    def record_delivery(self, event_id, payload, headers):
        return self._request(
            "POST", f"/emergency-cesareans/{event_id}/record-delivery", payload, headers
        )

    def close_cesarean(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/emergency-cesareans/{event_id}/close", payload or {}, headers
        )

    def abort_to_vaginal(self, event_id, payload, headers):
        return self._request(
            "POST", f"/emergency-cesareans/{event_id}/abort-to-vaginal", payload, headers
        )

    # ---- cesarean readiness drills ----------------------------------------
    def create_drill(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/obstetric-units/{unit_id}/cesarean-readiness-drills", payload, headers
        )

    def list_unit_drills(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/cesarean-readiness-drills",
            headers=headers, params=params,
        )

    def list_drills(self, headers, params=None):
        return self._request(
            "GET", "/cesarean-readiness-drills", headers=headers, params=params
        )

    def get_drill(self, drill_id, headers):
        return self._request(
            "GET", f"/cesarean-readiness-drills/{drill_id}", headers=headers
        )

    def start_drill(self, drill_id, headers, payload=None):
        return self._request(
            "POST", f"/cesarean-readiness-drills/{drill_id}/start", payload or {}, headers
        )

    def document_drill(self, drill_id, payload, headers):
        return self._request(
            "POST", f"/cesarean-readiness-drills/{drill_id}/document", payload, headers
        )

    def validate_drill(self, drill_id, headers, payload=None):
        return self._request(
            "POST", f"/cesarean-readiness-drills/{drill_id}/validate", payload or {}, headers
        )

    def invalidate_drill(self, drill_id, payload, headers):
        return self._request(
            "POST", f"/cesarean-readiness-drills/{drill_id}/invalidate", payload, headers
        )

    def abandon_drill(self, drill_id, headers, payload=None):
        return self._request(
            "POST", f"/cesarean-readiness-drills/{drill_id}/abandon", payload or {}, headers
        )

    # ---- newborn complication reviews -------------------------------------
    def create_review(self, payload, headers):
        return self._request("POST", "/newborn-complication-reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request(
            "GET", "/newborn-complication-reviews", headers=headers, params=params
        )

    def get_review(self, review_id, headers):
        return self._request(
            "GET", f"/newborn-complication-reviews/{review_id}", headers=headers
        )

    def schedule_debrief(self, review_id, payload, headers):
        return self._request(
            "POST", f"/newborn-complication-reviews/{review_id}/schedule-debrief",
            payload, headers,
        )

    def submit_findings(self, review_id, payload, headers):
        return self._request(
            "POST", f"/newborn-complication-reviews/{review_id}/submit-findings",
            payload, headers,
        )

    def request_rework(self, review_id, payload, headers):
        return self._request(
            "POST", f"/newborn-complication-reviews/{review_id}/request-rework",
            payload, headers,
        )

    def close_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/newborn-complication-reviews/{review_id}/close", payload or {}, headers
        )

    # ---- support person passes --------------------------------------------
    def create_pass(self, payload, headers):
        return self._request("POST", "/support-person-passes", payload, headers)

    def list_passes(self, headers, params=None):
        return self._request(
            "GET", "/support-person-passes", headers=headers, params=params
        )

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/support-person-passes/{pass_id}", headers=headers)

    def check_in_pass(self, pass_id, headers, payload=None):
        return self._request(
            "POST", f"/support-person-passes/{pass_id}/check-in", payload or {}, headers
        )

    def check_out_pass(self, pass_id, headers, payload=None):
        return self._request(
            "POST", f"/support-person-passes/{pass_id}/check-out", payload or {}, headers
        )

    def revoke_pass(self, pass_id, headers, payload=None):
        return self._request(
            "POST", f"/support-person-passes/{pass_id}/revoke", payload or {}, headers
        )

    # ---- quality measure snapshots ----------------------------------------
    def create_snapshot(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/obstetric-units/{unit_id}/quality-measure-snapshots", payload, headers
        )

    def list_unit_snapshots(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/obstetric-units/{unit_id}/quality-measure-snapshots",
            headers=headers, params=params,
        )

    def list_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/quality-measure-snapshots", headers=headers, params=params
        )

    def get_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/quality-measure-snapshots/{snapshot_id}", headers=headers
        )

    def certify_snapshot(self, snapshot_id, headers, payload=None):
        return self._request(
            "POST", f"/quality-measure-snapshots/{snapshot_id}/certify", payload or {}, headers
        )


api_client = ApiClient()
