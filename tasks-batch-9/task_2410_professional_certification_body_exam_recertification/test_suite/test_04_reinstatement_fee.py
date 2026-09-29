"""Lapse assessment: the administrative tier is keyed on the subtotal."""

import pytest

from test_helpers import assertions as ax
from test_helpers import fixtures as fx

GRACE_PROGRAM = {"recert_grace_days": 90}

# The credential is issued on 2026-08-10, so the cycle's grace ends on
# 2027-11-08 and this instant is twenty whole days past it.
TWENTY_DAYS_LATE = "2027-11-28T00:00:00Z"


class TestLapseAtTwentyDaysLate:
    """One maintenance run, twenty days past the grace deadline."""

    def test_run_lapses_the_open_cycle_and_expires_its_holder(self, api):
        """A cycle still OPEN once the clock is strictly past ``grace_ends_on``
        lapses, and drags its certificant to EXPIRED with visibility withheld.

        PRD §3.13: "Every cycle whose `status` is `OPEN` and whose `grace_ends_on`
        the logical clock is strictly past moves to `LAPSED`, has its
        `reinstatement_fee_cents` assessed as described in §3.11, and drags its
        owning certificant `ACTIVE → EXPIRED` with `publication_status` recomputed
        to `WITHHELD`."

        Design: Difficulty/combinatorial_formula/reinstatement_fee_tier_keyed_on_subtotal_totals_30600_not_31500
        """
        state = fx.pipeline_through_certificant(api, program_overrides=GRACE_PROGRAM)
        fx.set_clock(api, TWENTY_DAYS_LATE)

        fx.run_maintenance(api)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "LAPSED"

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "EXPIRED"
        assert certificant["publication_status"] == "WITHHELD"
        ax.assert_publication_status_agrees_with_status(certificant)

    def test_administrative_tier_is_selected_from_the_subtotal_not_the_total(self, api):
        """Twenty days late gives a 5000-cent surcharge on a 25000-cent base: a
        30000-cent subtotal, which sits in the 2 percent tier for a 600-cent
        administrative fee and a 30600-cent total. Tiering on the total instead
        would have selected 5 percent and produced 31500.

        PRD §3.11: "Twenty days late therefore gives a 5000-cent surcharge, a
        30000-cent subtotal, the 2 percent rate, a 600-cent administrative fee, and
        a 30600-cent total; keying the tier off the total instead would have
        selected 5 percent and produced 31500, which is precisely the error this
        ordering prevents."

        Design: Difficulty/combinatorial_formula/reinstatement_fee_tier_keyed_on_subtotal_totals_30600_not_31500
        """
        state = fx.pipeline_through_certificant(api, program_overrides=GRACE_PROGRAM)
        fx.set_clock(api, TWENTY_DAYS_LATE)

        fx.run_maintenance(api)

        cycle = fx.read_cycle(api, state.cycle_id)
        ax.assert_integer_cents(cycle["reinstatement_fee_cents"])
        assert cycle["reinstatement_fee_cents"] == 30600
        assert cycle["reinstatement_fee_cents"] != 31500

    def test_report_names_the_lapsed_cycle_and_leaves_the_completed_sitting_alone(self, api):
        """The run's report lists the cycle it lapsed and the certificant it
        expired, while the already-completed registration is not a no-show
        candidate at all.

        PRD §3.13: "Every registration whose `seat_status` is `SCHEDULED` and whose
        held session's `ends_at` the logical clock has passed moves to `NO_SHOW`."

        PRD §3.13: "six identifier lists record what it touched —
        `no_show_registration_ids`, `expired_application_ids`, `lapsed_cycle_ids`,
        `expired_certificant_ids`, `reactivated_certificant_ids`, and
        `unbarred_candidate_ids`".

        Design: Difficulty/combinatorial_formula/reinstatement_fee_tier_keyed_on_subtotal_totals_30600_not_31500
        """
        state = fx.pipeline_through_certificant(api, program_overrides=GRACE_PROGRAM)
        fx.set_clock(api, TWENTY_DAYS_LATE)

        report = fx.run_maintenance(api)

        ax.assert_maintenance_run_report(report)
        assert report["lapsed_cycle_ids"] == [state.cycle_id]
        assert report["expired_certificant_ids"] == [state.certificant_id]
        assert report["no_show_registration_ids"] == []
        assert fx.read_registration(api, state.registration_id)["seat_status"] == "COMPLETED"
        assert pytest.approx(0.00, abs=0.01) == float(
            fx.read_cycle(api, state.cycle_id)["credits_applied"])
