"""HTTP client for the Supplement Label Claim Compliance API.

One method per endpoint row of PRD §4. All endpoints are mounted under the
``/supplement-compliance`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class SupplementComplianceClient(GenericApiClient):
    """Endpoint methods for every row of the PRD §4 routing table."""

    # ------------------------------------------------------------------
    # Ingredients
    # ------------------------------------------------------------------
    def create_ingredient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/ingredients/{ingredient_id}", None, headers
        )

    def list_ingredients(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/ingredients", params, headers)

    def patch_ingredient(
        self, ingredient_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/ingredients/{ingredient_id}", payload, headers
        )

    def run_eligibility_determination(
        self,
        ingredient_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/ingredients/{ingredient_id}/eligibility-determination",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # NDI notifications
    # ------------------------------------------------------------------
    def create_ndi_notification(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/ndi-notifications", payload, headers)

    def get_ndi_notification(self, notification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/ndi-notifications/{notification_id}", None, headers
        )

    def list_ndi_notifications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/ndi-notifications", params, headers)

    def submit_ndi_notification(
        self,
        notification_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/ndi-notifications/{notification_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def record_agency_response(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/ndi-notifications/{notification_id}/agency-response",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/products/{product_id}", None, headers)

    def list_products(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/products", params, headers)

    def patch_product(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/products/{product_id}", payload, headers
        )

    def start_marketing(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/products/{product_id}/start-marketing", payload, headers
        )

    def get_risk_profile(self, product_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/products/{product_id}/risk-profile", None, headers
        )

    # ------------------------------------------------------------------
    # Supplement-facts lines
    # ------------------------------------------------------------------
    def create_product_ingredient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/product-ingredients", payload, headers
        )

    def get_product_ingredient(self, line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/product-ingredients/{line_id}", None, headers
        )

    def list_product_ingredients(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/product-ingredients", params, headers)

    def patch_product_ingredient(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/product-ingredients/{line_id}", payload, headers
        )

    def delete_product_ingredient(self, line_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"{API_PREFIX}/product-ingredients/{line_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/claims/{claim_id}", None, headers)

    def list_claims(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/claims", params, headers)

    def patch_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"{API_PREFIX}/claims/{claim_id}", payload, headers)

    def submit_claim_for_review(
        self,
        claim_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/claims/{claim_id}/submit-for-review",
            payload if payload is not None else {},
            headers,
        )

    def approve_claim(
        self,
        claim_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/claims/{claim_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/withdraw", payload, headers
        )

    def notify_fda(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/notify-fda", payload, headers
        )

    # ------------------------------------------------------------------
    # Substantiation dossiers
    # ------------------------------------------------------------------
    def create_dossier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/substantiation-dossiers", payload, headers
        )

    def get_dossier(self, dossier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/substantiation-dossiers/{dossier_id}", None, headers
        )

    def list_dossiers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/substantiation-dossiers", params, headers
        )

    def append_evidence(
        self, dossier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/substantiation-dossiers/{dossier_id}/evidence",
            payload,
            headers,
        )

    def review_dossier(
        self, dossier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/substantiation-dossiers/{dossier_id}/review",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Label panels
    # ------------------------------------------------------------------
    def create_label_panel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/label-panels", payload, headers)

    def get_label_panel(self, panel_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/label-panels/{panel_id}", None, headers
        )

    def list_label_panels(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/label-panels", params, headers)

    def patch_label_panel(
        self, panel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/label-panels/{panel_id}", payload, headers
        )

    def validate_label_panel(
        self,
        panel_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/label-panels/{panel_id}/validate",
            payload if payload is not None else {},
            headers,
        )

    def lock_label_panel(
        self,
        panel_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/label-panels/{panel_id}/lock",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Adverse event reports
    # ------------------------------------------------------------------
    def create_adverse_event_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/adverse-event-reports", payload, headers
        )

    def get_adverse_event_report(self, aer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/adverse-event-reports/{aer_id}", None, headers
        )

    def list_adverse_event_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/adverse-event-reports", params, headers
        )

    def triage_adverse_event_report(
        self,
        aer_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/adverse-event-reports/{aer_id}/triage",
            payload if payload is not None else {},
            headers,
        )

    def submit_aer_to_fda(
        self, aer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/adverse-event-reports/{aer_id}/submit-to-fda",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/suppliers/{supplier_id}", None, headers
        )

    def list_suppliers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/suppliers", params, headers)

    def qualification_decision(
        self, supplier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/suppliers/{supplier_id}/qualification-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Ingredient lots
    # ------------------------------------------------------------------
    def create_ingredient_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/ingredient-lots", payload, headers)

    def get_ingredient_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/ingredient-lots/{lot_id}", None, headers
        )

    def list_ingredient_lots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/ingredient-lots", params, headers)

    def release_lot(
        self,
        lot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/ingredient-lots/{lot_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def recall_lot(self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/ingredient-lots/{lot_id}/recall", payload, headers
        )

    # ------------------------------------------------------------------
    # Certificates of analysis
    # ------------------------------------------------------------------
    def create_coa(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/coas", payload, headers)

    def get_coa(self, coa_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/coas/{coa_id}", None, headers)

    def list_coas(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/coas", params, headers)

    def review_coa(self, coa_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/coas/{coa_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for header/param probes
    # ------------------------------------------------------------------
    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", f"{API_PREFIX}{path}", None, headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request("POST", f"{API_PREFIX}{path}", payload, headers)
