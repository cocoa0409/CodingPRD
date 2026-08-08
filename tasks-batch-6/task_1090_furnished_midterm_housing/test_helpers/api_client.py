"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Host ----
    def create_host(self, payload, headers=None):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def verify_host_payout(self, host_id, headers):
        return self._request("POST", f"/hosts/{host_id}/verify-payout", {}, headers)

    # ---- Tenant ----
    def create_tenant(self, payload, headers=None):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # ---- Verification ----
    def create_verification(self, payload, headers):
        return self._request("POST", "/verifications", payload, headers)

    def get_verification(self, verification_id, headers):
        return self._request("GET", f"/verifications/{verification_id}", headers=headers)

    def list_verifications(self, headers, params=None):
        return self._request("GET", "/verifications", headers=headers, params=params)

    def transition_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/verifications/{verification_id}/transitions", payload, headers)

    # ---- Unit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def transition_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/transitions", payload, headers)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def transition_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/transitions", payload, headers)

    # ---- Extension ----
    def create_extension(self, payload, headers):
        return self._request("POST", "/extensions", payload, headers)

    def get_extension(self, extension_id, headers):
        return self._request("GET", f"/extensions/{extension_id}", headers=headers)

    def list_extensions(self, headers, params=None):
        return self._request("GET", "/extensions", headers=headers, params=params)

    def transition_extension(self, extension_id, payload, headers):
        return self._request("POST", f"/extensions/{extension_id}/transitions", payload, headers)

    # ---- Deposit ----
    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def settle_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/settle", {}, headers)

    # ---- DamageClaim ----
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def transition_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/transitions", payload, headers)

    # ---- CoiPolicy ----
    def create_coi_policy(self, payload, headers):
        return self._request("POST", "/coi-policies", payload, headers)

    def get_coi_policy(self, coi_id, headers):
        return self._request("GET", f"/coi-policies/{coi_id}", headers=headers)

    def list_coi_policies(self, headers, params=None):
        return self._request("GET", "/coi-policies", headers=headers, params=params)

    def transition_coi_policy(self, coi_id, payload, headers):
        return self._request("POST", f"/coi-policies/{coi_id}/transitions", payload, headers)

    # ---- Turnover ----
    def get_turnover(self, turnover_id, headers):
        return self._request("GET", f"/turnovers/{turnover_id}", headers=headers)

    def list_turnovers(self, headers, params=None):
        return self._request("GET", "/turnovers", headers=headers, params=params)

    def transition_turnover(self, turnover_id, payload, headers):
        return self._request("POST", f"/turnovers/{turnover_id}/transitions", payload, headers)

    # ---- Payout ----
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def transition_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/transitions", payload, headers)

    # ---- TaxAssessment ----
    def get_tax_assessment(self, assessment_id, headers):
        return self._request("GET", f"/tax-assessments/{assessment_id}", headers=headers)

    def list_tax_assessments(self, headers, params=None):
        return self._request("GET", "/tax-assessments", headers=headers, params=params)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
