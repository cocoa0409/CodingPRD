"""Corner section: cross_cutting_complexity_layers.

Instances where two or more independent mechanisms — optimistic concurrency,
multi-hop cascades, dual-variant calculations and the capacity selector — are
exercised in the same request so that their interaction order is observable.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_submission,
    assert_decimal_equals,
    assert_posture,
    assert_share_conservation,
    assert_slot_conservation,
    claim,
    complete_content,
    create_behavior_finding_payload,
    create_guideline_rule_payload,
    create_review_capacity_window_payload,
    create_rollout_plan_payload,
    create_signing_credential_payload,
    create_submission_payload,
    get_success_data,
    new_account,
    num,
    privacy_item,
    queue,
    reject,
    rejection_reasons_for,
    run_pre_review,
    set_clock,
    setup_approved_ios,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# submission_create_rejects_the_app_record_version_the_previous_submission_already_burned
# ---------------------------------------------------------------------------
def _setup_burned_app_version(api):
    """BASE-IOS through the passing mapping, then one build created at the app
    record revision current at that moment, which the creation itself burns."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        with_submission=False,
        with_content=False,
        with_pre_review=False,
        with_window=False,
    )
    stale_version = ctx.app_version()
    first = validate_success(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                stale_version,
                build_number=100,
                version_string="5.0.0",
            ),
            ctx.release_manager,
        ),
        201,
    )
    return ctx, stale_version, first


def test_replaying_the_burned_app_record_version_is_a_412_revision_error(api):
    """"Creating a submission requires `expected_app_record_version` to equal the
    current `version` of the `AppRecord` named by `app_record_id`."

    Design: Corner/cross_cutting_complexity_layers/submission_create_rejects_the_app_record_version_the_previous_submission_already_burned
    """
    ctx, stale_version, first = _setup_burned_app_version(api)
    assert first["state"] == "DRAFT"
    assert ctx.app_version() == stale_version + 1

    validate_error(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                stale_version,
                build_number=101,
                version_string="5.0.1",
            ),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_STALE_APP_RECORD_VERSION,
        412,
    )

    rows, meta = validate_paginated(
        api.list_submissions(ctx.release_manager, {"app_record_id": ctx.app_record_id})
    )
    assert meta["total_count"] == 1, "the refused create must not have persisted a build"
    assert [row["build_number"] for row in rows] == [100]
    assert ctx.app_version() == stale_version + 1, "a refused create burns no revision"


