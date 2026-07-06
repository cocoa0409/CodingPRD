"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/va/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- ServicePlan ---------------------------------------------------------
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/va/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/va/service-plans/{plan_id}", headers=headers)

    def list_service_plans(self, headers, params=None):
        return self._request("GET", "/va/service-plans", headers=headers, params=params)

    # --- ClientAccount -------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/va/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/va/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/va/accounts", headers=headers, params=params)

    # --- CallScript ----------------------------------------------------------
    def create_call_script(self, payload, headers):
        return self._request("POST", "/va/call-scripts", payload, headers)

    def get_call_script(self, script_id, headers):
        return self._request("GET", f"/va/call-scripts/{script_id}", headers=headers)

    def list_call_scripts(self, headers, params=None):
        return self._request("GET", "/va/call-scripts", headers=headers, params=params)

    def publish_call_script(self, script_id, headers):
        return self._request("POST", f"/va/call-scripts/{script_id}/publish", {}, headers)

    # --- SpamRule ------------------------------------------------------------
    def create_spam_rule(self, payload, headers):
        return self._request("POST", "/va/spam-rules", payload, headers)

    def get_spam_rule(self, spam_rule_id, headers):
        return self._request("GET", f"/va/spam-rules/{spam_rule_id}", headers=headers)

    def list_spam_rules(self, headers, params=None):
        return self._request("GET", "/va/spam-rules", headers=headers, params=params)

    # --- Receptionist --------------------------------------------------------
    def create_receptionist(self, payload, headers):
        return self._request("POST", "/va/receptionists", payload, headers)

    def get_receptionist(self, receptionist_id, headers):
        return self._request("GET", f"/va/receptionists/{receptionist_id}", headers=headers)

    def list_receptionists(self, headers, params=None):
        return self._request("GET", "/va/receptionists", headers=headers, params=params)

    def go_online(self, receptionist_id, headers):
        return self._request(
            "POST", f"/va/receptionists/{receptionist_id}/go-online", {}, headers,
        )

    def go_offline(self, receptionist_id, headers):
        return self._request(
            "POST", f"/va/receptionists/{receptionist_id}/go-offline", {}, headers,
        )

    # --- AvailabilityWindow --------------------------------------------------
    def create_availability_window(self, receptionist_id, payload, headers):
        return self._request(
            "POST", f"/va/receptionists/{receptionist_id}/availability-windows",
            payload, headers,
        )

    def get_availability_window(self, window_id, headers):
        return self._request("GET", f"/va/availability-windows/{window_id}", headers=headers)

    def list_availability_windows(self, headers, params=None):
        return self._request("GET", "/va/availability-windows", headers=headers, params=params)

    # --- CalendarSlot --------------------------------------------------------
    def create_calendar_slot(self, payload, headers):
        return self._request("POST", "/va/calendar-slots", payload, headers)

    def get_calendar_slot(self, slot_id, headers):
        return self._request("GET", f"/va/calendar-slots/{slot_id}", headers=headers)

    def list_calendar_slots(self, headers, params=None):
        return self._request("GET", "/va/calendar-slots", headers=headers, params=params)

    def close_calendar_slot(self, slot_id, headers):
        return self._request("POST", f"/va/calendar-slots/{slot_id}/close", {}, headers)

    # --- Call ----------------------------------------------------------------
    def create_call(self, payload, headers):
        return self._request("POST", "/va/calls", payload, headers)

    def get_call(self, call_id, headers):
        return self._request("GET", f"/va/calls/{call_id}", headers=headers)

    def list_calls(self, headers, params=None):
        return self._request("GET", "/va/calls", headers=headers, params=params)

    def answer_call(self, call_id, headers):
        return self._request("POST", f"/va/calls/{call_id}/answer", {}, headers)

    def start_call(self, call_id, headers):
        return self._request("POST", f"/va/calls/{call_id}/start", {}, headers)

    def wrap_call(self, call_id, headers):
        return self._request("POST", f"/va/calls/{call_id}/wrap", {}, headers)

    def complete_call(self, call_id, headers):
        return self._request("POST", f"/va/calls/{call_id}/complete", {}, headers)

    def abandon_call(self, call_id, headers):
        return self._request("POST", f"/va/calls/{call_id}/abandon", {}, headers)

    def dispute_call(self, call_id, headers):
        return self._request("POST", f"/va/calls/{call_id}/dispute", {}, headers)

    def adjust_call(self, call_id, payload, headers):
        return self._request("POST", f"/va/calls/{call_id}/adjust", payload, headers)

    def escalate_call(self, call_id, payload, headers):
        return self._request("POST", f"/va/calls/{call_id}/escalate", payload, headers)

    # --- Message -------------------------------------------------------------
    def create_message(self, payload, headers):
        return self._request("POST", "/va/messages", payload, headers)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/va/messages/{message_id}", headers=headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/va/messages", headers=headers, params=params)

    # --- Escalation ----------------------------------------------------------
    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/va/escalations/{escalation_id}", headers=headers)

    def list_escalations(self, headers, params=None):
        return self._request("GET", "/va/escalations", headers=headers, params=params)

    def resolve_escalation(self, escalation_id, headers):
        return self._request("POST", f"/va/escalations/{escalation_id}/resolve", {}, headers)

    # --- CrmHandoff ----------------------------------------------------------
    def create_crm_handoff(self, payload, headers):
        return self._request("POST", "/va/crm-handoffs", payload, headers)

    def get_crm_handoff(self, handoff_id, headers):
        return self._request("GET", f"/va/crm-handoffs/{handoff_id}", headers=headers)

    def list_crm_handoffs(self, headers, params=None):
        return self._request("GET", "/va/crm-handoffs", headers=headers, params=params)

    # --- Appointment ---------------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/va/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/va/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/va/appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/va/appointments/{appointment_id}/confirm", {}, headers,
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/va/appointments/{appointment_id}/reschedule", payload, headers,
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/va/appointments/{appointment_id}/complete", {}, headers,
        )

    def no_show_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/va/appointments/{appointment_id}/no-show", {}, headers,
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/va/appointments/{appointment_id}/cancel", {}, headers,
        )

    # --- BillingPeriod -------------------------------------------------------
    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"/va/billing-periods/{period_id}", headers=headers)

    def list_billing_periods(self, headers, params=None):
        return self._request("GET", "/va/billing-periods", headers=headers, params=params)

    def get_overage_summary(self, period_id, headers):
        return self._request(
            "GET", f"/va/billing-periods/{period_id}/overage-summary", headers=headers,
        )

    def close_billing_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/va/billing-periods/{period_id}/close", payload, headers,
        )

    def finalize_billing_period(self, period_id, headers):
        return self._request(
            "POST", f"/va/billing-periods/{period_id}/finalize", {}, headers,
        )


api_client = ApiClient()
