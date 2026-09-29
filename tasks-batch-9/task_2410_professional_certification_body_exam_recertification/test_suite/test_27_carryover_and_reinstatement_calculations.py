"""The look-back widens one cycle's window, and a two-step fee prices a late reinstatement."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

CARRYOVER_PROGRAM = {"ceu_credit_accrual_basis": "CARRYOVER_ALLOWED"}


def _lapsed_two_hundred_days_late(api):
    """A credit cycle nobody fed, swept two hundred days past its grace date."""
    state = fx.pipeline_through_certificant(api)
    fx.set_clock(api, "2028-05-26T00:00:00Z")
    return state


class TestCarryoverLookbackWindow:
    """The variant comes from the cycle's own snapshot and moves the left edge."""

    def test_the_snapshot_admits_an_activity_dated_ninety_days_before_the_cycle(self, api):
        """The cycle pins CARRYOVER_ALLOWED at creation, so a claim dated exactly at the
        look-back edge is accepted and, once approved, satisfies the requirement.

        PRD §3.11: "Two program settings are **snapshotted at cycle creation and never
        re-based afterwards**: `required_credits` pins the program's `required_ceu_credits`,
        and `accrual_basis_snapshot` pins the program's `ceu_credit_accrual_basis` as either
        `STRICT_CYCLE` or `CARRYOVER_ALLOWED`."

        PRD §3.11: "Under `CARRYOVER_ALLOWED`, the window is extended backwards by a 90-day
        look-back, so it runs from 90 days before `starts_on` through `ends_on` inclusive,
        and the carry-in contribution is the lesser of the cycle's `carryover_credits_in`
        and the program's `ceu_carryover_max_credits`."

        Design: Corner/calculations/carryover_allowed_cycle_snapshots_the_basis_and_admits_an_activity_from_the_lookback_window
        """
        state = fx.pipeline_through_certificant(api, program_overrides=CARRYOVER_PROGRAM)
        opened = fx.read_cycle(api, state.cycle_id)
        assert opened["accrual_basis_snapshot"] == "CARRYOVER_ALLOWED"
        assert float(opened["carryover_credits_in"]) == pytest.approx(0.00, abs=0.01)
        assert str(opened["starts_on"]).startswith("2026-08-10")

        claimed = validate_success(api.claim_ceu_activity(
            state.cycle_id,
            f.claim_ceu_payload(activity_date="2026-05-12T00:00:00Z",
                                provider="Spring Institute", contact_hours=12.0),
            state.owner_headers), 201)
        assert float(claimed["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert claimed["status"] == "SUBMITTED"
        assert claimed["counted"] is False

        approved = validate_success(api.review_ceu_activity(
            claimed["id"], f.review_ceu_payload("APPROVE"), fx.ELIGIBILITY_REVIEWER_3), 200)
        assert float(approved["credits_counted"]) == pytest.approx(12.00, abs=0.01)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"

    def test_one_day_earlier_than_the_lookback_edge_is_refused_and_stored_nowhere(self, api):
        """A claim dated ninety-one days before the cycle opened falls outside even the
        widened window, and the refusal creates no row and disturbs no total.

        PRD §3.11: "The `activity_date` must fall inside the cycle's accrual window, or the
        claim is refused with `ERR_ACTIVITY_OUTSIDE_CYCLE`."

        PRD §3.11: "An activity dated exactly on `starts_on` or exactly on `ends_on` is
        inside the window under both variants; an activity dated 90 days before `starts_on`
        counts under `CARRYOVER_ALLOWED` and is rejected at submission time with
        `ERR_ACTIVITY_OUTSIDE_CYCLE` under `STRICT_CYCLE`."

        Design: Corner/calculations/carryover_allowed_cycle_snapshots_the_basis_and_admits_an_activity_from_the_lookback_window
        """
        state = fx.pipeline_through_certificant(api, program_overrides=CARRYOVER_PROGRAM)
        fx.approved_ceu(api, state, activity_date="2026-05-12T00:00:00Z",
                        provider="Spring Institute", contact_hours=12.0)

        refused = api.claim_ceu_activity(
            state.cycle_id,
            f.claim_ceu_payload(activity_date="2026-05-11T00:00:00Z",
                                provider="Spring Institute", contact_hours=6.0),
            state.owner_headers)

        validate_error(refused, ApiErrorId.ERR_ACTIVITY_OUTSIDE_CYCLE.value, 422)
        assert len(fx.read_activities_of(api, state.cycle_id)) == 1
        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"
        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert certificant["status"] == "ACTIVE"


class TestReinstatementFeeAtTwoHundredDaysLate:
    """The surcharge caps, the tier keys on the subtotal, and the total is 59400."""

    def test_the_dry_run_reports_the_lapse_it_declines_to_perform(self, api):
        """Two hundred days past the grace date the run can already name the cycle and the
        holder, yet the cycle is still OPEN with no fee assessed.

        PRD §3.13: "When `dry_run` is true the run computes and reports exactly the same six
        lists while mutating nothing at all, which makes it safe to inspect before
        committing."

        PRD §3.13: "**Step three — cycles.** Every cycle whose `status` is `OPEN` and whose
        `grace_ends_on` the logical clock is strictly past moves to `LAPSED`, has its
        `reinstatement_fee_cents` assessed as described in §3.11, and drags its owning
        certificant `ACTIVE → EXPIRED` with `publication_status` recomputed to `WITHHELD`."

        Design: Corner/calculations/reinstatement_fee_at_200_days_late_caps_the_surcharge_and_totals_59400
        """
        state = _lapsed_two_hundred_days_late(api)
        assert str(fx.read_cycle(api, state.cycle_id)["grace_ends_on"]).startswith("2027-11-08")

        report = fx.run_maintenance(api, dry_run=True)

        assert state.cycle_id in report["lapsed_cycle_ids"]
        assert state.certificant_id in report["expired_certificant_ids"]
        ax.assert_maintenance_run_report(report)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "OPEN"
        assert cycle["reinstatement_fee_cents"] is None
        assert fx.read_certificant(api, state.certificant_id)["status"] == "ACTIVE"

    def test_the_committed_run_assesses_exactly_fifty_nine_thousand_four_hundred_cents(
            self, api):
        """The 200-day surcharge is capped at 30000, the 55000 subtotal selects the eight
        percent tier, and 55000 + 4400 lands on 59400 — not 81000, 57750 or 30600.

        PRD §3.11: "First take the whole days elapsed between `grace_ends_on` and the
        current date — at least one by construction — and compute the late surcharge as 250
        cents per day late, capped at 30000 cents, which makes the surcharge flat beyond the
        hundred-and-twentieth day late."

        PRD §3.11: "Then select the administrative rate from the subtotal: 2 percent when
        the subtotal is at most 30000 cents, 5 percent when it is above 30000 and at most
        45000 cents, and 8 percent when it is above 45000 cents."

        PRD §3.11: "The administrative fee is that rate applied to the **whole** subtotal —
        an average rate, not a marginal one — rounded half up to whole cents, and
        `reinstatement_fee_cents` is the subtotal plus the administrative fee."

        Design: Corner/calculations/reinstatement_fee_at_200_days_late_caps_the_surcharge_and_totals_59400
        """
        state = _lapsed_two_hundred_days_late(api)

        fx.run_maintenance(api)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "LAPSED"
        assert cycle["reinstatement_fee_cents"] == 59400
        assert cycle["reinstatement_fee_cents"] != 81000
        assert cycle["reinstatement_fee_cents"] != 57750
        assert cycle["reinstatement_fee_cents"] != 30600
        ax.assert_integer_cents(cycle["reinstatement_fee_cents"])

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "EXPIRED"
        assert certificant["publication_status"] == "WITHHELD"
        ax.assert_publication_status_agrees_with_status(certificant)

    def test_one_cent_short_is_refused_and_the_exact_payment_restores_the_credential(
            self, api):
        """A payment of 59399 is turned away on the assessed fee, and paying 59400 reopens
        the cycle with a fresh grace window while the credential's identity is untouched.

        PRD §3.11: "It carries `payment_cents`, requires the cycle's `status` to be `LAPSED`
        — otherwise `ERR_INVALID_STATE` — requires the owning certificant not to be
        `REVOKED` — otherwise `ERR_CERTIFICANT_ALREADY_REVOKED` — and requires
        `payment_cents` to be at least the cycle's assessed `reinstatement_fee_cents`, or
        the payment is refused with `ERR_REINSTATEMENT_FEE_UNPAID`."

        PRD §3.11: "On success the cycle moves `LAPSED → OPEN`, its `grace_ends_on` is
        extended by the program's `recert_grace_days`, and its `reinstatement_fee_cents` is
        cleared back to null; the owning certificant moves `EXPIRED → ACTIVE` with
        `publication_status` recomputed to `PUBLISHED` and its `version` incremented by 1."

        Design: Corner/calculations/reinstatement_fee_at_200_days_late_caps_the_surcharge_and_totals_59400
        """
        state = _lapsed_two_hundred_days_late(api)
        fx.run_maintenance(api)

        refused = api.reinstate_cycle(state.cycle_id, f.reinstate_payload(59399),
                                     state.owner_headers)

        validate_error(refused, ApiErrorId.ERR_REINSTATEMENT_FEE_UNPAID.value, 402)
        assert fx.read_cycle(api, state.cycle_id)["status"] == "LAPSED"
        assert fx.read_certificant(api, state.certificant_id)["status"] == "EXPIRED"

        reinstated = validate_success(api.reinstate_cycle(
            state.cycle_id, f.reinstate_payload(59400), state.owner_headers), 200)

        assert reinstated["status"] == "OPEN"
        assert reinstated["reinstatement_fee_cents"] is None
        assert str(reinstated["grace_ends_on"]).startswith("2028-02-06")

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "ACTIVE"
        assert certificant["publication_status"] == "PUBLISHED"
        assert certificant["certificate_number"] == state.certificate_number
        assert str(certificant["issued_on"]).startswith("2026-08-10")
