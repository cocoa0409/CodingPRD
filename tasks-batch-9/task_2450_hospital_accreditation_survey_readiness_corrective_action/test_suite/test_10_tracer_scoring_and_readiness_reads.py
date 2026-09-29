"""Freezing a tracer's score at completion — partial credit, two-decimal
rounding and the exclusion of NOT_APPLICABLE rows — and the reads that expose
the result: the computed readiness derivation, the two observation collections,
and the forty-point penalty cap on the way from base score to band."""

from test_helpers import (
    assert_unit_readiness,
    assign_owner,
    create_chapter,
    create_standard,
    create_unit,
    open_rounding_session,
    raise_deficiency,
    read_standard,
    read_unit,
    record_observation,
    schedule_tracer,
    set_clock,
    tracer_action,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains — each test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_started_tracer(unit_name, unit_type, bed_count, standard_codes, tracer_type="PATIENT"):
    """Chapter EC at weight 100 carrying one standard per entry of
    `standard_codes` (the first one owned, so the chapter is mapped), one unit,
    and one tracer already IN_PROGRESS at clock 2026-08-05T09:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standards = [
        create_standard(chapter["id"], code, title, tier)
        for code, title, tier in standard_codes
    ]
    assign_owner(standards[0]["id"], "owner-1", "PRIMARY")
    unit = create_unit(unit_name, unit_type, bed_count)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        tracer_type=tracer_type,
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-05T09:00:00Z")
    tracer_action(tracer["id"], "START")
    return {"chapter": chapter, "standards": standards, "unit": unit, "tracer": tracer}


def _setup_unit_scoring_seventy_eight(unit_name):
    """Chapter EC at weight 100 with an owned s1 and an unowned s2, and one
    COMPLETED tracer on the named unit carrying a COMPLIANT observation of
    weight 39 and a NON_COMPLIANT observation of weight 11. The logical clock
    stands at 2026-08-10T09:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    first = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    second = create_standard(chapter["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT")
    assign_owner(first["id"], "owner-1", "PRIMARY")
    unit = create_unit(unit_name, "ICU", 12)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        tracer_type="PATIENT",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-10T09:00:00Z")
    tracer_action(tracer["id"], "START")
    first_observation = record_observation(tracer["id"], first["id"], "COMPLIANT", 39)
    second_observation = record_observation(tracer["id"], second["id"], "NON_COMPLIANT", 11)
    tracer = tracer_action(tracer["id"], "COMPLETE")
    return {
        "chapter": chapter,
        "first_standard": first,
        "second_standard": second,
        "unit": unit,
        "tracer": tracer,
        "first_observation": first_observation,
        "second_observation": second_observation,
    }


# ---------------------------------------------------------------------------
# calculations
# ---------------------------------------------------------------------------

def test_partial_observation_earns_half_of_its_weight(api, director_headers):
    """PRD §3.4: "`scored_weight` becomes the sum of `weight` across those observations and is kept exact."
    PRD §3.4: "`earned_weight` becomes the sum, across the same observations, of `weight` multiplied by that observation's credit — full credit of 1.0 for `COMPLIANT`, half credit of 0.5 for `PARTIAL`, and zero for `NON_COMPLIANT` — and is likewise kept exact."
    PRD §3.4: "Otherwise `tracer_score` is `earned_weight` divided by `scored_weight`, multiplied by one hundred, rounded half up to two decimal places, and `contributes_to_readiness` becomes true."
    PRD §3.3: "Each observation carries a credit determined by its result — a `COMPLIANT` observation earns full credit of 1.0, a `PARTIAL` observation earns half credit of 0.5, and a `NON_COMPLIANT` observation earns no credit at all."

    Design: Corner/calculations/mock_tracer_score_partial_credit_is_half_weight
    """
    built = _setup_started_tracer(
        "MED-8",
        "MED_SURG",
        30,
        [
            ("EC.02.01.01", "Risk management", "DIRECT_IMPACT"),
            ("EC.02.02.01", "Hazardous materials", "INDIRECT_IMPACT"),
            ("EC.02.03.01", "Fire response", "INDIRECT_IMPACT"),
        ],
    )
    record_observation(built["tracer"]["id"], built["standards"][0]["id"], "COMPLIANT", 10)
    record_observation(built["tracer"]["id"], built["standards"][1]["id"], "PARTIAL", 10)
    record_observation(built["tracer"]["id"], built["standards"][2]["id"], "NON_COMPLIANT", 10)

    completed = tracer_action(built["tracer"]["id"], "COMPLETE")

    assert float(completed["scored_weight"]) == 30
    assert float(completed["earned_weight"]) == 15
    assert float(completed["tracer_score"]) == 50.00
    assert completed["contributes_to_readiness"] is True

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))
    assert float(readiness["base_score"]) == 50.00
    assert float(readiness["readiness_score"]) == 50.00
    assert readiness["readiness_band"] == "NOT_READY"


