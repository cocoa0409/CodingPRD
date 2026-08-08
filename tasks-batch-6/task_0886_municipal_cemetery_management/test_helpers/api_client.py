"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cemetery-mgmt"


class ApiClient(GenericApiClient):
    # --- Cemetery ---------------------------------------------------------
    def create_cemetery(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cemeteries", payload, headers)

    def get_cemetery(self, cemetery_id, headers):
        return self._request("GET", f"{PREFIX}/cemeteries/{cemetery_id}", headers=headers)

    # --- Plot -------------------------------------------------------------
    def create_plot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plots", payload, headers)

    def get_plot(self, plot_id, headers):
        return self._request("GET", f"{PREFIX}/plots/{plot_id}", headers=headers)

    def list_plots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/plots", headers=headers, params=params)

    def retire_plot(self, plot_id, headers):
        return self._request("POST", f"{PREFIX}/plots/{plot_id}/retire", {}, headers)

    # --- RightHolder ------------------------------------------------------
    def create_holder(self, payload, headers):
        return self._request("POST", f"{PREFIX}/holders", payload, headers)

    def get_holder(self, holder_id, headers):
        return self._request("GET", f"{PREFIX}/holders/{holder_id}", headers=headers)

    # --- Decedent / genealogy --------------------------------------------
    def create_decedent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/decedents", payload, headers)

    def get_decedent(self, decedent_id, headers):
        return self._request("GET", f"{PREFIX}/decedents/{decedent_id}", headers=headers)

    def list_decedents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/decedents", headers=headers, params=params)

    # --- Deed -------------------------------------------------------------
    def create_deed(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deeds", payload, headers)

    def get_deed(self, deed_id, headers):
        return self._request("GET", f"{PREFIX}/deeds/{deed_id}", headers=headers)

    def list_deeds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deeds", headers=headers, params=params)

    def transfer_deed(self, deed_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deeds/{deed_id}/transfer", payload, headers)

    def accept_transfer(self, deed_id, headers):
        return self._request("POST", f"{PREFIX}/deeds/{deed_id}/accept-transfer", {}, headers)

    def surrender_deed(self, deed_id, headers):
        return self._request("POST", f"{PREFIX}/deeds/{deed_id}/surrender", {}, headers)

    # --- Interment --------------------------------------------------------
    def create_interment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interments", payload, headers)

    def get_interment(self, interment_id, headers):
        return self._request("GET", f"{PREFIX}/interments/{interment_id}", headers=headers)

    def list_interments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/interments", headers=headers, params=params)

    def open_interment(self, interment_id, headers):
        return self._request("POST", f"{PREFIX}/interments/{interment_id}/open", {}, headers)

    def complete_interment(self, interment_id, headers):
        return self._request("POST", f"{PREFIX}/interments/{interment_id}/complete", {}, headers)

    def cancel_interment(self, interment_id, headers):
        return self._request("POST", f"{PREFIX}/interments/{interment_id}/cancel", {}, headers)

    # --- DisintermentAuthorization ---------------------------------------
    def create_disinterment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disinterment-authorizations", payload, headers)

    def get_disinterment(self, auth_id, headers):
        return self._request("GET", f"{PREFIX}/disinterment-authorizations/{auth_id}", headers=headers)

    def list_disinterments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disinterment-authorizations", headers=headers, params=params)

    def record_clearance(self, auth_id, headers):
        return self._request("POST", f"{PREFIX}/disinterment-authorizations/{auth_id}/record-clearance", {}, headers)

    def record_consent(self, auth_id, headers):
        return self._request("POST", f"{PREFIX}/disinterment-authorizations/{auth_id}/record-consent", {}, headers)

    def approve_disinterment(self, auth_id, headers):
        return self._request("POST", f"{PREFIX}/disinterment-authorizations/{auth_id}/approve", {}, headers)

    def deny_disinterment(self, auth_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/disinterment-authorizations/{auth_id}/deny", payload or {}, headers)

    def execute_disinterment(self, auth_id, headers):
        return self._request("POST", f"{PREFIX}/disinterment-authorizations/{auth_id}/execute", {}, headers)

    # --- MarkerPermit -----------------------------------------------------
    def create_marker_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/marker-permits", payload, headers)

    def get_marker_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/marker-permits/{permit_id}", headers=headers)

    def list_marker_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/marker-permits", headers=headers, params=params)

    def approve_marker_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/marker-permits/{permit_id}/approve", {}, headers)

    def install_marker_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/marker-permits/{permit_id}/install", {}, headers)

    def reject_marker_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/marker-permits/{permit_id}/reject", payload or {}, headers)

    # --- Invoice ----------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/void", {}, headers)

    # --- Payment ----------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payments", headers=headers, params=params)

    # --- CareFundEntry ----------------------------------------------------
    def create_care_fund_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/care-fund-entries", payload, headers)

    def get_care_fund_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/care-fund-entries/{entry_id}", headers=headers)

    def list_care_fund_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/care-fund-entries", headers=headers, params=params)

    # --- Logical clock (test-driving) ------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
