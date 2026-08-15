"""Curfew compliance and the community annoyance index: engine-class tier
weights with the grace band, the PROBATION standing multiplier, closed-interval
curfew window conflicts, and the annoyance tier keyed on the base index only."""
import pytest

from test_helpers import (
    ApiErrorId,
    begin_review,
    close_complaint,
    correlate_complaint,
    create_complaint,
    create_complainant,
    create_curfew_rule,
    create_curfew_rule_payload,
    create_flight,
    create_notification,
    create_operated_flight,
    create_operator,
    operate_flight,
    send_notification,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]


def _setup_tiered_curfew_flights(api):
    """Operator + YEAR_ROUND DEPARTURE rule on 09L with window [1320, 1439] and
    grace 15 (violation interior [1335, 1424]), plus four flights:
    F1 STAGE_3 DEP, F2 STAGE_5 DEP, F3 STAGE_4 DEP, F4 STAGE_4 ARRIVAL."""
    operator = create_operator()
    create_curfew_rule(
        runway_code="09L",
        season="YEAR_ROUND",
        window_start_minute=1320,
        window_end_minute=1439,
        applies_to="DEPARTURE",
        grace_minutes=15,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    f1 = create_flight(
        operator["id"],
        aircraft_type="MD88",
        engine_class="STAGE_3",
        scheduled_at="2026-08-10T22:30:00Z",
    )
    f2 = create_flight(
        operator["id"],
        aircraft_type="A21N",
        engine_class="STAGE_5",
        scheduled_at="2026-08-11T22:30:00Z",
    )
    f3 = create_flight(operator["id"], scheduled_at="2026-08-12T22:10:00Z")
    f4 = create_flight(
        operator["id"], operation_type="ARRIVAL", scheduled_at="2026-08-12T22:45:00Z"
    )
    return operator, f1, f2, f3, f4


def _operate_tiered_curfew_flights(f1, f2, f3, f4):
    """F1/F2 land in the trimmed violation interior (minutes 1355/1360); F3 at
    minute 1334 sits in the grace band (movement only); F4 is an ARRIVAL missed
    by the DEPARTURE-scoped rule."""
    r1 = operate_flight(f1["id"], "2026-08-10T22:35:00Z")
    r2 = operate_flight(f2["id"], "2026-08-11T22:40:00Z")
    r3 = operate_flight(f3["id"], "2026-08-12T22:14:00Z")
    r4 = operate_flight(f4["id"], "2026-08-12T22:50:00Z")
    return r1, r2, r3, r4


def test_curfew_flags_grace_band_and_scope(api):
    """PRD 3.2: "A curfew movement is additionally a violation when two
    conditions hold: the minute-of-day lies inside the grace-trimmed interior of
    the window — from the window start plus the effective grace through the
    window end minus the effective grace, with those boundary minutes themselves
    counting as violations — and the flight's recorded `exemption_code` is
    `NONE`."
    PRD 3.2: "matching means the rule's runway equals the flight's
    `runway_code`, the rule's season covers the month of `actual_at`, the rule's
    `applies_to` covers the flight's `operation_type`, and the calendar date of
    `actual_at` lies between `effective_from` and `effective_to` inclusive."

    Design: Difficulty/combinatorial_formula/curfew_score_tiered_engine_weights_and_grace_band
    """
    _operator, f1, f2, f3, f4 = _setup_tiered_curfew_flights(api)
    r1, r2, r3, r4 = _operate_tiered_curfew_flights(f1, f2, f3, f4)

    # Minutes 1355 and 1360 lie inside the grace-trimmed interior [1335, 1424].
    assert r1["curfew_movement"] is True and r1["curfew_violation"] is True
    assert r2["curfew_movement"] is True and r2["curfew_violation"] is True
    # Minute 1334 is inside the window but inside the grace band.
    assert r3["curfew_movement"] is True and r3["curfew_violation"] is False
    # ARRIVAL is outside the DEPARTURE scope: not even a movement.
    assert r4["curfew_movement"] is False
    assert r4["curfew_violation"] is False


def test_curfew_score_engine_weights_and_standing_band(api):
    """PRD 3.2: "Each violation costs one hundred base points multiplied by an
    engine-class multiplier — one and a half for `STAGE_3`, one for `STAGE_4`,
    one half for `STAGE_5` — and by a standing multiplier of 1.25 when the
    operator is on `PROBATION`, otherwise 1.0."
    PRD 3.2: "The score itself is one thousand minus the summed points, floored
    at zero and rounded half-up to one decimal place. Standing bands follow from
    the score: 900 or above is `GOOD`, at least 700 but below 900 is `WATCH`,
    and below 700 is `PROBATION`."
    PRD 3.2: "computing it also stores the score on the operator's
    `compliance_score_latest` and updates the operator's stored
    `compliance_standing` to the band the score implies."

    Design: Difficulty/combinatorial_formula/curfew_score_tiered_engine_weights_and_grace_band
    """
    operator, f1, f2, f3, f4 = _setup_tiered_curfew_flights(api)
    _operate_tiered_curfew_flights(f1, f2, f3, f4)

    summary = validate_success(
        api.get_compliance_summary(operator["id"], ANALYST, params={"quarter": "2026-Q3"})
    )
    assert summary["curfew_movements"] == 3
    assert summary["curfew_violations"] == 2
    # 1000 - (100 * 1.5 STAGE_3) - (100 * 0.5 STAGE_5) = 800.0; the standing
    # multiplier read before this recalculation was GOOD (1.0).
    assert summary["score"] == pytest.approx(800.0, abs=1e-6)
    assert summary["standing"] == "WATCH"

    operator_after = validate_success(api.get_operator(operator["id"], ANALYST))
    assert operator_after["compliance_score_latest"] == pytest.approx(800.0, abs=1e-6)
    assert operator_after["compliance_standing"] == "WATCH"


def test_compliance_score_uses_probation_multiplier(api):
    """PRD 3.5: "an operator landing on `PROBATION` through escalation has its
    `curfew_grace_minutes` revoked to 0 and its future violation points weighted
    by the 1.25 standing multiplier."
    PRD 3.2: "The evaluation order is pinned: the standing multiplier always
    uses the operator's currently stored `compliance_standing` *before* this
    recalculation, so a freshly computed score never feeds back into its own
    arithmetic."
    PRD 3.2: "The effective grace is the smaller of the rule's `grace_minutes`
    and the operator's current `curfew_grace_minutes`; an operator whose grace
    has been revoked to zero therefore faces the untrimmed window."

    Design: Corner/calculations/compliance_score_uses_probation_multiplier
    """
    complainant = create_complainant()
    operator = create_operator()
    create_curfew_rule(
        runway_code="09L",
        season="YEAR_ROUND",
        window_start_minute=1320,
        window_end_minute=1439,
        applies_to="DEPARTURE",
        grace_minutes=15,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    complaint_a = create_complaint(complainant["id"], "2026-07-15T09:00:00Z")
    complaint_b = create_complaint(complainant["id"], "2026-07-16T09:00:00Z")
    n1 = create_notification(operator["id"], complaint_id=complaint_a["id"], subject="E1")
    n2 = create_notification(operator["id"], complaint_id=complaint_b["id"], subject="E2")
    send_notification(n1["id"])
    send_notification(n2["id"])
    # Two manual escalations: GOOD -> WATCH -> PROBATION, grace revoked to 0.
    validate_success(
        api.escalate_notification(n1["id"], {"escalation_reason": "no reply"}, ADMIN), 200
    )
    validate_success(
        api.escalate_notification(n2["id"], {"escalation_reason": "no reply again"}, ADMIN),
        200,
    )
    probationed = validate_success(api.get_operator(operator["id"], ANALYST))
    assert probationed["compliance_standing"] == "PROBATION"
    assert probationed["curfew_grace_minutes"] == 0

    for day in (3, 4, 5):
        flight = create_flight(
            operator["id"], scheduled_at=f"2026-08-{day:02d}T22:30:00Z"
        )
        operate_flight(flight["id"], f"2026-08-{day:02d}T22:35:00Z")

    summary = validate_success(
        api.get_compliance_summary(operator["id"], ANALYST, params={"quarter": "2026-Q3"})
    )
    assert summary["curfew_violations"] == 3
    # 1000 - 3 * 100 (STAGE_4 x1.0) * 1.25 (PROBATION, read before recompute).
    assert summary["score"] == pytest.approx(625.0, abs=1e-6)
    assert summary["standing"] == "PROBATION"


def test_curfew_rule_touching_minute_and_intersecting_season_conflict(api):
    """PRD 3.2: "A new rule conflicts with an existing `ACTIVE` rule — rejected
    with `ERR_CURFEW_WINDOW_OVERLAP` — when they share the same runway, their
    seasons intersect, their `applies_to` scopes intersect, their effective date
    ranges intersect, and their minute windows intersect *or touch*: because the
    minute intervals are closed, a rule ending at minute 1380 conflicts with one
    starting at 1380."
    PRD 3.2: "a `season` of `SUMMER` (calendar months four through nine),
    `WINTER` (months ten through three, spanning the year boundary), or
    `YEAR_ROUND`".

    Design: Difficulty/resource_temporal_overlap/curfew_closed_intervals_touching_minutes_conflict
    """
    create_curfew_rule(
        runway_code="09L",
        season="YEAR_ROUND",
        window_start_minute=1200,
        window_end_minute=1300,
        applies_to="DEPARTURE",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    # Closed intervals: [1300, 1400] shares boundary minute 1300 with
    # [1200, 1300] -> conflict.
    touching = api.create_curfew_rule(
        create_curfew_rule_payload(
            window_start_minute=1300, window_end_minute=1400
        ),
        ADMIN,
    )
    validate_error(touching, ApiErrorId.ERR_CURFEW_WINDOW_OVERLAP)

    # YEAR_ROUND intersects WINTER (months ten through three are covered by a
    # year-round season), and [1210, 1250] intersects [1200, 1300] -> conflict.
    winter = api.create_curfew_rule(
        create_curfew_rule_payload(
            season="WINTER", window_start_minute=1210, window_end_minute=1250
        ),
        ADMIN,
    )
    validate_error(winter, ApiErrorId.ERR_CURFEW_WINDOW_OVERLAP)


def test_curfew_rule_one_minute_gap_and_disjoint_scope_allowed(api):
    """PRD 3.2: "their minute windows intersect *or touch*".
    PRD 3.2: "The `applies_to` scope is `ARRIVAL`, `DEPARTURE`, or `BOTH`;
    `BOTH` matches any operation type, while a `RUNUP` operation matches only
    rules scoped `BOTH`."
    PRD 3.2: "Rules are created `ACTIVE`".

    Design: Difficulty/resource_temporal_overlap/curfew_closed_intervals_touching_minutes_conflict
    """
    create_curfew_rule(
        runway_code="09L",
        season="YEAR_ROUND",
        window_start_minute=1200,
        window_end_minute=1300,
        applies_to="DEPARTURE",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    # A one-minute gap: [1301, 1400] neither intersects nor touches [1200, 1300].
    gap = validate_success(
        api.create_curfew_rule(
            create_curfew_rule_payload(
                window_start_minute=1301, window_end_minute=1400
            ),
            ADMIN,
        ),
        201,
    )
    assert gap["status"] == "ACTIVE"

    # Disjoint scopes: DEPARTURE and ARRIVAL never intersect, so the identical
    # minute window is permitted.
    arrival = validate_success(
        api.create_curfew_rule(
            create_curfew_rule_payload(
                window_start_minute=1200,
                window_end_minute=1300,
                applies_to="ARRIVAL",
            ),
            ADMIN,
        ),
        201,
    )
    assert arrival["status"] == "ACTIVE"
    assert arrival["applies_to"] == "ARRIVAL"


def _setup_annoyance_zone(api, zone_code, complainant_count, violation_count):
    """At clock 2026-08-20: an operator, a YEAR_ROUND DEPARTURE rule on 27R
    ([1320, 1439], grace 15), `complainant_count` complainants in the zone, nine
    complaints spread across them (each correlated to one zone-matched day
    flight at dt=120s — STRICT 84.0 — and closed SUBSTANTIATED), and
    `violation_count` STAGE_4 departures operated at 22:35 (minute 1355, inside
    the trimmed interior [1335, 1424]) in the zone."""
    set_clock("2026-08-20T00:00:00Z")
    operator = create_operator()
    create_curfew_rule(
        runway_code="27R",
        season="YEAR_ROUND",
        window_start_minute=1320,
        window_end_minute=1439,
        applies_to="DEPARTURE",
        grace_minutes=15,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    complainants = [
        create_complainant(zone_code=zone_code) for _ in range(complainant_count)
    ]
    day_flight = create_operated_flight(
        operator["id"],
        "2026-08-10T12:00:00Z",
        runway_code="27R",
        scheduled_at="2026-08-10T11:55:00Z",
        zone_code=zone_code,
    )
    for index in range(9):
        owner = complainants[index % complainant_count]
        complaint = create_complaint(
            owner["id"], "2026-08-10T12:02:00Z", disturbance_type="LOUD_EVENT"
        )
        version = begin_review(complaint["id"])
        correlate_complaint(complaint["id"], version, flight_id=day_flight["id"])
        close_complaint(complaint["id"], "SUBSTANTIATED")
    for day in range(1, violation_count + 1):
        flight = create_flight(
            operator["id"],
            runway_code="27R",
            scheduled_at=f"2026-08-{day:02d}T22:30:00Z",
            zone_code=zone_code,
        )
        operate_flight(flight["id"], f"2026-08-{day:02d}T22:35:00Z")


def test_annoyance_index_base_tier_and_final_pinned(api):
    """PRD 3.6: "The base index is two and a half times the
    distinct-complainant count, plus four times the square root of the
    substantiated count, plus one and a half times the violation count, rounded
    half-up to one decimal place. The tier is keyed on the base alone — below 20
    is `LOW`, at least 20 but below 40 is `MODERATE`, and 40 or above is `HIGH`
    — and the final index adds a tier bonus: nothing for `LOW`, 6 for
    `MODERATE`, 15 for `HIGH`."

    Design: Difficulty/combinatorial_formula/annoyance_tier_keyed_on_base_index_only
    """
    _setup_annoyance_zone(api, "ZA", complainant_count=4, violation_count=11)

    data = validate_success(api.get_annoyance_index("ZA", ANALYST))
    # base = 2.5*4 + 4*sqrt(9) + 1.5*11 = 10 + 12 + 16.5 = 38.5.
    assert data["base_index"] == pytest.approx(38.5, abs=1e-6)
    # 20 <= 38.5 < 40 -> MODERATE; final = 38.5 + 6 = 44.5.
    assert data["tier"] == "MODERATE"
    assert data["final_index"] == pytest.approx(44.5, abs=1e-6)


def test_annoyance_tier_never_rekeyed_after_bonus(api):
    """PRD 3.6: "The tier is never re-keyed after the bonus: a base of 34.5 is
    `MODERATE`, and its final index of 40.5 remains `MODERATE` even though it
    crosses the 40 line."

    Design: Difficulty/combinatorial_formula/annoyance_tier_keyed_on_base_index_only
    """
    _setup_annoyance_zone(api, "ZB", complainant_count=3, violation_count=10)

    data = validate_success(api.get_annoyance_index("ZB", ANALYST))
    # base = 2.5*3 + 4*sqrt(9) + 1.5*10 = 7.5 + 12 + 15 = 34.5.
    assert data["base_index"] == pytest.approx(34.5, abs=1e-6)
    # Final 34.5 + 6 = 40.5 crosses the 40 line, yet the tier stays MODERATE.
    assert data["tier"] == "MODERATE"
    assert data["final_index"] == pytest.approx(40.5, abs=1e-6)
