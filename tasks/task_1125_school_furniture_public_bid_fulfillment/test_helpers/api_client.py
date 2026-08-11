"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- District ---
    def create_district(self, payload, headers):
        return self._request("POST", "/v1/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/v1/districts/{district_id}", headers=headers)

    # --- SchoolSite ---
    def create_school_site(self, payload, headers):
        return self._request("POST", "/v1/school-sites", payload, headers)

    def get_school_site(self, site_id, headers):
        return self._request("GET", f"/v1/school-sites/{site_id}", headers=headers)

    def list_school_sites(self, headers, params=None):
        return self._request("GET", "/v1/school-sites", headers=headers, params=params)

    # --- BidSpec ---
    def create_bid_spec(self, payload, headers):
        return self._request("POST", "/v1/bid-specs", payload, headers)

    def get_bid_spec(self, spec_id, headers):
        return self._request("GET", f"/v1/bid-specs/{spec_id}", headers=headers)

    def list_bid_specs(self, headers, params=None):
        return self._request("GET", "/v1/bid-specs", headers=headers, params=params)

    def publish_bid_spec(self, spec_id, headers):
        return self._request("POST", f"/v1/bid-specs/{spec_id}/publish", headers=headers)

    def issue_addendum(self, spec_id, payload, headers):
        return self._request("POST", f"/v1/bid-specs/{spec_id}/issue-addendum", payload, headers)

    def close_bid_spec(self, spec_id, headers):
        return self._request("POST", f"/v1/bid-specs/{spec_id}/close", headers=headers)

    # --- SpecLine ---
    def create_spec_line(self, payload, headers):
        return self._request("POST", "/v1/spec-lines", payload, headers)

    def get_spec_line(self, line_id, headers):
        return self._request("GET", f"/v1/spec-lines/{line_id}", headers=headers)

    def list_spec_lines(self, headers, params=None):
        return self._request("GET", "/v1/spec-lines", headers=headers, params=params)

    # --- CoopPriceAgreement ---
    def create_coop_agreement(self, payload, headers):
        return self._request("POST", "/v1/coop-agreements", payload, headers)

    def get_coop_agreement(self, agreement_id, headers):
        return self._request("GET", f"/v1/coop-agreements/{agreement_id}", headers=headers)

    # --- Award ---
    def create_award(self, payload, headers):
        return self._request("POST", "/v1/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/v1/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/v1/awards", headers=headers, params=params)

    def accept_award(self, award_id, headers):
        return self._request("POST", f"/v1/awards/{award_id}/accept", headers=headers)

    def issue_amendment(self, award_id, payload, headers):
        return self._request("POST", f"/v1/awards/{award_id}/issue-amendment", payload, headers)

    # --- PurchaseOrder ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/v1/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/v1/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/v1/purchase-orders", headers=headers, params=params)

    def accept_purchase_order(self, po_id, headers):
        return self._request("POST", f"/v1/purchase-orders/{po_id}/accept", headers=headers)

    def cancel_purchase_order(self, po_id, headers, payload=None):
        return self._request("POST", f"/v1/purchase-orders/{po_id}/cancel", payload, headers)

    def close_purchase_order(self, po_id, headers):
        return self._request("POST", f"/v1/purchase-orders/{po_id}/close", headers=headers)

    # --- POLine ---
    def create_po_line(self, payload, headers):
        return self._request("POST", "/v1/po-lines", payload, headers)

    def get_po_line(self, line_id, headers):
        return self._request("GET", f"/v1/po-lines/{line_id}", headers=headers)

    def list_po_lines(self, headers, params=None):
        return self._request("GET", "/v1/po-lines", headers=headers, params=params)

    def declare_backorder(self, line_id, payload, headers):
        return self._request("POST", f"/v1/po-lines/{line_id}/declare-backorder", payload, headers)

    def cancel_po_line(self, line_id, headers):
        return self._request("POST", f"/v1/po-lines/{line_id}/cancel", headers=headers)

    def create_backorder_notice(self, line_id, payload, headers):
        return self._request("POST", f"/v1/po-lines/{line_id}/backorder-notices", payload, headers)

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/v1/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/v1/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/v1/shipments", headers=headers, params=params)

    def mark_delivered(self, shipment_id, payload, headers):
        return self._request("POST", f"/v1/shipments/{shipment_id}/mark-delivered", payload, headers)

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/v1/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/v1/crews/{crew_id}", headers=headers)

    # --- InstallTask ---
    def create_install_task(self, payload, headers):
        return self._request("POST", "/v1/install-tasks", payload, headers)

    def get_install_task(self, task_id, headers):
        return self._request("GET", f"/v1/install-tasks/{task_id}", headers=headers)

    def list_install_tasks(self, headers, params=None):
        return self._request("GET", "/v1/install-tasks", headers=headers, params=params)

    def start_install_task(self, task_id, headers):
        return self._request("POST", f"/v1/install-tasks/{task_id}/start", headers=headers)

    def complete_install_task(self, task_id, payload, headers):
        return self._request("POST", f"/v1/install-tasks/{task_id}/complete", payload, headers)

    def unassign_install_task(self, task_id, headers):
        return self._request("POST", f"/v1/install-tasks/{task_id}/unassign", headers=headers)

    # --- DamageReport ---
    def create_damage_report(self, payload, headers):
        return self._request("POST", "/v1/damage-reports", payload, headers)

    def get_damage_report(self, report_id, headers):
        return self._request("GET", f"/v1/damage-reports/{report_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/v1/damage-reports", headers=headers, params=params)

    def approve_replacement(self, report_id, payload, headers):
        return self._request("POST", f"/v1/damage-reports/{report_id}/approve-replacement", payload, headers)

    def close_no_fault(self, report_id, headers):
        return self._request("POST", f"/v1/damage-reports/{report_id}/close-no-fault", headers=headers)

    # --- BackorderNotice ---
    def get_backorder_notice(self, notice_id, headers):
        return self._request("GET", f"/v1/backorder-notices/{notice_id}", headers=headers)

    def list_backorder_notices(self, headers, params=None):
        return self._request("GET", "/v1/backorder-notices", headers=headers, params=params)

    def update_eta(self, notice_id, payload, headers):
        return self._request("POST", f"/v1/backorder-notices/{notice_id}/update-eta", payload, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/v1/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/v1/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/v1/warranty-claims", headers=headers, params=params)

    def review_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/review", headers=headers)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/approve", headers=headers)

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/deny", payload, headers)

    def appeal_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/appeal", payload, headers)

    def order_parts(self, claim_id, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/order-parts", headers=headers)


api_client = ApiClient()
