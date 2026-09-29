"""Derived service fields settle inside the write that caused them, with no run."""

from test_helpers import (
    add_design_factor,
    assert_design_score,
    create_integration,
    create_service,
    published_notice,
    read_service,
    run_determination,
    set_integration_status,
    set_posture_override,
)


class TestPostureRecomputesWithoutAComplianceRun:
    """Exposure, open audits and posture move three times while the run counter stays 0."""

    def test_01_audit_transitions_and_the_override_are_immediately_visible(self):
        """Every read after a write already reflects it, and the write response does too.

        "The service's `third_party_exposure_points` is the sum of `exposure_points` over only
        those of its integrations whose `status` is `APPROVED`. Integrations that are
        `DECLARED`, `AUDIT_PENDING` or `BLOCKED` contribute nothing". "A successful approval
        stamps `last_audit_decision_at` with the current logical-clock instant, advances the
        service's `audit_decision_count` by one, adds this integration's `exposure_points` into
        the service's `third_party_exposure_points`, recomputes `open_audit_count`, re-derives
        `compliance_posture`, and advances the service's `version` by one." "The submitted value
        is stored, `compliance_posture` is then recomputed through the ordered clauses of §2.5".
        "A run first advances the service's `compliance_run_sequence` by one".

        Design: Corner/consistency_model/posture_and_exposure_recompute_without_any_compliance_run
        """
        service = create_service(name="Immediate Consistency Kids")
        service_id = service["id"]
        add_design_factor(service_id, "SUBJECT_MATTER", "MODERATE")
        determined = run_determination(service_id)
        assert determined["determination_status"] == "MIXED_AUDIENCE"
        assert_design_score(determined, 0.60)

        published_notice(service_id, disclosed_integration_vendors=["Kid Metrics"])
        integration = create_integration(
            service_id,
            vendor_name="Kid Metrics",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        assert integration["status"] == "DECLARED"
        assert integration["disclosed_in_notice"] is True, (
            "the published notice names this vendor, so the flag is true at declaration"
        )
        assert integration["exposure_points"] == 30, (
            f"ANALYTICS is 15, doubled for the persistent identifier, got "
            f"{integration['exposure_points']}"
        )

        declared_view = read_service(service_id)
        assert declared_view["third_party_exposure_points"] == 0, (
            "a freshly declared integration raises the total by zero, got "
            f"{declared_view['third_party_exposure_points']}"
        )
        assert declared_view["open_audit_count"] == 0
        assert declared_view["audit_decision_count"] == 0
        assert declared_view["compliance_posture"] == "OPEN"
        assert declared_view["compliance_run_sequence"] == 0

        pending = set_integration_status(integration["id"], "AUDIT_PENDING")
        assert pending["status"] == "AUDIT_PENDING"

        pending_view = read_service(service_id)
        assert pending_view["open_audit_count"] == 1, (
            f"the very next read already counts the audit, got {pending_view['open_audit_count']}"
        )
        assert pending_view["compliance_posture"] == "RESTRICTED", (
            "one open audit restricts the service without any run, got "
            f"{pending_view['compliance_posture']}"
        )
        assert pending_view["third_party_exposure_points"] == 0, (
            "an AUDIT_PENDING integration contributes nothing, got "
            f"{pending_view['third_party_exposure_points']}"
        )
        assert pending_view["compliance_run_sequence"] == 0

        approved = set_integration_status(integration["id"], "APPROVED")
        assert approved["status"] == "APPROVED"

        approved_view = read_service(service_id)
        assert approved_view["third_party_exposure_points"] == 30, (
            "the approved integration's points are in the total on the next read, got "
            f"{approved_view['third_party_exposure_points']}"
        )
        assert approved_view["open_audit_count"] == 0
        assert approved_view["audit_decision_count"] == 1, (
            f"the approval counts as one decision, got {approved_view['audit_decision_count']}"
        )
        assert approved_view["compliance_posture"] == "OPEN", (
            f"30 is below the restricting threshold of 40, got "
            f"{approved_view['compliance_posture']}"
        )
        assert approved_view["compliance_run_sequence"] == 0, (
            "no compliance run was needed for any of this, got "
            f"{approved_view['compliance_run_sequence']}"
        )

        frozen = set_posture_override(service_id, "FROZEN")
        assert frozen["compliance_posture"] == "FROZEN", (
            "the write response itself carries the recomputed posture, got "
            f"{frozen['compliance_posture']}"
        )
        assert frozen["third_party_exposure_points"] == 30, (
            "and the rest of the derived picture too, got "
            f"{frozen['third_party_exposure_points']}"
        )

        cleared = set_posture_override(service_id, None)
        assert cleared["posture_override"] is None
        assert cleared["compliance_posture"] == "OPEN", (
            "clearing the override falls straight back to the ladder, got "
            f"{cleared['compliance_posture']}"
        )

        final_view = read_service(service_id)
        assert final_view["compliance_posture"] == "OPEN"
        assert final_view["third_party_exposure_points"] == 30
        assert final_view["compliance_run_sequence"] == 0, (
            "every one of these transitions was immediately consistent, got "
            f"{final_view['compliance_run_sequence']}"
        )
