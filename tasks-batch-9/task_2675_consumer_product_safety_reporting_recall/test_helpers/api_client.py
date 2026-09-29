"""A typed client exposing one method per declared endpoint."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Every call the product safety service accepts."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601: str, headers: Headers = None):
        """Set the logical UTC clock used by every timestamp comparison."""
        return self._request(
            "POST", CLOCK_PATH, payload={"to_iso8601": to_iso8601}, headers=headers
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None):
        """Set the logical clock with an arbitrary body."""
        return self._request("POST", CLOCK_PATH, payload=payload, headers=headers)

    # -------------------------------------------------------- product models
    def create_product_model(self, payload: Payload, headers: Headers = None):
        """Register a product model in the reference registry."""
        return self._request(
            "POST", f"{API_PREFIX}/product-models", payload=payload, headers=headers
        )

    def get_product_model(self, model_id: str, headers: Headers = None):
        """Retrieve one product model with its registry counts and posture."""
        return self._request(
            "GET", f"{API_PREFIX}/product-models/{model_id}", headers=headers
        )

    # ------------------------------------------------------------- incidents
    def create_incident(self, payload: Payload, headers: Headers = None):
        """Record an incoming consumer incident report."""
        return self._request(
            "POST", f"{API_PREFIX}/incidents", payload=payload, headers=headers
        )

    def get_incident(self, incident_id: str, headers: Headers = None):
        """Retrieve one incident report with its severity weight."""
        return self._request(
            "GET", f"{API_PREFIX}/incidents/{incident_id}", headers=headers
        )

    def list_incidents(self, params: Params = None, headers: Headers = None):
        """List incidents under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/incidents", params=params, headers=headers
        )

    def classify_incident(
        self, incident_id: str, payload: Payload, headers: Headers = None
    ):
        """Classify an incident's hazard category and verification state."""
        return self._request(
            "POST",
            f"{API_PREFIX}/incidents/{incident_id}/classify",
            payload=payload,
            headers=headers,
        )

    def dispose_incident(
        self, incident_id: str, payload: Payload, headers: Headers = None
    ):
        """Dispose of an incident as a duplicate or as requiring no action."""
        return self._request(
            "POST",
            f"{API_PREFIX}/incidents/{incident_id}/dispose",
            payload=payload,
            headers=headers,
        )

    # -------------------------------------------------------- hazard patterns
    def create_hazard_pattern(self, payload: Payload, headers: Headers = None):
        """Open a hazard pattern analysis over a product model's incidents."""
        return self._request(
            "POST", f"{API_PREFIX}/hazard-patterns", payload=payload, headers=headers
        )

    def get_hazard_pattern(self, pattern_id: str, headers: Headers = None):
        """Retrieve one hazard pattern with its computed risk snapshot."""
        return self._request(
            "GET", f"{API_PREFIX}/hazard-patterns/{pattern_id}", headers=headers
        )

    def list_hazard_patterns(self, params: Params = None, headers: Headers = None):
        """List hazard patterns under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/hazard-patterns", params=params, headers=headers
        )

    def recompute_hazard_pattern(
        self, pattern_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Recompute an open pattern's risk snapshot."""
        return self._request(
            "POST",
            f"{API_PREFIX}/hazard-patterns/{pattern_id}/recompute",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def adjudicate_hazard_pattern(
        self, pattern_id: str, payload: Payload, headers: Headers = None
    ):
        """Confirm or dismiss an analysed hazard pattern."""
        return self._request(
            "POST",
            f"{API_PREFIX}/hazard-patterns/{pattern_id}/adjudicate",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------- reportability evaluations
    def create_evaluation(self, payload: Payload, headers: Headers = None):
        """Open a reportability evaluation on a confirmed hazard pattern."""
        return self._request(
            "POST",
            f"{API_PREFIX}/reportability-evaluations",
            payload=payload,
            headers=headers,
        )

    def get_evaluation(self, evaluation_id: str, headers: Headers = None):
        """Retrieve one reportability evaluation with its escalation clock."""
        return self._request(
            "GET",
            f"{API_PREFIX}/reportability-evaluations/{evaluation_id}",
            headers=headers,
        )

    def list_evaluations(self, params: Params = None, headers: Headers = None):
        """List reportability evaluations under the declared filters."""
        return self._request(
            "GET",
            f"{API_PREFIX}/reportability-evaluations",
            params=params,
            headers=headers,
        )

    def begin_review(
        self, evaluation_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Begin review of an open evaluation and record the breach question."""
        return self._request(
            "POST",
            f"{API_PREFIX}/reportability-evaluations/{evaluation_id}/begin-review",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def determine_evaluation(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ):
        """Record the reportability determination and fire its consequences."""
        return self._request(
            "POST",
            f"{API_PREFIX}/reportability-evaluations/{evaluation_id}/determine",
            payload=payload,
            headers=headers,
        )

    # -------------------------------------------------------- section reports
    def create_section_report(self, payload: Payload, headers: Headers = None):
        """Draft the statutory report for a reportable evaluation."""
        return self._request(
            "POST", f"{API_PREFIX}/section-reports", payload=payload, headers=headers
        )

    def get_section_report(self, report_id: str, headers: Headers = None):
        """Retrieve one statutory report with its lateness figures."""
        return self._request(
            "GET", f"{API_PREFIX}/section-reports/{report_id}", headers=headers
        )

    def list_section_reports(self, params: Params = None, headers: Headers = None):
        """List statutory reports under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/section-reports", params=params, headers=headers
        )

    def submit_section_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        """File the statutory report and compute its lateness and surcharge."""
        return self._request(
            "POST",
            f"{API_PREFIX}/section-reports/{report_id}/submit",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def review_section_report(
        self, report_id: str, payload: Payload, headers: Headers = None
    ):
        """Accept a filed report or return it for further information."""
        return self._request(
            "POST",
            f"{API_PREFIX}/section-reports/{report_id}/review",
            payload=payload,
            headers=headers,
        )

    def revise_section_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Revise a returned report and put it back into draft."""
        return self._request(
            "POST",
            f"{API_PREFIX}/section-reports/{report_id}/revise",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ----------------------------------------------------------------- recalls
    def create_recall(self, payload: Payload, headers: Headers = None):
        """Draft a corrective action plan against an accepted report."""
        return self._request(
            "POST", f"{API_PREFIX}/recalls", payload=payload, headers=headers
        )

    def get_recall(self, recall_id: str, headers: Headers = None):
        """Retrieve one recall plan with both state dimensions and its ledger."""
        return self._request(
            "GET", f"{API_PREFIX}/recalls/{recall_id}", headers=headers
        )

    def list_recalls(self, params: Params = None, headers: Headers = None):
        """List recall plans under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/recalls", params=params, headers=headers
        )

    def submit_plan(
        self, recall_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Submit a drafted corrective action plan for approval."""
        return self._request(
            "POST",
            f"{API_PREFIX}/recalls/{recall_id}/submit-plan",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def approve_plan(
        self, recall_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Approve a submitted plan and cascade the stop-sale."""
        return self._request(
            "POST",
            f"{API_PREFIX}/recalls/{recall_id}/approve-plan",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def begin_monitoring(
        self, recall_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Move an approved recall into ongoing effectiveness monitoring."""
        return self._request(
            "POST",
            f"{API_PREFIX}/recalls/{recall_id}/begin-monitoring",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def compliance_sweep(
        self, recall_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Sweep the recall's notifications for expired acknowledgements."""
        return self._request(
            "POST",
            f"{API_PREFIX}/recalls/{recall_id}/compliance-sweep",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def close_recall(
        self, recall_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Close a monitored recall and release the model's containment."""
        return self._request(
            "POST",
            f"{API_PREFIX}/recalls/{recall_id}/close",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # --------------------------------------------------------------- retailers
    def create_retailer(self, payload: Payload, headers: Headers = None):
        """Register a retailer in the reference registry."""
        return self._request(
            "POST", f"{API_PREFIX}/retailers", payload=payload, headers=headers
        )

    def get_retailer(self, retailer_id: str, headers: Headers = None):
        """Retrieve one retailer with its counters and compliance posture."""
        return self._request(
            "GET", f"{API_PREFIX}/retailers/{retailer_id}", headers=headers
        )

    # -------------------------------------------------- retailer notifications
    def create_retailer_notification(self, payload: Payload, headers: Headers = None):
        """Enrol a retailer in a recall's stop-sale notification list."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retailer-notifications",
            payload=payload,
            headers=headers,
        )

    def get_retailer_notification(
        self, notification_id: str, headers: Headers = None
    ):
        """Retrieve one stop-sale notification with its acknowledgement deadline."""
        return self._request(
            "GET",
            f"{API_PREFIX}/retailer-notifications/{notification_id}",
            headers=headers,
        )

    def list_retailer_notifications(
        self, params: Params = None, headers: Headers = None
    ):
        """List retailer notifications under the declared filters."""
        return self._request(
            "GET",
            f"{API_PREFIX}/retailer-notifications",
            params=params,
            headers=headers,
        )

    def acknowledge_notification(
        self, notification_id: str, payload: Payload, headers: Headers = None
    ):
        """Acknowledge a stop-sale notification and report shelf units."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retailer-notifications/{notification_id}/acknowledge",
            payload=payload,
            headers=headers,
        )

    def verify_notification(
        self, notification_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Verify shelf removal and release the retailer's stop-sale."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retailer-notifications/{notification_id}/verify",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------ audit visits
    def create_audit_visit(self, payload: Payload, headers: Headers = None):
        """Schedule a shelf audit visit inside a conflict-free window."""
        return self._request(
            "POST", f"{API_PREFIX}/audit-visits", payload=payload, headers=headers
        )

    def get_audit_visit(self, visit_id: str, headers: Headers = None):
        """Retrieve one shelf audit visit with its window and verdict."""
        return self._request(
            "GET", f"{API_PREFIX}/audit-visits/{visit_id}", headers=headers
        )

    def list_audit_visits(self, params: Params = None, headers: Headers = None):
        """List audit visits under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/audit-visits", params=params, headers=headers
        )

    def complete_audit_visit(
        self, visit_id: str, payload: Payload, headers: Headers = None
    ):
        """Record the audit verdict and the shelf units found."""
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-visits/{visit_id}/complete",
            payload=payload,
            headers=headers,
        )

    # -------------------------------------------------------- consumer notices
    def create_consumer_notice(self, payload: Payload, headers: Headers = None):
        """Schedule a consumer notice on one notification channel."""
        return self._request(
            "POST", f"{API_PREFIX}/consumer-notices", payload=payload, headers=headers
        )

    def get_consumer_notice(self, notice_id: str, headers: Headers = None):
        """Retrieve one consumer notice with its schedule and embargo."""
        return self._request(
            "GET", f"{API_PREFIX}/consumer-notices/{notice_id}", headers=headers
        )

    def list_consumer_notices(self, params: Params = None, headers: Headers = None):
        """List consumer notices under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/consumer-notices", params=params, headers=headers
        )

    def release_consumer_notice(
        self, notice_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Release a scheduled notice once it is due and un-embargoed."""
        return self._request(
            "POST",
            f"{API_PREFIX}/consumer-notices/{notice_id}/release",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ----------------------------------------------------------- remedy claims
    def create_remedy_claim(self, payload: Payload, headers: Headers = None):
        """Register a consumer remedy claim and freeze its reimbursement."""
        return self._request(
            "POST", f"{API_PREFIX}/remedy-claims", payload=payload, headers=headers
        )

    def get_remedy_claim(self, claim_id: str, headers: Headers = None):
        """Retrieve one remedy claim with its frozen reimbursement total."""
        return self._request(
            "GET", f"{API_PREFIX}/remedy-claims/{claim_id}", headers=headers
        )

    def list_remedy_claims(self, params: Params = None, headers: Headers = None):
        """List remedy claims under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/remedy-claims", params=params, headers=headers
        )

    def approve_claim(
        self, claim_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Approve a submitted remedy claim against the units outstanding."""
        return self._request(
            "POST",
            f"{API_PREFIX}/remedy-claims/{claim_id}/approve",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def fulfill_claim(
        self, claim_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Fulfil an approved claim and cascade the credit consequences."""
        return self._request(
            "POST",
            f"{API_PREFIX}/remedy-claims/{claim_id}/fulfill",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def void_claim(
        self, claim_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Void a claim, reversing the ledger when it had been fulfilled."""
        return self._request(
            "POST",
            f"{API_PREFIX}/remedy-claims/{claim_id}/void",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # --------------------------------------------------------- progress reports
    def create_progress_report(self, payload: Payload, headers: Headers = None):
        """Open a monthly effectiveness reporting period on a recall."""
        return self._request(
            "POST", f"{API_PREFIX}/progress-reports", payload=payload, headers=headers
        )

    def get_progress_report(self, report_id: str, headers: Headers = None):
        """Retrieve one monthly progress report with its rate and assessment."""
        return self._request(
            "GET", f"{API_PREFIX}/progress-reports/{report_id}", headers=headers
        )

    def list_progress_reports(self, params: Params = None, headers: Headers = None):
        """List monthly progress reports under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/progress-reports", params=params, headers=headers
        )

    def submit_progress_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        """File a monthly progress report with its computed figures."""
        return self._request(
            "POST",
            f"{API_PREFIX}/progress-reports/{report_id}/submit",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def accept_progress_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        """Accept a filed progress report and write back to the recall."""
        return self._request(
            "POST",
            f"{API_PREFIX}/progress-reports/{report_id}/accept",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ---------------------------------------------------- civil penalty cases
    def create_penalty_case(self, payload: Payload, headers: Headers = None):
        """Open a civil penalty docket and freeze the statutory assessment."""
        return self._request(
            "POST",
            f"{API_PREFIX}/civil-penalty-cases",
            payload=payload,
            headers=headers,
        )

    def get_penalty_case(self, case_id: str, headers: Headers = None):
        """Retrieve one civil penalty case with its assessment and reserve."""
        return self._request(
            "GET", f"{API_PREFIX}/civil-penalty-cases/{case_id}", headers=headers
        )

    def list_penalty_cases(self, params: Params = None, headers: Headers = None):
        """List civil penalty cases under the declared filters."""
        return self._request(
            "GET", f"{API_PREFIX}/civil-penalty-cases", params=params, headers=headers
        )

    def create_offer(self, case_id: str, payload: Payload, headers: Headers = None):
        """Table a settlement offer from either party."""
        return self._request(
            "POST",
            f"{API_PREFIX}/civil-penalty-cases/{case_id}/offers",
            payload=payload,
            headers=headers,
        )

    def resolve_offer(self, case_id: str, payload: Payload, headers: Headers = None):
        """Withdraw the standing agency offer or accept and bind it."""
        return self._request(
            "POST",
            f"{API_PREFIX}/civil-penalty-cases/{case_id}/offer-resolution",
            payload=payload,
            headers=headers,
        )


api_client = ApiClient()
