"""
Endpoint-surface and error-envelope compliance for the Concussion Protocol &
Return-to-Play Administration API.

This module walks the breadth of the endpoint table: the computed club
compliance summary, the clinician create/read/list triad, every collection read
with its declared filters, the by-id reads of the late-lifecycle entities, a
no-op operational sweep, the one-shot action endpoints (roster exemption,
clinician suspension, monitoring-closing symptom check), the optional audit
cross-references, and the uniform shape of a refused request.

The server is restarted before every test, so each test builds all the protocol
state it needs from scratch.
"""

from prd_bench_local_runner import testing as fw
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLINICIAN_SUSPENDED,
    ERR_EXEMPTION_ALREADY_GRANTED,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNIQUENESS_VIOLATION,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    DEFAULT_PAGE_LIMIT,
    VIOLATION_BASE_CENTS,
    VIOLATION_WEIGHT,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR_A,
    AUDITOR_OPENER_USER_ID,
    make_auditor_headers,
    make_club_physician_headers,
    make_compliance_officer_headers,
)

# Instants used by the fixtures these tests build on.
WEEK5_KICKOFF_AT = "2026-10-02T17:00:00Z"
REPORT_FILED_AT = "2026-09-30T00:00:00Z"
REPORT_FILED_AT_MS = "2026-09-30T00:00:00.000Z"
CLEARANCE_REQUESTED_AT_MS = "2026-09-27T12:00:00.000Z"
CLEARANCE_EXPIRES_AT_MS = "2026-10-04T12:00:00.000Z"
OFFSEASON_2026_AT = "2027-02-15T00:00:00Z"

SWEEP_RESULT_ARRAYS = [
    "breached_evaluation_ids",
    "auto_opened_audit_ids",
    "expired_baseline_test_ids",
    "expired_inc_clearance_ids",
    "prolonged_watch_case_ids",
    "offseason_monitoring_case_ids",
    "frozen_case_ids",
    "restored_case_ids",
]


def test_compliance_summary_is_a_pure_computed_read(api):
    """The club compliance summary derives all eleven members on every read.

    PRD: "Every member is derived by the posture routine of §2.8 and the slot
    ledger of §2.9 rather than stored independently."

    Design: Corner/endpoints/compliance_summary_is_a_pure_computed_read
    """
    # Arrange: a diagnosed case holding a roster exemption, plus one audit whose
    # findings charge MISSED_MANDATORY_REMOVAL against the same club.
    ctx = fx.setup_diagnosed_case(api)
    get_success_data(api.grant_roster_exemption(ctx["case_id"], ctx["club_h_headers"]))
    fx.setup_audit_with_findings(api, ctx["club_h_id"], ["MISSED_MANDATORY_REMOVAL"])

    # Preliminary score charges the FINDINGS_ISSUED audit's single weight;
    # the adjudicated score counts only CLOSED_UPHELD audits, so it stays at 100.
    expected_score = 100 - VIOLATION_WEIGHT["MISSED_MANDATORY_REMOVAL"]
    # exposure factor (7 + 0) / 7 = 1, severity factor 1.00 (no case named on the
    # audit) and the stamped tier is TIER_0 (multiplier 1.00).
    expected_fine = VIOLATION_BASE_CENTS["MISSED_MANDATORY_REMOVAL"]

    version_before = fx.read_club(api, ctx["club_h_id"])["version"]

    # Act: read the summary as the club's own officer.
    response = api.get_compliance_summary(ctx["club_h_id"], ctx["club_h_headers"])

    # Assert: every member is the freshly derived figure.
    summary = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert summary["club_id"] == ctx["club_h_id"]
    a.assert_club_posture(
        summary,
        compliance_score=expected_score,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=expected_fine,
        open_violation_count=1,
        adjudicated_compliance_score=100,
    )
    a.assert_exemption_slots(summary, used=1, available=2, total=3)
    assert summary["frozen_case_count"] == 0

    # Assert: the read is a projection, not a mutation - a second read by another
    # permitted role returns identical data and the club row has not advanced.
    second = validate_success(
        api.get_compliance_summary(ctx["club_h_id"], AUDITOR_A), 200
    )
    assert second == summary
    assert fx.read_club(api, ctx["club_h_id"])["version"] == version_before


