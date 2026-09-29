"""Corner section: validations.

The rejection ladder of §2.7 read one rung at a time: header shape before role,
role before tenancy, tenancy before existence, existence before schema, the parent
revision guard before the target's own state, and the posture and program-status
rungs before every business rule. Plus the temporal boundaries — 72-hour
attestation freshness, the 24-hour phase dwell, the 14-day appeal window, the
half-open capacity window and the review-deadline credential check — asserted on
both sides of the instant that separates a pass from a refusal.
"""
from datetime import datetime

from test_helpers import (
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_effective_rule,
    add_locale,
    add_rollout_plan,
    add_submission,
    assert_decimal_equals,
    assert_posture,
    build_user_headers,
    create_app_record_payload,
    create_behavior_finding_payload,
    create_feature_mapping_payload,
    create_guideline_rule_payload,
    create_metadata_locale_payload,
    create_signing_credential_payload,
    get_success_data,
    make_auditor_headers,
    new_account,
    privacy_item,
    reject,
    rejection_reasons_for,
    run_pre_review,
    set_clock,
    set_privacy,
    set_questionnaire,
    setup_approved_ios,
    setup_base_ios,
    validate_error,
    validate_paginated,
    validate_success,
)

CLEAN_ANSWERS = {
    "violence": 0,
    "sexual_content": 0,
    "profanity": 0,
    "gambling_simulated": 0,
    "drugs_alcohol": 0,
    "horror": 0,
    "unrestricted_web_access": False,
    "user_generated_content": False,
    "ugc_moderation_enabled": False,
    "real_money_gambling": False,
    "contests": False,
}


