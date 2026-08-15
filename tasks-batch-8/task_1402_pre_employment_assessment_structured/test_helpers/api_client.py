"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Vendors & content security ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/talent/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/talent/vendors/{vendor_id}", headers=headers)

    def list_vendor_instruments(self, vendor_id, headers):
        return self._request("GET", f"/talent/vendors/{vendor_id}/instruments", headers=headers)

    def list_vendor_content_ledger_events(self, vendor_id, headers):
        return self._request("GET", f"/talent/vendors/{vendor_id}/content-ledger-events", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/talent/vendors/{vendor_id}/suspend", headers=headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/talent/vendors/{vendor_id}/reinstate", headers=headers)

    def terminate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/talent/vendors/{vendor_id}/terminate", headers=headers)

    def create_content_ledger_event(self, vendor_id, payload, headers):
        return self._request("POST", f"/talent/vendors/{vendor_id}/content-ledger-events", payload, headers)

    # ---- Instruments & validation evidence ----
    def create_instrument(self, payload, headers):
        return self._request("POST", "/talent/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/talent/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/talent/instruments/{instrument_id}", headers=headers)

    def submit_instrument_validation_review(self, instrument_id, headers):
        return self._request("POST", f"/talent/instruments/{instrument_id}/submit-validation-review", headers=headers)

    def validate_instrument(self, instrument_id, headers):
        return self._request("POST", f"/talent/instruments/{instrument_id}/validate", headers=headers)

    def begin_instrument_revalidation(self, instrument_id, headers):
        return self._request("POST", f"/talent/instruments/{instrument_id}/begin-revalidation", headers=headers)

    def retire_instrument(self, instrument_id, headers):
        return self._request("POST", f"/talent/instruments/{instrument_id}/retire", headers=headers)

    def create_evidence(self, instrument_id, payload, headers):
        return self._request("POST", f"/talent/instruments/{instrument_id}/evidence", payload, headers)

    def list_evidence(self, instrument_id, headers):
        return self._request("GET", f"/talent/instruments/{instrument_id}/evidence", headers=headers)

    # ---- Interview guides & rubrics ----
    def create_guide(self, payload, headers):
        return self._request("POST", "/talent/interview-guides", payload, headers)

    def create_guide_revision(self, guide_id, payload, headers):
        return self._request("POST", f"/talent/interview-guides/{guide_id}/revisions", payload, headers)

    def list_guides(self, headers, params=None):
        return self._request("GET", "/talent/interview-guides", headers=headers, params=params)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/talent/interview-guides/{guide_id}", headers=headers)

    def pilot_guide(self, guide_id, headers):
        return self._request("POST", f"/talent/interview-guides/{guide_id}/pilot", headers=headers)

    def retract_guide(self, guide_id, headers):
        return self._request("POST", f"/talent/interview-guides/{guide_id}/retract", headers=headers)

    def approve_guide(self, guide_id, headers):
        return self._request("POST", f"/talent/interview-guides/{guide_id}/approve", headers=headers)

    def retire_guide(self, guide_id, headers):
        return self._request("POST", f"/talent/interview-guides/{guide_id}/retire", headers=headers)

    # ---- Requisitions ----
    def create_requisition(self, payload, headers):
        return self._request("POST", "/talent/requisitions", payload, headers)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/talent/requisitions/{requisition_id}", headers=headers)

    def close_requisition(self, requisition_id, headers):
        return self._request("POST", f"/talent/requisitions/{requisition_id}/close", headers=headers)

    def create_cycle(self, requisition_id, payload, headers):
        return self._request("POST", f"/talent/requisitions/{requisition_id}/cycles", payload, headers)

    # ---- Cycles ----
    def list_cycles(self, headers, params=None):
        return self._request("GET", "/talent/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/talent/cycles/{cycle_id}", headers=headers)

    def patch_cycle(self, cycle_id, payload, headers):
        return self._request("PATCH", f"/talent/cycles/{cycle_id}", payload, headers)

    def activate_cycle(self, cycle_id, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/activate", headers=headers)

    def freeze_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/freeze", payload, headers)

    def unfreeze_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/unfreeze", payload, headers)

    def begin_cycle_scoring(self, cycle_id, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/begin-scoring", headers=headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/close", headers=headers)

    def create_invitation(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/invitations", payload, headers)

    def create_session(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/sessions", payload, headers)

    def create_decision(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/decisions", payload, headers)

    def create_adverse_impact_snapshot(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/cycles/{cycle_id}/adverse-impact-snapshots", payload, headers)

    def list_adverse_impact_snapshots(self, cycle_id, headers):
        return self._request("GET", f"/talent/cycles/{cycle_id}/adverse-impact-snapshots", headers=headers)

    # ---- Candidates ----
    def create_candidate(self, payload, headers):
        return self._request("POST", "/talent/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/talent/candidates/{candidate_id}", headers=headers)

    def withdraw_candidate(self, candidate_id, headers):
        return self._request("POST", f"/talent/candidates/{candidate_id}/withdraw", headers=headers)

    # ---- Candidate assessments ----
    def list_assessments(self, headers, params=None):
        return self._request("GET", "/talent/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/talent/assessments/{assessment_id}", headers=headers)

    def schedule_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/schedule", payload, headers)

    def start_assessment(self, assessment_id, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/start", headers=headers)

    def complete_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/complete", payload, headers)

    def mark_assessment_no_show(self, assessment_id, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/mark-no-show", headers=headers)

    def cancel_assessment(self, assessment_id, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/cancel", headers=headers)

    def reschedule_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/reschedule", payload, headers)

    def send_feedback(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/feedback", payload, headers)

    def create_accommodation_request(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/assessments/{assessment_id}/accommodation-requests", payload, headers)

    def list_accommodation_requests(self, assessment_id, headers):
        return self._request("GET", f"/talent/assessments/{assessment_id}/accommodation-requests", headers=headers)

    def list_purge_events(self, assessment_id, headers):
        return self._request("GET", f"/talent/assessments/{assessment_id}/purge-events", headers=headers)

    # ---- Accommodation requests ----
    def get_accommodation_request(self, request_id, headers):
        return self._request("GET", f"/talent/accommodation-requests/{request_id}", headers=headers)

    def approve_accommodation_request(self, request_id, payload, headers):
        return self._request("POST", f"/talent/accommodation-requests/{request_id}/approve", payload, headers)

    def deny_accommodation_request(self, request_id, payload, headers):
        return self._request("POST", f"/talent/accommodation-requests/{request_id}/deny", payload, headers)

    def withdraw_accommodation_request(self, request_id, headers):
        return self._request("POST", f"/talent/accommodation-requests/{request_id}/withdraw", headers=headers)

    # ---- Interviewers & calibration ----
    def create_interviewer(self, payload, headers):
        return self._request("POST", "/talent/interviewers", payload, headers)

    def get_interviewer(self, interviewer_id, headers):
        return self._request("GET", f"/talent/interviewers/{interviewer_id}", headers=headers)

    def create_calibration(self, interviewer_id, payload, headers):
        return self._request("POST", f"/talent/interviewers/{interviewer_id}/calibrations", payload, headers)

    def list_calibrations(self, headers, params=None):
        return self._request("GET", "/talent/calibrations", headers=headers, params=params)

    def get_calibration(self, calibration_id, headers):
        return self._request("GET", f"/talent/calibrations/{calibration_id}", headers=headers)

    def certify_calibration(self, calibration_id, payload, headers):
        return self._request("POST", f"/talent/calibrations/{calibration_id}/certify", payload, headers)

    # ---- Interview sessions ----
    def list_sessions(self, headers, params=None):
        return self._request("GET", "/talent/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/talent/sessions/{session_id}", headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/talent/sessions/{session_id}/complete", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/talent/sessions/{session_id}/cancel", headers=headers)

    def create_scorecard(self, session_id, payload, headers):
        return self._request("POST", f"/talent/sessions/{session_id}/scorecards", payload, headers)

    # ---- Scorecards ----
    def list_scorecards(self, headers, params=None):
        return self._request("GET", "/talent/scorecards", headers=headers, params=params)

    def get_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/talent/scorecards/{scorecard_id}", headers=headers)

    def submit_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/talent/scorecards/{scorecard_id}/submit", headers=headers)

    def void_scorecard(self, scorecard_id, payload, headers):
        return self._request("POST", f"/talent/scorecards/{scorecard_id}/void", payload, headers)

    # ---- Hiring decisions ----
    def list_decisions(self, headers, params=None):
        return self._request("GET", "/talent/decisions", headers=headers, params=params)

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"/talent/decisions/{decision_id}", headers=headers)

    # ---- Adverse impact snapshots ----
    def get_adverse_impact_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/talent/adverse-impact-snapshots/{snapshot_id}", headers=headers)

    # ---- Retention ----
    def run_retention_sweep(self, headers):
        return self._request("POST", "/talent/retention-sweeps", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/talent/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
