"""Vendor lifecycle, competitive bids, turnover issue/ack/return/close/void."""

from test_helpers import (
    ApiErrorId, approve_review_round, assert_vendor_load, award_bid,
    close_round_notes, close_turnover, create_turnover, create_vendor,
    create_vendor_bid, issue_turnover, setup_active_project,
    setup_issued_turnover, setup_staged_turnover_with_bid, stage_turnover,
    validate_error, validate_success,
)
from test_helpers.test_users import (
    make_facility_admin_headers, make_post_supervisor_headers,
    make_reviewer_lead_headers, make_vendor_rep_headers,
)

PS = make_post_supervisor_headers()
FA = make_facility_admin_headers()
RL = make_reviewer_lead_headers()


class TestVendorLoadComputedRead:
    def test_vendor_load_computed_read(self, api):
        """PRD §3.5: "The in-flight load counts the vendor's turnover packages in
        `ISSUED` and `ACKED`; the utilization percentage is the whole-number
        floor of one hundred times that load divided by `capacity_slots`."
        PRD §3.5: "The computed read on a vendor returns `vendor_id`,
        `in_flight_count`, `capacity_slots`, and `utilization_pct`."

        Design: Corner/endpoints/vendor_load_computed_read
        """
        vendor = create_vendor(vendor_name="VX", capabilities=["COLOR"],
                               day_rate_cents=100000, capacity_slots=5)
        resp = api.get_vendor_load(vendor["id"], FA)
        data = validate_success(resp)
        assert_vendor_load(data)
        assert data["in_flight_count"] == 0
        assert data["utilization_pct"] == 0


class TestVendorLoadVariants:
    def test_vendor_load_steady_variant_counts_issued_and_acked(self, api):
        """PRD §3.5: "The in-flight load counts the vendor's turnover packages in
        `ISSUED` and `ACKED`; the utilization percentage is the whole-number
        floor of one hundred times that load divided by `capacity_slots`."
        PRD §3.5: "a steady variant used once turnovers have moved to `ACKED` or
        beyond, counting `ISSUED` and `ACKED` together."

        Design: Difficulty/dual_variant_calc/vendor_load_provisional_vs_steady
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P2", "client_code": "CL002", "storage_quota_gb": 100})
        vendor = create_vendor(vendor_name="V1 ColorHouse",
                               capabilities=["COLOR"], day_rate_cents=500000,
                               capacity_slots=4)
        # T1: awarded + issued (stays ISSUED).
        t1 = create_turnover(project["id"], turnover_kind="COLOR",
                             sequence_label="SEQ-01")
        stage_turnover(project["id"], t1["id"])
        b1 = create_vendor_bid(project["id"], t1["id"], vendor["id"])
        award_bid(project["id"], b1["id"])
        issue_turnover(project["id"], t1["id"])
        # T2: awarded + issued + acked (ACKED).
        t2 = create_turnover(project["id"], turnover_kind="COLOR",
                             sequence_label="SEQ-02")
        stage_turnover(project["id"], t2["id"])
        b2 = create_vendor_bid(project["id"], t2["id"], vendor["id"])
        award_bid(project["id"], b2["id"])
        issue_turnover(project["id"], t2["id"])
        api.ack_turnover(project["id"], t2["id"],
                         make_vendor_rep_headers(vendor["id"]))
        resp = api.get_vendor_load(vendor["id"], FA)
        data = validate_success(resp)
        # Steady load counts ISSUED + ACKED = 2 of capacity 4 -> 50%.
        assert data["in_flight_count"] == 2, (
            f"Steady load should count ISSUED+ACKED = 2, "
            f"got {data['in_flight_count']}")
        assert data["utilization_pct"] == 50

    def test_vendor_load_provisional_variant_counts_issued_only(self, api):
        """PRD §3.5: "The figure has a provisional variant used at
        award-evaluation time — before the turnover has been issued,
        acknowledgment cannot yet be observed, so only `ISSUED` turnovers count —
        and a steady variant used once turnovers have moved to `ACKED` or beyond,
        counting `ISSUED` and `ACKED` together."

        Design: Difficulty/dual_variant_calc/vendor_load_provisional_vs_steady
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P2", "client_code": "CL002", "storage_quota_gb": 100})
        vendor = create_vendor(vendor_name="V1 ColorHouse",
                               capabilities=["COLOR"], day_rate_cents=500000,
                               capacity_slots=4)
        t1 = create_turnover(project["id"], turnover_kind="COLOR",
                             sequence_label="SEQ-01")
        stage_turnover(project["id"], t1["id"])
        b1 = create_vendor_bid(project["id"], t1["id"], vendor["id"])
        award_bid(project["id"], b1["id"])
        issue_turnover(project["id"], t1["id"])
        # Provisional snapshot: one ISSUED turnover of capacity 4 -> 25%.
        data = validate_success(api.get_vendor_load(vendor["id"], FA))
        assert data["in_flight_count"] == 1
        assert data["utilization_pct"] == 25


