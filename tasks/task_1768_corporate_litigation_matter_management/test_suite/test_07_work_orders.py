"""Discovery work orders: cost tiers, hold gating, capacity, temporal windows,
and posture gates."""
from test_helpers import (
    TEST_USERS,
    add_hold,
    add_vendor,
    create_and_authorize_work_order,
    create_deadline,
    create_work_order,
    get_success_data,
    make_dgc_headers,
    setup_active_matter,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId, Posture, WorkOrderStatus

OPS = TEST_USERS["ops_headers"]


class TestWorkOrderCostTiers:
    def test_work_order_provisional_cost_at_create(self, api):
        """PRD §3.6: "At creation the server computes the provisional
        `estimated_cost_cents` using marginal per-tier pricing: the first 100 GB bill
        at the full negotiated rate; the next 400 GB — gigabytes 101 through 500 —
        bill at 80 percent of that rate; any volume beyond 500 GB bills at 60 percent."

        Design: Difficulty/dual_variant_calc/work_order_cost_provisional_vs_final_variant
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=600,
                               rate_per_gb_cents=1000)
        # 100*1000 + floor(400*1000*80/100) + floor(100*1000*60/100) = 480,000
        assert wo["estimated_cost_cents"] == 480_000, (
            f"provisional tiered cost for 600 GB @ 1000 must be 480000, "
            f"got {wo['estimated_cost_cents']}")

    def test_work_order_final_cost_uses_actual_volume(self, api):
        """PRD §3.6: "Completion (`IN_PROGRESS` → `COMPLETED`) takes the `actual_gb`
        processed, which must be zero or greater, releases the estimated capacity back
        to the vendor, and recomputes the final cost: when `actual_gb` is greater than
        zero the tiered calculation runs on the actual volume; when it is exactly zero
        the provisional estimate stands, there being no cost basis."

        Design: Difficulty/dual_variant_calc/work_order_cost_provisional_vs_final_variant
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                             estimated_gb=600, rate_per_gb_cents=1000)
        get_success_data(api.set_clock("2026-08-10T00:00:00Z", OPS))
        get_success_data(api.start_work_order(wo["id"], OPS))
        completed = validate_success(api.complete_work_order(wo["id"], 450, OPS))
        # final variant on 450 GB: 100*1000 + floor(350*1000*80/100) = 380,000
        assert completed["estimated_cost_cents"] == 380_000, (
            f"final cost on actual_gb=450 must be 380000, "
            f"got {completed['estimated_cost_cents']}")
        assert completed["estimated_cost_cents"] != 480_000

    def test_work_order_cost_per_tier_floor_102gb(self, api):
        """PRD §2.5: "Where a calculation applies a discounted rate tier by tier — the
        vendor work-order cost is the one such calculation — floor division is applied
        per tier before the tier subtotals are summed, never once at the end."

        Design: Difficulty/combinatorial_formula/work_order_cost_per_tier_floor_rounding_order
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=500)
        wo = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=102,
                               rate_per_gb_cents=1013, service_type="PROCESSING")
        # 100*1013 + floor(2*1013*80/100) = 101,300 + 1,620 = 102,920
        assert wo["estimated_cost_cents"] == 102_920, (
            f"per-tier floor must yield 102920 (round-half-up-per-tier would give "
            f"102921), got {wo['estimated_cost_cents']}")

    def test_work_order_cost_per_tier_floor_501gb(self, api):
        """PRD §2.5: "Where a calculation applies a discounted rate tier by tier — the
        vendor work-order cost is the one such calculation — floor division is applied
        per tier before the tier subtotals are summed, never once at the end."
        PRD §3.6: "the first 100 GB bill at the full negotiated rate; the next 400 GB
        — gigabytes 101 through 500 — bill at 80 percent of that rate; any volume
        beyond 500 GB bills at 60 percent."

        Design: Difficulty/combinatorial_formula/work_order_cost_per_tier_floor_rounding_order
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=501,
                               rate_per_gb_cents=1013, service_type="PROCESSING")
        # 101,300 + floor(400*1013*80/100) + floor(1*1013*60/100)
        # = 101,300 + 324,160 + 607 = 426,067
        assert wo["estimated_cost_cents"] == 426_067, (
            f"per-tier floor must yield 426067 (rounding tier C up would give "
            f"426068), got {wo['estimated_cost_cents']}")


