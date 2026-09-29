"""One method per endpoint of PRD section 4.

Every method returns the raw `requests.Response` so tests can assert on the HTTP
status themselves.  No validation happens here.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ #
    # Logical clock
    # ------------------------------------------------------------------ #
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------ #
    # Retailers
    # ------------------------------------------------------------------ #
    def create_retailer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/retailers/{retailer_id}", None, headers)

    def list_retailers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/retailers", params, headers)

    # ------------------------------------------------------------------ #
    # Principals
    # ------------------------------------------------------------------ #
    def create_principal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/principals", payload, headers)

    def get_principal(self, principal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/principals/{principal_id}", None, headers)

    def list_principals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/principals", params, headers)

    def patch_principal(self, principal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/principals/{principal_id}", payload, headers)

    def set_principal_status(self, principal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/principals/{principal_id}/status", payload, headers)

    def get_commission_statement(self, principal_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/principals/{principal_id}/commission-statement", params, headers
        )

    # ------------------------------------------------------------------ #
    # Commission agreements
    # ------------------------------------------------------------------ #
    def create_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/commission-agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/commission-agreements/{agreement_id}", None, headers)

    def list_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/commission-agreements", params, headers)

    def activate_agreement(self, agreement_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/commission-agreements/{agreement_id}/activate", payload or {}, headers
        )

    def terminate_agreement(self, agreement_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/commission-agreements/{agreement_id}/terminate", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # Conflict rules
    # ------------------------------------------------------------------ #
    def create_conflict_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conflict-rules", payload, headers)

    def get_conflict_rule(self, conflict_rule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conflict-rules/{conflict_rule_id}", None, headers)

    def list_conflict_rules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conflict-rules", params, headers)

    def waive_conflict_rule(self, conflict_rule_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/conflict-rules/{conflict_rule_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Items and catalog
    # ------------------------------------------------------------------ #
    def create_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/items", payload, headers)

    def get_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/items/{item_id}", None, headers)

    def list_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/items", params, headers)

    def submit_catalog(self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/items/{item_id}/catalog-submissions", payload, headers)

    def decide_catalog(self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/items/{item_id}/catalog-decision", payload, headers)

    # ------------------------------------------------------------------ #
    # Category reviews
    # ------------------------------------------------------------------ #
    def create_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/category-reviews", payload, headers)

    def get_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/category-reviews/{review_id}", None, headers)

    def list_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/category-reviews", params, headers)

    def open_review(self, review_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/category-reviews/{review_id}/open", payload or {}, headers)

    def lock_review(self, review_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/category-reviews/{review_id}/lock", payload or {}, headers)

    def reopen_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/category-reviews/{review_id}/reopen", payload, headers)

    def decide_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/category-reviews/{review_id}/decide", payload, headers)

    # ------------------------------------------------------------------ #
    # Presentations
    # ------------------------------------------------------------------ #
    def create_presentation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/presentations", payload, headers)

    def get_presentation(self, presentation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/presentations/{presentation_id}", None, headers)

    def list_presentations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/presentations", params, headers)

    def submit_presentation(self, presentation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/presentations/{presentation_id}/submit", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # Slotting deals
    # ------------------------------------------------------------------ #
    def create_deal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/slotting-deals", payload, headers)

    def get_deal(self, deal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/slotting-deals/{deal_id}", None, headers)

    def list_deals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/slotting-deals", params, headers)

    def propose_deal(self, deal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/slotting-deals/{deal_id}/propose", payload, headers)

    def counter_deal(self, deal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/slotting-deals/{deal_id}/counter", payload, headers)

    def accept_deal(self, deal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/slotting-deals/{deal_id}/accept", payload, headers)

    def reject_deal(self, deal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/slotting-deals/{deal_id}/reject", payload, headers)

    # ------------------------------------------------------------------ #
    # Authorizations
    # ------------------------------------------------------------------ #
    def get_authorization(self, authorization_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/authorizations/{authorization_id}", None, headers)

    def list_authorizations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/authorizations", params, headers)

    def get_voids_report(self, authorization_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/authorizations/{authorization_id}/voids-report", None, headers
        )

    def discontinue_authorization(self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/discontinue", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Distribution ledger
    # ------------------------------------------------------------------ #
    def post_snapshot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/distribution-snapshots", payload, headers)

    def get_snapshot(self, snapshot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/distribution-snapshots/{snapshot_id}", None, headers)

    def list_snapshots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/distribution-snapshots", params, headers)

    def reverse_snapshot(self, snapshot_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/distribution-snapshots/{snapshot_id}/reverse", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # Promotion events
    # ------------------------------------------------------------------ #
    def create_promotion(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/promotion-events", payload, headers)

    def get_promotion(self, promotion_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/promotion-events/{promotion_event_id}", None, headers)

    def list_promotions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/promotion-events", params, headers)

    def commit_promotion(self, promotion_event_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/promotion-events/{promotion_event_id}/commit", payload or {}, headers
        )

    def execute_promotion(self, promotion_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/promotion-events/{promotion_event_id}/execute", payload, headers
        )

    def cancel_promotion(self, promotion_event_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/promotion-events/{promotion_event_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # Deductions
    # ------------------------------------------------------------------ #
    def create_deduction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/deductions", payload, headers)

    def get_deduction(self, deduction_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/deductions/{deduction_id}", None, headers)

    def list_deductions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/deductions", params, headers)

    def dispute_deduction(self, deduction_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/deductions/{deduction_id}/dispute", payload, headers)

    def substantiate_deduction(self, deduction_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/deductions/{deduction_id}/substantiate", payload, headers)

    def approve_recovery(self, deduction_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/deductions/{deduction_id}/approve-recovery", payload or {}, headers
        )

    def deny_recovery(self, deduction_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/deductions/{deduction_id}/deny-recovery", payload, headers
        )

    def concede_deduction(self, deduction_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/deductions/{deduction_id}/concede", payload or {}, headers
        )
