"""
One method per declared endpoint of the brownfield voluntary-cleanup API.

Every method returns the raw ``requests.Response`` so a test can assert the status
code as well as the envelope. Paths live here and nowhere else, and list filters are
forwarded as query parameters so that pagination and the declared domain filters
behave exactly as the contract describes.

``*_raw`` variants exist wherever a test needs to send a deliberately malformed body
that the typed helper would not let it express.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH


def _params(**kwargs) -> Optional[Dict[str, Any]]:
    """Drop unset filters so a request carries only the parameters a test named."""
    cleaned = {k: v for k, v in kwargs.items() if v is not None}
    return cleaned or None


class BrownfieldClient(GenericApiClient):
    """Typed access to every endpoint of the voluntary-cleanup API."""

    # ─── The logical clock (open to every role) ────────────────────────────────

    def set_clock(self, current_utc: str, headers):
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── The ops-run checkpoint ───────────────────────────────────────────────

    def run_compliance_sweep(self, as_of_date: str, headers, site_id: str = None):
        payload: Dict[str, Any] = {"as_of_date": as_of_date}
        if site_id is not None:
            payload["site_id"] = site_id
        return self._request("POST", "/compliance-sweeps", payload, headers)

    def run_compliance_sweep_raw(self, payload, headers):
        return self._request("POST", "/compliance-sweeps", payload, headers)

    # ─── Parties ──────────────────────────────────────────────────────────────

    def create_party(self, payload, headers):
        return self._request("POST", "/parties", payload, headers)

    def list_parties(self, headers, party_type=None, limit=None, offset=None):
        return self._request(
            "GET",
            "/parties",
            None,
            headers,
            params=_params(party_type=party_type, limit=limit, offset=offset),
        )

    def get_party(self, party_id, headers):
        return self._request("GET", f"/parties/{party_id}", None, headers)

    # ─── Laboratories ─────────────────────────────────────────────────────────

    def create_laboratory(self, payload, headers):
        return self._request("POST", "/laboratories", payload, headers)

    def list_laboratories(self, headers, limit=None, offset=None):
        return self._request(
            "GET",
            "/laboratories",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    def get_laboratory(self, laboratory_id, headers):
        return self._request("GET", f"/laboratories/{laboratory_id}", None, headers)

    # ─── Sites ────────────────────────────────────────────────────────────────

    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(
        self, headers, owner_party_id=None, cleanup_posture=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            "/sites",
            None,
            headers,
            params=_params(
                owner_party_id=owner_party_id,
                cleanup_posture=cleanup_posture,
                limit=limit,
                offset=offset,
            ),
        )

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", None, headers)

    def record_acquisition(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/acquisition", payload, headers
        )

    def get_funding_assembly(self, site_id, headers):
        return self._request(
            "GET", f"/sites/{site_id}/funding-assembly", None, headers
        )

    # ─── Cleanup goals ────────────────────────────────────────────────────────

    def derive_cleanup_goal(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/cleanup-goals", payload, headers
        )

    def list_cleanup_goals(self, site_id, headers, limit=None, offset=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/cleanup-goals",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    def get_cleanup_goal(self, cleanup_goal_id, headers):
        return self._request("GET", f"/cleanup-goals/{cleanup_goal_id}", None, headers)

    # ─── Site-scoped list reads ───────────────────────────────────────────────

    def list_site_liability_protections(self, site_id, headers, limit=None, offset=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/liability-protections",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    def list_site_enrollments(self, site_id, headers, limit=None, offset=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/vcp-enrollments",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    def list_site_funding_awards(self, site_id, headers, limit=None, offset=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/funding-awards",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    # ─── Assessment phases ────────────────────────────────────────────────────

    def create_assessment_phase(self, payload, headers):
        return self._request("POST", "/assessment-phases", payload, headers)

    def list_assessment_phases(
        self,
        headers,
        site_id=None,
        consultant_party_id=None,
        supersedes_phase_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            "/assessment-phases",
            None,
            headers,
            params=_params(
                site_id=site_id,
                consultant_party_id=consultant_party_id,
                supersedes_phase_id=supersedes_phase_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_assessment_phase(self, phase_id, headers):
        return self._request("GET", f"/assessment-phases/{phase_id}", None, headers)

    def record_contaminant_finding(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/assessment-phases/{phase_id}/contaminant-findings", payload, headers
        )

    def list_contaminant_findings(self, phase_id, headers, limit=None, offset=None):
        return self._request(
            "GET",
            f"/assessment-phases/{phase_id}/contaminant-findings",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    def get_contaminant_finding(self, finding_id, headers):
        return self._request(
            "GET", f"/contaminant-findings/{finding_id}", None, headers
        )

    def submit_assessment_phase(self, phase_id, headers, payload=None):
        return self._request(
            "POST", f"/assessment-phases/{phase_id}/submit", payload or {}, headers
        )

    def review_assessment_phase(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/assessment-phases/{phase_id}/review", payload, headers
        )

    # ─── Liability protections ────────────────────────────────────────────────

    def create_liability_protection(self, payload, headers):
        return self._request("POST", "/liability-protections", payload, headers)

    def get_liability_protection(self, protection_id, headers):
        return self._request(
            "GET", f"/liability-protections/{protection_id}", None, headers
        )

    def complete_inquiry(self, protection_id, payload, headers):
        return self._request(
            "POST",
            f"/liability-protections/{protection_id}/inquiry-completion",
            payload,
            headers,
        )

    def impose_continuing_obligation(self, protection_id, payload, headers):
        return self._request(
            "POST",
            f"/liability-protections/{protection_id}/continuing-obligations",
            payload,
            headers,
        )

    def list_continuing_obligations(
        self, protection_id, headers, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"/liability-protections/{protection_id}/continuing-obligations",
            None,
            headers,
            params=_params(limit=limit, offset=offset),
        )

    def get_continuing_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"/continuing-obligations/{obligation_id}", None, headers
        )

    def certify_obligation(self, obligation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/continuing-obligations/{obligation_id}/certify",
            payload or {},
            headers,
        )

    def void_certification(self, obligation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/continuing-obligations/{obligation_id}/void-certification",
            payload or {},
            headers,
        )

    # ─── VCP enrollments ──────────────────────────────────────────────────────

    def create_enrollment(self, payload, headers):
        return self._request("POST", "/vcp-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/vcp-enrollments/{enrollment_id}", None, headers)

    def decide_eligibility(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/vcp-enrollments/{enrollment_id}/eligibility-decision",
            payload,
            headers,
        )

    def request_completion(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/vcp-enrollments/{enrollment_id}/completion-request",
            payload or {},
            headers,
        )

    def withdraw_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/vcp-enrollments/{enrollment_id}/withdraw",
            payload or {},
            headers,
        )

    # ─── Remedial action plans ────────────────────────────────────────────────

    def create_plan(self, payload, headers):
        return self._request("POST", "/remedial-action-plans", payload, headers)

    def list_plans(
        self,
        headers,
        vcp_enrollment_id=None,
        site_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            "/remedial-action-plans",
            None,
            headers,
            params=_params(
                vcp_enrollment_id=vcp_enrollment_id,
                site_id=site_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/remedial-action-plans/{plan_id}", None, headers)

    def patch_plan(self, plan_id, payload, headers):
        return self._request(
            "PATCH", f"/remedial-action-plans/{plan_id}", payload, headers
        )

    def submit_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/remedial-action-plans/{plan_id}/submit", payload or {}, headers
        )

    def technical_review_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/remedial-action-plans/{plan_id}/technical-review", payload, headers
        )

    def close_public_comment(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/remedial-action-plans/{plan_id}/public-comment-close",
            payload,
            headers,
        )

    def approve_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/remedial-action-plans/{plan_id}/approve", payload or {}, headers
        )

    # ─── Cost-cap policies ────────────────────────────────────────────────────

    def quote_policy(self, payload, headers):
        return self._request("POST", "/cost-cap-policies", payload, headers)

    def list_policies(
        self,
        headers,
        remedial_action_plan_id=None,
        insurer_party_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            "/cost-cap-policies",
            None,
            headers,
            params=_params(
                remedial_action_plan_id=remedial_action_plan_id,
                insurer_party_id=insurer_party_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/cost-cap-policies/{policy_id}", None, headers)

    def bind_policy(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/cost-cap-policies/{policy_id}/bind", payload or {}, headers
        )

    # ─── Site controls ────────────────────────────────────────────────────────

    def create_site_control(self, payload, headers):
        return self._request("POST", "/site-controls", payload, headers)

    def list_site_controls(
        self,
        headers,
        site_id=None,
        remedial_action_plan_id=None,
        sub_area_code=None,
        status=None,
        control_class=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            "/site-controls",
            None,
            headers,
            params=_params(
                site_id=site_id,
                remedial_action_plan_id=remedial_action_plan_id,
                sub_area_code=sub_area_code,
                status=status,
                control_class=control_class,
                limit=limit,
                offset=offset,
            ),
        )

    def get_site_control(self, control_id, headers):
        return self._request("GET", f"/site-controls/{control_id}", None, headers)

    def certify_control_operation(self, control_id, payload, headers):
        return self._request(
            "POST", f"/site-controls/{control_id}/operation-certification", payload, headers
        )

    def decommission_control(self, control_id, headers, payload=None):
        return self._request(
            "POST", f"/site-controls/{control_id}/decommission", payload or {}, headers
        )

    # ─── Funding awards ───────────────────────────────────────────────────────

    def create_funding_award(self, payload, headers):
        return self._request("POST", "/funding-awards", payload, headers)

    def list_funding_awards(
        self, headers, site_id=None, funding_kind=None, status=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            "/funding-awards",
            None,
            headers,
            params=_params(
                site_id=site_id,
                funding_kind=funding_kind,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_funding_award(self, award_id, headers):
        return self._request("GET", f"/funding-awards/{award_id}", None, headers)

    def decide_funding_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"/funding-awards/{award_id}/decision", payload, headers
        )

    # ─── No-further-action letters ────────────────────────────────────────────

    def create_nfa_letter(self, payload, headers):
        return self._request("POST", "/nfa-letters", payload, headers)

    def list_nfa_letters(
        self, headers, site_id=None, vcp_enrollment_id=None, status=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            "/nfa-letters",
            None,
            headers,
            params=_params(
                site_id=site_id,
                vcp_enrollment_id=vcp_enrollment_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_nfa_letter(self, letter_id, headers):
        return self._request("GET", f"/nfa-letters/{letter_id}", None, headers)

    def issue_nfa_letter(self, letter_id, headers, payload=None):
        return self._request(
            "POST", f"/nfa-letters/{letter_id}/issue", payload or {}, headers
        )

    def accept_nfa_letter(self, letter_id, payload, headers):
        return self._request(
            "POST", f"/nfa-letters/{letter_id}/lender-acceptance", payload, headers
        )

    # ─── Monitoring events ────────────────────────────────────────────────────

    def create_monitoring_event(self, payload, headers):
        return self._request("POST", "/monitoring-events", payload, headers)

    def list_monitoring_events(
        self,
        headers,
        site_id=None,
        laboratory_id=None,
        cleanup_goal_id=None,
        site_control_id=None,
        event_type=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            "/monitoring-events",
            None,
            headers,
            params=_params(
                site_id=site_id,
                laboratory_id=laboratory_id,
                cleanup_goal_id=cleanup_goal_id,
                site_control_id=site_control_id,
                event_type=event_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_monitoring_event(self, event_id, headers):
        return self._request("GET", f"/monitoring-events/{event_id}", None, headers)

    def file_monitoring_result(self, event_id, payload, headers):
        return self._request(
            "POST", f"/monitoring-events/{event_id}/results", payload, headers
        )
