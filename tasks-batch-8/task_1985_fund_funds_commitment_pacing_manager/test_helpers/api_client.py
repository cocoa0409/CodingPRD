"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- FoFProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/fof/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/fof/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/fof/programs/{program_id}", headers=headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/open", {}, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/resume", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/close", {}, headers)

    def create_ledger_entry(self, program_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/ledger-entries", payload, headers)

    def list_ledger_entries(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/ledger-entries", headers=headers, params=params)

    def get_liquidity_forecast(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/liquidity-forecast", headers=headers, params=params)

    # --- PacingPlan ---
    def create_pacing_plan(self, program_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/pacing-plans", payload, headers)

    def list_pacing_plans(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/pacing-plans", headers=headers, params=params)

    def get_pacing_plan(self, program_id, plan_id, headers):
        return self._request("GET", f"/fof/programs/{program_id}/pacing-plans/{plan_id}", headers=headers)

    def get_pacing_plan_flat(self, plan_id, headers):
        return self._request("GET", f"/fof/pacing-plans/{plan_id}", headers=headers)

    def approve_pacing_plan(self, program_id, plan_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/pacing-plans/{plan_id}/approve", {}, headers)

    def supersede_pacing_plan(self, program_id, plan_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/pacing-plans/{plan_id}/supersede", payload, headers)

    def list_plan_proposals(self, plan_id, headers, params=None):
        return self._request("GET", f"/fof/pacing-plans/{plan_id}/proposals", headers=headers, params=params)

    # --- Manager / FundVehicle ---
    def create_manager(self, payload, headers):
        return self._request("POST", "/fof/managers", payload, headers)

    def list_managers(self, headers, params=None):
        return self._request("GET", "/fof/managers", headers=headers, params=params)

    def get_manager(self, manager_id, headers):
        return self._request("GET", f"/fof/managers/{manager_id}", headers=headers)

    def approve_manager(self, manager_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/approve", {}, headers)

    def suspend_manager(self, manager_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/suspend", {}, headers)

    def reinstate_manager(self, manager_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/reinstate", {}, headers)

    def exit_manager(self, manager_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/exit", {}, headers)

    def create_vehicle(self, manager_id, payload, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/vehicles", payload, headers)

    def list_vehicles(self, manager_id, headers, params=None):
        return self._request("GET", f"/fof/managers/{manager_id}/vehicles", headers=headers, params=params)

    def get_vehicle(self, manager_id, vehicle_id, headers):
        return self._request("GET", f"/fof/managers/{manager_id}/vehicles/{vehicle_id}", headers=headers)

    def get_vehicle_flat(self, vehicle_id, headers):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}", headers=headers)

    def begin_diligence(self, manager_id, vehicle_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/vehicles/{vehicle_id}/begin-diligence", {}, headers)

    def approve_vehicle(self, manager_id, vehicle_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/vehicles/{vehicle_id}/approve-vehicle", {}, headers)

    def decline_vehicle(self, manager_id, vehicle_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/vehicles/{vehicle_id}/decline-vehicle", {}, headers)

    def close_vehicle_to_new(self, manager_id, vehicle_id, headers):
        return self._request("POST", f"/fof/managers/{manager_id}/vehicles/{vehicle_id}/close-to-new", {}, headers)

    def list_vehicle_commitments(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}/commitments", headers=headers, params=params)

    def list_vehicle_secondary_bids(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}/secondary-bids", headers=headers, params=params)

    def list_vehicle_snapshots(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}/snapshots", headers=headers, params=params)

    # --- DueDiligenceReview ---
    def create_dd_review(self, vehicle_id, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/dd-reviews", {}, headers)

    def list_dd_reviews(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}/dd-reviews", headers=headers, params=params)

    def get_dd_review(self, vehicle_id, review_id, headers):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}", headers=headers)

    def update_dd_review(self, vehicle_id, review_id, payload, headers):
        return self._request("PUT", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}", payload, headers)

    def submit_dd_review(self, vehicle_id, review_id, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}/submit", {}, headers)

    def request_info_dd_review(self, vehicle_id, review_id, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}/request-info", {}, headers)

    def resubmit_dd_review(self, vehicle_id, review_id, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}/resubmit", {}, headers)

    def complete_dd_review(self, vehicle_id, review_id, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}/complete", {}, headers)

    def withdraw_dd_review(self, vehicle_id, review_id, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/dd-reviews/{review_id}/withdraw", {}, headers)

    # --- InvestmentProposal ---
    def create_proposal(self, vehicle_id, payload, headers):
        return self._request("POST", f"/fof/vehicles/{vehicle_id}/proposals", payload, headers)

    def list_vehicle_proposals(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/fof/vehicles/{vehicle_id}/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/fof/proposals/{proposal_id}", headers=headers)

    def list_program_proposals(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/proposals", headers=headers, params=params)

    def recommend_proposal(self, proposal_id, headers):
        return self._request("POST", f"/fof/proposals/{proposal_id}/recommend", {}, headers)

    def ic_approve_proposal(self, proposal_id, headers):
        return self._request("POST", f"/fof/proposals/{proposal_id}/ic-approve", {}, headers)

    def ic_reject_proposal(self, proposal_id, headers):
        return self._request("POST", f"/fof/proposals/{proposal_id}/ic-reject", {}, headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/fof/proposals/{proposal_id}/withdraw", {}, headers)

    def list_proposal_commitments(self, proposal_id, headers, params=None):
        return self._request("GET", f"/fof/proposals/{proposal_id}/commitments", headers=headers, params=params)

    # --- Commitment ---
    def list_program_commitments(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/commitments", headers=headers, params=params)

    def get_program_commitment(self, program_id, commitment_id, headers):
        return self._request("GET", f"/fof/programs/{program_id}/commitments/{commitment_id}", headers=headers)

    def get_commitment_flat(self, commitment_id, headers):
        return self._request("GET", f"/fof/commitments/{commitment_id}", headers=headers)

    def execute_commitment(self, program_id, commitment_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/commitments/{commitment_id}/execute", payload, headers)

    def reduce_commitment(self, program_id, commitment_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/commitments/{commitment_id}/reduce", payload, headers)

    def cancel_commitment(self, program_id, commitment_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/commitments/{commitment_id}/cancel", {}, headers)

    # --- CapitalCall ---
    def create_capital_call(self, program_id, commitment_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/commitments/{commitment_id}/calls", payload, headers)

    def list_commitment_calls(self, program_id, commitment_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/commitments/{commitment_id}/calls", headers=headers, params=params)

    def list_commitment_calls_flat(self, commitment_id, headers, params=None):
        return self._request("GET", f"/fof/commitments/{commitment_id}/calls", headers=headers, params=params)

    def list_program_calls(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/calls", headers=headers, params=params)

    def get_call(self, call_id, headers):
        return self._request("GET", f"/fof/calls/{call_id}", headers=headers)

    def pay_call(self, call_id, headers):
        return self._request("POST", f"/fof/calls/{call_id}/pay", {}, headers)

    def cancel_call(self, call_id, headers):
        return self._request("POST", f"/fof/calls/{call_id}/cancel", {}, headers)

    # --- Distribution ---
    def create_distribution(self, program_id, commitment_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/commitments/{commitment_id}/distributions", payload, headers)

    def list_commitment_distributions(self, program_id, commitment_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/commitments/{commitment_id}/distributions", headers=headers, params=params)

    def list_commitment_distributions_flat(self, commitment_id, headers, params=None):
        return self._request("GET", f"/fof/commitments/{commitment_id}/distributions", headers=headers, params=params)

    def list_program_distributions(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/distributions", headers=headers, params=params)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/fof/distributions/{distribution_id}", headers=headers)

    def receive_distribution(self, distribution_id, headers):
        return self._request("POST", f"/fof/distributions/{distribution_id}/receive", {}, headers)

    def cancel_distribution(self, distribution_id, headers):
        return self._request("POST", f"/fof/distributions/{distribution_id}/cancel", {}, headers)

    # --- SecondaryBid ---
    def create_secondary_bid(self, program_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/secondary-bids", payload, headers)

    def list_secondary_bids(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/secondary-bids", headers=headers, params=params)

    def get_secondary_bid(self, program_id, bid_id, headers):
        return self._request("GET", f"/fof/programs/{program_id}/secondary-bids/{bid_id}", headers=headers)

    def counter_secondary_bid(self, program_id, bid_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/secondary-bids/{bid_id}/counter", {}, headers)

    def accept_secondary_bid(self, program_id, bid_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/secondary-bids/{bid_id}/accept", {}, headers)

    def settle_secondary_bid(self, program_id, bid_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/secondary-bids/{bid_id}/settle", payload, headers)

    def reject_secondary_bid(self, program_id, bid_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/secondary-bids/{bid_id}/reject", {}, headers)

    def withdraw_secondary_bid(self, program_id, bid_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/secondary-bids/{bid_id}/withdraw", {}, headers)

    def list_commitment_secondary_bids(self, commitment_id, headers, params=None):
        return self._request("GET", f"/fof/commitments/{commitment_id}/secondary-bids", headers=headers, params=params)

    # --- HoldingSnapshot / LookThroughLine ---
    def create_snapshot(self, commitment_id, payload, headers):
        return self._request("POST", f"/fof/commitments/{commitment_id}/snapshots", payload, headers)

    def list_commitment_snapshots(self, commitment_id, headers, params=None):
        return self._request("GET", f"/fof/commitments/{commitment_id}/snapshots", headers=headers, params=params)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/fof/snapshots/{snapshot_id}", headers=headers)

    def finalize_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/fof/snapshots/{snapshot_id}/finalize", {}, headers)

    def restate_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/fof/snapshots/{snapshot_id}/restate", {}, headers)

    def create_look_through_line(self, snapshot_id, payload, headers):
        return self._request("POST", f"/fof/snapshots/{snapshot_id}/look-through-lines", payload, headers)

    def list_look_through_lines(self, snapshot_id, headers, params=None):
        return self._request("GET", f"/fof/snapshots/{snapshot_id}/look-through-lines", headers=headers, params=params)

    def get_program_look_through(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/look-through", headers=headers, params=params)

    # --- ValuationReport ---
    def create_valuation_report(self, program_id, payload, headers):
        return self._request("POST", f"/fof/programs/{program_id}/valuation-reports", payload, headers)

    def list_valuation_reports(self, program_id, headers, params=None):
        return self._request("GET", f"/fof/programs/{program_id}/valuation-reports", headers=headers, params=params)

    def get_valuation_report(self, program_id, report_id, headers):
        return self._request("GET", f"/fof/programs/{program_id}/valuation-reports/{report_id}", headers=headers)

    def publish_valuation_report(self, program_id, report_id, headers):
        return self._request("POST", f"/fof/programs/{program_id}/valuation-reports/{report_id}/publish", {}, headers)

    # --- StaffUser directory ---
    def create_staff_user(self, payload, headers):
        return self._request("POST", "/fof/staff-users", payload, headers)

    def list_staff_users(self, headers, params=None):
        return self._request("GET", "/fof/staff-users", headers=headers, params=params)

    def get_staff_user(self, staff_user_id, headers):
        return self._request("GET", f"/fof/staff-users/{staff_user_id}", headers=headers)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/fof/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
