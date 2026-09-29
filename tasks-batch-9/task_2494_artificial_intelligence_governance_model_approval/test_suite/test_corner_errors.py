"""Error-path compliance tests for the AI governance / model approval API.

Each test drives the API to the one governance position in which a single
normative rejection rule fires, asserts the mandated error identity, and then
reads the affected record back to prove the refused call changed nothing.

The harness restarts the server with an empty database before every test, so
each test builds its own preconditions through the PRD's own endpoints.
"""

from test_helpers import (
    ASSESSMENT_GRADE_D,
    ASSESSMENT_NULL_RETENTION,
    ASSET_NOT_APPROVED_STATUS_ON_ASSET_ACTION,
    BUSINESS_REVIEWER,
    CONSERVATIVE_RETENTION_DAYS,
    DEFAULT_CLOCK,
    EVAL_WINDOWS,
    LIMITED_PASSING_BIAS,
    MINIMAL_USE_CASE,
    NON_EXISTENT_UUID,
    OFFICER,
    POSTURE_HEALTHY,
    POSTURE_IMPAIRED,
    POSTURE_WATCH,
    PROHIBITED_BY_BAND_USE_CASE,
    SECURITY_REVIEWER,
    THIRD_PARTY_ASSET_NIMBUS,
    VARIANT_CONSERVATIVE,
    VARIANT_DOCUMENTED,
    ApiErrorId,
    approval_payload,
    approve_asset,
    approved_design,
    assert_common_fields,
    assert_debt_equals,
    assert_metric_value,
    assert_model_asset,
    assert_monitoring_incident,
    assert_oversight_design,
    assert_review_gate,
    assert_shadow_deployment,
    assert_test_evaluation,
    assert_vendor_assessment,
    assessment_decision_payload,
    classified_use_case,
    clear_all_gates,
    conditions,
    create_binding,
    decide_assessment,
    design_decision_payload,
    discover_shadow,
    entry_types,
    evaluation_completion_payload,
    expected_base_score,
    expected_containment_hours,
    expected_grace_days,
    expected_terms_risk_points,
    gates_by_type,
    get_success_data,
    grade_for_points,
    grant_grace_payload,
    issue_conditions_payload,
    limited_use_case_under_review,
    limited_use_case_with_binding,
    list_assessments,
    list_bindings,
    list_ledger,
    list_snapshots,
    minimal_approved_use_case,
    minimal_use_case_under_review,
    model_binding_payload,
    move_clock,
    pin_clock,
    plus_days,
    plus_hours,
    plus_seconds,
    read_asset,
    read_evaluation,
    read_incident,
    read_shadow,
    read_summary,
    read_use_case,
    ready_asset,
    reassessment_payload,
    register_asset,
    report_incident,
    run_evaluation,
    shadow_link_payload,
    submit_assessment,
    use_case_under_reassessment,
    validate_error,
    validate_paginated,
)

# ─── Unresolvable path identifiers ─────────────────────────────────────────


def test_unknown_model_asset_id_yields_model_asset_not_found(api):
    """PRD §2.8: "On any path of the shape `/model-assets/{id}/...`, an unresolvable
    `{id}` yields `ERR_MODEL_ASSET_NOT_FOUND` (HTTP 404)."
    PRD §2.9: "The `{id}` of a `/model-assets/{id}...` path resolves —
    `ERR_MODEL_ASSET_NOT_FOUND` (404), on every such path."

    Design: Corner/errors/model_asset_unknown_id_not_found
    """
    pin_clock(api)
    asset = register_asset(api)

    response = api.get_model_asset(NON_EXISTENT_UUID, headers=OFFICER)
    validate_error(response, ApiErrorId.MODEL_ASSET_NOT_FOUND)

    # The registered asset the collection already held is untouched.
    assert_model_asset(read_asset(api, asset["id"]), status="REGISTERED", version=1)


