"""One method per endpoint of the QDRO Processing API.

Every method returns the raw ``requests.Response`` so tests can assert status
codes as well as bodies. List methods take a ``params`` dict for the filters and
the two pagination inputs.
"""

from prd_bench_local_runner.testing import GenericApiClient


class QdroApiClient(GenericApiClient):
    """HTTP client covering the API's endpoints."""

    # ─── Plans ────────────────────────────────────────────────────────────

    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", None, headers)

    def set_procedure_status(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/plans/{plan_id}/procedure-status", payload, headers
        )

    def list_plan_participants(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/participants", params, headers
        )

    # ─── Participants ─────────────────────────────────────────────────────

    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", None, headers)

    def open_plan_account(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/plan-accounts", payload, headers
        )

    def list_participant_plan_accounts(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/plan-accounts", params, headers
        )

    def list_participant_qdro_cases(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/qdro-cases", params, headers
        )

    # ─── Plan accounts ────────────────────────────────────────────────────

    def get_plan_account(self, plan_account_id, headers):
        return self._request(
            "GET", f"/plan-accounts/{plan_account_id}", None, headers
        )

    def create_money_source(self, plan_account_id, payload, headers):
        return self._request(
            "POST", f"/plan-accounts/{plan_account_id}/money-sources", payload, headers
        )

    def list_money_sources(self, plan_account_id, headers, params=None):
        return self._request(
            "GET", f"/plan-accounts/{plan_account_id}/money-sources", params, headers
        )

    def create_valuation_snapshot(self, plan_account_id, payload, headers):
        return self._request(
            "POST",
            f"/plan-accounts/{plan_account_id}/valuation-snapshots",
            payload,
            headers,
        )

    def list_valuation_snapshots(self, plan_account_id, headers, params=None):
        return self._request(
            "GET",
            f"/plan-accounts/{plan_account_id}/valuation-snapshots",
            params,
            headers,
        )

    # ─── QDRO cases ───────────────────────────────────────────────────────

    def create_qdro_case(self, payload, headers):
        return self._request("POST", "/qdro-cases", payload, headers)

    def get_qdro_case(self, case_id, headers):
        return self._request("GET", f"/qdro-cases/{case_id}", None, headers)

    def get_benefit_projection(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/qdro-cases/{case_id}/benefit-projection", params, headers
        )

    def create_attorney_authorization(self, case_id, payload, headers):
        return self._request(
            "POST", f"/qdro-cases/{case_id}/attorney-authorizations", payload, headers
        )

    def list_attorney_authorizations(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/qdro-cases/{case_id}/attorney-authorizations", params, headers
        )

    def revoke_attorney_authorization(self, authorization_id, headers, payload=None):
        return self._request(
            "POST",
            f"/attorney-authorizations/{authorization_id}/revoke",
            payload if payload is not None else {},
            headers,
        )

    def create_communication(self, case_id, payload, headers):
        return self._request(
            "POST", f"/qdro-cases/{case_id}/communications", payload, headers
        )

    def list_communications(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/qdro-cases/{case_id}/communications", params, headers
        )

    def list_alternate_payee_accounts(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/qdro-cases/{case_id}/alternate-payee-accounts", params, headers
        )

    # ─── Draft orders ─────────────────────────────────────────────────────

    def create_draft_order(self, payload, headers):
        return self._request("POST", "/draft-orders", payload, headers)

    def get_draft_order(self, draft_order_id, headers):
        return self._request("GET", f"/draft-orders/{draft_order_id}", None, headers)

    def list_draft_orders(self, headers, params=None):
        return self._request("GET", "/draft-orders", params, headers)

    def create_deficiency_notice(self, draft_order_id, payload, headers):
        return self._request(
            "POST",
            f"/draft-orders/{draft_order_id}/deficiency-notices",
            payload if payload is not None else {},
            headers,
        )

    def list_deficiency_notices(self, draft_order_id, headers, params=None):
        return self._request(
            "GET", f"/draft-orders/{draft_order_id}/deficiency-notices", params, headers
        )

    def resubmit_draft_order(self, draft_order_id, payload, headers):
        return self._request(
            "POST", f"/draft-orders/{draft_order_id}/resubmit", payload, headers
        )

    def qualify_draft_order(self, draft_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/draft-orders/{draft_order_id}/qualify",
            payload if payload is not None else {},
            headers,
        )

    def deny_draft_order(self, draft_order_id, payload, headers):
        return self._request(
            "POST", f"/draft-orders/{draft_order_id}/deny", payload, headers
        )

    # ─── Segregation holds ────────────────────────────────────────────────

    def get_segregation_hold(self, hold_id, headers):
        return self._request("GET", f"/segregation-holds/{hold_id}", None, headers)

    def list_segregation_holds(self, headers, params=None):
        return self._request("GET", "/segregation-holds", params, headers)

    def release_segregation_hold(self, hold_id, headers, payload=None):
        return self._request(
            "POST",
            f"/segregation-holds/{hold_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # ─── Alternate payee accounts and distributions ───────────────────────

    def get_alternate_payee_account(self, ap_account_id, headers):
        return self._request(
            "GET", f"/alternate-payee-accounts/{ap_account_id}", None, headers
        )

    def create_distribution(self, ap_account_id, payload, headers):
        return self._request(
            "POST",
            f"/alternate-payee-accounts/{ap_account_id}/distributions",
            payload,
            headers,
        )

    def list_distributions(self, ap_account_id, headers, params=None):
        return self._request(
            "GET",
            f"/alternate-payee-accounts/{ap_account_id}/distributions",
            params,
            headers,
        )

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/distributions/{distribution_id}", None, headers
        )

    def void_distribution(self, distribution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distributions/{distribution_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ─── Tax reports ──────────────────────────────────────────────────────

    def get_tax_report(self, tax_report_id, headers):
        return self._request("GET", f"/tax-reports/{tax_report_id}", None, headers)

    def list_tax_reports(self, headers, params=None):
        return self._request("GET", "/tax-reports", params, headers)

    # ─── Test-driving capabilities ────────────────────────────────────────

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_segregation_sweep(self, headers, payload=None):
        return self._request(
            "POST",
            "/_ops/run-segregation-sweep",
            payload if payload is not None else {},
            headers,
        )
