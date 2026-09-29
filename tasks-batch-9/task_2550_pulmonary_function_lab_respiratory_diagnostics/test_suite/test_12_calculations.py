"""The derived numbers, each pinned to the rule that produces it.

A withholding window is an aggregate maximum over per-hold anchors, an equation
set is chosen by a declared ranking rather than by publication order, the
interpretation boundaries sit on the normal side, the percentages round half up
at their own declared places, and a provocation protocol may land exactly on its
dose ceiling.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CHALLENGE_CONTRAINDICATED,
    ERR_NO_REFERENCE_EQUATION,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_instant,
    assert_listing_ids,
    assert_page,
    assert_signed_interpretation,
    assert_version_is,
)
from test_helpers.test_users import LAB_MANAGER

EARLY_MORNING = "2026-08-01T06:00:00Z"


def _submitted_order_on_two_medication_classes(api):
    """An order declaring a short-acting and a long-acting drug, awaiting holds."""
    fx.set_clock(api, EARLY_MORNING)
    roster = fx.build_roster(api)
    patient = fx.register_patient(api)
    order = fx.draft_and_submit_order(
        api,
        patient["id"],
        roster.doc1,
        current_medication_classes=("SABA", "LAMA"),
    )
    return roster, order


def _issue_hold(api, order_id, medication_class, expected_order_version, tech_headers):
    return validate_success(
        api.create_medication_hold(
            order_id,
            f.medication_hold_payload(medication_class, expected_order_version),
            tech_headers,
        ),
        expected_status=201,
    )


class TestMedicationHoldWindows:
    """The order's release instant is the maximum over its live holds."""

    def test_the_longest_acting_class_governs_the_whole_order(self, api):
        """The six-hour window issued last does not shorten the order's release.

        PRD 3.4: "The order's own `hold_release_at` is then recomputed as the
        **maximum** of `instructed_at` plus that class's hold hours, taken over
        every hold on the order whose `status` is `PENDING` or `ATTESTED`."

        Design: Corner/calculations/medication_hold_release_takes_the_longest_acting_class_window
        """
        roster, order = _submitted_order_on_two_medication_classes(api)
        assert order["status"] == "SUBMITTED"
        assert order["hold_release_at"] is None

        long_acting = _issue_hold(api, order["id"], "LAMA", order["version"], roster.tech1)
        after_first = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        short_acting = _issue_hold(
            api, order["id"], "SABA", after_first["version"], roster.tech1
        )

        assert long_acting["required_hold_hours"] == 36
        assert_instant(long_acting["instructed_at"], EARLY_MORNING)
        assert_instant(long_acting["release_at"], "2026-08-02T18:00:00Z")
        assert short_acting["required_hold_hours"] == 6
        assert_instant(short_acting["instructed_at"], EARLY_MORNING)
        assert_instant(short_acting["release_at"], "2026-08-01T12:00:00Z")
        assert long_acting["status"] == "PENDING"
        assert short_acting["status"] == "PENDING"

        final = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert final["status"] == "MED_HOLD_ISSUED"
        assert_instant(final["hold_release_at"], "2026-08-02T18:00:00Z")
        assert_version_is(final, 4)

    def test_each_window_runs_from_its_own_instruction_across_a_replacement(self, api):
        """Replacing one class restarts that window and leaves the other alone.

        PRD 3.4: "Because each hold keeps the `instructed_at` it was originally
        issued with, replacing one class's hold restarts only that class's window
        and leaves the others exactly where they were; and because the aggregate
        is a maximum, the single longest-acting class governs the whole order."

        Design: Corner/calculations/each_hold_window_runs_from_its_own_instructed_at_across_a_supersession
        """
        roster, order = _submitted_order_on_two_medication_classes(api)
        first_lama = _issue_hold(api, order["id"], "LAMA", order["version"], roster.tech1)

        fx.set_clock(api, "2026-08-01T08:00:00Z")
        at_eight = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        saba = _issue_hold(api, order["id"], "SABA", at_eight["version"], roster.tech1)
        assert_instant(saba["release_at"], "2026-08-01T14:00:00Z")

        before = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert_instant(before["hold_release_at"], "2026-08-02T18:00:00Z")

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        replacement = _issue_hold(
            api, order["id"], "LAMA", before["version"], roster.tech1
        )
        assert_instant(replacement["instructed_at"], "2026-08-02T00:00:00Z")
        assert_instant(replacement["release_at"], "2026-08-03T12:00:00Z")

        superseded = validate_success(
            api.get_medication_hold(first_lama["id"], LAB_MANAGER)
        )
        assert superseded["status"] == "SUPERSEDED"
        untouched = validate_success(api.get_medication_hold(saba["id"], LAB_MANAGER))
        assert_instant(untouched["release_at"], "2026-08-01T14:00:00Z")
        assert untouched["status"] == "PENDING"

        after = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert_instant(after["hold_release_at"], "2026-08-03T12:00:00Z")

        _, meta = validate_paginated(
            api.list_medication_holds(LAB_MANAGER, order_id=order["id"])
        )
        assert_page(meta, total_count=3, has_more=False)


