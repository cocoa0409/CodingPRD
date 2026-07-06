"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Studio ----
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    # ---- Client ----
    def create_client(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/clients", payload, headers)

    def get_client(self, studio_id, client_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/clients/{client_id}", headers=headers
        )

    def list_clients(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/clients", headers=headers, params=params
        )

    def archive_client(self, studio_id, client_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/clients/{client_id}/archive", {}, headers
        )

    # ---- Project ----
    def create_project(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/projects", payload, headers)

    def get_project(self, studio_id, project_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/projects/{project_id}", headers=headers
        )

    def list_projects(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/projects", headers=headers, params=params
        )

    def record_deposit(self, studio_id, project_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/deposits", payload, headers
        )

    def activate_project(self, studio_id, project_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/activate", {}, headers
        )

    def advance_project(self, studio_id, project_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/advance", {}, headers
        )

    def complete_project(self, studio_id, project_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/complete", {}, headers
        )

    def cancel_project(self, studio_id, project_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/cancel", {}, headers
        )

    # ---- Moodboard ----
    def create_moodboard(self, studio_id, project_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/moodboards", payload, headers
        )

    def list_moodboards(self, studio_id, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/moodboards",
            headers=headers,
            params=params,
        )

    def get_moodboard(self, studio_id, project_id, moodboard_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/moodboards/{moodboard_id}",
            headers=headers,
        )

    def submit_moodboard(self, studio_id, project_id, moodboard_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/moodboards/{moodboard_id}/submit",
            {},
            headers,
        )

    def approve_moodboard(self, studio_id, project_id, moodboard_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/moodboards/{moodboard_id}/approve",
            {},
            headers,
        )

    def reject_moodboard(self, studio_id, project_id, moodboard_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/moodboards/{moodboard_id}/reject",
            {},
            headers,
        )

    # ---- Concept ----
    def create_concept(self, studio_id, project_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/concepts", payload, headers
        )

    def list_concepts(self, studio_id, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/concepts",
            headers=headers,
            params=params,
        )

    def get_concept(self, studio_id, project_id, concept_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/concepts/{concept_id}",
            headers=headers,
        )

    def present_concept(self, studio_id, project_id, concept_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/concepts/{concept_id}/present",
            {},
            headers,
        )

    def request_concept_revision(self, studio_id, project_id, concept_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/concepts/{concept_id}/request-revision",
            {},
            headers,
        )

    def approve_concept(self, studio_id, project_id, concept_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/concepts/{concept_id}/approve",
            {},
            headers,
        )

    def reject_concept(self, studio_id, project_id, concept_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/concepts/{concept_id}/reject",
            {},
            headers,
        )

    # ---- Milestone ----
    def create_milestone(self, studio_id, project_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/milestones", payload, headers
        )

    def list_milestones(self, studio_id, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/milestones",
            headers=headers,
            params=params,
        )

    def get_milestone(self, studio_id, project_id, milestone_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/milestones/{milestone_id}",
            headers=headers,
        )

    # ---- Invoice ----
    def create_invoice(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/invoices", payload, headers)

    def get_invoice(self, studio_id, invoice_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/invoices/{invoice_id}", headers=headers
        )

    def list_invoices(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/invoices", headers=headers, params=params
        )

    def mark_invoice_overdue(self, studio_id, invoice_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/invoices/{invoice_id}/mark-overdue", {}, headers
        )

    def pay_invoice(self, studio_id, invoice_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/invoices/{invoice_id}/pay", {}, headers
        )

    # ---- Deliverable ----
    def create_deliverable(self, studio_id, project_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/projects/{project_id}/deliverables", payload, headers
        )

    def list_deliverables(self, studio_id, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/deliverables",
            headers=headers,
            params=params,
        )

    def get_deliverable(self, studio_id, project_id, deliverable_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/projects/{project_id}/deliverables/{deliverable_id}",
            headers=headers,
        )

    def deliver_deliverable(self, studio_id, project_id, deliverable_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/deliverables/{deliverable_id}/deliver",
            {},
            headers,
        )

    def accept_deliverable(self, studio_id, project_id, deliverable_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/deliverables/{deliverable_id}/accept",
            {},
            headers,
        )

    def request_deliverable_revision(self, studio_id, project_id, deliverable_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/projects/{project_id}/deliverables/{deliverable_id}/request-revision",
            {},
            headers,
        )

    # ---- License ----
    def create_license(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/licenses", payload, headers)

    def get_license(self, studio_id, license_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/licenses/{license_id}", headers=headers
        )

    def list_licenses(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/licenses", headers=headers, params=params
        )

    def clear_license(self, studio_id, license_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/licenses/{license_id}/clear", {}, headers
        )

    # ---- ChangeOrder ----
    def create_change_order(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/change-orders", payload, headers)

    def get_change_order(self, studio_id, change_order_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/change-orders/{change_order_id}", headers=headers
        )

    def list_change_orders(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/change-orders", headers=headers, params=params
        )

    def approve_change_order(self, studio_id, change_order_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/change-orders/{change_order_id}/approve", {}, headers
        )

    def reject_change_order(self, studio_id, change_order_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/change-orders/{change_order_id}/reject", {}, headers
        )

    # ---- Retainer ----
    def create_retainer(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/retainers", payload, headers)

    def get_retainer(self, studio_id, retainer_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/retainers/{retainer_id}", headers=headers
        )

    def list_retainers(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/retainers", headers=headers, params=params
        )

    def pause_retainer(self, studio_id, retainer_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/retainers/{retainer_id}/pause", {}, headers
        )

    def resume_retainer(self, studio_id, retainer_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/retainers/{retainer_id}/resume", {}, headers
        )

    def cancel_retainer(self, studio_id, retainer_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/retainers/{retainer_id}/cancel", {}, headers
        )

    # ---- CareCycle ----
    def create_care_cycle(self, studio_id, retainer_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/retainers/{retainer_id}/care-cycles", payload, headers
        )

    def list_care_cycles(self, studio_id, retainer_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/retainers/{retainer_id}/care-cycles",
            headers=headers,
            params=params,
        )

    def get_care_cycle(self, studio_id, retainer_id, care_cycle_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/retainers/{retainer_id}/care-cycles/{care_cycle_id}",
            headers=headers,
        )

    def close_care_cycle(self, studio_id, retainer_id, care_cycle_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/retainers/{retainer_id}/care-cycles/{care_cycle_id}/close",
            {},
            headers,
        )

    def bill_care_cycle(self, studio_id, retainer_id, care_cycle_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/retainers/{retainer_id}/care-cycles/{care_cycle_id}/bill",
            {},
            headers,
        )


api_client = ApiClient()
