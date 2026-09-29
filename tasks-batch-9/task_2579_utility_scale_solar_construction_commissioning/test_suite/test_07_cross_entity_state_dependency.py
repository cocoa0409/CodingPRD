"""Writes gated on the status of a sibling entity, not on their own.

Finalizing a capacity test depends on a substation reaching ENERGIZED, and
driving a pile depends on the grading area two levels above it reaching
ACCEPTED. In both pairs the identical payload is refused and then accepted with
no change whatsoever to the addressed resource, so the only thing that moved is
the other entity's status.
"""

from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_GRADING_AREA_NOT_ACCEPTED,
    ERR_SUBSTATION_NOT_ENERGIZED,
)
from test_helpers.assertions import (
    assert_block_counters,
    assert_commissioning_result,
    assert_grading_area_state,
    assert_instant_equals,
    assert_pile_disposition,
    assert_project_state,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_grading_area,
    advance_substation,
    append_interval,
    approved_outage_window,
    create_block,
    create_pile,
    create_project,
    create_substation,
    graded_area,
    read_block,
    read_commissioning_test,
    read_grading_area,
    read_pile,
    read_project,
    read_substation,
    schedule_commissioning_test,
    set_clock,
)
from test_helpers.test_users import COMMISSIONING_ENGINEER, INSTALLATION_FOREMAN

# The approved backfeed window runs 00:00 to 04:00 on the tenth, and the clock is
# parked inside it so energization is admissible the moment it is attempted.
INSIDE_THE_WINDOW = "2026-08-10T02:00:00Z"


def _metered_but_unconnected(api):
    """Two valid samples on a test whose substation has only requested backfeed."""
    set_clock(api, "2026-08-01T00:00:00Z")
    project = create_project(api, name="Ocotillo Bench")
    substation = create_substation(api, project["id"], substation_code="S1")
    window = approved_outage_window(
        api,
        substation["id"],
        start_at="2026-08-10T00:00:00Z",
        end_at="2026-08-10T04:00:00Z",
        purpose="BACKFEED",
    )
    advance_substation(api, substation["id"], "STEEL_ERECTED", "W-1")
    advance_substation(api, substation["id"], "EQUIPMENT_SET", "W-2")
    advance_substation(api, substation["id"], "BACKFEED_REQUESTED", "W-3")

    set_clock(api, INSIDE_THE_WINDOW)
    test = schedule_commissioning_test(
        api,
        project["id"],
        test_type="CAPACITY",
        correction_variant="AS_MEASURED",
        scheduled_at="2026-08-10T02:30:00Z",
    )
    append_interval(api, test["id"], "2026-08-10T02:35:00Z", 800, 76.00, ambient_c=30, wind_m_s=3.0)
    append_interval(api, test["id"], "2026-08-10T02:40:00Z", 800, 77.00, ambient_c=30, wind_m_s=3.0)
    return project, substation, window, test


def _attempt_finalization(api, test_id, note):
    """Ask for finalization without asserting that it is granted."""
    return api.finalize_commissioning_test(
        test_id, f.finalization_payload(note=note), COMMISSIONING_ENGINEER
    )


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/capacity_test_finalization_gated_on_substation_energization
# ---------------------------------------------------------------------------
def test_finalization_is_refused_while_the_substation_stops_short_of_energized(api):
    """A test with two good samples still cannot close over an unenergized facility.

    PRD 3.7: "A substation of the project must be `ENERGIZED`, or the request is
    refused with `ERR_SUBSTATION_NOT_ENERGIZED` — nothing can be metered at the
    point of interconnection before the plant is connected to it."

    Design: Difficulty/cross_entity_state_dependency/capacity_test_finalization_gated_on_substation_energization
    """
    _project, _substation, _window, test = _metered_but_unconnected(api)

    response = _attempt_finalization(api, test["id"], "first attempt")

    validate_error(response, ERR_SUBSTATION_NOT_ENERGIZED, expected_status=422)


