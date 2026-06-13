"""API client: one method per endpoint defined in the PRD."""
import time

from requests.exceptions import ConnectionError as RequestsConnectionError
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # The runner restarts the server (per-test-server isolation) before every
        # test. The first request after a restart can race a stale keep-alive
        # socket left in the pooled session, surfacing as a BadStatusLine /
        # ConnectionError. Send `Connection: close` so no socket is reused, and
        # retry once on a connection-level failure (test_helpers-only).
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        last_exc = None
        for _ in range(2):
            try:
                return super()._request(method, path, payload, hdrs, params)
            except RequestsConnectionError as exc:
                last_exc = exc
                self.session.close()
                time.sleep(0.1)
        raise last_exc

    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Officers ─────────────────────────────────────────────────────────
    def create_officer(self, payload, headers):
        return self._request("POST", "/officers", payload, headers)

    def get_officer(self, officer_id, headers):
        return self._request("GET", f"/officers/{officer_id}", headers=headers)

    def list_officers(self, headers, params=None):
        return self._request("GET", "/officers", headers=headers, params=params)

    # ─── Supervisees ──────────────────────────────────────────────────────
    def create_supervisee(self, payload, headers):
        return self._request("POST", "/supervisees", payload, headers)

    def get_supervisee(self, supervisee_id, headers):
        return self._request("GET", f"/supervisees/{supervisee_id}", headers=headers)

    def list_supervisees(self, headers, params=None):
        return self._request("GET", "/supervisees", headers=headers, params=params)

    def activate_supervisee(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/activate", {}, headers
        )

    def abscond_supervisee(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/abscond", {}, headers
        )

    def return_to_supervision(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/return-to-supervision", {}, headers
        )

    def refer_revocation(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/refer-revocation", {}, headers
        )

    def revoke_supervisee(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/revoke", {}, headers
        )

    def reinstate_supervisee(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/reinstate", {}, headers
        )

    def complete_supervisee(self, supervisee_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/complete", {}, headers
        )

    def get_compliance(self, supervisee_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/compliance", headers=headers
        )

    def get_payoff_quote(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/payoff-quote",
            headers=headers, params=params,
        )

    # ─── Risk Assessments ─────────────────────────────────────────────────
    def create_risk_assessment(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/risk-assessments", payload, headers
        )

    def list_risk_assessments(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/risk-assessments",
            headers=headers, params=params,
        )

    def get_risk_assessment(self, supervisee_id, ra_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/risk-assessments/{ra_id}",
            headers=headers,
        )

    def adopt_risk_assessment(self, supervisee_id, ra_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/risk-assessments/{ra_id}/adopt",
            {}, headers,
        )

    # ─── Conditions ───────────────────────────────────────────────────────
    def create_condition(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/conditions", payload, headers
        )

    def list_conditions(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/conditions",
            headers=headers, params=params,
        )

    def get_condition(self, supervisee_id, cond_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/conditions/{cond_id}",
            headers=headers,
        )

    def activate_condition(self, supervisee_id, cond_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/conditions/{cond_id}/activate",
            {}, headers,
        )

    def satisfy_condition(self, supervisee_id, cond_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/conditions/{cond_id}/satisfy",
            {}, headers,
        )

    def waive_condition(self, supervisee_id, cond_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/conditions/{cond_id}/waive",
            {}, headers,
        )

    # ─── Check-ins ────────────────────────────────────────────────────────
    def create_check_in(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/check-ins", payload, headers
        )

    def list_check_ins(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/check-ins",
            headers=headers, params=params,
        )

    def get_check_in(self, supervisee_id, ci_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/check-ins/{ci_id}", headers=headers
        )

    def attend_check_in(self, supervisee_id, ci_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/check-ins/{ci_id}/attend",
            payload, headers,
        )

    def mark_missed_check_in(self, supervisee_id, ci_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/check-ins/{ci_id}/mark-missed",
            {}, headers,
        )

    def excuse_check_in(self, supervisee_id, ci_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/check-ins/{ci_id}/excuse",
            {}, headers,
        )

    # ─── Drug Tests ───────────────────────────────────────────────────────
    def create_drug_test(self, supervisee_id, ci_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/check-ins/{ci_id}/drug-tests",
            payload, headers,
        )

    def list_drug_tests(self, supervisee_id, ci_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/check-ins/{ci_id}/drug-tests",
            headers=headers, params=params,
        )

    # ─── Violations ───────────────────────────────────────────────────────
    def create_violation(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/violations", payload, headers
        )

    def list_violations(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/violations",
            headers=headers, params=params,
        )

    def get_violation(self, supervisee_id, v_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/violations/{v_id}", headers=headers
        )

    def sustain_violation(self, supervisee_id, v_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/violations/{v_id}/sustain",
            {}, headers,
        )

    def dismiss_violation(self, supervisee_id, v_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/violations/{v_id}/dismiss",
            {}, headers,
        )

    def appeal_violation(self, supervisee_id, v_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/violations/{v_id}/appeal",
            {}, headers,
        )

    def list_sanctions_for_violation(self, supervisee_id, v_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/violations/{v_id}/sanctions",
            headers=headers, params=params,
        )

    # ─── Obligations ──────────────────────────────────────────────────────
    def create_obligation(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/obligations", payload, headers
        )

    def list_obligations(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/obligations",
            headers=headers, params=params,
        )

    def get_obligation(self, supervisee_id, ob_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/obligations/{ob_id}", headers=headers
        )

    def discharge_obligation(self, supervisee_id, ob_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/obligations/{ob_id}/discharge",
            {}, headers,
        )

    def list_payments_for_obligation(self, supervisee_id, ob_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/obligations/{ob_id}/payments",
            headers=headers, params=params,
        )

    # ─── Payments ─────────────────────────────────────────────────────────
    def create_payment(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/payments", payload, headers
        )

    def list_payments(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/payments",
            headers=headers, params=params,
        )

    # ─── Court Reports ────────────────────────────────────────────────────
    def create_court_report(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/court-reports", payload, headers
        )

    def list_court_reports(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/court-reports",
            headers=headers, params=params,
        )

    def get_court_report(self, supervisee_id, cr_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/court-reports/{cr_id}",
            headers=headers,
        )

    def file_court_report(self, supervisee_id, cr_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/court-reports/{cr_id}/file",
            {}, headers,
        )

    # ─── Interstate Transfers ─────────────────────────────────────────────
    def create_transfer(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/transfers", payload, headers
        )

    def list_transfers(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/transfers",
            headers=headers, params=params,
        )

    def get_transfer(self, supervisee_id, xfer_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/transfers/{xfer_id}", headers=headers
        )

    def accept_transfer(self, supervisee_id, xfer_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/transfers/{xfer_id}/accept",
            payload, headers,
        )

    def reject_transfer(self, supervisee_id, xfer_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/transfers/{xfer_id}/reject",
            payload, headers,
        )

    def withdraw_transfer(self, supervisee_id, xfer_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/transfers/{xfer_id}/withdraw",
            {}, headers,
        )

    # ─── Early Terminations ───────────────────────────────────────────────
    def create_early_termination(self, supervisee_id, payload, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/early-terminations", payload, headers
        )

    def list_early_terminations(self, supervisee_id, headers, params=None):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/early-terminations",
            headers=headers, params=params,
        )

    def get_early_termination(self, supervisee_id, et_id, headers):
        return self._request(
            "GET", f"/supervisees/{supervisee_id}/early-terminations/{et_id}",
            headers=headers,
        )

    def grant_early_termination(self, supervisee_id, et_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/early-terminations/{et_id}/grant",
            {}, headers,
        )

    def deny_early_termination(self, supervisee_id, et_id, headers):
        return self._request(
            "POST", f"/supervisees/{supervisee_id}/early-terminations/{et_id}/deny",
            {}, headers,
        )

    # ─── Flat reverse-reachability GETs ───────────────────────────────────
    def get_risk_assessment_flat(self, ra_id, headers):
        return self._request("GET", f"/risk-assessments/{ra_id}", headers=headers)

    def list_risk_assessments_flat(self, headers, params=None):
        return self._request("GET", "/risk-assessments", headers=headers, params=params)

    def get_condition_flat(self, cond_id, headers):
        return self._request("GET", f"/conditions/{cond_id}", headers=headers)

    def list_conditions_flat(self, headers, params=None):
        return self._request("GET", "/conditions", headers=headers, params=params)

    def get_check_in_flat(self, ci_id, headers):
        return self._request("GET", f"/check-ins/{ci_id}", headers=headers)

    def list_check_ins_flat(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    def get_drug_test_flat(self, dt_id, headers):
        return self._request("GET", f"/drug-tests/{dt_id}", headers=headers)

    def list_drug_tests_flat(self, headers, params=None):
        return self._request("GET", "/drug-tests", headers=headers, params=params)

    def get_violation_flat(self, v_id, headers):
        return self._request("GET", f"/violations/{v_id}", headers=headers)

    def list_violations_flat(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def get_sanction_flat(self, s_id, headers):
        return self._request("GET", f"/sanctions/{s_id}", headers=headers)

    def list_sanctions_flat(self, headers, params=None):
        return self._request("GET", "/sanctions", headers=headers, params=params)

    def get_obligation_flat(self, ob_id, headers):
        return self._request("GET", f"/obligations/{ob_id}", headers=headers)

    def list_obligations_flat(self, headers, params=None):
        return self._request("GET", "/obligations", headers=headers, params=params)

    def get_payment_flat(self, pay_id, headers):
        return self._request("GET", f"/payments/{pay_id}", headers=headers)

    def list_payments_flat(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_court_report_flat(self, cr_id, headers):
        return self._request("GET", f"/court-reports/{cr_id}", headers=headers)

    def list_court_reports_flat(self, headers, params=None):
        return self._request("GET", "/court-reports", headers=headers, params=params)

    def get_transfer_flat(self, xfer_id, headers):
        return self._request("GET", f"/transfers/{xfer_id}", headers=headers)

    def list_transfers_flat(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def get_early_termination_flat(self, et_id, headers):
        return self._request("GET", f"/early-terminations/{et_id}", headers=headers)

    def list_early_terminations_flat(self, headers, params=None):
        return self._request("GET", "/early-terminations", headers=headers, params=params)


api_client = ApiClient()
