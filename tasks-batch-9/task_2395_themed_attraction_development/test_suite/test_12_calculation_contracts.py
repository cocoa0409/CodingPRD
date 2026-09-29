"""Constants, ties and weights: the arithmetic the PRD pins down to the unit."""
from test_helpers import (
    TEST_USERS,
    add_maintenance_item,
    add_prologue_and_chase,
    create_queue_segment_payload,
    open_project,
    place_cue,
    program_scene,
    propose_ve_item,
    read_budget_position,
    read_capacity_summary,
    read_project,
    sequence_scene,
    setup_program_at_schematic,
    validate_success,
    verify_cue,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]

TIE_ITEM = {
    "title": "Swap practical fog for media haze",
    "gross_saving_cents": 70000022,
    "rework_loss_pct": 75,
    "implementation_cost_cents": 1000000,
    "capacity_impact_guests_per_hour": 0,
    "scope_impact_delta_cents": -69000022,
}


def test_one_footprint_sizes_three_ways_on_the_routing_class_area(api):
    """The routing class also selects the per-guest area used to size the segment. A `STANDARD` run allows sixty-five hundredths of a square metre per guest; an `ACCESSIBLE` run allows one and a half square metres per guest, reflecting wheelchair turning space; a `VIRTUAL_RETURN` run allows ninety hundredths of a square metre per guest. A segment's `capacity_guests` is its `length_meters` multiplied by its `width_meters`, divided by the per-guest area for its routing class, and rounded down to a whole guest; the area is carried as an exact decimal.

    Segments are created `PROPOSED` and their capacity is not yet part of any
    programme total.

    Two hundred square metres holds 307 standard guests, 133 accessible guests or
    222 virtual-return guests: every division is inexact, so the downward rounding is
    doing visible work on all three rows.

    Design: Corner/calculations/queue_segment_capacity_applies_the_routing_class_area_constants
    """
    project = open_project(project_code="TAD-CA1")

    standard = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], segment_label="Standard Switchback",
                                         length_meters=100, width_meters=2.0,
                                         routing_type="STANDARD", position_index=1),
            DESIGNER,
        ),
        201,
    )
    accessible = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], segment_label="Accessible Bypass",
                                         length_meters=100, width_meters=2.0,
                                         routing_type="ACCESSIBLE", position_index=2),
            DESIGNER,
        ),
        201,
    )
    virtual = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], segment_label="Virtual Return Lane",
                                         length_meters=100, width_meters=2.0,
                                         routing_type="VIRTUAL_RETURN", position_index=3),
            DESIGNER,
        ),
        201,
    )

    assert standard["capacity_guests"] == 307
    assert accessible["capacity_guests"] == 133
    assert virtual["capacity_guests"] == 222
    assert standard["status"] == "PROPOSED"
    assert accessible["status"] == "PROPOSED"
    assert virtual["status"] == "PROPOSED"
    assert read_project(project["id"])["queue_capacity_total_guests"] == 0


def test_a_half_cent_tie_in_the_retained_saving_rounds_upward(api):
    """Opening the ballot fixes the item's net saving: the retained saving is `gross_saving_cents` multiplied by one minus `rework_loss_pct` divided by one hundred, and `net_saving_cents` is that retained saving rounded half up to whole cents *first* and then reduced by `implementation_cost_cents`.

    The item is created `PROPOSED` with `net_saving_cents` null, `ballot_count` 0 and
    `veto_present` false.

    Across the programme, `ve_program_net_savings_cents` is the sum of
    `net_saving_cents` over items whose `status` is `ADOPTED`, and that sum is never
    re-rounded.

    A gross saving of 70000022 retains exactly 17500005.5 cents — a perfect
    half-cent tie — which resolves upward to 17500006 and leaves 16500006 net of the
    implementation cost, one cent above what a nearest-even rule would report; the
    programme's own savings line stays at zero until an item is adopted.

    Design: Corner/calculations/ve_item_net_saving_rounds_a_half_cent_tie_upward
    """
    ctx = setup_program_at_schematic(project_overrides={"project_code": "TAD-CA2"})
    item = propose_ve_item(ctx["project"]["id"], **TIE_ITEM)
    assert item["net_saving_cents"] is None

    under_review = validate_success(
        api.open_value_engineering_review(item["id"], {}, OWNER))

    assert under_review["net_saving_cents"] == 16500006
    assert under_review["net_saving_cents"] != 16500005
    assert under_review["status"] == "UNDER_REVIEW"
    assert read_budget_position(ctx["project"]["id"])["ve_program_net_savings_cents"] == 0


