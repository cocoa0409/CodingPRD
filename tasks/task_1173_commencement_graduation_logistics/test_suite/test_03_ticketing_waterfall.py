"""Guest ticketing: provisional vs FINAL waterfall variants, waterfall
ordering, entitlement caps, eligibility gates, pool conservation, promotion
cascade, deadline precedence, ownership, and OCC on requests."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_ceremony, setup_ceremony_with_graduates, import_graduate,
    import_and_audit, audit_graduate, get_graduate, get_graduate_allocation, request_tickets,
    run_waterfall, get_ceremony, create_reader_card, set_clock,
    create_ticket_request_payload, make_graduate_headers,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def _setup_rain_waterfall():
    """GX SUMMA req 6, GZ MAGNA req 6, GY NONE req 4 — all requested during
    AUDIT_OPEN; ceremony (cap 10 / rain cap 6, ratio 2.0) ends AUDIT_LOCKED."""
    ctx = setup_ceremony_with_graduates(
        [
            {"full_name": "Gail Summa", "email": "gx@x.edu", "tier": "SUMMA", "request": 6},
            {"full_name": "Zoe Magna", "email": "gz@x.edu", "tier": "MAGNA", "request": 6},
            {"full_name": "Yan None", "email": "gy@x.edu", "tier": "NONE", "request": 4},
        ],
        posture="AUDIT_LOCKED", ticket_ratio=2.0, venue_capacity=10,
        venue_accessible=2, venue_indoor=False, rain_capacity=6, rain_accessible=1)
    return ctx


class TestTicketDualVariantUnderRain:
    def test_provisional_estimate_under_fair_pool(self, api):
        """PRD §3.3: "At filing time the server computes the PROVISIONAL
        waterfall variant: the smaller of the `requested_count`, the
        entitlement evaluated with the graduate's **current** `honor_tier`
        (which, mid-audit, may still be a COMBINED provisional tier), and the
        ceremony's **current** `ticket_pool_remaining` under the current
        weather."

        Design: Difficulty/dual_variant_calc/ticket_provisional_vs_final_waterfall_under_rain
        """
        ctx = _setup_rain_waterfall()
        gx, gz, gy = (a for a in ctx["allocations"])
        # FAIR pool is floor(10 * 2.0) = 20; PROVISIONAL never mutates the pool
        assert gx["provisional_granted_count"] == 6  # min(req 6, entitlement 6, pool 20)
        assert gz["provisional_granted_count"] == 6
        assert gy["provisional_granted_count"] == 4  # min(req 4, entitlement 4, pool 20)

    def test_final_waterfall_under_shrunken_rain_pool(self, api):
        """PRD §3.3: "it never mutates the pool, and it may diverge from the
        FINAL grant computed later under finalized tiers or a shrunken
        rain-plan capacity."
        PRD §3.3: "a grant of exactly zero lands it in `WAITLISTED`, assigned a
        1-based `waitlist_position` ranking it among the zero-grant allocations
        in waterfall order."

        Design: Difficulty/dual_variant_calc/ticket_provisional_vs_final_waterfall_under_rain
        """
        ctx = _setup_rain_waterfall()
        ceremony_id = ctx["ceremony"]["id"]
        gx, gz, gy = (g["id"] for g in ctx["graduates"])
        validate_success(api.activate_rain_plan(ceremony_id,
                                                TEST_USERS["venue_coordinator_headers"]), 200)
        report = run_waterfall(ceremony_id)
        # rain pool == floor(6 * 2.0) == 12: SUMMA 6 + MAGNA 6 exhaust it
        assert report["pool_remaining"] == 0

        alloc_gx = get_graduate_allocation(gx)
        alloc_gz = get_graduate_allocation(gz)
        alloc_gy = get_graduate_allocation(gy)
        assert alloc_gx["granted_count"] == 6 and alloc_gx["status"] == "ALLOCATED"
        assert alloc_gz["granted_count"] == 6 and alloc_gz["status"] == "ALLOCATED"
        assert alloc_gy["granted_count"] == 0
        assert alloc_gy["status"] == "WAITLISTED"
        assert alloc_gy["waitlist_position"] == 1
        # the same request data (4 tickets) granted 4 provisionally, 0 finally
        assert alloc_gy["provisional_granted_count"] == 4


def _setup_multi_input_waterfall():
    """GA SUMMA req 6, GC MAGNA req 6, GB NONE req 4; pool floor(10*2.0) = 20;
    ceremony AUDIT_LOCKED, waterfall not yet run."""
    return setup_ceremony_with_graduates(
        [
            {"full_name": "Ann Summa", "email": "ga@x.edu", "tier": "SUMMA", "request": 6},
            {"full_name": "Cid Magna", "email": "gc@x.edu", "tier": "MAGNA", "request": 6},
            {"full_name": "Bob None", "email": "gb@x.edu", "tier": "NONE", "request": 4},
        ],
        posture="AUDIT_LOCKED", ticket_ratio=2.0)


class TestWaterfallMultiInputOrdering:
    def test_waterfall_grants_in_honor_rank_order(self, api):
        """PRD §3.3: "then walks the **waterfall order**: honor rank descending
        (`SUMMA_CUM_LAUDE` outranks `MAGNA_CUM_LAUDE`, which outranks
        `CUM_LAUDE`, which outranks `NONE`), then `requested_count` descending,
        then the allocation's `created_at` ascending — the allocation `id` is
        never a tiebreaker."
        PRD §3.3: "The run reports `processed_count`, `granted_total`,
        `waitlisted_count`, and the closing `pool_remaining`."

        Design: Difficulty/combinatorial_formula/waterfall_multi_input_entitlement_ordering
        """
        ctx = _setup_multi_input_waterfall()
        report = run_waterfall(ctx["ceremony"]["id"])
        assert report["granted_total"] == 16
        assert report["processed_count"] == 3
        assert report["waitlisted_count"] == 0
        assert report["pool_remaining"] == 4

        ga, gc, gb = (get_graduate_allocation(g["id"]) for g in ctx["graduates"])
        assert ga["granted_count"] == 6 and ga["status"] == "ALLOCATED"
        assert gc["granted_count"] == 6 and gc["status"] == "ALLOCATED"
        assert gb["granted_count"] == 4 and gb["status"] == "ALLOCATED"

    def test_waterfall_entitlement_snapshots_and_pool_fields(self, api):
        """PRD §3.3: "the ceremony's `guest_ticket_base_cap` plus, for a
        graduate whose current `honor_tier` is anything other than `NONE`, the
        ceremony's `honor_bonus_tickets`".
        PRD §3.3: "its `entitlement_count` is snapshotted at each waterfall
        run."
        PRD §2.9: "The `ticket_pool_total` is the `effective_capacity`
        multiplied by the ceremony's `ticket_ratio`, rounded down to a whole
        number."

        Design: Difficulty/combinatorial_formula/waterfall_multi_input_entitlement_ordering
        """
        ctx = _setup_multi_input_waterfall()
        run_waterfall(ctx["ceremony"]["id"])
        ga, gc, gb = (get_graduate_allocation(g["id"]) for g in ctx["graduates"])
        assert ga["entitlement_count"] == 6  # 4 base + 2 honor bonus
        assert gc["entitlement_count"] == 6
        assert gb["entitlement_count"] == 4  # NONE: no bonus

        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["ticket_pool_total"] == 20  # floor(10 * 2.0)
        assert ceremony["ticket_pool_remaining"] == 4


class TestTicketRequestCapBoundary:
    def _setup_none_graduate(self):
        ctx = setup_ceremony(open_audit=True)
        graduate, _ = import_and_audit(ctx["ceremony"]["id"], full_name="Cap Tester",
                                       email="cap@x.edu", tier="NONE")
        return ctx, graduate

    def test_request_exactly_entitlement_accepted(self, api):
        """PRD §3.3: "the `requested_count` must be at least one (else
        `ERR_INVALID_REQUEST`) and no greater than the graduate's entitlement —
        the ceremony's `guest_ticket_base_cap` plus, for a graduate whose
        current `honor_tier` is anything other than `NONE`, the ceremony's
        `honor_bonus_tickets`; asking for exactly the entitlement is allowed,
        and asking for more is rejected with `ERR_TICKET_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/ticket_request_exact_cap_boundary
        """
        ctx, graduate = self._setup_none_graduate()
        updated = request_tickets(graduate["id"], 4)  # entitlement is exactly 4
        assert updated["requested_count"] == 4
        assert updated["provisional_granted_count"] == 4  # min(4, 4, pool 10)
        assert updated["version"] == 2

    def test_request_above_entitlement_rejected_and_zero_invalid(self, api):
        """PRD §3.3: "the `requested_count` must be at least one (else
        `ERR_INVALID_REQUEST`) and no greater than the graduate's entitlement —
        the ceremony's `guest_ticket_base_cap` plus, for a graduate whose
        current `honor_tier` is anything other than `NONE`, the ceremony's
        `honor_bonus_tickets`; asking for exactly the entitlement is allowed,
        and asking for more is rejected with `ERR_TICKET_CAP_EXCEEDED`."
        PRD §2.11: "Body schema — required fields present, types valid, enum
        values inside their declared domains, and ranges valid (a requested
        ticket count of at least one, an `end_utc` strictly after its
        `start_utc`, capacities of at least one, amounts of at least zero),
        else `ERR_INVALID_REQUEST`."

        Design: Difficulty/boundary_precision_check/ticket_request_exact_cap_boundary
        """
        ctx, graduate = self._setup_none_graduate()
        allocation = request_tickets(graduate["id"], 4)

        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(5, allocation["version"]),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_TICKET_CAP_EXCEEDED)
        assert res.status_code == 422  # 5 > 4 strictly

        fresh = get_graduate_allocation(graduate["id"])
        res_zero = api.request_tickets(
            fresh["id"],
            create_ticket_request_payload(0, fresh["version"]),
            make_graduate_headers(graduate["id"]))
        validate_error(res_zero, ApiErrorId.ERR_INVALID_REQUEST)
        assert res_zero.status_code == 400

        assert get_graduate_allocation(graduate["id"])["requested_count"] == 4


class TestTicketRequestEligibilityGate:
    def test_pending_audit_graduate_request_rejected(self, api):
        """PRD §3.3: "the graduate's `status` must be `ELIGIBLE`,
        `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` (else
        `ERR_GRADUATE_NOT_ELIGIBLE`)".
        PRD §3.2: "Import also auto-creates the graduate's ticket allocation in
        `PENDING` status with a `requested_count` of zero".

        Design: Difficulty/cross_entity_state_dependency/ticket_request_requires_eligible_graduate
        """
        ctx = setup_ceremony(open_audit=True)
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Unaudited Uma",
                                   email="uma@x.edu")
        allocation = get_graduate_allocation(graduate["id"])
        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(2, allocation["version"]),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_GRADUATE_NOT_ELIGIBLE)
        assert res.status_code == 409

    def test_gate_leaves_allocation_untouched_and_lifts_after_audit(self, api):
        """PRD §3.3: "the graduate's `status` must be `ELIGIBLE`,
        `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` (else
        `ERR_GRADUATE_NOT_ELIGIBLE`)".
        PRD §3.3: "A successful filing updates `requested_count`, recomputes
        `provisional_granted_count`, and increments the allocation's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/ticket_request_requires_eligible_graduate
        """
        ctx = setup_ceremony(open_audit=True)
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Unaudited Uma",
                                   email="uma@x.edu")
        allocation = get_graduate_allocation(graduate["id"])
        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(2, allocation["version"]),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_GRADUATE_NOT_ELIGIBLE)

        after_fail = get_graduate_allocation(graduate["id"])
        assert after_fail["requested_count"] == 0
        assert after_fail["status"] == "PENDING"
        assert after_fail["version"] == allocation["version"]

        audit_graduate(graduate["id"])  # PASS -> ELIGIBLE
        updated = request_tickets(graduate["id"], 2)
        assert updated["requested_count"] == 2


def _setup_two_granted_pool():
    """Venue cap 10, ratio 1.0 (pool 10); NONE graduates A and B each request
    4; waterfall run grants 4 + 4. Returns (ctx, alloc_a, alloc_b, report)."""
    ctx = setup_ceremony_with_graduates(
        [
            {"full_name": "A Pool", "email": "pa@x.edu", "tier": "NONE", "request": 4},
            {"full_name": "B Pool", "email": "pb@x.edu", "tier": "NONE", "request": 4},
        ],
        posture="AUDIT_LOCKED", ticket_ratio=1.0)
    report = run_waterfall(ctx["ceremony"]["id"])
    ga, gb = ctx["graduates"]
    return ctx, get_graduate_allocation(ga["id"]), get_graduate_allocation(gb["id"]), report


class TestTicketPoolConservation:
    def test_grants_debit_pool_exactly(self, api):
        """PRD §2.9: "The `ticket_pool_remaining` is the `ticket_pool_total`
        minus the sum of `granted_count` over all of the ceremony's ticket
        allocations whose status is `PENDING`, `ALLOCATED`, `PARTIAL`, or
        `WAITLISTED` — allocations in `RELEASED` or `EXPIRED` contribute
        nothing."

        Design: Difficulty/compensating_invariant/ticket_pool_grant_release_conservation
        """
        ctx, alloc_a, alloc_b, report = _setup_two_granted_pool()
        assert report["pool_remaining"] == 2  # 10 - 4 - 4
        assert alloc_a["granted_count"] == 4 and alloc_a["status"] == "ALLOCATED"
        assert alloc_b["granted_count"] == 4 and alloc_b["status"] == "ALLOCATED"
        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["ticket_pool_total"] == 10
        assert ceremony["ticket_pool_remaining"] == 2

    def test_release_credits_pool_back_with_zero_drift(self, api):
        """PRD §3.3: "Releasing an allocation — permitted from `PENDING`,
        `ALLOCATED`, `PARTIAL`, or `WAITLISTED` — credits the full
        `granted_count` back to `ticket_pool_remaining`, zeroes
        `granted_count`, clears `waitlist_position`, moves the allocation to
        the terminal `RELEASED`, increments its `version`, and immediately
        fires the promotion scan over the remaining `WAITLISTED` and `PARTIAL`
        allocations in waterfall order."

        Design: Difficulty/compensating_invariant/ticket_pool_grant_release_conservation
        """
        ctx, alloc_a, alloc_b, _report = _setup_two_granted_pool()
        ga_id = ctx["graduates"][0]["id"]
        released = validate_success(
            api.release_tickets(alloc_a["id"], make_graduate_headers(ga_id)), 200)
        assert released["status"] == "RELEASED"
        assert released["granted_count"] == 0
        assert released["waitlist_position"] is None

        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["ticket_pool_total"] == 10
        assert ceremony["ticket_pool_remaining"] == 6
        other = get_graduate_allocation(ctx["graduates"][1]["id"])
        assert other["granted_count"] == 4 and other["status"] == "ALLOCATED"
        # conservation invariant: 10 == 6 + 4 (B) with zero pool drift
        assert ceremony["ticket_pool_total"] == (
            ceremony["ticket_pool_remaining"] + other["granted_count"])


def _setup_withdraw_promote_scenario():
    """Venue cap 8, ratio 2.0 (pool 16); A SUMMA req 6, C MAGNA req 6,
    B NONE req 4, D NONE req 4 (B created before D); waterfall run."""
    ctx = setup_ceremony_with_graduates(
        [
            {"full_name": "A Summa", "email": "a@x.edu", "tier": "SUMMA", "request": 6},
            {"full_name": "C Magna", "email": "c@x.edu", "tier": "MAGNA", "request": 6},
            {"full_name": "B None", "email": "b@x.edu", "tier": "NONE", "request": 4},
            {"full_name": "D None", "email": "d@x.edu", "tier": "NONE", "request": 4},
        ],
        posture="AUDIT_LOCKED", ticket_ratio=2.0, venue_capacity=8)
    report = run_waterfall(ctx["ceremony"]["id"])
    return ctx, report


class TestWithdrawReleasePromoteCascade:
    def test_withdrawal_releases_and_promotes_waitlisted(self, api):
        """PRD §3.9: "The graduate's ticket allocation, unless already
        `RELEASED` or `EXPIRED`, moves to `RELEASED`: its `granted_count` is
        credited back to `ticket_pool_remaining` and zeroed, and the release
        itself fires the promotion scan of §3.3 over the remaining `WAITLISTED`
        and `PARTIAL` allocations, each promotion decrementing the pool anew."
        PRD §3.3: "A top-up that closes the gap promotes the allocation to
        `ALLOCATED`, setting `granted_count` to the full target and clearing
        `waitlist_position`".

        Design: Difficulty/transitive_cascade/withdraw_release_promote_pool_cascade
        """
        ctx, report = _setup_withdraw_promote_scenario()
        assert report["pool_remaining"] == 0  # 16 - 6 - 6 - 4
        ga, _gc, _gb, gd = ctx["graduates"]
        alloc_d = get_graduate_allocation(gd["id"])
        assert alloc_d["status"] == "WAITLISTED"
        assert alloc_d["waitlist_position"] == 1

        validate_success(api.withdraw_graduate(ga["id"], REGISTRAR), 200)

        alloc_a = get_graduate_allocation(ga["id"])
        assert alloc_a["status"] == "RELEASED"
        assert alloc_a["granted_count"] == 0
        alloc_d = get_graduate_allocation(gd["id"])
        assert alloc_d["status"] == "ALLOCATED"
        assert alloc_d["granted_count"] == 4
        assert alloc_d["waitlist_position"] is None

    def test_cascade_conserves_pool_and_leaves_others_untouched(self, api):
        """PRD §3.9: "The graduate's ticket allocation, unless already
        `RELEASED` or `EXPIRED`, moves to `RELEASED`: its `granted_count` is
        credited back to `ticket_pool_remaining` and zeroed, and the release
        itself fires the promotion scan of §3.3 over the remaining `WAITLISTED`
        and `PARTIAL` allocations, each promotion decrementing the pool anew."
        PRD §2.9: "The `ticket_pool_remaining` is the `ticket_pool_total` minus
        the sum of `granted_count` over all of the ceremony's ticket
        allocations whose status is `PENDING`, `ALLOCATED`, `PARTIAL`, or
        `WAITLISTED` — allocations in `RELEASED` or `EXPIRED` contribute
        nothing."

        Design: Difficulty/transitive_cascade/withdraw_release_promote_pool_cascade
        """
        ctx, _report = _setup_withdraw_promote_scenario()
        ga, gc, gb, gd = ctx["graduates"]
        validate_success(api.withdraw_graduate(ga["id"], REGISTRAR), 200)

        assert get_graduate(ga["id"])["status"] == "WITHDRAWN"
        alloc_b = get_graduate_allocation(gb["id"])
        assert alloc_b["granted_count"] == 4 and alloc_b["status"] == "ALLOCATED"
        alloc_c = get_graduate_allocation(gc["id"])
        assert alloc_c["granted_count"] == 6 and alloc_c["status"] == "ALLOCATED"
        alloc_d = get_graduate_allocation(gd["id"])
        assert alloc_d["granted_count"] == 4

        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["ticket_pool_total"] == 16
        # 16 == 2 + 6 (C) + 4 (B) + 4 (D); A RELEASED contributes nothing
        assert ceremony["ticket_pool_remaining"] == 2


class TestTicketRequestDeadlinePrecedence:
    def _setup_past_deadline(self):
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Tim Late", "email": "tim@x.edu", "tier": "NONE"}],
            posture="AUDIT_OPEN")
        set_clock("2026-05-16T00:00:00Z")  # ticket_request_deadline is 2026-05-15
        return ctx

    def test_deadline_beats_cap_when_both_violated(self, api):
        """PRD §2.11: "on a ticket request, the request-window rejection
        (`ERR_REQUEST_WINDOW_CLOSED`) always surfaces before the
        entitlement-cap rejection (`ERR_TICKET_CAP_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/ticket_request_deadline_beats_cap_conflict
        """
        ctx = self._setup_past_deadline()
        graduate = ctx["graduates"][0]
        allocation = get_graduate_allocation(graduate["id"])
        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(5, allocation["version"]),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_REQUEST_WINDOW_CLOSED)
        assert res.status_code == 422  # 5 > entitlement 4 too, temporal wins

    def test_deadline_fires_alone_within_cap(self, api):
        """PRD §2.10: "A ticket request posted strictly after the ceremony's
        `ticket_request_deadline` is rejected with
        `ERR_REQUEST_WINDOW_CLOSED`".

        Design: Difficulty/priority_pair_validation_conflict/ticket_request_deadline_beats_cap_conflict
        """
        ctx = self._setup_past_deadline()
        graduate = ctx["graduates"][0]
        allocation = get_graduate_allocation(graduate["id"])
        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(4, allocation["version"]),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_REQUEST_WINDOW_CLOSED)
        assert res.status_code == 422


class TestWaterfallInputSetFiltering:
    def test_waterfall_rerun_excludes_released_allocations(self, api):
        """PRD §3.3: "Its scope is every allocation of the ceremony in
        `PENDING`, `ALLOCATED`, `PARTIAL`, or `WAITLISTED` status with a
        `requested_count` of at least one — `RELEASED` and `EXPIRED`
        allocations are out, and a `PENDING` allocation that never requested
        simply stays `PENDING`."

        Design: Corner/calculations/waterfall_rerun_excludes_released_allocations
        """
        ctx, alloc_a, alloc_b, _report = _setup_two_granted_pool()
        ga_id = ctx["graduates"][0]["id"]
        validate_success(api.release_tickets(alloc_a["id"],
                                             make_graduate_headers(ga_id)), 200)

        report = run_waterfall(ctx["ceremony"]["id"])
        assert report["processed_count"] == 1
        assert report["pool_remaining"] == 6

        assert get_graduate_allocation(ga_id)["status"] == "RELEASED"
        assert get_graduate_allocation(ga_id)["granted_count"] == 0
        other = get_graduate_allocation(ctx["graduates"][1]["id"])
        assert other["status"] == "ALLOCATED"
        assert other["granted_count"] == 4


class TestImmediateConsistency:
    def test_mutation_visible_in_same_response(self, api):
        """PRD §3.3: "A successful filing updates `requested_count`, recomputes
        `provisional_granted_count`, and increments the allocation's
        `version`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/mutation_visible_in_same_response
        """
        ctx = setup_ceremony(open_audit=True)
        graduate, _ = import_and_audit(ctx["ceremony"]["id"], full_name="Imm Irene",
                                       email="irene@x.edu", tier="SUMMA")
        allocation = get_graduate_allocation(graduate["id"])
        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(3, allocation["version"]),
            make_graduate_headers(graduate["id"]))
        updated = validate_success(res, 200)
        # SUMMA entitlement 6, pool 10: provisional == min(3, 6, 10) == 3
        assert updated["requested_count"] == 3
        assert updated["provisional_granted_count"] == 3
        assert updated["version"] == 2


class TestCompletionExpiresAllocations:
    def test_complete_expires_pending_allocations(self, api):
        """PRD §3.1: "Completion sweeps the ticket book: every allocation still
        `PENDING` or `WAITLISTED` for the ceremony moves to `EXPIRED`, its
        `granted_count` zeroed and its `waitlist_position` cleared."

        Design: Corner/state_machines/complete_expires_pending_allocations
        """
        ctx = setup_ceremony(open_audit=True)
        ceremony = ctx["ceremony"]
        graduate, _ = import_and_audit(ceremony["id"], full_name="Silent Sal",
                                       email="sal@x.edu")
        validate_success(api.lock_audit(ceremony["id"], CHAIR), 200)
        create_reader_card(graduate["id"], "SAH-lent SAL")
        validate_success(api.mark_ready(ceremony["id"], CHAIR), 200)
        validate_success(api.commence_ceremony(ceremony["id"], CHAIR), 200)

        before = get_graduate_allocation(graduate["id"])
        assert before["status"] == "PENDING"

        completed = validate_success(api.complete_ceremony(ceremony["id"], CHAIR), 200)
        assert completed["readiness_posture"] == "COMPLETED"
        after = get_graduate_allocation(graduate["id"])
        assert after["status"] == "EXPIRED"
        assert after["granted_count"] == 0


class TestTicketOwnershipAndConcurrency:
    def test_graduate_cannot_request_for_other_allocation_returns_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Graduate`, `X-User-ID` is the `id`
        of the acting Graduate; ownership checks on any resource that
        references a Graduate compare the resource's graduate foreign-key field
        to `X-User-ID`, and a mismatch is rejected with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/graduate_cannot_request_for_other_allocation_returns_forbidden
        """
        ctx = setup_ceremony_with_graduates(
            [
                {"full_name": "Owner Amy", "email": "amy@x.edu"},
                {"full_name": "Owner Bill", "email": "bill@x.edu"},
            ],
            posture="AUDIT_OPEN")
        ga, gb = ctx["graduates"]
        alloc_b = get_graduate_allocation(gb["id"])
        res = api.request_tickets(
            alloc_b["id"],
            create_ticket_request_payload(2, alloc_b["version"]),
            make_graduate_headers(ga["id"]))  # Amy presents Bill's allocation
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert res.status_code == 403

    def test_occ_ticket_request_stale_version_returns_412(self, api):
        """PRD §2.6: "Posting a guest-ticket request requires
        `expected_ticket_allocation_version`, matched against the allocation's
        current `version`. Because a new request supersedes the allocation's
        prior request terms, a mismatch means the client is about to silently
        overwrite request terms it never saw, and the request is rejected."

        Design: Corner/validations/occ_ticket_request_stale_version_returns_412
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Occ Olga", "email": "olga@x.edu"}], posture="AUDIT_OPEN")
        graduate = ctx["graduates"][0]
        allocation = get_graduate_allocation(graduate["id"])
        first = validate_success(
            api.request_tickets(
                allocation["id"],
                create_ticket_request_payload(2, allocation["version"]),
                make_graduate_headers(graduate["id"])), 200)
        assert first["requested_count"] == 2

        res = api.request_tickets(
            allocation["id"],
            create_ticket_request_payload(3, allocation["version"]),  # stale
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert res.status_code == 412
        assert get_graduate_allocation(graduate["id"])["requested_count"] == 2


class TestWaterfallRoleAuthorization:
    def test_registrar_cannot_run_waterfall_returns_unauthorized(self, api):
        """PRD §2.1: "A `CommitteeChair` owns the ceremony lifecycle (creation,
        configuration, audit open/lock/reopen, readiness, commencement,
        completion), runs the ticket waterfall, decides appeals, approves
        reader cards, fulfills regalia, issues diplomas, and manages vendor
        contracts."
        PRD §2.1: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/registrar_cannot_run_waterfall_returns_unauthorized
        """
        ctx = setup_ceremony(lock_audit=True)
        res = api.run_ticket_waterfall(ctx["ceremony"]["id"], REGISTRAR)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert res.status_code == 403
