"""One method per endpoint of the Trauma Verification Registry API.

Every method returns the raw ``requests.Response`` so a test can assert on the HTTP
status as well as the envelope. List methods accept a ``params`` mapping for the
filters and pagination the contract declares.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint surface of the API under test."""

    # ─── The logical clock ────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc — move the logical clock to a supplied instant."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Trauma centers ───────────────────────────────────

    def create_trauma_center(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /trauma-centers — register a verified trauma center."""
        return self._request("POST", "/trauma-centers", payload, headers)

    def get_trauma_center(
        self, center_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /trauma-centers/{id} — read one center with its computed fields."""
        return self._request("GET", f"/trauma-centers/{center_id}", None, headers)

    def list_trauma_centers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /trauma-centers — list centers."""
        return self._request("GET", "/trauma-centers", params, headers)

    # ─── Activation criteria tiers ────────────────────────

    def create_activation_tier(
        self, center_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /trauma-centers/{id}/activation-tiers — configure one tier."""
        return self._request(
            "POST", f"/trauma-centers/{center_id}/activation-tiers", payload, headers
        )

    def list_activation_tiers(
        self,
        center_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /trauma-centers/{id}/activation-tiers — list the center's tiers."""
        return self._request(
            "GET", f"/trauma-centers/{center_id}/activation-tiers", params, headers
        )

    # ─── Computed center reads ────────────────────────────

    def get_triage_rates(
        self,
        center_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /trauma-centers/{id}/triage-rates — computed under/over-triage rates."""
        return self._request(
            "GET", f"/trauma-centers/{center_id}/triage-rates", params, headers
        )

    # ─── Data dictionary rules ────────────────────────────

    def create_data_dictionary_rule(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /data-dictionary-rules — declare one immutable dictionary rule."""
        return self._request("POST", "/data-dictionary-rules", payload, headers)

    def list_data_dictionary_rules(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /data-dictionary-rules — list dictionary rules."""
        return self._request("GET", "/data-dictionary-rules", params, headers)

    # ─── Registry cases ───────────────────────────────────

    def create_registry_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /registry-cases — open a case against one activation tier."""
        return self._request("POST", "/registry-cases", payload, headers)

    def get_registry_case(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /registry-cases/{id} — read one case with its computed fields."""
        return self._request("GET", f"/registry-cases/{case_id}", None, headers)

    def list_registry_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /registry-cases — filtered list of registry cases."""
        return self._request("GET", "/registry-cases", params, headers)

    def lock_registry_case(
        self, case_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """POST /registry-cases/{id}/lock — lock a validated case."""
        return self._request(
            "POST", f"/registry-cases/{case_id}/lock", payload or {}, headers
        )

    def triage_review_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /registry-cases/{id}/triage-review — adjudicate the triage decision."""
        return self._request(
            "POST", f"/registry-cases/{case_id}/triage-review", payload, headers
        )

    def record_transfer_out(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /registry-cases/{id}/transfer-out — record a transfer-out."""
        return self._request(
            "POST", f"/registry-cases/{case_id}/transfer-out", payload, headers
        )

    def rescind_transfer_out(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /registry-cases/{id}/transfer-out/rescind — reverse a transfer-out."""
        return self._request(
            "POST", f"/registry-cases/{case_id}/transfer-out/rescind", payload, headers
        )

    # ─── Abstraction records ──────────────────────────────

    def create_abstraction(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /registry-cases/{id}/abstractions — submit an abstraction."""
        return self._request(
            "POST", f"/registry-cases/{case_id}/abstractions", payload, headers
        )

    def list_abstractions(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /registry-cases/{id}/abstractions — list the case's abstractions."""
        return self._request(
            "GET", f"/registry-cases/{case_id}/abstractions", params, headers
        )

    def validate_abstraction(
        self,
        abstraction_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /abstractions/{id}/validate — accept a submitted abstraction."""
        return self._request(
            "POST", f"/abstractions/{abstraction_id}/validate", payload or {}, headers
        )

    def reject_abstraction(
        self, abstraction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /abstractions/{id}/reject — reject an abstraction and reopen the case."""
        return self._request(
            "POST", f"/abstractions/{abstraction_id}/reject", payload, headers
        )

    # ─── Response logs ────────────────────────────────────

    def create_response_log(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /registry-cases/{id}/response-logs — document one responder."""
        return self._request(
            "POST", f"/registry-cases/{case_id}/response-logs", payload, headers
        )

    def list_response_logs(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /registry-cases/{id}/response-logs — list the case's response logs."""
        return self._request(
            "GET", f"/registry-cases/{case_id}/response-logs", params, headers
        )

    # ─── PI events ────────────────────────────────────────

    def create_pi_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /pi-events — open a performance-improvement event manually."""
        return self._request("POST", "/pi-events", payload, headers)

    def get_pi_event(self, pi_event_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /pi-events/{id} — read one event with its deadline and counters."""
        return self._request("GET", f"/pi-events/{pi_event_id}", None, headers)

    def list_pi_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /pi-events — filtered list of PI events."""
        return self._request("GET", "/pi-events", params, headers)

    def start_pi_review(
        self,
        pi_event_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /pi-events/{id}/start-review — move an event into review."""
        return self._request(
            "POST", f"/pi-events/{pi_event_id}/start-review", payload or {}, headers
        )

    def close_pi_loop(
        self, pi_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /pi-events/{id}/close-loop — document loop closure."""
        return self._request(
            "POST", f"/pi-events/{pi_event_id}/close-loop", payload, headers
        )

    def reopen_pi_event(
        self, pi_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /pi-events/{id}/reopen — reopen a closed loop."""
        return self._request(
            "POST", f"/pi-events/{pi_event_id}/reopen", payload, headers
        )

    # ─── Corrective actions ───────────────────────────────

    def create_corrective_action(
        self, pi_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /pi-events/{id}/corrective-actions — attach a corrective action."""
        return self._request(
            "POST", f"/pi-events/{pi_event_id}/corrective-actions", payload, headers
        )

    def list_corrective_actions(
        self,
        pi_event_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /pi-events/{id}/corrective-actions — list the event's actions."""
        return self._request(
            "GET", f"/pi-events/{pi_event_id}/corrective-actions", params, headers
        )

    def complete_corrective_action(
        self,
        action_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /corrective-actions/{id}/complete — mark an action complete."""
        return self._request(
            "POST", f"/corrective-actions/{action_id}/complete", payload or {}, headers
        )

    def verify_corrective_action(
        self,
        action_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /corrective-actions/{id}/verify — verify a completed action."""
        return self._request(
            "POST", f"/corrective-actions/{action_id}/verify", payload or {}, headers
        )

    # ─── Verification cycles ──────────────────────────────

    def create_verification_cycle(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /verification-cycles — open a national or state cycle."""
        return self._request("POST", "/verification-cycles", payload, headers)

    def get_verification_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /verification-cycles/{id} — read one cycle."""
        return self._request("GET", f"/verification-cycles/{cycle_id}", None, headers)

    def list_verification_cycles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /verification-cycles — list cycles across centers."""
        return self._request("GET", "/verification-cycles", params, headers)

    def list_center_verification_cycles(
        self,
        center_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /trauma-centers/{id}/verification-cycles — the center's cycles."""
        return self._request(
            "GET", f"/trauma-centers/{center_id}/verification-cycles", params, headers
        )

    def get_cycle_readiness(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /verification-cycles/{id}/readiness — computed readiness read."""
        return self._request(
            "GET", f"/verification-cycles/{cycle_id}/readiness", params, headers
        )

    def submit_verification_cycle(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /verification-cycles/{id}/submit — submit the prepared cycle."""
        return self._request(
            "POST", f"/verification-cycles/{cycle_id}/submit", payload or {}, headers
        )

    def schedule_site_visit(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /verification-cycles/{id}/schedule-site-visit — confirm the visit date."""
        return self._request(
            "POST", f"/verification-cycles/{cycle_id}/schedule-site-visit", payload, headers
        )

    def begin_cycle_review(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /verification-cycles/{id}/begin-review — open deliberation."""
        return self._request(
            "POST", f"/verification-cycles/{cycle_id}/begin-review", payload or {}, headers
        )

    def decide_verification_cycle(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /verification-cycles/{id}/decide — render the decision."""
        return self._request(
            "POST", f"/verification-cycles/{cycle_id}/decide", payload, headers
        )

    # ─── Criteria deficiencies ────────────────────────────

    def create_criteria_deficiency(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /verification-cycles/{id}/deficiencies — record a deficiency."""
        return self._request(
            "POST", f"/verification-cycles/{cycle_id}/deficiencies", payload, headers
        )

    def list_criteria_deficiencies(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /verification-cycles/{id}/deficiencies — list the cycle's deficiencies."""
        return self._request(
            "GET", f"/verification-cycles/{cycle_id}/deficiencies", params, headers
        )

    def submit_remediation(
        self, deficiency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /criteria-deficiencies/{id}/remediation — submit remediation evidence."""
        return self._request(
            "POST", f"/criteria-deficiencies/{deficiency_id}/remediation", payload, headers
        )

    def close_criteria_deficiency(
        self,
        deficiency_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /criteria-deficiencies/{id}/close — accept remediation and close."""
        return self._request(
            "POST",
            f"/criteria-deficiencies/{deficiency_id}/close",
            payload or {},
            headers,
        )

    def escalate_criteria_deficiency(
        self, deficiency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /criteria-deficiencies/{id}/escalate — escalate an unremediated deficiency."""
        return self._request(
            "POST", f"/criteria-deficiencies/{deficiency_id}/escalate", payload, headers
        )

    # ─── Surveyor bookings ────────────────────────────────

    def create_surveyor_booking(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /verification-cycles/{id}/surveyor-bookings — book a review window."""
        return self._request(
            "POST", f"/verification-cycles/{cycle_id}/surveyor-bookings", payload, headers
        )

    def list_surveyor_bookings(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /verification-cycles/{id}/surveyor-bookings — list the cycle's bookings."""
        return self._request(
            "GET", f"/verification-cycles/{cycle_id}/surveyor-bookings", params, headers
        )

    # ─── Outreach activities ──────────────────────────────

    def create_outreach_activity(
        self, center_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /trauma-centers/{id}/outreach-activities — log one activity."""
        return self._request(
            "POST", f"/trauma-centers/{center_id}/outreach-activities", payload, headers
        )

    def list_outreach_activities(
        self,
        center_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /trauma-centers/{id}/outreach-activities — list the center's activities."""
        return self._request(
            "GET", f"/trauma-centers/{center_id}/outreach-activities", params, headers
        )

    def verify_outreach_activity(
        self,
        activity_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /outreach-activities/{id}/verify — verify a logged activity."""
        return self._request(
            "POST", f"/outreach-activities/{activity_id}/verify", payload or {}, headers
        )

    def reject_outreach_activity(
        self, activity_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /outreach-activities/{id}/reject — reject a logged or verified activity."""
        return self._request(
            "POST", f"/outreach-activities/{activity_id}/reject", payload, headers
        )

    # ─── Referral agreements ──────────────────────────────

    def create_referral_agreement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-agreements — draft an agreement for a directed pair."""
        return self._request("POST", "/referral-agreements", payload, headers)

    def activate_referral_agreement(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /referral-agreements/{id}/activate — the receiving center activates."""
        return self._request(
            "POST", f"/referral-agreements/{agreement_id}/activate", payload or {}, headers
        )

    def terminate_referral_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /referral-agreements/{id}/terminate — either party terminates."""
        return self._request(
            "POST", f"/referral-agreements/{agreement_id}/terminate", payload, headers
        )

    def list_center_referral_agreements(
        self,
        center_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /trauma-centers/{id}/referral-agreements — agreements touching a center."""
        return self._request(
            "GET", f"/trauma-centers/{center_id}/referral-agreements", params, headers
        )
