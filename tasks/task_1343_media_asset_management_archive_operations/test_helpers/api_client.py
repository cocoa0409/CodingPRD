"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/archive/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- StaffMember ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/archive/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/archive/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/archive/staff-members/{staff_id}", headers=headers)

    # --- IngestBatch ---
    def create_ingest_batch(self, payload, headers):
        return self._request("POST", "/archive/ingest-batches", payload, headers)

    def list_ingest_batches(self, headers, params=None):
        return self._request("GET", "/archive/ingest-batches", headers=headers, params=params)

    def get_ingest_batch(self, batch_id, headers):
        return self._request("GET", f"/archive/ingest-batches/{batch_id}", headers=headers)

    def finalize_ingest_batch(self, batch_id, headers):
        return self._request("POST", f"/archive/ingest-batches/{batch_id}/finalize", {}, headers)

    # --- Asset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/archive/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/archive/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/archive/assets/{asset_id}", headers=headers)

    def patch_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/archive/assets/{asset_id}", payload, headers)

    def submit_metadata(self, asset_id, headers):
        return self._request("POST", f"/archive/assets/{asset_id}/submit-metadata", {}, headers)

    def metadata_approve(self, asset_id, headers):
        return self._request("POST", f"/archive/assets/{asset_id}/metadata-approve", {}, headers)

    def metadata_reject(self, asset_id, payload, headers):
        return self._request("POST", f"/archive/assets/{asset_id}/metadata-reject", payload, headers)

    def archive_asset(self, asset_id, headers):
        return self._request("POST", f"/archive/assets/{asset_id}/archive", {}, headers)

    def recatalog_asset(self, asset_id, headers):
        return self._request("POST", f"/archive/assets/{asset_id}/recatalog", {}, headers)

    def get_storage_cost(self, asset_id, headers):
        return self._request("GET", f"/archive/assets/{asset_id}/storage-cost", headers=headers)

    # --- ProxyRendition ---
    def create_proxy_rendition(self, payload, headers):
        return self._request("POST", "/archive/proxy-renditions", payload, headers)

    def get_proxy_rendition(self, rendition_id, headers):
        return self._request("GET", f"/archive/proxy-renditions/{rendition_id}", headers=headers)

    def list_proxy_renditions(self, headers, params=None):
        return self._request("GET", "/archive/proxy-renditions", headers=headers, params=params)

    def claim_proxy(self, rendition_id, headers):
        return self._request("POST", f"/archive/proxy-renditions/{rendition_id}/claim", {}, headers)

    def complete_proxy(self, rendition_id, headers):
        return self._request("POST", f"/archive/proxy-renditions/{rendition_id}/complete", {}, headers)

    def fail_proxy(self, rendition_id, payload, headers):
        return self._request("POST", f"/archive/proxy-renditions/{rendition_id}/fail", payload, headers)

    def retry_proxy(self, rendition_id, headers):
        return self._request("POST", f"/archive/proxy-renditions/{rendition_id}/retry", {}, headers)

    # --- RightsGrant ---
    def create_rights_grant(self, payload, headers):
        return self._request("POST", "/archive/rights-grants", payload, headers)

    def get_rights_grant(self, grant_id, headers):
        return self._request("GET", f"/archive/rights-grants/{grant_id}", headers=headers)

    def list_rights_grants(self, headers, params=None):
        return self._request("GET", "/archive/rights-grants", headers=headers, params=params)

    def revoke_rights_grant(self, grant_id, headers):
        return self._request("POST", f"/archive/rights-grants/{grant_id}/revoke", {}, headers)

    # --- LegalHold ---
    def create_legal_hold(self, payload, headers):
        return self._request("POST", "/archive/legal-holds", payload, headers)

    def get_legal_hold(self, hold_id, headers):
        return self._request("GET", f"/archive/legal-holds/{hold_id}", headers=headers)

    def list_legal_holds(self, headers, params=None):
        return self._request("GET", "/archive/legal-holds", headers=headers, params=params)

    def release_legal_hold(self, hold_id, headers):
        return self._request("POST", f"/archive/legal-holds/{hold_id}/release", {}, headers)

    # --- RetentionPolicy ---
    def create_retention_policy(self, payload, headers):
        return self._request("POST", "/archive/retention-policies", payload, headers)

    def list_retention_policies(self, headers, params=None):
        return self._request("GET", "/archive/retention-policies", headers=headers, params=params)

    # --- DisposalOrder ---
    def create_disposal_order(self, payload, headers):
        return self._request("POST", "/archive/disposal-orders", payload, headers)

    def list_disposal_orders(self, headers, params=None):
        return self._request("GET", "/archive/disposal-orders", headers=headers, params=params)

    def get_disposal_order(self, order_id, headers):
        return self._request("GET", f"/archive/disposal-orders/{order_id}", headers=headers)

    def submit_disposal_order(self, order_id, headers):
        return self._request("POST", f"/archive/disposal-orders/{order_id}/submit", {}, headers)

    def approve_disposal_order(self, order_id, headers):
        return self._request("POST", f"/archive/disposal-orders/{order_id}/approve", {}, headers)

    def reject_disposal_order(self, order_id, payload, headers):
        return self._request("POST", f"/archive/disposal-orders/{order_id}/reject", payload, headers)

    def resubmit_disposal_order(self, order_id, headers):
        return self._request("POST", f"/archive/disposal-orders/{order_id}/resubmit", {}, headers)

    def execute_disposal_order(self, order_id, headers):
        return self._request("POST", f"/archive/disposal-orders/{order_id}/execute", {}, headers)

    def withdraw_disposal_order(self, order_id, headers):
        return self._request("POST", f"/archive/disposal-orders/{order_id}/withdraw", {}, headers)

    # --- RetrievalRequest ---
    def create_retrieval_request(self, payload, headers):
        return self._request("POST", "/archive/retrieval-requests", payload, headers)

    def list_retrieval_requests(self, headers, params=None):
        return self._request("GET", "/archive/retrieval-requests", headers=headers, params=params)

    def get_retrieval_request(self, request_id, headers):
        return self._request("GET", f"/archive/retrieval-requests/{request_id}", headers=headers)

    def start_review(self, request_id, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/start-review", {}, headers)

    def approve_retrieval_request(self, request_id, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/approve", {}, headers)

    def return_retrieval_request(self, request_id, payload, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/return", payload, headers)

    def reject_retrieval_request(self, request_id, payload, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/reject", payload, headers)

    def stage_complete_retrieval_request(self, request_id, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/stage-complete", {}, headers)

    def deliver_retrieval_request(self, request_id, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/deliver", {}, headers)

    def cancel_retrieval_request(self, request_id, headers):
        return self._request("POST", f"/archive/retrieval-requests/{request_id}/cancel", {}, headers)

    # --- UsageEvent ---
    def create_usage_event(self, payload, headers):
        return self._request("POST", "/archive/usage-events", payload, headers)

    def get_usage_event(self, event_id, headers):
        return self._request("GET", f"/archive/usage-events/{event_id}", headers=headers)

    def list_usage_events(self, headers, params=None):
        return self._request("GET", "/archive/usage-events", headers=headers, params=params)

    def verify_usage_event(self, event_id, headers):
        return self._request("POST", f"/archive/usage-events/{event_id}/verify", {}, headers)

    def dispute_usage_event(self, event_id, payload, headers):
        return self._request("POST", f"/archive/usage-events/{event_id}/dispute", payload, headers)

    def resubmit_usage_event(self, event_id, headers):
        return self._request("POST", f"/archive/usage-events/{event_id}/resubmit", {}, headers)

    # --- RoyaltyStatement ---
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/archive/royalty-statements", payload, headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/archive/royalty-statements", headers=headers, params=params)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/archive/royalty-statements/{statement_id}", headers=headers)

    def close_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/archive/royalty-statements/{statement_id}/close", {}, headers)

    def reopen_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/archive/royalty-statements/{statement_id}/reopen", {}, headers)

    def post_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/archive/royalty-statements/{statement_id}/post", {}, headers)

    # --- MigrationJob ---
    def create_migration_job(self, payload, headers):
        return self._request("POST", "/archive/migration-jobs", payload, headers)

    def get_migration_job(self, job_id, headers):
        return self._request("GET", f"/archive/migration-jobs/{job_id}", headers=headers)

    def list_migration_jobs(self, headers, params=None):
        return self._request("GET", "/archive/migration-jobs", headers=headers, params=params)

    def start_migration_job(self, job_id, headers):
        return self._request("POST", f"/archive/migration-jobs/{job_id}/start", {}, headers)

    def complete_migration_job(self, job_id, payload, headers):
        return self._request("POST", f"/archive/migration-jobs/{job_id}/complete", payload, headers)

    def fail_migration_job(self, job_id, payload, headers):
        return self._request("POST", f"/archive/migration-jobs/{job_id}/fail", payload, headers)

    def retry_migration_job(self, job_id, headers):
        return self._request("POST", f"/archive/migration-jobs/{job_id}/retry", {}, headers)

    def cancel_migration_job(self, job_id, headers):
        return self._request("POST", f"/archive/migration-jobs/{job_id}/cancel", {}, headers)

    # --- DigitizationTicket ---
    def create_digitization_ticket(self, payload, headers):
        return self._request("POST", "/archive/digitization-tickets", payload, headers)

    def get_digitization_ticket(self, ticket_id, headers):
        return self._request("GET", f"/archive/digitization-tickets/{ticket_id}", headers=headers)

    def list_digitization_tickets(self, headers, params=None):
        return self._request("GET", "/archive/digitization-tickets", headers=headers, params=params)

    def assign_digitization_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/archive/digitization-tickets/{ticket_id}/assign", payload, headers)

    def auto_assign_digitization_ticket(self, payload, headers):
        return self._request("POST", "/archive/digitization-tickets/auto-assign", payload, headers)

    def start_digitization_ticket(self, ticket_id, headers):
        return self._request("POST", f"/archive/digitization-tickets/{ticket_id}/start", {}, headers)

    def submit_qc_digitization_ticket(self, ticket_id, headers):
        return self._request("POST", f"/archive/digitization-tickets/{ticket_id}/submit-qc", {}, headers)

    def qc_pass_digitization_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/archive/digitization-tickets/{ticket_id}/qc-pass", payload, headers)

    def qc_fail_digitization_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/archive/digitization-tickets/{ticket_id}/qc-fail", payload, headers)

    def cancel_digitization_ticket(self, ticket_id, headers):
        return self._request("POST", f"/archive/digitization-tickets/{ticket_id}/cancel", {}, headers)

    # --- Workstation ---
    def create_workstation(self, payload, headers):
        return self._request("POST", "/archive/workstations", payload, headers)

    def get_workstation(self, workstation_id, headers):
        return self._request("GET", f"/archive/workstations/{workstation_id}", headers=headers)

    def list_workstations(self, headers, params=None):
        return self._request("GET", "/archive/workstations", headers=headers, params=params)

    def patch_workstation(self, workstation_id, payload, headers):
        return self._request("PATCH", f"/archive/workstations/{workstation_id}", payload, headers)


api_client = ApiClient()
