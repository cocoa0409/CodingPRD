"""Multi-input formulas: the frozen signal score, the nested reach rounding and
the pre-fee containment band (PRD §3.2, §3.3, §3.6)."""

from test_helpers import (
    assert_containment,
    assert_field,
    assert_posture,
    assert_severity,
    assert_state,
    assert_two_decimals,
    notices_for_incident,
    queue_notice,
    read_notice,
    refresh,
    register_channel,
    release_notice,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_published_statement,
    validate_success,
)

# ---------------------------------------------------------------------------
# Mode (a): the four-input signal escalation score
# ---------------------------------------------------------------------------


def _listener_and_channels():
    """A social listener plus one SOCIAL surface (bump 4) and one REGULATORY
    surface (bump 15)."""
    set_clock("2026-08-10T09:00:00Z")
    scenario = seed_roster()
    scenario["social"] = register_channel(name="Platform X", channel_type="SOCIAL")
    scenario["regulatory"] = register_channel(
        name="Consumer Safety Docket", channel_type="REGULATORY"
    )
    return scenario


def test_credibility_multiplier_channel_bump_and_one_sided_sentiment_penalty_combine(api):
    """PRD §3.2: "the credibility multiplier is selected by the tier: 1.00 for
    `A`, 0.85 for `B`, 0.60 for `C`. The base component is the `reach_score`
    multiplied by that credibility multiplier, rounded half up to two decimals.
    Second, the sentiment penalty takes the negation of `sentiment_score`, keeps
    it only if it is greater than 0.0 and treats it as 0.0 otherwise, multiplies
    the result by a scale of 30 ... positive sentiment therefore contributes
    exactly nothing and never reduces the score. Third, a channel bump is added
    according to the surface: 8 points for a `MEDIA` channel, 4 for a `SOCIAL`
    channel, and 15 for a `REGULATORY` channel."

    Reach 70 at tier B on a SOCIAL surface with sentiment -0.4 gives
    59.50 + 12.00 + 4 = 75.50, while reach 40 at tier C with a *supportive*
    sentiment of 0.2 gives 24.00 + 0.00 + 4 = 28.00.

    Design: Difficulty/combinatorial_formula/combinatorial_signal_escalation_score_enum_matrix_mode_a
    """
    scenario = _listener_and_channels()
    listener = scenario["headers"]["listener"]

    hostile = validate_success(
        api.create_issue_signal(
            {
                "channel_id": scenario["social"]["id"],
                "headline": "Angry thread about support delays",
                "reach_score": 70,
                "sentiment_score": -0.4,
                "source_credibility_tier": "B",
            },
            listener,
        ),
        201,
    )
    supportive = validate_success(
        api.create_issue_signal(
            {
                "channel_id": scenario["social"]["id"],
                "headline": "Supportive fan post",
                "reach_score": 40,
                "sentiment_score": 0.2,
                "source_credibility_tier": "C",
            },
            listener,
        ),
        201,
    )

    assert_two_decimals(hostile["escalation_score"], 75.50, "hostile escalation_score")
    assert_two_decimals(
        supportive["escalation_score"], 28.00, "supportive escalation_score"
    )
    assert_state(supportive, "OPEN", "unlinked signal")
    assert hostile["detected_at"].startswith("2026-08-10T09:00:00"), (
        f"detected_at must be stamped at the current instant, got {hostile['detected_at']}"
    )


def test_the_summed_score_is_capped_at_one_hundred(api):
    """PRD §3.2: "a flat regulatory bump of 12 points is added when
    `regulatory_flag` is true ... the four contributions are then added; the sum
    is rounded half up to two decimals again; and finally the result is capped so
    that `escalation_score` never exceeds 100.00."

    Reach 90 at tier A on a REGULATORY surface with sentiment -0.6 and the
    regulatory flag set sums to 90.00 + 18.00 + 15 + 12 = 135.00, which the cap
    brings down to exactly 100.00.

    Design: Difficulty/combinatorial_formula/combinatorial_signal_escalation_score_enum_matrix_mode_a
    """
    scenario = _listener_and_channels()

    clamped = validate_success(
        api.create_issue_signal(
            {
                "channel_id": scenario["regulatory"]["id"],
                "headline": "Regulator opens inquiry docket",
                "reach_score": 90,
                "sentiment_score": -0.6,
                "source_credibility_tier": "A",
                "regulatory_flag": True,
            },
            scenario["headers"]["listener"],
        ),
        201,
    )

    assert_two_decimals(clamped["escalation_score"], 100.00, "escalation_score")
    assert_field(clamped, "regulatory_flag", True, "signal")
    assert_state(clamped, "OPEN", "signal")


# ---------------------------------------------------------------------------
# Mode (b): per-notice rounding before the sum
# ---------------------------------------------------------------------------


