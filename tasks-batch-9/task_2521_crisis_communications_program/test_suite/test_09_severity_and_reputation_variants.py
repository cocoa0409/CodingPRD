"""Dual-variant arithmetic: the two severity readings on one incident and the
two reputation deltas on one retrospective (PRD §3.3, §3.9)."""

from test_helpers import (
    approve_to_quorum,
    assert_field,
    assert_final_severity,
    assert_four_decimals,
    assert_severity,
    assert_state,
    assert_two_decimals,
    close_claim,
    draft_statement,
    escalate_signal,
    issue_correction,
    link_signal,
    log_claim,
    open_incident,
    publish_statement,
    queue_notice,
    read_incident,
    read_signal,
    record_signal,
    register_channel,
    release_notice,
    resolve_incident,
    score_review,
    seat_member,
    seed_roster,
    set_clock,
    setup_activated_incident,
    submit_for_review,
    triage_claim,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared arrangements
# ---------------------------------------------------------------------------


def _diverging_signal_incident():
    """A MONITORING incident carrying three linked signals whose two candidate
    sets disagree.

    Signal A is reach 84 on a MEDIA surface and ESCALATED, so its frozen
    ``escalation_score`` is 92.00; signal B is reach 68 on a SOCIAL surface and
    ESCALATED, so 72.00; signal C is reach 88 on a MEDIA surface and left merely
    LINKED, so 96.00.  The INCIDENT_LEAD and LEGAL_COUNSEL seats are both
    ACKNOWLEDGED because the provisional tier will come out ``SEV1``.
    """
    set_clock("2026-08-10T09:00:00Z")
    scenario = seed_roster()
    media = register_channel(name="National Wire", channel_type="MEDIA")
    social = register_channel(name="Platform X", channel_type="SOCIAL")
    incident = open_incident(
        scenario["headers"]["lead"],
        title="Battery pack overheating reports",
        scenario_code="PRODUCT_RECALL",
    )
    listener = scenario["headers"]["listener"]
    signal_a = record_signal(
        media["id"], listener, headline="Wire story on overheating packs", reach_score=84
    )
    signal_b = record_signal(
        social["id"], listener, headline="Unboxing thread claims fire risk", reach_score=68
    )
    signal_c = record_signal(
        media["id"], listener, headline="Broadcast segment scheduled", reach_score=88
    )
    for signal in (signal_a, signal_b, signal_c):
        link_signal(signal["id"], incident["id"], listener)
    escalate_signal(signal_a["id"], listener)
    escalate_signal(signal_b["id"], listener)
    seat_member(
        incident["id"],
        scenario["ids"]["lead"],
        "INCIDENT_LEAD",
        scenario["headers"]["lead"],
        member_headers=scenario["headers"]["lead"],
    )
    seat_member(
        incident["id"],
        scenario["ids"]["counsel"],
        "LEGAL_COUNSEL",
        scenario["headers"]["lead"],
        member_headers=scenario["headers"]["counsel"],
    )
    scenario["channel"] = media
    scenario["incident"] = incident
    scenario["signals"] = {"a": signal_a, "b": signal_b, "c": signal_c}
    return scenario


def _reputation_scenario():
    """A DATA_BREACH incident carried all the way to an OPEN retrospective whose
    snapshot is ``reputation_index_before`` 62.40, ``reputation_index_after``
    55.10, ``exposure_factor`` 0.0101 and one of one claim corrected."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="DATA_BREACH",
        title="Customer records exposed",
        reputation_index_before=62.40,
    )
    draft_statement(
        scenario,
        statement_type="CORRECTION",
        body="The exposed dataset did not contain payment credentials.",
    )
    submit_for_review(scenario)
    approve_to_quorum(scenario)
    publish_statement(scenario)

    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1006)
    release_notice(scenario, notice["id"])

    log_claim(
        scenario,
        virality_score=40.00,
        claim_text="Card numbers were sold on a forum.",
    )
    triage_claim(scenario)
    issue_correction(scenario, "2026-08-10T11:00:00Z", "2026-08-10T11:30:00Z")
    close_claim(scenario, outcome_note="Correction cited by the platform.")

    resolve_incident(scenario, reputation_index_after=55.10)
    return scenario


# ---------------------------------------------------------------------------
# Provisional versus final severity
# ---------------------------------------------------------------------------


def test_activation_bands_the_largest_score_over_linked_and_escalated_signals(api):
    """PRD §3.3: "At activation ... the **provisional** reading is used: the
    candidate set is every signal on the incident in state `LINKED` or
    `ESCALATED` — deliberately forward-looking, because a merely linked signal
    still represents live exposure — and the governing score is the largest
    `escalation_score` in that set. The result is written to `severity_tier` and
    `severity_score` with `severity_basis` set to `PROVISIONAL`."

    The never-escalated signal C holds the peak at 96.00, so the provisional
    reading is SEV1 even though only 92.00 and 72.00 have been escalated.

    Design: Difficulty/dual_variant_calc/dual_variant_incident_severity_provisional_vs_final
    """
    scenario = _diverging_signal_incident()
    activated = validate_success(
        api.activate_incident(scenario["incident"]["id"], scenario["headers"]["lead"])
    )

    assert_severity(activated, "SEV1", 96.00, "PROVISIONAL")
    assert_field(activated, "response_state", "ACTIVATED", "incident")
    assert_field(activated, "final_severity_tier", None, "incident")
    assert_field(activated, "final_severity_score", None, "incident")
    assert_state(read_signal(scenario["signals"]["c"]["id"]), "LINKED", "signal C")


def test_resolution_blends_the_escalated_peak_and_average_into_a_different_tier(api):
    """PRD §3.9: "Only signals in state `ESCALATED` are considered ... The peak
    is the largest `escalation_score` in that set. The average is the sum of the
    `escalation_score` values divided by the number of signals in the set,
    rounded half up to two decimals. The final score is six tenths of the peak
    plus four tenths of that rounded average, rounded half up to two decimals.
    Identical signal data can therefore land in a different tier than the
    provisional reading did."

    The escalated set is {92.00, 72.00}: peak 92.00, average 82.00, so the final
    score is 0.6 x 92.00 + 0.4 x 82.00 = 88.00, banding SEV2 where the
    provisional reading banded SEV1.

    Design: Difficulty/dual_variant_calc/dual_variant_incident_severity_provisional_vs_final
    """
    scenario = _diverging_signal_incident()
    scenario["incident"] = validate_success(
        api.activate_incident(scenario["incident"]["id"], scenario["headers"]["lead"])
    )
    resolved = validate_success(
        api.resolve_incident(
            scenario["incident"]["id"],
            scenario["headers"]["lead"],
            {"reputation_index_after": 44.00},
        )
    )

    assert_field(resolved, "response_state", "RESOLVED", "incident")
    assert_final_severity(resolved, "SEV2", 88.00)
    assert_field(resolved, "severity_basis", "FINAL", "incident")
    assert_severity(resolved, "SEV1", 96.00)
    assert resolved["final_severity_tier"] != resolved["severity_tier"], (
        "the two readings must be retained side by side and here they must differ"
    )
    assert_state(read_signal(scenario["signals"]["c"]["id"]), "LINKED", "signal C")


# ---------------------------------------------------------------------------
# Raw versus exposure-adjusted reputation delta
# ---------------------------------------------------------------------------


def test_scoring_stores_both_delta_variants_and_reports_the_adjusted_one(api):
    """PRD §3.9: "Both delta variants are **always** computed and both are
    always stored, whichever method is chosen. The raw delta is the review's
    snapshotted `reputation_index_after` less its snapshotted
    `reputation_index_before`, rounded half up to two decimals. ... The adjusted
    delta is the raw delta multiplied by one less the `exposure_factor`, plus the
    efficacy bonus, rounded half up to two decimals. ... `reported_delta` is then
    the raw variant when `scoring_method` is `RAW` and the adjusted variant when
    it is `ADJUSTED`."

    On 62.40 before and 55.10 after the raw delta is -7.30; with an
    ``exposure_factor`` of 0.0101 and one of one claim corrected the bonus is the
    full 2.50, so the adjusted delta is -7.30 x 0.9899 + 2.50 = -4.73.

    Design: Difficulty/dual_variant_calc/dual_variant_reputation_delta_raw_vs_adjusted
    """
    scenario = _reputation_scenario()
    review = scenario["review"]
    assert_four_decimals(review["exposure_factor"], 0.0101, "exposure_factor")
    assert_field(review, "total_claim_count", 1, "review")
    assert_field(review, "corrected_claim_count", 1, "review")

    scored = score_review(scenario, scoring_method="ADJUSTED", playbook_update_count=3)

    assert_two_decimals(scored["reputation_delta_raw"], -7.30, "reputation_delta_raw")
    assert_two_decimals(
        scored["reputation_delta_adjusted"], -4.73, "reputation_delta_adjusted"
    )
    assert_two_decimals(scored["reported_delta"], -4.73, "reported_delta")
    assert_field(scored, "scoring_method", "ADJUSTED", "review")
    assert_state(scored, "SCORED", "review")
    assert_field(scored, "playbook_update_count", 3, "review")
    assert_two_decimals(
        read_incident(scenario["incident"]["id"])["reputation_delta_reported"],
        -4.73,
        "incident.reputation_delta_reported",
    )


def test_the_raw_method_reports_the_undamped_delta_while_still_storing_both(api):
    """PRD §3.9: "Both delta variants are **always** computed and both are always
    stored, whichever method is chosen. ... `reported_delta` is then the raw
    variant when `scoring_method` is `RAW`."

    The identical reputation indices that report -4.73 under ``ADJUSTED`` report
    -7.30 under ``RAW`` — a 2.57 spread — and the adjusted variant is written to
    the review either way.

    Design: Difficulty/dual_variant_calc/dual_variant_reputation_delta_raw_vs_adjusted
    """
    scenario = _reputation_scenario()

    scored = score_review(scenario, scoring_method="RAW", playbook_update_count=3)

    assert_two_decimals(scored["reputation_delta_raw"], -7.30, "reputation_delta_raw")
    assert_two_decimals(
        scored["reputation_delta_adjusted"], -4.73, "reputation_delta_adjusted"
    )
    assert_two_decimals(scored["reported_delta"], -7.30, "reported_delta")
    assert_field(scored, "scoring_method", "RAW", "review")
    assert_state(scored, "SCORED", "review")
    assert_two_decimals(
        read_incident(scenario["incident"]["id"])["reputation_delta_reported"],
        -7.30,
        "incident.reputation_delta_reported",
    )
