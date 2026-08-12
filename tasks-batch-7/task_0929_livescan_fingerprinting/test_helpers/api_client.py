"""API client: one method per endpoint defined in the PRD.

Every path is mounted beneath the /livescan prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/livescan"


class ApiClient(GenericApiClient):
    # ---------------- Operations ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def aging_run(self, headers, payload=None):
        return self._request("POST", f"{PREFIX}/_ops/aging-run", payload or {}, headers)

    # ---------------- Agencies ----------------
    def create_agency(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"{PREFIX}/agencies/{agency_id}", headers=headers)

    # ---------------- ORIs ----------------
    def create_ori(self, payload, headers):
        return self._request("POST", f"{PREFIX}/oris", payload, headers)

    def get_ori(self, ori_id, headers):
        return self._request("GET", f"{PREFIX}/oris/{ori_id}", headers=headers)

    def list_oris(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/oris", headers=headers, params=params)

    def set_ori_authority_status(self, ori_id, to_status, headers):
        return self._request(
            "POST", f"{PREFIX}/oris/{ori_id}/authority-status", {"to_status": to_status}, headers
        )

    # ---------------- Service types ----------------
    def create_service_type(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-types", payload, headers)

    def get_service_type(self, service_type_id, headers):
        return self._request("GET", f"{PREFIX}/service-types/{service_type_id}", headers=headers)

    def list_service_types(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-types", headers=headers, params=params)

    # ---------------- Capture sites ----------------
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def reconcile_event(self, site_id, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/event-reconciliation", {}, headers)

    # ---------------- Devices ----------------
    def create_device(self, payload, headers):
        return self._request("POST", f"{PREFIX}/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"{PREFIX}/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/devices", headers=headers, params=params)

    def record_calibration(self, device_id, calibrated_at, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/calibration", {"calibrated_at": calibrated_at}, headers
        )

    def run_calibration_audit(self, device_id, corrected_last_calibrated_at, headers):
        return self._request(
            "POST",
            f"{PREFIX}/devices/{device_id}/calibration-audit",
            {"corrected_last_calibrated_at": corrected_last_calibrated_at},
            headers,
        )

    # ---------------- Device assignments ----------------
    def create_device_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/device-assignments", payload, headers)

    def get_device_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/device-assignments/{assignment_id}", headers=headers)

    def list_device_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/device-assignments", headers=headers, params=params)

    def release_device_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/device-assignments/{assignment_id}/release", {}, headers
        )

    # ---------------- Applicants ----------------
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    def patch_applicant(self, applicant_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/applicants/{applicant_id}", payload, headers)

    # ---------------- Appointments ----------------
    def create_appointment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"{PREFIX}/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appointments", headers=headers, params=params)

    def reschedule_appointment(self, appointment_id, scheduled_start, headers):
        return self._request(
            "POST",
            f"{PREFIX}/appointments/{appointment_id}/reschedule",
            {"scheduled_start": scheduled_start},
            headers,
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"{PREFIX}/appointments/{appointment_id}/cancel", {}, headers)

    def check_in_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/appointments/{appointment_id}/check-in", payload, headers
        )

    def mark_no_show(self, appointment_id, headers):
        return self._request("POST", f"{PREFIX}/appointments/{appointment_id}/no-show", {}, headers)

    # ---------------- Fingerprint cards ----------------
    def create_card(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cards", payload, headers)

    def get_card(self, card_id, headers):
        return self._request("GET", f"{PREFIX}/cards/{card_id}", headers=headers)

    def list_cards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cards", headers=headers, params=params)

    def list_card_positions(self, card_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cards/{card_id}/positions", headers=headers, params=params
        )

    def record_attempt(self, card_id, position_code, score, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cards/{card_id}/positions/{position_code}/attempts",
            {"score": score},
            headers,
        )

    def code_exception(self, card_id, position_code, exception_code, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cards/{card_id}/positions/{position_code}/exception",
            {"exception_code": exception_code},
            headers,
        )

    def grant_exception_override(self, card_id, justification, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cards/{card_id}/exception-override",
            {"justification": justification},
            headers,
        )

    def finalize_card(self, card_id, headers):
        return self._request("POST", f"{PREFIX}/cards/{card_id}/finalize", {}, headers)

    # ---------------- Submissions ----------------
    def create_submission(self, payload, headers):
        return self._request("POST", f"{PREFIX}/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"{PREFIX}/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/submissions", headers=headers, params=params)

    def post_destination_result(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/destination-results", payload, headers
        )

    def list_submission_responses(self, submission_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/submissions/{submission_id}/responses", headers=headers, params=params
        )

    def get_chr_response(self, response_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/chr-responses/{response_id}", headers=headers, params=params
        )

    def authorize_reprint(self, submission_id, device_id, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/reprints", {"device_id": device_id}, headers
        )

    def request_purge(self, submission_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/purge-requests", {"reason": reason}, headers
        )

    def decide_purge(self, submission_id, decision, headers):
        return self._request(
            "POST",
            f"{PREFIX}/submissions/{submission_id}/purge-decisions",
            {"decision": decision},
            headers,
        )

    # ---------------- Fitness determinations ----------------
    def create_fitness_determination(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fitness-determinations", payload, headers)

    def get_fitness_determination(self, determination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fitness-determinations/{determination_id}", headers=headers
        )

    def list_fitness_determinations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fitness-determinations", headers=headers, params=params
        )

    def file_challenge(self, determination_id, grounds, headers):
        return self._request(
            "POST",
            f"{PREFIX}/fitness-determinations/{determination_id}/challenges",
            {"grounds": grounds},
            headers,
        )

    def resolve_challenge(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/fitness-determinations/{determination_id}/challenge-resolutions",
            payload,
            headers,
        )

    # ---------------- Rap-back ----------------
    def create_rapback_subscription(self, submission_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rapback-subscriptions", {"submission_id": submission_id}, headers
        )

    def get_rapback_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rapback-subscriptions/{subscription_id}", headers=headers
        )

    def list_rapback_subscriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rapback-subscriptions", headers=headers, params=params)

    def renew_rapback_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rapback-subscriptions/{subscription_id}/renew", {}, headers
        )

    def cancel_rapback_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rapback-subscriptions/{subscription_id}/cancel", {}, headers
        )

    def create_rapback_notification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rapback-notifications", payload, headers)

    def get_rapback_notification(self, notification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rapback-notifications/{notification_id}", headers=headers
        )

    def list_rapback_notifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rapback-notifications", headers=headers, params=params)

    def acknowledge_rapback_notification(self, notification_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rapback-notifications/{notification_id}/acknowledge", {}, headers
        )

    # ---------------- Fees and invoices ----------------
    def get_fee_assessment(self, assessment_id, headers):
        return self._request("GET", f"{PREFIX}/fee-assessments/{assessment_id}", headers=headers)

    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fee-assessments", headers=headers, params=params)

    def pay_fee_assessment(self, assessment_id, amount_cents, headers):
        return self._request(
            "POST",
            f"{PREFIX}/fee-assessments/{assessment_id}/payments",
            {"amount_cents": amount_cents},
            headers,
        )

    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, amount_cents, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/payments", {"amount_cents": amount_cents}, headers
        )


api_client = ApiClient()
