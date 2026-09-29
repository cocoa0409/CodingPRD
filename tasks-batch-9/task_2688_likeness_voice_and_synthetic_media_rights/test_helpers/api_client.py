"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint in the Likeness Rights Clearance API."""

    # ---------------- state law profiles ----------------

    def create_state_law_profile(self, payload, headers):
        return self._request("POST", "/state-law-profiles", payload, headers)

    def get_state_law_profile(self, profile_id, headers):
        return self._request("GET", f"/state-law-profiles/{profile_id}", headers=headers)

    def list_state_law_profiles(self, headers, params=None):
        return self._request("GET", "/state-law-profiles", headers=headers, params=params)

    # ---------------- union minimum schedules ----------------

    def create_union_minimum_schedule(self, payload, headers):
        return self._request("POST", "/union-minimum-schedules", payload, headers)

    def get_union_minimum_schedule(self, row_id, headers):
        return self._request("GET", f"/union-minimum-schedules/{row_id}", headers=headers)

    def list_union_minimum_schedules(self, headers, params=None):
        return self._request("GET", "/union-minimum-schedules", headers=headers, params=params)

    # ---------------- talents ----------------

    def create_talent(self, payload, headers):
        return self._request("POST", "/talents", payload, headers)

    def get_talent(self, talent_id, headers):
        return self._request("GET", f"/talents/{talent_id}", headers=headers)

    def list_talents(self, headers, params=None):
        return self._request("GET", "/talents", headers=headers, params=params)

    def record_death(self, talent_id, payload, headers):
        return self._request("POST", f"/talents/{talent_id}/death-record", payload, headers)

    # ---------------- estate authorities ----------------

    def submit_estate_authority(self, talent_id, payload, headers):
        return self._request(
            "POST", f"/talents/{talent_id}/estate-authorities", payload, headers
        )

    def list_estate_authorities(self, talent_id, headers, params=None):
        return self._request(
            "GET", f"/talents/{talent_id}/estate-authorities", headers=headers, params=params
        )

    def get_estate_authority(self, authority_id, headers):
        return self._request("GET", f"/estate-authorities/{authority_id}", headers=headers)

    def verify_estate_authority(self, authority_id, payload, headers):
        return self._request(
            "POST", f"/estate-authorities/{authority_id}/verify", payload, headers
        )

    # ---------------- consent grants ----------------

    def create_consent_grant(self, payload, headers):
        return self._request("POST", "/consent-grants", payload, headers)

    def get_consent_grant(self, grant_id, headers):
        return self._request("GET", f"/consent-grants/{grant_id}", headers=headers)

    def list_consent_grants(self, headers, params=None):
        return self._request("GET", "/consent-grants", headers=headers, params=params)

    def countersign_consent_grant(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/consent-grants/{grant_id}/countersign", payload, headers
        )

    def change_consent_grant_suspension(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/consent-grants/{grant_id}/suspension", payload, headers
        )

    def revoke_consent_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/consent-grants/{grant_id}/revoke", payload, headers)

    # ---------------- biometric assets ----------------

    def create_biometric_asset(self, payload, headers):
        return self._request("POST", "/biometric-assets", payload, headers)

    def get_biometric_asset(self, asset_id, headers):
        return self._request("GET", f"/biometric-assets/{asset_id}", headers=headers)

    def list_biometric_assets(self, headers, params=None):
        return self._request("GET", "/biometric-assets", headers=headers, params=params)

    def purge_biometric_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/biometric-assets/{asset_id}/purge", payload, headers)

    # ---------------- digital replicas ----------------

    def create_digital_replica(self, payload, headers):
        return self._request("POST", "/digital-replicas", payload, headers)

    def get_digital_replica(self, replica_id, headers):
        return self._request("GET", f"/digital-replicas/{replica_id}", headers=headers)

    def list_digital_replicas(self, headers, params=None):
        return self._request("GET", "/digital-replicas", headers=headers, params=params)

    def approve_replica_for_use(self, replica_id, payload, headers):
        return self._request(
            "POST", f"/digital-replicas/{replica_id}/approve-for-use", payload, headers
        )

    # ---------------- generated performances ----------------

    def create_generated_performance(self, payload, headers):
        return self._request("POST", "/generated-performances", payload, headers)

    def get_generated_performance(self, performance_id, headers):
        return self._request(
            "GET", f"/generated-performances/{performance_id}", headers=headers
        )

    def list_generated_performances(self, headers, params=None):
        return self._request(
            "GET", "/generated-performances", headers=headers, params=params
        )

    def review_generated_performance(self, performance_id, payload, headers):
        return self._request(
            "POST", f"/generated-performances/{performance_id}/review", payload, headers
        )

    def resubmit_generated_performance(self, performance_id, payload, headers):
        return self._request(
            "POST", f"/generated-performances/{performance_id}/resubmit", payload, headers
        )

    # ---------------- usage licenses ----------------

    def create_usage_license(self, payload, headers):
        return self._request("POST", "/usage-licenses", payload, headers)

    def get_usage_license(self, license_id, headers):
        return self._request("GET", f"/usage-licenses/{license_id}", headers=headers)

    def list_usage_licenses(self, headers, params=None):
        return self._request("GET", "/usage-licenses", headers=headers, params=params)

    def attest_disclosure(self, license_id, payload, headers):
        return self._request(
            "POST", f"/usage-licenses/{license_id}/disclosure", payload, headers
        )

    def verify_disclosure(self, license_id, payload, headers):
        return self._request(
            "POST", f"/usage-licenses/{license_id}/disclosure-verification", payload, headers
        )

    def go_live(self, license_id, payload, headers):
        return self._request(
            "POST", f"/usage-licenses/{license_id}/go-live", payload, headers
        )

    def confirm_removal(self, license_id, payload, headers):
        return self._request(
            "POST", f"/usage-licenses/{license_id}/confirm-removal", payload, headers
        )

    # ---------------- compensation ledger ----------------

    def get_compensation_entry(self, entry_id, headers):
        return self._request("GET", f"/compensation-entries/{entry_id}", headers=headers)

    def list_compensation_entries(self, headers, params=None):
        return self._request("GET", "/compensation-entries", headers=headers, params=params)

    # ---------------- infringement cases ----------------

    def create_infringement_case(self, payload, headers):
        return self._request("POST", "/infringement-cases", payload, headers)

    def get_infringement_case(self, case_id, headers):
        return self._request("GET", f"/infringement-cases/{case_id}", headers=headers)

    def list_infringement_cases(self, headers, params=None):
        return self._request("GET", "/infringement-cases", headers=headers, params=params)

    def triage_infringement_case(self, case_id, payload, headers):
        return self._request("POST", f"/infringement-cases/{case_id}/triage", payload, headers)

    def escalate_infringement_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/infringement-cases/{case_id}/escalate", payload, headers
        )

    def close_infringement_case(self, case_id, payload, headers):
        return self._request("POST", f"/infringement-cases/{case_id}/close", payload, headers)

    # ---------------- ops run and logical clock ----------------

    def run_compliance_sweep(self, headers, payload=None):
        return self._request("POST", "/compliance-sweeps", payload or {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- raw escape hatches ----------------

    def raw_post(self, path, payload, headers):
        """POST with fully caller-controlled headers (used by header-level checks)."""
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers, params=None):
        """GET with fully caller-controlled headers (used by header-level checks)."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
