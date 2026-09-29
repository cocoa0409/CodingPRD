"""One method per endpoint of the Organ Procurement Donor Management API.

Every method returns the raw ``requests.Response`` so that a test can assert on
the status code as well as the envelope.  No method validates anything; the
validators in the framework do that.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class OpoApiClient(GenericApiClient):
    """Typed wrapper over the ``/opo`` surface plus the logical-clock control."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Hospital partners
    # ------------------------------------------------------------------
    def create_hospital_partner(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/hospital-partners", payload, headers)

    def get_hospital_partner(self, hospital_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/hospital-partners/{hospital_id}", None, headers
        )

    def get_hospital_performance(
        self, hospital_id: str, headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/hospital-partners/{hospital_id}/performance",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Recovery teams
    # ------------------------------------------------------------------
    def create_recovery_team(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/recovery-teams", payload, headers)

    def get_recovery_team(self, team_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/recovery-teams/{team_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Transport assets
    # ------------------------------------------------------------------
    def create_transport_asset(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/transport-assets", payload, headers)

    def get_transport_asset(self, asset_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/transport-assets/{asset_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Death referrals
    # ------------------------------------------------------------------
    def create_death_referral(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/death-referrals", payload, headers)

    def get_death_referral(self, referral_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/death-referrals/{referral_id}", None, headers
        )

    def list_death_referrals(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/death-referrals", params, headers)

    # ------------------------------------------------------------------
    # Eligibility screenings
    # ------------------------------------------------------------------
    def create_screening(self, referral_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/death-referrals/{referral_id}/screenings",
            payload or {},
            headers,
        )

    def list_screenings_for_referral(self, referral_id: str, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/death-referrals/{referral_id}/screenings",
            params,
            headers,
        )

    def get_screening(self, screening_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/eligibility-screenings/{screening_id}", None, headers
        )

    def submit_risk_assessment(
        self, screening_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-screenings/{screening_id}/risk-assessment",
            payload,
            headers,
        )

    def file_serology_result(self, screening_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-screenings/{screening_id}/serology-results",
            payload,
            headers,
        )

    def list_serology_results(self, screening_id: str, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/eligibility-screenings/{screening_id}/serology-results",
            params,
            headers,
        )

    def request_info(self, screening_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-screenings/{screening_id}/request-info",
            payload or {},
            headers,
        )

    def submit_screening_decision(
        self, screening_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-screenings/{screening_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Authorizations
    # ------------------------------------------------------------------
    def create_authorization(self, referral_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/death-referrals/{referral_id}/authorizations",
            payload,
            headers,
        )

    def list_authorizations_for_referral(self, referral_id: str, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/death-referrals/{referral_id}/authorizations",
            params,
            headers,
        )

    def get_authorization(self, authorization_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/authorizations/{authorization_id}", None, headers
        )

    def create_nok_contact(
        self, authorization_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/authorizations/{authorization_id}/nok-contacts",
            payload,
            headers,
        )

    def list_nok_contacts(self, authorization_id: str, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/authorizations/{authorization_id}/nok-contacts",
            params,
            headers,
        )

    def upload_document(self, authorization_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/authorizations/{authorization_id}/documents",
            payload,
            headers,
        )

    def finalize_authorization(self, authorization_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/authorizations/{authorization_id}/finalize",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Donor cases
    # ------------------------------------------------------------------
    def create_donor_case(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/donor-cases", payload, headers)

    def get_donor_case(self, case_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/donor-cases/{case_id}", None, headers
        )

    def list_donor_cases(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/donor-cases", params, headers)

    def create_observation(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/donor-cases/{case_id}/observations", payload, headers
        )

    def list_observations(self, case_id: str, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/donor-cases/{case_id}/observations", params, headers
        )

    def create_organ(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/donor-cases/{case_id}/organs", payload, headers
        )

    # ------------------------------------------------------------------
    # Organs
    # ------------------------------------------------------------------
    def get_organ(self, organ_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/organs/{organ_id}", None, headers)

    def list_organs(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/organs", params, headers)

    def submit_organ_evaluation(self, organ_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/organs/{organ_id}/evaluation", payload, headers
        )

    def create_match_run(self, organ_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/organs/{organ_id}/match-runs", payload, headers
        )

    def list_match_runs_for_organ(self, organ_id: str, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/organs/{organ_id}/match-runs", params, headers
        )

    def dispatch_transport(self, organ_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/organs/{organ_id}/transport", payload, headers
        )

    def record_disposition(self, organ_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/organs/{organ_id}/disposition", payload, headers
        )

    # ------------------------------------------------------------------
    # Match runs and offers
    # ------------------------------------------------------------------
    def get_match_run(self, run_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/match-runs/{run_id}", None, headers)

    def list_offers(self, run_id: str, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/match-runs/{run_id}/offers", params, headers
        )

    def respond_to_offer(
        self, run_id: str, offer_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/match-runs/{run_id}/offers/{offer_id}/respond",
            payload,
            headers,
        )

    def advance_match_run(self, run_id: str, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/match-runs/{run_id}/advance", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Recovery operations
    # ------------------------------------------------------------------
    def create_recovery_operation(self, case_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/donor-cases/{case_id}/recovery-operations",
            payload,
            headers,
        )

    def get_recovery_operation(self, operation_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/recovery-operations/{operation_id}", None, headers
        )

    def list_recovery_operations(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/recovery-operations", params, headers
        )

    def record_cross_clamp(self, operation_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/recovery-operations/{operation_id}/cross-clamp",
            payload or {},
            headers,
        )

    def cancel_recovery_operation(self, operation_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/recovery-operations/{operation_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw helpers for negative path-shape probes
    # ------------------------------------------------------------------
    def raw_post(self, path: str, payload: Any, headers):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", path, params, headers)


def candidate(
    sequence_position: int,
    center_code: str,
    candidate_code: str,
    acceptance_clock_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Build one entry of a match run's ``candidates`` array."""
    entry: Dict[str, Any] = {
        "sequence_position": sequence_position,
        "center_code": center_code,
        "candidate_code": candidate_code,
    }
    if acceptance_clock_minutes is not None:
        entry["acceptance_clock_minutes"] = acceptance_clock_minutes
    return entry


def candidate_sequence(
    count: int, acceptance_clock_minutes: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Build a contiguous candidate list of ``count`` entries starting at 1."""
    return [
        candidate(
            i + 1,
            f"CTR-{chr(ord('A') + i)}",
            f"CAND-{chr(ord('A') + i)}",
            acceptance_clock_minutes,
        )
        for i in range(count)
    ]
