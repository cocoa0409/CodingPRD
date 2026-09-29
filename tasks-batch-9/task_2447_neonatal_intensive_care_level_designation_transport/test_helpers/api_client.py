"""Typed HTTP client — one method per endpoint in the PRD's endpoint table.

Calling conventions (uniform across the whole module):

* create:  ``create_x(payload, headers)``                     -> POST /x
* list:    ``list_x(headers, params=None)``                   -> GET  /x
* read:    ``get_x(x_id, headers)``                           -> GET  /x/{id}
* patch:   ``patch_x(x_id, payload, headers)``                -> PATCH /x/{id}
* action:  ``do_x(x_id, payload=None, headers=None)``          -> POST /x/{id}/do

Every method returns the raw ``requests.Response`` so a test can assert on the
status code and on the response envelope itself.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Payload = Optional[Dict[str, Any]]
Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Operational endpoints
    # ------------------------------------------------------------------

    def set_current_utc(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_capacity_sweep(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/ops/run-capacity-sweep", payload, headers)

    # ------------------------------------------------------------------
    # NicuUnit
    # ------------------------------------------------------------------

    def create_nicu_unit(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/nicu-units", payload, headers)

    def list_nicu_units(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/nicu-units", None, headers, params)

    def get_nicu_unit(self, unit_id: str, headers: Headers = None):
        return self._request("GET", f"/nicu-units/{unit_id}", None, headers)

    def patch_nicu_unit(self, unit_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("PATCH", f"/nicu-units/{unit_id}", payload, headers)

    def get_capacity_projection(self, unit_id: str, headers: Headers = None):
        return self._request("GET", f"/nicu-units/{unit_id}/capacity-projection", None, headers)

    def get_deferral_queue(self, unit_id: str, headers: Headers = None, params: Params = None):
        return self._request("GET", f"/nicu-units/{unit_id}/deferral-queue", None, headers, params)

    # ------------------------------------------------------------------
    # DesignationStandard
    # ------------------------------------------------------------------

    def create_designation_standard(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/designation-standards", payload, headers)

    def list_designation_standards(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/designation-standards", None, headers, params)

    def get_designation_standard(self, standard_id: str, headers: Headers = None):
        return self._request("GET", f"/designation-standards/{standard_id}", None, headers)

    # ------------------------------------------------------------------
    # StaffCredential
    # ------------------------------------------------------------------

    def create_staff_credential(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/staff-credentials", payload, headers)

    def list_staff_credentials(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/staff-credentials", None, headers, params)

    def get_staff_credential(self, credential_id: str, headers: Headers = None):
        return self._request("GET", f"/staff-credentials/{credential_id}", None, headers)

    def revoke_staff_credential(
        self, credential_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/staff-credentials/{credential_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # EquipmentAsset
    # ------------------------------------------------------------------

    def create_equipment_asset(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/equipment-assets", payload, headers)

    def list_equipment_assets(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/equipment-assets", None, headers, params)

    def get_equipment_asset(self, asset_id: str, headers: Headers = None):
        return self._request("GET", f"/equipment-assets/{asset_id}", None, headers)

    def service_equipment_asset(
        self, asset_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/equipment-assets/{asset_id}/service", payload, headers)

    def take_equipment_asset_out_of_service(
        self, asset_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/equipment-assets/{asset_id}/out-of-service", payload, headers
        )

    # ------------------------------------------------------------------
    # DesignationReview
    # ------------------------------------------------------------------

    def create_designation_review(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/designation-reviews", payload, headers)

    def list_designation_reviews(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/designation-reviews", None, headers, params)

    def get_designation_review(self, review_id: str, headers: Headers = None):
        return self._request("GET", f"/designation-reviews/{review_id}", None, headers)

    def submit_designation_review(
        self, review_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/designation-reviews/{review_id}/submit", payload, headers)

    def return_designation_review(
        self, review_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/designation-reviews/{review_id}/return", payload, headers)

    def verify_designation_review(
        self, review_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/designation-reviews/{review_id}/verify", payload, headers)

    def certify_designation_review(
        self, review_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/designation-reviews/{review_id}/certify", payload, headers)

    # ------------------------------------------------------------------
    # Referral
    # ------------------------------------------------------------------

    def create_referral(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/referrals", None, headers, params)

    def get_referral(self, referral_id: str, headers: Headers = None):
        return self._request("GET", f"/referrals/{referral_id}", None, headers)

    def request_referral_info(
        self, referral_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/referrals/{referral_id}/request-info", payload, headers)

    def provide_referral_info(
        self, referral_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/referrals/{referral_id}/provide-info", payload, headers)

    def accept_referral(self, referral_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/referrals/{referral_id}/accept", payload, headers)

    def decline_referral(self, referral_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/referrals/{referral_id}/decline", payload, headers)

    def defer_referral(self, referral_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/referrals/{referral_id}/defer", payload, headers)

    def withdraw_referral(self, referral_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", payload, headers)

    def revoke_referral_acceptance(
        self, referral_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/revoke-acceptance", payload, headers
        )

    # ------------------------------------------------------------------
    # BedReservation
    # ------------------------------------------------------------------

    def list_bed_reservations(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/bed-reservations", None, headers, params)

    def get_bed_reservation(self, reservation_id: str, headers: Headers = None):
        return self._request("GET", f"/bed-reservations/{reservation_id}", None, headers)

    # ------------------------------------------------------------------
    # TransportRun
    # ------------------------------------------------------------------

    def create_transport_run(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/transport-runs", payload, headers)

    def list_transport_runs(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/transport-runs", None, headers, params)

    def get_transport_run(self, run_id: str, headers: Headers = None):
        return self._request("GET", f"/transport-runs/{run_id}", None, headers)

    def dispatch_transport_run(self, run_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/transport-runs/{run_id}/dispatch", payload, headers)

    def transport_run_on_scene(self, run_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/transport-runs/{run_id}/on-scene", payload, headers)

    def stabilize_transport_run(
        self, run_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/transport-runs/{run_id}/stabilize", payload, headers)

    def depart_transport_run(self, run_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/transport-runs/{run_id}/depart", payload, headers)

    def arrive_transport_run(self, run_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/transport-runs/{run_id}/arrive", payload, headers)

    def abort_transport_run(self, run_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/transport-runs/{run_id}/abort", payload, headers)

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------

    def create_admission(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/admissions", payload, headers)

    def list_admissions(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/admissions", None, headers, params)

    def get_admission(self, admission_id: str, headers: Headers = None):
        return self._request("GET", f"/admissions/{admission_id}", None, headers)

    def create_care_update(
        self, admission_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/admissions/{admission_id}/care-updates", payload, headers)

    def create_developmental_round(
        self, admission_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/admissions/{admission_id}/developmental-rounds", payload, headers
        )

    def create_infection_event(
        self, admission_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/admissions/{admission_id}/infection-events", payload, headers
        )

    def attest_back_transfer_ready(
        self, admission_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/admissions/{admission_id}/back-transfer-ready", payload, headers
        )

    def create_back_transfer_referral(
        self, admission_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/admissions/{admission_id}/back-transfer-referrals", payload, headers
        )

    def discharge_admission(
        self, admission_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/admissions/{admission_id}/discharge", payload, headers)

    # ------------------------------------------------------------------
    # MilkBatch
    # ------------------------------------------------------------------

    def create_milk_batch(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/milk-batches", payload, headers)

    def list_milk_batches(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/milk-batches", None, headers, params)

    def get_milk_batch(self, batch_id: str, headers: Headers = None):
        return self._request("GET", f"/milk-batches/{batch_id}", None, headers)

    def verify_milk_batch(self, batch_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/milk-batches/{batch_id}/verify", payload, headers)

    def administer_milk(self, batch_id: str, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST", f"/milk-batches/{batch_id}/administrations", payload, headers
        )

    def reverse_milk_administration(
        self, batch_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/milk-batches/{batch_id}/administrations/reverse", payload, headers
        )

    def discard_milk_batch(self, batch_id: str, payload: Payload = None, headers: Headers = None):
        return self._request("POST", f"/milk-batches/{batch_id}/discard", payload, headers)

    # ------------------------------------------------------------------
    # SurgeEscalation
    # ------------------------------------------------------------------

    def create_surge_escalation(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/surge-escalations", payload, headers)

    def list_surge_escalations(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/surge-escalations", None, headers, params)

    def get_surge_escalation(self, escalation_id: str, headers: Headers = None):
        return self._request("GET", f"/surge-escalations/{escalation_id}", None, headers)

    def authorize_surge_escalation(
        self, escalation_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/surge-escalations/{escalation_id}/authorize", payload, headers
        )

    def deny_surge_escalation(
        self, escalation_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request("POST", f"/surge-escalations/{escalation_id}/deny", payload, headers)

    def stand_down_surge_escalation(
        self, escalation_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/surge-escalations/{escalation_id}/stand-down", payload, headers
        )

    # ------------------------------------------------------------------
    # SurveillanceReport
    # ------------------------------------------------------------------

    def create_surveillance_report(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/surveillance-reports", payload, headers)

    def list_surveillance_reports(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/surveillance-reports", None, headers, params)

    def get_surveillance_report(self, report_id: str, headers: Headers = None):
        return self._request("GET", f"/surveillance-reports/{report_id}", None, headers)

    def submit_surveillance_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/surveillance-reports/{report_id}/submit", payload, headers
        )

    def accept_surveillance_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/surveillance-reports/{report_id}/accept", payload, headers
        )

    def reject_surveillance_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/surveillance-reports/{report_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # FollowUpEnrollment
    # ------------------------------------------------------------------

    def create_follow_up_enrollment(self, payload: Payload = None, headers: Headers = None):
        return self._request("POST", "/follow-up-enrollments", payload, headers)

    def list_follow_up_enrollments(self, headers: Headers = None, params: Params = None):
        return self._request("GET", "/follow-up-enrollments", None, headers, params)

    def get_follow_up_enrollment(self, enrollment_id: str, headers: Headers = None):
        return self._request("GET", f"/follow-up-enrollments/{enrollment_id}", None, headers)

    def schedule_follow_up_enrollment(
        self, enrollment_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/follow-up-enrollments/{enrollment_id}/schedule", payload, headers
        )

    def record_follow_up_attendance(
        self, enrollment_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/follow-up-enrollments/{enrollment_id}/record-attendance", payload, headers
        )


api_client = ApiClient()