def test_tracer_score_of_two_in_three_rounds_half_up_to_two_places(api, director_headers):
    """PRD §3.4: "Otherwise `tracer_score` is `earned_weight` divided by `scored_weight`, multiplied by one hundred, rounded half up to two decimal places, and `contributes_to_readiness` becomes true."
    PRD §2.6: "All rounding in this system is **round half up**, and every rounding step described in §3 is pinned — intermediate values are rounded where the specification says they are rounded, and the results of those roundings feed the next step."
    PRD §2.6: "A mock tracer's `tracer_score`, a unit's `readiness_score`, and the periodic performance review's `self_score`, `verified_score` and `gap` are all carried to exactly two decimal places."
    PRD §3.3: "The chapter's rate is the sum over those observations of `weight` multiplied by credit, divided by the sum of `weight` over the same observations, rounded half up to four decimal places."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."

    Design: Corner/calculations/tracer_score_precision_two_thirds_rounds_half_up
    """
    built = _setup_started_tracer(
        "MED-9",
        "MED_SURG",
        30,
        [
            ("EC.02.01.01", "Risk management", "DIRECT_IMPACT"),
            ("EC.02.02.01", "Hazardous materials", "INDIRECT_IMPACT"),
            ("EC.02.03.01", "Fire response", "INDIRECT_IMPACT"),
        ],
    )
    record_observation(built["tracer"]["id"], built["standards"][0]["id"], "COMPLIANT", 1)
    record_observation(built["tracer"]["id"], built["standards"][1]["id"], "COMPLIANT", 1)
    record_observation(built["tracer"]["id"], built["standards"][2]["id"], "NON_COMPLIANT", 1)

    completed = tracer_action(built["tracer"]["id"], "COMPLETE")

    # 2 of 3 is 66.6666..., which rounds half up at two decimal places.
    assert float(completed["tracer_score"]) == 66.67

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))
    assert float(readiness["base_score"]) == 66.67
    assert readiness["readiness_band"] == "AT_RISK"
    assert len(readiness["chapter_breakdown"]) == 1


def test_not_applicable_observations_are_excluded_from_both_weight_sums(api, director_headers):
    """PRD §3.4: "Every observation of this tracer whose `result` is not `NOT_APPLICABLE` participates — there is no time window, so every row created before the completion call is included, and because both terms are sums the order in which observations were recorded is irrelevant."
    PRD §3.4: "`scored_weight` becomes the sum of `weight` across those observations and is kept exact."
    PRD §3.4: "If `scored_weight` came out as zero, meaning every single observation was `NOT_APPLICABLE`, then `tracer_score` is set to 0.00 and `contributes_to_readiness` stays false."
    PRD §3.3: "Take every observation belonging to that chapter's completed, contributing tracers on this unit whose `result` is not `NOT_APPLICABLE`."

    Design: Corner/calculations/not_applicable_observations_excluded_from_both_sums
    """
    built = _setup_started_tracer(
        "OR-9",
        "OR",
        4,
        [
            ("EC.02.01.01", "Risk management", "DIRECT_IMPACT"),
            ("EC.02.02.01", "Hazardous materials", "INDIRECT_IMPACT"),
        ],
        tracer_type="SYSTEM",
    )
    excluded_standard = built["standards"][1]
    record_observation(built["tracer"]["id"], built["standards"][0]["id"], "COMPLIANT", 4)
    record_observation(built["tracer"]["id"], excluded_standard["id"], "NOT_APPLICABLE", 6)

    completed = tracer_action(built["tracer"]["id"], "COMPLETE")

    # The NOT_APPLICABLE weight of 6 leaves both sums untouched.
    assert float(completed["scored_weight"]) == 4
    assert float(completed["earned_weight"]) == 4
    assert float(completed["tracer_score"]) == 100.00
    assert completed["contributes_to_readiness"] is True

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))
    assert float(readiness["participating_weight_pct"]) == 100.00
    assert float(readiness["readiness_score"]) == 100.00
    assert readiness["readiness_band"] == "READY"

    # A NOT_APPLICABLE observation is not evidence of non-compliance.
    assert read_standard(excluded_standard["id"])["compliance_state"] == "UNMAPPED"


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_computed_readiness_read_returns_the_whole_derivation(api, director_headers):
    """PRD §3.3: "The computed readiness read returns the whole derivation rather than just the answer: the `unit_id` it was computed for, the `mode` that was applied, the `base_score` from step three, the `penalty_points_applied` from step four, the `participating_weight_pct`, the resulting `readiness_score` and `readiness_band`, and a `chapter_breakdown` array carrying the per-chapter detail behind the base."
    PRD §3.3: "The **attested** variant is the default — it applies when `mode` is omitted or supplied as `ATTESTED`, and it is the only variant ever persisted onto the unit's own `readiness_score` and `readiness_band` fields by a cascade."
    PRD §3.3: "Let the participating weight be the sum of `weight_pct` across the participating chapters — this is the value reported as `participating_weight_pct` on the computed readiness read."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."

    Design: Corner/endpoints/readiness_computed_read_returns_chapter_breakdown
    """
    built = _setup_unit_scoring_seventy_eight("ICU-12")
    assert float(built["tracer"]["tracer_score"]) == 78.00

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))
    assert_unit_readiness(readiness)

    assert readiness["unit_id"] == built["unit"]["id"]
    assert readiness["mode"] == "ATTESTED"
    assert float(readiness["base_score"]) == 78.00
    assert readiness["penalty_points_applied"] == 0
    assert float(readiness["participating_weight_pct"]) == 100.00
    assert float(readiness["readiness_score"]) == 78.00
    assert readiness["readiness_band"] == "CONDITIONAL"
    assert len(readiness["chapter_breakdown"]) == 1

    stored = read_unit(built["unit"]["id"])
    assert float(stored["readiness_score"]) == 78.00
    assert stored["readiness_band"] == "CONDITIONAL"


