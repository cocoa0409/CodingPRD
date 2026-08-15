"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5, §4) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- beneficiaries ---
    def create_beneficiary(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/beneficiaries/{beneficiary_id}", headers=headers
        )

    def suspend_beneficiary(self, beneficiary_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/beneficiaries/{beneficiary_id}/suspend", {}, headers
        )

    # --- foreclosure cases ---
    def create_case(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/foreclosure-cases", payload, headers)

    def list_cases(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/foreclosure-cases", headers=headers, params=params)

    def get_case(self, case_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}", headers=headers
        )

    def get_case_summary(self, case_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/summary", headers=headers
        )

    # --- notices of default ---
    def record_nod(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/notices-of-default",
            payload, headers,
        )

    def list_nods(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/notices-of-default",
            headers=headers, params=params,
        )

    def rescind_nod(self, nod_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/notices-of-default/{nod_id}/rescind", {}, headers
        )

    # --- notices of trustee's sale ---
    def record_nots(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/notices-of-trustee-sale",
            payload, headers,
        )

    def list_nots(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/notices-of-trustee-sale",
            headers=headers, params=params,
        )

    def get_nots(self, nots_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/notices-of-trustee-sale/{nots_id}", headers=headers
        )

    # --- publications ---
    def create_publication(self, nots_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/notices-of-trustee-sale/{nots_id}/publications",
            payload, headers,
        )

    def list_publications(self, nots_id: str, headers: Dict,
                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/notices-of-trustee-sale/{nots_id}/publications",
            headers=headers, params=params,
        )

    def file_affidavit(self, publication_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/publications/{publication_id}/file-affidavit", {}, headers
        )

    # --- sale scheduling ---
    def schedule_sale(self, nots_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/notices-of-trustee-sale/{nots_id}/schedule-sale",
            payload, headers,
        )

    # --- auction sales ---
    def list_auction_sales(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/auction-sales", headers=headers, params=params)

    def get_auction_sale(self, sale_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/auction-sales/{sale_id}", headers=headers
        )

    # --- cost advances ---
    def create_cost_advance(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/cost-advances",
            payload, headers,
        )

    def list_cost_advances(self, case_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/cost-advances",
            headers=headers, params=params,
        )

    def review_cost_advance(self, advance_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/cost-advances/{advance_id}/review", payload, headers
        )

    # --- quotes ---
    def create_quote(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/quotes", payload, headers
        )

    def list_quotes(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/quotes",
            headers=headers, params=params,
        )

    def accept_quote(self, quote_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/quotes/{quote_id}/accept", payload, headers
        )

    # --- stay orders ---
    def create_stay_order(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/stay-orders",
            payload, headers,
        )

    def list_stay_orders(self, case_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/stay-orders",
            headers=headers, params=params,
        )

    def release_stay_order(self, stay_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/stay-orders/{stay_id}/release", payload, headers
        )

    # --- bidding instructions ---
    def create_bidding_instruction(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/bidding-instructions",
            payload, headers,
        )

    def list_bidding_instructions(self, case_id: str, headers: Dict,
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/bidding-instructions",
            headers=headers, params=params,
        )

    def withdraw_bidding_instruction(self, instruction_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/bidding-instructions/{instruction_id}/withdraw", {}, headers
        )

    # --- postponements ---
    def create_postponement(self, sale_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/postponements", payload, headers
        )

    def list_postponements(self, sale_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/auction-sales/{sale_id}/postponements",
            headers=headers, params=params,
        )

    # --- bidder registrations ---
    def create_bidder_registration(self, sale_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/bidder-registrations",
            payload, headers,
        )

    def list_bidder_registrations(self, sale_id: str, headers: Dict,
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/auction-sales/{sale_id}/bidder-registrations",
            headers=headers, params=params,
        )

    def get_bidder_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/bidder-registrations/{registration_id}", headers=headers
        )

    def review_bidder_registration(self, registration_id: str, payload: Dict,
                                   headers: Dict):
        return self._request(
            "POST", f"/api/bidder-registrations/{registration_id}/review",
            payload, headers,
        )

    def refund_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/bidder-registrations/{registration_id}/refund", {}, headers
        )

    # --- bids ---
    def place_bid(self, sale_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/bids", payload, headers
        )

    def list_bids(self, sale_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/auction-sales/{sale_id}/bids",
            headers=headers, params=params,
        )

    def list_bids_for_registration(self, registration_id: str, headers: Dict,
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/bidder-registrations/{registration_id}/bids",
            headers=headers, params=params,
        )

    # --- conduct / close / void ---
    def conduct_sale(self, sale_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/conduct", {}, headers
        )

    def close_sale(self, sale_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/close", {}, headers
        )

    def void_sale(self, sale_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/void", payload, headers
        )

    # --- trustee's deeds ---
    def create_trustees_deed(self, sale_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/auction-sales/{sale_id}/trustees-deeds", {}, headers
        )

    def list_trustees_deeds(self, sale_id: str, headers: Dict,
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/auction-sales/{sale_id}/trustees-deeds",
            headers=headers, params=params,
        )

    def record_trustees_deed(self, deed_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/trustees-deeds/{deed_id}/record", payload, headers
        )

    # --- surplus claims ---
    def create_surplus_claim(self, case_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/surplus-claims",
            payload, headers,
        )

    def list_surplus_claims(self, case_id: str, headers: Dict,
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/foreclosure-cases/{case_id}/surplus-claims",
            headers=headers, params=params,
        )

    def review_surplus_claim(self, claim_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/surplus-claims/{claim_id}/review", payload, headers
        )

    # --- distribution & disbursements ---
    def distribute_surplus(self, case_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/foreclosure-cases/{case_id}/distribute-surplus", {}, headers
        )

    def list_disbursements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/disbursements/{disbursement_id}", headers=headers
        )

    def reverse_disbursement(self, disbursement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/disbursements/{disbursement_id}/reverse", payload, headers
        )


api_client = ApiClient()
