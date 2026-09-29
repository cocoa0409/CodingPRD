"""Lifecycles that are not straight lines: a kiln charge that cycles back into
conditioning, a warranty claim with two independent dimensions, and a lot whose
one closeout trigger branches on the yield floor."""

import pytest

from test_helpers import (
    finalize_lot_payload,
    record_stress_test_payload,
    reverse_claim_payload,
    setup_conditioning_charge,
    setup_finalized_grade_run,
    setup_line_only_approved_claim,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    INSPECTOR,
    OPERATOR,
    QUARANTINE_BUNDLES,
    QUARANTINE_MILLING,
    SUPERVISOR,
    refetch_chamber,
    refetch_product_line,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    make_warranty_adjudicator_headers,
)


class TestChargeConditioningRedryCycle:
    """`CONDITIONING` to `REDRY` and back again, with the loop counter and the
    extended occupancy window persisting across the cycle."""

    def test_failing_stress_test_returns_the_charge_to_redry_and_extends_its_window(
        self, api
    ):
        """PRD 3.5: "On the redry branch the charge moves from `CONDITIONING` to
        `REDRY`."

        PRD 3.5: "The readings and derived figures are stored exactly as on the
        release branch, `redry_count` is incremented, `planned_end_utc` is
        advanced by a further 48 hours, and `blocked_until_utc` is recomputed from
        the new end plus the same 6-hour cooldown buffer."

        PRD 3.3: "A charge starting at `2026-08-05T00:00:00.000Z` with 265.0
        planned hours ends at `2026-08-16T01:00:00.000Z` and blocks its chamber
        until `2026-08-16T07:00:00.000Z`."

        Design: Difficulty/non_linear_state_machine/kiln_charge_conditioning_redry_cycle
        """
        ctx = setup_conditioning_charge(api)
        charge_id = ctx["charge"]["id"]
        assert ctx["charge"]["planned_end_utc"] == "2026-08-16T01:00:00.000Z"
        assert ctx["charge"]["blocked_until_utc"] == "2026-08-16T07:00:00.000Z"

        charge = validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )

        assert charge["status"] == "REDRY"
        assert charge["moisture_gradient_pp"] == pytest.approx(2.1, abs=0.01)
        assert charge["redry_count"] == 1
        assert charge["planned_end_utc"] == "2026-08-18T01:00:00.000Z"
        assert charge["blocked_until_utc"] == "2026-08-18T07:00:00.000Z"
        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "OCCUPIED"

    def test_resume_clears_the_readings_and_a_second_test_releases_without_recounting(
        self, api
    ):
        """PRD 3.5: "A redrying charge returns to the conditioning phase when a
        `KilnOperator` resumes it, moving it from `REDRY` back to `CONDITIONING`
        and clearing all four stress-test figures — `shell_moisture_pct`,
        `core_moisture_pct`, `moisture_gradient_pp` and `average_moisture_pct` —
        so that the next test starts from a clean slate."

        PRD 3.5: "`remaining_dry_bf` is initialised to the same value, since no
        lot has yet drawn from the charge."

        PRD 3.5: "A charge holding 9700 green board feet of a `DENSE` species
        yields 8972.50 kiln-dry board feet."

        Design: Difficulty/non_linear_state_machine/kiln_charge_conditioning_redry_cycle
        """
        ctx = setup_conditioning_charge(api)
        charge_id = ctx["charge"]["id"]
        validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )

        resumed = validate_success(
            api.resume_conditioning(charge_id, OPERATOR), expected_status=200
        )
        assert resumed["status"] == "CONDITIONING"
        assert resumed["shell_moisture_pct"] is None
        assert resumed["core_moisture_pct"] is None
        assert resumed["moisture_gradient_pp"] is None
        assert resumed["average_moisture_pct"] is None
        assert resumed["redry_count"] == 1

        released = validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(6.4, 8.2), OPERATOR
            ),
            expected_status=200,
        )
        assert released["status"] == "RELEASED"
        assert released["moisture_gradient_pp"] == pytest.approx(1.8, abs=0.01)
        assert released["average_moisture_pct"] == pytest.approx(7.3, abs=0.01)
        assert released["dry_bf_out"] == pytest.approx(8972.50, abs=0.01)
        assert released["remaining_dry_bf"] == pytest.approx(8972.50, abs=0.01)
        assert released["redry_count"] == 1, (
            "a completed cycle counts once, not once per phase change"
        )
        # The extension earned during the redry survives the release.
        assert released["blocked_until_utc"] == "2026-08-18T07:00:00.000Z"
        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "AVAILABLE"


