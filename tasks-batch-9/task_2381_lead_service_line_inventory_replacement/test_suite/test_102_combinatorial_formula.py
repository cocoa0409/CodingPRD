"""Queue A - rule ``combinatorial_formula``.

Two multi-input formulas whose step order is normative: the eleven-step
replacement priority score, and the six-step compliance credit picture.
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    Classification,
    ComplianceStatus,
    ConsentBarrierReason,
    ConsentOutcome,
    ConsentState,
    EquityTier,
    FulfillmentState,
    FundingMode,
    InventoryStatus,
    Material,
    OrderScope,
    ProgramPosture,
    PublicationBasis,
    ReplacementState,
    SampleType,
    Side,
    SourceKind,
    SourceType,
)


# ---------------------------------------------------------------------------
# replacement_priority_cap_applies_before_barrier_penalty_and_equity_floor
# ---------------------------------------------------------------------------


def _capped_priority_line(api: ApiClient):
    """A verified, disadvantaged, sensitive LEAD line whose raw priority is 120.00."""
    system = fixtures.create_water_system(
        api,
        "IL2031003",
        system_name="Harbor Point Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=["17031-8402"],
        funding_mode=FundingMode.WATERFALL,
    )
    project = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm St Resurfacing",
        moratorium_start_date="2026-12-01",
        moratorium_end_date="2026-12-31",
        paving_start_date="2026-09-30",
        max_concurrent_excavations=1,
    )
    line = fixtures.create_service_line(
        api,
        system["id"],
        address_label="101 Elm St",
        census_tract_code="17031-8402",
        street_project_id=project["id"],
        serves_sensitive_population=True,
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-07-10T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.VISUAL_INSPECTION,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-07-11T00:00:00Z",
    )
    fixtures.publish_inventory(
        api,
        system["id"],
        line["id"],
        basis=PublicationBasis.FIELD_VERIFIED,
        reporting_period_label="2026-H2",
    )
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
        street_project_id=project["id"],
    )
    return {"system": system, "project": project, "line": line, "order": order}


def test_raw_priority_total_above_one_hundred_is_clamped_to_one_hundred(
    api: ApiClient,
) -> None:
    """50 + 15 + 25 + 20 + 10 sums to 120.00 raw and is stored as 100.00.

    PRD 3.6: "The sixth step sums the five contributions into a raw total. The
    seventh caps that total, taking the lower of 100.00 and the raw figure, and
    separately never letting it fall below 0.00."
    PRD 3.6: "Otherwise: 20.00 points when paving starts within three months,
    meaning ninety days or fewer; 12.00 points when it starts within a hundred
    and eighty days; 5.00 points when it starts within a full year, meaning three
    hundred and sixty-five days; and 0.00 beyond that."
    PRD 3.6: "The fifth step adds 10.00 points when `serves_sensitive_population`
    is true."

    Design: Difficulty/combinatorial_formula/replacement_priority_cap_applies_before_barrier_penalty_and_equity_floor
    """
    scenario = _capped_priority_line(api)

    line = fixtures.read_service_line(api, scenario["line"]["id"])

    assert line["classification"] == Classification.LEAD
    assert line["certainty_score"] == pytest.approx(91.00)
    assert line["replacement_priority_score"] == pytest.approx(100.00)


def test_barrier_penalty_lands_after_the_cap_and_the_equity_floor_lands_last(
    api: ApiClient,
) -> None:
    """A no-response canvass drops the capped 100.00 to 92.00, not 100.00 or 112.00.

    PRD 3.6: "The eighth step computes a barrier penalty of 8.00 points when the
    line's `consent_barrier_flag` is true and 0.00 otherwise; the ninth subtracts
    that penalty from the capped total and rounds half-up to two decimals."
    PRD 3.6: "The eleventh and last step takes the greater of the penalized
    figure and the floor, rounded half-up to two decimals, and stores it as
    `replacement_priority_score`."
    PRD 3.6: "Because the cap is applied before the penalty and the floor after
    it, a disadvantaged galvanized line with no paving coordination and no
    sensitive population — 35.00 plus 25.00, or 60.00 raw — is lifted by the
    floor to 65.00 whether or not it carries a consent barrier."

    Design: Difficulty/combinatorial_formula/replacement_priority_cap_applies_before_barrier_penalty_and_equity_floor
    """
    scenario = _capped_priority_line(api)
    fixtures.request_consent(api, scenario["order"]["id"])

    responded = fixtures.respond_consent(
        api,
        scenario["order"]["id"],
        outcome=ConsentOutcome.NO_RESPONSE,
        barrier_reason=ConsentBarrierReason.NO_CONTACT,
    )

    assert responded["fulfillment_state"] == FulfillmentState.SCOPED
    assert responded["consent_state"] == ConsentState.NO_RESPONSE
    assert responded["scope"] == OrderScope.PARTIAL
    assert responded["consent_barrier_reason"] == ConsentBarrierReason.NO_CONTACT

    line = fixtures.read_service_line(api, scenario["line"]["id"])
    assert line["consent_barrier_flag"] is True
    assert line["replacement_priority_score"] == pytest.approx(92.00)
    assert line["replacement_priority_score"] != pytest.approx(100.00)
    assert line["replacement_priority_score"] != pytest.approx(112.00)


# ---------------------------------------------------------------------------
# compliance_credit_evaluation_order_resolves_multiplier_and_deferral_dependency
# ---------------------------------------------------------------------------


def _three_completed_orders(api: ApiClient):
    """Two full replacements (one disadvantaged) and one partial, all inside August."""
    system = fixtures.create_water_system(
        api,
        "IL2031004",
        system_name="Millbrook Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=["17031-8402"],
        funding_mode=FundingMode.WATERFALL,
    )
    line_one = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-8402"
    )
    line_two = fixtures.make_lead_line(
        api, system["id"], address_label="205 Oak Ave", census_tract_code="17031-9900"
    )
    line_three = fixtures.make_lead_line(
        api, system["id"], address_label="310 Pine Rd", census_tract_code="17031-9901"
    )

    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    for line_id, ppb, stamp in (
        (line_one["id"], 1.0, "2026-07-11T09:00:00Z"),
        (line_one["id"], 2.0, "2026-07-12T09:00:00Z"),
        (line_two["id"], 3.0, "2026-07-13T09:00:00Z"),
        (line_two["id"], 4.0, "2026-07-14T09:00:00Z"),
        (line_three["id"], 5.0, "2026-07-15T09:00:00Z"),
    ):
        fixtures.append_sample(
            api, batch["id"], line_id, ppb, stamp, sample_type=SampleType.FIRST_DRAW
        )
    fixtures.validate_batch(api, batch["id"])
    advanced = fixtures.advance_to_validation_pending(api, system["id"])
    publication = fixtures.draft_publication(api, system["id"], advanced["version"])
    fixtures.certify_publication(api, publication["id"])
    fixtures.publish_publication(api, publication["id"])

    for line_id, stamp in (
        (line_one["id"], "2026-08-02T09:00:00Z"),
        (line_two["id"], "2026-08-02T09:05:00Z"),
        (line_three["id"], "2026-08-02T09:10:00Z"),
    ):
        fixtures.deliver_notification_for_line(api, line_id, delivered_at=stamp)

    fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=1000000,
        priority_rank=1,
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        max_share_pct=100.0,
        equity_required_pct=0.0,
    )

    order_a = fixtures.open_order(
        api,
        line_one["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.resolve_consent(api, order_a["id"], outcome=ConsentOutcome.GRANTED)
    fixtures.plan_funding(api, order_a["id"])

    order_b = fixtures.open_order(
        api,
        line_two["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-12",
        excavation_end_date="2026-08-13",
    )
    fixtures.resolve_consent(api, order_b["id"], outcome=ConsentOutcome.GRANTED)
    fixtures.plan_funding(api, order_b["id"])

    order_c = fixtures.open_order(
        api,
        line_three["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-14",
        excavation_end_date="2026-08-15",
    )
    fixtures.resolve_consent(
        api,
        order_c["id"],
        outcome=ConsentOutcome.DENIED,
        barrier_reason=ConsentBarrierReason.COST,
    )
    fixtures.plan_funding(api, order_c["id"])

    fixtures.schedule_order(api, order_a["id"], "2026-08-10", "2026-08-11")
    fixtures.schedule_order(api, order_b["id"], "2026-08-12", "2026-08-13")
    fixtures.schedule_order(api, order_c["id"], "2026-08-14", "2026-08-15")
    fixtures.start_order(api, order_a["id"])
    fixtures.start_order(api, order_b["id"])
    fixtures.start_order(api, order_c["id"])

    fixtures.set_clock(api, "2026-08-15T12:00:00Z")
    fixtures.complete_order(
        api, order_a["id"], "2026-08-15T12:00:00Z", [Side.UTILITY, Side.CUSTOMER]
    )
    fixtures.set_clock(api, "2026-08-16T12:00:00Z")
    fixtures.complete_order(
        api, order_b["id"], "2026-08-16T12:00:00Z", [Side.UTILITY, Side.CUSTOMER]
    )
    fixtures.set_clock(api, "2026-08-17T12:00:00Z")
    fixtures.complete_order(api, order_c["id"], "2026-08-17T12:00:00Z", [Side.UTILITY])
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    return {
        "system": system,
        "line_one": line_one,
        "line_two": line_two,
        "line_three": line_three,
        "order_a": order_a,
        "order_b": order_b,
        "order_c": order_c,
    }


def test_equity_tier_keys_on_share_while_deferral_keys_on_step_three_total_credit(
    api: ApiClient,
) -> None:
    """A 50.00 share gives TIER_B and a 2.75 total gives allowance 1, so shortfall is 6.25.

    PRD 3.8: "the `equity_tier` and its `equity_multiplier` are keyed on that
    share **and on nothing else** — never on `base_credit` and never on
    `total_credit`."
    PRD 3.8: "The fifth step reads `deferral_allowance` off the `total_credit`
    computed in step three: 3 when `total_credit` is at least 20, 2 when it is at
    least 10, and 1 otherwise."
    PRD 3.8: "The sixth step computes `shortfall_credit` as the mandated annual
    credit less the deferral allowance less the total credit, clamped at zero so
    it never goes negative, rounded half-up to two decimals, and sets
    `compliance_status` to `ON_TRACK` when `shortfall_credit` is exactly zero and
    `BEHIND` otherwise."

    Design: Difficulty/combinatorial_formula/compliance_credit_evaluation_order_resolves_multiplier_and_deferral_dependency
    """
    scenario = _three_completed_orders(api)

    report = fixtures.create_progress_report(
        api, scenario["system"]["id"], "2026-08-01", "2026-08-31"
    )

    assert report["full_replacement_count"] == 2
    assert report["partial_replacement_count"] == 1
    assert report["disadvantaged_full_count"] == 1
    assert report["base_credit"] == pytest.approx(2.50)
    assert report["disadvantaged_share_pct"] == pytest.approx(50.00)
    assert report["equity_tier"] == EquityTier.TIER_B
    assert report["equity_multiplier"] == pytest.approx(1.10)
    assert report["total_credit"] == pytest.approx(2.75)
    assert report["mandated_annual_credit"] == 10
    assert report["deferral_allowance"] == 1
    assert report["shortfall_credit"] == pytest.approx(6.25)
    assert report["shortfall_credit"] != pytest.approx(5.25)
    assert report["compliance_status"] == ComplianceStatus.BEHIND


def test_physical_progress_measure_counts_the_whole_inventory_not_the_period(
    api: ApiClient,
) -> None:
    """Three replaced lines over a denominator of four give 75.00 per cent.

    PRD 3.8: "`replaced_count` is the number of service lines of the water system
    whose `replacement_state` is `REPLACED_FULL` or `REPLACED_PARTIAL`."
    PRD 3.8: "`baseline_denominator` is the sum of the water system's
    `lead_count`, `grr_count` and `unknown_count` plus that replaced count, so
    that non-lead lines which were never replaced contribute to neither the
    numerator nor the denominator."
    PRD 3.7: "a partial replacement lands it on the utility side only, so the
    customer side keeps whatever previously governed it, the line stays
    `CLASSIFIED_PROVISIONAL` on `RECORDS_BASIS`, and its `classification` does
    not move off `LEAD`, `GRR` or `UNKNOWN`."

    Design: Difficulty/combinatorial_formula/compliance_credit_evaluation_order_resolves_multiplier_and_deferral_dependency
    """
    scenario = _three_completed_orders(api)

    report = fixtures.create_progress_report(
        api, scenario["system"]["id"], "2026-08-01", "2026-08-31"
    )

    assert report["replaced_count"] == 3
    assert report["baseline_denominator"] == 4
    assert report["replacement_progress_pct"] == pytest.approx(75.00)

    full_line = fixtures.read_service_line(api, scenario["line_one"]["id"])
    partial_line = fixtures.read_service_line(api, scenario["line_three"]["id"])
    assert full_line["replacement_state"] == ReplacementState.REPLACED_FULL
    assert full_line["classification"] == Classification.NON_LEAD
    assert partial_line["replacement_state"] == ReplacementState.REPLACED_PARTIAL
    assert partial_line["classification"] == Classification.LEAD


def test_flushing_guidance_adds_the_partial_penalty_only_on_the_partial_order(
    api: ApiClient,
) -> None:
    """The full order stores 31 minutes and the partial order stores 46.

    PRD 3.7: "Fourth, a partial replacement adds a fifteen-minute penalty, a full
    replacement adds nothing."
    PRD 3.7: "Sixth and last, the stored value is a base half-hour of 30 minutes
    plus the volume minutes plus the partial penalty, that whole sum multiplied by
    the corrosion-control multiplier, and the product rounded up to a whole
    minute."
    PRD 2.8: "And only then — if the water system's `inventory_status` was
    `PUBLISHED` and the recompute actually changed at least one service line's
    `classification` to a different value than it held before — does the water
    system move to `AMENDMENT_PENDING`, which by clause 3 of §2.7 forces the
    posture to `RESTRICTED`."

    Design: Difficulty/combinatorial_formula/compliance_credit_evaluation_order_resolves_multiplier_and_deferral_dependency
    """
    scenario = _three_completed_orders(api)

    full_order = fixtures.read_order(api, scenario["order_a"]["id"])
    partial_order = fixtures.read_order(api, scenario["order_c"]["id"])
    assert full_order["flushing_duration_minutes"] == 31
    assert partial_order["flushing_duration_minutes"] == 46

    system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert system["inventory_status"] == InventoryStatus.AMENDMENT_PENDING
    assert system["program_posture"] == ProgramPosture.RESTRICTED
