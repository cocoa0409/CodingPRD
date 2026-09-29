"""Who may act: the anonymous request, the role gate, the two identity bindings
that tie a role to one specific record, and the segregation-of-duties bar."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_money,
    assert_movement_state,
)
from test_helpers.fixtures import (
    M1_SEAL,
    build_carrier_without_bond,
    build_departed_movement,
    build_filed_movement,
    build_four_factor_petition,
    build_registered_world,
)
from test_helpers.test_users import (
    CBP_OFFICER_1_ID,
    FPF_OFFICER_AS_ISSUER,
    FPF_OFFICER_ID,
    headers_without_identity,
)


class TestAnonymousRequest:
    """No identity headers at all means the request never reaches any rule."""

    def test_a_filing_with_neither_identity_header_is_unauthenticated(self, client):
        """The filing body is perfectly valid and the bond would have covered it, but
        with no `X-User-Role` and no `X-User-ID` the request dies in band 1 and
        nothing is created.

        PRD: "If either header is absent or empty, or if the value of `X-User-Role` is not one of the four recognised role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined — including before the system checks whether the resources named in the path exist."

        PRD: "**Authentication.** `X-User-Role` present and equal to one of `BondedCarrier`, `CBPOfficer`, `FPFOfficer`, `SuretyAgent`, and `X-User-ID` present and non-empty — otherwise `ERR_UNAUTHENTICATED`. Evaluated on every request, ahead of path-parameter existence."

        Design: Corner/rbac/missing_role_header_returns_4XX_for_an_unauthenticated_filing
        """
        world = build_registered_world(client)

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0080",
                bond_id=world.bond_id,
            ),
            headers_without_identity(),
        )
        validate_error(response, api_errors.ERR_UNAUTHENTICATED, 401)

        _rows, meta = world.movement_list(carrier_id=world.carrier_id)
        assert meta["total_count"] == 0, (
            f"an unauthenticated filing must create nothing but the carrier now has "
            f"{meta['total_count']} movements"
        )
        assert_bond_amounts(
            world.read_bond(), obligated=0.00, available=50000.00, status="ACTIVE"
        )


class TestRoleGate:
    """Two operations belong to the officer alone."""

    def test_a_carrier_can_neither_register_a_port_nor_run_a_sweep(self, client):
        """Port registration and the compliance sweep are authorised for the officer
        role only, so both carrier attempts are refused on the role gate and both
        succeed unchanged when the officer makes them.

        PRD: "Once authenticated, the caller's role must appear in the target endpoint's authorised-role list; otherwise the response is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD: "**Role authorisation.** The caller's role appears in the endpoint's authorised list — otherwise `ERR_UNAUTHORIZED`. Evaluated on every request."

        Design: Corner/rbac/carrier_cannot_perform_cbp_officer_exclusive_operations
        """
        world = build_carrier_without_bond(client, port_aliases=["ny"])

        validate_error(
            client.create_port(factories.port_chicago_payload(), world.carrier),
            api_errors.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            client.run_sweep(
                factories.sweep_payload("carrier-initiated sweep"), world.carrier
            ),
            api_errors.ERR_UNAUTHORIZED,
            403,
        )

        _rows, meta = world.sweeps(limit=10, offset=0)
        assert meta["total_count"] == 0, (
            f"the refused sweep must not be recorded but the register holds "
            f"{meta['total_count']}"
        )

        port = validate_success(
            client.create_port(factories.port_chicago_payload(), world.officer), 201
        )
        assert_field(port, "port_code", factories.PORT_CHICAGO_CODE, "port")
        sweep = validate_success(
            client.run_sweep(
                factories.sweep_payload("officer-initiated sweep"), world.officer
            ),
            201,
        )
        assert_field(sweep, "executed_by_officer_id", CBP_OFFICER_1_ID, "sweep")


class TestCarrierIdentityBinding:
    """Holding the carrier role is not the same as owning the movement."""

    def test_another_carrier_cannot_depart_this_carriers_movement(self, client):
        """Beacon holds the carrier role but Atlas owns the movement, so Beacon's
        departure is refused on the identity binding and the movement is still
        waiting, unsealed, at version 1 — and Atlas can then depart it.

        PRD: "On a filing, `X-User-ID` must equal the `carrier_id` supplied in the request body; on every other carrier-driven write, it must equal the `carrier_id` of the movement being acted on — including when the movement is reached indirectly through a report, an amendment request, a claim, or a petition."

        PRD: "A mismatch is `ERR_NOT_MOVEMENT_CARRIER` (HTTP 403)."

        Design: Corner/rbac/one_carrier_cannot_depart_another_carriers_movement
        """
        world = build_filed_movement(client)
        movement_id = world.movements["MAN-0001"]
        other_carrier_id = world.register_carrier(factories.second_carrier_payload())

        response = client.depart_movement(
            movement_id,
            factories.departure_payload("SEAL-999"),
            world.carrier_headers(other_carrier_id),
        )
        validate_error(response, api_errors.ERR_NOT_MOVEMENT_CARRIER, 403)

        untouched = world.read_movement(movement_id)
        assert_movement_state(untouched, transit_status="FILED")
        assert_field(untouched, "seal_number", None, "movement")
        assert_field(untouched, "version", 1, "movement")
        assert len(world.seal_events(movement_id)) == 0, (
            "the refused departure must not record a seal event"
        )

        departed = validate_success(
            client.depart_movement(
                movement_id, factories.departure_payload(M1_SEAL), world.carrier
            ),
            200,
        )
        assert_movement_state(departed, transit_status="IN_TRANSIT")
        assert_field(departed, "seal_number", M1_SEAL, "movement")


class TestSuretyIdentityBinding:
    """A surety agent's user identifier *is* the one bond it administers."""

    def test_a_surety_cannot_suspend_a_bond_it_does_not_underwrite(self, client):
        """Acting as the surety of the first bond, the same caller is refused on the
        second bond and leaves it ACTIVE at version 1, while the identical call
        against its own bond suspends it without moving any money.

        PRD: "When `X-User-Role` is `SuretyAgent`, `X-User-ID` is the `id` of the acting `CustomsBond` — the surety's user identifier *is* the bond identifier it administers. Administering any bond other than the one named in the path yields `ERR_NOT_BOND_SURETY` (HTTP 403)."

        PRD: "The only status edges a surety may drive are `ACTIVE → SUSPENDED`, `SATURATED → SUSPENDED`, and `SUSPENDED → ACTIVE`; requesting anything else — touching an `EXPIRED` bond, or setting `SATURATED` by hand — is `ERR_BOND_INVALID_STATE`."

        PRD: "A new bond opens at `status` `ACTIVE`, with `obligated_amount` 0.00, `available_amount` equal to `limit_amount`, and `open_movement_count` 0."

        Design: Corner/rbac/surety_cannot_patch_a_bond_it_does_not_underwrite
        """
        world = build_carrier_without_bond(client)
        own_bond = world.underwrite_bond()
        other_bond = world.underwrite_bond(
            factories.continuous_bond_payload(
                world.carrier_id, limit_amount=30000.00, surety_code="SUR-200"
            )
        )

        response = client.patch_bond(
            other_bond,
            factories.bond_status_payload("SUSPENDED"),
            world.surety_headers(own_bond),
        )
        validate_error(response, api_errors.ERR_NOT_BOND_SURETY, 403)

        spared = world.read_bond(other_bond)
        assert_field(spared, "status", "ACTIVE", "bond")
        assert_field(spared, "version", 1, "bond")

        suspended = validate_success(
            client.patch_bond(
                own_bond,
                factories.bond_status_payload("SUSPENDED"),
                world.surety_headers(own_bond),
            ),
            200,
        )
        assert_field(suspended, "status", "SUSPENDED", "bond")
        assert_money(suspended["available_amount"], 50000.00, "available_amount")


