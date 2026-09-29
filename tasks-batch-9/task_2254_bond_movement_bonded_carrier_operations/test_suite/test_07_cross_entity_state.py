"""One entity's state decides what may be done to another: a revoked carrier
blocks new filings, and a cancelled claim closes its petition's supplement."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_money,
    assert_movement_state,
)
from test_helpers.fixtures import (
    M1_OBLIGATION,
    build_departed_movement,
    build_supplement_requested_petition,
)


class TestRevokedCarrierAndItsInFlightFreight:
    """Revoking custodial privileges stops the next filing without disturbing the
    consignment that is already on the road."""

    def _revoked_carrier_world(self, client):
        world = build_departed_movement(client)
        validate_success(
            client.patch_carrier(
                world.carrier_id,
                factories.carrier_status_payload("REVOKED", "PRIVILEGE_REVOKED"),
                world.officer,
            ),
            200,
        )
        return world

    def test_a_revoked_carrier_cannot_file_a_new_movement(self, client):
        """The filing payload that succeeded while the carrier was ACTIVE is refused
        as soon as its privileges are revoked.

        PRD: "Before the filing is accepted, the carrier's `custodial_status` must be `ACTIVE` — a `SUSPENDED` or `REVOKED` carrier may neither file nor depart, and the refusal is `ERR_CARRIER_NOT_ACTIVE` — and the resolved bond's `status` must be `ACTIVE`, with `SATURATED`, `SUSPENDED`, and `EXPIRED` all refused as `ERR_BOND_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/revoked_carrier_blocks_new_filing_but_not_movements_already_in_transit
        """
        world = self._revoked_carrier_world(client)

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0021",
                bond_id=world.bond_id,
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_CARRIER_NOT_ACTIVE)

        carrier = world.read_carrier()
        assert_field(carrier, "custodial_status", "REVOKED", "carrier")
        assert_field(carrier, "suspension_reason", "PRIVILEGE_REVOKED", "carrier")

        _rows, meta = world.movement_list(carrier_id=world.carrier_id)
        assert meta["total_count"] == 1, (
            f"only the movement filed before the revocation should exist but the "
            f"carrier has {meta['total_count']}"
        )

    def test_revocation_leaves_the_departed_movement_and_its_obligation_alone(
        self, client
    ):
        """The cascade that follows a revocation reaches only freight still sitting
        at FILED, so the in-transit movement keeps its status and its 41.75 stays
        obligated on the bond.

        PRD: "The same `FILED → CANCELLED` cascade, with the same ledger releases and bond re-derivation, fires when an officer revokes a carrier's privileges."

        Design: Difficulty/cross_entity_state_dependency/revoked_carrier_blocks_new_filing_but_not_movements_already_in_transit
        """
        world = self._revoked_carrier_world(client)
        movement_id = world.movements["MAN-0001"]

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="IN_TRANSIT")
        assert_field(movement, "cancellation_reason", None, "movement")

        assert_bond_amounts(
            world.read_bond(),
            obligated=M1_OBLIGATION,
            available=49958.25,
            status="ACTIVE",
            open_movement_count=1,
        )


class TestCancelledClaimAndItsPetition:
    """Cancelling the claim supersedes the petition hanging off it, which closes
    the supplement the carrier was invited to file."""

    def test_cancelling_the_claim_supersedes_the_open_petition(self, client):
        """The FPF officer cancels a claim whose petition sits in
        SUPPLEMENT_REQUESTED, and the petition is superseded with CLAIM_CANCELLED
        without any of its own numbers moving.

        PRD: "A petition sitting in either `SUBMITTED` or `SUPPLEMENT_REQUESTED` moves to `SUPERSEDED` when a newer petition is filed on the same claim, with `decision_reason_code` `SUPERSEDED_BY_NEWER_PETITION`, or when the claim itself is cancelled, with `decision_reason_code` `CLAIM_CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/cancelling_a_claim_supersedes_its_petition_and_blocks_the_supplement
        """
        world, claim, petition = build_supplement_requested_petition(client, "PET-0031")

        validate_success(
            client.dispose_claim(
                claim["id"],
                factories.claim_cancellation_payload("CLAIM_ISSUED_IN_ERROR"),
                world.fpf_officer,
            ),
            200,
        )

        cancelled = world.read_claim(claim["id"])
        assert_field(cancelled, "status", "CANCELLED", "claim")
        assert_field(
            cancelled, "cancellation_reason", "CLAIM_ISSUED_IN_ERROR", "claim"
        )

        rows, meta = world.petitions(claim["id"])
        assert meta["total_count"] == 1, (
            f"the claim should carry exactly one petition but it carries "
            f"{meta['total_count']}"
        )
        assert_field(rows[0], "status", "SUPERSEDED", "petition")
        assert_field(rows[0], "decision_reason_code", "CLAIM_CANCELLED", "petition")
        assert_field(rows[0], "round", 1, "petition")
        assert rows[0]["id"] == petition["id"], (
            "the superseded petition should be the one filed against the claim"
        )

    def test_the_supplement_is_refused_because_the_petition_was_superseded(
        self, client
    ):
        """The carrier touched nothing of its own, yet the supplement it was asked
        for is now refused: the petition is no longer at SUPPLEMENT_REQUESTED, and
        its round-one offer of 717.30 is left as it stood.

        PRD: "The petition must be sitting at `SUPPLEMENT_REQUESTED` — anything else is `ERR_PETITION_INVALID_STATE` — the acting user must be the claim's carrier, and the petition's `round` must still be below 2, or the supplement is refused with `ERR_PETITION_ROUND_LIMIT`."

        Design: Difficulty/cross_entity_state_dependency/cancelling_a_claim_supersedes_its_petition_and_blocks_the_supplement
        """
        world, claim, petition = build_supplement_requested_petition(client, "PET-0031")
        world.cancel_claim(claim["id"], "CLAIM_ISSUED_IN_ERROR")

        response = client.supplement_petition(
            petition["id"],
            factories.petition_supplement_payload(
                ["FIRST_VIOLATION", "CARGO_SECURED_INTACT"], "PET-0031-S1"
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_PETITION_INVALID_STATE)

        rows, _meta = world.petitions(claim["id"])
        assert_field(rows[0], "status", "SUPERSEDED", "petition")
        assert_field(rows[0], "round", 1, "petition")
        assert_field(rows[0], "narrative_reference", "PET-0031", "petition")
        assert_money(rows[0]["offer_amount"], 717.30, "petition offer_amount")