class TestWorkOrderHoldGate:
    def test_authorize_blocked_when_hold_not_issued(self, api):
        """PRD §3.6: "The matter must be `ACTIVE` or `REOPENED`; its posture must be
        `OPEN`, since `RESTRICTED` or `FROZEN` blocks new spend authorization with
        `ERR_MATTER_POSTURE_FROZEN`; the hold must be `ISSUED` or `ACKNOWLEDGED`; the
        vendor must be active."
        PRD §2.10: "A reference that exists but belongs to a different matter — or, in
        the work-order case, a hold of the right matter that is not in `ISSUED` or
        `ACKNOWLEDGED` — is rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/work_order_authorize_requires_hold_issued
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=100)
        # DRAFT orders do not pin the hold, so the hold can be released, leaving the
        # order pointing at a hold no longer in ISSUED/ACKNOWLEDGED.
        get_success_data(api.release_hold(hold["id"], "SCOPE_NARROWED", ctx["counsel"]))

        resp = api.authorize_work_order(wo["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)
        current = get_success_data(api.get_work_order(wo["id"], OPS))
        assert current["status"] == WorkOrderStatus.DRAFT.value

    def test_authorize_succeeds_with_issued_hold_and_debits_capacity(self, api):
        """PRD §3.6: "Authorization debits capacity (`committed_gb` grows by
        `estimated_gb`), recomputes the estimated cost, and increments the order's
        `version`."
        PRD §3.6: "the hold must be `ISSUED` or `ACKNOWLEDGED`"

        Design: Difficulty/cross_entity_state_dependency/work_order_authorize_requires_hold_issued
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=100)

        authorized = validate_success(api.authorize_work_order(wo["id"], OPS))
        assert authorized["status"] == WorkOrderStatus.AUTHORIZED.value
        vendor_after = get_success_data(api.get_vendor(vendor["id"], OPS))
        assert vendor_after["committed_gb"] == 100


