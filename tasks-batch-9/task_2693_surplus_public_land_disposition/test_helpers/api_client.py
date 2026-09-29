"""Typed HTTP client with one method per endpoint of the API under test."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint the specification declares."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Agencies
    # ------------------------------------------------------------------

    def create_agency(self, payload: dict, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agencies(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/agencies", headers=headers, params=params)

    def patch_agency(
        self, agency_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/agencies/{agency_id}", payload, headers)

    # ------------------------------------------------------------------
    # Parcels and title curative items
    # ------------------------------------------------------------------

    def create_parcel(self, payload: dict, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/parcels", headers=headers, params=params)

    def patch_parcel(
        self, parcel_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/parcels/{parcel_id}", payload, headers)

    def create_title_item(
        self, parcel_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/parcels/{parcel_id}/title-items", payload, headers
        )

    def list_parcel_title_items(
        self, parcel_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parcels/{parcel_id}/title-items", headers=headers, params=params
        )

    def get_title_item(
        self, title_item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/title-items/{title_item_id}", headers=headers)

    def resolve_title_item(
        self, title_item_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/title-items/{title_item_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Declarations
    # ------------------------------------------------------------------

    def create_declaration(
        self, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/declarations", payload, headers)

    def get_declaration(
        self, declaration_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/declarations/{declaration_id}", headers=headers)

    def list_declarations(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/declarations", headers=headers, params=params)

    def adopt_declaration(
        self, declaration_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/declarations/{declaration_id}/adopt", payload, headers
        )

    def issue_notices(
        self, declaration_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/declarations/{declaration_id}/issue-notices", payload, headers
        )

    def close_preference_window(
        self, declaration_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/close-preference-window",
            payload if payload is not None else {},
            headers,
        )

    def authorize_disposition(
        self, declaration_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/authorize-disposition",
            payload,
            headers,
        )

    def re_offer_declaration(
        self, declaration_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/re-offer",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_declaration(
        self, declaration_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/declarations/{declaration_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Statutory notices
    # ------------------------------------------------------------------

    def get_notice(self, notice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def list_notices(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/notices", headers=headers, params=params)

    def respond_to_notice(
        self, notice_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/notices/{notice_id}/respond", payload, headers)

    # ------------------------------------------------------------------
    # Preference offers and negotiation
    # ------------------------------------------------------------------

    def get_preference_offer(
        self, offer_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/preference-offers/{offer_id}", headers=headers)

    def list_preference_offers(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/preference-offers", headers=headers, params=params
        )

    def append_round(
        self, offer_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/preference-offers/{offer_id}/rounds", payload, headers
        )

    def list_rounds(
        self, offer_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/preference-offers/{offer_id}/rounds",
            headers=headers,
            params=params,
        )

    def open_good_faith_review(
        self, offer_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/preference-offers/{offer_id}/good-faith-review",
            payload if payload is not None else {},
            headers,
        )

    def determine_good_faith(
        self, offer_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/preference-offers/{offer_id}/good-faith-determination",
            payload if payload is not None else {},
            headers,
        )

    def conclude_negotiation(
        self, offer_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/preference-offers/{offer_id}/conclude", payload, headers
        )

    # ------------------------------------------------------------------
    # Appraisers and appraisals
    # ------------------------------------------------------------------

    def create_appraiser(
        self, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/appraisers", payload, headers)

    def get_appraiser(
        self, appraiser_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/appraisers/{appraiser_id}", headers=headers)

    def list_appraisers(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/appraisers", headers=headers, params=params)

    def create_appraisal(
        self, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/appraisals", payload, headers)

    def get_appraisal(
        self, appraisal_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/appraisals", headers=headers, params=params)

    def report_appraisal(
        self, appraisal_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/report", payload, headers
        )

    def accept_appraisal(
        self, appraisal_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/appraisals/{appraisal_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def file_challenge(
        self, appraisal_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/challenges", payload, headers
        )

    def get_challenge(
        self, challenge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/appraisal-challenges/{challenge_id}", headers=headers
        )

    def list_challenges(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/appraisal-challenges", headers=headers, params=params
        )

    def determine_challenge(
        self, challenge_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/appraisal-challenges/{challenge_id}/determine", payload, headers
        )

    # ------------------------------------------------------------------
    # Environmental review
    # ------------------------------------------------------------------

    def create_environmental_review(
        self, declaration_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/environmental-reviews",
            payload,
            headers,
        )

    def list_environmental_reviews(
        self, declaration_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/declarations/{declaration_id}/environmental-reviews",
            headers=headers,
            params=params,
        )

    def get_environmental_review(
        self, review_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/environmental-reviews/{review_id}", headers=headers
        )

    def certify_environmental_review(
        self, review_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/environmental-reviews/{review_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    def recirculate_environmental_review(
        self, review_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/environmental-reviews/{review_id}/recirculate", payload, headers
        )

    # ------------------------------------------------------------------
    # Offerings, bids and awards
    # ------------------------------------------------------------------

    def create_offering(
        self, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/offerings", payload, headers)

    def get_offering(
        self, offering_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def list_offerings(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/offerings", headers=headers, params=params)

    def publish_offering(
        self, offering_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/offerings/{offering_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def submit_bid(
        self, offering_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/offerings/{offering_id}/bids", payload, headers)

    def close_bidding(
        self, offering_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/offerings/{offering_id}/close-bidding",
            payload if payload is not None else {},
            headers,
        )

    def award_offering(
        self, offering_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/offerings/{offering_id}/award",
            payload if payload is not None else {},
            headers,
        )

    def rescind_award(
        self, offering_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/offerings/{offering_id}/rescind-award", payload, headers
        )

    # ------------------------------------------------------------------
    # Bidders and bids
    # ------------------------------------------------------------------

    def create_bidder(self, payload: dict, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/bidders", payload, headers)

    def get_bidder(self, bidder_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def list_bidders(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/bidders", headers=headers, params=params)

    def fund_bidder(
        self, bidder_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/bidders/{bidder_id}/funding", payload, headers)

    def debar_bidder(
        self, bidder_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/bidders/{bidder_id}/debarment", payload, headers)

    def get_bid(self, bid_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/bids", headers=headers, params=params)

    def withdraw_bid(
        self, bid_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bids/{bid_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Conveyances
    # ------------------------------------------------------------------

    def create_conveyance(
        self, offering_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/offerings/{offering_id}/conveyance", payload, headers
        )

    def get_conveyance(
        self, conveyance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/conveyances/{conveyance_id}", headers=headers)

    def list_conveyances(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/conveyances", headers=headers, params=params)

    def clear_title(
        self, conveyance_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/conveyances/{conveyance_id}/clear-title",
            payload if payload is not None else {},
            headers,
        )

    def record_conveyance(
        self, conveyance_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/conveyances/{conveyance_id}/record", payload, headers
        )

    def notice_violation(
        self, conveyance_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/conveyances/{conveyance_id}/violation-notice", payload, headers
        )

    def accept_cure(
        self, conveyance_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/conveyances/{conveyance_id}/accept-cure", payload, headers
        )

    def revert_conveyance(
        self, conveyance_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/conveyances/{conveyance_id}/revert",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Funds and proceeds allocations
    # ------------------------------------------------------------------

    def create_fund(self, payload: dict, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/funds", payload, headers)

    def get_fund(self, fund_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def list_funds(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", "/funds", headers=headers, params=params)

    def patch_fund(
        self, fund_id: str, payload: dict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/funds/{fund_id}", payload, headers)

    def list_fund_allocations(
        self, fund_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/funds/{fund_id}/proceeds-allocations",
            headers=headers,
            params=params,
        )

    def list_conveyance_allocations(
        self, conveyance_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/conveyances/{conveyance_id}/proceeds-allocations",
            headers=headers,
            params=params,
        )

    def list_proceeds_allocations(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/proceeds-allocations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for header-shape probes
    # ------------------------------------------------------------------

    def raw_post(
        self, path: str, payload: Any, headers: Optional[Dict[str, str]]
    ) -> requests.Response:
        """POST an arbitrary path, used when the headers themselves are under test."""
        return self._request("POST", path, payload, headers)

    def raw_get(
        self, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[dict] = None
    ) -> requests.Response:
        """GET an arbitrary path, used when the headers themselves are under test."""
        return self._request("GET", path, headers=headers, params=params)


#: Module-level client shared by the fixtures and the test suite.
api_client = ApiClient()
