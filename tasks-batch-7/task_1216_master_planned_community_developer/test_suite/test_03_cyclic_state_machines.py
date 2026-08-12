"""Non-linear (cyclic) state machines: design review rounds and tranche cure."""
from test_helpers import (
    api_client,
    create_active_community,
    create_application,
    create_phase,
    create_lot,
    create_builder,
    deny_round,
    resubmit_application,
    set_clock,
    setup_missed_tranche_scenario,
    get_success_data,
    make_builder_rep_headers,
    make_design_reviewer_headers,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]


class TestDesignReviewRevisionCycle:
    """Two full DENIED -> RESUBMITTED -> UNDER_REVIEW loops with escalating
    round fees and reviewer rotation between rounds."""

    def _setup_cycle(self):
        community = create_active_community("Cycle Creek", 50)
        phase = create_phase(community["id"], "P1", 1, 10)
        lot = create_lot(phase["id"], "L1")
        builder = create_builder(community["id"], "Builder Co", "A")
        application = create_application(
            community["id"], lot["id"], applicant_builder_id=builder["id"],
            project_type="EXTERIOR_MODIFICATION",
        )
        return builder, application

    def test_round_fees_escalate_across_resubmissions(self):
        """PRD §3.7: "A new application starts `SUBMITTED` at `submission_round` 1 with `review_fee_cents` 0. A `DesignReviewer` claims an application by beginning review, which stamps `reviewer_user_id` and moves it to `UNDER_REVIEW`."
        PRD §3.7: "Resubmission increments `submission_round` and assesses the round fee: `review_fee_cents` becomes 25000 cents entering round 2 and 75000 cents entering round 3. Withdrawal is available to the applicant from `SUBMITTED` or `DENIED` under the same identity match."

        Design: Difficulty/non_linear_state_machine/design_review_revision_cycle
        """
        builder, application = self._setup_cycle()
        assert application["review_fee_cents"] == 0
        assert application["submission_round"] == 1

        deny_round(application["id"], "rev-1", "materials")
        round2 = resubmit_application(application["id"], applicant_builder_id=builder["id"])
        assert round2["submission_round"] == 2
        assert round2["review_fee_cents"] == 25000, (
            f"round-2 fee must be 25000, got {round2['review_fee_cents']}"
        )

        deny_round(application["id"], "rev-2", "colors")
        round3 = resubmit_application(application["id"], applicant_builder_id=builder["id"])
        assert round3["submission_round"] == 3
        assert round3["review_fee_cents"] == 75000, (
            f"round-3 fee must be 75000, got {round3['review_fee_cents']}"
        )

    def test_reviewer_rotation_and_final_approval(self):
        """PRD §3.7: "Two conflict rules protect impartiality: on a first submission the reviewer's `X-User-ID` must not equal the applicant's id, and on a `RESUBMITTED` application it must not equal the `denied_by_user_id` of the latest denial; both surface as `ERR_REVIEWER_CONFLICT`. The same exclusivity binds decisions: approving, approving with conditions, and denying each require the actor to be the recorded `reviewer_user_id` (`ERR_REVIEWER_CONFLICT`)."
        PRD §3.7: "Approval stamps `construction_start_by` at the logical clock plus 180 days; conditional approval records `conditions_text` and leaves the application `CONDITIONALLY_APPROVED` until the reviewer verifies the conditions, at which point it becomes `APPROVED` and `construction_start_by` is set the same way."

        Design: Difficulty/non_linear_state_machine/design_review_revision_cycle
        """
        builder, application = self._setup_cycle()
        deny_round(application["id"], "rev-1", "materials")
        resubmit_application(application["id"], applicant_builder_id=builder["id"])
        deny_round(application["id"], "rev-2", "colors")
        resubmit_application(application["id"], applicant_builder_id=builder["id"])

        # Round-3 review can be claimed by rev-1: only the latest denier
        # (rev-2) is excluded.
        rev1 = make_design_reviewer_headers("rev-1")
        claimed = get_success_data(api_client.begin_review(application["id"], rev1))
        assert claimed["status"] == "UNDER_REVIEW"
        assert claimed["reviewer_user_id"] == "rev-1"

        approved = get_success_data(api_client.approve_application(application["id"], rev1))
        assert approved["status"] == "APPROVED"
        # Default clock 2026-05-01 + 180 days = 2026-10-28.
        assert approved["construction_start_by"] == "2026-10-28T00:00:00.000Z", (
            f"construction_start_by must be clock + 180 days, got "
            f"{approved['construction_start_by']}"
        )


