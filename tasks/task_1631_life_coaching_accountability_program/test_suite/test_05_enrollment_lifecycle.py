"""Enrollment pause/resume/cancel lifecycle, pause limits, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_session,
    complete_session,
    create_goal,
    get_enrollment,
    get_session,
    make_client_headers,
    pause_enrollment,
    resume_enrollment,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_success,
)

PM = TEST_USERS["practice_manager_headers"]


def test_third_pause_rejected_at_pause_limit(api):
    """PRD §3.5: "A client pauses their own `ACTIVE` enrollment — acting on
    another client's enrollment is `ERR_FORBIDDEN` — at most twice across the
    enrollment's life, with `pauses_used` counting completed transitions into
    `PAUSED`; a third attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/third_pause_rejected_at_pause_limit
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    pause_enrollment(enrollment["id"], client)
    resume_enrollment(enrollment["id"], client)
    pause_enrollment(enrollment["id"], client)
    resume_enrollment(enrollment["id"], client)
    data = get_enrollment(enrollment["id"])
    assert data["pauses_used"] == 2
    assert data["lifecycle_status"] == "ACTIVE"
    resp = api.pause_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": data["version"]},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_completed_enrollment_returns_invalid_state(api):
    """PRD §3.4: "When consumption thereby reaches `sessions_total`, the
    enrollment bubbles up to `COMPLETED` on its own". PRD §3.5: cancellation
    is "the client's exit from either `ACTIVE` or `PAUSED`" — a COMPLETED
    enrollment permits no cancel transition, so the state gate rejects it with
    `ERR_INVALID_STATE`.

    Design: Corner/state_machines/cancel_completed_enrollment_returns_invalid_state
    """
    ctx = setup_active_enrollment(
        tier_overrides={
            "tier_type": "SINGLE", "session_count": 1, "price_cents": 15000,
            "duration_days": 30, "installment_count_allowed": 1,
            "reschedule_cap": 0,
        }
    )
    client = ctx["client"]
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-05T10:00:00Z")
    set_clock("2026-08-05T10:30:00Z")
    complete_session(sess["id"], coach_a)
    data = get_enrollment(enrollment["id"])
    assert data["lifecycle_status"] == "COMPLETED", \
        "consuming the only session bubbles the enrollment to COMPLETED"
    resp = api.cancel_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": data["version"]},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_occ_stale_version_on_enrollment_pause(api):
    """PRD §2.8: "Three enrollment lifecycle writes — pausing, resuming, and
    cancelling — require the request to carry `expected_enrollment_version`,
    holding the `version` of the enrollment as the caller last observed it.
    If another write has advanced the enrollment's `version` since that read,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_stale_version_on_enrollment_pause
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    stale_version = enrollment["version"]
    # An intervening write bumps the version.
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-06T10:00:00Z")
    resp = api.pause_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": stale_version},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_enrollment(enrollment["id"])["lifecycle_status"] == "ACTIVE"
    # Retry against a fresh read succeeds and cascades.
    fresh = get_enrollment(enrollment["id"])
    resp = api.pause_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": fresh["version"]},
        make_client_headers(client["id"]),
    )
    data = validate_success(resp)
    assert data["lifecycle_status"] == "PAUSED"
    assert get_session(sess["id"])["session_status"] == "CANCELLED", \
        "pause cascades to cancel the enrollment's SCHEDULED sessions"


def test_occ_stale_version_on_enrollment_cancel(api):
    """PRD §2.8: "If another write has advanced the enrollment's `version`
    since that read, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412): the caller's view of `pauses_used`, of lifecycle position,
    or of cascaded session state is stale, and the request must be re-issued
    against a fresh read rather than overwrite mutations it never observed."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_enrollment_cancel
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    fresh = get_enrollment(enrollment["id"])
    resp = api.cancel_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": fresh["version"] - 1},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    resp = api.cancel_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": fresh["version"]},
        make_client_headers(client["id"]),
    )
    data = validate_success(resp)
    assert data["lifecycle_status"] == "CANCELLED"


def test_pause_response_reflects_mutation_immediately(api):
    """PRD §3.5: "Pausing moves `lifecycle_status` to `PAUSED`, increments
    `pauses_used`, advances the enrollment's `version`, and cascades: every
    `SCHEDULED` session of the enrollment becomes `CANCELLED`, after which
    `sessions_consumed` and `sessions_remaining` recompute."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/endpoints/pause_response_reflects_mutation_immediately
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    prior_version = enrollment["version"]
    prior_pauses = enrollment["pauses_used"]
    resp = api.pause_enrollment(
        enrollment["id"],
        {"expected_enrollment_version": prior_version},
        make_client_headers(client["id"]),
    )
    data = validate_success(resp)
    assert data["lifecycle_status"] == "PAUSED"
    assert data["pauses_used"] == prior_pauses + 1
    assert data["version"] == prior_version + 1
