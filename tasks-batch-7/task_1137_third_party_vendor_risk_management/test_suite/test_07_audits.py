"""Audit exercises: finding cascade into auto-raised incidents, audit-close
dependency on incident closure, per-engagement capacity, and computed finding
linkage."""
from test_helpers import (
    ApiErrorId,
    attach_finding,
    create_audit_payload,
    get_engagement,
    get_incident,
    remediate_incident_to_closed,
    setup_audit_in_fieldwork,
    triage_incident,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUDITOR


class TestAuditFindingCascade:
    def test_issue_findings_auto_raises_incident_for_sev2(self, api):
        """PRD §3.13: "At the moment of issuance the system walks every finding
        with severity `SEV_1` or `SEV_2` and auto-creates an `Incident` of type
        `REGULATORY_FINDING` with matching severity on the same engagement,
        recording the new incident's id in the finding's
        `raised_incident_id`."
        PRD §3.13: "Issuing findings requires `FIELDWORK` (otherwise
        `ERR_AUDIT_NOT_FIELDWORK`, HTTP 409) and transitions the audit to
        `FINDINGS_ISSUED`."

        Design: Difficulty/transitive_cascade/audit_finding_cascade_to_incident
        """
        ctx = setup_audit_in_fieldwork(vendor_name="Audit Cascade Vendor")
        finding = attach_finding(ctx["audit"]["id"], severity="SEV_2",
                                 description="Unpatched CVE in production")

        audit = validate_success(api.issue_audit_findings(ctx["audit"]["id"], AUDITOR), 200)
        assert audit["status"] == "FINDINGS_ISSUED"

        data, _meta = validate_paginated(api.list_audit_findings(ctx["audit"]["id"], AUDITOR))
        issued = {f["id"]: f for f in data}
        raised_id = issued[finding["id"]]["raised_incident_id"]
        assert raised_id is not None

        incident = get_incident(raised_id)
        assert incident["status"] == "OPEN"
        assert incident["severity"] == "SEV_2"
        assert incident["incident_type"] == "REGULATORY_FINDING"
        assert incident["engagement_id"] == ctx["engagement"]["id"]

    def test_auto_raised_incident_leaves_engagement_normal_until_triaged(self, api):
        """PRD §3.8: "New incidents land in `OPEN` with `reported_by_user_id`
        stamped from `X-User-ID` and `reopen_count` initialized to 0."
        PRD §3.8: "The triage side effects also include setting the
        engagement's `risk_attention_state` to `UNDER_REVIEW` if it was
        `NORMAL`, and recomputing the vendor's `tier_posture`."

        Design: Difficulty/transitive_cascade/audit_finding_cascade_to_incident
        """
        ctx = setup_audit_in_fieldwork(vendor_name="Audit Cascade Vendor 2")
        finding = attach_finding(ctx["audit"]["id"], severity="SEV_2", description="finding")
        validate_success(api.issue_audit_findings(ctx["audit"]["id"], AUDITOR), 200)

        # The auto-raised incident is OPEN (untriaged); the engagement's
        # risk_attention_state flips only at triage per PRD §3.8.
        assert get_engagement(ctx["engagement"]["id"])["risk_attention_state"] == "NORMAL"

        data, _meta = validate_paginated(api.list_audit_findings(ctx["audit"]["id"], AUDITOR))
        raised_id = {f["id"]: f for f in data}[finding["id"]]["raised_incident_id"]
        triage_incident(raised_id)
        assert get_engagement(ctx["engagement"]["id"])["risk_attention_state"] == "UNDER_REVIEW"


class TestAuditCloseDependency:
    def _setup_findings_issued_with_open_incident(self, api, vendor_name):
        ctx = setup_audit_in_fieldwork(vendor_name=vendor_name)
        finding = attach_finding(ctx["audit"]["id"], severity="SEV_2", description="finding")
        validate_success(api.issue_audit_findings(ctx["audit"]["id"], AUDITOR), 200)
        data, _meta = validate_paginated(api.list_audit_findings(ctx["audit"]["id"], AUDITOR))
        raised_id = {f["id"]: f for f in data}[finding["id"]]["raised_incident_id"]
        assert raised_id is not None
        return ctx, raised_id

    def test_close_blocked_while_auto_raised_incident_open(self, api):
        """PRD §3.13: "Closing the audit requires `FINDINGS_ISSUED` (otherwise
        `ERR_AUDIT_NOT_FINDINGS_ISSUED`, HTTP 409) and requires every
        auto-raised incident to be `CLOSED`; any auto-raised incident still in
        a non-`CLOSED` state blocks the close with
        `ERR_AUDIT_FINDINGS_UNRESOLVED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/audit_close_depends_on_incident_closed
        """
        ctx, _raised_id = self._setup_findings_issued_with_open_incident(api, "XDep3 Vendor")
        res = api.close_audit(ctx["audit"]["id"], AUDITOR)
        validate_error(res, ApiErrorId.ERR_AUDIT_FINDINGS_UNRESOLVED.value)

    def test_close_succeeds_once_auto_raised_incident_closed(self, api):
        """PRD §3.13: "Closing the audit requires `FINDINGS_ISSUED` (otherwise
        `ERR_AUDIT_NOT_FINDINGS_ISSUED`, HTTP 409) and requires every
        auto-raised incident to be `CLOSED`; any auto-raised incident still in
        a non-`CLOSED` state blocks the close with
        `ERR_AUDIT_FINDINGS_UNRESOLVED` (HTTP 422). On close the server stamps
        `closed_at`."

        Design: Difficulty/cross_entity_state_dependency/audit_close_depends_on_incident_closed
        """
        ctx, raised_id = self._setup_findings_issued_with_open_incident(api, "XDep3 Vendor 2")
        # Drive the auto-raised incident through the full remediation flow.
        triage_incident(raised_id)
        remediate_incident_to_closed(raised_id, committed="2026-05-05T00:00:00Z")
        assert get_incident(raised_id)["status"] == "CLOSED"

        closed = validate_success(api.close_audit(ctx["audit"]["id"], AUDITOR), 200)
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None


class TestAuditCapacity:
    def test_second_audit_rejected_while_first_active(self, api):
        """PRD §3.13: "At most one audit per engagement may be in `INITIATED`,
        `FIELDWORK`, or `FINDINGS_ISSUED` at any instant — a second concurrent
        attempt is rejected with `ERR_AUDIT_ALREADY_ACTIVE` (HTTP 422); closed
        audits do not count toward this capacity."

        Design: Difficulty/resource_temporal_overlap/audit_exercise_aggregate_capacity_one
        """
        ctx = setup_audit_in_fieldwork(vendor_name="Audit Cap Vendor")
        res = api.create_audit(
            ctx["engagement"]["id"], create_audit_payload(scope="FINANCIAL"), AUDITOR
        )
        validate_error(res, ApiErrorId.ERR_AUDIT_ALREADY_ACTIVE.value)

    def test_second_audit_allowed_after_first_closes(self, api):
        """PRD §3.13: "At most one audit per engagement may be in `INITIATED`,
        `FIELDWORK`, or `FINDINGS_ISSUED` at any instant — a second concurrent
        attempt is rejected with `ERR_AUDIT_ALREADY_ACTIVE` (HTTP 422); closed
        audits do not count toward this capacity."

        Design: Difficulty/resource_temporal_overlap/audit_exercise_aggregate_capacity_one
        """
        ctx = setup_audit_in_fieldwork(vendor_name="Audit Cap Vendor 2")
        audit_id = ctx["audit"]["id"]
        res = api.create_audit(ctx["engagement"]["id"], create_audit_payload(scope="FINANCIAL"), AUDITOR)
        validate_error(res, ApiErrorId.ERR_AUDIT_ALREADY_ACTIVE.value)

        # Close the first audit with zero findings (no auto-raised incidents).
        validate_success(api.issue_audit_findings(audit_id, AUDITOR), 200)
        closed = validate_success(api.close_audit(audit_id, AUDITOR), 200)
        assert closed["status"] == "CLOSED"

        second = validate_success(
            api.create_audit(ctx["engagement"]["id"], create_audit_payload(scope="FINANCIAL"), AUDITOR),
            201,
        )
        assert second["status"] == "INITIATED"


class TestAuditFindingComputedLinkage:
    def test_raised_incident_id_populated_only_for_high_severity(self, api):
        """PRD §3.13: "At the moment of issuance the system walks every finding
        with severity `SEV_1` or `SEV_2` and auto-creates an `Incident` of type
        `REGULATORY_FINDING` with matching severity on the same engagement,
        recording the new incident's id in the finding's `raised_incident_id`.
        Findings of severity `SEV_3` or `SEV_4` do not auto-raise incidents."

        Design: Corner/endpoints/computed_read_endpoint_audit_findings_list
        """
        ctx = setup_audit_in_fieldwork(vendor_name="CompR")
        f_high = attach_finding(ctx["audit"]["id"], severity="SEV_2", description="high")
        f_low = attach_finding(ctx["audit"]["id"], severity="SEV_3", description="low")
        validate_success(api.issue_audit_findings(ctx["audit"]["id"], AUDITOR), 200)

        data, _meta = validate_paginated(api.list_audit_findings(ctx["audit"]["id"], AUDITOR))
        by_id = {f["id"]: f for f in data}
        assert by_id[f_high["id"]]["raised_incident_id"] is not None
        assert by_id[f_low["id"]]["raised_incident_id"] is None
