"""Difficulty rule: cross_entity_state_dependency.

An operation whose own entity is in a perfectly legal state is refused because a
sibling entity it does not even reference is not yet terminal.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_effective_rule,
    add_rollout_plan,
    assert_decimal_equals,
    assert_posture,
    assert_slot_conservation,
    create_commerce_item_payload,
    get_success_data,
    make_reviewer_headers,
    set_clock,
    setup_approved_ios,
    setup_base_ios,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# queue_gated_by_open_impact_assessment_of_another_entity
# ---------------------------------------------------------------------------
def _setup_cascade_opened_assessment(api):
    """A PRE_REVIEW_PASSED build whose app was caught by a successor-rule publication,
    leaving one STALE mapping and one OPEN impact assessment behind."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
        risk_weight=4,
    )
    set_clock(api, "2026-08-02T00:00:00Z")
    successor = add_effective_rule(
        ctx,
        key="privacy_next",
        category="PRIVACY",
        title="Data collection and storage (2026.09 revision)",
        version_label="2026.09",
        effective_from="2026-08-01T00:00:00Z",
        supersedes_rule_id=ctx.rules["privacy"],
    )
    rows, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 1, "the cascade opens exactly one assessment per affected app"
    return ctx, successor["id"], rows[0]["id"]


def _repass_mapping(api, ctx):
    """`PASS` moves `STALE -> PASSED` directly, "for a re-attestation after a rulebook
    change"; `START` is declared only from `NOT_STARTED`."""
    return get_success_data(
        api.self_review_mapping(
            ctx.mappings["privacy"],
            {
                "outcome": "PASS",
                "evidence_ref": (
                    "https://evidence.northwind.example/acct-deletion-2026-09.pdf"
                ),
            },
            ctx.compliance_officer,
        )
    )


def test_publication_cascade_stales_the_mapping_and_halves_the_index(api):
    """"First, every feature mapping that pointed at the superseded rule is re-pointed at the
    new rule, and each such mapping whose `self_review_status` was `PASSED` or
    `WAIVED_BY_PLATFORM` is moved to `STALE` with `staled_by_rule_id` set to the new rule's
    identifier — prior attestations do not survive a rulebook change."

    Design: Difficulty/cross_entity_state_dependency/queue_gated_by_open_impact_assessment_of_another_entity
    """
    ctx, successor_id, _assessment_id = _setup_cascade_opened_assessment(api)

    predecessor = get_success_data(
        api.get_guideline_rule(ctx.rules["privacy"], ctx.policy_admin)
    )
    assert predecessor["status"] == "SUPERSEDED"

    mapping = ctx.mapping(ctx.mappings["privacy"])
    assert mapping["guideline_rule_id"] == successor_id
    assert mapping["self_review_status"] == "STALE"
    assert mapping["staled_by_rule_id"] == successor_id
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 50.00, 2, "index at half weight"
    )


def test_the_opened_assessment_carries_its_severity_and_grace_derived_deadline(api):
    """"`impact_severity` is the rule's `severity_weight` multiplied by the count of entries in
    `affected_feature_codes` multiplied by `exposure_factor`, with the single product rounded
    half up to two decimal places."

    Design: Difficulty/cross_entity_state_dependency/queue_gated_by_open_impact_assessment_of_another_entity
    """
    ctx, _successor_id, assessment_id = _setup_cascade_opened_assessment(api)

    assessment = validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )
    assert assessment["status"] == "OPEN"
    assert assessment["opened_at"] == "2026-08-02T00:00:00Z"
    assert_decimal_equals(assessment["impact_severity"], 4.00, 2, "impact_severity")
    assert assessment["remediation_deadline_at"] == "2026-08-31T00:00:00Z"
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )
    assert_posture(
        ctx.app(),
        "RESTRICTED",
        ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"],
    )