def test_the_refused_finalization_leaves_the_test_exactly_as_it_found_it(api):
    """The test keeps IN_PROGRESS and reports nothing, because nothing succeeded.

    PRD 3.7: "An optional `note` may accompany the request. On success
    `finalized_at` is stamped and the test's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/capacity_test_finalization_gated_on_substation_energization
    """
    _project, _substation, _window, test = _metered_but_unconnected(api)

    _attempt_finalization(api, test["id"], "first attempt")

    open_still = read_commissioning_test(api, test["id"])
    assert open_still["status"] == "IN_PROGRESS"
    assert open_still["finalized_at"] is None
    assert open_still["reported_kw_ac"] is None
    assert_commissioning_result(open_still, interval_count=2, valid_interval_count=2)


def test_energization_consumes_the_window_and_records_which_one(api):
    """The advance to ENERGIZED names the approved window it burned.

    PRD 3.6: "When one does, the facility's `status` becomes `ENERGIZED`,
    `energized_at` is stamped with the current logical-clock instant,
    `energizing_outage_window_id` records the `id` of the window that was
    consumed, and that window itself transitions `APPROVED → EXECUTED` with its
    own `version` incremented by 1 alongside the facility's."

    Design: Difficulty/cross_entity_state_dependency/capacity_test_finalization_gated_on_substation_energization
    """
    _project, substation, window, test = _metered_but_unconnected(api)
    _attempt_finalization(api, test["id"], "first attempt")

    advanced = advance_substation(api, substation["id"], "ENERGIZED", "W-4")

    assert advanced["status"] == "ENERGIZED"
    stored = read_substation(api, substation["id"])
    assert stored["energizing_outage_window_id"] == window["id"]
    assert_instant_equals(stored["energized_at"], INSIDE_THE_WINDOW, "energized_at")


def test_the_identical_finalization_is_granted_once_the_facility_is_energized(api):
    """The same call now averages 76.00 and 77.00 to 76.50 and lands on FAILED.

    PRD 3.7: "The test lands at `PASSED` when `reported_kw_ac` is at least
    `pass_threshold_kw_ac` and at `FAILED` when it falls short; equality passes."

    Design: Difficulty/cross_entity_state_dependency/capacity_test_finalization_gated_on_substation_energization
    """
    project, substation, _window, test = _metered_but_unconnected(api)
    validate_error(
        _attempt_finalization(api, test["id"], "first attempt"),
        ERR_SUBSTATION_NOT_ENERGIZED,
        expected_status=422,
    )
    advance_substation(api, substation["id"], "ENERGIZED", "W-4")

    response = _attempt_finalization(api, test["id"], "second attempt")

    finalized = validate_success(response, expected_status=200)
    assert_commissioning_result(
        finalized,
        status="FAILED",
        valid_interval_count=2,
        reported_kw_ac=76.50,
        pass_threshold_kw_ac=98.00,
    )
    # The gate was the substation's status; the project never left preconstruction.
    assert_project_state(read_project(api, project["id"]), milestone_state="PRECONSTRUCTION")


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/pile_driving_gated_on_grading_area_acceptance
# ---------------------------------------------------------------------------
DRIVE = {
    "actual_embedment_mm": 3000,
    "plumb_deviation_mm": 5.0,
    "blow_count": 42,
    "refusal": False,
    "driven_at": "2026-08-03T14:00:00Z",
}


def _pile_over_unaccepted_civil(api):
    """A single planned pile on a block whose pad is graded but not signed off."""
    set_clock(api, "2026-08-01T00:00:00Z")
    project = create_project(api, name="Yucca Rise")
    area = graded_area(
        api,
        project["id"],
        area_code="A1",
        permit_number="CGP-2026-118",
        disturbed_acreage_limit=40.00,
        bmp_inspection_interval_days=14,
    )
    block = create_block(
        api,
        project["id"],
        area["id"],
        block_code="B1",
        dc_capacity_kw=130,
        planned_pile_count=1,
        planned_string_count=1,
    )
    pile = create_pile(api, block["id"], row_index=1, position_index=1, design_embedment_mm=3000)
    return project, area, block, pile


