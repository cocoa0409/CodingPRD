"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Participants (PRD §3.1) ───────────────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def terminate_participant(self, participant_id, headers, payload=None):
        return self._request(
            "POST",
            f"/participants/{participant_id}/terminate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Plans (PRD §3.1) ──────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    # ─── Offering periods (PRD §3.2, §3.7) ─────────────────────────
    def create_offering_period(self, payload, headers):
        return self._request("POST", "/offering-periods", payload, headers)

    def get_offering_period(self, offering_id, headers):
        return self._request("GET", f"/offering-periods/{offering_id}", headers=headers)

    def list_offering_periods(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/offering-periods", headers=headers, params=params
        )

    def close_enrollment(self, offering_id, headers, payload=None):
        return self._request(
            "POST",
            f"/offering-periods/{offering_id}/close-enrollment",
            payload if payload is not None else {},
            headers,
        )

    def cancel_offering(self, offering_id, headers, payload=None):
        return self._request(
            "POST",
            f"/offering-periods/{offering_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Purchase periods (PRD §3.2, §3.4, §3.5) ───────────────────
    def create_purchase_period(self, offering_id, payload, headers):
        return self._request(
            "POST", f"/offering-periods/{offering_id}/purchase-periods", payload, headers
        )

    def get_purchase_period(self, pp_id, headers):
        return self._request("GET", f"/purchase-periods/{pp_id}", headers=headers)

    def list_purchase_periods(self, offering_id, headers, params=None):
        return self._request(
            "GET",
            f"/offering-periods/{offering_id}/purchase-periods",
            headers=headers,
            params=params,
        )

    def open_purchase_period(self, pp_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-periods/{pp_id}/open",
            payload if payload is not None else {},
            headers,
        )

    def certify_purchase_period(self, pp_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-periods/{pp_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    def run_purchase(self, pp_id, payload, headers):
        return self._request(
            "POST", f"/purchase-periods/{pp_id}/run-purchase", payload, headers
        )

    def cancel_purchase_period(self, pp_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-periods/{pp_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Enrollments (PRD §3.3) ────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def suspend_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/suspend",
            payload if payload is not None else {},
            headers,
        )

    def resume_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/resume",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── Contributions (PRD §3.3) ──────────────────────────────────
    def create_contribution(self, payload, headers):
        return self._request("POST", "/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/contributions", headers=headers, params=params)

    # ─── Purchases (PRD §3.5) ──────────────────────────────────────
    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/purchases/{purchase_id}", headers=headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/purchases", headers=headers, params=params)

    # ─── Form 3922 (PRD §3.5) ──────────────────────────────────────
    def issue_form_3922(self, purchase_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchases/{purchase_id}/form-3922",
            payload if payload is not None else {},
            headers,
        )

    def list_forms_for_purchase(self, purchase_id, headers, params=None):
        return self._request(
            "GET", f"/purchases/{purchase_id}/form-3922", headers=headers, params=params
        )

    def get_form_3922(self, form_id, headers):
        return self._request("GET", f"/form-3922/{form_id}", headers=headers)

    def list_forms(self, headers, params=None):
        return self._request("GET", "/form-3922", headers=headers, params=params)

    # ─── Share lots (PRD §3.5, §3.8) ───────────────────────────────
    def get_share_lot(self, lot_id, headers):
        return self._request("GET", f"/share-lots/{lot_id}", headers=headers)

    def list_share_lots(self, headers, params=None):
        return self._request("GET", "/share-lots", headers=headers, params=params)

    # ─── Dispositions (PRD §3.8) ───────────────────────────────────
    def create_disposition(self, payload, headers):
        return self._request("POST", "/dispositions", payload, headers)

    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/dispositions", headers=headers, params=params)

    # ─── Accrual ledgers (PRD §3.6) ────────────────────────────────
    def get_accrual_ledger(self, ledger_id, headers):
        return self._request("GET", f"/accrual-ledgers/{ledger_id}", headers=headers)

    def list_accrual_ledgers(self, headers, params=None):
        return self._request("GET", "/accrual-ledgers", headers=headers, params=params)


api_client = ApiClient()