def test_the_stocking_recommendation_takes_the_multiplier_then_the_floor(api):
    """Criticality drives the stocking recommendation two ways at once. It selects a multiplier — two for `SHOW_CRITICAL`, one and a half for `RUN_CRITICAL`, one for `NON_CRITICAL` — and it also selects an absolute floor of units to keep on the shelf regardless of consumption: two for `SHOW_CRITICAL`, one for `RUN_CRITICAL`, and none for `NON_CRITICAL`.

    Lead-time demand is `annual_consumption_rate` multiplied by `lead_time_days`,
    divided by 365 days in the operating year, and then multiplied by the criticality
    multiplier.

    `recommended_stock_qty` is the larger of the criticality floor and that lead-time
    demand rounded up to a whole unit; because the rounding up is applied once to the
    exact decimal, a demand of exactly four units stays four rather than gaining a
    phantom fifth, and a zero consumption rate on a `NON_CRITICAL` part yields
    exactly zero.

    The item is created `DRAFT` with `stocked_qty` null.

    At an identical hundred-day lead time, a show-critical part consuming 7.3 units a
    year demands exactly four and stays at four; one consuming a single unit a year
    demands barely half a unit and is lifted to the floor of two; and a non-critical
    part consuming 16.5 a year demands 4.5205 and is rounded up to five with no floor
    to help it.

    Design: Corner/calculations/spare_stock_recommendation_applies_criticality_multiplier_and_floor
    """
    project = open_project(project_code="TAD-CA3")

    exact = add_maintenance_item(
        project["id"], part_number="PN-EXACT-400",
        description="Trackless vehicle drive belt", criticality="SHOW_CRITICAL",
        annual_consumption_rate=7.3, lead_time_days=100)
    floored = add_maintenance_item(
        project["id"], part_number="PN-FLOOR-001",
        description="Show action equipment servo card", criticality="SHOW_CRITICAL",
        annual_consumption_rate=1.0, lead_time_days=100)
    ceiled = add_maintenance_item(
        project["id"], part_number="PN-CEIL-165",
        description="Queue rail bumper pad", criticality="NON_CRITICAL",
        annual_consumption_rate=16.5, lead_time_days=100)

    assert exact["recommended_stock_qty"] == 4
    assert floored["recommended_stock_qty"] == 2
    assert ceiled["recommended_stock_qty"] == 5
    assert exact["status"] == "DRAFT"
    assert floored["status"] == "DRAFT"
    assert ceiled["status"] == "DRAFT"
    assert exact["stocked_qty"] is None


def test_the_programme_score_weights_already_rounded_scene_scores_by_duration(api):
    """The scene's `scene_quality_score` is the weighted sum of those four — the lighting score weighted at twenty-five hundredths, the audio score at twenty hundredths, the animation score at thirty hundredths and the effects score at twenty-five hundredths, weights that sum to exactly one — rounded half up to two decimal places once, at the end.

    `show_quality_score` on the programme is the duration-weighted mean of the
    already-rounded `scene_quality_score` values of every scene of that programme
    whose `status` is `PROGRAMMED` or `VALIDATED`: the sum over those scenes of each
    scene's `scene_quality_score` multiplied by its `duration_seconds`, divided by the
    sum of those same `duration_seconds`, rounded half up to two decimal places.

    A three-minute prologue scoring 88.10 beside a two-minute chase scoring 66.50
    rolls up to 79.46, not to the 77.30 a plain mean of the two would give, and the
    programme's stored score matches the summary read exactly.

    Design: Corner/calculations/project_show_quality_score_is_duration_weighted_over_rounded_scene_scores
    """
    project = open_project(project_code="TAD-CA4")
    assert float(project["show_quality_score"]) == 0.00
    prologue, chase = add_prologue_and_chase(project["id"])
    verify_cue(place_cue(prologue["id"], cue_label="Prologue Wash",
                         discipline_channel="LIGHTING", offset_ms=0,
                         duration_ms=2000)["id"])
    verify_cue(place_cue(chase["id"], cue_label="Chase Stinger",
                         discipline_channel="AUDIO", offset_ms=0,
                         duration_ms=1500)["id"])
    sequence_scene(prologue["id"], 1)
    sequence_scene(chase["id"], 2, follows_scene_id=prologue["id"])

    first = program_scene(prologue["id"], 92, 88, 85, 88)
    second = program_scene(chase["id"], 70, 60, 65, 70)

    summary = read_capacity_summary(project["id"])
    programme = read_project(project["id"])
    assert float(first["scene_quality_score"]) == 88.10
    assert float(second["scene_quality_score"]) == 66.50
    assert first["status"] == "PROGRAMMED"
    assert second["status"] == "PROGRAMMED"
    assert float(summary["show_quality_score"]) == 79.46
    assert float(programme["show_quality_score"]) == 79.46