def test_unknown_review_gate_id_yields_review_gate_not_found(api):
    """PRD §2.8: "On the four gate actions — taking up review, issuing conditions,
    clearing and reopening — an unresolvable gate `{id}` yields
    `ERR_REVIEW_GATE_NOT_FOUND` (HTTP 404)."
    PRD §2.9: "The gate `{id}` resolves — `ERR_REVIEW_GATE_NOT_FOUND` (404), on gate
    take-up, issue-conditions, clear and reopen."

    Design: Corner/errors/review_gate_unknown_id_not_found
    """
    pin_clock(api)

    # The gate id resolves to nothing, so neither the gate-state rule nor the
    # gate-ownership rule further down the ladder can be reached.
    response = api.start_gate_review(NON_EXISTENT_UUID, headers=BUSINESS_REVIEWER)
    validate_error(response, ApiErrorId.REVIEW_GATE_NOT_FOUND)


def test_unknown_test_evaluation_id_yields_governance_record_not_found(api):
    """PRD §2.8: "For every other addressed record — a vendor assessment being decided,
    an oversight design being decided, a test evaluation being read or completed, a
    disclosure notice being withdrawn, a monitoring incident being read, contained or
    resolved, a shadow deployment being read, linked, granted grace or retired — an
    unresolvable `{id}` yields `ERR_GOVERNANCE_RECORD_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/test_evaluation_unknown_id_not_found
    """
    pin_clock(api)

    response = api.get_test_evaluation(NON_EXISTENT_UUID, headers=SECURITY_REVIEWER)
    validate_error(response, ApiErrorId.GOVERNANCE_RECORD_NOT_FOUND)


# ─── State preconditions on the addressed record ───────────────────────────


def test_issue_conditions_on_a_pending_gate_is_not_reviewable(api):
    """PRD §3.3: "Issuing conditions moves a gate `IN_REVIEW → CONDITIONS_ISSUED`."
    PRD §2.9: "The addressed gate is in a status the requested action has a transition
    out of: take-up needs `PENDING` or `CONDITIONS_ISSUED`, issuing conditions needs
    `IN_REVIEW`, clearing needs `IN_REVIEW` or `CONDITIONS_ISSUED`, reopening needs
    `CLEARED` — `ERR_GATE_NOT_IN_REVIEWABLE_STATE` (409), on all four gate actions."

    Design: Corner/errors/issue_conditions_on_pending_gate_invalid
    """
    chain = minimal_use_case_under_review(api)
    gate = chain.gates["BUSINESS"]
    assert_review_gate(gate, status="PENDING", assigned_reviewer_user_id=None, version=1)

    response = api.issue_gate_conditions(
        gate["id"],
        issue_conditions_payload(conditions(1)),
        headers=BUSINESS_REVIEWER,
    )
    validate_error(response, ApiErrorId.GATE_NOT_IN_REVIEWABLE_STATE)

    after = gates_by_type(api, chain.use_case_id)["BUSINESS"]
    assert_review_gate(after, status="PENDING", open_condition_count=0, version=1)
    assert_debt_equals(after["control_debt_index"], 0.00)

    # No condition was booked, so the intake was not pushed back to its requester.
    use_case = read_use_case(api, chain.use_case_id)
    assert_common_fields(use_case)
    assert use_case["status"] == "UNDER_REVIEW"
    assert use_case["open_conditions_count"] == 0


def test_complete_reassessment_on_a_fresh_approval_is_not_due(api):
    """PRD §3.9: "The use case must be in `UNDER_REASSESSMENT`, or the attempt is
    rejected with `ERR_REASSESSMENT_NOT_DUE`, and the closing officer must not be the
    use case's `requester_user_id`, or it is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/complete_reassessment_while_approved_not_due
    """
    chain = minimal_approved_use_case(api)
    before = read_use_case(api, chain.use_case_id)
    assert before["status"] == "APPROVED"
    assert before["reassessment_status"] == "SCHEDULED"
    assert before["reassessment_cycle_index"] == 1
    # Approval sets the reassessment due instant to the expiry instant, so the cycle
    # cannot be closed until the sweep has opened it.
    assert before["reassessment_due_at"] == before["approval_expires_at"]

    response = api.complete_reassessment(
        chain.use_case_id, reassessment_payload("CONFIRMED"), headers=OFFICER
    )
    validate_error(response, ApiErrorId.REASSESSMENT_NOT_DUE)

    after = read_use_case(api, chain.use_case_id)
    assert after["status"] == "APPROVED"
    assert after["reassessment_status"] == "SCHEDULED"
    assert after["reassessment_cycle_index"] == 1
    assert after["version"] == before["version"]
    assert "REASSESSMENT_COMPLETED" not in entry_types(
        list_ledger(api, chain.use_case_id)
    )


