"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Account Owners (PRD §3.1) ──────────────────────────────────
    def create_owner(self, payload, headers):
        return self._request("POST", "/ira/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/ira/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/ira/owners", headers=headers, params=params)

    def patch_owner_agi(self, owner_id, payload, headers):
        return self._request("PATCH", f"/ira/owners/{owner_id}/agi", payload, headers)

    def declare_owner_deceased(self, owner_id, payload, headers):
        return self._request(
            "POST", f"/ira/owners/{owner_id}/declare-deceased", payload, headers
        )

    # ─── IRA Accounts (PRD §3.2) ────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/ira/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/ira/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/ira/accounts", headers=headers, params=params)

    def freeze_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/ira/accounts/{account_id}/freeze", payload, headers
        )

    def unfreeze_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/ira/accounts/{account_id}/unfreeze", payload, headers
        )

    def close_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/ira/accounts/{account_id}/close", payload, headers
        )

    # ─── Contributions (PRD §3.3) ───────────────────────────────────
    def create_contribution(self, payload, headers):
        return self._request("POST", "/ira/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request(
            "GET", f"/ira/contributions/{contribution_id}", headers=headers
        )

    def list_contributions(self, headers, params=None):
        return self._request(
            "GET", "/ira/contributions", headers=headers, params=params
        )

    def confirm_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"/ira/contributions/{contribution_id}/confirm", payload, headers
        )

    def reject_contribution(self, contribution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ira/contributions/{contribution_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    def reverse_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"/ira/contributions/{contribution_id}/reverse", payload, headers
        )

    # ─── Distributions (PRD §3.4) ───────────────────────────────────
    def create_distribution(self, payload, headers):
        return self._request("POST", "/ira/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/ira/distributions/{distribution_id}", headers=headers
        )

    def list_distributions(self, headers, params=None):
        return self._request(
            "GET", "/ira/distributions", headers=headers, params=params
        )

    def confirm_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/ira/distributions/{distribution_id}/confirm", payload, headers
        )

    def reverse_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/ira/distributions/{distribution_id}/reverse", payload, headers
        )

    # ─── Conversions (PRD §3.5) ─────────────────────────────────────
    def create_conversion(self, payload, headers):
        return self._request("POST", "/ira/conversions", payload, headers)

    def get_conversion(self, conversion_id, headers):
        return self._request(
            "GET", f"/ira/conversions/{conversion_id}", headers=headers
        )

    def list_conversions(self, headers, params=None):
        return self._request("GET", "/ira/conversions", headers=headers, params=params)

    def complete_conversion(self, conversion_id, payload, headers):
        return self._request(
            "POST", f"/ira/conversions/{conversion_id}/complete", payload, headers
        )

    def reverse_conversion(self, conversion_id, payload, headers):
        return self._request(
            "POST", f"/ira/conversions/{conversion_id}/reverse", payload, headers
        )

    # ─── Beneficiary Designations (PRD §3.6) ────────────────────────
    def create_beneficiary_designation(self, payload, headers):
        return self._request("POST", "/ira/beneficiary-designations", payload, headers)

    def get_beneficiary_designation(self, designation_id, headers):
        return self._request(
            "GET",
            f"/ira/beneficiary-designations/{designation_id}",
            headers=headers,
        )

    def list_beneficiary_designations(self, headers, params=None):
        return self._request(
            "GET", "/ira/beneficiary-designations", headers=headers, params=params
        )

    def activate_beneficiary_designation(self, designation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ira/beneficiary-designations/{designation_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def revoke_beneficiary_designation(self, designation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ira/beneficiary-designations/{designation_id}/revoke",
            payload if payload is not None else {},
            headers,
        )

    # ─── RMD Schedules (PRD §3.7) ───────────────────────────────────
    def create_rmd_schedule(self, payload, headers):
        return self._request("POST", "/ira/rmd-schedules", payload, headers)

    def get_rmd_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/ira/rmd-schedules/{schedule_id}", headers=headers
        )

    def list_rmd_schedules(self, headers, params=None):
        return self._request(
            "GET", "/ira/rmd-schedules", headers=headers, params=params
        )

    # ─── 1099-R Forms (PRD §3.9) ────────────────────────────────────
    def get_form_1099r(self, form_id, headers):
        return self._request("GET", f"/ira/forms-1099r/{form_id}", headers=headers)

    def list_forms_1099r(self, headers, params=None):
        return self._request(
            "GET", "/ira/forms-1099r", headers=headers, params=params
        )

    # ─── Audit Events (PRD §3.8) ────────────────────────────────────
    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/ira/audit-events/{event_id}", headers=headers)

    def list_audit_events(self, headers, params=None):
        return self._request(
            "GET", "/ira/audit-events", headers=headers, params=params
        )

    # ─── Test-driving clock and ops (PRD §2.10, §3.7) ───────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/ira/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/ira/_clock", headers=headers)

    def advance_year_rollover(self, payload, headers):
        return self._request(
            "POST", "/ira/_ops/advance-year-rollover", payload, headers
        )


api_client = ApiClient()
