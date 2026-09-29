"""Unit readiness scoring: the two penalty variants, the pinned round-then-sum
order of the weighted base, and the empty-participating-set boundary."""

from test_helpers import (
    assign_owner,
    create_chapter,
    create_standard,
    create_unit,
    open_rounding_session,
    raise_deficiency,
    read_unit,
    record_observation,
    schedule_tracer,
    set_clock,
    ticket_action,
    tracer_action,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains — each test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_unit_with_low_and_in_progress_high_ticket():
    """Chapter EC at weight 100 with one owned standard, unit ICU-3 carrying one
    COMPLETED tracer whose chapter rate is 0.7800 (base 78.00), then one OPEN
    LOW ticket and one IN_PROGRESS HIGH ticket whose due_at is still in the
    future at the logical clock 2026-08-10T00:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    first = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    second = create_standard(chapter["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT")
    assign_owner(first["id"], "owner-1", "PRIMARY")
    unit = create_unit("ICU-3", "ICU", 20)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-10T00:00:00Z")
    tracer_action(tracer["id"], "START")
    record_observation(tracer["id"], first["id"], "COMPLIANT", 39)
    record_observation(tracer["id"], second["id"], "NON_COMPLIANT", 11)
    tracer = tracer_action(tracer["id"], "COMPLETE")
    session = open_rounding_session(
        unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    low_ticket = raise_deficiency(session["id"], first["id"], "LOW", "Corridor clutter")
    high_ticket = raise_deficiency(session["id"], second["id"], "HIGH", "Generator log gap")
    high_ticket = ticket_action(high_ticket["id"], "START_WORK")
    return {
        "chapter": chapter,
        "first_standard": first,
        "second_standard": second,
        "unit": unit,
        "tracer": tracer,
        "session": session,
        "low_ticket": low_ticket,
        "high_ticket": high_ticket,
    }


def _setup_three_participating_chapters():
    """Chapters EC 40, LS 25 and IC 10, each with one owned standard, and unit
    ICU-9 carrying one COMPLETED contributing tracer per chapter whose weighted
    rates are 0.6667, 0.3333 and 0.5000. No deficiency tickets exist."""
    ec = create_chapter("EC", "Environment of Care", 40, 1)
    ls = create_chapter("LS", "Life Safety", 25, 1)
    ic = create_chapter("IC", "Infection Control", 10, 1)
    ec_a = create_standard(ec["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    ec_b = create_standard(ec["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT")
    ls_a = create_standard(ls["id"], "LS.01.01.01", "Egress protection", "DIRECT_IMPACT")
    ls_b = create_standard(ls["id"], "LS.02.01.01", "Sprinkler coverage", "INDIRECT_IMPACT")
    ic_a = create_standard(ic["id"], "IC.01.01.01", "Hand hygiene program", "DIRECT_IMPACT")
    assign_owner(ec_a["id"], "owner-1", "PRIMARY")
    assign_owner(ls_a["id"], "owner-2", "PRIMARY")
    assign_owner(ic_a["id"], "owner-3", "PRIMARY")
    unit = create_unit("ICU-9", "ICU", 16)
    tracer_ec = schedule_tracer(
        unit["id"],
        ec["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        tracer_type="SYSTEM",
    )
    tracer_ls = schedule_tracer(
        unit["id"],
        ls["id"],
        "2026-08-05T11:00:00Z",
        "2026-08-05T12:00:00Z",
        tracer_type="SYSTEM",
    )
    tracer_ic = schedule_tracer(
        unit["id"],
        ic["id"],
        "2026-08-05T13:00:00Z",
        "2026-08-05T14:00:00Z",
        tracer_type="SYSTEM",
    )
    set_clock("2026-08-06T00:00:00Z")
    tracer_action(tracer_ec["id"], "START")
    record_observation(tracer_ec["id"], ec_a["id"], "COMPLIANT", 2)
    record_observation(tracer_ec["id"], ec_b["id"], "NON_COMPLIANT", 1)
    tracer_ec = tracer_action(tracer_ec["id"], "COMPLETE")
    tracer_action(tracer_ls["id"], "START")
    record_observation(tracer_ls["id"], ls_a["id"], "COMPLIANT", 1)
    record_observation(tracer_ls["id"], ls_b["id"], "NON_COMPLIANT", 2)
    tracer_ls = tracer_action(tracer_ls["id"], "COMPLETE")
    tracer_action(tracer_ic["id"], "START")
    record_observation(tracer_ic["id"], ic_a["id"], "PARTIAL", 1)
    tracer_ic = tracer_action(tracer_ic["id"], "COMPLETE")
    return {
        "unit": unit,
        "tracer_ec": tracer_ec,
        "tracer_ls": tracer_ls,
        "tracer_ic": tracer_ic,
    }


def _setup_unit_whose_only_observation_is_not_applicable():
    """Chapter NPSG at weight 60 with one owned standard, unit AMB-1, one tracer
    COMPLETED with exactly one NOT_APPLICABLE observation, and one OPEN HIGH
    ticket worth seven points, at the logical clock 2026-08-10T00:00:00Z."""
    chapter = create_chapter("NPSG", "National Patient Safety Goals", 60, 1)
    standard = create_standard(
        chapter["id"], "NPSG.03.04.01", "Label all medications", "DIRECT_IMPACT"
    )
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    unit = create_unit("AMB-1", "AMBULATORY", 0)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T09:00:00Z",
        tracer_type="INDIVIDUAL",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-10T00:00:00Z")
    tracer_action(tracer["id"], "START")
    record_observation(tracer["id"], standard["id"], "NOT_APPLICABLE", 5)
    tracer = tracer_action(tracer["id"], "COMPLETE")
    session = open_rounding_session(
        unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    ticket = raise_deficiency(session["id"], standard["id"], "HIGH", "Unlabeled syringe")
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": unit,
        "tracer": tracer,
        "session": session,
        "ticket": ticket,
    }


# ---------------------------------------------------------------------------
# dual_variant_calc / unit_readiness_attested_vs_projected_penalty_set
# ---------------------------------------------------------------------------

def test_unit_readiness_attested_variant_charges_every_non_verified_ticket(
    api, director_headers
):
    """PRD §3.3: "The **attested** variant is the default — it applies when `mode` is omitted or supplied as `ATTESTED`, and it is the only variant ever persisted onto the unit's own `readiness_score` and `readiness_band` fields by a cascade."
    PRD §3.3: "Under it, the penalised set is every deficiency ticket of the unit whose `state` is `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`: remediation that has not yet been verified still costs the unit points, because on paper nothing has been proven fixed."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."
    PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."

    Design: Difficulty/dual_variant_calc/unit_readiness_attested_vs_projected_penalty_set
    """
    built = _setup_unit_with_low_and_in_progress_high_ticket()

    attested = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))

    assert attested["mode"] == "ATTESTED"
    assert float(attested["base_score"]) == 78.00
    assert attested["penalty_points_applied"] == 8
    assert float(attested["readiness_score"]) == 70.00
    assert attested["readiness_band"] == "AT_RISK"

    unit = read_unit(built["unit"]["id"])
    assert float(unit["readiness_score"]) == 70.00
    assert unit["readiness_band"] == "AT_RISK"
    assert unit["open_deficiency_penalty_points"] == 8


def test_unit_readiness_projected_variant_forgives_in_flight_ticket_not_yet_due(
    api, director_headers
):
    """PRD §3.3: "The **projected** variant applies only when `mode` is supplied as `PROJECTED`, is never persisted, and exists so leadership can forecast where the unit will stand once in-flight work lands."
    PRD §3.3: "It starts from the same set and then excludes tickets that are simultaneously in `IN_PROGRESS` or `REMEDIATED` **and** whose `due_at` is at or after the current logical clock — work that is under way and not yet late is assumed to close by its due date."
    PRD §3.3: "Tickets in `OPEN` or `ESCALATED` are counted regardless of their due date, and an in-flight ticket whose `due_at` has already passed is counted too, because a commitment already missed cannot be assumed."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."

    Design: Difficulty/dual_variant_calc/unit_readiness_attested_vs_projected_penalty_set
    """
    built = _setup_unit_with_low_and_in_progress_high_ticket()

    assert built["high_ticket"]["due_at"] == "2026-08-24T00:00:00.000Z"
    assert built["high_ticket"]["state"] == "IN_PROGRESS"
    assert built["high_ticket"]["penalty_points"] == 7
    assert built["low_ticket"]["state"] == "OPEN"

    projected = validate_success(
        api.get_unit_readiness(built["unit"]["id"], director_headers, {"mode": "PROJECTED"})
    )

    assert projected["mode"] == "PROJECTED"
    assert float(projected["base_score"]) == 78.00
    assert projected["penalty_points_applied"] == 1
    assert float(projected["readiness_score"]) == 77.00
    assert projected["readiness_band"] == "CONDITIONAL"

    # The projected read is never persisted: the unit still carries the attested figures.
    unit = read_unit(built["unit"]["id"])
    assert float(unit["readiness_score"]) == 70.00
    assert unit["readiness_band"] == "AT_RISK"


# ---------------------------------------------------------------------------
# combinatorial_formula / readiness_round_per_chapter_then_sum_pinned_order
# ---------------------------------------------------------------------------

def test_unit_readiness_base_rounds_each_chapter_contribution_before_summing(
    api, director_headers
):
    """PRD §3.3: "**Step three** turns those rates into a weighted base, and the rounding order here is pinned as round-then-sum; summing first and rounding once is explicitly not the rule."
    PRD §3.3: "Let the participating weight be the sum of `weight_pct` across the participating chapters — this is the value reported as `participating_weight_pct` on the computed readiness read."
    PRD §3.3: "Each participating chapter's contribution is its `weight_pct` divided by that participating weight, multiplied by the chapter's four-decimal rate, multiplied by one hundred, and then rounded half up to two decimal places."
    PRD §3.3: "The base is the sum of those already-rounded per-chapter contributions, rounded half up to two decimal places again, and is reported as `base_score`."

    Design: Difficulty/combinatorial_formula/readiness_round_per_chapter_then_sum_pinned_order
    """
    built = _setup_three_participating_chapters()

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))

    assert float(readiness["participating_weight_pct"]) == 75.00
    assert readiness["penalty_points_applied"] == 0
    # 35.56 + 11.11 + 6.67 == 53.34 under round-then-sum; sum-then-round gives 53.33.
    assert float(readiness["base_score"]) == 53.34
    assert float(readiness["readiness_score"]) == 53.34


def test_unit_readiness_persists_round_then_sum_base_with_per_chapter_tracer_scores(
    api, director_headers
):
    """PRD §3.3: "The base is the sum of those already-rounded per-chapter contributions, rounded half up to two decimal places again, and is reported as `base_score`."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."
    PRD §3.4: "Otherwise `tracer_score` is `earned_weight` divided by `scored_weight`, multiplied by one hundred, rounded half up to two decimal places, and `contributes_to_readiness` becomes true."

    Design: Difficulty/combinatorial_formula/readiness_round_per_chapter_then_sum_pinned_order
    """
    built = _setup_three_participating_chapters()

    unit = read_unit(built["unit"]["id"])
    assert float(unit["readiness_score"]) == 53.34
    assert unit["readiness_band"] == "NOT_READY"

    tracer_ec = validate_success(api.get_mock_tracer(built["tracer_ec"]["id"], director_headers))
    tracer_ls = validate_success(api.get_mock_tracer(built["tracer_ls"]["id"], director_headers))
    tracer_ic = validate_success(api.get_mock_tracer(built["tracer_ic"]["id"], director_headers))

    assert float(tracer_ec["tracer_score"]) == 66.67
    assert float(tracer_ls["tracer_score"]) == 33.33
    assert float(tracer_ic["tracer_score"]) == 50.00
    for tracer in (tracer_ec, tracer_ls, tracer_ic):
        assert tracer["state"] == "COMPLETED"
        assert tracer["contributes_to_readiness"] is True


# ---------------------------------------------------------------------------
# boundary_precision_check / empty_participating_set_not_assessed_versus_zero_score
# ---------------------------------------------------------------------------

def test_tracer_with_only_not_applicable_observation_scores_zero_without_contributing(
    api, director_headers
):
    """PRD §3.4: "If `scored_weight` came out as zero, meaning every single observation was `NOT_APPLICABLE`, then `tracer_score` is set to 0.00 and `contributes_to_readiness` stays false."
    PRD §3.4: "Every observation of this tracer whose `result` is not `NOT_APPLICABLE` participates — there is no time window, so every row created before the completion call is included, and because both terms are sums the order in which observations were recorded is irrelevant."

    Design: Difficulty/boundary_precision_check/empty_participating_set_not_assessed_versus_zero_score
    """
    built = _setup_unit_whose_only_observation_is_not_applicable()

    assert built["tracer"]["state"] == "COMPLETED"
    assert float(built["tracer"]["tracer_score"]) == 0.00
    assert built["tracer"]["contributes_to_readiness"] is False

    tracer = validate_success(api.get_mock_tracer(built["tracer"]["id"], director_headers))
    assert float(tracer["scored_weight"]) == 0
    assert float(tracer["earned_weight"]) == 0
    assert float(tracer["tracer_score"]) == 0.00
    assert tracer["contributes_to_readiness"] is False


def test_unit_readiness_with_no_participating_chapter_is_not_assessed_without_penalty(
    api, director_headers
):
    """PRD §3.3: "**Step one** determines which chapters participate: a chapter participates for this unit when at least one mock tracer exists whose unit is this unit, whose chapter is that chapter, whose `state` is `COMPLETED`, and whose `contributes_to_readiness` is true."
    PRD §3.3: "If no chapter participates, the computation stops immediately with `readiness_score` 0.00 and `readiness_band` `NOT_ASSESSED`, and the penalty is **not** applied — an unassessed unit is not punished for its open deficiencies."
    PRD §3.3: "Note the exclusion this creates: a tracer that reached `COMPLETED` but whose every observation was `NOT_APPLICABLE` has `contributes_to_readiness` false and therefore does not make its chapter participate."
    PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."

    Design: Difficulty/boundary_precision_check/empty_participating_set_not_assessed_versus_zero_score
    """
    built = _setup_unit_whose_only_observation_is_not_applicable()

    assert built["ticket"]["state"] == "OPEN"
    assert built["ticket"]["penalty_points"] == 7

    readiness = validate_success(api.get_unit_readiness(built["unit"]["id"], director_headers))

    assert float(readiness["readiness_score"]) == 0.00
    assert readiness["readiness_band"] == "NOT_ASSESSED"
    assert readiness["penalty_points_applied"] == 0

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 7
    assert float(unit["readiness_score"]) == 0.00
    assert unit["readiness_band"] == "NOT_ASSESSED"
    assert unit["posture"] == "OPEN"
