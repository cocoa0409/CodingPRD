"""API client: one method per endpoint defined in the PRD (PRD 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD 2.4) -----------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Clients ----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # --- Engagements ------------------------------------------------------
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def qualify_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/qualify", payload, headers
        )

    def issue_sow(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/sow", payload, headers)

    def sign_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/sign", payload, headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/close", {}, headers)

    def get_burn_rate(self, engagement_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/burn-rate", headers=headers
        )

    # --- Milestones -------------------------------------------------------
    def create_milestone(self, payload, headers):
        return self._request("POST", "/milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/milestones", headers=headers, params=params)

    # --- Sprints ----------------------------------------------------------
    def create_sprint(self, payload, headers):
        return self._request("POST", "/sprints", payload, headers)

    def get_sprint(self, sprint_id, headers):
        return self._request("GET", f"/sprints/{sprint_id}", headers=headers)

    def list_sprints(self, headers, params=None):
        return self._request("GET", "/sprints", headers=headers, params=params)

    def transition_sprint(self, sprint_id, target_status, headers):
        return self._request(
            "POST",
            f"/sprints/{sprint_id}/transition",
            {"target_status": target_status},
            headers,
        )

    # --- Tickets ----------------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def transition_ticket(self, ticket_id, target_status, headers, note=None):
        payload = {"target_status": target_status}
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/tickets/{ticket_id}/transition", payload, headers)

    def block_ticket(self, ticket_id, blocking_ticket_id, headers):
        return self._request(
            "POST",
            f"/tickets/{ticket_id}/block",
            {"blocking_ticket_id": blocking_ticket_id},
            headers,
        )

    # --- Time entries -----------------------------------------------------
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def review_time_entry(self, time_entry_id, decision, headers, note=None):
        payload = {"decision": decision}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST", f"/time-entries/{time_entry_id}/review", payload, headers
        )

    def reverse_time_entry(self, time_entry_id, reason, headers):
        return self._request(
            "POST", f"/time-entries/{time_entry_id}/reverse", {"reason": reason}, headers
        )

    # --- Change requests --------------------------------------------------
    def create_change_request(self, payload, headers):
        return self._request("POST", "/change-requests", payload, headers)

    def get_change_request(self, cr_id, headers):
        return self._request("GET", f"/change-requests/{cr_id}", headers=headers)

    def list_change_requests(self, headers, params=None):
        return self._request("GET", "/change-requests", headers=headers, params=params)

    def submit_change_request(self, cr_id, headers):
        return self._request("POST", f"/change-requests/{cr_id}/submit", {}, headers)

    def decide_change_request(self, cr_id, action, headers, note=None):
        payload = {"action": action}
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/change-requests/{cr_id}/decision", payload, headers)

    # --- Releases ---------------------------------------------------------
    def create_release(self, payload, headers):
        return self._request("POST", "/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/releases/{release_id}", headers=headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/releases", headers=headers, params=params)

    def record_qa_result(self, release_id, outcome, defect_count, headers):
        return self._request(
            "POST",
            f"/releases/{release_id}/qa-result",
            {"outcome": outcome, "defect_count": defect_count},
            headers,
        )

    def decide_acceptance(self, release_id, action, headers, note=None):
        payload = {"action": action}
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/releases/{release_id}/acceptance", payload, headers)

    def deploy_release(self, release_id, environment, headers):
        return self._request(
            "POST", f"/releases/{release_id}/deploy", {"environment": environment}, headers
        )

    # --- Invoices ---------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, paid_amount, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/pay", {"paid_amount": paid_amount}, headers
        )

    def void_invoice(self, invoice_id, reason, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/void", {"reason": reason}, headers
        )

    # --- Retainers & support ----------------------------------------------
    def create_retainer(self, payload, headers):
        return self._request("POST", "/retainers", payload, headers)

    def get_retainer(self, retainer_id, headers):
        return self._request("GET", f"/retainers/{retainer_id}", headers=headers)

    def list_retainers(self, headers, params=None):
        return self._request("GET", "/retainers", headers=headers, params=params)

    def create_support_incident(self, payload, headers):
        return self._request("POST", "/support-incidents", payload, headers)

    def get_support_incident(self, incident_id, headers):
        return self._request(
            "GET", f"/support-incidents/{incident_id}", headers=headers
        )

    def list_support_incidents(self, headers, params=None):
        return self._request("GET", "/support-incidents", headers=headers, params=params)

    def respond_incident(self, incident_id, headers, note=None):
        payload = {}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST", f"/support-incidents/{incident_id}/respond", payload, headers
        )

    def resolve_incident(self, incident_id, resolution_note, headers):
        return self._request(
            "POST",
            f"/support-incidents/{incident_id}/resolve",
            {"resolution_note": resolution_note},
            headers,
        )


api_client = ApiClient()
