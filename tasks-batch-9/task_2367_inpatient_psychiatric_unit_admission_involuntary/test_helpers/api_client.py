"""One typed method per endpoint of the Inpatient Psychiatric Admission API.

Every method returns the raw ``requests.Response`` so a test can assert on the
transport status as well as the envelope. All paths sit under the
``/behavioral-health`` prefix (PRD 4).

Filter and pagination arguments default to ``None`` and are dropped from the
query string when unset, so a call exercises the server-side defaults rather
than restating them.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _query(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Drop unset filters so omitted parameters exercise server defaults."""
    params = {key: value for key, value in kwargs.items() if value is not None}
    return params or None


def _body(explicit: Optional[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
    """Build a request body, letting a caller pass a whole payload verbatim.

    Passing ``payload=`` wins outright, which is what a malformed-body test
    needs; otherwise the named arguments are assembled and ``None`` values are
    dropped so an omitted optional field is genuinely absent.
    """
    if explicit is not None:
        return explicit
    return {key: value for key, value in kwargs.items() if value is not None}


class ApiClient(GenericApiClient):
    """HTTP surface of the behavioural-health API."""

    # -- Clinicians --------------------------------------------------------

    def create_clinician(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        full_name: Optional[str] = None,
        staff_role: Optional[str] = None,
        license_number: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/clinicians",
            payload=_body(
                payload,
                full_name=full_name,
                staff_role=staff_role,
                license_number=license_number,
            ),
            headers=headers,
        )

    def get_clinician(
        self, headers: Dict[str, str], clinician_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/clinicians/{clinician_id}", headers=headers
        )

    # -- Units -------------------------------------------------------------

    def create_unit(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        name: Optional[str] = None,
        gender_mixing_policy: Optional[str] = None,
        seclusion_room_count: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/units",
            payload=_body(
                payload,
                name=name,
                gender_mixing_policy=gender_mixing_policy,
                seclusion_room_count=seclusion_room_count,
            ),
            headers=headers,
        )

    def get_unit(self, headers: Dict[str, str], unit_id: str) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/units/{unit_id}", headers=headers)

    # -- Beds --------------------------------------------------------------

    def create_bed(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        unit_id: Optional[str] = None,
        room_number: Optional[str] = None,
        wing_code: Optional[str] = None,
        bed_label: Optional[str] = None,
        bed_type: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/beds",
            payload=_body(
                payload,
                unit_id=unit_id,
                room_number=room_number,
                wing_code=wing_code,
                bed_label=bed_label,
                bed_type=bed_type,
            ),
            headers=headers,
        )

    def list_unit_beds(
        self,
        headers: Dict[str, str],
        unit_id: str,
        *,
        status: Optional[str] = None,
        bed_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/units/{unit_id}/beds",
            headers=headers,
            params=_query(
                status=status, bed_type=bed_type, limit=limit, offset=offset
            ),
        )

    def update_bed_status(
        self,
        headers: Dict[str, str],
        bed_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        status: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/beds/{bed_id}",
            payload=_body(payload, status=status),
            headers=headers,
        )

    # -- Patients ----------------------------------------------------------

    def create_patient(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        mrn: Optional[str] = None,
        legal_name: Optional[str] = None,
        age_years: Optional[int] = None,
        gender_care_category: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/patients",
            payload=_body(
                payload,
                mrn=mrn,
                legal_name=legal_name,
                age_years=age_years,
                gender_care_category=gender_care_category,
            ),
            headers=headers,
        )

    def get_patient(
        self, headers: Dict[str, str], patient_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/patients/{patient_id}", headers=headers
        )

    # -- Clock and sweep ---------------------------------------------------

    def set_clock(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        to_iso8601: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            payload=_body(payload, to_iso8601=to_iso8601),
            headers=headers,
        )

    def run_sweep(self, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_compliance/sweep", payload={}, headers=headers
        )

    # -- Emergency evaluations --------------------------------------------

    def create_evaluation(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        patient_id: Optional[str] = None,
        danger_to_self: Optional[bool] = None,
        danger_to_others: Optional[bool] = None,
        grave_disability: Optional[bool] = None,
        capacity_present: Optional[bool] = None,
        clinical_summary: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/evaluations",
            payload=_body(
                payload,
                patient_id=patient_id,
                danger_to_self=danger_to_self,
                danger_to_others=danger_to_others,
                grave_disability=grave_disability,
                capacity_present=capacity_present,
                clinical_summary=clinical_summary,
            ),
            headers=headers,
        )

    def sign_evaluation(
        self, headers: Dict[str, str], evaluation_id: str
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/evaluations/{evaluation_id}/sign",
            payload={},
            headers=headers,
        )

    def get_evaluation(
        self, headers: Dict[str, str], evaluation_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/evaluations/{evaluation_id}", headers=headers
        )

    def list_evaluations(
        self,
        headers: Dict[str, str],
        *,
        patient_id: Optional[str] = None,
        evaluating_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/evaluations",
            headers=headers,
            params=_query(
                patient_id=patient_id,
                evaluating_clinician_id=evaluating_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Hold orders -------------------------------------------------------

    def create_hold(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        patient_id: Optional[str] = None,
        evaluation_id: Optional[str] = None,
        hold_type: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/holds",
            payload=_body(
                payload,
                patient_id=patient_id,
                evaluation_id=evaluation_id,
                hold_type=hold_type,
            ),
            headers=headers,
        )

    def certify_hold(
        self,
        headers: Dict[str, str],
        hold_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        certification_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/holds/{hold_id}/certify",
            payload=_body(payload, certification_note=certification_note),
            headers=headers,
        )

    def rescind_hold(
        self,
        headers: Dict[str, str],
        hold_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        rescind_reason: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/holds/{hold_id}/rescind",
            payload=_body(payload, rescind_reason=rescind_reason),
            headers=headers,
        )

    def get_hold(self, headers: Dict[str, str], hold_id: str) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/holds/{hold_id}", headers=headers)

    def list_holds(
        self,
        headers: Dict[str, str],
        *,
        patient_id: Optional[str] = None,
        evaluation_id: Optional[str] = None,
        predecessor_hold_id: Optional[str] = None,
        initiated_by_clinician_id: Optional[str] = None,
        certifying_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/holds",
            headers=headers,
            params=_query(
                patient_id=patient_id,
                evaluation_id=evaluation_id,
                predecessor_hold_id=predecessor_hold_id,
                initiated_by_clinician_id=initiated_by_clinician_id,
                certifying_clinician_id=certifying_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Hold petitions ----------------------------------------------------

    def create_petition(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        hold_id: Optional[str] = None,
        requested_hold_type: Optional[str] = None,
        petition_grounds: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/petitions",
            payload=_body(
                payload,
                hold_id=hold_id,
                requested_hold_type=requested_hold_type,
                petition_grounds=petition_grounds,
            ),
            headers=headers,
        )

    def withdraw_petition(
        self,
        headers: Dict[str, str],
        petition_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        withdraw_reason: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/petitions/{petition_id}/withdraw",
            payload=_body(payload, withdraw_reason=withdraw_reason),
            headers=headers,
        )

    def get_petition(
        self, headers: Dict[str, str], petition_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/petitions/{petition_id}", headers=headers
        )

    def list_petitions(
        self,
        headers: Dict[str, str],
        *,
        hold_id: Optional[str] = None,
        petitioning_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/petitions",
            headers=headers,
            params=_query(
                hold_id=hold_id,
                petitioning_clinician_id=petitioning_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Court hearings ----------------------------------------------------

    def create_hearing(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        petition_id: Optional[str] = None,
        advocate_clinician_id: Optional[str] = None,
        scheduled_start_at: Optional[str] = None,
        duration_minutes: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/hearings",
            payload=_body(
                payload,
                petition_id=petition_id,
                advocate_clinician_id=advocate_clinician_id,
                scheduled_start_at=scheduled_start_at,
                duration_minutes=duration_minutes,
            ),
            headers=headers,
        )

    def record_hearing_outcome(
        self,
        headers: Dict[str, str],
        hearing_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        outcome: Optional[str] = None,
        findings_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/hearings/{hearing_id}/record-outcome",
            payload=_body(payload, outcome=outcome, findings_note=findings_note),
            headers=headers,
        )

    def get_hearing(
        self, headers: Dict[str, str], hearing_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/hearings/{hearing_id}", headers=headers
        )

    def list_hearings(
        self,
        headers: Dict[str, str],
        *,
        petition_id: Optional[str] = None,
        advocate_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/hearings",
            headers=headers,
            params=_query(
                petition_id=petition_id,
                advocate_clinician_id=advocate_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Admissions --------------------------------------------------------

    def create_admission(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        patient_id: Optional[str] = None,
        evaluation_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        requested_legal_status: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions",
            payload=_body(
                payload,
                patient_id=patient_id,
                evaluation_id=evaluation_id,
                unit_id=unit_id,
                requested_legal_status=requested_legal_status,
            ),
            headers=headers,
        )

    def get_admission(
        self, headers: Dict[str, str], admission_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/admissions/{admission_id}", headers=headers
        )

    def list_admissions(
        self,
        headers: Dict[str, str],
        *,
        patient_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        bed_id: Optional[str] = None,
        evaluation_id: Optional[str] = None,
        admitting_clinician_id: Optional[str] = None,
        search_performed_by_clinician_id: Optional[str] = None,
        search_witness_clinician_id: Optional[str] = None,
        legal_status: Optional[str] = None,
        placement_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/admissions",
            headers=headers,
            params=_query(
                patient_id=patient_id,
                unit_id=unit_id,
                bed_id=bed_id,
                evaluation_id=evaluation_id,
                admitting_clinician_id=admitting_clinician_id,
                search_performed_by_clinician_id=search_performed_by_clinician_id,
                search_witness_clinician_id=search_witness_clinician_id,
                legal_status=legal_status,
                placement_status=placement_status,
                limit=limit,
                offset=offset,
            ),
        )

    def record_safety_search(
        self,
        headers: Dict[str, str],
        admission_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        search_type: Optional[str] = None,
        search_witness_clinician_id: Optional[str] = None,
        search_items_secured_count: Optional[int] = None,
        contraband_found: Optional[bool] = None,
        outcome: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions/{admission_id}/safety-search",
            payload=_body(
                payload,
                search_type=search_type,
                search_witness_clinician_id=search_witness_clinician_id,
                search_items_secured_count=search_items_secured_count,
                contraband_found=contraband_found,
                outcome=outcome,
            ),
            headers=headers,
        )

    def place_admission(
        self,
        headers: Dict[str, str],
        admission_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        unit_id: Optional[str] = None,
        expected_unit_version: Optional[int] = None,
        bed_id: Optional[str] = None,
        posture_override_reason: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions/{admission_id}/place",
            payload=_body(
                payload,
                unit_id=unit_id,
                expected_unit_version=expected_unit_version,
                bed_id=bed_id,
                posture_override_reason=posture_override_reason,
            ),
            headers=headers,
        )

    def convert_admission_to_voluntary(
        self,
        headers: Dict[str, str],
        admission_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        conversion_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions/{admission_id}/convert-to-voluntary",
            payload=_body(payload, conversion_note=conversion_note),
            headers=headers,
        )

    def submit_discharge_plan(
        self,
        headers: Dict[str, str],
        admission_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        follow_up_provider_name: Optional[str] = None,
        follow_up_appointment_at: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions/{admission_id}/discharge-plan",
            payload=_body(
                payload,
                follow_up_provider_name=follow_up_provider_name,
                follow_up_appointment_at=follow_up_appointment_at,
            ),
            headers=headers,
        )

    def discharge_admission(
        self,
        headers: Dict[str, str],
        admission_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        discharge_summary: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions/{admission_id}/discharge",
            payload=_body(payload, discharge_summary=discharge_summary),
            headers=headers,
        )

    # -- Discharge requests ------------------------------------------------

    def create_discharge_request(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        admission_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/discharge-requests",
            payload=_body(
                payload, admission_id=admission_id, requested_by=requested_by
            ),
            headers=headers,
        )

    def respond_to_discharge_request(
        self,
        headers: Dict[str, str],
        discharge_request_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        decision: Optional[str] = None,
        response_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/discharge-requests/{discharge_request_id}/respond",
            payload=_body(payload, decision=decision, response_note=response_note),
            headers=headers,
        )

    def get_discharge_request(
        self, headers: Dict[str, str], discharge_request_id: str
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/discharge-requests/{discharge_request_id}",
            headers=headers,
        )

    def list_discharge_requests(
        self,
        headers: Dict[str, str],
        *,
        admission_id: Optional[str] = None,
        recorded_by_clinician_id: Optional[str] = None,
        responding_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/discharge-requests",
            headers=headers,
            params=_query(
                admission_id=admission_id,
                recorded_by_clinician_id=recorded_by_clinician_id,
                responding_clinician_id=responding_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Restraint episodes ------------------------------------------------

    def create_restraint(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        admission_id: Optional[str] = None,
        intervention_type: Optional[str] = None,
        ordered_duration_minutes: Optional[int] = None,
        clinical_justification: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/restraints",
            payload=_body(
                payload,
                admission_id=admission_id,
                intervention_type=intervention_type,
                ordered_duration_minutes=ordered_duration_minutes,
                clinical_justification=clinical_justification,
            ),
            headers=headers,
        )

    def record_face_to_face(
        self,
        headers: Dict[str, str],
        restraint_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        assessment_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/restraints/{restraint_id}/face-to-face",
            payload=_body(payload, assessment_note=assessment_note),
            headers=headers,
        )

    def add_monitoring_check(
        self,
        headers: Dict[str, str],
        restraint_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        check_type: Optional[str] = None,
        note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/restraints/{restraint_id}/monitoring-checks",
            payload=_body(payload, check_type=check_type, note=note),
            headers=headers,
        )

    def release_restraint(
        self,
        headers: Dict[str, str],
        restraint_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        release_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/restraints/{restraint_id}/release",
            payload=_body(payload, release_note=release_note),
            headers=headers,
        )

    def debrief_restraint(
        self,
        headers: Dict[str, str],
        restraint_id: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        patient_participated_in_debrief: Optional[bool] = None,
        staff_participants_count: Optional[int] = None,
        debrief_note: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/restraints/{restraint_id}/debrief",
            payload=_body(
                payload,
                patient_participated_in_debrief=patient_participated_in_debrief,
                staff_participants_count=staff_participants_count,
                debrief_note=debrief_note,
            ),
            headers=headers,
        )

    def get_restraint(
        self, headers: Dict[str, str], restraint_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/restraints/{restraint_id}", headers=headers
        )

    def list_restraints(
        self,
        headers: Dict[str, str],
        *,
        admission_id: Optional[str] = None,
        ordered_by_clinician_id: Optional[str] = None,
        face_to_face_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/restraints",
            headers=headers,
            params=_query(
                admission_id=admission_id,
                ordered_by_clinician_id=ordered_by_clinician_id,
                face_to_face_clinician_id=face_to_face_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Capacity determinations -------------------------------------------

    def create_capacity_determination(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        admission_id: Optional[str] = None,
        expected_admission_version: Optional[int] = None,
        capacity_present: Optional[bool] = None,
        surrogate_name: Optional[str] = None,
        surrogate_relationship: Optional[str] = None,
        surrogate_authority_scope: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/capacity-determinations",
            payload=_body(
                payload,
                admission_id=admission_id,
                expected_admission_version=expected_admission_version,
                capacity_present=capacity_present,
                surrogate_name=surrogate_name,
                surrogate_relationship=surrogate_relationship,
                surrogate_authority_scope=surrogate_authority_scope,
            ),
            headers=headers,
        )

    def get_capacity_determination(
        self, headers: Dict[str, str], determination_id: str
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/capacity-determinations/{determination_id}",
            headers=headers,
        )

    def list_capacity_determinations(
        self,
        headers: Dict[str, str],
        *,
        admission_id: Optional[str] = None,
        determined_by_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/capacity-determinations",
            headers=headers,
            params=_query(
                admission_id=admission_id,
                determined_by_clinician_id=determined_by_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    # -- Medication consents -----------------------------------------------

    def create_medication_consent(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        admission_id: Optional[str] = None,
        medication_name: Optional[str] = None,
        consent_basis: Optional[str] = None,
        capacity_determination_id: Optional[str] = None,
        emergency_justification: Optional[str] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/medication-consents",
            payload=_body(
                payload,
                admission_id=admission_id,
                medication_name=medication_name,
                consent_basis=consent_basis,
                capacity_determination_id=capacity_determination_id,
                emergency_justification=emergency_justification,
            ),
            headers=headers,
        )

    def get_medication_consent(
        self, headers: Dict[str, str], consent_id: str
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/medication-consents/{consent_id}", headers=headers
        )

    def list_medication_consents(
        self,
        headers: Dict[str, str],
        *,
        admission_id: Optional[str] = None,
        capacity_determination_id: Optional[str] = None,
        prescribing_clinician_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/medication-consents",
            headers=headers,
            params=_query(
                admission_id=admission_id,
                capacity_determination_id=capacity_determination_id,
                prescribing_clinician_id=prescribing_clinician_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )
