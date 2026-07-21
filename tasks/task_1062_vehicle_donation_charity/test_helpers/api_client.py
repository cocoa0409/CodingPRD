"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- charities ----------
    def create_charity(self, payload, headers):
        return self._request("POST", "/api/charities", payload, headers=headers)

    def get_charity(self, charity_id, headers):
        return self._request("GET", f"/api/charities/{charity_id}", headers=headers)

    def list_charities(self, headers, params=None):
        return self._request("GET", "/api/charities", headers=headers, params=params)

    def suspend_charity(self, charity_id, headers):
        return self._request("POST", f"/api/charities/{charity_id}/suspend", {}, headers=headers)

    # ---------- donors ----------
    def create_donor(self, payload, headers):
        return self._request("POST", "/api/donors", payload, headers=headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/api/donors/{donor_id}", headers=headers)

    def block_donor(self, donor_id, payload, headers):
        return self._request("POST", f"/api/donors/{donor_id}/block", payload, headers=headers)

    # ---------- tow vendors ----------
    def create_tow_vendor(self, payload, headers):
        return self._request("POST", "/api/tow-vendors", payload, headers=headers)

    def get_tow_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/tow-vendors/{vendor_id}", headers=headers)

    def suspend_tow_vendor(self, vendor_id, headers):
        return self._request("POST", f"/api/tow-vendors/{vendor_id}/suspend", {}, headers=headers)

    # ---------- venues ----------
    def create_venue(self, payload, headers):
        return self._request("POST", "/api/venues", payload, headers=headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/api/venues/{venue_id}", headers=headers)

    def suspend_venue(self, venue_id, headers):
        return self._request("POST", f"/api/venues/{venue_id}/suspend", {}, headers=headers)

    # ---------- logical clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ---------- donations ----------
    def create_donation(self, payload, headers):
        return self._request("POST", "/api/donations", payload, headers=headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/api/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/api/donations", headers=headers, params=params)

    def accept_donation(self, donation_id, headers):
        return self._request("POST", f"/api/donations/{donation_id}/accept", {}, headers=headers)

    def decline_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/api/donations/{donation_id}/decline", payload, headers=headers)

    def cancel_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/api/donations/{donation_id}/cancel", payload, headers=headers)

    def receive_dropoff(self, donation_id, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/receive-dropoff", {}, headers=headers
        )

    def reset_pickup(self, donation_id, payload, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/reset-pickup", payload, headers=headers
        )

    def withhold_payout(self, donation_id, payload, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/withhold-payout", payload, headers=headers
        )

    def record_exception(self, donation_id, payload, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/exception", payload, headers=headers
        )

    def list_donation_ledger_entries(self, donation_id, headers, params=None):
        return self._request(
            "GET", f"/api/donations/{donation_id}/ledger-entries", headers=headers, params=params
        )

    def list_donation_follow_up_tasks(self, donation_id, headers, params=None):
        return self._request(
            "GET", f"/api/donations/{donation_id}/follow-up-tasks", headers=headers, params=params
        )

    # ---------- vehicles ----------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/vehicles", payload, headers=headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/api/vehicles", headers=headers, params=params)

    def inspect_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/api/vehicles/{vehicle_id}", payload, headers=headers)

    # ---------- title records ----------
    def create_title_record(self, payload, headers):
        return self._request("POST", "/api/title-records", payload, headers=headers)

    def get_title_record(self, title_id, headers):
        return self._request("GET", f"/api/title-records/{title_id}", headers=headers)

    def list_title_records(self, headers, params=None):
        return self._request("GET", "/api/title-records", headers=headers, params=params)

    def submit_title_to_dmv(self, title_id, headers):
        return self._request("POST", f"/api/title-records/{title_id}/submit-dmv", {}, headers=headers)

    def record_dmv_decision(self, title_id, payload, headers):
        return self._request(
            "POST", f"/api/title-records/{title_id}/dmv-decision", payload, headers=headers
        )

    def resubmit_title(self, title_id, payload, headers):
        return self._request("POST", f"/api/title-records/{title_id}/resubmit", payload, headers=headers)

    def abandon_title(self, title_id, payload, headers):
        return self._request("POST", f"/api/title-records/{title_id}/abandon", payload, headers=headers)

    # ---------- pickup orders ----------
    def create_pickup_order(self, payload, headers):
        return self._request("POST", "/api/pickup-orders", payload, headers=headers)

    def get_pickup_order(self, pickup_id, headers):
        return self._request("GET", f"/api/pickup-orders/{pickup_id}", headers=headers)

    def list_pickup_orders(self, headers, params=None):
        return self._request("GET", "/api/pickup-orders", headers=headers, params=params)

    def complete_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/api/pickup-orders/{pickup_id}/complete", payload, headers=headers)

    def fail_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/api/pickup-orders/{pickup_id}/fail", payload, headers=headers)

    def cancel_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/api/pickup-orders/{pickup_id}/cancel", payload, headers=headers)

    # ---------- auction lots ----------
    def create_auction_lot(self, payload, headers):
        return self._request("POST", "/api/auction-lots", payload, headers=headers)

    def get_auction_lot(self, lot_id, headers):
        return self._request("GET", f"/api/auction-lots/{lot_id}", headers=headers)

    def list_auction_lots(self, headers, params=None):
        return self._request("GET", "/api/auction-lots", headers=headers, params=params)

    def record_sale(self, lot_id, payload, headers):
        return self._request("POST", f"/api/auction-lots/{lot_id}/record-sale", payload, headers=headers)

    def record_no_sale(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/api/auction-lots/{lot_id}/record-no-sale", payload, headers=headers
        )

    def relist_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/auction-lots/{lot_id}/relist", payload, headers=headers)

    def void_sale(self, lot_id, payload, headers):
        return self._request("POST", f"/api/auction-lots/{lot_id}/void-sale", payload, headers=headers)

    def withdraw_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/auction-lots/{lot_id}/withdraw", payload, headers=headers)

    # ---------- tax receipts ----------
    def create_tax_receipt(self, payload, headers):
        return self._request("POST", "/api/tax-receipts", payload, headers=headers)

    def get_tax_receipt(self, receipt_id, headers):
        return self._request("GET", f"/api/tax-receipts/{receipt_id}", headers=headers)

    def list_tax_receipts(self, headers, params=None):
        return self._request("GET", "/api/tax-receipts", headers=headers, params=params)

    def issue_receipt(self, receipt_id, headers):
        return self._request("POST", f"/api/tax-receipts/{receipt_id}/issue", {}, headers=headers)

    def void_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/api/tax-receipts/{receipt_id}/void", payload, headers=headers)

    def reissue_receipt(self, receipt_id, headers):
        return self._request("POST", f"/api/tax-receipts/{receipt_id}/reissue", {}, headers=headers)

    # ---------- remittance batches ----------
    def create_remittance_batch(self, payload, headers):
        return self._request("POST", "/api/remittance-batches", payload, headers=headers)

    def get_remittance_batch(self, batch_id, headers):
        return self._request("GET", f"/api/remittance-batches/{batch_id}", headers=headers)

    def list_remittance_batches(self, headers, params=None):
        return self._request("GET", "/api/remittance-batches", headers=headers, params=params)

    def list_batch_ledger_entries(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/api/remittance-batches/{batch_id}/ledger-entries", headers=headers, params=params
        )

    def close_batch(self, batch_id, headers):
        return self._request("POST", f"/api/remittance-batches/{batch_id}/close", {}, headers=headers)

    def pay_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/remittance-batches/{batch_id}/pay", payload, headers=headers
        )

    def dispute_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/remittance-batches/{batch_id}/dispute", payload, headers=headers
        )

    def reopen_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/remittance-batches/{batch_id}/reopen", payload, headers=headers
        )

    # ---------- follow-up tasks, ops, reports ----------
    def get_follow_up_task(self, task_id, headers):
        return self._request("GET", f"/api/follow-up-tasks/{task_id}", headers=headers)

    def complete_follow_up_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/api/follow-up-tasks/{task_id}/complete", payload, headers=headers
        )

    def run_sweep(self, headers):
        return self._request("POST", "/api/_ops/run-sweep", {}, headers=headers)

    def get_charity_summary(self, charity_id, headers):
        return self._request(
            "GET", "/api/reports/charity-summary", headers=headers, params={"charity_id": charity_id}
        )


api_client = ApiClient()
