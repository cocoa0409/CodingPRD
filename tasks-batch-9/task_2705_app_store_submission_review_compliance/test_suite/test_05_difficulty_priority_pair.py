"""Difficulty rule: priority_pair_validation_conflict.

One request that satisfies two different refusal conditions at once, where the
declared validation priorities decide which code the caller actually sees.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_submission,
    assert_posture,
    create_behavior_finding_payload,
    create_submission_payload,
    get_success_data,
    privacy_item,
    set_clock,
    setup_base_ios,
    setup_two_accounts,
    validate_error,
    validate_paginated,
    validate_success,
)

BOGUS_SUBMISSION_ID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# occ_412_precedes_duplicate_build_409
# ---------------------------------------------------------------------------
def _setup_one_draft_build(api):
    """One app with exactly one DRAFT build 10, plus the now-stale AppRecord
    revision the client held before that build was created."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api, with_rule=False, with_submission=False, with_window=False
    )
    app_v1 = ctx.app_version()
    first = add_submission(ctx, build_number=10)
    return ctx, app_v1, first["id"]


def _create_build(api, ctx, expected_version, build_number):
    return api.create_submission(
        create_submission_payload(
            ctx.app_record_id,
            ctx.profile_id,
            expected_version,
            build_number=build_number,
            version_string="1.0.1",
        ),
        ctx.release_manager,
    )


def test_stale_app_record_version_is_reported_before_the_duplicate_build(api):
    """"Creating a submission requires `expected_app_record_version` to equal the current
    `version` of the `AppRecord` named by `app_record_id`. A mismatch is rejected with
    `ERR_STALE_APP_RECORD_VERSION` and HTTP 412."

    Design: Difficulty/priority_pair_validation_conflict/occ_412_precedes_duplicate_build_409
    """
    ctx, app_v1, _sub1_id = _setup_one_draft_build(api)

    validate_error(
        _create_build(api, ctx, app_v1, 10),
        ApiErrorId.ERR_STALE_APP_RECORD_VERSION,
        412,
    )


def test_fresh_revision_lets_the_duplicate_build_number_surface_as_409(api):
    """"The `build_number` must be strictly greater than the `build_number` of every
    existing submission of the same app whose state is not `DEVELOPER_WITHDRAWN`; anything
    else, equal or lower, is refused with `ERR_DUPLICATE_BUILD_NUMBER`."

    Design: Difficulty/priority_pair_validation_conflict/occ_412_precedes_duplicate_build_409
    """
    ctx, app_v1, _sub1_id = _setup_one_draft_build(api)
    validate_error(
        _create_build(api, ctx, app_v1, 10), ApiErrorId.ERR_STALE_APP_RECORD_VERSION
    )

    app_v2 = ctx.app_version()
    assert app_v2 != app_v1, "the first create already advanced the app record revision"

    validate_error(
        _create_build(api, ctx, app_v2, 10),
        ApiErrorId.ERR_DUPLICATE_BUILD_NUMBER,
        409,
    )
    second = validate_success(_create_build(api, ctx, app_v2, 11), 201)
    assert second["build_number"] == 11
    assert second["state"] == "DRAFT"


