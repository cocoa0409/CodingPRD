"""One method per declared endpoint of the price-integrity API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class PriceIntegrityApiClient(GenericApiClient):
    """Typed surface over the sixty-eight declared endpoints."""

    def _p(self, suffix: str) -> str:
        return f"{API_PREFIX}{suffix}"

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            self._p("/_clock/set_current_utc"),
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p("/_clock/set_current_utc"), payload, headers
        )

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", self._p("/jurisdictions"), payload, headers)

    def get_jurisdiction(
        self, jurisdiction_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/jurisdictions/{jurisdiction_id}"), None, headers
        )

    def list_jurisdictions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/jurisdictions"), params, headers)

    def amend_jurisdiction(
        self, jurisdiction_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", self._p(f"/jurisdictions/{jurisdiction_id}"), payload, headers
        )

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------
    def create_store(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", self._p("/stores"), payload, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", self._p(f"/stores/{store_id}"), None, headers)

    def list_stores(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/stores"), params, headers)

    def get_store_compliance_summary(
        self, store_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/stores/{store_id}/compliance-summary"), None, headers
        )

    def run_signage_sweep(
        self, store_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/stores/{store_id}/signage-sweep"),
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Aisles
    # ------------------------------------------------------------------
    def create_aisle(
        self, store_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/stores/{store_id}/aisles"), payload, headers
        )

    def get_aisle(self, aisle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", self._p(f"/aisles/{aisle_id}"), None, headers)

    def list_store_aisles(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/stores/{store_id}/aisles"), params, headers
        )

    def list_associate_aisles(
        self, associate_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/associates/{associate_id}/aisles"), params, headers
        )

    def assign_aisle_associate(
        self, aisle_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/aisles/{aisle_id}/assign-associate"), payload, headers
        )

    # ------------------------------------------------------------------
    # Associates
    # ------------------------------------------------------------------
    def create_associate(
        self, store_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/stores/{store_id}/associates"), payload, headers
        )

    def get_associate(
        self, associate_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/associates/{associate_id}"), None, headers
        )

    def list_store_associates(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/stores/{store_id}/associates"), params, headers
        )

    def record_training_completion(
        self, associate_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/associates/{associate_id}/training-completions"),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Accountability actions
    # ------------------------------------------------------------------
    def create_accountability_action(
        self, associate_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/associates/{associate_id}/accountability-actions"),
            payload,
            headers,
        )

    def get_accountability_action(
        self, action_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/accountability-actions/{action_id}"), None, headers
        )

    def list_associate_accountability_actions(
        self, associate_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            self._p(f"/associates/{associate_id}/accountability-actions"),
            params,
            headers,
        )

    def transition_accountability_action(
        self, action_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/accountability-actions/{action_id}/transition"),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Price change files and lines
    # ------------------------------------------------------------------
    def create_price_change_file(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", self._p("/price-change-files"), payload, headers)

    def get_price_change_file(
        self, file_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/price-change-files/{file_id}"), None, headers
        )

    def list_price_change_files(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/price-change-files"), params, headers)

    def create_price_change_line(
        self, file_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/price-change-files/{file_id}/lines"), payload, headers
        )

    def get_price_change_line(
        self, line_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/price-change-lines/{line_id}"), None, headers
        )

    def list_price_change_lines(
        self, file_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/price-change-files/{file_id}/lines"), params, headers
        )

    def distribute_price_change_file(
        self, file_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/price-change-files/{file_id}/distribute"),
            payload if payload is not None else {},
            headers,
        )

    def supersede_price_change_file(
        self, file_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/price-change-files/{file_id}/supersede"),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Label tasks
    # ------------------------------------------------------------------
    def create_label_task(
        self, file_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/price-change-files/{file_id}/label-tasks"),
            payload,
            headers,
        )

    def get_label_task(
        self, task_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", self._p(f"/label-tasks/{task_id}"), None, headers)

    def list_label_tasks(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/label-tasks"), params, headers)

    def print_label_task(
        self, task_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/label-tasks/{task_id}/print"),
            payload if payload is not None else {},
            headers,
        )

    def place_label_task(
        self, task_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/label-tasks/{task_id}/place"), payload, headers
        )

    def verify_label_task_placement(
        self, task_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/label-tasks/{task_id}/verify-placement"),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Scanner audits and scan lines
    # ------------------------------------------------------------------
    def create_scanner_audit(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", self._p("/scanner-audits"), payload, headers)

    def get_scanner_audit(
        self, audit_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/scanner-audits/{audit_id}"), None, headers
        )

    def list_scanner_audits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/scanner-audits"), params, headers)

    def create_scan_line(
        self, audit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/scanner-audits/{audit_id}/scan-lines"), payload, headers
        )

    def get_scan_line(
        self, scan_line_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/scan-lines/{scan_line_id}"), None, headers
        )

    def list_scan_lines(
        self, audit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/scanner-audits/{audit_id}/scan-lines"), params, headers
        )

    def close_scanner_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/scanner-audits/{audit_id}/close"),
            payload if payload is not None else {},
            headers,
        )

    def reopen_scanner_audit(
        self, audit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/scanner-audits/{audit_id}/reopen"), payload, headers
        )

    # ------------------------------------------------------------------
    # Promotional signage
    # ------------------------------------------------------------------
    def create_promo_signage(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", self._p("/promo-signage"), payload, headers)

    def get_promo_signage(
        self, signage_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/promo-signage/{signage_id}"), None, headers
        )

    def list_promo_signage(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/promo-signage"), params, headers)

    def post_promo_signage(
        self, signage_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/promo-signage/{signage_id}/post"),
            payload if payload is not None else {},
            headers,
        )

    def remove_promo_signage(
        self, signage_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/promo-signage/{signage_id}/remove"),
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Regulatory inspections and findings
    # ------------------------------------------------------------------
    def create_regulatory_inspection(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p("/regulatory-inspections"), payload, headers
        )

    def get_regulatory_inspection(
        self, inspection_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/regulatory-inspections/{inspection_id}"), None, headers
        )

    def list_regulatory_inspections(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", self._p("/regulatory-inspections"), params, headers
        )

    def issue_inspection_findings(
        self, inspection_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/regulatory-inspections/{inspection_id}/issue-findings"),
            payload,
            headers,
        )

    def get_inspection_finding(
        self, finding_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/inspection-findings/{finding_id}"), None, headers
        )

    def list_inspection_findings(
        self, inspection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            self._p(f"/regulatory-inspections/{inspection_id}/findings"),
            params,
            headers,
        )

    def transition_inspection_finding(
        self, finding_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/inspection-findings/{finding_id}/transition"),
            payload,
            headers,
        )

    def submit_inspection_response(
        self, inspection_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/regulatory-inspections/{inspection_id}/response"),
            payload,
            headers,
        )

    def adjudicate_inspection(
        self, inspection_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/regulatory-inspections/{inspection_id}/adjudicate"),
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Refund claims
    # ------------------------------------------------------------------
    def create_refund_claim(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", self._p("/refund-claims"), payload, headers)

    def get_refund_claim(
        self, claim_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/refund-claims/{claim_id}"), None, headers
        )

    def list_refund_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/refund-claims"), params, headers)

    def settle_refund_claim(
        self, claim_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/refund-claims/{claim_id}/settle"), payload, headers
        )

    # ------------------------------------------------------------------
    # Exception reports
    # ------------------------------------------------------------------
    def create_exception_report(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", self._p("/exception-reports"), payload, headers)

    def get_exception_report(
        self, report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", self._p(f"/exception-reports/{report_id}"), None, headers
        )

    def list_exception_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", self._p("/exception-reports"), params, headers)

    def assign_exception_report_root_cause(
        self, report_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            self._p(f"/exception-reports/{report_id}/assign-root-cause"),
            payload,
            headers,
        )

    def close_exception_report(
        self, report_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", self._p(f"/exception-reports/{report_id}/close"), payload, headers
        )