def test_clinician_create_read_list_round_trip(api):
    """Registering a consultant round-trips through the by-id read and the list.

    PRD: "A newly registered clinician is `ACTIVE` with `cases_cleared_count` at
    0 and no `suspension_reason`."

    Design: Corner/endpoints/clinician_create_read_list_round_trip
    """
    # Arrange: an empty league with the clock on its default instant.
    fx.set_clock(api, DEFAULT_CLOCK)

    # Act: register an independent consultant, who carries no club_id at all.
    created = validate_success(
        api.create_clinician(
            f.consultant_payload(
                full_name="Dr Iyer",
                license_number="LIC-3001",
                credential_expires_at="2027-12-31T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )

    # Assert: the 201 body carries the supplied data plus the seeded fields.
    a.assert_common_fields(created, expected_version=1)
    assert created["full_name"] == "Dr Iyer"
    assert created["affiliation"] == "INDEPENDENT_CONSULTANT"
    assert created["license_number"] == "LIC-3001"
    assert created["status"] == "ACTIVE"
    assert created["cases_cleared_count"] == 0
    a.assert_null(created, "club_id", "suspension_reason")
    a.assert_instant(created["created_at"], "2026-08-01T00:00:00.000Z")

    # Assert: the by-id read returns the same row field for field.
    fetched = validate_success(api.get_clinician(created["id"], ADMIN), 200)
    assert fetched == created

    # Assert: the affiliation filter selects the row and excludes it from the
    # other affiliation's page.
    rows, meta = validate_paginated(
        api.list_clinicians(ADMIN, affiliation="INDEPENDENT_CONSULTANT")
    )
    a.assert_page_meta(meta, total_count=1, has_more=False)
    a.assert_ids_equal(rows, [created["id"]])

    empty_rows, empty_meta = validate_paginated(
        api.list_clinicians(ADMIN, affiliation="CLUB_AFFILIATED")
    )
    a.assert_page_meta(empty_meta, total_count=0, has_more=False)
    assert empty_rows == []


def test_all_collection_endpoints_list_and_filter(api):
    """Each collection read answers with the array envelope and its own filters.

    PRD: "Every collection read supports `limit` and `offset` plus a set of
    exact-match filters."
    PRD: "Unless a specific endpoint says otherwise, every list endpoint returns
    its rows sorted by `created_at` in ascending order."

    Design: Corner/endpoints/all_collection_endpoints_list_and_filter
    """
    # Arrange: the full protocol chain - five stages passed, the post-diagnosis
    # baseline retest filed, the consultant clearance approved, a scheduled
    # week-5 game and an OUT injury report filed inside its window.
    ctx = fx.setup_case_pending_clearance(api)
    fx.decide_clearance(api, ctx, "APPROVED")
    week5 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        week_index=5,
        kickoff_at=WEEK5_KICKOFF_AT,
    )
    fx.set_clock(api, REPORT_FILED_AT)
    report = get_success_data(
        api.create_injury_report_entry(
            f.injury_report_payload(
                week5["id"], ctx["player_id"], practice_participation="DNP", designation="OUT"
            ),
            ctx["club_h_headers"],
        )
    )
    passed_step_ids = [ctx["step_ids"][index] for index in range(1, 6)]

    # Act + Assert: walk every collection in turn, each with its declared filter.
    collections = [
        (
            "baseline-tests by player",
            api.list_baseline_tests(ADMIN, player_id=ctx["player_id"]),
            [ctx["baseline_id"], ctx["retest_id"]],
        ),
        (
            "baseline-tests by player and VALID status",
            api.list_baseline_tests(ADMIN, player_id=ctx["player_id"], status="VALID"),
            [ctx["retest_id"]],
        ),
        (
            "games by season and IN_PROGRESS status",
            api.list_games(ADMIN, season_year=2026, status="IN_PROGRESS"),
            [ctx["game_id"]],
        ),
        (
            "players by club and OUT designation",
            api.list_players(
                ADMIN, club_id=ctx["club_h_id"], public_injury_designation="OUT"
            ),
            [ctx["player_id"]],
        ),
        (
            "sideline-evaluations by game and DIAGNOSED status",
            api.list_sideline_evaluations(
                ADMIN, game_id=ctx["game_id"], status="DIAGNOSED"
            ),
            [ctx["eval_id"]],
        ),
        (
            "return-steps by case and PASSED status",
            api.list_return_steps(ADMIN, case_id=ctx["case_id"], status="PASSED"),
            passed_step_ids,
        ),
        (
            "inc-clearances by case and APPROVED status",
            api.list_inc_clearances(ADMIN, case_id=ctx["case_id"], status="APPROVED"),
            [ctx["clearance_id"]],
        ),
        (
            "injury-report-entries by game and OUT designation",
            api.list_injury_report_entries(
                ADMIN, game_id=week5["id"], designation="OUT"
            ),
            [report["id"]],
        ),
    ]

    listed = {}
    for label, response, expected_ids in collections:
        assert response.json()["response_type"] == "array", label
        rows, meta = validate_paginated(response)
        a.assert_page_meta(
            meta,
            total_count=len(expected_ids),
            limit=DEFAULT_PAGE_LIMIT,
            offset=0,
            has_more=False,
        )
        a.assert_ids_equal(rows, expected_ids)
        a.assert_sorted_by_created_at(rows)
        listed[label] = rows

    # Assert: the filtered rows really are the fixture's rows, with no leakage.
    valid_baseline = listed["baseline-tests by player and VALID status"][0]
    assert valid_baseline["status"] == "VALID"
    assert valid_baseline["composite_score"] == 87
    assert listed["players by club and OUT designation"][0][
        "availability_status"
    ] == "PROTOCOL_RESTRICTED"
    assert [
        step["stage_index"] for step in listed["return-steps by case and PASSED status"]
    ] == [1, 2, 3, 4, 5]
    assert listed["injury-report-entries by game and OUT designation"][0][
        "status"
    ] == "FILED"

    # Assert: limit and offset page the same collection without changing the
    # pre-pagination total_count.
    page_rows, page_meta = validate_paginated(
        api.list_return_steps(ADMIN, case_id=ctx["case_id"], limit=2, offset=4)
    )
    a.assert_page_meta(page_meta, total_count=5, limit=2, offset=4, has_more=False)
    a.assert_ids_equal(page_rows, [ctx["step_ids"][5]])
    assert page_rows[0]["stage_index"] == 5


def test_all_single_resource_reads_return_their_row(api):
    """The by-id reads of clearance, injury report and audit return stored rows.

    PRD: "Both `amended_at` and `amended_from_designation` are null until the
    first amendment."
    PRD: "Fields not yet applicable are null: `escalation_tier_at_issuance`,
    `club_response_note`, `findings_issued_by_user_id`, `closed_by_user_id`,
    `findings_issued_at` and `closed_at`."

    Design: Corner/endpoints/all_single_resource_reads_return_their_row
    """
    # Arrange: the same chain as the collection sweep, plus a freshly opened audit.
    ctx = fx.setup_case_pending_clearance(api)
    fx.decide_clearance(api, ctx, "APPROVED")
    week5 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        week_index=5,
        kickoff_at=WEEK5_KICKOFF_AT,
    )
    fx.set_clock(api, REPORT_FILED_AT)
    report = get_success_data(
        api.create_injury_report_entry(
            f.injury_report_payload(
                week5["id"], ctx["player_id"], practice_participation="DNP", designation="OUT"
            ),
            ctx["club_h_headers"],
        )
    )
    audit = fx.open_audit(api, ctx["club_h_id"])

    # Act: read each late-lifecycle row by id, each through a role permitted on
    # that read.
    clearance_response = api.get_inc_clearance(
        ctx["clearance_id"], make_club_physician_headers(ctx["doc_h_id"])
    )
    report_response = api.get_injury_report_entry(
        report["id"], make_compliance_officer_headers(ctx["club_h_id"])
    )
    audit_response = api.get_protocol_audit(
        audit["id"], make_auditor_headers(AUDITOR_OPENER_USER_ID)
    )

    # Assert: the consultant clearance shows its approval and seven-day expiry.
    clearance = validate_success(clearance_response, 200)
    assert clearance_response.json()["response_type"] == "object"
    a.assert_common_fields(clearance)
    assert clearance["status"] == "APPROVED"
    assert clearance["case_id"] == ctx["case_id"]
    assert clearance["inc_clinician_id"] == ctx["inc_id"]
    assert clearance["requested_by_clinician_id"] == ctx["doc_h_id"]
    assert clearance["documented_stage_count"] == 5
    a.assert_instant(clearance["requested_at"], CLEARANCE_REQUESTED_AT_MS)
    a.assert_instant(clearance["decided_at"], CLEARANCE_REQUESTED_AT_MS)
    a.assert_instant(clearance["expires_at"], CLEARANCE_EXPIRES_AT_MS)

    # Assert: the injury report entry shows its filing, with no amendment yet.
    entry = validate_success(report_response, 200)
    a.assert_common_fields(entry)
    assert entry["game_id"] == week5["id"]
    assert entry["player_id"] == ctx["player_id"]
    assert entry["club_id"] == ctx["club_h_id"]
    assert entry["practice_participation"] == "DNP"
    assert entry["designation"] == "OUT"
    assert entry["required_designation"] == "OUT"
    assert entry["status"] == "FILED"
    a.assert_instant(entry["filed_at"], REPORT_FILED_AT_MS)
    a.assert_null(entry, "amended_at", "amended_from_designation")

    # Assert: the freshly opened audit is OPEN with nothing priced yet.
    opened = validate_success(audit_response, 200)
    a.assert_common_fields(opened)
    assert opened["club_id"] == ctx["club_h_id"]
    assert opened["status"] == "OPEN"
    assert opened["auto_opened"] is False
    assert opened["opened_by_user_id"] == AUDITOR_OPENER_USER_ID
    assert opened["violation_codes"] == []
    assert opened["assessed_fine_cents"] == 0
    assert opened["disposition"] == "PENDING"
    assert opened["response_round_count"] == 0
    a.assert_null(
        opened,
        "case_id",
        "sideline_evaluation_id",
        "escalation_tier_at_issuance",
        "club_response_note",
        "findings_issued_by_user_id",
        "closed_by_user_id",
        "findings_issued_at",
        "closed_at",
    )


def test_sweep_with_nothing_due_is_a_no_op(api):
    """A sweep with no deadline, expiry or calendar line reached changes nothing.

    PRD: "A second sweep run at the same logical clock value mutates nothing
    further."

    Design: Corner/endpoints/sweep_with_nothing_due_is_a_no_op
    """
    # Arrange: the case diagnosed at 18:19, with the clock still on that instant -
    # the evaluation's 18:20 deadline, the 365-day baseline validity, the 21-day
    # prolonged-symptom line and the off-season boundary are all still ahead.
    ctx = fx.setup_diagnosed_case(api)
    case_version_before = fx.case_version(api, ctx["case_id"])

    # Act: run the sweep twice at the same logical clock value.
    first_response = api.run_protocol_sweep(ADMIN)
    second_response = api.run_protocol_sweep(ADMIN)

    # Assert: every one of the eight result arrays is empty on both runs.
    for response in (first_response, second_response):
        summary = validate_success(response, 200)
        assert fw.is_iso8601_timestamp(summary["swept_at"])
        assert summary["swept_at"].startswith("2026-09-13T18:19:00")
        for field_name in SWEEP_RESULT_ARRAYS:
            assert summary[field_name] == [], f"{field_name} should be empty"

    # Assert: nothing was mutated - no version advanced and no audit was opened.
    case = fx.read_case(api, ctx["case_id"])
    assert case["version"] == case_version_before
    a.assert_case_dimensions(case, monitoring_status="ACTIVE_SYMPTOM_WATCH")
    assert fx.read_evaluation(api, ctx["eval_id"])["status"] == "DIAGNOSED"
    assert fx.read_club(api, ctx["club_h_id"])["compliance_score"] == 100
    _, audits_meta = validate_paginated(
        api.list_protocol_audits(ADMIN, club_id=ctx["club_h_id"])
    )
    a.assert_page_meta(audits_meta, total_count=0)


def test_second_roster_exemption_grant_rejected(api):
    """A case already holding an exemption cannot be granted a second one.

    PRD: "A grant moves the case `NONE → GRANTED`, requires the case's
    `roster_exemption_status` to be `NONE` (a case already `GRANTED` or
    `RELEASED` is refused with `ERR_EXEMPTION_ALREADY_GRANTED`), requires the
    case not to have reached `CLEARED_FOR_CONTACT` (otherwise
    `ERR_CASE_STATE_INVALID`), and requires the club to have at least one slot
    available (otherwise `ERR_NO_EXEMPTION_SLOTS`)."

    Design: Corner/endpoints/second_roster_exemption_grant_rejected
    """
    # Arrange: the diagnosed case with one exemption already granted.
    ctx = fx.setup_diagnosed_case(api)
    get_success_data(api.grant_roster_exemption(ctx["case_id"], ctx["club_h_headers"]))

    # Act: the same officer asks for a second exemption on the same case.
    response = api.grant_roster_exemption(ctx["case_id"], ctx["club_h_headers"])

    # Assert: refused, and the slot ledger did not double-count.
    validate_error(response, ERR_EXEMPTION_ALREADY_GRANTED, 409)
    summary = validate_success(
        api.get_compliance_summary(ctx["club_h_id"], ctx["club_h_headers"]), 200
    )
    a.assert_exemption_slots(summary, used=1, available=2, total=3)
    a.assert_case_dimensions(
        fx.read_case(api, ctx["case_id"]), roster_exemption_status="GRANTED"
    )


def test_protocol_audit_links_case_and_evaluation(api):
    """One audit can carry both the case and the evaluation reference at once.

    PRD: "A `LeagueAuditor` opens an audit against a `club_id`, optionally naming
    the `case_id` under audit and optionally the `sideline_evaluation_id` under
    audit; both are null for a reporting-only audit, and `case_id` is null for an
    evaluation-only one."

    Design: Corner/endpoints/protocol_audit_links_case_and_evaluation
    """
    # Arrange: the canonical diagnosed case and the evaluation that produced it.
    ctx = fx.setup_diagnosed_case(api)

    # Act: open an audit naming both optional references.
    created = validate_success(
        api.create_protocol_audit(
            f.audit_payload(
                ctx["club_h_id"],
                case_id=ctx["case_id"],
                sideline_evaluation_id=ctx["eval_id"],
            ),
            AUDITOR_A,
        ),
        201,
    )

    # Assert: both foreign keys are stored and the audit opens unpriced.
    a.assert_common_fields(created, expected_version=1)
    assert created["club_id"] == ctx["club_h_id"]
    assert created["case_id"] == ctx["case_id"]
    assert created["sideline_evaluation_id"] == ctx["eval_id"]
    assert created["status"] == "OPEN"
    assert created["auto_opened"] is False
    assert created["opened_by_user_id"] == AUDITOR_OPENER_USER_ID
    assert created["violation_codes"] == []
    assert created["assessed_fine_cents"] == 0
    assert created["disposition"] == "PENDING"
    a.assert_null(created, "escalation_tier_at_issuance")

    # Assert: the audit is reachable through either declared filter.
    by_case_rows, by_case_meta = validate_paginated(
        api.list_protocol_audits(AUDITOR_A, case_id=ctx["case_id"])
    )
    a.assert_page_meta(by_case_meta, total_count=1)
    a.assert_ids_equal(by_case_rows, [created["id"]])

    by_eval_rows, by_eval_meta = validate_paginated(
        api.list_protocol_audits(AUDITOR_A, sideline_evaluation_id=ctx["eval_id"])
    )
    a.assert_page_meta(by_eval_meta, total_count=1)
    a.assert_ids_equal(by_eval_rows, [created["id"]])


def test_clinician_suspension_action_cascades_and_then_rejects(api):
    """Suspension is a one-shot action: the second attempt is refused.

    PRD: "A `LeagueAdmin` suspends a clinician with a stated `reason`, moving
    that clinician from `ACTIVE` to `SUSPENDED` and recording the reason as
    `suspension_reason`; suspending an already-suspended clinician is refused
    with `ERR_CLINICIAN_SUSPENDED`."

    Design: Corner/endpoints/clinician_suspension_action_cascades_and_then_rejects
    """
    # Arrange: a consultant with no pending clearances to cascade into.
    fx.set_clock(api, DEFAULT_CLOCK)
    fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    consultant = fx.create_consultant(api)
    reason = "licence under review by the state board"

    # Act: suspend once.
    first = validate_success(
        api.suspend_clinician(consultant["id"], f.suspend_payload(reason), ADMIN), 200
    )

    # Assert: the clinician is SUSPENDED with the stated reason recorded.
    assert first["status"] == "SUSPENDED"
    assert first["suspension_reason"] == reason
    a.assert_common_fields(first, expected_version=consultant["version"] + 1)

    # Act: suspend the same clinician again.
    second = api.suspend_clinician(
        consultant["id"], f.suspend_payload("duplicate administrative action"), ADMIN
    )

    # Assert: refused, and neither the reason nor the version moved.
    validate_error(second, ERR_CLINICIAN_SUSPENDED, 409)
    after = fx.read_clinician(api, consultant["id"])
    assert after["status"] == "SUSPENDED"
    assert after["suspension_reason"] == reason
    assert after["version"] == first["version"]


def test_symptom_check_closes_offseason_monitoring(api):
    """An asymptomatic check on an off-season cleared case closes monitoring.

    PRD: "A symptom check reporting a score of exactly 0 against a case that is
    both `OFFSEASON_MONITORING` and `CLEARED_FOR_CONTACT` moves
    `monitoring_status` to the terminal `MONITORING_CLOSED`, records
    `last_symptom_check_score` as 0, and increments the case's `version` by 1."
    PRD: "Where `initial_symptom_score` is at least 4, `last_symptomatic_at` is
    stamped equal to `diagnosis_at`; `last_symptom_check_score` remains null
    until a symptom check runs."

    Design: Corner/endpoints/symptom_check_closes_offseason_monitoring
    """
    # Arrange: the case cleared for contact, then swept across the off-season
    # boundary of its own season (15 February of the following year).
    ctx = fx.setup_case_with_approved_clearance(api)
    get_success_data(
        api.return_to_contact(
            ctx["case_id"], f.return_to_contact_payload(), ctx["doc_h_headers"]
        )
    )
    fx.set_clock(api, OFFSEASON_2026_AT)
    sweep = fx.run_sweep(api)

    # Assert the sweep moved the case into the off-season programme rather than
    # the 21-day prolonged watch, and left the cleared case's clearance alone.
    assert sweep["offseason_monitoring_case_ids"] == [ctx["case_id"]]
    assert sweep["prolonged_watch_case_ids"] == []
    assert sweep["expired_inc_clearance_ids"] == []
    swept_case = fx.read_case(api, ctx["case_id"])
    a.assert_case_dimensions(
        swept_case,
        case_status="CLEARED_FOR_CONTACT",
        monitoring_status="OFFSEASON_MONITORING",
    )

    # Act: record an asymptomatic monitoring check.
    response = api.symptom_check(
        ctx["case_id"], f.symptom_check_payload(symptom_score=0), ctx["doc_h_headers"]
    )

    # Assert: monitoring reaches its terminal state; the protocol dimension and
    # the recurrence history are untouched.
    case = validate_success(response, 200)
    a.assert_case_dimensions(
        case, case_status="CLEARED_FOR_CONTACT", monitoring_status="MONITORING_CLOSED"
    )
    assert case["last_symptom_check_score"] == 0
    a.assert_case_progress(
        case, recurrence_count=0, severity_index=fx.CANONICAL_SEVERITY_INDEX
    )
    assert case["version"] == swept_case["version"] + 1
    # The diagnosis symptom score was 9, so this instant was stamped at diagnosis
    # and an asymptomatic check never moves it.
    a.assert_instant(case["last_symptomatic_at"], fx.DIAGNOSIS_AT_MS)

    # Assert: the player is available again and the 72-hour publication window
    # after clearance has long closed.
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "AVAILABLE"
    assert player["public_injury_designation"] == "NONE"


def test_error_envelope_is_uniform_when_requests_are_rejected(api):
    """Schema, uniqueness and not-found refusals all share one error envelope.

    PRD: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."
    PRD: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/error_envelope_is_uniform_when_requests_are_rejected
    """
    # Arrange: one club already holds market_code HCK.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act: three refusals drawn from three different error families.
    missing_field = api.create_club(
        f.club_payload(name=f.OMIT, market_code="ZZZ", exemption_slots_total=2), ADMIN
    )
    duplicate_code = api.create_club(
        f.club_payload(name="Harbor City Imposters", market_code="HCK"), ADMIN
    )
    unknown_row = api.get_baseline_test(NON_EXISTENT_UUID, ADMIN)

    # Assert: each carries its own error_id at its own catalogued status.
    validate_error(missing_field, ERR_INVALID_REQUEST, 400)
    validate_error(duplicate_code, ERR_UNIQUENESS_VIOLATION, 409)
    validate_error(unknown_row, ERR_RESOURCE_NOT_FOUND, 404)

    # Assert: all three share the same envelope - response_type error, data
    # holding exactly error_id and message, and a meta of exactly the two keys.
    for response in (missing_field, duplicate_code, unknown_row):
        a.assert_error_envelope(response)
        meta = response.json()["meta"]
        assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}

    # Assert: no refusal left a row behind - the existing club is untouched and
    # market_code ZZZ is still free, so registering it now succeeds.
    assert fx.read_club(api, club["id"])["name"] == "Harbor City Kraken"
    retry = validate_success(
        api.create_club(
            f.club_payload(name="Zephyr Coast", market_code="ZZZ", exemption_slots_total=2),
            ADMIN,
        ),
        201,
    )
    assert retry["market_code"] == "ZZZ"
