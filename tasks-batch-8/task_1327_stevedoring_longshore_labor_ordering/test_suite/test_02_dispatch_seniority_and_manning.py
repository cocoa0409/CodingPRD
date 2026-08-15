"""Labor-hall dispatch: seniority ranking, manning derivation, bumps and refills."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    amend_gang,
    berth_vessel,
    check_in,
    create_shift,
    create_vessel,
    dispatch_batch,
    get_assignment,
    get_gang,
    get_worker,
    list_assignments,
    open_shift,
    place_gang,
    register_worker,
    run_dispatch,
    set_worker_status,
    setup_dispatched_gang,
    setup_placed_gang,
    start_shift,
    validate_error,
    validate_paginated,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]

HOLDMAN_SPECS_3 = [
    {"full_name": "W One", "registration_number": "R001",
     "classification": "HOLDMAN", "registered_on": "2010-01-01",
     "base_hourly_rate_cents": 4000},
    {"full_name": "W Two", "registration_number": "R002",
     "classification": "HOLDMAN", "registered_on": "2015-06-01",
     "base_hourly_rate_cents": 4000},
    {"full_name": "W Three", "registration_number": "R003",
     "classification": "HOLDMAN", "registered_on": "2020-03-01",
     "base_hourly_rate_cents": 4000},
]


class TestSeniorityDispatchOrder:

    def test_seniority_rank_orders_offers_by_registration_date(self, api):
        """PRD §3.3: "A new worker is born `ACTIVE`, and the server immediately computes `seniority_rank`: within each classification, all workers regardless of status are ordered by `registered_on` ascending — earlier registration means more senior — with ties broken by the worker's `created_at` ascending, and the one-based position is the rank."
        PRD §3.3: "Eligible candidates are ranked by `seniority_rank` ascending — the most senior first — with ties broken by worker `created_at` ascending; the selection is deterministic and involves no randomness."
        PRD §2.3: "When several items are created within a single request — for example, a dispatch batch that creates several `OFFERED` assignments in one call — their creation sequence follows the producing rule's ranking order (for dispatch, the selector's seniority ranking), and that creation sequence serves as the secondary order whenever `created_at` values tie."

        Design: Corner/calculations/seniority_rank_orders_offers_by_registration_date
        """
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV Senior", "voyage_number": "C-201"},
            gang_overrides={"required_headcount": 2},
            worker_specs=HOLDMAN_SPECS_3)
        w1, w2, w3 = ns.workers

        assert get_worker(w1["id"])["seniority_rank"] == 1
        assert get_worker(w2["id"])["seniority_rank"] == 2
        assert get_worker(w3["id"])["seniority_rank"] == 3

        offers = ns.assignments
        assert len(offers) == 2
        assert [a["worker_id"] for a in offers] == [w1["id"], w2["id"]], (
            "offers must go to the two most senior workers in rank order")
        for a in offers:
            assert a["status"] == "OFFERED"
        assert offers[0]["seniority_rank_at_dispatch"] == 1
        assert offers[1]["seniority_rank_at_dispatch"] == 2

        w3_rows, _meta = validate_paginated(
            api.list_dispatch_assignments(DISP, params={"worker_id": w3["id"]}))
        assert len(w3_rows) == 0, "least-senior worker must not be offered"

        gang = get_gang(ns.gang["id"])
        assert gang["offered_count"] == 2
        assert gang["status"] == "DISPATCHING"

    def test_seniority_tie_break_uses_created_at(self, api):
        """PRD §3.3: "within each classification, all workers regardless of status are ordered by `registered_on` ascending — earlier registration means more senior — with ties broken by the worker's `created_at` ascending, and the one-based position is the rank."

        Design: Corner/calculations/seniority_tie_break_uses_created_at
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Tie", "voyage_number": "C-202"},
            gang_overrides={"required_headcount": 1})
        wa = register_worker(full_name="W Alpha", registration_number="R101",
                             classification="HOLDMAN", registered_on="2012-01-01",
                             base_hourly_rate_cents=4000)
        wb = register_worker(full_name="W Beta", registration_number="R102",
                             classification="HOLDMAN", registered_on="2012-01-01",
                             base_hourly_rate_cents=4000)

        assert get_worker(wa["id"])["seniority_rank"] == 1
        assert get_worker(wb["id"])["seniority_rank"] == 2

        run_dispatch(ns.gang["id"])
        offers = list_assignments(gang_order_id=ns.gang["id"])
        assert len(offers) == 1
        assert offers[0]["worker_id"] == wa["id"], (
            "the worker created earlier in the system wins the registered_on tie")


