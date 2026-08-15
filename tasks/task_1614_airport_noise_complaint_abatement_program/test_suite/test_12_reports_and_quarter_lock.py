"""Quarterly reports and board governance: the revision loop back to DRAFT and
on to PUBLISHED, the unclassified-events submit gate, the frozen rollup
snapshot and its half-open window, the published-quarter complaint lock,
segregation of duties, and the report-edit OCC guard with its auth-first
ordering."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    assert_same_instant,
    begin_screening,
    classify_event,
    create_complaint_payload,
    create_complainant,
    create_event,
    create_monitor,
    create_report,
    make_board_member_headers,
    make_complainant_headers,
    make_noise_analyst_headers,
    publish_report,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]


def test_report_return_for_revision_cycles_back_to_draft(api):
    """PRD 3.9: "Alternatively the board member returns the report for revision
    with a `reason`, moving it back to `DRAFT` and incrementing
    `revision_round_count`."
    PRD 3.9: "While the report is `DRAFT`, the analyst may revise its `notes`
    through the report-editing operation, which carries the
    `expected_report_version` guard of §2.6".

    Design: Difficulty/non_linear_state_machine/report_revision_loop_then_publish
    """
    report = create_report(quarter_label="2026-Q2", notes="draft v1")
    validate_success(api.submit_for_review(report["id"], {}, ANALYST), 200)

    returned = validate_success(
        api.return_for_revision(
            report["id"],
            {"reason": "missing narrative"},
            make_board_member_headers("board-1"),
        ),
        200,
    )
    assert returned["status"] == "DRAFT"
    assert returned["revision_round_count"] == 1

    # The cycle is non-linear: editing re-opens on the returned version, and a
    # second submission succeeds.
    edited = validate_success(
        api.patch_report(
            report["id"],
            {"notes": "draft v2 complete", "expected_report_version": returned["version"]},
            ANALYST,
        ),
        200,
    )
    assert edited["version"] == returned["version"] + 1

    resubmitted = validate_success(api.submit_for_review(report["id"], {}, ANALYST), 200)
    assert resubmitted["status"] == "UNDER_REVIEW"


def test_report_revision_loop_then_publish_records_actors(api):
    """PRD 3.9: "Approval moves `UNDER_REVIEW` to `APPROVED` and records the
    approver on `approved_by_user_id`".
    PRD 3.9: "Publishing is the administrator's act: an `APPROVED` report
    becomes `PUBLISHED`, stamps `published_at`, and locks the quarter".
    PRD 3.9: "the creator's `X-User-ID` is stored on `created_by_user_id`."

    Design: Difficulty/non_linear_state_machine/report_revision_loop_then_publish
    """
    report = create_report(quarter_label="2026-Q2", notes="draft v1")
    validate_success(api.submit_for_review(report["id"], {}, ANALYST), 200)
    returned = validate_success(
        api.return_for_revision(
            report["id"],
            {"reason": "missing narrative"},
            make_board_member_headers("board-1"),
        ),
        200,
    )
    validate_success(
        api.patch_report(
            report["id"],
            {"notes": "draft v2 complete", "expected_report_version": returned["version"]},
            ANALYST,
        ),
        200,
    )
    validate_success(api.submit_for_review(report["id"], {}, ANALYST), 200)

    approved = validate_success(
        api.approve_report(report["id"], {}, make_board_member_headers("board-1")), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "board-1"

    published = validate_success(api.publish_report(report["id"], {}, ADMIN), 200)
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None
    assert published["created_by_user_id"] == "analyst-7"


def test_report_submit_blocked_by_unclassified_event_in_period(api):
    """PRD 3.9: "When the quarter has fully closed — `period_end` at or before
    now, else `ERR_QUARTER_NOT_CLOSED` — and no events with `started_at` in the
    period remain `CAPTURED` or `SCREENING` (else
    `ERR_UNCLASSIFIED_EVENTS_REMAIN`), the analyst submits the report for
    review, moving it to `UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/report_submit_gated_by_unclassified_events_in_period
    """
    monitor = create_monitor(station_code="MG1")
    # Started 2026-05-15: inside 2026-Q2 and left in SCREENING.
    event = create_event(monitor["id"], started_at="2026-05-15T10:00:00Z")
    begin_screening(event["id"])
    report = create_report(quarter_label="2026-Q2")

    response = api.submit_for_review(report["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_UNCLASSIFIED_EVENTS_REMAIN)

    reread = validate_success(api.get_report(report["id"], ANALYST))
    assert reread["status"] == "DRAFT"


def test_report_submit_released_after_event_verified_with_frozen_snapshot(api):
    """PRD 3.9: "no events with `started_at` in the period remain `CAPTURED` or
    `SCREENING` (else `ERR_UNCLASSIFIED_EVENTS_REMAIN`)".
    PRD 3.9: "Creation also computes the frozen rollup snapshot:
    `complaints_received_count` (complaints created in the period, any status),
    ... `events_aircraft_count` (events started in the period now
    `CLASSIFIED_AIRCRAFT` or `VERIFIED`), `events_community_count`
    (`CLASSIFIED_COMMUNITY`) ... The snapshot is frozen at creation and never
    recomputed".

    Design: Difficulty/cross_entity_state_dependency/report_submit_gated_by_unclassified_events_in_period
    """
    monitor = create_monitor(station_code="MG1")
    event = create_event(monitor["id"], started_at="2026-05-15T10:00:00Z")
    begin_screening(event["id"])
    report = create_report(quarter_label="2026-Q2")
    # Frozen while the event was still SCREENING: neither bucket counts it.
    assert report["events_aircraft_count"] == 0
    assert report["events_community_count"] == 0

    # 40 + 2*(72.0-65.0) + 20 (duration >= 30) = 74.0 >= 70.0; uptime 100.
    classify_event(event["id"], "COMMUNITY")
    verified = validate_success(api.verify_event(event["id"], {}, ANALYST), 200)
    assert verified["status"] == "VERIFIED"

    submitted = validate_success(api.submit_for_review(report["id"], {}, ANALYST), 200)
    assert submitted["status"] == "UNDER_REVIEW"

    reread = validate_success(api.get_report(report["id"], ANALYST))
    # Still zero even though the event now sits in VERIFIED (which the live
    # formula counts as aircraft): the snapshot never recomputes.
    assert reread["events_aircraft_count"] == 0
    assert reread["events_community_count"] == 0


def test_report_patch_without_auth_returns_unauthenticated(api):
    """PRD 2.11: "1. **Presence of credentials** — both `X-User-ID` and
    `X-User-Role` headers are present and the role is one of the seven declared
    roles, else `ERR_UNAUTHENTICATED`."
    PRD 2.11: "The ordering is deliberate — authentication outranks shape, shape
    outranks authorization, existence outranks state, and fiscal guards are
    evaluated last".

    Design: Difficulty/priority_pair_validation_conflict/report_patch_missing_auth_beats_not_found
    """
    report = create_report(quarter_label="2026-Q2")

    # Valid OCC-shaped body, but a nonexistent path id AND no credentials:
    # authentication (gate 1) fires before path existence (gate 6).
    response = api.patch_report(
        NON_EXISTENT_UUID,
        {"notes": "x", "expected_report_version": report["version"]},
        NO_AUTH_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_report_patch_unknown_id_with_auth_returns_not_found(api):
    """PRD 2.11: "6. **Path existence** — path identifiers resolve, left to
    right, else `ERR_NOT_FOUND`."
    PRD 2.10: "The request is rejected immediately with a `404 Not Found` error
    carrying `ERR_NOT_FOUND` for the *first* identifier in the path that does
    not resolve, before any later segment or business rule is examined."

    Design: Difficulty/priority_pair_validation_conflict/report_patch_missing_auth_beats_not_found
    """
    report = create_report(quarter_label="2026-Q2")

    # Authenticated and well-formed: only the existence gate can fail.
    response = api.patch_report(
        NON_EXISTENT_UUID,
        {"notes": "x", "expected_report_version": report["version"]},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_occ_stale_report_patch_rejected(api):
    """PRD 2.6: "First, editing the narrative of a quarterly report — the
    report-editing endpoint (`PATCH /noise-program/quarterly-reports/{reportId}`)
    — requires the request to carry `expected_report_version` holding the report
    `version` the client last observed. If the report's current `version` no
    longer matches, another edit has advanced the report since the client last
    read it, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) so
    the client's change, which is based on a stale view, is not applied."

    Design: Corner/complexity_layers/occ_stale_report_patch_rejected
    """
    report = create_report(quarter_label="2026-Q2")
    assert report["version"] == 1

    patched = validate_success(
        api.patch_report(
            report["id"], {"notes": "v2 notes", "expected_report_version": 1}, ANALYST
        ),
        200,
    )
    assert patched["version"] == 2

    replayed = api.patch_report(
        report["id"], {"notes": "stale notes", "expected_report_version": 1}, ANALYST
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_VERSION)


def test_quarterly_rollup_excludes_records_at_period_end(api):
    """PRD 3.9: "Creation derives the reporting window from the label:
    `period_start` inclusive and `period_end` exclusive, with Q1 running from
    January 1 up to April 1, Q2 from April 1 up to July 1, Q3 from July 1 up to
    October 1, and Q4 from October 1 up to the following January 1."
    PRD 3.9: "The window is half-open: records falling exactly at `period_end`
    are excluded."
    PRD 3.9: "`complaints_received_count` (complaints created in the period, any
    status)" and "`distinct_complainants_count` (distinct filers in the
    period)".

    Design: Corner/calculations/quarterly_rollup_excludes_records_at_period_end
    """
    set_clock("2026-05-01T00:00:00Z")
    complainant = create_complainant(full_name="Q2 One", email="q2@x.com")
    owner = make_complainant_headers(complainant["id"])
    # Both created at 2026-05-01: inside [2026-04-01, 2026-07-01).
    for occurred_at in ("2026-04-15T08:00:00Z", "2026-04-16T08:00:00Z"):
        validate_success(
            api.create_complaint(
                create_complaint_payload(complainant["id"], occurred_at=occurred_at),
                owner,
            ),
            201,
        )
    # Created exactly at period_end 2026-07-01T00:00:00Z: excluded.
    set_clock("2026-07-01T00:00:00Z")
    validate_success(
        api.create_complaint(
            create_complaint_payload(
                complainant["id"],
                occurred_at="2026-06-30T08:00:00Z",
                disturbance_type="VIBRATION",
            ),
            owner,
        ),
        201,
    )
    set_clock("2026-08-01T00:00:00Z")

    report = validate_success(api.create_report({"quarter_label": "2026-Q2"}, ANALYST), 201)
    assert_same_instant(report["period_start"], "2026-04-01T00:00:00Z", "period_start")
    assert_same_instant(report["period_end"], "2026-07-01T00:00:00Z", "period_end")
    assert report["complaints_received_count"] == 2
    assert report["distinct_complainants_count"] == 1


def test_complaint_filed_into_published_quarter_rejected(api):
    """PRD 3.9: "Publishing is the administrator's act: an `APPROVED` report
    becomes `PUBLISHED`, stamps `published_at`, and locks the quarter — from
    that moment, any complaint filing whose `occurred_at` falls inside the
    published period is rejected with `ERR_REPORT_QUARTER_LOCKED`."

    Design: Corner/validations/complaint_filed_into_published_quarter_rejected
    """
    report = create_report(quarter_label="2026-Q2")
    publish_report(report["id"])
    complainant = create_complainant(full_name="Lock One", email="lock1@x.com")
    owner = make_complainant_headers(complainant["id"])

    locked = api.create_complaint(
        create_complaint_payload(
            complainant["id"],
            occurred_at="2026-05-10T10:00:00Z",
            disturbance_type="LOUD_EVENT",
        ),
        owner,
    )
    validate_error(locked, ApiErrorId.ERR_REPORT_QUARTER_LOCKED)

    # Q3 is not locked: the same caller files there freely.
    open_q3 = api.create_complaint(
        create_complaint_payload(
            complainant["id"],
            occurred_at="2026-07-10T10:00:00Z",
            disturbance_type="LOUD_EVENT",
        ),
        owner,
    )
    complaint = validate_success(open_q3, 201)
    assert complaint["status"] == "RECEIVED"


def test_segregation_of_duties_self_approve_forbidden(api):
    """PRD 3.9: "Approval moves `UNDER_REVIEW` to `APPROVED` and records the
    approver on `approved_by_user_id`, but the approver must differ from the
    report's creator — a segregation-of-duties rule whose violation is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 2.11: "5. **Segregation of duties** — the approver of a quarterly report
    must not be the report's creator, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/segregation_of_duties_self_approve_forbidden
    """
    report = create_report(quarter_label="2026-Q2", user_id="user-9")
    validate_success(
        api.submit_for_review(report["id"], {}, make_noise_analyst_headers("user-9")),
        200,
    )

    # The creator (user-9) cannot approve their own report, whatever the role.
    rejected = api.approve_report(report["id"], {}, make_board_member_headers("user-9"))
    validate_error(rejected, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(
        api.approve_report(report["id"], {}, make_board_member_headers("board-2")), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "board-2"
