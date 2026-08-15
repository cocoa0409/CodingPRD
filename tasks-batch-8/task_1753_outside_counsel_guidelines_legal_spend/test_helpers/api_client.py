"""API client: one method per endpoint defined in the PRD (all under /legal-departments)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- LegalDepartment (PRD §3.1, §4) ---
    def create_legal_department(self, payload, headers):
        return self._request("POST", "/legal-departments", payload, headers)

    def get_legal_department(self, dept_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}", headers=headers)

    def list_legal_departments(self, headers, params=None):
        return self._request("GET", "/legal-departments", headers=headers, params=params)

    # --- PanelFirm (PRD §3.1, §4) ---
    def create_panel_firm(self, dept_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms", payload, headers)

    def get_panel_firm(self, dept_id, firm_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}", headers=headers)

    def list_panel_firms(self, dept_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms", headers=headers, params=params)

    def suspend_panel_firm(self, dept_id, firm_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/suspend", {}, headers)

    def reinstate_panel_firm(self, dept_id, firm_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/reinstate", {}, headers)

    def offboard_panel_firm(self, dept_id, firm_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/offboard", {}, headers)

    # --- GuidelineVersion (PRD §3.2, §4) ---
    def create_guideline_version(self, dept_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/guideline-versions", payload, headers)

    def get_guideline_version(self, dept_id, gv_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/guideline-versions/{gv_id}", headers=headers)

    def list_guideline_versions(self, dept_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/guideline-versions", headers=headers, params=params)

    def publish_guideline_version(self, dept_id, gv_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/guideline-versions/{gv_id}/publish", {}, headers)

    # --- GuidelineAcknowledgment (PRD §3.2, §4) ---
    def get_acknowledgment(self, dept_id, firm_id, ack_id, headers):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/panel-firms/{firm_id}/acknowledgments/{ack_id}",
            headers=headers,
        )

    def list_acknowledgments(self, dept_id, firm_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/panel-firms/{firm_id}/acknowledgments",
            headers=headers,
            params=params,
        )

    def acknowledge_guideline(self, dept_id, firm_id, ack_id, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/panel-firms/{firm_id}/acknowledgments/{ack_id}/acknowledge",
            {},
            headers,
        )

    # --- Matter (PRD §3.3, §4) ---
    def create_matter(self, dept_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters", payload, headers)

    def get_matter(self, dept_id, matter_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/matters/{matter_id}", headers=headers)

    def list_matters(self, dept_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/matters", headers=headers, params=params)

    def engage_matter(self, dept_id, matter_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/engage", {}, headers)

    def close_matter(self, dept_id, matter_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/close", {}, headers)

    def reopen_matter(self, dept_id, matter_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/reopen", {}, headers)

    def get_staffing_ratio(self, dept_id, matter_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/matters/{matter_id}/staffing-ratio",
            headers=headers,
            params=params,
        )

    # --- RateCard (PRD §3.4, §4) ---
    def create_rate_card(self, dept_id, firm_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards", payload, headers)

    def get_rate_card(self, dept_id, firm_id, card_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}", headers=headers)

    def list_rate_cards(self, dept_id, firm_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards", headers=headers, params=params)

    def submit_rate_card(self, dept_id, firm_id, card_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/submit", {}, headers)

    def approve_rate_card(self, dept_id, firm_id, card_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/approve", {}, headers)

    def reject_rate_card(self, dept_id, firm_id, card_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/reject", {}, headers)

    def revise_rate_card(self, dept_id, firm_id, card_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/revise", {}, headers)

    # --- Timekeeper (PRD §3.4, §4) ---
    def create_timekeeper(self, dept_id, firm_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/timekeepers", payload, headers)

    def get_timekeeper(self, dept_id, firm_id, tk_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/timekeepers/{tk_id}", headers=headers)

    def list_timekeepers(self, dept_id, firm_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/timekeepers", headers=headers, params=params)

    def qualify_timekeeper(self, dept_id, firm_id, tk_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/timekeepers/{tk_id}/qualify", {}, headers)

    def disqualify_timekeeper(self, dept_id, firm_id, tk_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/timekeepers/{tk_id}/disqualify", {}, headers)

    # --- TimekeeperRate (PRD §3.4, §4) ---
    def add_rate_row(self, dept_id, firm_id, card_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/rates",
            payload,
            headers,
        )

    def list_rate_rows(self, dept_id, firm_id, card_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/rates",
            headers=headers,
            params=params,
        )

    def get_rate_row(self, dept_id, firm_id, card_id, rate_id, headers):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/panel-firms/{firm_id}/rate-cards/{card_id}/rates/{rate_id}",
            headers=headers,
        )

    # --- Invoice (PRD §3.5, §3.6, §4) ---
    def create_invoice(self, dept_id, matter_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/invoices", payload, headers)

    def get_invoice(self, dept_id, matter_id, invoice_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, dept_id, matter_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/matters/{matter_id}/invoices", headers=headers, params=params)

    def pay_invoice(self, dept_id, matter_id, invoice_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, dept_id, matter_id, invoice_id, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/void", {}, headers)

    # --- InvoiceLineItem (PRD §3.5, §3.6, §4) ---
    def get_line_item(self, dept_id, matter_id, invoice_id, line_id, headers):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}",
            headers=headers,
        )

    def list_line_items(self, dept_id, matter_id, invoice_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items",
            headers=headers,
            params=params,
        )

    def approve_line_item(self, dept_id, matter_id, invoice_id, line_id, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/approve",
            {},
            headers,
        )

    def adjust_line_item(self, dept_id, matter_id, invoice_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/adjust",
            payload,
            headers,
        )

    def reject_line_item(self, dept_id, matter_id, invoice_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/reject",
            payload,
            headers,
        )

    # --- Appeal (PRD §3.6, §4) ---
    def create_appeal(self, dept_id, matter_id, invoice_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/appeals",
            payload,
            headers,
        )

    def get_appeal(self, dept_id, matter_id, invoice_id, line_id, appeal_id, headers):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/appeals/{appeal_id}",
            headers=headers,
        )

    def list_appeals(self, dept_id, matter_id, invoice_id, line_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/appeals",
            headers=headers,
            params=params,
        )

    def claim_appeal(self, dept_id, matter_id, invoice_id, line_id, appeal_id, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/appeals/{appeal_id}/claim",
            {},
            headers,
        )

    def grant_appeal(self, dept_id, matter_id, invoice_id, line_id, appeal_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/appeals/{appeal_id}/grant",
            payload,
            headers,
        )

    def deny_appeal(self, dept_id, matter_id, invoice_id, line_id, appeal_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-departments/{dept_id}/matters/{matter_id}/invoices/{invoice_id}/line-items/{line_id}/appeals/{appeal_id}/deny",
            payload,
            headers,
        )

    # --- Accrual (PRD §3.7, §4) ---
    def create_accrual(self, dept_id, matter_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/matters/{matter_id}/accruals", payload, headers)

    def get_accrual(self, dept_id, matter_id, accrual_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/matters/{matter_id}/accruals/{accrual_id}", headers=headers)

    def list_accruals(self, dept_id, matter_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/matters/{matter_id}/accruals", headers=headers, params=params)

    # --- MatterForecast (PRD §3.7, §4) ---
    def put_forecast(self, dept_id, matter_id, payload, headers):
        return self._request("PUT", f"/legal-departments/{dept_id}/matters/{matter_id}/forecast", payload, headers)

    def get_forecast(self, dept_id, matter_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/matters/{matter_id}/forecast", headers=headers)

    # --- ScorecardSnapshot (PRD §3.7, §4) ---
    def recompute_scorecard(self, dept_id, firm_id, payload, headers):
        return self._request("POST", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/scorecards/recompute", payload, headers)

    def get_scorecard(self, dept_id, firm_id, snapshot_id, headers):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/scorecards/{snapshot_id}", headers=headers)

    def list_scorecards(self, dept_id, firm_id, headers, params=None):
        return self._request("GET", f"/legal-departments/{dept_id}/panel-firms/{firm_id}/scorecards", headers=headers, params=params)

    # --- Logical clock (PRD §2.5, §4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
