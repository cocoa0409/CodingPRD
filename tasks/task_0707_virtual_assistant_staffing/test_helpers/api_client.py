"""API client: one method per endpoint mounted under /va-staffing.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP envelope, query-param vs JSON-body routing, and returns a raw Response.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/va-staffing"


class ApiClient(GenericApiClient):
    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", f"{PREFIX}/_clock", headers=headers)

    # ─── SkillTag ──────────────────────────────────────────────────────────
    def create_skill_tag(self, payload, headers):
        return self._request("POST", f"{PREFIX}/skill-tags", payload, headers)

    def get_skill_tag(self, skill_tag_id, headers):
        return self._request("GET", f"{PREFIX}/skill-tags/{skill_tag_id}", headers=headers)

    def list_skill_tags(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/skill-tags", headers=headers, params=params)

    # ─── SlaPolicy ─────────────────────────────────────────────────────────
    def create_sla_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sla-policies", payload, headers)

    def get_sla_policy(self, sla_policy_id, headers):
        return self._request("GET", f"{PREFIX}/sla-policies/{sla_policy_id}", headers=headers)

    def list_sla_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sla-policies", headers=headers, params=params)

    # ─── VirtualAssistant ──────────────────────────────────────────────────
    def create_virtual_assistant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/virtual-assistants", payload, headers)

    def get_virtual_assistant(self, va_id, headers):
        return self._request("GET", f"{PREFIX}/virtual-assistants/{va_id}", headers=headers)

    def list_virtual_assistants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/virtual-assistants", headers=headers, params=params)

    # ─── Client ────────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients", headers=headers, params=params)

    def scope_client(self, client_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/clients/{client_id}/scope", payload, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/suspend", headers=headers)

    def resume_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/resume", headers=headers)

    def close_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/close", headers=headers)

    # ─── Engagement ────────────────────────────────────────────────────────
    def create_engagement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"{PREFIX}/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/engagements", headers=headers, params=params)

    def accept_engagement(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/accept", headers=headers)

    def reject_engagement(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/reject", headers=headers)

    def return_engagement_to_proposed(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/return-to-proposed",
                             headers=headers)

    def activate_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/activate",
                             payload, headers)

    def end_engagement(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/engagements/{engagement_id}/end", headers=headers)

    # ─── AddOn ─────────────────────────────────────────────────────────────
    def create_addon(self, payload, headers):
        return self._request("POST", f"{PREFIX}/addons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"{PREFIX}/addons/{addon_id}", headers=headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/addons", headers=headers, params=params)

    def activate_addon(self, addon_id, headers):
        return self._request("POST", f"{PREFIX}/addons/{addon_id}/activate", headers=headers)

    # ─── RetainerCycle ─────────────────────────────────────────────────────
    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cycles", headers=headers, params=params)

    def close_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/close", payload, headers)

    # ─── Task ──────────────────────────────────────────────────────────────
    def create_task(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tasks", payload, headers)

    def get_task(self, task_id, headers):
        return self._request("GET", f"{PREFIX}/tasks/{task_id}", headers=headers)

    def list_tasks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tasks", headers=headers, params=params)

    def assign_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/tasks/{task_id}/assign", headers=headers)

    def start_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/tasks/{task_id}/start", headers=headers)

    def block_task(self, task_id, payload, headers):
        return self._request("POST", f"{PREFIX}/tasks/{task_id}/block", payload, headers)

    def unblock_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/tasks/{task_id}/unblock", headers=headers)

    def complete_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/tasks/{task_id}/complete", headers=headers)

    def cancel_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/tasks/{task_id}/cancel", headers=headers)

    # ─── TimeEntry ─────────────────────────────────────────────────────────
    def create_time_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/time-entries", payload, headers)

    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/time-entries/{entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/time-entries", headers=headers, params=params)

    def approve_time_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/time-entries/{entry_id}/approve", headers=headers)

    def reject_time_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/time-entries/{entry_id}/reject", headers=headers)

    # ─── Escalation ────────────────────────────────────────────────────────
    def create_escalation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/escalations", payload, headers)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"{PREFIX}/escalations/{escalation_id}", headers=headers)

    def list_escalations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/escalations", headers=headers, params=params)

    def resolve_escalation(self, escalation_id, headers):
        return self._request("POST", f"{PREFIX}/escalations/{escalation_id}/resolve", headers=headers)

    def replace_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/escalations/{escalation_id}/replace",
                             payload, headers)

    # ─── Invoice ───────────────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)


api_client = ApiClient()
