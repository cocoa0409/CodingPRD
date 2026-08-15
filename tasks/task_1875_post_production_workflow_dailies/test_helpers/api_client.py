"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/post-production/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/post-production/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}", headers=headers)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/activate", headers=headers)

    def wrap_project(self, project_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/wrap", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/close", headers=headers)

    def archive_project(self, project_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive", headers=headers)

    # --- MediaBatch ---
    def create_batch(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/batches", payload, headers)

    def list_batches(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/batches", headers=headers, params=params)

    def get_batch(self, project_id, batch_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/batches/{batch_id}", headers=headers)

    def start_ingest(self, project_id, batch_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/batches/{batch_id}/start-ingest", headers=headers)

    def finish_ingest(self, project_id, batch_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/batches/{batch_id}/finish-ingest", headers=headers)

    def purge_batch(self, project_id, batch_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/batches/{batch_id}/purge", headers=headers)

    def get_batch_flat(self, batch_id, headers):
        return self._request("GET", f"/post-production/batches/{batch_id}", headers=headers)

    def list_batch_assets(self, batch_id, headers, params=None):
        return self._request("GET", f"/post-production/batches/{batch_id}/assets", headers=headers, params=params)

    def list_batch_dailies(self, batch_id, headers, params=None):
        return self._request("GET", f"/post-production/batches/{batch_id}/dailies", headers=headers, params=params)

    # --- MediaAsset ---
    def create_asset(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/assets", payload, headers)

    def list_assets(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/assets", headers=headers, params=params)

    def get_asset(self, project_id, asset_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/assets/{asset_id}", headers=headers)

    def proxy_complete(self, project_id, asset_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/assets/{asset_id}/proxy-complete", payload, headers)

    def verify_asset(self, project_id, asset_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/assets/{asset_id}/verify", headers=headers)

    def conform_asset(self, project_id, asset_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/assets/{asset_id}/conform", headers=headers)

    def lock_asset(self, project_id, asset_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/assets/{asset_id}/lock", headers=headers)

    def get_asset_flat(self, asset_id, headers):
        return self._request("GET", f"/post-production/assets/{asset_id}", headers=headers)

    def list_asset_qc_reports(self, asset_id, headers, params=None):
        return self._request("GET", f"/post-production/assets/{asset_id}/qc-reports", headers=headers, params=params)

    # --- WatermarkProfile ---
    def create_watermark_profile(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/watermark-profiles", payload, headers)

    def list_watermark_profiles(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/watermark-profiles", headers=headers, params=params)

    def activate_watermark_profile(self, project_id, profile_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/watermark-profiles/{profile_id}/activate", headers=headers)

    def retire_watermark_profile(self, project_id, profile_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/watermark-profiles/{profile_id}/retire", headers=headers)

    def get_watermark_profile_flat(self, profile_id, headers):
        return self._request("GET", f"/post-production/watermark-profiles/{profile_id}", headers=headers)

    def list_watermark_profile_dailies(self, profile_id, headers, params=None):
        return self._request("GET", f"/post-production/watermark-profiles/{profile_id}/dailies", headers=headers, params=params)

    # --- DailiesPackage ---
    def create_dailies_package(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/dailies", payload, headers)

    def list_dailies_packages(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/dailies", headers=headers, params=params)

    def get_dailies_package(self, project_id, package_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/dailies/{package_id}", headers=headers)

    def publish_dailies_package(self, project_id, package_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/dailies/{package_id}/publish", headers=headers)

    def revoke_dailies_package(self, project_id, package_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/dailies/{package_id}/revoke", headers=headers)

    # --- EditBay ---
    def create_bay(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bays", payload, headers)

    def list_bays(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/bays", headers=headers, params=params)

    def bay_maintenance(self, project_id, bay_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bays/{bay_id}/maintenance", headers=headers)

    def bay_release(self, project_id, bay_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bays/{bay_id}/release", headers=headers)

    def bay_decommission(self, project_id, bay_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bays/{bay_id}/decommission", headers=headers)

    def get_bay_flat(self, bay_id, headers):
        return self._request("GET", f"/post-production/bays/{bay_id}", headers=headers)

    def list_bay_bookings(self, bay_id, headers, params=None):
        return self._request("GET", f"/post-production/bays/{bay_id}/bookings", headers=headers, params=params)

    def get_bay_utilization(self, project_id, bay_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/bays/{bay_id}/utilization", headers=headers, params=params)

    # --- Booking ---
    def create_booking(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bookings", payload, headers)

    def list_bookings(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/bookings", headers=headers, params=params)

    def get_booking(self, project_id, booking_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/bookings/{booking_id}", headers=headers)

    def check_in_booking(self, project_id, booking_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bookings/{booking_id}/check-in", headers=headers)

    def complete_booking(self, project_id, booking_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bookings/{booking_id}/complete", headers=headers)

    def cancel_booking(self, project_id, booking_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/bookings/{booking_id}/cancel", headers=headers)

    def get_booking_flat(self, booking_id, headers):
        return self._request("GET", f"/post-production/bookings/{booking_id}", headers=headers)

    # --- TurnoverPackage ---
    def create_turnover(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers", payload, headers)

    def list_turnovers(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/turnovers", headers=headers, params=params)

    def get_turnover(self, project_id, turnover_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/turnovers/{turnover_id}", headers=headers)

    def stage_turnover(self, project_id, turnover_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers/{turnover_id}/stage", headers=headers)

    def issue_turnover(self, project_id, turnover_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers/{turnover_id}/issue", headers=headers)

    def ack_turnover(self, project_id, turnover_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers/{turnover_id}/ack", headers=headers)

    def return_turnover(self, project_id, turnover_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers/{turnover_id}/return", headers=headers)

    def close_turnover(self, project_id, turnover_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers/{turnover_id}/close", headers=headers)

    def void_turnover(self, project_id, turnover_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/turnovers/{turnover_id}/void", headers=headers)

    def get_turnover_flat(self, turnover_id, headers):
        return self._request("GET", f"/post-production/turnovers/{turnover_id}", headers=headers)

    def list_turnover_change_lists(self, turnover_id, headers, params=None):
        return self._request("GET", f"/post-production/turnovers/{turnover_id}/change-lists", headers=headers, params=params)

    def list_turnover_bids(self, turnover_id, headers, params=None):
        return self._request("GET", f"/post-production/turnovers/{turnover_id}/vendor-bids", headers=headers, params=params)

    # --- ChangeList ---
    def create_change_list(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/change-lists", payload, headers)

    def list_change_lists(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/change-lists", headers=headers, params=params)

    def apply_change_list(self, project_id, change_list_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/change-lists/{change_list_id}/apply", payload, headers)

    def reject_change_list(self, project_id, change_list_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/change-lists/{change_list_id}/reject", headers=headers)

    def get_change_list_flat(self, change_list_id, headers):
        return self._request("GET", f"/post-production/change-lists/{change_list_id}", headers=headers)

    # --- ReviewRound ---
    def create_review_round(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-rounds", payload, headers)

    def list_review_rounds(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/review-rounds", headers=headers, params=params)

    def get_review_round(self, project_id, round_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/review-rounds/{round_id}", headers=headers)

    def close_round_notes(self, project_id, round_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-rounds/{round_id}/close-notes", headers=headers)

    def approve_review_round(self, project_id, round_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-rounds/{round_id}/approve", headers=headers)

    def reject_review_round(self, project_id, round_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-rounds/{round_id}/reject", headers=headers)

    def get_review_round_flat(self, round_id, headers):
        return self._request("GET", f"/post-production/review-rounds/{round_id}", headers=headers)

    def list_round_notes(self, round_id, headers, params=None):
        return self._request("GET", f"/post-production/review-rounds/{round_id}/notes", headers=headers, params=params)

    # --- ReviewNote ---
    def create_review_note(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-notes", payload, headers)

    def list_review_notes(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/review-notes", headers=headers, params=params)

    def ack_review_note(self, project_id, note_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-notes/{note_id}/ack", headers=headers)

    def resolve_review_note(self, project_id, note_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/review-notes/{note_id}/resolve", headers=headers)

    def get_review_note_flat(self, note_id, headers):
        return self._request("GET", f"/post-production/review-notes/{note_id}", headers=headers)

    # --- Deliverable / QCReport ---
    def create_deliverable(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables", payload, headers)

    def list_deliverables(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/deliverables", headers=headers, params=params)

    def get_deliverable(self, project_id, deliverable_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}", headers=headers)

    def render_deliverable(self, project_id, deliverable_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/render", payload, headers)

    def render_complete_deliverable(self, project_id, deliverable_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/render-complete", headers=headers)

    def enqueue_qc(self, project_id, deliverable_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/enqueue-qc", headers=headers)

    def create_qc_report(self, project_id, deliverable_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/qc-reports", payload, headers)

    def list_deliverable_qc_reports(self, project_id, deliverable_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/qc-reports", headers=headers, params=params)

    def deliver_deliverable(self, project_id, deliverable_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/deliver", headers=headers)

    def reject_deliverable(self, project_id, deliverable_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/deliverables/{deliverable_id}/reject", headers=headers)

    def get_deliverable_flat(self, deliverable_id, headers):
        return self._request("GET", f"/post-production/deliverables/{deliverable_id}", headers=headers)

    def get_qc_report_flat(self, qc_report_id, headers):
        return self._request("GET", f"/post-production/qc-reports/{qc_report_id}", headers=headers)

    # --- ArchiveJob ---
    def create_archive_job(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive-jobs", payload, headers)

    def list_archive_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/archive-jobs", headers=headers, params=params)

    def get_archive_job(self, project_id, job_id, headers):
        return self._request("GET", f"/post-production/projects/{project_id}/archive-jobs/{job_id}", headers=headers)

    def start_archive_job(self, project_id, job_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive-jobs/{job_id}/start", headers=headers)

    def verify_archive_job(self, project_id, job_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive-jobs/{job_id}/verify", headers=headers)

    def seal_archive_job(self, project_id, job_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive-jobs/{job_id}/seal", headers=headers)

    def cancel_archive_job(self, project_id, job_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive-jobs/{job_id}/cancel", headers=headers)

    def retry_archive_job(self, project_id, job_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/archive-jobs/{job_id}/retry", headers=headers)

    def get_archive_job_flat(self, job_id, headers):
        return self._request("GET", f"/post-production/archive-jobs/{job_id}", headers=headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/post-production/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/post-production/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/post-production/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/post-production/vendors/{vendor_id}/suspend", headers=headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/post-production/vendors/{vendor_id}/reinstate", headers=headers)

    def offboard_vendor(self, vendor_id, headers):
        return self._request("POST", f"/post-production/vendors/{vendor_id}/offboard", headers=headers)

    def get_vendor_load(self, vendor_id, headers):
        return self._request("GET", f"/post-production/vendors/{vendor_id}/load", headers=headers)

    def list_vendor_turnovers(self, vendor_id, headers, params=None):
        return self._request("GET", f"/post-production/vendors/{vendor_id}/turnovers", headers=headers, params=params)

    def list_vendor_bids(self, vendor_id, headers, params=None):
        return self._request("GET", f"/post-production/vendors/{vendor_id}/bids", headers=headers, params=params)

    # --- VendorBid ---
    def create_vendor_bid(self, project_id, payload, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/vendor-bids", payload, headers)

    def list_project_vendor_bids(self, project_id, headers, params=None):
        return self._request("GET", f"/post-production/projects/{project_id}/vendor-bids", headers=headers, params=params)

    def award_bid(self, project_id, bid_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/vendor-bids/{bid_id}/award", headers=headers)

    def withdraw_bid(self, project_id, bid_id, headers):
        return self._request("POST", f"/post-production/projects/{project_id}/vendor-bids/{bid_id}/withdraw", headers=headers)

    def get_vendor_bid_flat(self, bid_id, headers):
        return self._request("GET", f"/post-production/vendor-bids/{bid_id}", headers=headers)


api_client = ApiClient()
