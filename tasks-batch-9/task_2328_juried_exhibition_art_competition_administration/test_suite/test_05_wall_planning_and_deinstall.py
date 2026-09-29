"""Wall reservation: the condition block, the fifteen-centimetre buffer, span
bounds, and the deinstall that gives the centimetres back."""

from test_helpers import (
    REGISTRAR,
    ApiErrorId,
    api_client,
    assert_wall_space_conserved,
    create_installation_plan_payload,
    fixtures,
    validate_error,
)

THREE_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
    },
    {
        "title": "Second Ridge", "medium_category": "PAINTING",
        "width_cm": 80.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 5.0,
    },
    {
        "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 4.0,
    },
]

DAMAGE_NOTES = "Corner abrasion discovered on arrival."


def _three_delivered_works(damaged_index=None):
    """An `INSTALLATION`-phase show whose three accepted works are all intaken."""
    ctx = fixtures.setup_installation_show(
        works=THREE_WORKS,
        scores=[(8, 8, 8)] * 3,
        artist_overrides={"member_status": "MEMBER"},
        exhibition_overrides={"acceptance_capacity": 3},
    )
    for index, artwork in enumerate(ctx["artworks"]):
        if index == damaged_index:
            fixtures.file_condition_report(
                artwork["id"], "INTAKE", "DAMAGED", damage_notes=DAMAGE_NOTES
            )
        else:
            fixtures.file_condition_report(artwork["id"], "INTAKE", "A")
    return ctx


def _attempt_plan(artwork_id, wall_id, start, end, version):
    """File an installation plan without asserting success."""
    return api_client.file_installation_plan(
        artwork_id,
        create_installation_plan_payload(wall_id, start, end, version),
        REGISTRAR,
    )


# ─── The condition block outranks the span conflict ────

def test_damaged_work_reports_the_condition_block_not_a_span_conflict(api):
    """PRD §2.10: "**Condition block** — the work's `intake_condition_grade` is
    not `DAMAGED` before a wall span may be reserved, else
    `ERR_ARTWORK_CONDITION_BLOCKED` (422)." at position 17, ahead of "**Span
    buffer collision** — else `ERR_WALL_SPAN_CONFLICT` (409); see §3.7 for the
    buffer rule." at position 42.

    Design: Difficulty/priority_pair_validation_conflict/installation_plan_condition_before_span_conflict
    """
    ctx = _three_delivered_works(damaged_index=1)
    wall, artworks = ctx["wall"], ctx["artworks"]

    fixtures.plan_span(artworks[0]["id"], wall, 0.0, 100.0)
    occupied = fixtures.read_wall(wall["id"])
    assert occupied["occupied_cm"] == 100.0

    response = _attempt_plan(
        artworks[1]["id"], wall["id"], 110.0, 200.0, occupied["version"]
    )
    validate_error(response, ApiErrorId.ERR_ARTWORK_CONDITION_BLOCKED.value)

    blocked = fixtures.read_artwork(artworks[1]["id"])
    assert blocked["placement_status"] == "UNPLACED"
    assert blocked["wall_segment_id"] is None
    assert blocked["intake_condition_grade"] == "DAMAGED"

    unchanged = fixtures.read_wall(wall["id"])
    assert unchanged["occupied_cm"] == 100.0
    assert unchanged["available_cm"] == 500.0


