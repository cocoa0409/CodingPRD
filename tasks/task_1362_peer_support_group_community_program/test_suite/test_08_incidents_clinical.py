"""Incident escalation rules and clinical referral RBAC (PRD §2.1, §3.7)."""
from test_helpers import (
    ADMIN,
    COORDINATOR,
    ApiErrorId,
    assert_clinical_referral,
    make_incident,
    setup_in_progress_session,
    setup_pending_referral,
    validate_error,
    validate_success,
)


class TestEscalationSeverityGate:
    def test_escalate_standard_incident_rejected(self, api):
        """PRD §3.7: "Escalation, from either `OPEN` or `ACKNOWLEDGED`, is
        reserved for `CRITICAL` reports; escalating a `STANDARD` report is
        rejected with `ERR_CLINICAL_REQUIRES_CRITICAL` (HTTP 409)."

        Design: Corner/validations/incident_escalate_standard_rejected
        """
        env = setup_in_progress_session()
        incident = make_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.facilitator["id"], severity="STANDARD", category="OTHER",
            description="minor")
        resp = api.escalate_incident(
            env.program["id"], env.group["id"], env.session["id"],
            incident["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLINICAL_REQUIRES_CRITICAL)
        after = validate_success(api.get_incident(
            env.program["id"], env.group["id"], env.session["id"],
            incident["id"], ADMIN))
        assert after["status"] == "OPEN", "rejected escalation must not change the incident"


class TestClinicalReferralRbac:
    def test_admin_cannot_accept_referral_but_coordinator_can(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`ClinicalCoordinator` is a clinical services liaison who
        triages escalated referrals — accepting, declining, and completing
        them — and reads participants, referrals, and incidents for triage."
        PRD §3.7: "Escalation moves the report to `ESCALATED_TO_CLINICAL`,
        creates a **ClinicalReferral** in `PENDING` referencing the triggering
        incident via its `source_incident_id`"

        Design: Corner/rbac/clinical_coordinator_only_referral_actions
        """
        env = setup_pending_referral()
        referral = env.referral
        assert_clinical_referral(referral)
        assert referral["status"] == "PENDING"
        assert referral["source_incident_id"] == env.incident["id"]

        resp = api.accept_referral(referral["participant_id"], referral["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        accepted = validate_success(
            api.accept_referral(referral["participant_id"], referral["id"], COORDINATOR))
        assert accepted["status"] == "ACCEPTED"
