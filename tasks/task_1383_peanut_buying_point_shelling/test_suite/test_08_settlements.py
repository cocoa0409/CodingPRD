"""Grower settlement: pricing, quota straddle, drying/loan/hull components,
segregation of duties, supersede chains, OCC, and the quota invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_dryer,
    add_warehouse,
    api_client,
    assert_settlement,
    compute_settlement,
    create_dryer_booking_payload,
    get_grower,
    get_load,
    get_loan_pledge,
    get_quota_history,
    get_settlement,
    get_storage_receipt,
    issue_call,
    allocate_call,
    deliver_call,
    reconcile_call,
    create_active_contract,
    list_hull_lots_for_call,
    make_grower_headers,
    pledge_full_receipt,
    report_load,
    sell_hull_lot,
    set_clock,
    setup_active_schedule,
    setup_buying_point,
    setup_computed_settlement,
    setup_grower,
    setup_reconciled_call,
    setup_settlement_foundation,
    setup_stored_load,
    validate_error,
    validate_paginated,
    validate_success,
    grade_load,
    weigh_load,
    clear_aflatoxin,
    store_load,
    setup_cleared_load,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK_1 = TEST_USERS["clerk_1_headers"]
CLERK_2 = TEST_USERS["clerk_2_headers"]
CLERK_3 = TEST_USERS["clerk_3_headers"]


class TestProvisionalVsFinal:

    def test_provisional_estimate_written_at_finalize(self):
        """PRD section 3.4: "Its `provisional_net_estimate_cents` is computed
        as a forward-looking estimate of settlement value: the per-load net
        value of §3.9 computed with quota headroom taken as the grower's annual
        quota minus already-consumed quota with no intra-settlement
        consumption, minus an estimated drying charge when drying is
        `REQUIRED`, with hull credit and loan offset treated as zero."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
        """
        f = setup_settlement_foundation()
        load, _sheet, _cert, _receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        load_after = get_load(load["id"])
        assert load_after["payable_tons"] == 23.375
        # gross 23.375 x 56000 = 1309000; discounts 22207; drying/loan/hull zero
        assert load_after["provisional_net_estimate_cents"] == 1286793

    def test_final_settlement_diverges_by_hull_pool_share(self):
        """PRD section 3.9: "Finally, `net_payment_cents` is the gross value
        minus discounts, minus drying, minus the loan offset, plus the hull
        credit."
        PRD section 3.9: "the pool is the `revenue_cents` of `SOLD` hull lots
        whose delivery call's contract belongs to this buying point and whose
        `sold_at` is no later than the settlement's compute date".

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
        """
        f = setup_settlement_foundation()
        env = setup_reconciled_call(f["grower"], f["warehouse"], f["bp"]["id"])
        lot = list_hull_lots_for_call(env["call"]["id"])[0]
        sell_hull_lot(lot["id"], sale_price_cents_per_ton=4000)
        set_clock("2026-09-02T00:00:00Z")

        settlement = compute_settlement(f["grower"]["id"], f["grower"]["version"])
        assert_settlement(settlement)
        assert settlement["gross_value_cents"] == 1309000
        assert settlement["discount_cents"] == 22207
        assert settlement["drying_cents"] == 0
        assert settlement["loan_offset_cents"] == 0
        # sole contributing grower takes the whole pool: 3.8t x 4000
        assert settlement["hull_credit_cents"] == 15200
        assert settlement["net_payment_cents"] == 1301993

        load_after = get_load(env["load"]["id"])
        provisional = load_after["provisional_net_estimate_cents"]
        assert provisional == 1286793
        assert settlement["net_payment_cents"] - provisional == 15200, \
            "provisional and final diverge by exactly the hull pool share"


class TestLoanOffsetFrozen:

    def _setup_pledged_settlement(self):
        f = setup_settlement_foundation()
        load, _s, _c, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        pledge = pledge_full_receipt(f["grower"]["id"], receipt["id"],
                                     pledged_tons=25.0)
        set_clock("2026-10-01T09:00:00Z")  # day 30
        settlement = compute_settlement(f["grower"]["id"], f["grower"]["version"])
        return f, load, receipt, pledge, settlement

    def test_loan_offset_frozen_at_compute(self):
        """PRD section 3.9: "`loan_offset_cents` sums, over the grower's
        `ACTIVE` pledges, the outstanding principal plus interest accrued to
        the settlement's compute date; offsets are frozen at compute —
        approval and payment never recompute them, and any change requires a
        fresh superseding settlement."

        Design: Difficulty/combinatorial_formula/loan_offset_frozen_at_compute
        """
        f, load, receipt, pledge, settlement = self._setup_pledged_settlement()
        # interest at day 30: 887500 x 0.0002 x 30 = 5325
        assert settlement["loan_offset_cents"] == 892825
        assert settlement["gross_value_cents"] == 1309000
        assert settlement["discount_cents"] == 22207
        assert settlement["net_payment_cents"] == 393968
        assert settlement["offset_pledge_ids"] == [pledge["id"]]

    def test_approve_pay_never_recomputes_offset(self):
        """PRD section 3.9: "offsets are frozen at compute — approval and
        payment never recompute them".
        PRD section 3.9: "every pledge in `offset_pledge_ids` that is still
        `ACTIVE` moves to `REPAID`, and its storage receipt returns to `OPEN`."

        Design: Difficulty/combinatorial_formula/loan_offset_frozen_at_compute
        """
        f, load, receipt, pledge, settlement = self._setup_pledged_settlement()
        set_clock("2026-10-11T09:00:00Z")  # day 40: live interest would be 7100
        api_client.approve_settlement(settlement["id"], CLERK_2)
        api_client.pay_settlement(settlement["id"], CLERK_3)

        settled = get_settlement(settlement["id"])
        assert settled["status"] == "PAID"
        assert settled["loan_offset_cents"] == 892825, \
            "frozen at compute; a live recompute at day 40 (894600) is forbidden"

        pledge_after = get_loan_pledge(pledge["id"])
        assert pledge_after["status"] == "REPAID"
        assert pledge_after["outstanding_principal_cents"] == 0
        assert get_storage_receipt(receipt["id"])["status"] == "OPEN"


class TestSettlementFigures:

    def test_quota_straddle_split_pricing(self):
        """PRD section 3.9: "its `quota_tons_applied` is the payable tonnage
        capped at the grower's remaining quota, where remaining quota is the
        annual `quota_tons` minus `used_quota_tons` minus the quota-tier
        tonnage of loads earlier in this same settlement's inclusion order —
        other `COMPUTED` settlements do not reduce this view, a deliberate
        overcommit window that approval re-validates — and its
        `additional_tons_applied` is the rest."
        PRD section 3.9: "`gross_value_cents` sums the per-load gross values,
        each being the quota portion times `quota_price_cents_per_ton` rounded
        half up to whole cents plus the additional portion times
        `additional_price_cents_per_ton` rounded half up to whole cents."

        Design: Corner/calculations/quota_straddle_split_pricing
        """
        env = setup_computed_settlement(quota_tons=20)
        s1 = env["settlement"]
        assert s1["quota_tons_applied"] == 20.0
        assert s1["additional_tons_applied"] == 3.375
        # 20 x 56000 + 3.375 x 40000 = 1120000 + 135000
        assert s1["gross_value_cents"] == 1255000
        assert s1["discount_cents"] == 22207
        assert s1["net_payment_cents"] == 1232793

    def test_drying_charge_cycles_and_moisture_multiplier(self):
        """PRD section 3.6: "for each `COMPLETED` booking of an included load,
        the charge is the number of cycles — booking tonnage divided by the
        dryer's per-cycle capacity, rounded up — multiplied by
        `drying_rate_per_cycle_cents` and by a moisture multiplier, with the
        product rounded half up to whole cents. The multiplier starts at one
        and increases by 0.05 for each full percentage point by which
        `moisture_at_booking` exceeds 10.49 percent, disregarding any
        fractional part of a point."
        PRD section 3.6: "the booking snapshots `moisture_at_booking` from the
        load's finalized grade sheet".

        Design: Corner/calculations/drying_charge_cycles_and_moisture_multiplier
        """
        f = setup_settlement_foundation(quota_tons=100, with_dryer=True)
        gid = f["grower"]["id"]
        dryer_id = f["dryer"]["id"]
        bookings = []
        for moisture, start in ((11.2, "2026-09-03T06:00:00Z"),
                                (12.2, "2026-09-03T18:00:00Z")):
            load = report_load(gid)
            weighed = weigh_load(load["id"], 24.0)
            grade_load(load["id"], weighed["version"], moisture_pct=moisture,
                       foreign_material_pct=3.0, damage_pct=0.0, lsk_pct=0.0)
            bk = validate_success(api_client.create_dryer_booking(
                create_dryer_booking_payload(dryer_id=dryer_id,
                                             load_id=load["id"], tons=24.0,
                                             starts_at=start), ADMIN),
                expected_status=201)
            bookings.append((load, bk))
            api_client.complete_dryer_booking(
                bk["id"], {"actual_moisture_after": 9.0}, ADMIN)
            clear_aflatoxin(load["id"], result_ppb=6.0)
            store_load(load["id"], f["warehouse"]["id"])

        settlement = compute_settlement(gid, f["grower"]["version"])
        # B1: 2 cycles x 9000 x 1.00 = 18000; B2: 2 x 9000 x 1.05 = 18900
        assert settlement["drying_cents"] == 36900
        # payable 23.28 each; discounts: B1 23.28 x 700 = 16296 (m 11.2 tier),
        # B2 23.28 x 1500 = 34920 (m 12.2 tier)
        assert settlement["discount_cents"] == 51216
        assert settlement["gross_value_cents"] == 2607360
        assert settlement["net_payment_cents"] == 2519244

        bk1 = api_client.get_dryer_booking(bookings[0][1]["id"], ADMIN).json()["data"]
        bk2 = api_client.get_dryer_booking(bookings[1][1]["id"], ADMIN).json()["data"]
        assert bk1["moisture_at_booking"] == 11.2
        assert bk2["moisture_at_booking"] == 12.2

    def test_hull_credit_remainder_distribution(self):
        """PRD section 3.9: "each contributing grower's base share is the pool
        times its shelled tonnage divided by the total shelled tonnage, rounded
        down (floored) to whole cents; and the undistributed remainder is then
        dealt out one cent at a time to growers in order of their earliest
        contributing allocation line's `created_at`, ties broken by the
        grower's own `created_at`, never by identifier, until the remainder is
        exhausted."

        Design: Corner/calculations/hull_credit_remainder_distribution
        """
        bp = setup_buying_point()
        setup_active_schedule()
        g1 = setup_grower(name="Grower One", farm_number="F-1001", quota_tons=100)
        g2 = setup_grower(name="Grower Two", farm_number="F-1002", quota_tons=100)
        wh = add_warehouse(bp["id"])

        # G1: 40t clean load stored at 09:00
        load1, _s1, _c1, _r1 = setup_stored_load(
            g1["id"], wh["id"], gross_tons=40.0, moisture_pct=8.0,
            foreign_material_pct=0.0, damage_pct=0.0, lsk_pct=0.0, result_ppb=4.0)
        # G2: 26t clean load stored at 10:00
        set_clock("2026-09-01T10:00:00Z")
        load2, _s2, _c2, _r2 = setup_stored_load(
            g2["id"], wh["id"], gross_tons=26.0, moisture_pct=8.0,
            foreign_material_pct=0.0, damage_pct=0.0, lsk_pct=0.0, result_ppb=4.0)

        contract = create_active_contract(bp["id"], total_units_tons=100.0)
        dc1 = issue_call(contract["id"], 40.0)
        allocate_call(dc1["id"], dc1["version"])
        deliver_call(dc1["id"])
        reconcile_call(dc1["id"], 30.0, 10.0)
        hl1 = list_hull_lots_for_call(dc1["id"])[0]
        sell_hull_lot(hl1["id"], sale_price_cents_per_ton=4000)

        dc2 = issue_call(contract["id"], 26.0,
                         dock_window_start="2026-09-11T08:00:00Z",
                         dock_window_end="2026-09-11T12:00:00Z")
        allocate_call(dc2["id"], dc2["version"])
        deliver_call(dc2["id"])
        reconcile_call(dc2["id"], 20.0, 5.9)
        hl2 = list_hull_lots_for_call(dc2["id"])[0]
        sell_hull_lot(hl2["id"], sale_price_cents_per_ton=10170)

        s1 = compute_settlement(g1["id"], g1["version"])
        s2 = compute_settlement(g2["id"], g2["version"])

        # pool = 40000 + 60003 = 100003; shelled 30:20 ->
        # floor shares 60001 + 40001 = 100002, remainder cent to earliest line (G1)
        assert s1["hull_credit_cents"] == 60002
        assert s2["hull_credit_cents"] == 40001
        assert s1["hull_credit_cents"] + s2["hull_credit_cents"] == 100003
        assert s1["net_payment_cents"] == 2300002  # 40 x 56000 + 60002
        assert s2["net_payment_cents"] == 1496001  # 26 x 56000 + 40001


class TestSettlementPipeline:

    def test_settlement_pay_before_approve_rejected(self):
        """PRD section 3.9: "Payment requires a third clerk distinct from the
        approver (`ERR_SEG_OF_DUTIES`). It stamps `paid_by`, moves `APPROVED` →
        `PAID`".
        PRD section 2.9: "**State preconditions** — the target resource is in a
        valid from-state, and state-gated creations are satisfied
        (`ERR_INVALID_STATE`, including the specialized grower-suspension,
        intake-suspension, and drying gate codes described in §3)."

        Design: Corner/state_machines/settlement_pay_before_approve_rejected
        """
        env = setup_computed_settlement()
        s1 = env["settlement"]
        resp = api_client.pay_settlement(s1["id"], TEST_USERS["clerk_3_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_settlement(s1["id"])
        assert after["status"] == "COMPUTED"
        assert after.get("paid_by") in (None, "")

    def test_dispute_then_recompute_supersedes(self):
        """PRD section 3.9: "The grower may dispute its own `COMPUTED`
        settlement, moving it to `DISPUTED`."
        PRD section 3.9: "Computing it supersedes the grower's prior
        non-terminal settlements for the same crop year: any in `DISPUTED` or
        `STALE` moves to `SUPERSEDED`."
        PRD section 3.9: "links `supersedes_settlement_id` to the settlement it
        replaces (null for the first)".

        Design: Corner/state_machines/dispute_then_recompute_supersedes
        """
        env = setup_computed_settlement()
        s1 = env["settlement"]
        gid = env["grower"]["id"]

        resp = api_client.dispute_settlement(s1["id"], make_grower_headers(gid))
        disputed = validate_success(resp)
        assert disputed["status"] == "DISPUTED"

        grower_now = get_grower(gid)
        s2 = compute_settlement(gid, grower_now["version"])
        assert s2["status"] == "COMPUTED"
        assert s2["supersedes_settlement_id"] == s1["id"]
        assert s2["net_payment_cents"] == 1286793, \
            "identical inputs reproduce identical figures"

        s1_after = get_settlement(s1["id"])
        assert s1_after["status"] == "SUPERSEDED"

        _data, meta = validate_paginated(api_client.list_settlements(
            ADMIN, params={"supersedes_settlement_id": s1["id"]}))
        assert meta["total_count"] == 1

    def test_sod_settlement_three_clerk_legs(self):
        """PRD section 2.11: "The clerk who computes a settlement may not
        approve it. The clerk who approves a settlement may not pay it. Each
        crossing is rejected with `ERR_SEG_OF_DUTIES`."
        PRD section 3.9: "Approval stamps `approved_by`" and "It stamps
        `paid_by`, moves `APPROVED` → `PAID`".

        Design: Corner/validations/sod_settlement_three_clerk_legs
        """
        env = setup_computed_settlement()  # computed by clerk-1
        s1 = env["settlement"]
        assert s1["computed_by"] == "clerk-1"

        resp = api_client.approve_settlement(s1["id"], CLERK_1)
        validate_error(resp, ApiErrorId.ERR_SEG_OF_DUTIES)

        approved = validate_success(api_client.approve_settlement(s1["id"], CLERK_2))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "clerk-2"

        resp = api_client.pay_settlement(s1["id"], CLERK_2)
        validate_error(resp, ApiErrorId.ERR_SEG_OF_DUTIES)

        paid = validate_success(api_client.pay_settlement(s1["id"], CLERK_3))
        assert paid["status"] == "PAID"
        assert paid["paid_by"] == "clerk-3"

    def test_settlement_negative_net_blocks_approve(self):
        """PRD section 3.9: "the net payment must not be negative
        (`ERR_SETTLEMENT_NOT_PAYABLE`)".

        Design: Corner/errors/settlement_negative_net_blocks_approve
        """
        f = setup_settlement_foundation()
        load, _s, _c, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        pledge = pledge_full_receipt(f["grower"]["id"], receipt["id"],
                                     pledged_tons=25.0)
        set_clock("2037-08-14T09:00:00Z")  # 4000 days after the 2026-09-01 pledge
        settlement = compute_settlement(f["grower"]["id"], f["grower"]["version"])

        # interest = 887500 x 0.0002 x 4000 = 710000; offset = 1597500
        assert settlement["loan_offset_cents"] == 1597500
        assert settlement["net_payment_cents"] == -310707  # 1286793 - 1597500

        resp = api_client.approve_settlement(settlement["id"], CLERK_2)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PAYABLE)
        assert get_settlement(settlement["id"])["status"] == "COMPUTED"

    def test_quota_exceeded_at_approve_then_recompute(self):
        """PRD section 3.9: "other `COMPUTED` settlements do not reduce this
        view, a deliberate overcommit window that approval re-validates".
        PRD section 3.9: "the live quota check requires the history's
        `used_quota_tons` plus this settlement's `quota_tons_applied` to be no
        more than `quota_tons` (`ERR_QUOTA_EXCEEDED`)."
        PRD section 3.9: "The inclusion set is the grower's loads for that crop
        year in `STORED` or `DEPLETED` status whose `settlement_id` is still
        null".

        Design: Corner/validations/quota_exceeded_at_approve_then_recompute
        """
        f = setup_settlement_foundation(quota_tons=100)
        gid = f["grower"]["id"]
        qh_id = None
        resp = api_client.list_quota_histories(ADMIN, params={"grower_id": gid})
        qh_id = resp.json()["data"][0]["id"]

        def _store_clean_60t():
            load, _s, _c, _r = setup_stored_load(
                gid, f["warehouse"]["id"], gross_tons=60.0, moisture_pct=8.0,
                foreign_material_pct=0.0, damage_pct=0.0, lsk_pct=0.0,
                result_ppb=4.0)
            return load

        _l1 = _store_clean_60t()
        s1 = compute_settlement(gid, f["grower"]["version"])
        assert s1["quota_tons_applied"] == 60.0

        _l2 = _store_clean_60t()
        gv2 = get_grower(gid)["version"]
        s2 = compute_settlement(gid, gv2)
        # L1's settlement_id is still null (S1 merely COMPUTED), so S2's
        # inclusion set holds both 60t loads: 60 + min(60, 40) = 100.
        assert s2["quota_tons_applied"] == 100.0

        api_client.approve_settlement(s1["id"], CLERK_2)
        resp = api_client.approve_settlement(s2["id"], CLERK_2)
        validate_error(resp, ApiErrorId.ERR_QUOTA_EXCEEDED)
        assert get_settlement(s2["id"])["status"] == "COMPUTED"

        api_client.dispute_settlement(s2["id"], make_grower_headers(gid))
        gv3 = get_grower(gid)["version"]
        s3 = compute_settlement(gid, gv3)
        # only L2 is eligible now: quota 40 remaining of 100
        assert s3["quota_tons_applied"] == 40.0
        assert s3["additional_tons_applied"] == 20.0
        assert s3["gross_value_cents"] == 3040000  # 40 x 56000 + 20 x 40000
        assert s3["net_payment_cents"] == 3040000

        api_client.approve_settlement(s3["id"], CLERK_2)
        qh = get_quota_history(qh_id)
        assert qh["used_quota_tons"] == 100.0  # 60 + 40

        assert get_settlement(s2["id"])["status"] == "SUPERSEDED"
        assert get_settlement(s1["id"])["status"] == "APPROVED"


class TestQuotaInvariant:

    def test_approve_adds_and_void_restores_quota(self):
        """PRD section 3.9: "Approval stamps `approved_by`, adds
        `quota_tons_applied` into the quota history's `used_quota_tons`, and
        writes this settlement's id into every included load's
        `settlement_id`".
        PRD section 3.9: "voiding subtracts `quota_tons_applied` back out of
        the quota history's `used_quota_tons` — the compensating invariant that
        keeps consumed quota consistent — and clears every included load's
        `settlement_id`."

        Design: Difficulty/compensating_invariant/quota_consumption_invariant
        """
        env = setup_computed_settlement()
        s1 = env["settlement"]
        qh_id = api_client.list_quota_histories(
            ADMIN, params={"grower_id": env["grower"]["id"]}).json()["data"][0]["id"]

        assert s1["quota_tons_applied"] == 23.375
        api_client.approve_settlement(s1["id"], CLERK_2)
        qh = get_quota_history(qh_id)
        assert qh["used_quota_tons"] == 23.375
        assert get_load(env["load"]["id"])["settlement_id"] == s1["id"]

        api_client.void_settlement(s1["id"], ADMIN)
        qh = get_quota_history(qh_id)
        assert qh["used_quota_tons"] == 0, "void restores the invariant, zero drift"
        assert get_load(env["load"]["id"])["settlement_id"] is None
        assert get_settlement(s1["id"])["status"] == "VOIDED"

    def test_recompute_after_void_reapproves_cleanly(self):
        """PRD section 3.9: "Computing it supersedes the grower's prior
        non-terminal settlements for the same crop year: any in `DISPUTED` or
        `STALE` moves to `SUPERSEDED`. Multiple `COMPUTED` settlements for the
        same grower and crop year coexist, each having seen the same quota
        headroom at compute; `APPROVED` and `PAID` settlements are locked and
        are never superseded."

        Design: Difficulty/compensating_invariant/quota_consumption_invariant
        """
        env = setup_computed_settlement()
        s1 = env["settlement"]
        qh_id = api_client.list_quota_histories(
            ADMIN, params={"grower_id": env["grower"]["id"]}).json()["data"][0]["id"]
        api_client.approve_settlement(s1["id"], CLERK_2)
        api_client.void_settlement(s1["id"], ADMIN)

        grower_now = get_grower(env["grower"]["id"])
        s2 = compute_settlement(env["grower"]["id"], grower_now["version"])
        assert s2["supersedes_settlement_id"] is None, \
            "a VOIDED settlement is terminal — nothing is superseded"
        assert s2["quota_tons_applied"] == 23.375

        api_client.approve_settlement(s2["id"], CLERK_2)
        assert get_quota_history(qh_id)["used_quota_tons"] == 23.375


class TestSettlementOCC:

    def test_occ_settlement_create_stale_grower_version(self):
        """PRD section 2.8: "Computing a settlement for a grower requires
        `expected_grower_version`, carrying the client's last-observed
        `version` of that grower."
        PRD section 2.8: "if the supplied value does not match the parent
        entity's current `version` — because another writer has advanced that
        version since the client last read the parent — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.9: "Multiple `COMPUTED` settlements for the same grower
        and crop year coexist".

        Design: Corner/cross_cutting/occ_settlement_create_stale_grower_version
        """
        f = setup_settlement_foundation()
        setup_stored_load(f["grower"]["id"], f["warehouse"]["id"])
        gid = f["grower"]["id"]
        observed_v = f["grower"]["version"]

        s1 = compute_settlement(gid, observed_v)
        assert s1["status"] == "COMPUTED"
        assert get_grower(gid)["version"] == observed_v + 1

        resp = api_client.compute_settlement(
            gid, {"crop_year": 2026, "expected_grower_version": observed_v},
            CLERK_1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        gv2 = get_grower(gid)["version"]
        s2 = compute_settlement(gid, gv2)
        assert s2["status"] == "COMPUTED"
        assert get_settlement(s1["id"])["status"] == "COMPUTED", \
            "COMPUTED settlements coexist — supersede applies only to DISPUTED/STALE"
        assert get_grower(gid)["version"] == observed_v + 2
