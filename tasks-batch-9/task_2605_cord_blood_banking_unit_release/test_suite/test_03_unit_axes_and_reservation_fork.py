"""State that does not advance in lockstep: a unit's three axes and a hold's two branches."""

import pytest

from test_helpers import (
    api_client,
    assert_created_at_ascending,
    build_bank_scenario,
    build_listed_public_scenario,
    complete_processing_run,
    confirm_reservation,
    cryopreserve,
    decline_reservation,
    determine_eligibility,
    expected_pre_cryo_dose,
    make_technologist_headers,
    place_reservation,
    read_listing,
    read_reservation,
    read_tank,
    read_unit,
    record_quality_test,
    set_clock,
    start_processing_run,
    validate_success,
)


def _received_private_unit():
    """A private-family unit freshly minted by receipt, before any processing run."""
    return build_bank_scenario(
        stage="received",
        tank_code="TANK-C",
        capacity_slots=5,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Axes Parent",
        collection_site_code="SITE-03",
        consent_document_hash="hash-axes-v1",
    )


class TestUnitAxesEvolveIndependently:
    def test_a_failed_run_reverts_only_the_processing_axis(self):
        """A failed reduction rewinds processing and leaves the other two axes alone.

        "`IN_PROGRESS → FAILED` reverts the unit `PROCESSING → RECEIVED` and sets the unit's
        `post_processing_volume_ml` back to null, precisely so that a second run may be
        opened on a unit whose first reduction went wrong."

        Design: Difficulty/non_linear_state_machine/unit_three_axes_evolve_independently
        """
        scenario = _received_private_unit()
        unit_id = scenario["unit"]["id"]

        run = start_processing_run(unit_id, method="HES_SEDIMENTATION", pre_tnc_millions=1100)
        failed = complete_processing_run(
            run["id"], outcome="FAILED", post_volume_ml=30.0, post_tnc_millions=500
        )

        assert failed["status"] == "FAILED"
        assert failed["tnc_recovery_pct"] == pytest.approx(45.45, abs=0.01)
        assert failed["volume_reduction_pct"] == pytest.approx(71.43, abs=0.01)

        unit = read_unit(unit_id)
        assert unit["processing_status"] == "RECEIVED"
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["eligibility_status"] == "PENDING"
        assert unit["post_processing_volume_ml"] is None

    def test_both_outcomes_compute_both_recovery_metrics(self):
        """A failed run is still a measured run, and the second run measures again.

        "`tnc_recovery_pct` is the post-reduction count divided by the pre-reduction count,
        multiplied by 100, rounded half up to 2 decimal places."

        Design: Difficulty/non_linear_state_machine/unit_three_axes_evolve_independently
        """
        scenario = _received_private_unit()
        unit_id = scenario["unit"]["id"]

        first = start_processing_run(unit_id, method="HES_SEDIMENTATION", pre_tnc_millions=1100)
        complete_processing_run(
            first["id"], outcome="FAILED", post_volume_ml=30.0, post_tnc_millions=500
        )
        second = start_processing_run(
            unit_id, method="AUTOMATED_SEPARATION", pre_tnc_millions=1100
        )
        completed = complete_processing_run(
            second["id"], outcome="COMPLETED", post_volume_ml=25.0, post_tnc_millions=1000
        )

        assert completed["status"] == "COMPLETED"
        assert completed["tnc_recovery_pct"] == pytest.approx(90.91, abs=0.01)
        assert completed["volume_reduction_pct"] == pytest.approx(76.19, abs=0.01)

        runs = validate_success(
            api_client.list_unit_processing_runs(unit_id, make_technologist_headers())
        )
        assert len(runs) == 2
        assert_created_at_ascending(runs)

    def test_characterisation_scores_the_unit_without_moving_availability_or_eligibility(self):
        """Writing the post-processing test recomputes the score and nothing else.

        "Writing a `POST_PROCESSING` test also republishes the unit's summary counts"

        Design: Difficulty/non_linear_state_machine/unit_three_axes_evolve_independently
        """
        scenario = _received_private_unit()
        unit_id = scenario["unit"]["id"]

        run = start_processing_run(unit_id, method="AUTOMATED_SEPARATION", pre_tnc_millions=1100)
        complete_processing_run(
            run["id"], outcome="COMPLETED", post_volume_ml=25.0, post_tnc_millions=1000
        )
        record_quality_test(
            unit_id,
            test_kind="POST_PROCESSING",
            tnc_millions=1000,
            cd34_thousands=2400,
            viability_pct=88.0,
            volume_ml=25.0,
            sterility_result="NEGATIVE",
        )

        unit = read_unit(unit_id)
        assert unit["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)
        assert unit["processing_status"] == "VOLUME_REDUCED"
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["eligibility_status"] == "PENDING"

    def test_determination_then_cryopreservation_move_one_axis_each(self):
        """Determination moves eligibility alone; the freeze then moves the other two.

        "a `PRIVATE_FAMILY` unit moves `UNAVAILABLE → PRIVATE_STORED` and is immediately part
        of billable inventory"

        Design: Difficulty/non_linear_state_machine/unit_three_axes_evolve_independently
        """
        scenario = _received_private_unit()
        unit_id = scenario["unit"]["id"]

        run = start_processing_run(unit_id, method="AUTOMATED_SEPARATION", pre_tnc_millions=1100)
        complete_processing_run(
            run["id"], outcome="COMPLETED", post_volume_ml=25.0, post_tnc_millions=1000
        )
        record_quality_test(
            unit_id,
            test_kind="POST_PROCESSING",
            tnc_millions=1000,
            cd34_thousands=2400,
            viability_pct=88.0,
            volume_ml=25.0,
        )

        determine_eligibility(unit_id, director_user_id="md-001")
        after_determination = read_unit(unit_id)
        assert after_determination["eligibility_status"] == "ELIGIBLE"
        assert after_determination["processing_status"] == "VOLUME_REDUCED"
        assert after_determination["availability_status"] == "UNAVAILABLE"

        cryopreserve(
            unit_id, scenario["tank"]["id"], slot_code="C-01", freeze_at="2026-08-11T02:00:00Z"
        )
        after_freeze = read_unit(unit_id)
        assert after_freeze["processing_status"] == "CRYOPRESERVED"
        assert after_freeze["availability_status"] == "PRIVATE_STORED"
        assert after_freeze["eligibility_status"] == "ELIGIBLE"

        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 1


def _listed_unit_with_two_holds():
    """A listed public unit carrying two pending holds over non-touching windows."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-D",
        capacity_slots=5,
        primary_parent_name="Fork Parent",
        collection_site_code="SITE-04",
        hla_typing_consent=True,
        consent_document_hash="hash-fork-v1",
        slot_code="D-01",
    )
    set_clock("2026-08-11T03:00:00Z")
    first = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center One",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    second = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-002",
        requesting_center_name="Center Two",
        patient_weight_kg=40.0,
        patient_hla_match_count=5,
        hold_from="2026-09-06T00:00:00Z",
        hold_until="2026-09-10T00:00:00Z",
    )
    scenario["first_hold"] = first
    scenario["second_hold"] = second
    return scenario


class TestReservationForkAndJoin:
    def test_declining_changes_nothing_else_in_the_system(self):
        """The decline branch is scoped to the hold it is aimed at.

        "the hold moves `PENDING_CONFIRMATORY → DECLINED`, `cancellation_reason_code` is set
        to that `reason_code`, and **nothing else in the system changes**."

        Design: Difficulty/non_linear_state_machine/reservation_fork_join_divergent_side_effect_sets
        """
        scenario = _listed_unit_with_two_holds()

        declined = decline_reservation(
            scenario["second_hold"]["id"],
            reason_code="ALTERNATIVE_UNIT_SELECTED",
            center_user_id="tc-002",
        )

        assert declined["status"] == "DECLINED"
        assert declined["cancellation_reason_code"] == "ALTERNATIVE_UNIT_SELECTED"
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "LISTED"
        assert read_listing(scenario["listing"]["id"])["listing_status"] == "ACTIVE"
        assert (
            read_reservation(scenario["first_hold"]["id"], center_user_id="tc-001")["status"]
            == "PENDING_CONFIRMATORY"
        )

    def test_confirming_reserves_the_unit_and_matches_its_listing(self):
        """The confirm branch fans out across the unit and its listing.

        "the unit moves `LISTED → RESERVED` or `PRIVATE_STORED → RESERVED`, the unit's
        registry listing in `ACTIVE` moves to `MATCHED`"

        Design: Difficulty/non_linear_state_machine/reservation_fork_join_divergent_side_effect_sets
        """
        scenario = _listed_unit_with_two_holds()
        decline_reservation(
            scenario["second_hold"]["id"],
            reason_code="ALTERNATIVE_UNIT_SELECTED",
            center_user_id="tc-002",
        )

        confirmed = confirm_reservation(
            scenario["first_hold"]["id"],
            intended_transplant_date="2026-09-03",
            center_user_id="tc-001",
        )

        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["intended_transplant_date"].startswith("2026-09-03")
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "RESERVED"
        assert read_listing(scenario["listing"]["id"])["listing_status"] == "MATCHED"

    def test_the_two_holds_carry_their_own_pre_freeze_doses(self):
        """Each hold's dose reflects its own patient weight against the same unit counts.

        "It treats the pre-freeze count as fully recoverable, ignoring both thaw viability
        and TNC recovery"

        Design: Difficulty/non_linear_state_machine/reservation_fork_join_divergent_side_effect_sets
        """
        scenario = _listed_unit_with_two_holds()

        assert scenario["first_hold"]["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(4.29, abs=0.01)
        assert scenario["second_hold"]["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(3.75, abs=0.01)
        assert scenario["second_hold"]["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(
            expected_pre_cryo_dose(1500, 40.0), abs=0.01
        )

    def test_neither_branch_touches_the_tanks_occupied_slots(self):
        """The unit stays physically frozen throughout the fork and the join.

        "The unit's `availability_status` is not touched, its registry listing is not touched,
        no sibling hold is affected, and the tank's `occupied_slots` is unchanged."

        Design: Difficulty/non_linear_state_machine/reservation_fork_join_divergent_side_effect_sets
        """
        scenario = _listed_unit_with_two_holds()
        before = read_tank(scenario["tank"]["id"])["occupied_slots"]

        decline_reservation(
            scenario["second_hold"]["id"],
            reason_code="ALTERNATIVE_UNIT_SELECTED",
            center_user_id="tc-002",
        )
        confirm_reservation(
            scenario["first_hold"]["id"],
            intended_transplant_date="2026-09-03",
            center_user_id="tc-001",
        )

        assert before == 1
        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 1
