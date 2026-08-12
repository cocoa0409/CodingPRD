"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock utility
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Party registry
    # ------------------------------------------------------------------
    def create_forester(self, payload, headers):
        return self._request("POST", "/forestry/foresters", payload, headers)

    def create_landowner(self, payload, headers):
        return self._request("POST", "/forestry/landowners", payload, headers)

    def create_buyer(self, payload, headers):
        return self._request("POST", "/forestry/buyers", payload, headers)

    def create_contractor(self, payload, headers):
        return self._request("POST", "/forestry/contractors", payload, headers)

    # ------------------------------------------------------------------
    # Tracts and stands
    # ------------------------------------------------------------------
    def create_tract(self, payload, headers):
        return self._request("POST", "/forestry/tracts", payload, headers)

    def get_tract(self, tract_id, headers):
        return self._request("GET", f"/forestry/tracts/{tract_id}", headers=headers)

    def list_tracts(self, headers, params=None):
        return self._request("GET", "/forestry/tracts", headers=headers, params=params)

    def create_stand(self, payload, headers):
        return self._request("POST", "/forestry/stands", payload, headers)

    def get_stand(self, stand_id, headers):
        return self._request("GET", f"/forestry/stands/{stand_id}", headers=headers)

    def list_stands(self, headers, params=None):
        return self._request("GET", "/forestry/stands", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cruises
    # ------------------------------------------------------------------
    def create_cruise(self, payload, headers):
        return self._request("POST", "/forestry/cruises", payload, headers)

    def get_cruise(self, cruise_id, headers):
        return self._request("GET", f"/forestry/cruises/{cruise_id}", headers=headers)

    def list_cruises(self, headers, params=None):
        return self._request("GET", "/forestry/cruises", headers=headers, params=params)

    def finalize_tally(self, cruise_id, headers):
        return self._request("POST", f"/forestry/cruises/{cruise_id}/finalize-tally", {}, headers)

    def reconcile_cruise(self, cruise_id, payload, headers):
        return self._request("POST", f"/forestry/cruises/{cruise_id}/reconcile", payload, headers)

    def reopen_cruise(self, cruise_id, headers):
        return self._request("POST", f"/forestry/cruises/{cruise_id}/reopen", {}, headers)

    def certify_cruise(self, cruise_id, payload, headers):
        return self._request("POST", f"/forestry/cruises/{cruise_id}/certify", payload, headers)

    def void_cruise(self, cruise_id, headers):
        return self._request("POST", f"/forestry/cruises/{cruise_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Prescriptions
    # ------------------------------------------------------------------
    def create_prescription(self, payload, headers):
        return self._request("POST", "/forestry/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/forestry/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/forestry/prescriptions", headers=headers, params=params)

    def propose_prescription(self, prescription_id, headers):
        return self._request("POST", f"/forestry/prescriptions/{prescription_id}/propose", {}, headers)

    def approve_prescription(self, prescription_id, headers):
        return self._request("POST", f"/forestry/prescriptions/{prescription_id}/approve", {}, headers)

    def revise_prescription(self, prescription_id, payload, headers):
        return self._request("POST", f"/forestry/prescriptions/{prescription_id}/revise", payload, headers)

    def activate_prescription(self, prescription_id, headers):
        return self._request("POST", f"/forestry/prescriptions/{prescription_id}/activate", {}, headers)

    def complete_prescription(self, prescription_id, headers):
        return self._request("POST", f"/forestry/prescriptions/{prescription_id}/complete", {}, headers)

    def withdraw_prescription(self, prescription_id, headers):
        return self._request("POST", f"/forestry/prescriptions/{prescription_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Sales and bids
    # ------------------------------------------------------------------
    def create_sale(self, payload, headers):
        return self._request("POST", "/forestry/sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/forestry/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/forestry/sales", headers=headers, params=params)

    def offer_sale(self, sale_id, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/offer", {}, headers)

    def open_bidding(self, sale_id, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/open-bidding", {}, headers)

    def close_bidding(self, sale_id, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/close-bidding", {}, headers)

    def award_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/award", payload, headers)

    def no_sale(self, sale_id, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/no-sale", {}, headers)

    def reoffer_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/reoffer", payload, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/cancel", {}, headers)

    def submit_bid(self, sale_id, payload, headers):
        return self._request("POST", f"/forestry/sales/{sale_id}/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/forestry/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/forestry/bids", headers=headers, params=params)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/forestry/bids/{bid_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Contracts and bonds
    # ------------------------------------------------------------------
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/forestry/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/forestry/contracts", headers=headers, params=params)

    def post_bond(self, contract_id, payload, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/bond", payload, headers)

    def assign_contractor(self, contract_id, payload, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/assign-contractor", payload, headers)

    def start_harvest(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/start-harvest", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/suspend", {}, headers)

    def resume_contract(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/resume", {}, headers)

    def complete_harvest(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/complete-harvest", {}, headers)

    def declare_default(self, contract_id, payload, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/declare-default", payload, headers)

    def cure_contract(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/cure", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/terminate", {}, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/close", {}, headers)

    def release_holdback(self, contract_id, headers):
        return self._request("POST", f"/forestry/contracts/{contract_id}/release-holdback", {}, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/forestry/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/forestry/bonds", headers=headers, params=params)

    def claim_forfeiture(self, bond_id, headers):
        return self._request("POST", f"/forestry/bonds/{bond_id}/claim-forfeiture", {}, headers)

    def adjudicate_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/forestry/bonds/{bond_id}/adjudicate", payload, headers)

    def release_bond(self, bond_id, headers):
        return self._request("POST", f"/forestry/bonds/{bond_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Scale tickets
    # ------------------------------------------------------------------
    def create_scale_ticket(self, payload, headers):
        return self._request("POST", "/forestry/scale-tickets", payload, headers)

    def get_scale_ticket(self, ticket_id, headers):
        return self._request("GET", f"/forestry/scale-tickets/{ticket_id}", headers=headers)

    def list_scale_tickets(self, headers, params=None):
        return self._request("GET", "/forestry/scale-tickets", headers=headers, params=params)

    def verify_scale_ticket(self, ticket_id, headers):
        return self._request("POST", f"/forestry/scale-tickets/{ticket_id}/verify", {}, headers)

    def dispute_scale_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/forestry/scale-tickets/{ticket_id}/dispute", payload, headers)

    def resolve_scale_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/forestry/scale-tickets/{ticket_id}/resolve", payload, headers)

    def void_scale_ticket(self, ticket_id, headers):
        return self._request("POST", f"/forestry/scale-tickets/{ticket_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------
    def create_settlement(self, payload, headers):
        return self._request("POST", "/forestry/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/forestry/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/forestry/settlements", headers=headers, params=params)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/forestry/settlements/{settlement_id}/approve", {}, headers)

    def disburse_settlement(self, settlement_id, headers):
        return self._request("POST", f"/forestry/settlements/{settlement_id}/disburse", {}, headers)

    def refund_settlement(self, settlement_id, headers):
        return self._request("POST", f"/forestry/settlements/{settlement_id}/refund", {}, headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/forestry/settlements/{settlement_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/forestry/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/forestry/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/forestry/inspections", headers=headers, params=params)

    def conduct_inspection(self, inspection_id, headers):
        return self._request("POST", f"/forestry/inspections/{inspection_id}/conduct", {}, headers)

    def close_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/forestry/inspections/{inspection_id}/close", payload, headers)

    def verify_corrective(self, inspection_id, headers):
        return self._request("POST", f"/forestry/inspections/{inspection_id}/verify-corrective", {}, headers)

    # ------------------------------------------------------------------
    # Reforestation obligations and survival surveys
    # ------------------------------------------------------------------
    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/forestry/obligations/{obligation_id}", headers=headers)

    def list_obligations(self, headers, params=None):
        return self._request("GET", "/forestry/obligations", headers=headers, params=params)

    def record_planting(self, obligation_id, payload, headers):
        return self._request("POST", f"/forestry/obligations/{obligation_id}/record-planting", payload, headers)

    def declare_delinquent(self, obligation_id, headers):
        return self._request("POST", f"/forestry/obligations/{obligation_id}/declare-delinquent", {}, headers)

    def create_survey(self, obligation_id, payload, headers):
        return self._request("POST", f"/forestry/obligations/{obligation_id}/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/forestry/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/forestry/surveys", headers=headers, params=params)

    def finalize_survey(self, survey_id, headers):
        return self._request("POST", f"/forestry/surveys/{survey_id}/finalize", {}, headers)

    def void_survey(self, survey_id, headers):
        return self._request("POST", f"/forestry/surveys/{survey_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Carbon valuations
    # ------------------------------------------------------------------
    def create_carbon_valuation(self, payload, headers):
        return self._request("POST", "/forestry/carbon-valuations", payload, headers)

    def get_carbon_valuation(self, valuation_id, headers):
        return self._request("GET", f"/forestry/carbon-valuations/{valuation_id}", headers=headers)

    def list_carbon_valuations(self, headers, params=None):
        return self._request("GET", "/forestry/carbon-valuations", headers=headers, params=params)

    def accept_carbon_valuation(self, valuation_id, headers):
        return self._request("POST", f"/forestry/carbon-valuations/{valuation_id}/accept", {}, headers)

    def reject_carbon_valuation(self, valuation_id, headers):
        return self._request("POST", f"/forestry/carbon-valuations/{valuation_id}/reject", {}, headers)


api_client = ApiClient()
# Under per-test-server isolation the runner kills and re-spawns the server on
# the same port before every test. This client instance is session-scoped, so a
# pooled HTTP keep-alive connection to the previous (now-killed) server process
# would otherwise be reused by the next test and surface as a spurious
# "RemoteDisconnected: Remote end closed connection without response" whenever
# the dead-connection reset races the reused request under load. Sending
# "Connection: close" makes every request open a fresh connection to whichever
# server process is currently bound, eliminating the stale-connection reuse race.
api_client.session.headers["Connection"] = "close"
