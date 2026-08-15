"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/pdm"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc", payload, headers)

    # --- RosterSource ---
    def create_roster_source(self, payload, headers):
        return self._request("POST", f"{P}/roster-sources", payload, headers)

    def list_roster_sources(self, headers, params=None):
        return self._request("GET", f"{P}/roster-sources", headers=headers, params=params)

    def get_roster_source(self, source_id, headers):
        return self._request("GET", f"{P}/roster-sources/{source_id}", headers=headers)

    def patch_roster_source(self, source_id, payload, headers):
        return self._request("PATCH", f"{P}/roster-sources/{source_id}", payload, headers)

    def suspend_roster_source(self, source_id, headers):
        return self._request("POST", f"{P}/roster-sources/{source_id}/suspend", {}, headers)

    def resume_roster_source(self, source_id, headers):
        return self._request("POST", f"{P}/roster-sources/{source_id}/resume", {}, headers)

    def retire_roster_source(self, source_id, headers):
        return self._request("POST", f"{P}/roster-sources/{source_id}/retire", {}, headers)

    # --- RosterFile ---
    def create_roster_file(self, payload, headers):
        return self._request("POST", f"{P}/roster-files", payload, headers)

    def list_roster_files(self, headers, params=None):
        return self._request("GET", f"{P}/roster-files", headers=headers, params=params)

    def get_roster_file(self, file_id, headers):
        return self._request("GET", f"{P}/roster-files/{file_id}", headers=headers)

    def parse_roster_file(self, file_id, headers):
        return self._request("POST", f"{P}/roster-files/{file_id}/parse", {}, headers)

    def normalize_roster_file(self, file_id, headers):
        return self._request("POST", f"{P}/roster-files/{file_id}/normalize", {}, headers)

    def validate_roster_file(self, file_id, headers):
        return self._request("POST", f"{P}/roster-files/{file_id}/validate", {}, headers)

    def commit_roster_file(self, file_id, payload, headers):
        return self._request("POST", f"{P}/roster-files/{file_id}/commit", payload, headers)

    def reject_roster_file(self, file_id, headers):
        return self._request("POST", f"{P}/roster-files/{file_id}/reject", {}, headers)

    def supersede_roster_file(self, file_id, headers):
        return self._request("POST", f"{P}/roster-files/{file_id}/supersede", {}, headers)

    # --- RosterRow ---
    def list_file_roster_rows(self, file_id, headers, params=None):
        return self._request(
            "GET", f"{P}/roster-files/{file_id}/roster-rows", headers=headers, params=params
        )

    def get_roster_row(self, row_id, headers):
        return self._request("GET", f"{P}/roster-rows/{row_id}", headers=headers)

    def list_roster_rows(self, headers, params=None):
        return self._request("GET", f"{P}/roster-rows", headers=headers, params=params)

    def link_roster_row(self, row_id, payload, headers):
        return self._request("POST", f"{P}/roster-rows/{row_id}/link", payload, headers)

    def spawn_new_roster_row(self, row_id, headers):
        return self._request("POST", f"{P}/roster-rows/{row_id}/spawn-new", {}, headers)

    def reject_roster_row(self, row_id, payload, headers):
        return self._request("POST", f"{P}/roster-rows/{row_id}/reject", payload, headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", f"{P}/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", f"{P}/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"{P}/providers/{provider_id}", headers=headers)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"{P}/providers/{provider_id}/suspend", {}, headers)

    def reinstate_provider(self, provider_id, headers):
        return self._request("POST", f"{P}/providers/{provider_id}/reinstate", {}, headers)

    def terminate_provider(self, provider_id, headers):
        return self._request("POST", f"{P}/providers/{provider_id}/terminate", {}, headers)

    # --- ProviderAttribute ---
    def create_provider_attribute(self, provider_id, payload, headers):
        return self._request(
            "POST", f"{P}/providers/{provider_id}/attributes", payload, headers
        )

    def list_provider_attributes(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"{P}/providers/{provider_id}/attributes", headers=headers, params=params
        )

    def get_provider_attribute(self, attribute_id, headers):
        return self._request(
            "GET", f"{P}/provider-attributes/{attribute_id}", headers=headers
        )

    def list_all_provider_attributes(self, headers, params=None):
        return self._request("GET", f"{P}/provider-attributes", headers=headers, params=params)

    def patch_provider_attribute(self, attribute_id, payload, headers):
        return self._request(
            "PATCH", f"{P}/provider-attributes/{attribute_id}", payload, headers
        )

    def approve_retro_attribute(self, attribute_id, payload, headers):
        return self._request(
            "POST", f"{P}/provider-attributes/{attribute_id}/approve-retro", payload, headers
        )

    def void_attribute(self, attribute_id, headers):
        return self._request(
            "POST", f"{P}/provider-attributes/{attribute_id}/void", {}, headers
        )

    # --- ProviderAlias ---
    def list_provider_aliases(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"{P}/providers/{provider_id}/aliases", headers=headers, params=params
        )

    def unlink_provider_alias(self, alias_id, headers):
        return self._request(
            "POST", f"{P}/provider-aliases/{alias_id}/unlink", {}, headers
        )

    # --- AttributeConflict ---
    def list_attribute_conflicts(self, headers, params=None):
        return self._request("GET", f"{P}/attribute-conflicts", headers=headers, params=params)

    def get_attribute_conflict(self, conflict_id, headers):
        return self._request("GET", f"{P}/attribute-conflicts/{conflict_id}", headers=headers)

    def resolve_attribute_conflict(self, conflict_id, payload, headers):
        return self._request(
            "POST", f"{P}/attribute-conflicts/{conflict_id}/resolve", payload, headers
        )

    def escalate_attribute_conflict(self, conflict_id, headers):
        return self._request(
            "POST", f"{P}/attribute-conflicts/{conflict_id}/escalate", {}, headers
        )

    # --- DistributionTarget ---
    def create_distribution_target(self, payload, headers):
        return self._request("POST", f"{P}/distribution-targets", payload, headers)

    def list_distribution_targets(self, headers, params=None):
        return self._request(
            "GET", f"{P}/distribution-targets", headers=headers, params=params
        )

    def disable_distribution_target(self, target_id, headers):
        return self._request(
            "POST", f"{P}/distribution-targets/{target_id}/disable", {}, headers
        )

    # --- DistributionBatch ---
    def create_distribution_batch(self, payload, headers):
        return self._request("POST", f"{P}/distribution-batches", payload, headers)

    def list_distribution_batches(self, headers, params=None):
        return self._request(
            "GET", f"{P}/distribution-batches", headers=headers, params=params
        )

    def get_distribution_batch(self, batch_id, headers):
        return self._request("GET", f"{P}/distribution-batches/{batch_id}", headers=headers)

    def list_batch_items(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"{P}/distribution-batches/{batch_id}/items", headers=headers, params=params
        )

    def list_provider_distribution_items(self, provider_id, headers, params=None):
        return self._request(
            "GET",
            f"{P}/providers/{provider_id}/distribution-items",
            headers=headers,
            params=params,
        )

    def publish_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{P}/distribution-batches/{batch_id}/publish", {}, headers
        )

    def ack_batch(self, batch_id, headers):
        return self._request("POST", f"{P}/distribution-batches/{batch_id}/ack", {}, headers)

    def fail_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{P}/distribution-batches/{batch_id}/fail", payload, headers
        )

    def discard_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{P}/distribution-batches/{batch_id}/discard", {}, headers
        )

    # --- AttestationCampaign ---
    def create_attestation_campaign(self, payload, headers):
        return self._request("POST", f"{P}/attestation-campaigns", payload, headers)

    def list_attestation_campaigns(self, headers, params=None):
        return self._request(
            "GET", f"{P}/attestation-campaigns", headers=headers, params=params
        )

    def get_attestation_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"{P}/attestation-campaigns/{campaign_id}", headers=headers
        )

    def open_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{P}/attestation-campaigns/{campaign_id}/open", {}, headers
        )

    def close_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{P}/attestation-campaigns/{campaign_id}/close", {}, headers
        )

    # --- AttestationRequest ---
    def create_attestation_request(self, campaign_id, payload, headers):
        return self._request(
            "POST",
            f"{P}/attestation-campaigns/{campaign_id}/attestation-requests",
            payload,
            headers,
        )

    def list_campaign_requests(self, campaign_id, headers, params=None):
        return self._request(
            "GET",
            f"{P}/attestation-campaigns/{campaign_id}/attestation-requests",
            headers=headers,
            params=params,
        )

    def list_attestation_requests(self, headers, params=None):
        return self._request(
            "GET", f"{P}/attestation-requests", headers=headers, params=params
        )

    def get_attestation_request(self, request_id, headers):
        return self._request("GET", f"{P}/attestation-requests/{request_id}", headers=headers)

    def list_provider_attestation_requests(self, provider_id, headers, params=None):
        return self._request(
            "GET",
            f"{P}/providers/{provider_id}/attestation-requests",
            headers=headers,
            params=params,
        )

    def send_attestation_request(self, request_id, headers):
        return self._request(
            "POST", f"{P}/attestation-requests/{request_id}/send", {}, headers
        )

    def respond_attestation_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/attestation-requests/{request_id}/respond", payload, headers
        )

    def escalate_attestation_request(self, request_id, headers):
        return self._request(
            "POST", f"{P}/attestation-requests/{request_id}/escalate", {}, headers
        )

    def withdraw_attestation_request(self, request_id, headers):
        return self._request(
            "POST", f"{P}/attestation-requests/{request_id}/withdraw", {}, headers
        )

    def sweep_attestation_requests(self, headers):
        return self._request("POST", f"{P}/attestation-requests/sweep", {}, headers)

    # --- DataQualityScore ---
    def list_provider_quality_scores(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"{P}/providers/{provider_id}/quality-scores", headers=headers, params=params
        )

    def recompute_quality_score(self, provider_id, headers):
        return self._request(
            "POST", f"{P}/providers/{provider_id}/quality-scores/recompute", {}, headers
        )

    def list_quality_scores(self, headers, params=None):
        return self._request("GET", f"{P}/quality-scores", headers=headers, params=params)

    def get_quality_score(self, score_id, headers):
        return self._request("GET", f"{P}/quality-scores/{score_id}", headers=headers)

    # --- ProviderMerge ---
    def create_provider_merge(self, payload, headers):
        return self._request("POST", f"{P}/provider-merges", payload, headers)

    def list_provider_merges(self, headers, params=None):
        return self._request("GET", f"{P}/provider-merges", headers=headers, params=params)

    def get_provider_merge(self, merge_id, headers):
        return self._request("GET", f"{P}/provider-merges/{merge_id}", headers=headers)

    def list_provider_merge_records(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"{P}/providers/{provider_id}/merge-records", headers=headers, params=params
        )


api_client = ApiClient()