class TestVendorCapacity:
    def test_error_vendor_capacity_exceeded(self, api):
        """PRD §3.6: "Then capacity: `committed_gb` plus the order's `estimated_gb`
        must not exceed the vendor's `capacity_gb`, else `ERR_VENDOR_CAPACITY_EXCEEDED`."

        Design: Corner/errors/error_vendor_capacity_exceeded
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=100)
        create_and_authorize_work_order(ctx, vendor["id"], hold["id"], estimated_gb=60,
                                        scheduled_start="2026-08-10T00:00:00Z",
                                        scheduled_end="2026-08-15T00:00:00Z")
        over = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=41,
                                 service_type="PROCESSING",
                                 scheduled_start="2026-09-01T00:00:00Z",
                                 scheduled_end="2026-09-10T00:00:00Z")
        resp = api.authorize_work_order(over["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)

    def test_authorize_debits_vendor_capacity(self, api):
        """PRD §3.6: "The vendor's `committed_gb` is derived: the sum of
        `estimated_gb` over that vendor's work orders in `AUTHORIZED` or `IN_PROGRESS`
        — `DRAFT`, `COMPLETED`, and `CANCELLED` orders hold no capacity — recomputed
        whenever an order is authorized, completed, or cancelled."
        PRD §3.6: "Authorization debits capacity (`committed_gb` grows by
        `estimated_gb`)"

        Design: Difficulty/compensating_invariant/vendor_capacity_authorize_cancel_conservation
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=500)
        wo = create_work_order(ctx, vendor["id"], hold["id"], estimated_gb=120)
        get_success_data(api.authorize_work_order(wo["id"], OPS))
        vendor_after = get_success_data(api.get_vendor(vendor["id"], OPS))
        assert vendor_after["committed_gb"] == 120

    def test_cancel_releases_vendor_capacity(self, api):
        """PRD §3.6: "Cancellation is reachable from `DRAFT`, `AUTHORIZED`, or
        `IN_PROGRESS`; cancelling an authorized or in-progress order releases its
        capacity debit."

        Design: Difficulty/compensating_invariant/vendor_capacity_authorize_cancel_conservation
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=500)
        wo = create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                             estimated_gb=120)
        assert get_success_data(api.get_vendor(vendor["id"], OPS))["committed_gb"] == 120
        get_success_data(api.cancel_work_order(wo["id"], OPS))
        vendor_after = get_success_data(api.get_vendor(vendor["id"], OPS))
        assert vendor_after["committed_gb"] == 0, \
            "authorize/cancel round trip must restore the vendor's exact prior headroom"


class TestTemporalWindowOverlap:
    def test_adjacent_half_open_window_permitted(self, api):
        """PRD §3.6: "no other work order of the same vendor in `AUTHORIZED` or
        `IN_PROGRESS` may have a window overlapping this order's — windows are
        half-open, so an order ending exactly when another begins is adjacency, not
        conflict — and a clash is `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/work_order_vendor_window_half_open_overlap
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=2000)
        create_and_authorize_work_order(ctx, vendor["id"], hold["id"], estimated_gb=100)
        adjacent = create_work_order(ctx, vendor["id"], hold["id"],
                                     service_type="PROCESSING", estimated_gb=100,
                                     scheduled_start="2026-08-20T00:00:00Z",
                                     scheduled_end="2026-08-30T00:00:00Z")
        authorized = validate_success(api.authorize_work_order(adjacent["id"], OPS))
        assert authorized["status"] == WorkOrderStatus.AUTHORIZED.value, \
            "an order starting exactly when another ends is adjacency, not conflict"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.6: "no other work order of the same vendor in `AUTHORIZED` or
        `IN_PROGRESS` may have a window overlapping this order's — windows are
        half-open, so an order ending exactly when another begins is adjacency, not
        conflict — and a clash is `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/work_order_vendor_window_half_open_overlap
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=2000)
        create_and_authorize_work_order(ctx, vendor["id"], hold["id"], estimated_gb=100)
        overlapping = create_work_order(ctx, vendor["id"], hold["id"],
                                        service_type="REVIEW", estimated_gb=100,
                                        scheduled_start="2026-08-19T00:00:00Z",
                                        scheduled_end="2026-08-25T00:00:00Z")
        resp = api.authorize_work_order(overlapping["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)
        current = get_success_data(api.get_work_order(overlapping["id"], OPS))
        assert current["status"] == WorkOrderStatus.DRAFT.value


class TestPostureAndStartGates:
    def test_authorize_frozen_matter_beats_temporal_conflict(self, api):
        """PRD §2.11: "When a request could fail several checks at once, the server
        evaluates validations in a fixed priority order and reports the first failure
        encountered; clients can rely on this order to understand which problem to fix
        first." The order places "(9) posture gates (`ERR_MATTER_POSTURE_FROZEN`)"
        ahead of "(13) schedule conflicts and cooling periods (`ERR_SCHEDULE_CONFLICT`)".
        PRD §2.9: "a posture of `RESTRICTED` or `FROZEN` blocks work-order
        authorization"

        Design: Difficulty/priority_pair_validation_conflict/work_order_authorize_posture_vs_temporal_priority
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        create_and_authorize_work_order(ctx, vendor["id"], hold["id"], estimated_gb=100)
        # Jurisdictional miss freezes the matter.
        juris = create_deadline(ctx["matter_id"], ctx["counsel_id"],
                                deadline_type="COURT_DEADLINE", title="Answer due",
                                due_at="2026-08-05T00:00:00Z", is_jurisdictional=True)
        get_success_data(api.mark_deadline_missed(juris["id"], ctx["counsel"]))
        frozen = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert frozen["posture"] == Posture.FROZEN.value

        overlapping = create_work_order(ctx, vendor["id"], hold["id"],
                                        service_type="PROCESSING", estimated_gb=100,
                                        scheduled_start="2026-08-15T00:00:00Z",
                                        scheduled_end="2026-08-25T00:00:00Z")
        resp = api.authorize_work_order(overlapping["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_MATTER_POSTURE_FROZEN)
        current = get_success_data(api.get_work_order(overlapping["id"], OPS))
        assert current["status"] == WorkOrderStatus.DRAFT.value

    def test_temporal_conflict_surfaces_after_unfreeze(self, api):
        """PRD §2.11: "When a request could fail several checks at once, the server
        evaluates validations in a fixed priority order and reports the first failure
        encountered" — with the posture gate cleared, the schedule-conflict check
        reports "(13) schedule conflicts and cooling periods (`ERR_SCHEDULE_CONFLICT`)".
        PRD §3.7: "Vacating the deadline whose miss froze the matter re-runs the
        posture ladder and may unfreeze it."

        Design: Difficulty/priority_pair_validation_conflict/work_order_authorize_posture_vs_temporal_priority
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        create_and_authorize_work_order(ctx, vendor["id"], hold["id"], estimated_gb=100)
        juris = create_deadline(ctx["matter_id"], ctx["counsel_id"],
                                deadline_type="COURT_DEADLINE", title="Answer due",
                                due_at="2026-08-05T00:00:00Z", is_jurisdictional=True)
        get_success_data(api.mark_deadline_missed(juris["id"], ctx["counsel"]))
        get_success_data(api.vacate_deadline(juris["id"], make_dgc_headers(ctx["dgc_id"]),
                                             court_order_reference="ORDER-2026-118"))
        unfrozen = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert unfrozen["posture"] == Posture.OPEN.value

        overlapping = create_work_order(ctx, vendor["id"], hold["id"],
                                        service_type="PROCESSING", estimated_gb=100,
                                        scheduled_start="2026-08-15T00:00:00Z",
                                        scheduled_end="2026-08-25T00:00:00Z")
        resp = api.authorize_work_order(overlapping["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)

    def test_work_order_start_before_scheduled_start_rejected(self, api):
        """PRD §3.6: "Starting an authorized order (`AUTHORIZED` → `IN_PROGRESS`) may
        not happen before its `scheduled_start` on the logical clock — early starts
        fail with `ERR_SCHEDULE_CONFLICT` — and is blocked while the matter's posture
        is `FROZEN`."

        Design: Corner/cross_cutting_layers/work_order_start_before_scheduled_start_rejected
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                             estimated_gb=100)

        early = api.start_work_order(wo["id"], OPS)
        validate_error(early, ApiErrorId.ERR_SCHEDULE_CONFLICT)

        get_success_data(api.set_clock("2026-08-10T00:00:00Z", OPS))
        started = validate_success(api.start_work_order(wo["id"], OPS))
        assert started["status"] == WorkOrderStatus.IN_PROGRESS.value, \
            "start at exactly scheduled_start must succeed"
