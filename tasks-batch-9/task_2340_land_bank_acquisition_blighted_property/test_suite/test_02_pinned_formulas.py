"""
Pinned multi-term calculations of the County Land Bank Authority API.

Three figures are computed from several interacting terms with their evaluation
order fixed by the specification: the maintenance-order estimate, whose line
items round before the county overhead does; the demolition-run allocation,
whose administrative fee is a function of the very subtotal that has to fit
inside the budget net of that fee; and the blight priority score, whose capped
terms and final ceiling all bind at once.
"""

from test_helpers import factories, fixtures, validate_paginated, validate_success
from test_helpers.assertions import assert_ledger_position, assert_score
from test_helpers.test_users import INTAKE_1, INV_1, TREAS_1

# ─── the 7,778 sqft grade F parcel the demolition estimate is read from ──────
CEDAR_ROAD_PARCEL = {
    "address": "20 Cedar Rd",
    "situs_ward": 4,
    "lot_area_sqft": 7778,
    "assessed_value_cents": 300000,
    "structure_present": True,
    "structure_condition_grade": "F",
    "vacancy_months": 6,
}

# ─── the grade F target and its two inventory neighbours on Elm Street ───────
ELM_STREET_NEIGHBOUR = {
    "situs_ward": 6,
    "structure_present": False,
    "structure_condition_grade": "C",
    "vacancy_months": 3,
}

ELM_STREET_TARGET = {
    "address": "43 Elm St",
    "situs_ward": 6,
    "lot_area_sqft": 6000,
    "assessed_value_cents": 140000,
    "structure_present": True,
    "structure_condition_grade": "F",
    "vacancy_months": 84,
}


def _cedar_road_demolition_setup(api):
    """
    An ACQUIRED 7,778 sqft grade F parcel taken in with a zero title search fee
    against an unrestricted 5,000,000-cent grant, plus a licensed demolition
    contractor. Nothing has been disbursed or committed against the grant.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Demolition Block Grant",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides=dict(CEDAR_ROAD_PARCEL),
        packet_overrides={
            "title_search_fee_cents": 0,
            "donor_name": "Cedar Road Estate",
        },
    )
    contractor = fixtures.create_contractor(
        api,
        name="Ironclad Demolition",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=2,
        specialties=["DEMOLITION", "SECURE"],
        debarred=False,
    )
    bundle["contractor"] = contractor
    return bundle


def _schedule_cedar_road_demolition(api, bundle):
    """Schedule the demolition order whose estimate is the figure under test."""
    property_id = bundle["property"]["id"]
    payload = factories.maintenance_order_payload(
        bundle["contractor"]["id"],
        bundle["funding_source"]["id"],
        fixtures.property_version(api, property_id),
        work_type="DEMOLITION",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    return validate_success(
        api.create_maintenance_order(property_id, payload, INV_1), 201
    )


def _dell_street_run_setup(api):
    """
    Three ACQUIRED, CLEAR-title parcels carrying structures, funded by an
    acquisition-only line, plus a separate demolition-only source authorized for
    5,000,000 cents against which the run is planned.

    P1 scores 47.0 (estimate 1,427,611), P2 scores 46.0 (estimate 1,973,019) and
    P3 scores 54.0 (estimate 2,332,350) at the starting clock, where every
    holding term is still zero.
    """
    acquisition_source = fixtures.create_funding_source(
        api,
        name="Acquisition Line",
        source_type="GENERAL_FUND",
        authorized_cents=1000000,
        restriction="ACQUISITION_ONLY",
    )
    demolition_source = fixtures.create_funding_source(
        api,
        name="Hardest Hit Demolition Fund",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="DEMOLITION_ONLY",
    )
    p1 = fixtures.demolition_candidate(
        api,
        acquisition_source["id"],
        address="31 Dell St",
        situs_ward=5,
        lot_area_sqft=3000,
        assessed_value_cents=150000,
        structure_condition_grade="F",
        vacancy_months=12,
    )
    p2 = fixtures.demolition_candidate(
        api,
        acquisition_source["id"],
        address="32 Dell St",
        situs_ward=5,
        lot_area_sqft=10000,
        assessed_value_cents=250000,
        structure_condition_grade="D",
        vacancy_months=40,
        nuisance_complaint_count=4,
        open_code_violation_count=0,
    )
    p3 = fixtures.demolition_candidate(
        api,
        acquisition_source["id"],
        address="33 Dell St",
        situs_ward=5,
        lot_area_sqft=20000,
        assessed_value_cents=350000,
        structure_condition_grade="C",
        vacancy_months=72,
        nuisance_complaint_count=8,
        open_code_violation_count=3,
    )
    return {
        "acquisition_source": acquisition_source,
        "demolition_source": demolition_source,
        "p1": p1,
        "p2": p2,
        "p3": p3,
    }


def _plan_dell_street_run(api, setup):
    """Plan the 5,000,000-cent run whose allocation is under test."""
    funding_source_id = setup["demolition_source"]["id"]
    payload = factories.demolition_run_payload(
        funding_source_id,
        5000000,
        fixtures.funding_source_version(api, funding_source_id),
    )
    return validate_success(api.create_demolition_run(payload, INV_1), 201)


def _elm_street_setup(api):
    """
    A grade F target parcel with 84 vacant months, 20 nuisance complaints, 9 open
    violations and shared-boundary edges to two neighbouring parcels already in
    the authority's hands, acquired at the starting clock.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Neighborhood Stabilization Grant",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
    )
    neighbour_one = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides=dict(
            ELM_STREET_NEIGHBOUR,
            address="41 Elm St",
            lot_area_sqft=4000,
            assessed_value_cents=120000,
        ),
        packet_overrides={
            "title_search_fee_cents": 5000,
            "donor_name": "Elm Street Trust",
        },
    )["property"]
    neighbour_two = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides=dict(
            ELM_STREET_NEIGHBOUR,
            address="42 Elm St",
            lot_area_sqft=4200,
            assessed_value_cents=130000,
        ),
        packet_overrides={
            "title_search_fee_cents": 5000,
            "donor_name": "Elm Street Trust",
        },
    )["property"]

    target = fixtures.create_property(api, **ELM_STREET_TARGET)
    fixtures.post_code_violations(
        api, target["id"], open_code_violation_count=9, nuisance_complaint_count=20
    )
    fixtures.create_adjacency(
        api, target["id"], neighbour_one["id"], shared_boundary_feet=42.5
    )
    fixtures.create_adjacency(
        api, target["id"], neighbour_two["id"], shared_boundary_feet=30
    )
    fixtures.acquire_property(
        api,
        target["id"],
        funding_source["id"],
        title_search_fee_cents=5000,
        donor_name="Elm Street Trust",
    )
    return {
        "funding_source": funding_source,
        "target": target,
        "neighbours": [neighbour_one, neighbour_two],
    }


