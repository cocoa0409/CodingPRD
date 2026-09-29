"""Periodized programs: the unbroken block chain, activation and the pinned load order."""
import pytest

from test_helpers import (
    api_client,
    append_program_block,
    create_draft_program,
    create_program_block_payload,
    fetch_program_block,
    fetch_training_program,
    register_athlete,
    setup_activatable_program,
    setup_active_program,
    validate_error,
    validate_success,
)

UNKNOWN_PROGRAM_ID = "7c2b1a52-0000-4000-8000-0000000000ff"


def test_01_appending_a_block_to_a_missing_program_is_a_not_found(
        api, performance_director_headers):
    """The path identifier is resolved before the body's concurrency guard is read.

    "**Path existence.** Every `{...}` path identifier must resolve to a live row
    of its entity, and the entity-specific not-found code is returned (see §2.9)."

    Design: Corner/entities/program_block_creation_against_missing_program_returns_not_found
    """
    validate_error(
        api.create_program_block(
            UNKNOWN_PROGRAM_ID,
            create_program_block_payload(1, phase="GENERAL_PREP", start_week=1,
                                        end_week=4, target_intensity_pct=70,
                                        weekly_volume_units=100.0),
            performance_director_headers),
        "ERR_TRAINING_PROGRAM_NOT_FOUND", expected_status=404)


def test_02_a_stale_program_version_on_an_append_is_a_precondition_failure(
        api, performance_director_headers):
    """The append carries the version the client last saw, and a mismatch is refused.

    "A mismatch with the program's current `version` is rejected with
    `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_layers/program_block_append_with_stale_program_version_returns_stale_version
    """
    athlete = register_athlete(full_name="Stale Version Athlete")
    program = create_draft_program(athlete["id"])
    assert program["version"] == 1

    first = validate_success(api.create_program_block(
        program["id"],
        create_program_block_payload(1, phase="GENERAL_PREP", start_week=1, end_week=4,
                                     target_intensity_pct=70, weekly_volume_units=100.0),
        performance_director_headers), expected_status=201)
    assert fetch_training_program(program["id"])["version"] == 2

    validate_error(
        api.create_program_block(
            program["id"],
            create_program_block_payload(1, phase="SPECIFIC_PREP", start_week=5,
                                        end_week=8, target_intensity_pct=80,
                                        weekly_volume_units=90.0,
                                        predecessor_block_id=first["id"]),
            performance_director_headers),
        "ERR_STALE_VERSION", expected_status=412)

    reread = fetch_training_program(program["id"])
    assert reread["block_count"] == 1, "the refused append added nothing"
    assert reread["version"] == 2
    assert reread["planned_load_units"] == pytest.approx(0.0, abs=0.01)


def test_03_a_gap_in_the_week_chain_is_refused_on_the_append(
        api, performance_director_headers):
    """A successor must start the week after its predecessor ends.

    "Every later block must name as its predecessor an existing block of the same
    program — of any `status`, since blocks are created `PLANNED` and only reach
    `PINNED` at activation, so the predecessor's status is never part of this check
    — must be the only block referencing that predecessor, and must have a
    `start_week` exactly one greater than the predecessor's `end_week`."

    Design: Corner/validations/program_block_chain_gap_rejected_before_activation
    """
    athlete = register_athlete(full_name="Chain Gap Athlete")
    program = create_draft_program(athlete["id"])
    first = append_program_block(program["id"], phase="GENERAL_PREP", start_week=1,
                                end_week=4, target_intensity_pct=70,
                                weekly_volume_units=100.0)
    assert fetch_training_program(program["id"])["version"] == 2

    validate_error(
        api.create_program_block(
            program["id"],
            create_program_block_payload(2, phase="SPECIFIC_PREP", start_week=6,
                                        end_week=9, target_intensity_pct=80,
                                        weekly_volume_units=90.0,
                                        predecessor_block_id=first["id"]),
            performance_director_headers),
        "ERR_PROGRAM_BLOCK_SEQUENCE_INVALID", expected_status=422)

    reread = fetch_training_program(program["id"])
    assert reread["block_count"] == 1
    assert reread["version"] == 2


