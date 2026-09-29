"""Difficulty rule: transitive_cascade.

One write whose effects propagate through three or more entity types, where each
hop is caused by the previous hop rather than by the original request.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    add_rollout_plan,
    add_submission,
    approve,
    assert_decimal_equals,
    assert_posture,
    complete_content,
    create_guideline_rule_payload,
    get_success_data,
    make_reviewer_headers,
    run_pre_review,
    set_clock,
    setup_base_ios,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# compromise_four_hop_signing_cascade
# ---------------------------------------------------------------------------
def _setup_signing_cascade(api):
    """Build 10 approved and rolling out, build 11 waiting for review, both signed by
    the same provisioning profile, then the root certificate reported compromised."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"})
    first = ctx.submission_id
    set_clock(api, "2026-08-02T00:00:00Z")
    approve(ctx, first)
    add_rollout_plan(
        ctx,
        first,
        mode="PHASED",
        scheduled_start_at="2026-08-02T00:00:00Z",
        start=True,
    )
    add_submission(ctx, build_number=11, version_string="1.0.1")
    second = ctx.submission_id
    complete_content(ctx, second)
    run_pre_review(ctx, second)
    get_success_data(api.queue_submission(second, ctx.release_manager))
    return ctx, first, second


def test_compromise_revokes_every_credential_linked_to_the_certificate(api):
    """"First, every credential whose `linked_cert_id` points at the compromised one and
    whose own status is `PENDING_ACTIVATION`, `ACTIVE` or `EXPIRING_SOON` moves to
    `REVOKED` with `revocation_reason` set to `COMPROMISE_CASCADE`."

    Design: Difficulty/transitive_cascade/compromise_four_hop_signing_cascade
    """
    ctx, _first, _second = _setup_signing_cascade(api)

    cert = validate_success(
        api.report_credential_compromise(
            ctx.cert_id, {"reason_code": "PRIVATE_KEY_LEAKED"}, ctx.publisher_admin
        ),
        200,
    )
    assert cert["status"] == "COMPROMISED"
    assert cert["compromised_at"] == "2026-08-02T00:00:00Z"

    profile = validate_success(
        api.get_signing_credential(ctx.profile_id, ctx.publisher_admin), 200
    )
    assert profile["status"] == "REVOKED"
    assert profile["revocation_reason"] == "COMPROMISE_CASCADE"
    assert profile["blocked_submission_count"] == 1


def test_compromise_blocks_the_in_flight_build_and_returns_its_slot(api):
    """"Second — caused by the first — every submission signed with one of those newly
    revoked profiles that is sitting in `WAITING_FOR_REVIEW` or `IN_REVIEW` moves to
    `BLOCKED_INVALID_SIGNING`, has its `review_window_id` cleared (which decrements that
    window's `slots_reserved` by one and increments its `slots_available` by one), and
    increments the revoked credential's `blocked_submission_count`."

    Design: Difficulty/transitive_cascade/compromise_four_hop_signing_cascade
    """
    ctx, first, second = _setup_signing_cascade(api)
    get_success_data(
        api.report_credential_compromise(
            ctx.cert_id, {"reason_code": "PRIVATE_KEY_LEAKED"}, ctx.publisher_admin
        )
    )

    blocked = ctx.submission(second)
    assert blocked["state"] == "BLOCKED_INVALID_SIGNING"
    assert blocked["review_window_id"] is None
    assert ctx.submission(first)["state"] == "APPROVED", (
        "an APPROVED build is not in flight and is untouched"
    )

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4


def test_compromise_restricts_the_posture_and_pauses_the_rollout(api):
    """"Fourth — caused by the third — every rollout plan of those apps sitting in
    `PHASE_ACTIVE` moves to `PAUSED` with `pause_reason_code` set to `POSTURE_DEGRADED`,
    which in turn drives each app's `distribution_state` from `PHASED_ROLLOUT` to
    `PAUSED`."

    Design: Difficulty/transitive_cascade/compromise_four_hop_signing_cascade
    """
    ctx, _first, _second = _setup_signing_cascade(api)
    get_success_data(
        api.report_credential_compromise(
            ctx.cert_id, {"reason_code": "PRIVATE_KEY_LEAKED"}, ctx.publisher_admin
        )
    )

    summary = ctx.summary()
    assert_posture(summary, "RESTRICTED", ["NO_ACTIVE_DISTRIBUTION_CERT"])
    assert_decimal_equals(summary["feature_compliance_index"], 100.00, 2, "index")
    assert summary["active_distribution_cert_present"] is False

    plan = ctx.plan()
    assert plan["state"] == "PAUSED"
    assert plan["pause_reason_code"] == "POSTURE_DEGRADED"

    app = ctx.app()
    assert app["distribution_state"] == "PAUSED"
    assert_decimal_equals(app["released_share_pct"], 1.00, 2, "released")
    assert_decimal_equals(app["held_back_share_pct"], 99.00, 2, "held back")