def test_oversight_design_cannot_be_decided_twice(api):
    """PRD §3.5: "Either decision is refused with `ERR_PROHIBITED_USE_CASE` when the use
    case's `risk_tier` is `PROHIBITED`, and a design that has already left `DRAFT`
    cannot be decided again — that attempt is rejected with
    `ERR_ASSESSMENT_ALREADY_DECIDED`."

    Design: Corner/errors/oversight_design_decided_twice_already_decided
    """
    chain = minimal_use_case_under_review(api)
    design = approved_design(api, chain.use_case_id)
    assert_oversight_design(design, status="APPROVED")

    response = api.decide_oversight_design(
        design["id"], design_decision_payload("REJECT"), headers=OFFICER
    )
    validate_error(response, ApiErrorId.ASSESSMENT_ALREADY_DECIDED)

    designs, _ = validate_paginated(
        api.list_oversight_designs(chain.use_case_id, headers=OFFICER)
    )
    assert len(designs) == 1
    assert_oversight_design(
        designs[0],
        status="APPROVED",
        version=design["version"],
        decided_at=design["decided_at"],
        decided_by_user_id=design["decided_by_user_id"],
    )


def test_passed_evaluation_cannot_be_completed_again(api):
    """PRD §3.4: "A run that is not `PLANNED` cannot be completed and the attempt is
    rejected with `ERR_EVALUATION_NOT_PLANNED`."

    Design: Corner/errors/evaluation_completed_twice_not_planned
    """
    chain = limited_use_case_with_binding(api)
    value, samples = LIMITED_PASSING_BIAS
    start, end = EVAL_WINDOWS["BIAS"]
    passed = run_evaluation(
        api, chain.binding_id, "BIAS", start, end, value, samples, chain.use_case_id
    )
    assert_test_evaluation(passed, status="PASSED", sample_size=samples)

    response = api.complete_test_evaluation(
        passed["id"],
        evaluation_completion_payload(0.4000, 900, eval_type="BIAS"),
        headers=SECURITY_REVIEWER,
    )
    validate_error(response, ApiErrorId.EVALUATION_NOT_PLANNED)

    after = read_evaluation(api, passed["id"])
    assert_test_evaluation(
        after, status="PASSED", sample_size=samples, version=passed["version"]
    )
    assert_metric_value(after["observed_metric_value"], value)

    # A failing metric on a refused call cannot raise the safety flag.
    use_case = read_use_case(api, chain.use_case_id)
    assert use_case["safety_flag"] is False


def test_resolve_on_an_open_incident_is_not_actionable(api):
    """PRD §3.8: "Resolution is a `GovernanceOfficer` action on a `CONTAINED` incident,
    optionally updating `reported_to_regulator`, and it carries the same
    `SEV1`-plus-`affects_individuals` reporting duty enforced by
    `ERR_REGULATOR_REPORT_REQUIRED`."
    PRD §2.9: "The addressed incident is in a status the requested action has a
    transition out of: containment needs `OPEN` or `ESCALATED`, resolution needs
    `CONTAINED` — `ERR_INCIDENT_NOT_ACTIONABLE` (409), on incident containment and
    resolution."

    Design: Corner/errors/resolve_open_incident_not_actionable
    """
    chain = limited_use_case_under_review(api)
    incident = report_incident(api, chain.use_case_id, "SEV3", category="DRIFT")
    expected_hours = expected_containment_hours("SEV3", "LIMITED")
    assert_monitoring_incident(
        incident,
        status="OPEN",
        containment_hours=expected_hours,
        containment_deadline_at=plus_hours(DEFAULT_CLOCK, expected_hours),
    )
    # A single unresolved incident below SEV1 only watches the deployment.
    assert read_use_case(api, chain.use_case_id)["monitoring_posture"] == POSTURE_WATCH

    response = api.resolve_incident(incident["id"], headers=OFFICER)
    validate_error(response, ApiErrorId.INCIDENT_NOT_ACTIONABLE)

    after = read_incident(api, incident["id"])
    assert_monitoring_incident(after, status="OPEN", resolved_at=None, version=1)


