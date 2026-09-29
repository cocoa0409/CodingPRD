"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/circulation"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Publications and qualification policy
    # ------------------------------------------------------------------
    def create_publication(self, payload, headers):
        return self._request("POST", f"{PREFIX}/publications", payload, headers)

    def get_publication(self, publication_id, headers):
        return self._request(
            "GET", f"{PREFIX}/publications/{publication_id}", headers=headers
        )

    def create_qualification_rule(self, publication_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/publications/{publication_id}/qualification-rules",
            payload,
            headers,
        )

    def list_qualification_rules(self, publication_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/publications/{publication_id}/qualification-rules",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Recipient file
    # ------------------------------------------------------------------
    def create_subscriber(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscribers/{subscriber_id}", headers=headers
        )

    def list_subscribers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/subscribers", headers=headers, params=params
        )

    def record_undeliverable_event(self, subscriber_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/subscribers/{subscriber_id}/undeliverable-events",
            payload,
            headers,
        )

    def reclassify_subscriber(self, subscriber_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/subscribers/{subscriber_id}/reclassify",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Source documents
    # ------------------------------------------------------------------
    def create_source_document(self, subscriber_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/subscribers/{subscriber_id}/source-documents",
            payload,
            headers,
        )

    def list_source_documents(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscribers/{subscriber_id}/source-documents",
            headers=headers,
            params=params,
        )

    def purge_source_document(self, document_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/source-documents/{document_id}/purge",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Qualification requests
    # ------------------------------------------------------------------
    def create_qualification_request(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/qualification-requests", payload, headers
        )

    def get_qualification_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/qualification-requests/{request_id}", headers=headers
        )

    def list_qualification_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/qualification-requests", headers=headers, params=params
        )

    def review_qualification_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-requests/{request_id}/review",
            payload,
            headers,
        )

    def request_info_qualification_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-requests/{request_id}/request-info",
            payload,
            headers,
        )

    def resubmit_qualification_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-requests/{request_id}/resubmit",
            payload,
            headers,
        )

    def verify_qualification_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-requests/{request_id}/verify",
            payload,
            headers,
        )

    def reject_qualification_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-requests/{request_id}/reject",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Hygiene sweeps
    # ------------------------------------------------------------------
    def create_hygiene_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hygiene-runs", payload, headers)

    def list_hygiene_runs(self, publication_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/publications/{publication_id}/hygiene-runs",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Circulation statements
    # ------------------------------------------------------------------
    def create_statement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/statements/{statement_id}", headers=headers
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/statements", headers=headers, params=params
        )

    def recompute_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/recompute", payload, headers
        )

    def certify_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/certify", payload, headers
        )

    def settle_guarantees(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/statements/{statement_id}/settle-guarantees",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Audit engagements, sampling and findings
    # ------------------------------------------------------------------
    def create_audit_engagement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audit-engagements", payload, headers)

    def list_audit_engagements(self, statement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/statements/{statement_id}/audit-engagements",
            headers=headers,
            params=params,
        )

    def record_sample_verification(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-engagements/{engagement_id}/record-sample-verification",
            payload,
            headers,
        )

    def issue_report(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-engagements/{engagement_id}/issue-report",
            payload,
            headers,
        )

    def create_audit_finding(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audit-findings", payload, headers)

    def get_audit_finding(self, finding_id, headers):
        return self._request(
            "GET", f"{PREFIX}/audit-findings/{finding_id}", headers=headers
        )

    def list_audit_findings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/audit-findings", headers=headers, params=params
        )

    def respond_to_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-findings/{finding_id}/respond", payload, headers
        )

    def accept_finding_resolution(self, finding_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-findings/{finding_id}/accept-resolution",
            payload,
            headers,
        )

    def reject_finding_response(self, finding_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-findings/{finding_id}/reject-response",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Advertiser contracts and make-good obligations
    # ------------------------------------------------------------------
    def create_advertiser_contract(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/advertiser-contracts", payload, headers
        )

    def get_advertiser_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{PREFIX}/advertiser-contracts/{contract_id}", headers=headers
        )

    def list_advertiser_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/advertiser-contracts", headers=headers, params=params
        )

    def get_make_good(self, make_good_id, headers):
        return self._request(
            "GET", f"{PREFIX}/make-goods/{make_good_id}", headers=headers
        )

    def list_make_goods(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/make-goods", headers=headers, params=params
        )

    def offer_make_good(self, make_good_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/make-goods/{make_good_id}/offer", payload, headers
        )

    def accept_make_good(self, make_good_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/make-goods/{make_good_id}/accept", payload, headers
        )

    def waive_make_good(self, make_good_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/make-goods/{make_good_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------
    # Digital audience measurement
    # ------------------------------------------------------------------
    def create_digital_snapshot(self, publication_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/publications/{publication_id}/digital-snapshots",
            payload,
            headers,
        )

    def list_digital_snapshots(self, publication_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/publications/{publication_id}/digital-snapshots",
            headers=headers,
            params=params,
        )

    def validate_digital_snapshot(self, snapshot_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/digital-snapshots/{snapshot_id}/validate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Logical circulation clock (mounted outside the /circulation prefix)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Raw helpers for calls that deliberately omit identity headers
    # ------------------------------------------------------------------
    def raw_post(self, path, payload=None, headers=None):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
