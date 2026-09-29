"""Corner section: errors.

Codes that are only reachable through one very specific arrangement of the ladder.
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    assert_decimal_equals,
    assert_posture,
    create_feature_mapping_payload,
    create_guideline_rule_payload,
    create_signing_credential_payload,
    make_auditor_headers,
    new_account,
    set_clock,
    setup_approved_ios,
    setup_base_ios,
    validate_error,
    validate_success,
    get_success_data,
)

GHOST_ID = "00000000-0000-4000-8000-000000000404"


def test_every_by_id_read_names_its_own_entity_in_the_not_found_code(api):
    """"Existence yields a 404 whose code names the resource type that failed to resolve, drawn
    from a family of fifteen: `ERR_PUBLISHER_ACCOUNT_NOT_FOUND`, `ERR_SIGNING_CREDENTIAL_NOT_FOUND`,
    `ERR_APP_RECORD_NOT_FOUND`, `ERR_GUIDELINE_RULE_NOT_FOUND`, `ERR_FEATURE_MAPPING_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND`, `ERR_METADATA_LOCALE_NOT_FOUND`, `ERR_BEHAVIOR_FINDING_NOT_FOUND`,
    `ERR_REJECTION_REASON_NOT_FOUND`, `ERR_APPEAL_REQUEST_NOT_FOUND`,
    `ERR_EXPEDITE_REQUEST_NOT_FOUND`, `ERR_REVIEW_CAPACITY_WINDOW_NOT_FOUND`,
    `ERR_ROLLOUT_PLAN_NOT_FOUND`, `ERR_COMMERCE_ITEM_NOT_FOUND` and
    `ERR_IMPACT_ASSESSMENT_NOT_FOUND`."

    Design: Corner/errors/every_remaining_not_found_code_answers_the_same_unresolvable_uuid
    """
    set_clock(api, DEFAULT_CLOCK)
    new_account(api)
    auditor = make_auditor_headers()

    cases = [
        (api.get_publisher_account, ApiErrorId.ERR_PUBLISHER_ACCOUNT_NOT_FOUND),
        (api.get_signing_credential, ApiErrorId.ERR_SIGNING_CREDENTIAL_NOT_FOUND),
        (api.get_feature_mapping, ApiErrorId.ERR_FEATURE_MAPPING_NOT_FOUND),
        (api.get_metadata_locale, ApiErrorId.ERR_METADATA_LOCALE_NOT_FOUND),
        (api.get_behavior_finding, ApiErrorId.ERR_BEHAVIOR_FINDING_NOT_FOUND),
        (api.get_rejection_reason, ApiErrorId.ERR_REJECTION_REASON_NOT_FOUND),
        (api.get_appeal_request, ApiErrorId.ERR_APPEAL_REQUEST_NOT_FOUND),
        (api.get_expedite_request, ApiErrorId.ERR_EXPEDITE_REQUEST_NOT_FOUND),
        (
            api.get_review_capacity_window,
            ApiErrorId.ERR_REVIEW_CAPACITY_WINDOW_NOT_FOUND,
        ),
        (api.get_rollout_plan, ApiErrorId.ERR_ROLLOUT_PLAN_NOT_FOUND),
        (api.get_commerce_item, ApiErrorId.ERR_COMMERCE_ITEM_NOT_FOUND),
        (api.get_impact_assessment, ApiErrorId.ERR_IMPACT_ASSESSMENT_NOT_FOUND),
    ]
    for reader, expected in cases:
        validate_error(reader(GHOST_ID, auditor), expected, 404)


def test_expired_membership_blocks_a_mapping_the_posture_gate_cannot_reach(api):
    """"When it is `EXPIRED`, the affected operations are rejected with
    `ERR_PROGRAM_MEMBERSHIP_EXPIRED` and HTTP 403; when it is `SUSPENDED` or `TERMINATED`, they
    are rejected with `ERR_ACCOUNT_SUSPENDED` and HTTP 403."

    Design: Corner/errors/an_expired_membership_blocks_mapping_creation_where_the_posture_gate_cannot_reach
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance=None,
        with_submission=False,
        with_window=False,
    )

    swept = validate_success(
        api.set_clock_raw({"current_utc": "2027-08-01T00:00:01Z"}, ctx.policy_admin),
        200,
    )
    assert swept["accounts_expired_count"] == 1
    assert swept["credentials_expired_count"] == 2
    assert ctx.account()["program_status"] == "EXPIRED"

    validate_error(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id, ctx.rules["privacy"], feature_code="DATA_EXPORT"
            ),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_PROGRAM_MEMBERSHIP_EXPIRED,
        403,
    )

    assert_posture(
        ctx.app(),
        "RESTRICTED",
        [
            "MEMBERSHIP_EXPIRED",
            "NO_ACTIVE_DISTRIBUTION_CERT",
            "COMPLIANCE_INDEX_BELOW_FLOOR",
        ],
    )