BOUNDARY_SERIES = [
    f.maneuver_payload(3.840, 2.688, pef_l_s=6.40, back_extrapolated_volume_ml=100,
                       expiratory_time_s=15.0),
    f.maneuver_payload(3.800, 2.650, pef_l_s=6.20, back_extrapolated_volume_ml=120,
                       expiratory_time_s=16.0),
    f.maneuver_payload(3.760, 2.610, pef_l_s=6.00, back_extrapolated_volume_ml=110,
                       expiratory_time_s=15.5),
]

HALF_UP_SERIES = [
    f.maneuver_payload(3.200, 2.310, pef_l_s=6.00, back_extrapolated_volume_ml=100,
                       expiratory_time_s=15.0),
    f.maneuver_payload(3.150, 2.250, pef_l_s=5.80, back_extrapolated_volume_ml=120,
                       expiratory_time_s=16.0),
    f.maneuver_payload(3.100, 2.200, pef_l_s=5.60, back_extrapolated_volume_ml=110,
                       expiratory_time_s=15.5),
]


class TestInterpretationBoundaries:
    """A study sitting exactly on both boundaries is normal on both arms."""

    def test_a_ratio_and_an_fvc_exactly_on_their_limits_read_as_normal(self, api):
        """The normal verdict short-circuits a severity the FEV1 would have earned.

        PRD 3.9: "Both comparisons put the boundary on the normal side, so a
        ratio exactly equal to `ratio_lln` and an `fvc_pct_predicted` of exactly
        80.0 are both normal and together yield `NORMAL`." and "`severity` is
        then graded on `fev1_pct_predicted`, except that a `NORMAL` pattern
        always carries `severity` `NONE` regardless of the number."

        Design: Corner/calculations/interpretation_pattern_is_normal_when_ratio_and_fvc_sit_exactly_on_their_boundaries
        """
        lab = fx.build_lab(api, interpreters=1)
        accepted = fx.build_accepted_session(api, lab, payloads=BOUNDARY_SERIES)

        assert_3dp(accepted["fev1_fvc_ratio"], 0.700)
        assert_1dp(accepted["fvc_pct_predicted"], 80.0)
        assert_1dp(accepted["fev1_pct_predicted"], 67.2)
        assert accepted["quality_grade"] == "A"
        assert accepted["acceptable_maneuver_count"] == 3
        assert accepted["repeatability_delta_ml"] == 38
        assert accepted["fvc_repeatability_delta_ml"] == 40

        report = fx.assign_report(api, accepted["id"], accepted["version"])
        signed = fx.sign_report(
            api, report["id"], lab.roster.rad1, "Spirometry within normal limits."
        )

        assert_signed_interpretation(signed, "NORMAL", "NONE")
        assert signed["severity"] != "MODERATE"

    def test_the_percentages_and_the_ratio_round_half_up_at_their_own_places(self, api):
        """57.75 becomes 57.8 and 0.721875 becomes 0.722, not 57.7 and 0.721.

        PRD 2.6: "Every rounded quantity in this specification uses the
        **round-half-up** convention: a value exactly on the midpoint rounds away
        from zero, so 159.5 millilitres becomes 160 and 3.0035 becomes 3.004 at
        three decimal places."

        Design: Corner/calculations/percent_predicted_and_ratio_round_half_up_at_their_declared_places
        """
        lab = fx.build_lab(api)
        session = fx.build_session_with_maneuvers(api, lab, payloads=HALF_UP_SERIES)

        rolled_up = validate_success(api.get_test_session(session["id"], LAB_MANAGER))

        assert_1dp(rolled_up["fev1_pct_predicted"], 57.8)
        assert_1dp(rolled_up["fvc_pct_predicted"], 66.7)
        assert_3dp(rolled_up["fev1_fvc_ratio"], 0.722)
        assert rolled_up["repeatability_delta_ml"] == 60
        assert rolled_up["fvc_repeatability_delta_ml"] == 50
        assert_3dp(rolled_up["best_fev1_l"], 2.310)
        assert_3dp(rolled_up["best_fvc_l"], 3.200)
        assert rolled_up["acceptable_maneuver_count"] == 3


