"""API client: one method per endpoint defined in the PRD (section 4).

Everything is mounted under the /kidswear prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

P = "/kidswear"


class ApiClient(GenericApiClient):
    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---------------- Plans ----------------
    def create_plan(self, payload, headers):
        return self._request("POST", f"{P}/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", f"{P}/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{P}/plans/{plan_id}", headers=headers)

    def update_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"{P}/plans/{plan_id}", payload, headers)

    # ---------------- Members ----------------
    def create_member(self, payload, headers):
        return self._request("POST", f"{P}/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{P}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{P}/members/{member_id}", headers=headers)

    def activate_member(self, member_id, headers, payload=None):
        return self._request("POST", f"{P}/members/{member_id}/activate",
                             payload or {}, headers)

    def size_up_member(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/size-up", payload, headers)

    def set_member_protection(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/protection", payload, headers)

    def cancel_member(self, member_id, headers, payload=None):
        return self._request("POST", f"{P}/members/{member_id}/cancel",
                             payload or {}, headers)

    def get_member_entitlements(self, member_id, headers):
        return self._request("GET", f"{P}/members/{member_id}/entitlements", headers=headers)

    def create_charge_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/charge-adjustments",
                             payload, headers)

    def create_credit_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/credit-adjustments",
                             payload, headers)

    def create_credit_application(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/credit-applications",
                             payload, headers)

    def create_pause_request(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/pause-requests",
                             payload, headers)

    # ---------------- Cycles ----------------
    def create_cycle(self, payload, headers):
        return self._request("POST", f"{P}/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{P}/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{P}/cycles/{cycle_id}", headers=headers)

    def open_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"{P}/cycles/{cycle_id}/open", payload or {}, headers)

    def close_swap_window(self, cycle_id, headers, payload=None):
        return self._request("POST", f"{P}/cycles/{cycle_id}/close-swap-window",
                             payload or {}, headers)

    def assess_late(self, cycle_id, headers, payload=None):
        return self._request("POST", f"{P}/cycles/{cycle_id}/assess-late",
                             payload or {}, headers)

    def close_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"{P}/cycles/{cycle_id}/close", payload or {}, headers)

    def get_cycle_invoice(self, cycle_id, headers):
        return self._request("GET", f"{P}/cycles/{cycle_id}/invoice", headers=headers)

    def create_swap_request(self, cycle_id, payload, headers):
        return self._request("POST", f"{P}/cycles/{cycle_id}/swap-requests", payload, headers)

    # ---------------- Garment styles ----------------
    def create_garment_style(self, payload, headers):
        return self._request("POST", f"{P}/garment-styles", payload, headers)

    def list_garment_styles(self, headers, params=None):
        return self._request("GET", f"{P}/garment-styles", headers=headers, params=params)

    def get_garment_style(self, style_id, headers):
        return self._request("GET", f"{P}/garment-styles/{style_id}", headers=headers)

    def update_garment_style(self, style_id, payload, headers):
        return self._request("PATCH", f"{P}/garment-styles/{style_id}", payload, headers)

    # ---------------- Garment units ----------------
    def create_garment_unit(self, payload, headers):
        return self._request("POST", f"{P}/garment-units", payload, headers)

    def list_garment_units(self, headers, params=None):
        return self._request("GET", f"{P}/garment-units", headers=headers, params=params)

    def get_garment_unit(self, unit_id, headers):
        return self._request("GET", f"{P}/garment-units/{unit_id}", headers=headers)

    def retire_garment_unit(self, unit_id, payload, headers):
        return self._request("POST", f"{P}/garment-units/{unit_id}/retire", payload, headers)

    # ---------------- Boxes ----------------
    def create_box(self, payload, headers):
        return self._request("POST", f"{P}/boxes", payload, headers)

    def list_boxes(self, headers, params=None):
        return self._request("GET", f"{P}/boxes", headers=headers, params=params)

    def get_box(self, box_id, headers):
        return self._request("GET", f"{P}/boxes/{box_id}", headers=headers)

    def allocate_into_box(self, box_id, payload, headers):
        return self._request("POST", f"{P}/boxes/{box_id}/allocate", payload, headers)

    def pack_box(self, box_id, headers, payload=None):
        return self._request("POST", f"{P}/boxes/{box_id}/pack", payload or {}, headers)

    def ship_box(self, box_id, payload, headers):
        return self._request("POST", f"{P}/boxes/{box_id}/ship", payload, headers)

    # ---------------- Box items ----------------
    def list_box_items(self, headers, params=None):
        return self._request("GET", f"{P}/box-items", headers=headers, params=params)

    def get_box_item(self, box_item_id, headers):
        return self._request("GET", f"{P}/box-items/{box_item_id}", headers=headers)

    def start_return(self, box_item_id, payload, headers):
        return self._request("POST", f"{P}/box-items/{box_item_id}/start-return",
                             payload, headers)

    def create_buy_out_quote(self, box_item_id, payload, headers):
        return self._request("POST", f"{P}/box-items/{box_item_id}/buy-out", payload, headers)

    # ---------------- Swap requests ----------------
    def list_swap_requests(self, headers, params=None):
        return self._request("GET", f"{P}/swap-requests", headers=headers, params=params)

    def get_swap_request(self, swap_request_id, headers):
        return self._request("GET", f"{P}/swap-requests/{swap_request_id}", headers=headers)

    def submit_swap_request(self, swap_request_id, headers, payload=None):
        return self._request("POST", f"{P}/swap-requests/{swap_request_id}/submit",
                             payload or {}, headers)

    def approve_swap_request(self, swap_request_id, headers, payload=None):
        return self._request("POST", f"{P}/swap-requests/{swap_request_id}/approve",
                             payload or {}, headers)

    def reject_swap_request(self, swap_request_id, payload, headers):
        return self._request("POST", f"{P}/swap-requests/{swap_request_id}/reject",
                             payload, headers)

    def fulfill_swap_request(self, swap_request_id, headers, payload=None):
        return self._request("POST", f"{P}/swap-requests/{swap_request_id}/fulfill",
                             payload or {}, headers)

    # ---------------- Shipments ----------------
    def create_shipment(self, payload, headers):
        return self._request("POST", f"{P}/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{P}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{P}/shipments/{shipment_id}", headers=headers)

    def depart_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"{P}/shipments/{shipment_id}/depart",
                             payload or {}, headers)

    def receive_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"{P}/shipments/{shipment_id}/receive",
                             payload or {}, headers)

    def mark_shipment_lost(self, shipment_id, headers, payload=None):
        return self._request("POST", f"{P}/shipments/{shipment_id}/mark-lost",
                             payload or {}, headers)

    def return_shipment_to_sender(self, shipment_id, headers, payload=None):
        return self._request("POST", f"{P}/shipments/{shipment_id}/return-to-sender",
                             payload or {}, headers)

    # ---------------- Shipping labels ----------------
    def create_shipping_label(self, payload, headers):
        return self._request("POST", f"{P}/shipping-labels", payload, headers)

    def list_shipping_labels(self, headers, params=None):
        return self._request("GET", f"{P}/shipping-labels", headers=headers, params=params)

    def get_shipping_label(self, label_id, headers):
        return self._request("GET", f"{P}/shipping-labels/{label_id}", headers=headers)

    def void_shipping_label(self, label_id, headers, payload=None):
        return self._request("POST", f"{P}/shipping-labels/{label_id}/void",
                             payload or {}, headers)

    def expire_shipping_label(self, label_id, headers, payload=None):
        return self._request("POST", f"{P}/shipping-labels/{label_id}/expire",
                             payload or {}, headers)

    def reissue_shipping_label(self, label_id, headers, payload=None):
        return self._request("POST", f"{P}/shipping-labels/{label_id}/reissue",
                             payload or {}, headers)

    # ---------------- Condition assessments ----------------
    def create_condition_assessment(self, payload, headers):
        return self._request("POST", f"{P}/condition-assessments", payload, headers)

    def list_condition_assessments(self, headers, params=None):
        return self._request("GET", f"{P}/condition-assessments", headers=headers, params=params)

    def get_condition_assessment(self, assessment_id, headers):
        return self._request("GET", f"{P}/condition-assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{P}/condition-assessments/{assessment_id}/submit",
                             payload, headers)

    def confirm_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"{P}/condition-assessments/{assessment_id}/confirm",
                             payload or {}, headers)

    def dispute_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{P}/condition-assessments/{assessment_id}/dispute",
                             payload, headers)

    def regrade_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{P}/condition-assessments/{assessment_id}/regrade",
                             payload, headers)

    # ---------------- Processing jobs ----------------
    def list_processing_jobs(self, headers, params=None):
        return self._request("GET", f"{P}/processing-jobs", headers=headers, params=params)

    def get_processing_job(self, job_id, headers):
        return self._request("GET", f"{P}/processing-jobs/{job_id}", headers=headers)

    def start_processing_job(self, job_id, headers, payload=None):
        return self._request("POST", f"{P}/processing-jobs/{job_id}/start",
                             payload or {}, headers)

    def pass_processing_job(self, job_id, headers, payload=None):
        return self._request("POST", f"{P}/processing-jobs/{job_id}/pass",
                             payload or {}, headers)

    def fail_processing_job(self, job_id, headers, payload=None):
        return self._request("POST", f"{P}/processing-jobs/{job_id}/fail",
                             payload or {}, headers)

    def scrap_processing_job(self, job_id, headers, payload=None):
        return self._request("POST", f"{P}/processing-jobs/{job_id}/scrap",
                             payload or {}, headers)

    # ---------------- Trade-in submissions ----------------
    def create_trade_in_submission(self, payload, headers):
        return self._request("POST", f"{P}/trade-in-submissions", payload, headers)

    def list_trade_in_submissions(self, headers, params=None):
        return self._request("GET", f"{P}/trade-in-submissions", headers=headers, params=params)

    def get_trade_in_submission(self, submission_id, headers):
        return self._request("GET", f"{P}/trade-in-submissions/{submission_id}", headers=headers)

    def add_trade_in_item(self, submission_id, payload, headers):
        return self._request("POST", f"{P}/trade-in-submissions/{submission_id}/items",
                             payload, headers)

    def issue_trade_in_label(self, submission_id, payload, headers):
        return self._request("POST", f"{P}/trade-in-submissions/{submission_id}/issue-label",
                             payload, headers)

    def finalize_trade_in_submission(self, submission_id, headers, payload=None):
        return self._request("POST", f"{P}/trade-in-submissions/{submission_id}/finalize",
                             payload or {}, headers)

    # ---------------- Trade-in items ----------------
    def list_trade_in_items(self, headers, params=None):
        return self._request("GET", f"{P}/trade-in-items", headers=headers, params=params)

    def get_trade_in_item(self, trade_in_item_id, headers):
        return self._request("GET", f"{P}/trade-in-items/{trade_in_item_id}", headers=headers)

    def absorb_trade_in_item(self, trade_in_item_id, payload, headers):
        return self._request("POST", f"{P}/trade-in-items/{trade_in_item_id}/absorb",
                             payload, headers)

    def elect_disposition(self, trade_in_item_id, payload, headers):
        return self._request("POST",
                             f"{P}/trade-in-items/{trade_in_item_id}/elect-disposition",
                             payload, headers)

    def apply_default_disposition(self, trade_in_item_id, headers, payload=None):
        return self._request("POST",
                             f"{P}/trade-in-items/{trade_in_item_id}/apply-default-disposition",
                             payload or {}, headers)

    # ---------------- Credit ledger ----------------
    def list_credit_entries(self, headers, params=None):
        return self._request("GET", f"{P}/credit-entries", headers=headers, params=params)

    def get_credit_entry(self, credit_entry_id, headers):
        return self._request("GET", f"{P}/credit-entries/{credit_entry_id}", headers=headers)

    def expire_credit_entry(self, credit_entry_id, headers, payload=None):
        return self._request("POST", f"{P}/credit-entries/{credit_entry_id}/expire",
                             payload or {}, headers)

    def revoke_credit_entry(self, credit_entry_id, payload, headers):
        return self._request("POST", f"{P}/credit-entries/{credit_entry_id}/revoke",
                             payload, headers)

    # ---------------- Charge ledger ----------------
    def list_charge_entries(self, headers, params=None):
        return self._request("GET", f"{P}/charge-entries", headers=headers, params=params)

    def get_charge_entry(self, charge_entry_id, headers):
        return self._request("GET", f"{P}/charge-entries/{charge_entry_id}", headers=headers)

    def waive_charge_entry(self, charge_entry_id, payload, headers):
        return self._request("POST", f"{P}/charge-entries/{charge_entry_id}/waive",
                             payload, headers)

    # ---------------- Buy-out orders ----------------
    def list_buy_out_orders(self, headers, params=None):
        return self._request("GET", f"{P}/buy-out-orders", headers=headers, params=params)

    def get_buy_out_order(self, buy_out_order_id, headers):
        return self._request("GET", f"{P}/buy-out-orders/{buy_out_order_id}", headers=headers)

    def accept_buy_out_order(self, buy_out_order_id, headers, payload=None):
        return self._request("POST", f"{P}/buy-out-orders/{buy_out_order_id}/accept",
                             payload or {}, headers)

    def pay_buy_out_order(self, buy_out_order_id, headers, payload=None):
        return self._request("POST", f"{P}/buy-out-orders/{buy_out_order_id}/pay",
                             payload or {}, headers)

    def cancel_buy_out_order(self, buy_out_order_id, headers, payload=None):
        return self._request("POST", f"{P}/buy-out-orders/{buy_out_order_id}/cancel",
                             payload or {}, headers)

    def expire_buy_out_order(self, buy_out_order_id, headers, payload=None):
        return self._request("POST", f"{P}/buy-out-orders/{buy_out_order_id}/expire",
                             payload or {}, headers)

    # ---------------- Capsules ----------------
    def create_capsule(self, payload, headers):
        return self._request("POST", f"{P}/capsules", payload, headers)

    def list_capsules(self, headers, params=None):
        return self._request("GET", f"{P}/capsules", headers=headers, params=params)

    def get_capsule(self, capsule_id, headers):
        return self._request("GET", f"{P}/capsules/{capsule_id}", headers=headers)

    def announce_capsule(self, capsule_id, headers, payload=None):
        return self._request("POST", f"{P}/capsules/{capsule_id}/announce",
                             payload or {}, headers)

    def open_capsule(self, capsule_id, headers, payload=None):
        return self._request("POST", f"{P}/capsules/{capsule_id}/open", payload or {}, headers)

    def lift_capsule_embargo(self, capsule_id, headers, payload=None):
        return self._request("POST", f"{P}/capsules/{capsule_id}/lift-embargo",
                             payload or {}, headers)

    def close_capsule(self, capsule_id, headers, payload=None):
        return self._request("POST", f"{P}/capsules/{capsule_id}/close", payload or {}, headers)

    def create_capsule_allocation(self, capsule_id, payload, headers):
        return self._request("POST", f"{P}/capsules/{capsule_id}/allocations", payload, headers)

    def list_capsule_allocations(self, headers, params=None):
        return self._request("GET", f"{P}/capsule-allocations", headers=headers, params=params)

    def get_capsule_allocation(self, allocation_id, headers):
        return self._request("GET", f"{P}/capsule-allocations/{allocation_id}", headers=headers)

    def release_capsule_allocation(self, allocation_id, headers, payload=None):
        return self._request("POST", f"{P}/capsule-allocations/{allocation_id}/release",
                             payload or {}, headers)

    # ---------------- Pause requests ----------------
    def list_pause_requests(self, headers, params=None):
        return self._request("GET", f"{P}/pause-requests", headers=headers, params=params)

    def get_pause_request(self, pause_request_id, headers):
        return self._request("GET", f"{P}/pause-requests/{pause_request_id}", headers=headers)

    def activate_pause_request(self, pause_request_id, headers, payload=None):
        return self._request("POST", f"{P}/pause-requests/{pause_request_id}/activate",
                             payload or {}, headers)

    def end_pause_request(self, pause_request_id, headers, payload=None):
        return self._request("POST", f"{P}/pause-requests/{pause_request_id}/end",
                             payload or {}, headers)

    def cancel_pause_request(self, pause_request_id, headers, payload=None):
        return self._request("POST", f"{P}/pause-requests/{pause_request_id}/cancel",
                             payload or {}, headers)

    def deny_pause_request(self, pause_request_id, payload, headers):
        return self._request("POST", f"{P}/pause-requests/{pause_request_id}/deny",
                             payload, headers)

    # ---------------- Lost-shipment claims ----------------
    def create_lost_shipment_claim(self, payload, headers):
        return self._request("POST", f"{P}/lost-shipment-claims", payload, headers)

    def list_lost_shipment_claims(self, headers, params=None):
        return self._request("GET", f"{P}/lost-shipment-claims", headers=headers, params=params)

    def get_lost_shipment_claim(self, claim_id, headers):
        return self._request("GET", f"{P}/lost-shipment-claims/{claim_id}", headers=headers)

    def investigate_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"{P}/lost-shipment-claims/{claim_id}/investigate",
                             payload or {}, headers)

    def request_claim_info(self, claim_id, headers, payload=None):
        return self._request("POST", f"{P}/lost-shipment-claims/{claim_id}/request-info",
                             payload or {}, headers)

    def provide_claim_info(self, claim_id, payload, headers):
        return self._request("POST", f"{P}/lost-shipment-claims/{claim_id}/provide-info",
                             payload, headers)

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"{P}/lost-shipment-claims/{claim_id}/approve",
                             payload or {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{P}/lost-shipment-claims/{claim_id}/deny",
                             payload, headers)

    def settle_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"{P}/lost-shipment-claims/{claim_id}/settle",
                             payload or {}, headers)


api_client = ApiClient()
