"""Delegation oversight: deficiency threshold, suspension cascade (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_audit_finding,
    create_arrangement,
    create_audit_finding,
    create_criteria_set,
    create_prior_auth_request_payload,
    create_provider,
    denied_determination,
    get_arrangement,
    list_all_events,
    make_active_criteria_set,
    setup_arrangement_with_denied_determinations,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _suspend_arrangement():
    """Drive an arrangement to SUSPENDED via three open deficiencies.
    Returns the setup context dict."""
    ctx = setup_arrangement_with_denied_determinations(n=3)
    arr_id = ctx["arrangement"]["id"]
    d1, d2, d3 = ctx["determinations"]
    f1 = create_audit_finding(arr_id, d1["id"], "NOTICE_DEFICIENT")
    mid1 = get_arrangement(arr_id)
    assert mid1["open_deficiency_count"] == 1
    assert mid1["status"] == "ACTIVE"
    create_audit_finding(arr_id, d2["id"], "CRITERIA_MISAPPLIED")
    mid2 = get_arrangement(arr_id)
    assert mid2["open_deficiency_count"] == 2
    assert mid2["status"] == "ACTIVE"
    create_audit_finding(arr_id, d3["id"], "TAT_VIOLATION")
    ctx["first_finding"] = f1
    return ctx


class TestDeficiencyThresholdCascade:
    def test_third_deficiency_suspends_arrangement_and_blocks_intake(self, api):
        """PRD §3.7: "When a newly created finding lifts that count to 3 — the comparison is inclusive, so the third open deficiency suspends — the arrangement flips `ACTIVE → SUSPENDED`, a `DELEGATION_SUSPENDED` event is recorded with null request and provider ids (its `details` reference the arrangement), and subsequent intake for the criteria set is rejected per §3.2."
        PRD §3.2: "Second, delegation: if the criteria set's delegation arrangement is `SUSPENDED`, intake is rejected with `ERR_DELEGATION_SUSPENDED` (§3.7)."

        Design: Difficulty/transitive_cascade/audit_finding_suspend_cascade_depth2
        """
        ctx = _suspend_arrangement()
        arr_id = ctx["arrangement"]["id"]
        suspended = get_arrangement(arr_id)
        assert suspended["open_deficiency_count"] == 3
        assert suspended["status"] == "SUSPENDED", (
            "the third deficiency crossing triggers the flip"
        )
        events = list_all_events(event_type="DELEGATION_SUSPENDED")
        assert len(events) == 1, (
            "the unscoped event is reachable via the system-wide event query"
        )
        assert events[0]["request_id"] is None
        assert events[0]["provider_id"] is None
        payload = create_prior_auth_request_payload(
            provider_id=ctx["provider"]["id"],
            criteria_set_id=ctx["criteria_set"]["id"],
            member_ref="M-04",
        )
        resp = api.create_prior_auth_request(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_DELEGATION_SUSPENDED)

    def test_closing_below_threshold_resumes_arrangement(self, api):
        """PRD §3.7: "When the `ComplianceOfficer` closes a finding by transitioning it from `OPEN` to `CLOSED` (any close attempted on a non-`OPEN` finding is `ERR_FINDING_NOT_OPEN`), the count recomputes; if it has dropped below 3 and the arrangement is `SUSPENDED`, the arrangement cascades back to `ACTIVE` and intake for the criteria set unblocks."

        Design: Difficulty/transitive_cascade/audit_finding_suspend_cascade_depth2
        """
        ctx = _suspend_arrangement()
        arr_id = ctx["arrangement"]["id"]
        assert get_arrangement(arr_id)["status"] == "SUSPENDED"
        close_audit_finding(ctx["first_finding"]["id"])
        resumed = get_arrangement(arr_id)
        assert resumed["open_deficiency_count"] == 2
        assert resumed["status"] == "ACTIVE", (
            "closing below the threshold auto-resumes"
        )
        payload = create_prior_auth_request_payload(
            provider_id=ctx["provider"]["id"],
            criteria_set_id=ctx["criteria_set"]["id"],
            member_ref="M-05",
        )
        unblocked = validate_success(
            api.create_prior_auth_request(payload, INTAKE), expected_status=201,
        )
        assert unblocked["status"] == "PENDED_REVIEW"


class TestFindingRules:
    def test_finding_close_twice_rejected(self, api):
        """PRD §3.7: "When the `ComplianceOfficer` closes a finding by transitioning it from `OPEN` to `CLOSED` (any close attempted on a non-`OPEN` finding is `ERR_FINDING_NOT_OPEN`), the count recomputes; if it has dropped below 3 and the arrangement is `SUSPENDED`, the arrangement cascades back to `ACTIVE` and intake for the criteria set unblocks."
        PRD §3.7: "The `open_deficiency_count` is the number of the arrangement's findings that are `OPEN` with a `finding_type` other than `COMPLIANT`."

        Design: Corner/validations/finding_close_twice_rejected
        """
        ctx = setup_arrangement_with_denied_determinations(n=1)
        arr_id = ctx["arrangement"]["id"]
        finding = create_audit_finding(
            arr_id, ctx["determinations"][0]["id"], "NOTICE_DEFICIENT",
        )
        close_audit_finding(finding["id"])
        resp = api.transition_audit_finding(
            finding["id"], {"to_status": "CLOSED"}, COMPLIANCE,
        )
        validate_error(resp, ApiErrorId.ERR_FINDING_NOT_OPEN)
        assert get_arrangement(arr_id)["open_deficiency_count"] == 0, (
            "no double-decrement from the rejected close"
        )

    def test_finding_scope_mismatch_rejected(self, api):
        """PRD §3.7: "The audited determination must fall inside the arrangement's scope — its request's `criteria_set_id` must equal the arrangement's `criteria_set_id` — else `ERR_DELEGATION_SCOPE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/finding_scope_mismatch_rejected
        """
        csa, _ga = make_active_criteria_set(name="Set A")
        csb, _gb = make_active_criteria_set(
            name="Set B", line_of_business="MEDICARE", service_category="DME",
        )
        provider = create_provider(name="P")
        arrangement = create_arrangement(csa["id"], delegating_plan_name="Plan A")
        _req, det = denied_determination(
            provider["id"], csb["id"], service_code="E0431",
        )
        resp = api.create_audit_finding(
            arrangement["id"],
            {"determination_id": det["id"], "finding_type": "CRITERIA_MISAPPLIED"},
            COMPLIANCE,
        )
        validate_error(resp, ApiErrorId.ERR_DELEGATION_SCOPE_MISMATCH)

    def test_second_arrangement_for_set_rejected(self, api):
        """PRD §3.7: "A `UMAdmin` creates a `DelegationArrangement` from a `delegating_plan_name` and a `criteria_set_id` scoping the delegated authority; at most one arrangement may exist per criteria set (`ERR_ARRANGEMENT_ALREADY_EXISTS`)."

        Design: Corner/validations/second_arrangement_for_set_rejected
        """
        cs = create_criteria_set(name="Solo Set")
        create_arrangement(cs["id"], delegating_plan_name="Plan X")
        resp = api.create_delegation_arrangement(
            {"delegating_plan_name": "Plan Y", "criteria_set_id": cs["id"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ARRANGEMENT_ALREADY_EXISTS)
