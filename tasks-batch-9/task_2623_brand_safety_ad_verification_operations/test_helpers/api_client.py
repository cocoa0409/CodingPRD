"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- advertisers ------------------------------------------------------
    def create_advertiser(self, payload, headers):
        return self._request("POST", "/advertisers", payload, headers)

    def get_advertiser(self, advertiser_id, headers):
        return self._request("GET", f"/advertisers/{advertiser_id}", headers=headers)

    # ---- publishers -------------------------------------------------------
    def create_publisher(self, payload, headers):
        return self._request("POST", "/publishers", payload, headers)

    def get_publisher(self, publisher_id, headers):
        return self._request("GET", f"/publishers/{publisher_id}", headers=headers)

    def change_publisher_status(self, publisher_id, payload, headers):
        return self._request(
            "POST", f"/publishers/{publisher_id}/status", payload, headers
        )

    def get_publisher_scorecard(self, publisher_id, headers):
        return self._request(
            "GET", f"/publishers/{publisher_id}/scorecard", headers=headers
        )

    # ---- methodology versions --------------------------------------------
    def create_methodology_version(self, payload, headers):
        return self._request("POST", "/methodology-versions", payload, headers)

    def get_methodology_version(self, version_id, headers):
        return self._request(
            "GET", f"/methodology-versions/{version_id}", headers=headers
        )

    def list_methodology_versions(self, headers, params=None):
        return self._request(
            "GET", "/methodology-versions", headers=headers, params=params
        )

    def conclude_audit(self, version_id, payload, headers):
        return self._request(
            "POST", f"/methodology-versions/{version_id}/audit-conclusion",
            payload, headers,
        )

    # ---- campaigns --------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    # ---- inventory lists --------------------------------------------------
    def create_inventory_list(self, payload, headers):
        return self._request("POST", "/inventory-lists", payload, headers)

    def get_inventory_list(self, list_id, headers):
        return self._request("GET", f"/inventory-lists/{list_id}", headers=headers)

    def list_inventory_lists(self, headers, params=None):
        return self._request("GET", "/inventory-lists", headers=headers, params=params)

    def create_list_entry(self, list_id, payload, headers):
        return self._request(
            "POST", f"/inventory-lists/{list_id}/entries", payload, headers
        )

    def list_list_entries(self, list_id, headers, params=None):
        return self._request(
            "GET", f"/inventory-lists/{list_id}/entries", headers=headers, params=params
        )

    def publish_inventory_list(self, list_id, headers, payload=None):
        return self._request(
            "POST", f"/inventory-lists/{list_id}/publish", payload or {}, headers
        )

    # ---- pre-bid segments -------------------------------------------------
    def create_pre_bid_segment(self, payload, headers):
        return self._request("POST", "/pre-bid-segments", payload, headers)

    def get_pre_bid_segment(self, segment_id, headers):
        return self._request("GET", f"/pre-bid-segments/{segment_id}", headers=headers)

    def list_pre_bid_segments(self, headers, params=None):
        return self._request(
            "GET", "/pre-bid-segments", headers=headers, params=params
        )

    def sync_pre_bid_segment(self, segment_id, headers, payload=None):
        return self._request(
            "POST", f"/pre-bid-segments/{segment_id}/sync", payload or {}, headers
        )

    # ---- pages ------------------------------------------------------------
    def create_page(self, payload, headers):
        return self._request("POST", "/pages", payload, headers)

    def get_page(self, page_id, headers):
        return self._request("GET", f"/pages/{page_id}", headers=headers)

    def list_pages(self, headers, params=None):
        return self._request("GET", "/pages", headers=headers, params=params)

    def get_pre_bid_decision(self, page_id, headers, params=None):
        return self._request(
            "GET", f"/pages/{page_id}/pre-bid-decision", headers=headers, params=params
        )

    # ---- page classifications ---------------------------------------------
    def create_page_classification(self, payload, headers):
        return self._request("POST", "/page-classifications", payload, headers)

    def get_page_classification(self, classification_id, headers):
        return self._request(
            "GET", f"/page-classifications/{classification_id}", headers=headers
        )

    def list_page_classifications(self, headers, params=None):
        return self._request(
            "GET", "/page-classifications", headers=headers, params=params
        )

    def review_page_classification(self, classification_id, payload, headers):
        return self._request(
            "POST", f"/page-classifications/{classification_id}/review",
            payload, headers,
        )

    # ---- appeals ----------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def submit_appeal_evidence(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/evidence", payload, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ---- measurement batches ----------------------------------------------
    def create_measurement_batch(self, payload, headers):
        return self._request("POST", "/measurement-batches", payload, headers)

    def get_measurement_batch(self, batch_id, headers):
        return self._request("GET", f"/measurement-batches/{batch_id}", headers=headers)

    def list_measurement_batches(self, headers, params=None):
        return self._request(
            "GET", "/measurement-batches", headers=headers, params=params
        )

    def score_measurement_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/measurement-batches/{batch_id}/score", payload or {}, headers
        )

    def certify_measurement_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/measurement-batches/{batch_id}/certify", payload or {}, headers
        )

    # ---- invalid-traffic findings -----------------------------------------
    def create_ivt_finding(self, payload, headers):
        return self._request("POST", "/ivt-findings", payload, headers)

    def get_ivt_finding(self, finding_id, headers):
        return self._request("GET", f"/ivt-findings/{finding_id}", headers=headers)

    def list_batch_ivt_findings(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/measurement-batches/{batch_id}/ivt-findings",
            headers=headers, params=params,
        )

    def confirm_ivt_finding(self, finding_id, headers, payload=None):
        return self._request(
            "POST", f"/ivt-findings/{finding_id}/confirm", payload or {}, headers
        )

    def retract_ivt_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/ivt-findings/{finding_id}/retract", payload, headers
        )

    # ---- refund claims ----------------------------------------------------
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/refund-claims", payload, headers)

    def get_refund_claim(self, claim_id, headers):
        return self._request("GET", f"/refund-claims/{claim_id}", headers=headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def review_refund_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/refund-claims/{claim_id}/review", payload or {}, headers
        )

    def approve_refund_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/refund-claims/{claim_id}/approve", payload or {}, headers
        )

    def reject_refund_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/refund-claims/{claim_id}/reject", payload, headers
        )

    def reverse_refund_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/refund-claims/{claim_id}/reverse", payload, headers
        )


api_client = ApiClient()