# ---------------------------------------------------------------------------
# guideline_publish_four_hop_staling_cascade
# ---------------------------------------------------------------------------
def _setup_superseding_rule(api):
    """An app distributing on a PASSED mapping against rule 2026.08, plus a DRAFT
    2026.09 successor that supersedes it."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        rule_overrides={"rule_code": "5.1.1", "version_label": "2026.08"},
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
    )
    set_clock(api, "2026-08-02T00:00:00Z")
    approve(ctx)
    add_rollout_plan(
        ctx, mode="PHASED", scheduled_start_at="2026-08-02T00:00:00Z", start=True
    )
    successor = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="5.1.1",
                title="Data collection and storage (2026.09 revision)",
                version_label="2026.09",
                effective_from="2026-07-15T00:00:00Z",
                supersedes_rule_id=ctx.rules["privacy"],
            ),
            ctx.policy_admin,
        )
    )
    ctx.rules["successor"] = successor["id"]
    return ctx


def _open_assessment_id(api, ctx):
    rows, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert rows, "the publication cascade must mint exactly one assessment for this app"
    return rows[0]["id"]


def test_publishing_the_successor_stales_the_repointed_mapping(api):
    """"First, every feature mapping that pointed at the superseded rule is re-pointed at
    the new rule, and each such mapping whose `self_review_status` was `PASSED` or
    `WAIVED_BY_PLATFORM` is moved to `STALE` with `staled_by_rule_id` set to the new
    rule's identifier — prior attestations do not survive a rulebook change."

    Design: Difficulty/transitive_cascade/guideline_publish_four_hop_staling_cascade
    """
    ctx = _setup_superseding_rule(api)

    published = validate_success(
        api.publish_guideline_rule(ctx.rules["successor"], ctx.policy_admin), 200
    )
    assert published["status"] == "EFFECTIVE"
    assert published["severity_weight"] == 4
    assert published["remediation_grace_days"] == 30
    assert published["impacted_app_count"] == 1

    predecessor = validate_success(
        api.get_guideline_rule(ctx.rules["privacy"], ctx.policy_admin), 200
    )
    assert predecessor["status"] == "SUPERSEDED"

    mapping = ctx.mapping(ctx.mappings["privacy"])
    assert mapping["self_review_status"] == "STALE"
    assert mapping["guideline_rule_id"] == ctx.rules["successor"]
    assert mapping["staled_by_rule_id"] == ctx.rules["successor"]
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 50.00, 2, "index")


def test_publishing_pauses_a_rollout_the_publisher_never_touched(api):
    """"Fourth — caused by the third — every rollout plan of those apps that is
    `PHASE_ACTIVE` moves to `PAUSED` with `pause_reason_code` set to `POSTURE_DEGRADED`,
    driving `distribution_state` to `PAUSED` with both share fields frozen."

    Design: Difficulty/transitive_cascade/guideline_publish_four_hop_staling_cascade
    """
    ctx = _setup_superseding_rule(api)
    get_success_data(
        api.publish_guideline_rule(ctx.rules["successor"], ctx.policy_admin)
    )

    assert_posture(
        ctx.summary(),
        "RESTRICTED",
        ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"],
    )

    plan = ctx.plan()
    assert plan["state"] == "PAUSED"
    assert plan["pause_reason_code"] == "POSTURE_DEGRADED"

    app = ctx.app()
    assert app["distribution_state"] == "PAUSED"
    assert_decimal_equals(app["released_share_pct"], 1.00, 2, "released")
    assert_decimal_equals(app["held_back_share_pct"], 99.00, 2, "held back")


def test_the_minted_assessment_carries_the_exposure_weighted_severity(api):
    """"`impact_severity` is the rule's `severity_weight` multiplied by the count of
    entries in `affected_feature_codes` multiplied by `exposure_factor`, with the single
    product rounded half up to two decimal places."

    Design: Difficulty/transitive_cascade/guideline_publish_four_hop_staling_cascade
    """
    ctx = _setup_superseding_rule(api)
    get_success_data(
        api.publish_guideline_rule(ctx.rules["successor"], ctx.policy_admin)
    )

    assessment = validate_success(
        api.get_impact_assessment(
            _open_assessment_id(api, ctx), ctx.compliance_officer
        ),
        200,
    )
    assert assessment["affected_feature_codes"] == ["ACCOUNT_DELETION"]
    assert_decimal_equals(assessment["exposure_factor"], 1.5, 2, "exposure_factor")
    assert_decimal_equals(assessment["impact_severity"], 6.00, 2, "impact_severity")
    assert assessment["remediation_deadline_at"] == "2026-08-14T00:00:00Z"
    assert assessment["opened_at"] == "2026-08-02T00:00:00Z"


def test_accept_no_change_restores_the_stale_mapping_but_not_the_rollout(api):
    """"Acceptance is not merely a bookkeeping close: every feature mapping named in
    `affected_feature_codes` that is still `STALE` is restored to `PASSED`, the app's
    `feature_compliance_index` is recomputed on that basis, and with no other objection
    outstanding the app's posture returns to `OPEN`."

    Design: Difficulty/transitive_cascade/guideline_publish_four_hop_staling_cascade
    """
    ctx = _setup_superseding_rule(api)
    get_success_data(
        api.publish_guideline_rule(ctx.rules["successor"], ctx.policy_admin)
    )
    assessment_id = _open_assessment_id(api, ctx)
    get_success_data(
        api.assess_impact(
            assessment_id,
            {
                "action": "START",
                "note": (
                    "Reviewing the 2026.09 delta against the shipped deletion flow"
                ),
            },
            ctx.compliance_officer,
        )
    )

    accepted = validate_success(
        api.assess_impact(
            assessment_id,
            {
                "action": "ACCEPT_NO_CHANGE",
                "note": "The shipped flow already satisfies the 2026.09 wording",
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED_NO_CHANGE"
    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "PASSED"

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, 2, "index")
    assert app["compliance_posture"] == "OPEN"
    assert app["distribution_state"] == "PAUSED", (
        "posture recovery does not auto-resume the rollout"
    )


# ---------------------------------------------------------------------------
# approve_supersede_cancels_scheduled_plan
# ---------------------------------------------------------------------------
def _setup_second_build_ready_to_approve(api):
    """Build 10 approved with a still-SCHEDULED plan for 2026-08-10, build 11 claimed
    by a second reviewer at 2026-08-03."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"})
    first = ctx.submission_id
    set_clock(api, "2026-08-02T00:00:00Z")
    approve(ctx, first)
    plan = add_rollout_plan(
        ctx, first, mode="PHASED", scheduled_start_at="2026-08-10T00:00:00Z"
    )
    add_submission(ctx, build_number=11, version_string="1.0.1")
    second = ctx.submission_id
    complete_content(ctx, second)
    run_pre_review(ctx, second)
    set_clock(api, "2026-08-03T00:00:00Z")
    get_success_data(api.queue_submission(second, ctx.release_manager))
    second_reviewer = make_reviewer_headers("u-reviewer-2")
    get_success_data(api.claim_submission(second, second_reviewer))
    return ctx, first, second, plan["id"], second_reviewer


