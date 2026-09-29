"""API client: one method per endpoint defined in the PRD (§4).

All business paths are mounted under ``/nature-center``; the logical-clock
test-driving endpoint is mounted at the root as ``/_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/nature-center"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------- program offerings
    def create_program_offering(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-offerings", payload, headers)

    def list_program_offerings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/program-offerings", headers=headers, params=params
        )

    def get_program_offering(self, offering_id, headers):
        return self._request(
            "GET", f"{PREFIX}/program-offerings/{offering_id}", headers=headers
        )

    def create_standard_alignment(self, offering_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/program-offerings/{offering_id}/standard-alignments",
            payload,
            headers,
        )

    def list_standard_alignments(self, offering_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/program-offerings/{offering_id}/standard-alignments",
            headers=headers,
            params=params,
        )

    def create_curriculum_material(self, offering_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/program-offerings/{offering_id}/materials",
            payload,
            headers,
        )

    def list_curriculum_materials(self, offering_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/program-offerings/{offering_id}/materials",
            headers=headers,
            params=params,
        )

    def publish_curriculum_material(self, material_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/curriculum-materials/{material_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def submit_offering_for_review(self, offering_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/program-offerings/{offering_id}/submit-for-review",
            payload if payload is not None else {},
            headers,
        )

    def review_program_offering(self, offering_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/program-offerings/{offering_id}/review",
            payload,
            headers,
        )

    def retire_program_offering(self, offering_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/program-offerings/{offering_id}/retire",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------- schools
    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    # ----------------------------------------------------------- educators
    def create_educator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/educators", payload, headers)

    def get_educator(self, educator_id, headers):
        return self._request(
            "GET", f"{PREFIX}/educators/{educator_id}", headers=headers
        )

    def advance_educator_hiring(self, educator_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/educators/{educator_id}/advance-hiring",
            payload,
            headers,
        )

    def create_training_record(self, educator_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/educators/{educator_id}/training-records",
            payload,
            headers,
        )

    def list_training_records(self, educator_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/educators/{educator_id}/training-records",
            headers=headers,
            params=params,
        )

    def assess_training_record(self, training_record_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/training-records/{training_record_id}/assess",
            payload,
            headers,
        )

    def reenroll_training_record(self, training_record_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/training-records/{training_record_id}/reenroll",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------- permits
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def set_permit_status(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/set-status", payload, headers
        )

    # ------------------------------------------------- animal ambassadors
    def create_animal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/animals", payload, headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/animals", headers=headers, params=params)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"{PREFIX}/animals/{animal_id}", headers=headers)

    def set_animal_care_status(self, animal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/animals/{animal_id}/set-care-status", payload, headers
        )

    # ------------------------------------------------------ trail segments
    def create_trail_segment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trail-segments", payload, headers)

    def get_trail_segment(self, trail_segment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/trail-segments/{trail_segment_id}", headers=headers
        )

    def set_trail_segment_status(self, trail_segment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/trail-segments/{trail_segment_id}/set-status",
            payload,
            headers,
        )

    # ------------------------------------------------------------ bookings
    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", headers=headers)

    def assign_booking_resources(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/assign-resources", payload, headers
        )

    def confirm_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/bookings/{booking_id}/confirm",
            payload if payload is not None else {},
            headers,
        )

    def rain_divert_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/rain-divert", payload, headers
        )

    def deliver_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/deliver", payload, headers
        )

    def no_show_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/no-show", payload, headers
        )

    def cancel_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/cancel", payload, headers
        )

    def record_payment(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/record-payment", payload, headers
        )

    # -------------------------------------------------- equipment manifests
    def create_equipment_manifest(self, booking_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/bookings/{booking_id}/equipment-manifests",
            payload,
            headers,
        )

    def list_equipment_manifests(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/bookings/{booking_id}/equipment-manifests",
            headers=headers,
            params=params,
        )

    def advance_equipment_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/equipment-manifests/{manifest_id}/advance",
            payload,
            headers,
        )

    # -------------------------------------------------- evaluation reports
    def create_evaluation_report(self, booking_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/bookings/{booking_id}/evaluation-reports",
            payload,
            headers,
        )

    def list_evaluation_reports(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/bookings/{booking_id}/evaluation-reports",
            headers=headers,
            params=params,
        )

    def submit_evaluation_report(self, report_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/evaluation-reports/{report_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_evaluation_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/evaluation-reports/{report_id}/review", payload, headers
        )

    # --------------------------------------------------- scholarship funds
    def create_scholarship_fund(self, payload, headers):
        return self._request("POST", f"{PREFIX}/scholarship-funds", payload, headers)

    def get_scholarship_fund(self, fund_id, headers):
        return self._request(
            "GET", f"{PREFIX}/scholarship-funds/{fund_id}", headers=headers
        )

    def set_scholarship_fund_status(self, fund_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/scholarship-funds/{fund_id}/set-status",
            payload,
            headers,
        )

    def get_fund_outcome_report(self, fund_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/scholarship-funds/{fund_id}/outcome-report",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- aid applications
    def create_aid_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/aid-applications", payload, headers)

    def list_aid_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/aid-applications", headers=headers, params=params
        )

    def get_aid_application(self, aid_application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/aid-applications/{aid_application_id}", headers=headers
        )

    def review_aid_application(self, aid_application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/aid-applications/{aid_application_id}/review",
            payload,
            headers,
        )


api_client = ApiClient()