def _at(value):
    """Parse an ISO 8601 UTC instant so a rendered fractional part cannot change it."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_two_publishers(api):
    """Account A owning one app record, plus an unrelated account B."""
    set_clock(api, DEFAULT_CLOCK)
    account_a = setup_base_ios(
        client=api,
        with_rule=False,
        with_submission=False,
        with_window=False,
    )
    account_b = new_account(api, suffix="2")
    return account_a, account_b


def test_an_unrecognised_role_name_is_a_four_hundred_and_never_a_four_oh_three(api):
    """"If `X-User-Role` is absent or is not one of the seven names above, if `X-User-ID` is absent
    or empty, or if an account-backed role omits `X-Publisher-Account-Id` or sends it empty, the
    request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP 400 — never a
    403, even when the role that would have been sent is not permitted on the endpoint in question."

    Design: Corner/validations/an_unrecognised_role_header_is_four_hundred_and_never_four_oh_three
    """
    set_clock(api, DEFAULT_CLOCK)
    overlord = build_user_headers("ppa-01", "StoreOverlord")

    validate_error(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="9.9.9",
                title="Bogus",
                category="DESIGN",
                requires_feature_mapping=False,
            ),
            overlord,
        ),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        400,
    )

    _, meta = validate_paginated(api.list_guideline_rules(make_auditor_headers()))
    assert meta["total_count"] == 0


def test_an_empty_user_id_is_rejected_before_the_permission_check(api):
    """"Header enforcement is shape-only and happens before anything else. If `X-User-Role` is
    absent or is not one of the seven names above, if `X-User-ID` is absent or empty, or if an
    account-backed role omits `X-Publisher-Account-Id` or sends it empty, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP 400 — never a 403, even when the role
    that would have been sent is not permitted on the endpoint in question."

    Design: Corner/validations/an_empty_user_id_header_is_rejected_before_any_permission_check
    """
    set_clock(api, DEFAULT_CLOCK)
    nameless = build_user_headers("", "PlatformPolicyAdmin")

    validate_error(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="9.9.9",
                title="Bogus",
                category="DESIGN",
                requires_feature_mapping=False,
            ),
            nameless,
        ),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        400,
    )

    _, meta = validate_paginated(api.list_guideline_rules(make_auditor_headers()))
    assert meta["total_count"] == 0


def test_an_unauthorised_role_naming_a_missing_id_is_a_four_oh_three(api):
    """"That permission check deliberately precedes resource lookup: a request from an unauthorised
    role that also names a non-existent identifier returns 403 `ERR_ROLE_NOT_PERMITTED`, never 404,
    because resource existence must not leak to callers who have no business asking."

    Design: Corner/validations/an_unauthorized_role_naming_a_missing_id_gets_four_oh_three_not_four_oh_four
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)

    validate_error(
        api.publish_guideline_rule(NON_EXISTENT_UUID, ctx.release_manager),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_another_accounts_app_is_a_four_oh_three_while_a_ghost_id_is_a_four_oh_four(api):
    """"An identifier that resolves to a row belonging to a different account is rejected with
    `ERR_CROSS_ACCOUNT_ACCESS_DENIED` and HTTP 403 — and note the ordering: tenancy precedes
    existence, so a resolvable identifier owned by somebody else is a 403, while an identifier that
    resolves to nothing at all is a 404."

    Design: Corner/validations/another_accounts_app_is_four_oh_three_while_a_nonexistent_app_is_four_oh_four
    """
    account_a, account_b = _setup_two_publishers(api)

    validate_error(
        api.get_app_record(account_a.app_record_id, account_b.publisher_admin),
        ApiErrorId.ERR_CROSS_ACCOUNT_ACCESS_DENIED,
        403,
    )
    validate_error(
        api.get_app_record(NON_EXISTENT_UUID, account_b.publisher_admin),
        ApiErrorId.ERR_APP_RECORD_NOT_FOUND,
        404,
    )


def test_a_list_read_narrows_silently_instead_of_erroring(api):
    """"List endpoints behave differently rather than erroring: for the three account-backed roles a
    list result is silently narrowed to the account named in `X-Publisher-Account-Id`."

    Design: Corner/validations/another_accounts_app_is_four_oh_three_while_a_nonexistent_app_is_four_oh_four
    """
    account_a, account_b = _setup_two_publishers(api)

    own, own_meta = validate_paginated(
        api.list_app_records(account_a.publisher_admin)
    )
    assert own_meta["total_count"] == 1
    assert own[0]["id"] == account_a.app_record_id

    _, foreign_meta = validate_paginated(
        api.list_app_records(account_b.publisher_admin)
    )
    assert foreign_meta["total_count"] == 0


def test_two_unknown_body_references_report_the_first_declared_one(api):
    """"Because path identifiers precede body fields and body fields are examined in declaration
    order, a rollout-plan creation that names both an unknown app record and an unknown submission
    reports `ERR_APP_RECORD_NOT_FOUND`, since `app_record_id` is declared first."

    Design: Corner/validations/two_unknown_body_references_report_the_first_declared_one
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        with_rule=False,
        with_submission=False,
        with_window=False,
    )

    validate_error(
        api.create_rollout_plan(
            {
                "expected_app_record_version": ctx.app_version(),
                "app_record_id": NON_EXISTENT_UUID,
                "submission_id": "00000000-0000-4000-8000-000000000405",
                "mode": "PHASED",
                "scheduled_start_at": DEFAULT_CLOCK,
            },
            ctx.release_manager,
        ),
        ApiErrorId.ERR_APP_RECORD_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, {"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 0


def test_a_malformed_body_sent_to_a_missing_submission_is_a_four_oh_four(api):
    """"Note the rung order: a malformed body sent to a non-existent submission returns 404, not
    422."

    Design: Corner/validations/a_malformed_body_sent_to_a_missing_submission_is_four_oh_four_not_four_twenty_two
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_content=False, with_pre_review=False)

    validate_error(
        api.set_age_rating(
            NON_EXISTENT_UUID,
            {"age_rating_answers": dict(CLEAN_ANSWERS), "attested_age_rating": 5},
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_FOUND,
        404,
    )
    assert ctx.submission()["attested_age_rating"] is None


def test_a_limit_of_zero_and_a_negative_offset_are_both_schema_violations(api):
    """"A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is a schema
    violation and is rejected with `ERR_VALIDATION` and HTTP 422."

    Design: Corner/validations/a_limit_of_zero_is_refused_while_a_limit_of_one_hundred_is_accepted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    add_effective_rule(ctx)

    validate_error(
        api.list_guideline_rules(ctx.auditor, {"limit": 0}),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.list_guideline_rules(ctx.auditor, {"offset": -1}),
        ApiErrorId.ERR_VALIDATION,
        422,
    )


def test_the_upper_pagination_bound_of_one_hundred_is_accepted_and_echoed(api):
    """"The `meta` object of a list response carries `limit` and `offset` echoing the effective
    values used, `total_count` giving the number of rows matching the filter before pagination was
    applied, and `has_more` indicating whether any row remains beyond the current page."

    Design: Corner/validations/a_limit_of_zero_is_refused_while_a_limit_of_one_hundred_is_accepted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    add_effective_rule(ctx)

    rules, meta = validate_paginated(
        api.list_guideline_rules(ctx.auditor, {"limit": 100, "offset": 0})
    )
    assert len(rules) == 1
    assert meta["total_count"] == 1
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_an_answer_set_missing_one_intensity_key_is_a_schema_violation(api):
    """"Two shape rules deserve naming here because they are structured objects: the age-rating
    questionnaire must carry exactly the six intensity keys with values from 0 through 3 inclusive
    plus the five declared booleans, and every value inside a screenshot count map must be an
    integer of at least 0."

    Design: Corner/validations/an_unknown_body_field_and_a_short_answer_set_are_both_schema_failures
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_content=False, with_pre_review=False)

    short_answers = dict(CLEAN_ANSWERS)
    del short_answers["horror"]
    validate_error(
        api.set_age_rating(
            ctx.submission_id,
            {"age_rating_answers": short_answers, "attested_age_rating": 4},
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    assert ctx.submission()["derived_age_rating"] is None


def test_an_unknown_body_field_is_rejected_rather_than_ignored(api):
    """"It covers missing required fields, wrong types, values outside a declared enumeration,
    string lengths outside their declared bounds, array cardinalities, numeric ranges, malformed
    ISO 8601 UTC instants, unknown fields, out-of-bounds pagination, and a handful of body-shape
    rules stated with their workflows in §3 — a non-zero price on an external payment link, an empty
    rejection-reason array on a reject decision, an overturned-reason list that is not a strict
    subset of the cited list, a provisioning profile enrolled without a linked certificate, or a
    validity end that is not after the validity start."

    Design: Corner/validations/an_unknown_body_field_and_a_short_answer_set_are_both_schema_failures
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        with_rule=False,
        with_submission=False,
        with_window=False,
    )

    validate_error(
        api.create_app_record(
            create_app_record_payload(
                ctx.account_id,
                bundle_id="com.northwind.extra",
                display_name="Extra",
                nickname="wallet2",
            ),
            ctx.publisher_admin,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    _, meta = validate_paginated(
        api.list_app_records(
            ctx.publisher_admin, {"publisher_account_id": ctx.account_id}
        )
    )
    assert meta["total_count"] == 1


def test_a_stale_parent_version_outranks_the_forbidden_state(api):
    """"The revision guard is also positioned deliberately in the rejection ladder of §2.7: it is
    evaluated *before* the target entity's own state is examined, so when the supplied expected
    version is stale **and** the target is in a state that forbids the operation, the response is
    the 412 revision error, never the 409 state error."

    Design: Corner/validations/a_stale_parent_version_outranks_the_forbidden_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_submission=False)
    stale_version = ctx.app_version()
    add_submission(ctx)

    validate_error(
        api.create_rollout_plan(
            {
                "expected_app_record_version": stale_version,
                "app_record_id": ctx.app_record_id,
                "submission_id": ctx.submission_id,
                "mode": "PHASED",
                "scheduled_start_at": DEFAULT_CLOCK,
            },
            ctx.release_manager,
        ),
        ApiErrorId.ERR_STALE_APP_RECORD_VERSION,
        412,
    )

    _, meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, {"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 0
    assert ctx.submission()["state"] == "DRAFT"


def _file_critical_finding(ctx, **overrides):
    """The scanner files one CRITICAL DEVICE_ID observation against the build."""
    payload = create_behavior_finding_payload(
        ctx.submission_id,
        severity="CRITICAL",
        scanner_confidence=0.99,
        endpoint_domain="ads.northwind.example",
        detected_at="2026-07-31T00:00:00Z",
        **overrides,
    )
    return get_success_data(
        ctx.client.create_behavior_finding(payload, ctx.policy_admin)
    )


def test_a_critical_finding_freezes_the_app_and_rewrites_the_provisional_score(api):
    """"A finding lands `OPEN` with `triaged_by_user_id`, `triage_justification` and `triaged_at`
    null, and a `CRITICAL` finding immediately recomputes the app's posture, which freezes the app."

    Design: Corner/validations/a_frozen_posture_masks_the_critical_finding_error_at_queue_entry
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)

    finding = _file_critical_finding(ctx)
    assert finding["status"] == "OPEN"
    assert_posture(ctx.app(), "FROZEN", ["CRITICAL_FINDING_OPEN"])
    assert_decimal_equals(
        ctx.submission()["disclosure_accuracy_score_provisional"],
        0.6000,
        4,
        "provisional disclosure score",
    )


def test_the_frozen_posture_masks_the_critical_finding_error_at_queue_entry(api):
    """"An app whose posture is frozen and whose submission also carries an unreconciled critical
    behaviour finding reports `ERR_APP_COMPLIANCE_FROZEN`, not `ERR_CRITICAL_FINDING_UNRESOLVED`."

    Design: Corner/validations/a_frozen_posture_masks_the_critical_finding_error_at_queue_entry
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _file_critical_finding(ctx)

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_FROZEN,
        409,
    )
    assert ctx.submission()["state"] == "PRE_REVIEW_PASSED"


def _setup_frozen_by_a_matching_critical_finding(api):
    """A PRE_REVIEW_PASSED build whose declared label already matches the CRITICAL finding."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        declared_privacy_items=[
            privacy_item("DEVICE_ID", "ADVERTISING", linked=True, tracking=True)
        ],
        tracking_consent_prompt_present=True,
    )
    finding = _file_critical_finding(ctx)
    assert_posture(ctx.app(), "FROZEN", ["CRITICAL_FINDING_OPEN"])
    return ctx, finding


