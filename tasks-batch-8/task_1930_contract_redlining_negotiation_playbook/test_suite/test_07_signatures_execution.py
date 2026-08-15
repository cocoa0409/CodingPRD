"""Signature routing, execution cascade, and abort paths."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_signature_packet, assert_negotiation, assert_obligation,
    setup_awaiting_countersign_ctx, setup_redlining_ctx,
    create_packet, get_packet, sign_packet, sign_packet_ok,
    record_deviation, approve_deviation, finalize_redlining, refresh_negotiation,
    create_signature_packet_payload, signatory_entry, set_logical_clock,
)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestSignatureWindowBracketing:
    WINDOW_OPENS = "2026-08-10T00:00:00Z"
    WINDOW_CLOSES = "2026-08-20T23:59:59Z"

    def test_signing_before_window_opens_rejected(self, api):
        """A signature before signature_window_opens_at violates the window; the
        packet is untouched.

        PRD §3.8: "Second, the window: the current logical time must fall within the
        closed interval from `signature_window_opens_at` to
        `signature_window_closes_at`, else `ERR_SIGNATURE_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/signature_window_inclusive_bracket_membership
        """
        ctx = setup_awaiting_countersign_ctx(with_second_signatory=True)
        packet = create_packet(ctx, [ctx.users["sg"]["id"], ctx.users["sg2"]["id"]],
                               opens_at=self.WINDOW_OPENS, closes_at=self.WINDOW_CLOSES)
        # Clock is still at the startup instant, before the window opens.
        resp = sign_packet(ctx, packet["id"], ctx.users["sg"]["id"])
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_WINDOW_VIOLATION)
        assert resp.status_code == 409

        packet_after = get_packet(ctx, packet["id"])
        assert packet_after["status"] == "ROUTING"
        assert packet_after["signed_record"] == []

    def test_signing_at_exact_window_boundaries_succeeds(self, api):
        """Both endpoints of the closed interval accept a signature: the first
        signatory at exactly opens_at, the last at exactly closes_at.

        PRD §3.8: "the current logical time must fall within the closed interval from
        `signature_window_opens_at` to `signature_window_closes_at`".
        PRD §3.8: "The first signature moves the packet `ROUTING → PARTIALLY_SIGNED`;
        middle signatures hold it at `PARTIALLY_SIGNED`; and the signature that
        completes coverage of every listed signatory moves it `PARTIALLY_SIGNED →
        FULLY_SIGNED` and lifts the negotiation's signature dimension to
        `FULLY_SIGNED`."

        Design: Difficulty/resource_temporal_overlap/signature_window_inclusive_bracket_membership
        """
        ctx = setup_awaiting_countersign_ctx(with_second_signatory=True)
        packet = create_packet(ctx, [ctx.users["sg"]["id"], ctx.users["sg2"]["id"]],
                               opens_at=self.WINDOW_OPENS, closes_at=self.WINDOW_CLOSES)

        set_logical_clock(self.WINDOW_OPENS)
        packet = sign_packet_ok(ctx, packet["id"], ctx.users["sg"]["id"])
        assert packet["status"] == "PARTIALLY_SIGNED"

        set_logical_clock(self.WINDOW_CLOSES)
        packet = sign_packet_ok(ctx, packet["id"], ctx.users["sg2"]["id"])
        assert_signature_packet(packet)
        assert packet["status"] == "FULLY_SIGNED"
        assert len(packet["signed_record"]) == 2

        negotiation = refresh_negotiation(ctx)
        assert negotiation["signature_status"] == "FULLY_SIGNED"


class TestSingleActivePacket:
    def test_second_packet_blocked_while_first_is_active(self, api):
        """Only one packet may be live at a time.

        PRD §3.8: "Only one packet may be live at a time: an existing packet in
        `ROUTING`, `PARTIALLY_SIGNED`, or `FULLY_SIGNED` blocks creation of another
        with `ERR_SIGNATURE_PACKET_ALREADY_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/signature_packet_active_overlap_prevention
        """
        ctx = setup_awaiting_countersign_ctx()
        create_packet(ctx, [ctx.users["sg"]["id"]])

        version = refresh_negotiation(ctx)["version"]
        payload = create_signature_packet_payload(
            [signatory_entry(ctx.users["sg"]["id"], 1)], version)
        resp = api.create_signature_packet(
            ctx.negotiation["id"], payload, ctx.headers[ctx.users["lc"]["id"]])
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_PACKET_ALREADY_ACTIVE)
        assert resp.status_code == 409

        negotiation = refresh_negotiation(ctx)
        assert negotiation["signature_status"] == "ROUTING"

    def test_voiding_packet_frees_counsel_to_cut_fresh_packet(self, api):
        """Voiding a packet with an empty signed_record returns the signature
        dimension to NOT_STARTED and allows a new packet.

        PRD §3.8: "A `LegalCounsel` may void a packet only while its `signed_record`
        is still empty — once any signature has landed, voiding is refused with
        `ERR_SIGNATURE_ALREADY_STARTED` — moving the packet to `VOIDED` and returning
        the negotiation's signature dimension to `NOT_STARTED`, freeing counsel to cut
        a fresh packet."

        Design: Difficulty/resource_temporal_overlap/signature_packet_active_overlap_prevention
        """
        ctx = setup_awaiting_countersign_ctx()
        packet = create_packet(ctx, [ctx.users["sg"]["id"]])
        lc = ctx.headers[ctx.users["lc"]["id"]]

        resp = api.void_packet(ctx.negotiation["id"], packet["id"], lc)
        voided = validate_success(resp, expected_status=200)
        assert voided["status"] == "VOIDED"
        assert refresh_negotiation(ctx)["signature_status"] == "NOT_STARTED"

        new_packet = create_packet(ctx, [ctx.users["sg"]["id"]])
        assert new_packet["status"] == "ROUTING"
        assert refresh_negotiation(ctx)["signature_status"] == "ROUTING"


class TestSignatoryAuthorityBoundary:
    def test_authority_equal_to_contract_value_rejected(self, api):
        """The authority check is strict: a ceiling exactly equal to the contract
        value is not sufficient, and the authority check precedes the window check.

        PRD §2.10: "the user may execute a contract only when the ceiling is strictly
        greater than the negotiation's `contract_value_cents`, and a ceiling exactly
        equal to the contract value is not sufficient. A breach is rejected with
        `ERR_SIGNATORY_AUTHORITY_EXCEEDED` (HTTP 403)."
        PRD §3.8: "First, authority: the signing user's `can_sign_above_cents` must be
        strictly greater than the negotiation's `contract_value_cents` — equality
        fails — else `ERR_SIGNATORY_AUTHORITY_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/signature_window_bracketing_nested_rounding
        """
        ctx = setup_awaiting_countersign_ctx(
            value_cents=5_000_000, signatory_cap=5_000_000)  # equal: NOT strictly greater
        packet = create_packet(ctx, [ctx.users["sg"]["id"]])

        resp = sign_packet(ctx, packet["id"], ctx.users["sg"]["id"])
        validate_error(resp, ApiErrorId.ERR_SIGNATORY_AUTHORITY_EXCEEDED)
        assert resp.status_code == 403

        packet_after = get_packet(ctx, packet["id"])
        assert packet_after["status"] == "ROUTING"
        assert packet_after["signed_record"] == []

    def test_authority_one_cent_above_contract_value_accepted(self, api):
        """A ceiling one cent above the contract value satisfies the strict
        comparison and the first signature lands.

        PRD §3.8: "First, authority: the signing user's `can_sign_above_cents` must be
        strictly greater than the negotiation's `contract_value_cents`".
        PRD §3.8: "The first signature moves the packet `ROUTING → PARTIALLY_SIGNED`".

        Design: Difficulty/combinatorial_formula/signature_window_bracketing_nested_rounding
        """
        ctx = setup_awaiting_countersign_ctx(
            value_cents=5_000_000, signatory_cap=5_000_001,
            with_second_signatory=True)
        packet = create_packet(ctx, [ctx.users["sg"]["id"], ctx.users["sg2"]["id"]])

        packet = sign_packet_ok(ctx, packet["id"], ctx.users["sg"]["id"])
        assert packet["status"] == "PARTIALLY_SIGNED"
        assert len(packet["signed_record"]) == 1
        assert packet["signed_record"][0]["user_id"] == ctx.users["sg"]["id"]


class TestSignatureGuardsAndAbort:
    def test_signatory_signing_out_of_order_rejected(self, api):
        """The second-order signatory cannot sign before the first.

        PRD §3.8: "Third, order: the signer must be the signatory at the smallest
        `order_index` not yet present in `signed_record`, else
        `ERR_SIGNATORY_OUT_OF_ORDER`."

        Design: Corner/errors/error_signature_out_of_order
        """
        ctx = setup_awaiting_countersign_ctx(with_second_signatory=True)
        packet = create_packet(ctx, [ctx.users["sg"]["id"], ctx.users["sg2"]["id"]])

        resp = sign_packet(ctx, packet["id"], ctx.users["sg2"]["id"])
        validate_error(resp, ApiErrorId.ERR_SIGNATORY_OUT_OF_ORDER)
        assert resp.status_code == 409

    def test_record_execution_requires_fully_signed_packet(self, api):
        """Recording execution on a PARTIALLY_SIGNED packet is refused.

        PRD §3.8: "The packet must stand at `FULLY_SIGNED` — anything less is
        `ERR_SIGNATURE_INCOMPLETE`".

        Design: Corner/errors/error_signature_incomplete_on_record_execution
        """
        ctx = setup_awaiting_countersign_ctx(with_second_signatory=True)
        packet = create_packet(ctx, [ctx.users["sg"]["id"], ctx.users["sg2"]["id"]])
        sign_packet_ok(ctx, packet["id"], ctx.users["sg"]["id"])

        resp = api.record_execution(
            ctx.negotiation["id"], packet["id"],
            {"execution_timestamp": "2026-08-15T10:00:00Z"},
            ctx.headers[ctx.users["sg2"]["id"]])
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_INCOMPLETE)
        assert resp.status_code == 409

    def test_abort_blocked_once_packet_fully_signed(self, api):
        """A signed deal cannot be un-signed: abort with a FULLY_SIGNED packet is
        refused.

        PRD §3.8: "a `LegalCounsel` may abort only while no packet has reached
        `FULLY_SIGNED` or `EXECUTION_RECORDED` — a signed deal cannot be un-signed,
        and the attempt is refused with `ERR_SIGNATURE_ALREADY_FINAL`."

        Design: Corner/errors/error_signature_already_final_on_abort
        """
        ctx = setup_awaiting_countersign_ctx()
        packet = create_packet(ctx, [ctx.users["sg"]["id"]])
        sign_packet_ok(ctx, packet["id"], ctx.users["sg"]["id"])
        assert get_packet(ctx, packet["id"])["status"] == "FULLY_SIGNED"

        resp = api.abort_negotiation(
            ctx.negotiation["id"], ctx.headers[ctx.users["lc"]["id"]])
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_ALREADY_FINAL)
        assert resp.status_code == 409


class TestExecutionCascade:
    EXEC_CLAUSES = [
        {"clause_key": "A", "category": "OPERATIONAL", "standard_text": "a_std",
         "fallback_positions": ["a_fb"], "approver_role_required": "LEGAL_COUNSEL",
         "deviation_severity_cap": "MEDIUM"},
        {"clause_key": "B", "category": "OPERATIONAL", "standard_text": "b_std",
         "fallback_positions": [], "approver_role_required": "LEGAL_COUNSEL",
         "deviation_severity_cap": "LOW"},
    ]
    EXECUTION_TS = "2026-08-15T10:00:00Z"

    def _setup_executed(self, api):
        """Negotiation with one APPROVED fallback deviation on clause A (clause B
        undeviated), fully signed, then executed at EXECUTION_TS."""
        ctx = setup_redlining_ctx(clause_specs=self.EXEC_CLAUSES)
        dev = record_deviation(ctx, clause_index=0, proposed_text="altA", fallback_index=0)
        approve_deviation(ctx, dev)
        finalize_redlining(ctx)
        packet = create_packet(ctx, [ctx.users["sg"]["id"]])
        sign_packet_ok(ctx, packet["id"], ctx.users["sg"]["id"])
        return ctx, packet

    def test_execution_cascade_updates_negotiation_counterparty_playbook(self, api):
        """record-execution fires the depth-3 cascade: packet and both negotiation
        dimensions settle, cycle time is computed, the counterparty records its
        execution instant, and both active counters decrement.

        PRD §3.8: "the packet moves to `EXECUTION_RECORDED`; the negotiation's draft
        dimension moves `AWAITING_COUNTERSIGN → EXECUTED` and its signature dimension
        to `EXECUTION_RECORDED`; `cycle_time_seconds` is computed as the execution
        timestamp minus the negotiation's `created_at`, in seconds; the counterparty's
        `last_executed_at` is set to the execution timestamp; the counterparty's and
        playbook's `active_negotiation_count` each decrement by one; obligation
        extraction runs (§3.9); and the negotiation's `version` increments."

        Design: Difficulty/transitive_cascade/execution_cascade_depth_3
        """
        ctx, packet = self._setup_executed(api)
        resp = api.record_execution(
            ctx.negotiation["id"], packet["id"],
            {"execution_timestamp": self.EXECUTION_TS},
            ctx.headers[ctx.users["sg"]["id"]])
        negotiation = validate_success(resp, expected_status=200)

        assert_negotiation(negotiation)
        assert negotiation["draft_status"] == "EXECUTED"
        assert negotiation["signature_status"] == "EXECUTION_RECORDED"
        # created at the pinned startup instant 2026-08-01T00:00:00Z;
        # 14 days + 10 hours = 1,245,600 seconds.
        assert negotiation["cycle_time_seconds"] == 1_245_600

        packet_after = get_packet(ctx, packet["id"])
        assert packet_after["status"] == "EXECUTION_RECORDED"

        ca = ctx.headers[ctx.users["ca"]["id"]]
        cp = get_success_data(api.get_counterparty(ctx.counterparty["id"], ca))
        pb = get_success_data(api.get_playbook(ctx.playbook["id"], ca))
        assert cp["active_negotiation_count"] == 0
        assert pb["active_negotiation_count"] == 0
        assert cp["last_executed_at"] is not None
        assert _parse_iso(cp["last_executed_at"]) == _parse_iso(self.EXECUTION_TS)

    def test_execution_extracts_obligations_per_extraction_source(self, api):
        """Extraction spawns one obligation per APPROVED deviation (sourced
        FALLBACK_POSITION) plus one per undeviated clause (STANDARD_TEXT).

        PRD §3.9: "the server extracts one `Obligation` per `APPROVED` deviation and
        one per clause template used as standard text with no deviation created."
        PRD §3.9: "`STANDARD_TEXT` for an undeviated clause, `FALLBACK_POSITION` for
        an approved deviation whose severity was `FALLBACK`, or `APPROVED_DEVIATION`
        for one whose severity was `NON_STANDARD`."

        Design: Difficulty/transitive_cascade/execution_cascade_depth_3
        """
        ctx, packet = self._setup_executed(api)
        resp = api.record_execution(
            ctx.negotiation["id"], packet["id"],
            {"execution_timestamp": self.EXECUTION_TS},
            ctx.headers[ctx.users["sg"]["id"]])
        validate_success(resp, expected_status=200)

        ca = ctx.headers[ctx.users["ca"]["id"]]
        obligations, _ = validate_paginated(api.list_obligations(ctx.negotiation["id"], ca))
        assert len(obligations) == 2, (
            f"expected one obligation per playbook clause, got {len(obligations)}")
        by_clause = {o["clause_template_id"]: o for o in obligations}
        for o in obligations:
            assert_obligation(o)
        clause_a, clause_b = ctx.clauses[0]["id"], ctx.clauses[1]["id"]
        assert by_clause[clause_a]["extraction_source"] == "FALLBACK_POSITION"
        assert by_clause[clause_b]["extraction_source"] == "STANDARD_TEXT"