def test_granting_grace_twice_leaves_the_shadow_not_actionable(api):
    """PRD §3.9: "**Granting grace** gives the business a bounded window to either link
    or tear the deployment down: it is available only from `DISCOVERED`, only while the
    current logical instant is at or before `grace_deadline_at` (later is rejected with
    `ERR_GRACE_PERIOD_ELAPSED`), and only for a `grace_days` figure of at least 1 and at
    most 30 (outside that range is rejected with `ERR_GRACE_EXTENSION_EXCEEDED`)."
    PRD §2.9: "The addressed shadow deployment is neither `RETIRED` nor
    `ENFORCED_BLOCK`, and granting grace additionally requires `DISCOVERED` —
    `ERR_SHADOW_NOT_ACTIONABLE` (409), on shadow linking, grace granting and
    retirement."

    Design: Corner/errors/grant_grace_twice_shadow_not_actionable
    """
    pin_clock(api)
    asset = register_asset(api)
    shadow = discover_shadow(api, asset["id"], "SANDBOX")

    granted = get_success_data(
        api.grant_shadow_grace(shadow["id"], grant_grace_payload(10), headers=OFFICER)
    )
    expected_deadline = plus_days(DEFAULT_CLOCK, expected_grace_days("SANDBOX", 10))
    assert_shadow_deployment(
        granted,
        status="GRACE_GRANTED",
        grace_days_granted=10,
        grace_deadline_at=expected_deadline,
    )

    # The clock is still far inside the deadline, so the status rule answers here
    # rather than the elapsed-grace rule.
    response = api.grant_shadow_grace(
        shadow["id"], grant_grace_payload(5), headers=OFFICER
    )
    validate_error(response, ApiErrorId.SHADOW_NOT_ACTIONABLE)

    after = read_shadow(api, shadow["id"])
    assert_shadow_deployment(
        after,
        status="GRACE_GRANTED",
        grace_days_granted=10,
        grace_deadline_at=expected_deadline,
        version=granted["version"],
    )


def test_approving_an_already_approved_asset_for_use_is_refused(api):
    """PRD §2.9: "The addressed model asset is in a status the requested action has a
    transition out of: approving for use needs `REGISTERED` or `RESTRICTED`, and a
    `RESTRICTED` asset additionally needs `enforced_shadow_count` equal to 0, while
    revising an asset in place needs `APPROVED_FOR_USE` because the revise transition is
    declared only on that state — `ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE` (409), on asset
    approve-for-use and asset revision."

    Design: Corner/errors/approve_for_use_twice_asset_not_approvable
    """
    pin_clock(api)
    asset = register_asset(api)
    approved = approve_asset(api, asset["id"])
    assert_model_asset(approved, status="APPROVED_FOR_USE", version=2)

    response = api.approve_asset_for_use(asset["id"], headers=OFFICER)
    validate_error(
        response,
        ApiErrorId.MODEL_ASSET_NOT_APPROVED_FOR_USE,
        expected_status=ASSET_NOT_APPROVED_STATUS_ON_ASSET_ACTION,
    )

    # The refused call cannot be used to bump the version and stale bindings.
    assert_model_asset(
        read_asset(api, asset["id"]), status="APPROVED_FOR_USE", version=2
    )


# ─── Business rules on the use case's governance position ──────────────────


