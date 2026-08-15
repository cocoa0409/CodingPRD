"""Capacity windows: half-open overlap, posture thresholds, approval cascades,
window-full quote gating, and reserve/release conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_ro_in_quote_in_progress,
    api_client,
    approve_quote,
    assert_capacity_window,
    assert_window_posture_consistent,
    create_capacity_window,
    create_capacity_window_payload,
    create_quote_for_ro,
    create_quote_payload,
    get_quote,
    get_repair_order,
    get_success_data,
    get_window,
    issue_quote,
    issue_quote_for,
    make_customer_headers,
    record_test_run,
    setup_authorized_shop,
    setup_issued_quote_shop,
    setup_in_test_shop,
    setup_quote_in_progress_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
PLANNER = TEST_USERS["planner_headers"]


class TestApprovalCascade:
    def test_approval_cascades_to_order_window_and_posture(self, api):
        """PRD §3.6: "An approved quote cascades in three links: the repair order moves `QUOTE_IN_PROGRESS` → `AUTHORIZED`; the quote's `capacity_window_id` is copied onto the order; and the order's `estimated_bay_hours` are added to the window's `bay_hours_reserved`, recomputing `window_posture`, which may flip `NORMAL` → `SURGE` or `SURGE` → `FULL`."
        PRD §3.6: "From the reserved figure the `window_posture` derives: the window is `FULL` when reserved hours meet or exceed capacity; short of that, it is `SURGE` when reserved hours meet or exceed the smallest whole number that is at least eighty percent of capacity — a 101-hour window turns `SURGE` at 81 reserved hours; otherwise it is `NORMAL`."

        Design: Difficulty/transitive_cascade/quote_approval_capacity_posture_cascade
        """
        shop = setup_issued_quote_shop(window_capacity=100,
                                       ro_over={"estimated_bay_hours": 85},
                                       quote_over={"labor_hours": 20})
        window0 = get_window(shop["window"]["id"])
        assert window0["bay_hours_reserved"] == 0
        assert window0["window_posture"] == "NORMAL"

        approved = get_success_data(api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(shop["customer"]["id"])))
        assert approved["status"] == "APPROVED"

        ro = get_repair_order(shop["ro"]["id"])
        assert ro["status"] == "AUTHORIZED", "cascade link 1"
        assert ro["capacity_window_id"] == shop["window"]["id"], "window copied onto order"

        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 85, "cascade link 2"
        assert window["window_posture"] == "SURGE", "cascade link 3: 85 >= 80"
        assert_window_posture_consistent(window)

    def test_approval_flips_posture_surge_to_full(self, api):
        """PRD §3.6: "An approved quote cascades in three links: the repair order moves `QUOTE_IN_PROGRESS` → `AUTHORIZED`; the quote's `capacity_window_id` is copied onto the order; and the order's `estimated_bay_hours` are added to the window's `bay_hours_reserved`, recomputing `window_posture`, which may flip `NORMAL` → `SURGE` or `SURGE` → `FULL`."
        PRD §3.6: "Both thresholds are inclusive, so reserved hours exactly equal to capacity is `FULL`."

        Design: Difficulty/transitive_cascade/quote_approval_capacity_posture_cascade
        """
        # Capacity 200: first approval of 160h lands exactly on the SURGE
        # threshold (160 == 0.8 * 200); second approval of 40h fills it.
        shop = setup_authorized_shop(window_capacity=200,
                                     ro_over={"estimated_bay_hours": 160})
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 160
        assert window["window_posture"] == "SURGE"

        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 40})
        q2 = issue_quote_for(shop, ro=ro2)
        get_success_data(api_client.approve_quote(
            q2["id"], make_customer_headers(shop["customer"]["id"])))

        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 200
        assert window["window_posture"] == "FULL", "SURGE -> FULL on the second approval"
        assert_window_posture_consistent(window)


class TestWindowFullGate:
    def test_quote_creation_rejected_when_window_full(self, api):
        """PRD §3.6: "When the referenced window's posture is `FULL`, quote creation is rejected outright with `ERR_WINDOW_FULL` — no multiplier is produced and no quote is stored."
        PRD §3.6: "From the reserved figure the `window_posture` derives: the window is `FULL` when reserved hours meet or exceed capacity; short of that, it is `SURGE` when reserved hours meet or exceed the smallest whole number that is at least eighty percent of capacity — a 101-hour window turns `SURGE` at 81 reserved hours; otherwise it is `NORMAL`."

        Design: Difficulty/cross_entity_state_dependency/quote_creation_blocked_when_window_full
        """
        # Capacity 10; approving a 10-hour order fills it exactly (inclusive).
        shop = setup_authorized_shop(window_capacity=10,
                                     ro_over={"estimated_bay_hours": 10})
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 10
        assert window["window_posture"] == "FULL"

        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 5})
        resp = api_client.create_quote(
            create_quote_payload(ro2["id"], shop["window"]["id"], ro2["version"],
                                 labor_hours=2),
            SM)
        validate_error(resp, ApiErrorId.ERR_WINDOW_FULL)
        assert get_repair_order(ro2["id"])["status"] == "QUOTE_IN_PROGRESS"
        data, meta = validate_paginated(api_client.list_quotes(
            SM, params={"repair_order_id": ro2["id"]}))
        assert data == [] and meta["total_count"] == 0, "no quote is stored"

    def test_quote_creation_recovers_after_full_window_releases(self, api):
        """PRD §3.6: "When the referenced window's posture is `FULL`, quote creation is rejected outright with `ERR_WINDOW_FULL` — no multiplier is produced and no quote is stored."
        PRD §3.9: "Cancellation releases everything the order holds: if the order had reached `AUTHORIZED` or any later non-terminal state, its `estimated_bay_hours` come off the window's `bay_hours_reserved` and posture is recomputed; any pool unit `RESERVED` for the order returns `RESERVED` → `IN_POOL` with `reserved_for_ro_id` cleared to null; and every non-terminal quote on the order — `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — moves to `CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/quote_creation_blocked_when_window_full
        """
        shop = setup_authorized_shop(window_capacity=10,
                                     ro_over={"estimated_bay_hours": 10})
        assert get_window(shop["window"]["id"])["window_posture"] == "FULL"

        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 5})
        blocked = api_client.create_quote(
            create_quote_payload(ro2["id"], shop["window"]["id"], ro2["version"],
                                 labor_hours=2),
            SM)
        validate_error(blocked, ApiErrorId.ERR_WINDOW_FULL)

        # Cancel the approved order: its hours come off and posture recomputes.
        get_success_data(api_client.cancel_repair_order(shop["ro"]["id"], IC))
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 0
        assert window["window_posture"] == "NORMAL"

        created = create_quote_for_ro(ro2["id"], shop["window"]["id"], labor_hours=2)
        assert created["status"] == "DRAFT"
        assert created["revision"] == 1


class TestReserveReleaseConservation:
    def test_approve_then_cancel_restores_reserved_hours(self, api):
        """PRD §3.6: "An approved quote cascades in three links: the repair order moves `QUOTE_IN_PROGRESS` → `AUTHORIZED`; the quote's `capacity_window_id` is copied onto the order; and the order's `estimated_bay_hours` are added to the window's `bay_hours_reserved`, recomputing `window_posture`, which may flip `NORMAL` → `SURGE` or `SURGE` → `FULL`."
        PRD §3.9: "Cancellation releases everything the order holds: if the order had reached `AUTHORIZED` or any later non-terminal state, its `estimated_bay_hours` come off the window's `bay_hours_reserved` and posture is recomputed; any pool unit `RESERVED` for the order returns `RESERVED` → `IN_POOL` with `reserved_for_ro_id` cleared to null; and every non-terminal quote on the order — `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — moves to `CANCELLED`."
        PRD §3.5: "A quote's full status vocabulary is `DRAFT`, `ISSUED`, `REVISION_REQUESTED`, `APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED`, and `CANCELLED`, the last five terminal."

        Design: Difficulty/compensating_invariant/capacity_hours_reserve_release_conservation
        """
        shop = setup_issued_quote_shop(window_capacity=200,
                                       ro_over={"estimated_bay_hours": 40},
                                       quote_over={"labor_hours": 8})
        assert get_window(shop["window"]["id"])["bay_hours_reserved"] == 0

        get_success_data(api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(shop["customer"]["id"])))
        assert get_repair_order(shop["ro"]["id"])["status"] == "AUTHORIZED"
        assert get_window(shop["window"]["id"])["bay_hours_reserved"] == 40

        get_success_data(api_client.cancel_repair_order(shop["ro"]["id"], IC))
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 0, (
            "the compensating cancel restores the conserved hours"
        )
        assert window["window_posture"] == "NORMAL"
        # APPROVED is terminal for a quote: the cancel cascade moves only
        # non-terminal quotes (DRAFT / ISSUED / REVISION_REQUESTED) to CANCELLED.
        assert get_quote(shop["quote"]["id"])["status"] == "APPROVED"

    def test_close_and_cancel_both_release_reserved_hours(self, api):
        """PRD §3.9: "Closing an order moves it `COMPLETE` → `CLOSED` and settles every open ledger at once: `closed_at` stamps the current logical clock; `invoiced_total_cents` snapshots the approved quote's `total_cents`; `repair_outcome` resolves to `FIRST_TIME_FIX` when `repair_round` is zero and `RE_REPAIR` otherwise; the order's `estimated_bay_hours` are subtracted from its window's `bay_hours_reserved`, recomputing the window's posture; and, where a pool unit stands `RESERVED` for this order, the exchange settles — the reserved unit moves `RESERVED` → `ISSUED`, and a fresh pool unit carrying this order's `customer_id` and `asset_id` is created `IN_POOL` as replenishment."
        PRD §3.9: "Cancellation releases everything the order holds: if the order had reached `AUTHORIZED` or any later non-terminal state, its `estimated_bay_hours` come off the window's `bay_hours_reserved` and posture is recomputed; any pool unit `RESERVED` for the order returns `RESERVED` → `IN_POOL` with `reserved_for_ro_id` cleared to null; and every non-terminal quote on the order — `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — moves to `CANCELLED`."

        Design: Difficulty/compensating_invariant/capacity_hours_reserve_release_conservation
        """
        shop = setup_authorized_shop(window_capacity=200,
                                     ro_over={"estimated_bay_hours": 40})
        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 25})
        q2 = issue_quote_for(shop, ro=ro2)
        get_success_data(api_client.approve_quote(
            q2["id"], make_customer_headers(shop["customer"]["id"])))
        assert get_window(shop["window"]["id"])["bay_hours_reserved"] == 65

        # Close the first order (drive it through test first): releases 40.
        tech = TEST_USERS["technician_headers"]
        get_success_data(api_client.start_repair(shop["ro"]["id"], tech))
        get_success_data(api_client.submit_for_test(shop["ro"]["id"], tech))
        record_test_run(shop["ro"]["id"])
        closed = get_success_data(api_client.close_repair_order(shop["ro"]["id"], IC))
        assert closed["status"] == "CLOSED"
        assert get_window(shop["window"]["id"])["bay_hours_reserved"] == 25

        # Cancel the second: releases the remaining 25.
        get_success_data(api_client.cancel_repair_order(ro2["id"], IC))
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 0
        assert window["window_posture"] == "NORMAL"


class TestWindowOverlapSemantics:
    def test_half_open_adjacency_allowed_straddle_rejected(self, api):
        """PRD §3.6: "Windows are half-open intervals — the start inclusive, the end exclusive — and a new window may not overlap an existing one; adjacency is allowed, and an overlapping creation is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/capacity_window_half_open_overlap_semantics
        """
        w1 = create_capacity_window(
            label="W1", window_start="2026-06-01T00:00:00Z",
            window_end="2026-07-01T00:00:00Z", bay_hours_capacity=100)
        assert_capacity_window(w1)
        assert w1["bay_hours_reserved"] == 0
        assert w1["window_posture"] == "NORMAL"

        # Adjacent at the end: [07-01, 08-01) starts exactly where W1 ends.
        w2 = validate_success(api_client.create_capacity_window(
            create_capacity_window_payload(
                label="W2", window_start="2026-07-01T00:00:00Z",
                window_end="2026-08-01T00:00:00Z", bay_hours_capacity=100),
            PLANNER), 201)
        assert_capacity_window(w2)

        # Straddling W1's end and W2's start overlaps both.
        w3 = api_client.create_capacity_window(
            create_capacity_window_payload(
                label="W3", window_start="2026-06-15T00:00:00Z",
                window_end="2026-07-15T00:00:00Z", bay_hours_capacity=50),
            PLANNER)
        validate_error(w3, ApiErrorId.ERR_WINDOW_OVERLAP)

        _data, meta = validate_paginated(api_client.list_capacity_windows(SM))
        assert meta["total_count"] == 2

    def test_half_open_containment_identical_and_front_adjacency(self, api):
        """PRD §3.6: "Windows are half-open intervals — the start inclusive, the end exclusive — and a new window may not overlap an existing one; adjacency is allowed, and an overlapping creation is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/capacity_window_half_open_overlap_semantics
        """
        create_capacity_window(label="W1", window_start="2026-06-01T00:00:00Z",
                               window_end="2026-07-01T00:00:00Z", bay_hours_capacity=100)

        # Fully contained window overlaps.
        contained = api_client.create_capacity_window(
            create_capacity_window_payload(
                label="WINNER", window_start="2026-06-10T00:00:00Z",
                window_end="2026-06-20T00:00:00Z", bay_hours_capacity=10),
            PLANNER)
        validate_error(contained, ApiErrorId.ERR_WINDOW_OVERLAP)

        # Ending exactly at W1's start is adjacent: allowed.
        front = validate_success(api_client.create_capacity_window(
            create_capacity_window_payload(
                label="WFRONT", window_start="2026-05-01T00:00:00Z",
                window_end="2026-06-01T00:00:00Z", bay_hours_capacity=10),
            PLANNER), 201)
        assert_capacity_window(front)

        # Identical interval overlaps.
        identical = api_client.create_capacity_window(
            create_capacity_window_payload(
                label="WDUP", window_start="2026-06-01T00:00:00Z",
                window_end="2026-07-01T00:00:00Z", bay_hours_capacity=10),
            PLANNER)
        validate_error(identical, ApiErrorId.ERR_WINDOW_OVERLAP)

        _data, meta = validate_paginated(api_client.list_capacity_windows(SM))
        assert meta["total_count"] == 2

    def test_window_end_before_start_returns_validation(self, api):
        """PRD §3.6: "A `Planner` creates each window with a `label`, a `window_start`, a `window_end` that must be strictly later than the start (otherwise `ERR_VALIDATION`), and a positive whole number of `bay_hours_capacity`."

        Design: Corner/validations/capacity_window_end_before_start_returns_validation
        """
        resp = api_client.create_capacity_window(
            create_capacity_window_payload(
                label="WBAD", window_start="2026-07-01T00:00:00Z",
                window_end="2026-06-01T00:00:00Z", bay_hours_capacity=100),
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestPostureThresholds:
    def test_surge_threshold_inclusive_boundary(self, api):
        """PRD §3.6: "From the reserved figure the `window_posture` derives: the window is `FULL` when reserved hours meet or exceed capacity; short of that, it is `SURGE` when reserved hours meet or exceed the smallest whole number that is at least eighty percent of capacity — a 101-hour window turns `SURGE` at 81 reserved hours; otherwise it is `NORMAL`."

        Design: Corner/calculations/window_posture_surge_threshold_boundary
        """
        # Capacity 100: 79 hours approved stays NORMAL; one more hour hits 80.
        shop = setup_authorized_shop(window_capacity=100,
                                     ro_over={"estimated_bay_hours": 79})
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 79
        assert window["window_posture"] == "NORMAL", "79 < 80"

        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 1})
        q2 = issue_quote_for(shop, ro=ro2)
        get_success_data(api_client.approve_quote(
            q2["id"], make_customer_headers(shop["customer"]["id"])))
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 80
        assert window["window_posture"] == "SURGE", "reserved == 80 is SURGE (inclusive)"
        assert_window_posture_consistent(window)

    def test_exact_fit_approved_then_window_full_overflow_rejected(self, api):
        """PRD §3.6: "The capacity gate requires that the window absorb the order: the window's current `bay_hours_reserved` plus the order's `estimated_bay_hours` must not exceed `bay_hours_capacity`, with equality permitted; an overflow is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`."
        PRD §3.6: "Both thresholds are inclusive, so reserved hours exactly equal to capacity is `FULL`."

        Design: Corner/calculations/window_capacity_exact_fit_then_full
        """
        shop = setup_authorized_shop(window_capacity=100,
                                     ro_over={"estimated_bay_hours": 85})
        cust = make_customer_headers(shop["customer"]["id"])

        # 85 + 16 = 101 > 100: overflow rejected, quote stays ISSUED.
        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 16})
        q2 = issue_quote_for(shop, ro=ro2)
        resp = api_client.approve_quote(q2["id"], cust)
        validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED)
        assert get_quote(q2["id"])["status"] == "ISSUED"

        # 85 + 15 = 100 <= 100: exact fit approved, window flips FULL.
        ro3 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 15})
        q3 = issue_quote_for(shop, ro=ro3)
        approved = get_success_data(api_client.approve_quote(q3["id"], cust))
        assert approved["status"] == "APPROVED"

        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 100
        assert window["window_posture"] == "FULL"
        assert_window_posture_consistent(window)

    def test_immediate_consistency_after_approval(self, api):
        """PRD §3.6: "An approved quote cascades in three links: the repair order moves `QUOTE_IN_PROGRESS` → `AUTHORIZED`; the quote's `capacity_window_id` is copied onto the order; and the order's `estimated_bay_hours` are added to the window's `bay_hours_reserved`, recomputing `window_posture`, which may flip `NORMAL` → `SURGE` or `SURGE` → `FULL`."

        Design: Corner/consistency_model/immediate_consistency_after_approval
        """
        shop = setup_issued_quote_shop(window_capacity=100,
                                       ro_over={"estimated_bay_hours": 30})
        get_success_data(api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(shop["customer"]["id"])))

        # The very next reads observe every cascade link, with no settling lag.
        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 30
        assert window["window_posture"] == "NORMAL", "30 < 80"
        ro = get_repair_order(shop["ro"]["id"])
        assert ro["status"] == "AUTHORIZED"
        assert ro["capacity_window_id"] == shop["window"]["id"]
