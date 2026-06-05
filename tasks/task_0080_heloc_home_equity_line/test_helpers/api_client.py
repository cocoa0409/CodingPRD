"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Borrower ----
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def update_borrower(self, borrower_id, payload, headers):
        return self._request("PATCH", f"/borrowers/{borrower_id}", payload, headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def update_property(self, property_id, payload, headers):
        return self._request("PATCH", f"/properties/{property_id}", payload, headers)

    def list_property_lien_records(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/lien-records", headers=headers, params=params)

    # ---- IndexRate ----
    def create_index_rate(self, payload, headers):
        return self._request("POST", "/index-rates", payload, headers)

    def get_index_rate(self, index_rate_id, headers):
        return self._request("GET", f"/index-rates/{index_rate_id}", headers=headers)

    def list_index_rates(self, headers, params=None):
        return self._request("GET", "/index-rates", headers=headers, params=params)

    def supersede_index_rate(self, index_rate_id, payload, headers):
        return self._request("POST", f"/index-rates/{index_rate_id}/supersede", payload, headers)

    # ---- Heloc ----
    def create_heloc(self, payload, headers):
        return self._request("POST", "/helocs", payload, headers)

    def get_heloc(self, heloc_id, headers):
        return self._request("GET", f"/helocs/{heloc_id}", headers=headers)

    def list_helocs(self, headers, params=None):
        return self._request("GET", "/helocs", headers=headers, params=params)

    def activate_heloc(self, heloc_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/activate", {}, headers)

    def convert_to_repayment(self, heloc_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/convert-to-repayment", {}, headers)

    def freeze_heloc(self, heloc_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/freeze", {}, headers)

    def unfreeze_heloc(self, heloc_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/unfreeze", {}, headers)

    def declare_default(self, heloc_id, payload, headers):
        return self._request("POST", f"/helocs/{heloc_id}/declare-default", payload, headers)

    def close_heloc(self, heloc_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/close", {}, headers)

    def get_payoff_quote(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/payoff-quote", headers=headers, params=params)

    def get_interest_quote(self, heloc_id, headers):
        return self._request("GET", f"/helocs/{heloc_id}/interest-quote", headers=headers)

    # ---- Draw ----
    def create_draw(self, heloc_id, payload, headers):
        return self._request("POST", f"/helocs/{heloc_id}/draws", payload, headers)

    def list_draws(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/draws", headers=headers, params=params)

    def reverse_draw(self, heloc_id, draw_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/draws/{draw_id}/reverse", {}, headers)

    # ---- Payment ----
    def create_payment(self, heloc_id, payload, headers):
        return self._request("POST", f"/helocs/{heloc_id}/payments", payload, headers)

    def list_payments(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/payments", headers=headers, params=params)

    # ---- Covenant ----
    def create_covenant(self, heloc_id, payload, headers):
        return self._request("POST", f"/helocs/{heloc_id}/covenants", payload, headers)

    def list_covenants(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/covenants", headers=headers, params=params)

    def get_covenant(self, covenant_id, headers):
        return self._request("GET", f"/covenants/{covenant_id}", headers=headers)

    def evaluate_covenant(self, heloc_id, covenant_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/covenants/{covenant_id}/evaluate", {}, headers)

    def cure_covenant(self, heloc_id, covenant_id, headers):
        return self._request("POST", f"/helocs/{heloc_id}/covenants/{covenant_id}/cure", {}, headers)

    # ---- DefaultEvent / FeeAssessment / LienRecord reverse-reachability ----
    def list_default_events(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/default-events", headers=headers, params=params)

    def list_fee_assessments(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/fee-assessments", headers=headers, params=params)

    def list_heloc_lien_records(self, heloc_id, headers, params=None):
        return self._request("GET", f"/helocs/{heloc_id}/lien-records", headers=headers, params=params)

    def list_covenant_default_events(self, covenant_id, headers, params=None):
        return self._request("GET", f"/covenants/{covenant_id}/default-events", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock(self, heloc_id, payload, headers):
        return self._request("POST", f"/helocs/{heloc_id}/advance-clock", payload, headers)


api_client = ApiClient()
