"""Counselor training currency and session assignment/start gates
(PRD §3.1, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_caller,
    create_counselor,
    create_jurisdiction,
    create_script_payload,
    get_session,
    intake_session,
    make_counselor_headers,
    record_training,
    setup_hotline,
    validate_error,
    validate_success,
)


def test_counselor_training_append_threshold(api):
    """PRD §3.1: "When the `score` is at least 80 and the named script is
    `PUBLISHED` or `SUPERSEDED`, the script id is appended to the counselor's
    `trained_script_ids`, idempotently within the array."

    Design: Corner/entities/counselor_training_append_threshold
    """
    bundle = setup_hotline(train_worker=False)
    worker = bundle["worker"]
    script = bundle["script"]

    below = record_training(worker["id"], script["id"], score=70)
    assert below["trained_script_ids"] == [], (
        "score 70 is below the pass threshold of 80 — no append"
    )
    passed = record_training(worker["id"], script["id"], score=90)
    assert passed["trained_script_ids"] == [script["id"]], (
        "score 90 appends the script id exactly once"
    )


def test_counselor_cannot_record_training(api):
    """PRD §3.1: "Training is recorded per script version: a `HotlineSupervisor`
    submits the `script_id` and the achieved `score`, and the acting supervisor's
    identifier must differ from the subject counselor's (`ERR_FORBIDDEN` otherwise)."
    PRD §2.10: "The role must be admitted by the endpoint, transition-level actor
    restrictions apply (de-escalation, closure, and retirement transitions are
    supervisor-only), a `Caller` may act only on their own record, a counselor may
    submit or withdraw only their own scripts, and the actor recording a training
    certification must differ from the subject counselor — otherwise
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/counselor_cannot_record_training
    """
    jur = create_jurisdiction()
    author = create_counselor(display_name="Author A")
    script = validate_success(api.create_script(
        create_script_payload(jur["id"], "EVICTION", version_no=1, body="script v1"),
        make_counselor_headers(author["id"]),
    ), expected_status=201)

    resp = api.create_training_certification(
        author["id"], {"script_id": script["id"], "score": 95},
        make_counselor_headers(author["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = validate_success(
        api.get_counselor(author["id"], TEST_USERS["agency_admin_headers"])
    )
    assert current["trained_script_ids"] == []


def test_assign_suspended_counselor_rejected(api):
    """PRD §3.5: "Four gates apply: the counselor must be `ACTIVE`
    (`ERR_COUNSELOR_INACTIVE`); the counselor's `certification_expires_at` must lie
    after the current logical time (`ERR_CERTIFICATION_EXPIRED`); the counselor's
    `certified_jurisdiction_codes` must contain the session jurisdiction's `code`
    and `certified_categories` must contain the session's `issue_category`, with a
    wrong certification scope rejected as `ERR_INVALID_REQUEST`; and a `PUBLISHED`
    script must exist for the session's (`jurisdiction_id`, `issue_category`) pair
    whose id appears in the counselor's `trained_script_ids`
    (`ERR_TRAINING_NOT_CURRENT`)."

    Design: Corner/state_machines/assign_suspended_counselor_rejected
    """
    bundle = setup_hotline()
    validate_success(api.update_counselor(
        bundle["worker"]["id"], {"status": "SUSPENDED"},
        TEST_USERS["agency_admin_headers"],
    ))
    caller = create_caller()
    session = intake_session(bundle, caller)

    resp = api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        TEST_USERS["supervisor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_COUNSELOR_INACTIVE)
    current = get_session(bundle, session["id"])
    assert current["session_status"] == "QUEUED"
    assert current.get("counselor_id") is None


def test_assign_expired_certification_rejected(api):
    """PRD §3.5: "Four gates apply: the counselor must be `ACTIVE`
    (`ERR_COUNSELOR_INACTIVE`); the counselor's `certification_expires_at` must lie
    after the current logical time (`ERR_CERTIFICATION_EXPIRED`); the counselor's
    `certified_jurisdiction_codes` must contain the session jurisdiction's `code`
    and `certified_categories` must contain the session's `issue_category`, with a
    wrong certification scope rejected as `ERR_INVALID_REQUEST`; and a `PUBLISHED`
    script must exist for the session's (`jurisdiction_id`, `issue_category`) pair
    whose id appears in the counselor's `trained_script_ids`
    (`ERR_TRAINING_NOT_CURRENT`)."

    Design: Corner/state_machines/assign_expired_certification_rejected
    """
    bundle = setup_hotline(worker_cert_expiry="2026-07-01T00:00:00Z")
    caller = create_caller()
    session = intake_session(bundle, caller)

    resp = api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        TEST_USERS["supervisor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED)


def test_assign_untrained_counselor_rejected(api):
    """PRD §3.5: "Four gates apply: the counselor must be `ACTIVE`
    (`ERR_COUNSELOR_INACTIVE`); the counselor's `certification_expires_at` must lie
    after the current logical time (`ERR_CERTIFICATION_EXPIRED`); the counselor's
    `certified_jurisdiction_codes` must contain the session jurisdiction's `code`
    and `certified_categories` must contain the session's `issue_category`, with a
    wrong certification scope rejected as `ERR_INVALID_REQUEST`; and a `PUBLISHED`
    script must exist for the session's (`jurisdiction_id`, `issue_category`) pair
    whose id appears in the counselor's `trained_script_ids`
    (`ERR_TRAINING_NOT_CURRENT`)."

    Design: Corner/state_machines/assign_untrained_counselor_rejected
    """
    bundle = setup_hotline(train_worker=False)
    caller = create_caller()
    session = intake_session(bundle, caller)

    resp = api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        TEST_USERS["supervisor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CURRENT)


def test_start_blocked_by_suspended_counselor(api):
    """PRD §3.5: "Starting the session (`ASSIGNED` → `ACTIVE`) re-evaluates the live
    gates: the interpretation dimension must not be `REQUESTED` (`ERR_INVALID_STATE`
    — a session cannot start while awaiting an interpreter); the assigned counselor
    must be `ACTIVE` at this moment (`ERR_COUNSELOR_INACTIVE`) with unexpired
    certification (`ERR_CERTIFICATION_EXPIRED`); and the language rule fires —
    either the counselor's `languages` contain the caller's `preferred_language`, or
    the interpretation dimension stands at `CONNECTED`, failing which the start is
    rejected with `ERR_LANGUAGE_UNSUPPORTED`."

    Design: Difficulty/cross_entity_state_dependency/start_blocked_by_suspended_counselor
    """
    bundle = setup_hotline()
    caller = create_caller()
    session = intake_session(bundle, caller)
    validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))
    # Suspend the assigned counselor between assignment and start.
    validate_success(api.update_counselor(
        bundle["worker"]["id"], {"status": "SUSPENDED"},
        TEST_USERS["agency_admin_headers"],
    ))

    resp = api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_COUNSELOR_INACTIVE)
    current = get_session(bundle, session["id"])
    assert current["session_status"] == "ASSIGNED", (
        "no partial transition: the session stays ASSIGNED"
    )
    assert current.get("pinned_script_id") is None


def test_start_succeeds_after_counselor_reactivated(api):
    """PRD §3.1: "An administrator update can refresh any profile field, renew the
    certification, or move the counselor `ACTIVE` → `SUSPENDED` → `ACTIVE`, or from
    either `ACTIVE` or `SUSPENDED` to the terminal `INACTIVE`."
    PRD §3.5: "Starting the session (`ASSIGNED` → `ACTIVE`) re-evaluates the live
    gates: the interpretation dimension must not be `REQUESTED` (`ERR_INVALID_STATE`
    — a session cannot start while awaiting an interpreter); the assigned counselor
    must be `ACTIVE` at this moment (`ERR_COUNSELOR_INACTIVE`) with unexpired
    certification (`ERR_CERTIFICATION_EXPIRED`); and the language rule fires —
    either the counselor's `languages` contain the caller's `preferred_language`, or
    the interpretation dimension stands at `CONNECTED`, failing which the start is
    rejected with `ERR_LANGUAGE_UNSUPPORTED`."

    Design: Difficulty/cross_entity_state_dependency/start_blocked_by_suspended_counselor
    """
    bundle = setup_hotline()
    caller = create_caller()
    session = intake_session(bundle, caller)
    validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))
    validate_success(api.update_counselor(
        bundle["worker"]["id"], {"status": "SUSPENDED"},
        TEST_USERS["agency_admin_headers"],
    ))
    blocked = api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    )
    validate_error(blocked, ApiErrorId.ERR_COUNSELOR_INACTIVE)

    # Re-activation lifts the live gate; the same start now succeeds.
    validate_success(api.update_counselor(
        bundle["worker"]["id"], {"status": "ACTIVE"},
        TEST_USERS["agency_admin_headers"],
    ))
    started = validate_success(api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    ))
    assert started["session_status"] == "ACTIVE"
    assert started["pinned_script_id"] == bundle["script"]["id"]
