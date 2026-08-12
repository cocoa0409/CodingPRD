"""Dispatch release: creation gates, initial state, the joint signature cycle,
recall/amend, terminal lockdown, and release RBAC/ownership (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_release,
    assert_release_signature,
    create_captain_payload,
    create_dispatcher_payload,
    make_captain_headers,
    make_dispatcher_headers,
    setup_locked_plan,
    setup_manifest_chain,
    setup_release_draft,
    setup_release_draft_with_expired_mel,
    setup_release_pending,
    setup_release_released,
    validate_error,
    validate_paginated,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestReleaseCreation:
    def test_release_created_in_draft_initial_state(self, api):
        """PRD §3.5: "A new release starts in `DRAFT` status with `cycle_seq` 1
        and `amendment_count` 0, and creation writes an
        `OperationalControlRecord` with action `RELEASE_CREATED`." and "The
        release snapshots its accountability at creation: `plan_id` names the
        locked plan it was created against, while `dispatcher_id` and
        `captain_id` are copied from the leg and name the two accountable
        officers from that moment on."

        Design: Corner/state_machines/release_created_in_draft_initial_state
        """
        ctx = setup_manifest_chain()
        release = validate_success(
            api.create_release({"leg_id": ctx["leg"]["id"]}, ctx["d_headers"]), 201
        )
        assert_release(release)
        assert release["status"] == "DRAFT"
        assert release["cycle_seq"] == 1
        assert release["amendment_count"] == 0
        assert release["plan_id"] == ctx["plan"]["id"]
        assert release["dispatcher_id"] == ctx["dispatcher"]["id"]
        assert release["captain_id"] == ctx["captain"]["id"]

    def test_release_create_requires_manifest(self, api):
        """PRD §3.5: "Creation requires the leg's plan to be `LOCKED`
        (`ERR_PLAN_NOT_LOCKED` otherwise) and a manifest to exist for the leg
        (`ERR_MANIFEST_MISSING` otherwise)"

        Design: Corner/validations/release_create_requires_manifest
        """
        ctx = setup_locked_plan()  # LOCKED plan, no manifest
        res = api.create_release({"leg_id": ctx["leg"]["id"]}, ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_MANIFEST_MISSING.value)

    def test_second_release_rejected(self, api):
        """PRD §3.5: "at most one non-terminal release may exist per leg — a
        second open attempt is rejected with `ERR_RELEASE_EXISTS`."

        Design: Corner/validations/second_release_rejected
        """
        ctx = setup_release_draft()
        res = api.create_release({"leg_id": ctx["leg"]["id"]}, ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_RELEASE_EXISTS.value)

    def test_plan_create_blocked_when_plan_in_use(self, api):
        """PRD §3.3: "There is one hard exception — when a non-terminal release
        still references the leg's `LOCKED` plan, the supersede path is closed
        and plan creation is rejected with `ERR_PLAN_IN_USE`."

        Design: Corner/validations/plan_create_blocked_when_plan_in_use
        """
        from test_helpers import create_plan_payload

        ctx = setup_release_draft()
        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        res = api.create_plan(
            create_plan_payload(ctx["leg"]["id"], leg["version"],
                                route_code="DCT ALT DCT", cruise_altitude_ft=37000,
                                forecast_wind_kts=10),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PLAN_IN_USE.value)


class TestSubmitGateOnPlan:
    def test_release_submit_rejected_when_plan_recomputed(self, api):
        """PRD §3.5: "submission re-validates the entire safety envelope: the
        release's `plan_id` must still refer to a `LOCKED` plan
        (`ERR_PLAN_NOT_LOCKED`)"

        Design: Difficulty/cross_entity_state_dependency/release_submit_gated_on_plan_locked
        """
        ctx = setup_release_draft()
        recomputed = validate_success(
            api.recompute_plan(ctx["plan"]["id"], ctx["d_headers"]), 200
        )
        assert recomputed["status"] == "COMPUTED"
        res = api.submit_release(ctx["release"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_LOCKED.value)

    def test_release_submit_restored_after_relock(self, api):
        """PRD §3.5: "Submitting moves a `DRAFT` release — or an
        `UNDER_AMENDMENT` one, with every check re-evaluated against the current
        world state — to `PENDING_SIGNATURES`." Once the recomputed plan is
        locked again, the referential gate passes.

        Design: Difficulty/cross_entity_state_dependency/release_submit_gated_on_plan_locked
        """
        ctx = setup_release_draft()
        validate_success(api.recompute_plan(ctx["plan"]["id"], ctx["d_headers"]), 200)
        validate_success(api.lock_plan(ctx["plan"]["id"], ctx["d_headers"]), 200)
        submitted = validate_success(
            api.submit_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert submitted["status"] == "PENDING_SIGNATURES"


class TestSignatureCycle:
    def test_second_signature_same_slot_rejected(self, api):
        """PRD §3.5: "Signing the same slot twice within one cycle is rejected
        with `ERR_DUPLICATE_SIGNATURE`. When both slots hold valid signatures
        for the current cycle, the release transitions to `RELEASED` — the
        moment joint responsibility attaches — and each signing writes a
        `SIGNATURE_RECORDED` record." One filled slot leaves the release
        PENDING_SIGNATURES.

        Design: Corner/state_machines/second_signature_same_slot_rejected
        """
        ctx = setup_release_pending()
        mid = validate_success(
            api.sign_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert mid["status"] == "PENDING_SIGNATURES"
        res = api.sign_release(ctx["release"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SIGNATURE.value)
        after = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert after["status"] == "PENDING_SIGNATURES"

    def test_amendment_cycle_requires_fresh_dual_signature(self, api):
        """PRD §3.5: "A `RELEASED` release may be amended by the dispatcher of
        record, moving it to `UNDER_AMENDMENT` with `cycle_seq` incremented by
        one, `amendment_count` incremented by one, and a `RELEASE_AMENDED`
        record written; amendment likewise invalidates the existing signatures,
        so an amended release must pass through submission and a fresh dual
        signature before it is effective again."

        Design: Difficulty/non_linear_state_machine/release_signature_amendment_cycle
        """
        ctx = setup_release_released()
        assert ctx["release"]["status"] == "RELEASED"
        assert ctx["release"]["cycle_seq"] == 1

        amended = validate_success(
            api.amend_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert amended["status"] == "UNDER_AMENDMENT"
        assert amended["cycle_seq"] == 2
        assert amended["amendment_count"] == 1

        validate_success(api.submit_release(ctx["release"]["id"], ctx["d_headers"]),
                         200)
        mid = validate_success(
            api.sign_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert mid["status"] == "PENDING_SIGNATURES", (
            "dispatcher re-signature alone is insufficient — joint responsibility"
        )
        final = validate_success(
            api.sign_release(ctx["release"]["id"], ctx["c_headers"]), 200
        )
        assert final["status"] == "RELEASED"

    def test_amendment_cycle_signature_ledger_is_append_only(self, api):
        """PRD §3.5: "A signature is valid only while its recorded `cycle_seq`
        equals the release's current `cycle_seq`; the moment the cycle advances,
        every earlier signature goes stale." and "The signature list of a
        release is append-only and readable with standard pagination."

        Design: Difficulty/non_linear_state_machine/release_signature_amendment_cycle
        """
        ctx = setup_release_released()
        validate_success(api.amend_release(ctx["release"]["id"], ctx["d_headers"]),
                         200)
        validate_success(api.submit_release(ctx["release"]["id"], ctx["d_headers"]),
                         200)
        validate_success(api.sign_release(ctx["release"]["id"], ctx["d_headers"]),
                         200)
        validate_success(api.sign_release(ctx["release"]["id"], ctx["c_headers"]),
                         200)

        sigs, meta = validate_paginated(
            api.list_release_signatures(ctx["release"]["id"], ctx["d_headers"])
        )
        assert meta["total_count"] == 4
        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert release["cycle_seq"] == 2
        cycle1 = [s for s in sigs if s["cycle_seq"] == 1]
        cycle2 = [s for s in sigs if s["cycle_seq"] == 2]
        assert len(cycle1) == 2, "two stale cycle-1 rows remain in the ledger"
        assert len(cycle2) == 2, "two valid cycle-2 rows released the amendment"


class TestSignatureRowShape:
    def test_release_signature_immutable_rows(self, api):
        """PRD §2.5: "A `ReleaseSignature` and an `OperationalControlRecord`
        each carry only `id` and `created_at`; both `updated_at` and `version`
        are absent on these two append-only record types." PRD §3.5: "Each
        signing appends a **ReleaseSignature** recording the `release_id`, the
        `signer_role` derived from the caller's role (`DISPATCHER` for a
        `Dispatcher` caller, `CAPTAIN` for a `Captain` caller), the `signer_id`
        taken from the caller's `X-User-ID`, the release's `cycle_seq` at
        signing time, and the `signed_at_utc` logical-clock instant."

        Design: Corner/entities/release_signature_immutable_rows
        """
        ctx = setup_release_pending()
        validate_success(api.sign_release(ctx["release"]["id"], ctx["d_headers"]),
                         200)
        sigs, meta = validate_paginated(
            api.list_release_signatures(ctx["release"]["id"], ctx["d_headers"])
        )
        assert meta["total_count"] == 1
        sig = sigs[0]
        assert_release_signature(sig)
        assert sig["signer_role"] == "DISPATCHER"
        assert sig["signer_id"] == ctx["dispatcher"]["id"]
        assert sig["cycle_seq"] == 1
        # Fixture set the logical clock to 2026-05-01T08:00:00Z before signing.
        assert_instant_equals(sig["signed_at_utc"], "2026-05-01T08:00:00Z")


class TestRecallAndTerminal:
    def test_recall_from_released_returns_invalid_state(self, api):
        """PRD §3.5: "A `PENDING_SIGNATURES` release may be recalled to `DRAFT`
        by the dispatcher of record" — recall from RELEASED is not a defined
        transition, and per PRD §2.9 "6. **State-machine admissibility.** A
        target resource in the wrong from-state for the requested transition
        yields `ERR_INVALID_STATE`, `ERR_RELEASE_NOT_PENDING`, or
        `ERR_LEG_NOT_IN_FLIGHT` as the workflow specifies."

        Design: Corner/state_machines/recall_from_released_returns_invalid_state
        """
        ctx = setup_release_released()
        res = api.recall_release(ctx["release"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert after["status"] == "RELEASED"
        assert after["cycle_seq"] == 1

    def test_cancelled_release_terminal_lockdown(self, api):
        """PRD §3.5: "When the leg is cancelled or diverted, any non-terminal
        release — `DRAFT`, `PENDING_SIGNATURES`, `UNDER_AMENDMENT`, and in the
        diversion case `RELEASED` as well — transitions to `CANCELLED`. Terminal
        states are locked: no further transitions occur from `CANCELLED` or
        `CLOSED`."

        Design: Corner/state_machines/cancelled_release_terminal_lockdown
        """
        ctx = setup_release_draft()
        cancelled_leg = validate_success(
            api.cancel_leg(ctx["leg"]["id"], {"reason_code": "OPS"}, ctx["d_headers"]),
            200,
        )
        assert cancelled_leg["ops_status"] == "CANCELLED"
        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert release["status"] == "CANCELLED"
        res = api.submit_release(ctx["release"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestExpiredMelGate:
    def test_submit_with_expired_mel_rejected(self, api):
        """PRD §3.6: "And while any `EXPIRED` item exists on an aircraft,
        release submission, release signing, and departure for legs of that
        aircraft are all rejected with `ERR_MEL_ITEM_EXPIRED`."

        Design: Corner/validations/submit_with_expired_mel_rejected
        """
        ctx = setup_release_draft_with_expired_mel()
        mel = validate_success(api.get_mel_item(ctx["mel"]["id"], SUP), 200)
        assert mel["status"] == "EXPIRED"
        res = api.submit_release(ctx["release"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_MEL_ITEM_EXPIRED.value)

    def test_sign_conflict_state_beats_safety_dispatcher(self, api):
        """PRD §2.9: "6. **State-machine admissibility.** A target resource in
        the wrong from-state for the requested transition yields
        `ERR_INVALID_STATE`, `ERR_RELEASE_NOT_PENDING`, or
        `ERR_LEG_NOT_IN_FLIGHT` as the workflow specifies." precedes
        "7. **Business safety.** Deferred-defect expiry, worst-case wind
        enforcement, captain qualification, dual-role segregation, and the rest
        buffer yield `ERR_MEL_ITEM_EXPIRED`, `ERR_WORST_CASE_REQUIRED`,
        `ERR_CAPTAIN_NOT_QUALIFIED`, `ERR_DUAL_ROLE_ASSIGNMENT`, or
        `ERR_REST_VIOLATION`." Signing a DRAFT release on an aircraft with an
        EXPIRED item therefore surfaces ERR_RELEASE_NOT_PENDING.

        Design: Difficulty/priority_pair_validation_conflict/sign_conflict_state_beats_safety
        """
        ctx = setup_release_draft_with_expired_mel()
        mel = validate_success(api.get_mel_item(ctx["mel"]["id"], SUP), 200)
        assert mel["status"] == "EXPIRED"
        res = api.sign_release(ctx["release"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_RELEASE_NOT_PENDING.value)

    def test_sign_conflict_state_beats_safety_captain(self, api):
        """PRD §2.9: "6. **State-machine admissibility.** A target resource in
        the wrong from-state for the requested transition yields
        `ERR_INVALID_STATE`, `ERR_RELEASE_NOT_PENDING`, or
        `ERR_LEG_NOT_IN_FLIGHT` as the workflow specifies." — the captain slot
        of the same DRAFT release hits the same state error even though the
        EXPIRED item also violates the business-safety rule (item 7).

        Design: Difficulty/priority_pair_validation_conflict/sign_conflict_state_beats_safety
        """
        ctx = setup_release_draft_with_expired_mel()
        mel = validate_success(api.get_mel_item(ctx["mel"]["id"], SUP), 200)
        assert mel["status"] == "EXPIRED"
        res = api.sign_release(ctx["release"]["id"], ctx["c_headers"])
        validate_error(res, ApiErrorId.ERR_RELEASE_NOT_PENDING.value)


class TestReleaseRbacOwnership:
    def test_supervisor_cannot_sign_forbidden(self, api):
        """PRD §2.10: "The `DispatchSupervisor` role has no signature authority
        whatsoever." PRD §2.1: "A request whose role is not in the target
        endpoint's authorized role list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/supervisor_cannot_sign_forbidden
        """
        ctx = setup_release_pending()
        res = api.sign_release(ctx["release"]["id"], SUP)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)

    def test_dispatcher_cannot_create_station_forbidden(self, api):
        """PRD §2.1: "A request whose role is not in the target endpoint's
        authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4 restricts POST /dispatch/stations to
        DispatchSupervisor.

        Design: Corner/rbac/dispatcher_cannot_create_station_forbidden
        """
        from test_helpers import create_station_payload, setup_reference_data

        ctx = setup_reference_data(with_alternate=False)
        res = api.create_station(create_station_payload(iata_code="KAAA"),
                                 ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)

    def test_non_assigned_dispatcher_cannot_submit(self, api):
        """PRD §3.5: "Only the dispatcher of record may submit
        (`ERR_NOT_ASSIGNED_DISPATCHER` otherwise)"

        Design: Corner/rbac/non_assigned_dispatcher_cannot_submit
        """
        ctx = setup_release_draft()
        d2 = validate_success(
            api.create_dispatcher(
                create_dispatcher_payload(name="Dana Two", license_no="D002"), SUP
            ),
            201,
        )
        res = api.submit_release(ctx["release"]["id"],
                                 make_dispatcher_headers(d2["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_DISPATCHER.value,
                       expected_status=403)

    def test_non_assigned_captain_cannot_sign(self, api):
        """PRD §3.5: "A captain caller must be the release's `captain_id` and a
        dispatcher caller its `dispatcher_id` (`ERR_NOT_ASSIGNED_CAPTAIN`,
        `ERR_NOT_ASSIGNED_DISPATCHER`); no one may sign a slot that is not
        theirs."

        Design: Corner/rbac/non_assigned_captain_cannot_sign
        """
        ctx = setup_release_pending()
        c2 = validate_success(
            api.create_captain(
                create_captain_payload(name="Cole Two", license_no="C002"), SUP
            ),
            201,
        )
        res = api.sign_release(ctx["release"]["id"], make_captain_headers(c2["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_CAPTAIN.value,
                       expected_status=403)