def _attempt_drive(api, pile_id):
    """Report the drive result without asserting that it is admitted."""
    return api.create_drive_result(pile_id, f.drive_result_payload(**DRIVE), INSTALLATION_FOREMAN)


def test_a_graded_pad_is_not_yet_a_signed_off_pad(api):
    """Two earthwork logs reach GRADED, which is one status short of ACCEPTED.

    PRD 3.2: "A `GRADING` log requires the area to be `CLEARED` or `GRADED` and
    advances `CLEARED → GRADED`, leaving an already-`GRADED` area unchanged;
    attempting it on a `PLANNED` area is rejected with
    `ERR_GRADING_AREA_NOT_OPEN_FOR_WORK`."

    Design: Difficulty/cross_entity_state_dependency/pile_driving_gated_on_grading_area_acceptance
    """
    _project, area, _block, _pile = _pile_over_unaccepted_civil(api)

    assert_grading_area_state(read_grading_area(api, area["id"]), status="GRADED")


def test_the_drive_is_refused_until_the_civil_work_is_accepted(api):
    """The foreman's measurements are turned away by the pad's status, not their own.

    PRD 3.4: "Driving a pile is only permitted once the civil work under it has
    been signed off: the grading area owning the pile's block must be `ACCEPTED`,
    and a drive attempted before that is refused with
    `ERR_GRADING_AREA_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/pile_driving_gated_on_grading_area_acceptance
    """
    _project, _area, _block, pile = _pile_over_unaccepted_civil(api)

    response = _attempt_drive(api, pile["id"])

    validate_error(response, ERR_GRADING_AREA_NOT_ACCEPTED, expected_status=409)


def test_the_refused_drive_stores_none_of_its_measurements(api):
    """The pile is still PLANNED with every measurement null and no counter moved.

    PRD 3.4: "A registered pile begins at `PLANNED` with `actual_embedment_mm`,
    `plumb_deviation_mm`, `blow_count`, `driven_at` and `remediation_method` all
    null, `refusal_flag` false and `remediated` false."

    Design: Difficulty/cross_entity_state_dependency/pile_driving_gated_on_grading_area_acceptance
    """
    _project, _area, block, pile = _pile_over_unaccepted_civil(api)

    _attempt_drive(api, pile["id"])

    untouched = read_pile(api, pile["id"])
    assert_pile_disposition(untouched, "PLANNED")
    assert untouched["actual_embedment_mm"] is None
    assert untouched["plumb_deviation_mm"] is None
    assert untouched["blow_count"] is None
    assert untouched["driven_at"] is None
    assert_block_counters(
        read_block(api, block["id"]), mechanical_status="PLANNED", piles_accepted_count=0
    )


def test_acceptance_unlocks_the_identical_drive_and_the_mechanical_rollup(api):
    """Owner sign-off turns the same payload into an ACCEPTED pile and PILES_COMPLETE.

    PRD 3.4: "An `ACCEPTED` pile increments the block's `piles_accepted_count` and
    therefore increments the block's `version` by 1; when that count reaches the
    block's `planned_pile_count` and no pile of the block is `REFUSED`, the
    mechanical dimension additionally advances `PLANNED → PILES_COMPLETE` and the
    block's `mc_ready` is recomputed, staying false until the electrical dimension
    reaches `TESTED`."

    Design: Difficulty/cross_entity_state_dependency/pile_driving_gated_on_grading_area_acceptance
    """
    _project, area, block, pile = _pile_over_unaccepted_civil(api)
    validate_error(
        _attempt_drive(api, pile["id"]), ERR_GRADING_AREA_NOT_ACCEPTED, expected_status=409
    )

    accepted_pad = accept_grading_area(
        api, area["id"], compaction_test_pct=96.5, drainage_inspection_passed=True
    )
    assert accepted_pad["status"] == "ACCEPTED"

    driven = validate_success(_attempt_drive(api, pile["id"]), expected_status=200)

    assert_pile_disposition(driven, "ACCEPTED")
    assert_block_counters(
        read_block(api, block["id"]),
        mechanical_status="PILES_COMPLETE",
        piles_accepted_count=1,
        mc_ready=False,
    )
