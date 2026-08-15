"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # --- Product classes ---
    def create_product_class(self, payload, headers):
        return self._request("POST", "/product-classes", payload, headers)

    def get_product_class(self, product_class_id, headers):
        return self._request(
            "GET", f"/product-classes/{product_class_id}", headers=headers)

    # --- Tax rates ---
    def create_tax_rate(self, payload, headers):
        return self._request("POST", "/tax-rates", payload, headers)

    def get_tax_rate(self, rate_id, headers):
        return self._request("GET", f"/tax-rates/{rate_id}", headers=headers)

    def list_tax_rates(self, headers, params=None):
        return self._request(
            "GET", "/tax-rates", headers=headers, params=params)

    # --- Rate change notices ---
    def create_rate_change_notice(self, payload, headers):
        return self._request("POST", "/rate-change-notices", payload, headers)

    def get_rate_change_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/rate-change-notices/{notice_id}", headers=headers)

    def list_rate_change_notices(self, headers, params=None):
        return self._request(
            "GET", "/rate-change-notices", headers=headers, params=params)

    def validate_rate_change_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/rate-change-notices/{notice_id}/validate", {}, headers)

    def reject_rate_change_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/rate-change-notices/{notice_id}/reject", {}, headers)

    def apply_rate_change_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/rate-change-notices/{notice_id}/apply", payload, headers)

    # --- Registrants ---
    def create_registrant(self, payload, headers):
        return self._request("POST", "/registrants", payload, headers)

    def get_registrant(self, registrant_id, headers):
        return self._request(
            "GET", f"/registrants/{registrant_id}", headers=headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request(
            "GET", "/registrations", headers=headers, params=params)

    def activate_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/activate", {}, headers)

    def suspend_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/suspend", {}, headers)

    def reinstate_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/reinstate", {}, headers)

    def revoke_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/revoke", {}, headers)

    def get_bond_status(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}/bond-status",
            headers=headers)

    def purge_expired_records(self, registration_id, period, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/purge-expired-records",
            {"period": period}, headers)

    # --- Bonds ---
    def create_bond(self, payload, headers):
        return self._request("POST", "/bonds", payload, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/bonds", headers=headers, params=params)

    def activate_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/activate", {}, headers)

    def cancel_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/cancel", {}, headers)

    # --- Exemption certificates ---
    def create_exemption_certificate(self, payload, headers):
        return self._request("POST", "/exemption-certificates", payload, headers)

    def get_exemption_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/exemption-certificates/{certificate_id}", headers=headers)

    def list_exemption_certificates(self, headers, params=None):
        return self._request(
            "GET", "/exemption-certificates", headers=headers, params=params)

    def verify_exemption_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/exemption-certificates/{certificate_id}/verify",
            {}, headers)

    def revoke_exemption_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/exemption-certificates/{certificate_id}/revoke",
            {}, headers)

    # --- Bonded movements ---
    def create_bonded_movement(self, payload, headers):
        return self._request("POST", "/bonded-movements", payload, headers)

    def get_bonded_movement(self, movement_id, headers):
        return self._request(
            "GET", f"/bonded-movements/{movement_id}", headers=headers)

    def list_bonded_movements(self, headers, params=None):
        return self._request(
            "GET", "/bonded-movements", headers=headers, params=params)

    def dispatch_movement(self, movement_id, headers):
        return self._request(
            "POST", f"/bonded-movements/{movement_id}/dispatch", {}, headers)

    def receive_movement(self, movement_id, quantity_received_units, headers):
        return self._request(
            "POST", f"/bonded-movements/{movement_id}/receive",
            {"quantity_received_units": quantity_received_units}, headers)

    def discharge_movement(self, movement_id, headers):
        return self._request(
            "POST", f"/bonded-movements/{movement_id}/discharge", {}, headers)

    def default_movement(self, movement_id, headers):
        return self._request(
            "POST", f"/bonded-movements/{movement_id}/default", {}, headers)

    # --- Taxable events ---
    def create_taxable_event(self, payload, headers):
        return self._request("POST", "/taxable-events", payload, headers)

    def get_taxable_event(self, event_id, headers):
        return self._request(
            "GET", f"/taxable-events/{event_id}", headers=headers)

    def list_taxable_events(self, headers, params=None):
        return self._request(
            "GET", "/taxable-events", headers=headers, params=params)

    def classify_event(self, event_id, headers):
        return self._request(
            "POST", f"/taxable-events/{event_id}/classify", {}, headers)

    def rate_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/taxable-events/{event_id}/rate", payload, headers)

    def reclassify_event(self, event_id, headers):
        return self._request(
            "POST", f"/taxable-events/{event_id}/reclassify", {}, headers)

    def void_event(self, event_id, headers):
        return self._request(
            "POST", f"/taxable-events/{event_id}/void", {}, headers)

    # --- Returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def get_return_summary(self, return_id, headers):
        return self._request(
            "GET", f"/returns/{return_id}/summary", headers=headers)

    def submit_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/submit", {}, headers)

    def withdraw_return(self, return_id, headers):
        return self._request(
            "POST", f"/returns/{return_id}/withdraw", {}, headers)

    def file_return(self, return_id, expected_return_version, headers):
        return self._request(
            "POST", f"/returns/{return_id}/file",
            {"expected_return_version": expected_return_version}, headers)

    def amend_return(self, return_id, payload, headers):
        return self._request(
            "POST", f"/returns/{return_id}/amend", payload, headers)

    # --- Deposits ---
    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def pay_deposit(self, deposit_id, amount_cents, headers):
        return self._request(
            "POST", f"/deposits/{deposit_id}/pay",
            {"amount_cents": amount_cents}, headers)

    def waive_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/waive", {}, headers)

    # --- Credit claims ---
    def create_credit_claim(self, payload, headers):
        return self._request("POST", "/credit-claims", payload, headers)

    def get_credit_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/credit-claims/{claim_id}", headers=headers)

    def list_credit_claims(self, headers, params=None):
        return self._request(
            "GET", "/credit-claims", headers=headers, params=params)

    def submit_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/submit", {}, headers)

    def approve_credit_claim(self, claim_id, approved_cents, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/approve",
            {"approved_cents": approved_cents}, headers)

    def deny_credit_claim(self, claim_id, reason, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/deny",
            {"reason": reason}, headers)

    def apply_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/apply", {}, headers)

    def reverse_credit_claim(self, claim_id, amount_cents, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/reverse",
            {"amount_cents": amount_cents}, headers)

    def withdraw_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/withdraw", {}, headers)

    def resubmit_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/resubmit", {}, headers)

    # --- Audit cases ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/audit-cases", payload, headers)

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"/audit-cases/{case_id}", headers=headers)

    def list_audit_cases(self, headers, params=None):
        return self._request(
            "GET", "/audit-cases", headers=headers, params=params)

    def request_audit_documents(self, case_id, headers):
        return self._request(
            "POST", f"/audit-cases/{case_id}/request-documents", {}, headers)

    def begin_audit_review(self, case_id, headers):
        return self._request(
            "POST", f"/audit-cases/{case_id}/begin-review", {}, headers)

    def close_audit_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/audit-cases/{case_id}/close", payload, headers)


api_client = ApiClient()