def test_a_profile_linked_across_platforms_is_a_platform_mismatch(api):
    """"A provisioning profile requires a non-null `linked_cert_id` pointing at a distribution
    certificate of the same account and the same platform; a missing `linked_cert_id` on a profile
    is a schema violation, while a profile whose platform differs from that of its linked
    certificate is `ERR_CREDENTIAL_PLATFORM_MISMATCH`."

    Design: Corner/errors/a_provisioning_profile_linked_to_a_cross_platform_certificate_is_refused
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)

    cert = validate_success(
        api.create_signing_credential(
            create_signing_credential_payload(
                ctx.account_id, ctx.account_version(), platform="ANDROID"
            ),
            ctx.publisher_admin,
        ),
        201,
    )
    activated = validate_success(
        api.activate_signing_credential(cert["id"], ctx.publisher_admin), 200
    )
    assert activated["status"] == "ACTIVE"

    validate_error(
        api.create_signing_credential(
            create_signing_credential_payload(
                ctx.account_id,
                ctx.account_version(),
                credential_type="PROVISIONING_PROFILE",
                platform="IOS",
                key_custody="CLOUD_MANAGED",
                linked_cert_id=cert["id"],
            ),
            ctx.publisher_admin,
        ),
        ApiErrorId.ERR_CREDENTIAL_PLATFORM_MISMATCH,
        409,
    )


def test_publishing_a_rule_that_supersedes_a_draft_is_refused(api):
    """"Publishing is the single most consequential operation in the system. A
    `PlatformPolicyAdmin` moves a rule `DRAFT → EFFECTIVE`, which requires that `effective_from`
    is at or before the current logical instant — a rule may not be published into the future, and
    attempting it is `ERR_RULE_NOT_YET_EFFECTIVE` — and, when `supersedes_rule_id` is set, that the
    superseded rule is itself currently `EFFECTIVE`, otherwise `ERR_GUIDELINE_RULE_NOT_EFFECTIVE`."

    Design: Corner/errors/publishing_a_rule_that_supersedes_an_unpublished_draft_is_refused
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    first = get_success_data(
        api.create_guideline_rule(create_guideline_rule_payload(), ctx.policy_admin)
    )
    successor = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                version_label="2026.09",
                effective_from=DEFAULT_CLOCK,
                supersedes_rule_id=first["id"],
            ),
            ctx.policy_admin,
        )
    )

    validate_error(
        api.publish_guideline_rule(successor["id"], ctx.policy_admin),
        ApiErrorId.ERR_GUIDELINE_RULE_NOT_EFFECTIVE,
        409,
    )
    assert get_success_data(
        api.get_guideline_rule(successor["id"], ctx.policy_admin)
    )["status"] == "DRAFT"

    validate_success(api.publish_guideline_rule(first["id"], ctx.policy_admin), 200)
    published = validate_success(
        api.publish_guideline_rule(successor["id"], ctx.policy_admin), 200
    )
    assert published["status"] == "EFFECTIVE"
    assert published["impacted_app_count"] == 0
    assert get_success_data(
        api.get_guideline_rule(first["id"], ctx.policy_admin)
    )["status"] == "SUPERSEDED"