def test_04_a_program_with_no_blocks_cannot_be_activated(api, performance_director_headers):
    """Activation of an empty chain is a sequence violation, not a state error.

    "A program with zero blocks cannot be activated."

    Design: Corner/validations/program_block_chain_gap_rejected_before_activation
    """
    athlete = register_athlete(full_name="Empty Program Athlete")
    program = create_draft_program(athlete["id"])

    validate_error(
        api.activate_training_program(program["id"], performance_director_headers),
        "ERR_PROGRAM_BLOCK_SEQUENCE_INVALID", expected_status=422)

    reread = fetch_training_program(program["id"])
    assert reread["status"] == "DRAFT"
    assert reread["block_count"] == 0
    assert reread["activated_at"] is None


def test_05_activation_rounds_each_block_before_summing_the_planned_load(
        api, performance_director_headers):
    """Two contributions of x.005 each round up before the sum, giving 30.02 not 30.01.

    "**The rounding order is pinned:** each block's contribution is its
    `weekly_volume_units` multiplied by its week count — the `end_week` minus the
    `start_week`, plus one — multiplied by its `target_intensity_pct` divided by
    100, and that per-block product is rounded half up to two decimal places
    *before* being added in."

    Design: Corner/calculations/program_planned_load_rounds_each_block_before_summing_to_30_02
    """
    athlete = register_athlete(full_name="Rounding Order Athlete")
    program, blocks = setup_activatable_program(athlete["id"], blocks=[
        # 20.01 x 1 week x 0.50 = 10.005 -> 10.01
        {"phase": "GENERAL_PREP", "start_week": 1, "end_week": 1,
         "target_intensity_pct": 50, "weekly_volume_units": 20.01},
        # 40.01 x 1 week x 0.50 = 20.005 -> 20.01
        {"phase": "COMPETITION", "start_week": 2, "end_week": 2,
         "target_intensity_pct": 50, "weekly_volume_units": 40.01},
    ])
    assert [block["sequence_index"] for block in blocks] == [0, 1]
    assert all(block["status"] == "PLANNED" for block in blocks)
    assert program["block_count"] == 2
    assert program["total_weeks"] == 2

    activated = validate_success(api.activate_training_program(
        program["id"], performance_director_headers))

    assert activated["status"] == "ACTIVE"
    assert activated["planned_load_units"] == pytest.approx(30.02, abs=0.005)
    assert activated["planned_load_units"] != pytest.approx(30.01, abs=0.005), \
        "summing the unrounded contributions and rounding once is not the contract"
    assert activated["total_weeks"] == 2
    for block in blocks:
        assert fetch_program_block(block["id"])["status"] == "PINNED"


def test_06_a_second_activation_archives_the_previously_active_program(
        api, performance_director_headers):
    """One athlete runs at most one live plan, so the earlier program is archived.

    "When a program becomes `ACTIVE`, any other program of the same athlete that was
    `ACTIVE` is moved to `ARCHIVED`, retaining its own `pinned_block_versions` as
    the historical record."

    Design: Corner/state_machines/second_program_activation_archives_the_previously_active_program
    """
    athlete = register_athlete(full_name="Two Program Athlete")
    first, _first_blocks = setup_active_program(
        athlete["id"],
        competition_start_date="2026-11-01", competition_end_date="2027-02-01")
    assert first["status"] == "ACTIVE"

    second, second_blocks = setup_activatable_program(
        athlete["id"], blocks=[
            {"phase": "SPECIFIC_PREP", "start_week": 1, "end_week": 3,
             "target_intensity_pct": 75, "weekly_volume_units": 18.0},
            {"phase": "COMPETITION", "start_week": 4, "end_week": 7,
             "target_intensity_pct": 90, "weekly_volume_units": 16.0},
        ],
        competition_start_date="2027-03-01", competition_end_date="2027-06-01")

    activated = validate_success(api.activate_training_program(
        second["id"], performance_director_headers))

    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] is not None
    pinned_ids = [row["program_block_id"] for row in activated["pinned_block_versions"]]
    assert sorted(pinned_ids) == sorted(block["id"] for block in second_blocks)

    assert fetch_training_program(first["id"])["status"] == "ARCHIVED"
    for block in second_blocks:
        assert fetch_program_block(block["id"])["status"] == "PINNED"