def test_approving_build_eleven_supersedes_the_approved_build_ten(api):
    """"Approval stamps `decided_at`, and any other submission of the same app already
    `APPROVED` is moved to `SUPERSEDED`, which cancels that build's `SCHEDULED` rollout
    plans and is refused if that build has a plan in `PHASE_ACTIVE`."

    Design: Difficulty/transitive_cascade/approve_supersede_cancels_scheduled_plan
    """
    ctx, first, second, _plan_id, second_reviewer = (
        _setup_second_build_ready_to_approve(api)
    )

    approved = validate_success(
        api.decide_submission(second, {"outcome": "APPROVE"}, second_reviewer), 200
    )
    assert approved["state"] == "APPROVED"
    assert ctx.submission(first)["state"] == "SUPERSEDED"


def test_supersede_cancels_the_scheduled_plan_with_no_audience_to_undo(api):
    """"`ROLLED_BACK` and `CANCELLED` are terminal; a `SCHEDULED` plan is cancelled
    automatically, with `terminated_at` stamped, when its submission is superseded, and
    because no share field ever moved there is no audience accounting to undo."

    Design: Difficulty/transitive_cascade/approve_supersede_cancels_scheduled_plan
    """
    ctx, _first, second, plan_id, second_reviewer = (
        _setup_second_build_ready_to_approve(api)
    )
    get_success_data(
        api.decide_submission(second, {"outcome": "APPROVE"}, second_reviewer)
    )

    plan = ctx.plan(plan_id)
    assert plan["state"] == "CANCELLED"
    assert plan["terminated_at"] == "2026-08-03T00:00:00Z"
    assert_decimal_equals(plan["released_share_pct"], 0.00, 2, "plan released")

    app = ctx.app()
    assert app["distribution_state"] == "NOT_DISTRIBUTED"
    assert app["live_submission_id"] is None


def test_both_decided_builds_hold_consumed_capacity_slots(api):
    """"`slots_available` is `capacity_slots` minus both."

    Design: Difficulty/transitive_cascade/approve_supersede_cancels_scheduled_plan
    """
    ctx, _first, second, _plan_id, second_reviewer = (
        _setup_second_build_ready_to_approve(api)
    )
    get_success_data(
        api.decide_submission(second, {"outcome": "APPROVE"}, second_reviewer)
    )

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 2
    assert window["slots_available"] == 3