def test_prohibited_tier_use_case_cannot_take_a_binding(api):
    """PRD §3.4: "The referenced asset must be `APPROVED_FOR_USE`, otherwise the creation
    is rejected with `ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE`, and the use case's
    `risk_tier` must not be `PROHIBITED`, otherwise it is rejected with
    `ERR_PROHIBITED_USE_CASE`."

    Design: Corner/errors/prohibited_band_use_case_cannot_take_binding
    """
    pin_clock(api)
    asset, _ = ready_asset(api)
    use_case = classified_use_case(api, PROHIBITED_BY_BAND_USE_CASE)

    # Reaching PROHIBITED through the score band rather than the forced combination
    # leaves the use case alive in UNDER_REVIEW with no gates demanded of it.
    assert use_case["risk_score"] == expected_base_score(PROHIBITED_BY_BAND_USE_CASE)
    assert use_case["risk_tier"] == "PROHIBITED"
    assert use_case["status"] == "UNDER_REVIEW"
    assert use_case["required_gate_types"] == []
    assert use_case["rejection_reason"] is None
    assert gates_by_type(api, use_case["id"]) == {}

    response = api.create_model_binding(
        use_case["id"],
        model_binding_payload(asset["id"], use_case["version"]),
        headers=OFFICER,
    )
    validate_error(response, ApiErrorId.PROHIBITED_USE_CASE)

    assert list_bindings(api, use_case["id"]) == []
    assert_model_asset(read_asset(api, asset["id"]), active_binding_count=0)


def test_approve_without_an_approved_oversight_design_is_refused(api):
    """PRD §3.7: "An `OversightDesign` with status `APPROVED` must exist on the use case,
    or the attempt fails with `ERR_OVERSIGHT_DESIGN_NOT_APPROVED`."

    Design: Corner/errors/approve_without_oversight_design_rejected
    """
    chain = minimal_use_case_under_review(api)
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    clear_all_gates(api, chain.use_case_id)

    ready = read_use_case(api, chain.use_case_id)
    assert ready["status"] == "READY_FOR_APPROVAL"
    assert ready["cleared_gate_count"] == 1

    response = api.approve_use_case(
        chain.use_case_id, approval_payload(ready["version"]), headers=OFFICER
    )
    validate_error(response, ApiErrorId.OVERSIGHT_DESIGN_NOT_APPROVED)

    designs, _ = validate_paginated(
        api.list_oversight_designs(chain.use_case_id, headers=OFFICER)
    )
    assert designs == []

    after = read_use_case(api, chain.use_case_id)
    assert after["status"] == "READY_FOR_APPROVAL"
    assert after["approved_at"] is None
    assert after["version"] == ready["version"]
    assert list_snapshots(api, chain.use_case_id, variant="DEPLOYMENT_FINAL") == []

    summary = read_summary(api)
    assert summary["portfolio_approved_reach"] == 0
    assert summary["ledger_reach_balance"] == 0


def test_approve_without_a_pinned_binding_is_refused(api):
    """PRD §3.7: "A `ModelBinding` with status `PINNED` must exist, or it fails with
    `ERR_MODEL_BINDING_MISSING`, and that binding's `pinned_model_version` must still
    equal its asset's current `version`, or it fails with `ERR_MODEL_BINDING_STALE`."

    Design: Corner/errors/approve_without_pinned_binding_rejected
    """
    chain = minimal_use_case_under_review(api)
    # The oversight design is in place, so the design rule earlier in the ladder is
    # satisfied and the referential binding rule is the one that answers.
    chain.design = approved_design(api, chain.use_case_id)
    assert_oversight_design(chain.design, status="APPROVED")
    clear_all_gates(api, chain.use_case_id)

    ready = read_use_case(api, chain.use_case_id)
    assert ready["status"] == "READY_FOR_APPROVAL"
    assert list_bindings(api, chain.use_case_id) == []

    response = api.approve_use_case(
        chain.use_case_id, approval_payload(ready["version"]), headers=OFFICER
    )
    validate_error(response, ApiErrorId.MODEL_BINDING_MISSING)

    after = read_use_case(api, chain.use_case_id)
    assert after["status"] == "READY_FOR_APPROVAL"
    assert after["approved_at"] is None
    assert after["version"] == ready["version"]
    assert list_bindings(api, chain.use_case_id) == []


