"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the ``/smart-home-support`` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/smart-home-support"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Households and members
    # ------------------------------------------------------------------
    def create_household(self, payload, headers):
        return self._request("POST", f"{PREFIX}/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"{PREFIX}/households/{household_id}", headers=headers)

    def set_account_status(self, household_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/households/{household_id}/account-status", payload, headers
        )

    def add_member(self, household_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/households/{household_id}/members", payload, headers
        )

    def list_household_members(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/household-members", headers=headers, params=params
        )

    def get_household_member(self, member_id, headers):
        return self._request(
            "GET", f"{PREFIX}/household-members/{member_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Plans and subscriptions
    # ------------------------------------------------------------------
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscription-plans/{plan_id}", headers=headers
        )

    def create_subscription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers
        )

    def change_tier(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/change-tier", payload, headers
        )

    def set_overage_policy(self, subscription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/subscriptions/{subscription_id}/set-overage-policy",
            payload,
            headers,
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/cancel", payload, headers
        )

    def close_cycle(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/close-cycle", payload, headers
        )

    # ------------------------------------------------------------------
    # Catalog and devices
    # ------------------------------------------------------------------
    def create_catalog_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/device-catalog", payload, headers)

    def get_catalog_entry(self, catalog_entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/device-catalog/{catalog_entry_id}", headers=headers
        )

    def claim_device(self, payload, headers):
        return self._request("POST", f"{PREFIX}/devices/claim", payload, headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/devices", headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", f"{PREFIX}/devices/{device_id}", headers=headers)

    def activate_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/activate", payload, headers
        )

    def reclaim_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/reclaim", payload, headers
        )

    def decommission_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/decommission", payload, headers
        )

    def transfer_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/transfer", payload, headers
        )

    def accept_transfer(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/accept-transfer", payload, headers
        )

    # ------------------------------------------------------------------
    # Tickets
    # ------------------------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tickets", payload, headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/tickets/{ticket_id}", headers=headers)

    def get_ticket_sla(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/tickets/{ticket_id}/sla", headers=headers)

    def first_response(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/first-response", payload, headers
        )

    def await_customer(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/await-customer", payload, headers
        )

    def customer_reply(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/customer-reply", payload, headers
        )

    def open_remote_session(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/remote-sessions", payload, headers
        )

    def evaluate_sla(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/sla-evaluate", payload, headers
        )

    def close_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"{PREFIX}/tickets/{ticket_id}/close", payload, headers)

    def reopen_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"{PREFIX}/tickets/{ticket_id}/reopen", payload, headers)

    def submit_survey(self, ticket_id, payload, headers):
        return self._request("POST", f"{PREFIX}/tickets/{ticket_id}/survey", payload, headers)

    # ------------------------------------------------------------------
    # Remote sessions
    # ------------------------------------------------------------------
    def list_remote_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/remote-sessions", headers=headers, params=params
        )

    def get_remote_session(self, session_id, headers):
        return self._request(
            "GET", f"{PREFIX}/remote-sessions/{session_id}", headers=headers
        )

    def complete_remote_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/remote-sessions/{session_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Technicians, slots and visits
    # ------------------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"{PREFIX}/technicians/{technician_id}", headers=headers)

    def publish_visit_slot(self, technician_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/technicians/{technician_id}/visit-slots", payload, headers
        )

    def list_visit_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/visit-slots", headers=headers, params=params)

    def get_visit_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/visit-slots/{slot_id}", headers=headers)

    def book_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/visits/{visit_id}", headers=headers)

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/visits/{visit_id}/reschedule", payload, headers
        )

    def cancel_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/cancel", payload, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/complete", payload, headers)

    def report_no_show(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/no-show", payload, headers)

    # ------------------------------------------------------------------
    # Firmware campaigns and rollouts
    # ------------------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{PREFIX}/firmware-campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/firmware-campaigns", headers=headers, params=params
        )

    def get_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"{PREFIX}/firmware-campaigns/{campaign_id}", headers=headers
        )

    def launch_ring(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/firmware-campaigns/{campaign_id}/launch-ring", payload, headers
        )

    def resume_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/firmware-campaigns/{campaign_id}/resume", payload, headers
        )

    def list_rollouts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/firmware-rollouts", headers=headers, params=params
        )

    def get_rollout(self, rollout_id, headers):
        return self._request(
            "GET", f"{PREFIX}/firmware-rollouts/{rollout_id}", headers=headers
        )

    def report_rollout_result(self, rollout_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/firmware-rollouts/{rollout_id}/report-result", payload, headers
        )

    def defer_rollout(self, rollout_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/firmware-rollouts/{rollout_id}/defer", payload, headers
        )

    def retry_rollout(self, rollout_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/firmware-rollouts/{rollout_id}/retry", payload, headers
        )

    # ------------------------------------------------------------------
    # Add-on orders
    # ------------------------------------------------------------------
    def place_addon_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/addon-orders", payload, headers)

    def list_addon_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/addon-orders", headers=headers, params=params)

    def get_addon_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/addon-orders/{order_id}", headers=headers)

    def fulfill_addon_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/addon-orders/{order_id}/fulfill", payload, headers
        )

    # ------------------------------------------------------------------
    # RMA cases
    # ------------------------------------------------------------------
    def open_rma_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rma-cases", payload, headers)

    def list_rma_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rma-cases", headers=headers, params=params)

    def get_rma_case(self, rma_id, headers):
        return self._request("GET", f"{PREFIX}/rma-cases/{rma_id}", headers=headers)

    def ship_advance_replacement(self, rma_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rma-cases/{rma_id}/ship-advance-replacement", payload, headers
        )

    def receive_return(self, rma_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rma-cases/{rma_id}/receive-return", payload, headers
        )

    def close_return_window(self, rma_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rma-cases/{rma_id}/close-return-window", payload, headers
        )

    # ------------------------------------------------------------------
    # Surveys, credits and the logical clock
    # ------------------------------------------------------------------
    def list_surveys(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"{PREFIX}/surveys/{survey_id}", headers=headers)

    def list_service_credits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-credits", headers=headers, params=params
        )

    def get_service_credit(self, credit_id, headers):
        return self._request("GET", f"{PREFIX}/service-credits/{credit_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
