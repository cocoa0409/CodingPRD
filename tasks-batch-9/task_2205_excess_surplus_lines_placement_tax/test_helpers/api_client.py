"""Typed HTTP client -- one method per endpoint of PRD section 4.

Every method returns the raw ``requests.Response`` so that tests can assert
status codes and error envelopes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -----------------------------------------------------------------
    # Brokers and licences
    # -----------------------------------------------------------------
    def create_broker(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/brokers", payload, headers)

    def get_broker(self, broker_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/brokers/{broker_id}", None, headers)

    def suspend_broker(self, broker_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/brokers/{broker_id}/suspend", payload or {}, headers)

    def create_broker_license(self, broker_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/brokers/{broker_id}/licenses", payload, headers)

    def list_broker_licenses(
        self, broker_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/brokers/{broker_id}/licenses", params, headers)

    # -----------------------------------------------------------------
    # State programs
    # -----------------------------------------------------------------
    def create_state_program(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/state-programs", payload, headers)

    def get_state_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/state-programs/{program_id}", None, headers)

    def patch_state_program(self, program_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/state-programs/{program_id}", payload, headers)

    # -----------------------------------------------------------------
    # Carriers
    # -----------------------------------------------------------------
    def create_carrier(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/carriers/{carrier_id}", None, headers)

    def patch_carrier(self, carrier_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/carriers/{carrier_id}", payload, headers)

    # -----------------------------------------------------------------
    # Carrier eligibilities (the white list)
    # -----------------------------------------------------------------
    def create_carrier_eligibility(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/carrier-eligibilities", payload, headers)

    def get_carrier_eligibility(self, eligibility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/carrier-eligibilities/{eligibility_id}", None, headers)

    def list_carrier_eligibilities(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/carrier-eligibilities", params, headers)

    def remove_carrier_eligibility(
        self, eligibility_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/carrier-eligibilities/{eligibility_id}/remove", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Market security reviews
    # -----------------------------------------------------------------
    def create_security_review(
        self, carrier_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/carriers/{carrier_id}/security-reviews", payload or {}, headers
        )

    def list_security_reviews(
        self, carrier_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/carriers/{carrier_id}/security-reviews", params, headers)

    def start_security_review(self, review_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/market-security-reviews/{review_id}/start", payload or {}, headers
        )

    def decide_security_review(self, review_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/market-security-reviews/{review_id}/decide", payload, headers
        )

    # -----------------------------------------------------------------
    # Placements
    # -----------------------------------------------------------------
    def create_placement(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/placements/{placement_id}", None, headers)

    def list_placements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/placements", params, headers)

    def begin_search(self, placement_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/placements/{placement_id}/begin-search", payload or {}, headers
        )

    def complete_search(self, placement_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/placements/{placement_id}/complete-search", payload or {}, headers
        )

    def request_changes(self, placement_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/placements/{placement_id}/request-changes", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Declinations
    # -----------------------------------------------------------------
    def create_declination(self, placement_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/placements/{placement_id}/declinations", payload, headers)

    def list_declinations(
        self, placement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/placements/{placement_id}/declinations", params, headers)

    def invalidate_declination(
        self, declination_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/declinations/{declination_id}/invalidate", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Policies
    # -----------------------------------------------------------------
    def create_policy(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/policies/{policy_id}", None, headers)

    def list_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/policies", params, headers)

    def affix_notices(self, policy_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/policies/{policy_id}/affix-notices", payload, headers)

    def calculate_tax(self, policy_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/policies/{policy_id}/calculate-tax", payload or {}, headers
        )

    def submit_stamping(self, policy_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/policies/{policy_id}/submit-stamping", payload or {}, headers
        )

    def stamping_decision(self, policy_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/policies/{policy_id}/stamping-decision", payload, headers)

    def list_allocations(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/policies/{policy_id}/allocations", params, headers)

    # -----------------------------------------------------------------
    # Endorsements
    # -----------------------------------------------------------------
    def create_endorsement(self, policy_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/policies/{policy_id}/endorsements", payload, headers)

    def get_endorsement(self, endorsement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/endorsements/{endorsement_id}", None, headers)

    def list_endorsements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/endorsements", params, headers)

    def issue_endorsement(self, endorsement_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/endorsements/{endorsement_id}/issue", payload or {}, headers
        )

    def void_endorsement(self, endorsement_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/endorsements/{endorsement_id}/void", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Cancellations
    # -----------------------------------------------------------------
    def create_cancellation(self, policy_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/policies/{policy_id}/cancellations", payload, headers)

    def list_cancellations(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/policies/{policy_id}/cancellations", params, headers)

    def process_cancellation(
        self, cancellation_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/cancellations/{cancellation_id}/process", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Tax filing lines
    # -----------------------------------------------------------------
    def get_tax_filing_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tax-filing-lines/{line_id}", None, headers)

    def list_tax_filing_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/tax-filing-lines", params, headers)

    # -----------------------------------------------------------------
    # Filing batches
    # -----------------------------------------------------------------
    def create_filing_batch(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/filing-batches", payload, headers)

    def get_filing_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/filing-batches/{batch_id}", None, headers)

    def list_filing_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/filing-batches", params, headers)

    def prepare_filing_batch(self, batch_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/filing-batches/{batch_id}/prepare", payload or {}, headers
        )

    def submit_filing_batch(self, batch_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/filing-batches/{batch_id}/submit", payload or {}, headers)

    def remit_filing_batch(self, batch_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/filing-batches/{batch_id}/remit", payload, headers)

    # -----------------------------------------------------------------
    # Affidavits
    # -----------------------------------------------------------------
    def create_affidavit(self, policy_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/policies/{policy_id}/affidavits", payload, headers)

    def list_affidavits(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/policies/{policy_id}/affidavits", params, headers)

    def sign_affidavit(self, affidavit_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/affidavits/{affidavit_id}/sign", payload or {}, headers)
