"""API client: one method per endpoint defined in the PRD (§4).

The whole surface is mounted under `/procurement`, with the single
administrative clock endpoint outside that mount.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/procurement"


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the public procurement API."""

    # ------------------------------------------------------------ the clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------------- vendor file
    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/vendors", headers=headers, params=params)

    def create_fee_deposit(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/fee-deposits", payload, headers
        )

    def list_vendor_questions(
        self, vendor_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/vendors/{vendor_id}/questions", headers=headers, params=params
        )

    def list_debarred_vendors(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/debarred-vendors", headers=headers, params=params
        )

    # --------------------------------------------------------- solicitations
    def create_solicitation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/solicitations", payload, headers)

    def get_solicitation(self, solicitation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/solicitations/{solicitation_id}", headers=headers
        )

    def list_solicitations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/solicitations", headers=headers, params=params
        )

    def issue_solicitation(
        self, solicitation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/issue", payload or {}, headers
        )

    def create_addendum(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/addenda", payload, headers
        )

    def list_addenda(
        self, solicitation_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/solicitations/{solicitation_id}/addenda",
            headers=headers,
            params=params,
        )

    def list_requirements(
        self, solicitation_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/solicitations/{solicitation_id}/requirements",
            headers=headers,
            params=params,
        )

    def submit_question(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/questions", payload, headers
        )

    def list_questions(
        self, solicitation_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/solicitations/{solicitation_id}/questions",
            headers=headers,
            params=params,
        )

    def close_question_period(
        self, solicitation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/solicitations/{solicitation_id}/close-question-period",
            payload or {},
            headers,
        )

    def open_bids(
        self, solicitation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/solicitations/{solicitation_id}/open-bids",
            payload or {},
            headers,
        )

    def cancel_solicitation(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/cancel", payload, headers
        )

    def resolicit_solicitation(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/resolicit", payload, headers
        )

    # ------------------------------------------------------------------ bids
    def create_bid(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/bids", payload, headers)

    def get_bid(self, bid_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/bids/{bid_id}", headers=headers)

    def list_bids(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/bids", headers=headers, params=params)

    def determine_responsiveness(
        self, bid_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/bids/{bid_id}/responsiveness", payload, headers
        )

    def create_responsibility_review(
        self, bid_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/bids/{bid_id}/responsibility-reviews", payload, headers
        )

    def list_responsibility_reviews(
        self, bid_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/bids/{bid_id}/responsibility-reviews",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------------- awards
    def create_award(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/awards", payload, headers)

    def execute_award(
        self, award_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/awards/{award_id}/execute", payload or {}, headers
        )

    def get_award(self, award_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/awards/{award_id}", headers=headers)

    def list_awards(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/awards", headers=headers, params=params)

    # -------------------------------------------------------------- protests
    def create_protest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/protests", payload, headers)

    def get_protest(self, protest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/protests/{protest_id}", headers=headers)

    def list_protests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/protests", headers=headers, params=params)

    def create_record_item(
        self, protest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/record-items", payload, headers
        )

    def list_record_items(
        self, protest_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/protests/{protest_id}/record-items",
            headers=headers,
            params=params,
        )

    def create_hearing(
        self, protest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/hearings", payload, headers
        )

    def list_hearings(
        self, protest_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/protests/{protest_id}/hearings",
            headers=headers,
            params=params,
        )

    def get_hearing(self, hearing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/hearings/{hearing_id}", headers=headers)

    def convene_hearing(
        self, hearing_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/hearings/{hearing_id}/convene", payload or {}, headers
        )

    def continue_hearing(
        self, hearing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/hearings/{hearing_id}/continue", payload, headers
        )

    def conclude_hearing(
        self, hearing_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/hearings/{hearing_id}/conclude", payload or {}, headers
        )

    def decide_protest(
        self, protest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/decision", payload, headers
        )

    def withdraw_protest(
        self, protest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/withdraw", payload, headers
        )

    def override_stay(
        self, protest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/stay-override", payload, headers
        )

    # -------------------------------------------------- debarment proceedings
    def create_debarment_proceeding(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/debarment-proceedings", payload, headers
        )

    def get_debarment_proceeding(self, proceeding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/debarment-proceedings/{proceeding_id}", headers=headers
        )

    def list_debarment_proceedings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/debarment-proceedings", headers=headers, params=params
        )

    def file_debarment_response(
        self, proceeding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/debarment-proceedings/{proceeding_id}/response",
            payload,
            headers,
        )

    def hold_debarment_hearing(
        self, proceeding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/debarment-proceedings/{proceeding_id}/hearing",
            payload,
            headers,
        )

    def decide_debarment(
        self, proceeding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/debarment-proceedings/{proceeding_id}/decision",
            payload,
            headers,
        )

    def create_reinstatement_petition(
        self, proceeding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/debarment-proceedings/{proceeding_id}/reinstatement-petitions",
            payload,
            headers,
        )

    def list_reinstatement_petitions(
        self, proceeding_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/debarment-proceedings/{proceeding_id}/reinstatement-petitions",
            headers=headers,
            params=params,
        )

    def get_reinstatement_petition(self, petition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/reinstatement-petitions/{petition_id}", headers=headers
        )

    def decide_reinstatement_petition(
        self, petition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/reinstatement-petitions/{petition_id}/decision",
            payload,
            headers,
        )

    # ----------------------------------------------- subcontractor screenings
    def create_subcontractor_screening(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/subcontractor-screenings", payload, headers
        )

    def get_subcontractor_screening(self, screening_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/subcontractor-screenings/{screening_id}", headers=headers
        )

    def list_subcontractor_screenings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/subcontractor-screenings", headers=headers, params=params
        )


api_client = ApiClient()