def _laboratory_without_a_published_equation(api):
    """A programmed spirometer, a 45-year-old male patient and a READY order."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    roster = fx.build_roster(api)
    device = fx.register_device(api, "SPIRO-1", "SPIROMETRY")
    fx.run_daily_quality_program(api, device["id"], roster.tech1, roster.bcs_id)
    patient = fx.register_patient(api)
    order = fx.draft_and_submit_order(api, patient["id"], roster.doc1)
    return roster, device["id"], patient, order


def _attempt_to_schedule(api, roster, order_id, device_id):
    return api.create_test_session(
        f.test_session_payload(
            order_id, device_id, "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z"
        ),
        roster.tech1,
    )


class TestReferenceEquationSelector:
    """The selector ranks its pool rather than taking the first publication."""

    def test_the_narrower_age_band_wins_over_the_set_published_first(self, api):
        """The predicted FEV1 shows which of the two eligible sets was pinned.

        PRD 3.5: "The surviving candidates are ranked by the width of the age
        band, computed as `applicable_age_max` minus `applicable_age_min`,
        ascending — a narrower band is the better-fitting reference — then by
        `lln_percentile` ascending, which breaks ties toward the more
        conservative lower limit, and finally by `created_at` ascending. The
        first candidate wins."

        Design: Corner/calculations/reference_equation_selection_prefers_the_narrower_age_band
        """
        roster, device_id, _, order = _laboratory_without_a_published_equation(api)
        fx.publish_reference_equation(
            api,
            equation_code="GLI-WIDE",
            applicable_age_min=18,
            applicable_age_max=80,
            a_fev1=2.000,
        )
        narrow = fx.publish_reference_equation(
            api,
            equation_code="GLI-NARROW",
            applicable_age_min=40,
            applicable_age_max=60,
            a_fev1=2.300,
        )

        session = validate_success(
            _attempt_to_schedule(api, roster, order["id"], device_id),
            expected_status=201,
        )

        assert session["reference_equation_id"] == narrow["id"]
        assert_3dp(session["predicted_fev1_l"], 4.000)
        assert session["predicted_fev1_l"] != 3.700, (
            "3.700 is what the wider, earlier-published set would have predicted"
        )
        assert_3dp(session["predicted_fvc_l"], 4.800)
        assert_3dp(session["ratio_lln"], 0.700)
        assert_3dp(session["lln_fev1_l"], 3.145)

        rows, meta = validate_paginated(
            api.list_test_sessions(LAB_MANAGER, reference_equation_id=narrow["id"])
        )
        assert_page(meta, total_count=1, has_more=False)
        assert_listing_ids(rows, [session["id"]])

    def test_a_pool_that_matches_only_one_clause_each_is_empty(self, api):
        """Neither the wrong-sex set nor the wrong-age set is a fallback.

        PRD 3.5: "The selector considers every `ReferenceEquationSet` whose
        `status` is `ACTIVE`, whose `modality_scope` contains the device's
        `modality`, whose inclusive age band from `applicable_age_min` through
        `applicable_age_max` contains the patient's `age_years`, and whose
        `sex_scope` either equals the patient's `sex` or is `ANY`. An empty pool
        reports `ERR_NO_REFERENCE_EQUATION`."

        Design: Corner/calculations/equation_pool_excludes_sets_outside_the_age_or_sex_scope
        """
        roster, device_id, _, order = _laboratory_without_a_published_equation(api)
        fx.publish_reference_equation(
            api,
            equation_code="GLI-F",
            sex_scope="FEMALE",
            applicable_age_min=40,
            applicable_age_max=60,
        )
        fx.publish_reference_equation(
            api,
            equation_code="GLI-YOUNG",
            sex_scope="MALE",
            applicable_age_min=18,
            applicable_age_max=30,
        )

        validate_error(
            _attempt_to_schedule(api, roster, order["id"], device_id),
            ERR_NO_REFERENCE_EQUATION,
        )
        still_ready = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert still_ready["status"] == "READY"

        in_scope = fx.publish_reference_equation(api)

        session = validate_success(
            _attempt_to_schedule(api, roster, order["id"], device_id),
            expected_status=201,
        )
        assert session["reference_equation_id"] == in_scope["id"]
        assert_3dp(session["predicted_fev1_l"], 4.000)
        assert_3dp(session["lln_fev1_l"], 3.145)


def _challenge_study(api, lab, best_fev1_l, start, end):
    """An IN_PROGRESS methacholine study whose single blow fixes its best FEV1."""
    session = fx.build_scheduled_session(
        api,
        lab,
        scheduled_start_at=start,
        scheduled_end_at=end,
        indication_code="ASTHMA_DIAGNOSIS",
        challenge_type="METHACHOLINE",
    )
    fx.append_maneuver(
        api, session["id"], f.maneuver_payload(3.200, best_fev1_l), lab.tech1
    )
    return validate_success(api.get_test_session(session["id"], LAB_MANAGER))


class TestChallengeArmingThreshold:
    """Sixty percent of predicted is admitted; a hair below it is not."""

    def test_exactly_sixty_percent_of_predicted_may_be_provoked(self, api):
        """Ten millilitres of best FEV1 separates an arming from a refusal.

        PRD 3.7: "The study's `fev1_pct_predicted` must be at least 60.0 percent,
        and a study whose best pre-bronchodilator FEV1 sits below that may never
        be provoked whatever the order asked for, reporting
        `ERR_CHALLENGE_CONTRAINDICATED`."

        Design: Corner/calculations/challenge_min_fev1_constant_admits_exactly_sixty_percent_of_predicted
        """
        lab = fx.build_lab(api)
        lot = fx.receive_rescue_lot(api)
        on_the_line = _challenge_study(
            api, lab, 2.400, "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z"
        )
        below_the_line = _challenge_study(
            api, lab, 2.390, "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z"
        )

        assert_1dp(on_the_line["fev1_pct_predicted"], 60.0)
        assert_1dp(below_the_line["fev1_pct_predicted"], 59.8)

        armed = fx.arm_challenge_run(api, on_the_line["id"], lot["id"], lab.tech1)
        assert armed["status"] == "ARMED"
        assert_3dp(armed["baseline_fev1_l"], 2.400)

        validate_error(
            api.create_challenge_run(
                below_the_line["id"], f.challenge_run_payload(lot["id"]), lab.tech1
            ),
            ERR_CHALLENGE_CONTRAINDICATED,
        )

        ledger = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert ledger["doses_reserved"] == 4, "the refused arming reserved nothing"

        _, meta = validate_paginated(
            api.list_challenge_runs(LAB_MANAGER, session_id=below_the_line["id"])
        )
        assert_page(meta, total_count=0, has_more=False)


class TestCumulativeDoseCeiling:
    """A protocol that lands exactly on the ceiling completes rather than fails."""

    def test_five_steps_reaching_exactly_four_hundred_units_complete_negative(self, api):
        """The ceiling comparison is strict, so 400 units is a negative challenge.

        PRD 3.7: "When instead the fall is below 20.00 percent and the post-step
        `cumulative_dose_units` has reached exactly 400, the patient has taken the
        full protocol without reacting: `status` becomes `COMPLETED_NEGATIVE` with
        `stop_reason` `MAX_CUMULATIVE_DOSE_REACHED` and `pc20_dose_units` stays
        null."

        Design: Corner/calculations/cumulative_challenge_dose_lands_exactly_on_the_maximum
        """
        lab = fx.build_lab(api)
        lot = fx.receive_rescue_lot(api)
        session = _challenge_study(
            api, lab, 2.400, "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z"
        )
        run = fx.arm_challenge_run(api, session["id"], lot["id"], lab.tech1)

        latest = None
        for dose_units, post_step_fev1_l in (
            (25, 2.380), (50, 2.370), (100, 2.360), (200, 2.350), (25, 2.340)
        ):
            latest = validate_success(
                api.create_challenge_step(
                    run["id"],
                    f.challenge_step_payload(dose_units, post_step_fev1_l),
                    lab.tech1,
                )
            )

        assert_3dp(latest["cumulative_dose_units"], 400.000)
        assert latest["status"] == "COMPLETED_NEGATIVE"
        assert latest["stop_reason"] == "MAX_CUMULATIVE_DOSE_REACHED"
        assert latest["pc20_dose_units"] is None
        assert latest["current_step_index"] == 5
        assert_2dp(latest["max_fev1_drop_pct"], 2.50)
        assert latest["rescue_doses_administered"] == 4

        ledger = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert ledger["doses_remaining"] == 6
        assert ledger["doses_reserved"] == 0
        assert ledger["status"] == "STOCKED"

        still_live = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert still_live["session_status"] == "IN_PROGRESS"