class TestVendorCapacityBoundary:
    def test_vendor_capacity_at_limit(self, api):
        """PRD §3.5: "the awarded vendor's `capacity_slots` is not exceeded by
        its concurrent in-flight turnovers — a vendor already at capacity is
        rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`."
        PRD §2.9 item 13: "At turnover issue, the vendor's concurrent in-flight
        turnovers must be below its slot capacity; otherwise
        `ERR_VENDOR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/vendor_capacity_at_limit
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PCap", "client_code": "CL012", "storage_quota_gb": 100})
        vendor = create_vendor(vendor_name="V1 Color", capabilities=["COLOR"],
                               day_rate_cents=500000, capacity_slots=1)
        t1 = create_turnover(project["id"], turnover_kind="COLOR",
                             sequence_label="SEQ-01")
        stage_turnover(project["id"], t1["id"])
        b1 = create_vendor_bid(project["id"], t1["id"], vendor["id"])
        award_bid(project["id"], b1["id"])
        issue_turnover(project["id"], t1["id"])
        # Vendor's single slot is now consumed by the ISSUED T1.
        load = validate_success(api.get_vendor_load(vendor["id"], FA))
        assert load["in_flight_count"] == 1 == vendor["capacity_slots"]
        # T2 with an awarded bid from the same vendor: issue must fail.
        t2 = create_turnover(project["id"], turnover_kind="COLOR",
                             sequence_label="SEQ-02")
        stage_turnover(project["id"], t2["id"])
        b2 = create_vendor_bid(project["id"], t2["id"], vendor["id"])
        award_bid(project["id"], b2["id"])
        resp = api.issue_turnover(project["id"], t2["id"], PS)
        validate_error(resp, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)

    def test_vendor_capacity_recheck_after_close_frees_slot(self, api):
        """PRD §3.5: "Closing, a `PostSupervisor` action, moves the package from
        `RETURNED` to `CLOSED` once that auto-created round has reached
        `APPROVED` or `VOID`, and releases the vendor's capacity slot."

        Design: Difficulty/boundary_precision_check/vendor_capacity_at_limit
        """
        project, turnover, vendor, _bid = setup_issued_turnover(
            project_overrides={"title": "PCap", "client_code": "CL012",
                               "storage_quota_gb": 100},
            vendor_overrides={"capacity_slots": 1},
            turnover_overrides={"turnover_kind": "COLOR",
                                "sequence_label": "SEQ-01"})
        api.ack_turnover(project["id"], turnover["id"],
                         make_vendor_rep_headers(vendor["id"]))
        api.return_turnover(project["id"], turnover["id"],
                            make_vendor_rep_headers(vendor["id"]))
        rounds = validate_success(api.list_review_rounds(project["id"], RL))
        auto_rr = rounds[0]
        close_round_notes(project["id"], auto_rr["id"])
        approve_review_round(project["id"], auto_rr["id"])
        close_turnover(project["id"], turnover["id"])
        # Slot freed: a fresh turnover to the same vendor can now issue.
        t2 = create_turnover(project["id"], turnover_kind="COLOR",
                             sequence_label="SEQ-02")
        stage_turnover(project["id"], t2["id"])
        b2 = create_vendor_bid(project["id"], t2["id"], vendor["id"])
        award_bid(project["id"], b2["id"])
        issued = validate_success(api.issue_turnover(project["id"], t2["id"], PS))
        assert issued["status"] == "ISSUED"


class TestVendorSlotConservation:
    def test_vendor_slot_conservation_full_cycle(self, api):
        """PRD §3.5: "Closing, a `PostSupervisor` action, moves the package from
        `RETURNED` to `CLOSED` once that auto-created round has reached
        `APPROVED` or `VOID`, and releases the vendor's capacity slot."
        PRD §3.5: "The in-flight load counts the vendor's turnover packages in
        `ISSUED` and `ACKED`."

        Design: Difficulty/compensating_invariant/vendor_slot_conservation
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PInv1", "client_code": "CL017", "storage_quota_gb": 100})
        vendor = create_vendor(vendor_name="V1 Color", capabilities=["COLOR"],
                               day_rate_cents=500000, capacity_slots=2)
        before = validate_success(api.get_vendor_load(vendor["id"], FA))
        assert before["in_flight_count"] == 0
        turnover = create_turnover(project["id"], turnover_kind="COLOR",
                                   sequence_label="SEQ-01")
        stage_turnover(project["id"], turnover["id"])
        bid = create_vendor_bid(project["id"], turnover["id"], vendor["id"])
        award_bid(project["id"], bid["id"])
        issue_turnover(project["id"], turnover["id"])
        api.ack_turnover(project["id"], turnover["id"],
                         make_vendor_rep_headers(vendor["id"]))
        api.return_turnover(project["id"], turnover["id"],
                            make_vendor_rep_headers(vendor["id"]))
        rounds = validate_success(api.list_review_rounds(project["id"], RL))
        auto_rr = rounds[0]
        close_round_notes(project["id"], auto_rr["id"])
        approve_review_round(project["id"], auto_rr["id"])
        close_turnover(project["id"], turnover["id"])
        after = validate_success(api.get_vendor_load(vendor["id"], FA))
        assert after["in_flight_count"] == 0, (
            f"Slot must be conserved across the full lifecycle; "
            f"expected 0, got {after['in_flight_count']}")
        assert after["in_flight_count"] == before["in_flight_count"]

    def test_vendor_slot_peak_during_cycle(self, api):
        """PRD §3.5: "The in-flight load counts the vendor's turnover packages in
        `ISSUED` and `ACKED`; the utilization percentage is the whole-number
        floor of one hundred times that load divided by `capacity_slots`."

        Design: Difficulty/compensating_invariant/vendor_slot_conservation
        """
        project, turnover, vendor, _bid = setup_issued_turnover(
            project_overrides={"title": "PInv1", "client_code": "CL017",
                               "storage_quota_gb": 100},
            vendor_overrides={"capacity_slots": 2},
            turnover_overrides={"turnover_kind": "COLOR",
                                "sequence_label": "SEQ-01"})
        peak = validate_success(api.get_vendor_load(vendor["id"], FA))
        assert peak["in_flight_count"] == 1, (
            f"One ISSUED turnover of capacity 2 should report load 1, "
            f"got {peak['in_flight_count']}")
        assert peak["utilization_pct"] == 50


