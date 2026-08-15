"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ops / clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/caption-ad/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/caption-ad/_ops/run-sweep", {}, headers)

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/caption-ad/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/caption-ad/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/caption-ad/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/caption-ad/clients/{client_id}/suspend", {}, headers)

    def reactivate_client(self, client_id, headers):
        return self._request("POST", f"/caption-ad/clients/{client_id}/reactivate", {}, headers)

    # --- MediaAsset ---
    def create_media_asset(self, payload, headers):
        return self._request("POST", "/caption-ad/media-assets", payload, headers)

    def list_media_assets(self, headers, params=None):
        return self._request("GET", "/caption-ad/media-assets", headers=headers, params=params)

    def get_media_asset(self, media_asset_id, headers):
        return self._request("GET", f"/caption-ad/media-assets/{media_asset_id}", headers=headers)

    def begin_inspection(self, media_asset_id, headers):
        return self._request("POST", f"/caption-ad/media-assets/{media_asset_id}/begin-inspection", {}, headers)

    def clear_media(self, media_asset_id, headers):
        return self._request("POST", f"/caption-ad/media-assets/{media_asset_id}/clear", {}, headers)

    def reject_media(self, media_asset_id, headers, payload=None):
        return self._request("POST", f"/caption-ad/media-assets/{media_asset_id}/reject", payload or {}, headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/caption-ad/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/caption-ad/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/caption-ad/work-orders/{work_order_id}", headers=headers)

    def quote_work_order(self, work_order_id, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/quote", {}, headers)

    def confirm_work_order(self, work_order_id, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/confirm", {}, headers)

    def amend_work_order(self, work_order_id, payload, headers):
        return self._request("PATCH", f"/caption-ad/work-orders/{work_order_id}", payload, headers)

    def start_production(self, work_order_id, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/start-production", {}, headers)

    def deliver_work_order(self, work_order_id, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/deliver", {}, headers)

    def accept_delivery(self, work_order_id, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/accept-delivery", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/cancel", {}, headers)

    # --- CaptionTrack ---
    def create_caption_track(self, work_order_id, payload, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/caption-tracks", payload, headers)

    def list_caption_tracks(self, headers, params=None):
        return self._request("GET", "/caption-ad/caption-tracks", headers=headers, params=params)

    def get_caption_track(self, track_id, headers):
        return self._request("GET", f"/caption-ad/caption-tracks/{track_id}", headers=headers)

    def submit_review(self, track_id, headers):
        return self._request("POST", f"/caption-ad/caption-tracks/{track_id}/submit-review", {}, headers)

    def return_to_authoring(self, track_id, headers):
        return self._request("POST", f"/caption-ad/caption-tracks/{track_id}/return-to-authoring", {}, headers)

    def enqueue_qc(self, track_id, headers):
        return self._request("POST", f"/caption-ad/caption-tracks/{track_id}/enqueue-qc", {}, headers)

    def begin_rework(self, track_id, headers):
        return self._request("POST", f"/caption-ad/caption-tracks/{track_id}/begin-rework", {}, headers)

    def mark_conformed(self, track_id, headers):
        return self._request("POST", f"/caption-ad/caption-tracks/{track_id}/mark-conformed", {}, headers)

    # --- QCReview ---
    def create_qc_review(self, track_id, payload, headers):
        return self._request("POST", f"/caption-ad/caption-tracks/{track_id}/qc-reviews", payload, headers)

    def list_qc_reviews(self, headers, params=None):
        return self._request("GET", "/caption-ad/qc-reviews", headers=headers, params=params)

    def get_qc_review(self, qc_review_id, headers):
        return self._request("GET", f"/caption-ad/qc-reviews/{qc_review_id}", headers=headers)

    # --- AudioDescriptionTrack ---
    def create_ad_track(self, work_order_id, payload, headers):
        return self._request("POST", f"/caption-ad/work-orders/{work_order_id}/audio-description-tracks", payload, headers)

    def list_ad_tracks(self, headers, params=None):
        return self._request("GET", "/caption-ad/audio-description-tracks", headers=headers, params=params)

    def get_ad_track(self, ad_track_id, headers):
        return self._request("GET", f"/caption-ad/audio-description-tracks/{ad_track_id}", headers=headers)

    def patch_ad_track(self, ad_track_id, payload, headers):
        return self._request("PATCH", f"/caption-ad/audio-description-tracks/{ad_track_id}", payload, headers)

    def submit_script(self, ad_track_id, headers):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/submit-script", {}, headers)

    def approve_script(self, ad_track_id, headers):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/approve-script", {}, headers)

    def reject_script(self, ad_track_id, headers, payload=None):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/reject-script", payload or {}, headers)

    def book_studio(self, ad_track_id, payload, headers):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/book-studio", payload, headers)

    def submit_mix(self, ad_track_id, headers):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/submit-mix", {}, headers)

    def approve_mix(self, ad_track_id, headers):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/approve-mix", {}, headers)

    def reject_mix(self, ad_track_id, headers, payload=None):
        return self._request("POST", f"/caption-ad/audio-description-tracks/{ad_track_id}/reject-mix", payload or {}, headers)

    # --- LiveEvent ---
    def create_live_event(self, payload, headers):
        return self._request("POST", "/caption-ad/live-events", payload, headers)

    def list_live_events(self, headers, params=None):
        return self._request("GET", "/caption-ad/live-events", headers=headers, params=params)

    def get_live_event(self, live_event_id, headers):
        return self._request("GET", f"/caption-ad/live-events/{live_event_id}", headers=headers)

    def go_on_air(self, live_event_id, headers):
        return self._request("POST", f"/caption-ad/live-events/{live_event_id}/go-on-air", {}, headers)

    def wrap_event(self, live_event_id, headers):
        return self._request("POST", f"/caption-ad/live-events/{live_event_id}/wrap", {}, headers)

    def settle_event(self, live_event_id, headers):
        return self._request("POST", f"/caption-ad/live-events/{live_event_id}/settle", {}, headers)

    def cancel_event(self, live_event_id, headers):
        return self._request("POST", f"/caption-ad/live-events/{live_event_id}/cancel", {}, headers)

    # --- Stenographer ---
    def create_stenographer(self, payload, headers):
        return self._request("POST", "/caption-ad/stenographers", payload, headers)

    def list_stenographers(self, headers, params=None):
        return self._request("GET", "/caption-ad/stenographers", headers=headers, params=params)

    def get_stenographer(self, stenographer_id, headers):
        return self._request("GET", f"/caption-ad/stenographers/{stenographer_id}", headers=headers)

    def suspend_stenographer(self, stenographer_id, headers):
        return self._request("POST", f"/caption-ad/stenographers/{stenographer_id}/suspend", {}, headers)

    def reinstate_stenographer(self, stenographer_id, headers):
        return self._request("POST", f"/caption-ad/stenographers/{stenographer_id}/reinstate", {}, headers)

    def renew_certification(self, stenographer_id, payload, headers):
        return self._request("POST", f"/caption-ad/stenographers/{stenographer_id}/renew-certification", payload, headers)

    # --- LiveAssignment ---
    def create_assignment(self, live_event_id, payload, headers):
        return self._request("POST", f"/caption-ad/live-events/{live_event_id}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/caption-ad/live-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/caption-ad/live-assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/caption-ad/live-assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/caption-ad/live-assignments/{assignment_id}/decline", {}, headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/caption-ad/live-assignments/{assignment_id}/check-in", {}, headers)

    def preempt_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/caption-ad/live-assignments/{assignment_id}/preempt", payload, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/caption-ad/live-assignments/{assignment_id}/mark-no-show", {}, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/caption-ad/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/caption-ad/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/caption-ad/complaints/{complaint_id}", headers=headers)

    def triage_complaint(self, complaint_id, headers, payload=None):
        return self._request("POST", f"/caption-ad/complaints/{complaint_id}/triage", payload or {}, headers)

    def dismiss_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/caption-ad/complaints/{complaint_id}/dismiss", payload, headers)

    def begin_remediation(self, complaint_id, headers):
        return self._request("POST", f"/caption-ad/complaints/{complaint_id}/begin-remediation", {}, headers)

    def resolve_complaint(self, complaint_id, headers, payload=None):
        return self._request("POST", f"/caption-ad/complaints/{complaint_id}/resolve", payload or {}, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/caption-ad/complaints/{complaint_id}/reopen", {}, headers)

    # --- ConversionJob ---
    def create_conversion_job(self, payload, headers):
        return self._request("POST", "/caption-ad/conversion-jobs", payload, headers)

    def list_conversion_jobs(self, headers, params=None):
        return self._request("GET", "/caption-ad/conversion-jobs", headers=headers, params=params)

    def get_conversion_job(self, conversion_job_id, headers):
        return self._request("GET", f"/caption-ad/conversion-jobs/{conversion_job_id}", headers=headers)

    def run_conversion_job(self, conversion_job_id, payload, headers):
        return self._request("POST", f"/caption-ad/conversion-jobs/{conversion_job_id}/run", payload, headers)

    def retry_conversion_job(self, conversion_job_id, headers):
        return self._request("POST", f"/caption-ad/conversion-jobs/{conversion_job_id}/retry", {}, headers)

    def cancel_conversion_job(self, conversion_job_id, headers):
        return self._request("POST", f"/caption-ad/conversion-jobs/{conversion_job_id}/cancel", {}, headers)

    # --- ArchiveItem ---
    def list_archive_items(self, headers, params=None):
        return self._request("GET", "/caption-ad/archive-items", headers=headers, params=params)

    def get_archive_item(self, archive_item_id, headers):
        return self._request("GET", f"/caption-ad/archive-items/{archive_item_id}", headers=headers)

    def cold_store(self, archive_item_id, headers):
        return self._request("POST", f"/caption-ad/archive-items/{archive_item_id}/cold-store", {}, headers)

    def request_restore(self, archive_item_id, headers):
        return self._request("POST", f"/caption-ad/archive-items/{archive_item_id}/request-restore", {}, headers)

    def complete_restore(self, archive_item_id, headers):
        return self._request("POST", f"/caption-ad/archive-items/{archive_item_id}/complete-restore", {}, headers)

    def rearchive(self, archive_item_id, headers):
        return self._request("POST", f"/caption-ad/archive-items/{archive_item_id}/rearchive", {}, headers)

    def purge(self, archive_item_id, headers):
        return self._request("POST", f"/caption-ad/archive-items/{archive_item_id}/purge", {}, headers)

    def set_legal_hold(self, archive_item_id, payload, headers):
        return self._request("POST", f"/caption-ad/archive-items/{archive_item_id}/set-legal-hold", payload, headers)


api_client = ApiClient()
