"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.9)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Growers
    # ------------------------------------------------------------------
    def create_grower(self, payload, headers):
        return self._request("POST", "/api/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/api/growers/{grower_id}", headers=headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/api/growers", headers=headers, params=params)

    def issue_loan(self, grower_id, payload, headers):
        return self._request("POST", f"/api/growers/{grower_id}/loans", payload, headers)

    def list_loans(self, grower_id, headers, params=None):
        return self._request("GET", f"/api/growers/{grower_id}/loans",
                             headers=headers, params=params)

    def list_grower_houses(self, grower_id, headers, params=None):
        return self._request("GET", f"/api/growers/{grower_id}/houses",
                             headers=headers, params=params)

    def list_grower_contracts(self, grower_id, headers, params=None):
        return self._request("GET", f"/api/growers/{grower_id}/contracts",
                             headers=headers, params=params)

    def suspend_grower(self, grower_id, headers):
        return self._request("POST", f"/api/growers/{grower_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/activate", {}, headers)

    def impose_upgrade(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/impose-upgrade",
                             {}, headers)

    def request_renewal(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/request-renewal",
                             {}, headers)

    def renew_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/renew",
                             payload, headers)

    def reject_renewal(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/reject-renewal",
                             {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Houses
    # ------------------------------------------------------------------
    def create_house(self, payload, headers):
        return self._request("POST", "/api/houses", payload, headers)

    def get_house(self, house_id, headers):
        return self._request("GET", f"/api/houses/{house_id}", headers=headers)

    def release_downtime(self, house_id, headers):
        return self._request("POST", f"/api/houses/{house_id}/release-downtime",
                             {}, headers)

    def release_quarantine(self, house_id, headers):
        return self._request("POST", f"/api/houses/{house_id}/release-quarantine",
                             {}, headers)

    def record_audit(self, house_id, payload, headers):
        return self._request("POST", f"/api/houses/{house_id}/audits", payload, headers)

    def list_audits(self, house_id, headers, params=None):
        return self._request("GET", f"/api/houses/{house_id}/audits",
                             headers=headers, params=params)

    def list_house_flocks(self, house_id, headers, params=None):
        return self._request("GET", f"/api/houses/{house_id}/flocks",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Flocks
    # ------------------------------------------------------------------
    def create_flock(self, payload, headers):
        return self._request("POST", "/api/flocks", payload, headers)

    def get_flock(self, flock_id, headers):
        return self._request("GET", f"/api/flocks/{flock_id}", headers=headers)

    def list_flocks(self, headers, params=None):
        return self._request("GET", "/api/flocks", headers=headers, params=params)

    def schedule_placement(self, flock_id, payload, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/placements",
                             payload, headers)

    def list_placements(self, flock_id, headers, params=None):
        return self._request("GET", f"/api/flocks/{flock_id}/placements",
                             headers=headers, params=params)

    def record_feed_delivery(self, flock_id, payload, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/feed-deliveries",
                             payload, headers)

    def list_feed_deliveries(self, flock_id, headers, params=None):
        return self._request("GET", f"/api/flocks/{flock_id}/feed-deliveries",
                             headers=headers, params=params)

    def record_mortality_report(self, flock_id, payload, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/mortality-reports",
                             payload, headers)

    def list_mortality_reports(self, flock_id, headers, params=None):
        return self._request("GET", f"/api/flocks/{flock_id}/mortality-reports",
                             headers=headers, params=params)

    def record_weight_ticket(self, flock_id, payload, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/weight-tickets",
                             payload, headers)

    def list_weight_tickets(self, flock_id, headers, params=None):
        return self._request("GET", f"/api/flocks/{flock_id}/weight-tickets",
                             headers=headers, params=params)

    def schedule_catch(self, flock_id, payload, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/catch-schedules",
                             payload, headers)

    def list_catch_schedules(self, flock_id, headers, params=None):
        return self._request("GET", f"/api/flocks/{flock_id}/catch-schedules",
                             headers=headers, params=params)

    def declare_condemned_loss(self, flock_id, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/declare-condemned-loss",
                             {}, headers)

    def recompute_settlement(self, flock_id, payload, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/recompute-settlement",
                             payload, headers)

    def get_flock_settlement(self, flock_id, headers):
        return self._request("GET", f"/api/flocks/{flock_id}/settlement",
                             headers=headers)

    # ------------------------------------------------------------------
    # Placements
    # ------------------------------------------------------------------
    def confirm_placement(self, placement_id, headers):
        return self._request("POST", f"/api/placements/{placement_id}/confirm",
                             {}, headers)

    def cancel_placement(self, placement_id, headers):
        return self._request("POST", f"/api/placements/{placement_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Catch schedules
    # ------------------------------------------------------------------
    def complete_catch(self, schedule_id, headers):
        return self._request("POST", f"/api/catch-schedules/{schedule_id}/complete",
                             {}, headers)

    def cancel_catch(self, schedule_id, headers):
        return self._request("POST", f"/api/catch-schedules/{schedule_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Settlement groups
    # ------------------------------------------------------------------
    def create_settlement_group(self, payload, headers):
        return self._request("POST", "/api/settlement-groups", payload, headers)

    def get_settlement_group(self, group_id, headers):
        return self._request("GET", f"/api/settlement-groups/{group_id}",
                             headers=headers)

    def list_group_flocks(self, group_id, headers, params=None):
        return self._request("GET", f"/api/settlement-groups/{group_id}/flocks",
                             headers=headers, params=params)

    def lock_settlement_group(self, group_id, headers):
        return self._request("POST", f"/api/settlement-groups/{group_id}/lock",
                             {}, headers)

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------
    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/approve",
                             {}, headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/dispute",
                             {}, headers)

    def resolve_dispute(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/resolve-dispute",
                             {}, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/pay",
                             {}, headers)

    # ------------------------------------------------------------------
    # Catch crews
    # ------------------------------------------------------------------
    def create_catch_crew(self, payload, headers):
        return self._request("POST", "/api/catch-crews", payload, headers)

    def get_catch_crew(self, crew_id, headers):
        return self._request("GET", f"/api/catch-crews/{crew_id}", headers=headers)

    def list_crew_schedules(self, crew_id, headers, params=None):
        return self._request("GET", f"/api/catch-crews/{crew_id}/schedules",
                             headers=headers, params=params)


api_client = ApiClient()
