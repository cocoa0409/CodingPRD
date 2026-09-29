"""Cancelling a claim compensates what it charged: the money nets to nothing and
the risk score returns to what the surviving violations justify — but freight the
cascade already cancelled is not brought back."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_nets_to_zero,
    assert_ledger_stream,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    LATE_ARRIVAL_ASSESSED,
    M1_OBLIGATION,
    build_late_arrival_claim,
    build_suspension_cascade_world,
)


class TestCancelledClaimNetsItsMoneyToZero:
    """The two ledger entries a cancelled claim leaves behind sum to exactly
    nothing, and the bond returns to its pre-claim numbers."""

    def test_issuing_the_claim_charges_the_bond_with_an_increase_entry(self, client):
        """A seven-day late arrival is assessed 1,234.60 and the INCREASE_LD entry
        takes the bond from 41.75 to 1,276.35 obligated.

        PRD: "It appends an `INCREASE_LD` ledger entry for the positive `assessed_amount` with `reason_code` `CLAIM_ISSUED`, which recomputes the bond's `obligated_amount` and `available_amount` and may drive the bond to `SATURATED`."

        Design: Difficulty/compensating_invariant/cancelling_a_claim_nets_its_ledger_stream_to_zero
        """
        world, claim = build_late_arrival_claim(client)

        assert_money(claim["assessed_amount"], LATE_ARRIVAL_ASSESSED, "assessed_amount")
        assert_field(claim, "overdue_days_at_issue", 7, "claim")

        assert_bond_amounts(
            world.read_bond(),
            obligated=1276.35,
            available=48723.65,
            status="ACTIVE",
        )
        assert_ledger_stream(
            world.ledger_entries(claim_id=claim["id"]),
            [
                {
                    "entry_type": "INCREASE_LD",
                    "amount": LATE_ARRIVAL_ASSESSED,
                    "balance_after": 1276.35,
                    "reason_code": "CLAIM_ISSUED",
                }
            ],
        )

    def test_cancelling_the_claim_releases_exactly_what_it_charged(self, client):
        """The RELEASE_LD entry is the negative of the assessment, so the stream for
        the claim nets to 0.00 and the bond is back at 41.75 obligated — the
        movement's own obligation, untouched throughout.

        PRD: "Cancellation records the supplied `reason_code` in `cancellation_reason`, moves the claim to `CANCELLED`, and appends a `RELEASE_LD` ledger entry with `reason_code` `CLAIM_CANCELLED` whose `amount` is the negative of whatever remained obligated on the claim — the full `assessed_amount` when no mitigation had been recorded, or the `mitigated_amount` when a `MITIGATE` entry had already released the difference — so that the net of all ledger entries carrying that `claim_id` becomes exactly 0.00."

        Design: Difficulty/compensating_invariant/cancelling_a_claim_nets_its_ledger_stream_to_zero
        """
        world, claim = build_late_arrival_claim(client)

        cancelled = validate_success(
            client.dispose_claim(
                claim["id"],
                factories.claim_cancellation_payload("CLAIM_ISSUED_IN_ERROR"),
                world.fpf_officer,
            ),
            200,
        )
        assert_field(cancelled, "status", "CANCELLED", "claim")
        assert_field(cancelled, "mitigated_amount", None, "claim")

        entries = world.ledger_entries(claim_id=claim["id"])
        assert_ledger_stream(
            entries,
            [
                {
                    "entry_type": "INCREASE_LD",
                    "amount": LATE_ARRIVAL_ASSESSED,
                    "balance_after": 1276.35,
                },
                {
                    "entry_type": "RELEASE_LD",
                    "amount": -LATE_ARRIVAL_ASSESSED,
                    "balance_after": M1_OBLIGATION,
                    "reason_code": "CLAIM_CANCELLED",
                },
            ],
        )
        assert_ledger_nets_to_zero(entries, "the cancelled late-arrival claim")

        assert_bond_amounts(
            world.read_bond(),
            obligated=M1_OBLIGATION,
            available=49958.25,
            status="ACTIVE",
        )

        movement = world.read_movement(world.movements["MAN-0001"])
        assert_movement_state(movement, transit_status="ARRIVED")
        assert_money(movement["obligation_amount"], M1_OBLIGATION, "obligation_amount")


class TestCancelledClaimRestoresPointsButNotFreight:
    """Dropping the claim out of the countable set reinstates the carrier, but the
    movement the suspension cascade cancelled stays cancelled."""

    def test_cancelling_the_second_claim_reinstates_the_carrier(self, client):
        """With the six-point non-arrival claim excluded, the score falls back to the
        surviving seal violation's 4.0 and the carrier returns to ACTIVE.

        PRD: "Cancellation then recomputes the carrier's `sanction_points` with this claim excluded from the countable set, and when the result falls strictly below 10.0 the carrier transitions `SUSPENDED → ACTIVE` with `suspension_reason` cleared."

        Design: Difficulty/compensating_invariant/cancelling_the_claim_restores_sanction_points_but_not_cancelled_movements
        """
        world, seal_claim = build_suspension_cascade_world(client)
        non_arrival = world.issue_claim(
            world.movements["MAN-0001"], "NON_ARRIVAL", "NEVER_ARRIVED"
        )
        assert_field(world.read_carrier(), "custodial_status", "SUSPENDED", "carrier")

        cancelled = world.cancel_claim(non_arrival["id"], "VIOLATION_NOT_SUSTAINED")
        assert_field(cancelled, "status", "CANCELLED", "claim")
        assert_field(world.read_claim(seal_claim["id"]), "status", "ISSUED", "claim")

        carrier = world.read_carrier()
        assert_points(carrier["sanction_points"], 4.0)
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")
        assert_field(carrier, "suspension_reason", None, "carrier")

        assert_ledger_nets_to_zero(
            world.ledger_entries(claim_id=non_arrival["id"]),
            "the cancelled non-arrival claim",
        )

    def test_the_cascade_cancelled_movement_is_never_reinstated(self, client):
        """MAN-0003 keeps its CARRIER_SUSPENSION_CASCADE cancellation and its 41.75
        is not re-obligated, so the bond stands at 1,041.75 — the surviving claim
        plus the one movement still in flight.

        PRD: "If a later recomputation brings the score back strictly below 10.0 — which happens when a claim is cancelled and drops out of the countable set — the carrier returns `SUSPENDED → ACTIVE` and `suspension_reason` is cleared to null, but movements the cascade already cancelled are **never** reinstated."

        Design: Difficulty/compensating_invariant/cancelling_the_claim_restores_sanction_points_but_not_cancelled_movements
        """
        world, _seal_claim = build_suspension_cascade_world(client)
        non_arrival = world.issue_claim(
            world.movements["MAN-0001"], "NON_ARRIVAL", "NEVER_ARRIVED"
        )
        world.cancel_claim(non_arrival["id"], "VIOLATION_NOT_SUSTAINED")

        cascaded = world.read_movement(world.movements["MAN-0003"])
        assert_movement_state(cascaded, transit_status="CANCELLED")
        assert_field(
            cascaded, "cancellation_reason", "CARRIER_SUSPENSION_CASCADE", "movement"
        )

        assert_movement_state(
            world.read_movement(world.movements["MAN-0001"]),
            transit_status="OVERDUE",
        )

        assert_bond_amounts(
            world.read_bond(),
            obligated=1041.75,
            available=48958.25,
            status="ACTIVE",
            open_movement_count=1,
        )
