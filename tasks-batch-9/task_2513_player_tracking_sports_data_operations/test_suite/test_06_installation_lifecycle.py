"""
Rig calibration and certification: the accuracy boundary, the drift cycle back
to CERTIFIED, and the venue posture the game depends on.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_VENUE_NOT_CERTIFIED
from test_helpers.assertions import (
    assert_installation_census,
    assert_two_dp,
    expected_composite_rms_mm,
)
from test_helpers.constants import (
    COLLECTION_LIVE,
    COLLECTION_SCHEDULED,
    INSTALLATION_CALIBRATING,
    INSTALLATION_CERTIFIED,
    INSTALLATION_RECALIBRATION_REQUIRED,
    INSTALLATION_VALIDATED,
    POSTURE_CERTIFIED,
    POSTURE_RESTRICTED,
    POSTURE_UNCERTIFIED,
    QUALITY_FLAG_CLEAN,
    RESULT_INVALID,
    RESULT_PASS,
    RESULT_PROVISIONAL,
)
from test_helpers.test_users import (
    ENGINEER_ALT_HEADERS,
    ENGINEER_HEADERS,
    ENGINEER_SECONDARY,
    OPS_HEADERS,
    OPS_PRIMARY,
)


# ---------------------------------------------------------------------------
# The accuracy boundary and the sample gate
# ---------------------------------------------------------------------------

def _four_rig_venue(api: ApiClient) -> fx.World:
    """One venue with four freshly deployed rigs, one per boundary case."""
    world = fx.World()
    world.venue = fx.register_venue(api)
    labels_and_modalities = [
        ("RIG-A", "UWB_ANCHOR"),
        ("RIG-B", "UWB_ANCHOR"),
        ("RIG-C", "LIDAR"),
        ("RIG-D", "OPTICAL_CAMERA"),
    ]
    world.extra["rigs"] = {
        label: fx.deploy_rig(api, world.venue["id"], rig_label=label, modality=modality)
        for label, modality in labels_and_modalities
    }
    return world


def _run_on(api: ApiClient, rig_id: str, **payload) -> dict:
    return get_success_data(
        api.create_calibration_run(
            rig_id, fac.calibration_run_payload(**payload), ENGINEER_HEADERS
        ),
        expected_status=201,
    )


@pytest.mark.parametrize(
    "label, axis_mm, sample_count, reference_point_count, result, status",
    [
        ("RIG-A", 90.0, 6000, 16, RESULT_PASS, INSTALLATION_VALIDATED),
        ("RIG-B", 90.01, 6000, 16, RESULT_PROVISIONAL, INSTALLATION_CALIBRATING),
        ("RIG-C", 90.0, 4999, 16, RESULT_INVALID, INSTALLATION_CALIBRATING),
        ("RIG-D", 90.0, 5000, 12, RESULT_PASS, INSTALLATION_VALIDATED),
    ],
)
def test_calibration_verdict_at_the_accuracy_and_gate_boundaries(
    api, clock, label, axis_mm, sample_count, reference_point_count, result, status
):
    """PRD §3.2: "First the sufficiency gate: if `sample_count` is below 5,000 *or*
    `reference_point_count` is below 12, the verdict is `INVALID` and no accuracy claim
    is recorded at all, whatever the composite figure happens to be."
    PRD §3.2: "Otherwise, if `composite_rms_mm` is at most 90.00 millimetres — nine
    centimetres, inclusive, so a composite of exactly 90.00 passes — the verdict is
    `PASS`."
    PRD §3.2: "Immediately afterwards, and without any further call, a rig whose
    just-recorded verdict was `PASS` advances `CALIBRATING → VALIDATED`, and the venue
    census and posture are re-derived again to reflect the move."
    PRD §3.2: "A verdict of `PROVISIONAL`, `FAIL` or `INVALID` leaves the rig sitting in
    `CALIBRATING`, awaiting another attempt."

    90.00 passes, 90.01 does not, and 4999 samples are rejected outright.

    The sample gate is evaluated before the accuracy thresholds, so a rig with
    perfect accuracy but one sample too few is still INVALID; 5000 samples and
    12 reference points are both inclusive minimums.

    Design: Difficulty/boundary_precision_check/calibration_pass_threshold_exact_value_and_gate_minimums
    """
    world = _four_rig_venue(api)
    rig_id = world.extra["rigs"][label]["id"]

    run = _run_on(
        api,
        rig_id,
        axis_rms_x_mm=axis_mm,
        axis_rms_y_mm=axis_mm,
        axis_rms_z_mm=axis_mm,
        sample_count=sample_count,
        reference_point_count=reference_point_count,
    )
    assert run["result"] == result
    assert_two_dp(run["composite_rms_mm"], expected_composite_rms_mm(axis_mm, axis_mm, axis_mm))

    rig = validate_success(api.get_installation(rig_id, OPS_HEADERS))
    assert rig["status"] == status


def test_the_four_verdicts_leave_the_venue_uncertified(api, clock):
    """PRD §3.1: "The derivation partitions the venue's installations by `status` and
    counts them: the certified count is the number of rigs in `CERTIFIED`; the
    recalibrating count is the number in either `CALIBRATING` or
    `RECALIBRATION_REQUIRED`; the uncertified count is the number in either `DEPLOYED`
    or `VALIDATED`; the retired count is the number in `RETIRED`."
    PRD §3.1: "If the certified count is zero, `data_posture` is `UNCERTIFIED` — and
    that outcome holds regardless of how many rigs are mid-calibration."

    Two validated and two still calibrating means nothing is certified yet.

    Design: Difficulty/boundary_precision_check/calibration_pass_threshold_exact_value_and_gate_minimums
    """
    world = _four_rig_venue(api)
    rigs = world.extra["rigs"]

    _run_on(api, rigs["RIG-A"]["id"], **fac.uniform_calibration_run_payload(90.0))
    _run_on(api, rigs["RIG-B"]["id"], **fac.uniform_calibration_run_payload(90.01))
    _run_on(
        api, rigs["RIG-C"]["id"], **fac.uniform_calibration_run_payload(90.0, sample_count=4999)
    )
    _run_on(
        api,
        rigs["RIG-D"]["id"],
        **fac.uniform_calibration_run_payload(
            90.0, sample_count=5000, reference_point_count=12
        ),
    )

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue, certified=0, recalibrating=2, uncertified=2)


# ---------------------------------------------------------------------------
# The drift cycle
# ---------------------------------------------------------------------------

def _drifted_world(api: ApiClient) -> fx.World:
    """A certified rig that has just been flagged for drift."""
    world = fx.certified_venue(api)
    world.extra["after_drift"] = validate_success(
        api.flag_drift(world.rig_id, ENGINEER_HEADERS)
    )
    return world


def test_flagging_drift_pulls_the_rig_and_the_venue_back(api, clock):
    """PRD §3.2: "A `CalibrationEngineer` who measures drift on a certified rig flags it,
    moving the rig `CERTIFIED → RECALIBRATION_REQUIRED` and raising its
    `drift_flag_count` by one."
    PRD §3.2: "The first link re-derives the venue's census — certified count down one,
    recalibrating count up one — and with it the `data_posture`, which necessarily
    leaves `CERTIFIED`."

    A certified rig returns to RECALIBRATION_REQUIRED and the venue drops.

    Design: Difficulty/non_linear_state_machine/installation_recalibration_cycle_returns_to_certified
    """
    world = _drifted_world(api)
    flagged = world.extra["after_drift"]

    assert flagged["status"] == INSTALLATION_RECALIBRATION_REQUIRED
    assert flagged["drift_flag_count"] == 1

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue, certified=0, recalibrating=1, uncertified=0)


def test_a_second_passing_run_and_certification_close_the_cycle(api, clock):
    """PRD §3.2: "The recording always moves the rig into `CALIBRATING`, whether it came
    from `DEPLOYED` or from `RECALIBRATION_REQUIRED`, and in both cases the same effects
    follow: the run row is created, the rig's `calibration_run_count` rises by one, and
    its four mirror fields — `latest_run_result`, `latest_run_composite_rms_mm`,
    `latest_run_recorded_at_utc` and `latest_run_engineer_user_id` — are refreshed from
    the run that now has the greatest `recorded_at_utc` (with `created_at` ascending as
    the tie-break, so the last-written of two runs sharing an instant wins)."
    PRD §3.2: "On success the rig moves `VALIDATED → CERTIFIED`, `certified_at_utc` is
    stamped with the logical clock and `certified_by_user_id` with the acting
    `X-User-ID`, the venue's certified count rises by one while its uncertified count
    falls by one, and the venue's posture is re-derived — which is the moment a venue
    can finally flip from `RESTRICTED` to `CERTIFIED`."

    The rig arrives back at CERTIFIED, distinguishable only by its counters.

    Design: Difficulty/non_linear_state_machine/installation_recalibration_cycle_returns_to_certified
    """
    world = _drifted_world(api)

    second_run = get_success_data(
        api.create_calibration_run(
            world.rig_id,
            fac.uniform_calibration_run_payload(75.0),
            ENGINEER_ALT_HEADERS,
        ),
        expected_status=201,
    )
    assert second_run["result"] == RESULT_PASS
    assert_two_dp(second_run["composite_rms_mm"], 75.00)

    recertified = validate_success(api.certify_installation(world.rig_id, OPS_HEADERS))
    assert recertified["status"] == INSTALLATION_CERTIFIED
    assert recertified["calibration_run_count"] == 2
    assert recertified["drift_flag_count"] == 1
    assert recertified["latest_run_engineer_user_id"] == ENGINEER_SECONDARY
    assert_two_dp(recertified["latest_run_composite_rms_mm"], 75.00)
    assert recertified["certified_by_user_id"] == OPS_PRIMARY

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_CERTIFIED
    assert_installation_census(venue, certified=1, recalibrating=0, uncertified=0)


# ---------------------------------------------------------------------------
# The game's dependency on the venue's derived posture
# ---------------------------------------------------------------------------

def _restricted_venue_world(api: ApiClient) -> fx.World:
    """A venue needing two certified rigs while only one of the two is certified."""
    world = fx.World()
    world.venue = fx.register_venue(api, required_certified_installations=2)
    world.rig = fx.deploy_rig(api, world.venue["id"], rig_label="RIG-A")
    world.rig_b = fx.deploy_rig(
        api, world.venue["id"], rig_label="RIG-B", modality="OPTICAL_CAMERA"
    )
    fx.record_run(api, world.rig["id"], ENGINEER_HEADERS)
    fx.record_run(
        api,
        world.rig_b["id"],
        ENGINEER_ALT_HEADERS,
        axis_rms_x_mm=75.0,
        axis_rms_y_mm=75.0,
        axis_rms_z_mm=75.0,
    )
    world.rig = fx.certify_rig(api, world.rig["id"], OPS_HEADERS)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"], world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    return world


def test_a_restricted_venue_cannot_open_collection(api, clock):
    """PRD §3.1: "In every remaining case — some rigs certified but not enough of them, or
    enough of them but at least one rig back in calibration — `data_posture` is
    `RESTRICTED`."
    PRD §3.1: "Only a venue at `CERTIFIED` posture may have collection opened or resumed
    on its games; anything else is refused with `ERR_VENUE_NOT_CERTIFIED`."

    One certified rig out of the two required leaves the posture RESTRICTED.

    Design: Difficulty/cross_entity_state_dependency/open_collection_requires_certified_venue_posture
    """
    world = _restricted_venue_world(api)

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_RESTRICTED
    assert_installation_census(venue, certified=1, recalibrating=0, uncertified=1)

    validate_error(
        api.open_collection(world.game_id, OPS_HEADERS), ERR_VENUE_NOT_CERTIFIED
    )

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["collection_status"] == COLLECTION_SCHEDULED


def test_certifying_the_second_rig_lets_the_identical_call_through(api, clock):
    """PRD §3.1: "Otherwise, if the certified count is greater than or equal to the venue's
    `required_certified_installations` *and* the recalibrating count is exactly zero,
    `data_posture` is `CERTIFIED`."
    PRD §3.4: "It is permitted only from `SCHEDULED` — any other source state is
    `ERR_INVALID_GAME_COLLECTION_STATE` — and only when the hosting venue's
    `data_posture` reads `CERTIFIED` at that instant, which is the single hard link from
    the calibration subsystem into game operations."
    PRD §3.4: "Success advances `collection_status` `SCHEDULED → LIVE`, sets
    `data_quality_flag` to `CLEAN`, and increments the game's `version`."

    Nothing about the game changes; only the venue's derived census does.

    Design: Difficulty/cross_entity_state_dependency/open_collection_requires_certified_venue_posture
    """
    world = _restricted_venue_world(api)
    validate_error(
        api.open_collection(world.game_id, OPS_HEADERS), ERR_VENUE_NOT_CERTIFIED
    )

    fx.certify_rig(api, world.rig_b["id"], OPS_HEADERS)
    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_CERTIFIED
    assert_installation_census(venue, certified=2, recalibrating=0, uncertified=0)

    opened = validate_success(api.open_collection(world.game_id, OPS_HEADERS))
    assert opened["collection_status"] == COLLECTION_LIVE
    assert opened["data_quality_flag"] == QUALITY_FLAG_CLEAN