class TestVendorSuspendCascade:
    def test_vendor_suspend_cascade_depth2(self, api):
        """PRD §3.5: "Suspension moves it to `SUSPENDED` and, as a side effect,
        expires every bid it still has in `SUBMITTED`, transitioning those bids
        to `EXPIRED`."

        Design: Difficulty/transitive_cascade/vendor_suspend_cascade_depth2
        """
        project, turnover, vendor, bid = setup_staged_turnover_with_bid(
            project_overrides={"title": "PV", "client_code": "CL008",
                               "storage_quota_gb": 100},
            vendor_overrides={"vendor_name": "V9 Sound",
                              "capabilities": ["SOUND"], "capacity_slots": 1},
            turnover_overrides={"turnover_kind": "SOUND",
                                "sequence_label": "SEQ-S01"})
        resp = api.suspend_vendor(vendor["id"], FA)
        vendor_after = validate_success(resp)
        assert vendor_after["status"] == "SUSPENDED"
        bid_after = validate_success(
            api.get_vendor_bid_flat(bid["id"], FA))
        assert bid_after["status"] == "EXPIRED", (
            f"SUBMITTED bid must expire when its vendor is suspended; "
            f"got {bid_after['status']}")

    def test_vendor_suspend_cascade_only_submitted_bids_expire(self, api):
        """PRD §3.5: "Suspension moves it to `SUSPENDED` and, as a side effect,
        expires every bid it still has in `SUBMITTED`, transitioning those bids
        to `EXPIRED`."
        PRD §3.5: "A `VendorRep` may also withdraw their own `SUBMITTED` bid,
        moving it to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/vendor_suspend_cascade_depth2
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PV", "client_code": "CL008", "storage_quota_gb": 100})
        vendor = create_vendor(vendor_name="V9 Sound", capabilities=["SOUND"],
                               capacity_slots=1)
        t = create_turnover(project["id"], turnover_kind="SOUND",
                            sequence_label="SEQ-S01")
        stage_turnover(project["id"], t["id"])
        bid_a = create_vendor_bid(project["id"], t["id"], vendor["id"],
                                  bid_amount_cents=700000, eta_days=4)
        bid_b = create_vendor_bid(project["id"], t["id"], vendor["id"],
                                  bid_amount_cents=710000, eta_days=5)
        # Withdraw bid_b first so only bid_a remains SUBMITTED.
        api.withdraw_bid(project["id"], bid_b["id"],
                         make_vendor_rep_headers(vendor["id"]))
        api.suspend_vendor(vendor["id"], FA)
        assert validate_success(api.get_vendor_bid_flat(bid_a["id"], FA))["status"] == "EXPIRED"
        assert validate_success(api.get_vendor_bid_flat(bid_b["id"], FA))["status"] == "WITHDRAWN"


class TestTurnoverVoid:
    def test_action_endpoint_turnover_void_releases_bids(self, api):
        """PRD §3.5: "A `DRAFT` turnover may instead be voided by a
        `PostSupervisor`: the package goes to `VOID`, every `SUBMITTED` bid
        against it transitions to `EXPIRED`, and an `AWARDED` bid, if one exists,
        transitions to `REJECTED` with the vendor's slot released."
        PRD §4: "POST /post-production/projects/{id}/turnovers/{turnover_id}/void
        | `DRAFT` → `VOID`".

        Design: Corner/endpoints/action_endpoint_turnover_void_releases_bids

        NOTE (STEP 1c split): the original test exercised the bid cascade by
        submitting bids against the DRAFT (never-staged) turnover. That setup
        premise is not uniquely derivable from PRD: §4 ("Submit a bid against a
        `STAGED` turnover") and §3.5 ("With the package `STAGED`, vendors
        compete") admit a faithful implementation that gates bid submission on
        STAGED, under which SUBMITTED bids can never attach to a DRAFT turnover
        and this test errors in setup. The bid-cascade assertions were removed;
        the verbatim, uniquely-derivable DRAFT → VOID transition assertion is
        kept. (The SUBMITTED → EXPIRED cascade mechanism itself remains covered
        via the vendor-suspension path in TestVendorSuspendCascade, which is
        reachable under every PRD-faithful reading.)
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL501", "storage_quota_gb": 10})
        turnover = create_turnover(project["id"], turnover_kind="COLOR",
                                   sequence_label="SEQ-01")
        assert turnover["status"] == "DRAFT"
        resp = api.void_turnover(project["id"], turnover["id"], PS)
        data = validate_success(resp)
        assert data["status"] == "VOID"
