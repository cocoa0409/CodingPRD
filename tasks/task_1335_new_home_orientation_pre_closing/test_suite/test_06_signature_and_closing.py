"""The acknowledgment signature cycle, readiness derivation, and closing."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_buyer_headers,
    make_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestCloseGating:
    def test_close_requires_signed_acknowledgment(self, api, manager_headers):
        """PRD §3.7: "Closing is the fiscal point of no return, performed by a
        `CustomerCareManager` on a home in `READY_TO_CLOSE` — any other status
        is rejected with `ERR_INVALID_STATE`."
        PRD §3.7: "Closing freezes `final_holdback_cents`, records
        `funded_amount_cents`, sets `remaining_amount_cents` to the funded
        amount, voids an escrow still in `DRAFT` whose final amount is zero,
        moves the home `READY_TO_CLOSE` → `CLOSED`, and increments the home's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/close_requires_signed_acknowledgment
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        fx.setup_completed_orientation(
            home["id"], rep["id"], buyer["id"], "2026-08-25T14:00:00Z"
        )
        # Signature still PENDING: the home is ORIENTED, so closing must fail.
        validate_error(api.close_home(home["id"], {}, manager_headers),
                       ApiErrorId.ERR_INVALID_STATE)
        fx.sign_acknowledgment(home["id"], buyer["id"])
        closed = validate_success(api.close_home(home["id"], {}, manager_headers))
        assert closed["status"] == "CLOSED", (
            f"signed home with no open items must close, got {closed['status']}"
        )
        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["status"] == "VOIDED", (
            f"DRAFT escrow with final 0 must void at close, got {escrow['status']}"
        )

    def test_close_with_funding_when_none_due_rejected(self, api, manager_headers):
        """PRD §3.7: "when no holdback is due, `funded_holdback_cents` must be
        omitted entirely, and supplying it is rejected with `ERR_VALIDATION`."

        Design: Difficulty/cross_entity_state_dependency/close_requires_signed_acknowledgment
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        fx.setup_completed_orientation(
            home["id"], rep["id"], buyer["id"], "2026-08-25T14:00:00Z"
        )
        fx.sign_acknowledgment(home["id"], buyer["id"])
        # No after-closing items exist: the DRAFT escrow's final amount is 0,
        # so no holdback is due and funding must be omitted.
        resp = api.close_home(home["id"], {"funded_holdback_cents": 1},
                              manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "READY_TO_CLOSE", (
            f"the rejected close must not move the home, got {home['status']}"
        )

    def test_close_blocked_by_open_before_items(self, api, manager_headers):
        """PRD §3.4: "while the home is `ACKNOWLEDGED` with its signature still
        `SIGNED`, a before-closing count that reaches zero — after a sign-off,
        a withdrawal, or a resolution change — advances the home to
        `READY_TO_CLOSE`"
        PRD §3.7: "Closing is the fiscal point of no return, performed by a
        `CustomerCareManager` on a home in `READY_TO_CLOSE` — any other status
        is rejected with `ERR_INVALID_STATE`."

        Design: Corner/errors/close_with_unresolved_before_items_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        fx.sign_acknowledgment(home["id"], buyer["id"])

        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "ACKNOWLEDGED", (
            f"an open before-closing item must hold the home at ACKNOWLEDGED, "
            f"got {home['status']}"
        )
        assert home["open_before_closing_count"] == 1
        resp = api.close_home(home["id"], {}, manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSignatureStaleResignCycle:
    def _signed_ready_home(self, api):
        ctx = fx.setup_signed_home()  # READY_TO_CLOSE, snapshot 0
        assert ctx["home"]["status"] == "READY_TO_CLOSE", (
            f"Setup failed: expected READY_TO_CLOSE, got {ctx['home']['status']}"
        )
        assert ctx["signature"]["open_item_snapshot_count"] == 0
        return ctx

    def test_stale_then_resign_refreshes_snapshot(self, api, manager_headers):
        """PRD §3.6: "The record's later life is reactive: identifying a new
        deficiency against the home turns a `SIGNED` record `STALE` and reverts
        the home as described in §3.4, after which the buyer may sign again
        with a freshly pinned snapshot — the `PENDING` → `SIGNED` → `STALE` →
        `SIGNED` cycle."
        PRD §3.6: "`open_item_snapshot_count` pins the number of the home's
        deficiency items in non-terminal states — everything except
        `SIGNED_OFF` and `WITHDRAWN` — at the moment of signing."

        Design: Difficulty/non_linear_state_machine/signature_signed_stale_resign_cycle
        """
        ctx = self._signed_ready_home(api)
        item = fx.create_deficiency(
            ctx["home"]["id"], ctx["appointment"]["id"], ctx["rep"]["id"],
            title="Post-signing paint scuff",
        )
        sig = get_success_data(
            api.get_acknowledgment_signature(ctx["signature"]["id"], manager_headers)
        )
        assert sig["status"] == "STALE", (
            f"a new deficiency must stale the signature, got {sig['status']}"
        )
        home = get_success_data(api.get_home(ctx["home"]["id"], manager_headers))
        assert home["status"] == "ORIENTED", (
            f"the stale flip must revert the home to ORIENTED, got {home['status']}"
        )

        resigned = validate_success(api.respond_acknowledgment_signature(
            sig["id"],
            {"decision": "SIGN", "signature_payload": "sig:buyer:2"},
            make_buyer_headers(ctx["buyer"]["id"]),
        ))
        assert resigned["status"] == "SIGNED"
        assert resigned["open_item_snapshot_count"] == 1, (
            f"the still-open new item must refresh the snapshot to 1, "
            f"got {resigned['open_item_snapshot_count']}"
        )
        home = get_success_data(api.get_home(ctx["home"]["id"], manager_headers))
        assert home["status"] == "READY_TO_CLOSE", (
            f"an IDENTIFIED item with no before resolution must not block "
            f"READY_TO_CLOSE, got {home['status']}"
        )

    def test_resign_records_signer_and_timestamp(self, api, manager_headers):
        """PRD §3.6: "Signing — from `PENDING` or, in the cycle's second act,
        from `STALE` — moves the record to `SIGNED`: `signer_buyer_id` and
        `signed_at` are recorded from the acting buyer and the logical clock,
        any `decline_reason` is cleared, and `open_item_snapshot_count` pins
        the number of the home's deficiency items in non-terminal states —
        everything except `SIGNED_OFF` and `WITHDRAWN` — at the moment of
        signing."

        Design: Difficulty/non_linear_state_machine/signature_signed_stale_resign_cycle
        """
        ctx = self._signed_ready_home(api)
        fx.create_deficiency(
            ctx["home"]["id"], ctx["appointment"]["id"], ctx["rep"]["id"],
            title="Post-signing paint scuff",
        )
        resigned = validate_success(api.respond_acknowledgment_signature(
            ctx["signature"]["id"],
            {"decision": "SIGN", "signature_payload": "sig:buyer:2"},
            make_buyer_headers(ctx["buyer"]["id"]),
        ))
        assert resigned["status"] == "SIGNED"
        assert resigned["signer_buyer_id"] == ctx["buyer"]["id"], (
            f"the acting buyer must be recorded, got {resigned['signer_buyer_id']}"
        )
        assert resigned["signed_at"], "signed_at must be stamped from the clock"
        assert resigned["decline_reason"] is None, (
            f"signing must clear any decline reason, got {resigned['decline_reason']}"
        )

    def test_identification_stales_signature_and_reverts_home(self, api, manager_headers):
        """PRD §3.4: "identification carries a deliberate shock wave: if the
        home's acknowledgment signature is currently `SIGNED` it immediately
        becomes `STALE`, and a home sitting in `ACKNOWLEDGED` or
        `READY_TO_CLOSE` reverts to `ORIENTED`, forcing the buyer to
        re-acknowledge the changed picture."

        Design: Difficulty/transitive_cascade/deficiency_identification_stales_signature_reverts_home
        """
        ctx = self._signed_ready_home(api)
        item = fx.create_deficiency(
            ctx["home"]["id"], ctx["appointment"]["id"], ctx["rep"]["id"],
            title="Driveway hairline crack",
        )
        assert item["status"] == "IDENTIFIED"
        sig = get_success_data(
            api.get_acknowledgment_signature(ctx["signature"]["id"], manager_headers)
        )
        assert sig["status"] == "STALE", (
            f"signature must flip SIGNED -> STALE, got {sig['status']}"
        )
        home = get_success_data(api.get_home(ctx["home"]["id"], manager_headers))
        assert home["status"] == "ORIENTED", (
            f"home must revert READY_TO_CLOSE -> ORIENTED, got {home['status']}"
        )

    def test_identification_reverts_acknowledged_home(self, api, manager_headers):
        """PRD §3.4: "identification carries a deliberate shock wave: if the
        home's acknowledgment signature is currently `SIGNED` it immediately
        becomes `STALE`, and a home sitting in `ACKNOWLEDGED` or
        `READY_TO_CLOSE` reverts to `ORIENTED`, forcing the buyer to
        re-acknowledge the changed picture."

        Design: Difficulty/transitive_cascade/deficiency_identification_stales_signature_reverts_home
        """
        # ACKNOWLEDGED variant: an open before-closing item holds the home at
        # ACKNOWLEDGED after signing; a new identification still stales the
        # signature and reverts the home.
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        sig = fx.sign_acknowledgment(home["id"], buyer["id"])
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "ACKNOWLEDGED", (
            f"Setup failed: expected ACKNOWLEDGED, got {home['status']}"
        )

        fx.create_deficiency(home["id"], appt["id"], rep["id"],
                             title="Driveway hairline crack")
        sig = get_success_data(
            api.get_acknowledgment_signature(sig["id"], manager_headers)
        )
        assert sig["status"] == "STALE"
        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "ORIENTED", (
            f"home must revert ACKNOWLEDGED -> ORIENTED, got {home['status']}"
        )


class TestDeclineAndReRequest:
    def test_decline_re_request_sign_cycle(self, api, manager_headers):
        """PRD §3.6: "Declining from `PENDING` lands the record in `DECLINED`
        with the buyer's `decline_reason` recorded. A `CustomerCareRep` may
        then re-request the acknowledgment, returning the record `DECLINED` →
        `PENDING`, clearing `decline_reason`, and incrementing the signature's
        `version`."

        Design: Corner/state_machines/signature_decline_and_re_request_cycle
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-20T17:00:00Z")
        fx.setup_completed_orientation(
            home["id"], rep["id"], buyer["id"], "2026-08-25T14:00:00Z"
        )
        sig = fx.get_signature_for_home(home["id"])

        declined = validate_success(api.respond_acknowledgment_signature(
            sig["id"],
            {"decision": "DECLINE", "decline_reason": "want items fixed first"},
            make_buyer_headers(buyer["id"]),
        ))
        assert declined["status"] == "DECLINED"
        assert declined["decline_reason"] == "want items fixed first"

        pending = validate_success(api.re_request_acknowledgment_signature(
            sig["id"], make_rep_headers(rep["id"])
        ))
        assert pending["status"] == "PENDING"
        assert pending["decline_reason"] is None, (
            f"re-request must clear the decline reason, got {pending['decline_reason']}"
        )

        signed = validate_success(api.respond_acknowledgment_signature(
            sig["id"],
            {"decision": "SIGN", "signature_payload": "sig:buyer:2"},
            make_buyer_headers(buyer["id"]),
        ))
        assert signed["status"] == "SIGNED"


class TestHomeRescheduleClosingOcc:
    def test_stale_home_version_rejected(self, api, manager_headers):
        """PRD §2.7: "Moving a home's closing date —
        `POST /api/homes/{id}/reschedule-closing` — requires
        `expected_home_version` matching the home's current `version`; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since every
        cascade that touches the home bumps its version and a stale expectation
        means the closing context the client observed no longer holds."

        Design: Corner/errors/home_reschedule_closing_stale_version_rejected
        """
        community, buyer, _rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"], mark_ready=False)
        stale_version = home["version"]  # observed at create time
        ready = validate_success(api.mark_home_ready(home["id"], manager_headers))

        moved = validate_success(api.reschedule_closing(
            home["id"],
            {"closing_date": "2026-09-05T17:00:00Z",
             "expected_home_version": ready["version"]},
            manager_headers,
        ))
        assert moved["closing_date"].startswith("2026-09-05T17:00"), (
            f"closing date must move, got {moved['closing_date']}"
        )
        resp = api.reschedule_closing(
            home["id"],
            {"closing_date": "2026-09-08T17:00:00Z",
             "expected_home_version": stale_version},
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestMarkReadyGuard:
    def test_double_mark_ready_rejected(self, api, manager_headers):
        """PRD §3.1: "the manager marks the home ready, moving it from
        `UNDER_CONSTRUCTION` to `PRE_CLOSE_READY` and incrementing the home's
        `version`."
        PRD §2.8: "State — the target entity is in a valid from-state for the
        requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/home_double_mark_ready_rejected
        """
        community, buyer, _rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])  # already PRE_CLOSE_READY
        resp = api.mark_home_ready(home["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
