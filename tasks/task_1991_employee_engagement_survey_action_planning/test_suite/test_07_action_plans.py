"""Action plans: review loop, execution cascade, cross-entity gates, OCC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_plan_item,
    get_direct_snapshot,
    get_plan,
    get_success_data,
    make_plan,
    make_unit_manager_headers,
    api_client,
    setup_cycle_with_field_results,
    setup_in_progress_plan,
    setup_submitted_plan,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.factories import create_action_plan_payload

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]
EXECUTIVE = TEST_USERS["executive_headers"]


def test_revise_returns_rejected_plan_to_draft_and_clears_reason(api):
    """PRD §3.7: "A rejected plan is returned to the manager, who revises it —
    moving `REJECTED → DRAFT`, clearing `rejection_reason` back to null, and
    incrementing `version` — for another round."

    Design: Difficulty/non_linear_state_machine/action_plan_rejection_revision_cycle
    """
    sc = setup_submitted_plan(title="Manager 1:1s", focus_dimension="MANAGER_SUPPORT")
    mgr = sc["manager_user_id"]
    plan_id = sc["plan"]["id"]

    rejected = get_success_data(
        api.reject_action_plan(plan_id, {"rejection_reason": "too vague"}, PEOPLE_ANALYST)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "too vague"

    revised = get_success_data(
        api.revise_action_plan(plan_id, make_unit_manager_headers(mgr))
    )
    assert revised["status"] == "DRAFT", "revise completes the loop back to DRAFT"
    assert revised["rejection_reason"] is None, "revise clears the recorded rejection_reason"


def test_resubmission_after_revision_is_accepted(api):
    """PRD §3.7: "A rejected plan is returned to the manager, who revises it —
    moving `REJECTED → DRAFT`, clearing `rejection_reason` back to null, and
    incrementing `version` — for another round."
    PRD §3.7: "Submission moves the plan `DRAFT → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/action_plan_rejection_revision_cycle
    """
    sc = setup_submitted_plan(title="Manager 1:1s", focus_dimension="MANAGER_SUPPORT")
    mgr = sc["manager_user_id"]
    plan_id = sc["plan"]["id"]
    get_success_data(
        api.reject_action_plan(plan_id, {"rejection_reason": "too vague"}, PEOPLE_ANALYST)
    )
    revised = get_success_data(
        api.revise_action_plan(plan_id, make_unit_manager_headers(mgr))
    )

    resp = api.submit_action_plan(
        plan_id,
        {"expected_plan_version": revised["version"]},
        make_unit_manager_headers(mgr),
    )
    resubmitted = validate_success(resp, 200)
    assert resubmitted["status"] == "SUBMITTED", (
        "the revision loop is cyclic: DRAFT -> SUBMITTED -> REJECTED -> DRAFT -> SUBMITTED"
    )
    assert resubmitted["rejection_reason"] is None
    assert resubmitted["version"] == revised["version"] + 1


def test_completing_item_recomputes_plan_progress(api):
    """PRD §3.7: "Progress is the count of items in `DONE`, divided by the
    count of all of the plan's items regardless of status, multiplied by 100
    and rounded down to a whole percent; dropped items stay in the denominator,
    so abandoning work never inflates progress, and a plan with no items at all
    reports 0."
    PRD §3.7: "Marking an item done — moving it `OPEN → DONE` — requires the
    parent plan to be `IN_PROGRESS`, and may be performed either by the item's
    accountable owner (the caller's `X-User-ID` equals the item's
    `owner_user_id`) or by the unit's manager."

    Design: Difficulty/transitive_cascade/item_complete_cascades_plan_progress_then_plan_completion
    """
    sc = setup_in_progress_plan(num_items=1)
    mgr = sc["manager_user_id"]
    item = sc["plan_items"][0]

    resp = api.complete_action_item(item["id"], make_unit_manager_headers(mgr))
    done_item = validate_success(resp, 200)
    assert done_item["status"] == "DONE", "hop 1: the item resolves OPEN -> DONE"

    plan = get_plan(sc["plan"]["id"])
    assert plan["progress_pct"] == 100, "hop 2: progress recomputed as floor(100*1/1)"


def test_last_open_item_completion_auto_completes_plan(api):
    """PRD §3.7: "When the last `OPEN` item resolves — every item now `DONE` or
    `DROPPED` with at least one `DONE` — the plan completes itself, moving
    `IN_PROGRESS → COMPLETED`, recomputing `progress_pct` to 100, and
    incrementing the plan's `version` by 1."

    Design: Difficulty/transitive_cascade/item_complete_cascades_plan_progress_then_plan_completion
    """
    sc = setup_in_progress_plan(num_items=1)
    mgr = sc["manager_user_id"]
    item = sc["plan_items"][0]
    version_before = sc["plan"]["version"]

    validate_success(api.complete_action_item(item["id"], make_unit_manager_headers(mgr)), 200)

    plan = get_plan(sc["plan"]["id"])
    assert plan["status"] == "COMPLETED", (
        "hop 3: the auto-transition fires from the item resolution, not from a plan call"
    )
    assert plan["progress_pct"] == 100
    assert plan["version"] > version_before


def test_approve_rejected_while_cycle_still_scoring(api):
    """PRD §3.7: "Approval moves `SUBMITTED → APPROVED` and requires the cycle
    to be in `REPORTED` status."
    PRD §2.8: "an action that the target resource's current state does not
    permit is rejected with `ERR_INVALID_STATE` (HTTP 409), so an illegal
    transition always surfaces as a state error rather than being masked by a
    business rule."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_requires_cycle_reported
    """
    sc = setup_cycle_with_field_results(
        unit_name="UnitL", manager_user_id="mgr-l", target_state="SCORING",
        submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    plan = make_plan(sc["cycle"]["id"], sc["unit"]["id"], "mgr-l",
                     title="Growth plan", focus_dimension="GROWTH")
    add_plan_item(plan["id"], "mgr-l", description="mentorship")
    plan = submit_plan(plan["id"], "mgr-l")
    assert plan["status"] == "SUBMITTED"

    resp = api.approve_action_plan(plan["id"], PEOPLE_ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_plan(plan["id"])["status"] == "SUBMITTED", (
        "cross-entity gate: cycle SCORING blocks SUBMITTED -> APPROVED"
    )


def test_approve_succeeds_once_cycle_is_reported(api):
    """PRD §3.7: "Approval moves `SUBMITTED → APPROVED` and requires the cycle
    to be in `REPORTED` status."
    PRD §3.5: "Publication moves the cycle `SCORING → REPORTED`, provided every
    snapshot of the cycle has reached `generation` at least 1, and increments
    the cycle's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_requires_cycle_reported
    """
    sc = setup_cycle_with_field_results(
        unit_name="UnitL2", manager_user_id="mgr-l2", target_state="SCORING",
        submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    plan = make_plan(sc["cycle"]["id"], sc["unit"]["id"], "mgr-l2",
                     title="Growth plan", focus_dimension="GROWTH")
    add_plan_item(plan["id"], "mgr-l2", description="mentorship")
    plan = submit_plan(plan["id"], "mgr-l2")

    validate_success(api.publish_cycle(sc["cycle"]["id"], HR_ADMIN), 200)
    approved = validate_success(api.approve_action_plan(plan["id"], PEOPLE_ANALYST), 200)
    assert approved["status"] == "APPROVED", (
        "same plan, same from-state — only the sibling cycle state changed"
    )


def test_recompute_flips_suppression_after_threshold_raise(api):
    """PRD §3.5: "A snapshot may later be recomputed — a `PeopleAnalyst`
    re-runs suppression and scoring on it — which bumps `generation` by 1 and
    increments the snapshot's `version` by 1."
    PRD §3.5: "`numeric_suppressed` is true exactly when `submitted_n` is
    strictly less than the effective minimum, counting only `SUBMITTED`
    invitations; a suppressed snapshot exposes an empty `dimension_scores` map
    and a null `overall_score`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_suppressed_plan_submit
    """
    sc = setup_cycle_with_field_results(
        unit_name="UnitI", manager_user_id="mgr-i", min_n_threshold=3,
        target_state="REPORTED", submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["numeric_suppressed"] is False
    generation_before = snap["generation"]

    get_success_data(
        api.update_org_unit(
            sc["unit"]["id"],
            {"min_n_threshold": 20, "verbatim_n_threshold": 20},
            HR_ADMIN,
        )
    )
    recomputed = validate_success(
        api.recompute_report_snapshot(snap["id"], PEOPLE_ANALYST), 200
    )
    assert recomputed["numeric_suppressed"] is True, (
        "3 submitted < raised min_n 20 -> suppressed after recompute"
    )
    assert recomputed["overall_score"] is None
    assert recomputed["dimension_scores"] == {}
    assert recomputed["generation"] == generation_before + 1, (
        "recompute bumps generation by exactly 1"
    )


def test_state_error_outranks_suppression_gate_on_plan_submit(api):
    """PRD §2.8: "Only after the request is well-formed, authenticated,
    authorized, and fully resolved does the platform consult the state
    machines: an action that the target resource's current state does not
    permit is rejected with `ERR_INVALID_STATE` (HTTP 409), so an illegal
    transition always surfaces as a state error rather than being masked by a
    business rule."
    PRD §3.7: "Submission moves the plan `DRAFT → SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_suppressed_plan_submit
    """
    sc = setup_submitted_plan(
        unit_name="UnitI2", manager_user_id="mgr-i2", min_n_threshold=3,
        submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    mgr = sc["manager_user_id"]
    plan_id = sc["plan"]["id"]
    get_success_data(
        api.reject_action_plan(plan_id, {"rejection_reason": "needs metrics"}, PEOPLE_ANALYST)
    )

    # Flip the unit snapshot to suppressed, then attempt submit from REJECTED.
    get_success_data(
        api.update_org_unit(
            sc["unit"]["id"],
            {"min_n_threshold": 20, "verbatim_n_threshold": 20},
            HR_ADMIN,
        )
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    recomputed = validate_success(api.recompute_report_snapshot(snap["id"], PEOPLE_ANALYST), 200)
    assert recomputed["numeric_suppressed"] is True

    current = get_plan(plan_id)
    assert current["status"] == "REJECTED"
    resp = api.submit_action_plan(
        plan_id,
        {"expected_plan_version": current["version"]},
        make_unit_manager_headers(mgr),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_submit_reject_revise_increments_version_exactly_once_each(api):
    """PRD §2.4: "`version` is an integer that starts at 1 and increments by
    exactly 1 on every mutation of the resource — including cascaded mutations
    triggered by a child resource, such as the survey cycle's `version`
    advancing when an item is pinned into it, and derived-field recomputes such
    as `response_rate`, `progress_pct`, or `attrition_risk` changing value."
    PRD §3.7: "A successful submission stamps `submitted_at` and increments the
    plan's `version` by 1. ... Both increment the plan's `version` by 1."

    Design: Difficulty/compensating_invariant/plan_rejection_revision_conserves_version_parity
    """
    sc = setup_cycle_with_field_results(
        unit_name="UnitQ", manager_user_id="mgr-q", target_state="REPORTED",
        submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    mgr = sc["manager_user_id"]
    plan = make_plan(sc["cycle"]["id"], sc["unit"]["id"], mgr,
                     title="Recognition plan", focus_dimension="RECOGNITION")
    add_plan_item(plan["id"], mgr, description="shout-outs")
    v0 = get_plan(plan["id"])["version"]

    submitted = submit_plan(plan["id"], mgr)
    assert submitted["version"] == v0 + 1, "submit bumps version exactly once"
    rejected = get_success_data(
        api.reject_action_plan(plan["id"], {"rejection_reason": "vague"}, PEOPLE_ANALYST)
    )
    assert rejected["version"] == v0 + 2, "reject bumps version exactly once"
    revised = get_success_data(api.revise_action_plan(plan["id"], make_unit_manager_headers(mgr)))
    assert revised["version"] == v0 + 3, (
        "revise bumps version exactly once — no skip, no double bump across the pair"
    )


def test_revision_leaves_no_rejection_residue(api):
    """PRD §3.7: "A rejected plan is returned to the manager, who revises it —
    moving `REJECTED → DRAFT`, clearing `rejection_reason` back to null, and
    incrementing `version` — for another round."

    Design: Difficulty/compensating_invariant/plan_rejection_revision_conserves_version_parity
    """
    sc = setup_cycle_with_field_results(
        unit_name="UnitQ2", manager_user_id="mgr-q2", target_state="REPORTED",
        submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    mgr = sc["manager_user_id"]
    plan = make_plan(sc["cycle"]["id"], sc["unit"]["id"], mgr,
                     title="Recognition plan", focus_dimension="RECOGNITION")
    add_plan_item(plan["id"], mgr, description="shout-outs")
    submit_plan(plan["id"], mgr)
    get_success_data(
        api.reject_action_plan(plan["id"], {"rejection_reason": "vague"}, PEOPLE_ANALYST)
    )
    revised = get_success_data(api.revise_action_plan(plan["id"], make_unit_manager_headers(mgr)))
    assert revised["status"] == "DRAFT", "compensating revise returns to the pre-submit state"
    assert revised["rejection_reason"] is None, "compensation restores the pre-reject value"


def test_plan_due_at_before_cycle_close_rejected(api):
    """PRD §2.5: "Plan and milestone deadlines are checked against the cycle's
    close: an action plan's `due_at` must be strictly after the cycle's
    `closes_at`, and a milestone's `target_at` must be no later than its plan's
    `due_at`. Violations of these temporal rules are rejected with
    `ERR_WINDOW_VIOLATION` (HTTP 422)."

    Design: Corner/validations/plan_due_at_before_cycle_close_rejected
    """
    sc = setup_cycle_with_field_results(
        unit_name="DueUnit", manager_user_id="mgr-du", num_employees=1,
        target_state="CLOSED",
    )
    resp = api.create_action_plan(
        create_action_plan_payload(
            cycle_id=sc["cycle"]["id"],
            unit_id=sc["unit"]["id"],
            title="Early plan",
            due_at="2026-09-10T00:00:00Z",
        ),
        make_unit_manager_headers("mgr-du"),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)


def test_executive_cannot_create_action_plan(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.8: "Next comes authentication (`ERR_UNAUTHENTICATED`), then role
    authorization (`ERR_UNAUTHORIZED`), then existence of the resources named
    in the URL, validated left to right (`ERR_NOT_FOUND`), then existence of
    entity identifiers referenced in the request body — `bank_id`, `item_id`,
    `unit_id`, `employee_id`, `cycle_id`, `plan_id` — which surface as
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/rbac/executive_post_plan_returns_unauthorized
    """
    resp = api.create_action_plan(
        create_action_plan_payload(
            cycle_id=NON_EXISTENT_UUID,
            unit_id=NON_EXISTENT_UUID,
            title="Exec plan",
        ),
        EXECUTIVE,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_occ_stale_plan_version_on_submit(api):
    """PRD §2.12: "Second, submitting an action plan requires
    `expected_plan_version` carrying the plan's last observed `version`; if the
    plan's `version` has advanced — for example because a reviewer's rejection
    landed after the manager's last read — the submission is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "Adding an item recomputes the plan's `progress_pct` and
    increments the plan's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_stale_plan_version_on_submit
    """
    sc = setup_cycle_with_field_results(
        unit_name="UnitZ", manager_user_id="mgr-z", target_state="REPORTED",
        submitters=3, submit_scores=[[4, 4, 4]] * 3,
    )
    mgr = sc["manager_user_id"]
    plan = make_plan(sc["cycle"]["id"], sc["unit"]["id"], mgr, title="Z plan")
    stale_version = plan["version"]
    add_plan_item(plan["id"], mgr, description="item one")

    resp = api.submit_action_plan(
        plan["id"],
        {"expected_plan_version": stale_version},
        make_unit_manager_headers(mgr),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_plan(plan["id"])
    assert after["status"] == "DRAFT", "stale submit leaves the plan DRAFT"
    assert after["version"] == stale_version + 1, "the item add bumped the plan version once"
