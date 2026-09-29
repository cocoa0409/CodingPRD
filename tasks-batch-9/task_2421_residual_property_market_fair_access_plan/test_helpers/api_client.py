"""One method per endpoint of the Residual Property Fair Access Plan API.

Every method returns the raw ``requests.Response`` so that callers can assert on
status codes as well as bodies.  Paths mirror the PRD endpoint table exactly and
are all mounted under ``/fair-plan``.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE_PATH

Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]


class FairPlanApiClient(GenericApiClient):
    """Typed wrapper over the plan's HTTP surface."""

    # ------------------------------------------------------------------
    # Clock and batch capabilities
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/_clock/set_current_utc", payload, headers
        )

    def run_expiration_sweep(
        self, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/sweeps/expiration", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Member insurers
    # ------------------------------------------------------------------
    def create_member_insurer(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/member-insurers", payload, headers)

    def update_member_insurer(
        self, member_insurer_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{BASE_PATH}/member-insurers/{member_insurer_id}", payload, headers
        )

    def get_member_insurer(
        self, member_insurer_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/member-insurers/{member_insurer_id}", None, headers
        )

    def list_member_insurers(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/member-insurers", params, headers)

    def list_member_insurer_declinations(
        self, member_insurer_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/member-insurers/{member_insurer_id}/declinations",
            params,
            headers,
        )

    def list_member_insurer_allocations(
        self, member_insurer_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/member-insurers/{member_insurer_id}/allocations",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Catastrophe zones
    # ------------------------------------------------------------------
    def create_cat_zone(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/cat-zones", payload, headers)

    def get_cat_zone(self, cat_zone_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/cat-zones/{cat_zone_id}", None, headers)

    def list_cat_zone_properties(
        self, cat_zone_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/cat-zones/{cat_zone_id}/properties", params, headers
        )

    def list_cat_zone_rate_filings(
        self, cat_zone_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/cat-zones/{cat_zone_id}/rate-filings", params, headers
        )

    def list_cat_zone_assessment_events(
        self, cat_zone_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/cat-zones/{cat_zone_id}/assessment-events",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Producers
    # ------------------------------------------------------------------
    def create_producer(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/producers", payload, headers)

    def execute_producer_agreement(
        self, producer_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/producers/{producer_id}/agreement-execution",
            payload,
            headers,
        )

    def producer_status_action(
        self, producer_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/producers/{producer_id}/status-actions", payload, headers
        )

    def get_producer(self, producer_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/producers/{producer_id}", None, headers)

    # ------------------------------------------------------------------
    # Applicants and properties
    # ------------------------------------------------------------------
    def create_applicant(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/applicants", payload, headers)

    def create_property(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/properties", payload, headers)

    def get_property(self, property_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/properties/{property_id}", None, headers)

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/applications", payload, headers)

    def get_application(
        self, application_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/applications/{application_id}", None, headers
        )

    def list_applications(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/applications", params, headers)

    def create_declination(
        self, application_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/applications/{application_id}/declinations",
            payload,
            headers,
        )

    def list_application_declinations(
        self, application_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/applications/{application_id}/declinations",
            params,
            headers,
        )

    def submit_application(
        self, application_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/applications/{application_id}/submission",
            payload if payload is not None else {},
            headers,
        )

    def review_application_eligibility(
        self, application_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/applications/{application_id}/eligibility-review",
            payload,
            headers,
        )

    def order_inspection(
        self, application_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/applications/{application_id}/inspections",
            payload if payload is not None else {},
            headers,
        )

    def list_application_inspections(
        self, application_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/applications/{application_id}/inspections",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Inspections and improvement requirements
    # ------------------------------------------------------------------
    def get_inspection(self, inspection_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/inspections/{inspection_id}", None, headers
        )

    def complete_inspection(
        self, inspection_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/inspections/{inspection_id}/completion", payload, headers
        )

    def list_inspection_requirements(
        self, inspection_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/inspections/{inspection_id}/requirements",
            params,
            headers,
        )

    def submit_requirement_evidence(
        self, requirement_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/improvement-requirements/{requirement_id}/evidence",
            payload,
            headers,
        )

    def clear_requirement(
        self, requirement_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/improvement-requirements/{requirement_id}/clearance",
            payload if payload is not None else {},
            headers,
        )

    def waive_requirement(
        self, requirement_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/improvement-requirements/{requirement_id}/waiver",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Rate filings
    # ------------------------------------------------------------------
    def create_rate_filing(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/rate-filings", payload, headers)

    def review_rate_filing(
        self, rate_filing_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/rate-filings/{rate_filing_id}/review", payload, headers
        )

    def get_rate_filing(
        self, rate_filing_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/rate-filings/{rate_filing_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def bind_policy(self, payload: Any, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/policies", payload, headers)

    def get_policy(self, policy_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/policies/{policy_id}", None, headers)

    def list_policies(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/policies", params, headers)

    def cancel_policy(
        self, policy_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/policies/{policy_id}/cancellation", payload, headers
        )

    def renew_policy(
        self, policy_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/policies/{policy_id}/renewal", payload, headers
        )

    def create_takeout_offer(
        self, policy_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/policies/{policy_id}/takeout-offers", payload, headers
        )

    # ------------------------------------------------------------------
    # Take-out offers
    # ------------------------------------------------------------------
    def get_takeout_offer(self, offer_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/takeout-offers/{offer_id}", None, headers
        )

    def list_takeout_offers(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/takeout-offers", params, headers)

    def elect_takeout_offer(
        self, offer_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/takeout-offers/{offer_id}/election", payload, headers
        )

    def withdraw_takeout_offer(
        self, offer_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/takeout-offers/{offer_id}/withdrawal",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------
    def create_assessment_event(
        self, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/assessment-events", payload, headers)

    def run_allocation(
        self, event_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/assessment-events/{event_id}/allocation-run",
            payload,
            headers,
        )

    def invoice_assessment(
        self, event_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/assessment-events/{event_id}/invoicing",
            payload if payload is not None else {},
            headers,
        )

    def cancel_assessment(
        self, event_id: str, payload: Any = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/assessment-events/{event_id}/cancellation",
            payload if payload is not None else {},
            headers,
        )

    def get_assessment_event(
        self, event_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/assessment-events/{event_id}", None, headers
        )

    def list_assessment_event_allocations(
        self, event_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/assessment-events/{event_id}/allocations",
            params,
            headers,
        )

    def pay_allocation(
        self, allocation_id: str, payload: Any, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/assessment-allocations/{allocation_id}/payment",
            payload,
            headers,
        )
