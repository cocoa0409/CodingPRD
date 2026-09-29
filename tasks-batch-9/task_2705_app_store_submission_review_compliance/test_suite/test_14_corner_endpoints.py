"""Corner section: endpoints.

Computed reads, action endpoints, listings and the cascades a single call fans out.
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    add_effective_rule,
    assert_decimal_equals,
    assert_posture,
    create_behavior_finding_payload,
    create_expedite_request_payload,
    create_feature_mapping_payload,
    create_guideline_rule_payload,
    create_submission_payload,
    get_success_data,
    make_policy_admin_headers,
    reject,
    rejection_reasons_for,
    set_clock,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_ID = "00000000-0000-4000-8000-000000000404"


def _publish_successor(ctx):
    """Publish a 2026.09 PRIVACY rule superseding the app's only rule."""
    return add_effective_rule(
        ctx,
        key="privacy_v2",
        version_label="2026.09",
        effective_from=DEFAULT_CLOCK,
        supersedes_rule_id=ctx.rules["privacy"],
    )


def test_the_compliance_summary_explains_a_restricted_posture(api):
    """"An app's compliance position is also readable as a single explanation, which recomputes
    the index and the posture from current rows and returns `compliance_posture`, the ordered
    `posture_reason_codes`, the `feature_compliance_index`, and the blocking child counts
    `mapping_total`, `mapping_passed`, `mapping_stale`, `mapping_failed`, `open_impact_count`,
    `overdue_impact_count`, `critical_finding_open_count` and the boolean
    `active_distribution_cert_present`."

    Design: Corner/endpoints/the_compliance_summary_read_explains_a_restricted_posture_without_persisting_anything
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_submission=False, with_window=False)
    _publish_successor(ctx)

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.auditor), 200
    )
    assert_posture(
        summary, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"]
    )
    assert_decimal_equals(summary["feature_compliance_index"], 50.00, 2, "index")
    assert summary["mapping_total"] == 1
    assert summary["mapping_passed"] == 0
    assert summary["mapping_stale"] == 1
    assert summary["mapping_failed"] == 0
    assert summary["open_impact_count"] == 1
    assert summary["overdue_impact_count"] == 0
    assert summary["critical_finding_open_count"] == 0
    assert summary["active_distribution_cert_present"] is True


def test_the_standing_read_shows_both_variants_and_their_totals(api):
    """"Both standing scores are recomputed on every submission decision, every appeal decision,
    every rollout completion, every rollback and every clock advance, and they share one definition
    with two scopes."

    Design: Corner/endpoints/the_standing_read_exposes_both_variants_and_their_component_totals_side_by_side
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    reject(ctx, rejection_reasons_for(ctx.rules["privacy"]))

    standing = validate_success(api.get_standing(ctx.account_id, ctx.auditor), 200)
    assert_decimal_equals(standing["standing_score_rolling_365"], 88.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 88.00, 2, "lifetime")
    assert standing["rejection_strike_count"] == 1
    assert standing["penalty_event_count"] == 1
    assert_decimal_equals(standing["decayed_penalty_total"], 12.00, 2, "decayed")
    assert_decimal_equals(standing["undecayed_penalty_total"], 12.00, 2, "undecayed")
    assert_decimal_equals(standing["credit_total"], 0.00, 2, "credit")
    assert standing["expedite_credits_remaining"] == 2
    assert standing["credits_used_in_window"] == 0


