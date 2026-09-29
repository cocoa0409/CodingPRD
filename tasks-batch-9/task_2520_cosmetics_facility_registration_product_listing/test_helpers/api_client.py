"""One method per route of the Cosmetics API, all mounted under /cosmetics."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class CosmeticsApiClient(GenericApiClient):
    """Thin transport wrapper: every method returns the raw response."""

    # ------------------------------------------------------------------
    # Establishment registration
    # ------------------------------------------------------------------
    def create_facility(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/facilities/{facility_id}", None, headers)

    def list_facilities(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/facilities", params, headers)

    def submit_registration(self, facility_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/facilities/{facility_id}/submit-registration",
            payload if payload is not None else {}, headers,
        )

    def decide_registration(self, facility_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/facilities/{facility_id}/registration-decision",
            payload, headers,
        )

    def file_renewal(self, facility_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/facilities/{facility_id}/renewals", payload, headers
        )

    def list_registration_periods(self, facility_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}/registration-periods",
            params, headers,
        )

    # ------------------------------------------------------------------
    # Ownership changes
    # ------------------------------------------------------------------
    def file_ownership_change(self, facility_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/facilities/{facility_id}/ownership-changes",
            payload, headers,
        )

    def list_ownership_changes(self, facility_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}/ownership-changes",
            params, headers,
        )

    def decide_ownership_change(self, ownership_change_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/ownership-changes/{ownership_change_id}/decision",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Compliance ledger
    # ------------------------------------------------------------------
    def list_ledger_entries(self, facility_id: str, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}/ledger-entries",
            params, headers,
        )

    # ------------------------------------------------------------------
    # Inspection engagements
    # ------------------------------------------------------------------
    def schedule_inspection(self, facility_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/facilities/{facility_id}/inspections", payload, headers
        )

    def list_inspections(self, facility_id: str, headers: Dict[str, str],
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}/inspections", params, headers
        )

    def issue_observations(self, facility_id: str, inspection_id: str,
                           payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/facilities/{facility_id}/inspections/{inspection_id}/observations",
            payload, headers,
        )

    def submit_inspection_response(self, facility_id: str, inspection_id: str,
                                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/facilities/{facility_id}/inspections/{inspection_id}/response",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Responsible persons
    # ------------------------------------------------------------------
    def create_responsible_person(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/responsible-persons", payload, headers)

    def get_responsible_person(self, responsible_person_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/responsible-persons/{responsible_person_id}",
            None, headers,
        )

    # ------------------------------------------------------------------
    # Product listings
    # ------------------------------------------------------------------
    def create_listing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/listings", payload, headers)

    def get_listing(self, listing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/listings/{listing_id}", None, headers)

    def list_listings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/listings", params, headers)

    def add_ingredient(self, listing_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/ingredients", payload, headers
        )

    def list_ingredients(self, listing_id: str, headers: Dict[str, str],
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/listings/{listing_id}/ingredients", params, headers
        )

    def submit_listing(self, listing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def decide_listing(self, listing_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/listing-decision", payload, headers
        )

    def transfer_responsible_person(self, listing_id: str, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/transfer-responsible-person",
            payload, headers,
        )

    def delist_listing(self, listing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/delist",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Safety substantiation
    # ------------------------------------------------------------------
    def open_substantiation(self, listing_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/substantiations", payload, headers
        )

    def list_substantiations(self, listing_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/listings/{listing_id}/substantiations", params, headers
        )

    def get_substantiation(self, substantiation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/substantiations/{substantiation_id}", None, headers
        )

    def add_review_item(self, substantiation_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/substantiations/{substantiation_id}/review-items",
            payload, headers,
        )

    def list_review_items(self, substantiation_id: str, headers: Dict[str, str],
                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/substantiations/{substantiation_id}/review-items",
            params, headers,
        )

    def submit_substantiation(self, substantiation_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/substantiations/{substantiation_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def decide_substantiation_review(self, substantiation_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/substantiations/{substantiation_id}/review-decision",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Adverse events
    # ------------------------------------------------------------------
    def record_adverse_event(self, listing_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/adverse-events", payload, headers
        )

    def list_adverse_events(self, listing_id: str, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/listings/{listing_id}/adverse-events", params, headers
        )

    def file_adverse_event_report(self, adverse_event_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/adverse-events/{adverse_event_id}/report",
            payload if payload is not None else {}, headers,
        )

    def reclassify_adverse_event(self, adverse_event_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/adverse-events/{adverse_event_id}/reclassify",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Recall actions
    # ------------------------------------------------------------------
    def open_recall_action(self, listing_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/recall-actions", payload, headers
        )

    def list_recall_actions(self, listing_id: str, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/listings/{listing_id}/recall-actions", params, headers
        )

    def get_recall_action(self, recall_action_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/recall-actions/{recall_action_id}", None, headers
        )

    def submit_recall_plan(self, recall_action_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recall-actions/{recall_action_id}/plan", payload, headers
        )

    def decide_recall_plan(self, recall_action_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recall-actions/{recall_action_id}/plan-decision",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Market withdrawals and distribution records
    # ------------------------------------------------------------------
    def open_withdrawal(self, recall_action_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/recall-actions/{recall_action_id}/withdrawals",
            payload, headers,
        )

    def list_withdrawals(self, recall_action_id: str, headers: Dict[str, str],
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/recall-actions/{recall_action_id}/withdrawals",
            params, headers,
        )

    def get_withdrawal(self, withdrawal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/withdrawals/{withdrawal_id}", None, headers
        )

    def produce_records(self, withdrawal_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/withdrawals/{withdrawal_id}/records-production",
            payload, headers,
        )

    def post_recovery_entry(self, withdrawal_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/withdrawals/{withdrawal_id}/recovery-entries",
            payload, headers,
        )

    def run_effectiveness_check(self, withdrawal_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/withdrawals/{withdrawal_id}/effectiveness-check",
            payload, headers,
        )

    def create_distribution_record(self, listing_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/distribution-records",
            payload, headers,
        )

    def list_distribution_records(self, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/distribution-records", params, headers
        )

    def get_distribution_record(self, distribution_record_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/distribution-records/{distribution_record_id}",
            None, headers,
        )

    # ------------------------------------------------------------------
    # Operator capabilities
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    def run_compliance_sweep(self, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/_ops/compliance-sweep",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Escape hatches for deliberately malformed calls
    # ------------------------------------------------------------------
    def raw_post(self, path: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}{path}", payload, headers)

    def raw_get(self, path: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}{path}", params, headers)
