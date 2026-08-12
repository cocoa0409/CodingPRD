"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/piano-dealer/_clock/set_current_utc", payload, headers)

    # --- consignors ---
    def create_consignor(self, payload, headers):
        return self._request("POST", "/piano-dealer/consignors", payload, headers)

    def get_consignor(self, consignor_id, headers):
        return self._request("GET", f"/piano-dealer/consignors/{consignor_id}", headers=headers)

    def list_consignor_instruments(self, consignor_id, headers, params=None):
        return self._request("GET", f"/piano-dealer/consignors/{consignor_id}/instruments", headers=headers, params=params)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/piano-dealer/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/piano-dealer/customers/{customer_id}", headers=headers)

    # --- instruments ---
    def create_instrument(self, payload, headers):
        return self._request("POST", "/piano-dealer/instruments", payload, headers)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/piano-dealer/instruments/{instrument_id}", headers=headers)

    def list_instrument_for_sale(self, instrument_id, headers):
        return self._request("POST", f"/piano-dealer/instruments/{instrument_id}/list-for-sale", headers=headers)

    def complete_restoration(self, instrument_id, headers):
        return self._request("POST", f"/piano-dealer/instruments/{instrument_id}/complete-restoration", headers=headers)

    def release_hold(self, instrument_id, headers):
        return self._request("POST", f"/piano-dealer/instruments/{instrument_id}/release-hold", headers=headers)

    def return_to_consignor(self, instrument_id, headers):
        return self._request("POST", f"/piano-dealer/instruments/{instrument_id}/return-to-consignor", headers=headers)

    # --- trade-in appraisals ---
    def create_trade_in_appraisal(self, payload, headers):
        return self._request("POST", "/piano-dealer/trade-in-appraisals", payload, headers)

    def get_trade_in_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/piano-dealer/trade-in-appraisals/{appraisal_id}", headers=headers)

    def list_trade_in_appraisals(self, headers, params=None):
        return self._request("GET", "/piano-dealer/trade-in-appraisals", headers=headers, params=params)

    def evaluate_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/piano-dealer/trade-in-appraisals/{appraisal_id}/evaluate", payload, headers)

    def counter_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/piano-dealer/trade-in-appraisals/{appraisal_id}/counter", payload, headers)

    def accept_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/piano-dealer/trade-in-appraisals/{appraisal_id}/accept", headers=headers)

    def decline_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/piano-dealer/trade-in-appraisals/{appraisal_id}/decline", headers=headers)

    # --- institutional bids ---
    def create_bid_package(self, payload, headers):
        return self._request("POST", "/piano-dealer/bid-packages", payload, headers)

    def get_bid_package(self, bid_id, headers):
        return self._request("GET", f"/piano-dealer/bid-packages/{bid_id}", headers=headers)

    def list_bid_packages(self, headers, params=None):
        return self._request("GET", "/piano-dealer/bid-packages", headers=headers, params=params)

    def submit_bid_package(self, bid_id, headers):
        return self._request("POST", f"/piano-dealer/bid-packages/{bid_id}/submit", headers=headers)

    def compliance_approve_bid(self, bid_id, headers):
        return self._request("POST", f"/piano-dealer/bid-packages/{bid_id}/compliance-approve", headers=headers)

    def return_bid_for_revision(self, bid_id, headers):
        return self._request("POST", f"/piano-dealer/bid-packages/{bid_id}/return-for-revision", headers=headers)

    def record_bid_outcome(self, bid_id, payload, headers):
        return self._request("POST", f"/piano-dealer/bid-packages/{bid_id}/record-outcome", payload, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/piano-dealer/bid-packages/{bid_id}/withdraw", headers=headers)

    def create_bid_revision(self, bid_id, payload, headers):
        return self._request("POST", f"/piano-dealer/bid-packages/{bid_id}/revisions", payload, headers)

    # --- sales orders ---
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/piano-dealer/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/piano-dealer/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/piano-dealer/sales-orders", headers=headers, params=params)

    def amend_sales_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/piano-dealer/sales-orders/{order_id}", payload, headers)

    def post_payment(self, order_id, payload, headers):
        return self._request("POST", f"/piano-dealer/sales-orders/{order_id}/payments", payload, headers)

    def confirm_installation(self, order_id, headers):
        return self._request("POST", f"/piano-dealer/sales-orders/{order_id}/confirm-installation", headers=headers)

    def complete_return(self, order_id, headers):
        return self._request("POST", f"/piano-dealer/sales-orders/{order_id}/complete-return", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/piano-dealer/sales-orders/{order_id}/cancel", headers=headers)

    # --- delivery resources ---
    def create_delivery_crew(self, payload, headers):
        return self._request("POST", "/piano-dealer/delivery-crews", payload, headers)

    def create_technician(self, payload, headers):
        return self._request("POST", "/piano-dealer/technicians", payload, headers)

    def create_delivery_job(self, payload, headers):
        return self._request("POST", "/piano-dealer/delivery-jobs", payload, headers)

    def get_delivery_job(self, job_id, headers):
        return self._request("GET", f"/piano-dealer/delivery-jobs/{job_id}", headers=headers)

    def list_delivery_jobs(self, headers, params=None):
        return self._request("GET", "/piano-dealer/delivery-jobs", headers=headers, params=params)

    def start_delivery_job(self, job_id, headers):
        return self._request("POST", f"/piano-dealer/delivery-jobs/{job_id}/start", headers=headers)

    def complete_delivery_job(self, job_id, headers):
        return self._request("POST", f"/piano-dealer/delivery-jobs/{job_id}/complete", headers=headers)

    def fail_delivery_job(self, job_id, headers):
        return self._request("POST", f"/piano-dealer/delivery-jobs/{job_id}/fail", headers=headers)

    def reschedule_delivery_job(self, job_id, payload, headers):
        return self._request("POST", f"/piano-dealer/delivery-jobs/{job_id}/reschedule", payload, headers)

    # --- service plans & visits ---
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/piano-dealer/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/piano-dealer/service-plans/{plan_id}", headers=headers)

    def list_service_plans(self, headers, params=None):
        return self._request("GET", "/piano-dealer/service-plans", headers=headers, params=params)

    def suspend_service_plan(self, plan_id, headers):
        return self._request("POST", f"/piano-dealer/service-plans/{plan_id}/suspend", headers=headers)

    def resume_service_plan(self, plan_id, headers):
        return self._request("POST", f"/piano-dealer/service-plans/{plan_id}/resume", headers=headers)

    def cancel_service_plan(self, plan_id, headers):
        return self._request("POST", f"/piano-dealer/service-plans/{plan_id}/cancel", headers=headers)

    def create_service_visit(self, payload, headers):
        return self._request("POST", "/piano-dealer/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/piano-dealer/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/piano-dealer/service-visits", headers=headers, params=params)

    def complete_service_visit(self, visit_id, headers):
        return self._request("POST", f"/piano-dealer/service-visits/{visit_id}/complete", headers=headers)

    def cancel_service_visit(self, visit_id, headers):
        return self._request("POST", f"/piano-dealer/service-visits/{visit_id}/cancel", headers=headers)

    # --- financing ---
    def create_financing_agreement(self, payload, headers):
        return self._request("POST", "/piano-dealer/financing-agreements", payload, headers)

    def get_financing_agreement(self, agreement_id, headers):
        return self._request("GET", f"/piano-dealer/financing-agreements/{agreement_id}", headers=headers)

    def list_financing_agreements(self, headers, params=None):
        return self._request("GET", "/piano-dealer/financing-agreements", headers=headers, params=params)

    def approve_financing_agreement(self, agreement_id, headers):
        return self._request("POST", f"/piano-dealer/financing-agreements/{agreement_id}/approve", headers=headers)

    def post_financing_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"/piano-dealer/financing-agreements/{agreement_id}/payments", payload, headers)

    def convert_to_purchase(self, agreement_id, headers):
        return self._request("POST", f"/piano-dealer/financing-agreements/{agreement_id}/convert-to-purchase", headers=headers)

    def declare_default(self, agreement_id, headers):
        return self._request("POST", f"/piano-dealer/financing-agreements/{agreement_id}/declare-default", headers=headers)

    # --- warranties ---
    def create_warranty_registration(self, payload, headers):
        return self._request("POST", "/piano-dealer/warranty-registrations", payload, headers)

    def get_warranty_registration(self, warranty_id, headers):
        return self._request("GET", f"/piano-dealer/warranty-registrations/{warranty_id}", headers=headers)

    def list_warranty_registrations(self, headers, params=None):
        return self._request("GET", "/piano-dealer/warranty-registrations", headers=headers, params=params)

    def confirm_warranty(self, warranty_id, headers):
        return self._request("POST", f"/piano-dealer/warranty-registrations/{warranty_id}/confirm", headers=headers)

    # --- restoration referrals ---
    def create_restoration_referral(self, payload, headers):
        return self._request("POST", "/piano-dealer/restoration-referrals", payload, headers)

    def get_restoration_referral(self, referral_id, headers):
        return self._request("GET", f"/piano-dealer/restoration-referrals/{referral_id}", headers=headers)

    def list_restoration_referrals(self, headers, params=None):
        return self._request("GET", "/piano-dealer/restoration-referrals", headers=headers, params=params)

    def assess_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/piano-dealer/restoration-referrals/{referral_id}/assess", payload, headers)

    def quote_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/piano-dealer/restoration-referrals/{referral_id}/quote", payload, headers)

    def record_referral_decision(self, referral_id, payload, headers):
        return self._request("POST", f"/piano-dealer/restoration-referrals/{referral_id}/record-decision", payload, headers)

    # --- showroom events ---
    def create_showroom_event(self, payload, headers):
        return self._request("POST", "/piano-dealer/showroom-events", payload, headers)

    def get_showroom_event(self, event_id, headers):
        return self._request("GET", f"/piano-dealer/showroom-events/{event_id}", headers=headers)

    def open_rsvp(self, event_id, headers):
        return self._request("POST", f"/piano-dealer/showroom-events/{event_id}/open-rsvp", headers=headers)

    def add_rsvp(self, event_id, payload, headers):
        return self._request("POST", f"/piano-dealer/showroom-events/{event_id}/rsvps", payload, headers)

    def settle_event(self, event_id, payload, headers):
        return self._request("POST", f"/piano-dealer/showroom-events/{event_id}/settle", payload, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/piano-dealer/showroom-events/{event_id}/cancel", headers=headers)


api_client = ApiClient()