def test_neither_refused_create_advanced_the_revision_or_swept_the_draft(api):
    """"The guard exists because a new submission legitimately supersedes the app's other
    `DRAFT` submissions by moving them to `DEVELOPER_WITHDRAWN`; a stale expected value
    means the client's picture of the app's draft set, its posture or its live build is out
    of date, and the write would destroy work the client never saw."

    Design: Difficulty/priority_pair_validation_conflict/occ_412_precedes_duplicate_build_409
    """
    ctx, app_v1, sub1_id = _setup_one_draft_build(api)
    validate_error(
        _create_build(api, ctx, app_v1, 10), ApiErrorId.ERR_STALE_APP_RECORD_VERSION
    )
    app_v2 = ctx.app_version()
    validate_error(
        _create_build(api, ctx, app_v2, 10), ApiErrorId.ERR_DUPLICATE_BUILD_NUMBER
    )
    assert ctx.submission(sub1_id)["state"] == "DRAFT", (
        "a refused create must not sweep the existing draft"
    )

    second = validate_success(_create_build(api, ctx, app_v2, 11), 201)
    assert ctx.app_version() == app_v2 + 1
    assert ctx.submission(sub1_id)["state"] == "DEVELOPER_WITHDRAWN"
    assert ctx.submission(second["id"])["state"] == "DRAFT"

    rows, _meta = validate_paginated(
        api.list_submissions(
            ctx.release_manager, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 2, "the 412 and the 409 must not have left partial rows behind"


# ---------------------------------------------------------------------------
# frozen_posture_precedes_critical_finding
# ---------------------------------------------------------------------------
def _setup_frozen_with_two_findings(api):
    """A PRE_REVIEW_PASSED build declaring one PRECISE_LOCATION tuple, then one
    CRITICAL finding matching that tuple and one MINOR finding that matches nothing."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        declared_privacy_items=[
            privacy_item("PRECISE_LOCATION", "APP_FUNCTIONALITY", linked=True)
        ],
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
    )
    set_clock(api, "2026-08-01T06:00:00Z")
    critical = get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="PRECISE_LOCATION",
                observed_purpose="APP_FUNCTIONALITY",
                observed_linked_to_user=True,
                observed_tracking=False,
                endpoint_domain="geo.northwind.example",
                severity="CRITICAL",
                scanner_confidence=0.99,
                detected_at="2026-08-01T06:00:00Z",
            ),
            ctx.policy_admin,
        )
    )
    minor = get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="DEVICE_ID",
                observed_purpose="ADVERTISING",
                observed_linked_to_user=True,
                observed_tracking=True,
                severity="MINOR",
                scanner_confidence=0.9,
                detected_at="2026-08-01T06:00:00Z",
            ),
            ctx.policy_admin,
        )
    )
    return ctx, critical["id"], minor["id"]


def test_frozen_posture_is_reported_instead_of_the_unresolved_critical_finding(api):
    """"An app whose posture is frozen and whose submission also carries an unreconciled
    critical behaviour finding reports `ERR_APP_COMPLIANCE_FROZEN`, not
    `ERR_CRITICAL_FINDING_UNRESOLVED`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_precedes_critical_finding
    """
    ctx, _critical_id, _minor_id = _setup_frozen_with_two_findings(api)

    assert_posture(ctx.app(), "FROZEN", ["CRITICAL_FINDING_OPEN"])
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_FROZEN,
        409,
    )
    assert ctx.submission()["state"] == "PRE_REVIEW_PASSED"


def test_partial_tuple_match_refuses_reconcile_on_the_minor_finding(api):
    """"A partial match does not count: a declared tuple with the right data type but the
    wrong purpose, or with linked-to-user false where the scanner saw true, leaves the
    finding unreconciled and the request is refused with `ERR_DISCLOSURE_STILL_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_precedes_critical_finding
    """
    ctx, _critical_id, minor_id = _setup_frozen_with_two_findings(api)

    validate_error(
        api.triage_behavior_finding(
            minor_id, {"action": "RECONCILE"}, ctx.policy_admin
        ),
        ApiErrorId.ERR_DISCLOSURE_STILL_MISSING,
        409,
    )
    assert get_success_data(
        api.get_behavior_finding(minor_id, ctx.policy_admin)
    )["status"] == "OPEN"


def test_critical_finding_may_not_be_dismissed_while_a_minor_one_may(api):
    """"`DISMISS` is refused for a `CRITICAL` finding with `ERR_WAIVER_NOT_PERMITTED` — the
    platform may not simply wave away its own most serious evidence."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_precedes_critical_finding
    """
    ctx, critical_id, minor_id = _setup_frozen_with_two_findings(api)

    validate_error(
        api.triage_behavior_finding(
            critical_id,
            {"action": "DISMISS", "justification": "Scanner false positive per review"},
            ctx.policy_admin,
        ),
        ApiErrorId.ERR_WAIVER_NOT_PERMITTED,
        409,
    )
    dismissed = validate_success(
        api.triage_behavior_finding(
            minor_id,
            {"action": "DISMISS", "justification": "Third-party SDK removed in build 10"},
            ctx.policy_admin,
        ),
        200,
    )
    assert dismissed["status"] == "DISMISSED"
    assert_posture(ctx.app(), "FROZEN", ["CRITICAL_FINDING_OPEN"])


def test_dispute_keeps_the_freeze_and_only_reconcile_reopens_the_queue(api):
    """"The frozen tier has three codes: `ACCOUNT_NOT_IN_GOOD_STANDING` when the owning
    account's `program_status` is `SUSPENDED` or `TERMINATED`; `IMPACT_OVERDUE` when any
    impact assessment of this app is in status `OVERDUE`; and `CRITICAL_FINDING_OPEN` when
    any behaviour finding belonging to any submission of this app has severity `CRITICAL`
    and status `OPEN` or `DISPUTED`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_precedes_critical_finding
    """
    ctx, critical_id, _minor_id = _setup_frozen_with_two_findings(api)

    disputed = validate_success(
        api.triage_behavior_finding(
            critical_id,
            {
                "action": "DISPUTE",
                "justification": "Location access is foreground-only and disclosed",
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert disputed["status"] == "DISPUTED"
    assert_posture(ctx.app(), "FROZEN", ["CRITICAL_FINDING_OPEN"])
    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_FROZEN,
    )

    reconciled = validate_success(
        api.triage_behavior_finding(
            critical_id, {"action": "RECONCILE"}, ctx.policy_admin
        ),
        200,
    )
    assert reconciled["status"] == "RECONCILED"
    assert_posture(ctx.app(), "OPEN", [])

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["queued_at"] == "2026-08-01T06:00:00Z"
    assert queued["provisional_deadline_at"] == "2026-08-03T06:00:00Z"
    assert queued["review_window_id"] == ctx.window_id


# ---------------------------------------------------------------------------
# header_role_tenancy_existence_schema_ladder
# ---------------------------------------------------------------------------
GHOST_ROLE_HEADERS = {"X-User-Role": "StoreSuperAdmin", "X-User-ID": "u-ghost-1"}


def _setup_two_draft_builds(api):
    """Account A (Northwind) and account B (Eastgate), each with one DRAFT build."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_two_accounts(api)


def test_unknown_role_name_is_a_400_header_failure_never_a_403(api):
    """"If `X-User-Role` is absent or is not one of the seven names above, if `X-User-ID` is
    absent or empty, or if an account-backed role omits `X-Publisher-Account-Id` or sends it
    empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and
    HTTP 400 — never a 403, even when the role that would have been sent is not permitted on
    the endpoint in question."

    Design: Difficulty/priority_pair_validation_conflict/header_role_tenancy_existence_schema_ladder
    """
    _a, _b = _setup_two_draft_builds(api)

    validate_error(
        api.queue_submission(BOGUS_SUBMISSION_ID, GHOST_ROLE_HEADERS),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        400,
    )


def test_unauthorised_role_naming_a_missing_submission_is_403_not_404(api):
    """"That permission check deliberately precedes resource lookup: a request from an
    unauthorised role that also names a non-existent identifier returns 403
    `ERR_ROLE_NOT_PERMITTED`, never 404, because resource existence must not leak to callers
    who have no business asking."

    Design: Difficulty/priority_pair_validation_conflict/header_role_tenancy_existence_schema_ladder
    """
    a, _b = _setup_two_draft_builds(api)

    validate_error(
        api.queue_submission(BOGUS_SUBMISSION_ID, a.compliance_officer),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_unknown_body_field_on_a_missing_submission_is_404_not_422(api):
    """"Note the rung order: a malformed body sent to a non-existent submission returns 404,
    not 422."

    Design: Difficulty/priority_pair_validation_conflict/header_role_tenancy_existence_schema_ladder
    """
    a, _b = _setup_two_draft_builds(api)

    validate_error(
        api.queue_submission(
            BOGUS_SUBMISSION_ID, a.release_manager, {"unknown_field": 1}
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_FOUND,
        404,
    )


def test_tenancy_precedes_existence_so_a_foreign_build_answers_403(api):
    """"An identifier that resolves to a row belonging to a different account is rejected
    with `ERR_CROSS_ACCOUNT_ACCESS_DENIED` and HTTP 403 — and note the ordering: tenancy
    precedes existence, so a resolvable identifier owned by somebody else is a 403, while an
    identifier that resolves to nothing at all is a 404."

    Design: Difficulty/priority_pair_validation_conflict/header_role_tenancy_existence_schema_ladder
    """
    a, b = _setup_two_draft_builds(api)

    validate_error(
        api.queue_submission(b.submission_id, a.release_manager),
        ApiErrorId.ERR_CROSS_ACCOUNT_ACCESS_DENIED,
        403,
    )


def test_the_ladder_bottoms_out_at_409_with_nothing_mutated(api):
    """"Each state machine has its own 409 code, and the response always uses the code of the
    entity named in the path: `ERR_INVALID_SUBMISSION_STATE`, `ERR_INVALID_LISTING_STATE`,
    `ERR_INVALID_DISTRIBUTION_STATE`, `ERR_INVALID_CREDENTIAL_STATE`,
    `ERR_INVALID_ROLLOUT_STATE`, `ERR_INVALID_GUIDELINE_STATE`, `ERR_INVALID_MAPPING_STATE`,
    `ERR_INVALID_IMPACT_STATE`, `ERR_INVALID_APPEAL_STATE`, `ERR_INVALID_EXPEDITE_STATE`,
    `ERR_INVALID_COMMERCE_ITEM_STATE` and `ERR_INVALID_FINDING_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/header_role_tenancy_existence_schema_ladder
    """
    a, b = _setup_two_draft_builds(api)

    validate_error(
        api.queue_submission(BOGUS_SUBMISSION_ID, GHOST_ROLE_HEADERS),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    )
    validate_error(
        api.queue_submission(BOGUS_SUBMISSION_ID, a.compliance_officer),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.queue_submission(b.submission_id, a.release_manager),
        ApiErrorId.ERR_CROSS_ACCOUNT_ACCESS_DENIED,
    )
    validate_error(
        api.queue_submission(a.submission_id, a.release_manager),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        409,
    )

    assert a.submission()["state"] == "DRAFT"
    assert b.submission()["state"] == "DRAFT"
    windows, _meta = validate_paginated(
        api.list_review_capacity_windows(a.policy_admin)
    )
    assert windows == [], "no queue attempt may have reached capacity allocation"
