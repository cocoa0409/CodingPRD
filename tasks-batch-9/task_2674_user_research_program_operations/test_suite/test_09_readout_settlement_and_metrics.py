"""Readout settlement: acceptance, citation scoping, metrics and the money.

These tests cover the end of the research chain — the stakeholder acceptance that
closes a study and its request, the citation-scoping rule that refuses a readout
naming a sibling study's finding, the five operations metrics with their
four-term impact score, and the two settlement modes whose availability turns on
the study's execution status.
"""

import pytest

from test_helpers import (
    RESEARCH_LEAD_HEADERS,
    RESEARCH_OPS_ADMIN_HEADERS,
    RESEARCHER_HEADERS,
    STAKEHOLDER_HEADERS,
    assert_ledger_partition,
    close_fielding,
    complete_session,
    create_finding,
    create_incentive_settlement_payload,
    create_readout_payload,
    create_theme,
    grant_consent,
    invite,
    open_follow_up,
    read_decision,
    read_metrics,
    read_pool,
    read_recruitment,
    read_request,
    read_study,
    read_theme,
    record_no_show,
    respond_to_readout_payload,
    schedule,
    screen,
    setup_accepted_readout,
    setup_delivered_readout,
    setup_fielding_study,
    setup_two_fielding_studies_sharing_pool,
    validate_error,
    validate_paginated,
    validate_success,
)

STARTUP_INSTANT = "2026-08-01T00:00:00.000Z"
ROOMY_POOL = {"incentive_budget_cents": 100000}


