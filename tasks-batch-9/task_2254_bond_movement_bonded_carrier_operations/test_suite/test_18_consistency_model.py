"""Read-your-writes: one claim issuance, and every entity it touches already
tells the same story on the very next read."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_entry,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    LATE_ARRIVAL_ASSESSED,
    LATE_ARRIVAL_CLOCK,
    build_departed_movement,
)


class TestClaimIssuanceIsImmediatelyVisible:
    """No lag anywhere: the response and every follow-up read agree."""

    def test_the_claim_response_and_the_reads_after_it_agree_on_every_figure(
        self, client
    ):
        """The issuance response already carries the assessed 1,234.60 and the seven
        overdue days, and the bond, the carrier, the ledger and the movement read
        immediately afterwards each show the consequence of that same request.

        PRD: "Otherwise the measure is the number of seconds from the deadline to the reference instant divided by 86,400 and rounded **up** to the next whole number, so any fraction of a day counts as a full overdue day and an interval of exactly seven days measures 7."

        PRD: "A cap is then taken as the lesser of the movement's `cargo_value` and the underwriting bond's `limit_amount`, and `assessed_amount` is the lesser of the raw assessment and that cap, rounded half-up to two decimal places."

        PRD: "An issued claim opens at `status` `ISSUED` with `bond_id` copied from the movement, `issued_by_officer_id` set to the issuing officer's `X-User-ID`, `issued_at` stamped from the logical clock, `mitigated_amount` null, `paid_amount` null, and `cancellation_reason` null."

        PRD: "It appends an `INCREASE_LD` ledger entry for the positive `assessed_amount` with `reason_code` `CLAIM_ISSUED`, which recomputes the bond's `obligated_amount` and `available_amount` and may drive the bond to `SATURATED`."

        PRD: "It also recomputes the carrier's `open_claim_count` and `sanction_points`, and it records on the claim, as `sanction_points_applied`, the undecayed severity points the claim contributes to that score."

        PRD: "Each entry also stamps `recorded_at` from the logical clock and stores `balance_after`, the bond's obligated amount immediately after that entry was applied."

        PRD: "This measure produces the movement's `overdue_days` during a sweep, with the sweep's clock as the reference instant, and it produces a claim's `overdue_days_at_issue` at issuance."

        Design: Corner/consistency_model/claim_issuance_is_visible_immediately_across_every_touched_entity
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock(LATE_ARRIVAL_CLOCK)
        world.report_arrival(movement_id)

        claim = validate_success(
            client.issue_claim(
                factories.claim_payload(movement_id, "LATE_ARRIVAL", "OVERDUE_ARRIVAL"),
                world.officer,
            ),
            201,
        )
        assert_money(claim["assessed_amount"], LATE_ARRIVAL_ASSESSED, "assessed_amount")
        assert_field(claim, "overdue_days_at_issue", 7, "claim")
        assert_field(claim, "bond_id", world.bond_id, "claim")
        assert_field(claim, "status", "ISSUED", "claim")

        assert_bond_amounts(
            world.read_bond(),
            obligated=1276.35,
            available=48723.65,
            status="ACTIVE",
        )

        carrier = world.read_carrier()
        assert_points(carrier["sanction_points"], 2.0)
        assert_field(carrier, "open_claim_count", 1, "carrier")
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")

        entries = world.ledger_entries(
            claim_id=claim["id"], entry_type="INCREASE_LD"
        )
        assert len(entries) == 1, (
            f"the issuance should have written exactly one INCREASE_LD entry but the "
            f"claim has {len(entries)}"
        )
        assert_ledger_entry(
            entries[0],
            entry_type="INCREASE_LD",
            amount=LATE_ARRIVAL_ASSESSED,
            balance_after=1276.35,
            reason_code="CLAIM_ISSUED",
        )

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="ARRIVED")
        assert_field(movement, "overdue_days", 0, "movement")
