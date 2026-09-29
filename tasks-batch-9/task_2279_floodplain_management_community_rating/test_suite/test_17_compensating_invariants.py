"""Compensating invariants.

Derived state is always recomputed, never patched: a reversal, a remediation, or
a lowered adopted standard returns the conserved aggregate to exactly the value
it held before the entry that is being undone — while the historical rows the
system keeps as evidence stay exactly where they were.
"""
from test_helpers import (
    TEST_USERS,
    append_reversal,
    assert_improvement_record,
    assert_ledger_aggregates,
    assert_no_ledger_mutation,
    assert_sanction_state,
    certify_cycle,
    determine_case,
    draft_standard,
    get_success_data,
    issue_order,
    issue_violation,
    open_cycle,
    parse_instant,
    read_community,
    read_compliance_summary,
    read_cycle,
    read_standard,
    read_structure,
    record_visit,
    register_community,
    resolve_order,
    resolve_violation,
    set_clock,
    setup_ledger,
    setup_parcel,
    submit_cycle,
    submit_standard,
    validate_paginated,
    validate_success,
    verify_standard,
)

ADMIN_HEADERS = TEST_USERS["administrator_headers"]


def _read_record(api, record_id):
    return validate_success(api.get_improvement_record(record_id, ADMIN_HEADERS), 200)