class TestDispatchPoolExhaustion:

    def test_dispatch_with_insufficient_pool_marks_short_manned(self, api):
        """PRD §3.3: "When the pool runs dry, nothing is created."
        PRD §3.3: "The first batch moves the order out of `PLACED`; afterwards, if the filled plus offered counts cover the requirement the order stands in `DISPATCHING`, and otherwise it falls to `SHORT_MANNED`."

        Design: Corner/calculations/dispatch_with_insufficient_pool_marks_short_manned
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Short", "voyage_number": "C-203"},
            gang_overrides={"required_classification": "CLERK",
                            "required_headcount": 2})
        register_worker(full_name="Clerk One", registration_number="R201",
                        classification="CLERK", registered_on="2010-01-01",
                        base_hourly_rate_cents=3900)

        gang = run_dispatch(ns.gang["id"])
        assert gang["offered_count"] == 1, "the single eligible CLERK is offered"
        assert gang["filled_headcount"] == 0
        assert gang["status"] == "SHORT_MANNED", (
            "filled 0 + offered 1 < required 2: pool exhaustion is a state, not an error")


class TestWorkerShiftOverlap:

    def _setup_three_shift_vessel(self):
        vessel = create_vessel(vessel_name="MV Overlap", voyage_number="O-401")
        berth_vessel(vessel["id"])
        s1 = create_shift(vessel["id"], period="DAY",
                          start_utc="2026-08-10T08:00:00Z",
                          end_utc="2026-08-10T16:00:00Z")
        s2 = create_shift(vessel["id"], period="NIGHT",
                          start_utc="2026-08-10T16:00:00Z",
                          end_utc="2026-08-10T23:00:00Z")
        s3 = create_shift(vessel["id"], period="NIGHT",
                          start_utc="2026-08-10T15:00:00Z",
                          end_utc="2026-08-10T20:00:00Z")
        for s in (s1, s2, s3):
            open_shift(s["id"])
        g1 = place_gang(s1["id"], required_headcount=1)
        g2 = place_gang(s2["id"], required_headcount=1)
        g3 = place_gang(s3["id"], required_headcount=1)
        w1 = register_worker(full_name="W One", registration_number="R001",
                             classification="HOLDMAN", registered_on="2010-01-01",
                             base_hourly_rate_cents=4000)
        return g1, g2, g3, w1

    def test_worker_half_open_adjacency_allows_back_to_back_offers(self, api):
        """PRD §2.8: "Every interval in the system is half-open: the start instant belongs to the interval and the end instant does not. Adjacency therefore never counts as overlap — a booking or shift that ends exactly when another begins touches it without conflicting — and this holds uniformly for the worker double-booking check, the move-record period check, and equipment bookings."

        Design: Difficulty/resource_temporal_overlap/worker_half_open_shift_overlap_adjacency_allowed
        """
        g1, g2, _g3, w1 = self._setup_three_shift_vessel()
        run_dispatch(g1["id"])  # 08:00-16:00
        run_dispatch(g2["id"])  # 16:00-23:00: adjacent to g1's shift

        rows, meta = validate_paginated(
            api.list_dispatch_assignments(DISP, params={"worker_id": w1["id"]}))
        assert meta["total_count"] == 2
        assert all(a["status"] == "OFFERED" for a in rows), (
            "the 16:00 end / 16:00 start seam is adjacency, not overlap")
        assert {a["gang_order_id"] for a in rows} == {g1["id"], g2["id"]}

    def test_worker_overlapping_shift_forced_dispatch_double_booked(self, api):
        """PRD §3.3: "the worker must hold no assignment in `OFFERED`, `CHECKED_IN`, or `WORKING` on a different gang order whose shift window overlaps this order's shift window under half-open semantics (adjacent shifts do not overlap)."
        PRD §3.3: "When a forced list is present, a listed worker who fails eligibility is not silently skipped: the batch is rejected with `ERR_WORKER_INELIGIBLE` (409), or with `ERR_WORKER_DOUBLE_BOOKED` (409) when the cross-gang overlap clause is the only clause that worker fails."

        Design: Difficulty/resource_temporal_overlap/worker_half_open_shift_overlap_adjacency_allowed
        """
        g1, g2, g3, w1 = self._setup_three_shift_vessel()
        run_dispatch(g1["id"])
        run_dispatch(g2["id"])

        # g3's shift (15:00-20:00) overlaps both existing assignments' shifts.
        resp = dispatch_batch(g3["id"], worker_ids=[w1["id"]])
        validate_error(resp, ApiErrorId.ERR_WORKER_DOUBLE_BOOKED)
        g3_after = get_gang(g3["id"])
        assert g3_after["status"] == "PLACED"
        assert g3_after["offered_count"] == 0


class TestBumpAndRefill:

    def _setup_checked_in_gang(self):
        """Headcount-1 gang, W1 CHECKED_IN (MANNED), W2 still eligible."""
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV Invariant", "voyage_number": "I-501"},
            gang_overrides={"required_headcount": 1})
        start_shift(ns.shift["id"])
        check_in(ns.assignments[0]["id"])
        return ns

    def test_bump_of_checked_in_worker_auto_offers_next_eligible(self, api):
        """PRD §3.3: "Bumping works the same way from either `OFFERED` or `CHECKED_IN`: the assignment becomes `BUMPED`, a single-slot auto-offer goes to the next eligible candidate with the bumped worker excluded, and the manning recomputes — a bump from `CHECKED_IN` drops the filled count by one, so a `MANNED` order may regress to `DISPATCHING`, or to `SHORT_MANNED` when the pool is exhausted."
        PRD §3.3: "the worker must hold no assignment on this same gang order in any of `OFFERED`, `CHECKED_IN`, `WORKING`, `NO_SHOW`, or `BUMPED` status — a worker who no-showed or was bumped off this order is never re-offered it"

        Design: Difficulty/compensating_invariant/bump_plus_refill_restores_filled_headcount
        """
        ns = self._setup_checked_in_gang()
        a1 = ns.assignments[0]
        w1, w2 = ns.workers
        gang = get_gang(ns.gang["id"])
        assert gang["filled_headcount"] == 1
        assert gang["status"] == "MANNED"

        resp = api.bump_assignment(a1["id"], DISP)
        validate_success(resp)
        assert get_assignment(a1["id"])["status"] == "BUMPED"

        gang = get_gang(ns.gang["id"])
        assert gang["filled_headcount"] == 0, "bump from CHECKED_IN drops filled by one"

        rows = list_assignments(gang_order_id=ns.gang["id"])
        assert len(rows) == 2
        replacement = rows[1]
        assert replacement["status"] == "OFFERED"
        assert replacement["worker_id"] == w2["id"], (
            "auto-offer goes to the next eligible candidate; the bumped worker "
            "is excluded from the refill pool")
        assert replacement["worker_id"] != w1["id"]

    def test_replacement_checkin_restores_filled_headcount(self, api):
        """PRD §3.3: "Each successful check-in recomputes `filled_headcount`, and when it reaches the requirement the order advances automatically from `DISPATCHING` or `SHORT_MANNED` to `MANNED`."
        PRD §2.9: "On a gang order, `filled_headcount` recounts the assignments in `CHECKED_IN` or `WORKING` status and `offered_count` recounts those in `OFFERED` on every assignment status change"

        Design: Difficulty/compensating_invariant/bump_plus_refill_restores_filled_headcount
        """
        ns = self._setup_checked_in_gang()
        a1 = ns.assignments[0]

        api.bump_assignment(a1["id"], DISP)
        rows = list_assignments(gang_order_id=ns.gang["id"])
        replacement = rows[1]

        check_in(replacement["id"])
        gang = get_gang(ns.gang["id"])
        assert gang["filled_headcount"] == 1, (
            "forward bump + compensating refill conserve filled_headcount")
        assert gang["status"] == "MANNED"


class TestNoShowRetry:

    def test_no_show_retry_excludes_the_no_show_worker(self, api):
        """PRD §3.3: "Marking an offered assignment as no-show (`OFFERED` → `NO_SHOW`) requires the shift to be `IN_PROGRESS` and triggers a single-slot auto-offer: the selection runs again for one slot with the no-show worker excluded from this order's candidate pool, creating one new `OFFERED` assignment when a candidate exists, and the order's manning recomputes."

        Design: Corner/cross_cutting_complexity_layers/no_show_retry_excludes_the_no_show_worker
        """
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV NoShow", "voyage_number": "X-605"},
            gang_overrides={"required_headcount": 1})
        start_shift(ns.shift["id"])
        a1 = ns.assignments[0]
        _w1, w2 = ns.workers

        resp = api.mark_no_show(a1["id"], DISP)
        validate_success(resp)
        assert get_assignment(a1["id"])["status"] == "NO_SHOW"

        rows = list_assignments(gang_order_id=ns.gang["id"])
        assert len(rows) == 2, "one replacement offer is auto-created"
        replacement = rows[1]
        assert replacement["worker_id"] == w2["id"]
        assert replacement["status"] == "OFFERED"

        gang = get_gang(ns.gang["id"])
        assert gang["offered_count"] == 1
        assert gang["filled_headcount"] == 0


class TestForcedDispatchEligibility:

    def test_forced_dispatch_of_suspended_worker_returns_ineligible(self, api):
        """PRD §3.3: "Eligibility is then evaluated per worker: the worker must be `ACTIVE`; the worker's `classification` must equal the order's `required_classification`; the worker must hold no assignment on this same gang order in any of `OFFERED`, `CHECKED_IN`, `WORKING`, `NO_SHOW`, or `BUMPED` status — a worker who no-showed or was bumped off this order is never re-offered it; and the worker must hold no assignment in `OFFERED`, `CHECKED_IN`, or `WORKING` on a different gang order whose shift window overlaps this order's shift window under half-open semantics (adjacent shifts do not overlap)."
        PRD §3.3: "When a forced list is present, a listed worker who fails eligibility is not silently skipped: the batch is rejected with `ERR_WORKER_INELIGIBLE` (409), or with `ERR_WORKER_DOUBLE_BOOKED` (409) when the cross-gang overlap clause is the only clause that worker fails."

        Design: Corner/validations/forced_dispatch_of_suspended_worker_returns_ineligible
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Inelig", "voyage_number": "V-310"},
            gang_overrides={"required_headcount": 1})
        w1 = register_worker(full_name="W One", registration_number="R001",
                             classification="HOLDMAN", registered_on="2010-01-01",
                             base_hourly_rate_cents=4000)
        resp = set_worker_status(w1["id"], "SUSPENDED", w1["version"])
        validate_success(resp)

        batch = dispatch_batch(ns.gang["id"], worker_ids=[w1["id"]])
        validate_error(batch, ApiErrorId.ERR_WORKER_INELIGIBLE)

        gang = get_gang(ns.gang["id"])
        assert gang["offered_count"] == 0
        assert gang["status"] == "PLACED"


