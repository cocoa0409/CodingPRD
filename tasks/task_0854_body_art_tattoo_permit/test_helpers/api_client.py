"""API client: one method per route defined in the PRD (§4).

Every route is mounted beneath the /body-art prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/body-art"


class ApiClient(GenericApiClient):
    # ─── Establishments ────────────────────────────────────────────────

    def create_establishment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/establishments", payload, headers)

    def get_establishment(self, establishment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/establishments/{establishment_id}", headers=headers
        )

    def list_establishments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/establishments", headers=headers, params=params
        )

    def activate_establishment(self, establishment_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/establishments/{establishment_id}/activate",
            {},
            headers,
        )

    def get_compliance_summary(self, establishment_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/establishments/{establishment_id}/compliance-summary",
            headers=headers,
        )

    def create_establishment_enforcement_action(self, establishment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/establishments/{establishment_id}/enforcement-actions",
            payload,
            headers,
        )

    # ─── Artists ───────────────────────────────────────────────────────

    def create_artist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"{PREFIX}/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/artists", headers=headers, params=params)

    def record_bbp_training(self, artist_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/artists/{artist_id}/bbp-training", payload, headers
        )

    def activate_artist(self, artist_id, headers):
        return self._request(
            "POST", f"{PREFIX}/artists/{artist_id}/activate", {}, headers
        )

    def create_artist_enforcement_action(self, artist_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/artists/{artist_id}/enforcement-actions",
            payload,
            headers,
        )

    # ─── Plan reviews ──────────────────────────────────────────────────

    def create_plan_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plan-reviews", payload, headers)

    def get_plan_review(self, plan_review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/plan-reviews/{plan_review_id}", headers=headers
        )

    def list_plan_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/plan-reviews", headers=headers, params=params
        )

    def decide_plan_review(self, plan_review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-reviews/{plan_review_id}/decision", payload, headers
        )

    def resubmit_plan_review(self, plan_review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-reviews/{plan_review_id}/resubmit", payload, headers
        )

    # ─── Inspections ───────────────────────────────────────────────────

    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspections", headers=headers, params=params
        )

    def start_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/start", {}, headers
        )

    def finalize_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/finalize", {}, headers
        )

    def create_violation(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/violations", payload, headers
        )

    # ─── Violations ────────────────────────────────────────────────────

    def get_violation(self, violation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/violations/{violation_id}", headers=headers
        )

    def list_violations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/violations", headers=headers, params=params
        )

    def submit_violation_correction(self, violation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violations/{violation_id}/correction", payload, headers
        )

    def decide_violation_correction(self, violation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/violations/{violation_id}/correction-decision",
            payload,
            headers,
        )

    # ─── Sterilization records ─────────────────────────────────────────

    def create_sterilization_record(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sterilization-records", payload, headers
        )

    def get_sterilization_record(self, sterilization_record_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/sterilization-records/{sterilization_record_id}",
            headers=headers,
        )

    def list_sterilization_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sterilization-records", headers=headers, params=params
        )

    # ─── Minor consents ────────────────────────────────────────────────

    def create_minor_consent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/minor-consents", payload, headers)

    def get_minor_consent(self, minor_consent_id, headers):
        return self._request(
            "GET", f"{PREFIX}/minor-consents/{minor_consent_id}", headers=headers
        )

    def list_minor_consents(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/minor-consents", headers=headers, params=params
        )

    def verify_minor_consent(self, minor_consent_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/minor-consents/{minor_consent_id}/verify",
            payload,
            headers,
        )

    # ─── Procedure logs ────────────────────────────────────────────────

    def create_procedure_log(self, payload, headers):
        return self._request("POST", f"{PREFIX}/procedure-logs", payload, headers)

    def get_procedure_log(self, procedure_log_id, headers):
        return self._request(
            "GET", f"{PREFIX}/procedure-logs/{procedure_log_id}", headers=headers
        )

    def list_procedure_logs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/procedure-logs", headers=headers, params=params
        )

    def audit_procedure_log(self, procedure_log_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/procedure-logs/{procedure_log_id}/audit",
            payload,
            headers,
        )

    # ─── Complaints ────────────────────────────────────────────────────

    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers
        )

    def list_complaints(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints", headers=headers, params=params
        )

    def transition_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/transition", payload, headers
        )

    # ─── Infection reports ─────────────────────────────────────────────

    def create_infection_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/infection-reports", payload, headers)

    def get_infection_report(self, infection_report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/infection-reports/{infection_report_id}", headers=headers
        )

    def list_infection_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/infection-reports", headers=headers, params=params
        )

    def advance_infection_investigation(self, infection_report_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/infection-reports/{infection_report_id}/investigation",
            payload,
            headers,
        )

    def advance_infection_notification(self, infection_report_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/infection-reports/{infection_report_id}/notification",
            payload,
            headers,
        )

    # ─── Enforcement actions ───────────────────────────────────────────

    def get_enforcement_action(self, enforcement_action_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/enforcement-actions/{enforcement_action_id}",
            headers=headers,
        )

    def list_enforcement_actions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/enforcement-actions", headers=headers, params=params
        )

    def lift_enforcement_action(self, enforcement_action_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/enforcement-actions/{enforcement_action_id}/lift",
            {},
            headers,
        )

    # ─── Renewal applications ──────────────────────────────────────────

    def create_renewal_application(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/renewal-applications", payload, headers
        )

    def get_renewal_application(self, renewal_application_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/renewal-applications/{renewal_application_id}",
            headers=headers,
        )

    def list_renewal_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/renewal-applications", headers=headers, params=params
        )

    def submit_renewal_application(self, renewal_application_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-applications/{renewal_application_id}/submit",
            {},
            headers,
        )

    def pay_renewal_application(self, renewal_application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-applications/{renewal_application_id}/payment",
            payload,
            headers,
        )

    def review_renewal_application(self, renewal_application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-applications/{renewal_application_id}/review",
            payload,
            headers,
        )

    def refund_renewal_application(self, renewal_application_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-applications/{renewal_application_id}/refund",
            {},
            headers,
        )

    # ─── Logical clock ─────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