def _incident_with_three_queued_notices():
    """A SEV2 incident carrying a PUBLISHED HOLDING statement and three QUEUED
    notices whose unrounded contributions are 1.006, 1.00625 and 1.0065."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PLANT_INCIDENT",
        title="Plant fire near residential zone",
    )
    setup_published_statement(
        scenario,
        statement_type="HOLDING",
        body="Everyone on site is accounted for; the fire is contained.",
    )
    queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1006)
    queue_notice(scenario, audience="CUSTOMER", estimated_reach=805)
    queue_notice(scenario, audience="REGULATOR", estimated_reach=671)
    return scenario


def test_each_notice_contribution_is_rounded_before_the_index_is_summed(api):
    """PRD §3.6: "each notice's contribution is rounded to two decimals
    **first**, those rounded contributions are then summed, and the sum is
    rounded half up to two decimals again. This ordering is pinned and it changes
    the cents: three notices whose unrounded contributions are 1.006, 1.00625 and
    1.0065 yield 3.03 under the pinned per-notice-first order, whereas summing the
    unrounded values and rounding once would give 3.02. The pinned answer is
    3.03."

    Design: Difficulty/combinatorial_formula/combinatorial_stakeholder_reach_index_nested_rounding_mode_b
    """
    scenario = _incident_with_three_queued_notices()
    for audience in ("EMPLOYEE", "CUSTOMER", "REGULATOR"):
        release_notice(scenario, scenario["notices"][audience]["id"])

    for audience in ("EMPLOYEE", "CUSTOMER", "REGULATOR"):
        notice = read_notice(scenario["notices"][audience]["id"])
        assert_state(notice, "RELEASED", f"{audience} notice")
        assert_two_decimals(
            notice["reach_contribution"], 1.01, f"{audience} reach_contribution"
        )

    incident = refresh(scenario)
    assert_two_decimals(
        incident["stakeholder_reach_index"], 3.03, "stakeholder_reach_index"
    )
    assert_field(incident, "released_notice_count", 3, "incident")


def test_sequence_rank_is_derived_from_the_audience_and_unreleased_reach_is_zero(api):
    """PRD §3.6: "The server derives `sequence_rank` from the audience and it is
    never client-supplied: `EMPLOYEE` ranks 1, `CUSTOMER` 2, `REGULATOR` 3,
    `INVESTOR` 4 and `MEDIA` 5" and "Notices that are not `RELEASED` carry a
    `reach_contribution` of 0.00."

    Design: Difficulty/combinatorial_formula/combinatorial_stakeholder_reach_index_nested_rounding_mode_b
    """
    scenario = _incident_with_three_queued_notices()

    expected_rank = {"EMPLOYEE": 1, "CUSTOMER": 2, "REGULATOR": 3}
    for audience, rank in expected_rank.items():
        notice = read_notice(scenario["notices"][audience]["id"])
        assert_state(notice, "QUEUED", f"{audience} notice")
        assert_field(notice, "sequence_rank", rank, f"{audience} notice")
        assert_two_decimals(
            notice["reach_contribution"], 0.00, f"{audience} reach_contribution"
        )

    assert len(notices_for_incident(scenario["incident"]["id"])) == 3
    assert_two_decimals(
        refresh(scenario)["stakeholder_reach_index"], 0.00, "stakeholder_reach_index"
    )


# ---------------------------------------------------------------------------
# Mode (c): the amplification band keys on the pre-fee subtotal
# ---------------------------------------------------------------------------


def _activated_sev2_without_claims():
    """A SEV2 incident activated at 09:00 with no misinformation claims, so the
    exposure component of the containment family is 0.00."""
    return setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="EXEC_MISCONDUCT",
        title="Executive expense allegations",
        seat_roles=["INCIDENT_LEAD"],
    )


def test_the_amplification_band_is_keyed_on_the_base_score_and_never_rebanded(api):
    """PRD §3.3: "`base_containment_score` is seven tenths of the tier's point
    value plus three tenths of that exposure component ... The base score is then
    placed into an amplification band: `HIGH` when it is at least 80.00, otherwise
    `MEDIUM` when it is at least 55.00, otherwise `LOW` ... **The evaluation order
    is pinned and the band is keyed on the pre-fee base score only.** The total is
    never re-banded after the fee is added: a base score of 52.50 sits in `LOW`,
    takes the 0.05 rate, and yields a total of 55.13 — a figure that falls inside
    the `MEDIUM` band while keeping the `LOW` rate."

    Design: Difficulty/combinatorial_formula/combinatorial_containment_priority_band_of_pre_fee_subtotal_mode_c
    """
    incident = _activated_sev2_without_claims()["incident"]

    assert_severity(incident, "SEV2", 83.00, "PROVISIONAL")
    assert_containment(incident, 52.50, 0.05, 55.13)


def test_activation_fixes_the_holding_deadline_from_the_provisional_tier_window(api):
    """PRD §3.3: "`holding_statement_due_at` is `activated_at` plus the
    service-level window belonging to the current `severity_tier`: half an hour
    for `SEV1`, one hour for `SEV2`, three hours for `SEV3`, and eight hours for
    `SEV4`."

    Activating a SEV2 incident at 09:00 therefore puts the holding deadline at
    10:00, with the posture still OPEN because nothing is blocked or breached.

    Design: Difficulty/combinatorial_formula/combinatorial_containment_priority_band_of_pre_fee_subtotal_mode_c
    """
    incident = _activated_sev2_without_claims()["incident"]

    assert_field(incident, "severity_tier", "SEV2", "incident")
    assert incident["holding_statement_due_at"].startswith("2026-08-10T10:00:00"), (
        "holding_statement_due_at must be activated_at plus the SEV2 window, got "
        f"{incident['holding_statement_due_at']}"
    )
    assert_posture(incident, "OPEN")
    assert_field(incident, "sla_breached", False, "incident")
