"""Unwinds that must leave no residue behind.

A rescission inside the window has to reverse every derived total the acceptance
wrote — the lot, the class's outstanding shares, the offering's proceeds and
aggregate valuation, the stockholder's ledgers and account axis — and the same
operation must be refused outright once the window has closed (PRD §3.5). A failed
escrow has to roll the whole fundraise back to its pre-money state and terminate
the repurchase plan, so the offering cannot be revived by a later break (PRD §3.5).
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE,
    TRANSFER_AGENT,
    ApiErrorId,
    assert_error,
    assert_fields,
    assert_ok,
)
from test_helpers.fixtures import ReitWorld

ZERO_LOAD = {
    "upfront_selling_commission_bps": 0,
    "dealer_manager_fee_bps": 0,
    "annual_distribution_fee_bps": 0,
    "distribution_fee_cap_bps": 0,
}


# ─── Cornerstone: rescission inside and outside the window ────────────


def _cornerstone_two_accepted_lots(world: ReitWorld) -> Dict[str, Any]:
    """Two 10,000,000-cent class T tickets accepted by the escrow break at boot.

    Class T charges 300 bps of selling commission and 50 bps of dealer manager
    fee, so each ticket nets 9,650,000 cents and buys 96,500,000 e4 at the
    initial price of 1000 cents. Both lots carry an ``issued_date`` of
    2026-08-01, and the clock is then advanced to 2026-08-04 — three days into
    the offering's five-day rescission window.
    """
    off = world.offering(
        name="Cornerstone Income REIT",
        minimum_offering_amount_cents=20000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    sc_t = world.share_class(
        off["id"],
        class_code="T",
        upfront_selling_commission_bps=300,
        dealer_manager_fee_bps=50,
        annual_distribution_fee_bps=850,
        distribution_fee_cap_bps=875,
        converts_to_class_code="I",
    )
    firm = world.broker_dealer(
        firm_name="Meridian Securities LLC", crd_number="CRD-100001"
    )
    agreement = world.selling_agreement(
        off["id"],
        firm["id"],
        max_commission_bps=500,
        suitability_documentation_required=True,
    )
    world.declare_effective(off["id"])
    world.activate_agreement(agreement["id"])

    avery = world.investor(
        legal_name="Avery Nolan",
        email="avery.nolan@example.com",
        state_code="TX",
        net_worth_cents=500000000,
        annual_income_cents=100000000,
    )
    world.document_suitability(avery["id"], "SUIT-A-2026-08")
    blake = world.investor(
        legal_name="Blake Ortiz",
        email="blake.ortiz@example.com",
        state_code="TX",
        net_worth_cents=500000000,
        annual_income_cents=100000000,
    )
    world.document_suitability(blake["id"], "SUIT-B-2026-08")

    sub_a = world.subscription(off["id"], sc_t["id"], avery["id"], agreement["id"], 10000000)
    world.escrow_subscription(sub_a["id"])
    sub_b = world.subscription(off["id"], sc_t["id"], blake["id"], agreement["id"], 10000000)
    world.escrow_subscription(sub_b["id"])
    world.break_escrow(off["id"])

    lot_b = world.lot_of_subscription(sub_b["id"])
    world.set_clock("2026-08-04T00:00:00Z", TRANSFER_AGENT)
    return {
        "offering_id": off["id"],
        "share_class_t_id": sc_t["id"],
        "avery_id": avery["id"],
        "blake_id": blake["id"],
        "subscription_a_id": sub_a["id"],
        "subscription_b_id": sub_b["id"],
        "lot_b_id": lot_b["id"],
    }


class TestRescissionRestoresShareAndProceedsConservation:
    """PRD §3.5: the unwind is exact, and it is only available inside the window."""

    def test_rescission_voids_the_lot_and_empties_the_holders_ledgers(self, api, world):
        """Blake's lot goes RESCINDED at zero remaining and his account closes out.

        PRD §3.5: "A successful rescission increments the subscription's
        `version`, sets the minted lot to the terminal `RESCINDED` and zeroes its
        `remaining_shares_e4`, subtracts the `gross_investment_cents` from both
        the offering's `gross_proceeds_cents` and the stockholder's
        `cumulative_invested_cents`, recomputes the class's
        `shares_outstanding_e4`, the stockholder's `total_shares_e4` and the
        offering's `aggregate_nav_cents`, re-evaluates `suitability_status` so
        that a `FLAGGED` stockholder returns to `DOCUMENTED` once the
        concentration limit is respected again, and moves `account_status` to
        `CLOSED_NO_POSITION` when the stockholder is left holding no `OPEN` lot at
        all."

        Design: Difficulty/compensating_invariant/rescission_restores_share_and_proceeds_conservation
        """
        scene = _cornerstone_two_accepted_lots(world)

        rescinded = assert_ok(
            api.set_subscription_status(
                scene["subscription_b_id"],
                {"to_status": "RESCINDED", "rejection_reason": "INVESTOR_RESCISSION"},
                TRANSFER_AGENT,
            )
        )

        assert_fields(rescinded, status="RESCINDED")
        assert_fields(
            world.read_lot(scene["lot_b_id"]),
            status="RESCINDED",
            remaining_shares_e4=0,
            original_shares_e4=96500000,
        )
        assert_fields(
            world.read_investor(scene["blake_id"]),
            total_shares_e4=0,
            cumulative_invested_cents=0,
            account_status="CLOSED_NO_POSITION",
            suitability_status="DOCUMENTED",
        )

    def test_rescission_restores_offering_proceeds_and_class_outstanding_shares(
        self, api, world
    ):
        """The offering falls back to one lot's worth of proceeds and valuation.

        PRD §3.5: "A successful rescission increments the subscription's
        `version`, sets the minted lot to the terminal `RESCINDED` and zeroes its
        `remaining_shares_e4`, subtracts the `gross_investment_cents` from both
        the offering's `gross_proceeds_cents` and the stockholder's
        `cumulative_invested_cents`, recomputes the class's
        `shares_outstanding_e4`, the stockholder's `total_shares_e4` and the
        offering's `aggregate_nav_cents`, re-evaluates `suitability_status` so
        that a `FLAGGED` stockholder returns to `DOCUMENTED` once the
        concentration limit is respected again, and moves `account_status` to
        `CLOSED_NO_POSITION` when the stockholder is left holding no `OPEN` lot at
        all."
        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class
        of the offering, of each class's transaction price multiplied by that
        class's `shares_outstanding_e4`, divided by 10,000 and rounded half up —
        each class's contribution rounded to a whole cent on its own before the
        contributions are added."

        Design: Difficulty/compensating_invariant/rescission_restores_share_and_proceeds_conservation
        """
        scene = _cornerstone_two_accepted_lots(world)

        assert_ok(
            api.set_subscription_status(
                scene["subscription_b_id"],
                {"to_status": "RESCINDED", "rejection_reason": "INVESTOR_RESCISSION"},
                TRANSFER_AGENT,
            )
        )

        assert_fields(
            world.read_share_class(scene["share_class_t_id"]),
            shares_outstanding_e4=96500000,
        )
        assert_fields(
            world.read_offering(scene["offering_id"]),
            gross_proceeds_cents=10000000,
            escrow_balance_cents=0,
            aggregate_nav_cents=9650000,
        )

    def test_the_sibling_holding_is_untouched_by_its_neighbours_rescission(self, api, world):
        """Avery keeps her 96,500,000 e4 and her 10,000,000-cent investment.

        PRD §3.5: "And a `TransferAgent` may drive `ACCEPTED` to `RESCINDED`,
        again with a `rejection_reason`, but only inside the rescission window and
        only against an untouched lot."

        Design: Difficulty/compensating_invariant/rescission_restores_share_and_proceeds_conservation
        """
        scene = _cornerstone_two_accepted_lots(world)

        assert_ok(
            api.set_subscription_status(
                scene["subscription_b_id"],
                {"to_status": "RESCINDED", "rejection_reason": "INVESTOR_RESCISSION"},
                TRANSFER_AGENT,
            )
        )

        assert_fields(world.read_subscription(scene["subscription_a_id"]), status="ACCEPTED")
        assert_fields(
            world.read_investor(scene["avery_id"]),
            total_shares_e4=96500000,
            cumulative_invested_cents=10000000,
            account_status="ACTIVE",
        )

    def test_rescission_refused_once_the_window_has_run_out(self, api, world):
        """At 2026-08-08 the lot issued on 2026-08-01 is four days past its five-day window.

        PRD §3.5: "The window test is that the current logical clock is at or
        before the lot's `issued_date` advanced by the offering's
        `rescission_window_days` days; past that instant the request is refused
        with `ERR_RESCISSION_WINDOW_EXPIRED`."

        Design: Difficulty/compensating_invariant/rescission_restores_share_and_proceeds_conservation
        """
        scene = _cornerstone_two_accepted_lots(world)
        assert_ok(
            api.set_subscription_status(
                scene["subscription_b_id"],
                {"to_status": "RESCINDED", "rejection_reason": "INVESTOR_RESCISSION"},
                TRANSFER_AGENT,
            )
        )
        world.set_clock("2026-08-08T00:00:00Z", TRANSFER_AGENT)

        response = api.set_subscription_status(
            scene["subscription_a_id"],
            {"to_status": "RESCINDED", "rejection_reason": "LATE_RESCISSION_ATTEMPT"},
            TRANSFER_AGENT,
        )

        assert_error(response, ApiErrorId.RESCISSION_WINDOW_EXPIRED, 409)
        assert_fields(world.read_subscription(scene["subscription_a_id"]), status="ACCEPTED")
        assert_fields(
            world.read_investor(scene["avery_id"]),
            total_shares_e4=96500000,
            cumulative_invested_cents=10000000,
            account_status="ACTIVE",
        )


# ─── Halcyon: the escrow failure rollback ─────────────────────────────


def _halcyon_underfunded_escrow(world: ReitWorld) -> Dict[str, Any]:
    """Two 10,000,000-cent escrowed tickets against a 30,000,000-cent minimum.

    ``escrow_balance_cents`` therefore stands at 20,000,000 — short of the
    minimum — and the clock is advanced to 2027-01-01, one day past the
    offering's escrow deadline of 2026-12-31.
    """
    off = world.offering(
        name="Halcyon Opportunity REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    sc_i = world.share_class(off["id"], class_code="I", **ZERO_LOAD)
    firm = world.broker_dealer(
        firm_name="Halcyon Placement LLC", crd_number="CRD-170001"
    )
    agreement = world.selling_agreement(
        off["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(off["id"])
    world.activate_agreement(agreement["id"])

    hollis = world.investor(
        legal_name="Hollis Vandermeer",
        email="hollis.vandermeer@example.com",
        state_code="TX",
        net_worth_cents=500000000,
        annual_income_cents=100000000,
    )
    world.document_suitability(hollis["id"], "SUIT-H-2026-08")
    odalys = world.investor(
        legal_name="Odalys Menendez",
        email="odalys.menendez@example.com",
        state_code="TX",
        net_worth_cents=500000000,
        annual_income_cents=100000000,
    )
    world.document_suitability(odalys["id"], "SUIT-O-2026-08")

    sub_h = world.subscription(off["id"], sc_i["id"], hollis["id"], agreement["id"], 10000000)
    world.escrow_subscription(sub_h["id"])
    sub_o = world.subscription(off["id"], sc_i["id"], odalys["id"], agreement["id"], 10000000)
    world.escrow_subscription(sub_o["id"])

    world.set_clock("2027-01-01T00:00:00Z", COMPLIANCE)
    return {
        "offering_id": off["id"],
        "share_class_i_id": sc_i["id"],
        "hollis_id": hollis["id"],
        "odalys_id": odalys["id"],
        "subscription_h_id": sub_h["id"],
        "subscription_o_id": sub_o["id"],
    }


class TestEscrowFailureRefundRestoresZeroEscrowBalance:
    """PRD §3.5: failing escrow rolls the fundraise back and kills the plan."""

    def test_failure_refunds_every_escrowed_subscription_with_the_escrow_reason(
        self, api, world
    ):
        """Both escrowed tickets land in REFUNDED carrying the reason ESCROW_FAILED.

        PRD §3.5: "Failure increments the offering's `version`, drives every
        `ESCROWED` subscription of the offering to `REFUNDED` with
        `rejection_reason` set to `ESCROW_FAILED`, zeroes `escrow_balance_cents`,
        and moves `repurchase_plan_status` to the terminal `TERMINATED`, because
        an offering that never raised its minimum has no plan to run."

        Design: Difficulty/compensating_invariant/escrow_failure_refund_restores_zero_escrow_balance
        """
        scene = _halcyon_underfunded_escrow(world)

        assert_ok(api.drive_escrow(scene["offering_id"], {"action": "FAIL"}, COMPLIANCE))

        assert_fields(
            world.read_subscription(scene["subscription_h_id"]),
            status="REFUNDED",
            rejection_reason="ESCROW_FAILED",
        )
        assert_fields(
            world.read_subscription(scene["subscription_o_id"]),
            status="REFUNDED",
            rejection_reason="ESCROW_FAILED",
        )

    def test_failure_leaves_no_money_no_shares_and_no_plan(self, api, world):
        """Escrow, proceeds, valuation and both holdings all read zero after the failure.

        PRD §3.5: "`FAIL` is the other exit, taking `COLLECTING` to the terminal
        `FAILED`."
        PRD §3.5: "Failure increments the offering's `version`, drives every
        `ESCROWED` subscription of the offering to `REFUNDED` with
        `rejection_reason` set to `ESCROW_FAILED`, zeroes `escrow_balance_cents`,
        and moves `repurchase_plan_status` to the terminal `TERMINATED`, because
        an offering that never raised its minimum has no plan to run."

        Design: Difficulty/compensating_invariant/escrow_failure_refund_restores_zero_escrow_balance
        """
        scene = _halcyon_underfunded_escrow(world)

        assert_ok(api.drive_escrow(scene["offering_id"], {"action": "FAIL"}, COMPLIANCE))

        assert_fields(
            world.read_offering(scene["offering_id"]),
            escrow_status="FAILED",
            escrow_balance_cents=0,
            gross_proceeds_cents=0,
            aggregate_nav_cents=0,
            repurchase_plan_status="TERMINATED",
        )
        assert_fields(
            world.read_share_class(scene["share_class_i_id"]), shares_outstanding_e4=0
        )
        assert_fields(
            world.read_investor(scene["hollis_id"]),
            total_shares_e4=0,
            cumulative_invested_cents=0,
        )
        assert_fields(world.read_investor(scene["odalys_id"]), total_shares_e4=0)

    def test_failure_does_not_disturb_the_registration_axis(self, api, world):
        """The offering is still EFFECTIVE even though its escrow axis is terminal.

        PRD §2.10: "A change on one axis never implies a change on another unless
        a rule in §3 says so explicitly."

        Design: Difficulty/compensating_invariant/escrow_failure_refund_restores_zero_escrow_balance
        """
        scene = _halcyon_underfunded_escrow(world)

        assert_ok(api.drive_escrow(scene["offering_id"], {"action": "FAIL"}, COMPLIANCE))

        assert_fields(
            world.read_offering(scene["offering_id"]),
            registration_status="EFFECTIVE",
            escrow_status="FAILED",
        )

    def test_break_after_failure_cannot_revive_the_offering(self, api, world):
        """A later BREAK on the terminal FAILED axis is refused as an invalid transition.

        PRD §2.10: "It carries three independent axes, each with its own state
        machine and its own transition vocabulary: `registration_status`
        (`DRAFT`, `EFFECTIVE`, `SUSPENDED`, `CLOSED`, with `CLOSED` terminal),
        `escrow_status` (`COLLECTING`, `BROKEN`, `FAILED`, with both `BROKEN` and
        `FAILED` terminal), and `repurchase_plan_status` (`ACTIVE`, `SUSPENDED`,
        `TERMINATED`, with `TERMINATED` terminal)."
        PRD §2.9: "This covers terminal-state lockdown and repeated triggers —
        paying an already paid declaration, processing an already processed
        period, breaking an already broken escrow."

        Design: Difficulty/compensating_invariant/escrow_failure_refund_restores_zero_escrow_balance
        """
        scene = _halcyon_underfunded_escrow(world)
        assert_ok(api.drive_escrow(scene["offering_id"], {"action": "FAIL"}, COMPLIANCE))

        response = api.drive_escrow(scene["offering_id"], {"action": "BREAK"}, COMPLIANCE)

        assert_error(response, ApiErrorId.INVALID_STATE_TRANSITION, 409)
        assert_fields(
            world.read_offering(scene["offering_id"]),
            escrow_status="FAILED",
            escrow_balance_cents=0,
        )
