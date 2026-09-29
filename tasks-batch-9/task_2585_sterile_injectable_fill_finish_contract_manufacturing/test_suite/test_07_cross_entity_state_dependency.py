"""Operations whose legality is decided by state living on another row.

A fill may only start when a suite's derived posture says so, and that posture
is a function of environmental samples the batch never mentions. A qualification
may only be granted when a simulation on a third row says the room was sterile.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    QA_REVIEWER,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance:
#   start_fill_blocked_by_derived_suite_posture_until_excursion_investigation_closes
# ---------------------------------------------------------------------------
def _batch_in_setup_with_an_open_excursion(api) -> Json:
    """A batch ready to fill in a suite an action excursion has just restricted."""
    program = fixtures.build_program(api, stage=fixtures.STAGE_SETUP)
    program["sample"] = fixtures.record_em_sample(
        api, program["suite_id"], sample_type="VIABLE_AIR", cfu_count=20
    )
    return program


def test_start_fill_is_refused_while_the_excursion_investigation_is_open(api):
    """A restricted suite is not good enough to expose sterile product.

    PRD 3.6: "The suite's `posture` must be exactly `OPEN` — `RESTRICTED` is not good enough here, and a suite that is merely restricted yields `ERR_SUITE_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/start_fill_blocked_by_derived_suite_posture_until_excursion_investigation_closes
    """
    world = _batch_in_setup_with_an_open_excursion(api)
    sample = world["sample"]
    assert (sample["alert_limit"], sample["action_limit"]) == (5, 10)
    assert sample["classification"] == "ACTION"
    assert sample["risk_index"] == 80

    blocked = api.start_fill(world["batch_id"], PRODUCTION_SUPERVISOR)
    validate_error(blocked, ApiErrorId.SUITE_NOT_OPEN, 409)
    assert fixtures.read_batch(api, world["batch_id"])["production_status"] == "SETUP"

    investigating = fixtures.investigate_em(api, sample["id"], MICROBIOLOGY_ANALYST)
    assert investigating["investigation_status"] == "INVESTIGATING"
    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["open_action_excursion_count"] == 1
    assert suite["posture"] == constants.POSTURE_RESTRICTED

    still_blocked = api.start_fill(world["batch_id"], PRODUCTION_SUPERVISOR)
    validate_error(still_blocked, ApiErrorId.SUITE_NOT_OPEN, 409)


def test_closing_the_investigation_reopens_the_suite_and_lets_the_fill_start(api):
    """Closure is the only route back from an excursion-driven restriction.

    PRD 3.7: "Closing recomputes the suite's `open_action_excursion_count`, which recomputes `posture` and can return the suite to `OPEN` — the only route back from an excursion-driven restriction — and bumps both the sample's `version` and the suite's `version`."

    Design: Difficulty/cross_entity_state_dependency/start_fill_blocked_by_derived_suite_posture_until_excursion_investigation_closes
    """
    world = _batch_in_setup_with_an_open_excursion(api)
    sample_id = world["sample"]["id"]

    fixtures.investigate_em(api, sample_id, MICROBIOLOGY_ANALYST)
    closed = fixtures.close_em_investigation(api, sample_id, MICROBIOLOGY_ANALYST)
    assert closed["investigation_status"] == "CLOSED"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["open_action_excursion_count"] == 0
    assert suite["posture"] == constants.POSTURE_OPEN

    batch = validate_success(api.start_fill(world["batch_id"], PRODUCTION_SUPERVISOR))
    assert batch["production_status"] == "FILLING"
    assert batch["quality_status"] == "IN_PROCESS_REVIEW"


# ---------------------------------------------------------------------------
# Design instance:
#   aseptic_qualification_gated_by_media_fill_status_and_participant_membership
# ---------------------------------------------------------------------------
def _suite_awaiting_adjudication(api) -> Json:
    """A single-contaminant simulation and three pending qualification records."""
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api, suite_code="FS-1", grade="B")
    media_fill = fixtures.create_media_fill(api, suite["id"])
    fixtures.execute_media_fill(
        api,
        media_fill["id"],
        units_filled=6000,
        participating_operator_names=["OP-A", "OP-B"],
    )
    under_investigation = fixtures.read_media_fill_out(api, media_fill["id"], 1)

    participant = fixtures.create_qualification(
        api, "OP-A", suite["id"], media_fill_id=media_fill["id"]
    )
    outsider = fixtures.create_qualification(
        api, "OP-Z", suite["id"], media_fill_id=media_fill["id"]
    )
    gowning = fixtures.create_qualification(
        api,
        "OP-G",
        suite["id"],
        qualification_type="GOWNING",
        expires_on="2027-06-01T00:00:00Z",
    )
    return {
        "suite_id": suite["id"],
        "media_fill_id": media_fill["id"],
        "media_fill": under_investigation,
        "participant_id": participant["id"],
        "outsider_id": outsider["id"],
        "gowning_id": gowning["id"],
    }


def test_aseptic_grant_waits_for_the_simulation_to_be_adjudicated_passed(api):
    """An INVESTIGATION_REQUIRED simulation is not yet evidence of anything.

    PRD 3.3: "Where `qualification_type` is `ASEPTIC_INTERVENTION` the grant carries an extra evidential burden: `media_fill_id` must be non-null, the cited simulation must have `status` of `PASSED`, and the record's `operator_name` must be a member of that simulation's `participating_operator_names`."

    Design: Difficulty/cross_entity_state_dependency/aseptic_qualification_gated_by_media_fill_status_and_participant_membership
    """
    world = _suite_awaiting_adjudication(api)
    assert world["media_fill"]["status"] == "INVESTIGATION_REQUIRED"

    too_early = api.qualify(world["participant_id"], MICROBIOLOGY_ANALYST)
    validate_error(too_early, ApiErrorId.MEDIA_FILL_NOT_PASSED, 409)
    assert fixtures.read_qualification(api, world["participant_id"])["status"] == "PENDING"

    adjudicated = fixtures.adjudicate_media_fill(
        api, world["media_fill_id"], QA_REVIEWER, outcome="PASSED"
    )
    assert adjudicated["status"] == "PASSED"
    assert adjudicated["outcome_reason"] == "ADJUDICATED_PASS"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["aseptic_qualification_status"] == "QUALIFIED"
    assertions.assert_same_instant(
        suite["media_fill_valid_until"],
        constants.MEDIA_FILL_VALID_UNTIL,
        "media_fill_valid_until",
    )

    granted = fixtures.qualify(api, world["participant_id"], MICROBIOLOGY_ANALYST)
    assert granted["status"] == "QUALIFIED"
    assertions.assert_same_instant(
        granted["qualified_at"], constants.SCENARIO_CLOCK, "qualified_at"
    )


def test_participant_membership_gates_only_the_aseptic_qualification_type(api):
    """A non-participant is refused while a gowning record needs no simulation.

    PRD 3.3: "The other two qualification types carry no such requirement, and for them `media_fill_id` may be left null."

    Design: Difficulty/cross_entity_state_dependency/aseptic_qualification_gated_by_media_fill_status_and_participant_membership
    """
    world = _suite_awaiting_adjudication(api)
    fixtures.adjudicate_media_fill(
        api, world["media_fill_id"], QA_REVIEWER, outcome="PASSED"
    )
    fixtures.qualify(api, world["participant_id"], MICROBIOLOGY_ANALYST)

    not_a_participant = api.qualify(world["outsider_id"], MICROBIOLOGY_ANALYST)
    validate_error(not_a_participant, ApiErrorId.MEDIA_FILL_NOT_PASSED, 409)
    assert fixtures.read_qualification(api, world["outsider_id"])["status"] == "PENDING"

    gowning = fixtures.qualify(api, world["gowning_id"], MICROBIOLOGY_ANALYST)
    assert gowning["status"] == "QUALIFIED"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["qualified_operator_count"] == constants.QUALIFIED_OPERATOR_THRESHOLD
    assert suite["posture"] == constants.POSTURE_OPEN
