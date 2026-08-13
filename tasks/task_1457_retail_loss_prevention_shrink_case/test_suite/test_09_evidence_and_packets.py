"""Evidence custody chain, sealing rules, retention sweep, legal holds, and
the referral-packet cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_packet,
    adjudicate_case,
    advance_case,
    assert_custody_event,
    attach_evidence,
    collect_and_seal,
    collect_custody,
    document_interview,
    draft_demand,
    get_case,
    get_evidence,
    get_packet,
    hold_interview,
    issue_demand,
    make_admin_headers,
    make_analyst_headers,
    make_manager_headers,
    make_packet,
    make_period,
    make_store,
    schedule_interview,
    seal_packet,
    set_clock,
    setup_case_closed_substantiated,
    setup_case_interviewed,
    setup_case_investigating,
    submit_packet,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ADMIN_1, ANALYST_1, MANAGER_1


class TestCustodyChain:
    def _setup_case_with_evidence(self, api, store_number="S022", name="Store 22"):
        store = make_store(store_number=store_number, name=name)
        ctx = setup_case_investigating(store["id"], manual_loss_cents=5000)
        ev = attach_evidence(ctx["case"]["id"], ANALYST_1)
        return store, ctx, ev

    def test_custody_event_append_only_no_version_field(self, api):
        """PRD §2.4: "Custody events are the single exception: because a
        custody entry is immutable once appended to the chain, it carries only
        `id` and `created_at`; both `updated_at` and `version` are absent from
        it."
        PRD §3.7: "Every movement of an evidence item is chronicled by
        appending a custody event naming the `evidence_id`, an `action` of
        `COLLECTED`, `SEALED`, `ACCESSED`, `TRANSFERRED`, `RELEASED_TO_LE`, or
        `RETURNED_FROM_LE`, and an optional free-text `note`; the server stamps
        `actor_id` from the caller's `X-User-ID`."

        Design: Corner/entities/custody_event_append_only_no_version_field
        """
        _store, _ctx, ev = self._setup_case_with_evidence(api)
        resp = api.create_custody_event(
            ev["id"], {"action": "COLLECTED"}, make_analyst_headers(ANALYST_1)
        )
        data = validate_success(resp, expected_status=201)
        assert_custody_event(data)
        assert data["actor_id"] == ANALYST_1, "stamped from X-User-ID, not input"
        assert data["evidence_id"] == ev["id"]

    def test_evidence_seal_without_collected_custody_gap(self, api):
        """PRD §3.7: "An analyst seals an `ACTIVE` item — anything else draws
        `ERR_INVALID_STATE_TRANSITION` — but only after the chain shows a
        `COLLECTED` custody event for it; sealing an item with no collection
        record fails with `ERR_CUSTODY_GAP`. Sealing stamps `sealed_by` and
        automatically appends a `SEALED` custody event."

        Design: Corner/state_machines/evidence_seal_without_collected_custody_gap
        """
        _store, _ctx, ev = self._setup_case_with_evidence(api, "S039", "Store 39")
        resp = api.seal_evidence(ev["id"], make_analyst_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_CUSTODY_GAP)
        collect_custody(ev["id"], ANALYST_1)
        sealed = validate_success(
            api.seal_evidence(ev["id"], make_analyst_headers(ANALYST_1))
        )
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by"] == ANALYST_1
        events, meta = validate_paginated(api.list_custody_events(
            make_analyst_headers(ANALYST_1), params={"evidence_id": ev["id"]}
        ))
        assert meta["total_count"] == 2, "COLLECTED + auto-appended SEALED"
        assert {e["action"] for e in events} == {"COLLECTED", "SEALED"}

    def test_evidence_unseal_active_returns_invalid_state(self, api):
        """PRD §3.7: "A manager may unseal a `SEALED` item back to `ACTIVE`,
        except while `legal_hold` is true (`ERR_LEGAL_HOLD_ACTIVE`)."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        Unseal is defined from SEALED only; an ACTIVE item rejects it.

        Design: Corner/state_machines/evidence_unseal_active_returns_invalid_state
        """
        _store, _ctx, ev = self._setup_case_with_evidence(api, "S040", "Store 40")
        resp = api.unseal_evidence(ev["id"], make_manager_headers(MANAGER_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_custody_mutation_on_sealed_evidence_rejected(self, api):
        """PRD §3.7: "Custody entries are immutable — per §2.4 they carry only
        `id` and `created_at` — and two actions are forbidden while the item is
        `SEALED`: recording `ACCESSED` or `TRANSFERRED` against sealed evidence
        fails with `ERR_EVIDENCE_SEALED_IMMUTABLE`."

        Design: Corner/errors/custody_mutation_on_sealed_evidence_rejected
        """
        _store, _ctx, ev = self._setup_case_with_evidence(api, "S090", "Store 90")
        collect_and_seal(ev["id"], ANALYST_1)
        resp1 = api.create_custody_event(
            ev["id"], {"action": "ACCESSED", "note": "review"},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp1, ApiErrorId.ERR_EVIDENCE_SEALED_IMMUTABLE)
        resp2 = api.create_custody_event(
            ev["id"], {"action": "TRANSFERRED", "note": "to lab"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp2, ApiErrorId.ERR_EVIDENCE_SEALED_IMMUTABLE)
        _events, meta = validate_paginated(api.list_custody_events(
            make_analyst_headers(ANALYST_1), params={"evidence_id": ev["id"]}
        ))
        assert meta["total_count"] == 2, "chain frozen at COLLECTED + SEALED"


class TestRetentionSweep:
    def test_retention_strict_greater_and_two_phase_sweep(self, api):
        """PRD §3.7: "A `STANDARD` item's `retention_until` is its
        `captured_at` plus 90 days; an `EXTENDED` item's is `captured_at` plus
        365 days; a `CASE_HOLD` item's is the parent case's `closed_at` plus 30
        days, and such an item is not eligible for expiry at all while its
        case is not closed — the horizon is recomputed when the case closes and
        again if it reopens."
        PRD §3.7: "An item expiring in a given sweep is never purged in that
        same sweep; it waits for a later one. Expiry eligibility requires all
        of the following at once: status `ACTIVE`; the current instant strictly
        greater than `retention_until` — at the exact `retention_until` second
        the item is retained; the parent case in `CLOSED_SUBSTANTIATED`,
        `CLOSED_UNSUBSTANTIATED`, or `CLOSED_REFERRED`; and `legal_hold`
        false."

        Captured 2026-05-01T00:00:00Z -> retention_until 2026-07-30T00:00:00Z.

        Design: Corner/calculations/evidence_retention_strict_greater_and_two_phase_sweep
        """
        store = make_store(store_number="S056", name="Store 56")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        ev = attach_evidence(ctx["case"]["id"], ANALYST_1,
                             evidence_type="VIDEO_CLIP",
                             captured_at="2026-05-01T00:00:00Z",
                             retention_class="STANDARD")
        # Close the case early so expiry eligibility can hold.
        validate_success(api.dismiss_case(
            ctx["case"]["id"], {"reason": "insufficient evidence"},
            make_manager_headers(MANAGER_1),
        ))
        set_clock("2026-07-30T00:00:00Z")  # exactly retention_until
        sweep1 = validate_success(api.retention_sweep(make_admin_headers(ADMIN_1)))
        assert sweep1["expired_count"] == 0, "at the exact instant the item is retained"
        assert get_evidence(ev["id"])["status"] == "ACTIVE"
        set_clock("2026-07-30T00:00:01Z")  # one second past
        sweep2 = validate_success(api.retention_sweep(make_admin_headers(ADMIN_1)))
        assert sweep2["expired_count"] == 1
        assert sweep2["purged_count"] == 0, "not purged in the same sweep"
        sweep3 = validate_success(api.retention_sweep(make_admin_headers(ADMIN_1)))
        assert sweep3["expired_count"] == 0
        assert sweep3["purged_count"] == 1, "purge phase on the next sweep"
        assert get_evidence(ev["id"])["status"] == "PURGED"


class TestReferralPackets:
    def _setup_substantiated_with_sealed_evidence(
        self, api, store_number, *, loss=10000, with_demand=False,
        evidence_retention="EXTENDED",
    ):
        """Case CLOSED_SUBSTANTIATED; evidence collected + sealed; packet
        drafted. Returns (store, ctx, ev, packet)."""
        store = make_store(store_number=store_number, name=f"Store {store_number}")
        make_period(store["id"])
        ctx = setup_case_closed_substantiated(
            store["id"], manual_loss_cents=loss, restitution_waived=not with_demand,
            evidence_type="VIDEO_CLIP", retention_class=evidence_retention,
        )
        ev = ctx["evidence"]
        collect_and_seal(ev["id"], ANALYST_1)
        packet = make_packet(ctx["case"]["id"], ANALYST_1)
        return store, ctx, ev, packet

    def test_packet_submit_from_draft_returns_invalid_state(self, api):
        """PRD §3.7: "Submission belongs to the manager: the packet must be
        `SEALED`, the case must be `CLOSED_SUBSTANTIATED`, and no civil demand
        of the case may still be in `DRAFT` — the latter two failures surface
        as `ERR_PACKET_NOT_READY`."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        A DRAFT packet fails its own state machine before readiness checks.

        Design: Corner/state_machines/packet_submit_from_draft_returns_invalid_state
        """
        _store, _ctx, _ev, packet = self._setup_substantiated_with_sealed_evidence(
            api, "S045", loss=40000,
        )
        resp = api.submit_referral_packet(packet["id"], make_manager_headers(MANAGER_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_packet_seal_blocked_by_unsealed_evidence(self, api):
        """PRD §3.7: "Sealing the packet — again the assignee — requires that
        every evidence item of the case still in `ACTIVE` status be sealed
        first (`ERR_EVIDENCE_UNSEALED`); items already `EXPIRED` or `PURGED`
        are simply excluded from the packet."
        PRD §3.7: "Sealing snapshots `packet_exposure_cents` from the case's
        `total_loss_cents` and moves the packet to `SEALED`."

        Design: Corner/validations/packet_seal_blocked_by_unsealed_evidence
        """
        store = make_store(store_number="S069", name="Store 69")
        make_period(store["id"])
        # Case walked to INTERVIEWED with EV1 attached; EV2 attached while the
        # case is INTERVIEWED (still an attachable state), then the case is
        # adjudicated SUBSTANTIATED with restitution waived.
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=10000,
                                     evidence_type="VIDEO_CLIP",
                                     retention_class="EXTENDED")
        ev1 = ctx["evidence"]
        ev2 = attach_evidence(ctx["case"]["id"], ANALYST_1,
                              captured_at="2026-07-15T11:00:00Z")
        ctx["case"] = advance_case(ctx["case"]["id"], ANALYST_1)
        adjudicate_case(ctx["case"]["id"], MANAGER_1,
                        decision="SUBSTANTIATED", restitution_waived=True)
        collect_and_seal(ev1["id"], ANALYST_1)
        packet = make_packet(ctx["case"]["id"], ANALYST_1, jurisdiction_code="WA-SEA")
        resp = api.seal_referral_packet(packet["id"], make_analyst_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_UNSEALED)
        collect_and_seal(ev2["id"], ANALYST_1)
        sealed = seal_packet(packet["id"], ANALYST_1)
        assert sealed["status"] == "SEALED"
        assert sealed["packet_exposure_cents"] == 10000, "case total_loss snapshot"

    def test_packet_submit_blocked_by_draft_demand(self, api):
        """PRD §3.7: "Submission belongs to the manager: the packet must be
        `SEALED`, the case must be `CLOSED_SUBSTANTIATED`, and no civil demand
        of the case may still be in `DRAFT` — the latter two failures surface
        as `ERR_PACKET_NOT_READY`."

        The DRAFT demand that satisfied the adjudication gate blocks submit
        until cancelled.

        Design: Corner/validations/packet_submit_blocked_by_draft_demand
        """
        store = make_store(store_number="S070", name="Store 70")
        make_period(store["id"])
        ctx = setup_case_closed_substantiated(
            store["id"], manual_loss_cents=10000, restitution_waived=False,
            evidence_type="VIDEO_CLIP", retention_class="EXTENDED",
        )
        ev = ctx["evidence"]
        collect_and_seal(ev["id"], ANALYST_1)
        packet = make_packet(ctx["case"]["id"], ANALYST_1, jurisdiction_code="WA-SEA")
        seal_packet(packet["id"], ANALYST_1)
        resp = api.submit_referral_packet(packet["id"], make_manager_headers(MANAGER_1))
        validate_error(resp, ApiErrorId.ERR_PACKET_NOT_READY)
        validate_success(api.cancel_civil_demand(
            ctx["demand"]["id"], make_manager_headers(MANAGER_1)
        ))
        submitted = submit_packet(packet["id"], MANAGER_1)
        assert submitted["status"] == "SUBMITTED"

    def test_legal_hold_blocks_unseal_while_packet_submitted(self, api):
        """PRD §3.7: "Submission stamps `submitted_at`, moves the packet to
        `SUBMITTED`, and sets `legal_hold` true on every `SEALED` or `ACTIVE`
        evidence item of the case, which blocks both unsealing and retention
        expiry until the hold clears."
        PRD §3.7: "A manager may unseal a `SEALED` item back to `ACTIVE`,
        except while `legal_hold` is true (`ERR_LEGAL_HOLD_ACTIVE`)."
        PRD §3.7: "an `outcome` of `RETURNED` moves it to `RETURNED`, records
        the supplied `return_reason`, and clears `legal_hold` on all of the
        case's evidence."

        Design: Corner/errors/legal_hold_blocks_unseal_while_packet_submitted
        """
        _store, _ctx, ev, packet = self._setup_substantiated_with_sealed_evidence(
            api, "S089",
        )
        seal_packet(packet["id"], ANALYST_1)
        submit_packet(packet["id"], MANAGER_1)
        held = get_evidence(ev["id"])
        assert held["legal_hold"] is True
        resp = api.unseal_evidence(ev["id"], make_manager_headers(MANAGER_1))
        validate_error(resp, ApiErrorId.ERR_LEGAL_HOLD_ACTIVE)
        acknowledge_packet(packet["id"], "RETURNED", MANAGER_1,
                           return_reason="jurisdiction declined")
        unsealed = validate_success(
            api.unseal_evidence(ev["id"], make_manager_headers(MANAGER_1))
        )
        assert unsealed["status"] == "ACTIVE"
        assert unsealed["legal_hold"] is False


class TestPacketCycle:
    """DRAFT -> SEALED -> SUBMITTED -> RETURNED -> DRAFT -> SEALED ->
    SUBMITTED -> ACKNOWLEDGED, with legal_hold tracking the cycle."""

    def _setup_packet(self, api):
        """Case CLOSED_SUBSTANTIATED with an ISSUED demand (issued while
        INTERVIEWED, so the demand gate passes at adjudication and no DRAFT
        lingers at submit); evidence collected + sealed; packet drafted."""
        store = make_store(store_number="S140", name="Store 140")
        make_period(store["id"])
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=40000,
                                     evidence_type="VIDEO_CLIP",
                                     retention_class="CASE_HOLD")
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="STATUTORY",
                              priors_offense_count=0)
        issue_demand(demand["id"], MANAGER_1)
        ctx["case"] = advance_case(ctx["case"]["id"], ANALYST_1)
        ctx["case"] = adjudicate_case(ctx["case"]["id"], MANAGER_1,
                                      decision="SUBSTANTIATED")
        assert ctx["case"]["status"] == "CLOSED_SUBSTANTIATED"
        ev = ctx["evidence"]
        collect_custody(ev["id"], ANALYST_1, note="Collected at store office")
        validate_success(api.seal_evidence(ev["id"], make_analyst_headers(ANALYST_1)))
        packet = make_packet(ctx["case"]["id"], ANALYST_1)
        return store, ctx, ev, packet

    def test_packet_return_clears_hold_and_revise_reopens_draft(self, api):
        """PRD §3.7: "Submission stamps `submitted_at`, moves the packet to
        `SUBMITTED`, and sets `legal_hold` true on every `SEALED` or `ACTIVE`
        evidence item of the case, which blocks both unsealing and retention
        expiry until the hold clears."
        PRD §3.7: "an `outcome` of `RETURNED` moves it to `RETURNED`, records
        the supplied `return_reason`, and clears `legal_hold` on all of the
        case's evidence."
        PRD §3.7: "A `RETURNED` packet is not a dead end — the assigned analyst
        may revise it back to `DRAFT`, correct it, and run the cycle again; the
        loop from `DRAFT` through `SEALED`, `SUBMITTED`, and `RETURNED` back to
        `DRAFT` is allowed without limit."

        Design: Difficulty/non_linear_state_machine/referral_packet_return_revise_resubmit_cycle
        """
        _store, _ctx, ev, packet = self._setup_packet(api)
        seal_packet(packet["id"], ANALYST_1)
        submitted = submit_packet(packet["id"], MANAGER_1)
        assert submitted["status"] == "SUBMITTED"
        assert get_evidence(ev["id"])["legal_hold"] is True
        returned = acknowledge_packet(
            packet["id"], "RETURNED", MANAGER_1,
            return_reason="Packet missing transaction log appendix",
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_reason"] == "Packet missing transaction log appendix"
        assert get_evidence(ev["id"])["legal_hold"] is False
        revised = validate_success(
            api.revise_referral_packet(packet["id"], make_analyst_headers(ANALYST_1))
        )
        assert revised["status"] == "DRAFT", "cycle closes back to DRAFT"

    def test_packet_cycle_completes_to_acknowledged(self, api):
        """PRD §3.7: "A `RETURNED` packet is not a dead end — the assigned
        analyst may revise it back to `DRAFT`, correct it, and run the cycle
        again; the loop from `DRAFT` through `SEALED`, `SUBMITTED`, and
        `RETURNED` back to `DRAFT` is allowed without limit."
        PRD §3.7: "Sealing snapshots `packet_exposure_cents` from the case's
        `total_loss_cents` and moves the packet to `SEALED`."
        PRD §3.7: "an `outcome` of `ACKNOWLEDGED` moves the packet to its
        terminal `ACKNOWLEDGED` state, keeps `legal_hold` in place, and makes
        sealed evidence releasable"

        Design: Difficulty/non_linear_state_machine/referral_packet_return_revise_resubmit_cycle
        """
        _store, _ctx, _ev, packet = self._setup_packet(api)
        seal_packet(packet["id"], ANALYST_1)
        submit_packet(packet["id"], MANAGER_1)
        acknowledge_packet(packet["id"], "RETURNED", MANAGER_1,
                           return_reason="Packet missing transaction log appendix")
        validate_success(
            api.revise_referral_packet(packet["id"], make_analyst_headers(ANALYST_1))
        )
        resealed = seal_packet(packet["id"], ANALYST_1)
        assert resealed["status"] == "SEALED"
        assert resealed["packet_exposure_cents"] == 40000
        resubmitted = submit_packet(packet["id"], MANAGER_1)
        assert resubmitted["status"] == "SUBMITTED"
        final = acknowledge_packet(packet["id"], "ACKNOWLEDGED", MANAGER_1)
        assert final["status"] == "ACKNOWLEDGED"
        assert final["packet_exposure_cents"] == 40000


class TestCloseReferred:
    """CLOSED_SUBSTANTIATED -> CLOSED_REFERRED is gated on the packet's state."""

    def _setup_submitted_packet(self, api):
        store = make_store(store_number="S211", name="Store 211")
        make_period(store["id"])
        ctx = setup_case_closed_substantiated(
            store["id"], manual_loss_cents=40000, evidence_type="VIDEO_CLIP",
        )
        ev = ctx["evidence"]
        collect_and_seal(ev["id"], ANALYST_1)
        packet = make_packet(ctx["case"]["id"], ANALYST_1, jurisdiction_code="TX-DAL")
        seal_packet(packet["id"], ANALYST_1)
        submit_packet(packet["id"], MANAGER_1)
        return store, ctx, packet

    def test_close_referred_rejected_while_packet_submitted(self, api):
        """PRD §3.5: "Once a substantiated case's referral packet has been
        acknowledged, an `LPManager` may move it from `CLOSED_SUBSTANTIATED` to
        `CLOSED_REFERRED`; without an `ACKNOWLEDGED` packet the attempt fails
        with `ERR_CASE_NOT_REFERRABLE`."

        A merely-SUBMITTED packet does not satisfy the gate.

        Design: Difficulty/cross_entity_state_dependency/close_referred_gated_on_packet_acknowledged
        """
        _store, ctx, packet = self._setup_submitted_packet(api)
        assert get_packet(packet["id"])["status"] == "SUBMITTED"
        resp = api.close_case_referred(
            ctx["case"]["id"], make_manager_headers(MANAGER_1)
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_REFERRABLE)
        assert get_case(ctx["case"]["id"])["status"] == "CLOSED_SUBSTANTIATED"

    def test_close_referred_succeeds_after_acknowledgement(self, api):
        """PRD §3.5: "Once a substantiated case's referral packet has been
        acknowledged, an `LPManager` may move it from `CLOSED_SUBSTANTIATED` to
        `CLOSED_REFERRED`; without an `ACKNOWLEDGED` packet the attempt fails
        with `ERR_CASE_NOT_REFERRABLE`."
        PRD §3.5: "`CLOSED_REFERRED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/close_referred_gated_on_packet_acknowledged
        """
        _store, ctx, packet = self._setup_submitted_packet(api)
        acked = acknowledge_packet(packet["id"], "ACKNOWLEDGED", MANAGER_1)
        assert acked["status"] == "ACKNOWLEDGED"
        closed = validate_success(
            api.close_case_referred(ctx["case"]["id"], make_manager_headers(MANAGER_1))
        )
        assert closed["status"] == "CLOSED_REFERRED"
