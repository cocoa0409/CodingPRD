"""Queue A - rule ``compensating_invariant``.

Two conserved quantities and the operations that compensate a mutation of each:
the funding-source money ledger across commit and release, and the water
system's classification count partition across an evidence retraction.
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    AllocationState,
    Classification,
    ConsentOutcome,
    FulfillmentState,
    FundingMode,
    InventoryState,
    Material,
    ReplacementState,
    Side,
    SourceKind,
    SourceType,
)


# ---------------------------------------------------------------------------
# funding_source_ledger_conserved_across_commit_and_release
# ---------------------------------------------------------------------------


def _funded_order_with_fresh_ledger(api: ApiClient):
    """One 200000-cent source with 100000 cents committed against one FUNDED order."""
    system = fixtures.create_water_system(
        api,
        "IL2031020",
        system_name="Marlowe Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    fixtures.publish_inventory(api, system["id"], line["id"])
    source = fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=200000,
        priority_rank=1,
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        max_share_pct=100.0,
        equity_required_pct=0.0,
    )
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.resolve_consent(api, order["id"], outcome=ConsentOutcome.GRANTED)
    funded = fixtures.plan_funding(api, order["id"])
    return {"system": system, "line": line, "source": source, "order": order, "funded": funded}


def test_money_ledger_identity_holds_before_during_and_after_the_commit(
    api: ApiClient,
) -> None:
    """authorized == available + committed + drawn at every one of the three instants.

    PRD 3.6: "The ledger on a funding source is fully derived and holds a
    conservation identity: `available_cents` is always `authorized_cents` less
    `committed_cents` less `drawn_cents`."
    PRD 3.7: "For every referenced funding source, `committed_cents` increases by
    that source's allocated amount, `available_cents` is re-derived as
    `authorized_cents` less `committed_cents` less `drawn_cents`, and
    `disadvantaged_committed_cents`, `disadvantaged_share_pct` and
    `equity_shortfall_cents` are recomputed."
    PRD 3.7: "Cancelling from `FUNDED` runs the full financial reversal: every row
    of `funding_allocations` flips from `COMMITTED` to `RELEASED`; each referenced
    source's `committed_cents` decreases by that row's allocated amount and its
    `available_cents` is re-derived as `authorized_cents` less `committed_cents`
    less `drawn_cents`, which restores `available_cents` to exactly its pre-commit
    value; `disadvantaged_committed_cents`, `disadvantaged_share_pct` and
    `equity_shortfall_cents` are recomputed, and then the water system's
    `program_posture`; and the order's `allocated_total_cents` is set back to 0."

    Design: Difficulty/compensating_invariant/funding_source_ledger_conserved_across_commit_and_release
    """
    scenario = _funded_order_with_fresh_ledger(api)
    source_id = scenario["source"]["id"]

    assert scenario["source"]["available_cents"] == 200000
    assert scenario["source"]["committed_cents"] == 0
    assert scenario["source"]["drawn_cents"] == 0
    assert scenario["funded"]["allocated_total_cents"] == 100000

    committed = fixtures.read_funding_source(api, source_id)
    assert committed["available_cents"] == 100000
    assert committed["committed_cents"] == 100000
    assert committed["drawn_cents"] == 0
    assert (
        committed["authorized_cents"]
        == committed["available_cents"] + committed["committed_cents"] + committed["drawn_cents"]
    )

    fixtures.cancel_order(api, scenario["order"]["id"], "CUSTOMER_WITHDREW")

    released = fixtures.read_funding_source(api, source_id)
    assert released["available_cents"] == 200000
    assert released["committed_cents"] == 0
    assert released["drawn_cents"] == 0
    assert (
        released["authorized_cents"]
        == released["available_cents"] + released["committed_cents"] + released["drawn_cents"]
        == 200000
    )
    assert released["disadvantaged_committed_cents"] == 0
    assert released["disadvantaged_share_pct"] == pytest.approx(0.00)
    assert released["equity_shortfall_cents"] == 0


def test_cancelling_a_funded_order_is_a_true_inverse_with_no_cents_stranded(
    api: ApiClient,
) -> None:
    """Every allocation is RELEASED, the total returns to 0 and the line returns to ELIGIBLE.

    PRD 3.7: "Every cancel takes a `reason`, stores it as `cancellation_reason`,
    moves the order to `CANCELLED`, returns the service line's `replacement_state`
    from `IN_PROGRAM` to `ELIGIBLE`, and advances both rows' `version` by one."
    PRD 3.7: "and the order's `allocated_total_cents` is set back to 0."

    Design: Difficulty/compensating_invariant/funding_source_ledger_conserved_across_commit_and_release
    """
    scenario = _funded_order_with_fresh_ledger(api)

    cancelled = fixtures.cancel_order(api, scenario["order"]["id"], "CUSTOMER_WITHDREW")

    assert cancelled["fulfillment_state"] == FulfillmentState.CANCELLED
    assert cancelled["cancellation_reason"] == "CUSTOMER_WITHDREW"
    assert cancelled["allocated_total_cents"] == 0
    assert cancelled["funding_allocations"] != []
    assert all(
        row["state"] == AllocationState.RELEASED for row in cancelled["funding_allocations"]
    )

    line = fixtures.read_service_line(api, scenario["line"]["id"])
    assert line["replacement_state"] == ReplacementState.ELIGIBLE
    assert line["classification"] == Classification.LEAD

    assert fixtures.read_funding_source(api, scenario["source"]["id"])["drawn_cents"] == 0


# ---------------------------------------------------------------------------
# water_system_classification_counter_partition_conserved_across_evidence_retraction
# ---------------------------------------------------------------------------


def _line_with_a_retractable_lead_record(api: ApiClient):
    """An UNKNOWN line pushed to LEAD by one historic record that can be retracted."""
    system = fixtures.create_water_system(
        api,
        "IL2031021",
        system_name="Rookwood Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    predictive = fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.PREDICTIVE_MODEL,
        side=Side.CUSTOMER,
        observed_material=Material.UNKNOWN,
        observed_at="2026-06-02T00:00:00Z",
    )
    at_t0 = fixtures.read_water_system(api, system["id"])
    lead_record = fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )
    return {
        "system": system,
        "line": line,
        "predictive": predictive,
        "lead_record": lead_record,
        "at_t0": at_t0,
    }


def test_count_partition_totals_the_line_exactly_once_at_every_instant(
    api: ApiClient,
) -> None:
    """1 = 0+0+0+1 as UNKNOWN, 1 = 1+0+0+0 as LEAD, and 1 = 0+0+0+1 again after retraction.

    PRD 3.1: "`total_service_line_count` counts every service line of the system
    with no status filter whatsoever, and `lead_count`, `grr_count`,
    `non_lead_count` and `unknown_count` count the subsets whose `classification`
    is `LEAD`, `GRR`, `NON_LEAD` and `UNKNOWN` respectively."
    PRD 3.2: "An `InventoryAnalyst` may retract an evidence item by supplying a
    `reason`; the server sets `retracted` to true, stores that text as
    `retraction_reason`, and re-derives the line's `classification` and
    `certainty_score`, because a retracted item is excluded from every
    governing-evidence pool from then on."

    Design: Difficulty/compensating_invariant/water_system_classification_counter_partition_conserved_across_evidence_retraction
    """
    scenario = _line_with_a_retractable_lead_record(api)

    at_t0 = scenario["at_t0"]
    assert at_t0["total_service_line_count"] == 1
    assert at_t0["lead_count"] == 0
    assert at_t0["grr_count"] == 0
    assert at_t0["non_lead_count"] == 0
    assert at_t0["unknown_count"] == 1
    assert at_t0["unknown_share_pct"] == pytest.approx(100.00)

    at_t1 = fixtures.read_water_system(api, scenario["system"]["id"])
    assert at_t1["total_service_line_count"] == 1
    assert at_t1["lead_count"] == 1
    assert at_t1["unknown_count"] == 0
    assert at_t1["unknown_share_pct"] == pytest.approx(0.00)

    retracted = fixtures.retract_evidence(
        api, scenario["lead_record"]["id"], "RECORD_ATTRIBUTED_TO_WRONG_PREMISE"
    )
    assert retracted["retracted"] is True
    assert retracted["retraction_reason"] == "RECORD_ATTRIBUTED_TO_WRONG_PREMISE"

    at_t2 = fixtures.read_water_system(api, scenario["system"]["id"])
    assert at_t2["total_service_line_count"] == 1
    assert at_t2["lead_count"] == 0
    assert at_t2["grr_count"] == 0
    assert at_t2["non_lead_count"] == 0
    assert at_t2["unknown_count"] == 1
    assert at_t2["unknown_share_pct"] == pytest.approx(100.00)


def test_retraction_restores_the_derived_line_picture_and_touches_no_other_row(
    api: ApiClient,
) -> None:
    """The certainty score returns from 16.00 to 0.00 and the predictive item survives.

    PRD 3.2: "A line verified by potholing on both sides therefore reaches 100.00,
    while a line resting on a single historic record with nothing on the other side
    reaches 16.00."
    PRD 3.2: "Note the third rung — an unknown side outranks a clean side, so a
    line with copper on the utility side and nothing at all on the customer side
    classifies as `UNKNOWN`, not `NON_LEAD`."
    PRD 3.6: "The first step converts material risk into points: 50.00 points for a
    `LEAD` line, 35.00 for a `GRR` line, 0.00 for a `NON_LEAD` line, and for an
    `UNKNOWN` line a sliding figure — forty multiplied by the quantity one minus
    one hundredth of the line's `certainty_score`, rounded half-up to two decimals
    — so an utterly uncharacterized unknown line earns the full 40.00 while an
    unknown line already carrying strong evidence earns proportionally less."

    Design: Difficulty/compensating_invariant/water_system_classification_counter_partition_conserved_across_evidence_retraction
    """
    scenario = _line_with_a_retractable_lead_record(api)

    at_t1 = fixtures.read_service_line(api, scenario["line"]["id"])
    assert at_t1["classification"] == Classification.LEAD
    assert at_t1["certainty_score"] == pytest.approx(16.00)
    assert at_t1["replacement_priority_score"] == pytest.approx(50.00)

    fixtures.retract_evidence(
        api, scenario["lead_record"]["id"], "RECORD_ATTRIBUTED_TO_WRONG_PREMISE"
    )

    at_t2 = fixtures.read_service_line(api, scenario["line"]["id"])
    assert at_t2["classification"] == Classification.UNKNOWN
    assert at_t2["utility_side_material"] == Material.UNKNOWN
    assert at_t2["customer_side_material"] == Material.UNKNOWN
    assert at_t2["certainty_score"] == pytest.approx(0.00)
    assert at_t2["replacement_priority_score"] == pytest.approx(40.00)
    assert at_t2["inventory_state"] == InventoryState.CLASSIFIED_PROVISIONAL
    assert at_t2["replacement_state"] == ReplacementState.ELIGIBLE

    assert fixtures.read_evidence_item(api, scenario["predictive"]["id"])["retracted"] is False