def test_a_healed_index_still_cannot_queue_while_the_sibling_row_lives(api):
    """"`START` moves `OPEN → IN_ASSESSMENT`, stamps `assessed_by_user_id` with the acting
    operator and `assessed_at` with the current instant, and recomputes `impact_severity`
    against the app's *current* `exposure_factor` — an app that has begun distributing since
    the row was opened becomes more severe at this moment."

    Design: Difficulty/cross_entity_state_dependency/queue_gated_by_open_impact_assessment_of_another_entity
    """
    ctx, _successor_id, assessment_id = _setup_cascade_opened_assessment(api)
    _repass_mapping(api, ctx)

    assert_decimal_equals(ctx.app()["feature_compliance_index"], 100.00, 2, "index")
    assert_posture(ctx.app(), "RESTRICTED", ["OPEN_IMPACT_ASSESSMENT"])
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )

    started = validate_success(
        api.assess_impact(
            assessment_id,
            {
                "action": "START",
                "note": "Reviewing the 2026.09 wording against the shipped flow",
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert started["status"] == "IN_ASSESSMENT"
    assert_decimal_equals(started["impact_severity"], 4.00, 2, "impact_severity")
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )


def test_terminating_the_assessment_finally_lets_the_build_queue(api):
    """"`ACCEPT_NO_CHANGE` instead terminates the row at `ACCEPTED_NO_CHANGE`, and it is gated
    twice: the rule's `category` must not be `SAFETY`, and `impact_severity` must be at or
    below 6.00 — the ceiling is inclusive, so a severity of exactly 6.00 may be accepted while
    6.01 may not, and a breach is refused with `ERR_IMPACT_TOO_SEVERE`."

    Design: Difficulty/cross_entity_state_dependency/queue_gated_by_open_impact_assessment_of_another_entity
    """
    ctx, _successor_id, assessment_id = _setup_cascade_opened_assessment(api)
    _repass_mapping(api, ctx)
    get_success_data(
        api.assess_impact(
            assessment_id, {"action": "START"}, ctx.compliance_officer
        )
    )

    accepted = validate_success(
        api.assess_impact(
            assessment_id,
            {
                "action": "ACCEPT_NO_CHANGE",
                "note": "Existing deletion flow already satisfies the revised wording",
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED_NO_CHANGE"
    assert_posture(ctx.app(), "OPEN", [])

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["review_window_id"] == ctx.window_id
    assert queued["queued_at"] == "2026-08-02T00:00:00Z"
    assert queued["provisional_deadline_at"] == "2026-08-04T00:00:00Z"
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority_score")
    assert queued["priority_band"] == "NORMAL"

    window = ctx.window()
    assert window["slots_reserved"] == 1
    assert window["slots_available"] == 4
    assert_slot_conservation(window)


# ---------------------------------------------------------------------------
# listing_list_gated_by_rollout_driven_distribution_state
# ---------------------------------------------------------------------------
def _setup_metadata_complete_with_scheduled_plan(api):
    """An APPROVED build, a METADATA_COMPLETE listing and one SCHEDULED phased plan."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    get_success_data(
        api.drive_listing(
            ctx.app_record_id,
            {"listing_action": "COMPLETE_METADATA"},
            ctx.publisher_admin,
        )
    )
    add_rollout_plan(ctx, mode="PHASED", scheduled_start_at=DEFAULT_CLOCK)
    return ctx


def _listing(api, ctx, action, headers=None):
    return api.drive_listing(
        ctx.app_record_id, {"listing_action": action}, headers or ctx.publisher_admin
    )


def test_list_is_refused_while_the_app_is_not_distributed(api):
    """"`LIST` moves `METADATA_COMPLETE → LISTED`, or `DELISTED → LISTED`, and requires two
    things: the posture must not be `FROZEN`, and `distribution_state` must not be
    `NOT_DISTRIBUTED` — a store page may only go live once a build is actually being
    distributed, and attempting it before then is `ERR_APP_NOT_DISTRIBUTED`."

    Design: Difficulty/cross_entity_state_dependency/listing_list_gated_by_rollout_driven_distribution_state
    """
    ctx = _setup_metadata_complete_with_scheduled_plan(api)

    assert ctx.app()["distribution_state"] == "NOT_DISTRIBUTED"
    assert ctx.plan()["state"] == "SCHEDULED"

    validate_error(
        _listing(api, ctx, "LIST"), ApiErrorId.ERR_APP_NOT_DISTRIBUTED, 409
    )
    assert ctx.app()["listing_state"] == "METADATA_COMPLETE"


def test_starting_the_phased_plan_unlocks_the_identical_listing_transition(api):
    """"A phased plan then moves `SCHEDULED → PHASE_ACTIVE` with `phase_index` 0,
    `released_share_pct` 1.00, `held_back_share_pct` 99.00 and `phase_entered_at` stamped, and
    the app's `distribution_state` becomes `PHASED_ROLLOUT`."

    Design: Difficulty/cross_entity_state_dependency/listing_list_gated_by_rollout_driven_distribution_state
    """
    ctx = _setup_metadata_complete_with_scheduled_plan(api)

    started = validate_success(
        api.start_rollout_plan(ctx.plan_id, ctx.release_manager), 200
    )
    assert started["state"] == "PHASE_ACTIVE"
    assert started["phase_index"] == 0
    assert_decimal_equals(started["released_share_pct"], 1.00, 2, "released")
    assert_decimal_equals(started["held_back_share_pct"], 99.00, 2, "held back")

    app = ctx.app()
    assert app["distribution_state"] == "PHASED_ROLLOUT"
    assert app["live_submission_id"] == ctx.submission_id

    listed = validate_success(_listing(api, ctx, "LIST"), 200)
    assert listed["listing_state"] == "LISTED"


def test_rollback_clears_the_distribution_but_never_the_listing(api):
    """"In every case the plan moves to `ROLLED_BACK`, `released_share_pct` returns to 0.00 with
    `held_back_share_pct` back to exactly 100.00 and no residue, `terminated_at` is stamped, the
    app's `rollback_count` increments, `live_submission_id` is cleared, and both standing scores
    are recomputed — a rollback costs the account the clean-rollout credit it would otherwise
    have earned."

    Design: Difficulty/cross_entity_state_dependency/listing_list_gated_by_rollout_driven_distribution_state
    """
    ctx = _setup_metadata_complete_with_scheduled_plan(api)
    get_success_data(api.start_rollout_plan(ctx.plan_id, ctx.release_manager))
    get_success_data(_listing(api, ctx, "LIST"))

    rolled_back = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert rolled_back["state"] == "ROLLED_BACK"
    assert rolled_back["terminated_at"] == DEFAULT_CLOCK
    assert_decimal_equals(rolled_back["released_share_pct"], 0.00, 2, "released")
    assert_decimal_equals(rolled_back["held_back_share_pct"], 100.00, 2, "held back")

    app = ctx.app()
    assert app["distribution_state"] == "ROLLED_BACK"
    assert app["live_submission_id"] is None
    assert app["rollback_count"] == 1
    assert app["listing_state"] == "LISTED", (
        "the rollback never touches the listing dimension"
    )


def test_delist_always_succeeds_but_relisting_a_rolled_back_app_does_not(api):
    """"`DELIST` moves `LISTED → DELISTED` with no preconditions at all, and is the only listing
    action a `PlatformPolicyAdmin` may take."

    Design: Difficulty/cross_entity_state_dependency/listing_list_gated_by_rollout_driven_distribution_state
    """
    ctx = _setup_metadata_complete_with_scheduled_plan(api)
    get_success_data(api.start_rollout_plan(ctx.plan_id, ctx.release_manager))
    get_success_data(_listing(api, ctx, "LIST"))
    get_success_data(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        )
    )

    delisted = validate_success(_listing(api, ctx, "DELIST"), 200)
    assert delisted["listing_state"] == "DELISTED"
    validate_error(
        _listing(api, ctx, "LIST"), ApiErrorId.ERR_APP_NOT_DISTRIBUTED, 409
    )
    assert ctx.app()["listing_state"] == "DELISTED"


# ---------------------------------------------------------------------------
# build_approval_gated_by_sibling_commerce_item_status
# ---------------------------------------------------------------------------
def _setup_in_review_with_submitted_item(api):
    """A clean IN_REVIEW build plus one sibling commerce item sitting in SUBMITTED."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    item = get_success_data(
        api.create_commerce_item(
            create_commerce_item_payload(
                ctx.app_record_id,
                item_type="CONSUMABLE",
                price_tier_cents=299,
            ),
            ctx.publisher_admin,
        )
    )
    get_success_data(api.submit_commerce_item(item["id"], ctx.publisher_admin))
    return ctx, item["id"]


def _approve_build(api, ctx):
    return api.decide_submission(
        ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer
    )


def test_a_submitted_sibling_item_blocks_the_build_approval(api):
    """"This queue is coupled to the build queue in one direction: a build may not be approved
    while any commerce item of its app is still `SUBMITTED`."

    Design: Difficulty/cross_entity_state_dependency/build_approval_gated_by_sibling_commerce_item_status
    """
    ctx, item_id = _setup_in_review_with_submitted_item(api)

    assert get_success_data(
        api.get_commerce_item(item_id, ctx.publisher_admin)
    )["status"] == "SUBMITTED"
    validate_error(
        _approve_build(api, ctx), ApiErrorId.ERR_INVALID_COMMERCE_ITEM_STATE, 409
    )
    assert ctx.submission()["state"] == "IN_REVIEW"


def test_a_rejected_sibling_item_is_irrelevant_to_the_gate(api):
    """"`APPROVE` moves `SUBMITTED → APPROVED` and recomputes `commission_rate_applied` and
    `commission_cents` from whatever gross is already stored; `REJECT` moves `SUBMITTED →
    REJECTED` and requires a non-empty `rejection_note`, otherwise `ERR_VALIDATION`."

    Design: Difficulty/cross_entity_state_dependency/build_approval_gated_by_sibling_commerce_item_status
    """
    ctx, _item_a_id = _setup_in_review_with_submitted_item(api)

    item_b = get_success_data(
        api.create_commerce_item(
            create_commerce_item_payload(
                ctx.app_record_id,
                item_type="NON_CONSUMABLE",
                price_tier_cents=1999,
            ),
            ctx.publisher_admin,
        )
    )
    get_success_data(api.submit_commerce_item(item_b["id"], ctx.publisher_admin))
    rejected = validate_success(
        api.review_commerce_item(
            item_b["id"],
            {
                "outcome": "REJECT",
                "rejection_note": (
                    "Entitlement description does not match the shipped unlock"
                ),
            },
            make_reviewer_headers("u-reviewer-2"),
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_note"]

    validate_error(
        _approve_build(api, ctx), ApiErrorId.ERR_INVALID_COMMERCE_ITEM_STATE, 409
    )
    assert ctx.submission()["state"] == "IN_REVIEW"


def test_clearing_the_submitted_item_lets_the_build_approve_past_a_draft_sibling(api):
    """"`APPROVE` moves `IN_REVIEW → APPROVED` and re-checks the content gates against the
    authoritative final figures: `disclosure_accuracy_score_final` must be at or above 0.9500,
    otherwise `ERR_PRIVACY_DISCLOSURE_INACCURATE`; no finding of severity `CRITICAL` may be
    `OPEN` or `DISPUTED`, otherwise `ERR_CRITICAL_FINDING_UNRESOLVED` — note that disputing a
    critical finding does not clear this gate, only reconciling or dismissing it does;
    `attested_age_rating` must be at or above `derived_age_rating`, otherwise
    `ERR_AGE_RATING_UNDERSTATED`; and no commerce item of the app may still be sitting in
    `SUBMITTED`, otherwise `ERR_INVALID_COMMERCE_ITEM_STATE`."

    Design: Difficulty/cross_entity_state_dependency/build_approval_gated_by_sibling_commerce_item_status
    """
    ctx, item_a_id = _setup_in_review_with_submitted_item(api)

    approved_item = validate_success(
        api.review_commerce_item(
            item_a_id, {"outcome": "APPROVE"}, make_reviewer_headers("u-reviewer-2")
        ),
        200,
    )
    assert approved_item["status"] == "APPROVED"
    assert_decimal_equals(approved_item["commission_rate_applied"], 0.30, 2, "rate")
    assert approved_item["commission_cents"] == 0

    item_c = get_success_data(
        api.create_commerce_item(
            create_commerce_item_payload(
                ctx.app_record_id, item_type="CONSUMABLE", price_tier_cents=99
            ),
            ctx.publisher_admin,
        )
    )
    assert item_c["status"] == "DRAFT"

    decided = validate_success(_approve_build(api, ctx), 200)
    assert decided["state"] == "APPROVED"
    assert_decimal_equals(
        decided["disclosure_accuracy_score_final"], 1.0000, 4, "final"
    )

    still_submitted, _meta = validate_paginated(
        api.list_commerce_items(
            ctx.publisher_admin,
            params={"app_record_id": ctx.app_record_id, "status": "SUBMITTED"},
        )
    )
    assert still_submitted == []
    assert ctx.app()["distribution_state"] == "NOT_DISTRIBUTED"
