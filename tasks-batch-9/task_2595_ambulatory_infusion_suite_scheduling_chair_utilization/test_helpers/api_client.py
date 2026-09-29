"""One method per endpoint of the Infusion Suite Scheduling API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin transport wrapper: every method returns the raw ``requests.Response``."""

    # ------------------------------------------------------------------
    # Infusion centers
    # ------------------------------------------------------------------
    def create_center(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/infusion-centers", payload, headers)

    def get_center(self, center_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/infusion-centers/{center_id}", None, headers)

    def list_centers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/infusion-centers", params, headers)

    def get_utilization(
        self, center_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/infusion-centers/{center_id}/utilization", params, headers
        )

    def get_chair_billing_summary(
        self, center_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/infusion-centers/{center_id}/chair-billing-summary", params, headers
        )

    def run_daily_sweep(
        self, center_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/infusion-centers/{center_id}/daily-sweep", payload, headers
        )

    # ------------------------------------------------------------------
    # Chairs
    # ------------------------------------------------------------------
    def create_chair(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/chairs", payload, headers)

    def get_chair(self, chair_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/chairs/{chair_id}", None, headers)

    def list_chairs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/chairs", params, headers)

    def update_chair(
        self, chair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/chairs/{chair_id}", payload, headers)

    # ------------------------------------------------------------------
    # Nurses
    # ------------------------------------------------------------------
    def create_nurse(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/nurses", payload, headers)

    def get_nurse(self, nurse_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/nurses/{nurse_id}", None, headers)

    def list_nurses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/nurses", params, headers)

    def update_nurse(
        self, nurse_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/nurses/{nurse_id}", payload, headers)

    # ------------------------------------------------------------------
    # Drugs
    # ------------------------------------------------------------------
    def create_drug(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/drugs", payload, headers)

    def get_drug(self, drug_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/drugs/{drug_id}", None, headers)

    def list_drugs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/drugs", params, headers)

    # ------------------------------------------------------------------
    # Drug lots
    # ------------------------------------------------------------------
    def create_drug_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/drug-lots", payload, headers)

    def get_drug_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/drug-lots/{lot_id}", None, headers)

    def list_drug_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/drug-lots", params, headers)

    def create_lot_adjustment(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/drug-lots/{lot_id}/adjustments", payload, headers
        )

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/patients/{patient_id}", None, headers)

    def list_patients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/patients", params, headers)

    def get_no_show_risk(
        self, patient_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/patients/{patient_id}/no-show-risk", params, headers
        )

    # ------------------------------------------------------------------
    # Treatment plans
    # ------------------------------------------------------------------
    def create_treatment_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/treatment-plans", payload, headers)

    def get_treatment_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/treatment-plans/{plan_id}", None, headers)

    def list_treatment_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/treatment-plans", params, headers)

    def create_plan_revision(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/revisions", payload, headers
        )

    def resume_treatment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/resume", payload, headers
        )

    # ------------------------------------------------------------------
    # Appointment templates
    # ------------------------------------------------------------------
    def create_template(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appointment-templates", payload, headers)

    def get_template(self, template_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appointment-templates/{template_id}", None, headers
        )

    def list_templates(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/appointment-templates", params, headers)

    def update_template(
        self, template_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/appointment-templates/{template_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------
    def create_appointment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/appointments/{appointment_id}", None, headers)

    def list_appointments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/appointments", params, headers)

    def confirm_appointment(
        self,
        appointment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/confirm", payload or {}, headers
        )

    def check_in_appointment(
        self,
        appointment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/check-in", payload or {}, headers
        )

    def start_infusion(
        self,
        appointment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/appointments/{appointment_id}/start-infusion",
            payload or {},
            headers,
        )

    def complete_infusion(
        self,
        appointment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/appointments/{appointment_id}/complete-infusion",
            payload or {},
            headers,
        )

    def discharge_appointment(
        self,
        appointment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/discharge", payload or {}, headers
        )

    def cancel_appointment(
        self,
        appointment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", payload or {}, headers
        )

    def reschedule_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/reschedule", payload, headers
        )

    def create_authorization_request(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/appointments/{appointment_id}/authorization-requests",
            payload,
            headers,
        )

    def create_drug_preparation(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/drug-preparations", payload, headers
        )

    def create_adverse_event(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/adverse-events", payload, headers
        )

    def create_reminder(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appointments/{appointment_id}/reminders", payload, headers
        )

    # ------------------------------------------------------------------
    # Authorization requests
    # ------------------------------------------------------------------
    def get_authorization_request(self, auth_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/authorization-requests/{auth_id}", None, headers)

    def list_authorization_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/authorization-requests", params, headers)

    def submit_authorization(
        self,
        auth_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/submit", payload or {}, headers
        )

    def decide_authorization(
        self, auth_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Drug preparations
    # ------------------------------------------------------------------
    def get_drug_preparation(self, prep_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/drug-preparations/{prep_id}", None, headers)

    def list_drug_preparations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/drug-preparations", params, headers)

    def prepare_dose(
        self,
        prep_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/drug-preparations/{prep_id}/prepare", payload or {}, headers
        )

    def return_dose(
        self,
        prep_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/drug-preparations/{prep_id}/return", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Adverse events
    # ------------------------------------------------------------------
    def get_adverse_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/adverse-events/{event_id}", None, headers)

    def list_adverse_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/adverse-events", params, headers)

    def start_adverse_event_review(
        self,
        event_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/adverse-events/{event_id}/start-review", payload or {}, headers
        )

    def close_adverse_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/adverse-events/{event_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Lab results
    # ------------------------------------------------------------------
    def create_lab_result(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/lab-results", payload, headers)

    def get_lab_result(self, lab_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lab-results/{lab_id}", None, headers)

    def list_lab_results(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/lab-results", params, headers)

    # ------------------------------------------------------------------
    # Reminder contacts
    # ------------------------------------------------------------------
    def get_reminder_contact(self, reminder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reminder-contacts/{reminder_id}", None, headers)

    def list_reminder_contacts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/reminder-contacts", params, headers)

    def respond_to_reminder(
        self, reminder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reminder-contacts/{reminder_id}/response", payload, headers
        )

    # ------------------------------------------------------------------
    # Operational capabilities
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def inject_appointment_history(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/_inject/appointment_history", payload, headers)
