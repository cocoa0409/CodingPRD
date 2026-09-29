"""
Validation and refusal-ladder compliance for the Concussion Protocol &
Return-to-Play Administration API.

Each test drives one PRD validation rule to its refusal, asserts the exact
`error_id` and HTTP status the PRD pins for it, and then proves the refused write
left no trace on the resource or its collection.  Where the PRD also fixes what
the identical call does once the offending condition is removed, the accepted
call is exercised alongside the refusal.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BASELINE_NOT_ESTABLISHED,
    ERR_BASELINE_RETEST_REQUIRED,
    ERR_CLINICIAN_CREDENTIAL_EXPIRED,
    ERR_DUPLICATE_INJURY_REPORT,
    ERR_EXAM_INC_INELIGIBLE,
    ERR_GAME_NOT_IN_PROGRESS,
    ERR_INC_CLEARANCE_EXPIRED,
    ERR_INC_CLEARANCE_MISSING,
    ERR_INC_NOT_INDEPENDENT,
    ERR_INJURY_DESIGNATION_MISMATCH,
    ERR_OPEN_CASE_EXISTS,
    ERR_PLAYER_CLUB_MISMATCH,
    ERR_REPORT_WINDOW_CLOSED,
    ERR_RETURN_BEFORE_EARLIEST_DATE,
    ERR_STAGE_DWELL_NOT_MET,
    ERR_STAGE_SEQUENCE_VIOLATION,
    ERR_STEP_ALREADY_IN_PROGRESS,
)
from test_helpers.test_users import ADMIN, make_club_physician_headers

WEEK5_KICKOFF_AT = "2026-10-02T17:00:00Z"


def test_evaluation_for_player_of_a_club_outside_the_game_is_refused(api):
    """A player whose club is neither the home nor the away club cannot be evaluated.

    PRD: "The referenced game must be `IN_PROGRESS`, and the player's club must be either the home or the away club of that game — otherwise the request is refused with `ERR_PLAYER_CLUB_MISMATCH`."

    Design: Corner/validations/evaluation_for_player_not_on_either_game_club_rejected
    """
    # Arrange: a live Harbor City v Ridgeway game, plus a third club whose own
    # physician acts on his own player — inside his club scope, outside the game.
    ctx = fx.setup_live_game(api)
    club_n = fx.create_club(api, "Northshore Pilots", "NSP", 2)
    doc_n = fx.create_club_physician(api, club_n["id"], "Dr Novak", "LIC-1004")
    player_n = fx.create_player(api, club_n["id"], "P Novak", 11, "QB")
    fx.set_clock(api, fx.EVALUATION_INITIATED_AT)

    # Act
    response = api.create_sideline_evaluation(
        f.evaluation_payload(
            player_n["id"], ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
        ),
        make_club_physician_headers(doc_n["id"]),
    )

    # Assert: the pinned refusal, and no evaluation written for that game.
    validate_error(response, ERR_PLAYER_CLUB_MISMATCH, expected_status=422)
    rows, meta = validate_paginated(
        api.list_sideline_evaluations(ADMIN, game_id=ctx["game_id"])
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fx.read_player(api, player_n["id"])["availability_status"] == "AVAILABLE"


def test_baseline_filing_by_lapsed_credential_physician_is_refused(api):
    """A physician whose credential has lapsed cannot file a baseline test.

    PRD: "The second is `credential_expires_at`, the instant at which league credentialing lapses: an action is refused with `ERR_CLINICIAN_CREDENTIAL_EXPIRED` at or after that instant, so the credential is valid only while the logical clock is strictly earlier than it."

    Design: Corner/validations/expired_credential_blocks_clinician_write
    """
    # Arrange: a physician credentialed only to 2026-09-01, acting on 2026-09-13.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    lapsed = fx.create_club_physician(
        api,
        club["id"],
        "Dr Lapsed",
        "LIC-1009",
        credential_expires_at="2026-09-01T00:00:00Z",
    )
    player = fx.create_player(api, club["id"])
    fx.set_clock(api, "2026-09-13T18:05:00Z")

    # Act: a perfectly fresh expected_player_version does not save the request.
    response = api.create_baseline_test(
        f.baseline_payload(
            player_id=player["id"], expected_player_version=player["version"]
        ),
        make_club_physician_headers(lapsed["id"]),
    )

    # Assert
    validate_error(response, ERR_CLINICIAN_CREDENTIAL_EXPIRED, expected_status=422)
    reread = fx.read_player(api, player["id"])
    assert reread["baseline_status"] == "NONE"
    assert reread["version"] == 1
    _, meta = validate_paginated(api.list_baseline_tests(ADMIN, player_id=player["id"]))
    assert meta["total_count"] == 0


def test_sideline_evaluation_on_a_scheduled_game_is_refused(api):
    """Sideline work is confined to a live game.

    PRD: "`ERR_GAME_NOT_IN_PROGRESS` (409) — the referenced game is not `IN_PROGRESS`. Applies to evaluation initiation, screening and on-field clearance."

    Design: Corner/validations/evaluation_in_scheduled_game_rejected
    """
    # Arrange: reference data leaves the week-1 game SCHEDULED.
    ctx = fx.setup_reference_data(api)
    fx.set_clock(api, fx.EVALUATION_INITIATED_AT)

    # Act: the observer exercises removal authority before the game is live.
    refused = api.create_sideline_evaluation(
        f.evaluation_payload(
            ctx["player_id"], ctx["game_id"], trigger_source="UNAFFILIATED_OBSERVER"
        ),
        ctx["obs_headers"],
    )

    # Assert: refused, and no evaluation row exists for the game.
    validate_error(refused, ERR_GAME_NOT_IN_PROGRESS, expected_status=409)
    _, meta = validate_paginated(
        api.list_sideline_evaluations(ADMIN, game_id=ctx["game_id"])
    )
    assert meta["total_count"] == 0

    # Assert: the identical call succeeds once the game is IN_PROGRESS, with the
    # mandatory-removal deadline fifteen minutes after initiation.
    fx.advance_game(api, ctx["game_id"], "IN_PROGRESS")
    accepted = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], ctx["game_id"], trigger_source="UNAFFILIATED_OBSERVER"
            ),
            ctx["obs_headers"],
        ),
        expected_status=201,
    )
    assert accepted["status"] == "INITIATED"
    assert accepted["mandatory_removal"] is True
    assert accepted["protocol_deadline_at"] == "2026-09-13T18:20:00.000Z"


def test_locker_room_exam_refuses_ineligible_attending_clinician(api):
    """The attending clinician may be neither club-affiliated nor the screener.

    PRD: "The named clinician's `affiliation` must be `UNAFFILIATED_OBSERVER` or `INDEPENDENT_CONSULTANT`, and must not be the evaluation's own `evaluating_clinician_id`; a club-affiliated nominee, or the screening physician nominating themselves, is refused with `ERR_EXAM_INC_INELIGIBLE`."

    Design: Corner/validations/locker_room_exam_consultant_must_be_eligible
    """
    # Arrange: the screened evaluation plus a second Harbor City physician.
    ctx = fx.setup_screened_evaluation(api)
    fx.add_second_physician(api, ctx)
    fx.set_clock(api, fx.EXAM_STARTED_AT)

    # Act + assert: a club-affiliated nominee is ineligible.
    club_affiliated = api.start_locker_room_exam(
        ctx["eval_id"], f.locker_room_exam_payload(ctx["doc_h2_id"]), ctx["doc_h_headers"]
    )
    validate_error(club_affiliated, ERR_EXAM_INC_INELIGIBLE, expected_status=422)

    # Act + assert: the screening physician may not nominate himself.
    self_nomination = api.start_locker_room_exam(
        ctx["eval_id"], f.locker_room_exam_payload(ctx["doc_h_id"]), ctx["doc_h_headers"]
    )
    validate_error(self_nomination, ERR_EXAM_INC_INELIGIBLE, expected_status=422)

    # Assert: neither refusal started an examination.
    untouched = fx.read_evaluation(api, ctx["eval_id"])
    assert untouched["status"] == "SCREENED"
    assert untouched["exam_started_at"] is None
    assert untouched["inc_clinician_id"] is None

    # Assert: the unaffiliated observer is accepted, and the block is 30 minutes.
    accepted = validate_success(
        api.start_locker_room_exam(
            ctx["eval_id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
        ),
        expected_status=200,
    )
    assert accepted["status"] == "LOCKER_ROOM_EXAM"
    assert accepted["inc_clinician_id"] == ctx["obs_id"]
    assert accepted["exam_started_at"] == "2026-09-13T18:10:00.000Z"
    assert accepted["inc_block_ends_at"] == fx.EXAM_BLOCK_ENDS_AT


def test_final_clearance_naming_a_conflicted_consultant_is_refused(api):
    """Consultant independence is checked before the ladder-completeness rules.

    PRD: "The nominated consultant must be an `INDEPENDENT_CONSULTANT` whose `club_id` is null, must not be the case's `diagnosing_clinician_id`, and must not be the clinician who attended that case's locker-room examination; each of those failures is refused with `ERR_INC_NOT_INDEPENDENT`."

    Design: Corner/validations/final_clearance_consultant_conflict_rejected
    """
    # Arrange: a freshly diagnosed case with no return steps at all.
    ctx = fx.setup_diagnosed_case(api)
    case_version_before = fx.case_version(api, ctx["case_id"])

    # Act + assert: naming the diagnosing physician.
    diagnosing = api.request_inc_clearance(
        ctx["case_id"],
        f.clearance_request_payload(ctx["doc_h_id"], case_version_before),
        ctx["doc_h_headers"],
    )
    validate_error(diagnosing, ERR_INC_NOT_INDEPENDENT, expected_status=422)

    # Act + assert: naming the clinician who attended the locker-room examination.
    attendee = api.request_inc_clearance(
        ctx["case_id"],
        f.clearance_request_payload(ctx["obs_id"], case_version_before),
        ctx["doc_h_headers"],
    )
    validate_error(attendee, ERR_INC_NOT_INDEPENDENT, expected_status=422)

    # Assert: the case never moved and no clearance was minted.
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "MANDATORY_REMOVAL"
    assert case["version"] == case_version_before
    _, meta = validate_paginated(api.list_inc_clearances(ADMIN, case_id=ctx["case_id"]))
    assert meta["total_count"] == 0


def test_second_diagnosis_while_a_case_is_open_is_refused(api):
    """A player may hold only one case that has not reached CLEARED_FOR_CONTACT.

    PRD: "A player may hold at most one case whose `case_status` is anything other than `CLEARED_FOR_CONTACT`, so diagnosing a player who already has an open case is refused with `ERR_OPEN_CASE_EXISTS`."

    Design: Corner/validations/second_diagnosis_while_case_open_rejected
    """
    # Arrange: the canonical case, then a second complete examination the same night.
    ctx = fx.setup_diagnosed_case(api)
    fx.set_clock(api, "2026-09-13T18:45:00Z")
    second = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
            ),
            ctx["doc_h_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.screen_evaluation(
            second["id"],
            f.screen_payload(no_go_signs=["CONFUSION"], symptom_score=9),
            ctx["doc_h_headers"],
        )
    )
    fx.set_clock(api, "2026-09-13T18:50:00Z")
    validate_success(
        api.start_locker_room_exam(
            second["id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
        )
    )
    # Nine whole minutes of examination, so the eight-minute minimum is satisfied.
    fx.set_clock(api, "2026-09-13T18:59:00Z")

    # Act
    response = api.diagnose_concussion(
        second["id"],
        f.diagnose_payload(symptom_score=9, composite_score=70),
        ctx["doc_h_headers"],
    )

    # Assert: refused, the second evaluation stays mid-examination, one case only.
    validate_error(response, ERR_OPEN_CASE_EXISTS, expected_status=409)
    assert fx.read_evaluation(api, second["id"])["status"] == "LOCKER_ROOM_EXAM"
    _, meta = validate_paginated(
        api.list_concussion_cases(ADMIN, player_id=ctx["player_id"])
    )
    assert meta["total_count"] == 1
    assert fx.read_player(api, ctx["player_id"])["diagnosed_case_count"] == 1


def test_return_stage_index_skip_is_refused(api):
    """stage_index must be exactly one greater than the case's rtp_stage.

    PRD: "A `ClubPhysician` of the case's club opens a rung by supplying its `stage_index`, and the value must be exactly one greater than the case's current `rtp_stage`; anything else — skipping ahead, or repeating a stage already passed — is refused with `ERR_STAGE_SEQUENCE_VIOLATION`."

    Design: Corner/validations/stage_index_skip_rejected
    """
    # Arrange: stage 1 passed, and the clock moved far enough that no rest buffer
    # is outstanding for either stage 2 or stage 3.
    ctx = fx.setup_case_through_stage(api, 1)
    fx.set_clock(api, "2026-09-20T12:00:00Z")

    # Act
    response = api.create_return_step(
        ctx["case_id"], f.return_step_payload(3), ctx["doc_h_headers"]
    )

    # Assert
    validate_error(response, ERR_STAGE_SEQUENCE_VIOLATION, expected_status=422)
    assert fx.read_case(api, ctx["case_id"])["rtp_stage"] == 1
    _, meta = validate_paginated(api.list_return_steps(ADMIN, case_id=ctx["case_id"]))
    assert meta["total_count"] == 1


def test_opening_a_stage_while_another_step_is_in_progress_is_refused(api):
    """Only one rung of the ladder may be live at a time.

    PRD: "Only one rung may be live at a time: opening a stage while another step on the case is still `IN_PROGRESS` is refused with `ERR_STEP_ALREADY_IN_PROGRESS`."

    Design: Corner/validations/second_step_start_while_one_in_progress_rejected
    """
    # Arrange: stage 1 open and not yet signed off, so rtp_stage is still 0 and the
    # sequence check on a repeat stage-1 request passes.
    ctx = fx.setup_case_with_stage_open(api, 1)

    # Act
    response = api.create_return_step(
        ctx["case_id"], f.return_step_payload(1), ctx["doc_h_headers"]
    )

    # Assert
    validate_error(response, ERR_STEP_ALREADY_IN_PROGRESS, expected_status=409)
    step = fx.read_step(api, ctx["step_ids"][1])
    assert step["status"] == "IN_PROGRESS"
    assert step["attempt_index"] == 1
    rows, meta = validate_paginated(api.list_return_steps(ADMIN, case_id=ctx["case_id"]))
    assert meta["total_count"] == 1
    assert [r["id"] for r in rows] == [ctx["step_ids"][1]]
    assert fx.read_case(api, ctx["case_id"])["rtp_stage"] == 0


def test_stage_pass_before_dwell_complete_is_refused(api):
    """The dwell gate is half-open: a pass at exactly dwell_complete_at is accepted.

    PRD: "`dwell_complete_at` is the step's `started_at` plus that requirement, and a pass before it is refused with `ERR_STAGE_DWELL_NOT_MET` while a pass at exactly `dwell_complete_at` succeeds."

    Design: Corner/validations/stage_dwell_boundary_enforced
    """
    # Arrange: stage 1 started 2026-09-15T12:00:00Z, so dwell completes one day on.
    ctx = fx.setup_case_with_stage_open(api, 1)
    step_id = ctx["step_ids"][1]
    assert fx.read_step(api, step_id)["dwell_complete_at"] == "2026-09-16T12:00:00.000Z"
    fx.set_clock(api, "2026-09-16T11:59:59Z")

    # Act + assert: one second early is refused and leaves the step untouched.
    early = api.evaluate_return_step(
        step_id, f.evaluate_step_payload(outcome="PASS", symptom_score=0), ctx["doc_h_headers"]
    )
    validate_error(early, ERR_STAGE_DWELL_NOT_MET, expected_status=409)
    untouched = fx.read_step(api, step_id)
    assert untouched["status"] == "IN_PROGRESS"
    assert untouched["evaluated_at"] is None
    assert untouched["cleared_by_clinician_id"] is None
    assert fx.read_case(api, ctx["case_id"])["rtp_stage"] == 0

    # Act + assert: the boundary instant itself is accepted.
    fx.set_clock(api, "2026-09-16T12:00:00Z")
    passed = validate_success(
        api.evaluate_return_step(
            step_id,
            f.evaluate_step_payload(outcome="PASS", symptom_score=0),
            ctx["doc_h_headers"],
        )
    )
    assert passed["status"] == "PASSED"
    assert passed["evaluated_at"] == "2026-09-16T12:00:00.000Z"
    case = fx.read_case(api, ctx["case_id"])
    assert case["rtp_stage"] == 1
    assert case["case_status"] == "RTP_IN_PROGRESS"


def test_earliest_return_date_outranks_the_missing_clearance_refusal(api):
    """Two unmet return conditions: the earlier rung of the ladder decides.

    PRD: "When one request violates several rules at once, exactly one error is returned: the one belonging to the earliest applicable rung of the ladder below."
    PRD: "`ERR_RETURN_BEFORE_EARLIEST_DATE` (409) — returning to contact before the case's `earliest_return_at`."

    Design: Corner/validations/return_to_contact_earliest_date_precedes_clearance_missing
    """
    # Arrange: five stages passed, a baseline retest on file and a clearance that
    # was requested but never decided; the clock sits on the stage-five sign-off.
    ctx = fx.setup_case_pending_clearance(api)
    assert (
        fx.read_case(api, ctx["case_id"])["earliest_return_at"]
        == fx.CANONICAL_EARLIEST_RETURN_AT
    )

    # Act + assert: before earliest_return_at, rung 28 wins over the clearance rung.
    early = api.return_to_contact(
        ctx["case_id"],
        f.return_to_contact_payload("attempting early return"),
        ctx["doc_h_headers"],
    )
    validate_error(early, ERR_RETURN_BEFORE_EARLIEST_DATE, expected_status=409)

    # Act + assert: on the earliest permitted day the missing approval surfaces.
    fx.set_clock(api, "2026-09-28T12:00:00Z")
    unapproved = api.return_to_contact(
        ctx["case_id"],
        f.return_to_contact_payload("retrying on the earliest permitted day"),
        ctx["doc_h_headers"],
    )
    validate_error(unapproved, ERR_INC_CLEARANCE_MISSING, expected_status=409)

    # Assert: neither refusal decided the clearance or cleared the case.
    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "PENDING"
    assert clearance["decided_at"] is None
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "PENDING_INC_CLEARANCE"
    assert case["cleared_for_contact_at"] is None
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "PROTOCOL_RESTRICTED"
    assert player["public_injury_designation"] == "OUT"


def test_baseline_readiness_variants_gate_return_to_contact(api):
    """One rung, two error ids: RETEST_REQUIRED and NONE are refused differently.

    PRD: "And the player's `baseline_status` must be `VALID` — a status of `RETEST_REQUIRED` is refused with `ERR_BASELINE_RETEST_REQUIRED` and a status of `NONE` with `ERR_BASELINE_NOT_ESTABLISHED`."

    Design: Corner/validations/baseline_readiness_variants_gate_return_to_contact
    """
    # Arrange: all five stages passed and the clearance approved, but the diagnosis
    # stamped NEW_DIAGNOSIS on the pre-season baseline and no retest has been filed.
    ctx = fx.setup_case_all_stages_passed(api)
    fx.request_clearance(api, ctx)
    fx.decide_clearance(api, ctx, "APPROVED")
    fx.set_clock(api, "2026-09-28T12:00:00Z")
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "RETEST_REQUIRED"

    # Act + assert: the retest obligation is refused with its own error id.
    owed_retest = api.return_to_contact(
        ctx["case_id"], f.return_to_contact_payload("no retest yet"), ctx["doc_h_headers"]
    )
    validate_error(owed_retest, ERR_BASELINE_RETEST_REQUIRED, expected_status=422)
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "PENDING_INC_CLEARANCE"
    assert case["cleared_for_contact_at"] is None

    # Arrange: the retest is filed and then administratively invalidated, so no
    # VALID baseline row survives at all.
    fx.file_baseline_retest(api, ctx)
    assert fx.read_baseline(api, ctx["baseline_id"])["status"] == "SUPERSEDED"
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "VALID"
    validate_success(
        api.invalidate_baseline_test(
            ctx["retest_id"],
            f.invalidate_payload("retest administered with the wrong protocol"),
            ADMIN,
        )
    )
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "NONE"

    # Act + assert: the same call now yields the not-established error id.
    no_baseline = api.return_to_contact(
        ctx["case_id"],
        f.return_to_contact_payload("retest invalidated"),
        ctx["doc_h_headers"],
    )
    validate_error(no_baseline, ERR_BASELINE_NOT_ESTABLISHED, expected_status=422)
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "PENDING_INC_CLEARANCE"
    assert case["cleared_for_contact_at"] is None

    # Assert: refiling the baseline lets the identical call succeed.
    refiled = fx.file_baseline(
        api, ctx["player_id"], ctx["doc_h_id"], composite_score=87, reaction_time_ms=515
    )
    assert refiled["status"] == "VALID"
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "VALID"
    cleared = validate_success(
        api.return_to_contact(
            ctx["case_id"],
            f.return_to_contact_payload("retest refiled, clearing"),
            ctx["doc_h_headers"],
        )
    )
    assert cleared["case_status"] == "CLEARED_FOR_CONTACT"
    assert cleared["cleared_for_contact_at"] == "2026-09-28T12:00:00.000Z"


def test_return_to_contact_at_clearance_expiry_instant_is_refused(api):
    """A clearance is dead at its own expires_at, before any sweep says so.

    PRD: "`ERR_INC_CLEARANCE_EXPIRED` (409) — returning to contact when the case's most recent clearance is `EXPIRED`, or its `expires_at` is at or before the logical clock."

    Design: Corner/validations/expired_consultant_clearance_blocks_return
    """
    # Arrange: a clearance approved on 2026-09-27T12:00:00Z expires seven days on;
    # the club never filed the return until that instant arrived.
    ctx = fx.setup_case_pending_clearance(api)
    fx.decide_clearance(api, ctx, "APPROVED")
    fx.set_clock(api, "2026-10-04T12:00:00Z")

    # Act + assert: refused on the expiry instant while the row still reads APPROVED.
    on_expiry = api.return_to_contact(
        ctx["case_id"],
        f.return_to_contact_payload("returning on the expiry instant"),
        ctx["doc_h_headers"],
    )
    validate_error(on_expiry, ERR_INC_CLEARANCE_EXPIRED, expected_status=409)
    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "APPROVED"
    assert clearance["expires_at"] == "2026-10-04T12:00:00.000Z"
    assert fx.read_case(api, ctx["case_id"])["case_status"] == "PENDING_INC_CLEARANCE"

    # Act: the sweep flips the row to EXPIRED; the 21-day line is not reached yet.
    summary = fx.run_sweep(api)
    assert summary["expired_inc_clearance_ids"] == [ctx["clearance_id"]]
    assert summary["prolonged_watch_case_ids"] == []
    assert fx.read_clearance(api, ctx["clearance_id"])["status"] == "EXPIRED"

    # Assert: the verdict is unchanged after the sweep, and the case never moved.
    after_sweep = api.return_to_contact(
        ctx["case_id"],
        f.return_to_contact_payload("retrying after the sweep"),
        ctx["doc_h_headers"],
    )
    validate_error(after_sweep, ERR_INC_CLEARANCE_EXPIRED, expected_status=409)
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "PENDING_INC_CLEARANCE"
    assert case["cleared_for_contact_at"] is None


def test_injury_report_designation_must_equal_required_designation(api):
    """A club may not understate an open concussion case on the injury report.

    PRD: "The filed `designation` must equal that `required_designation`, and a mismatch is refused with `ERR_INJURY_DESIGNATION_MISMATCH`."

    Design: Corner/validations/injury_report_designation_must_match_required
    """
    # Arrange: the case is MANDATORY_REMOVAL, so the league-resolved value is OUT.
    ctx = fx.setup_diagnosed_case(api)
    game_w5 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        season_year=2026,
        week_index=5,
        kickoff_at=WEEK5_KICKOFF_AT,
    )
    fx.set_clock(api, "2026-09-30T00:00:00Z")

    # Act + assert: QUESTIONABLE is refused and writes nothing.
    understated = api.create_injury_report_entry(
        f.injury_report_payload(
            game_w5["id"],
            ctx["player_id"],
            practice_participation="DNP",
            designation="QUESTIONABLE",
        ),
        ctx["club_h_headers"],
    )
    validate_error(understated, ERR_INJURY_DESIGNATION_MISMATCH, expected_status=422)
    _, meta = validate_paginated(
        api.list_injury_report_entries(ADMIN, game_id=game_w5["id"])
    )
    assert meta["total_count"] == 0

    # Assert: only OUT is accepted, inside the open filing window.
    filed = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(
                game_w5["id"],
                ctx["player_id"],
                practice_participation="DNP",
                designation="OUT",
            ),
            ctx["club_h_headers"],
        ),
        expected_status=201,
    )
    assert filed["designation"] == "OUT"
    assert filed["required_designation"] == "OUT"
    assert filed["status"] == "FILED"
    assert filed["club_id"] == ctx["club_h_id"]
    assert filed["filed_at"] == "2026-09-30T00:00:00.000Z"


def test_duplicate_injury_report_for_same_game_and_player_is_refused(api):
    """At most one entry may exist for one pairing of game and player.

    PRD: "The player's club must be the home or away club of the referenced game, else `ERR_PLAYER_CLUB_MISMATCH`, and at most one entry may exist for any pairing of game and player, a second attempt being refused with `ERR_DUPLICATE_INJURY_REPORT`."

    Design: Corner/validations/duplicate_injury_report_rejected
    """
    # Arrange: one correct OUT entry already filed for the week-5 game.
    ctx = fx.setup_diagnosed_case(api)
    game_w5 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        season_year=2026,
        week_index=5,
        kickoff_at=WEEK5_KICKOFF_AT,
    )
    fx.set_clock(api, "2026-09-30T00:00:00Z")
    first = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(
                game_w5["id"], ctx["player_id"], practice_participation="DNP", designation="OUT"
            ),
            ctx["club_h_headers"],
        ),
        expected_status=201,
    )

    # Act: a second filing whose designation is nonetheless correct.
    response = api.create_injury_report_entry(
        f.injury_report_payload(
            game_w5["id"], ctx["player_id"], practice_participation="DNP", designation="OUT"
        ),
        ctx["club_h_headers"],
    )

    # Assert
    validate_error(response, ERR_DUPLICATE_INJURY_REPORT, expected_status=409)
    rows, meta = validate_paginated(
        api.list_injury_report_entries(
            ADMIN, game_id=game_w5["id"], player_id=ctx["player_id"]
        )
    )
    assert meta["total_count"] == 1
    assert [r["id"] for r in rows] == [first["id"]]
    entry = fx.read_injury_report(api, first["id"])
    assert entry["status"] == "FILED"
    assert entry["amended_at"] is None


def test_injury_report_amendment_window_shuts_at_kickoff(api):
    """Amendments follow the same kickoff cut-off as filings.

    PRD: "The amendment supplies a fresh `practice_participation` and `designation`, must arrive strictly before `kickoff_at` (otherwise `ERR_REPORT_WINDOW_CLOSED`), and its new `designation` must equal the freshly recomputed `required_designation` (otherwise `ERR_INJURY_DESIGNATION_MISMATCH`)."

    Design: Corner/validations/amendment_window_shuts_at_kickoff
    """
    # Arrange: two FILED entries on the week-5 game — the diagnosed player (OUT) and
    # a healthy team-mate with no case at all (NONE).
    ctx = fx.setup_diagnosed_case(api)
    team_mate = fx.add_second_player(api, ctx)
    game_w5 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        season_year=2026,
        week_index=5,
        kickoff_at=WEEK5_KICKOFF_AT,
    )
    fx.set_clock(api, "2026-09-30T00:00:00Z")
    diagnosed_entry = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(
                game_w5["id"], ctx["player_id"], practice_participation="DNP", designation="OUT"
            ),
            ctx["club_h_headers"],
        ),
        expected_status=201,
    )
    team_mate_entry = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(
                game_w5["id"], team_mate["id"], practice_participation="FULL", designation="NONE"
            ),
            ctx["club_h_headers"],
        ),
        expected_status=201,
    )

    # Act + assert: one second before kickoff the amendment is accepted.
    fx.set_clock(api, "2026-10-02T16:59:59Z")
    amended = validate_success(
        api.amend_injury_report_entry(
            diagnosed_entry["id"],
            f.injury_report_amendment_payload(
                practice_participation="LIMITED", designation="OUT"
            ),
            ctx["club_h_headers"],
        )
    )
    assert amended["status"] == "AMENDED"
    assert amended["practice_participation"] == "LIMITED"
    assert amended["designation"] == "OUT"
    assert amended["amended_from_designation"] == "OUT"
    assert amended["amended_at"] == "2026-10-02T16:59:59.000Z"

    # Act + assert: at exactly kickoff the still-FILED entry cannot be amended.
    fx.set_clock(api, WEEK5_KICKOFF_AT)
    at_kickoff = api.amend_injury_report_entry(
        team_mate_entry["id"],
        f.injury_report_amendment_payload(
            practice_participation="LIMITED", designation="NONE"
        ),
        ctx["club_h_headers"],
    )
    validate_error(at_kickoff, ERR_REPORT_WINDOW_CLOSED, expected_status=409)
    untouched = fx.read_injury_report(api, team_mate_entry["id"])
    assert untouched["status"] == "FILED"
    assert untouched["practice_participation"] == "FULL"
    assert untouched["amended_at"] is None
    assert untouched["amended_from_designation"] is None
