"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Label ---
    def create_label(self, payload, headers):
        return self._request("POST", "/api/labels", payload, headers)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/api/labels/{label_id}", headers=headers)

    def sweep_label(self, label_id, headers):
        return self._request("POST", f"/api/labels/{label_id}/ops/sweep", {}, headers)

    # --- Artist ---
    def create_artist(self, payload, headers):
        return self._request("POST", "/api/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/api/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/api/artists", headers=headers, params=params)

    def hiatus_artist(self, artist_id, headers):
        return self._request("POST", f"/api/artists/{artist_id}/hiatus", {}, headers)

    def reactivate_artist(self, artist_id, headers):
        return self._request("POST", f"/api/artists/{artist_id}/reactivate", {}, headers)

    def drop_artist(self, artist_id, headers):
        return self._request("POST", f"/api/artists/{artist_id}/drop", {}, headers)

    # --- DealMemo ---
    def create_deal_memo(self, artist_id, payload, headers):
        return self._request("POST", f"/api/artists/{artist_id}/deal-memos", payload, headers)

    def get_deal_memo(self, memo_id, headers):
        return self._request("GET", f"/api/deal-memos/{memo_id}", headers=headers)

    def list_artist_deal_memos(self, artist_id, headers, params=None):
        return self._request("GET", f"/api/artists/{artist_id}/deal-memos", headers=headers, params=params)

    def list_deal_memos(self, headers, params=None):
        return self._request("GET", "/api/deal-memos", headers=headers, params=params)

    def propose_deal_memo(self, memo_id, headers):
        return self._request("POST", f"/api/deal-memos/{memo_id}/propose", {}, headers)

    def counter_deal_memo(self, memo_id, payload, headers):
        return self._request("POST", f"/api/deal-memos/{memo_id}/counter", payload, headers)

    def approve_deal_memo(self, memo_id, headers):
        return self._request("POST", f"/api/deal-memos/{memo_id}/approve", {}, headers)

    def execute_deal_memo(self, memo_id, headers):
        return self._request("POST", f"/api/deal-memos/{memo_id}/execute", {}, headers)

    def reject_deal_memo(self, memo_id, headers):
        return self._request("POST", f"/api/deal-memos/{memo_id}/reject", {}, headers)

    # --- Contract / RecoupmentAccount ---
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def disburse_advance(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/disburse-advance", {}, headers)

    def exercise_option(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/exercise-option", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/terminate", payload, headers)

    def list_contract_recoupment_accounts(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}/recoupment-accounts", headers=headers)

    def get_recoupment_account(self, account_id, headers):
        return self._request("GET", f"/api/recoupment-accounts/{account_id}", headers=headers)

    # --- RecordingProject ---
    def create_recording_project(self, contract_id, payload, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/recording-projects", payload, headers)

    def get_recording_project(self, project_id, headers):
        return self._request("GET", f"/api/recording-projects/{project_id}", headers=headers)

    def list_contract_recording_projects(self, contract_id, headers, params=None):
        return self._request("GET", f"/api/contracts/{contract_id}/recording-projects", headers=headers, params=params)

    def amend_project_budget(self, project_id, payload, headers):
        return self._request("POST", f"/api/recording-projects/{project_id}/amend-budget", payload, headers)

    def start_project(self, project_id, headers):
        return self._request("POST", f"/api/recording-projects/{project_id}/start", {}, headers)

    def advance_project_stage(self, project_id, headers):
        return self._request("POST", f"/api/recording-projects/{project_id}/advance-stage", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/api/recording-projects/{project_id}/cancel", {}, headers)

    # --- RecordingMilestone ---
    def create_milestone(self, project_id, payload, headers):
        return self._request("POST", f"/api/recording-projects/{project_id}/milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/api/milestones/{milestone_id}", headers=headers)

    def list_project_milestones(self, project_id, headers, params=None):
        return self._request("GET", f"/api/recording-projects/{project_id}/milestones", headers=headers, params=params)

    def submit_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/api/milestones/{milestone_id}/submit", payload, headers)

    def approve_milestone(self, milestone_id, headers):
        return self._request("POST", f"/api/milestones/{milestone_id}/approve", {}, headers)

    def reject_milestone(self, milestone_id, headers):
        return self._request("POST", f"/api/milestones/{milestone_id}/reject", {}, headers)

    def pay_milestone(self, milestone_id, headers):
        return self._request("POST", f"/api/milestones/{milestone_id}/pay", {}, headers)

    # --- Track ---
    def create_track(self, project_id, payload, headers):
        return self._request("POST", f"/api/recording-projects/{project_id}/tracks", payload, headers)

    def get_track(self, track_id, headers):
        return self._request("GET", f"/api/tracks/{track_id}", headers=headers)

    def list_project_tracks(self, project_id, headers, params=None):
        return self._request("GET", f"/api/recording-projects/{project_id}/tracks", headers=headers, params=params)

    def list_tracks(self, headers, params=None):
        return self._request("GET", "/api/tracks", headers=headers, params=params)

    def advance_track_stage(self, track_id, headers):
        return self._request("POST", f"/api/tracks/{track_id}/advance-stage", {}, headers)

    def block_track(self, track_id, headers):
        return self._request("POST", f"/api/tracks/{track_id}/block", {}, headers)

    def rework_track(self, track_id, headers):
        return self._request("POST", f"/api/tracks/{track_id}/rework", {}, headers)

    # --- Release ---
    def create_release(self, contract_id, payload, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/api/releases/{release_id}", headers=headers)

    def list_contract_releases(self, contract_id, headers, params=None):
        return self._request("GET", f"/api/contracts/{contract_id}/releases", headers=headers, params=params)

    def list_project_releases(self, project_id, headers, params=None):
        return self._request("GET", f"/api/recording-projects/{project_id}/releases", headers=headers, params=params)

    def assemble_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/assemble", {}, headers)

    def lock_release_assets(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/lock-assets", payload, headers)

    def schedule_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/schedule", {}, headers)

    def create_release_deliveries(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/deliveries", payload, headers)

    def go_live_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/go-live", {}, headers)

    def takedown_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/takedown", {}, headers)

    def relaunch_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/relaunch", {}, headers)

    def cancel_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/cancel", {}, headers)

    # --- AssetDelivery ---
    def get_asset_delivery(self, delivery_id, headers):
        return self._request("GET", f"/api/asset-deliveries/{delivery_id}", headers=headers)

    def list_release_deliveries(self, release_id, headers, params=None):
        return self._request("GET", f"/api/releases/{release_id}/deliveries", headers=headers, params=params)

    def list_asset_deliveries(self, headers, params=None):
        return self._request("GET", "/api/asset-deliveries", headers=headers, params=params)

    def transmit_delivery(self, delivery_id, headers):
        return self._request("POST", f"/api/asset-deliveries/{delivery_id}/transmit", {}, headers)

    def acknowledge_delivery(self, delivery_id, headers):
        return self._request("POST", f"/api/asset-deliveries/{delivery_id}/acknowledge", {}, headers)

    def reject_delivery(self, delivery_id, headers):
        return self._request("POST", f"/api/asset-deliveries/{delivery_id}/reject", {}, headers)

    def retry_delivery(self, delivery_id, headers):
        return self._request("POST", f"/api/asset-deliveries/{delivery_id}/retry", {}, headers)

    # --- Distributor ---
    def create_distributor(self, payload, headers):
        return self._request("POST", "/api/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/api/distributors/{distributor_id}", headers=headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", "/api/distributors", headers=headers, params=params)

    def update_distributor(self, distributor_id, payload, headers):
        return self._request("PATCH", f"/api/distributors/{distributor_id}", payload, headers)

    # --- MarketingBeat ---
    def create_beat(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/beats", payload, headers)

    def get_beat(self, beat_id, headers):
        return self._request("GET", f"/api/beats/{beat_id}", headers=headers)

    def list_release_beats(self, release_id, headers, params=None):
        return self._request("GET", f"/api/releases/{release_id}/beats", headers=headers, params=params)

    def ready_beat(self, beat_id, headers):
        return self._request("POST", f"/api/beats/{beat_id}/ready", {}, headers)

    def execute_beat(self, beat_id, headers):
        return self._request("POST", f"/api/beats/{beat_id}/execute", {}, headers)

    def measure_beat(self, beat_id, payload, headers):
        return self._request("POST", f"/api/beats/{beat_id}/measure", payload, headers)

    def skip_beat(self, beat_id, headers):
        return self._request("POST", f"/api/beats/{beat_id}/skip", {}, headers)

    # --- PromoCampaign ---
    def create_promo_campaign(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/promo-campaigns", payload, headers)

    def get_promo_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/promo-campaigns/{campaign_id}", headers=headers)

    def list_release_promo_campaigns(self, release_id, headers, params=None):
        return self._request("GET", f"/api/releases/{release_id}/promo-campaigns", headers=headers, params=params)

    def activate_promo_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/promo-campaigns/{campaign_id}/activate", {}, headers)

    def pause_promo_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/promo-campaigns/{campaign_id}/pause", {}, headers)

    def resume_promo_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/promo-campaigns/{campaign_id}/resume", {}, headers)

    def complete_promo_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/promo-campaigns/{campaign_id}/complete", {}, headers)

    def kill_promo_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/promo-campaigns/{campaign_id}/kill", {}, headers)

    def spend_promo_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/api/promo-campaigns/{campaign_id}/spend", payload, headers)

    # --- TourSupport / TourExpense ---
    def create_tour_support(self, contract_id, payload, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/tour-supports", payload, headers)

    def get_tour_support(self, tour_support_id, headers):
        return self._request("GET", f"/api/tour-supports/{tour_support_id}", headers=headers)

    def list_contract_tour_supports(self, contract_id, headers, params=None):
        return self._request("GET", f"/api/contracts/{contract_id}/tour-supports", headers=headers, params=params)

    def approve_tour_support(self, tour_support_id, payload, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/approve", payload, headers)

    def decline_tour_support(self, tour_support_id, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/decline", {}, headers)

    def advance_funds_tour_support(self, tour_support_id, payload, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/advance-funds", payload, headers)

    def reconcile_tour_support(self, tour_support_id, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/reconcile", {}, headers)

    def close_tour_support(self, tour_support_id, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/close", {}, headers)

    def cancel_tour_support(self, tour_support_id, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/cancel", {}, headers)

    def create_tour_expense(self, tour_support_id, payload, headers):
        return self._request("POST", f"/api/tour-supports/{tour_support_id}/expenses", payload, headers)

    def get_tour_expense(self, expense_id, headers):
        return self._request("GET", f"/api/tour-expenses/{expense_id}", headers=headers)

    def list_tour_expenses(self, tour_support_id, headers, params=None):
        return self._request("GET", f"/api/tour-supports/{tour_support_id}/expenses", headers=headers, params=params)

    def approve_tour_expense(self, expense_id, headers):
        return self._request("POST", f"/api/tour-expenses/{expense_id}/approve", {}, headers)

    def reject_tour_expense(self, expense_id, headers):
        return self._request("POST", f"/api/tour-expenses/{expense_id}/reject", {}, headers)

    def void_tour_expense(self, expense_id, headers):
        return self._request("POST", f"/api/tour-expenses/{expense_id}/void", {}, headers)

    # --- RevenueReport / RoyaltyRun / RoyaltyStatement ---
    def create_revenue_report(self, payload, headers):
        return self._request("POST", "/api/revenue-reports", payload, headers)

    def get_revenue_report(self, report_id, headers):
        return self._request("GET", f"/api/revenue-reports/{report_id}", headers=headers)

    def list_revenue_reports(self, headers, params=None):
        return self._request("GET", "/api/revenue-reports", headers=headers, params=params)

    def create_royalty_run(self, payload, headers):
        return self._request("POST", "/api/royalty-runs", payload, headers)

    def get_royalty_run(self, run_id, headers):
        return self._request("GET", f"/api/royalty-runs/{run_id}", headers=headers)

    def list_royalty_runs(self, headers, params=None):
        return self._request("GET", "/api/royalty-runs", headers=headers, params=params)

    def close_royalty_run(self, run_id, headers):
        return self._request("POST", f"/api/royalty-runs/{run_id}/close", {}, headers)

    def calculate_royalty_run(self, run_id, headers):
        return self._request("POST", f"/api/royalty-runs/{run_id}/calculate", {}, headers)

    def finalize_royalty_run(self, run_id, headers):
        return self._request("POST", f"/api/royalty-runs/{run_id}/finalize", {}, headers)

    def mark_paid_royalty_run(self, run_id, headers):
        return self._request("POST", f"/api/royalty-runs/{run_id}/mark-paid", {}, headers)

    def list_run_statements(self, run_id, headers, params=None):
        return self._request("GET", f"/api/royalty-runs/{run_id}/statements", headers=headers, params=params)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/api/royalty-statements/{statement_id}", headers=headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/api/royalty-statements", headers=headers, params=params)

    def dispute_royalty_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/api/royalty-statements/{statement_id}/dispute", payload, headers)

    def adjust_royalty_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/api/royalty-statements/{statement_id}/adjust", payload, headers)

    def resolve_dispute_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/api/royalty-statements/{statement_id}/resolve-dispute", {}, headers)

    def pay_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/api/royalty-statements/{statement_id}/pay", {}, headers)


api_client = ApiClient()
