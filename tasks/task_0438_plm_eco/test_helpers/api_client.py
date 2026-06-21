"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/plm/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/plm/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/plm/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/plm/suppliers", headers=headers, params=params)

    # --- Part ---
    def create_part(self, payload, headers):
        return self._request("POST", "/plm/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/plm/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/plm/parts", headers=headers, params=params)

    def where_used(self, part_id, headers):
        return self._request("GET", f"/plm/parts/{part_id}/where-used", headers=headers)

    # --- PartRevision ---
    def create_revision(self, part_id, payload, headers):
        return self._request("POST", f"/plm/parts/{part_id}/revisions", payload, headers)

    def list_part_revisions(self, part_id, headers, params=None):
        return self._request(
            "GET", f"/plm/parts/{part_id}/revisions", headers=headers, params=params
        )

    def get_revision(self, revision_id, headers):
        return self._request("GET", f"/plm/part-revisions/{revision_id}", headers=headers)

    def list_revisions(self, headers, params=None):
        return self._request("GET", "/plm/part-revisions", headers=headers, params=params)

    def get_revision_cost(self, revision_id, headers):
        return self._request(
            "GET", f"/plm/part-revisions/{revision_id}/cost", headers=headers
        )

    def submit_revision_review(self, revision_id, headers):
        return self._request(
            "POST", f"/plm/part-revisions/{revision_id}/submit-review", {}, headers
        )

    def return_revision_to_work(self, revision_id, headers):
        return self._request(
            "POST", f"/plm/part-revisions/{revision_id}/return-to-work", {}, headers
        )

    # --- BomLine ---
    def add_bom_line(self, revision_id, payload, headers):
        return self._request(
            "POST", f"/plm/part-revisions/{revision_id}/bom-lines", payload, headers
        )

    def list_revision_bom_lines(self, revision_id, headers, params=None):
        return self._request(
            "GET",
            f"/plm/part-revisions/{revision_id}/bom-lines",
            headers=headers,
            params=params,
        )

    def get_bom_line(self, bom_line_id, headers):
        return self._request("GET", f"/plm/bom-lines/{bom_line_id}", headers=headers)

    def list_bom_lines(self, headers, params=None):
        return self._request("GET", "/plm/bom-lines", headers=headers, params=params)

    # --- EngineeringChangeRequest ---
    def create_change_request(self, payload, headers):
        return self._request("POST", "/plm/change-requests", payload, headers)

    def get_change_request(self, ecr_id, headers):
        return self._request("GET", f"/plm/change-requests/{ecr_id}", headers=headers)

    def list_change_requests(self, headers, params=None):
        return self._request(
            "GET", "/plm/change-requests", headers=headers, params=params
        )

    def submit_change_request(self, ecr_id, headers):
        return self._request(
            "POST", f"/plm/change-requests/{ecr_id}/submit", {}, headers
        )

    def approve_change_request(self, ecr_id, headers):
        return self._request(
            "POST", f"/plm/change-requests/{ecr_id}/approve", {}, headers
        )

    def reject_change_request(self, ecr_id, headers):
        return self._request(
            "POST", f"/plm/change-requests/{ecr_id}/reject", {}, headers
        )

    def reopen_change_request(self, ecr_id, headers):
        return self._request(
            "POST", f"/plm/change-requests/{ecr_id}/reopen", {}, headers
        )

    # --- EngineeringChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/plm/change-orders", payload, headers)

    def get_change_order(self, eco_id, headers):
        return self._request("GET", f"/plm/change-orders/{eco_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/plm/change-orders", headers=headers, params=params)

    def add_affected_item(self, eco_id, payload, headers):
        return self._request(
            "POST", f"/plm/change-orders/{eco_id}/affected-items", payload, headers
        )

    def list_eco_affected_items(self, eco_id, headers, params=None):
        return self._request(
            "GET",
            f"/plm/change-orders/{eco_id}/affected-items",
            headers=headers,
            params=params,
        )

    def get_affected_item(self, item_id, headers):
        return self._request("GET", f"/plm/affected-items/{item_id}", headers=headers)

    def list_affected_items(self, headers, params=None):
        return self._request("GET", "/plm/affected-items", headers=headers, params=params)

    def add_approval_task(self, eco_id, payload, headers):
        return self._request(
            "POST", f"/plm/change-orders/{eco_id}/approval-tasks", payload, headers
        )

    def list_eco_approval_tasks(self, eco_id, headers, params=None):
        return self._request(
            "GET",
            f"/plm/change-orders/{eco_id}/approval-tasks",
            headers=headers,
            params=params,
        )

    def get_approval_task(self, task_id, headers):
        return self._request("GET", f"/plm/approval-tasks/{task_id}", headers=headers)

    def submit_eco_for_approval(self, eco_id, headers):
        return self._request(
            "POST", f"/plm/change-orders/{eco_id}/submit-for-approval", {}, headers
        )

    def recall_change_order(self, eco_id, headers):
        return self._request(
            "POST", f"/plm/change-orders/{eco_id}/recall", {}, headers
        )

    def approve_task(self, task_id, headers):
        return self._request(
            "POST", f"/plm/approval-tasks/{task_id}/approve", {}, headers
        )

    def reject_task(self, task_id, headers):
        return self._request(
            "POST", f"/plm/approval-tasks/{task_id}/reject", {}, headers
        )

    def make_change_order_effective(self, eco_id, headers):
        return self._request(
            "POST", f"/plm/change-orders/{eco_id}/make-effective", {}, headers
        )

    def cancel_change_order(self, eco_id, headers):
        return self._request(
            "POST", f"/plm/change-orders/{eco_id}/cancel", {}, headers
        )

    # --- Document ---
    def create_document(self, payload, headers):
        return self._request("POST", "/plm/documents", payload, headers)

    def get_document(self, doc_id, headers):
        return self._request("GET", f"/plm/documents/{doc_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/plm/documents", headers=headers, params=params)

    def submit_document_review(self, doc_id, headers):
        return self._request(
            "POST", f"/plm/documents/{doc_id}/submit-review", {}, headers
        )

    def return_document_to_work(self, doc_id, headers):
        return self._request(
            "POST", f"/plm/documents/{doc_id}/return-to-work", {}, headers
        )

    def release_document(self, doc_id, headers):
        return self._request("POST", f"/plm/documents/{doc_id}/release", {}, headers)

    def obsolete_document(self, doc_id, headers):
        return self._request("POST", f"/plm/documents/{doc_id}/obsolete", {}, headers)

    # --- Deviation ---
    def create_deviation(self, payload, headers):
        return self._request("POST", "/plm/deviations", payload, headers)

    def get_deviation(self, dev_id, headers):
        return self._request("GET", f"/plm/deviations/{dev_id}", headers=headers)

    def list_deviations(self, headers, params=None):
        return self._request("GET", "/plm/deviations", headers=headers, params=params)

    def submit_deviation(self, dev_id, headers):
        return self._request("POST", f"/plm/deviations/{dev_id}/submit", {}, headers)

    def grant_deviation(self, dev_id, headers):
        return self._request("POST", f"/plm/deviations/{dev_id}/grant", {}, headers)

    def deny_deviation(self, dev_id, headers):
        return self._request("POST", f"/plm/deviations/{dev_id}/deny", {}, headers)

    def expire_deviation(self, dev_id, headers):
        return self._request("POST", f"/plm/deviations/{dev_id}/expire", {}, headers)

    # --- SupplierChangeNotice ---
    def create_pcn(self, payload, headers):
        return self._request("POST", "/plm/supplier-change-notices", payload, headers)

    def get_pcn(self, pcn_id, headers):
        return self._request(
            "GET", f"/plm/supplier-change-notices/{pcn_id}", headers=headers
        )

    def list_pcns(self, headers, params=None):
        return self._request(
            "GET", "/plm/supplier-change-notices", headers=headers, params=params
        )

    def assess_pcn(self, pcn_id, headers):
        return self._request(
            "POST", f"/plm/supplier-change-notices/{pcn_id}/assess", {}, headers
        )

    def accept_pcn(self, pcn_id, headers):
        return self._request(
            "POST", f"/plm/supplier-change-notices/{pcn_id}/accept", {}, headers
        )

    def reject_pcn(self, pcn_id, headers):
        return self._request(
            "POST", f"/plm/supplier-change-notices/{pcn_id}/reject", {}, headers
        )

    # --- SerializedUnit ---
    def create_serialized_unit(self, payload, headers):
        return self._request("POST", "/plm/serialized-units", payload, headers)

    def get_serialized_unit(self, unit_id, headers):
        return self._request(
            "GET", f"/plm/serialized-units/{unit_id}", headers=headers
        )

    def list_serialized_units(self, headers, params=None):
        return self._request(
            "GET", "/plm/serialized-units", headers=headers, params=params
        )

    def build_serialized_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/plm/serialized-units/{unit_id}/build", {}, headers
        )

    def ship_serialized_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/plm/serialized-units/{unit_id}/ship", {}, headers
        )

    def flag_unit_nonconforming(self, unit_id, headers):
        return self._request(
            "POST", f"/plm/serialized-units/{unit_id}/flag-nonconforming", {}, headers
        )


api_client = ApiClient()