def test_dismissing_a_critical_finding_is_refused_even_while_the_app_is_frozen(api):
    """"`DISMISS` is refused for a `CRITICAL` finding with `ERR_WAIVER_NOT_PERMITTED` — the platform
    may not simply wave away its own most serious evidence."

    Design: Corner/validations/triage_is_exempt_from_the_posture_gate_so_a_frozen_app_can_be_unfrozen
    """
    ctx, finding = _setup_frozen_by_a_matching_critical_finding(api)

    validate_error(
        api.triage_behavior_finding(
            finding["id"], {"action": "DISMISS"}, ctx.policy_admin
        ),
        ApiErrorId.ERR_WAIVER_NOT_PERMITTED,
        409,
    )
    assert_posture(ctx.app(), "FROZEN", ["CRITICAL_FINDING_OPEN"])


def test_reconciling_the_finding_unfreezes_the_app_and_reopens_the_queue_path(api):
    """"`RECONCILE` requires that the submission's `declared_privacy_items` now contains a tuple
    matching the finding on all four attributes — `data_type` equal to `data_type`, purpose equal to
    `observed_purpose`, linked-to-user equal to `observed_linked_to_user` and tracking equal to
    `observed_tracking`."

    Design: Corner/validations/triage_is_exempt_from_the_posture_gate_so_a_frozen_app_can_be_unfrozen
    """
    ctx, finding = _setup_frozen_by_a_matching_critical_finding(api)

    reconciled = validate_success(
        api.triage_behavior_finding(
            finding["id"], {"action": "RECONCILE"}, ctx.policy_admin
        ),
        200,
    )
    assert reconciled["status"] == "RECONCILED"
    assert_posture(ctx.app(), "OPEN", [])

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert_decimal_equals(
        queued["disclosure_accuracy_score_provisional"],
        1.0000,
        4,
        "provisional disclosure score",
    )


def _suspend_the_account(api, ctx):
    """Platform enforcement drives the whole portfolio into the frozen tier."""
    enforced = validate_success(
        api.enforce_account(
            ctx.account_id,
            {"action": "SUSPEND", "reason_code": "FRAUD_INVESTIGATION"},
            ctx.policy_admin,
        ),
        200,
    )
    assert enforced["program_status"] == "SUSPENDED"
    assert enforced["enforcement_reason_code"] == "FRAUD_INVESTIGATION"
    return enforced


def test_a_suspended_account_reports_the_app_posture_at_the_queue(api):
    """"This rung sits *after* the app-posture rung, so a frozen app owned by a suspended account
    reports the app-level cause first."

    Design: Corner/validations/a_suspended_account_reports_the_app_posture_on_queue_and_the_account_on_mapping_create
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _suspend_the_account(api, ctx)

    assert_posture(ctx.app(), "FROZEN", ["ACCOUNT_NOT_IN_GOOD_STANDING"])
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_FROZEN,
        409,
    )


def test_a_suspended_account_reports_itself_on_a_mapping_create(api):
    """"When it is `EXPIRED`, the affected operations are rejected with
    `ERR_PROGRAM_MEMBERSHIP_EXPIRED` and HTTP 403; when it is `SUSPENDED` or `TERMINATED`, they are
    rejected with `ERR_ACCOUNT_SUSPENDED` and HTTP 403."

    Design: Corner/validations/a_suspended_account_reports_the_app_posture_on_queue_and_the_account_on_mapping_create
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _suspend_the_account(api, ctx)

    validate_error(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id, ctx.rules["privacy"], feature_code="DATA_EXPORT"
            ),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_ACCOUNT_SUSPENDED,
        403,
    )


