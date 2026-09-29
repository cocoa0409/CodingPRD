"""The quorum is two tests, and trimming can starve a panel that passed the first."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

WIDE_TRIM_PROGRAM = {"form_length": 4, "min_panelists": 3, "panel_trim_count": 2}
FIVE_PANELISTS = ["pan-1", "pan-2", "pan-3", "pan-4", "pan-5"]
FOUR_RATINGS = [("pan-1", 0.4), ("pan-2", 0.85), ("pan-4", 0.5), ("pan-5", 0.7)]
MEDIAN_RATING = [("pan-3", 0.6)]


def _four_position_form_with_four_ratings(api):
    """A four-item form on a programme that trims two means from each end, with
    four of its five panellists rated.
    """
    program = fx.active_program(api, **WIDE_TRIM_PROGRAM)
    item_ids = [fx.approved_item(api, program["id"], stem=f"Angoff item {n}")["id"]
                for n in range(1, 5)]
    form = fx.assembled_form(api, program["id"], item_ids, FIVE_PANELISTS,
                             form_code="CPX-F4")
    rated = fx.submit_ratings(api, form["id"], FOUR_RATINGS)
    return program, form, rated


class TestQuorumSurvivorBoundary:
    """Four ratings clear ``min_panelists`` and still leave nothing to average."""

    def test_four_ratings_clear_min_panelists_but_leave_zero_survivors(self, api):
        """Four entries are at least the three the programme demands, yet four less
        twice a trim of two is zero, so the second quorum test refuses adoption.

        PRD §3.5: "Quorum is then tested twice: the number of entries in
        `panel_ratings` must be at least the program's `min_panelists`, and that
        number less twice the program's `panel_trim_count` must be at least 1; either
        failure is `ERR_PANEL_QUORUM_NOT_MET`."

        Design: Difficulty/boundary_precision_check/angoff_quorum_boundary_four_ratings_leave_zero_survivors_and_five_leave_exactly_one
        """
        program, form, rated = _four_position_form_with_four_ratings(api)
        assert program["min_panelists"] == 3
        assert program["panel_trim_count"] == 2
        assert len(rated["panel_ratings"]) == 4

        refused = api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(rated["version"],
                                                  adoption_note="attempt with four ratings"),
            fx.PSYCHOMETRICIAN)

        validate_error(refused, ApiErrorId.ERR_PANEL_QUORUM_NOT_MET.value, 422)

    def test_starved_adoption_leaves_the_form_and_its_cut_score_untouched(self, api):
        """The refusal writes nothing: the form is still awaiting a panel and holds
        neither a trimmed mean nor a cut score.

        PRD §3.5: "Adoption moves the form `ASSEMBLED → CUT_SCORE_SET`, or leaves it
        in `CUT_SCORE_SET` when it is a re-adoption after further ratings, sets
        `panel_status` to `ADOPTED`, and increments the form's `version` by 1."

        Design: Difficulty/boundary_precision_check/angoff_quorum_boundary_four_ratings_leave_zero_survivors_and_five_leave_exactly_one
        """
        _program, form, rated = _four_position_form_with_four_ratings(api)

        api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(rated["version"]), fx.PSYCHOMETRICIAN)

        after = fx.read_form(api, form["id"])
        assert after["status"] == "ASSEMBLED"
        assert after["panel_status"] == "OPEN"
        assert after["raw_cut_score"] is None
        assert after["mean_expected_pass_rate"] is None
        ax.assert_exam_form(after)

    def test_fifth_rating_makes_exactly_one_mean_survive_the_trim(self, api):
        """The fifth judgement is appended and the form advances one version, which is
        the version the next adoption must name.

        PRD §3.5: "Each accepted rating is appended to `panel_ratings` as a record of
        the `panelist_user_id`, the `mean_expected_pass_rate`, and a `submitted_at`
        stamp from the logical clock."

        PRD §2.4: "`version` is an integer that starts at 1 when the resource is
        created and increments by 1 on every mutation of that record, including
        mutations reached indirectly through a cascade."

        Design: Difficulty/boundary_precision_check/angoff_quorum_boundary_four_ratings_leave_zero_survivors_and_five_leave_exactly_one
        """
        _program, form, rated = _four_position_form_with_four_ratings(api)
        four_rating_version = rated["version"]

        five_rated = fx.submit_ratings(api, form["id"], MEDIAN_RATING)

        assert len(five_rated["panel_ratings"]) == 5
        assert five_rated["version"] == four_rating_version + 1

    def test_five_ratings_adopt_on_the_single_surviving_median(self, api):
        """With one survivor the trimmed mean is that median alone, not the mean of
        all five, and the form takes its cut score.

        PRD §3.5: "Sort those means in ascending order, keeping insertion order among
        ties, then discard the lowest `panel_trim_count` means and the highest
        `panel_trim_count` means — exactly one from each end under the default, and
        the discard happens even when the extreme values are equal to their
        neighbours."

        PRD §3.5: "The trimmed mean is the sum of the surviving means divided by the
        trimmed size, rounded half up to six decimal places, and it is written to the
        form's `mean_expected_pass_rate`."

        Design: Difficulty/boundary_precision_check/angoff_quorum_boundary_four_ratings_leave_zero_survivors_and_five_leave_exactly_one
        """
        _program, form, _rated = _four_position_form_with_four_ratings(api)
        five_rated = fx.submit_ratings(api, form["id"], MEDIAN_RATING)

        adopted = validate_success(api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(five_rated["version"],
                                                  adoption_note="attempt with five ratings"),
            fx.PSYCHOMETRICIAN), 200)

        assert adopted["status"] == "CUT_SCORE_SET"
        assert adopted["panel_status"] == "ADOPTED"
        assert adopted["scored_item_count"] == 4
        assert float(adopted["mean_expected_pass_rate"]) == pytest.approx(0.6, abs=1e-6)
        assert float(adopted["mean_expected_pass_rate"]) != pytest.approx(0.61, abs=1e-6)
        ax.assert_standard_setting_precision(adopted["mean_expected_pass_rate"])

    def test_lone_survivor_gives_zero_standard_error_and_a_raw_cut_of_two(self, api):
        """A single survivor has no dispersion, so the multiplier subtracts nothing and
        the raw cut is the trimmed mean across the four scored positions, inside the
        clamp band.

        PRD §3.5: "The standard error of that trimmed mean is zero when exactly one
        mean survives trimming; otherwise take the sample variance of the surviving
        means".

        PRD §3.5: "Finally clamp it: the lower bound is forty percent of
        `scored_item_count` rounded up to a whole number, the upper bound is ninety
        percent of `scored_item_count` rounded down to a whole number, and
        `raw_cut_score` is the unclamped raw cut raised to the lower bound if it falls
        below and then lowered to the upper bound if it rises above."

        Design: Difficulty/boundary_precision_check/angoff_quorum_boundary_four_ratings_leave_zero_survivors_and_five_leave_exactly_one
        """
        _program, form, _rated = _four_position_form_with_four_ratings(api)
        five_rated = fx.submit_ratings(api, form["id"], MEDIAN_RATING)

        adopted = validate_success(api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(five_rated["version"]),
            fx.PSYCHOMETRICIAN), 200)

        assert adopted["raw_cut_score"] == 2
        assert isinstance(adopted["raw_cut_score"], int)

    def test_the_adopting_psychometrician_is_not_on_the_panel(self, api):
        """Adoption succeeds because the adopter rates nothing, which keeps the
        separation-of-duties bar out of the quorum picture.

        PRD §3.5: "The form must be in `ASSEMBLED` or `CUT_SCORE_SET` status —
        otherwise `ERR_INVALID_STATE` — and the adopting user must not appear in the
        form's `panelist_user_ids`, or the adoption is refused with
        `ERR_SEGREGATION_OF_DUTIES`: nobody ratifies their own judgement."

        Design: Difficulty/boundary_precision_check/angoff_quorum_boundary_four_ratings_leave_zero_survivors_and_five_leave_exactly_one
        """
        _program, form, _rated = _four_position_form_with_four_ratings(api)
        assert form["panelist_user_ids"] == FIVE_PANELISTS
        assert "psy-1" not in form["panelist_user_ids"]
        five_rated = fx.submit_ratings(api, form["id"], MEDIAN_RATING)

        adopted = validate_success(api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(five_rated["version"]),
            fx.PSYCHOMETRICIAN), 200)

        assert adopted["panel_status"] == "ADOPTED"
