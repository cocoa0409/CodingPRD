"""Disputes: opening, the disbursement freeze, resolution, and overrides."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_draw,
    close_holdback,
    create_approved_draw,
    create_dispute,
    create_verified_draw,
    expire_holdback,
    get_holdback,
    list_disputes,
    list_ledger,
    resolve_dispute,
    set_logical_clock,
    setup_active_holdback,
    setup_engagement,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
BUYER = TEST_USERS["buyer_1_headers"]
SELLER = TEST_USERS["seller_1_headers"]


class TestDisputeFreeze:
    def test_dispute_freeze_blocks_approve_and_pay(self, api):
        """PRD §3.7: "The moment a dispute stands `OPEN`, the holdback's `disbursement_frozen` recomputes to true, and while any dispute remains `OPEN` every draw approval and every draw payment is rejected with `ERR_DISPUTE_FROZEN` — the freeze is what protects the trust while the parties argue."
        PRD §2.9: "Disbursement freeze: while the holdback is disbursement-frozen, draw approval and draw payment are rejected with `ERR_DISPUTE_FROZEN` (HTTP 409)."

        Both money-moving actions fail while an extension request — not a
        disbursement — still succeeds.

        Design: Corner/validations/dispute_freeze_blocks_approve_and_pay
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        pair1 = create_approved_draw(ctx, 50000, description="Stage 1",
                                     scheduled_start="2026-08-20T10:00:00Z",
                                     scheduled_end="2026-08-20T11:00:00Z")
        pair2 = create_verified_draw(ctx, 40000, description="Stage 2",
                                     scheduled_start="2026-08-21T10:00:00Z",
                                     scheduled_end="2026-08-21T11:00:00Z")
        create_dispute(hb_id, SELLER, category="DRAW_DENIAL",
                       claimed_amount_cents=50000, statement="Stage 1 overbilled")

        pay_resp = api.pay_draw_request(pair1["draw"]["id"], OFFICER)
        validate_error(pay_resp, ApiErrorId.ERR_DISPUTE_FROZEN)

        approve_resp = api.approve_draw_request(pair2["draw"]["id"], OFFICER)
        validate_error(approve_resp, ApiErrorId.ERR_DISPUTE_FROZEN)

        assert get_holdback(hb_id)["disbursement_frozen"] is True

        ext = validate_success(
            api.create_extension_request(
                {"holdback_id": hb_id, "reason": "WEATHER_EXTERIOR",
                 "requested_days": 3, "evidence_ref": "NOAA log"},
                BUYER),
            201,
        )
        assert ext["status"] == "PENDING", "extensions are not disbursements"

    def test_second_open_dispute_rejected(self, api):
        """PRD §3.7: "One `OPEN` dispute at a time per holdback: a second attempt fails with `ERR_DISPUTE_ALREADY_OPEN`."

        Design: Corner/validations/second_open_dispute_rejected
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]
        create_dispute(hb_id, BUYER, category="WORK_QUALITY",
                       claimed_amount_cents=10000, statement="Shingles mismatched")

        resp = api.create_dispute(
            {"holdback_id": hb_id, "category": "DEADLINE",
             "claimed_amount_cents": 0, "statement": "Counter-dispute"},
            SELLER,
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN)


class TestDisputeResolution:
    def test_dispute_double_resolve_rejected(self, api):
        """PRD §3.7: "Resolution is the `EscrowOfficer`'s judgment call on an `OPEN` dispute (resolving one already resolved is `ERR_INVALID_STATE`)."

        The first resolution's fields are immutable afterwards.

        Design: Corner/state_machines/dispute_double_resolve_rejected
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]
        disp = create_dispute(hb_id, BUYER, category="WORK_QUALITY",
                              claimed_amount_cents=50000,
                              statement="Work not to code")
        resolved = resolve_dispute(disp["id"], "FOR_SELLER", "Work verified adequate")
        assert resolved["status"] == "RESOLVED_SELLER"

        again = api.resolve_dispute(
            disp["id"], {"resolution": "FOR_BUYER", "resolution_note": "Changed mind"},
            OFFICER)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        disputes = {d["id"]: d for d in list_disputes(hb_id)}
        assert disputes[disp["id"]]["status"] == "RESOLVED_SELLER"
        assert disputes[disp["id"]]["resolution_note"] == "Work verified adequate"

    def test_dispute_resolution_overrides_expiration_terms(self, api):
        """PRD §3.7: "when the holdback is `EXPIRED` at resolve time, the resolution writes the holdback's `disposition_override` — `RELEASE_TO_BUYER` for `FOR_BUYER`, `RETURN_TO_SELLER` for `FOR_SELLER`, `SPLIT_EQUAL` for `SPLIT` — and that override, not the holdback's `expiration_terms`, will govern the remainder at the expiration close."
        PRD §3.8: "On the expired path the basis is the `disposition_override` when one was set by dispute resolution, otherwise the holdback's `expiration_terms`"

        expiration_terms RETURN_TO_SELLER is overridden by a FOR_BUYER
        resolution: the expiration close releases the 230000 remainder to the
        buyer.

        Design: Corner/complexity_layers/dispute_resolution_overrides_expiration_terms
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]

        set_logical_clock("2026-09-16T00:00:00Z")
        expired = expire_holdback(hb_id)
        assert expired["status"] == "EXPIRED"

        disp = create_dispute(hb_id, BUYER, category="DEADLINE",
                              claimed_amount_cents=230000,
                              statement="Seller never performed")
        resolved = resolve_dispute(disp["id"], "FOR_BUYER",
                                   "Non-performance documented")
        assert resolved["status"] == "RESOLVED_BUYER"

        hb = get_holdback(hb_id)
        assert hb["disposition_override"] == "RELEASE_TO_BUYER"

        closed = close_holdback(hb_id)
        assert closed["status"] == "CLOSED_EXPIRED"

        entries = list_ledger(hb_id)
        assert [e["entry_type"] for e in entries] == ["FUNDING", "RELEASE_TO_BUYER"]
        assert entries[1]["amount_cents"] == -230000
        assert entries[1]["running_balance_cents"] == 0

        disputes = {d["id"]: d for d in list_disputes(hb_id)}
        assert disputes[disp["id"]]["status"] == "RESOLVED_BUYER"

    def test_dispute_resolve_lifts_freeze_without_override(self, api):
        """PRD §3.7: "Once no dispute of the holdback remains `OPEN`, the freeze recomputes to false and disbursements may resume."
        PRD §3.7: "Resolving a dispute while the holdback is in any other state sets no override."

        On an ACTIVE holdback the resolution clears the freeze, writes no
        disposition override, and the previously frozen approve then succeeds.

        Design: Corner/complexity_layers/dispute_resolve_lifts_freeze
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        pair = create_verified_draw(ctx, 50000, description="Stage 1")
        disp = create_dispute(hb_id, SELLER, category="DRAW_DENIAL",
                              claimed_amount_cents=50000, statement="Hold the draw")

        frozen = api.approve_draw_request(pair["draw"]["id"], OFFICER)
        validate_error(frozen, ApiErrorId.ERR_DISPUTE_FROZEN)

        resolved = resolve_dispute(disp["id"], "SPLIT", "Split the difference")
        assert resolved["status"] == "RESOLVED_SPLIT"

        hb = get_holdback(hb_id)
        assert hb["disbursement_frozen"] is False
        assert hb["disposition_override"] is None

        approved = approve_draw(pair["draw"]["id"])
        assert approved["status"] == "APPROVED"
