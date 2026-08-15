"""Program creation defaults, posture gate, not-found path validation, and the
program-config OCC contract."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_program_payload,
    assert_band_program,
    create_open_program,
    create_program,
    create_student_payload,
    get_program,
    is_valid_uuid,
    patch_program_payload,
    validate_error,
    validate_success,
)


def test_program_create_applies_documented_defaults(api, director_headers,
                                                    reader_headers):
    """PRD §3.1: "`rental_fee_mode` selects the rental-fee variant and defaults to `FLAT`; `scoring_mode` selects the audition scoring variant and defaults to `RAW_WEIGHTED`; `subsidy_pool_cents` seeds the booster-funded pool used to subsidize trip cost shares and defaults to 0. The grace threshold `delinquency_grace_cents` may also be overridden at creation, defaulting to 2500. A new program starts in `SETUP` with both spending aggregates — `music_spent_cents` and `repair_spent_cents` — at zero."

    Design: Corner/entities/program_create_applies_defaults
    """
    created = validate_success(api.create_program(
        {"season_name": "Def", "music_budget_cents": 100000,
         "repair_budget_cents": 50000}, director_headers), 201)
    program = validate_success(api.get_program(created["id"], reader_headers))
    assert_band_program(program)
    assert program["status"] == "SETUP"
    assert program["rental_fee_mode"] == "FLAT"
    assert program["scoring_mode"] == "RAW_WEIGHTED"
    assert program["delinquency_grace_cents"] == 2500
    assert program["subsidy_pool_cents"] == 0
    assert program["music_spent_cents"] == 0
    assert program["repair_spent_cents"] == 0
    assert isinstance(program["version"], int)


def test_child_creation_blocked_in_setup_then_allowed(api, director_headers):
    """PRD §2.9: "Creation of any program-scoped child resource — students, instruments, uniforms, events, arrangements, auditions, fundraisers, cleaning batches, and truck charters alike — is permitted only while the program is in `ENROLLMENT_OPEN` or `SEASON_ACTIVE`. Attempting such a creation while the program is in `SETUP` or `CLOSED` is rejected with `ERR_PROGRAM_NOT_IN_REQUIRED_STATE` (HTTP 409)."

    Design: Corner/validations/program_posture_gates_child_creation
    """
    program = create_program(season_name="PG2")
    rejected = api.create_student(
        create_student_payload(program["id"], full_name="Early"), director_headers)
    validate_error(rejected, ApiErrorId.ERR_PROGRAM_NOT_IN_REQUIRED_STATE)

    validate_success(api.advance_program(
        program["id"], advance_program_payload("ENROLLMENT_OPEN"), director_headers))
    created = validate_success(api.create_student(
        create_student_payload(program["id"], full_name="Early"), director_headers),
        201)
    assert is_valid_uuid(created["id"])
    assert created["enrollment_status"] == "APPLIED"


def test_get_nonexistent_program_returns_program_not_found(api, reader_headers):
    """PRD §2.11 item 4: "Path identifiers exist, validated left to right — else the corresponding `ERR_<RESOURCE>_NOT_FOUND`." PRD §2.13: "the first missing identifier produces its own `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) before any later identifier is examined."

    Design: Corner/errors/not_found_left_to_right_path_validation
    """
    resp = api.get_program(NON_EXISTENT_UUID, reader_headers)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)


def test_program_patch_rejects_stale_version_and_applies_nothing(api, director_headers):
    """PRD §2.10: "Updating a program's configuration requires the request to carry `expected_program_version` holding the `version` of the `BandProgram` the client last observed. If the program's current `version` differs — because another writer has since patched budgets, thresholds, or modes — the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/program_patch_occ_stale_version
    """
    program = create_program(season_name="OC1")
    observed_version = program["version"]

    patched = validate_success(api.patch_program(
        program["id"],
        patch_program_payload(observed_version, subsidy_pool_cents=5000),
        director_headers))
    assert patched["version"] == observed_version + 1, (
        "PRD §2.4: version increments by exactly 1 on every mutation")
    assert patched["subsidy_pool_cents"] == 5000

    stale = api.patch_program(
        program["id"],
        patch_program_payload(observed_version, subsidy_pool_cents=9000),
        director_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    program = get_program(program["id"])
    assert program["subsidy_pool_cents"] == 5000, (
        "the stale writer's value must not be applied")
    assert program["version"] == observed_version + 1
