"""The escrow break settles everything inside its own request.

Every test builds the whole of its own world against an empty database, with the
logical clock at its boot instant of 2026-08-01T00:00:00Z (PRD §2.6).
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    EscrowAction,
    EscrowStatus,
    ShareLotStatus,
    SubscriptionStatus,
    assert_fields,
    assert_ok,
    assert_total_count,
)
from test_helpers.fixtures import ReitWorld


def _veylancourt_world(world: ReitWorld) -> dict:
    """An EFFECTIVE offering holding 30250000 cents of escrow across two stockholders."""
    offering = world.offering(name="Veylancourt Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(
        firm_name="Veylancourt Placement", crd_number="CRD-370001"
    )
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    major = world.investor(
        legal_name="Zaid Okafor",
        email="zaid.okafor@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(major["id"], "SUIT-ZAID-2026-08")
    minor = world.investor(
        legal_name="Aoife Ledger",
        email="aoife.ledger@example.com",
        state_code="TX",
        net_worth_cents=4000000000,
        annual_income_cents=900000000,
    )
    world.document_suitability(minor["id"], "SUIT-AOIFE-2026-08")
    subscription_a = world.subscription(
        offering["id"], share_class["id"], major["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription_a["id"])
    subscription_b = world.subscription(
        offering["id"], share_class["id"], minor["id"], agreement["id"], 250000
    )
    world.escrow_subscription(subscription_b["id"])
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "major_id": major["id"],
        "minor_id": minor["id"],
        "subscription_a_id": subscription_a["id"],
        "subscription_b_id": subscription_b["id"],
    }


class TestEscrowBreakIsImmediatelyConsistent:
    """PRD §2.10: the request that disturbs a derived figure also recomputes it."""

    def test_the_break_response_itself_already_carries_every_cascaded_total(
        self, world: ReitWorld, api
    ):
        """The 200 body — not a follow-up read — shows the swept balance, the proceeds and the aggregate.

        PRD §2.10: "Derived figures are never stale."
        PRD §2.10: "An offering's `escrow_balance_cents`, `gross_proceeds_cents` and `aggregate_nav_cents`, a share class's `shares_outstanding_e4`, a stockholder's `concentration_limit_cents`, `cumulative_invested_cents`, `total_shares_e4`, `cumulative_distributions_received_cents` and `cumulative_early_repurchase_deduction_cents`, a firm's `suspended_agreement_count`, an agreement's `open_minor_finding_count` and `open_major_finding_count`, and a lot's `remaining_shares_e4` and `cumulative_distribution_fee_cents` are all recomputed synchronously within the request that disturbs them, and are visible on the very next read."
        PRD §3.8: "`aggregate_nav_cents` is the sum, taken over every share class of the offering, of each class's transaction price multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up — each class's contribution rounded to a whole cent on its own before the contributions are added."

        Design: Corner/consistency_model/the_escrow_break_response_already_shows_every_cascaded_total
        """
        setup = _veylancourt_world(world)
        assert_fields(
            world.read_offering(setup["offering_id"]),
            escrow_balance_cents=30250000,
            gross_proceeds_cents=0,
            aggregate_nav_cents=0,
        )

        broken = assert_ok(
            api.drive_escrow(
                setup["offering_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
            )
        )
        assert_fields(
            broken,
            escrow_status=EscrowStatus.BROKEN,
            escrow_balance_cents=0,
            gross_proceeds_cents=30250000,
            aggregate_nav_cents=30250000,
        )

    def test_every_row_the_break_cascaded_into_is_readable_on_the_next_call(
        self, world: ReitWorld, api
    ):
        """Subscriptions, class shares, the statement and both lots are settled with no delay.

        PRD §2.10: "Cascades are equally synchronous."
        PRD §3.5: "The offering's `version` increments; every subscription of the offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at` order; one share lot is minted per accepted subscription with `issued_date` set to the current logical clock instant; `shares_outstanding_e4` on every touched class and `total_shares_e4` on every touched stockholder are recomputed; each affected stockholder's `cumulative_invested_cents` is recomputed and their `suitability_status` re-evaluated against `concentration_limit_cents`, so a stockholder pushed over the limit by the batch lands in `FLAGGED`; and the whole of `escrow_balance_cents` is moved into `gross_proceeds_cents`."

        Design: Corner/consistency_model/the_escrow_break_response_already_shows_every_cascaded_total
        """
        setup = _veylancourt_world(world)
        assert_ok(
            api.drive_escrow(
                setup["offering_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
            )
        )

        assert_fields(
            assert_ok(api.get_subscription(setup["subscription_a_id"], SPONSOR)),
            status=SubscriptionStatus.ACCEPTED,
        )
        assert_fields(
            assert_ok(api.get_subscription(setup["subscription_b_id"], SPONSOR)),
            status=SubscriptionStatus.ACCEPTED,
        )
        assert_fields(
            assert_ok(api.get_share_class(setup["share_class_id"], SPONSOR)),
            shares_outstanding_e4=302500000,
        )

        statement = assert_ok(
            api.get_investor_statement(setup["major_id"], TRANSFER_AGENT)
        )
        assert_fields(
            statement,
            total_shares_e4=300000000,
            open_lot_count=1,
            cumulative_invested_cents=30000000,
            estimated_value_cents=30000000,
        )

        minor_lots = assert_total_count(
            api.list_share_lots({"investor_id": setup["minor_id"]}, TRANSFER_AGENT), 1
        )
        assert_fields(
            minor_lots[0],
            original_shares_e4=2500000,
            remaining_shares_e4=2500000,
            status=ShareLotStatus.OPEN,
        )
        assert minor_lots[0]["issued_date"].startswith("2026-08-01T00:00:00"), (
            "the lot is stamped with the current logical clock instant, "
            f"got {minor_lots[0]['issued_date']!r}"
        )

        assert_total_count(
            api.list_share_lots(
                {"share_class_id": setup["share_class_id"]}, TRANSFER_AGENT
            ),
            2,
        )