# ─────────────────────────────────────────────────────────────────────────────
# The two-stage rounding of the maintenance-order estimate
# ─────────────────────────────────────────────────────────────────────────────
def test_demolition_estimate_rounds_line_items_before_the_county_overhead(api):
    """The demolition base, the per-square-foot charge and the asbestos surcharge are each rounded to whole cents and summed to 1,690,038 before the 6.5 percent overhead of 109,852 is rounded on that sum, giving 1,799,890 cents.

    In every case the rounded line items are then summed into a subtotal, county overhead of 6.5 percent of that subtotal is computed and rounded half up as a second, separate step, and `estimated_cost_cents` is the subtotal plus that overhead.

    Design: Difficulty/combinatorial_formula/demolition_estimate_two_stage_pinned_rounding
    """
    bundle = _cedar_road_demolition_setup(api)

    order = _schedule_cedar_road_demolition(api, bundle)

    # 950000 base + 482236 for 7778 sqft at 62 cents + 257802 asbestos on a
    # grade F structure = 1690038, plus 109852 of county overhead.
    assert order["estimated_cost_cents"] == 1799890
    assert order["work_type"] == "DEMOLITION"
    assert order["status"] == "SCHEDULED"


def test_demolition_estimate_is_not_the_single_final_rounding_figure(api):
    """Carrying the asbestos surcharge and the overhead at full precision and rounding once at the end would yield 1,799,891 cents, which is one cent more than the pinned two-stage figure the order must carry.

    Summing at full precision and rounding once at the end is not the rule and produces different cents.

    Design: Difficulty/combinatorial_formula/demolition_estimate_two_stage_pinned_rounding
    """
    bundle = _cedar_road_demolition_setup(api)

    order = _schedule_cedar_road_demolition(api, bundle)

    assert order["estimated_cost_cents"] == 1799890
    assert order["estimated_cost_cents"] != 1799891


