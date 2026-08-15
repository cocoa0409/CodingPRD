"""Waitlist joins, offer selection, claims, expiry requeue, and withdrawal."""
from test_helpers import (
    ApiErrorId,
    cancel_permit,
    create_allocation,
    create_patron,
    get_allocation,
    get_allocation_version,
    get_waitlist_entry,
    join_waitlist,
    make_commuter_headers,
    purchase_permit,
    set_clock,
    setup_blocked_patron,
    setup_full_allocation,
    setup_offered_entry,
    setup_waitlisting_with_entry,
    validate_error,
    validate_success,
)


class TestJoinConstraints:
    def test_duplicate_waitlist_join_rejected(self, api):
        """PRD §3.4: "A patron may hold at most one entry with status
        `WAITING` or `OFFERED` per allocation — duplicates are rejected with
        `ERR_ALREADY_WAITLISTED` (HTTP 409)."

        Design: Corner/validations/duplicate_waitlist_join_rejected
        """
        ctx = setup_waitlisting_with_entry(waiter_name="D", lot_code="LD")
        resp = api.create_waitlist_entry(
            {"patron_id": ctx["waiter"]["id"], "allocation_id": ctx["allocation"]["id"]},
            make_commuter_headers(ctx["waiter"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_WAITLISTED, 409)

    def test_rejoin_waitlist_after_withdrawal_allowed(self, api):
        """PRD §3.4: "A patron may hold at most one entry with status
        `WAITING` or `OFFERED` per allocation — duplicates are rejected with
        `ERR_ALREADY_WAITLISTED` (HTTP 409)."
        PRD §3.4.3: "Withdrawing from `WAITING` simply transitions to
        `WITHDRAWN`."

        Design: Corner/state_machines/rejoin_waitlist_after_withdrawal_allowed
        """
        ctx = setup_waitlisting_with_entry(waiter_name="K", lot_code="LK")
        api.withdraw_waitlist_entry(
            ctx["entry"]["id"], make_commuter_headers(ctx["waiter"]["id"])
        )
        resp = api.create_waitlist_entry(
            {"patron_id": ctx["waiter"]["id"], "allocation_id": ctx["allocation"]["id"]},
            make_commuter_headers(ctx["waiter"]["id"]),
        )
        entry = validate_success(resp, 201)
        assert entry["status"] == "WAITING", (
            f"a WITHDRAWN prior entry must not block rejoining, got {entry['status']}"
        )


class TestClaimStateGate:
    def test_claim_withdrawn_entry_rejected(self, api):
        """PRD §3.4.2: "The entry must be `OFFERED` — otherwise
        `ERR_OFFER_NOT_PENDING` (HTTP 409)."

        Design: Corner/state_machines/claim_withdrawn_entry_rejected
        """
        ctx = setup_waitlisting_with_entry(waiter_name="J", lot_code="LJ")
        api.withdraw_waitlist_entry(
            ctx["entry"]["id"], make_commuter_headers(ctx["waiter"]["id"])
        )
        version = get_allocation_version(ctx["allocation"]["id"])
        resp = api.claim_waitlist_entry(
            ctx["entry"]["id"],
            {"expected_allocation_version": version},
            make_commuter_headers(ctx["waiter"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_PENDING, 409)


class TestDeclineOffered:
    def test_decline_offered_entry_releases_hold(self, api):
        """PRD §3.4.3: "Withdrawing from `OFFERED` (declining the offer)
        additionally increments `decline_count` by `1`, decrements the
        allocation's `offers_outstanding` by `1`, re-evaluates allocation
        status, and increments the allocation's `version`."
        PRD §3.2: "after any mutation that leaves the sum strictly below
        `quota`, it flips back to `OPEN`."

        Design: Corner/state_machines/decline_offered_entry_releases_hold
        """
        ctx = setup_offered_entry(waiter_name="D", lot_code="LD")
        assert ctx["entry"]["status"] == "OFFERED"

        resp = api.withdraw_waitlist_entry(
            ctx["entry"]["id"], make_commuter_headers(ctx["waiter"]["id"])
        )
        entry = validate_success(resp, 200)
        assert entry["status"] == "WITHDRAWN"
        assert entry["decline_count"] == 1, (
            f"declining an offer adds one decline, got {entry['decline_count']}"
        )

        allocation = get_allocation(ctx["allocation"]["id"])
        assert allocation["offers_outstanding"] == 0, (
            f"the held seat is released, got {allocation['offers_outstanding']}"
        )
        assert allocation["status"] == "OPEN", (
            f"0 allocated + 0 offered < quota 1 must flip the allocation OPEN, "
            f"got {allocation['status']}"
        )


class TestPriorityScoreOrdering:
    """Quota-1 allocation occupied; S (STAFF) waited since 2026-08-01, T
    (STUDENT) since 2026-08-06; the occupier cancels at 2026-08-21."""

    def _setup(self):
        ctx = setup_full_allocation(lot_code="LW")
        staff = create_patron(full_name="S", campus_role="STAFF",
                              residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        s_entry = join_waitlist(staff["id"], ctx["allocation"]["id"])  # at 2026-08-01
        set_clock("2026-08-06T00:00:00Z")
        student = create_patron(full_name="T", campus_role="STUDENT",
                                residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        t_entry = join_waitlist(student["id"], ctx["allocation"]["id"])
        set_clock("2026-08-21T00:00:00Z")
        ctx.update({"staff": staff, "s_entry": s_entry,
                    "student": student, "t_entry": t_entry})
        return ctx

    def test_offer_round_promotes_highest_scored_entry(self, api, admin_headers):
        """PRD §3.4.1: "the system ranks all `WAITING` entries on the
        allocation by `waitlist_priority_score` descending, tie-broken by
        `waiting_since` ascending (earliest waiter first), and promotes at
        most that many entries to `OFFERED`." and "The score is the role
        weight (`FACULTY` contributes `100`, `STAFF` contributes `80`,
        `STUDENT` contributes `60`), plus two points per `wait_day` capped at
        thirty days of credit (so the wait-day term contributes at most `60`
        points), plus a residency bonus of `10` if the patron's `residency` is
        `ON_CAMPUS`, minus a decline penalty of `15` multiplied by the entry's
        `decline_count`."
        PRD §3.5.2: "The system immediately runs the waitlist offer selector
        on the freed allocation — the same selection logic as an explicit
        offer round — so a freed seat cascades into fresh offers without admin
        action."

        Design: Difficulty/combinatorial_formula/waitlist_priority_score_offer_ordering
        """
        ctx = self._setup()
        cancel_permit(ctx["occupier_permit"]["id"])  # auto-offer at 2026-08-21
        # S: 80 + min(20, 30) * 2 = 120; T: 60 + min(15, 30) * 2 = 90.
        s_entry = get_waitlist_entry(ctx["s_entry"]["id"])
        t_entry = get_waitlist_entry(ctx["t_entry"]["id"])
        assert s_entry["status"] == "OFFERED", (
            f"highest-scored S must be promoted, got {s_entry['status']}"
        )
        assert t_entry["status"] == "WAITING", (
            f"the single freed seat cannot promote T too, got {t_entry['status']}"
        )

    def test_decline_penalty_flips_offer_ordering(self, api, admin_headers):
        """PRD §3.4.3: "If `requeue_count` is strictly less than `2`, the
        entry requeues: `requeue_count` increments by `1`, `decline_count`
        increments by `1`, `waiting_since` resets to the current logical time
        (the wait clock restarts), `offered_at` and `offer_expires_at` are
        cleared, and the entry returns to `WAITING`."
        PRD §3.4.1: "First, any `OFFERED` entries whose `offer_expires_at` is
        strictly before the current logical time are swept: each transitions
        `OFFERED → EXPIRED`, decrements `offers_outstanding` by `1`, and
        immediately requeues per the requeue policy below."

        Design: Difficulty/combinatorial_formula/waitlist_priority_score_offer_ordering
        """
        ctx = self._setup()
        cancel_permit(ctx["occupier_permit"]["id"])  # S OFFERED at 2026-08-21
        set_clock("2026-08-24T01:00:00Z")  # past S's 72h offer expiry
        api.extend_offers(ctx["allocation"]["id"], admin_headers)

        s_entry = get_waitlist_entry(ctx["s_entry"]["id"])
        t_entry = get_waitlist_entry(ctx["t_entry"]["id"])
        # After requeue: S = 80 + 0 - 15 = 65; T = 60 + 18 * 2 = 96 -> T wins.
        assert s_entry["status"] == "WAITING", (
            f"S's expired offer requeues to WAITING, got {s_entry['status']}"
        )
        assert s_entry["decline_count"] == 1, (
            f"the expired offer adds one decline, got {s_entry['decline_count']}"
        )
        assert s_entry["requeue_count"] == 1, (
            f"first requeue, got {s_entry['requeue_count']}"
        )
        assert t_entry["status"] == "OFFERED", (
            f"T's higher score (96 vs 65) wins the freed seat, got {t_entry['status']}"
        )


class TestOfferExpiryRequeueCycle:
    """One WAITING entry W on a quota-1 allocation; repeated offer rounds past
    each 72h expiry drive the bounded requeue loop."""

    def _setup(self):
        return setup_offered_entry(waiter_name="W", lot_code="LC")

    def test_offer_expiry_requeues_entry(self, api, admin_headers):
        """PRD §3.4.3: "If `requeue_count` is strictly less than `2`, the
        entry requeues: `requeue_count` increments by `1`, `decline_count`
        increments by `1`, `waiting_since` resets to the current logical time
        (the wait clock restarts), `offered_at` and `offer_expires_at` are
        cleared, and the entry returns to `WAITING`."

        Design: Difficulty/non_linear_state_machine/waitlist_entry_offer_expiry_requeue_cycle
        """
        ctx = self._setup()
        alloc_id = ctx["allocation"]["id"]
        entry_id = ctx["entry"]["id"]
        # W offered at 2026-08-01T00:00:00Z, expires 2026-08-04T00:00:00Z.
        set_clock("2026-08-04T00:00:01Z")
        api.extend_offers(alloc_id, admin_headers)
        entry = get_waitlist_entry(entry_id)
        assert entry["status"] == "OFFERED", (
            f"sole candidate is re-offered right after requeue, got {entry['status']}"
        )
        assert entry["requeue_count"] == 1, f"got {entry['requeue_count']}"

        # Second offer expires 2026-08-07T00:00:01Z.
        set_clock("2026-08-07T00:00:02Z")
        api.extend_offers(alloc_id, admin_headers)
        entry = get_waitlist_entry(entry_id)
        assert entry["status"] == "OFFERED", (
            f"second requeue is still allowed, got {entry['status']}"
        )
        assert entry["requeue_count"] == 2, f"got {entry['requeue_count']}"

    def test_third_expiry_terminates_entry_withdrawn(self, api, admin_headers):
        """PRD §3.4.3: "If `requeue_count` equals `2`, the entry transitions
        to `WITHDRAWN` (terminal) and `decline_count` increments by `1`."

        Design: Difficulty/non_linear_state_machine/waitlist_entry_offer_expiry_requeue_cycle
        """
        ctx = self._setup()
        alloc_id = ctx["allocation"]["id"]
        entry_id = ctx["entry"]["id"]
        set_clock("2026-08-04T00:00:01Z")
        api.extend_offers(alloc_id, admin_headers)
        set_clock("2026-08-07T00:00:02Z")
        api.extend_offers(alloc_id, admin_headers)
        # Third offer expires 2026-08-10T00:00:02Z.
        set_clock("2026-08-10T00:00:03Z")
        api.extend_offers(alloc_id, admin_headers)

        entry = get_waitlist_entry(entry_id)
        assert entry["status"] == "WITHDRAWN", (
            f"requeue_count 2 == the cap terminates the entry, got {entry['status']}"
        )
        assert entry["decline_count"] == 3, (
            f"each expiry adds a decline, got {entry['decline_count']}"
        )
        assert entry["requeue_count"] == 2


class TestClaimExecution:
    def test_claim_offer_at_exact_expiry_succeeds(self, api):
        """PRD §3.4.2: "The current logical time must be at or before
        `offer_expires_at`; if it is strictly later, the request is rejected
        with `ERR_OFFER_EXPIRED` (HTTP 422) and the entry first transitions
        `OFFERED → EXPIRED` and immediately requeues per the requeue policy."

        Design: Corner/calculations/claim_offer_at_exact_expiry_succeeds
        """
        ctx = setup_offered_entry(waiter_name="W", lot_code="LW")
        # Offered at 2026-08-01T00:00:00Z -> offer_expires_at 2026-08-04T00:00:00Z.
        set_clock("2026-08-04T00:00:00Z")  # exactly at the expiry instant
        version = get_allocation_version(ctx["allocation"]["id"])
        resp = api.claim_waitlist_entry(
            ctx["entry"]["id"],
            {"expected_allocation_version": version},
            make_commuter_headers(ctx["waiter"]["id"]),
        )
        permit = validate_success(resp, 201)
        assert permit["status"] == "ACTIVE"
        # valid_from defaults to 2026-08-04 -> 111 remaining days -> 16 weeks.
        assert permit["fee_total_cents"] == 84000, (
            f"full 16-week fee expected, got {permit['fee_total_cents']}"
        )
        entry = get_waitlist_entry(ctx["entry"]["id"])
        assert entry["status"] == "CLAIMED", (
            f"claim at exactly the expiry instant is allowed, got {entry['status']}"
        )

    def test_claim_creates_permit_and_settles_counts(self, api, admin_headers):
        """PRD §3.4.2: "On a successful claim, a permit is created on the
        entry's allocation with the fee computed per the proration rules of
        §3.3, `valid_from` defaulting to the later of the current logical date
        and `term_start`, and `valid_to` set to `term_end`. The entry
        transitions to `CLAIMED` (terminal). The allocation's
        `offers_outstanding` decrements by `1` and `allocated_count`
        increments by `1`; the allocation's status is re-evaluated and its
        `version` increments."

        Design: Corner/endpoints/claim_creates_permit_and_settles_counts
        """
        ctx = setup_offered_entry(waiter_name="W", lot_code="LW")
        version = get_allocation_version(ctx["allocation"]["id"])
        resp = api.claim_waitlist_entry(
            ctx["entry"]["id"],
            {"expected_allocation_version": version},
            make_commuter_headers(ctx["waiter"]["id"]),
        )
        permit = validate_success(resp, 201)
        # Clock still 2026-08-01 < term_start 2026-08-03 -> full-term fee.
        assert permit["status"] == "ACTIVE"
        assert permit["fee_total_cents"] == 84000, (
            f"full-term claim fee must be 84000, got {permit['fee_total_cents']}"
        )
        assert permit["allocation_id"] == ctx["allocation"]["id"]

        entry = get_waitlist_entry(ctx["entry"]["id"])
        assert entry["status"] == "CLAIMED"

        allocation = get_allocation(ctx["allocation"]["id"])
        assert allocation["allocated_count"] == 1
        assert allocation["offers_outstanding"] == 0
        assert allocation["status"] == "WAITLISTING", (
            f"1 + 0 >= quota 1 keeps the allocation WAITLISTING, got {allocation['status']}"
        )


class TestExpiredClaimMasksBlocked:
    """Z holds an OFFERED entry; Z is BLOCKED (escalated unpaid citation); the
    offer is past its 72h TTL at claim time."""

    def _setup(self):
        occ = create_patron(full_name="Occ", campus_role="STAFF",
                            residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        z_ctx = setup_blocked_patron(name="Z", plate="Z888")
        # quota-1 allocation on the violation lot; occ fills it, Z queues,
        # occ cancels -> Z's entry is OFFERED at the default clock.
        lot_b = z_ctx["violation_lot"]
        alloc_b = create_allocation(lot_b["id"], permit_code="GEN2",
                                    eligible_roles=["STAFF"], quota=1)
        occ_permit = purchase_permit(occ["id"], alloc_b["id"], "O222")
        z_entry = join_waitlist(z_ctx["patron"]["id"], alloc_b["id"])
        cancel_permit(occ_permit["id"])  # auto-offer at 2026-08-01T00:00:00Z
        set_clock("2026-08-04T00:00:01Z")  # strictly past offer_expires_at
        z_ctx.update({"alloc_b": alloc_b, "z_entry": z_entry})
        return z_ctx

    def test_claim_expired_offer_beats_blocked_patron_error(self, api):
        """PRD §2.8: "Every write endpoint evaluates checks in a fixed
        priority order. A failure at an earlier tier masks later checks (the
        earlier error is the one returned)" — with "9. **Temporal conflicts**
        — closure overlap, plate double-booking, fleet window buffer, offer
        expiry, `valid_from` within term." preceding "12. **Capacity &
        fiscal** — patron standing, credit balance, displacement capacity,
        route funding and seat coverage, redemption points. Fiscal checks
        always run after state and temporal checks."
        PRD §3.4.2: "The current logical time must be at or before
        `offer_expires_at`; if it is strictly later, the request is rejected
        with `ERR_OFFER_EXPIRED` (HTTP 422) and the entry first transitions
        `OFFERED → EXPIRED` and immediately requeues per the requeue policy."

        Design: Difficulty/priority_pair_validation_conflict/claim_offer_expired_vs_patron_blocked
        """
        ctx = self._setup()
        assert ctx["unpaid_citation"]["fine_amount_cents"] == 11250, (
            "the escalated unpaid citation must be 11250 so Z is BLOCKED"
        )
        version = get_allocation_version(ctx["alloc_b"]["id"])
        resp = api.claim_waitlist_entry(
            ctx["z_entry"]["id"],
            {"expected_allocation_version": version},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED, 422)

    def test_expired_claim_requeues_entry_despite_rejection(self, api):
        """PRD §3.4.2: "if it is strictly later, the request is rejected with
        `ERR_OFFER_EXPIRED` (HTTP 422) and the entry first transitions
        `OFFERED → EXPIRED` and immediately requeues per the requeue policy."
        PRD §3.4.3: "If `requeue_count` is strictly less than `2`, the entry
        requeues: `requeue_count` increments by `1`, `decline_count`
        increments by `1`, `waiting_since` resets to the current logical time
        (the wait clock restarts), `offered_at` and `offer_expires_at` are
        cleared, and the entry returns to `WAITING`."

        Design: Difficulty/priority_pair_validation_conflict/claim_offer_expired_vs_patron_blocked
        """
        ctx = self._setup()
        version = get_allocation_version(ctx["alloc_b"]["id"])
        resp = api.claim_waitlist_entry(
            ctx["z_entry"]["id"],
            {"expected_allocation_version": version},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED, 422)
        entry = get_waitlist_entry(ctx["z_entry"]["id"])
        assert entry["status"] == "WAITING", (
            f"the failed claim still ran the lazy expiry requeue, got {entry['status']}"
        )
        assert entry["requeue_count"] == 1, f"got {entry['requeue_count']}"


class TestExtendOffersNoOp:
    def test_extend_offers_empty_pool_succeeds_as_noop(self, api, admin_headers):
        """PRD §3.4.1: "Then, if the free-seat count (computed as `quota`
        minus `allocated_count` minus `offers_outstanding`) is greater than
        zero, the system ranks all `WAITING` entries on the allocation by
        `waitlist_priority_score` descending, tie-broken by `waiting_since`
        ascending (earliest waiter first), and promotes at most that many
        entries to `OFFERED`."
        PRD §4: "New resources are returned with HTTP `201`; modifications and
        retrievals return HTTP `200`."

        Design: Corner/endpoints/extend_offers_empty_pool_returns_zero
        """
        ctx = setup_full_allocation(lot_code="LE")  # WAITLISTING, zero entries
        resp = api.extend_offers(ctx["allocation"]["id"], admin_headers)
        validate_success(resp, 200)
        allocation = get_allocation(ctx["allocation"]["id"])
        assert allocation["allocated_count"] == 1
        assert allocation["offers_outstanding"] == 0, (
            "an empty candidate pool promotes nobody"
        )
        assert allocation["status"] == "WAITLISTING"