class TestTakedownTrancheMissedCureCycle:
    """SCHEDULED -> OPEN -> MISSED -> CURED with the builder-standing side
    effect and an exact-penalty cure payment (deficit 1 x 1000c/day x 10 days)."""

    def test_missed_sweep_demotes_builder_and_accrues_penalty(self):
        """PRD §3.3: "Past the due date with the count still short, the sweep marks it `MISSED`, which demotes the builder from `GOOD_STANDING` to `PROBATION` and starts the penalty meter. The accrued penalty on a `MISSED` tranche is evaluated on read, at cure, and at default certification: the deficit is `lot_count_due` minus `lots_credited`; the days late are the calendar days from `due_date` to the evaluation moment (zero while the tranche is not `MISSED`); the raw penalty is the deficit times the agreement's `penalty_per_lot_per_day_cents` times the days late; and `accrued_penalty_cents` is the lesser of that raw figure and a cap of twenty-five percent of `lot_count_due` times the agreement's `base_price_per_lot_cents`, the cap itself rounded half-up to whole cents."
        PRD §3.3: "The accrued penalty on a `MISSED` tranche is evaluated on read, at cure, and at default certification: the deficit is `lot_count_due` minus `lots_credited`; the days late are the calendar days from `due_date` to the evaluation moment (zero while the tranche is not `MISSED`); the raw penalty is the deficit times the agreement's `penalty_per_lot_per_day_cents` times the days late; and `accrued_penalty_cents` is the lesser of that raw figure and a cap of twenty-five percent of `lot_count_due` times the agreement's `base_price_per_lot_cents`, the cap itself rounded half-up to whole cents.".

        Design: Difficulty/non_linear_state_machine/takedown_tranche_missed_cure_cycle
        """
        scenario = setup_missed_tranche_scenario(community_name="Cure Canyon")
        tranche = scenario["tranches"][0]
        builder = scenario["builder"]

        mid_builder = get_success_data(api_client.get_builder(builder["id"], EXEC))
        assert mid_builder["standing"] == "PROBATION", (
            f"builder must be PROBATION after the miss, got {mid_builder['standing']}"
        )

        set_clock("2026-07-10T00:00:00Z")
        read = get_success_data(api_client.get_tranche(tranche["id"], CTRL))
        assert read["status"] == "MISSED"
        assert read["accrued_penalty_cents"] == 10000, (
            f"1 deficit lot x 1000c/day x 10 days = 10000 (cap 1250000), got "
            f"{read['accrued_penalty_cents']}"
        )

    def test_exact_penalty_cure_restores_tranche_not_standing(self):
        """PRD §3.3: "The builder's own `BuilderRep` may cure it — the acting user's `X-User-ID` must equal the agreement's `builder_id` (`ERR_FORBIDDEN_ROLE` otherwise) — by paying `payment_cents` exactly equal to the current `accrued_penalty_cents` (`ERR_PENALTY_AMOUNT_MISMATCH` on any other amount) while the logical clock is on or before the `cure_deadline`; attempting to cure a tranche that is not `MISSED`, or one whose cure deadline has already passed, is rejected with `ERR_TRANCHE_NOT_CURABLE`. A cured tranche moves to `CURED`. An `AssociationDirector` may waive it, moving it to `WAIVED` with a recorded `waiver_reason` and forgiving the accrued penalty — it is frozen at its current value and no longer owed — but only while the community's `transition_stage` is not `TURNOVER_COMPLETE` (`ERR_DECLARANT_AUTHORITY_ENDED`)."
        PRD §3.3: "A `DeclarantExecutive` may reinstate a builder to `GOOD_STANDING` only when no tranche of any of its agreements remains `MISSED` or `DEFAULTED` — and, when reinstating from `SUSPENDED`, additionally when no agreement of the builder is `DEFAULTED`; outstanding compliance defaults are rejected with `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS`.".

        Design: Difficulty/non_linear_state_machine/takedown_tranche_missed_cure_cycle
        """
        scenario = setup_missed_tranche_scenario(community_name="Cure Canyon")
        tranche = scenario["tranches"][0]
        builder = scenario["builder"]
        set_clock("2026-07-10T00:00:00Z")

        cured = get_success_data(
            api_client.cure_tranche(
                tranche["id"], {"payment_cents": 10000}, make_builder_rep_headers(builder["id"])
            )
        )
        assert cured["status"] == "CURED"
        # Curing does not itself restore standing; reinstate is a separate act.
        after = get_success_data(api_client.get_builder(builder["id"], EXEC))
        assert after["standing"] == "PROBATION", (
            f"cure leaves the builder PROBATION until reinstate, got {after['standing']}"
        )