def test_undamaged_work_at_the_same_span_reports_the_span_conflict(api):
    """PRD §3.7: "The span must clear its neighbours by a **15-centimetre hanging
    buffer**: the plan is refused with `ERR_WALL_SPAN_CONFLICT` if, for any other
    artwork on the same wall whose `placement_status` is `PLANNED` or
    `INSTALLED`, the requested `span_start_cm` less 15 is smaller than that
    neighbour's `span_end_cm` while at the same time the requested `span_end_cm`
    plus 15 is greater than that neighbour's `span_start_cm`."

    Design: Difficulty/priority_pair_validation_conflict/installation_plan_condition_before_span_conflict
    """
    ctx = _three_delivered_works(damaged_index=1)
    wall, artworks = ctx["wall"], ctx["artworks"]

    fixtures.plan_span(artworks[0]["id"], wall, 0.0, 100.0)
    version = fixtures.read_wall(wall["id"])["version"]

    response = _attempt_plan(artworks[2]["id"], wall["id"], 110.0, 200.0, version)
    validate_error(response, ApiErrorId.ERR_WALL_SPAN_CONFLICT.value)

    assert fixtures.read_artwork(artworks[2]["id"])["placement_status"] == "UNPLACED"
    assert fixtures.read_wall(wall["id"])["occupied_cm"] == 100.0


# ─── The fifteen-centimetre buffer at its exact edge ──

def test_gap_of_exactly_fifteen_centimetres_between_spans_is_legal(api):
    """PRD §3.7: "A gap of exactly 15 centimetres between two spans is therefore
    legal and a gap of 14 is not."

    Design: Difficulty/resource_temporal_overlap/wall_span_buffered_gap_exactly_fifteen_allowed
    """
    ctx = _three_delivered_works()
    wall, artworks = ctx["wall"], ctx["artworks"]

    fixtures.plan_span(artworks[0]["id"], wall, 0.0, 100.0)
    second = fixtures.plan_span(artworks[1]["id"], wall, 115.0, 200.0)
    assert second["placement_status"] == "PLANNED"
    assert second["span_start_cm"] == 115.0
    assert second["span_end_cm"] == 200.0

    after = fixtures.read_wall(wall["id"])
    assert after["occupied_cm"] == 185.0
    assert after["available_cm"] == 415.0
    assert after["loaded_weight_kg"] == 11.0


def test_gap_of_fourteen_centimetres_is_refused_then_fifteen_succeeds(api):
    """PRD §3.7: "A successful plan carries the work `UNPLACED → PLANNED`, stores
    its `wall_segment_id`, `span_start_cm` and `span_end_cm`, and recomputes the
    wall's three derived figures: `occupied_cm` as the sum of span widths over the
    artworks assigned to that wall whose `placement_status` is `PLANNED` or
    `INSTALLED`, `available_cm` as the wall's `length_cm` minus `occupied_cm`, and
    `loaded_weight_kg` as the sum of `weight_kg` over the same set."

    Design: Difficulty/resource_temporal_overlap/wall_span_buffered_gap_exactly_fifteen_allowed
    """
    ctx = _three_delivered_works()
    wall, artworks = ctx["wall"], ctx["artworks"]

    fixtures.plan_span(artworks[0]["id"], wall, 0.0, 100.0)
    fixtures.plan_span(artworks[1]["id"], wall, 115.0, 200.0)

    version = fixtures.read_wall(wall["id"])["version"]
    response = _attempt_plan(artworks[2]["id"], wall["id"], 210.0, 300.0, version)
    validate_error(response, ApiErrorId.ERR_WALL_SPAN_CONFLICT.value)
    assert fixtures.read_wall(wall["id"])["occupied_cm"] == 185.0

    third = fixtures.plan_span(artworks[2]["id"], wall, 215.0, 300.0)
    assert third["placement_status"] == "PLANNED"
    assert third["span_start_cm"] == 215.0
    assert third["span_end_cm"] == 300.0

    after = fixtures.read_wall(wall["id"])
    assert after["occupied_cm"] == 270.0
    assert after["available_cm"] == 330.0
    assert after["loaded_weight_kg"] == 15.0


