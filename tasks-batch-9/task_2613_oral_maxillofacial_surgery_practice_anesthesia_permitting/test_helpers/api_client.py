"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Operational utilities ------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_compliance_sweep(self, payload, headers):
        return self._request("POST", "/_ops/run-compliance-sweep", payload, headers)

    # --- Practices ------------------------------------------------------
    def create_practice(self, payload, headers):
        return self._request("POST", "/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/practices/{practice_id}", headers=headers)

    def get_compliance_summary(self, practice_id, headers):
        return self._request(
            "GET", f"/practices/{practice_id}/compliance-summary", headers=headers
        )

    # --- Anesthesia permits ---------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/anesthesia-permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/anesthesia-permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/anesthesia-permits", headers=headers, params=params)

    def remediate_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/anesthesia-permits/{permit_id}/remediation", payload, headers
        )

    # --- Facility inspections -------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/facility-inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/facility-inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", "/facility-inspections", headers=headers, params=params
        )

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/facility-inspections/{inspection_id}/result", payload, headers
        )

    # --- Emergency drills -----------------------------------------------
    def create_drill(self, payload, headers):
        return self._request("POST", "/emergency-drills", payload, headers)

    def get_drill(self, drill_id, headers):
        return self._request("GET", f"/emergency-drills/{drill_id}", headers=headers)

    def list_drills(self, headers, params=None):
        return self._request("GET", "/emergency-drills", headers=headers, params=params)

    # --- Staff members --------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    # --- Patients -------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # --- Block time -----------------------------------------------------
    def create_block_time(self, payload, headers):
        return self._request("POST", "/block-times", payload, headers)

    def get_block_time(self, block_id, headers):
        return self._request("GET", f"/block-times/{block_id}", headers=headers)

    def list_block_times(self, headers, params=None):
        return self._request("GET", "/block-times", headers=headers, params=params)

    def release_block_time(self, block_id, payload, headers):
        return self._request(
            "POST", f"/block-times/{block_id}/release", payload, headers
        )

    # --- Surgical cases -------------------------------------------------
    def create_surgical_case(self, payload, headers):
        return self._request("POST", "/surgical-cases", payload, headers)

    def get_surgical_case(self, case_id, headers):
        return self._request("GET", f"/surgical-cases/{case_id}", headers=headers)

    def list_surgical_cases(self, headers, params=None):
        return self._request("GET", "/surgical-cases", headers=headers, params=params)

    def hold_block(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/hold-block", payload, headers
        )

    def confirm_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/confirm", payload, headers
        )

    def cancel_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/cancel", payload, headers
        )

    def start_recovery(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/start-recovery", payload, headers
        )

    def complete_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/complete", payload, headers
        )

    def record_referral_coordination(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/referral-coordination", payload, headers
        )

    def set_prerequisite(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surgical-cases/{case_id}/prerequisite", payload, headers
        )

    # --- Pre-anesthesia evaluations -------------------------------------
    def create_evaluation(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/surgical-cases/{case_id}/pre-anesthesia-evaluations",
            payload,
            headers,
        )

    def get_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/pre-anesthesia-evaluations/{evaluation_id}", headers=headers
        )

    def list_evaluations(self, headers, params=None):
        return self._request(
            "GET", "/pre-anesthesia-evaluations", headers=headers, params=params
        )

    def sign_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/pre-anesthesia-evaluations/{evaluation_id}/sign",
            payload,
            headers,
        )

    def verify_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/pre-anesthesia-evaluations/{evaluation_id}/day-of-verification",
            payload,
            headers,
        )

    # --- Benefit determinations -----------------------------------------
    def create_determination(self, payload, headers):
        return self._request("POST", "/benefit-determinations", payload, headers)

    def get_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/benefit-determinations/{determination_id}", headers=headers
        )

    def list_determinations(self, headers, params=None):
        return self._request(
            "GET", "/benefit-determinations", headers=headers, params=params
        )

    def submit_determination(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/benefit-determinations/{determination_id}/submit", payload, headers
        )

    def record_payer_response(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"/benefit-determinations/{determination_id}/payer-response",
            payload,
            headers,
        )

    # --- Implant lots ---------------------------------------------------
    def create_implant_lot(self, payload, headers):
        return self._request("POST", "/implant-lots", payload, headers)

    def get_implant_lot(self, lot_id, headers):
        return self._request("GET", f"/implant-lots/{lot_id}", headers=headers)

    def list_implant_lots(self, headers, params=None):
        return self._request("GET", "/implant-lots", headers=headers, params=params)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/implant-lots/{lot_id}/quarantine", payload, headers
        )

    # --- Implant reservations -------------------------------------------
    def create_reservation(self, payload, headers):
        return self._request("POST", "/implant-reservations", payload, headers)

    def auto_size_reservation(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/surgical-cases/{case_id}/implant-reservations/auto-size",
            payload,
            headers,
        )

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/implant-reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", "/implant-reservations", headers=headers, params=params
        )

    def consume_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/implant-reservations/{reservation_id}/consume", payload, headers
        )

    def release_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/implant-reservations/{reservation_id}/release", payload, headers
        )

    # --- Adverse events -------------------------------------------------
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/adverse-events", payload, headers)

    def get_adverse_event(self, event_id, headers):
        return self._request("GET", f"/adverse-events/{event_id}", headers=headers)

    def list_adverse_events(self, headers, params=None):
        return self._request("GET", "/adverse-events", headers=headers, params=params)

    def morbidity_review(self, event_id, payload, headers):
        return self._request(
            "POST", f"/adverse-events/{event_id}/morbidity-review", payload, headers
        )

    def record_regulator_notification(self, event_id, payload, headers):
        return self._request(
            "POST", f"/adverse-events/{event_id}/regulator-notification", payload, headers
        )

    def close_adverse_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/adverse-events/{event_id}/close", payload, headers
        )

    # --- Imaging studies ------------------------------------------------
    def create_imaging_study(self, payload, headers):
        return self._request("POST", "/imaging-studies", payload, headers)

    def get_imaging_study(self, study_id, headers):
        return self._request("GET", f"/imaging-studies/{study_id}", headers=headers)

    def list_imaging_studies(self, headers, params=None):
        return self._request("GET", "/imaging-studies", headers=headers, params=params)


api_client = ApiClient()