def test_grade_d_assessment_cannot_clear_a_third_party_asset(api):
    """PRD §3.1: "Clearing an asset for use moves it from `REGISTERED` to
    `APPROVED_FOR_USE`, and this is the gate at which third-party supply is tested: if
    `is_third_party` is true, the asset must already carry a `VendorModelAssessment`
    with status `ACCEPTED` whose `terms_grade` is `A`, `B` or `C`, and without one the
    attempt is rejected with `ERR_VENDOR_ASSESSMENT_NOT_ACCEPTED`. A grade of `D` is
    never sufficient."

    Design: Corner/errors/grade_d_assessment_cannot_approve_asset_for_use
    """
    pin_clock(api)
    asset = register_asset(api, THIRD_PARTY_ASSET_NIMBUS)
    submitted = submit_assessment(api, asset["id"], ASSESSMENT_GRADE_D)
    expected_points = expected_terms_risk_points(
        ASSESSMENT_GRADE_D, VARIANT_CONSERVATIVE
    )
    assert_vendor_assessment(
        submitted,
        status="SUBMITTED",
        terms_variant=VARIANT_CONSERVATIVE,
        effective_retention_days=CONSERVATIVE_RETENTION_DAYS,
        terms_risk_points=expected_points,
        terms_grade=grade_for_points(expected_points),
    )

    accepted = decide_assessment(
        api, submitted["id"], "ACCEPT", VARIANT_CONSERVATIVE
    )
    assert_vendor_assessment(accepted, status="ACCEPTED", terms_grade="D")

    before = read_asset(api, asset["id"])
    assert_model_asset(before, status="REGISTERED", vendor_terms_grade="D")

    response = api.approve_asset_for_use(asset["id"], headers=OFFICER)
    validate_error(response, ApiErrorId.VENDOR_ASSESSMENT_NOT_ACCEPTED)

    assert_model_asset(
        read_asset(api, asset["id"]),
        status="REGISTERED",
        version=before["version"],
    )


def test_documented_terms_variant_needs_a_declared_retention_period(api):
    """PRD §3.1: "Deciding under `DOCUMENTED_TERMS` requires the assessment's
    `retention_days` to be non-null; a null figure makes the documented variant
    unavailable and the decision is rejected with `ERR_RETENTION_TERMS_UNDOCUMENTED`."

    Design: Corner/errors/documented_terms_without_retention_days_rejected
    """
    pin_clock(api)
    asset = register_asset(api, THIRD_PARTY_ASSET_NIMBUS)
    submitted = submit_assessment(api, asset["id"], ASSESSMENT_NULL_RETENTION)
    assert_vendor_assessment(
        submitted,
        status="SUBMITTED",
        retention_days=None,
        terms_variant=VARIANT_CONSERVATIVE,
        effective_retention_days=CONSERVATIVE_RETENTION_DAYS,
    )

    response = api.decide_vendor_assessment(
        submitted["id"],
        assessment_decision_payload("ACCEPT", VARIANT_DOCUMENTED),
        headers=OFFICER,
    )
    validate_error(response, ApiErrorId.RETENTION_TERMS_UNDOCUMENTED)

    assessments = list_assessments(api, asset["id"])
    assert len(assessments) == 1
    assert_vendor_assessment(
        assessments[0],
        status="SUBMITTED",
        terms_variant=VARIANT_CONSERVATIVE,
        terms_grade=submitted["terms_grade"],
        terms_risk_points=submitted["terms_risk_points"],
        version=submitted["version"],
    )
    # A refused decision writes nothing to the parent asset.
    assert_model_asset(read_asset(api, asset["id"]), vendor_terms_grade=None)