def test_the_fresh_app_record_version_lets_the_second_build_through(api):
    """"The guard exists because a new submission legitimately supersedes the app's
    other `DRAFT` submissions by moving them to `DEVELOPER_WITHDRAWN`; a stale expected
    value means the client's picture of the app's draft set, its posture or its live
    build is out of date, and the write would destroy work the client never saw."

    Design: Corner/cross_cutting_complexity_layers/submission_create_rejects_the_app_record_version_the_previous_submission_already_burned
    """
    ctx, stale_version, first = _setup_burned_app_version(api)

    second = validate_success(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                stale_version + 1,
                build_number=101,
                version_string="5.0.1",
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert second["build_number"] == 101
    assert second["state"] == "DRAFT"
    assert ctx.app_version() == stale_version + 2
    assert ctx.submission(first["id"])["state"] == "DEVELOPER_WITHDRAWN"


# ---------------------------------------------------------------------------
# the_stale_app_record_version_outranks_the_rollout_window_conflict_it_would_also_have_hit
# ---------------------------------------------------------------------------
def _setup_live_phased_rollout(api):
    """An APPROVED build whose PHASED plan has been created and started, so the
    revision captured before the plan existed is two writes behind."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api)
    stale_version = ctx.app_version()
    plan = get_success_data(
        api.create_rollout_plan(
            create_rollout_plan_payload(
                ctx.app_record_id,
                ctx.submission_id,
                stale_version,
                mode="PHASED",
                scheduled_start_at=DEFAULT_CLOCK,
            ),
            ctx.release_manager,
        )
    )
    ctx.plan_id = plan["id"]
    get_success_data(api.start_rollout_plan(plan["id"], ctx.release_manager))
    return ctx, stale_version


def test_the_stale_revision_answers_before_the_window_exclusivity_conflict(api):
    """"The revision guard is also positioned deliberately in the rejection ladder of
    §2.7: it is evaluated *before* the target entity's own state is examined, so when
    the supplied expected version is stale **and** the target is in a state that forbids
    the operation, the response is the 412 revision error, never the 409 state error."

    Design: Corner/cross_cutting_complexity_layers/the_stale_app_record_version_outranks_the_rollout_window_conflict_it_would_also_have_hit
    """
    ctx, stale_version = _setup_live_phased_rollout(api)
    fresh_version = ctx.app_version()
    assert fresh_version == stale_version + 2, "create plus start each burn a revision"

    validate_error(
        api.create_rollout_plan(
            create_rollout_plan_payload(
                ctx.app_record_id,
                ctx.submission_id,
                stale_version,
                mode="PHASED",
                scheduled_start_at="2026-08-05T00:00:00Z",
            ),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_STALE_APP_RECORD_VERSION,
        412,
    )

    _rows, meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, {"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 1
    assert ctx.app_version() == fresh_version


def test_refreshing_the_revision_makes_the_overlap_conflict_visible(api):
    """"Against every other plan of the same app in state `SCHEDULED`, `PHASE_ACTIVE` or
    `PAUSED`, a conflict exists when the new start is at or before that plan's projected
    end and that plan's start is at or before the new projected end."

    Design: Corner/cross_cutting_complexity_layers/the_stale_app_record_version_outranks_the_rollout_window_conflict_it_would_also_have_hit
    """
    ctx, _stale_version = _setup_live_phased_rollout(api)
    fresh_version = ctx.app_version()

    validate_error(
        api.create_rollout_plan(
            create_rollout_plan_payload(
                ctx.app_record_id,
                ctx.submission_id,
                fresh_version,
                mode="PHASED",
                scheduled_start_at="2026-08-05T00:00:00Z",
            ),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, {"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 1
    assert ctx.app_version() == fresh_version, "a refused create burns no revision"
    plan = ctx.plan()
    assert plan["state"] == "PHASE_ACTIVE"
    assert_decimal_equals(plan["released_share_pct"], 1.00, 2, "released_share_pct")


# ---------------------------------------------------------------------------
# a_second_signing_credential_may_not_reuse_the_account_version_the_first_one_consumed
# ---------------------------------------------------------------------------
def _setup_account_with_one_certificate(api):
    """One enrolled account plus one IOS distribution certificate registered at the
    account's creation revision, which the registration consumes."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    acct_v1 = ctx.account_version()
    cert = validate_success(
        api.create_signing_credential(
            create_signing_credential_payload(ctx.account_id, acct_v1),
            ctx.publisher_admin,
        ),
        201,
    )
    ctx.cert_id = cert["id"]
    return ctx, acct_v1


def _profile_payload(ctx, expected_version):
    return create_signing_credential_payload(
        ctx.account_id,
        expected_version,
        credential_type="PROVISIONING_PROFILE",
        key_custody="CLOUD_MANAGED",
        linked_cert_id=ctx.cert_id,
    )


def test_replaying_the_account_version_yields_the_account_scoped_revision_error(api):
    """"Registering a signing credential requires `expected_publisher_account_version`
    to equal the current `version` of the `PublisherAccount` named by
    `publisher_account_id`; a mismatch is rejected with
    `ERR_STALE_PUBLISHER_ACCOUNT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/a_second_signing_credential_may_not_reuse_the_account_version_the_first_one_consumed
    """
    ctx, acct_v1 = _setup_account_with_one_certificate(api)

    validate_error(
        api.create_signing_credential(
            _profile_payload(ctx, acct_v1), ctx.publisher_admin
        ),
        ApiErrorId.ERR_STALE_PUBLISHER_ACCOUNT_VERSION,
        412,
    )

    _rows, meta = validate_paginated(
        api.list_signing_credentials(
            ctx.publisher_admin, {"publisher_account_id": ctx.account_id}
        )
    )
    assert meta["total_count"] == 1, "the refused registration persisted nothing"
    assert ctx.account_version() == acct_v1 + 1


def test_the_refreshed_account_version_registers_the_profile_pending_activation(api):
    """"Newly registered material lands in status `PENDING_ACTIVATION` with
    `revocation_reason` and `compromised_at` null and `blocked_submission_count` at 0,
    and the registration advances the owning account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/a_second_signing_credential_may_not_reuse_the_account_version_the_first_one_consumed
    """
    ctx, acct_v1 = _setup_account_with_one_certificate(api)
    acct_v2 = ctx.account_version()

    profile = validate_success(
        api.create_signing_credential(
            _profile_payload(ctx, acct_v2), ctx.publisher_admin
        ),
        201,
    )
    assert profile["status"] == "PENDING_ACTIVATION"
    assert profile["revocation_reason"] is None
    assert profile["compromised_at"] is None
    assert profile["blocked_submission_count"] == 0
    assert ctx.account_version() == acct_v2 + 1 == acct_v1 + 2


# ---------------------------------------------------------------------------
# membership_renewal_is_occ_guarded_on_the_same_account_version_as_credential_creation
# ---------------------------------------------------------------------------
def test_renewal_replaying_the_version_the_certificate_burned_is_refused(api):
    """"Renewing program membership also requires `expected_publisher_account_version`
    to match the account's current `version`, with the same
    `ERR_STALE_PUBLISHER_ACCOUNT_VERSION` and HTTP 412 on mismatch."

    Design: Corner/cross_cutting_complexity_layers/membership_renewal_is_occ_guarded_on_the_same_account_version_as_credential_creation
    """
    ctx, acct_v1 = _setup_account_with_one_certificate(api)

    validate_error(
        api.renew_membership(
            ctx.account_id,
            {
                "expected_publisher_account_version": acct_v1,
                "paid_through_at": "2028-08-01T00:00:00Z",
            },
            ctx.publisher_admin,
        ),
        ApiErrorId.ERR_STALE_PUBLISHER_ACCOUNT_VERSION,
        412,
    )

    account = ctx.account()
    assert account["membership_paid_through_at"] == "2027-08-01T00:00:00Z"
    assert account["version"] == acct_v1 + 1


def test_renewal_at_the_current_version_moves_the_paid_through_instant(api):
    """"On success `membership_paid_through_at` becomes the supplied `paid_through_at`,
    `program_status` returns from `EXPIRED` to `ACTIVE`, the compliance posture of every
    app record of the account is recomputed, and the account's `version` advances by
    one."

    Design: Corner/cross_cutting_complexity_layers/membership_renewal_is_occ_guarded_on_the_same_account_version_as_credential_creation
    """
    ctx, acct_v1 = _setup_account_with_one_certificate(api)
    acct_v2 = ctx.account_version()

    renewed = validate_success(
        api.renew_membership(
            ctx.account_id,
            {
                "expected_publisher_account_version": acct_v2,
                "paid_through_at": "2028-08-01T00:00:00Z",
            },
            ctx.publisher_admin,
        ),
        200,
    )
    assert renewed["membership_paid_through_at"] == "2028-08-01T00:00:00Z"
    assert renewed["program_status"] == "ACTIVE"
    assert renewed["version"] == acct_v2 + 1 == acct_v1 + 2


# ---------------------------------------------------------------------------
# the_guideline_publication_cascade_runs_all_four_hops_on_a_live_app_in_one_request
# ---------------------------------------------------------------------------
def _publish_privacy_successor(api, ctx):
    """Publish a 2026.09 PRIVACY rule superseding the app's effective rule."""
    successor = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="5.1.2",
                title="Account Deletion In App",
                version_label="2026.09",
                effective_from=DEFAULT_CLOCK,
                supersedes_rule_id=ctx.rules["privacy"],
            ),
            ctx.policy_admin,
        )
    )
    published = validate_success(
        api.publish_guideline_rule(successor["id"], ctx.policy_admin), 200
    )
    return successor["id"], published