def test_reinstating_the_account_clears_the_reason_code_and_the_posture(api):
    """"The supplied `reason_code` is stored as `enforcement_reason_code`, and is cleared to null on
    a reinstatement — that field is null whenever `program_status` is `ACTIVE` or `EXPIRED`."

    Design: Corner/validations/reinstating_the_account_restores_the_posture_and_the_queue_path
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _suspend_the_account(api, ctx)

    reinstated = validate_success(
        api.enforce_account(
            ctx.account_id,
            {"action": "REINSTATE", "reason_code": "INVESTIGATION_CLOSED"},
            ctx.policy_admin,
        ),
        200,
    )
    assert reinstated["program_status"] == "ACTIVE"
    assert reinstated["enforcement_reason_code"] is None
    assert_posture(ctx.app(), "OPEN", [])


def test_the_queue_call_that_was_frozen_one_call_earlier_now_succeeds(api):
    """"Then `priority_score` is 0.50 times standing plus 0.30 times urgency *minus* 0.20 times
    risk, rounded half up to two decimals and clamped to 0.00 through 100.00."

    Design: Corner/validations/reinstating_the_account_restores_the_posture_and_the_queue_path
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _suspend_the_account(api, ctx)
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_FROZEN,
        409,
    )

    validate_success(
        api.enforce_account(
            ctx.account_id,
            {"action": "REINSTATE", "reason_code": "INVESTIGATION_CLOSED"},
            ctx.policy_admin,
        ),
        200,
    )
    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority score")


def _add_an_unstarted_second_mapping(api, ctx):
    """A second NOT_STARTED mapping halves the index and restricts the app."""
    get_success_data(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id, ctx.rules["privacy"], feature_code="DATA_EXPORT"
            ),
            ctx.compliance_officer,
        )
    )
    app = ctx.app()
    assert_decimal_equals(
        app["feature_compliance_index"], 50.00, 2, "compliance index"
    )
    assert_posture(app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])
    return app


def test_a_restricted_posture_blocks_the_queue(api):
    """"A restricted posture is narrower: it blocks only the release-advancing subset — queueing a
    submission, creating a rollout plan, starting a rollout, advancing a rollout phase, resuming a
    paused rollout, submitting a commerce item for commerce review, and creating an expedite
    request — with the code `ERR_APP_COMPLIANCE_RESTRICTED` and HTTP 409."

    Design: Corner/validations/a_restricted_posture_blocks_the_queue_but_not_the_store_page_edit
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _add_an_unstarted_second_mapping(api, ctx)

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )
    assert ctx.submission()["state"] == "PRE_REVIEW_PASSED"


def test_a_restricted_posture_does_not_block_the_store_page_edit(api):
    """"Attaching a locale is a content mutation, so it increments the submission's
    `metadata_locale_count` by one and, if the submission was `PRE_REVIEW_PASSED`, drives it back to
    `DRAFT` — changing the store page invalidates the clearance that was granted against the old
    one."

    Design: Corner/validations/a_restricted_posture_blocks_the_queue_but_not_the_store_page_edit
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    _add_an_unstarted_second_mapping(api, ctx)

    locale = validate_success(
        api.create_metadata_locale(
            create_metadata_locale_payload(
                ctx.submission_id,
                locale="fr-FR",
                title="Northwind Portefeuille",
                is_primary=False,
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert locale["is_complete"] is True
    assert locale["is_primary"] is False

    voided = ctx.submission()
    assert voided["state"] == "DRAFT"
    assert voided["metadata_locale_count"] == 2


def test_an_attestation_exactly_seventy_two_hours_old_still_queues(api):
    """"In addition: `pre_review_passed` must be true, otherwise `ERR_PRE_REVIEW_NOT_PASSED`; the
    attestation must be no more than 72 hours old, measured from `pre_review_checked_at`, with
    exactly 72 hours still passing and anything older refused as `ERR_PRE_REVIEW_STALE`; the app's
    posture must be `OPEN`, so `FROZEN` yields `ERR_APP_COMPLIANCE_FROZEN` and `RESTRICTED` yields
    `ERR_APP_COMPLIANCE_RESTRICTED`; the signing credential must still be usable; guideline coverage
    must be complete, meaning that every `EFFECTIVE` rule with `requires_feature_mapping` true has at
    least one mapping from this app and that every mapping of the app pointing at an `EFFECTIVE` rule
    is `PASSED` or `WAIVED_BY_PLATFORM`, and any shortfall — including an app with no mappings at
    all, for which there is no vacuous pass — is `ERR_GUIDELINE_MAPPING_INCOMPLETE`; any declared
    privacy tuple marked as used for cross-app tracking obliges `tracking_consent_prompt_present` to
    be true, and declared tracking without the prompt is a hard block regardless of the accuracy
    score, refused with `ERR_TRACKING_CONSENT_PROMPT_MISSING`; and a capacity window must be
    selectable, otherwise `ERR_NO_REVIEW_CAPACITY`."

    Design: Corner/validations/an_attestation_exactly_seventy_two_hours_old_still_queues
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    assert ctx.submission()["pre_review_checked_at"] is not None

    set_clock(api, "2026-08-04T00:00:00Z")
    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert _at(queued["queued_at"]) == _at("2026-08-04T00:00:00Z")
    assert _at(queued["provisional_deadline_at"]) == _at("2026-08-06T00:00:00Z")
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority score")
    assert queued["priority_band"] == "NORMAL"


def test_one_second_past_seventy_two_hours_the_attestation_is_stale(api):
    """"Every content rule that the self-review merely reported is enforced here as a hard error,
    re-evaluated against the *current* clock and the current rows, not against whatever the
    self-review saw."

    Design: Corner/validations/one_second_past_seventy_two_hours_the_attestation_is_stale
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)

    set_clock(api, "2026-08-04T00:00:01Z")
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_PRE_REVIEW_STALE,
        409,
    )

    stale = ctx.submission()
    assert stale["pre_review_passed"] is True
    assert _at(stale["pre_review_checked_at"]) == _at(DEFAULT_CLOCK)
    assert stale["state"] == "PRE_REVIEW_PASSED"
    assert stale["review_window_id"] is None


def test_a_second_build_reusing_the_build_number_is_refused(api):
    """"The `build_number` must be strictly greater than the `build_number` of every existing
    submission of the same app whose state is not `DEVELOPER_WITHDRAWN`; anything else, equal or
    lower, is refused with `ERR_DUPLICATE_BUILD_NUMBER`."

    Design: Corner/validations/a_second_build_reusing_the_build_number_is_refused
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_content=False, with_window=False, with_pre_review=False
    )
    first = ctx.submission()
    assert first["state"] == "DRAFT"
    version_before = ctx.app_version()

    validate_error(
        api.create_submission(
            {
                "expected_app_record_version": version_before,
                "app_record_id": ctx.app_record_id,
                "signing_credential_id": ctx.profile_id,
                "build_number": 10,
                "version_string": "1.0.0-hotfix",
            },
            ctx.release_manager,
        ),
        ApiErrorId.ERR_DUPLICATE_BUILD_NUMBER,
        409,
    )

    kept, meta = validate_paginated(
        api.list_submissions(
            ctx.release_manager, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 1
    assert kept[0]["id"] == ctx.submission_id
    assert kept[0]["state"] == "DRAFT"
    assert ctx.app_version() == version_before


def _setup_draft_build_without_content(api):
    """A DRAFT build on an OPEN app, with no locale and no declaration yet."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        client=api, with_content=False, with_window=False, with_pre_review=False
    )