def test_linking_a_shadow_to_a_use_case_without_a_matching_binding_is_a_mismatch(api):
    """PRD §3.9: "The link target must be a use case in status `APPROVED` that holds a
    `ModelBinding` in `PINNED` whose `model_asset_id` equals the shadow deployment's own
    `model_asset_id`; anything else is rejected with `ERR_SHADOW_LINK_MISMATCH`."

    Design: Corner/errors/shadow_link_to_use_case_without_matching_binding
    """
    pin_clock(api)
    asset, _ = ready_asset(api)
    use_case = classified_use_case(api, MINIMAL_USE_CASE)
    assert use_case["status"] == "UNDER_REVIEW"
    assert list_bindings(api, use_case["id"]) == []
    shadow = discover_shadow(api, asset["id"], "PRODUCTION")

    # Linking takes `use_case_id`; the record sets `claimed_use_case_id` from it.
    response = api.link_shadow_deployment(
        shadow["id"],
        shadow_link_payload(use_case["id"]),
        headers=OFFICER,
    )
    validate_error(response, ApiErrorId.SHADOW_LINK_MISMATCH)

    after = read_shadow(api, shadow["id"])
    assert_shadow_deployment(
        after, status="DISCOVERED", claimed_use_case_id=None, version=1
    )


def test_sev1_resolution_requires_the_regulator_report_on_file(api):
    """PRD §3.8: "Resolution is a `GovernanceOfficer` action on a `CONTAINED` incident,
    optionally updating `reported_to_regulator`, and it carries the same
    `SEV1`-plus-`affects_individuals` reporting duty enforced by
    `ERR_REGULATOR_REPORT_REQUIRED`."
    PRD §2.9: "A `SEV1` incident on a use case whose `affects_individuals` is true has
    `reported_to_regulator` true — `ERR_REGULATOR_REPORT_REQUIRED` (422). This guards
    containment out of `ESCALATED` and resolution."

    Design: Corner/errors/sev1_resolve_without_regulator_report_rejected
    """
    chain = limited_use_case_under_review(api)
    incident = report_incident(
        api, chain.use_case_id, "SEV1", reported_to_regulator=False
    )
    expected_hours = expected_containment_hours("SEV1", "LIMITED")
    assert_monitoring_incident(
        incident,
        status="OPEN",
        containment_hours=expected_hours,
        containment_deadline_at=plus_hours(DEFAULT_CLOCK, expected_hours),
        reported_to_regulator=False,
    )
    assert read_use_case(api, chain.use_case_id)["monitoring_posture"] == POSTURE_IMPAIRED

    contained = get_success_data(
        api.contain_incident(incident["id"], headers=SECURITY_REVIEWER)
    )
    assert_monitoring_incident(
        contained, status="CONTAINED", contained_at=DEFAULT_CLOCK
    )

    refused = api.resolve_incident(
        incident["id"], {"reported_to_regulator": False}, headers=OFFICER
    )
    validate_error(refused, ApiErrorId.REGULATOR_REPORT_REQUIRED)
    still_contained = read_incident(api, incident["id"])
    assert_monitoring_incident(
        still_contained,
        status="CONTAINED",
        resolved_at=None,
        version=contained["version"],
    )

    # The identical call with the notification on file is accepted.
    resolved = get_success_data(
        api.resolve_incident(
            incident["id"], {"reported_to_regulator": True}, headers=OFFICER
        )
    )
    assert_monitoring_incident(
        resolved,
        status="RESOLVED",
        reported_to_regulator=True,
        resolved_at=DEFAULT_CLOCK,
    )
    assert read_use_case(api, chain.use_case_id)["monitoring_posture"] == POSTURE_HEALTHY


# ─── Temporal and bounded-quantity rules ──────────────────────────────────