def test_a_skipped_phase_outranks_the_dwell_that_has_not_elapsed(api):
    """"A `ReleaseManager` advances by supplying `to_phase_index`, which must equal the current
    `phase_index` plus exactly one and must not exceed 6 — phases may neither be skipped nor
    repeated, and a violation is `ERR_PHASE_SEQUENCE_INVALID`."

    Design: Corner/errors/skipping_a_phase_outranks_the_dwell_that_has_not_elapsed
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api)
    plan = get_success_data(
        api.create_rollout_plan(
            {
                "expected_app_record_version": ctx.app_version(),
                "app_record_id": ctx.app_record_id,
                "submission_id": ctx.submission_id,
                "mode": "PHASED",
                "scheduled_start_at": DEFAULT_CLOCK,
            },
            ctx.release_manager,
        )
    )
    started = get_success_data(
        api.start_rollout_plan(plan["id"], ctx.release_manager)
    )
    assert started["phase_index"] == 0

    for to_phase_index in (2, 7, 0):
        validate_error(
            api.advance_rollout_plan(
                plan["id"], {"to_phase_index": to_phase_index}, ctx.release_manager
            ),
            ApiErrorId.ERR_PHASE_SEQUENCE_INVALID,
            409,
        )

    unchanged = get_success_data(api.get_rollout_plan(plan["id"], ctx.release_manager))
    assert unchanged["phase_index"] == 0
    assert unchanged["phase_entered_at"] == DEFAULT_CLOCK
    assert_decimal_equals(ctx.app()["released_share_pct"], 1.00, 2, "released")


def test_four_critical_reasons_drop_the_account_below_the_expedite_floor(api):
    """"The score is 100 minus the total penalty plus the total credit, rounded half up to two
    decimals once at the very end and clamped to 0.00 through 100.00; the sums themselves are
    computed unrounded."

    Design: Corner/errors/four_critical_reasons_in_one_rejection_drop_the_account_below_the_expedite_floor
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))

    reasons = [
        ("PRIVACY_LABEL_MISMATCH", "Undisclosed device identifier collection."),
        ("PRIVACY_PURPOSE_MISMATCH", "Analytics purpose undeclared."),
        ("PRIVACY_TRACKING_UNDECLARED", "Cross-app tracking undeclared."),
        ("PRIVACY_DELETION_FLOW_MISSING", "No in-app deletion path."),
    ]
    rejected = validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": [
                    {
                        "guideline_rule_id": ctx.rules["privacy"],
                        "reason_code": code,
                        "severity": "CRITICAL",
                        "detail": detail,
                    }
                    for code, detail in reasons
                ],
            },
            ctx.reviewer,
        ),
        200,
    )
    assert rejected["state"] == "REJECTED"

    standing = ctx.standing()
    assert standing["rejection_strike_count"] == 4
    assert_decimal_equals(standing["decayed_penalty_total"], 48.00, 2, "penalty total")
    assert_decimal_equals(
        standing["standing_score_rolling_365"], 52.00, 2, "rolling standing"
    )
    assert_decimal_equals(
        standing["standing_score_lifetime"], 52.00, 2, "lifetime standing"
    )

    # The reject cascade failed the cited mapping, which drove the index to 0.00 and the
    # posture to `RESTRICTED`; creating an expedite request is one of the restricted-blocked
    # operations, so the publisher re-attests first to leave standing as the only obstacle.
    get_success_data(
        api.self_review_mapping(
            ctx.mappings["privacy"], {"outcome": "PASS"}, ctx.compliance_officer
        )
    )
    assert ctx.app()["compliance_posture"] == "OPEN"

    rebuilt = get_success_data(
        api.create_submission(
            {
                "expected_app_record_version": ctx.app_version(),
                "app_record_id": ctx.app_record_id,
                "signing_credential_id": ctx.profile_id,
                "build_number": 101,
                "version_string": "4.2.1",
                "release_mode": "PHASED",
            },
            ctx.release_manager,
        )
    )
    validate_error(
        api.create_expedite_request(
            {
                "submission_id": rebuilt["id"],
                "justification_category": "CRITICAL_BUG",
                "justification": "Crash on launch for 30 percent of devices.",
            },
            ctx.release_manager,
        ),
        ApiErrorId.ERR_STANDING_TOO_LOW,
        409,
    )
    assert ctx.standing()["expedite_credits_remaining"] == 2