class TestSegregationOfDutiesOnHolds:
    """The officer who opened an examination may not be the one who clears it."""

    def test_the_placing_officer_cannot_release_the_hold_but_a_colleague_can(
        self, client
    ):
        """The officer recorded in `placed_by_user_id` is barred from the release, so
        the hold stays OPEN and the port still counts it; the second officer's
        identical release closes it and hands custody back.

        PRD: "Symmetrically, the officer whose `X-User-ID` was stored in `placed_by_user_id` on an examination hold may not release that hold."

        PRD: "All three violations return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD: "When the released hold was the **last** open hold on the movement, custody reverts `EXAM_HOLD → BONDED` — never straight to `RELEASED` — and, if the movement had already reached `EXPORTED`, it now auto-closes `EXPORTED → CLOSED` with its `RELEASE` ledger entry and the bond recomputation that entry entails."

        Design: Corner/rbac/officer_who_placed_a_hold_cannot_release_it
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        hold = world.place_unscheduled_hold(movement_id)

        response = client.release_hold(
            hold["id"], factories.hold_release_payload("CLEAR"), world.officer
        )
        validate_error(response, api_errors.ERR_SEGREGATION_OF_DUTIES, 403)

        assert_field(world.read_hold(hold["id"]), "status", "OPEN", "hold")
        assert_field(world.read_port("chicago"), "open_hold_count", 1, "port")

        released = validate_success(
            client.release_hold(
                hold["id"],
                factories.hold_release_payload("CLEAR"),
                world.second_officer,
            ),
            200,
        )
        assert_field(released, "status", "RELEASED", "hold")
        assert_field(released, "placed_by_user_id", CBP_OFFICER_1_ID, "hold")

        assert_movement_state(
            world.read_movement(movement_id), custody_status="BONDED"
        )
        assert_field(world.read_port("chicago"), "open_hold_count", 0, "port")


class TestSegregationOfDutiesOnClaims:
    """The operator identifier that issued a claim is barred from both later
    decisions, whichever role it wears."""

    def test_the_claim_issuer_can_neither_decide_the_petition_nor_cancel_the_claim(
        self, client
    ):
        """OFF-1 issued the claim, so OFF-1 wearing the adjudicating role is refused
        both the petition decision and the cancellation; the untainted adjudicator
        then denies the petition, which returns the claim to ISSUED and moves no
        money at all.

        PRD: "The officer whose `X-User-ID` was stored in `issued_by_officer_id` on a claim may never decide a petition against that claim and may never dispose of that claim, even if that same operator identifier arrives wearing the `FPFOfficer` role."

        PRD: "All three violations return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD: "`DENY` moves the petition `SUBMITTED → DENIED` and cycles the claim `PETITIONED → ISSUED` with no ledger movement at all, leaving the full `assessed_amount` obligated."

        Design: Corner/rbac/claim_issuer_cannot_decide_the_petition_or_cancel_the_claim
        """
        world, claim, petition = build_four_factor_petition(
            client, narrative_reference="PET-0111"
        )
        assert_field(claim, "issued_by_officer_id", CBP_OFFICER_1_ID, "claim")

        validate_error(
            client.decide_petition(
                petition["id"],
                factories.petition_decision_payload("DENY", "NO_MITIGATION"),
                FPF_OFFICER_AS_ISSUER,
            ),
            api_errors.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            client.dispose_claim(
                claim["id"],
                factories.claim_cancellation_payload("ISSUED_IN_ERROR"),
                FPF_OFFICER_AS_ISSUER,
            ),
            api_errors.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        assert_field(world.read_claim(claim["id"]), "status", "PETITIONED", "claim")
        pending_rows, _pending_meta = world.petitions(claim["id"])
        assert_field(pending_rows[0], "status", "SUBMITTED", "petition")

        denied = validate_success(
            client.decide_petition(
                petition["id"],
                factories.petition_decision_payload("DENY", "NO_MITIGATION"),
                world.fpf_officer,
            ),
            200,
        )
        assert_field(denied, "status", "DENIED", "petition")
        assert_field(denied, "decided_by_user_id", FPF_OFFICER_ID, "petition")

        reopened = world.read_claim(claim["id"])
        assert_field(reopened, "status", "ISSUED", "claim")
        assert_field(reopened, "issued_by_officer_id", CBP_OFFICER_1_ID, "claim")
        assert_field(reopened, "mitigated_amount", None, "claim")
        assert_bond_amounts(world.read_bond(), obligated=1276.35)
