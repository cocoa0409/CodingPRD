"""Litigation holds, their release, and the retention schedule: the depth-3
suspension cascade, record hold/release round-trip, destruction boundaries,
and hold-gated report creation (PRD §3.6, §3.9)."""
from test_helpers import (
    TEST_USERS,
    assert_timestamp_prefix,
    create_draft_report,
    create_in_progress_engagement,
    place_hold,
    release_hold,
    setup_delivered_engagement,
    setup_report_client_review,
    setup_report_revision_requested,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]
RM = TEST_USERS["records_manager_headers"]


def test_litigation_hold_suspends_engagement_and_report(api):
    """PRD §3.9: "On an `IN_PROGRESS` engagement, the engagement moves to
    `LITIGATION_HOLD`, the matter caption is recorded on the engagement's
    `litigation_matter_reference`, every report of the engagement in a
    non-terminal, non-`SUPERSEDED` state is suspended — moving to `SUSPENDED`
    with its prior status saved into `pre_hold_status`".

    Design: Difficulty/transitive_cascade/litigation_hold_depth3_cascade
    """
    bundle = setup_report_revision_requested(
        category="CLARIFICATION",
        requested_change="Clarify easement language")
    place_hold(bundle, matter_reference="Case 26-CV-1042")
    eng = validate_success(
        api.get_engagement(bundle["engagement"]["id"], EM), 200)
    assert eng["status"] == "LITIGATION_HOLD"
    assert eng["litigation_matter_reference"] == "Case 26-CV-1042"
    report = validate_success(api.get_report(bundle["report"]["id"], EM), 200)
    assert report["status"] == "SUSPENDED"
    assert report["pre_hold_status"] == "REVISION_REQUESTED"


def test_litigation_hold_escalates_open_revision_request(api):
    """PRD §3.9: "every revision request still `OPEN` on each suspended
    report is escalated to `ESCALATED` as a direct consequence of the
    suspension" — the third link of the hold cascade, caused by the report's
    suspension rather than by the hold call directly.

    Design: Difficulty/transitive_cascade/litigation_hold_depth3_cascade
    """
    bundle = setup_report_revision_requested(
        category="CLARIFICATION",
        requested_change="Clarify easement language")
    place_hold(bundle)
    req = validate_success(
        api.get_revision_request(bundle["request"]["id"], EM), 200)
    assert req["status"] == "ESCALATED"


def test_litigation_release_restores_report_state(api):
    """PRD §3.9: "A held engagement returns from `LITIGATION_HOLD` to
    `IN_PROGRESS`; each suspended report is restored to its saved
    `pre_hold_status`, which is then cleared to null; and the engagement's
    `litigation_matter_reference` is cleared."

    Design: Corner/state_machines/litigation_release_restores_report_state
    """
    bundle = setup_report_client_review()
    place_hold(bundle)
    release_hold(bundle)
    eng = validate_success(
        api.get_engagement(bundle["engagement"]["id"], EM), 200)
    assert eng["status"] == "IN_PROGRESS"
    assert eng.get("litigation_matter_reference") is None
    report = validate_success(api.get_report(bundle["report"]["id"], EM), 200)
    assert report["status"] == "CLIENT_REVIEW"
    assert report.get("pre_hold_status") is None


def test_retention_hold_nulls_retain_until(api):
    """PRD §3.9: "On a `COMPLETED` engagement, the hold instead lands on its
    retention record: the record moves from `ACTIVE` to `LITIGATION_HOLD`,
    stamping `litigation_hold_placed_at`, recording the matter caption, and
    setting `retain_until_date` to null — retention becomes indefinite while
    held." The record was created with `base_retain_until_date` five years
    beyond completion (PRD §3.8) — 2031-08-01 for a 2026-08-01 completion.

    Design: Difficulty/compensating_invariant/retention_hold_release_roundtrip
    """
    bundle = setup_delivered_engagement()
    record = bundle["retention_record"]
    assert_timestamp_prefix(record["base_retain_until_date"], "2031-08-01T00:00:00")
    assert_timestamp_prefix(record["retain_until_date"], "2031-08-01T00:00:00")

    api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, RM)
    place_hold(bundle)
    held = validate_success(api.get_retention_record(record["id"], RM), 200)
    assert held["status"] == "LITIGATION_HOLD"
    assert held.get("retain_until_date") is None