def test_one_clock_move_reports_its_counters_and_freezes_the_posture(api):
    """"When the value is accepted, the server runs a sweep in this pinned order, and the order
    matters because each step feeds the next: (1) signing credentials move from `ACTIVE` to
    `EXPIRING_SOON` and onward to `EXPIRED`; (2) publisher accounts whose paid-through instant has
    passed move from `ACTIVE` to `EXPIRED`; (3) impact assessments that are past their remediation
    deadline move from `REMEDIATION_REQUIRED` to `OVERDUE`; (4) the compliance posture of every app
    record is recomputed; (5) rollout plans in `PHASE_ACTIVE` belonging to apps that have just
    become frozen are paused; (6) the standing-score and expedite-credit rolling windows are
    re-evaluated."

    Design: Corner/endpoints/the_clock_sweep_reports_its_six_counters_and_freezes_the_posture_in_one_call
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_submission=False, with_window=False)
    _publish_successor(ctx)
    rows, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assessment_id = rows[0]["id"]
    get_success_data(
        api.assess_impact(assessment_id, {"action": "START"}, ctx.compliance_officer)
    )
    required = get_success_data(
        api.assess_impact(
            assessment_id,
            {
                "action": "REQUIRE_REMEDIATION",
                "note": "The deletion flow must be reworked for the new wording.",
            },
            ctx.compliance_officer,
        )
    )
    assert required["status"] == "REMEDIATION_REQUIRED"
    assert required["remediation_deadline_at"] == "2026-08-31T00:00:00Z"

    swept = validate_success(
        api.set_clock_raw({"current_utc": "2026-08-31T00:00:01Z"}, ctx.policy_admin),
        200,
    )
    assert swept["current_utc"] == "2026-08-31T00:00:01Z"
    assert swept["credentials_warned_count"] == 0
    assert swept["credentials_expired_count"] == 0
    assert swept["accounts_expired_count"] == 0
    assert swept["assessments_overdue_count"] == 1
    assert swept["postures_frozen_count"] == 1
    assert swept["rollouts_paused_count"] == 0

    assert get_success_data(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer)
    )["status"] == "OVERDUE"
    assert_posture(ctx.app(), "FROZEN", ["IMPACT_OVERDUE"])


def test_a_non_monotonic_clock_move_leaves_the_clock_untouched(api):
    """"The clock is monotonic: a `current_utc` earlier than the currently stored value is
    rejected with `ERR_CLOCK_NOT_MONOTONIC` and HTTP 409."

    Design: Corner/endpoints/a_non_monotonic_clock_move_is_refused_and_leaves_the_clock_untouched
    """
    set_clock(api, DEFAULT_CLOCK)
    policy_admin = make_policy_admin_headers()

    forward = validate_success(
        api.set_clock_raw({"current_utc": "2026-08-02T00:00:00Z"}, policy_admin), 200
    )
    assert forward["current_utc"] == "2026-08-02T00:00:00Z"

    validate_error(
        api.set_clock_raw({"current_utc": "2026-08-01T23:59:59Z"}, policy_admin),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC,
        409,
    )

    again = validate_success(
        api.set_clock_raw({"current_utc": "2026-08-02T00:00:00Z"}, policy_admin), 200
    )
    assert again["current_utc"] == "2026-08-02T00:00:00Z", (
        "re-setting the identical instant is accepted and the clock has not moved back"
    )


def test_filtering_and_paging_the_guideline_list_partitions_the_rows(api):
    """"The `meta` object of a list response carries `limit` and `offset` echoing the effective
    values used, `total_count` giving the number of rows matching the filter before pagination was
    applied, and `has_more` indicating whether any row remains beyond the current page."

    Design: Corner/endpoints/filtering_and_paging_the_guideline_list_partitions_the_rows_without_overlap
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_submission=False, with_mapping=False, with_window=False
    )
    successor = _publish_successor(ctx)
    drafted = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                title="In-app purchase disclosure",
                category="COMMERCE",
                version_label="2026.3",
                effective_from="2026-07-01T00:00:00Z",
            ),
            ctx.policy_admin,
        )
    )

    first_rows, first_meta = validate_paginated(
        api.list_guideline_rules(ctx.auditor, params={"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_guideline_rules(ctx.auditor, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    first_ids = {row["id"] for row in first_rows}
    second_ids = {row["id"] for row in second_rows}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == {
        ctx.rules["privacy"],
        successor["id"],
        drafted["id"],
    }

    filtered_rows, filtered_meta = validate_paginated(
        api.list_guideline_rules(
            ctx.auditor, params={"status": "EFFECTIVE", "limit": 10, "offset": 0}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert [row["id"] for row in filtered_rows] == [successor["id"]]


def test_a_new_build_auto_withdraws_the_draft_and_frees_its_number(api):
    """"Withdrawn builds are excluded from that comparison precisely so a publisher who withdraws
    a mistaken build can reuse its number."

    Design: Corner/endpoints/a_new_build_auto_withdraws_the_draft_it_replaces_and_a_withdrawn_number_can_be_reused
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_content=False, with_window=False, with_pre_review=False,
        build_number=100, version_string="4.2.0",
    )
    first_id = ctx.submission_id

    second = validate_success(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                ctx.app_version(),
                build_number=101,
                version_string="4.2.1",
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert ctx.submission(first_id)["state"] == "DEVELOPER_WITHDRAWN"

    withdrawn = validate_success(
        api.withdraw_submission(second["id"], ctx.release_manager), 200
    )
    assert withdrawn["state"] == "DEVELOPER_WITHDRAWN"

    reused = validate_success(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                ctx.app_version(),
                build_number=101,
                version_string="4.2.1",
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert reused["build_number"] == 101
    assert reused["state"] == "DRAFT"


def test_a_mapping_needs_both_parents_and_is_unique_per_triple(api):
    """"The triple of `app_record_id`, `guideline_rule_id` and `feature_code` must be unique, and
    a repeat is rejected as `ERR_VALIDATION`."

    Design: Corner/endpoints/a_feature_mapping_needs_both_parents_and_is_unique_per_app_rule_and_feature_code
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, mapping_advance="START", with_submission=False, with_window=False
    )
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 25.00, 2, "index"
    )

    validate_error(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id, GHOST_ID, feature_code="DATA_EXPORT"
            ),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_GUIDELINE_RULE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id,
                ctx.rules["privacy"],
                feature_code="ACCOUNT_DELETION",
            ),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    second = validate_success(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id, ctx.rules["privacy"], feature_code="DATA_EXPORT"
            ),
            ctx.compliance_officer,
        ),
        201,
    )
    assert second["feature_code"] == "DATA_EXPORT"
    assert second["self_review_status"] == "NOT_STARTED"

    rows, meta = validate_paginated(
        api.list_feature_mappings(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 2 and len(rows) == 2
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 12.50, 2, "index")
    assert app["compliance_posture"] == "RESTRICTED"


def test_citing_a_granted_expedite_quarters_the_sla(api):
    """"When an `expedite_request_id` is supplied it must name a request whose `submission_id` is
    this submission and whose `state` is `GRANTED`, otherwise `ERR_INVALID_EXPEDITE_STATE`; on
    success that request moves to `CONSUMED` with `consumed_at` stamped and the submission's
    `submission_channel` becomes `EXPEDITED`."

    Design: Corner/endpoints/citing_a_granted_expedite_at_queue_entry_consumes_the_credit_and_quarters_the_sla
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )

    filed = validate_success(
        api.create_expedite_request(
            create_expedite_request_payload(
                ctx.submission_id,
                justification_category="SECURITY_FIX",
                justification="Patches a token leak reported by a researcher.",
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert filed["state"] == "REQUESTED"

    granted = validate_success(
        api.decide_expedite_request(
            filed["id"],
            {
                "outcome": "GRANT",
                "decision_rationale": "Security fix accepted for expedited handling.",
            },
            ctx.appeal_board,
        ),
        200,
    )
    assert granted["state"] == "GRANTED"
    assert ctx.account()["expedite_credits_remaining"] == 1

    queued = validate_success(
        api.queue_submission(
            ctx.submission_id, ctx.release_manager, {"expedite_request_id": filed["id"]}
        ),
        200,
    )
    assert queued["submission_channel"] == "EXPEDITED"
    assert queued["priority_band"] == "EXPEDITED"
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority_score")
    assert queued["provisional_deadline_at"] == "2026-08-03T00:00:00Z"
    assert queued["effective_review_deadline_at"] == "2026-08-01T12:00:00Z"

    consumed = get_success_data(api.get_expedite_request(filed["id"], ctx.auditor))
    assert consumed["state"] == "CONSUMED"
    assert consumed["consumed_at"] == DEFAULT_CLOCK
    assert ctx.standing()["credits_used_in_window"] == 1


def test_a_posture_degrading_publication_locks_the_resume_action(api):
    """"A restricted posture is narrower: it blocks only the release-advancing subset — queueing a
    submission, creating a rollout plan, starting a rollout, advancing a rollout phase, resuming a
    paused rollout, submitting a commerce item for commerce review, and creating an expedite
    request — with the code `ERR_APP_COMPLIANCE_RESTRICTED` and HTTP 409."

    Design: Corner/endpoints/a_posture_degrading_publication_pauses_the_rollout_and_locks_the_resume_action
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, mode="PHASED")
    _publish_successor(ctx)

    paused = ctx.plan()
    assert paused["state"] == "PAUSED"
    assert paused["pause_reason_code"] == "POSTURE_DEGRADED"
    app = ctx.app()
    assert app["distribution_state"] == "PAUSED"
    assert app["compliance_posture"] == "RESTRICTED"

    validate_error(
        api.hold_rollout_plan(
            ctx.plan_id, {"action": "RESUME"}, ctx.release_manager
        ),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )
    assert ctx.plan()["state"] == "PAUSED"


