"""Thin typed wrapper over the National Account Contract HTTP API.

One method per endpoint declared by the PRD. Every method returns the raw
response object so tests can assert on both status code and body.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/nac"


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------
    # Operators
    # ----------------------------------------------------------------

    def create_operator(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/operators", payload, headers)

    def get_operator(self, operator_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/operators/{operator_id}", None, headers)

    # ----------------------------------------------------------------
    # Manufacturers
    # ----------------------------------------------------------------

    def create_manufacturer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/manufacturers/{manufacturer_id}", None, headers
        )

    # ----------------------------------------------------------------
    # Distribution centers
    # ----------------------------------------------------------------

    def create_distribution_center(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/distribution-centers", payload, headers)

    def get_distribution_center(
        self, distribution_center_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"{BASE}/distribution-centers/{distribution_center_id}",
            None,
            headers,
        )

    # ----------------------------------------------------------------
    # Products
    # ----------------------------------------------------------------

    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/products/{product_id}", None, headers)

    def list_products(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/products", params or {}, headers)

    def set_product_availability(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/products/{product_id}/availability", payload, headers
        )

    # ----------------------------------------------------------------
    # Contracts
    # ----------------------------------------------------------------

    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/contracts/{contract_id}", None, headers)

    def list_contracts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/contracts", params or {}, headers)

    def submit_contract_for_signature(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/contracts/{contract_id}/submit-for-signature",
            payload or {},
            headers,
        )

    def return_contract_to_draft(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/contracts/{contract_id}/return-to-draft",
            payload or {},
            headers,
        )

    def sign_contract(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/sign", payload or {}, headers
        )

    def open_contract_amendment(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/contracts/{contract_id}/amendments",
            payload or {},
            headers,
        )

    def suspend_contract(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/suspend", payload or {}, headers
        )

    def reinstate_contract(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/reinstate", payload or {}, headers
        )

    def terminate_contract(
        self,
        contract_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/terminate", payload or {}, headers
        )

    def get_compliance_report(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/contracts/{contract_id}/compliance-report", None, headers
        )

    # ----------------------------------------------------------------
    # Contract tiers
    # ----------------------------------------------------------------

    def create_contract_tier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/contract-tiers", payload, headers)

    def get_contract_tier(self, contract_tier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/contract-tiers/{contract_tier_id}", None, headers
        )

    def list_contract_tiers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/contract-tiers", params or {}, headers)

    # ----------------------------------------------------------------
    # DC coverages
    # ----------------------------------------------------------------

    def create_dc_coverage(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dc-coverages", payload, headers)

    def get_dc_coverage(self, dc_coverage_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/dc-coverages/{dc_coverage_id}", None, headers
        )

    def list_dc_coverages(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/dc-coverages", params or {}, headers)

    # ----------------------------------------------------------------
    # Deviation agreements
    # ----------------------------------------------------------------

    def create_deviation_agreement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/deviation-agreements", payload, headers)

    def get_deviation_agreement(
        self, deviation_agreement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"{BASE}/deviation-agreements/{deviation_agreement_id}",
            None,
            headers,
        )

    def list_deviation_agreements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{BASE}/deviation-agreements", params or {}, headers
        )

    def submit_deviation_agreement(
        self,
        deviation_agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/deviation-agreements/{deviation_agreement_id}/submit",
            payload or {},
            headers,
        )

    def decide_deviation_agreement(
        self,
        deviation_agreement_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/deviation-agreements/{deviation_agreement_id}"
            "/manufacturer-decision",
            payload,
            headers,
        )

    def activate_deviation_agreement(
        self,
        deviation_agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/deviation-agreements/{deviation_agreement_id}/activate",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------------
    # Substitution rules
    # ----------------------------------------------------------------

    def create_substitution_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/substitution-rules", payload, headers)

    def get_substitution_rule(self, substitution_rule_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/substitution-rules/{substitution_rule_id}", None, headers
        )

    def list_substitution_rules(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/substitution-rules", params or {}, headers)

    # ----------------------------------------------------------------
    # Price change notices
    # ----------------------------------------------------------------

    def create_price_change_notice(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/price-change-notices", payload, headers)

    def get_price_change_notice(
        self, price_change_notice_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"{BASE}/price-change-notices/{price_change_notice_id}",
            None,
            headers,
        )

    def list_price_change_notices(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{BASE}/price-change-notices", params or {}, headers
        )

    def acknowledge_price_change_notice(
        self,
        price_change_notice_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/price-change-notices/{price_change_notice_id}/acknowledge",
            payload or {},
            headers,
        )

    def dispute_price_change_notice(
        self,
        price_change_notice_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/price-change-notices/{price_change_notice_id}/dispute",
            payload,
            headers,
        )

    def revise_price_change_notice(
        self,
        price_change_notice_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/price-change-notices/{price_change_notice_id}/revise",
            payload,
            headers,
        )

    def activate_price_change_notice(
        self,
        price_change_notice_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/price-change-notices/{price_change_notice_id}/activate",
            payload or {},
            headers,
        )

    def withdraw_price_change_notice(
        self,
        price_change_notice_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/price-change-notices/{price_change_notice_id}/withdraw",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------------
    # Rebate periods
    # ----------------------------------------------------------------

    def create_rebate_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/rebate-periods", payload, headers)

    def get_rebate_period(self, rebate_period_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/rebate-periods/{rebate_period_id}", None, headers
        )

    def list_rebate_periods(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/rebate-periods", params or {}, headers)

    def close_rebate_period(
        self,
        rebate_period_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/rebate-periods/{rebate_period_id}/close",
            payload or {},
            headers,
        )

    def settle_rebate_period(
        self, rebate_period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/rebate-periods/{rebate_period_id}/settle",
            payload,
            headers,
        )

    def reverse_rebate_settlement(
        self, rebate_period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/rebate-periods/{rebate_period_id}/reverse-settlement",
            payload,
            headers,
        )

    # ----------------------------------------------------------------
    # Order lines
    # ----------------------------------------------------------------

    def create_order_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/order-lines", payload, headers)

    def get_order_line(self, order_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/order-lines/{order_line_id}", None, headers)

    def list_order_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/order-lines", params or {}, headers)

    def substitute_order_line(
        self,
        order_line_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/order-lines/{order_line_id}/substitute",
            payload or {},
            headers,
        )

    def invoice_order_line(
        self,
        order_line_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/order-lines/{order_line_id}/invoice", payload or {}, headers
        )

    def reprice_order_line(
        self,
        order_line_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/order-lines/{order_line_id}/reprice", payload or {}, headers
        )

    # ----------------------------------------------------------------
    # Bill-back claims
    # ----------------------------------------------------------------

    def create_bill_back_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/bill-back-claims", payload, headers)

    def get_bill_back_claim(self, bill_back_claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/bill-back-claims/{bill_back_claim_id}", None, headers
        )

    def list_bill_back_claims(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/bill-back-claims", params or {}, headers)

    def submit_bill_back_claim(
        self,
        bill_back_claim_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/bill-back-claims/{bill_back_claim_id}/submit",
            payload or {},
            headers,
        )

    def dispute_bill_back_claim(
        self, bill_back_claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/bill-back-claims/{bill_back_claim_id}/dispute",
            payload,
            headers,
        )

    def write_off_bill_back_claim(
        self, bill_back_claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/bill-back-claims/{bill_back_claim_id}/write-off",
            payload,
            headers,
        )

    # ----------------------------------------------------------------
    # Bill-back remittances
    # ----------------------------------------------------------------

    def create_bill_back_remittance(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/bill-back-remittances", payload, headers)

    def get_bill_back_remittance(
        self, bill_back_remittance_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"{BASE}/bill-back-remittances/{bill_back_remittance_id}",
            None,
            headers,
        )

    def list_bill_back_remittances(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{BASE}/bill-back-remittances", params or {}, headers
        )

    def reverse_bill_back_remittance(
        self,
        bill_back_remittance_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/bill-back-remittances/{bill_back_remittance_id}/reverse",
            payload,
            headers,
        )

    # ----------------------------------------------------------------
    # Pricing disputes
    # ----------------------------------------------------------------

    def create_pricing_dispute(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/pricing-disputes", payload, headers)

    def get_pricing_dispute(self, pricing_dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/pricing-disputes/{pricing_dispute_id}", None, headers
        )

    def list_pricing_disputes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{BASE}/pricing-disputes", params or {}, headers)

    def start_dispute_audit(
        self,
        pricing_dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/pricing-disputes/{pricing_dispute_id}/start-audit",
            payload or {},
            headers,
        )

    def request_dispute_info(
        self, pricing_dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/pricing-disputes/{pricing_dispute_id}/request-info",
            payload,
            headers,
        )

    def resolve_pricing_dispute(
        self, pricing_dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/pricing-disputes/{pricing_dispute_id}/resolve",
            payload,
            headers,
        )

    def issue_dispute_credit(
        self,
        pricing_dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/pricing-disputes/{pricing_dispute_id}/issue-credit",
            payload or {},
            headers,
        )

    def withdraw_pricing_dispute(
        self,
        pricing_dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/pricing-disputes/{pricing_dispute_id}/withdraw",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------------
    # Logical clock
    # ----------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------------------
    # Raw escape hatches for negative probes
    # ----------------------------------------------------------------

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", path, params or {}, headers)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request("POST", path, payload or {}, headers)


api_client = ApiClient()