def test_scheduling_the_demolition_commits_its_estimate_to_the_source(api):
    """Scheduling the order commits exactly its 1,799,890-cent estimate against the 5,000,000-cent grant, leaving 3,200,110 cents available and the source still ACTIVE above its 250,000-cent reserve floor.

    The funding source's `restriction` must admit the category, its `available_cents` must be at least the estimate (`ERR_FUNDING_INSUFFICIENT` otherwise), and on success the estimate is added to `committed_cents`, `available_cents` is recomputed, and the source's `status` follows the reserve-floor rules of §2.8 — including parking `DUE_DILIGENCE` packets in `ON_HOLD_FUNDING` when the commitment pushes the source below its floor.

    Design: Difficulty/combinatorial_formula/demolition_estimate_two_stage_pinned_rounding
    """
    bundle = _cedar_road_demolition_setup(api)
    _schedule_cedar_road_demolition(api, bundle)

    funding_source = validate_success(
        api.get_funding_source(bundle["funding_source"]["id"], TREAS_1)
    )

    # The donation cost nothing and its title search fee was zero, so the whole
    # commitment is the single demolition estimate.
    assert_ledger_position(
        funding_source,
        authorized_cents=5000000,
        committed_cents=1799890,
        disbursed_cents=0,
        available_cents=3200110,
        status="ACTIVE",
    )


# ─────────────────────────────────────────────────────────────────────────────
# The self-referential administrative fee of the demolition-run allocation
# ─────────────────────────────────────────────────────────────────────────────
def test_run_floors_the_provisional_cap_first_and_rounds_the_fee_last(api):
    """The run carves the administrative loading out of the 5,000,000-cent budget in advance as a floored cap of 4,651,162 cents, and only after the walk rounds the 7.5 percent fee on the 3,759,961-cent subtotal to 281,997 cents.

    Two calculations are deliberately multi-stage: the maintenance-order estimate rounds each line item to whole cents before summing them and then rounds the county overhead once against that sum, and the demolition-run allocation floors the provisional cap before selection and rounds the administrative fee after selection.

    Design: Difficulty/combinatorial_formula/demolition_run_admin_fee_circular_dependency_pinned
    """
    setup = _dell_street_run_setup(api)

    run = _plan_dell_street_run(api, setup)

    # floor(5000000 / 1.075) == 4651162, computed before any parcel is selected.
    assert run["provisional_cap_cents"] == 4651162
    # 2332350 for P3 plus 1427611 for P1.
    assert run["committed_subtotal_cents"] == 3759961
    # round_half_up(0.075 * 3759961) == 281997, evaluated after the walk.
    assert run["admin_fee_cents"] == 281997
    assert run["total_committed_cents"] == 4041958
    assert run["budget_cents"] == 5000000


def test_run_skips_the_parcel_that_does_not_fit_and_keeps_walking(api):
    """Ranked by score, P3 at 54.0 and P1 at 47.0 are selected in that order, and P2 at 46.0 is skipped because its 1,973,019-cent estimate exceeds the 891,201 cents of capacity left rather than because the walk stopped.

    The ranked candidates are then walked in order: once five parcels have been selected the run is full and every further candidate is skipped; otherwise the parcel's demolition estimate is computed exactly as in §3.5, and if that cost is no greater than the remaining capacity the parcel is selected and the cost is subtracted from the remaining capacity, while if the cost exceeds the remaining capacity the parcel is skipped and **the walk continues** — a parcel too expensive to fit does not stop cheaper, lower-ranked parcels from being taken.

    Design: Difficulty/combinatorial_formula/demolition_run_admin_fee_circular_dependency_pinned
    """
    setup = _dell_street_run_setup(api)

    run = _plan_dell_street_run(api, setup)

    assert run["selected_property_ids"] == [setup["p3"]["id"], setup["p1"]["id"]]
    assert run["skipped_property_ids"] == [setup["p2"]["id"]]
    assert run["properties_selected_count"] == 2
    assert run["skipped_property_count"] == 1


