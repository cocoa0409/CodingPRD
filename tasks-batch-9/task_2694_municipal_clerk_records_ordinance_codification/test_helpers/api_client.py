"""One method per endpoint declared in PRD section 4.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as the envelope.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Typed wrapper over the ``/clerk`` surface."""

    # -- logical clock (PRD 2.4) -------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # -- venues (PRD 3.1) --------------------------------------------------

    def create_venue(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/venues", payload, headers)

    def get_venue(self, venue_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues/{venue_id}", None, headers)

    def update_venue(
        self, venue_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("PUT", f"{API_PREFIX}/venues/{venue_id}", payload, headers)

    def list_venues(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues", params, headers)

    # -- numbering series (PRD 3.5) ---------------------------------------

    def create_number_series(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/number-series", payload, headers)

    def get_number_series(self, series_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/number-series/{series_id}", None, headers
        )

    def close_number_series(self, series_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/number-series/{series_id}/close", {}, headers
        )

    # -- meetings (PRD 3.1) ------------------------------------------------

    def create_meeting(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/meetings", payload, headers)

    def get_meeting(self, meeting_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/meetings/{meeting_id}", None, headers)

    def list_meetings(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/meetings", params, headers)

    def reschedule_meeting(
        self, meeting_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/meetings/{meeting_id}/reschedule", payload, headers
        )

    def convene_meeting(
        self, meeting_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/meetings/{meeting_id}/convene", payload, headers
        )

    def adjourn_meeting(self, meeting_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/meetings/{meeting_id}/adjourn", {}, headers
        )

    def cancel_meeting(
        self, meeting_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/meetings/{meeting_id}/cancel", payload, headers
        )

    # -- agenda packets (PRD 3.2) -----------------------------------------

    def create_agenda_packet(
        self, meeting_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/meetings/{meeting_id}/agenda-packets",
            payload,
            headers,
        )

    def list_meeting_agenda_packets(
        self, meeting_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/meetings/{meeting_id}/agenda-packets", params, headers
        )

    def get_agenda_packet(self, packet_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agenda-packets/{packet_id}", None, headers
        )

    def list_agenda_packets(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/agenda-packets", params, headers)

    def create_agenda_item(
        self, packet_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/agenda-packets/{packet_id}/agenda-items",
            payload,
            headers,
        )

    def list_packet_agenda_items(
        self, packet_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/agenda-packets/{packet_id}/agenda-items",
            params,
            headers,
        )

    def get_agenda_item(self, item_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agenda-items/{item_id}", None, headers
        )

    def list_agenda_items(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/agenda-items", params, headers)

    def post_agenda_packet(self, packet_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agenda-packets/{packet_id}/post", {}, headers
        )

    def withdraw_agenda_packet(
        self, packet_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agenda-packets/{packet_id}/withdraw", {}, headers
        )

    # -- minutes (PRD 3.4) -------------------------------------------------

    def list_meeting_minutes(
        self, meeting_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/meetings/{meeting_id}/minutes", params, headers
        )

    def get_minutes(self, minutes_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/minutes/{minutes_id}", None, headers)

    def list_minutes(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/minutes", params, headers)

    def update_minutes(
        self, minutes_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PUT", f"{API_PREFIX}/minutes/{minutes_id}", payload, headers
        )

    def submit_minutes(self, minutes_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/minutes/{minutes_id}/submit", {}, headers
        )

    def open_minutes_correction(
        self, minutes_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/minutes/{minutes_id}/corrections", payload, headers
        )

    # -- legislative instruments (PRD 3.5) --------------------------------

    def create_instrument(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/instruments", payload, headers)

    def get_instrument(self, instrument_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/instruments/{instrument_id}", None, headers
        )

    def list_instruments(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/instruments", params, headers)

    def advance_reading(
        self, instrument_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/instruments/{instrument_id}/advance-reading",
            payload,
            headers,
        )

    def veto_instrument(
        self, instrument_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/instruments/{instrument_id}/veto", payload, headers
        )

    # -- motions (PRD 3.3) -------------------------------------------------

    def create_motion(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/motions", payload, headers)

    def get_motion(self, motion_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/motions/{motion_id}", None, headers)

    def list_motions(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/motions", params, headers)

    def tally_motion(
        self, motion_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/motions/{motion_id}/tally", payload, headers
        )

    # -- publication notices (PRD 3.6) ------------------------------------

    def get_publication_notice(
        self, notice_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/publication-notices/{notice_id}", None, headers
        )

    def list_publication_notices(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/publication-notices", params, headers)

    def order_publication(
        self, notice_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/publication-notices/{notice_id}/order",
            payload,
            headers,
        )

    def certify_publication(
        self, notice_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/publication-notices/{notice_id}/certify-publication",
            payload,
            headers,
        )

    # -- code titles and supplement cycles (PRD 3.7) ----------------------

    def create_code_title(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/code-titles", payload, headers)

    def get_code_title(self, title_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/code-titles/{title_id}", None, headers
        )

    def list_code_titles(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/code-titles", params, headers)

    def create_supplement_cycle(
        self, title_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/code-titles/{title_id}/supplement-cycles",
            payload,
            headers,
        )

    def list_title_supplement_cycles(
        self, title_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/code-titles/{title_id}/supplement-cycles",
            params,
            headers,
        )

    def get_supplement_cycle(self, cycle_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/supplement-cycles/{cycle_id}", None, headers
        )

    def list_supplement_cycles(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/supplement-cycles", params, headers)

    def lock_supplement_cycle(
        self, cycle_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/supplement-cycles/{cycle_id}/lock", {}, headers
        )

    def certify_supplement_cycle(
        self, cycle_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/supplement-cycles/{cycle_id}/certify",
            payload,
            headers,
        )

    # -- codification submissions (PRD 3.7) -------------------------------

    def create_codification_submission(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/codification-submissions", payload, headers
        )

    def get_codification_submission(
        self, submission_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/codification-submissions/{submission_id}",
            None,
            headers,
        )

    def list_codification_submissions(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/codification-submissions", params, headers
        )

    def decide_submission(
        self, submission_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/codification-submissions/{submission_id}/decide",
            payload,
            headers,
        )

    def resolve_submission_conflict(
        self, submission_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/codification-submissions/{submission_id}/resolve-conflict",
            payload,
            headers,
        )

    # -- public records requests (PRD 3.8) --------------------------------

    def create_records_request(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/records-requests", payload, headers)

    def get_records_request(self, request_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/records-requests/{request_id}", None, headers
        )

    def list_records_requests(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/records-requests", params, headers)

    def begin_review(self, request_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/begin-review",
            {},
            headers,
        )

    def exemption_review(
        self, request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/exemption-review",
            payload,
            headers,
        )

    def assess_fee(
        self, request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/assess-fee",
            payload,
            headers,
        )

    def waive_fee(
        self, request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/waive-fee",
            payload,
            headers,
        )

    def record_payment(
        self, request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/payments",
            payload,
            headers,
        )

    def record_disposition(
        self, request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/disposition",
            payload,
            headers,
        )

    def withdraw_records_request(
        self, request_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-requests/{request_id}/withdraw",
            {},
            headers,
        )

    def close_records_request(
        self, request_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/records-requests/{request_id}/close", {}, headers
        )

    # -- retention schedule and destruction (PRD 3.9) ---------------------

    def create_record_series(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/record-series", payload, headers)

    def get_record_series(self, series_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/record-series/{series_id}", None, headers
        )

    def update_record_series(
        self, series_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PUT", f"{API_PREFIX}/record-series/{series_id}", payload, headers
        )

    def create_accession(
        self, series_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/record-series/{series_id}/accessions",
            payload,
            headers,
        )

    def create_destruction_batch(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/destruction-batches", payload, headers
        )

    def get_destruction_batch(self, batch_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/destruction-batches/{batch_id}", None, headers
        )

    def list_destruction_batches(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/destruction-batches", params, headers)

    def certify_destruction_batch(
        self, batch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/destruction-batches/{batch_id}/certify",
            payload,
            headers,
        )

    def rescind_destruction_batch(
        self, batch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/destruction-batches/{batch_id}/rescind",
            payload,
            headers,
        )


# Module-level singleton reused by every fixture and test.
api_client = ApiClient()
