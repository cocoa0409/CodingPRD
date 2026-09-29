"""API client: one method per endpoint defined in the PRD.

All paths are relative to the API mount point `/hearing-care`.
"""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/hearing-care"


class ApiClient(GenericApiClient):
    """Endpoint methods for the direct-to-consumer hearing aid API."""

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _p(self, path: str) -> str:
        return f"{API_PREFIX}{path}"

    # ------------------------------------------------------------------
    # StatePolicy
    # ------------------------------------------------------------------
    def create_state_policy(self, payload, headers):
        return self._request("POST", self._p("/state-policies"), payload, headers)

    def list_state_policies(self, headers, params=None):
        return self._request("GET", self._p("/state-policies"), headers=headers, params=params)

    def get_state_policy(self, policy_id, headers):
        return self._request("GET", self._p(f"/state-policies/{policy_id}"), headers=headers)

    def update_state_policy(self, policy_id, payload, headers):
        return self._request("PATCH", self._p(f"/state-policies/{policy_id}"), payload, headers)

    def delete_state_policy(self, policy_id, headers):
        return self._request("DELETE", self._p(f"/state-policies/{policy_id}"), headers=headers)

    # ------------------------------------------------------------------
    # Patient
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", self._p("/patients"), payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", self._p("/patients"), headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", self._p(f"/patients/{patient_id}"), headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", self._p(f"/patients/{patient_id}"), payload, headers)

    def acknowledge_waiver(self, patient_id, headers):
        return self._request("POST", self._p(f"/patients/{patient_id}/acknowledge-waiver"), {}, headers)

    def delete_patient(self, patient_id, headers):
        return self._request("DELETE", self._p(f"/patients/{patient_id}"), headers=headers)

    # ------------------------------------------------------------------
    # ScreeningSession / RedFlagFinding
    # ------------------------------------------------------------------
    def start_screening_session(self, patient_id, payload, headers):
        return self._request("POST", self._p(f"/patients/{patient_id}/screening-sessions"), payload, headers)

    def list_patient_screening_sessions(self, patient_id, headers, params=None):
        return self._request("GET", self._p(f"/patients/{patient_id}/screening-sessions"),
                             headers=headers, params=params)

    def list_screening_sessions(self, headers, params=None):
        return self._request("GET", self._p("/screening-sessions"), headers=headers, params=params)

    def get_screening_session(self, session_id, headers):
        return self._request("GET", self._p(f"/screening-sessions/{session_id}"), headers=headers)

    def update_screening_session(self, session_id, payload, headers):
        return self._request("PATCH", self._p(f"/screening-sessions/{session_id}"), payload, headers)

    def submit_screening_session(self, session_id, headers):
        return self._request("POST", self._p(f"/screening-sessions/{session_id}/submit"), {}, headers)

    def invalidate_screening_session(self, session_id, payload, headers):
        return self._request("POST", self._p(f"/screening-sessions/{session_id}/invalidate"), payload, headers)

    def list_screening_red_flag_findings(self, session_id, headers, params=None):
        return self._request("GET", self._p(f"/screening-sessions/{session_id}/red-flag-findings"),
                             headers=headers, params=params)

    def list_red_flag_findings(self, headers, params=None):
        return self._request("GET", self._p("/red-flag-findings"), headers=headers, params=params)

    # ------------------------------------------------------------------
    # ComplianceOverride
    # ------------------------------------------------------------------
    def create_compliance_override(self, patient_id, payload, headers):
        return self._request("POST", self._p(f"/patients/{patient_id}/compliance-overrides"), payload, headers)

    def list_compliance_overrides(self, patient_id, headers, params=None):
        return self._request("GET", self._p(f"/patients/{patient_id}/compliance-overrides"),
                             headers=headers, params=params)

    def approve_compliance_override(self, patient_id, override_id, headers):
        return self._request(
            "POST",
            self._p(f"/patients/{patient_id}/compliance-overrides/{override_id}/approve"),
            {}, headers,
        )

    def reject_compliance_override(self, patient_id, override_id, payload, headers):
        return self._request(
            "POST",
            self._p(f"/patients/{patient_id}/compliance-overrides/{override_id}/reject"),
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", self._p("/providers"), payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", self._p("/providers"), headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", self._p(f"/providers/{provider_id}"), headers=headers)

    def update_provider(self, provider_id, payload, headers):
        return self._request("PATCH", self._p(f"/providers/{provider_id}"), payload, headers)

    # ------------------------------------------------------------------
    # ProviderReferral
    # ------------------------------------------------------------------
    def list_provider_referrals(self, headers, params=None):
        return self._request("GET", self._p("/provider-referrals"), headers=headers, params=params)

    def get_provider_referral(self, referral_id, headers):
        return self._request("GET", self._p(f"/provider-referrals/{referral_id}"), headers=headers)

    def list_referral_cleared_findings(self, referral_id, headers, params=None):
        return self._request("GET", self._p(f"/provider-referrals/{referral_id}/cleared-findings"),
                             headers=headers, params=params)

    def record_referral_determination(self, referral_id, payload, headers):
        return self._request("POST", self._p(f"/provider-referrals/{referral_id}/determination"), payload, headers)

    def withdraw_provider_referral(self, referral_id, payload, headers):
        return self._request("POST", self._p(f"/provider-referrals/{referral_id}/withdraw"), payload, headers)

    # ------------------------------------------------------------------
    # RemoteFittingSession
    # ------------------------------------------------------------------
    def create_remote_fitting_session(self, payload, headers):
        return self._request("POST", self._p("/remote-fitting-sessions"), payload, headers)

    def list_remote_fitting_sessions(self, headers, params=None):
        return self._request("GET", self._p("/remote-fitting-sessions"), headers=headers, params=params)

    def get_remote_fitting_session(self, session_id, headers):
        return self._request("GET", self._p(f"/remote-fitting-sessions/{session_id}"), headers=headers)

    def start_fitting_session(self, session_id, headers):
        return self._request("POST", self._p(f"/remote-fitting-sessions/{session_id}/start"), {}, headers)

    def complete_fitting_session(self, session_id, payload, headers):
        return self._request("POST", self._p(f"/remote-fitting-sessions/{session_id}/complete"), payload, headers)

    def no_show_fitting_session(self, session_id, headers):
        return self._request("POST", self._p(f"/remote-fitting-sessions/{session_id}/no-show"), {}, headers)

    def cancel_fitting_session(self, session_id, headers):
        return self._request("POST", self._p(f"/remote-fitting-sessions/{session_id}/cancel"), {}, headers)

    def rebook_fitting_session(self, session_id, headers):
        return self._request("POST", self._p(f"/remote-fitting-sessions/{session_id}/rebook"), {}, headers)

    # ------------------------------------------------------------------
    # DeviceOrder
    # ------------------------------------------------------------------
    def create_device_order(self, patient_id, payload, headers):
        return self._request("POST", self._p(f"/patients/{patient_id}/device-orders"), payload, headers)

    def list_device_orders(self, headers, params=None):
        return self._request("GET", self._p("/device-orders"), headers=headers, params=params)

    def get_device_order(self, order_id, headers):
        return self._request("GET", self._p(f"/device-orders/{order_id}"), headers=headers)

    def get_device_order_summary(self, order_id, headers):
        return self._request("GET", self._p(f"/device-orders/{order_id}/summary"), headers=headers)

    def confirm_fit(self, order_id, headers):
        return self._request("POST", self._p(f"/device-orders/{order_id}/confirm-fit"), {}, headers)

    def ship_device_order(self, order_id, headers):
        return self._request("POST", self._p(f"/device-orders/{order_id}/ship"), {}, headers)

    def cancel_device_order(self, order_id, payload, headers):
        return self._request("POST", self._p(f"/device-orders/{order_id}/cancel"), payload, headers)

    # ------------------------------------------------------------------
    # Device
    # ------------------------------------------------------------------
    def create_device(self, payload, headers):
        return self._request("POST", self._p("/devices"), payload, headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", self._p("/devices"), headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", self._p(f"/devices/{device_id}"), headers=headers)

    # ------------------------------------------------------------------
    # InventoryPool
    # ------------------------------------------------------------------
    def create_inventory_pool(self, payload, headers):
        return self._request("POST", self._p("/inventory-pools"), payload, headers)

    def list_inventory_pools(self, headers, params=None):
        return self._request("GET", self._p("/inventory-pools"), headers=headers, params=params)

    def restock_inventory_pool(self, pool_id, payload, headers):
        return self._request("POST", self._p(f"/inventory-pools/{pool_id}/restock"), payload, headers)

    def discontinue_inventory_pool(self, pool_id, headers):
        return self._request("DELETE", self._p(f"/inventory-pools/{pool_id}"), headers=headers)

    # ------------------------------------------------------------------
    # TrialPeriod / ReturnAuthorization
    # ------------------------------------------------------------------
    def list_trial_periods(self, headers, params=None):
        return self._request("GET", self._p("/trial-periods"), headers=headers, params=params)

    def get_trial_period(self, trial_id, headers):
        return self._request("GET", self._p(f"/trial-periods/{trial_id}"), headers=headers)

    def extend_trial_period(self, trial_id, payload, headers):
        return self._request("POST", self._p(f"/trial-periods/{trial_id}/extend"), payload, headers)

    def create_return_authorization(self, trial_id, payload, headers):
        return self._request("POST", self._p(f"/trial-periods/{trial_id}/return-authorizations"), payload, headers)

    def list_trial_return_authorizations(self, trial_id, headers, params=None):
        return self._request("GET", self._p(f"/trial-periods/{trial_id}/return-authorizations"),
                             headers=headers, params=params)

    def get_return_authorization(self, rma_id, headers):
        return self._request("GET", self._p(f"/return-authorizations/{rma_id}"), headers=headers)

    def receive_return_authorization(self, rma_id, headers):
        return self._request("POST", self._p(f"/return-authorizations/{rma_id}/receive"), {}, headers)

    def inspect_return_authorization(self, rma_id, payload, headers):
        return self._request("POST", self._p(f"/return-authorizations/{rma_id}/inspect"), payload, headers)

    def settle_return_authorization(self, rma_id, headers):
        return self._request("POST", self._p(f"/return-authorizations/{rma_id}/settle"), {}, headers)

    def void_return_authorization(self, rma_id, payload, headers):
        return self._request("POST", self._p(f"/return-authorizations/{rma_id}/void"), payload, headers)

    def waive_restocking(self, rma_id, payload, headers):
        return self._request("POST", self._p(f"/return-authorizations/{rma_id}/waive-restocking"), payload, headers)

    # ------------------------------------------------------------------
    # FitExchange
    # ------------------------------------------------------------------
    def create_fit_exchange(self, order_id, payload, headers):
        return self._request("POST", self._p(f"/device-orders/{order_id}/fit-exchanges"), payload, headers)

    def list_fit_exchanges(self, headers, params=None):
        return self._request("GET", self._p("/fit-exchanges"), headers=headers, params=params)

    def get_fit_exchange(self, exchange_id, headers):
        return self._request("GET", self._p(f"/fit-exchanges/{exchange_id}"), headers=headers)

    def ship_fit_exchange(self, exchange_id, headers):
        return self._request("POST", self._p(f"/fit-exchanges/{exchange_id}/ship"), {}, headers)

    def confirm_fit_exchange(self, exchange_id, headers):
        return self._request("POST", self._p(f"/fit-exchanges/{exchange_id}/confirm"), {}, headers)

    def cancel_fit_exchange(self, exchange_id, payload, headers):
        return self._request("POST", self._p(f"/fit-exchanges/{exchange_id}/cancel"), payload, headers)

    # ------------------------------------------------------------------
    # RepairOrder
    # ------------------------------------------------------------------
    def create_repair_order(self, payload, headers):
        return self._request("POST", self._p("/repair-orders"), payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", self._p("/repair-orders"), headers=headers, params=params)

    def get_repair_order(self, repair_id, headers):
        return self._request("GET", self._p(f"/repair-orders/{repair_id}"), headers=headers)

    def send_repair_kit(self, repair_id, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/send-kit"), {}, headers)

    def receive_repair_order(self, repair_id, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/receive"), {}, headers)

    def start_repair_order(self, repair_id, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/start"), {}, headers)

    def resolve_repair_order(self, repair_id, payload, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/resolve"), payload, headers)

    def return_repair_to_patient(self, repair_id, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/return-to-patient"), {}, headers)

    def escalate_repair_order(self, repair_id, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/escalate"), {}, headers)

    def cancel_repair_order(self, repair_id, payload, headers):
        return self._request("POST", self._p(f"/repair-orders/{repair_id}/cancel"), payload, headers)

    # ------------------------------------------------------------------
    # WarrantyClaim
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", self._p("/warranty-claims"), payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", self._p("/warranty-claims"), headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", self._p(f"/warranty-claims/{claim_id}"), headers=headers)

    def triage_warranty_claim(self, claim_id, headers):
        return self._request("POST", self._p(f"/warranty-claims/{claim_id}/triage"), {}, headers)

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", self._p(f"/warranty-claims/{claim_id}/decide"), payload, headers)

    def pay_warranty_deductible(self, claim_id, payload, headers):
        return self._request("POST", self._p(f"/warranty-claims/{claim_id}/pay-deductible"), payload, headers)

    def fulfill_warranty_claim(self, claim_id, headers):
        return self._request("POST", self._p(f"/warranty-claims/{claim_id}/fulfill"), {}, headers)

    def withdraw_warranty_claim(self, claim_id, headers):
        return self._request("POST", self._p(f"/warranty-claims/{claim_id}/withdraw"), {}, headers)

    # ------------------------------------------------------------------
    # ReimbursementClaim
    # ------------------------------------------------------------------
    def create_reimbursement_claim(self, payload, headers):
        return self._request("POST", self._p("/reimbursement-claims"), payload, headers)

    def list_reimbursement_claims(self, headers, params=None):
        return self._request("GET", self._p("/reimbursement-claims"), headers=headers, params=params)

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request("GET", self._p(f"/reimbursement-claims/{claim_id}"), headers=headers)

    def submit_reimbursement_claim(self, claim_id, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/submit"), {}, headers)

    def start_reimbursement_review(self, claim_id, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/start-review"), {}, headers)

    def request_reimbursement_info(self, claim_id, payload, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/request-info"), payload, headers)

    def supply_reimbursement_info(self, claim_id, payload, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/supply-info"), payload, headers)

    def decide_reimbursement_claim(self, claim_id, payload, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/decide"), payload, headers)

    def pay_reimbursement_claim(self, claim_id, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/pay"), {}, headers)

    def void_reimbursement_claim(self, claim_id, payload, headers):
        return self._request("POST", self._p(f"/reimbursement-claims/{claim_id}/void"), payload, headers)

    # ------------------------------------------------------------------
    # CarePlanSubscription
    # ------------------------------------------------------------------
    def create_care_plan_subscription(self, payload, headers):
        return self._request("POST", self._p("/care-plan-subscriptions"), payload, headers)

    def list_care_plan_subscriptions(self, headers, params=None):
        return self._request("GET", self._p("/care-plan-subscriptions"), headers=headers, params=params)

    def get_care_plan_subscription(self, subscription_id, headers):
        return self._request("GET", self._p(f"/care-plan-subscriptions/{subscription_id}"), headers=headers)

    def change_care_plan_tier(self, subscription_id, payload, headers):
        return self._request("POST", self._p(f"/care-plan-subscriptions/{subscription_id}/change-tier"),
                             payload, headers)

    def run_billing_cycle(self, subscription_id, payload, headers):
        return self._request("POST", self._p(f"/care-plan-subscriptions/{subscription_id}/run-billing-cycle"),
                             payload, headers)

    def retry_care_plan_payment(self, subscription_id, payload, headers):
        return self._request("POST", self._p(f"/care-plan-subscriptions/{subscription_id}/retry-payment"),
                             payload, headers)

    def reinstate_care_plan_subscription(self, subscription_id, headers):
        return self._request("POST", self._p(f"/care-plan-subscriptions/{subscription_id}/reinstate"), {}, headers)

    def cancel_care_plan_subscription(self, subscription_id, payload, headers):
        return self._request("POST", self._p(f"/care-plan-subscriptions/{subscription_id}/cancel"), payload, headers)

    # ------------------------------------------------------------------
    # Firmware
    # ------------------------------------------------------------------
    def create_firmware_campaign(self, payload, headers):
        return self._request("POST", self._p("/firmware-campaigns"), payload, headers)

    def list_firmware_campaigns(self, headers, params=None):
        return self._request("GET", self._p("/firmware-campaigns"), headers=headers, params=params)

    def get_firmware_campaign(self, campaign_id, headers):
        return self._request("GET", self._p(f"/firmware-campaigns/{campaign_id}"), headers=headers)

    def schedule_firmware_campaign(self, campaign_id, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/schedule"), {}, headers)

    def advance_firmware_campaign(self, campaign_id, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/advance"), {}, headers)

    def pause_firmware_campaign(self, campaign_id, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/pause"), {}, headers)

    def resume_firmware_campaign(self, campaign_id, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/resume"), {}, headers)

    def complete_firmware_campaign(self, campaign_id, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/complete"), {}, headers)

    def abort_firmware_campaign(self, campaign_id, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/abort"), {}, headers)

    def create_manual_enrollment(self, campaign_id, payload, headers):
        return self._request("POST", self._p(f"/firmware-campaigns/{campaign_id}/manual-enrollments"),
                             payload, headers)

    def list_campaign_rollouts(self, campaign_id, headers, params=None):
        return self._request("GET", self._p(f"/firmware-campaigns/{campaign_id}/rollouts"),
                             headers=headers, params=params)

    def list_firmware_rollouts(self, headers, params=None):
        return self._request("GET", self._p("/firmware-rollouts"), headers=headers, params=params)

    def offer_firmware_rollout(self, rollout_id, headers):
        return self._request("POST", self._p(f"/firmware-rollouts/{rollout_id}/offer"), {}, headers)

    def install_firmware_rollout(self, rollout_id, headers):
        return self._request("POST", self._p(f"/firmware-rollouts/{rollout_id}/install"), {}, headers)

    def rollback_firmware_rollout(self, rollout_id, headers):
        return self._request("POST", self._p(f"/firmware-rollouts/{rollout_id}/rollback"), {}, headers)

    # ------------------------------------------------------------------
    # Test-driving endpoints
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", self._p("/_clock/set_current_utc"), payload, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", self._p("/_payments/simulate"), payload, headers)

    def scan_shipment(self, payload, headers):
        return self._request("POST", self._p("/_shipments/scan"), payload, headers)

    def report_firmware_install(self, payload, headers):
        return self._request("POST", self._p("/_firmware/report"), payload, headers)


api_client = ApiClient()
