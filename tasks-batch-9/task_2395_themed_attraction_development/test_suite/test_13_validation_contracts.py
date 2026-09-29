"""One broken rule at a time, and the rule's own error id answers for it."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_scene,
    create_design_package_payload,
    create_project_payload,
    create_queue_segment_payload,
    open_project,
    post_change_order,
    project_version,
    propose_segment,
    read_budget_position,
    read_ledger,
    read_project,
    register_ride_system,
    retire_segment,
    validate_error,
    validate_paginated,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]

UNDERSIZED_RIDE = {
    "vendor_name": "Small Works", "system_type": "OMNIMOVER", "vehicle_count": 2,
    "riders_per_vehicle": 4, "block_zone_count": 3, "cycle_time_seconds": 240,
    "availability_pct": 90, "load_efficiency_pct": 80, "show_stops_per_hour": 0,
}
SWITCHBACK = {"segment_label": "Switchback A", "length_meters": 120,
              "width_meters": 2.4, "routing_type": "STANDARD", "position_index": 1}


def test_a_repeated_programme_code_is_refused_while_a_repeated_name_is_not(api):
    """The mandatory five are `project_code`, an external programme code of 1 to 32 characters that must be unique across all programmes — a collision is refused with `ERR_PROJECT_CODE_DUPLICATE`; `name`, the attraction's show title as it appears in creative documents, 1 to 120 characters; `design_day_attendance`, the expected guest count on the design day, at least 1; `peak_hour_share`, the fraction of that design-day crowd expected to demand this attraction in the peak hour, greater than 0 and at most 1 with at most four decimal places; and `budget_ceiling_cents`, the owner-authorised cost ceiling in cents, at least 1.

    Uniqueness is scoped to the code alone: reusing the code under a different show
    title is refused, while repeating the show title under a fresh code opens a
    perfectly legitimate second programme.

    Design: Corner/validations/duplicate_project_code_is_rejected_while_the_name_may_repeat
    """
    first = open_project(project_code="TAD-VA1", name="Skyward Saga")

    duplicate = api.create_project(
        create_project_payload(project_code="TAD-VA1", name="Different Attraction",
                               design_day_attendance=4000, peak_hour_share=0.12,
                               budget_ceiling_cents=1000000000),
        OWNER,
    )
    twin_name = validate_success(
        api.create_project(
            create_project_payload(project_code="TAD-VA1-B", name="Skyward Saga",
                                   design_day_attendance=4000, peak_hour_share=0.12,
                                   budget_ceiling_cents=1000000000),
            OWNER,
        ),
        201,
    )

    validate_error(duplicate, ApiErrorId.ERR_PROJECT_CODE_DUPLICATE.value, 409)
    assert twin_name["project_code"] == "TAD-VA1-B"
    assert twin_name["name"] == "Skyward Saga"
    assert read_project(first["id"])["name"] == "Skyward Saga"


def test_a_draft_scene_still_reserves_its_running_order_position(api):
    """Each is created against a `project_id` with a `scene_label` drawn from the beat sheet (1 to 80 characters), a `sequence_index` giving its running-order position (at least 1, and unique across all scenes of the same programme — a collision is refused with `ERR_SCENE_SEQUENCE_DUPLICATE`), a `duration_seconds` of at least 1, and optionally a `follows_scene_id` naming the scene immediately preceding it.

    Locking a scene into the running order advances it from `DRAFT` to `SEQUENCED`.

    The prologue has never been sequenced, yet it still holds position one, so moving
    the chase onto that position is refused; re-asserting the chase's own position two
    is no conflict with itself and locks it in.

    Design: Corner/validations/scene_sequence_index_already_held_is_rejected_on_resequence
    """
    project = open_project(project_code="TAD-VA2")
    prologue = add_scene(project["id"], scene_label="Prologue", sequence_index=1,
                         duration_seconds=180)
    chase = add_scene(project["id"], scene_label="Chase", sequence_index=2,
                      duration_seconds=120)

    collision = api.sequence_show_scene(chase["id"], {"sequence_index": 1}, DESIGNER)
    accepted = validate_success(
        api.sequence_show_scene(chase["id"], {"sequence_index": 2}, DESIGNER))

    validate_error(collision, ApiErrorId.ERR_SCENE_SEQUENCE_DUPLICATE.value, 409)
    held = validate_success(api.get_show_scene(prologue["id"], DESIGNER))
    assert held["status"] == "DRAFT"
    assert held["sequence_index"] == 1
    assert accepted["status"] == "SEQUENCED"
    assert accepted["sequence_index"] == 2


def test_closing_a_three_scene_loop_is_caught_by_walking_the_chain(api):
    """Walking the `follows_scene_id` links forward from the requested predecessor must never arrive back at the scene being written; a request that would close the loop is refused with `ERR_SCENE_ORDER_CYCLE`.

    Locking a scene into the running order advances it from `DRAFT` to `SEQUENCED`.

    Scene A leads to B and B leads to C, so pointing A at C would close a three-node
    loop that only a full walk of the chain can see: the refusal names the cycle, not
    the sequence duplicate that A's unchanged position might have suggested, and A
    keeps no predecessor at all.

    Design: Corner/validations/scene_order_cycle_is_detected_by_walking_the_follows_chain
    """
    project = open_project(project_code="TAD-VA3")
    scene_a = add_scene(project["id"], scene_label="Scene A", sequence_index=1,
                        duration_seconds=180)
    scene_b = add_scene(project["id"], scene_label="Scene B", sequence_index=2,
                        duration_seconds=120, follows_scene_id=scene_a["id"])
    scene_c = add_scene(project["id"], scene_label="Scene C", sequence_index=3,
                        duration_seconds=90, follows_scene_id=scene_b["id"])

    response = api.sequence_show_scene(
        scene_a["id"], {"sequence_index": 1, "follows_scene_id": scene_c["id"]}, DESIGNER)

    validate_error(response, ApiErrorId.ERR_SCENE_ORDER_CYCLE.value, 422)
    stored_a = validate_success(api.get_show_scene(scene_a["id"], DESIGNER))
    stored_c = validate_success(api.get_show_scene(scene_c["id"], DESIGNER))
    assert stored_a["follows_scene_id"] is None
    assert stored_a["status"] == "DRAFT"
    assert stored_c["follows_scene_id"] == scene_b["id"]


def test_a_width_of_one_seventy_nine_fails_the_accessible_floor_only(api):
    """Clear width is a code matter, and the minimum depends on the routing class: a `STANDARD` run must be at least 1.10 metres wide, and an `ACCESSIBLE` or `VIRTUAL_RETURN` run must be at least 1.80 metres wide. A narrower run is refused with `ERR_QUEUE_WIDTH_BELOW_MINIMUM`.

    A segment's `capacity_guests` is its `length_meters` multiplied by its
    `width_meters`, divided by the per-guest area for its routing class, and rounded
    down to a whole guest; the area is carried as an exact decimal.

    One centimetre short of the accessible floor is refused by the width rule itself
    rather than by a schema complaint, while the very same 1.79 metres clears the
    standard floor comfortably and is sized at 275 guests.

    Design: Corner/validations/accessible_queue_width_of_one_seventy_nine_is_rejected
    """
    project = open_project(project_code="TAD-VA4")

    narrow_accessible = api.create_queue_segment(
        create_queue_segment_payload(project["id"], segment_label="Narrow Bypass",
                                     length_meters=100, width_meters=1.79,
                                     routing_type="ACCESSIBLE", position_index=1),
        DESIGNER,
    )
    narrow_standard = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], segment_label="Narrow Switchback",
                                         length_meters=100, width_meters=1.79,
                                         routing_type="STANDARD", position_index=1),
            DESIGNER,
        ),
        201,
    )

    validate_error(narrow_accessible, ApiErrorId.ERR_QUEUE_WIDTH_BELOW_MINIMUM.value, 422)
    assert narrow_standard["routing_type"] == "STANDARD"
    assert narrow_standard["capacity_guests"] == 275


def test_a_standard_run_of_exactly_one_metre_ten_is_admitted(api):
    """Clear width is a code matter, and the minimum depends on the routing class: a `STANDARD` run must be at least 1.10 metres wide, and an `ACCESSIBLE` or `VIRTUAL_RETURN` run must be at least 1.80 metres wide.

    On success the segment's `capacity_guests` is added to the programme's
    `queue_capacity_total_guests` and the programme's `version` advances.

    The floor is inclusive, so a run built to exactly the code minimum is created
    rather than refused, and its 110 square metres size it at 169 guests — the
    downward rounding again visible — which is precisely what acceptance adds to the
    programme.

    Design: Corner/validations/standard_queue_width_of_exactly_one_ten_satisfies_the_class_minimum
    """
    project = open_project(project_code="TAD-VA5")

    segment = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], segment_label="Minimum Width Run",
                                         length_meters=100, width_meters=1.1,
                                         routing_type="STANDARD", position_index=1),
            DESIGNER,
        ),
        201,
    )
    accepted = validate_success(
        api.accept_queue_segment(segment["id"],
                                 {"expected_project_version": project["version"]},
                                 OWNER)
    )

    assert segment["capacity_guests"] == 169
    assert float(accepted["width_meters"]) == 1.10
    assert accepted["status"] == "ACCEPTED"
    assert read_project(project["id"])["queue_capacity_total_guests"] == 169


def test_two_affordable_change_orders_are_refused_in_aggregate(api):
    """A change order whose `amount_cents` would push `committed_cost_cents` above `budget_ceiling_cents` is refused with `ERR_BUDGET_CEILING_EXCEEDED`, and a positive change order is refused with `ERR_POSTURE_RESTRICTED` while the programme is `RESTRICTED`.

    The **committed basis** is a chronological replay: starting from zero, the server
    walks every ledger entry of the programme ordered by `created_at` ascending and
    then by `sequence_no` ascending, adding each entry's `amount_cents` to a running
    total, and the final total is `committed_cost_cents`.

    Alongside them, `headroom_cents` is `budget_ceiling_cents` less
    `committed_cost_cents`, and `restricted_utilisation_cents` is
    `budget_ceiling_cents` multiplied by ninety percent, rounded down to whole cents —
    the threshold that separates `OPEN` from `RESTRICTED` per §2.7.

    Each order is affordable read on its own, and the first lands exactly on the
    ninety-percent line so the posture stays OPEN; the second is still refused,
    because the ceiling is tested against the replayed total and 3240000000 plus
    360000001 clears it by a single cent.

    Design: Corner/validations/two_individually_affordable_change_orders_collectively_exceed_the_ceiling
    """
    project = open_project(project_code="TAD-VA6")
    first = post_change_order(project["id"], 3240000000,
                              memo="Show set steelwork change order")
    budget = read_budget_position(project["id"])
    assert first["sequence_no"] == 1
    assert budget["committed_cost_cents"] == 3240000000
    assert budget["readiness_posture"] == "OPEN"
    assert budget["headroom_cents"] == 360000000

    response = api.create_ledger_entry(
        {
            "project_id": project["id"], "entry_kind": "CHANGE_ORDER",
            "amount_cents": 360000001, "memo": "Animation figure change order",
            "expected_project_version": project_version(project["id"]),
        },
        OWNER,
    )

    validate_error(response, ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED.value, 409)
    assert read_budget_position(project["id"])["committed_cost_cents"] == 3240000000
    rows, meta = read_ledger(project["id"])
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_a_forty_one_percent_virtual_share_breaks_a_business_rule_not_the_schema(api):
    """The schema admits anything from 0 through 100, so a submitted share of 41 is *not* a schema violation; it is a business-rule violation of the forty-percent cap on virtual-queue release, and it is therefore refused with `ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED` rather than `ERR_INVALID_REQUEST`. The same cap is checked on programme creation and on every programme patch, and again — as a precondition — when a queue segment is accepted.

    A programme patch takes the required `expected_project_version` plus any subset of
    `budget_ceiling_cents`, `virtual_queue_share_pct`, `design_day_attendance` and
    `peak_hour_share`.

    Forty-one percent is refused on the create path and on the patch path alike, and
    both refusals leave the programme's revision untouched — so the same pinned token
    still admits the forty percent the cap does allow.

    Design: Corner/validations/virtual_queue_share_of_forty_one_percent_is_rejected_as_a_business_rule
    """
    project = open_project(project_code="TAD-VA7")

    on_create = api.create_project(
        create_project_payload(project_code="TAD-VA7-B",
                               name="Overallocated Attraction",
                               virtual_queue_share_pct=41),
        OWNER,
    )
    on_patch = api.patch_project(
        project["id"],
        {"expected_project_version": project["version"], "virtual_queue_share_pct": 41},
        OWNER,
    )
    at_the_cap = validate_success(
        api.patch_project(
            project["id"],
            {"expected_project_version": project["version"],
             "virtual_queue_share_pct": 40},
            OWNER,
        )
    )

    validate_error(on_create, ApiErrorId.ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED.value, 422)
    validate_error(on_patch, ApiErrorId.ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED.value, 422)
    assert float(at_the_cap["virtual_queue_share_pct"]) == 40.00
    assert at_the_cap["version"] == 2


def test_a_retired_run_releases_its_position_for_the_rebuild(api):
    """The position must not already be held by another segment of the same programme that is `PROPOSED` or `ACCEPTED`; a retired segment releases its position. A collision is refused with `ERR_QUEUE_POSITION_DUPLICATE`.

    Four queue figures are derived from the accepted set — segments that are
    `PROPOSED` or `RETIRED` contribute to none of them.

    Position one is taken while the original switchback is live, so the rebuild is
    refused; retiring the original frees the position and the identical payload is
    then accepted as a fresh proposal that counts for nothing yet.

    Design: Corner/validations/queue_position_index_duplicate_is_scoped_to_live_segments
    """
    project = open_project(project_code="TAD-VA8")
    original = propose_segment(project["id"], **SWITCHBACK)
    validate_success(
        api.accept_queue_segment(original["id"],
                                 {"expected_project_version": project["version"]},
                                 OWNER)
    )
    rebuild_payload = create_queue_segment_payload(
        project["id"], segment_label="Switchback A Rebuild", length_meters=120,
        width_meters=2.4, routing_type="STANDARD", position_index=1)

    collision = api.create_queue_segment(rebuild_payload, DESIGNER)
    validate_error(collision, ApiErrorId.ERR_QUEUE_POSITION_DUPLICATE.value, 409)

    retired = retire_segment(original["id"], project["id"])
    rebuild = validate_success(api.create_queue_segment(rebuild_payload, DESIGNER), 201)

    assert retired["status"] == "RETIRED"
    assert rebuild["position_index"] == 1
    assert rebuild["status"] == "PROPOSED"
    assert read_project(project["id"])["queue_capacity_total_guests"] == 0


def test_an_undersized_vehicle_cannot_be_selected_against_the_capacity_target(api):
    """It requires the posture not to be `FROZEN`, a matching `expected_project_version`, that no other ride system of the same programme is already in `ENGINEERED` or `COMMISSIONED` — otherwise `ERR_RIDE_SYSTEM_ALREADY_ENGINEERED` — and that this system's `operational_hourly_capacity_guests` is at least the programme's `required_hourly_capacity_guests`, otherwise `ERR_CAPACITY_TARGET_NOT_MET`.

    `selected_ride_system_id` is a computed mirror, never a client-writable
    reference: it holds the `id` of the programme's ride system whose `status` is
    `SELECTED`, `ENGINEERED` or `COMMISSIONED`, and is null while no system has been
    selected.

    Two vehicles inside three block zones dispatch every two minutes for a
    theoretical 120 guests an hour and a derated 86, nowhere near the 800 the design
    day demands, so the offer cannot be selected; the adequate candidate is selected
    on the very same pinned revision, which shows the refusal was the capacity
    comparison rather than a stale token.

    Design: Corner/validations/select_of_an_undersized_ride_system_fails_the_capacity_target
    """
    project = open_project(project_code="TAD-VA9")
    weak = register_ride_system(project["id"], **UNDERSIZED_RIDE)
    adequate = register_ride_system(project["id"])

    refused = api.select_ride_system(
        weak["id"], {"expected_project_version": project["version"]}, OWNER)
    selected = validate_success(
        api.select_ride_system(
            adequate["id"], {"expected_project_version": project["version"]}, OWNER))

    validate_error(refused, ApiErrorId.ERR_CAPACITY_TARGET_NOT_MET.value, 409)
    assert project["required_hourly_capacity_guests"] == 800
    assert weak["theoretical_hourly_capacity_guests"] == 120
    assert weak["operational_hourly_capacity_guests"] == 86
    assert adequate["operational_hourly_capacity_guests"] == 1179
    assert validate_success(api.get_ride_system(weak["id"], ENGINEER))["status"] == "CANDIDATE"
    assert selected["status"] == "SELECTED"
    assert read_project(project["id"])["selected_ride_system_id"] == adequate["id"]


def test_the_restricted_gate_binds_the_package_create_and_not_the_queue_create(api):
    """`RESTRICTED` is a narrower gate: it blocks only scope-increasing writes. Creating a new design package is refused with `ERR_POSTURE_RESTRICTED` (HTTP 409) while the programme is `RESTRICTED`, and so is posting a ledger entry whose `amount_cents` is positive; a ledger entry with a negative `amount_cents`, which reduces cost, remains permitted.

    Otherwise, if `open_major_finding_count` is greater than zero, or
    `committed_cost_cents` is strictly greater than `restricted_utilisation_cents`,
    the posture is `RESTRICTED`.

    One cent past the ninety-percent line is enough to restrict the programme, and
    the restriction answers the package create ahead of the ceiling that 400000000
    would have cleared anyway — while proposing queue, which the rule does not list,
    goes through untouched under the identical posture.

    Design: Corner/validations/restricted_posture_gates_only_the_two_endpoints_that_declare_it
    """
    project = open_project(project_code="TAD-VA10")
    ride = register_ride_system(project["id"])
    post_change_order(project["id"], 3240000001,
                      memo="Ride and controls change order")
    budget = read_budget_position(project["id"])
    assert budget["committed_cost_cents"] == 3240000001
    assert budget["restricted_utilisation_cents"] == 3240000000
    assert budget["readiness_posture"] == "RESTRICTED"

    refused = api.create_design_package(
        create_design_package_payload(project["id"], ride["id"],
                                      project_version(project["id"]),
                                      package_label="Show Set Release 1",
                                      discipline_scope="SHOW_SET",
                                      base_construction_cost_cents=400000000),
        DESIGNER,
    )
    permitted = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], **SWITCHBACK), DESIGNER),
        201,
    )

    validate_error(refused, ApiErrorId.ERR_POSTURE_RESTRICTED.value, 409)
    assert permitted["capacity_guests"] == 443
    packages, meta = validate_paginated(
        api.list_design_packages(DESIGNER, params={"project_id": project["id"]}))
    assert packages == []
    assert meta["total_count"] == 0
