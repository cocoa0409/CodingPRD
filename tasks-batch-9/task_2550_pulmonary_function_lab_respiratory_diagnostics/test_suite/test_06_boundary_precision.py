"""Millimetre-level boundaries decide acceptability and grade in this laboratory.

A start-of-test limit is rounded to the nearest whole millilitre and then
compared inclusively, so a ten-millilitre change in vital capacity flips the
verdict on an identical start volume.  One rung higher, a study's repeatability
delta of exactly 150 millilitres holds the top grade while 151 does not.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_COACHING_NOTE_REQUIRED
from test_helpers.assertions import (
    assert_1dp,
    assert_3dp,
    assert_maneuver_acceptable,
    assert_maneuver_unacceptable,
)

LATE_START_COACHING = (
    "Blow started late - relax the shoulders and blast out immediately on my count."
)


def _scheduled_spirometry_study(api):
    """One study booked on a programmed spirometer, no efforts recorded yet."""
    lab = fx.build_lab(api)
    session = fx.build_scheduled_session(api, lab)
    return lab, session


class TestBackExtrapolatedVolumeBoundary:
    """The relative start-of-test limit is rounded half up and compared inclusively."""

    def test_a_start_volume_landing_exactly_on_its_limit_is_acceptable(self, api):
        """Five percent of 3.190 L is 159.5 mL, which rounds up to a limit of 160.

        PRD 3.6: "`bev_limit_ml` is the greater of 100 millilitres and 5 percent
        of the maneuver's own `fvc_l` expressed in millilitres, rounded to the
        nearest whole millilitre."

        Design: Difficulty/boundary_precision_check/bev_limit_half_up_rounding_and_inclusive_maneuver_boundaries
        """
        lab, session = _scheduled_spirometry_study(api)

        effort = validate_success(
            api.create_maneuver(
                session["id"],
                f.maneuver_payload(
                    3.190,
                    2.400,
                    pef_l_s=6.00,
                    back_extrapolated_volume_ml=160,
                    expiratory_time_s=15.0,
                ),
                lab.tech1,
            ),
            expected_status=201,
        )

        assert effort["bev_limit_ml"] == 160, (
            "truncating 159.5 would have given 159 and disqualified this blow"
        )
        assert_maneuver_acceptable(effort)
        assert effort["maneuver_index"] == 1

    def test_ten_millilitres_less_capacity_disqualifies_the_same_start_volume(self, api):
        """3.180 L lowers the limit to 159, and the refused blow needs a coaching note.

        PRD 3.6: "Because an unacceptable blow must leave a coaching record,
        `coaching_note` is required and must be non-empty whenever the computed
        `acceptability` is `UNACCEPTABLE`, and its absence reports
        `ERR_COACHING_NOTE_REQUIRED`."

        Design: Difficulty/boundary_precision_check/bev_limit_half_up_rounding_and_inclusive_maneuver_boundaries
        """
        lab, session = _scheduled_spirometry_study(api)
        fx.append_maneuver(
            api,
            session["id"],
            f.maneuver_payload(
                3.190, 2.400, pef_l_s=6.00, back_extrapolated_volume_ml=160,
                expiratory_time_s=15.0,
            ),
            lab.tech1,
        )
        smaller_blow = f.maneuver_payload(
            3.180, 2.380, pef_l_s=5.90, back_extrapolated_volume_ml=160,
            expiratory_time_s=15.0,
        )

        validate_error(
            api.create_maneuver(session["id"], smaller_blow, lab.tech1),
            ERR_COACHING_NOTE_REQUIRED,
        )
        coached = fx.append_maneuver(
            api,
            session["id"],
            dict(smaller_blow, coaching_note=LATE_START_COACHING),
            lab.tech1,
        )

        assert coached["bev_limit_ml"] == 159
        assert_maneuver_unacceptable(coached, ["BEV_EXCEEDED"])
        assert coached["maneuver_index"] == 2, (
            "the refused attempt persisted nothing, so it consumed no index"
        )

        study = validate_success(api.get_test_session(session["id"], lab.tech1))
        assert study["acceptable_maneuver_count"] == 1
        assert study["quality_grade"] == "D"
        assert_3dp(study["best_fev1_l"], 2.400)
        assert study["repeatability_delta_ml"] is None
        assert study["session_status"] == "IN_PROGRESS"


ONE_MILLILITRE_LOOSER_SERIES = [
    f.maneuver_payload(3.200, 2.400, pef_l_s=6.00, back_extrapolated_volume_ml=100,
                       expiratory_time_s=15.0),
    f.maneuver_payload(3.150, 2.249, pef_l_s=5.80, back_extrapolated_volume_ml=120,
                       expiratory_time_s=16.0),
    f.maneuver_payload(3.100, 2.200, pef_l_s=5.60, back_extrapolated_volume_ml=110,
                       expiratory_time_s=15.5),
]


def _two_studies_differing_by_one_millilitre(api):
    """Two studies whose only difference is the second effort's FEV1.

    Both collect three acceptable efforts over the same FVC series, so the FVC
    repeatability delta is identical and only the FEV1 delta can separate them.
    """
    lab = fx.build_lab(api, device_codes=("SPIRO-1", "SPIRO-2"))
    tight = fx.build_session_with_maneuvers(api, lab)
    loose = fx.build_session_with_maneuvers(
        api,
        lab,
        payloads=ONE_MILLILITRE_LOOSER_SERIES,
        device_id=lab.device_ids[1],
        scheduled_start_at="2026-08-03T10:00:00Z",
        scheduled_end_at="2026-08-03T10:30:00Z",
    )
    return lab, tight, loose


class TestRepeatabilityGradeBoundary:
    """The tight repeatability tolerance is inclusive at 150 millilitres."""

    def test_a_delta_of_exactly_one_hundred_fifty_millilitres_holds_grade_a(self, api):
        """2.400 L against 2.250 L is 150 mL, and 150 is inside the tolerance.

        PRD 3.6: "Grade `A` requires `acceptable_maneuver_count` of at least 3
        with `repeatability_delta_ml` at or below 150 millilitres **and**
        `fvc_repeatability_delta_ml` at or below 150 millilitres."

        Design: Difficulty/boundary_precision_check/repeatability_delta_exactly_150_ml_holds_grade_a_at_151_drops_to_b
        """
        lab, tight, _ = _two_studies_differing_by_one_millilitre(api)

        closed = fx.finalize_quality(api, tight["id"], lab.tech1)

        assert closed["acceptable_maneuver_count"] == 3
        assert closed["repeatability_delta_ml"] == 150
        assert closed["quality_grade"] == "A"
        assert closed["fvc_repeatability_delta_ml"] == 50
        assert_3dp(closed["best_fev1_l"], 2.400)
        assert closed["session_status"] == "ACCEPTED"
        assert_1dp(closed["fev1_pct_predicted"], 60.0)
        assert_1dp(closed["fvc_pct_predicted"], 66.7)
        assert_3dp(closed["fev1_fvc_ratio"], 0.750)

    def test_one_millilitre_further_apart_drops_the_study_to_grade_b(self, api):
        """A delta of 151 mL misses grade A and lands on the looser rung below it.

        PRD 3.6: "Grade `B` requires `acceptable_maneuver_count` of at least 3
        with `repeatability_delta_ml` at or below 200 millilitres, and consults
        the FVC delta not at all."

        Design: Difficulty/boundary_precision_check/repeatability_delta_exactly_150_ml_holds_grade_a_at_151_drops_to_b
        """
        lab, tight, loose = _two_studies_differing_by_one_millilitre(api)

        closed_tight = fx.finalize_quality(api, tight["id"], lab.tech1)
        closed_loose = fx.finalize_quality(api, loose["id"], lab.tech1)

        assert closed_loose["acceptable_maneuver_count"] == 3
        assert closed_loose["repeatability_delta_ml"] == 151
        assert closed_loose["quality_grade"] == "B"
        assert closed_loose["session_status"] == "ACCEPTED", (
            "grades A and B both accept the study"
        )

        assert closed_loose["fvc_repeatability_delta_ml"] == (
            closed_tight["fvc_repeatability_delta_ml"]
        )
        assert_3dp(closed_loose["best_fev1_l"], 2.400)
        assert closed_loose["quality_grade"] != closed_tight["quality_grade"], (
            "one millilitre in the second effort is the only difference between them"
        )