def test_a_second_primary_locale_is_refused_while_a_secondary_one_is_accepted(api):
    """"Exactly one locale of a submission may be primary; both a second locale carrying
    `is_primary` true and a repeat of the same `locale` on the same submission are refused with
    `ERR_DUPLICATE_PRIMARY_LOCALE`."

    Design: Corner/validations/a_second_primary_locale_is_refused_while_a_secondary_one_is_accepted
    """
    ctx = _setup_draft_build_without_content(api)
    add_locale(ctx)

    secondary = validate_success(
        api.create_metadata_locale(
            create_metadata_locale_payload(
                ctx.submission_id,
                locale="fr-FR",
                title="Northwind Portefeuille",
                is_primary=False,
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert secondary["is_primary"] is False

    validate_error(
        api.create_metadata_locale(
            create_metadata_locale_payload(
                ctx.submission_id,
                locale="de-DE",
                title="Northwind Geldbeutel",
                is_primary=True,
            ),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_DUPLICATE_PRIMARY_LOCALE,
        409,
    )

    _, meta = validate_paginated(
        api.list_metadata_locales(
            ctx.release_manager, params={"submission_id": ctx.submission_id}
        )
    )
    assert meta["total_count"] == 2


def test_a_locale_one_screenshot_short_is_still_created_but_is_not_complete(api):
    """"`required_device_classes` follows the app's platform: an `IOS` submission requires both
    `PHONE_65` and `TABLET_129`, while an `ANDROID` submission requires only `PHONE_65`.
    `is_complete` is true exactly when `title` is non-empty and, for every one of the required device
    classes, `screenshot_counts` carries an entry of at least 2 — the minimum screenshot count per
    class — and false otherwise, including when a required class is absent from the map altogether."

    Design: Corner/validations/a_locale_one_screenshot_short_is_created_but_refused_at_the_queue
    """
    ctx = _setup_draft_build_without_content(api)

    short = validate_success(
        api.create_metadata_locale(
            create_metadata_locale_payload(
                ctx.submission_id,
                screenshot_counts={"PHONE_65": 3, "TABLET_129": 1},
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert short["required_device_classes"] == ["PHONE_65", "TABLET_129"]
    assert short["is_complete"] is False


def test_a_build_with_no_locale_at_all_fails_its_own_pre_review(api):
    """"When at least one code is recorded the submission stays in `DRAFT` with `pre_review_passed`
    false; when the array comes back empty the submission moves `DRAFT → PRE_REVIEW_PASSED`,
    `pre_review_passed` becomes true, and `attested_by_user_id` is stamped with the acting officer,
    who thereby becomes the subject of the segregation-of-duties rule at the decision gate."

    Design: Corner/validations/zero_locales_outranks_the_failed_pre_review_at_the_queue
    """
    ctx = _setup_draft_build_without_content(api)
    set_questionnaire(ctx)
    set_privacy(ctx)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert reported["pre_review_passed"] is False
    assert "METADATA_INCOMPLETE" in reported["pre_review_blocking_reasons"]
    assert reported["state"] == "DRAFT"


def test_a_guideline_published_after_the_pass_blocks_the_queue_for_coverage(api):
    """"Every content rule that the self-review merely reported is enforced here as a hard error,
    re-evaluated against the *current* clock and the current rows, not against whatever the
    self-review saw."

    Design: Corner/validations/a_guideline_published_after_the_pre_review_pass_blocks_the_queue_for_coverage
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    assert ctx.submission()["pre_review_passed"] is True

    latecomer = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="3.1.1",
                title="In-app purchase disclosure",
                category="COMMERCE",
                version_label="2026.3",
                effective_from="2026-07-01T00:00:00Z",
                requires_feature_mapping=True,
            ),
            ctx.policy_admin,
        )
    )
    published = validate_success(
        api.publish_guideline_rule(latecomer["id"], ctx.policy_admin), 200
    )
    assert published["status"] == "EFFECTIVE"
    assert published["impacted_app_count"] == 0
    assert_posture(ctx.app(), "OPEN", [])
    assert ctx.submission()["pre_review_passed"] is True

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_GUIDELINE_MAPPING_INCOMPLETE,
        409,
    )


TRACKING_ITEM = privacy_item("DEVICE_ID", "ADVERTISING", linked=True, tracking=True)


def _setup_tracking_declared_without_a_prompt(api):
    """A complete build whose only defect is a declared tracking item with no prompt."""
    ctx = setup_base_ios(client=api, with_content=False, with_pre_review=False)
    add_locale(ctx)
    set_questionnaire(ctx)
    declared = validate_success(
        api.set_privacy_declaration(
            ctx.submission_id,
            {
                "declared_privacy_items": [TRACKING_ITEM],
                "tracking_consent_prompt_present": False,
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert declared["tracking_consent_prompt_present"] is False
    return ctx


def test_declared_tracking_without_a_prompt_is_reported_beside_a_perfect_score(api):
    """"The provisional variant, `disclosure_accuracy_score_provisional`, counts only findings whose
    `status` is `OPEN`, whose `detected_at` is at or before the submission's `pre_review_checked_at`,
    and whose `scanner_confidence` is at or above 0.8000; it does **not** apply the over-disclosure
    term, because declaring more than was observed costs a publisher nothing at self-review time."

    Design: Corner/validations/declared_tracking_without_a_consent_prompt_blocks_a_perfect_disclosure_score
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = _setup_tracking_declared_without_a_prompt(api)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(
        reported["disclosure_accuracy_score_provisional"],
        1.0000,
        4,
        "provisional disclosure score",
    )
    assert (
        "TRACKING_CONSENT_PROMPT_MISSING" in reported["pre_review_blocking_reasons"]
    )
    assert reported["pre_review_passed"] is False


def test_flipping_the_consent_prompt_on_clears_the_block_without_touching_the_score(api):
    """"Separately a `ComplianceOfficer` sets the privacy label by supplying `declared_privacy_items`
    — an array of tuples each naming a `data_type`, a purpose, whether the collection is linked to a
    user identity, and whether it is used for cross-app tracking — together with
    `tracking_consent_prompt_present`, the publisher's assertion that the binary actually shows a
    consent prompt. This too is a content mutation that voids a passed self-review."

    Design: Corner/validations/flipping_the_consent_prompt_on_clears_the_tracking_block_without_touching_the_score
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = _setup_tracking_declared_without_a_prompt(api)
    blocked = run_pre_review(ctx)
    assert blocked["pre_review_passed"] is False

    redeclared = validate_success(
        api.set_privacy_declaration(
            ctx.submission_id,
            {
                "declared_privacy_items": [TRACKING_ITEM],
                "tracking_consent_prompt_present": True,
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert redeclared["tracking_consent_prompt_present"] is True

    cleared = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert cleared["pre_review_blocking_reasons"] == []
    assert cleared["pre_review_passed"] is True

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert_decimal_equals(
        queued["disclosure_accuracy_score_provisional"],
        1.0000,
        4,
        "provisional disclosure score",
    )


def test_mark_remediated_is_the_reachable_home_of_the_remediation_incomplete_code(api):
    """"`MARK_REMEDIATED` moves the row to `REMEDIATED` from either `REMEDIATION_REQUIRED` or
    `OVERDUE`, and requires that every feature mapping named in `affected_feature_codes` now has
    `self_review_status` of `PASSED` or `WAIVED_BY_PLATFORM`; if any remains unattested the request is
    refused with `ERR_REMEDIATION_INCOMPLETE`."

    Design: Corner/validations/mark_remediated_is_the_only_reachable_home_of_the_remediation_incomplete_code
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_submission=False, with_window=False
    )
    successor = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                rule_code="5.1.2",
                title="Account Deletion In App",
                category="PRIVACY",
                version_label="2026.09",
                effective_from=DEFAULT_CLOCK,
                supersedes_rule_id=ctx.rules["privacy"],
                requires_feature_mapping=True,
            ),
            ctx.policy_admin,
        )
    )
    validate_success(
        api.publish_guideline_rule(successor["id"], ctx.policy_admin), 200
    )

    rows, _ = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 1
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

    validate_error(
        api.assess_impact(
            assessment_id, {"action": "MARK_REMEDIATED"}, ctx.compliance_officer
        ),
        ApiErrorId.ERR_REMEDIATION_INCOMPLETE,
        409,
    )

    assert get_success_data(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer)
    )["status"] == "REMEDIATION_REQUIRED"
    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "STALE"
    assert_posture(
        ctx.app(),
        "RESTRICTED",
        ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"],
    )


def _second_build_on_a_short_lived_profile(api, not_after):
    """A ready NORMAL-band build signed by a profile that expires at ``not_after``."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)

    short_lived = get_success_data(
        api.create_signing_credential(
            create_signing_credential_payload(
                ctx.account_id,
                ctx.account_version(),
                credential_type="PROVISIONING_PROFILE",
                platform="IOS",
                key_custody="CLOUD_MANAGED",
                linked_cert_id=ctx.cert_id,
                not_before="2026-07-01T00:00:00Z",
                not_after=not_after,
            ),
            ctx.publisher_admin,
        )
    )
    validate_success(
        api.activate_signing_credential(short_lived["id"], ctx.publisher_admin), 200
    )

    second = get_success_data(
        api.create_submission(
            {
                "expected_app_record_version": ctx.app_version(),
                "app_record_id": ctx.app_record_id,
                "signing_credential_id": short_lived["id"],
                "build_number": 101,
                "version_string": "4.2.1",
                "release_mode": "PHASED",
            },
            ctx.release_manager,
        )
    )
    add_locale(ctx, second["id"])
    set_questionnaire(ctx, second["id"])
    set_privacy(ctx, second["id"])
    cleared = validate_success(
        api.pre_review_check(second["id"], ctx.compliance_officer), 200
    )
    assert cleared["pre_review_passed"] is True
    return ctx, second["id"]


def test_a_credential_expiring_exactly_at_the_review_deadline_is_refused(api):
    """"One temporal rule joins at queue entry and is the only reason an `EXPIRING_SOON` credential
    can block: the credential's `not_after` must be strictly later than the
    `effective_review_deadline_at` this very queue entry just computed."

    Design: Corner/validations/a_credential_expiring_exactly_at_the_review_deadline_is_refused
    """
    ctx, submission_id = _second_build_on_a_short_lived_profile(
        api, "2026-08-03T00:00:00Z"
    )

    validate_error(
        api.queue_submission(submission_id, ctx.release_manager),
        ApiErrorId.ERR_CREDENTIAL_EXPIRES_BEFORE_DEADLINE,
        409,
    )

    refused = ctx.submission(submission_id)
    assert refused["state"] == "PRE_REVIEW_PASSED"
    assert refused["queued_at"] is None


def test_a_credential_expiring_one_second_after_the_deadline_queues(api):
    """"A credential expiring exactly at the review deadline is refused with
    `ERR_CREDENTIAL_EXPIRES_BEFORE_DEADLINE`, because the review may legitimately conclude at that
    instant."

    Design: Corner/validations/a_credential_expiring_one_second_after_the_deadline_queues_while_expiring_soon
    """
    ctx, submission_id = _second_build_on_a_short_lived_profile(
        api, "2026-08-03T00:00:01Z"
    )

    queued = validate_success(
        api.queue_submission(submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert _at(queued["effective_review_deadline_at"]) == _at("2026-08-03T00:00:00Z")
    assert queued["priority_band"] == "NORMAL"
    assert queued["review_window_id"] == ctx.window_id


def test_a_rollout_start_is_refused_before_and_legal_at_its_scheduled_instant(api):
    """"Starting requires the current instant to be at or after `scheduled_start_at`, with equality
    succeeding and anything earlier refused as `ERR_ROLLOUT_NOT_DUE`; the cited submission must still
    be `APPROVED`; the app's posture must be `OPEN`; and no other plan of the app may be
    `PHASE_ACTIVE` or `PAUSED`, otherwise `ERR_ROLLOUT_WINDOW_CONFLICT`."

    Design: Corner/validations/a_rollout_start_is_refused_before_and_legal_exactly_at_its_scheduled_instant
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api)
    plan = validate_success(
        api.create_rollout_plan(
            {
                "expected_app_record_version": ctx.app_version(),
                "app_record_id": ctx.app_record_id,
                "submission_id": ctx.submission_id,
                "mode": "PHASED",
                "scheduled_start_at": "2026-08-02T00:00:00Z",
            },
            ctx.release_manager,
        ),
        201,
    )
    assert plan["state"] == "SCHEDULED"

    validate_error(
        api.start_rollout_plan(plan["id"], ctx.release_manager),
        ApiErrorId.ERR_ROLLOUT_NOT_DUE,
        409,
    )
    assert ctx.plan(plan["id"])["state"] == "SCHEDULED"

    set_clock(api, "2026-08-02T00:00:00Z")
    started = validate_success(
        api.start_rollout_plan(plan["id"], ctx.release_manager), 200
    )
    assert started["state"] == "PHASE_ACTIVE"
    assert started["phase_index"] == 0
    assert _at(started["phase_entered_at"]) == _at("2026-08-02T00:00:00Z")

    app = ctx.app()
    assert_decimal_equals(app["released_share_pct"], 1.00, 2, "released share")
    assert_decimal_equals(app["held_back_share_pct"], 99.00, 2, "held back share")


def test_the_phase_dwell_refuses_at_twenty_three_fifty_nine_and_passes_at_twenty_four(api):
    """"The dwell rule requires the current instant to be at or after `phase_entered_at` plus 24
    hours, inclusively: advancing exactly 24 hours after entering the phase is legal, 23 hours and 59
    minutes is not, and the refusal is `ERR_PHASE_DWELL_NOT_MET`."

    Design: Corner/validations/the_phase_dwell_boundary_refuses_at_twenty_three_fifty_nine_and_passes_at_twenty_four_hours
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api)
    started = add_rollout_plan(ctx, start=True)
    assert _at(started["phase_entered_at"]) == _at(DEFAULT_CLOCK)

    set_clock(api, "2026-08-01T23:59:59Z")
    validate_error(
        api.advance_rollout_plan(
            ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager
        ),
        ApiErrorId.ERR_PHASE_DWELL_NOT_MET,
        409,
    )
    assert ctx.plan()["phase_index"] == 0
    assert_decimal_equals(ctx.app()["released_share_pct"], 1.00, 2, "released share")

    set_clock(api, "2026-08-02T00:00:00Z")
    advanced = validate_success(
        api.advance_rollout_plan(
            ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager
        ),
        200,
    )
    assert advanced["phase_index"] == 1
    assert _at(advanced["phase_entered_at"]) == _at("2026-08-02T00:00:00Z")

    app = ctx.app()
    assert_decimal_equals(app["released_share_pct"], 2.00, 2, "released share")
    assert_decimal_equals(app["held_back_share_pct"], 98.00, 2, "held back share")


def test_a_resume_rewrites_phase_entered_at_and_restarts_the_whole_dwell(api):
    """"`RESUME` moves `PAUSED → PHASE_ACTIVE`, requires the posture to be `OPEN` (otherwise
    `ERR_APP_COMPLIANCE_RESTRICTED`), clears `pause_reason_code`, and re-stamps `phase_entered_at` to
    the resume instant — which means the **full 24-hour dwell restarts from the resume**, so a pause
    does not bank time toward the next advance."

    Design: Corner/validations/a_resume_rewrites_phase_entered_at_and_restarts_the_whole_dwell
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api)
    add_rollout_plan(ctx, start=True)

    paused = validate_success(
        api.hold_rollout_plan(
            ctx.plan_id,
            {"action": "PAUSE", "pause_reason_code": "MANUAL_HOLD"},
            ctx.release_manager,
        ),
        200,
    )
    assert paused["state"] == "PAUSED"

    set_clock(api, "2026-08-02T00:00:00Z")
    resumed = validate_success(
        api.hold_rollout_plan(ctx.plan_id, {"action": "RESUME"}, ctx.release_manager),
        200,
    )
    assert resumed["state"] == "PHASE_ACTIVE"
    assert resumed["pause_reason_code"] is None
    assert _at(resumed["phase_entered_at"]) == _at("2026-08-02T00:00:00Z")
    assert ctx.app()["distribution_state"] == "PHASED_ROLLOUT"

    validate_error(
        api.advance_rollout_plan(
            ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager
        ),
        ApiErrorId.ERR_PHASE_DWELL_NOT_MET,
        409,
    )
    assert ctx.plan()["phase_index"] == 0

    set_clock(api, "2026-08-03T00:00:00Z")
    advanced = validate_success(
        api.advance_rollout_plan(
            ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager
        ),
        200,
    )
    assert advanced["phase_index"] == 1
    assert _at(advanced["phase_entered_at"]) == _at("2026-08-03T00:00:00Z")