def test_span_running_past_the_wall_length_is_out_of_bounds(api):
    """PRD §3.7: "The span must satisfy `span_start_cm` at least 0, strictly less
    than `span_end_cm`, and `span_end_cm` at most the wall's `length_cm`, else
    `ERR_WALL_SPAN_OUT_OF_BOUNDS`."

    Design: Difficulty/resource_temporal_overlap/wall_span_buffered_gap_exactly_fifteen_allowed
    """
    ctx = _three_delivered_works()
    wall, artworks = ctx["wall"], ctx["artworks"]

    fixtures.plan_span(artworks[0]["id"], wall, 0.0, 100.0)
    fixtures.plan_span(artworks[1]["id"], wall, 115.0, 200.0)

    version = fixtures.read_wall(wall["id"])["version"]
    response = _attempt_plan(artworks[2]["id"], wall["id"], 590.0, 700.0, version)
    validate_error(response, ApiErrorId.ERR_WALL_SPAN_OUT_OF_BOUNDS.value)

    assert fixtures.read_artwork(artworks[2]["id"])["placement_status"] == "UNPLACED"
    assert fixtures.read_wall(wall["id"])["occupied_cm"] == 185.0


# ─── Deinstall as the compensating counterpart ────────

TWO_PAINTINGS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
    },
    {
        "title": "Second Ridge", "medium_category": "PAINTING",
        "width_cm": 80.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 5.0,
    },
]


def _on_view_pair():
    ctx = fixtures.setup_on_view_show(
        works=TWO_PAINTINGS,
        artist_overrides={"member_status": "MEMBER"},
    )
    first, second = ctx["accepted_artwork_ids"]
    return ctx, first, second


def test_deinstall_releases_the_reserved_centimetres_and_load(api):
    """PRD §3.7: "Deinstallation is the compensating counterpart of the
    reservation and releases the centimetres. It is available from either
    `PLANNED` or `INSTALLED`, moves the work to `DEINSTALLED`, and recomputes the
    wall's `occupied_cm`, `available_cm` and `loaded_weight_kg` so that
    `occupied_cm` plus `available_cm` still equals `length_cm` — that pair is the
    conserved spatial quantity of the system."

    Design: Difficulty/compensating_invariant/deinstall_restores_wall_segment_occupancy
    """
    ctx, first_id, second_id = _on_view_pair()
    wall = ctx["wall"]

    before = fixtures.read_wall(wall["id"])
    assert before["occupied_cm"] == 200.0
    assert before["available_cm"] == 400.0
    assert before["loaded_weight_kg"] == 11.0

    removed = fixtures.deinstall_artwork(second_id)
    assert removed["placement_status"] == "DEINSTALLED"
    assert removed["status"] == "ON_VIEW", (
        "deinstall acts on the placement axis alone"
    )

    after = fixtures.read_wall(wall["id"])
    assert after["occupied_cm"] == 100.0
    assert after["available_cm"] == 500.0
    assert after["loaded_weight_kg"] == 6.0

    still_hung = fixtures.read_artwork(first_id)
    assert still_hung["placement_status"] == "INSTALLED"
    assert still_hung["span_start_cm"] == 0.0
    assert still_hung["span_end_cm"] == 100.0


def test_wall_space_pair_is_conserved_across_a_deinstall(api):
    """PRD §3.7: "It is available from either `PLANNED` or `INSTALLED`, moves the
    work to `DEINSTALLED`, and recomputes the wall's `occupied_cm`,
    `available_cm` and `loaded_weight_kg` so that `occupied_cm` plus
    `available_cm` still equals `length_cm` — that pair is the conserved spatial
    quantity of the system."

    Design: Difficulty/compensating_invariant/deinstall_restores_wall_segment_occupancy
    """
    ctx, _, second_id = _on_view_pair()
    wall_id = ctx["wall"]["id"]

    before = fixtures.read_wall(wall_id)
    assert_wall_space_conserved(before)
    assert before["length_cm"] == 600.0

    fixtures.deinstall_artwork(second_id)

    after = fixtures.read_wall(wall_id)
    assert_wall_space_conserved(after)
    assert after["length_cm"] == 600.0
    retained = fixtures.read_artwork(second_id)
    assert retained["wall_segment_id"] == wall_id, (
        "the work's wall_segment_id is retained after deinstall"
    )
