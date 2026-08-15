"""Checkout lifecycle: cross-entity gates, returns, verify, dispute loop,
and invalid triggers."""
from test_helpers import (
    ApiErrorId,
    api_client,
    borrow_packet,
    create_member,
    get_member,
    get_packet,
    make_member_headers,
    return_checkout_as_member,
    setup_active_lot,
    TEST_USERS,
    validate_error,
    validate_success,
    verify_return,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCheckoutGatedByLotState:
    def _setup_lot_in_quarantine_with_available_packet(self):
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        resp = api_client.recheck_seed_lot(ctx["lot"]["id"], ADMIN)
        validate_success(resp, 200)
        member = create_member(ctx["site"]["id"])
        return ctx, member

    def test_checkout_rejected_when_parent_lot_not_active(self):
        """PRD §3.5: "The packet's lot must be `ACTIVE`, else
        `ERR_LOT_NOT_ACTIVE`; a variety retired behind the lot likewise blocks
        creation under the generic state rule."

        The packet itself is AVAILABLE; the parent lot sitting in QUARANTINE
        blocks the borrow.

        Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_seedlot_state
        """
        ctx, member = self._setup_lot_in_quarantine_with_available_packet()
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": ctx["packet_ids"][0]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACTIVE)

    def test_rejected_checkout_leaves_no_side_effects(self):
        """PRD §3.5: "The packet's lot must be `ACTIVE`, else
        `ERR_LOT_NOT_ACTIVE`; a variety retired behind the lot likewise blocks
        creation under the generic state rule."

        After the rejection the packet is still AVAILABLE and the member's
        active_checkout_count is still 0 — no partial mutation.

        Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_seedlot_state
        """
        ctx, member = self._setup_lot_in_quarantine_with_available_packet()
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": ctx["packet_ids"][0]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACTIVE)
        packet = get_packet(ctx["packet_ids"][0])
        assert packet["status"] == "AVAILABLE", (
            f"Rejected checkout must not move the packet, got "
            f"{packet['status']}"
        )
        member_now = get_member(member["id"])
        assert member_now["active_checkout_count"] == 0


class TestDisputeLoopCycle:
    def test_dispute_from_returned_and_return_accepted_loop_edge(self):
        """PRD §3.5: "From `RETURNED`, an administrator opens a dispute — the
        inspection failed, the packet came back damaged — moving the checkout
        to `DISPUTED`."
        PRD §3.5: "Resolution is administrator-only and takes an `outcome`:
        `RETURN_ACCEPTED` loops the checkout back to `RETURNED` so verification
        can proceed normally, while `WRITE_OFF` terminates it as `WRITTEN_OFF`
        and runs the write-off cascade".

        Design: Difficulty/non_linear_state_machine/checkout_return_dispute_loop_cycle
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        return_checkout_as_member(checkout["id"], member["id"])

        resp = api_client.dispute_checkout(
            checkout["id"], {"reason": "packet damaged on return"}, ADMIN
        )
        disputed = validate_success(resp, 200)
        assert disputed["status"] == "DISPUTED"

        resp = api_client.resolve_dispute(
            checkout["id"], {"outcome": "RETURN_ACCEPTED"}, ADMIN
        )
        looped = validate_success(resp, 200)
        assert looped["status"] == "RETURNED", (
            "RETURN_ACCEPTED loops DISPUTED -> RETURNED"
        )

    def test_second_loop_iteration_then_write_off_terminates(self):
        """PRD §3.5: "Resolution is administrator-only and takes an `outcome`:
        `RETURN_ACCEPTED` loops the checkout back to `RETURNED` so verification
        can proceed normally, while `WRITE_OFF` terminates it as `WRITTEN_OFF`
        and runs the write-off cascade — the held packet, whether `CHECKED_OUT`
        or `RETURNED`, becomes `DISCARDED` with its seeds moving to the
        discarded bucket; the member's terminal count rises by one, the
        overdue count falls by one when it had been flipped, rates and tier
        are recomputed, and the same auto-reinstatement check applies".

        Two full RETURNED<->DISPUTED iterations, then WRITE_OFF; member
        terminal counters move only at the final write-off.

        Design: Difficulty/non_linear_state_machine/checkout_return_dispute_loop_cycle
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        return_checkout_as_member(checkout["id"], member["id"])

        for _ in range(2):
            resp = api_client.dispute_checkout(checkout["id"], {}, ADMIN)
            assert validate_success(resp, 200)["status"] == "DISPUTED"
            member_mid = get_member(member["id"])
            assert member_mid["terminal_checkout_count"] == 0, (
                "loop iterations must not move terminal counters"
            )
            if _ == 0:
                resp = api_client.resolve_dispute(
                    checkout["id"], {"outcome": "RETURN_ACCEPTED"}, ADMIN
                )
                assert validate_success(resp, 200)["status"] == "RETURNED"

        resp = api_client.resolve_dispute(
            checkout["id"], {"outcome": "WRITE_OFF"}, ADMIN
        )
        final = validate_success(resp, 200)
        assert final["status"] == "WRITTEN_OFF"
        member_end = get_member(member["id"])
        assert member_end["terminal_checkout_count"] == 1
        assert member_end["verified_return_count"] == 0


class TestInvalidAndRepeatedTriggers:
    def test_verify_return_on_active_checkout_is_invalid_state(self):
        """PRD §3.5: "an administrator verifies a `RETURNED` checkout into the
        terminal `VERIFIED` state".
        PRD §2.9: "when the entity is non-terminal but the trigger is not valid
        from its current state, the rejection is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sm_checkout_invalid_transition_verify_on_active
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        resp = api_client.verify_return(checkout["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_checkout(checkout["id"], ADMIN), 200)
        assert after["status"] == "ACTIVE", "no side effects on rejection"

    def test_double_return_is_invalid_state(self):
        """PRD §3.5: "Recording the return moves an `ACTIVE` or `OVERDUE`
        checkout to `RETURNED`, stamps `returned_at` from the logical clock,
        and moves its packet `CHECKED_OUT` → `RETURNED`; a member may record
        only their own returns."
        PRD §2.9: "when the entity is non-terminal but the trigger is not valid
        from its current state, the rejection is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sm_double_return_is_invalid_state
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        return_checkout_as_member(checkout["id"], member["id"])
        resp = api_client.return_checkout(
            checkout["id"], make_member_headers(member["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestVerifyReturnReintegration:
    def test_verify_return_reintegrates_packet_when_lot_active(self):
        """PRD §3.5: "an administrator verifies a `RETURNED` checkout into the
        terminal `VERIFIED` state, and the packet's fate depends on its lot —
        when the lot is `ACTIVE` the packet returns to `AVAILABLE` for the next
        borrower".
        PRD §3.5: "Verification recomputes the member's counters: the terminal
        count rises by one, the verified count rises by one, and the overdue
        count falls by one when the checkout had previously been flipped
        overdue."

        Design: Corner/state_machines/sm_side_effect_verify_return_reintegrates_packet
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        return_checkout_as_member(checkout["id"], member["id"])
        verified = verify_return(checkout["id"])
        assert verified["status"] == "VERIFIED"
        packet = get_packet(ctx["packet_ids"][0])
        assert packet["status"] == "AVAILABLE", (
            f"lot ACTIVE -> packet reintegrates to AVAILABLE, "
            f"got {packet['status']}"
        )
        member_now = get_member(member["id"])
        assert member_now["active_checkout_count"] == 0
        assert member_now["terminal_checkout_count"] == 1
        assert member_now["verified_return_count"] == 1


class TestPacketAvailability:
    def test_second_borrow_of_checked_out_packet_rejected(self):
        """PRD §3.5: "The packet must be `AVAILABLE`
        (`ERR_PACKET_NOT_AVAILABLE`)."

        Design: Corner/errors/err_packet_not_available_on_second_borrow
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member1 = create_member(ctx["site"]["id"])
        member2 = create_member(ctx["site"]["id"])
        borrow_packet(member1, ctx["packet_ids"][0])
        resp = api_client.create_checkout(
            {"member_id": member2["id"], "packet_id": ctx["packet_ids"][0]},
            make_member_headers(member2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PACKET_NOT_AVAILABLE)


class TestRegionalAppropriateness:
    def test_variety_zone_not_matching_member_home_site_rejected(self):
        """PRD §3.5: "The variety's `approved_zones` must contain the region
        zone of the member's home site, else `ERR_REGION_NOT_APPROVED`."

        Variety approved only for ZONE_9A; member's home site is ZONE_5A.

        Design: Corner/validations/val_region_not_approved_on_checkout
        """
        ctx = setup_active_lot(
            num_packets=1,
            seeds_per_packet=10,
            variety_overrides={"approved_zones": ["ZONE_9A"]},
        )
        member = create_member(ctx["site"]["id"])
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": ctx["packet_ids"][0]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGION_NOT_APPROVED)
