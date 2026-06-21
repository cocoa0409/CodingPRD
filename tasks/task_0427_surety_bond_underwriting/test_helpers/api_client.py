"""API client: one method per endpoint defined in the Surety Bond Underwriting PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- SuretyProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/surety/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/surety/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/surety/programs", headers=headers, params=params)

    def suspend_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/programs/{program_id}/suspend", payload or {}, headers
        )

    # --- Principal ---
    def create_principal(self, payload, headers):
        return self._request("POST", "/surety/principals", payload, headers)

    def get_principal(self, principal_id, headers):
        return self._request("GET", f"/surety/principals/{principal_id}", headers=headers)

    # --- IndemnityAgreement ---
    def create_indemnity_agreement(self, payload, headers):
        return self._request("POST", "/surety/indemnity-agreements", payload, headers)

    def get_indemnity_agreement(self, gia_id, headers):
        return self._request(
            "GET", f"/surety/indemnity-agreements/{gia_id}", headers=headers
        )

    def list_indemnity_agreements(self, headers, params=None):
        return self._request(
            "GET", "/surety/indemnity-agreements", headers=headers, params=params
        )

    def sign_indemnity_agreement(self, gia_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/indemnity-agreements/{gia_id}/sign", payload or {}, headers
        )

    def void_indemnity_agreement(self, gia_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/indemnity-agreements/{gia_id}/void", payload or {}, headers
        )

    # --- BondApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", "/surety/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/surety/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request("GET", "/surety/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/applications/{application_id}/submit", payload or {}, headers
        )

    def approve_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/applications/{application_id}/approve", payload or {}, headers
        )

    def refer_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/applications/{application_id}/refer", payload or {}, headers
        )

    def decline_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/surety/applications/{application_id}/decline", payload, headers
        )

    # --- Bond ---
    def create_bond(self, payload, headers):
        return self._request("POST", "/surety/bonds", payload, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/surety/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/surety/bonds", headers=headers, params=params)

    def issue_bond(self, bond_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/bonds/{bond_id}/issue", payload or {}, headers
        )

    def cancel_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/surety/bonds/{bond_id}/cancel", payload, headers)

    def renew_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/surety/bonds/{bond_id}/renew", payload, headers)

    def expire_bond(self, bond_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/bonds/{bond_id}/expire", payload or {}, headers
        )

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/surety/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/surety/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/surety/claims", headers=headers, params=params)

    def investigate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/surety/claims/{claim_id}/investigate", payload, headers
        )

    def settle_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/surety/claims/{claim_id}/settle", payload, headers
        )

    # --- Rider ---
    def create_rider(self, payload, headers):
        return self._request("POST", "/surety/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/surety/riders/{rider_id}", headers=headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/surety/riders", headers=headers, params=params)

    def apply_rider(self, rider_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/riders/{rider_id}/apply", payload or {}, headers
        )

    def reject_rider(self, rider_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/riders/{rider_id}/reject", payload or {}, headers
        )

    # --- ReinsuranceTreaty ---
    def create_treaty(self, payload, headers):
        return self._request("POST", "/surety/treaties", payload, headers)

    def get_treaty(self, treaty_id, headers):
        return self._request("GET", f"/surety/treaties/{treaty_id}", headers=headers)

    def list_treaties(self, headers, params=None):
        return self._request("GET", "/surety/treaties", headers=headers, params=params)

    def close_treaty(self, treaty_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/treaties/{treaty_id}/close", payload or {}, headers
        )

    # --- Cession ---
    def create_cession(self, payload, headers):
        return self._request("POST", "/surety/cessions", payload, headers)

    def get_cession(self, cession_id, headers):
        return self._request("GET", f"/surety/cessions/{cession_id}", headers=headers)

    def list_cessions(self, headers, params=None):
        return self._request("GET", "/surety/cessions", headers=headers, params=params)

    def recapture_cession(self, cession_id, headers, payload=None):
        return self._request(
            "POST", f"/surety/cessions/{cession_id}/recapture", payload or {}, headers
        )

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/surety/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
