"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the inherited _request() does the HTTP plumbing.
GET methods pass filters/pagination via params; POST methods pass a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Crew members ─────────────────────────────────
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/crew-members", headers=headers, params=params)

    def get_crew_member_risk_score(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}/risk-score", headers=headers)

    # ─── Instruments ──────────────────────────────────
    def create_instrument(self, payload, headers):
        return self._request("POST", "/instruments", payload, headers)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/instruments/{instrument_id}", headers=headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/instruments", headers=headers, params=params)

    # ─── Survey orders ────────────────────────────────
    def create_survey_order(self, payload, headers):
        return self._request("POST", "/survey-orders", payload, headers)

    def get_survey_order(self, order_id, headers):
        return self._request("GET", f"/survey-orders/{order_id}", headers=headers)

    def list_survey_orders(self, headers, params=None):
        return self._request("GET", "/survey-orders", headers=headers, params=params)

    def start_research(self, order_id, headers, payload=None):
        return self._request("POST", f"/survey-orders/{order_id}/start-research", payload or {}, headers)

    def clear_research(self, order_id, headers, payload=None):
        return self._request("POST", f"/survey-orders/{order_id}/clear-research", payload or {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/survey-orders/{order_id}/cancel", payload or {}, headers)

    # ─── Research packets ─────────────────────────────
    def create_research_packet(self, payload, headers):
        return self._request("POST", "/research-packets", payload, headers)

    def get_research_packet(self, packet_id, headers):
        return self._request("GET", f"/research-packets/{packet_id}", headers=headers)

    def list_research_packets(self, headers, params=None):
        return self._request("GET", "/research-packets", headers=headers, params=params)

    def begin_research_packet(self, packet_id, headers, payload=None):
        return self._request("POST", f"/research-packets/{packet_id}/begin", payload or {}, headers)

    def clear_research_packet(self, packet_id, headers, payload=None):
        return self._request("POST", f"/research-packets/{packet_id}/clear", payload or {}, headers)

    def hold_research_packet(self, packet_id, headers, payload=None):
        return self._request("POST", f"/research-packets/{packet_id}/hold", payload or {}, headers)

    # ─── Field assignments ────────────────────────────
    def create_field_assignment(self, payload, headers):
        return self._request("POST", "/field-assignments", payload, headers)

    def get_field_assignment(self, assignment_id, headers):
        return self._request("GET", f"/field-assignments/{assignment_id}", headers=headers)

    def list_field_assignments(self, headers, params=None):
        return self._request("GET", "/field-assignments", headers=headers, params=params)

    def start_field_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/field-assignments/{assignment_id}/start", payload or {}, headers)

    def complete_field_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/field-assignments/{assignment_id}/complete", payload or {}, headers)

    def cancel_field_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/field-assignments/{assignment_id}/cancel", payload or {}, headers)

    # ─── Instrument reservations ──────────────────────
    def create_instrument_reservation(self, payload, headers):
        return self._request("POST", "/instrument-reservations", payload, headers)

    def get_instrument_reservation(self, reservation_id, headers):
        return self._request("GET", f"/instrument-reservations/{reservation_id}", headers=headers)

    def list_instrument_reservations(self, headers, params=None):
        return self._request("GET", "/instrument-reservations", headers=headers, params=params)

    # ─── Data sets ────────────────────────────────────
    def create_data_set(self, payload, headers):
        return self._request("POST", "/data-sets", payload, headers)

    def get_data_set(self, dataset_id, headers):
        return self._request("GET", f"/data-sets/{dataset_id}", headers=headers)

    def list_data_sets(self, headers, params=None):
        return self._request("GET", "/data-sets", headers=headers, params=params)

    def reduce_data_set(self, dataset_id, headers, payload=None):
        return self._request("POST", f"/data-sets/{dataset_id}/reduce", payload or {}, headers)

    def accept_data_set(self, dataset_id, headers, payload=None):
        return self._request("POST", f"/data-sets/{dataset_id}/accept", payload or {}, headers)

    # ─── Plat drawings ────────────────────────────────
    def create_plat_drawing(self, payload, headers):
        return self._request("POST", "/plat-drawings", payload, headers)

    def get_plat_drawing(self, plat_id, headers):
        return self._request("GET", f"/plat-drawings/{plat_id}", headers=headers)

    def list_plat_drawings(self, headers, params=None):
        return self._request("GET", "/plat-drawings", headers=headers, params=params)

    def submit_plat_review(self, plat_id, headers, payload=None):
        return self._request("POST", f"/plat-drawings/{plat_id}/submit-review", payload or {}, headers)

    def seal_plat(self, plat_id, payload, headers):
        return self._request("POST", f"/plat-drawings/{plat_id}/seal", payload, headers)

    def resume_draft(self, plat_id, headers, payload=None):
        return self._request("POST", f"/plat-drawings/{plat_id}/resume-draft", payload or {}, headers)

    # ─── Revision requests ────────────────────────────
    def create_revision_request(self, payload, headers):
        return self._request("POST", "/revision-requests", payload, headers)

    def get_revision_request(self, revision_id, headers):
        return self._request("GET", f"/revision-requests/{revision_id}", headers=headers)

    def list_revision_requests(self, headers, params=None):
        return self._request("GET", "/revision-requests", headers=headers, params=params)

    def apply_revision(self, revision_id, headers, payload=None):
        return self._request("POST", f"/revision-requests/{revision_id}/apply", payload or {}, headers)

    def reject_revision(self, revision_id, headers, payload=None):
        return self._request("POST", f"/revision-requests/{revision_id}/reject", payload or {}, headers)

    # ─── Deliverables ─────────────────────────────────
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/deliverables", payload, headers)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/deliverables", headers=headers, params=params)

    def release_deliverable(self, deliverable_id, headers, payload=None):
        return self._request("POST", f"/deliverables/{deliverable_id}/release", payload or {}, headers)

    # ─── Invoices ─────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)


api_client = ApiClient()