# ===========================================================================
# Acceptance closes three rows at once
# ===========================================================================
def test_readout_acceptance_closes_the_study_and_the_request(api):
    """One stakeholder acceptance carries the readout, its study and the study's
    request into their terminal states in a single call.

    PRD 3.8: "Both outcomes require the readout to be `DELIVERED` and set
    `responded_at` to the clock instant, and both are terminal."

    PRD 3.8: "Finally it closes the chain of work: the study moves `REPORTED →
    CLOSED` and the study's research request moves `IN_STUDY → CLOSED`."

    PRD 3.8: "On the `DELIVERED → ACCEPTED` transition the platform captures the
    decision's current `evidence_confidence` into the readout's
    `decision_confidence_before`, recomputes that decision's
    `evidence_confidence` from scratch, and stores the recomputed figure into the
    readout's `decision_confidence_after` as well as onto the decision itself."

    Design: Corner/state_machines/readout_acceptance_closes_the_study_and_the_request
    """
    ctx = setup_delivered_readout(api, pool_overrides=dict(ROOMY_POOL))
    assert ctx["readout"]["status"] == "DELIVERED", (
        f"Expected the precondition to leave the readout DELIVERED, "
        f"got {ctx['readout']['status']}"
    )
    assert ctx["study"]["execution_status"] == "REPORTED", (
        f"Expected delivery to have moved the study to REPORTED, "
        f"got {ctx['study']['execution_status']}"
    )

    accepted = validate_success(
        api.respond_to_readout(
            ctx["readout"]["id"],
            respond_to_readout_payload(
                "ACCEPTED", note="Adding the template library to the next cycle"
            ),
            STAKEHOLDER_HEADERS,
        )
    )

    assert accepted["status"] == "ACCEPTED", (
        f"Expected the readout to reach ACCEPTED, got {accepted['status']}"
    )
    assert accepted["responded_at"] == STARTUP_INSTANT, (
        f"Expected responded_at to be set to the clock instant, "
        f"got {accepted['responded_at']!r}"
    )
    assert accepted["response_note"] == "Adding the template library to the next cycle", (
        f"Expected the supplied note to be stored as response_note, "
        f"got {accepted['response_note']!r}"
    )
    assert accepted["decision_confidence_before"] == pytest.approx(0.00, abs=0.01), (
        f"Expected the decision's confidence before acceptance to be captured as "
        f"0.00, got {accepted['decision_confidence_before']}"
    )
    assert accepted["decision_confidence_after"] == pytest.approx(0.60, abs=0.01), (
        f"Expected the recomputed confidence of 0.60 — a 0.6000 mean published "
        f"strength at the INTERVIEW multiplier of 1.00 — to be stored as "
        f"decision_confidence_after, got {accepted['decision_confidence_after']}"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["execution_status"] == "CLOSED", (
        f"Expected acceptance to carry the study REPORTED -> CLOSED, "
        f"got {study['execution_status']}"
    )
    assert study["recruitment_status"] == "QUOTA_MET", (
        f"Expected the recruitment dimension to stand at QUOTA_MET with 3 completed "
        f"sessions against a target of 3, got {study['recruitment_status']}"
    )

    request = read_request(ctx["request"]["id"], api)
    assert request["status"] == "CLOSED", (
        f"Expected acceptance to carry the request IN_STUDY -> CLOSED, "
        f"got {request['status']}"
    )


def test_acceptance_feeds_decision_confidence_and_bumps_theme_reuse(api):
    """Acceptance is the only path that writes confidence onto the decision and
    counts a theme as reused; it does not lock the decision.

    PRD 3.8: "It then increments `reuse_count` for every theme referenced by a
    cited finding and for each of that theme's ancestors up to the root."

    PRD 3.8: "Sum the contributions across all accepted readouts, divide by a
    divisor of 1.00 — the sum is used as-is — hold the result at a ceiling of
    1.00, and round half-up to two decimals to obtain the decision's
    `evidence_confidence`."

    PRD 3.7: "A theme whose `evidence_weight` is **at least 1.20** is
    `ESTABLISHED`; below that it is `EMERGING`, and the two transitions between
    those postures are pure consequences of the rollup, never a command."

    PRD 3.7: "Separately, a theme's `reuse_count` is the number of `ACCEPTED`
    readouts whose `cited_finding_ids` include at least one finding belonging to
    that theme *or to any of its descendants* — this is the repository's reuse
    signal, and it is why drafting a finding leaves the counter alone."

    Design: Corner/state_machines/readout_acceptance_closes_the_study_and_the_request
    """
    ctx = setup_delivered_readout(api, pool_overrides=dict(ROOMY_POOL))

    validate_success(
        api.respond_to_readout(
            ctx["readout"]["id"],
            respond_to_readout_payload("ACCEPTED"),
            STAKEHOLDER_HEADERS,
        )
    )

    decision = read_decision(ctx["decision"]["id"], api)
    assert decision["evidence_confidence"] == pytest.approx(0.60, abs=0.01), (
        f"Expected the decision to hold the recomputed 0.60, "
        f"got {decision['evidence_confidence']}"
    )
    assert decision["status"] == "OPEN", (
        f"Expected acceptance to feed confidence without locking the decision, "
        f"got {decision['status']}"
    )
    assert decision["locked_at"] is None, (
        f"Expected locked_at to stay null after a mere acceptance, "
        f"got {decision['locked_at']!r}"
    )

    theme = read_theme(ctx["theme"]["id"], api)
    assert theme["reuse_count"] == 1, (
        f"Expected the theme behind the cited finding to be counted as reused once, "
        f"got {theme['reuse_count']}"
    )
    assert theme["own_evidence_weight"] == pytest.approx(0.60, abs=0.01), (
        f"Expected the theme's own weight to be the single published finding's 0.60 "
        f"at the MEDIUM severity multiplier of 1.00, "
        f"got {theme['own_evidence_weight']}"
    )
    assert theme["evidence_weight"] == pytest.approx(0.60, abs=0.01), (
        f"Expected a leaf theme's rolled-up weight to equal its own weight, "
        f"got {theme['evidence_weight']}"
    )
    assert theme["status"] == "EMERGING", (
        f"Expected 0.60 to sit below the 1.20 established bar, got {theme['status']}"
    )

    finding = validate_success(
        api.get_finding(ctx["finding"]["id"], RESEARCHER_HEADERS)
    )
    assert finding["evidence_strength"] == pytest.approx(0.60, abs=0.01), (
        f"Expected a raw 3.00 over three DIRECT_QUOTE links on an INTERVIEW study to "
        f"give density 1.0000 and corroboration 0.60, got {finding['evidence_strength']}"
    )
    assert finding["strength_variant"] == "CORROBORATED", (
        f"Expected a locked finding to read under the corroborated variant, "
        f"got {finding['strength_variant']!r}"
    )


# ===========================================================================
# The five operations metrics and the four-term impact score
# ===========================================================================
def test_study_metrics_impact_score_sums_its_four_terms(api):
    """Acceptance, a partial findings term, a perfect recruitment ratio and — only
    once every follow-up is done — the follow-up term add up to the impact score.

    PRD 3.9: "`recruitment_efficiency` is `completed_count` divided by
    `invited_count`, rounded half-up to four decimal places, and exactly 0.0000
    when `invited_count` is 0."

    PRD 3.9: "`published_findings` is the count of the study's findings whose
    `status` is `PUBLISHED`; retracted findings are excluded, as are superseded
    readouts wherever readouts are counted."

    PRD 3.9: "`impact_score` is the sum of four terms, each rounded to two
    decimals before it enters the sum, with the sum itself rounded half-up to two
    decimals:"

    PRD 3.9: "**Findings term:** divide `published_findings` by a target of 3,
    hold the ratio at a ceiling of 1.0, multiply by 30.0 and round half-up to two
    decimals."

    PRD 3.9: "**Follow-up term:** 10.0 points when the study has at least one
    follow-up **and** every follow-up of every readout of the study is `DONE`;
    0.0 otherwise."

    Design: Corner/calculations/study_metrics_impact_score_sums_its_four_terms
    """
    ctx = setup_accepted_readout(
        api, note="Scheduling the refresh this quarter", pool_overrides=dict(ROOMY_POOL)
    )
    study_id = ctx["study"]["id"]

    first = read_metrics(study_id, api)
    assert first["cycle_time_days"] == 0, (
        f"Expected the readout to have been delivered at the same clock instant the "
        f"study was created, giving a 0-day cycle time, got {first['cycle_time_days']}"
    )
    assert first["fielding_days"] == 0, (
        f"Expected fielding to have opened and closed at the same clock instant, "
        f"got {first['fielding_days']}"
    )
    assert first["recruitment_efficiency"] == pytest.approx(1.0000, abs=0.0001), (
        f"Expected 3 completed over 3 invited to report as 1.0000, "
        f"got {first['recruitment_efficiency']}"
    )
    assert first["published_findings"] == 1, (
        f"Expected exactly one PUBLISHED finding, got {first['published_findings']}"
    )
    assert first["impact_score"] == pytest.approx(70.00, abs=0.01), (
        f"Expected 40.00 acceptance plus a partial 10.00 findings term plus 20.00 "
        f"recruitment plus 0.00 follow-up, got {first['impact_score']}"
    )

    follow_up = open_follow_up(
        ctx["readout"]["id"],
        api,
        due_date="2026-08-15T00:00:00Z",
        description="Land the nightly refresh",
    )
    assert follow_up["status"] == "OPEN", (
        f"Expected a freshly opened follow-up to be OPEN, got {follow_up['status']}"
    )

    second = read_metrics(study_id, api)
    assert second["impact_score"] == pytest.approx(70.00, abs=0.01), (
        f"Expected an OPEN follow-up to earn nothing, leaving the score at 70.00, "
        f"got {second['impact_score']}"
    )

    completed = validate_success(
        api.complete_follow_up(follow_up["id"], STAKEHOLDER_HEADERS)
    )
    assert completed["status"] == "DONE", (
        f"Expected the owner's completion to carry the follow-up to DONE, "
        f"got {completed['status']}"
    )
    assert completed["completed_at"] == STARTUP_INSTANT, (
        f"Expected completed_at to be set to the clock instant, "
        f"got {completed['completed_at']!r}"
    )

    third = read_metrics(study_id, api)
    assert third["impact_score"] == pytest.approx(80.00, abs=0.01), (
        f"Expected the follow-up term's 10.00 to land once every follow-up of every "
        f"readout of the study is DONE, got {third['impact_score']}"
    )
    assert third["published_findings"] == 1, (
        f"Expected the findings term to stay partial at one published finding, "
        f"got {third['published_findings']}"
    )


# ===========================================================================
# Citations are scoped to the readout's own study
# ===========================================================================
def test_readout_citing_another_studys_finding_is_rejected(api):
    """A finding that exists but belongs to a sibling study cannot be cited, and a
    mixed citation list is refused just as a wholly out-of-scope one is.

    PRD 3.8: "Every id in `cited_finding_ids` must resolve to a finding — an id
    that resolves to nothing is `ERR_FINDING_NOT_FOUND` — and every one of those
    findings must belong to the same study as the readout, else
    `ERR_CITATION_STUDY_MISMATCH`."

    PRD 3.8: "A successful draft opens in `status` `DRAFT` with `delivered_at`,
    `responded_at`, `response_note`, `decision_confidence_before` and
    `decision_confidence_after` all null, and it increments the target study's
    `version` by 1."

    Design: Corner/validations/readout_citing_another_studys_finding_is_rejected
    """
    ctx = setup_two_fielding_studies_sharing_pool(api, pool_overrides=dict(ROOMY_POOL))
    study_a, study_b = ctx["studies"][0], ctx["studies"][1]
    study_a = close_fielding(study_a["id"], api)
    close_fielding(study_b["id"], api)
    assert study_a["execution_status"] == "ANALYSIS", (
        f"Expected closing fielding to move study A into ANALYSIS, "
        f"got {study_a['execution_status']}"
    )

    decision_id = read_request(study_a["research_request_id"], api)["roadmap_decision_id"]
    theme = create_theme(api, label="Planning friction")
    finding_a = create_finding(
        study_a["id"],
        theme["id"],
        api,
        statement="Weekly planning waits on the data refresh",
        severity="MEDIUM",
    )
    finding_b = create_finding(
        study_b["id"],
        theme["id"],
        api,
        statement="Daily planning waits on approvals",
        severity="MEDIUM",
    )

    version_before = read_study(study_a["id"], api)["version"]

    validate_error(
        api.create_readout(
            study_a["id"],
            create_readout_payload(
                decision_id,
                [finding_b["id"]],
                version_before,
                recommendation="Move the refresh earlier",
            ),
            RESEARCH_LEAD_HEADERS,
        ),
        "ERR_CITATION_STUDY_MISMATCH",
    )
    validate_error(
        api.create_readout(
            study_a["id"],
            create_readout_payload(
                decision_id,
                [finding_b["id"], finding_a["id"]],
                version_before,
                recommendation="Move the refresh earlier",
            ),
            RESEARCH_LEAD_HEADERS,
        ),
        "ERR_CITATION_STUDY_MISMATCH",
    )

    drafted = validate_success(
        api.create_readout(
            study_a["id"],
            create_readout_payload(
                decision_id,
                [finding_a["id"]],
                version_before,
                recommendation="Move the refresh earlier",
            ),
            RESEARCH_LEAD_HEADERS,
        ),
        201,
    )
    assert drafted["status"] == "DRAFT", (
        f"Expected the in-scope citation to open a DRAFT readout, "
        f"got {drafted['status']}"
    )
    assert drafted["cited_finding_ids"] == [finding_a["id"]], (
        f"Expected the citation list to hold only study A's own finding, "
        f"got {drafted['cited_finding_ids']}"
    )
    for field in (
        "delivered_at",
        "responded_at",
        "response_note",
        "decision_confidence_before",
        "decision_confidence_after",
    ):
        assert drafted[field] is None, (
            f"Expected a fresh draft to open with {field} null, got {drafted[field]!r}"
        )

    version_after = read_study(study_a["id"], api)["version"]
    assert version_after == version_before + 1, (
        f"Expected only the successful draft to increment study A's version, taking it "
        f"from {version_before} to {version_before + 1}, got {version_after}"
    )

    rows, meta = validate_paginated(
        api.list_readouts(RESEARCH_LEAD_HEADERS, params={"study_id": study_a["id"]})
    )
    assert meta["total_count"] == 1, (
        f"Expected the two refused calls to have created no readout rows, leaving one "
        f"readout on study A, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [drafted["id"]], (
        f"Expected the only readout of study A to be the accepted draft, "
        f"got {[row['id'] for row in rows]}"
    )


# ===========================================================================
# The two settlement modes and the study status each one needs
# ===========================================================================
def _study_with_one_completed_one_no_show_and_one_invited(api):
    """A fielded study of three invitations: one completed session, one no-show
    that has already forfeited its reservation, and one still merely invited."""
    ctx = setup_fielding_study(api, participant_count=3, pool_overrides=dict(ROOMY_POOL))
    study_id = ctx["study"]["id"]
    participants = ctx["participants"]

    ctx["recruitments"] = [
        invite(study_id, participants[index]["id"], api) for index in range(3)
    ]
    grant_consent(participants[0]["id"], study_id, api)
    grant_consent(participants[1]["id"], study_id, api)

    ctx["recruitments"][0] = screen(ctx["recruitments"][0]["id"], api)
    ctx["recruitments"][1] = screen(ctx["recruitments"][1]["id"], api)
    ctx["recruitments"][0] = schedule(
        ctx["recruitments"][0]["id"],
        "2026-08-05T10:00:00Z",
        "2026-08-05T11:00:00Z",
        api,
    )
    ctx["recruitments"][1] = schedule(
        ctx["recruitments"][1]["id"],
        "2026-08-05T12:00:00Z",
        "2026-08-05T13:00:00Z",
        api,
    )
    ctx["recruitments"][0] = complete_session(ctx["recruitments"][0]["id"], api)
    ctx["recruitments"][1] = record_no_show(
        ctx["recruitments"][1]["id"], api, reason="No answer at the scheduled time"
    )
    ctx["pool"] = read_pool(ctx["pool"]["id"], api)
    return ctx


def test_settlement_mode_is_conditional_on_the_studys_execution_status(api):
    """The advisory mode answers from `FIELDING`; the binding mode is refused until
    fielding closes and then refused a second time as already settled.

    PRD 3.9: "**`FORWARD_ESTIMATE` is advisory and moves no money.** It may be
    requested at any time, including while the study is still `FIELDING`, and
    from any `execution_status` whatsoever; it may be run repeatedly."

    PRD 3.9: "The estimate is the plain sum of those rows' `reserved_cents` — the
    assumption being that every open recruitment completes at its full reserved
    amount."

    PRD 3.9: "The figure is written to the pool's `last_estimate_cents` and **no
    recruitment row is mutated**."

    PRD 3.9: "It is refused with `ERR_SETTLEMENT_NOT_PERMITTED` unless the named
    study's `execution_status` is `ANALYSIS`, `REPORTED` or `CLOSED`, and refused
    with `ERR_ALREADY_SETTLED` when that `study_id` already appears in the pool's
    `settled_study_ids` — a study's incentives are settled bindingly once and only
    once."

    Design: Corner/endpoints/settlement_mode_is_conditional_on_the_studys_execution_status
    """
    ctx = _study_with_one_completed_one_no_show_and_one_invited(api)
    study_id = ctx["study"]["id"]
    pool_id = ctx["pool"]["id"]
    completed, no_show, invited = ctx["recruitments"]
    assert ctx["study"]["execution_status"] == "FIELDING", (
        f"Expected the study still to be FIELDING, "
        f"got {ctx['study']['execution_status']}"
    )

    estimated = validate_success(
        api.create_incentive_settlement(
            pool_id,
            create_incentive_settlement_payload(
                study_id, "FORWARD_ESTIMATE", read_pool(pool_id, api)["version"]
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        )
    )
    assert estimated is not None, "Expected the advisory settlement to answer with data"
    pool = read_pool(pool_id, api)
    assert pool["last_estimate_cents"] == 10000, (
        f"Expected the estimate to be the plain sum of the completed row's 5000 and the "
        f"still-invited row's 5000, with the forfeited row outside the candidate set, "
        f"got {pool['last_estimate_cents']}"
    )
    assert read_recruitment(completed["id"], api)["incentive_state"] == "RESERVED", (
        "Expected the advisory run to mutate no recruitment row, but the completed "
        "row left RESERVED"
    )
    assert read_recruitment(invited["id"], api)["incentive_state"] == "RESERVED", (
        "Expected the advisory run to mutate no recruitment row, but the invited "
        "row left RESERVED"
    )

    validate_error(
        api.create_incentive_settlement(
            pool_id,
            create_incentive_settlement_payload(
                study_id, "CHRONOLOGICAL_ACTUAL", read_pool(pool_id, api)["version"]
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        ),
        "ERR_SETTLEMENT_NOT_PERMITTED",
    )
    for recruitment in (completed, no_show, invited):
        before = recruitment["incentive_state"]
        after = read_recruitment(recruitment["id"], api)["incentive_state"]
        assert after == before, (
            f"Expected the refused binding run to leave every incentive_state alone, "
            f"but one row moved from {before} to {after}"
        )

    study = close_fielding(study_id, api)
    assert study["execution_status"] == "ANALYSIS", (
        f"Expected closing fielding to open the binding mode's door by moving the "
        f"study to ANALYSIS, got {study['execution_status']}"
    )

    validate_success(
        api.create_incentive_settlement(
            pool_id,
            create_incentive_settlement_payload(
                study_id, "CHRONOLOGICAL_ACTUAL", read_pool(pool_id, api)["version"]
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        )
    )
    settled_pool = read_pool(pool_id, api)
    assert settled_pool["settled_study_ids"].count(study_id) == 1, (
        f"Expected the study to appear exactly once in settled_study_ids, "
        f"got {settled_pool['settled_study_ids']}"
    )

    validate_error(
        api.create_incentive_settlement(
            pool_id,
            create_incentive_settlement_payload(
                study_id, "CHRONOLOGICAL_ACTUAL", read_pool(pool_id, api)["version"]
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        ),
        "ERR_ALREADY_SETTLED",
    )


def test_the_binding_walk_pays_the_completed_row_and_releases_the_rest(api):
    """The binding run pays the completed row in full, releases the row that was
    entitled to nothing, and never touches the forfeited row.

    PRD 3.9: "A `COMPLETED` row is entitled to its full `reserved_cents`."

    PRD 3.9: "A row still in `INVITED`, `SCREENED_IN` or `SCHEDULED`, or one
    already `WITHDRAWN`, is entitled to nothing."

    PRD 3.9: "When the payment is zero — whether because the row was not entitled
    to anything or because the pool had nothing left — the row's `paid_cents`
    stays 0 and its `incentive_state` moves `RESERVED → RELEASED`."

    PRD 3.9: "Rows whose `incentive_state` is already `FORFEITED` from a no-show,
    or already `RELEASED` from a withdrawal, are outside both modes' candidate
    sets — their money was accounted for when the session fell through."

    Design: Corner/endpoints/settlement_mode_is_conditional_on_the_studys_execution_status
    """
    ctx = _study_with_one_completed_one_no_show_and_one_invited(api)
    study_id = ctx["study"]["id"]
    pool_id = ctx["pool"]["id"]
    completed, no_show, invited = ctx["recruitments"]
    close_fielding(study_id, api)

    validate_success(
        api.create_incentive_settlement(
            pool_id,
            create_incentive_settlement_payload(
                study_id, "CHRONOLOGICAL_ACTUAL", read_pool(pool_id, api)["version"]
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        )
    )

    paid_row = read_recruitment(completed["id"], api)
    assert paid_row["incentive_state"] == "PAID", (
        f"Expected the completed row to be paid, got {paid_row['incentive_state']}"
    )
    assert paid_row["paid_cents"] == 5000, (
        f"Expected the completed row to be paid its full 5000 reserved cents, "
        f"got {paid_row['paid_cents']}"
    )

    forfeited_row = read_recruitment(no_show["id"], api)
    assert forfeited_row["incentive_state"] == "FORFEITED", (
        f"Expected the no-show row to stay outside the candidate set as FORFEITED, "
        f"got {forfeited_row['incentive_state']}"
    )
    assert forfeited_row["paid_cents"] == 0, (
        f"Expected the forfeited row to be paid nothing, "
        f"got {forfeited_row['paid_cents']}"
    )

    released_row = read_recruitment(invited["id"], api)
    assert released_row["incentive_state"] == "RELEASED", (
        f"Expected the still-invited row to be released rather than paid, "
        f"got {released_row['incentive_state']}"
    )
    assert released_row["paid_cents"] == 0, (
        f"Expected a row entitled to nothing to keep paid_cents at 0, "
        f"got {released_row['paid_cents']}"
    )

    pool = read_pool(pool_id, api)
    assert pool["incentive_reserved_cents"] == 0, (
        f"Expected every reservation of the study to have left the reserved bucket, "
        f"got {pool['incentive_reserved_cents']}"
    )
    assert pool["incentive_paid_cents"] == 5000, (
        f"Expected the single payment of 5000 to be the pool's whole paid balance, "
        f"got {pool['incentive_paid_cents']}"
    )
    assert pool["incentive_available_cents"] == 95000, (
        f"Expected the 100000-cent budget less the 5000 paid to sit in available, "
        f"got {pool['incentive_available_cents']}"
    )
    assert_ledger_partition(pool)
