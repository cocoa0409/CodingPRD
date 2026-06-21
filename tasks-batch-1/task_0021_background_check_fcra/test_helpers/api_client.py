"""API client: one method per endpoint defined in the PRD (PRD §4).

All endpoints are mounted under `/api/v1` (PRD §4 routing prefix).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/api/v1"


class ApiClient(GenericApiClient):
    # ─── Jurisdictions ─────────────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"{PREFIX}/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/jurisdictions", headers=headers, params=params)

    # ─── Applicants ────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    # ─── Applications ──────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def submit_application(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/submit", payload, headers)

    def conditional_offer(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/conditional-offer", payload, headers)

    def hire_application(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/hire", payload, headers)

    def withdraw_application(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/withdraw", payload, headers)

    def list_application_consents(self, application_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications/{application_id}/consents",
                             headers=headers, params=params)

    # ─── Consents ──────────────────────────────────────────
    def create_consent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consents", payload, headers)

    def grant_consent(self, consent_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/grant", payload, headers)

    def revoke_consent(self, consent_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/revoke", payload, headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"{PREFIX}/consents/{consent_id}", headers=headers)

    # ─── BackgroundCheckOrders ─────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/background-check-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/background-check-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/background-check-orders", headers=headers, params=params)

    def create_verification(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/background-check-orders/{order_id}/verifications",
                             payload, headers)

    def list_order_verifications(self, order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/background-check-orders/{order_id}/verifications",
                             headers=headers, params=params)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/background-check-orders/{order_id}/cancel",
                             payload, headers)

    def get_risk_score(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/background-check-orders/{order_id}/risk-score",
                             headers=headers)

    def list_order_adverse_action(self, order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/background-check-orders/{order_id}/adverse-action",
                             headers=headers, params=params)

    # ─── Verifications ─────────────────────────────────────
    def get_verification(self, verification_id, headers):
        return self._request("GET", f"{PREFIX}/verifications/{verification_id}", headers=headers)

    def report_verification(self, verification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/verifications/{verification_id}/report",
                             payload, headers)

    def dispute_verification(self, verification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/verifications/{verification_id}/dispute",
                             payload, headers)

    def resolve_verification(self, verification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/verifications/{verification_id}/resolve",
                             payload, headers)

    # ─── AdverseActions ────────────────────────────────────
    def get_adverse_action(self, adverse_action_id, headers):
        return self._request("GET", f"{PREFIX}/adverse-actions/{adverse_action_id}", headers=headers)

    def finalize_adverse_action(self, adverse_action_id, payload, headers):
        return self._request("POST", f"{PREFIX}/adverse-actions/{adverse_action_id}/finalize",
                             payload, headers)

    # ─── AuditLog ──────────────────────────────────────────
    def list_audit_logs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audit-logs", headers=headers, params=params)

    # ─── SystemClock (test-driving) ────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", f"{PREFIX}/_clock", headers=headers)


api_client = ApiClient()