def _setup_ledger_with_determined_auto_case(api):
    """Two counted records — 60000.00 on 2019-03-01 and 45000.00 on 2026-03-01 —
    whose 52.50 percent cumulative ratio auto-opens a CUMULATIVE case, then the
    determination is recorded so substantial_status is SUBSTANTIAL_IMPROVEMENT."""
    scenario = setup_ledger(
        [
            {"record_type": "IMPROVEMENT", "event_date": "2019-03-01T00:00:00Z",
             "cost_usd": 60_000.00},
            {"record_type": "IMPROVEMENT", "event_date": "2026-03-01T00:00:00Z",
             "cost_usd": 45_000.00},
        ],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"structure_use": "RESIDENTIAL", "pre_firm": True,
                             "construction_year": 1964, "market_value_usd": 200_000.00,
                             "highest_adjacent_grade_ft": 10.0},
    )
    cases, meta = validate_paginated(
        api.list_determination_cases(
            ADMIN_HEADERS, params={"structure_id": scenario["structure"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "The 52.50 percent cumulative ratio must have opened exactly one case, "
        f"got {meta['total_count']}"
    )
    scenario["case"] = determine_case(cases[0]["id"])
    scenario["structure"] = read_structure(scenario["structure"]["id"])
    return scenario


# ==========================================================================
# A reversal restores the ledger aggregates without rewriting history
# ==========================================================================

def test_reversal_restores_the_counted_cumulative_cost_and_re_anchors(api):
    """PRD §3.6: "The aggregates themselves are recomputed from scratch on every
    ledger append, on every reversal, and on every correction of a structure's
    `market_value_usd`."

    PRD §3.6: "Otherwise the **anchor** is chosen as the candidate with the latest
    `event_date`, breaking ties by the latest `created_at` — `created_at` is the only
    sanctioned tiebreaker and `id` is never used for ordering — and its identifier is
    written to the structure's `anchor_record_id`."

    PRD §3.6: "Finally, reversing the record that a case anchored moves that case to
    `WITHDRAWN` and reverts the structure's `substantial_status` to `NONE`, and when a
    linked property's `repetitive_loss_status` changes and that property has a
    `repetitive_loss_area_id`, the referenced area's `analysis_status` becomes
    `STALE`."

    Design: Difficulty/compensating_invariant/reversal_record_restores_ledger_aggregates_without_mutating_history
    """
    scenario = _setup_ledger_with_determined_auto_case(api)
    record_2019, record_2026 = scenario["records"]
    structure_id = scenario["structure"]["id"]

    assert_ledger_aggregates(scenario["structure"], record_2026["id"], 105_000.00, 52.50, 22.50)
    assert scenario["structure"]["substantial_status"] == "SUBSTANTIAL_IMPROVEMENT"

    reversal = append_reversal(
        structure_id, record_2026["id"], event_date="2026-03-01T00:00:00Z"
    )

    after = read_structure(structure_id)
    assert_ledger_aggregates(after, record_2019["id"], 60_000.00, 30.00, 30.00)
    assert after["substantial_status"] == "NONE"

    case = validate_success(
        api.get_determination_case(scenario["case"]["id"], ADMIN_HEADERS), 200
    )
    assert case["status"] == "WITHDRAWN"

    assert reversal["record_type"] == "REVERSAL"
    assert reversal["source"] == "REVERSAL_ADJUSTMENT"


def test_reversal_appends_a_row_and_leaves_the_reversed_record_intact(api):
    """PRD §2.4: "A record is never edited; when its effect must be undone, a
    compensating reversal record is appended instead, and the only flag the server
    ever flips on the original is the derived `reversed` marker described in §3.6."

    PRD §3.6: "A reversal copies its `cost_usd`, `claim_paid_amount_usd`, and
    `event_date` from its target, is itself never counted, and flips the target's
    `reversed` flag to true."

    Design: Difficulty/compensating_invariant/reversal_record_restores_ledger_aggregates_without_mutating_history
    """
    scenario = _setup_ledger_with_determined_auto_case(api)
    record_2026 = scenario["records"][1]
    before = _read_record(api, record_2026["id"])
    assert before["reversed"] is False

    reversal = append_reversal(
        scenario["structure"]["id"], record_2026["id"], event_date="2026-03-01T00:00:00Z"
    )

    assert_improvement_record(reversal)
    assert reversal["record_type"] == "REVERSAL"
    assert reversal["source"] == "REVERSAL_ADJUSTMENT"
    assert float(reversal["cost_usd"]) == 45_000.00
    assert float(reversal["claim_paid_amount_usd"]) == 0.00
    assert parse_instant(reversal["event_date"]) == parse_instant("2026-03-01T00:00:00Z")
    assert reversal["counted_in_cumulative"] is False
    assert reversal["reverses_record_id"] == record_2026["id"]

    after = _read_record(api, record_2026["id"])
    assert after["reversed"] is True
    assert float(after["cost_usd"]) == 45_000.00
    assert_no_ledger_mutation(before, after)

    _, meta = validate_paginated(
        api.list_improvement_records(
            ADMIN_HEADERS, params={"structure_id": scenario["structure"]["id"]}
        )
    )
    assert meta["total_count"] == 3


def test_improvement_summary_reports_the_restored_window_after_the_reversal(api):
    """PRD §3.6: "The candidate set is every record of the structure whose
    `counted_in_cumulative` is true and whose `reversed` is false."

    PRD §3.3: "A computed improvement summary is available for any structure and
    reports `structure_id`, the current `anchor_record_id`, the `window_start_date`
    and `window_end_date` of the closed anchored cumulative window — both null when
    no counted record exists — the `counted_record_count` of counted, non-reversed
    records lying inside that window, and the three aggregates
    `cumulative_counted_cost_usd`, `cumulative_improvement_pct`, and
    `single_event_improvement_pct`."

    Design: Difficulty/compensating_invariant/reversal_record_restores_ledger_aggregates_without_mutating_history
    """
    scenario = _setup_ledger_with_determined_auto_case(api)
    record_2019, record_2026 = scenario["records"]

    append_reversal(
        scenario["structure"]["id"], record_2026["id"], event_date="2026-03-01T00:00:00Z"
    )

    summary = validate_success(
        api.get_improvement_summary(scenario["structure"]["id"], ADMIN_HEADERS), 200
    )
    assert summary["structure_id"] == scenario["structure"]["id"]
    assert summary["anchor_record_id"] == record_2019["id"]
    assert summary["counted_record_count"] == 1
    assert float(summary["cumulative_counted_cost_usd"]) == 60_000.00
    assert float(summary["cumulative_improvement_pct"]) == 30.00
    assert float(summary["single_event_improvement_pct"]) == 30.00


# ==========================================================================
# Remediating an escalated violation returns the sanction score to zero
# ==========================================================================

def _setup_escalated_violation():
    """A CRITICAL violation whose remediation order defaulted after its deadline,
    so the raw score is 12 severity points plus the 5-point default penalty."""
    scenario = setup_parcel(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    scenario["violation"] = issue_violation(
        scenario["property"]["id"], violation_type="UNPERMITTED_FILL", severity="CRITICAL"
    )
    scenario["order"] = issue_order(
        scenario["violation"]["id"], deadline_at="2026-08-10T00:00:00Z",
        required_action="Remove unpermitted fill from the floodway fringe",
    )
    set_clock("2026-08-11T00:00:00Z")
    scenario["order"] = resolve_order(scenario["order"]["id"], "DEFAULTED")
    return scenario


def test_remediating_an_escalated_violation_returns_the_score_to_zero(api):
    """PRD §3.8: "Remediating from `ESCALATED` runs that identical side-effect list
    and additionally undoes the escalation penalty: the defaulted order stops
    contributing its 5 points because its violation is no longer `ESCALATED`, so the
    community's sanction score returns to its pre-violation value."

    PRD §3.8: "The tier rule is inclusive on the worse side: a score of 25 points or
    more is `SUSPENDED`, a score of 10 points or more is `ON_PROBATION`, and anything
    lower is `GOOD_STANDING`."

    Design: Difficulty/compensating_invariant/violation_remediation_restores_community_sanction_points_to_zero
    """
    scenario = _setup_escalated_violation()
    assert scenario["order"]["status"] == "DEFAULTED"
    escalated = validate_success(
        api.get_violation(scenario["violation"]["id"], ADMIN_HEADERS), 200
    )
    assert escalated["status"] == "ESCALATED"
    assert_sanction_state(read_community(scenario["community"]["id"]), 17, "ON_PROBATION")

    violation = get_success_data(
        api.resolve_violation(
            scenario["violation"]["id"],
            {"resolution": "REMEDIATED",
             "resolution_note": "Fill removed under municipal contract"},
            ADMIN_HEADERS,
        ),
        200,
    )

    assert violation["status"] == "REMEDIATED"
    assert violation["sanction_points_contributed"] == 0
    assert parse_instant(violation["resolved_at"]) == parse_instant("2026-08-11T00:00:00Z")
    assert_sanction_state(read_community(scenario["community"]["id"]), 0, "GOOD_STANDING")


def test_defaulted_order_survives_the_remediation_as_the_permanent_record(api):
    """PRD §3.8: "`REMEDIATED` moves the violation to the terminal `REMEDIATED`,
    stamps `resolved_at`, drops `sanction_points_contributed` to 0, moves every
    remediation order of that violation whose `status` is `ISSUED` or `EXTENDED` to
    `SATISFIED` in ascending `created_at` order, recomputes the community's
    `sanction_risk_points` and `compliance_posture`, and — when the `violation_type`
    was `ELEVATION_DEFICIENT`, a `structure_id` was named, and that structure carries
    no other violation in `OPEN`, `ORDER_ISSUED`, or `ESCALATED` — restores the
    structure's `compliance_status` to `COMPLIANT` if its `lowest_floor_elevation_ft`
    is not null and to `PENDING_CERTIFICATE` if it is null."

    PRD §3.1: "A computed compliance summary is available to the
    `StateNfipCoordinator` and the `FloodplainAdministrator` and reports the
    community's enforcement and rating posture in one payload: `community_id`, the
    current `sanction_risk_points` and `compliance_posture`, the
    `counted_violation_count` of violations currently inside the counted set, the
    `defaulted_order_count` of defaulted orders currently carrying a penalty, the
    `a510_credit_applied` value actually subtracted by the probation credit rule, and
    the rating figures `crs_class`, `crs_credit_points_claimed`,
    `crs_credit_points_verified`, `freeboard_ft`, and `cumulative_period_years`."

    Design: Difficulty/compensating_invariant/violation_remediation_restores_community_sanction_points_to_zero
    """
    scenario = _setup_escalated_violation()

    resolve_violation(
        scenario["violation"]["id"], "REMEDIATED",
        resolution_note="Fill removed under municipal contract",
    )

    order = validate_success(
        api.get_remediation_order(scenario["order"]["id"], ADMIN_HEADERS), 200
    )
    assert order["status"] == "DEFAULTED"

    summary = read_compliance_summary(scenario["community"]["id"])
    assert summary["counted_violation_count"] == 0
    assert summary["defaulted_order_count"] == 0
    assert summary["a510_credit_applied"] == 0
    assert summary["sanction_risk_points"] == 0
    assert summary["compliance_posture"] == "GOOD_STANDING"


# ==========================================================================
# Lowering the adopted freeboard expires the verified credit it supported
# ==========================================================================

def _setup_certified_freeboard_credit():
    """freeboard_ft 5.0 supports a VERIFIED A430_FREEBOARD claim of 500 points, and
    the 2026 cycle is CERTIFIED at class 9 on those verified points."""
    community = register_community(
        name="Bayou City", state_code="TX", freeboard_ft=5.0, cumulative_period_years=10
    )
    standard = draft_standard(
        community["id"], activity_code="A430_FREEBOARD", documentation_cycle_year=2026,
        claimed_points=500,
    )
    submit_standard(standard["id"])
    cycle = open_cycle(
        community["id"], cycle_year=2026, cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z", due_at="2026-09-30T00:00:00Z",
    )
    submit_cycle(cycle["id"])
    standard = verify_standard(standard["id"])
    record_visit(cycle["id"])
    cycle = certify_cycle(cycle["id"])
    return {"community": read_community(community["id"]), "standard": standard, "cycle": cycle}


def test_lowering_freeboard_expires_the_verified_claim_and_resets_the_class(api):
    """PRD §3.1: "Every `VERIFIED` higher-standards submission of that community is
    re-evaluated against the new configuration, and any whose recomputed
    `max_points_allowed` now falls below its recorded `verified_points` moves to
    `EXPIRED` with `verified_points` reset to 0 — processed in ascending `created_at`
    order — after which `crs_credit_points_verified` and `crs_class` are recomputed."

    PRD §3.9: "For `A430_FREEBOARD` the ceiling is 100 points for each foot of
    adopted `freeboard_ft`, counting no more than 5.0 feet, with the product
    truncated downward to a whole number of points — so 2.5 feet of freeboard yields
    250 and 5.4 feet still yields 500."

    Design: Difficulty/compensating_invariant/lowering_adopted_freeboard_expires_verified_credit_and_reverses_class
    """
    scenario = _setup_certified_freeboard_credit()
    assert scenario["standard"]["verified_points"] == 500
    assert scenario["community"]["crs_credit_points_verified"] == 500
    assert scenario["community"]["crs_class"] == 9

    community = validate_success(
        api.amend_community_standards(
            scenario["community"]["id"], {"freeboard_ft": 1.0}, ADMIN_HEADERS
        ),
        200,
    )

    assert float(community["freeboard_ft"]) == 1.0
    assert community["crs_credit_points_verified"] == 0
    assert community["crs_class"] == 10

    standard = read_standard(scenario["standard"]["id"])
    assert standard["documentation_status"] == "EXPIRED"
    assert standard["verified_points"] == 0


def test_certified_cycle_keeps_its_historical_class_after_the_amendment(api):
    """PRD §3.9: "`total_verified_points` is frozen from that recomputed figure,
    `resulting_class` is computed by the **verified variant** of the same class
    formula — fed with `crs_credit_points_verified`, which sums `verified_points`,
    each already capped at its activity ceiling, and which reflects the sweep — the
    community's `crs_class` is set to `resulting_class`, and the cycle moves to the
    terminal `CERTIFIED`."

    PRD §3.1: "Every `VERIFIED` higher-standards submission of that community is
    re-evaluated against the new configuration, and any whose recomputed
    `max_points_allowed` now falls below its recorded `verified_points` moves to
    `EXPIRED` with `verified_points` reset to 0 — processed in ascending `created_at`
    order — after which `crs_credit_points_verified` and `crs_class` are recomputed."

    Design: Difficulty/compensating_invariant/lowering_adopted_freeboard_expires_verified_credit_and_reverses_class
    """
    scenario = _setup_certified_freeboard_credit()
    assert scenario["cycle"]["status"] == "CERTIFIED"
    assert scenario["cycle"]["resulting_class"] == 9
    assert scenario["cycle"]["total_verified_points"] == 500

    validate_success(
        api.amend_community_standards(
            scenario["community"]["id"], {"freeboard_ft": 1.0}, ADMIN_HEADERS
        ),
        200,
    )

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "CERTIFIED"
    assert cycle["resulting_class"] == 9
    assert cycle["total_verified_points"] == 500
    assert read_standard(scenario["standard"]["id"])["max_points_allowed"] == 100