def test_observations_are_reachable_from_both_standard_and_tracer(api, director_headers):
    """PRD §3.4: "Each observation names the `standard_id` observed and a `result` of `COMPLIANT`, `PARTIAL`, `NON_COMPLIANT` or `NOT_APPLICABLE`, plus an optional sampling `weight` that must be greater than zero and defaults to 1 when omitted, and an optional free-text `note` stored as null when omitted."
    PRD §3.4: "The tracer is taken from the path and stored as `mock_tracer_id`."
    PRD §2.3: "The standards of a chapter may be filtered by `compliance_state`; the owner assignments of a standard by `status`; a standard's evidence repository by `validation_state`; the mock tracer collection by `unit_id`, `chapter_id` and `state`; both observation collections — the one scoped to a tracer and the one scoped to a standard — by `result`; the rounding-session collection by `unit_id`, `round_type` and `state`; the deficiency-ticket collection by `rounding_session_id`, `standard_id`, `state` and `severity`; the survey-finding collection by `survey_window_id`, `standard_id`, `unit_id` and `state`; and a chapter's periodic performance review collection by `state`."
    PRD §2.3: "Unless a specific endpoint says otherwise, every collection is sorted by `created_at` in ascending order."

    Design: Corner/endpoints/standard_tracer_observations_cross_reference_read
    """
    built = _setup_unit_scoring_seventy_eight("ICU-13")

    by_standard, standard_meta = validate_paginated(
        api.list_standard_tracer_observations(
            built["second_standard"]["id"], director_headers, {"limit": 20, "offset": 0}
        )
    )
    assert standard_meta["total_count"] == 1
    assert by_standard[0]["id"] == built["second_observation"]["id"]
    assert by_standard[0]["result"] == "NON_COMPLIANT"
    assert float(by_standard[0]["weight"]) == 11
    assert by_standard[0]["mock_tracer_id"] == built["tracer"]["id"]

    by_tracer, tracer_meta = validate_paginated(
        api.list_tracer_observations(
            built["tracer"]["id"], director_headers, {"limit": 20, "offset": 0}
        )
    )
    assert tracer_meta["total_count"] == 2
    assert by_tracer[0]["id"] == built["first_observation"]["id"]
    assert by_tracer[1]["id"] == built["second_observation"]["id"]

    filtered, filtered_meta = validate_paginated(
        api.list_standard_tracer_observations(
            built["second_standard"]["id"], director_headers, {"result": "COMPLIANT"}
        )
    )
    assert filtered_meta["total_count"] == 0
    assert filtered == []


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers
# ---------------------------------------------------------------------------

def test_penalty_points_applied_caps_at_forty_while_ledger_keeps_the_raw_total(
    api, director_headers
):
    """PRD §3.3: "Each penalised ticket contributes its `penalty_points`, and the sum is capped at forty points no matter how much open deficiency the unit is carrying; the applied figure is reported as `penalty_points_applied`."
    PRD §3.3: "Severity determines a ticket's points: a `LOW` ticket is worth one point, a `MODERATE` ticket three, a `HIGH` ticket seven, and an `IMMEDIATE_THREAT` ticket fifteen."
    PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."
    PRD §3.3: "The score is the base minus the capped penalty, floored at zero so it can never go negative, rounded half up to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/penalty_cap_forty_applied_at_six_high_tickets
    """
    built = _setup_unit_scoring_seventy_eight("ICU-18")
    assert float(built["tracer"]["tracer_score"]) == 78.00

    session = open_rounding_session(
        built["unit"]["id"], "LIFE_SAFETY", "2026-08-10T13:00:00Z", "2026-08-10T17:00:00Z"
    )
    last_ticket = None
    for index in range(1, 7):
        last_ticket = raise_deficiency(
            session["id"],
            built["first_standard"]["id"],
            "HIGH",
            f"Sprinkler head obstruction {index}",
        )
    assert last_ticket["penalty_points"] == 7

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 42
    assert unit["posture"] == "RESTRICTED"

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))
    assert float(readiness["base_score"]) == 78.00
    assert readiness["penalty_points_applied"] == 40
    assert float(readiness["readiness_score"]) == 38.00
    assert readiness["readiness_band"] == "NOT_READY"