def test_filing_a_finding_rescores_the_provisional_and_leaves_the_final_null(api):
    """"Each unmatched finding in scope contributes an integer penalty of 40 if `CRITICAL`, 20 if
    `MAJOR` and 5 if `MINOR`."

    The final variant stays null here because the rewrite points are pinned: "The provisional
    score is rewritten by the self-review check and by any finding or declaration mutation; the
    final score is rewritten when a reviewer claims the build and again at the decision gate."
    This build has been queued but never claimed.

    Design: Corner/endpoints/filing_a_behavior_finding_rescores_both_disclosure_variants_in_the_same_request
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))

    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="USAGE_DATA",
                observed_purpose="ANALYTICS",
                observed_linked_to_user=False,
                observed_tracking=False,
                endpoint_domain="metrics.northwind.example",
                severity="MINOR",
                scanner_confidence=0.95,
                detected_at=DEFAULT_CLOCK,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    assert finding["status"] == "OPEN"

    reread = validate_success(
        api.get_submission(ctx.submission_id, ctx.auditor), 200
    )
    assert_decimal_equals(
        reread["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )
    assert reread["disclosure_accuracy_score_final"] is None
    assert_decimal_equals(reread["priority_score"], 50.00, 2, "priority_score")
    assert reread["priority_band"] == "NORMAL"
    assert reread["state"] == "WAITING_FOR_REVIEW"
