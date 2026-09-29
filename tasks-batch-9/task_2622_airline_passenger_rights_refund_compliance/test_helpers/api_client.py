"""One method per endpoint of PRD §4, plus the logical-clock control endpoint.

Every method returns the raw ``requests.Response`` so tests can assert both the
status code and the envelope. Headers are always explicit: identity is part of
the contract under test, never a client default.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/compliance"


def _query(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset filters so an omitted parameter is genuinely absent."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ApiClient(GenericApiClient):
    # ─── Policy profiles (PRD §2.9) ────────────────────

    def create_policy_profile(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policy-profiles", payload, headers)

    def get_policy_profile(self, profile_id: str, headers) -> requests.Response:
        return self._request("GET", f"{PREFIX}/policy-profiles/{profile_id}", None, headers)

    def list_policy_profile_reports(
        self,
        profile_id: str,
        headers,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/policy-profiles/{profile_id}/regulator-reports",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    # ─── Passengers (PRD §3.1) ─────────────────────────

    def create_passenger(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{PREFIX}/passengers", payload, headers)

    def get_passenger(self, passenger_id: str, headers) -> requests.Response:
        return self._request("GET", f"{PREFIX}/passengers/{passenger_id}", None, headers)

    # ─── Bookings (PRD §3.1, §2.11) ────────────────────

    def create_booking(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def list_bookings(
        self,
        headers,
        passenger_id: Optional[str] = None,
        policy_profile_id: Optional[str] = None,
        disruption_posture: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/bookings",
            _query(
                passenger_id=passenger_id,
                policy_profile_id=policy_profile_id,
                disruption_posture=disruption_posture,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_booking(self, booking_id: str, headers) -> requests.Response:
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", None, headers)

    def get_refund_exposure(self, booking_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/refund-exposure", None, headers
        )

    # ─── Flight segments (PRD §3.1, §3.2) ──────────────

    def create_flight_segment(
        self, booking_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/flight-segments", payload, headers
        )

    def list_booking_flight_segments(
        self,
        booking_id: str,
        headers,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/bookings/{booking_id}/flight-segments",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    def get_flight_segment(self, segment_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/flight-segments/{segment_id}", None, headers
        )

    def declare_disruption(
        self, segment_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/flight-segments/{segment_id}/declare-disruption",
            payload,
            headers,
        )

    def record_operation(
        self, segment_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/flight-segments/{segment_id}/record-operation",
            payload,
            headers,
        )

    def list_segment_tarmac_events(
        self,
        segment_id: str,
        headers,
        status: Optional[str] = None,
        phase: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/flight-segments/{segment_id}/tarmac-delay-events",
            _query(status=status, phase=phase, limit=limit, offset=offset),
            headers,
        )

    # ─── Ancillary purchases (PRD §3.3) ────────────────

    def create_ancillary_purchase(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ancillary-purchases", payload, headers)

    def list_ancillary_purchases(
        self,
        headers,
        booking_id: Optional[str] = None,
        flight_segment_id: Optional[str] = None,
        service_type: Optional[str] = None,
        delivery_status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/ancillary-purchases",
            _query(
                booking_id=booking_id,
                flight_segment_id=flight_segment_id,
                service_type=service_type,
                delivery_status=delivery_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_ancillary_purchase(self, purchase_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/ancillary-purchases/{purchase_id}", None, headers
        )

    def mark_ancillary_not_provided(
        self, purchase_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/ancillary-purchases/{purchase_id}/mark-not-provided",
            payload,
            headers,
        )

    # ─── Checked bags (PRD §3.3) ───────────────────────

    def create_checked_bag(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{PREFIX}/checked-bags", payload, headers)

    def list_booking_checked_bags(
        self,
        booking_id: str,
        headers,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/bookings/{booking_id}/checked-bags",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    def resolve_checked_bag(
        self, bag_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/checked-bags/{bag_id}/resolve", payload, headers
        )

    # ─── Denied boarding records (PRD §3.4) ────────────

    def create_denied_boarding_record(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/denied-boarding-records", payload, headers
        )

    def list_denied_boarding_records(
        self,
        headers,
        booking_id: Optional[str] = None,
        flight_segment_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/denied-boarding-records",
            _query(
                booking_id=booking_id,
                flight_segment_id=flight_segment_id,
                category=category,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_denied_boarding_record(self, record_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/denied-boarding-records/{record_id}", None, headers
        )

    def finalize_denied_boarding_record(
        self, record_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/denied-boarding-records/{record_id}/finalize",
            payload,
            headers,
        )

    # ─── Tarmac delay events (PRD §3.5) ────────────────

    def create_tarmac_delay_event(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tarmac-delay-events", payload, headers)

    def deplane_tarmac_event(
        self, event_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/tarmac-delay-events/{event_id}/deplane", payload, headers
        )

    def claim_tarmac_exemption(
        self, event_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/tarmac-delay-events/{event_id}/claim-exemption",
            payload,
            headers,
        )

    def file_tarmac_report(
        self, event_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/tarmac-delay-events/{event_id}/file-report",
            payload,
            headers,
        )

    # ─── Refund obligations (PRD §3.6, §3.7) ───────────

    def create_refund_obligation(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/refund-obligations", payload, headers)

    def list_refund_obligations(
        self,
        headers,
        booking_id: Optional[str] = None,
        flight_segment_id: Optional[str] = None,
        checked_bag_id: Optional[str] = None,
        ancillary_purchase_id: Optional[str] = None,
        denied_boarding_record_id: Optional[str] = None,
        basis: Optional[str] = None,
        issuance_mode: Optional[str] = None,
        election_status: Optional[str] = None,
        settlement_status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/refund-obligations",
            _query(
                booking_id=booking_id,
                flight_segment_id=flight_segment_id,
                checked_bag_id=checked_bag_id,
                ancillary_purchase_id=ancillary_purchase_id,
                denied_boarding_record_id=denied_boarding_record_id,
                basis=basis,
                issuance_mode=issuance_mode,
                election_status=election_status,
                settlement_status=settlement_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_refund_obligation(self, obligation_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/refund-obligations/{obligation_id}", None, headers
        )

    def elect_refund_obligation(
        self, obligation_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/refund-obligations/{obligation_id}/elect", payload, headers
        )

    def initiate_settlement(
        self, obligation_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/refund-obligations/{obligation_id}/initiate-settlement",
            payload,
            headers,
        )

    def complete_settlement(
        self, obligation_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/refund-obligations/{obligation_id}/complete-settlement",
            payload,
            headers,
        )

    def void_refund_obligation(
        self, obligation_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/refund-obligations/{obligation_id}/void", payload, headers
        )

    # ─── Consumer complaints (PRD §3.8) ────────────────

    def create_consumer_complaint(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/consumer-complaints", payload, headers)

    def list_booking_complaints(
        self,
        booking_id: str,
        headers,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/bookings/{booking_id}/consumer-complaints",
            _query(category=category, status=status, limit=limit, offset=offset),
            headers,
        )

    def get_consumer_complaint(self, complaint_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/consumer-complaints/{complaint_id}", None, headers
        )

    def list_complaint_activities(
        self,
        complaint_id: str,
        headers,
        activity_type: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/consumer-complaints/{complaint_id}/activities",
            _query(activity_type=activity_type, limit=limit, offset=offset),
            headers,
        )

    def acknowledge_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/consumer-complaints/{complaint_id}/acknowledge",
            payload,
            headers,
        )

    def request_complaint_info(
        self, complaint_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/consumer-complaints/{complaint_id}/request-info",
            payload,
            headers,
        )

    def answer_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/consumer-complaints/{complaint_id}/answer",
            payload,
            headers,
        )

    def reopen_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/consumer-complaints/{complaint_id}/reopen",
            payload,
            headers,
        )

    # ─── Regulator reports and the sweep (PRD §3.9) ────

    def create_regulator_report(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/regulator-reports", payload, headers)

    def submit_regulator_report(
        self, report_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/regulator-reports/{report_id}/submit", payload, headers
        )

    def amend_regulator_report(
        self, report_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/regulator-reports/{report_id}/amend", payload, headers
        )

    def run_compliance_sweep(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/compliance-sweeps", payload, headers)

    # ─── Logical clock (PRD §2.8) ──────────────────────

    def set_clock(self, to_iso8601: str, headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Raw escape hatches for path/param edge cases ──

    def raw_get(self, path: str, headers, params: Optional[Dict] = None):
        return self._request("GET", path, params, headers)

    def raw_post(self, path: str, headers, payload: Optional[Dict] = None):
        return self._request("POST", path, payload, headers)
