"""
Derived arithmetic of the Concussion Protocol & Return-to-Play Administration API.

Every figure this module pins is computed by the server rather than supplied by a
caller: the five-component `severity_index`, the provisional `projected_return_at`
and the accrued `earliest_return_at`, the preliminary `compliance_score` and its
included audit set, the twice-rounded `assessed_fine_cents`, the injury-report
window classification and the league-resolved `required_designation`, the
resolution of `baseline_status` from the player's baseline rows, the
roster-exemption slot ledger, and the rest-buffer / dwell instants stamped on each
graduated-return step.  Each test asserts exact integers and
millisecond-precision instants, never a tolerance.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INJURY_DESIGNATION_MISMATCH,
    ERR_NO_EXEMPTION_SLOTS,
    ERR_REPORT_WINDOW_CLOSED,
    ERR_REPORT_WINDOW_NOT_OPEN,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    VIOLATION_BASE_CENTS,
    VIOLATION_WEIGHT,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR_A,
    AUDITOR_B,
    make_club_physician_headers,
    make_compliance_officer_headers,
    make_observer_headers,
)


def test_second_case_severity_adds_prior_case_and_baseline_deviation_terms(api):
    """A second in-season concussion scores 92 while the first case keeps its 82.

    PRD: "The history term is 10 points when `prior_case_id` is present and 0 when it is null."
    PRD: "The baseline term itself is a flat 15-point penalty when the player had no `VALID` baseline; otherwise it is the smaller of 15 and `baseline_deviation_points` multiplied by 1.5 and rounded half up — the rounding happens **before** the 15-point cap, never after."

    Design: Corner/calculations/second_case_severity_adds_prior_case_and_deviation_terms
    """
    # Arrange: walk the canonical case all the way to CLEARED_FOR_CONTACT, so the
    # post-diagnosis retest (composite 87) is the player's only VALID baseline.
    ctx = fx.setup_case_with_approved_clearance(api)  # clock rests on 2026-09-28T12:00:00Z
    validate_success(
        api.return_to_contact(
            ctx["case_id"], f.return_to_contact_payload(), ctx["doc_h_headers"]
        )
    )

    # A fresh week-4 game, taken live, with a second removal for the same player.
    game_w4 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        week_index=4,
        kickoff_at="2026-10-04T17:00:00Z",
    )
    fx.set_clock(api, "2026-10-04T17:00:00Z")
    fx.advance_game(api, game_w4["id"], "IN_PROGRESS")

    fx.set_clock(api, "2026-10-04T19:50:00Z")
    eval2 = get_success_data(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], game_w4["id"], trigger_source="UNAFFILIATED_OBSERVER"
            ),
            ctx["obs_headers"],
        )
    )
    get_success_data(
        api.screen_evaluation(
            eval2["id"],
            f.screen_payload(no_go_signs=["CONFUSION"], symptom_score=9),
            ctx["doc_h_headers"],
        )
    )
    fx.set_clock(api, "2026-10-04T19:52:00Z")
    get_success_data(
        api.start_locker_room_exam(
            eval2["id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
        )
    )
    # Eight whole minutes of examination is the minimum any conclusion may carry.
    fx.set_clock(api, "2026-10-04T20:00:00Z")

    # Act: document the second concussion at composite 70 against the 87 retest.
    case2 = validate_success(
        api.diagnose_concussion(
            eval2["id"],
            f.diagnose_payload(
                symptom_score=9,
                composite_score=70,
                documentation_note="second concussion this season",
            ),
            ctx["doc_h_headers"],
        ),
        201,
    )

    # Assert: 40 base + min(30, 3*9)=27 symptom + min(24, 12*0)=0 recurrence
    #         + 10 history + min(15, round_half_up(1.5 * (87 - 70)) = 26) = 15  ->  92
    a.assert_case_progress(
        case2, rtp_stage=0, recurrence_count=0, severity_index=92, earliest_return_at=None
    )
    assert case2["prior_case_id"] == ctx["case_id"], (
        "the earlier case in the same season_year is the prior case"
    )
    assert case2["baseline_deviation_points"] == 17, "87 - 70, floored at 0"
    assert case2["case_status"] == "MANDATORY_REMOVAL"
    # severity_index 92 >= 70, so seven days plus a further three: 240 hours out.
    a.assert_instant(case2["projected_return_at"], "2026-10-14T20:00:00.000Z")
    a.assert_millisecond_timestamp(case2["projected_return_at"])

    # The first case is scored once and never re-scored by a later diagnosis.
    first_case = fx.read_case(api, ctx["case_id"])
    a.assert_case_progress(first_case, severity_index=82)
    assert first_case["case_status"] == "CLEARED_FOR_CONTACT"

    player = fx.read_player(api, ctx["player_id"])
    assert player["diagnosed_case_count"] == 2
    assert player["public_injury_designation"] == "OUT"


def test_severity_threshold_of_70_splits_the_provisional_return_projection(api):
    """Severity exactly 70 buys the extra three days; severity 67 does not.

    PRD: "A `severity_index` of at least 70 marks the case high-severity, which matters both to the return timeline and to fine pricing."
    PRD: "At the same time the server stamps `projected_return_at`, the **provisional projection** of when the player might come back: `diagnosis_at` plus seven days, plus a further three days when `severity_index` is at least 70."

    Design: Corner/calculations/severity_threshold_splits_provisional_return_projection
    """
    # Arrange: the canonical examination under way, plus a second Harbor City
    # player carrying the same composite-88 baseline.
    ctx = fx.setup_locker_room_exam(api)
    player_b = fx.create_player(api, ctx["club_h_id"], "T Adeyemi", 33, "LB")
    fx.file_baseline(
        api,
        player_b["id"],
        ctx["doc_h_id"],
        composite_score=88,
        reaction_time_ms=530,
        symptom_score=0,
        expected_player_version=player_b["version"],
    )

    # Act (high side): symptom 9, composite 86 against the 88 baseline.
    fx.set_clock(api, fx.DIAGNOSIS_AT)  # 2026-09-13T18:19:00Z
    case_hi = validate_success(
        api.diagnose_concussion(
            ctx["eval_id"],
            f.diagnose_payload(symptom_score=9, composite_score=86),
            ctx["doc_h_headers"],
        ),
        201,
    )

    # Act (low side): the same composite, one symptom point fewer.
    fx.set_clock(api, "2026-09-13T18:20:00Z")
    eval_lo = get_success_data(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                player_b["id"], ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
            ),
            ctx["doc_h_headers"],
        )
    )
    get_success_data(
        api.screen_evaluation(
            eval_lo["id"],
            f.screen_payload(no_go_signs=[], symptom_score=8),
            ctx["doc_h_headers"],
        )
    )
    fx.set_clock(api, "2026-09-13T18:21:00Z")
    get_success_data(
        api.start_locker_room_exam(
            eval_lo["id"], f.locker_room_exam_payload(ctx["inc_id"]), ctx["doc_h_headers"]
        )
    )
    fx.set_clock(api, "2026-09-13T18:29:00Z")
    case_lo = validate_success(
        api.diagnose_concussion(
            eval_lo["id"],
            f.diagnose_payload(symptom_score=8, composite_score=86),
            ctx["doc_h_headers"],
        ),
        201,
    )

    # Assert: 40 + min(30, 3*9)=27 + min(15, round_half_up(1.5 * (88 - 86)) = 3) = 3  ->  70
    a.assert_case_progress(case_hi, severity_index=70, earliest_return_at=None)
    a.assert_instant(case_hi["projected_return_at"], "2026-09-23T18:19:00.000Z")

    # 40 + min(30, 3*8)=24 + 3  ->  67, three points under the high-severity line.
    a.assert_case_progress(case_lo, severity_index=67, earliest_return_at=None)
    a.assert_instant(case_lo["projected_return_at"], "2026-09-20T18:29:00.000Z")


def test_compliance_score_and_fine_ledger_exclude_open_audits(api):
    """An OPEN audit raises open_violation_count only; it scores and prices nothing.

    PRD: "Audits that are still `OPEN`, and audits that closed dismissed, are excluded from both figures."
    PRD: "`compliance_score` is the **preliminary** figure: it starts at 100 and is the greater of 0 and 100 minus the sum, taken over every audit of that club whose `status` is `FINDINGS_ISSUED`, `CLUB_RESPONDED` or `CLOSED_UPHELD`, of the weights of that audit's `violation_codes`."

    Design: Corner/calculations/compliance_score_excludes_open_audits
    """
    # Arrange: a club with no audit history at all.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api)

    # Act 1: open an audit and read the club's computed posture.
    audit = validate_success(
        api.create_protocol_audit({"club_id": club["id"]}, AUDITOR_A), 201
    )
    summary_open = validate_success(api.get_compliance_summary(club["id"], AUDITOR_A))

    # Assert 1: nothing is charged while the audit is merely OPEN.
    a.assert_club_posture(
        summary_open,
        compliance_score=100,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=0,
        open_violation_count=1,
        adjudicated_compliance_score=100,
    )

    # Act 2: a second auditor prices the audit, then a further audit is opened.
    priced = validate_success(
        api.issue_findings(
            audit["id"],
            f.findings_payload(["MISSED_MANDATORY_REMOVAL"], exposure_days=0),
            AUDITOR_B,
        )
    )
    audit_b = validate_success(
        api.create_protocol_audit({"club_id": club["id"]}, AUDITOR_A), 201
    )
    summary_priced = validate_success(api.get_compliance_summary(club["id"], AUDITOR_A))

    # Assert 2: exposure factor (7+0)/7 = 1 and severity factor 1.00 on a null
    # case_id, so the single line is 15000000 * 1 * 1 = 15000000, and the stamped
    # TIER_0 multiplier of 1.00 leaves it there.
    assert priced["assessed_fine_cents"] == VIOLATION_BASE_CENTS["MISSED_MANDATORY_REMOVAL"]
    assert priced["assessed_fine_cents"] == 15_000_000
    assert priced["escalation_tier_at_issuance"] == "TIER_0"
    assert priced["status"] == "FINDINGS_ISSUED"

    # 100 - 18 = 82: TIER_1 (75..89) and PROBATION (70..89) on the preliminary score,
    # while the adjudicated score stays at 100 because nothing closed upheld.
    assert VIOLATION_WEIGHT["MISSED_MANDATORY_REMOVAL"] == 18
    a.assert_club_posture(
        summary_priced,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15_000_000,
        open_violation_count=2,  # the FINDINGS_ISSUED audit and the new OPEN one
        adjudicated_compliance_score=100,
    )

    # The freshly opened audit is unpriced and untiered.
    audit_b_row = fx.read_audit(api, audit_b["id"])
    assert audit_b_row["assessed_fine_cents"] == 0
    a.assert_null(audit_b_row, "escalation_tier_at_issuance")


def test_audit_fine_line_rounds_half_up_on_the_exact_exposure_factor(api):
    """2500000 * 8/7 lands on 2857143, not the truncated 2857142.

    PRD: "The **exposure factor** is 7 plus `exposure_days`, all divided by 7, held as an exact rational and never pre-rounded."
    PRD: "The rounded lines are summed to a gross figure, and `assessed_fine_cents` is that gross figure multiplied by the tier multiplier of the **stamped** `escalation_tier_at_issuance` — 1.00 for `TIER_0`, 1.50 for `TIER_1`, 2.00 for `TIER_2`, 3.00 for `TIER_3` — rounded half up once more."

    Design: Corner/calculations/audit_fine_line_rounding_precision_on_exposure_factor
    """
    # Arrange: a clean club and an audit with no linked case, so the severity
    # factor is 1.00 and the stamped tier multiplier is 1.00.
    fx.set_clock(api, DEFAULT_CLOCK)
    club = fx.create_club(api)
    audit = fx.open_audit(api, club["id"])

    # Act: one BASELINE_TEST_MISSING line at exposure_days 1.
    priced = validate_success(
        api.issue_findings(
            audit["id"],
            f.findings_payload(["BASELINE_TEST_MISSING"], exposure_days=1),
            AUDITOR_B,
        )
    )

    # Assert: 2500000 * (7+1)/7 = 20000000/7 = 2857142.857... -> 2857143 per line,
    # summed to a gross of 2857143, then * 1.00 for TIER_0 -> 2857143.
    assert VIOLATION_BASE_CENTS["BASELINE_TEST_MISSING"] == 2_500_000
    assert priced["assessed_fine_cents"] == 2_857_143
    assert priced["escalation_tier_at_issuance"] == "TIER_0"
    assert priced["exposure_days"] == 1

    # 100 - 8 = 92 keeps the club in TIER_0 and ACTIVE, with the fine outstanding.
    club_row = fx.read_club(api, club["id"])
    a.assert_club_posture(
        club_row,
        compliance_score=92,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=2_857_143,
    )
    audits, _meta = validate_paginated(api.list_protocol_audits(ADMIN, club_id=club["id"]))
    a.assert_fine_ledger_reconciles(club_row, audits)


def test_injury_report_window_boundaries_classify_a_filing(api):
    """96 hours and 90 minutes before kickoff split refusal, FILED and LATE_FILED.

    PRD: "The window opens four days before `kickoff_at` and the late line falls ninety minutes before it."
    PRD: "A filing at or after the opening instant but strictly before the late line is stamped `FILED`."

    Design: Corner/calculations/injury_report_window_boundaries_classify_filing
    """
    # Arrange: three healthy Harbor City players (no cases at all, so the league
    # resolves required_designation to NONE) and a 2026-09-13T17:00:00Z kickoff.
    fx.set_clock(api, DEFAULT_CLOCK)
    club_h = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    player_a = fx.create_player(api, club_h["id"], "K Mbeki", 24, "WR")
    player_b = fx.create_player(api, club_h["id"], "T Adeyemi", 33, "LB")
    player_c = fx.create_player(api, club_h["id"], "L Duarte", 41, "TE")
    game = fx.create_game(api, club_h["id"], club_r["id"])  # kickoff 2026-09-13T17:00:00Z
    officer = make_compliance_officer_headers(club_h["id"])

    # The two window instants are derived from kickoff and stamped on the game.
    a.assert_instant(game["report_window_opens_at"], "2026-09-09T17:00:00.000Z")
    a.assert_instant(game["report_window_closes_at"], "2026-09-13T15:30:00.000Z")

    # Act/Assert 1: one second before the window opens.
    fx.set_clock(api, "2026-09-09T16:59:59Z")
    validate_error(
        api.create_injury_report_entry(
            f.injury_report_payload(game["id"], player_a["id"], "FULL", "NONE"), officer
        ),
        ERR_REPORT_WINDOW_NOT_OPEN,
        expected_status=409,
    )

    # Act/Assert 2: exactly at the opening instant the filing is on time.
    fx.set_clock(api, "2026-09-09T17:00:00Z")
    on_time = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(game["id"], player_a["id"], "FULL", "NONE"), officer
        ),
        201,
    )
    assert on_time["status"] == "FILED"
    assert on_time["required_designation"] == "NONE"
    assert on_time["club_id"] == club_h["id"]
    a.assert_instant(on_time["filed_at"], "2026-09-09T17:00:00.000Z")
    a.assert_null(on_time, "amended_at", "amended_from_designation")

    # Act/Assert 3: exactly at the late line the filing is late and self-audits.
    fx.set_clock(api, "2026-09-13T15:30:00Z")
    late = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(game["id"], player_b["id"], "LIMITED", "NONE"), officer
        ),
        201,
    )
    assert late["status"] == "LATE_FILED"

    audits, meta = validate_paginated(api.list_protocol_audits(ADMIN, club_id=club_h["id"]))
    assert meta["total_count"] == 1, "exactly one auto-opened audit for the late filing"
    auto = audits[0]
    assert auto["auto_opened"] is True
    a.assert_null(auto, "opened_by_user_id", "case_id")
    assert auto["violation_codes"] == ["LATE_INJURY_REPORT"]
    assert auto["exposure_days"] == 0
    assert auto["status"] == "FINDINGS_ISSUED"
    assert auto["escalation_tier_at_issuance"] == "TIER_0"
    # 1500000 * (7+0)/7 * 1.00 severity = 1500000 per line, * 1.00 for TIER_0.
    assert auto["assessed_fine_cents"] == 1_500_000

    club_row = fx.read_club(api, club_h["id"])
    # 100 - 6 for LATE_INJURY_REPORT leaves 94: still TIER_0 and ACTIVE.
    assert VIOLATION_WEIGHT["LATE_INJURY_REPORT"] == 6
    a.assert_club_posture(
        club_row,
        compliance_score=94,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=1_500_000,
        open_violation_count=1,
    )

    # Act/Assert 4: at kickoff the window has closed outright.
    fx.set_clock(api, "2026-09-13T17:00:00Z")
    validate_error(
        api.create_injury_report_entry(
            f.injury_report_payload(game["id"], player_c["id"], "DNP", "NONE"), officer
        ),
        ERR_REPORT_WINDOW_CLOSED,
        expected_status=409,
    )


def test_post_clearance_questionable_window_is_half_open_at_72_hours(api):
    """QUESTIONABLE two days after clearance; NONE at exactly the 72-hour mark.

    PRD: "`QUESTIONABLE` when the same 72-hour window still applies and that case's `recurrence_count` is 0."
    PRD: "The post-clearance window is half-open: at exactly 72 hours after `cleared_for_contact_at` the window has closed and the designation falls to `NONE`."

    Design: Corner/calculations/post_clearance_questionable_window_is_half_open
    """
    # Arrange: the canonical case cleared for contact at 2026-09-28T12:00:00Z with
    # no recurrences, plus a week-5 game kicking off 2026-10-02T17:00:00Z.
    ctx = fx.setup_case_with_approved_clearance(api)
    validate_success(
        api.return_to_contact(
            ctx["case_id"], f.return_to_contact_payload(), ctx["doc_h_headers"]
        )
    )
    case = fx.read_case(api, ctx["case_id"])
    a.assert_instant(case["cleared_for_contact_at"], "2026-09-28T12:00:00.000Z")
    a.assert_case_progress(case, recurrence_count=0)

    game_w5 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        week_index=5,
        kickoff_at="2026-10-02T17:00:00Z",
    )
    officer = ctx["club_h_headers"]

    # Act/Assert 1: inside the window (60 hours after clearance) the league still
    # requires QUESTIONABLE, because recurrence_count is 0 rather than 1 or more.
    fx.set_clock(api, "2026-09-30T00:00:00Z")
    entry = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(
                game_w5["id"], ctx["player_id"], "LIMITED", "QUESTIONABLE"
            ),
            officer,
        ),
        201,
    )
    assert entry["status"] == "FILED"
    assert entry["required_designation"] == "QUESTIONABLE"

    # Act/Assert 2: at exactly 2026-09-28T12:00 + 72h the window has closed, so
    # QUESTIONABLE no longer matches the freshly recomputed required designation.
    fx.set_clock(api, "2026-10-01T12:00:00Z")
    validate_error(
        api.amend_injury_report_entry(
            entry["id"], f.injury_report_amendment_payload("FULL", "QUESTIONABLE"), officer
        ),
        ERR_INJURY_DESIGNATION_MISMATCH,
        expected_status=422,
    )

    # Act/Assert 3: NONE is the value the league now resolves.
    amended = validate_success(
        api.amend_injury_report_entry(
            entry["id"], f.injury_report_amendment_payload("FULL", "NONE"), officer
        )
    )
    assert amended["status"] == "AMENDED"
    assert amended["designation"] == "NONE"
    assert amended["required_designation"] == "NONE"
    assert amended["amended_from_designation"] == "QUESTIONABLE"
    a.assert_instant(amended["amended_at"], "2026-10-01T12:00:00.000Z")


def test_baseline_status_ignores_superseded_and_invalidated_rows(api):
    """Invalidating the only VALID row yields NONE, never a fallback to the superseded one.

    PRD: "A player's `baseline_status` is never set directly; it is resolved from the player's baseline rows every time one of them changes, and only rows whose `status` is `VALID` are considered at all — `SUPERSEDED`, `INVALIDATED` and `EXPIRED` rows are ignored entirely."
    PRD: "When no `VALID` row remains, `baseline_status` is `NONE`."

    Design: Corner/calculations/baseline_status_ignores_superseded_and_invalidated_rows
    """
    # Arrange: K Mbeki with one pre-season baseline at composite 88.
    ctx = fx.setup_reference_data(api)
    assert fx.read_baseline(api, ctx["baseline_id"])["status"] == "VALID"

    # Act 1: a second filing supersedes the first.
    second = validate_success(
        api.create_baseline_test(
            f.baseline_payload(
                ctx["player_id"],
                expected_player_version=fx.player_version(api, ctx["player_id"]),
                composite_score=80,
                reaction_time_ms=560,
                symptom_score=1,
            ),
            make_club_physician_headers(ctx["doc_h_id"]),
        ),
        201,
    )

    # Assert 1: the older row leaves the candidate set entirely.
    assert second["status"] == "VALID"
    assert second["retest_required_reason"] == "NONE"
    assert fx.read_baseline(api, ctx["baseline_id"])["status"] == "SUPERSEDED"
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "VALID"

    # Act 2: the league invalidates that second row administratively.
    invalidated = validate_success(
        api.invalidate_baseline_test(
            second["id"], f.invalidate_payload("wrong test battery administered"), ADMIN
        )
    )

    # Assert 2: no VALID row survives, and the superseded 88 is never resurrected.
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["retest_required_reason"] == "ADMIN_INVALIDATION"
    assert fx.read_baseline(api, ctx["baseline_id"])["status"] == "SUPERSEDED"
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "NONE"


def test_exemption_slot_ledger_refuses_the_overdrawing_grant(api):
    """With one slot the second grant is refused rather than clamped to zero.

    PRD: "Against that total the server maintains two derived counters: `exemption_slots_used` is the number of that club's cases whose `roster_exemption_status` is `GRANTED`, and `exemption_slots_available` is `exemption_slots_total` minus `exemption_slots_used`."
    PRD: "A grant that would drive the available count below 0 is refused with `ERR_NO_EXEMPTION_SLOTS` rather than being clamped to 0."

    Design: Corner/calculations/exemption_slot_ledger_refuses_overdraw
    """
    # Arrange: a club declaring exactly one exemption slot, two of whose players
    # are diagnosed during one live game.
    fx.set_clock(api, DEFAULT_CLOCK)
    club_n = fx.create_club(api, "Northshore Pilots", "NSP", 1)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    doc_n = fx.create_club_physician(api, club_n["id"], "Dr Larkin", "LIC-1101")
    observer = fx.create_observer(api)
    consultant = fx.create_consultant(api)
    doc_headers = make_club_physician_headers(doc_n["id"])
    obs_headers = make_observer_headers(observer["id"])

    players = [
        fx.create_player(api, club_n["id"], "P Novak", 11, "QB"),
        fx.create_player(api, club_n["id"], "S Okafor", 12, "RB"),
    ]
    for player, reaction_time_ms in zip(players, (520, 525)):
        fx.file_baseline(
            api,
            player["id"],
            doc_n["id"],
            composite_score=88,
            reaction_time_ms=reaction_time_ms,
            symptom_score=0,
            expected_player_version=player["version"],
        )

    game = fx.create_game(
        api,
        club_n["id"],
        club_r["id"],
        week_index=2,
        kickoff_at="2026-09-20T17:00:00Z",
    )
    fx.set_clock(api, "2026-09-20T17:00:00Z")
    fx.advance_game(api, game["id"], "IN_PROGRESS")

    # Two removals, each attended by a different consultant so the 30-minute
    # examination blocks cannot collide.
    case_ids = []
    for player, attendant_id, initiated_at, diagnosed_at in (
        (players[0], observer["id"], "2026-09-20T18:00:00Z", "2026-09-20T18:09:00Z"),
        (players[1], consultant["id"], "2026-09-20T18:10:00Z", "2026-09-20T18:19:00Z"),
    ):
        fx.set_clock(api, initiated_at)
        evaluation = get_success_data(
            api.create_sideline_evaluation(
                f.evaluation_payload(
                    player["id"], game["id"], trigger_source="UNAFFILIATED_OBSERVER"
                ),
                obs_headers,
            )
        )
        get_success_data(
            api.screen_evaluation(
                evaluation["id"],
                f.screen_payload(no_go_signs=["ATAXIA"], symptom_score=9),
                doc_headers,
            )
        )
        get_success_data(
            api.start_locker_room_exam(
                evaluation["id"], f.locker_room_exam_payload(attendant_id), doc_headers
            )
        )
        fx.set_clock(api, diagnosed_at)  # nine whole examination minutes
        case = get_success_data(
            api.diagnose_concussion(
                evaluation["id"],
                f.diagnose_payload(symptom_score=9, composite_score=70),
                doc_headers,
            )
        )
        case_ids.append(case["id"])

    officer = make_compliance_officer_headers(club_n["id"])

    # Act 1: the club's single slot is consumed.
    granted = validate_success(api.grant_roster_exemption(case_ids[0], officer))
    assert granted["roster_exemption_status"] == "GRANTED"

    # Act/Assert 2: the second grant would drive available to -1, so it is refused.
    validate_error(
        api.grant_roster_exemption(case_ids[1], officer),
        ERR_NO_EXEMPTION_SLOTS,
        expected_status=409,
    )
    assert fx.read_case(api, case_ids[1])["roster_exemption_status"] == "NONE"

    # Assert: used 1 + available 0 == total 1 at this observable instant.
    summary = validate_success(api.get_compliance_summary(club_n["id"], officer))
    a.assert_exemption_slots(summary, used=1, available=0, total=1)


def test_stage_gating_windows_are_stamped_from_the_rest_and_dwell_tables(api):
    """Each rung's min_start_at and dwell_complete_at land on their exact instants.

    PRD: "For stage 1 there is no buffer and `min_start_at` equals the case's `diagnosis_at`."
    PRD: "For stages 2, 3 and 4 the buffer is one day after the previous stage's sign-off; for stage 5 it is two days."
    PRD: "Stages 1, 2 and 3 each require one day; stages 4 and 5 each require two days."

    Design: Corner/calculations/stage_gating_windows_stamped_from_constants
    """
    # Arrange/Act: all five rungs opened and passed on their earliest legal
    # instants, from a diagnosis stamped at 2026-09-13T18:19:00.000Z.
    ctx = fx.setup_case_all_stages_passed(api)

    # (min_start_at, started_at, dwell_complete_at) per stage.
    # Stage 1: min_start is diagnosis_at itself; stages 2-4 add 24h to the previous
    # sign-off, stage 5 adds 48h.  Dwell is 24/24/24/48/48 hours after each start.
    expected = {
        1: ("2026-09-13T18:19:00.000Z", "2026-09-15T12:00:00.000Z", "2026-09-16T12:00:00.000Z"),
        2: ("2026-09-17T12:00:00.000Z", "2026-09-17T12:00:00.000Z", "2026-09-18T12:00:00.000Z"),
        3: ("2026-09-19T12:00:00.000Z", "2026-09-19T12:00:00.000Z", "2026-09-20T12:00:00.000Z"),
        4: ("2026-09-21T12:00:00.000Z", "2026-09-21T12:00:00.000Z", "2026-09-23T12:00:00.000Z"),
        5: ("2026-09-25T12:00:00.000Z", "2026-09-25T12:00:00.000Z", "2026-09-27T12:00:00.000Z"),
    }

    # Assert: every stamped instant is millisecond-exact, with no day rounding.
    for stage_index, (min_start_at, started_at, dwell_complete_at) in expected.items():
        step = fx.read_step(api, ctx["step_ids"][stage_index])
        a.assert_return_step(
            step,
            stage_index=stage_index,
            status="PASSED",
            attempt_index=1,
            started_at=started_at,
            min_start_at=min_start_at,
            dwell_complete_at=dwell_complete_at,
        )
        assert step["cleared_by_clinician_id"] == ctx["doc_h_id"]
        a.assert_millisecond_timestamp(step["min_start_at"])
        a.assert_millisecond_timestamp(step["dwell_complete_at"])

    # The stage-5 sign-off accrues the gating return date: 2026-09-27T12:00 + 24h
    # and no recurrence penalty at all.
    case = fx.read_case(api, ctx["case_id"])
    a.assert_case_progress(
        case,
        rtp_stage=5,
        recurrence_count=0,
        earliest_return_at="2026-09-28T12:00:00.000Z",
    )
    assert case["case_status"] == "RTP_IN_PROGRESS"
