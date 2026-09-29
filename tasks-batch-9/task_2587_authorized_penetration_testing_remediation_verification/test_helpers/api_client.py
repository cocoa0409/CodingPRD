"""Domain client for the Pentest Assurance API.

Every collection lives beneath the ``/pentest`` prefix, with the single
exception of the logical-clock capability, and every method below returns the
raw response so the caller can validate a success envelope or an error envelope
as the assertion requires.

Each method carries a role-appropriate default set of headers, so a test only
passes ``headers=`` when the acting identity is part of what it is proving.
"""

from prd_bench_local_runner.testing import GenericApiClient

from . import api_errors  # noqa: F401  (registers the error/status catalogue)
from .constants import API_PREFIX, CLOCK_PATH
from .test_users import (
    admin_headers,
    compliance_officer_headers,
    program_manager_headers,
    remediation_owner_headers,
)


class PentestApiClient(GenericApiClient):
    """Thin, explicit wrapper over the HTTP surface of the service."""

    # -- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers=None):
        return self.post(
            CLOCK_PATH,
            json={"to_iso8601": to_iso8601},
            headers=headers or admin_headers(),
        )

    # -- assets ---------------------------------------------------------
    def create_asset(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/assets", json=payload, headers=headers or admin_headers()
        )

    def get_asset(self, asset_id, headers=None):
        return self.get(
            f"{API_PREFIX}/assets/{asset_id}",
            headers=headers or program_manager_headers(),
        )

    def list_assets(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/assets",
            params=params,
            headers=headers or program_manager_headers(),
        )

    # -- test plans -----------------------------------------------------
    def create_test_plan(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/test-plans",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_test_plan(self, plan_id, headers=None):
        return self.get(
            f"{API_PREFIX}/test-plans/{plan_id}",
            headers=headers or program_manager_headers(),
        )

    def list_test_plans(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/test-plans",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def set_prioritization_mode(self, plan_id, mode, headers=None):
        return self.post(
            f"{API_PREFIX}/test-plans/{plan_id}/prioritization-mode",
            json={"prioritization_mode": mode},
            headers=headers or program_manager_headers(),
        )

    def activate_test_plan(self, plan_id, headers=None):
        return self.post(
            f"{API_PREFIX}/test-plans/{plan_id}/activate",
            json={},
            headers=headers or program_manager_headers(),
        )

    def generate_training_recommendations(
        self, plan_id, window_start, window_end, headers=None
    ):
        return self.post(
            f"{API_PREFIX}/test-plans/{plan_id}/training-recommendations",
            json={"window_start": window_start, "window_end": window_end},
            headers=headers or program_manager_headers(),
        )

    def list_plan_training_recommendations(self, plan_id, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/test-plans/{plan_id}/training-recommendations",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def get_training_recommendation(self, recommendation_id, headers=None):
        return self.get(
            f"{API_PREFIX}/training-recommendations/{recommendation_id}",
            headers=headers or program_manager_headers(),
        )

    # -- scope items ----------------------------------------------------
    def create_scope_item(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/scope-items",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_scope_item(self, scope_item_id, headers=None):
        return self.get(
            f"{API_PREFIX}/scope-items/{scope_item_id}",
            headers=headers or program_manager_headers(),
        )

    def list_scope_items(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/scope-items",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def decide_scope_item(self, scope_item_id, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/scope-items/{scope_item_id}/decision",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    # -- engagements ----------------------------------------------------
    def create_engagement(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/engagements",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_engagement(self, engagement_id, headers=None):
        return self.get(
            f"{API_PREFIX}/engagements/{engagement_id}",
            headers=headers or program_manager_headers(),
        )

    def list_engagements(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/engagements",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def drive_execution(self, engagement_id, action, headers=None):
        return self.post(
            f"{API_PREFIX}/engagements/{engagement_id}/execution",
            json={"action": action},
            headers=headers or program_manager_headers(),
        )

    def emergency_stop(self, engagement_id, stop_code, reason, headers=None):
        return self.post(
            f"{API_PREFIX}/engagements/{engagement_id}/emergency-stop",
            json={"stop_code": stop_code, "reason": reason},
            headers=headers or program_manager_headers(),
        )

    def resume_engagement(self, engagement_id, resume_note=None, headers=None):
        payload = {} if resume_note is None else {"resume_note": resume_note}
        return self.post(
            f"{API_PREFIX}/engagements/{engagement_id}/resume",
            json=payload,
            headers=headers or compliance_officer_headers(),
        )

    # -- rules of engagement --------------------------------------------
    def create_rules_of_engagement(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/rules-of-engagement",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_rules_of_engagement(self, roe_id, headers=None):
        return self.get(
            f"{API_PREFIX}/rules-of-engagement/{roe_id}",
            headers=headers or program_manager_headers(),
        )

    def list_rules_of_engagement(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/rules-of-engagement",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def sign_rules_of_engagement(self, roe_id, signature_note=None, headers=None):
        payload = {} if signature_note is None else {"signature_note": signature_note}
        return self.post(
            f"{API_PREFIX}/rules-of-engagement/{roe_id}/sign",
            json=payload,
            headers=headers or compliance_officer_headers(),
        )

    # -- authorized targets ---------------------------------------------
    def create_authorized_target(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/authorized-targets",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_authorized_target(self, target_id, headers=None):
        return self.get(
            f"{API_PREFIX}/authorized-targets/{target_id}",
            headers=headers or program_manager_headers(),
        )

    def list_authorized_targets(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/authorized-targets",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def exclude_authorized_target(self, target_id, reason, headers=None):
        return self.post(
            f"{API_PREFIX}/authorized-targets/{target_id}/exclude",
            json={"reason": reason},
            headers=headers or program_manager_headers(),
        )

    # -- testers --------------------------------------------------------
    def create_tester(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/testers", json=payload, headers=headers or admin_headers()
        )

    def get_tester(self, tester_id, headers=None):
        return self.get(
            f"{API_PREFIX}/testers/{tester_id}",
            headers=headers or program_manager_headers(),
        )

    def list_testers(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/testers",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def record_background_check(self, tester_id, result, headers=None):
        return self.post(
            f"{API_PREFIX}/testers/{tester_id}/background-check",
            json={"result": result},
            headers=headers or admin_headers(),
        )

    def replace_certifications(self, tester_id, certifications, headers=None):
        return self.post(
            f"{API_PREFIX}/testers/{tester_id}/certifications",
            json={"certifications": certifications},
            headers=headers or admin_headers(),
        )

    # -- tester assignments ---------------------------------------------
    def create_tester_assignment(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/tester-assignments",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_tester_assignment(self, assignment_id, headers=None):
        return self.get(
            f"{API_PREFIX}/tester-assignments/{assignment_id}",
            headers=headers or program_manager_headers(),
        )

    def list_tester_assignments(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/tester-assignments",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def set_access(self, assignment_id, action, headers=None):
        return self.post(
            f"{API_PREFIX}/tester-assignments/{assignment_id}/access",
            json={"action": action},
            headers=headers or program_manager_headers(),
        )

    # -- findings -------------------------------------------------------
    def create_finding(self, payload, headers):
        """Report a finding. The acting tester's headers are always explicit."""
        return self.post(f"{API_PREFIX}/findings", json=payload, headers=headers)

    def get_finding(self, finding_id, headers=None):
        return self.get(
            f"{API_PREFIX}/findings/{finding_id}",
            headers=headers or program_manager_headers(),
        )

    def list_findings(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/findings",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def triage_finding(self, finding_id, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/findings/{finding_id}/triage",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    # -- critical alerts ------------------------------------------------
    def get_critical_alert(self, alert_id, headers=None):
        return self.get(
            f"{API_PREFIX}/critical-alerts/{alert_id}",
            headers=headers or program_manager_headers(),
        )

    def list_critical_alerts(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/critical-alerts",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def acknowledge_critical_alert(self, alert_id, containment_action, headers=None):
        return self.post(
            f"{API_PREFIX}/critical-alerts/{alert_id}/acknowledge",
            json={"containment_action": containment_action},
            headers=headers or program_manager_headers(),
        )

    # -- remediations ---------------------------------------------------
    def create_remediation(self, payload, headers=None):
        return self.post(
            f"{API_PREFIX}/remediations",
            json=payload,
            headers=headers or program_manager_headers(),
        )

    def get_remediation(self, remediation_id, headers=None):
        return self.get(
            f"{API_PREFIX}/remediations/{remediation_id}",
            headers=headers or program_manager_headers(),
        )

    def list_remediations(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/remediations",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def submit_remediation(self, remediation_id, evidence_uri, headers=None):
        return self.post(
            f"{API_PREFIX}/remediations/{remediation_id}/submit",
            json={"evidence_uri": evidence_uri},
            headers=headers or remediation_owner_headers(),
        )

    def extend_remediation(self, remediation_id, additional_days, reason, headers=None):
        return self.post(
            f"{API_PREFIX}/remediations/{remediation_id}/extension",
            json={"additional_days": additional_days, "reason": reason},
            headers=headers or program_manager_headers(),
        )

    # -- retest verifications -------------------------------------------
    def create_retest_verification(self, payload, headers):
        """Record a verification. The verifying identity is always explicit."""
        return self.post(
            f"{API_PREFIX}/retest-verifications", json=payload, headers=headers
        )

    def get_retest_verification(self, verification_id, headers=None):
        return self.get(
            f"{API_PREFIX}/retest-verifications/{verification_id}",
            headers=headers or program_manager_headers(),
        )

    def list_retest_verifications(self, params=None, headers=None):
        return self.get(
            f"{API_PREFIX}/retest-verifications",
            params=params,
            headers=headers or program_manager_headers(),
        )

    def sign_off_retest_verification(self, verification_id, closure_note, headers=None):
        return self.post(
            f"{API_PREFIX}/retest-verifications/{verification_id}/sign-off",
            json={"closure_note": closure_note},
            headers=headers or compliance_officer_headers(),
        )