def _setup_live_app_awaiting_a_rulebook_change(api):
    """A PASSED mapping, an APPROVED build and a started PHASED plan, so the app is
    distributing at 1.00 / 99.00 when the successor rule is published."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api)
    assert ctx.app()["distribution_state"] == "PHASED_ROLLOUT"
    return ctx


def test_publication_repoints_the_mapping_and_stales_the_attestation(api):
    """"First, every feature mapping that pointed at the superseded rule is re-pointed at
    the new rule, and each such mapping whose `self_review_status` was `PASSED` or
    `WAIVED_BY_PLATFORM` is moved to `STALE` with `staled_by_rule_id` set to the new
    rule's identifier — prior attestations do not survive a rulebook change."

    Design: Corner/cross_cutting_complexity_layers/the_guideline_publication_cascade_runs_all_four_hops_on_a_live_app_in_one_request
    """
    ctx = _setup_live_app_awaiting_a_rulebook_change(api)
    successor_id, published = _publish_privacy_successor(api, ctx)

    assert published["status"] == "EFFECTIVE"
    assert published["impacted_app_count"] == 1
    predecessor = get_success_data(
        api.get_guideline_rule(ctx.rules["privacy"], ctx.policy_admin)
    )
    assert predecessor["status"] == "SUPERSEDED"

    mapping = ctx.mapping(ctx.mappings["privacy"])
    assert mapping["guideline_rule_id"] == successor_id
    assert mapping["self_review_status"] == "STALE"
    assert mapping["staled_by_rule_id"] == successor_id


def test_publication_opens_one_assessment_scored_against_the_live_exposure(api):
    """"`impact_severity` is the rule's `severity_weight` multiplied by the count of
    entries in `affected_feature_codes` multiplied by `exposure_factor`, with the single
    product rounded half up to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/the_guideline_publication_cascade_runs_all_four_hops_on_a_live_app_in_one_request
    """
    ctx = _setup_live_app_awaiting_a_rulebook_change(api)
    _publish_privacy_successor(api, ctx)

    rows, meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, {"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 1
    assessment = rows[0]
    assert assessment["status"] == "OPEN"
    assert_decimal_equals(assessment["exposure_factor"], 1.5, 2, "exposure_factor")
    assert_decimal_equals(assessment["impact_severity"], 6.00, 2, "impact_severity")
    assert assessment["remediation_deadline_at"] == "2026-08-31T00:00:00Z"


def test_publication_halves_the_index_and_restricts_the_posture(api):
    """"Third — caused by the second — each affected app's `feature_compliance_index` is
    recomputed with the now-stale mappings contributing at half weight, and its posture
    is recomputed, which yields `RESTRICTED` through the `OPEN_IMPACT_ASSESSMENT` reason
    and, where the index has fallen below the floor, `COMPLIANCE_INDEX_BELOW_FLOOR` as
    well."

    Design: Corner/cross_cutting_complexity_layers/the_guideline_publication_cascade_runs_all_four_hops_on_a_live_app_in_one_request
    """
    ctx = _setup_live_app_awaiting_a_rulebook_change(api)
    _publish_privacy_successor(api, ctx)

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 50.00, 2, "index")
    assert_posture(
        app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"]
    )


def test_publication_pauses_the_live_plan_and_freezes_the_two_shares(api):
    """"Fourth — caused by the third — every rollout plan of those apps that is
    `PHASE_ACTIVE` moves to `PAUSED` with `pause_reason_code` set to `POSTURE_DEGRADED`,
    driving `distribution_state` to `PAUSED` with both share fields frozen."

    Design: Corner/cross_cutting_complexity_layers/the_guideline_publication_cascade_runs_all_four_hops_on_a_live_app_in_one_request
    """
    ctx = _setup_live_app_awaiting_a_rulebook_change(api)
    _publish_privacy_successor(api, ctx)

    plan = ctx.plan()
    assert plan["state"] == "PAUSED"
    assert plan["pause_reason_code"] == "POSTURE_DEGRADED"
    assert_decimal_equals(plan["released_share_pct"], 1.00, 2, "released_share_pct")
    assert_decimal_equals(plan["held_back_share_pct"], 99.00, 2, "held_back_share_pct")
    assert_share_conservation(plan)
    assert plan["phase_index"] == 0
    assert plan["phase_entered_at"] == DEFAULT_CLOCK

    app = ctx.app()
    assert app["distribution_state"] == "PAUSED"
    assert_share_conservation(app)
    assert ctx.submission()["state"] == "APPROVED", "the cascade never touches the build"


# ---------------------------------------------------------------------------
# the_reject_decision_cascade_pauses_a_live_rollout_through_the_index_it_just_destroyed
# ---------------------------------------------------------------------------
def _setup_second_build_in_review_over_a_live_rollout(api):
    """Build 100 APPROVED and distributing, build 101 claimed and IN_REVIEW."""
    ctx = _setup_live_app_awaiting_a_rulebook_change(api)
    first_submission_id = ctx.submission_id
    add_submission(ctx, build_number=101, version_string="1.0.1")
    complete_content(ctx)
    run_pre_review(ctx)
    queue(ctx)
    claim(ctx)
    return ctx, first_submission_id


def test_reject_records_one_pending_reason_row_per_entry(api):
    """"One rejection reason row is created per entry, each carrying its
    `submission_id`, `guideline_rule_id`, `reason_code`, `severity` of `CRITICAL`,
    `MAJOR` or `MINOR`, and reviewer `detail`, with `recorded_at` set to the current
    instant, `recorded_by_user_id` set to the deciding reviewer, `developer_response`
    null and both `disposition` and `appeal_disposition` at `PENDING`."

    Design: Corner/cross_cutting_complexity_layers/the_reject_decision_cascade_pauses_a_live_rollout_through_the_index_it_just_destroyed
    """
    ctx, _first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    decided = validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(ctx.rules["privacy"]),
            },
            ctx.reviewer,
        ),
        200,
    )
    assert decided["state"] == "REJECTED"
    assert decided["rejected_at"] == DEFAULT_CLOCK

    rows, meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.release_manager, {"submission_id": ctx.submission_id}
        )
    )
    assert meta["total_count"] == 1
    reason = rows[0]
    assert reason["severity"] == "CRITICAL"
    assert reason["disposition"] == "PENDING"
    assert reason["appeal_disposition"] == "PENDING"
    assert reason["developer_response"] is None
    assert reason["recorded_at"] == DEFAULT_CLOCK


def test_reject_runs_all_four_hops_down_to_the_paused_distribution(api):
    """"Then a four-hop cascade runs: every feature mapping of the app whose
    `guideline_rule_id` is cited by a `CRITICAL` or `MAJOR` reason moves
    `PASSED → FAILED`; the app's `feature_compliance_index` is recomputed from those
    changed statuses and, when it falls below the posture floor, the posture becomes
    `RESTRICTED`; every rollout plan of the app in `PHASE_ACTIVE` moves to `PAUSED` with
    `pause_reason_code` set to `POSTURE_DEGRADED`; and the app's `distribution_state`
    goes `PHASED_ROLLOUT → PAUSED` with `released_share_pct` and `held_back_share_pct`
    held at their pre-pause values."

    Design: Corner/cross_cutting_complexity_layers/the_reject_decision_cascade_pauses_a_live_rollout_through_the_index_it_just_destroyed
    """
    ctx, _first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(ctx.rules["privacy"]),
            },
            ctx.reviewer,
        ),
        200,
    )

    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "FAILED"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 0.00, 2, "index")
    assert_posture(app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])
    assert app["distribution_state"] == "PAUSED"

    plan = ctx.plan()
    assert plan["state"] == "PAUSED"
    assert plan["pause_reason_code"] == "POSTURE_DEGRADED"
    assert_decimal_equals(plan["released_share_pct"], 1.00, 2, "released_share_pct")
    assert_decimal_equals(plan["held_back_share_pct"], 99.00, 2, "held_back_share_pct")


def test_reject_consumes_the_second_slot_and_leaves_the_live_build_alone(api):
    """"`slots_consumed` is the count whose `state` is `APPROVED`, `REJECTED`,
    `METADATA_REJECTED`, `APPEAL_PENDING`, `REJECTED_FINAL` or `SUPERSEDED`."

    Design: Corner/cross_cutting_complexity_layers/the_reject_decision_cascade_pauses_a_live_rollout_through_the_index_it_just_destroyed
    """
    ctx, first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(ctx.rules["privacy"]),
            },
            ctx.reviewer,
        ),
        200,
    )

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 2
    assert window["slots_available"] == 3
    assert_slot_conservation(window)

    assert ctx.submission(first_id)["state"] == "APPROVED"
    assert ctx.app()["live_submission_id"] == first_id


def test_reject_charges_the_critical_penalty_to_both_standing_variants(api):
    """"Each carries weight 12 if `CRITICAL`, 6 if `MAJOR` and 2 if `MINOR`, multiplied
    by a decay factor."

    Design: Corner/cross_cutting_complexity_layers/the_reject_decision_cascade_pauses_a_live_rollout_through_the_index_it_just_destroyed
    """
    ctx, _first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(ctx.rules["privacy"]),
            },
            ctx.reviewer,
        ),
        200,
    )

    standing = validate_success(
        api.get_standing(ctx.account_id, ctx.publisher_admin), 200
    )
    assert_decimal_equals(standing["standing_score_rolling_365"], 88.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 88.00, 2, "lifetime")
    assert standing["rejection_strike_count"] == 1


# ---------------------------------------------------------------------------
# reporting_a_compromised_certificate_revokes_its_profile_blocks_the_build_and_pauses_the_rollout
# ---------------------------------------------------------------------------
def _report_certificate_compromise(api, ctx):
    return validate_success(
        api.report_credential_compromise(
            ctx.cert_id, {"reason_code": "PRIVATE_KEY_LEAKED"}, ctx.publisher_admin
        ),
        200,
    )


def test_report_compromise_cascades_onto_the_linked_profile(api):
    """"First, every credential whose `linked_cert_id` points at the compromised one and
    whose own status is `PENDING_ACTIVATION`, `ACTIVE` or `EXPIRING_SOON` moves to
    `REVOKED` with `revocation_reason` set to `COMPROMISE_CASCADE`."

    Design: Corner/cross_cutting_complexity_layers/reporting_a_compromised_certificate_revokes_its_profile_blocks_the_build_and_pauses_the_rollout
    """
    ctx, _first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    reported = _report_certificate_compromise(api, ctx)
    assert reported["status"] == "COMPROMISED"
    assert reported["compromised_at"] == DEFAULT_CLOCK

    profile = get_success_data(
        api.get_signing_credential(ctx.profile_id, ctx.publisher_admin)
    )
    assert profile["status"] == "REVOKED"
    assert profile["revocation_reason"] == "COMPROMISE_CASCADE"


def test_report_compromise_blocks_the_in_review_build_and_hands_the_slot_back(api):
    """"Second — caused by the first — every submission signed with one of those newly
    revoked profiles that is sitting in `WAITING_FOR_REVIEW` or `IN_REVIEW` moves to
    `BLOCKED_INVALID_SIGNING`, has its `review_window_id` cleared (which decrements that
    window's `slots_reserved` by one and increments its `slots_available` by one), and
    increments the revoked credential's `blocked_submission_count`."

    Design: Corner/cross_cutting_complexity_layers/reporting_a_compromised_certificate_revokes_its_profile_blocks_the_build_and_pauses_the_rollout
    """
    ctx, first_id = _setup_second_build_in_review_over_a_live_rollout(api)
    before = ctx.window()
    assert (before["slots_reserved"], before["slots_consumed"]) == (1, 1)

    _report_certificate_compromise(api, ctx)

    blocked = ctx.submission()
    assert blocked["state"] == "BLOCKED_INVALID_SIGNING"
    assert blocked["review_window_id"] is None
    profile = get_success_data(
        api.get_signing_credential(ctx.profile_id, ctx.publisher_admin)
    )
    assert profile["blocked_submission_count"] == 1

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4
    assert_slot_conservation(window)
    assert ctx.submission(first_id)["state"] == "APPROVED"


def test_report_compromise_restricts_the_posture_with_a_perfect_index(api):
    """"Third — caused by the second — the compliance posture of each affected app record
    is recomputed, and with no active distribution certificate left it becomes
    `RESTRICTED`."

    Design: Corner/cross_cutting_complexity_layers/reporting_a_compromised_certificate_revokes_its_profile_blocks_the_build_and_pauses_the_rollout
    """
    ctx, _first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    _report_certificate_compromise(api, ctx)

    app = ctx.app()
    assert_posture(app, "RESTRICTED", ["NO_ACTIVE_DISTRIBUTION_CERT"])
    assert_decimal_equals(app["feature_compliance_index"], 100.00, 2, "index")


def test_report_compromise_pauses_the_live_rollout_despite_the_two_exemptions(api):
    """"Fourth — caused by the third — every rollout plan of those apps sitting in
    `PHASE_ACTIVE` moves to `PAUSED` with `pause_reason_code` set to `POSTURE_DEGRADED`,
    which in turn drives each app's `distribution_state` from `PHASED_ROLLOUT` to
    `PAUSED`."

    Design: Corner/cross_cutting_complexity_layers/reporting_a_compromised_certificate_revokes_its_profile_blocks_the_build_and_pauses_the_rollout
    """
    ctx, _first_id = _setup_second_build_in_review_over_a_live_rollout(api)

    _report_certificate_compromise(api, ctx)

    plan = ctx.plan()
    assert plan["state"] == "PAUSED"
    assert plan["pause_reason_code"] == "POSTURE_DEGRADED"
    assert ctx.app()["distribution_state"] == "PAUSED"
    assert_share_conservation(plan)


# ---------------------------------------------------------------------------
# all_four_disclosure_divergence_causes_stack_into_a_single_provisional_versus_final_gap
# ---------------------------------------------------------------------------
def _file_finding(api, ctx, **overrides):
    return get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(ctx.submission_id, **overrides),
            ctx.policy_admin,
        )
    )


def _setup_four_divergence_causes(api):
    """One declared tuple no finding matches, plus one in-window MINOR, one
    below-floor MAJOR and one DISPUTED MAJOR, then the pre-review check."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        declared_privacy_items=[
            privacy_item("DEVICE_ID", "ADVERTISING", linked=True, tracking=True)
        ],
        tracking_consent_prompt_present=True,
        with_pre_review=False,
    )
    _file_finding(
        api,
        ctx,
        data_type="PRECISE_LOCATION",
        observed_purpose="ANALYTICS",
        severity="MINOR",
        scanner_confidence=0.95,
    )
    low_confidence = _file_finding(
        api,
        ctx,
        data_type="CONTACTS",
        severity="MAJOR",
        scanner_confidence=0.7999,
    )
    disputed = _file_finding(
        api,
        ctx,
        data_type="USAGE_DATA",
        observed_purpose="ANALYTICS",
        observed_tracking=False,
        severity="MAJOR",
        scanner_confidence=0.99,
    )
    get_success_data(
        api.triage_behavior_finding(
            disputed["id"],
            {
                "action": "DISPUTE",
                "justification": (
                    "Usage telemetry is aggregated on device and never leaves it."
                ),
            },
            ctx.compliance_officer,
        )
    )
    run_pre_review(ctx)
    return ctx, low_confidence["id"], disputed["id"]