class TestAmendmentBumpWaterfall:

    def test_amendment_reduction_bumps_least_senior_first(self, api):
        """PRD §3.2: "When an amendment reduces `required_headcount` below the current `filled_headcount`, a bump waterfall runs: checked-in and working assignments are bumped starting from the least senior — the highest `seniority_rank_at_dispatch` value first, ties broken by the assignment's `created_at` descending so the most recently created goes first — until the filled count equals the new requirement. Amendment-driven bumps never trigger a replacement offer, because headcount is being deliberately reduced."

        Design: Corner/cross_cutting_complexity_layers/amendment_reduction_bumps_least_senior_first
        """
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV Amend", "voyage_number": "X-606"},
            gang_overrides={"required_headcount": 2})
        start_shift(ns.shift["id"])
        a1, a2 = ns.assignments[0], ns.assignments[1]
        check_in(a1["id"])
        check_in(a2["id"])
        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "MANNED"
        assert gang["filled_headcount"] == 2

        resp = amend_gang(gang["id"], gang["version"], required_headcount=1)
        amended = validate_success(resp)
        assert amended["required_headcount"] == 1
        assert amended["filled_headcount"] == 1
        assert amended["status"] == "MANNED"
        assert amended["offered_count"] == 0

        # a2 was offered second -> seniority_rank_at_dispatch 2 -> bumped first.
        assert get_assignment(a2["id"])["status"] == "BUMPED"
        assert get_assignment(a1["id"])["status"] == "CHECKED_IN"

        rows = list_assignments(gang_order_id=gang["id"])
        assert len(rows) == 2, "amendment bumps never trigger a replacement offer"


