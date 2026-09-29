"""
HTTP client for the Wholesaling Assignment Desk API.

Every collection in this API is mounted at the server root, so each method's
path is written exactly as the endpoint table gives it. Methods return the raw
response so that tests can assert on status codes as well as bodies.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Payload = Dict[str, Any]

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?(?:Z|\+00:00)$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    The API renders timestamps with three fractional digits, but a test that
    compares a stored instant against a literal such as
    "2026-08-10T00:00:00Z" should not fail merely on how many digits of
    sub-second precision appear on the wire. This collapses both sides onto
    the same canonical spelling so that equality reflects the instant itself.
    Values that are not recognisable instants are returned unchanged.
    """
    if value is None or not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('date')}T{match.group('time')}.{frac}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 UTC strings denote the same instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per endpoint in the API's endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        """POST /_clock/set_current_utc"""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Wholesalers
    # ------------------------------------------------------------------

    def create_wholesaler(self, payload: Payload, headers: Dict[str, str]):
        """POST /wholesalers"""
        return self._request("POST", "/wholesalers", payload, headers)

    def get_wholesaler(self, wholesaler_id: str, headers: Dict[str, str]):
        """GET /wholesalers/{wholesaler_id}"""
        return self._request("GET", f"/wholesalers/{wholesaler_id}", None, headers)

    def list_wholesalers(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /wholesalers"""
        return self._request("GET", "/wholesalers", params or {}, headers)

    # ------------------------------------------------------------------
    # Marketing campaigns
    # ------------------------------------------------------------------

    def create_marketing_campaign(self, payload: Payload, headers: Dict[str, str]):
        """POST /marketing-campaigns"""
        return self._request("POST", "/marketing-campaigns", payload, headers)

    def get_marketing_campaign(self, campaign_id: str, headers: Dict[str, str]):
        """GET /marketing-campaigns/{marketing_campaign_id}"""
        return self._request(
            "GET", f"/marketing-campaigns/{campaign_id}", None, headers
        )

    def list_marketing_campaigns(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /marketing-campaigns"""
        return self._request("GET", "/marketing-campaigns", params or {}, headers)

    def publish_marketing_campaign(
        self, campaign_id: str, headers: Dict[str, str], payload: Optional[Payload] = None
    ):
        """POST /marketing-campaigns/{marketing_campaign_id}/publish"""
        return self._request(
            "POST",
            f"/marketing-campaigns/{campaign_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def archive_marketing_campaign(
        self, campaign_id: str, headers: Dict[str, str], payload: Optional[Payload] = None
    ):
        """POST /marketing-campaigns/{marketing_campaign_id}/archive"""
        return self._request(
            "POST",
            f"/marketing-campaigns/{campaign_id}/archive",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Seller leads
    # ------------------------------------------------------------------

    def create_seller_lead(self, payload: Payload, headers: Dict[str, str]):
        """POST /seller-leads"""
        return self._request("POST", "/seller-leads", payload, headers)

    def get_seller_lead(self, seller_lead_id: str, headers: Dict[str, str]):
        """GET /seller-leads/{seller_lead_id}"""
        return self._request("GET", f"/seller-leads/{seller_lead_id}", None, headers)

    def list_seller_leads(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /seller-leads"""
        return self._request("GET", "/seller-leads", params or {}, headers)

    def protection_screen(
        self, seller_lead_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /seller-leads/{seller_lead_id}/protection-screen"""
        return self._request(
            "POST", f"/seller-leads/{seller_lead_id}/protection-screen", payload, headers
        )

    # ------------------------------------------------------------------
    # Deal analyses
    # ------------------------------------------------------------------

    def create_deal_analysis(self, payload: Payload, headers: Dict[str, str]):
        """POST /deal-analyses"""
        return self._request("POST", "/deal-analyses", payload, headers)

    def get_deal_analysis(self, deal_analysis_id: str, headers: Dict[str, str]):
        """GET /deal-analyses/{deal_analysis_id}"""
        return self._request("GET", f"/deal-analyses/{deal_analysis_id}", None, headers)

    def list_deal_analyses(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /deal-analyses"""
        return self._request("GET", "/deal-analyses", params or {}, headers)

    def finalize_deal_analysis(
        self, deal_analysis_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /deal-analyses/{deal_analysis_id}/finalize"""
        return self._request(
            "POST", f"/deal-analyses/{deal_analysis_id}/finalize", payload, headers
        )

    # ------------------------------------------------------------------
    # Purchase contracts
    # ------------------------------------------------------------------

    def create_purchase_contract(self, payload: Payload, headers: Dict[str, str]):
        """POST /purchase-contracts"""
        return self._request("POST", "/purchase-contracts", payload, headers)

    def get_purchase_contract(self, contract_id: str, headers: Dict[str, str]):
        """GET /purchase-contracts/{purchase_contract_id}"""
        return self._request("GET", f"/purchase-contracts/{contract_id}", None, headers)

    def list_purchase_contracts(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /purchase-contracts"""
        return self._request("GET", "/purchase-contracts", params or {}, headers)

    def sign_purchase_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Optional[Payload] = None
    ):
        """POST /purchase-contracts/{purchase_contract_id}/sign"""
        return self._request(
            "POST",
            f"/purchase-contracts/{contract_id}/sign",
            payload if payload is not None else {},
            headers,
        )

    def elect_structure(
        self, contract_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /purchase-contracts/{purchase_contract_id}/elect-structure"""
        return self._request(
            "POST", f"/purchase-contracts/{contract_id}/elect-structure", payload, headers
        )

    def cancel_purchase_contract(
        self, contract_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /purchase-contracts/{purchase_contract_id}/cancel"""
        return self._request(
            "POST", f"/purchase-contracts/{contract_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Disclosure acknowledgements
    # ------------------------------------------------------------------

    def create_disclosure_acknowledgement(
        self, payload: Payload, headers: Dict[str, str]
    ):
        """POST /disclosure-acknowledgements"""
        return self._request("POST", "/disclosure-acknowledgements", payload, headers)

    def get_disclosure_acknowledgement(
        self, acknowledgement_id: str, headers: Dict[str, str]
    ):
        """GET /disclosure-acknowledgements/{disclosure_acknowledgement_id}"""
        return self._request(
            "GET", f"/disclosure-acknowledgements/{acknowledgement_id}", None, headers
        )

    def list_disclosure_acknowledgements(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /disclosure-acknowledgements"""
        return self._request(
            "GET", "/disclosure-acknowledgements", params or {}, headers
        )

    # ------------------------------------------------------------------
    # Earnest money deposits
    # ------------------------------------------------------------------

    def get_earnest_money_deposit(self, deposit_id: str, headers: Dict[str, str]):
        """GET /earnest-money-deposits/{earnest_money_deposit_id}"""
        return self._request(
            "GET", f"/earnest-money-deposits/{deposit_id}", None, headers
        )

    def list_earnest_money_deposits(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /earnest-money-deposits"""
        return self._request("GET", "/earnest-money-deposits", params or {}, headers)

    def forfeit_earnest_money_deposit(
        self, deposit_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /earnest-money-deposits/{earnest_money_deposit_id}/forfeit"""
        return self._request(
            "POST", f"/earnest-money-deposits/{deposit_id}/forfeit", payload, headers
        )

    # ------------------------------------------------------------------
    # Cash buyers
    # ------------------------------------------------------------------

    def create_cash_buyer(self, payload: Payload, headers: Dict[str, str]):
        """POST /cash-buyers"""
        return self._request("POST", "/cash-buyers", payload, headers)

    def get_cash_buyer(self, cash_buyer_id: str, headers: Dict[str, str]):
        """GET /cash-buyers/{cash_buyer_id}"""
        return self._request("GET", f"/cash-buyers/{cash_buyer_id}", None, headers)

    def list_cash_buyers(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /cash-buyers"""
        return self._request("GET", "/cash-buyers", params or {}, headers)

    # ------------------------------------------------------------------
    # Proof of funds
    # ------------------------------------------------------------------

    def create_proof_of_funds(self, payload: Payload, headers: Dict[str, str]):
        """POST /proof-of-funds"""
        return self._request("POST", "/proof-of-funds", payload, headers)

    def get_proof_of_funds(self, proof_of_funds_id: str, headers: Dict[str, str]):
        """GET /proof-of-funds/{proof_of_funds_id}"""
        return self._request(
            "GET", f"/proof-of-funds/{proof_of_funds_id}", None, headers
        )

    def list_proof_of_funds(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /proof-of-funds"""
        return self._request("GET", "/proof-of-funds", params or {}, headers)

    def verify_proof_of_funds(
        self, proof_of_funds_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /proof-of-funds/{proof_of_funds_id}/verify"""
        return self._request(
            "POST", f"/proof-of-funds/{proof_of_funds_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Assignment offers
    # ------------------------------------------------------------------

    def create_assignment_offer(self, payload: Payload, headers: Dict[str, str]):
        """POST /assignment-offers"""
        return self._request("POST", "/assignment-offers", payload, headers)

    def get_assignment_offer(self, offer_id: str, headers: Dict[str, str]):
        """GET /assignment-offers/{assignment_offer_id}"""
        return self._request("GET", f"/assignment-offers/{offer_id}", None, headers)

    def list_assignment_offers(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /assignment-offers"""
        return self._request("GET", "/assignment-offers", params or {}, headers)

    def counter_assignment_offer(
        self, offer_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /assignment-offers/{assignment_offer_id}/counter"""
        return self._request(
            "POST", f"/assignment-offers/{offer_id}/counter", payload, headers
        )

    def revise_assignment_offer(
        self, offer_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /assignment-offers/{assignment_offer_id}/revise"""
        return self._request(
            "POST", f"/assignment-offers/{offer_id}/revise", payload, headers
        )

    def accept_assignment_offer(
        self, offer_id: str, headers: Dict[str, str], payload: Optional[Payload] = None
    ):
        """POST /assignment-offers/{assignment_offer_id}/accept"""
        return self._request(
            "POST",
            f"/assignment-offers/{offer_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Assignment agreements
    # ------------------------------------------------------------------

    def create_assignment_agreement(self, payload: Payload, headers: Dict[str, str]):
        """POST /assignment-agreements"""
        return self._request("POST", "/assignment-agreements", payload, headers)

    def get_assignment_agreement(self, agreement_id: str, headers: Dict[str, str]):
        """GET /assignment-agreements/{assignment_agreement_id}"""
        return self._request(
            "GET", f"/assignment-agreements/{agreement_id}", None, headers
        )

    def list_assignment_agreements(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /assignment-agreements"""
        return self._request("GET", "/assignment-agreements", params or {}, headers)

    def settle_assignment_agreement(
        self, agreement_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /assignment-agreements/{assignment_agreement_id}/settle"""
        return self._request(
            "POST", f"/assignment-agreements/{agreement_id}/settle", payload, headers
        )

    # ------------------------------------------------------------------
    # Title orders
    # ------------------------------------------------------------------

    def create_title_order(self, payload: Payload, headers: Dict[str, str]):
        """POST /title-orders"""
        return self._request("POST", "/title-orders", payload, headers)

    def get_title_order(self, title_order_id: str, headers: Dict[str, str]):
        """GET /title-orders/{title_order_id}"""
        return self._request("GET", f"/title-orders/{title_order_id}", None, headers)

    def list_title_orders(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /title-orders"""
        return self._request("GET", "/title-orders", params or {}, headers)

    def clear_to_fund(
        self, title_order_id: str, headers: Dict[str, str], payload: Optional[Payload] = None
    ):
        """POST /title-orders/{title_order_id}/clear-to-fund"""
        return self._request(
            "POST",
            f"/title-orders/{title_order_id}/clear-to-fund",
            payload if payload is not None else {},
            headers,
        )

    def fund_and_close(
        self, title_order_id: str, headers: Dict[str, str], payload: Optional[Payload] = None
    ):
        """POST /title-orders/{title_order_id}/fund-and-close"""
        return self._request(
            "POST",
            f"/title-orders/{title_order_id}/fund-and-close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Compliance reviews
    # ------------------------------------------------------------------

    def create_compliance_review(self, payload: Payload, headers: Dict[str, str]):
        """POST /compliance-reviews"""
        return self._request("POST", "/compliance-reviews", payload, headers)

    def get_compliance_review(self, review_id: str, headers: Dict[str, str]):
        """GET /compliance-reviews/{compliance_review_id}"""
        return self._request("GET", f"/compliance-reviews/{review_id}", None, headers)

    def list_compliance_reviews(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /compliance-reviews"""
        return self._request("GET", "/compliance-reviews", params or {}, headers)

    def adjudicate_compliance_review(
        self, review_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /compliance-reviews/{compliance_review_id}/adjudicate"""
        return self._request(
            "POST", f"/compliance-reviews/{review_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------------
    # Dispute cases
    # ------------------------------------------------------------------

    def create_dispute_case(self, payload: Payload, headers: Dict[str, str]):
        """POST /dispute-cases"""
        return self._request("POST", "/dispute-cases", payload, headers)

    def get_dispute_case(self, dispute_case_id: str, headers: Dict[str, str]):
        """GET /dispute-cases/{dispute_case_id}"""
        return self._request("GET", f"/dispute-cases/{dispute_case_id}", None, headers)

    def list_dispute_cases(
        self, headers: Dict[str, str], params: Optional[Payload] = None
    ):
        """GET /dispute-cases"""
        return self._request("GET", "/dispute-cases", params or {}, headers)

    def submit_dispute_evidence(
        self, dispute_case_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /dispute-cases/{dispute_case_id}/submit-evidence"""
        return self._request(
            "POST", f"/dispute-cases/{dispute_case_id}/submit-evidence", payload, headers
        )

    def adjudicate_dispute_case(
        self, dispute_case_id: str, payload: Payload, headers: Dict[str, str]
    ):
        """POST /dispute-cases/{dispute_case_id}/adjudicate"""
        return self._request(
            "POST", f"/dispute-cases/{dispute_case_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------------
    # Raw request escape hatch for header-level probes
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Payload] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """Send an arbitrary request, for probes that manipulate headers."""
        return self._request(method, path, payload, headers)