def _file_late_finding(api, ctx):
    set_clock(api, "2026-08-01T06:00:00Z")
    return _file_finding(
        api,
        ctx,
        data_type="HEALTH",
        observed_purpose="ANALYTICS",
        observed_tracking=False,
        severity="MINOR",
        scanner_confidence=0.99,
        detected_at="2026-08-01T06:00:00Z",
    )


def test_provisional_charges_only_the_one_in_window_minor_finding(api):
    """"Each unmatched finding in scope contributes an integer penalty of 40 if
    `CRITICAL`, 20 if `MAJOR` and 5 if `MINOR`."

    Design: Corner/cross_cutting_complexity_layers/all_four_disclosure_divergence_causes_stack_into_a_single_provisional_versus_final_gap
    """
    ctx, _low_id, _disputed_id = _setup_four_divergence_causes(api)

    submission = ctx.submission()
    assert submission["pre_review_checked_at"] == DEFAULT_CLOCK
    assert submission["pre_review_passed"] is True
    assert_decimal_equals(
        submission["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )


def test_the_late_finding_stays_outside_the_provisional_window_at_queue_entry(api):
    """"The provisional variant, `disclosure_accuracy_score_provisional`, counts only
    findings whose `status` is `OPEN`, whose `detected_at` is at or before the
    submission's `pre_review_checked_at`, and whose `scanner_confidence` is at or above
    0.8000; it does **not** apply the over-disclosure term, because declaring more than
    was observed costs a publisher nothing at self-review time."

    Design: Corner/cross_cutting_complexity_layers/all_four_disclosure_divergence_causes_stack_into_a_single_provisional_versus_final_gap
    """
    ctx, _low_id, _disputed_id = _setup_four_divergence_causes(api)
    _file_late_finding(api, ctx)

    assert_decimal_equals(
        ctx.submission()["disclosure_accuracy_score_provisional"],
        0.9500,
        4,
        "provisional",
    )
    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"


def test_the_claim_sums_all_four_causes_into_the_final_score(api):
    """"Start from 100, subtract the total undisclosed penalty, subtract the
    over-disclosure term where the variant applies it, floor the result at 0, then divide
    by 100 and round half up to four decimal places."

    Design: Corner/cross_cutting_complexity_layers/all_four_disclosure_divergence_causes_stack_into_a_single_provisional_versus_final_gap
    """
    ctx, _low_id, _disputed_id = _setup_four_divergence_causes(api)
    _file_late_finding(api, ctx)
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)

    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 0.4800, 4, "final"
    )


