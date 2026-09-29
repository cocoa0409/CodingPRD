"""Queue B - corner section ``calculations``.

The derived-value surface: governing-evidence ranking, the four-rung
classification ladder, the confidence-weight constants, the nearest-rank
percentile with its four-decimal confidence, the invalidation filter, the
coordination tiers, the equity floor and the flushing multiplier.
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    BatchState,
    CctOptimizationStatus,
    CertaintyBasis,
    Classification,
    ConsentBarrierReason,
    ConsentOutcome,
    FulfillmentState,
    InventoryState,
    Material,
    OrderScope,
    ReplacementState,
    SampleType,
    Side,
    SourceKind,
    SourceType,
)

_SIX_INSTANTS = (
    "2026-07-11T09:00:00Z",
    "2026-07-12T09:00:00Z",
    "2026-07-13T09:00:00Z",
    "2026-07-14T09:00:00Z",
    "2026-07-15T09:00:00Z",
    "2026-07-16T09:00:00Z",
)
_SIX_KINDS = (
    SampleType.FIRST_DRAW,
    SampleType.FIRST_DRAW,
    SampleType.FIRST_DRAW,
    SampleType.FIFTH_LITER,
    SampleType.FIFTH_LITER,
    SampleType.FIRST_DRAW,
)


def test_governing_evidence_tie_break_uses_observed_at_not_creation_order(
    api: ApiClient,
) -> None:
    """Two POTHOLE items tie on tier 5, so the later observation wins over the later row.

    PRD 3.2: "Then a ranking: the pool is ordered by `tier_rank` descending, so the
    highest tier wins; ties on tier are broken by `observed_at` descending, so the
    most recent observation wins; ties on both are broken by `created_at` descending,
    so the most recently recorded row wins."
    PRD 3.2: "An evidence item's `id` is never a ranking or tie-break input."
    PRD 3.2: "`utility_side_material` becomes the `observed_material` of the governing
    utility-side item, or `UNKNOWN` when nothing governs that side"

    Design: Corner/calculations/governing_evidence_tie_break_uses_observed_at_not_creation_order
    """
    system = fixtures.create_water_system(api, "IL2102001", system_name="Tiebreak Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.COPPER,
        observed_at="2026-07-01T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-06-15T00:00:00Z",
    )

    settled = fixtures.read_service_line(api, line["id"])

    assert settled["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert settled["certainty_basis"] == CertaintyBasis.FIELD_BASIS
    assert settled["utility_side_material"] == Material.COPPER
    assert settled["customer_side_material"] == Material.COPPER
    assert settled["classification"] == Classification.NON_LEAD
    assert settled["certainty_score"] == pytest.approx(100.00)
    assert settled["replacement_state"] == ReplacementState.NOT_REQUIRED
    assert settled["replacement_priority_score"] == pytest.approx(0.00)
    parent = fixtures.read_water_system(api, system["id"])
    assert parent["non_lead_count"] == 1
    assert parent["lead_count"] == 0


def test_classification_precedence_ranks_unknown_above_non_lead(api: ApiClient) -> None:
    """Four lines walk all four rungs, and the copper-plus-nothing line lands UNKNOWN.

    PRD 3.2: "The line's `classification` is then the worst of the two sides, tested
    in a fixed order: if either side is `LEAD` the classification is `LEAD`;
    otherwise if either side is `GRR` it is `GRR`; otherwise if either side is
    `UNKNOWN` it is `UNKNOWN`; otherwise it is `NON_LEAD`. Note the third rung — an
    unknown side outranks a clean side, so a line with copper on the utility side and
    nothing at all on the customer side classifies as `UNKNOWN`, not `NON_LEAD`."
    PRD 3.6: "The first step converts material risk into points: 50.00 points for a
    `LEAD` line, 35.00 for a `GRR` line, 0.00 for a `NON_LEAD` line, and for an
    `UNKNOWN` line a sliding figure — forty multiplied by the quantity one minus one
    hundredth of the line's `certainty_score`, rounded half-up to two decimals"
    PRD 3.1: "`unknown_share_pct` is 0.00 when the system has no service lines at
    all; otherwise it is one hundred times the unknown count divided by the total
    count, rounded half-up to two decimals."

    Design: Corner/calculations/classification_precedence_ranks_unknown_above_non_lead
    """
    system = fixtures.create_water_system(api, "IL2102002", system_name="Ladder Water")

    lead_line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    fixtures.add_evidence(
        api, lead_line["id"], side=Side.UTILITY, observed_material=Material.LEAD
    )
    fixtures.add_evidence(
        api, lead_line["id"], side=Side.CUSTOMER, observed_material=Material.COPPER
    )

    grr_line = fixtures.create_service_line(api, system["id"], address_label="102 Elm St")
    fixtures.add_evidence(
        api, grr_line["id"], side=Side.UTILITY, observed_material=Material.GRR
    )
    fixtures.add_evidence(
        api, grr_line["id"], side=Side.CUSTOMER, observed_material=Material.COPPER
    )

    unknown_line = fixtures.create_service_line(api, system["id"], address_label="103 Elm St")
    fixtures.add_evidence(
        api, unknown_line["id"], side=Side.UTILITY, observed_material=Material.COPPER
    )

    clean_line = fixtures.create_service_line(api, system["id"], address_label="104 Elm St")
    fixtures.add_evidence(
        api,
        clean_line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.COPPER,
    )
    fixtures.add_evidence(
        api,
        clean_line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
    )

    lead_row = fixtures.read_service_line(api, lead_line["id"])
    assert lead_row["classification"] == Classification.LEAD
    assert lead_row["certainty_score"] == pytest.approx(40.00)
    assert lead_row["replacement_priority_score"] == pytest.approx(50.00)

    grr_row = fixtures.read_service_line(api, grr_line["id"])
    assert grr_row["classification"] == Classification.GRR
    assert grr_row["certainty_score"] == pytest.approx(40.00)
    assert grr_row["replacement_priority_score"] == pytest.approx(35.00)

    unknown_row = fixtures.read_service_line(api, unknown_line["id"])
    assert unknown_row["utility_side_material"] == Material.COPPER
    assert unknown_row["customer_side_material"] == Material.UNKNOWN
    assert unknown_row["classification"] == Classification.UNKNOWN
    assert unknown_row["certainty_score"] == pytest.approx(16.00)
    assert unknown_row["replacement_priority_score"] == pytest.approx(33.60)

    clean_row = fixtures.read_service_line(api, clean_line["id"])
    assert clean_row["classification"] == Classification.NON_LEAD
    assert clean_row["certainty_score"] == pytest.approx(100.00)
    assert clean_row["replacement_priority_score"] == pytest.approx(0.00)

    parent = fixtures.read_water_system(api, system["id"])
    assert parent["lead_count"] == 1
    assert parent["grr_count"] == 1
    assert parent["unknown_count"] == 1
    assert parent["non_lead_count"] == 1
    assert parent["total_service_line_count"] == 4
    assert parent["unknown_share_pct"] == pytest.approx(25.00)


def test_predictive_model_weight_constants_yield_a_fifty_five_point_score(
    api: ApiClient,
) -> None:
    """Both sides on 0.55 collapse the uneven weighting back onto the constant itself.

    PRD 3.2: "Its `confidence_weight` is 0.40 for `HISTORIC_RECORD`, 0.55 for
    `PREDICTIVE_MODEL`, 0.70 for `WATER_SAMPLING`, 0.85 for `VISUAL_INSPECTION` and
    1.00 for `POTHOLE`."
    PRD 3.2: "The score then weights the two contributions unevenly, deliberately
    favouring the weaker side: one hundred multiplied by the sum of six tenths of the
    lower of the two side figures and four tenths of the higher of the two, rounded
    half-up to two decimal places."
    PRD 3.2: "Under `RECORDS_BASIS` only `HISTORIC_RECORD` and `PREDICTIVE_MODEL` are
    admissible; under `FIELD_BASIS` all five source types are."

    Design: Corner/calculations/predictive_model_weight_constants_yield_a_fifty_five_point_score
    """
    system = fixtures.create_water_system(api, "IL2102003", system_name="Predict Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")

    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.PREDICTIVE_MODEL,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.PREDICTIVE_MODEL,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
    )

    settled = fixtures.read_service_line(api, line["id"])
    assert settled["inventory_state"] == InventoryState.CLASSIFIED_PROVISIONAL
    assert settled["certainty_basis"] == CertaintyBasis.RECORDS_BASIS
    assert settled["certainty_score"] == pytest.approx(55.00)
    assert settled["classification"] == Classification.LEAD
    assert settled["replacement_priority_score"] == pytest.approx(50.00)
    assert settled["replacement_state"] == ReplacementState.ELIGIBLE


def test_sampling_confidence_is_rounded_to_four_decimals_and_flips_corrosion_control(
    api: ApiClient,
) -> None:
    """One exceedance in six gives 0.8333, which clears the floor and re-opens optimization.

    PRD 3.4: "And `classification_confidence` is one minus the exceedance count
    divided by the valid-sample count, rounded half-up to four decimal places."
    PRD 3.4: "the ninetieth-percentile rank is computed by the one-based nearest-rank
    method: nine tenths of the valid-sample count, rounded up to a whole number."
    PRD 3.4: "When `classification_confidence` is at least 0.8000 — exactly 0.8000
    validates — the batch moves from `OPEN` to `VALIDATED`. On that branch alone, and
    on that branch only when `exceedance` came out true, a second link fires: the
    parent water system's `cct_optimization_status` moves to
    `PENDING_REOPTIMIZATION`."

    Design: Corner/calculations/sampling_confidence_is_rounded_to_four_decimals_and_flips_corrosion_control
    """
    system = fixtures.create_water_system(api, "IL2102004", system_name="Precision Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    fixtures.append_samples(
        api,
        batch["id"],
        line["id"],
        readings=(1.0, 2.0, 3.0, 4.0, 5.0, 16.0),
        instants=_SIX_INSTANTS,
        sample_types=_SIX_KINDS,
    )

    validated = fixtures.validate_batch(api, batch["id"])

    assert validated["required_sample_count"] == 5
    assert validated["valid_sample_count"] == 6
    assert validated["percentile_90_ppb"] == pytest.approx(16.0)
    assert validated["exceedance"] is True
    assert validated["exceedance_count"] == 1
    assert validated["classification_confidence"] == pytest.approx(0.8333)
    assert validated["state"] == BatchState.VALIDATED
    assert validated["rejection_reason"] is None
    assert (
        fixtures.read_water_system(api, system["id"])["cct_optimization_status"]
        == CctOptimizationStatus.PENDING_REOPTIMIZATION
    )


def test_invalidated_samples_leave_the_statistical_population(api: ApiClient) -> None:
    """Voiding the single high reading shrinks n, moves the rank and clears the exceedance.

    PRD 3.4: "Only entries with `invalidated` false participate — invalidated samples
    are excluded from the population count, from the percentile rank and from the
    exceedance tally alike."
    PRD 3.4: "A `ComplianceOfficer` may later void a sample by naming its
    `sample_seq` and a `reason`; the server sets that entry's `invalidated` to true,
    stores the reason as its `invalidation_reason`, refreshes `valid_sample_count`
    and advances `version`."
    PRD 3.4: "The rejected branch carries **no** corrosion-control side effect
    whatsoever"

    Design: Corner/calculations/invalidated_samples_leave_the_statistical_population
    """
    system = fixtures.create_water_system(api, "IL2102005", system_name="Filter Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    fixtures.append_samples(
        api,
        batch["id"],
        line["id"],
        readings=(1.0, 2.0, 3.0, 4.0, 5.0, 16.0),
        instants=_SIX_INSTANTS,
        sample_types=_SIX_KINDS,
    )

    voided = fixtures.invalidate_sample(api, batch["id"], 6, "HOLDING_TIME_EXCEEDED")

    assert voided["valid_sample_count"] == 5
    struck = [entry for entry in voided["samples"] if entry["sample_seq"] == 6]
    assert len(struck) == 1
    assert struck[0]["invalidated"] is True
    assert struck[0]["invalidation_reason"] == "HOLDING_TIME_EXCEEDED"

    validated = fixtures.validate_batch(api, batch["id"])

    assert validated["percentile_90_ppb"] == pytest.approx(5.0)
    assert validated["exceedance"] is False
    assert validated["exceedance_count"] == 0
    assert validated["classification_confidence"] == pytest.approx(1.0000)
    assert validated["state"] == BatchState.VALIDATED
    assert validated["rejection_reason"] is None
    assert (
        fixtures.read_water_system(api, system["id"])["cct_optimization_status"]
        == CctOptimizationStatus.NOT_REQUIRED
    )


def test_coordination_tier_boundary_at_ninety_and_ninety_one_days_and_past_paving(
    api: ApiClient,
) -> None:
    """Paving 90 days out earns 20.00, 91 days out earns 12.00 and past paving earns 0.00.

    PRD 3.6: "The fourth step scores coordination with paving. The server takes the
    number of whole days from the logical clock's calendar date to the
    `paving_start_date` of the line's linked street project. When the line has no
    `street_project_id`, or when that day count is negative because paving has
    already begun, coordination contributes 0.00. Otherwise: 20.00 points when paving
    starts within three months, meaning ninety days or fewer; 12.00 points when it
    starts within a hundred and eighty days; 5.00 points when it starts within a full
    year, meaning three hundred and sixty-five days; and 0.00 beyond that."
    PRD 3.6: "Registering a project immediately changes the coordination tier of every
    service line linked to it."

    Design: Corner/calculations/coordination_tier_boundary_at_ninety_and_ninety_one_days_and_past_paving
    """
    system = fixtures.create_water_system(api, "IL2102006", system_name="Coordination Water")
    ninety = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm Repave 90",
        moratorium_start_date="2026-11-01",
        moratorium_end_date="2026-11-30",
        paving_start_date="2026-10-30",
    )
    ninety_one = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm Repave 91",
        moratorium_start_date="2026-11-01",
        moratorium_end_date="2026-11-30",
        paving_start_date="2026-10-31",
    )
    already_paved = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm Repave Past",
        moratorium_start_date="2026-06-01",
        moratorium_end_date="2026-06-30",
        paving_start_date="2026-07-01",
    )

    rows = {}
    for label, project in (
        ("ninety", ninety),
        ("ninety_one", ninety_one),
        ("already_paved", already_paved),
    ):
        line = fixtures.create_service_line(
            api,
            system["id"],
            address_label=f"{label} Elm St",
            street_project_id=project["id"],
        )
        fixtures.add_evidence(
            api, line["id"], side=Side.UTILITY, observed_material=Material.LEAD
        )
        rows[label] = fixtures.read_service_line(api, line["id"])

    for row in rows.values():
        assert row["classification"] == Classification.LEAD
        assert row["certainty_score"] == pytest.approx(16.00)

    assert rows["ninety"]["replacement_priority_score"] == pytest.approx(70.00)
    assert rows["ninety_one"]["replacement_priority_score"] == pytest.approx(62.00)
    assert rows["already_paved"]["replacement_priority_score"] == pytest.approx(50.00)


def test_disadvantaged_equity_floor_lifts_a_grr_line_but_not_an_unknown_line(
    api: ApiClient,
) -> None:
    """Both lines earn the 25.00 equity points, but only the GRR line reaches the floor.

    PRD 3.6: "The third step adds 25.00 equity points when the line's
    `disadvantaged_status` is true, and nothing otherwise."
    PRD 3.6: "The tenth step establishes an equity floor of 65.00 — but only for a
    line whose `disadvantaged_status` is true **and** whose `classification` is `LEAD`
    or `GRR`; for every other line the floor is 0.00."
    PRD 3.2: "In the same pass the server sets `disadvantaged_status` to true exactly
    when the line's `census_tract_code` is a member of the parent water system's
    `disadvantaged_tract_codes` list at that moment, and false otherwise."

    Design: Corner/calculations/disadvantaged_equity_floor_lifts_a_grr_line_but_not_an_unknown_line
    """
    system = fixtures.create_water_system(
        api,
        "IL2102007",
        system_name="Equity Water",
        disadvantaged_tract_codes=["17031-0001"],
    )
    grr_line = fixtures.create_service_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-0001"
    )
    fixtures.add_evidence(
        api, grr_line["id"], side=Side.UTILITY, observed_material=Material.GRR
    )
    fixtures.add_evidence(
        api, grr_line["id"], side=Side.CUSTOMER, observed_material=Material.COPPER
    )
    unknown_line = fixtures.create_service_line(
        api, system["id"], address_label="102 Elm St", census_tract_code="17031-0001"
    )
    fixtures.add_evidence(
        api, unknown_line["id"], side=Side.UTILITY, observed_material=Material.COPPER
    )

    grr_row = fixtures.read_service_line(api, grr_line["id"])
    unknown_row = fixtures.read_service_line(api, unknown_line["id"])

    assert grr_row["disadvantaged_status"] is True
    assert unknown_row["disadvantaged_status"] is True
    assert grr_row["classification"] == Classification.GRR
    assert grr_row["replacement_priority_score"] == pytest.approx(65.00)
    assert unknown_row["classification"] == Classification.UNKNOWN
    assert unknown_row["certainty_score"] == pytest.approx(16.00)
    assert unknown_row["replacement_priority_score"] == pytest.approx(58.60)


def test_pending_reoptimization_multiplies_flushing_guidance_by_one_point_five(
    api: ApiClient,
) -> None:
    """The same 46-minute partial job becomes 69 minutes under re-optimization.

    PRD 3.7: "Fifth, the corrosion-control multiplier is one and a half when the water
    system's `cct_optimization_status` is `PENDING_REOPTIMIZATION` and exactly one
    otherwise. Sixth and last, the stored value is a base half-hour of 30 minutes plus
    the volume minutes plus the partial penalty, that whole sum multiplied by the
    corrosion-control multiplier, and the product rounded up to a whole minute."
    PRD 3.7: "Third, the volume-driven flushing time is that litre figure multiplied
    by three complete pipe turnovers, divided by a flush rate of 20.0 litres per
    minute, and rounded up to a whole minute. Fourth, a partial replacement adds a
    fifteen-minute penalty, a full replacement adds nothing."
    PRD 3.6: "The project also carries a derived `active_excavation_order_count`,
    starting at 0, counting the replacement orders linked to it whose
    `fulfillment_state` is `SCHEDULED` or `IN_PROGRESS`."

    Design: Corner/calculations/pending_reoptimization_multiplies_flushing_guidance_by_one_point_five
    """
    system = fixtures.create_water_system(api, "IL2102008", system_name="Flush Water")
    project = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm Repave",
        moratorium_start_date="2026-12-01",
        moratorium_end_date="2026-12-31",
        paving_start_date="2027-01-05",
    )
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    fixtures.publish_inventory(api, system["id"], line["id"])
    fixtures.deliver_notification_for_line(api, line["id"], delivered_at="2026-08-02T10:00:00Z")
    fixtures.create_funding_source(
        api,
        system["id"],
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        authorized_cents=200000,
        priority_rank=1,
    )
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
        street_project_id=project["id"],
    )
    fixtures.resolve_consent(
        api,
        order["id"],
        outcome=ConsentOutcome.NO_RESPONSE,
        barrier_reason=ConsentBarrierReason.NO_CONTACT,
    )
    fixtures.plan_funding(api, order["id"])
    scheduled = fixtures.schedule_order(api, order["id"], "2026-08-10", "2026-08-11")
    assert scheduled["fulfillment_state"] == FulfillmentState.SCHEDULED
    assert (
        fixtures.read_street_project(api, project["id"])["active_excavation_order_count"] == 1
    )

    fixtures.patch_corrosion_control(
        api, system["id"], cct_optimization_status=CctOptimizationStatus.PENDING_REOPTIMIZATION
    )
    started = fixtures.start_order(api, order["id"])
    assert started["fulfillment_state"] == FulfillmentState.IN_PROGRESS
    assert (
        fixtures.read_street_project(api, project["id"])["active_excavation_order_count"] == 1
    )

    fixtures.set_clock(api, "2026-08-11T16:00:00Z")
    completed = fixtures.complete_order(
        api, order["id"], "2026-08-11T16:00:00Z", [Side.UTILITY]
    )

    assert completed["scope"] == OrderScope.PARTIAL
    assert completed["flushing_duration_minutes"] == 69
    assert (
        fixtures.read_street_project(api, project["id"])["active_excavation_order_count"] == 0
    )
    assert (
        fixtures.read_service_line(api, line["id"])["replacement_state"]
        == ReplacementState.REPLACED_PARTIAL
    )