class TestClaimParallelDimensions:
    """Adjudication and remediation are separate axes on one claim, coupled in
    one direction only."""

    def test_remediation_advances_while_the_adjudication_dimension_stands_still(
        self, api
    ):
        """PRD 3.9: "Remediation runs on its own dimension, independent of
        adjudication, and may be driven by a `WarrantyAdjudicator` or a
        `MillSupervisor`."

        PRD 3.9: "Starting remediation moves the claim's remediation status from
        `NOT_STARTED` to `IN_PROGRESS`, and completing it moves that status from
        `IN_PROGRESS` to `COMPLETED`; both require the claim's adjudication status
        to be `APPROVED`, and both are refused with `ERR_CLAIM_STATE_INVALID` when
        either dimension is in the wrong state — remediating an unapproved claim,
        starting work already in progress, or completing work never started."

        Design: Difficulty/non_linear_state_machine/warranty_claim_parallel_dimensions_move_independently
        """
        ctx = setup_line_only_approved_claim(api)
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["remediation_status"] == "NOT_STARTED"

        started = validate_success(
            api.start_remediation(claim_id, SUPERVISOR), expected_status=200
        )
        assert started["remediation_status"] == "IN_PROGRESS"
        assert started["adjudication_status"] == "APPROVED"
        assert started["adjudicated_liability_cents"] == 151474

        completed = validate_success(
            api.complete_remediation(claim_id, SUPERVISOR), expected_status=200
        )
        assert completed["remediation_status"] == "COMPLETED"
        assert completed["adjudication_status"] == "APPROVED"
        assert completed["adjudicated_liability_cents"] == 151474

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_balance_cents"] == 448526
        assert line["warranty_committed_cents"] == 151474

    def test_finished_remediation_locks_the_adjudication_dimension_against_reversal(
        self, api
    ):
        """PRD 3.9: "Work that has already finished cannot be unwound, so a claim
        whose remediation status is `COMPLETED` may not be reversed and is refused
        with `ERR_CLAIM_STATE_INVALID`, as is any attempt to reverse a claim that
        is not `APPROVED`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_parallel_dimensions_move_independently
        """
        ctx = setup_line_only_approved_claim(api)
        claim_id = ctx["claim"]["id"]
        validate_success(api.start_remediation(claim_id, SUPERVISOR), expected_status=200)
        validate_success(
            api.complete_remediation(claim_id, SUPERVISOR), expected_status=200
        )

        response = api.reverse_claim(
            claim_id,
            reverse_claim_payload(reversal_reason="Adjuster error found on review"),
            make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
        )
        validate_error(response, "ERR_CLAIM_STATE_INVALID", expected_status=409)

        # The combined state (APPROVED, COMPLETED) is untouched by the refusal.
        claim = validate_success(
            api.get_warranty_claim(claim_id, ADJUDICATOR), expected_status=200
        )
        assert claim["adjudication_status"] == "APPROVED"
        assert claim["remediation_status"] == "COMPLETED"
        assert refetch_product_line(api, ctx["product_line"]["id"])[
            "warranty_balance_cents"
        ] == 448526


class TestLotCloseoutBranchesOnYieldFloor:
    """One trigger, two destinations, chosen by the final yield alone."""

    def test_closeout_above_the_floor_grades_the_lot_with_no_quarantine_note(
        self, api
    ):
        """PRD 3.7: "The branch then follows the yield floor of 55.00 percent: at
        or above the floor the lot moves from `MILLED` to `GRADED`; below it the
        lot moves from `MILLED` to `QUARANTINED` and a `quarantine_reason` is
        recorded."

        PRD 3.7: "Both branches set `final_grade_run_id` and `final_yield_pct`
        identically; only the state and the quarantine note differ."

        Design: Difficulty/non_linear_state_machine/flooring_lot_finalize_branches_on_yield_floor
        """
        ctx = setup_finalized_grade_run(api)

        lot = validate_success(
            api.finalize_flooring_lot(
                ctx["lot"]["id"], finalize_lot_payload(ctx["grade_run"]["id"]), INSPECTOR
            ),
            expected_status=200,
        )

        assert lot["status"] == "GRADED"
        assert lot["final_yield_pct"] == pytest.approx(66.17, abs=0.01)
        assert lot["final_grade_run_id"] == ctx["grade_run"]["id"]
        assert lot["quarantine_reason"] is None
        assert lot["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)

    def test_closeout_below_the_floor_quarantines_the_same_way_but_notes_the_reason(
        self, api
    ):
        """PRD 3.7: "The lot's `final_yield_pct` is the run's
        `credited_board_feet` divided by the lot's `input_dry_bf`, expressed as a
        percentage and rounded half up to two decimal places, and
        `final_grade_run_id` records the closing run."

        PRD 3.7: "The provisional figure is never overwritten — it remains the
        milling record — and only the final figure decides the branch."

        Design: Difficulty/non_linear_state_machine/flooring_lot_finalize_branches_on_yield_floor
        """
        ctx = setup_finalized_grade_run(
            api,
            bundles=QUARANTINE_BUNDLES,
            input_dry_bf=2900,
            milling=dict(QUARANTINE_MILLING),
        )
        assert ctx["grade_run"]["credited_board_feet"] == pytest.approx(
            1090.0000, abs=0.0001
        )
        assert ctx["grade_run"]["tally_board_feet"] == pytest.approx(1800.00, abs=0.01)

        lot = validate_success(
            api.finalize_flooring_lot(
                ctx["lot"]["id"], finalize_lot_payload(ctx["grade_run"]["id"]), INSPECTOR
            ),
            expected_status=200,
        )

        assert lot["status"] == "QUARANTINED"
        assert lot["final_yield_pct"] == pytest.approx(37.59, abs=0.01)
        assert lot["final_grade_run_id"] == ctx["grade_run"]["id"]
        assert isinstance(lot["quarantine_reason"], str)
        assert lot["quarantine_reason"] != ""
        # 2500 net of 2900 drawn: a healthy milling figure that does not save the lot.
        assert lot["provisional_yield_pct"] == pytest.approx(86.21, abs=0.01)
