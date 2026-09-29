"""Corner section: rbac.

Peer-role exclusivity, the read-only Auditor, cross-account walls and all six
segregation-of-duties comparisons.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    age_rating_answers,
    assert_decimal_equals,
    assert_posture,
    create_appeal_request_payload,
    create_commerce_item_payload,
    create_expedite_request_payload,
    create_feature_mapping_payload,
    create_guideline_rule_payload,
    create_signing_credential_payload,
    create_submission_payload,
    get_success_data,
    make_appeal_board_headers,
    make_policy_admin_headers,
    make_reviewer_headers,
    new_account,
    rejection_reasons_for,
    set_clock,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# the_three_publisher_roles_cannot_reach_into_each_others_exclusive_steps
# ---------------------------------------------------------------------------
def _setup_draft_build(api):
    """BASE-IOS stopped at a DRAFT build: three publisher operators on one
    account, two signing credentials, one PASSED mapping and one submission."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        api, with_content=False, with_window=False, with_pre_review=False
    )


def test_each_publisher_role_is_refused_the_step_that_belongs_to_a_peer(api):
    """"Once the headers are well-formed, the role is checked against the endpoint's
    authorised role list in §4; a role that does not appear there is rejected with
    `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    Design: Corner/rbac/the_three_publisher_roles_cannot_reach_into_each_others_exclusive_steps
    """
    ctx = _setup_draft_build(api)

    validate_error(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                ctx.app_version(),
                build_number=101,
                version_string="4.2.1",
            ),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.publisher_admin),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_signing_credential(
            create_signing_credential_payload(ctx.account_id, ctx.account_version()),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_the_refused_peer_calls_leave_every_row_exactly_as_it_was(api):
    """"A `ComplianceOfficer` owns guideline mapping, pre-submission self-review, the
    privacy declaration, rejection responses, appeals and impact remediation, and may
    neither create builds, nor queue them for review, nor start a rollout."

    Design: Corner/rbac/the_three_publisher_roles_cannot_reach_into_each_others_exclusive_steps
    """
    ctx = _setup_draft_build(api)

    validate_error(
        api.create_submission(
            create_submission_payload(
                ctx.app_record_id,
                ctx.profile_id,
                ctx.app_version(),
                build_number=101,
                version_string="4.2.1",
            ),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.publisher_admin),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_signing_credential(
            create_signing_credential_payload(ctx.account_id, ctx.account_version()),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    _mappings, mapping_meta = validate_paginated(
        api.list_feature_mappings(
            ctx.compliance_officer, {"app_record_id": ctx.app_record_id}
        )
    )
    assert mapping_meta["total_count"] == 1
    _subs, sub_meta = validate_paginated(
        api.list_submissions(
            ctx.release_manager, {"app_record_id": ctx.app_record_id}
        )
    )
    assert sub_meta["total_count"] == 1
    assert ctx.submission()["state"] == "DRAFT"
    _creds, cred_meta = validate_paginated(
        api.list_signing_credentials(
            ctx.publisher_admin, {"publisher_account_id": ctx.account_id}
        )
    )
    assert cred_meta["total_count"] == 2


# ---------------------------------------------------------------------------
# the_auditor_reads_everything_and_may_mutate_nothing_not_even_remediation
# ---------------------------------------------------------------------------
def _setup_remediation_required(api):
    """One PASSED mapping staled by a successor rule, its impact assessment worked
    as far as REMEDIATION_REQUIRED by the account's own officer."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, with_submission=False, with_window=False)
    successor = get_success_data(
        api.create_guideline_rule(
            create_guideline_rule_payload(
                title="Account Deletion In App",
                category="PRIVACY",
                version_label="2026.09",
                effective_from=DEFAULT_CLOCK,
                supersedes_rule_id=ctx.rules["privacy"],
            ),
            ctx.policy_admin,
        )
    )
    get_success_data(api.publish_guideline_rule(successor["id"], ctx.policy_admin))
    assessments, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, {"app_record_id": ctx.app_record_id}
        )
    )
    assessment_id = assessments[0]["id"]
    get_success_data(
        api.assess_impact(assessment_id, {"action": "START"}, ctx.compliance_officer)
    )
    get_success_data(
        api.assess_impact(
            assessment_id,
            {
                "action": "REQUIRE_REMEDIATION",
                "note": "The deletion flow must be reworked for the new wording.",
            },
            ctx.compliance_officer,
        )
    )
    return ctx, assessment_id


def test_the_auditor_reads_the_oversight_views_of_an_account_it_does_not_belong_to(api):
    """"The four platform roles skip the tenancy rule entirely and address every
    account."

    Design: Corner/rbac/the_auditor_reads_everything_and_may_mutate_nothing_not_even_remediation
    """
    ctx, _assessment_id = _setup_remediation_required(api)

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.auditor), 200
    )
    assert summary["mapping_stale"] == 1
    assert summary["open_impact_count"] == 1
    assert_posture(
        summary,
        "RESTRICTED",
        ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"],
    )

    standing = validate_success(api.get_standing(ctx.account_id, ctx.auditor), 200)
    assert_decimal_equals(standing["standing_score_rolling_365"], 100.00, 2, "rolling")


def test_the_auditor_is_refused_every_mutation_including_remediation(api):
    """"On the platform side, a `PlatformReviewer` claims and decides builds and reviews
    commerce items; a `PlatformAppealBoard` operator hears appeals and rules on
    expedited-review quota; a `PlatformPolicyAdmin` owns the guideline corpus, the
    scanner findings, reviewer capacity, account enforcement and the platform-side
    emergency controls; and an `Auditor` holds read-only oversight across every account
    with no mutating permission whatsoever, including the remediation endpoints."

    Design: Corner/rbac/the_auditor_reads_everything_and_may_mutate_nothing_not_even_remediation
    """
    ctx, assessment_id = _setup_remediation_required(api)
    mapping_id = ctx.mappings["privacy"]

    validate_error(
        api.assess_impact(
            assessment_id, {"action": "MARK_REMEDIATED"}, ctx.auditor
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.self_review_mapping(
            mapping_id,
            {"outcome": "PASS", "evidence_ref": "audit/forced.pdf"},
            ctx.auditor,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.triage_behavior_finding(
            "00000000-0000-4000-8000-000000000404",
            {"action": "RECONCILE"},
            ctx.auditor,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assessment = validate_success(
        api.get_impact_assessment(assessment_id, ctx.auditor), 200
    )
    assert assessment["status"] == "REMEDIATION_REQUIRED"
    assert ctx.mapping(mapping_id)["self_review_status"] == "STALE"


# ---------------------------------------------------------------------------
# the_age_rating_write_is_shared_by_two_roles_while_the_privacy_write_is_not
# ---------------------------------------------------------------------------
def _setup_declared_draft(api):
    """BASE-IOS with the locale and both content declarations already recorded by
    the officer, left in DRAFT so the declarations can be rewritten."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(api, with_pre_review=False)


def _age_rating_payload():
    return {"age_rating_answers": age_rating_answers(), "attested_age_rating": 4}


def test_both_publisher_roles_may_record_the_content_questionnaire(api):
    """"A `ComplianceOfficer` or a `ReleaseManager` sets a submission's content
    questionnaire by supplying `age_rating_answers` and an `attested_age_rating`."

    Design: Corner/rbac/the_age_rating_write_is_shared_by_two_roles_while_the_privacy_write_is_not
    """
    ctx = _setup_declared_draft(api)

    by_manager = validate_success(
        api.set_age_rating(
            ctx.submission_id, _age_rating_payload(), ctx.release_manager
        ),
        200,
    )
    by_officer = validate_success(
        api.set_age_rating(
            ctx.submission_id, _age_rating_payload(), ctx.compliance_officer
        ),
        200,
    )
    for data in (by_manager, by_officer):
        assert data["derived_age_rating"] == 0
        assert data["attested_age_rating"] == 4


def test_only_the_officer_may_record_the_privacy_declaration(api):
    """"Separately a `ComplianceOfficer` sets the privacy label by supplying
    `declared_privacy_items` — an array of tuples each naming a `data_type`, a purpose,
    whether the collection is linked to a user identity, and whether it is used for
    cross-app tracking — together with `tracking_consent_prompt_present`, the publisher's
    assertion that the binary actually shows a consent prompt."

    Design: Corner/rbac/the_age_rating_write_is_shared_by_two_roles_while_the_privacy_write_is_not
    """
    ctx = _setup_declared_draft(api)
    body = {"declared_privacy_items": [], "tracking_consent_prompt_present": False}

    validate_error(
        api.set_privacy_declaration(ctx.submission_id, body, ctx.release_manager),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    accepted = validate_success(
        api.set_privacy_declaration(ctx.submission_id, body, ctx.compliance_officer),
        200,
    )
    assert accepted["tracking_consent_prompt_present"] is False
    assert accepted["declared_privacy_items"] == []


# ---------------------------------------------------------------------------
# only_the_claiming_reviewer_may_decide_the_build_it_claimed
# ---------------------------------------------------------------------------
def _setup_claimed_by_first_reviewer(api):
    """BASE-IOS queued and claimed by the reviewer u-reviewer-1."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    return ctx


def test_a_second_reviewer_is_refused_the_decision_with_a_conflict_not_a_forbidden(api):
    """"Concretely: recording a review decision on a submission requires that the acting
    `X-User-ID` **equals** that submission's `reviewed_by_user_id` — only the reviewer who
    claimed the build may decide it — and simultaneously that it **differs** from that
    submission's `attested_by_user_id`, so the publisher-side operator who attested the
    pre-review can never also decide the build."

    Design: Corner/rbac/only_the_claiming_reviewer_may_decide_the_build_it_claimed
    """
    ctx = _setup_claimed_by_first_reviewer(api)

    validate_error(
        api.decide_submission(
            ctx.submission_id,
            {"outcome": "APPROVE"},
            make_reviewer_headers("u-reviewer-2"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )

    submission = ctx.submission()
    assert submission["state"] == "IN_REVIEW"
    assert submission["reviewed_by_user_id"] == "u-reviewer-1"


def test_the_claiming_reviewer_then_decides_the_same_build(api):
    """"A violation is `ERR_SEGREGATION_OF_DUTIES_VIOLATION` with HTTP 409, and it is
    evaluated after the posture and program-status rungs but before any business rule."

    Design: Corner/rbac/only_the_claiming_reviewer_may_decide_the_build_it_claimed
    """
    ctx = _setup_claimed_by_first_reviewer(api)

    validate_error(
        api.decide_submission(
            ctx.submission_id,
            {"outcome": "APPROVE"},
            make_reviewer_headers("u-reviewer-2"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    )
    approved = validate_success(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        200,
    )
    assert approved["state"] == "APPROVED"


# ---------------------------------------------------------------------------
# the_officer_who_attested_the_build_may_never_decide_it_even_as_a_reviewer
# ---------------------------------------------------------------------------
ATTESTING_OFFICER_ID = "u-compliance-1"


def _setup_queued_attested_build(api):
    """BASE-IOS whose pre-review was attested by u-compliance-1, then queued."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    return ctx


def test_the_attesting_officer_may_still_claim_the_build_as_a_reviewer(api):
    """"When at least one code is recorded the submission stays in `DRAFT` with
    `pre_review_passed` false; when the array comes back empty the submission moves
    `DRAFT → PRE_REVIEW_PASSED`, `pre_review_passed` becomes true, and
    `attested_by_user_id` is stamped with the acting officer, who thereby becomes the
    subject of the segregation-of-duties rule at the decision gate."

    Design: Corner/rbac/the_officer_who_attested_the_build_may_never_decide_it_even_as_a_reviewer
    """
    ctx = _setup_queued_attested_build(api)
    assert ctx.submission()["attested_by_user_id"] == ATTESTING_OFFICER_ID

    claimed = validate_success(
        api.claim_submission(
            ctx.submission_id, make_reviewer_headers(ATTESTING_OFFICER_ID)
        ),
        200,
    )
    assert claimed["state"] == "IN_REVIEW"
    assert claimed["reviewed_by_user_id"] == ATTESTING_OFFICER_ID


def test_the_attesting_officer_is_refused_the_decision_it_now_owns_the_claim_for(api):
    """"Six operations judge an artifact somebody else produced, and in each of them the
    acting `X-User-ID` must be distinct from — or, in one case, identical to — an operator
    identifier already recorded on the artifact."

    Design: Corner/rbac/the_officer_who_attested_the_build_may_never_decide_it_even_as_a_reviewer
    """
    ctx = _setup_queued_attested_build(api)
    officer_as_reviewer = make_reviewer_headers(ATTESTING_OFFICER_ID)
    get_success_data(api.claim_submission(ctx.submission_id, officer_as_reviewer))

    validate_error(
        api.decide_submission(
            ctx.submission_id, {"outcome": "APPROVE"}, officer_as_reviewer
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )
    assert ctx.submission()["state"] == "IN_REVIEW"


# ---------------------------------------------------------------------------
# the_reviewer_who_rejected_the_build_may_neither_take_up_nor_judge_the_appeal
# ---------------------------------------------------------------------------
def _setup_open_appeal(api):
    """A build rejected by u-reviewer-1 on one CONTESTED CRITICAL reason, with the
    officer's appeal filed and the submission in APPEAL_PENDING."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    get_success_data(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(
                    ctx.rules["privacy"],
                    reason_code="PRIVACY_LABEL_MISMATCH",
                    detail="Undisclosed device identifier collection in build 10.",
                ),
            },
            ctx.reviewer,
        )
    )
    reasons, _meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, {"submission_id": ctx.submission_id}
        )
    )
    reason_id = reasons[0]["id"]
    get_success_data(
        api.respond_to_rejection_reason(
            reason_id,
            {
                "disposition": "CONTESTED",
                "developer_response": (
                    "The identifier never leaves the device and the label already "
                    "covers the DEVICE_ID disclosure."
                ),
            },
            ctx.compliance_officer,
        )
    )
    appeal = get_success_data(
        api.create_appeal_request(
            create_appeal_request_payload(ctx.submission_id, [reason_id]),
            ctx.compliance_officer,
        )
    )
    return ctx, appeal["id"]


def test_the_rejecting_reviewer_cannot_take_the_appeal_up_but_the_board_can(api):
    """"Taking an appeal up for board review, and deciding it, both require that the
    acting `X-User-ID` differs from the `reviewed_by_user_id` of the submission under
    appeal: the reviewer who rejected a build may neither review nor judge the appeal
    against that rejection."

    Design: Corner/rbac/the_reviewer_who_rejected_the_build_may_neither_take_up_nor_judge_the_appeal
    """
    ctx, appeal_id = _setup_open_appeal(api)

    validate_error(
        api.board_review_appeal(appeal_id, make_appeal_board_headers("u-reviewer-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )
    assert (
        get_success_data(api.get_appeal_request(appeal_id, ctx.compliance_officer))[
            "state"
        ]
        == "SUBMITTED"
    )

    taken_up = validate_success(
        api.board_review_appeal(appeal_id, ctx.appeal_board), 200
    )
    assert taken_up["state"] == "BOARD_REVIEW"
    assert taken_up["board_started_at"] == DEFAULT_CLOCK


def test_the_rejecting_reviewer_cannot_judge_the_appeal_either(api):
    """"A `PlatformAppealBoard` operator takes the appeal into `BOARD_REVIEW`, which
    requires the submission to be `APPEAL_PENDING` and stamps `board_started_at`, and then
    decides with an `outcome` of `OVERTURNED`, `PARTIALLY_OVERTURNED` or `UPHELD`, a
    `rationale`, and for the partial branch an `overturned_rejection_reason_ids` array."

    Design: Corner/rbac/the_reviewer_who_rejected_the_build_may_neither_take_up_nor_judge_the_appeal
    """
    ctx, appeal_id = _setup_open_appeal(api)
    get_success_data(api.board_review_appeal(appeal_id, ctx.appeal_board))

    validate_error(
        api.decide_appeal(
            appeal_id,
            {
                "outcome": "UPHELD",
                "rationale": "The identifier is not device-local after all.",
            },
            make_appeal_board_headers("u-reviewer-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )
    appeal = get_success_data(api.get_appeal_request(appeal_id, ctx.compliance_officer))
    assert appeal["state"] == "BOARD_REVIEW"
    assert ctx.submission()["state"] == "APPEAL_PENDING"


# ---------------------------------------------------------------------------
# the_rejecting_reviewer_cannot_grant_the_expedite_but_the_board_can
# ---------------------------------------------------------------------------
def _setup_rejected_build_with_expedite(api):
    """A build rejected by u-reviewer-1, with a fresh expedite request filed against
    it by the release manager."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    get_success_data(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(
                    ctx.rules["privacy"],
                    reason_code="PRIVACY_LABEL_MISMATCH",
                    detail="Undisclosed device identifier collection in build 10.",
                ),
            },
            ctx.reviewer,
        )
    )
    # The reject cascade failed the cited mapping and restricted the posture; creating an
    # expedite request is restricted-blocked, so the publisher re-attests first.
    get_success_data(
        api.self_review_mapping(
            ctx.mappings["privacy"], {"outcome": "PASS"}, ctx.compliance_officer
        )
    )
    request = validate_success(
        api.create_expedite_request(
            create_expedite_request_payload(
                ctx.submission_id,
                justification_category="SECURITY_FIX",
                justification="Patches a token leak reported by an outside researcher.",
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert request["state"] == "REQUESTED"
    return ctx, request["id"]


def test_the_rejecting_reviewer_is_refused_the_expedite_grant_and_spends_nothing(api):
    """"Deciding an expedite request requires the same distinction from the cited
    submission's `reviewed_by_user_id`."

    Design: Corner/rbac/the_rejecting_reviewer_cannot_grant_the_expedite_but_the_board_can
    """
    ctx, expedite_id = _setup_rejected_build_with_expedite(api)

    validate_error(
        api.decide_expedite_request(
            expedite_id,
            {"outcome": "GRANT", "decision_rationale": "Self-granted."},
            make_appeal_board_headers("u-reviewer-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )

    assert (
        get_success_data(api.get_expedite_request(expedite_id, ctx.release_manager))[
            "state"
        ]
        == "REQUESTED"
    )
    assert ctx.account()["expedite_credits_remaining"] == 2


def test_the_board_grants_the_same_expedite_request_and_spends_one_credit(api):
    """"`GRANT` moves `REQUESTED → GRANTED`, stamps `granted_at`, records
    `decided_by_user_id`, and decreases `expedite_credits_remaining` by exactly one; it is
    refused with `ERR_EXPEDITE_QUOTA_EXHAUSTED` when no credit remains and with
    `ERR_STANDING_TOO_LOW` when standing has since fallen below the floor, and the
    deciding operator must differ from the submission's `reviewed_by_user_id`."

    Design: Corner/rbac/the_rejecting_reviewer_cannot_grant_the_expedite_but_the_board_can
    """
    ctx, expedite_id = _setup_rejected_build_with_expedite(api)
    validate_error(
        api.decide_expedite_request(
            expedite_id,
            {"outcome": "GRANT", "decision_rationale": "Self-granted."},
            make_appeal_board_headers("u-reviewer-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    )

    granted = validate_success(
        api.decide_expedite_request(
            expedite_id,
            {
                "outcome": "GRANT",
                "decision_rationale": "Security fix accepted for expedited handling.",
            },
            ctx.appeal_board,
        ),
        200,
    )
    assert granted["state"] == "GRANTED"
    assert granted["granted_at"] == DEFAULT_CLOCK
    assert ctx.account()["expedite_credits_remaining"] == 1


# ---------------------------------------------------------------------------
# whoever_attested_the_self_review_may_not_be_the_one_to_waive_it
# ---------------------------------------------------------------------------
WAIVER_REASON = "Compensating control accepted by platform policy review."


def _setup_failed_mapping(api):
    """BASE-IOS whose single PRIVACY mapping was failed by u-compliance-1."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        api, mapping_advance="FAIL", with_submission=False, with_window=False
    )


def test_the_attester_cannot_waive_the_mapping_it_attested(api):
    """"Waiving a feature mapping requires that the acting `X-User-ID` differs from that
    mapping's `attested_by_user_id`, so whoever attested a self-review may not waive that
    same mapping."

    Design: Corner/rbac/whoever_attested_the_self_review_may_not_be_the_one_to_waive_it
    """
    ctx = _setup_failed_mapping(api)
    mapping_id = ctx.mappings["privacy"]
    assert ctx.mapping(mapping_id)["attested_by_user_id"] == ATTESTING_OFFICER_ID

    validate_error(
        api.waive_mapping(
            mapping_id,
            {"waiver_reason": WAIVER_REASON},
            make_policy_admin_headers(ATTESTING_OFFICER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )
    assert ctx.mapping(mapping_id)["self_review_status"] == "FAILED"
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 0.00, 2, "index")


def test_a_different_policy_admin_waives_the_failed_mapping_to_full_compliance(api):
    """"A waiver clears `staled_by_rule_id`, stamps `attested_at`, and recomputes the
    app's index and posture; a waived mapping counts as fully compliant for index
    purposes."

    Design: Corner/rbac/whoever_attested_the_self_review_may_not_be_the_one_to_waive_it
    """
    ctx = _setup_failed_mapping(api)
    mapping_id = ctx.mappings["privacy"]
    validate_error(
        api.waive_mapping(
            mapping_id,
            {"waiver_reason": WAIVER_REASON},
            make_policy_admin_headers(ATTESTING_OFFICER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    )

    waived = validate_success(
        api.waive_mapping(
            mapping_id, {"waiver_reason": WAIVER_REASON}, ctx.policy_admin
        ),
        200,
    )
    assert waived["self_review_status"] == "WAIVED_BY_PLATFORM"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, 2, "index")
    assert_posture(app, "OPEN", [])


# ---------------------------------------------------------------------------
# the_commerce_mapping_attester_is_barred_from_reviewing_that_apps_commerce_item
# ---------------------------------------------------------------------------
def _setup_commerce_item_awaiting_review(api):
    """A distributing app that also carries a PASSED COMMERCE-category mapping
    attested by u-compliance-1, plus one SUBMITTED commerce item."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(api)
    commerce_rule = get_success_data(
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
    get_success_data(api.publish_guideline_rule(commerce_rule["id"], ctx.policy_admin))
    mapping = get_success_data(
        api.create_feature_mapping(
            create_feature_mapping_payload(
                ctx.app_record_id,
                commerce_rule["id"],
                feature_code="IN_APP_PURCHASE",
            ),
            ctx.compliance_officer,
        )
    )
    get_success_data(
        api.self_review_mapping(
            mapping["id"], {"outcome": "START"}, ctx.compliance_officer
        )
    )
    attested = get_success_data(
        api.self_review_mapping(
            mapping["id"],
            {"outcome": "PASS", "evidence_ref": "audit/iap-2026-08.pdf"},
            ctx.compliance_officer,
        )
    )
    assert attested["self_review_status"] == "PASSED"
    assert attested["attested_by_user_id"] == ATTESTING_OFFICER_ID
    item = get_success_data(
        api.create_commerce_item(
            create_commerce_item_payload(
                ctx.app_record_id,
                reference_name="Coin Pack 500",
                price_tier_cents=2000,
            ),
            ctx.publisher_admin,
        )
    )
    submitted = validate_success(
        api.submit_commerce_item(item["id"], ctx.publisher_admin), 200
    )
    assert submitted["status"] == "SUBMITTED"
    return ctx, item["id"]


def test_the_commerce_attester_cannot_review_the_apps_commerce_item(api):
    """"Reviewing a commerce item requires that the acting `X-User-ID` differs from the
    `attested_by_user_id` of any commerce-category feature mapping of the same app record."

    Design: Corner/rbac/the_commerce_mapping_attester_is_barred_from_reviewing_that_apps_commerce_item
    """
    ctx, item_id = _setup_commerce_item_awaiting_review(api)
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 100.00, 2, "index")

    validate_error(
        api.review_commerce_item(
            item_id,
            {"outcome": "APPROVE"},
            make_reviewer_headers(ATTESTING_OFFICER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )
    assert (
        get_success_data(api.get_commerce_item(item_id, ctx.publisher_admin))["status"]
        == "SUBMITTED"
    )


def test_an_unconflicted_reviewer_approves_the_identical_commerce_item(api):
    """"`APPROVE` moves `SUBMITTED → APPROVED` and recomputes `commission_rate_applied`
    and `commission_cents` from whatever gross is already stored; `REJECT` moves
    `SUBMITTED → REJECTED` and requires a non-empty `rejection_note`, otherwise
    `ERR_VALIDATION`."

    Design: Corner/rbac/the_commerce_mapping_attester_is_barred_from_reviewing_that_apps_commerce_item
    """
    ctx, item_id = _setup_commerce_item_awaiting_review(api)
    validate_error(
        api.review_commerce_item(
            item_id,
            {"outcome": "APPROVE"},
            make_reviewer_headers(ATTESTING_OFFICER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    )

    approved = validate_success(
        api.review_commerce_item(
            item_id, {"outcome": "APPROVE"}, make_reviewer_headers("u-reviewer-2")
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert_decimal_equals(approved["commission_rate_applied"], 0.30, 2, "rate")


# ---------------------------------------------------------------------------
# delist_is_the_only_listing_action_the_platform_may_take_and_it_leaves_distribution_alone
# ---------------------------------------------------------------------------
def _setup_distributing_draft_listing(api):
    """A PHASE_ACTIVE phased rollout at phase 0, with the listing still in DRAFT."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_released_ios(api)


def test_the_platform_may_not_complete_the_metadata_step(api):
    """"The listing dimension is driven by exactly one operation, available to a
    `PublisherAdmin` and, in one narrow case, to a `PlatformPolicyAdmin`."

    Design: Corner/rbac/delist_is_the_only_listing_action_the_platform_may_take_and_it_leaves_distribution_alone
    """
    ctx = _setup_distributing_draft_listing(api)

    validate_error(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "COMPLETE_METADATA"}, ctx.policy_admin
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    assert ctx.app()["listing_state"] == "DRAFT"


def test_the_platform_delist_leaves_the_running_rollout_untouched(api):
    """"`DELIST` moves `LISTED → DELISTED` with no preconditions at all, and is the only
    listing action a `PlatformPolicyAdmin` may take."

    Design: Corner/rbac/delist_is_the_only_listing_action_the_platform_may_take_and_it_leaves_distribution_alone
    """
    ctx = _setup_distributing_draft_listing(api)

    completed = validate_success(
        api.drive_listing(
            ctx.app_record_id,
            {"listing_action": "COMPLETE_METADATA"},
            ctx.publisher_admin,
        ),
        200,
    )
    assert completed["listing_state"] == "METADATA_COMPLETE"
    listed = validate_success(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "LIST"}, ctx.publisher_admin
        ),
        200,
    )
    assert listed["listing_state"] == "LISTED"

    delisted = validate_success(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "DELIST"}, ctx.policy_admin
        ),
        200,
    )
    assert delisted["listing_state"] == "DELISTED"
    assert delisted["distribution_state"] == "PHASED_ROLLOUT"
    assert_decimal_equals(delisted["released_share_pct"], 1.00, 2, "released")
    assert_decimal_equals(delisted["held_back_share_pct"], 99.00, 2, "held back")
    assert ctx.plan()["state"] == "PHASE_ACTIVE"


# ---------------------------------------------------------------------------
# platform_roles_read_across_accounts_where_publisher_roles_are_walled_off
# ---------------------------------------------------------------------------
def _setup_two_walled_accounts(api):
    """Account A owning one app record, and an unrelated enrolled account B."""
    set_clock(api, DEFAULT_CLOCK)
    a = setup_base_ios(
        api,
        with_rule=False,
        with_submission=False,
        with_window=False,
        with_pre_review=False,
    )
    b = new_account(api, suffix="2", legal_name="Second Studio SARL")
    return a, b


def test_every_platform_role_reads_another_accounts_app_record(api):
    """"The four platform-side roles — `PlatformReviewer`, `PlatformAppealBoard`,
    `PlatformPolicyAdmin` and `Auditor` — carry an **opaque** identity: their `X-User-ID`
    is an operator identifier not tied to any persisted entity, they do not send
    `X-Publisher-Account-Id`, and the server never compares their `X-User-ID` to any
    entity's `id`."

    Design: Corner/rbac/platform_roles_read_across_accounts_where_publisher_roles_are_walled_off
    """
    a, _b = _setup_two_walled_accounts(api)

    for headers in (a.reviewer, a.policy_admin, a.auditor):
        data = validate_success(api.get_app_record(a.app_record_id, headers), 200)
        assert data["id"] == a.app_record_id


def test_the_other_publishers_list_is_narrowed_while_its_by_id_read_is_refused(api):
    """"An identifier that resolves to a row belonging to a different account is rejected
    with `ERR_CROSS_ACCOUNT_ACCESS_DENIED` and HTTP 403 — and note the ordering: tenancy
    precedes existence, so a resolvable identifier owned by somebody else is a 403, while
    an identifier that resolves to nothing at all is a 404."

    Design: Corner/rbac/platform_roles_read_across_accounts_where_publisher_roles_are_walled_off
    """
    a, b = _setup_two_walled_accounts(api)

    rows, meta = validate_paginated(
        api.list_app_records(b.publisher_admin, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert rows == []

    validate_error(
        api.get_app_record(a.app_record_id, b.publisher_admin),
        ApiErrorId.ERR_CROSS_ACCOUNT_ACCESS_DENIED,
        403,
    )
