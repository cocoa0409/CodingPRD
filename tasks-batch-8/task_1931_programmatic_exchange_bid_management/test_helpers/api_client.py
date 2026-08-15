"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Publishers
    # ------------------------------------------------------------------
    def create_publisher(self, payload, headers):
        return self._request("POST", "/publishers", payload, headers)

    def list_publishers(self, headers, params=None):
        return self._request("GET", "/publishers", headers=headers, params=params)

    def get_publisher(self, publisher_id, headers):
        return self._request("GET", f"/publishers/{publisher_id}", headers=headers)

    def suspend_publisher(self, publisher_id, headers):
        return self._request("POST", f"/publishers/{publisher_id}/suspend", {}, headers)

    def resume_publisher(self, publisher_id, headers):
        return self._request("POST", f"/publishers/{publisher_id}/resume", {}, headers)

    def list_publisher_payout_lines(self, publisher_id, headers, params=None):
        return self._request("GET", f"/publishers/{publisher_id}/payout-lines",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inventory packages
    # ------------------------------------------------------------------
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def update_package(self, package_id, payload, headers):
        return self._request("PUT", f"/packages/{package_id}", payload, headers)

    def pause_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/pause", {}, headers)

    def resume_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/resume", {}, headers)

    def get_package_fee_report(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}/fee-report",
                             headers=headers)

    # ------------------------------------------------------------------
    # Seasonal pricing windows
    # ------------------------------------------------------------------
    def create_seasonal_window(self, payload, headers):
        return self._request("POST", "/seasonal-windows", payload, headers)

    def list_seasonal_windows(self, headers, params=None):
        return self._request("GET", "/seasonal-windows", headers=headers, params=params)

    def get_seasonal_window(self, window_id, headers):
        return self._request("GET", f"/seasonal-windows/{window_id}", headers=headers)

    def delete_seasonal_window(self, window_id, headers):
        return self._request("DELETE", f"/seasonal-windows/{window_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Demand partners
    # ------------------------------------------------------------------
    def create_demand_partner(self, payload, headers):
        return self._request("POST", "/demand-partners", payload, headers)

    def list_demand_partners(self, headers, params=None):
        return self._request("GET", "/demand-partners", headers=headers, params=params)

    def get_demand_partner(self, demand_partner_id, headers):
        return self._request("GET", f"/demand-partners/{demand_partner_id}",
                             headers=headers)

    def update_demand_partner(self, demand_partner_id, payload, headers):
        return self._request("PUT", f"/demand-partners/{demand_partner_id}",
                             payload, headers)

    def suspend_demand_partner(self, demand_partner_id, headers):
        return self._request("POST", f"/demand-partners/{demand_partner_id}/suspend",
                             {}, headers)

    def reactivate_demand_partner(self, demand_partner_id, headers):
        return self._request("POST", f"/demand-partners/{demand_partner_id}/reactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Deals
    # ------------------------------------------------------------------
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def update_deal(self, deal_id, payload, headers):
        return self._request("PUT", f"/deals/{deal_id}", payload, headers)

    def submit_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/submit", {}, headers)

    def approve_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/approve", {}, headers)

    def reject_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/reject", {}, headers)

    def renegotiate_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/renegotiate", {}, headers)

    def pause_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/pause", {}, headers)

    def resume_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/resume", {}, headers)

    def list_deal_records(self, deal_id, headers, params=None):
        return self._request("GET", f"/deals/{deal_id}/records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Supply chain nodes
    # ------------------------------------------------------------------
    def create_supply_chain_node(self, payload, headers):
        return self._request("POST", "/supply-chain-nodes", payload, headers)

    def list_supply_chain_nodes(self, headers, params=None):
        return self._request("GET", "/supply-chain-nodes", headers=headers,
                             params=params)

    def get_supply_chain_node(self, node_id, headers):
        return self._request("GET", f"/supply-chain-nodes/{node_id}", headers=headers)

    # ------------------------------------------------------------------
    # Blocklist entries
    # ------------------------------------------------------------------
    def create_blocklist_entry(self, payload, headers):
        return self._request("POST", "/blocklist-entries", payload, headers)

    def list_blocklist_entries(self, headers, params=None):
        return self._request("GET", "/blocklist-entries", headers=headers,
                             params=params)

    def get_blocklist_entry(self, entry_id, headers):
        return self._request("GET", f"/blocklist-entries/{entry_id}", headers=headers)

    def lift_blocklist_entry(self, entry_id, headers):
        return self._request("POST", f"/blocklist-entries/{entry_id}/lift",
                             {}, headers)

    # ------------------------------------------------------------------
    # Auctions and auction records
    # ------------------------------------------------------------------
    def execute_auction(self, payload, headers):
        return self._request("POST", "/auctions/execute", payload, headers)

    def list_auction_records(self, headers, params=None):
        return self._request("GET", "/auction-records", headers=headers, params=params)

    def get_auction_record(self, record_id, headers):
        return self._request("GET", f"/auction-records/{record_id}", headers=headers)

    def confirm_billing(self, record_id, headers):
        return self._request("POST", f"/auction-records/{record_id}/confirm-billing",
                             {}, headers)

    def void_auction_record(self, record_id, headers):
        return self._request("POST", f"/auction-records/{record_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Reconciliation reports
    # ------------------------------------------------------------------
    def create_reconciliation_report(self, payload, headers):
        return self._request("POST", "/reconciliation-reports", payload, headers)

    def list_reconciliation_reports(self, headers, params=None):
        return self._request("GET", "/reconciliation-reports", headers=headers,
                             params=params)

    def get_reconciliation_report(self, report_id, headers):
        return self._request("GET", f"/reconciliation-reports/{report_id}",
                             headers=headers)

    def acknowledge_report(self, report_id, headers):
        return self._request("POST", f"/reconciliation-reports/{report_id}/acknowledge",
                             {}, headers)

    def dispute_report(self, report_id, headers):
        return self._request("POST", f"/reconciliation-reports/{report_id}/dispute",
                             {}, headers)

    def resolve_report(self, report_id, payload, headers):
        return self._request("POST", f"/reconciliation-reports/{report_id}/resolve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Payout batches and lines
    # ------------------------------------------------------------------
    def create_payout_batch(self, payload, headers):
        return self._request("POST", "/payout-batches", payload, headers)

    def list_payout_batches(self, headers, params=None):
        return self._request("GET", "/payout-batches", headers=headers, params=params)

    def get_payout_batch(self, batch_id, headers):
        return self._request("GET", f"/payout-batches/{batch_id}", headers=headers)

    def submit_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/payout-batches/{batch_id}/submit", {}, headers)

    def approve_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/payout-batches/{batch_id}/approve", {}, headers)

    def reject_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/payout-batches/{batch_id}/reject", {}, headers)

    def release_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/payout-batches/{batch_id}/release", {}, headers)

    def list_batch_lines(self, batch_id, headers, params=None):
        return self._request("GET", f"/payout-batches/{batch_id}/lines",
                             headers=headers, params=params)

    def hold_payout_line(self, batch_id, line_id, headers):
        return self._request(
            "POST", f"/payout-batches/{batch_id}/lines/{line_id}/hold", {}, headers)

    def release_hold_payout_line(self, batch_id, line_id, headers):
        return self._request(
            "POST", f"/payout-batches/{batch_id}/lines/{line_id}/release-hold",
            {}, headers)

    def write_off_payout_line(self, batch_id, line_id, payload, headers):
        return self._request(
            "POST", f"/payout-batches/{batch_id}/lines/{line_id}/write-off",
            payload, headers)


api_client = ApiClient()