def test_planned_run_commits_nothing_and_holds_the_source_run_open(api):
    """The planned run opens in PLANNED as the first run drawn on the source, with no orders created and no money committed, while the source's open run count rises to one.

    The run opens in `PLANNED` with `orders_created_count` at zero, `dropped_property_ids` empty and `executed_at` null, takes a `run_sequence` one greater than the number of runs already drawn on that source, and increments the source's `open_run_count` and `version`.

    Design: Difficulty/combinatorial_formula/demolition_run_admin_fee_circular_dependency_pinned
    """
    setup = _dell_street_run_setup(api)

    run = _plan_dell_street_run(api, setup)

    assert run["status"] == "PLANNED"
    assert run["run_sequence"] == 1
    assert run["orders_created_count"] == 0
    assert run["dropped_property_ids"] == []
    assert run["executed_at"] is None

    funding_source = validate_success(
        api.get_funding_source(setup["demolition_source"]["id"], TREAS_1)
    )
    assert funding_source["open_run_count"] == 1
    # Only an executed run's administrative fee is an open commitment.
    assert_ledger_position(
        funding_source,
        authorized_cents=5000000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=5000000,
        status="ACTIVE",
    )


# ─────────────────────────────────────────────────────────────────────────────
# The capped terms and the final ceiling of the blight priority score
# ─────────────────────────────────────────────────────────────────────────────
def test_every_capped_blight_term_binds_at_once_in_the_intake_snapshot(api):
    """With 84 vacant months clipped to the 60-month maximum, 20 complaints clipped to 12 points and 9 violations clipped to 15 points, the grade F target's intake snapshot is exactly 96.0.

    The vacancy term is 0.25 points per month of `vacancy_months`, counting no more than 60 months — five years of vacancy is the most any parcel can claim.

    Design: Difficulty/combinatorial_formula/blight_score_nested_caps_and_ceiling
    """
    setup = _elm_street_setup(api)

    parcel = validate_success(api.get_property(setup["target"]["id"], INTAKE_1))

    # 44 for grade F + min(60, 84) * 0.25 = 15.0 + min(12, 1.5 * 20) = 12
    # + min(15, 3 * 9) = 15 + the 10-point concentration bonus.
    assert_score(parcel["intake_blight_score"], 96.0)


def test_score_ceiling_clips_the_aged_parcel_to_one_hundred(api):
    """After 24 whole 30-day months of holding, the raw terms total 108 points and the live score is clipped by the ceiling to exactly 100.0.

    The six terms are added at full precision, the sum is rounded half up to one decimal place, and the result is capped at 100 — the rounding and the cap are applied once, at the very end.

    Design: Difficulty/combinatorial_formula/blight_score_nested_caps_and_ceiling
    """
    setup = _elm_street_setup(api)
    # 2026-08-01 to 2028-08-01 is 731 days: 24 whole 30-day months of holding.
    fixtures.set_clock(api, "2028-08-01T00:00:00Z")

    parcel = validate_success(
        api.post_code_violation_report(
            setup["target"]["id"],
            {"open_code_violation_count": 9, "nuisance_complaint_count": 20},
            INTAKE_1,
        )
    )

    # 96 of capped terms + min(12, 0.5 * 24) = 12 holding points = 108 raw.
    assert_score(parcel["current_blight_score"], 100.0)
    assert parcel["current_blight_score"] < 108.0


def test_two_inventory_neighbours_earn_the_flat_concentration_bonus(api):
    """Both shared-boundary edges are readable from the target parcel, and because two neighbours are already in the authority's hands the flat 10-point bonus is inside the target's 96.0 intake snapshot.

    The concentration bonus reads the adjacency graph symmetrically — an edge counts whichever endpoint the parcel occupies — and counts the distinct neighbouring parcels whose `custody_status` is `ACQUIRED`, `LISTED` or `REVERTED`, excluding neighbours that are merely `PROSPECT` or already `CONVEYED`; when at least two such neighbours are already in the land bank's hands, a flat 10-point bonus applies, and otherwise the bonus is zero.

    Design: Difficulty/combinatorial_formula/blight_score_nested_caps_and_ceiling
    """
    setup = _elm_street_setup(api)

    edges, meta = validate_paginated(
        api.list_adjacencies(setup["target"]["id"], INTAKE_1)
    )

    assert meta["total_count"] == 2
    assert len(edges) == 2
    neighbour_ids = {parcel["id"] for parcel in setup["neighbours"]}
    for edge in edges:
        endpoints = {edge["property_id"], edge["adjacent_property_id"]}
        assert setup["target"]["id"] in endpoints
        assert endpoints & neighbour_ids

    parcel = validate_success(api.get_property(setup["target"]["id"], INV_1))
    # 44 + 15.0 + 12 + 15 of parcel terms leaves the 10-point bonus as the
    # difference up to 96.0.
    assert_score(parcel["intake_blight_score"], 96.0)
