"""Queue A - rule ``dual_variant_calc``.

Two calculations in this contract have two pinned variants selected by stored
state rather than by a request field: the certainty score (records basis versus
field basis) and the funding apportionment (waterfall versus pro rata).
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    AllocationState,
    CertaintyBasis,
    Classification,
    FulfillmentState,
    FundingMode,
    InventoryState,
    Material,
    SampleType,
    Side,
    SourceKind,
    SourceType,
)


# ---------------------------------------------------------------------------
# certainty_score_records_basis_versus_field_basis_on_identical_evidence_set
# ---------------------------------------------------------------------------


def _records_basis_line(api: ApiClient):
    """One line holding historic, predictive and utility-side pothole evidence.

    Field evidence exists on the utility side only, so the both-sides condition
    does not hold and the line is still scored under the records basis.
    """
    system = fixtures.create_water_system(
        api,
        "IL2031001",
        system_name="Riverbend Water District",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-9900"
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.PREDICTIVE_MODEL,
        side=Side.CUSTOMER,
        observed_material=Material.UNKNOWN,
        observed_at="2026-06-02T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-07-10T00:00:00Z",
    )
    return system, line


def test_records_basis_certainty_score_filters_field_evidence_out_of_the_pool(
    api: ApiClient,
) -> None:
    """Field evidence on one side only leaves the line on the records basis at 16.00.

    PRD 3.2: "A line's `certainty_basis` is `RECORDS_BASIS` while its
    `inventory_state` is `UNCLASSIFIED` or `CLASSIFIED_PROVISIONAL`, and
    `FIELD_BASIS` once its `inventory_state` is `CLASSIFIED_VERIFIED`."
    PRD 3.2: "Under `RECORDS_BASIS` only `HISTORIC_RECORD` and
    `PREDICTIVE_MODEL` are admissible; under `FIELD_BASIS` all five source types
    are."
    PRD 3.2: "A line verified by potholing on both sides therefore reaches
    100.00, while a line resting on a single historic record with nothing on the
    other side reaches 16.00."

    Design: Difficulty/dual_variant_calc/certainty_score_records_basis_versus_field_basis_on_identical_evidence_set
    """
    _system, line = _records_basis_line(api)

    before = fixtures.read_service_line(api, line["id"])

    assert before["inventory_state"] == InventoryState.CLASSIFIED_PROVISIONAL
    assert before["certainty_basis"] == CertaintyBasis.RECORDS_BASIS
    assert before["certainty_score"] == pytest.approx(16.00)
    assert before["replacement_priority_score"] == pytest.approx(50.00)


def test_field_basis_rescores_the_same_evidence_set_to_ninety_one(api: ApiClient) -> None:
    """Landing field evidence on the second side flips the basis and rescores to 91.00.

    PRD 3.2: "The moment that both-sides field-evidence condition does hold —
    immediately after any evidence insertion, whether manual, by override, or by
    an appointment cascade — the server moves the line from
    `CLASSIFIED_PROVISIONAL` to `CLASSIFIED_VERIFIED` on its own initiative."
    PRD 3.2: "That transition sets `certainty_basis` to `FIELD_BASIS` and
    re-derives `utility_side_material`, `customer_side_material`,
    `classification` and `certainty_score` under the field variant: the very same
    evidence set now admits field observations into the pool, so a pothole or
    visual inspection outranks the records tier and supplies both the material
    and its higher weight."
    PRD 3.6: "The second step adds a certainty bonus of 15.00 points when the
    line's `inventory_state` is `CLASSIFIED_VERIFIED`, and nothing otherwise."

    Design: Difficulty/dual_variant_calc/certainty_score_records_basis_versus_field_basis_on_identical_evidence_set
    """
    _system, line = _records_basis_line(api)

    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.VISUAL_INSPECTION,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-07-11T00:00:00Z",
    )

    after = fixtures.read_service_line(api, line["id"])

    assert after["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert after["certainty_basis"] == CertaintyBasis.FIELD_BASIS
    assert after["certainty_score"] == pytest.approx(91.00)
    assert after["utility_side_material"] == Material.LEAD
    assert after["customer_side_material"] == Material.COPPER
    assert after["classification"] == Classification.LEAD
    assert after["replacement_priority_score"] == pytest.approx(65.00)


def test_basis_switch_leaves_the_water_system_lead_partition_unchanged(
    api: ApiClient,
) -> None:
    """The rescored line stays LEAD, so the classification counters do not move.

    PRD 3.1: "`total_service_line_count` counts every service line of the system
    with no status filter whatsoever, and `lead_count`, `grr_count`,
    `non_lead_count` and `unknown_count` count the subsets whose
    `classification` is `LEAD`, `GRR`, `NON_LEAD` and `UNKNOWN` respectively."

    Design: Difficulty/dual_variant_calc/certainty_score_records_basis_versus_field_basis_on_identical_evidence_set
    """
    system, line = _records_basis_line(api)

    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.VISUAL_INSPECTION,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-07-11T00:00:00Z",
    )

    refreshed = fixtures.read_water_system(api, system["id"])

    assert refreshed["lead_count"] == 1
    assert refreshed["unknown_count"] == 0
    assert refreshed["total_service_line_count"] == 1


# ---------------------------------------------------------------------------
# funding_apportionment_waterfall_share_caps_versus_pro_rata_remainder
# ---------------------------------------------------------------------------


def _three_source_pool(api: ApiClient):
    """A published system with two LEAD lines and a three source funding pool."""
    system = fixtures.create_water_system(
        api,
        "IL2031002",
        system_name="Cedar Falls Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line_one = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-9900"
    )
    line_two = fixtures.make_lead_line(
        api, system["id"], address_label="205 Oak Ave", census_tract_code="17031-9900"
    )

    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    for line_id, ppb, stamp in (
        (line_one["id"], 1.0, "2026-07-11T09:00:00Z"),
        (line_one["id"], 2.0, "2026-07-12T09:00:00Z"),
        (line_one["id"], 3.0, "2026-07-13T09:00:00Z"),
        (line_two["id"], 4.0, "2026-07-14T09:00:00Z"),
        (line_two["id"], 5.0, "2026-07-15T09:00:00Z"),
    ):
        fixtures.append_sample(
            api, batch["id"], line_id, ppb, stamp, sample_type=SampleType.FIRST_DRAW
        )
    fixtures.validate_batch(api, batch["id"])
    advanced = fixtures.advance_to_validation_pending(api, system["id"])
    publication = fixtures.draft_publication(api, system["id"], advanced["version"])
    fixtures.certify_publication(api, publication["id"])
    fixtures.publish_publication(api, publication["id"])

    source_one = fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=200000,
        priority_rank=1,
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        max_share_pct=60.0,
        equity_required_pct=0.0,
    )
    source_two = fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=300000,
        priority_rank=2,
        source_kind=SourceKind.FEDERAL_GRANT,
        max_share_pct=40.0,
        equity_required_pct=0.0,
    )
    source_three = fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=200000,
        priority_rank=3,
        source_kind=SourceKind.RATE_REVENUE,
        max_share_pct=100.0,
        equity_required_pct=0.0,
    )
    return {
        "system": system,
        "line_one": line_one,
        "line_two": line_two,
        "s1": source_one["id"],
        "s2": source_two["id"],
        "s3": source_three["id"],
    }


def _allocation_by_source(order, source_id: str):
    matches = [
        row for row in order["funding_allocations"] if row["funding_source_id"] == source_id
    ]
    return matches[0] if matches else None


def test_waterfall_apportionment_stops_once_the_share_caps_cover_the_cost(
    api: ApiClient,
) -> None:
    """Waterfall draws 60000 then 40000 and never reaches the third source.

    PRD 3.7: "Under the **waterfall** variant, the sources are filled in
    candidate order."
    PRD 3.7: "The amount allocated to that source is then the smallest of three
    quantities: the cost still remaining to be covered, the source's
    `available_cents`, and that cap."
    PRD 3.7: "when it comes out at zero the source is omitted from
    `funding_allocations` entirely."

    Design: Difficulty/dual_variant_calc/funding_apportionment_waterfall_share_caps_versus_pro_rata_remainder
    """
    pool = _three_source_pool(api)

    order = fixtures.open_order(
        api,
        pool["line_one"]["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.resolve_consent(api, order["id"])
    funded = fixtures.plan_funding(api, order["id"])

    assert funded["funding_mode_applied"] == FundingMode.WATERFALL
    assert funded["allocated_total_cents"] == 100000
    assert len(funded["funding_allocations"]) == 2
    first = _allocation_by_source(funded, pool["s1"])
    second = _allocation_by_source(funded, pool["s2"])
    assert first is not None and first["allocated_cents"] == 60000
    assert first["priority_rank"] == 1
    assert second is not None and second["allocated_cents"] == 40000
    assert second["priority_rank"] == 2
    assert _allocation_by_source(funded, pool["s3"]) is None


def test_pro_rata_apportionment_spreads_across_every_source_and_ignores_share_caps(
    api: ApiClient,
) -> None:
    """Pro rata produces three rows summing to the cost, with the odd cent on rank 1.

    PRD 3.7: "Otherwise every candidate receives a row, in the same candidate
    order, proportional to its own share of the pool: the order total multiplied
    by that source's `available_cents`, divided by the pool."
    PRD 3.7: "Only after every per-source share has been rounded does the server
    reconcile: the difference between the order total and the sum of the rounded
    allocations is added to the first row, which is the row of the lowest
    `priority_rank` source."
    PRD 3.7: "Under pro-rata, `max_share_pct` is not applied at all."

    Design: Difficulty/dual_variant_calc/funding_apportionment_waterfall_share_caps_versus_pro_rata_remainder
    """
    pool = _three_source_pool(api)

    first_order = fixtures.open_order(
        api,
        pool["line_one"]["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.resolve_consent(api, first_order["id"])
    fixtures.plan_funding(api, first_order["id"])
    fixtures.cancel_order(api, first_order["id"], "REBID_UNDER_PRO_RATA_POLICY")
    fixtures.patch_funding_policy(api, pool["system"]["id"], FundingMode.PRO_RATA)

    second_order = fixtures.open_order(
        api,
        pool["line_two"]["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-12",
        excavation_end_date="2026-08-13",
    )
    fixtures.resolve_consent(api, second_order["id"])
    funded = fixtures.plan_funding(api, second_order["id"])

    assert funded["funding_mode_applied"] == FundingMode.PRO_RATA
    assert len(funded["funding_allocations"]) == 3
    assert _allocation_by_source(funded, pool["s1"])["allocated_cents"] == 28572
    assert _allocation_by_source(funded, pool["s2"])["allocated_cents"] == 42857
    assert _allocation_by_source(funded, pool["s3"])["allocated_cents"] == 28571
    assert funded["allocated_total_cents"] == 100000
    assert funded["fulfillment_state"] == FulfillmentState.FUNDED


def test_cancelling_the_waterfall_order_restores_the_pool_before_pro_rata_runs(
    api: ApiClient,
) -> None:
    """The cancelled order releases every cent, so pro rata sees the full ledgers again.

    PRD 3.7: "every row of `funding_allocations` flips from `COMMITTED` to
    `RELEASED`; each referenced source's `committed_cents` decreases by that
    row's allocated amount and its `available_cents` is re-derived as
    `authorized_cents` less `committed_cents` less `drawn_cents`, which restores
    `available_cents` to exactly its pre-commit value"
    PRD 3.7: "and the order's `allocated_total_cents` is set back to 0."

    Design: Difficulty/dual_variant_calc/funding_apportionment_waterfall_share_caps_versus_pro_rata_remainder
    """
    pool = _three_source_pool(api)

    first_order = fixtures.open_order(
        api,
        pool["line_one"]["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.resolve_consent(api, first_order["id"])
    fixtures.plan_funding(api, first_order["id"])
    fixtures.cancel_order(api, first_order["id"], "REBID_UNDER_PRO_RATA_POLICY")

    cancelled = fixtures.read_order(api, first_order["id"])
    assert cancelled["fulfillment_state"] == FulfillmentState.CANCELLED
    assert cancelled["allocated_total_cents"] == 0
    assert cancelled["funding_allocations"] != []
    assert all(
        row["state"] == AllocationState.RELEASED
        for row in cancelled["funding_allocations"]
    )

    fixtures.patch_funding_policy(api, pool["system"]["id"], FundingMode.PRO_RATA)
    second_order = fixtures.open_order(
        api,
        pool["line_two"]["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-12",
        excavation_end_date="2026-08-13",
    )
    fixtures.resolve_consent(api, second_order["id"])
    fixtures.plan_funding(api, second_order["id"])

    source_one = fixtures.read_funding_source(api, pool["s1"])
    source_two = fixtures.read_funding_source(api, pool["s2"])
    source_three = fixtures.read_funding_source(api, pool["s3"])
    assert source_one["committed_cents"] == 28572
    assert source_one["available_cents"] == 171428
    assert source_two["committed_cents"] == 42857
    assert source_two["available_cents"] == 257143
    assert source_three["committed_cents"] == 28571
    assert source_three["available_cents"] == 171429
