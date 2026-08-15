"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- bins ----
    def create_bin(self, payload, headers):
        return self._request("POST", "/grain/bins", payload, headers)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/grain/bins/{bin_id}", headers=headers)

    # ---- lots ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/grain/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/grain/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/grain/lots", headers=headers, params=params)

    def get_carry_analysis(self, lot_id, headers, params):
        return self._request(
            "GET", f"/grain/lots/{lot_id}/carry-analysis", headers=headers, params=params
        )

    def list_shrink_events(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/grain/lots/{lot_id}/shrink-events", headers=headers, params=params
        )

    # ---- temperature readings ----
    def create_reading(self, payload, headers):
        return self._request("POST", "/grain/temperature-readings", payload, headers)

    def get_reading(self, reading_id, headers):
        return self._request(
            "GET", f"/grain/temperature-readings/{reading_id}", headers=headers
        )

    def list_readings(self, headers, params=None):
        return self._request(
            "GET", "/grain/temperature-readings", headers=headers, params=params
        )

    # ---- spoilage alerts ----
    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/grain/spoilage-alerts/{alert_id}", headers=headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/grain/spoilage-alerts", headers=headers, params=params)

    def close_alert(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/grain/spoilage-alerts/{alert_id}/close", payload, headers
        )

    # ---- fumigations ----
    def create_fumigation(self, payload, headers):
        return self._request("POST", "/grain/fumigations", payload, headers)

    def get_fumigation(self, fumigation_id, headers):
        return self._request(
            "GET", f"/grain/fumigations/{fumigation_id}", headers=headers
        )

    def list_fumigations(self, headers, params=None):
        return self._request("GET", "/grain/fumigations", headers=headers, params=params)

    def clear_fumigation(self, fumigation_id, headers):
        return self._request(
            "POST", f"/grain/fumigations/{fumigation_id}/clear", {}, headers
        )

    # ---- entry permits ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/grain/entry-permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/grain/entry-permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/grain/entry-permits", headers=headers, params=params)

    def approve_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/grain/entry-permits/{permit_id}/approve", {}, headers
        )

    # ---- contracts ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/grain/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/grain/contracts/{contract_id}", headers=headers)

    # ---- loadouts ----
    def create_loadout(self, payload, headers):
        return self._request("POST", "/grain/loadouts", payload, headers)

    def get_loadout(self, loadout_id, headers):
        return self._request("GET", f"/grain/loadouts/{loadout_id}", headers=headers)

    def list_loadouts(self, headers, params=None):
        return self._request("GET", "/grain/loadouts", headers=headers, params=params)

    def dispatch_loadout(self, loadout_id, headers):
        return self._request(
            "POST", f"/grain/loadouts/{loadout_id}/dispatch", {}, headers
        )

    def deliver_loadout(self, loadout_id, payload, headers):
        return self._request(
            "POST", f"/grain/loadouts/{loadout_id}/deliver", payload, headers
        )

    def confirm_settlement(self, loadout_id, headers):
        return self._request(
            "POST", f"/grain/loadouts/{loadout_id}/confirm-settlement", {}, headers
        )

    def void_settlement(self, loadout_id, headers):
        return self._request(
            "POST", f"/grain/loadouts/{loadout_id}/void-settlement", {}, headers
        )

    # ---- policies / claims ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/grain/policies", payload, headers)

    def create_claim(self, payload, headers):
        return self._request("POST", "/grain/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/grain/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/grain/claims", headers=headers, params=params)

    def approve_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/grain/claims/{claim_id}/approve", payload, headers
        )

    # ---- applicators ----
    def create_applicator(self, payload, headers):
        return self._request("POST", "/grain/applicators", payload, headers)

    # ---- assessments ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/grain/assessments", payload, headers)

    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