def test_granting_grace_after_the_deadline_has_elapsed_is_refused(api):
    """PRD §3.9: "**Granting grace** gives the business a bounded window to either link
    or tear the deployment down: it is available only from `DISCOVERED`, only while the
    current logical instant is at or before `grace_deadline_at` (later is rejected with
    `ERR_GRACE_PERIOD_ELAPSED`), and only for a `grace_days` figure of at least 1 and at
    most 30 (outside that range is rejected with `ERR_GRACE_EXTENSION_EXCEEDED`)."

    Design: Corner/errors/grant_grace_after_deadline_elapsed
    """
    pin_clock(api)
    asset = register_asset(api)
    shadow = discover_shadow(api, asset["id"], "PRODUCTION")
    deadline = plus_days(DEFAULT_CLOCK, expected_grace_days("PRODUCTION"))
    assert_shadow_deployment(
        shadow, status="DISCOVERED", grace_days_granted=0, grace_deadline_at=deadline
    )

    # One second past the deadline, and no sweep has run, so the row is still
    # DISCOVERED and only the temporal rule can refuse the extension.
    move_clock(api, plus_seconds(deadline, 1))

    response = api.grant_shadow_grace(
        shadow["id"], grant_grace_payload(5), headers=OFFICER
    )
    validate_error(response, ApiErrorId.GRACE_PERIOD_ELAPSED)

    after = read_shadow(api, shadow["id"])
    assert_shadow_deployment(
        after,
        status="DISCOVERED",
        grace_days_granted=0,
        grace_deadline_at=deadline,
        version=1,
    )


def test_granting_thirty_one_grace_days_exceeds_the_extension_limit(api):
    """PRD §3.9: "**Granting grace** gives the business a bounded window to either link
    or tear the deployment down: it is available only from `DISCOVERED`, only while the
    current logical instant is at or before `grace_deadline_at` (later is rejected with
    `ERR_GRACE_PERIOD_ELAPSED`), and only for a `grace_days` figure of at least 1 and at
    most 30 (outside that range is rejected with `ERR_GRACE_EXTENSION_EXCEEDED`)."

    Design: Corner/errors/grant_grace_thirty_one_days_exceeded
    """
    pin_clock(api)
    asset = register_asset(api)
    shadow = discover_shadow(api, asset["id"], "PRODUCTION")
    deadline = plus_days(DEFAULT_CLOCK, expected_grace_days("PRODUCTION"))

    # The clock stays comfortably inside the deadline, which isolates the bounded
    # quantity rule from the temporal one.
    response = api.grant_shadow_grace(
        shadow["id"], grant_grace_payload(31), headers=OFFICER
    )
    validate_error(response, ApiErrorId.GRACE_EXTENSION_EXCEEDED)

    after = read_shadow(api, shadow["id"])
    assert_shadow_deployment(
        after,
        status="DISCOVERED",
        grace_days_granted=0,
        grace_deadline_at=deadline,
        version=shadow["version"],
    )


def test_complete_reassessment_after_the_approval_expired_is_refused(api):
    """PRD §3.9: "Closing a reassessment strictly after the use case's
    `approval_expires_at` is rejected with `ERR_APPROVAL_EXPIRED`; at exactly that
    instant the call still succeeds, for the reason set out in §2.9."

    Design: Corner/errors/complete_reassessment_after_expiry_rejected
    """
    chain = use_case_under_reassessment(api)
    opened = chain.use_case
    assert opened["status"] == "UNDER_REASSESSMENT"
    assert opened["reassessment_status"] == "IN_PROGRESS"
    assert opened["reassessment_cycle_index"] == 1

    # One second past the expiry, with no second sweep to suspend the approval.
    move_clock(api, plus_seconds(opened["approval_expires_at"], 1))

    response = api.complete_reassessment(
        chain.use_case_id, reassessment_payload("CONFIRMED"), headers=OFFICER
    )
    validate_error(response, ApiErrorId.APPROVAL_EXPIRED)

    after = read_use_case(api, chain.use_case_id)
    assert after["status"] == "UNDER_REASSESSMENT"
    assert after["reassessment_cycle_index"] == 1
    assert after["version"] == opened["version"]
    assert "REASSESSMENT_COMPLETED" not in entry_types(
        list_ledger(api, chain.use_case_id)
    )