def test_retention_release_restores_base_deadline(api):
    """PRD §3.9: "A held retention record returns to `ACTIVE`, stamps
    `litigation_released_at`, and recomputes `retain_until_date` as the later
    of `base_retain_until_date` and the calendar date of release extended by
    two years — litigation tolls the schedule." Released 2027-03-01, the
    extension (2029-03-01) falls short of the base 2031-08-01, so the base
    deadline is conserved.

    Design: Difficulty/compensating_invariant/retention_hold_release_roundtrip
    """
    bundle = setup_delivered_engagement()
    record = bundle["retention_record"]
    api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, RM)
    place_hold(bundle)
    api.set_clock({"to_iso8601": "2027-03-01T00:00:00Z"}, RM)
    release_hold(bundle)
    restored = validate_success(api.get_retention_record(record["id"], RM), 200)
    assert restored["status"] == "ACTIVE"
    assert_timestamp_prefix(restored["retain_until_date"], "2031-08-01T00:00:00")


def test_retention_authorize_date_boundary(api):
    """PRD §3.9: "Authorization moves a record from `ACTIVE` to
    `RELEASED_PENDING_DESTRUCTION` once the retention period has fully
    elapsed: the calendar date of the logical clock must be on or after
    `retain_until_date` — destruction authorized exactly on that date is
    allowed — and an earlier attempt is rejected with
    `ERR_RETENTION_PERIOD_NOT_ELAPSED`. Confirmation then moves the record
    from `RELEASED_PENDING_DESTRUCTION` to `DESTROYED`, its terminal state."

    Design: Corner/calculations/retention_authorize_date_boundary
    """
    bundle = setup_delivered_engagement()
    record = bundle["retention_record"]

    api.set_clock({"to_iso8601": "2031-07-31T00:00:00Z"}, RM)
    res = api.authorize_destruction(record["id"], RM)
    validate_error(res, "ERR_RETENTION_PERIOD_NOT_ELAPSED", expected_status=409)

    api.set_clock({"to_iso8601": "2031-08-01T00:00:00Z"}, RM)
    authorized = validate_success(api.authorize_destruction(record["id"], RM), 200)
    assert authorized["status"] == "RELEASED_PENDING_DESTRUCTION"

    destroyed = validate_success(api.confirm_destruction(record["id"], RM), 200)
    assert destroyed["status"] == "DESTROYED"

    res_after = api.authorize_destruction(record["id"], RM)
    validate_error(res_after, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_report_create_blocked_by_engagement_hold(api):
    """PRD §3.6: "The author appraiser creates each new version against an
    `IN_PROGRESS` engagement — any other engagement state rejects with
    `ERR_INVALID_STATE_TRANSITION`" — and under §3.9 the held engagement
    stands in `LITIGATION_HOLD`, so report creation is rejected.

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_by_engagement_hold
    """
    bundle = create_in_progress_engagement()
    stale_v = bundle["engagement"]["version"]
    place_hold(bundle)
    res = api.create_report(
        bundle["engagement"]["id"],
        {"expected_engagement_version": stale_v},
        bundle["author_headers"])
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_report_create_allowed_after_hold_release(api):
    """PRD §3.9: "A held engagement returns from `LITIGATION_HOLD` to
    `IN_PROGRESS`" — and per §3.6 the author may then create a new report
    version against the `IN_PROGRESS` engagement, born in `DRAFTING`.

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_by_engagement_hold
    """
    bundle = create_in_progress_engagement()
    place_hold(bundle)
    release_hold(bundle)
    report = create_draft_report(bundle)
    assert report["status"] == "DRAFTING"
    eng = validate_success(
        api.get_engagement(bundle["engagement"]["id"], EM), 200)
    assert eng["status"] == "IN_PROGRESS"