class TestGangFullCheckinBoundary:

    def _setup_amended_to_full_gang(self):
        """Gang headcount 2 -> W1 checked in -> amendment cuts headcount to 1,
        leaving W2's OFFERED assignment outstanding."""
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV Full", "voyage_number": "B-203"},
            gang_overrides={"required_headcount": 2})
        start_shift(ns.shift["id"])
        a1, a2 = ns.assignments[0], ns.assignments[1]
        check_in(a1["id"])
        gang = get_gang(ns.gang["id"])
        amended = amend_gang(gang["id"], gang["version"], required_headcount=1)
        validate_success(amended)
        return ns, a2

    def test_checkin_rejected_exactly_at_full_headcount(self, api):
        """PRD §3.3: "Checking in an offered worker moves the assignment `OFFERED` → `CHECKED_IN`; it requires the shift to be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), the posture to be other than `FULL_STOPPAGE` (otherwise `ERR_WORK_STOPPAGE_ACTIVE`), the worker to still be `ACTIVE` (otherwise `ERR_WORKER_INELIGIBLE`), and the gang to have an open slot — when `filled_headcount` already equals `required_headcount` the check-in is rejected with `ERR_GANG_FULL` (409)."

        Design: Difficulty/boundary_precision_check/checkin_rejected_exactly_at_full_headcount
        """
        ns, a2 = self._setup_amended_to_full_gang()
        gang = get_gang(ns.gang["id"])
        assert gang["filled_headcount"] == 1
        assert gang["required_headcount"] == 1, (
            "setup: filled == required exactly (zero remaining slots)")

        resp = api.check_in_assignment(a2["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_GANG_FULL)

    def test_gang_full_rejection_preserves_offered_assignment(self, api):
        """PRD §3.2: "Outstanding `OFFERED` assignments are not cancelled by an amendment; they are turned away later at check-in time with `ERR_GANG_FULL` when the gang is already full."

        Design: Difficulty/boundary_precision_check/checkin_rejected_exactly_at_full_headcount
        """
        ns, a2 = self._setup_amended_to_full_gang()

        resp = api.check_in_assignment(a2["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_GANG_FULL)

        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "MANNED"
        assert gang["filled_headcount"] == 1
        assert get_assignment(a2["id"])["status"] == "OFFERED", (
            "the bounced offer is not cancelled by the rejection")