def test_an_elapsed_capacity_window_closes_the_claim_path_after_the_slot_was_reserved(api):
    """"Two things must hold: the assigned capacity window must still be `OPEN` with the current
    instant inside its half-open interval, otherwise `ERR_REVIEW_WINDOW_CLOSED`; and the signing
    credential must still be `ACTIVE` or `EXPIRING_SOON`, otherwise `ERR_SIGNING_CREDENTIAL_INVALID`."

    Design: Corner/validations/an_elapsed_capacity_window_closes_the_claim_path_after_the_slot_was_already_reserved
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )
    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["review_window_id"] == ctx.window_id

    validate_success(
        api.set_clock_raw({"current_utc": "2026-09-01T00:00:00Z"}, ctx.policy_admin),
        200,
    )
    validate_error(
        api.claim_submission(ctx.submission_id, ctx.reviewer),
        ApiErrorId.ERR_REVIEW_WINDOW_CLOSED,
        409,
    )

    stranded = ctx.submission()
    assert stranded["state"] == "WAITING_FOR_REVIEW"
    assert stranded["review_window_id"] == ctx.window_id
    assert ctx.window()["slots_reserved"] == 1


def test_an_appeal_filed_exactly_fourteen_days_after_rejection_is_accepted(api):
    """"The filing must happen within 14 days of `rejected_at`, inclusive — an appeal filed at
    exactly `rejected_at` plus 14 days is accepted, later is `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/validations/an_appeal_filed_exactly_fourteen_days_after_rejection_is_accepted_and_one_second_later_is_not
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    rejected = reject(ctx, rejection_reasons_for(ctx.rules["privacy"]))
    assert rejected["state"] == "REJECTED"
    assert _at(rejected["rejected_at"]) == _at(DEFAULT_CLOCK)

    reasons, _ = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    contested = get_success_data(
        api.respond_to_rejection_reason(
            reasons[0]["id"],
            {
                "disposition": "CONTESTED",
                "developer_response": (
                    "The identifier never leaves the device and is covered by the "
                    "DEVICE_ID disclosure already in the label."
                ),
            },
            ctx.compliance_officer,
        )
    )
    assert contested["disposition"] == "CONTESTED"

    set_clock(api, "2026-08-15T00:00:00Z")
    appeal = validate_success(
        api.create_appeal_request(
            {
                "submission_id": ctx.submission_id,
                "appeal_type": "GUIDELINE_INTERPRETATION",
                "argument": (
                    "The identifier is device-local and the disclosure already covers it."
                ),
                "cited_rejection_reason_ids": [reasons[0]["id"]],
            },
            ctx.compliance_officer,
        ),
        201,
    )
    assert _at(appeal["filed_at"]) == _at("2026-08-15T00:00:00Z")
    assert ctx.submission()["state"] == "APPEAL_PENDING"


def test_one_second_later_the_refiled_appeal_is_outside_the_window(api):
    """"A `ComplianceOfficer` may instead withdraw an appeal that is still `SUBMITTED`, optionally
    citing a `reason_code`; the appeal becomes `WITHDRAWN`, which is terminal, and the submission
    returns to `REJECTED`, again without refreshing `rejected_at`."

    Design: Corner/validations/an_appeal_filed_exactly_fourteen_days_after_rejection_is_accepted_and_one_second_later_is_not
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    reject(ctx, rejection_reasons_for(ctx.rules["privacy"]))
    reasons, _ = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    get_success_data(
        api.respond_to_rejection_reason(
            reasons[0]["id"],
            {
                "disposition": "CONTESTED",
                "developer_response": (
                    "The identifier never leaves the device and is covered by the "
                    "DEVICE_ID disclosure already in the label."
                ),
            },
            ctx.compliance_officer,
        )
    )
    filing = {
        "submission_id": ctx.submission_id,
        "appeal_type": "GUIDELINE_INTERPRETATION",
        "argument": (
            "The identifier is device-local and the disclosure already covers it."
        ),
        "cited_rejection_reason_ids": [reasons[0]["id"]],
    }

    set_clock(api, "2026-08-15T00:00:00Z")
    appeal = get_success_data(
        api.create_appeal_request(filing, ctx.compliance_officer)
    )
    withdrawn = validate_success(
        api.withdraw_appeal(
            appeal["id"],
            ctx.compliance_officer,
            {"reason_code": "DEVELOPER_RECONSIDERED"},
        ),
        200,
    )
    assert withdrawn["state"] == "WITHDRAWN"

    back = ctx.submission()
    assert back["state"] == "REJECTED"
    assert _at(back["rejected_at"]) == _at(DEFAULT_CLOCK)

    set_clock(api, "2026-08-15T00:00:01Z")
    validate_error(
        api.create_appeal_request(filing, ctx.compliance_officer),
        ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED,
        409,
    )
    assert ctx.submission()["state"] == "REJECTED"
