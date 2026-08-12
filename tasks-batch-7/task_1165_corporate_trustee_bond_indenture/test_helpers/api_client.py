"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- system ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Indenture ---
    def create_indenture(self, payload, headers):
        return self._request("POST", "/indentures", payload, headers)

    def list_indentures(self, headers, params=None):
        return self._request("GET", "/indentures", headers=headers, params=params)

    def get_indenture(self, indenture_id, headers):
        return self._request("GET", f"/indentures/{indenture_id}", headers=headers)

    def activate_indenture(self, indenture_id, headers):
        return self._request("POST", f"/indentures/{indenture_id}/activate", {}, headers)

    # --- Tranche ---
    def create_tranche(self, payload, headers):
        return self._request("POST", "/tranches", payload, headers)

    def list_tranches(self, headers, params=None):
        return self._request("GET", "/tranches", headers=headers, params=params)

    def get_tranche(self, tranche_id, headers):
        return self._request("GET", f"/tranches/{tranche_id}", headers=headers)

    # --- NoteholderAccount ---
    def create_noteholder_account(self, payload, headers):
        return self._request("POST", "/noteholder-accounts", payload, headers)

    def list_noteholder_accounts(self, headers, params=None):
        return self._request("GET", "/noteholder-accounts", headers=headers, params=params)

    def get_noteholder_account(self, account_id, headers):
        return self._request("GET", f"/noteholder-accounts/{account_id}", headers=headers)

    # --- Position ---
    def create_position(self, payload, headers):
        return self._request("POST", "/positions", payload, headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    # --- CovenantObligation ---
    def create_covenant_obligation(self, payload, headers):
        return self._request("POST", "/covenant-obligations", payload, headers)

    def list_covenant_obligations(self, headers, params=None):
        return self._request("GET", "/covenant-obligations", headers=headers, params=params)

    def get_covenant_obligation(self, obligation_id, headers):
        return self._request("GET", f"/covenant-obligations/{obligation_id}", headers=headers)

    # --- CovenantCertificate ---
    def create_covenant_certificate(self, payload, headers):
        return self._request("POST", "/covenant-certificates", payload, headers)

    def list_covenant_certificates(self, headers, params=None):
        return self._request("GET", "/covenant-certificates", headers=headers, params=params)

    def get_covenant_certificate(self, certificate_id, headers):
        return self._request("GET", f"/covenant-certificates/{certificate_id}", headers=headers)

    def review_covenant_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/covenant-certificates/{certificate_id}/review", payload, headers)

    # --- PaymentRun ---
    def create_payment_run(self, payload, headers):
        return self._request("POST", "/payment-runs", payload, headers)

    def list_payment_runs(self, headers, params=None):
        return self._request("GET", "/payment-runs", headers=headers, params=params)

    def get_payment_run(self, run_id, headers):
        return self._request("GET", f"/payment-runs/{run_id}", headers=headers)

    def fund_payment_run(self, run_id, payload, headers):
        return self._request("POST", f"/payment-runs/{run_id}/fund", payload, headers)

    def execute_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/execute", {}, headers)

    def reverse_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/reverse", {}, headers)

    # --- DistributionRecord ---
    def list_distribution_records(self, headers, params=None):
        return self._request("GET", "/distribution-records", headers=headers, params=params)

    def get_distribution_record(self, record_id, headers):
        return self._request("GET", f"/distribution-records/{record_id}", headers=headers)

    def return_distribution_record(self, record_id, headers):
        return self._request("POST", f"/distribution-records/{record_id}/return", {}, headers)

    # --- DefaultCase ---
    def create_default_case(self, payload, headers):
        return self._request("POST", "/default-cases", payload, headers)

    def list_default_cases(self, headers, params=None):
        return self._request("GET", "/default-cases", headers=headers, params=params)

    def get_default_case(self, case_id, headers):
        return self._request("GET", f"/default-cases/{case_id}", headers=headers)

    def confirm_default_case(self, case_id, headers):
        return self._request("POST", f"/default-cases/{case_id}/confirm", {}, headers)

    def cure_default_case(self, case_id, headers):
        return self._request("POST", f"/default-cases/{case_id}/cure", {}, headers)

    # --- NoteholderDirection / DirectionEndorsement ---
    def create_direction(self, payload, headers):
        return self._request("POST", "/directions", payload, headers)

    def list_directions(self, headers, params=None):
        return self._request("GET", "/directions", headers=headers, params=params)

    def get_direction(self, direction_id, headers):
        return self._request("GET", f"/directions/{direction_id}", headers=headers)

    def endorse_direction(self, direction_id, payload, headers):
        return self._request("POST", f"/directions/{direction_id}/endorsements", payload, headers)

    def list_direction_endorsements(self, headers, params=None):
        return self._request("GET", "/direction-endorsements", headers=headers, params=params)

    def get_direction_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/direction-endorsements/{endorsement_id}", headers=headers)

    def withdraw_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/direction-endorsements/{endorsement_id}/withdraw", {}, headers)

    def execute_direction(self, direction_id, headers):
        return self._request("POST", f"/directions/{direction_id}/execute", {}, headers)

    # --- ConsentSolicitation ---
    def create_consent_solicitation(self, payload, headers):
        return self._request("POST", "/consent-solicitations", payload, headers)

    def list_consent_solicitations(self, headers, params=None):
        return self._request("GET", "/consent-solicitations", headers=headers, params=params)

    def get_consent_solicitation(self, solicitation_id, headers):
        return self._request("GET", f"/consent-solicitations/{solicitation_id}", headers=headers)

    def open_consent_solicitation(self, solicitation_id, headers):
        return self._request("POST", f"/consent-solicitations/{solicitation_id}/open", {}, headers)

    def cast_ballot(self, solicitation_id, payload, headers):
        return self._request("POST", f"/consent-solicitations/{solicitation_id}/ballots", payload, headers)

    def close_consent_solicitation(self, solicitation_id, headers):
        return self._request("POST", f"/consent-solicitations/{solicitation_id}/close", {}, headers)

    def revoke_consent_solicitation(self, solicitation_id, headers):
        return self._request("POST", f"/consent-solicitations/{solicitation_id}/revoke", {}, headers)

    # --- CollateralItem ---
    def create_collateral_item(self, payload, headers):
        return self._request("POST", "/collateral-items", payload, headers)

    def list_collateral_items(self, headers, params=None):
        return self._request("GET", "/collateral-items", headers=headers, params=params)

    def get_collateral_item(self, item_id, headers):
        return self._request("GET", f"/collateral-items/{item_id}", headers=headers)

    # --- CollateralReleaseRequest ---
    def create_collateral_release_request(self, payload, headers):
        return self._request("POST", "/collateral-release-requests", payload, headers)

    def list_collateral_release_requests(self, headers, params=None):
        return self._request("GET", "/collateral-release-requests", headers=headers, params=params)

    def get_collateral_release_request(self, request_id, headers):
        return self._request("GET", f"/collateral-release-requests/{request_id}", headers=headers)

    def verify_collateral_release_request(self, request_id, headers):
        return self._request("POST", f"/collateral-release-requests/{request_id}/verify", {}, headers)

    def decide_collateral_release_request(self, request_id, payload, headers):
        return self._request("POST", f"/collateral-release-requests/{request_id}/decide", payload, headers)

    def effect_collateral_release_request(self, request_id, headers):
        return self._request("POST", f"/collateral-release-requests/{request_id}/effect", {}, headers)

    # --- FeeInvoice ---
    def create_fee_invoice(self, payload, headers):
        return self._request("POST", "/fee-invoices", payload, headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def get_fee_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{invoice_id}", headers=headers)

    def issue_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/issue", {}, headers)

    def pay_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/pay", {}, headers)

    def dispute_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/dispute", {}, headers)

    def amend_fee_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/amend", payload, headers)

    # --- TrusteeAppointment ---
    def create_trustee_appointment(self, payload, headers):
        return self._request("POST", "/trustee-appointments", payload, headers)

    def list_trustee_appointments(self, headers, params=None):
        return self._request("GET", "/trustee-appointments", headers=headers, params=params)

    def get_trustee_appointment(self, appointment_id, headers):
        return self._request("GET", f"/trustee-appointments/{appointment_id}", headers=headers)

    def accept_trustee_appointment(self, appointment_id, headers):
        return self._request("POST", f"/trustee-appointments/{appointment_id}/accept", {}, headers)

    def effect_trustee_appointment(self, appointment_id, headers):
        return self._request("POST", f"/trustee-appointments/{appointment_id}/effect", {}, headers)

    def rescind_trustee_appointment(self, appointment_id, headers):
        return self._request("POST", f"/trustee-appointments/{appointment_id}/rescind", {}, headers)


api_client = ApiClient()
