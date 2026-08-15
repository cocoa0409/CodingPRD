"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Portfolios
    # ------------------------------------------------------------------
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/portfolios", payload, headers)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}", headers=headers)

    def list_portfolios(self, headers, params=None):
        return self._request("GET", "/portfolios", headers=headers, params=params)

    def get_portfolio_ladder(self, portfolio_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}/ladder", headers=headers)

    def get_negotiations_compliance(self, portfolio_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}/negotiations/compliance",
                             headers=headers)

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------
    def create_contact(self, portfolio_id, payload, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/contacts",
                             payload, headers)

    def list_contacts(self, portfolio_id, headers, params=None):
        return self._request("GET", f"/portfolios/{portfolio_id}/contacts",
                             headers=headers, params=params)

    def get_contact(self, portfolio_id, contact_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}/contacts/{contact_id}",
                             headers=headers)

    def patch_contact(self, portfolio_id, contact_id, payload, headers):
        return self._request("PATCH", f"/portfolios/{portfolio_id}/contacts/{contact_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------
    def create_lease(self, portfolio_id, payload, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/leases",
                             payload, headers)

    def get_lease(self, portfolio_id, lease_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}/leases/{lease_id}",
                             headers=headers)

    def list_leases(self, portfolio_id, headers, params=None):
        return self._request("GET", f"/portfolios/{portfolio_id}/leases",
                             headers=headers, params=params)

    def activate_lease(self, portfolio_id, lease_id, payload, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/leases/{lease_id}/activate",
                             payload, headers)

    def vacate_lease(self, portfolio_id, lease_id, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/leases/{lease_id}/vacate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------
    def create_option(self, portfolio_id, lease_id, payload, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/leases/{lease_id}/options",
                             payload, headers)

    def get_option(self, portfolio_id, lease_id, option_id, headers):
        return self._request("GET",
                             f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}",
                             headers=headers)

    def list_options(self, portfolio_id, lease_id, headers, params=None):
        return self._request("GET", f"/portfolios/{portfolio_id}/leases/{lease_id}/options",
                             headers=headers, params=params)

    def withdraw_option(self, portfolio_id, lease_id, option_id, payload, headers):
        return self._request("POST",
                             f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/withdraw",
                             payload, headers)

    # ------------------------------------------------------------------
    # Exercise notices
    # ------------------------------------------------------------------
    def create_notice(self, portfolio_id, lease_id, option_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/notices",
            payload, headers)

    def list_notices(self, portfolio_id, lease_id, option_id, headers, params=None):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/notices",
            headers=headers, params=params)

    def get_notice(self, portfolio_id, lease_id, option_id, notice_id, headers):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/notices/{notice_id}",
            headers=headers)

    def deliver_notice(self, portfolio_id, lease_id, option_id, notice_id, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/notices/{notice_id}/deliver",
            {}, headers)

    def reject_notice(self, portfolio_id, lease_id, option_id, notice_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/notices/{notice_id}/reject",
            payload, headers)

    def acknowledge_notice(self, portfolio_id, lease_id, option_id, notice_id, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/notices/{notice_id}/acknowledge",
            {}, headers)

    # ------------------------------------------------------------------
    # Market-rate assessments
    # ------------------------------------------------------------------
    def create_assessment(self, portfolio_id, lease_id, option_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/assessments",
            payload, headers)

    def list_assessments(self, portfolio_id, lease_id, option_id, headers, params=None):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/assessments",
            headers=headers, params=params)

    def get_assessment(self, portfolio_id, lease_id, option_id, assessment_id, headers):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/assessments/{assessment_id}",
            headers=headers)

    def dispute_assessment(self, portfolio_id, lease_id, option_id, assessment_id,
                           payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/assessments/{assessment_id}/dispute",
            payload, headers)

    def get_arbitration(self, portfolio_id, lease_id, option_id, assessment_id, headers):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/assessments/{assessment_id}/arbitration",
            headers=headers)

    def decide_arbitration(self, portfolio_id, lease_id, option_id, assessment_id,
                           payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/assessments/{assessment_id}/arbitration/decide",
            payload, headers)

    # ------------------------------------------------------------------
    # Amendments
    # ------------------------------------------------------------------
    def create_amendment(self, portfolio_id, lease_id, payload, headers):
        return self._request("POST",
                             f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments",
                             payload, headers)

    def list_amendments(self, portfolio_id, lease_id, headers, params=None):
        return self._request("GET",
                             f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments",
                             headers=headers, params=params)

    def get_amendment(self, portfolio_id, lease_id, amendment_id, headers):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}",
            headers=headers)

    def propose_amendment(self, portfolio_id, lease_id, amendment_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}/propose",
            payload, headers)

    def counter_amendment(self, portfolio_id, lease_id, amendment_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}/counter",
            payload, headers)

    def repropose_amendment(self, portfolio_id, lease_id, amendment_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}/repropose",
            payload, headers)

    def agree_amendment(self, portfolio_id, lease_id, amendment_id, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}/agree",
            {}, headers)

    def execute_amendment(self, portfolio_id, lease_id, amendment_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}/execute",
            payload, headers)

    def abandon_amendment(self, portfolio_id, lease_id, amendment_id, headers):
        return self._request(
            "POST",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/amendments/{amendment_id}/abandon",
            {}, headers)

    # ------------------------------------------------------------------
    # Ledger and reminders (nested)
    # ------------------------------------------------------------------
    def list_ledger(self, portfolio_id, lease_id, headers, params=None):
        return self._request("GET", f"/portfolios/{portfolio_id}/leases/{lease_id}/ledger",
                             headers=headers, params=params)

    def list_reminders(self, portfolio_id, lease_id, option_id, headers, params=None):
        return self._request(
            "GET",
            f"/portfolios/{portfolio_id}/leases/{lease_id}/options/{option_id}/reminders",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Flat read aliases
    # ------------------------------------------------------------------
    def get_lease_flat(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases_flat(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_option_flat(self, option_id, headers):
        return self._request("GET", f"/options/{option_id}", headers=headers)

    def get_assessment_flat(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def get_contact_flat(self, contact_id, headers):
        return self._request("GET", f"/contacts/{contact_id}", headers=headers)

    def get_amendment_flat(self, amendment_id, headers):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def list_amendments_flat(self, headers, params=None):
        return self._request("GET", "/amendments", headers=headers, params=params)

    def list_lease_options_flat(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/options",
                             headers=headers, params=params)

    def list_lease_amendments_flat(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/amendments",
                             headers=headers, params=params)

    def list_lease_ledger_flat(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/ledger",
                             headers=headers, params=params)

    def list_option_assessments_flat(self, option_id, headers, params=None):
        return self._request("GET", f"/options/{option_id}/assessments",
                             headers=headers, params=params)

    def list_option_notices_flat(self, option_id, headers, params=None):
        return self._request("GET", f"/options/{option_id}/notices",
                             headers=headers, params=params)

    def list_option_reminders_flat(self, option_id, headers, params=None):
        return self._request("GET", f"/options/{option_id}/reminders",
                             headers=headers, params=params)

    def list_option_ledger_flat(self, option_id, headers, params=None):
        return self._request("GET", f"/options/{option_id}/ledger",
                             headers=headers, params=params)

    def list_assessment_arbitration_flat(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}/arbitration",
                             headers=headers)

    def list_assessment_ledger_flat(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/ledger",
                             headers=headers, params=params)

    def list_contact_reminders_flat(self, contact_id, headers, params=None):
        return self._request("GET", f"/contacts/{contact_id}/reminders",
                             headers=headers, params=params)


api_client = ApiClient()
