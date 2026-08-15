"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Venues
    # ------------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def advance_season(self, venue_id, headers):
        return self._request("POST", f"/venues/{venue_id}/advance-season", {}, headers)

    # ------------------------------------------------------------------
    # Sponsors
    # ------------------------------------------------------------------
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    def transition_sponsor(self, sponsor_id, payload, headers):
        return self._request("POST", f"/sponsors/{sponsor_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def transition_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Rights windows
    # ------------------------------------------------------------------
    def create_rights_window(self, payload, headers):
        return self._request("POST", "/rights-windows", payload, headers)

    def get_rights_window(self, window_id, headers):
        return self._request("GET", f"/rights-windows/{window_id}", headers=headers)

    def list_rights_windows(self, headers, params=None):
        return self._request("GET", "/rights-windows", headers=headers, params=params)

    def transition_rights_window(self, window_id, payload, headers):
        return self._request("POST", f"/rights-windows/{window_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def patch_contract(self, contract_id, payload, headers):
        return self._request("PATCH", f"/contracts/{contract_id}", payload, headers)

    def transition_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/transition",
                             payload, headers)

    def countersign_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/countersign",
                             payload, headers)

    # ------------------------------------------------------------------
    # Exclusivity grants
    # ------------------------------------------------------------------
    def create_grant(self, payload, headers):
        return self._request("POST", "/exclusivity-grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/exclusivity-grants/{grant_id}", headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/exclusivity-grants", headers=headers, params=params)

    def transition_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/exclusivity-grants/{grant_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Deliverables
    # ------------------------------------------------------------------
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/deliverables", payload, headers)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/deliverables", headers=headers, params=params)

    def transition_deliverable(self, deliverable_id, payload, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Evidence submissions
    # ------------------------------------------------------------------
    def create_evidence(self, payload, headers):
        return self._request("POST", "/evidence-submissions", payload, headers)

    def get_evidence(self, submission_id, headers):
        return self._request("GET", f"/evidence-submissions/{submission_id}",
                             headers=headers)

    def list_evidence(self, headers, params=None):
        return self._request("GET", "/evidence-submissions", headers=headers,
                             params=params)

    def transition_evidence(self, submission_id, payload, headers):
        return self._request("POST",
                             f"/evidence-submissions/{submission_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Make-good credits
    # ------------------------------------------------------------------
    def create_credit(self, payload, headers):
        return self._request("POST", "/make-good-credits", payload, headers)

    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/make-good-credits/{credit_id}", headers=headers)

    def list_credits(self, headers, params=None):
        return self._request("GET", "/make-good-credits", headers=headers,
                             params=params)

    def transition_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/make-good-credits/{credit_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Invoices and payments
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/transition",
                             payload, headers)

    def post_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments",
                             payload, headers)

    def void_payment(self, invoice_id, payment_id, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/payments/{payment_id}/void",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Valuation reports
    # ------------------------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/valuation-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/valuation-reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/valuation-reports", headers=headers,
                             params=params)

    def transition_report(self, report_id, payload, headers):
        return self._request("POST", f"/valuation-reports/{report_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Renewal opportunities
    # ------------------------------------------------------------------
    def create_opportunity(self, payload, headers):
        return self._request("POST", "/renewal-opportunities", payload, headers)

    def get_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/renewal-opportunities/{opportunity_id}",
                             headers=headers)

    def list_opportunities(self, headers, params=None):
        return self._request("GET", "/renewal-opportunities", headers=headers,
                             params=params)

    def transition_opportunity(self, opportunity_id, payload, headers):
        return self._request("POST",
                             f"/renewal-opportunities/{opportunity_id}/transition",
                             payload, headers)

    def counter_opportunity(self, opportunity_id, payload, headers):
        return self._request("POST",
                             f"/renewal-opportunities/{opportunity_id}/counter",
                             payload, headers)


api_client = ApiClient()
