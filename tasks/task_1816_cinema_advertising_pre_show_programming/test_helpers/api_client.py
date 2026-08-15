"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/network/_clock/set_current_utc", payload, headers)

    # --- Theaters / screens / features / showtimes ---
    def create_theater(self, payload, headers):
        return self._request("POST", "/network/theaters", payload, headers)

    def get_theater(self, theater_id, headers):
        return self._request("GET", f"/network/theaters/{theater_id}", headers=headers)

    def create_screen(self, theater_id, payload, headers):
        return self._request("POST", f"/network/theaters/{theater_id}/screens", payload, headers)

    def get_screen(self, screen_id, headers):
        return self._request("GET", f"/network/screens/{screen_id}", headers=headers)

    def list_screens(self, theater_id, headers, params=None):
        return self._request("GET", f"/network/theaters/{theater_id}/screens", headers=headers, params=params)

    def create_feature(self, payload, headers):
        return self._request("POST", "/network/features", payload, headers)

    def get_feature(self, feature_id, headers):
        return self._request("GET", f"/network/features/{feature_id}", headers=headers)

    def create_showtime(self, screen_id, payload, headers):
        return self._request("POST", f"/network/screens/{screen_id}/showtimes", payload, headers)

    def get_showtime(self, showtime_id, headers):
        return self._request("GET", f"/network/showtimes/{showtime_id}", headers=headers)

    def list_showtimes(self, headers, params=None):
        return self._request("GET", "/network/showtimes", headers=headers, params=params)

    def get_showtime_reel(self, showtime_id, headers):
        return self._request("GET", f"/network/showtimes/{showtime_id}/reel", headers=headers)

    def get_reel(self, reel_id, headers):
        return self._request("GET", f"/network/reels/{reel_id}", headers=headers)

    # --- Advertisers & campaigns ---
    def create_advertiser(self, payload, headers):
        return self._request("POST", "/network/advertisers", payload, headers)

    def get_advertiser(self, advertiser_id, headers):
        return self._request("GET", f"/network/advertisers/{advertiser_id}", headers=headers)

    def create_campaign(self, payload, headers):
        return self._request("POST", "/network/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/network/campaigns/{campaign_id}", headers=headers)

    def list_advertiser_campaigns(self, advertiser_id, headers, params=None):
        return self._request("GET", f"/network/advertisers/{advertiser_id}/campaigns", headers=headers, params=params)

    def patch_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/network/campaigns/{campaign_id}", payload, headers)

    def submit_campaign(self, campaign_id, headers):
        return self._request("POST", f"/network/campaigns/{campaign_id}/submit", headers=headers)

    def approve_campaign(self, campaign_id, headers):
        return self._request("POST", f"/network/campaigns/{campaign_id}/approve", headers=headers)

    def reject_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/network/campaigns/{campaign_id}/reject", payload, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/network/campaigns/{campaign_id}/cancel", headers=headers)

    def complete_campaign(self, campaign_id, headers):
        return self._request("POST", f"/network/campaigns/{campaign_id}/complete", headers=headers)

    # --- Reel slots & reel lifecycle ---
    def create_slot(self, reel_id, payload, headers):
        return self._request("POST", f"/network/reels/{reel_id}/slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/network/slots/{slot_id}", headers=headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/network/slots", headers=headers, params=params)

    def cancel_slot(self, slot_id, headers):
        return self._request("POST", f"/network/slots/{slot_id}/cancel", headers=headers)

    def lock_reel(self, reel_id, payload, headers):
        return self._request("POST", f"/network/reels/{reel_id}/lock", payload, headers)

    def dispatch_reel(self, reel_id, headers):
        return self._request("POST", f"/network/reels/{reel_id}/dispatch", headers=headers)

    def acknowledge_delivery(self, reel_id, payload, headers):
        return self._request("POST", f"/network/reels/{reel_id}/acknowledge-delivery", payload, headers)

    def reconcile_reel(self, reel_id, headers):
        return self._request("POST", f"/network/reels/{reel_id}/reconcile", headers=headers)

    # --- Playback verification & attendance ---
    def create_playlog(self, slot_id, payload, headers):
        return self._request("POST", f"/network/slots/{slot_id}/playlogs", payload, headers)

    def list_playlogs(self, slot_id, headers, params=None):
        return self._request("GET", f"/network/slots/{slot_id}/playlogs", headers=headers, params=params)

    def create_attendance_report(self, showtime_id, payload, headers):
        return self._request("POST", f"/network/showtimes/{showtime_id}/attendance-reports", payload, headers)

    def list_attendance_reports(self, showtime_id, headers, params=None):
        return self._request("GET", f"/network/showtimes/{showtime_id}/attendance-reports", headers=headers, params=params)

    def review_attendance_report(self, report_id, payload, headers):
        return self._request("POST", f"/network/attendance-reports/{report_id}/review", payload, headers)

    def resubmit_attendance_report(self, report_id, payload, headers):
        return self._request("POST", f"/network/attendance-reports/{report_id}/resubmit", payload, headers)

    def audit_attendance_report(self, report_id, payload, headers):
        return self._request("POST", f"/network/attendance-reports/{report_id}/audit", payload, headers)

    # --- Billing: invoices & make-goods ---
    def create_invoice(self, campaign_id, payload, headers):
        return self._request("POST", f"/network/campaigns/{campaign_id}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/network/invoices/{invoice_id}", headers=headers)

    def list_campaign_invoices(self, campaign_id, headers, params=None):
        return self._request("GET", f"/network/campaigns/{campaign_id}/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/network/invoices/{invoice_id}/issue", headers=headers)

    def certify_invoice(self, invoice_id, headers):
        return self._request("POST", f"/network/invoices/{invoice_id}/certify", headers=headers)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"/network/invoices/{invoice_id}/settle", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/network/invoices/{invoice_id}/void", headers=headers)

    def create_make_good(self, invoice_id, headers):
        return self._request("POST", f"/network/invoices/{invoice_id}/make-goods", headers=headers)

    def list_make_goods(self, invoice_id, headers, params=None):
        return self._request("GET", f"/network/invoices/{invoice_id}/make-goods", headers=headers, params=params)

    def review_make_good(self, make_good_id, payload, headers):
        return self._request("POST", f"/network/make-goods/{make_good_id}/review", payload, headers)

    def apply_make_good(self, make_good_id, payload, headers):
        return self._request("POST", f"/network/make-goods/{make_good_id}/apply", payload, headers)


api_client = ApiClient()
