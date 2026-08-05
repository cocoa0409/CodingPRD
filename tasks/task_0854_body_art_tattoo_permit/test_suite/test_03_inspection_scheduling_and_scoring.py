"""Booking visit windows, conducting them and scoring them."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    cite_violation,
    create_open_violations,
    decide_correction,
    submit_correction,
    create_permitted_establishment,
    finalize_inspection,
    read_establishment,
    register_establishment,
    schedule_inspection,
    set_clock,
    start_inspection_at,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
INSP = TEST_USERS["inspector_headers"]

FIVE_NONCRITICAL = [
    ("STER_004", "NONCRITICAL"),
    ("HAND_002", "NONCRITICAL"),
    ("SIGN_001", "NONCRITICAL"),
    ("WASTE_003", "NONCRITICAL"),
    ("TOWEL_005", "NONCRITICAL"),
]


def test_finalize_before_the_visit_starts_is_rejected(api):
    """PRD §3.3: "Closing computes the score, writes it to `score`, stamps
    `finalized_at` with the current logical-clock instant, and branches the visit to
    either `IN_PROGRESS → PASSED` or `IN_PROGRESS → FAILED`."
    PRD §3.3: "The new visit is born `SCHEDULED` with `inspector_user_id` null, `score`
    null, `finalized_at` null, `open_violation_count_at_start` at zero and
    `source_complaint_id` null."
    PRD §2.9: "Every action route that drives a state machine first checks that its
    target sits in a state the requested transition declares as its origin."

    Design: Corner/state_machines/finalize_inspection_while_still_scheduled_is_rejected
    """
    establishment = register_establishment(
        name="Unstarted Ink", street_address="10 Tenth St"
    )
    inspection = schedule_inspection(
        establishment["id"],
        inspection_type="PREOPENING",
        scheduled_start_at="2026-05-01T00:00:00Z",
        scheduled_end_at="2026-05-01T02:00:00Z",
    )

    response = api.finalize_inspection(inspection["id"], INSP)
    validate_error(response, ApiErrorId.ERR_INSPECTION_STATE_INVALID.value)
    assert response.status_code == 409

    stored = validate_success(api.get_inspection(inspection["id"], HO))
    assert stored["status"] == "SCHEDULED"
    assert stored["score"] is None


def test_starting_the_same_visit_twice_is_rejected(api):
    """PRD §3.3: "Beginning the visit is the starting `Inspector`'s act and drives
    `SCHEDULED → IN_PROGRESS`."
    PRD §3.3: "Two things are written at that moment: `inspector_user_id` takes the
    calling `X-User-ID`, and the establishment's current `open_violation_count` is
    snapshotted into `open_violation_count_at_start`."

    Design: Corner/state_machines/start_inspection_twice_is_rejected_on_second_attempt
    """
    establishment = register_establishment(name="Twice Ink", street_address="11 Eleventh St")
    inspection = schedule_inspection(
        establishment["id"],
        inspection_type="PREOPENING",
        scheduled_start_at="2026-05-01T00:00:00Z",
        scheduled_end_at="2026-05-01T02:00:00Z",
    )
    started = validate_success(api.start_inspection(inspection["id"], INSP))
    assert started["status"] == "IN_PROGRESS"

    again = api.start_inspection(inspection["id"], INSP)
    validate_error(again, ApiErrorId.ERR_INSPECTION_STATE_INVALID.value)
    assert again.status_code == 409

    stored = validate_success(api.get_inspection(inspection["id"], HO))
    assert stored["status"] == "IN_PROGRESS"
    assert stored["inspector_user_id"] == "officer-insp-1"


def test_carryover_term_is_capped_at_twenty_points(api):
    """PRD §3.3: "**Step two** adds the carryover term: five points for every violation
    counted in `open_violation_count_at_start`, capped so that the carryover
    contribution can never exceed 20 points no matter how large the backlog."
    PRD §3.3: "**Step four** performs the one and only final rounding: the raw deduction
    and the carryover are added together, that sum is multiplied by the type factor,
    the product is rounded half up to a whole point, and the result is subtracted from
    a perfect score of 100."

    Design: Corner/calculations/inspection_score_carryover_is_capped_at_twenty
    """
    establishment = create_permitted_establishment(
        name="Carryover Ink", street_address="24 Twentyfourth St"
    )
    first, _ = create_open_violations(
        establishment["id"], FIVE_NONCRITICAL, finalize=True
    )
    assert first["score"] == 70, f"Five non-critical lines deduct 30, got {first['score']}"

    second = start_inspection_at(
        establishment["id"], "2026-05-12T00:00:00Z", "2026-05-12T02:00:00Z"
    )
    assert second["open_violation_count_at_start"] == 5

    finalized = finalize_inspection(second["id"])
    assert finalized["score"] == 80, (
        f"min(20, 5 * 5) is 20 and nothing was cited, so the score is 80, got {finalized['score']}"
    )
    assert finalized["status"] == "PASSED"

    parent = read_establishment(establishment["id"])
    assert parent["open_violation_count"] == 5
    assert parent["risk_score"] == 50


def test_score_landing_exactly_on_seventy_passes_the_visit(api):
    """PRD §3.3: "A citation of `severity` `CRITICAL` starts from a base of 12 points
    and a citation of `severity` `NONCRITICAL` starts from a base of 6 points."
    PRD §3.3: "It fails when the score is strictly below 70, or when at least one
    cited violation is `CRITICAL` — a single critical finding fails the visit
    regardless of how good the arithmetic looks."

    Design: Difficulty/boundary_precision_check/inspection_score_exactly_at_pass_threshold_passes
    """
    establishment = create_permitted_establishment(
        name="Threshold Tattoo", street_address="70 Fir Ave"
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    assert inspection["open_violation_count_at_start"] == 0

    for code, severity in FIVE_NONCRITICAL:
        cite_violation(inspection["id"], code, severity, f"{code} observed.")

    finalized = finalize_inspection(inspection["id"])
    assert finalized["score"] == 70, (
        f"Five non-critical lines deduct exactly 30, so the score is 70, got {finalized['score']}"
    )
    assert finalized["status"] == "PASSED", (
        "70 is at the pass mark, so the comparison must admit equality"
    )


def test_passing_visit_leaves_open_counters_and_spawns_no_follow_up(api):
    """PRD §3.3: "Both branches write `score` and `finalized_at`, and both recompute
    the establishment's `risk_score` and `operating_posture`."
    PRD §3.3: "A passing visit spawns nothing either."
    PRD §3.7: "The open-non-critical term contributes 5 points for each violation in
    the open set that is not critical — that is, for the difference between
    `open_violation_count` and `open_critical_violation_count`."

    Design: Difficulty/boundary_precision_check/inspection_score_exactly_at_pass_threshold_passes
    """
    establishment = create_permitted_establishment(
        name="Threshold Tattoo Two", street_address="71 Fir Ave"
    )
    inspection, _ = create_open_violations(
        establishment["id"], FIVE_NONCRITICAL, finalize=True
    )
    assert inspection["status"] == "PASSED"

    parent = read_establishment(establishment["id"])
    assert parent["open_violation_count"] == 5
    assert parent["open_critical_violation_count"] == 0
    assert parent["risk_score"] == 50, (
        f"25 sterilization points plus 5 x 5 open non-critical, got {parent['risk_score']}"
    )
    assert parent["operating_posture"] == "OPEN"

    rows, meta = validate_paginated(
        api.list_inspections(
            HO,
            params={
                "establishment_id": establishment["id"],
                "inspection_type": "REINSPECTION",
            },
        )
    )
    assert meta["total_count"] == 0, "A passing visit spawns no follow-up"


def _reinspection_scenario():
    """Failed ROUTINE citing BBP_001 (verified afterwards) plus two open lines, then a
    REINSPECTION ten days later citing the same BBP_001 code again."""
    establishment = create_permitted_establishment(
        name="Iron Rose", street_address="9 Elm Rd"
    )
    first = start_inspection_at(
        establishment["id"], "2026-05-10T00:00:00Z", "2026-05-10T02:00:00Z"
    )
    v1 = cite_violation(first["id"], "BBP_001", "CRITICAL", "Sharps container overfull.")
    cite_violation(first["id"], "STER_004", "NONCRITICAL", "Autoclave log gap.")
    cite_violation(first["id"], "HAND_002", "NONCRITICAL", "Handwash soap empty.")
    first_final = finalize_inspection(first["id"])

    submit_correction(v1["id"], establishment["id"], "Sharps container replaced and logged.")
    decide_correction(v1["id"], "VERIFY")

    second = schedule_inspection(
        establishment["id"],
        inspection_type="REINSPECTION",
        scheduled_start_at="2026-05-20T00:00:00Z",
        scheduled_end_at="2026-05-20T02:00:00Z",
    )
    set_clock("2026-05-20T00:00:00Z")
    started = validate_success(api_client.start_inspection(second["id"], INSP))
    v4 = cite_violation(
        started["id"], "BBP_001", "CRITICAL", "Sharps container overfull again."
    )
    v5 = cite_violation(
        started["id"], "STER_009", "NONCRITICAL", "Weekly spore test not run."
    )
    return establishment, first_final, started, v4, v5


def test_reinspection_factor_multiplies_the_combined_sum_once(api):
    """PRD §3.3: "Each line is then tested for repetition: the line counts as a repeat
    when some other violation exists at the same establishment carrying an identical
    `violation_code`, having a different identifier, sitting in status `VERIFIED` or
    `ESCALATED`, and whose `issued_at` falls at or after the instant 365 days before
    this inspection's `scheduled_start_at` and strictly before that
    `scheduled_start_at` itself."
    PRD §3.3: "**Step three** selects the inspection-type factor, which is 1.25 when this
    visit's own `inspection_type` is `REINSPECTION` and 1.00 for every other type — a
    re-visit is scored more harshly because the shop has already had its chance."
    PRD §3.3: "Note carefully that the type factor is applied once, to the combined
    sum, and not per line."

    Design: Difficulty/combinatorial_formula/reinspection_factor_applies_after_repeat_and_carryover_are_summed
    """
    establishment, first_final, started, _v4, _v5 = _reinspection_scenario()

    assert first_final["score"] == 76, (
        f"12 + 6 + 6 with no carryover leaves 76, got {first_final['score']}"
    )
    assert started["open_violation_count_at_start"] == 2, (
        "BBP_001 was verified, so only the two non-critical lines remain open"
    )

    finalized = finalize_inspection(started["id"])
    assert finalized["score"] == 57, (
        "18 + 6 raw plus a capped carryover of 10 is 34, times 1.25 is 42.5 rounded to "
        f"43, leaving 57, got {finalized['score']}"
    )
    assert finalized["status"] == "FAILED"


def test_reinspection_writes_per_line_repeat_multiplier_and_deduction_points(api):
    """PRD §3.3: "A repeat line records `repeat_multiplier_applied` of 1.5; a
    first-time line records 1.0. The line's `deduction_points` is the base multiplied
    by that factor, rounded half up to a whole point."
    PRD §3.3: "A citation of `severity` `CRITICAL` starts from a base of 12 points and
    a citation of `severity` `NONCRITICAL` starts from a base of 6 points."

    Design: Difficulty/combinatorial_formula/reinspection_factor_applies_after_repeat_and_carryover_are_summed
    """
    _establishment, _first_final, started, v4, v5 = _reinspection_scenario()
    finalize_inspection(started["id"])

    repeat_line = validate_success(api.get_violation(v4["id"], HO))
    assert float(repeat_line["repeat_multiplier_applied"]) == 1.5
    assert repeat_line["deduction_points"] == 18

    fresh_line = validate_success(api.get_violation(v5["id"], HO))
    assert float(fresh_line["repeat_multiplier_applied"]) == 1.0
    assert fresh_line["deduction_points"] == 6


def test_buffered_inspection_windows_conflict_when_they_touch(api):
    """PRD §3.3: "Each window is expanded by one hour on both sides, giving a closed
    interval running from sixty minutes before `scheduled_start_at` to sixty minutes
    after `scheduled_end_at`."
    PRD §3.3: "Because the intervals are closed, expanded windows that merely touch at
    an endpoint do conflict — a proposed visit whose expanded interval begins at
    exactly the instant another expanded interval ends is a collision, not an
    adjacency. Any intersection is rejected with `ERR_INSPECTION_WINDOW_CONFLICT` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_windows_conflict_when_they_touch
    """
    establishment = create_permitted_establishment(
        name="Buffer Zone Body Art", street_address="23 Juniper Ln"
    )
    schedule_inspection(
        establishment["id"],
        inspection_type="ROUTINE",
        scheduled_start_at="2026-06-01T09:00:00Z",
        scheduled_end_at="2026-06-01T11:00:00Z",
    )

    touching = api.create_inspection(
        {
            "establishment_id": establishment["id"],
            "inspection_type": "ROUTINE",
            "scheduled_start_at": "2026-06-01T13:00:00Z",
            "scheduled_end_at": "2026-06-01T14:00:00Z",
        },
        INSP,
    )
    validate_error(touching, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT.value)
    assert touching.status_code == 409, (
        "Buffered [12:00, 15:00] meets buffered [08:00, 12:00] at exactly 12:00"
    )


def test_inspection_window_clear_of_the_buffer_is_accepted(api):
    """PRD §3.3: "The proposed expanded interval is compared against the identically
    expanded interval of every other inspection at the same establishment whose status
    is `SCHEDULED` or `IN_PROGRESS`; inspections that have already reached `PASSED`,
    `FAILED` or `CANCELLED` are ignored."
    PRD §3.3: "Each window is expanded by one hour on both sides, giving a closed
    interval running from sixty minutes before `scheduled_start_at` to sixty minutes
    after `scheduled_end_at`."

    Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_windows_conflict_when_they_touch
    """
    establishment = create_permitted_establishment(
        name="Buffer Zone Two", street_address="24 Juniper Ln"
    )
    schedule_inspection(
        establishment["id"],
        inspection_type="ROUTINE",
        scheduled_start_at="2026-06-01T09:00:00Z",
        scheduled_end_at="2026-06-01T11:00:00Z",
    )

    accepted = api.create_inspection(
        {
            "establishment_id": establishment["id"],
            "inspection_type": "ROUTINE",
            "scheduled_start_at": "2026-06-01T14:00:00Z",
            "scheduled_end_at": "2026-06-01T15:00:00Z",
        },
        INSP,
    )
    created = validate_success(accepted, 201)
    assert created["status"] == "SCHEDULED", (
        "Buffered [13:00, 16:00] starts strictly after the other window's 12:00 edge"
    )

    rows, meta = validate_paginated(
        api.list_inspections(
            HO, params={"establishment_id": establishment["id"], "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2