def test_the_two_variants_disagree_by_exactly_the_stacked_gap(api):
    """"For identical stored data the two therefore return different numbers whenever a
    finding arrived after the pre-review instant, was disputed, scored below the
    confidence floor, or the publisher over-declared a data type."

    Design: Corner/cross_cutting_complexity_layers/all_four_disclosure_divergence_causes_stack_into_a_single_provisional_versus_final_gap
    """
    ctx, _low_id, disputed_id = _setup_four_divergence_causes(api)
    _file_late_finding(api, ctx)
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    submission = ctx.submission()
    gap = num(submission["disclosure_accuracy_score_provisional"]) - num(
        submission["disclosure_accuracy_score_final"]
    )
    assert_decimal_equals(
        submission["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )
    assert_decimal_equals(gap, 0.4700, 4, "provisional minus final")

    validate_error(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        ApiErrorId.ERR_PRIVACY_DISCLOSURE_INACCURATE,
        409,
    )
    assert ctx.submission()["state"] == "IN_REVIEW"
    finding = get_success_data(api.get_behavior_finding(disputed_id, ctx.policy_admin))
    assert finding["status"] == "DISPUTED"


# ---------------------------------------------------------------------------
# the_same_critical_rejection_decays_in_the_rolling_variant_and_never_in_the_lifetime_variant
# ---------------------------------------------------------------------------
def _setup_one_critical_rejection(api):
    """One CRITICAL rejection reason recorded at the default clock instant."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api)
    reject(ctx, rejection_reasons_for(ctx.rules["privacy"]))
    return ctx


def test_the_rolling_variant_steps_down_the_penalty_at_each_decay_band(api):
    """"`standing_score_rolling_365` counts only rows dated at or after 365 days before
    the current instant, with the lower bound inclusive, and decays each penalty by 1.0
    when it is at most 90 days old, 0.5 when older than 90 but at most 180 days, and 0.25
    when older than 180 days, where age is the whole number of complete days since
    `recorded_at`."

    Design: Corner/cross_cutting_complexity_layers/the_same_critical_rejection_decays_in_the_rolling_variant_and_never_in_the_lifetime_variant
    """
    ctx = _setup_one_critical_rejection(api)

    expected = {
        DEFAULT_CLOCK: 88.00,
        "2026-12-01T00:00:00Z": 94.00,
        "2027-03-01T00:00:00Z": 97.00,
        "2027-08-02T00:00:00Z": 100.00,
    }
    for instant, rolling in expected.items():
        set_clock(api, instant)
        standing = validate_success(
            api.get_standing(ctx.account_id, ctx.publisher_admin), 200
        )
        assert_decimal_equals(
            standing["standing_score_rolling_365"], rolling, 2, f"rolling at {instant}"
        )


def test_the_lifetime_variant_never_moves_and_the_strike_row_survives(api):
    """"`standing_score_lifetime` has no window at all — every row of the account's
    history counts — and applies no decay whatsoever."

    Design: Corner/cross_cutting_complexity_layers/the_same_critical_rejection_decays_in_the_rolling_variant_and_never_in_the_lifetime_variant
    """
    ctx = _setup_one_critical_rejection(api)

    # `rejection_strike_count` "counts the account's rejection reasons of severity `CRITICAL`
    # whose recording instant falls inside the rolling 365-day window", so unlike the lifetime
    # score it does drop away once the row ages out of that window.
    expected_strikes = {
        DEFAULT_CLOCK: 1,
        "2026-12-01T00:00:00Z": 1,
        "2027-03-01T00:00:00Z": 1,
        "2027-08-02T00:00:00Z": 0,
    }
    for instant, strikes in expected_strikes.items():
        set_clock(api, instant)
        account = ctx.account()
        assert_decimal_equals(
            account["standing_score_lifetime"], 88.00, 2, f"lifetime at {instant}"
        )
        assert account["rejection_strike_count"] == strikes

    _rows, meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.release_manager, {"submission_id": ctx.submission_id}
        )
    )
    assert meta["total_count"] == 1, "no clock sweep may delete a recorded reason"


# ---------------------------------------------------------------------------
# the_window_selector_ranks_by_free_slots_before_creation_order
# ---------------------------------------------------------------------------
def _setup_build_ready_to_queue(api):
    """A build in PRE_REVIEW_PASSED plus the default POOL_A window of 5 free slots."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    assert ctx.submission()["state"] == "PRE_REVIEW_PASSED"
    return ctx


def _open_window(api, ctx, pool_code, capacity, starts_at):
    return validate_success(
        api.create_review_capacity_window(
            create_review_capacity_window_payload(
                reviewer_pool_code=pool_code,
                capacity_slots=capacity,
                starts_at=starts_at,
                ends_at="2026-09-01T00:00:00Z",
            ),
            ctx.policy_admin,
        ),
        201,
    )


def test_the_roomier_later_created_window_wins_the_reservation(api):
    """"Among the eligible, rank by `slots_available` descending, then by `starts_at`
    ascending, and break any remaining tie by `created_at` ascending; never by `id`."

    Design: Corner/cross_cutting_complexity_layers/the_window_selector_ranks_by_free_slots_before_creation_order
    """
    ctx = _setup_build_ready_to_queue(api)
    pool_b = _open_window(api, ctx, "POOL_B", 6, DEFAULT_CLOCK)
    assert pool_b["slots_available"] == 6

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["review_window_id"] == pool_b["id"]

    chosen = ctx.window(pool_b["id"])
    assert (chosen["slots_reserved"], chosen["slots_consumed"]) == (1, 0)
    assert chosen["slots_available"] == 5
    assert_slot_conservation(chosen)

    untouched = ctx.window()
    assert untouched["slots_reserved"] == 0
    assert untouched["slots_available"] == 5


# ---------------------------------------------------------------------------
# a_tie_on_free_slots_is_broken_by_the_earlier_starts_at_not_by_creation_order
# ---------------------------------------------------------------------------
def test_a_slot_tie_is_broken_by_the_earlier_interval_start(api):
    """"Eligible windows are those whose `status` is `OPEN`, whose `platform` equals the
    app's `platform`, whose half-open interval contains the current instant — `starts_at`
    at or before it and `ends_at` strictly after it — and whose `slots_available` is at
    least 1."

    Design: Corner/cross_cutting_complexity_layers/a_tie_on_free_slots_is_broken_by_the_earlier_starts_at_not_by_creation_order
    """
    ctx = _setup_build_ready_to_queue(api)
    pool_c = _open_window(api, ctx, "POOL_C", 5, "2026-07-15T00:00:00Z")
    assert pool_c["slots_available"] == 5

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["review_window_id"] == pool_c["id"]

    chosen = ctx.window(pool_c["id"])
    assert chosen["slots_reserved"] == 1
    assert chosen["slots_available"] == 4

    untouched = ctx.window()
    assert untouched["slots_reserved"] == 0
    assert untouched["slots_available"] == 5
