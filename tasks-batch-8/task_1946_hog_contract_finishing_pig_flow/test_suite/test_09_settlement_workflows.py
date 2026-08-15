"""Close-out settlements: the tiered performance bonus with its gates, the
mortality threshold boundary, the dispute/refinalize cycle, terminal
lockdown, and approve/pay segregation.
"""
from test_helpers import (
    ApiErrorId,
    assert_settlement_pay_invariants,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import dispute_settlement_payload
from test_helpers.fixtures import (
    ADMIN,
    ADMIN2,
    FIELDTECH,
    FIELDTECH2,
    book_load,
    confirm_group,
    create_and_deliver_feed,
    create_scheduled_group,
    create_slot,
    create_ticket,
    create_verified_truck_wash,
    deliver_load,
    dispatch_load,
    get_grower,
    get_group,
    get_settlement_for_group,
    quote_ticket,
    report_mortality,
    set_clock,
    setup_closed_group_with_settlement,
    setup_paid_settlement,
    setup_placed_group,
)
from test_helpers.test_users import make_grower_headers


def _run_combo_scenario(api):
    """1000-head group: 555000 lbs feed; report (40 dead, 10 culled); a
    30000-cent NEGLIGENCE ticket completed mid-stay; a 100-head load rejected
    at the plant; then two 475-head loads closing the group on 2026-07-13."""
    ctx = setup_placed_group(head_placed=1000)
    group_id = ctx["group"]["id"]
    barn_id = ctx["barn"]["id"]
    grower_id = ctx["grower"]["id"]

    create_and_deliver_feed(group_id, 555000)
    report_mortality(group_id, grower_id, "2026-03-15", 40, cull_count=10,
                     reason_code="STRESS", clock="2026-03-15T00:00:00Z")

    # NEGLIGENCE ticket completed while the group occupies the barn: the
    # grower share (30000, the whole cost) lands on pending deductions.
    ticket = create_ticket(barn_id, grower_id, category="EQUIPMENT",
                           description="feeder motor")
    quote_ticket(ticket["id"], cost_cents=30000, cause="NEGLIGENCE",
                 quoter=FIELDTECH)
    get_success_data(api.approve_maintenance_ticket(ticket["id"], FIELDTECH2))
    get_success_data(api.start_work_maintenance_ticket(ticket["id"], FIELDTECH2))
    set_clock("2026-04-01T00:00:00Z")
    get_success_data(api.complete_maintenance_ticket(ticket["id"], FIELDTECH2))

    # Rejected load: avg 310 lbs sits outside the slot's 240-300 window.
    slot_r = create_slot(slot_date="2026-07-06", shift="AM", capacity_head=500,
                         min_weight_lbs=240, max_weight_lbs=300)
    load_r = book_load(group_id, slot_r["id"], 100)
    set_clock("2026-07-05T08:00:00Z")
    wash_r = create_verified_truck_wash("2026-07-05T08:00:00Z", truck_code="T-R")
    set_clock("2026-07-06T00:00:00Z")
    dispatch_load(load_r["id"], wash_r["id"])
    rejected = deliver_load(load_r["id"], 31000)
    assert rejected["load_status"] == "REJECTED_AT_PLANT"

    # Two closing loads on 2026-07-13, avg 285 lbs inside 240-320.
    slot_a = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                         min_weight_lbs=240, max_weight_lbs=320)
    slot_b = create_slot(slot_date="2026-07-13", shift="PM", capacity_head=500,
                         min_weight_lbs=240, max_weight_lbs=320)
    load_a = book_load(group_id, slot_a["id"], 475)
    load_b = book_load(group_id, slot_b["id"], 475)
    set_clock("2026-07-11T08:00:00Z")
    wash_a = create_verified_truck_wash("2026-07-11T08:00:00Z", truck_code="T-A")
    wash_b = create_verified_truck_wash("2026-07-11T08:00:00Z", truck_code="T-B")
    set_clock("2026-07-12T00:00:00Z")
    dispatch_load(load_a["id"], wash_a["id"])
    dispatch_load(load_b["id"], wash_b["id"])
    set_clock("2026-07-13T00:00:00Z")
    deliver_load(load_a["id"], 135375)
    deliver_load(load_b["id"], 135375)

    ctx["settlement"] = get_settlement_for_group(group_id)
    return ctx


class TestPerformanceBonusCombo:
    def test_performance_bonus_tier_adg_gate_combo(self, api):
        """PRD §3.8: "A surviving bonus is then tiered on feed conversion
        against the contract's `fcr_target`: an `fcr` at or below one-tenth
        under the target earns the full tier factor of 1.00; an `fcr` at or
        below the target itself earns 0.60; an `fcr` at or below one-tenth
        above the target earns 0.30; and anything worse earns 0.00. The tier
        is then scaled by growth: when `adg_lbs` meets or exceeds
        `adg_target_lbs` the growth factor is 1.0, otherwise 0.5."
        PRD §3.5: "a reject penalty of 1,500 cents per head shipped is added to
        the group's `pending_deductions_cents`".
        PRD §3.7: "When the cause is `NEGLIGENCE`, the owner bears nothing and
        `grower_share_cents` equals the entire `cost_cents`."

        fcr 2.49 (<= 2.60 - 0.10) earns tier 1.00; adg 1.77 < 1.90 halves it;
        mortality 4.00 <= 5.00 keeps it: 1200 * 1000 * 1.00 * 0.5 = 600000.
        Deductions = 150000 reject penalty + 30000 negligence = 180000.

        Design: Difficulty/combinatorial_formula/performance_bonus_tier_adg_gate_combo
        """
        ctx = _run_combo_scenario(api)
        s = ctx["settlement"]
        assert s["settlement_status"] == "FINALIZED"
        assert s["base_pay_cents"] == 4000000
        assert s["fcr"] == 2.49
        assert s["adg_lbs"] == 1.77
        assert s["mortality_pct"] == 4.0
        assert s["bonus_cents"] == 600000
        assert s["deductions_cents"] == 180000
        assert s["adjustment_cents"] == 0
        assert s["total_pay_cents"] == 4420000
        assert_settlement_pay_invariants(s)

    def test_bonus_full_tier_at_exact_fcr_edge_with_adg_met(self, api):
        """PRD §3.8: "an `fcr` at or below one-tenth under the target earns the
        full tier factor of 1.00; ... The tier is then scaled by growth: when
        `adg_lbs` meets or exceeds `adg_target_lbs` the growth factor is 1.0,
        otherwise 0.5. The final `bonus_cents` is the contract's
        `bonus_cap_cents_per_head` multiplied by `head_placed`, by the tier
        factor, and by the growth factor, with the whole chain rounded half-up
        to a whole cent in a single final rounding — no intermediate products
        are rounded."

        fcr exactly 2.50 == 2.60 - 0.10 earns 1.00 (inclusive edge); adg 1.95
        >= 1.90 earns 1.0: bonus = 1200 * 100 * 1.00 * 1.0 = 120000.

        Design: Difficulty/combinatorial_formula/performance_bonus_tier_adg_gate_combo
        """
        ctx = setup_closed_group_with_settlement(
            head_placed=100, live_weight_lbs_total=31000, feed_lbs=65000,
            slot_overrides={"capacity_head": 200, "min_weight_lbs": 240,
                            "max_weight_lbs": 320},
        )
        s = ctx["settlement"]
        assert s["fcr"] == 2.50
        assert s["adg_lbs"] == 1.95
        assert s["mortality_pct"] == 0.0
        assert s["bonus_cents"] == 120000
        assert s["base_pay_cents"] == 400000
        assert s["total_pay_cents"] == 520000
        assert_settlement_pay_invariants(s)


class TestMortalityThresholdBoundary:
    def _run_threshold_pair(self, api):
        """Two 1000-head groups on two barns: GB loses 50 head (5.00%), GC
        loses 51 (5.10%); both close on 2026-07-13 with fcr 2.45 / adg 1.95."""
        ctx = setup_placed_group(head_placed=1000, barn_code="B1")
        grower_id = ctx["grower"]["id"]
        contract_id = ctx["contract"]["id"]
        barn2 = get_success_data(
            api.create_barn(
                {"site_id": ctx["site"]["id"], "barn_code": "B2",
                 "capacity_head": 1200, "floor_space_sqft": 9600}, ADMIN
            ),
            201,
        )
        group_b = ctx["group"]["id"]
        gc = create_scheduled_group(barn2["id"], contract_id, head_placed=1000)
        group_c = gc["id"]
        confirm_group(group_c)

        create_and_deliver_feed(group_b, 605150)
        create_and_deliver_feed(group_c, 604513)
        report_mortality(group_b, grower_id, "2026-03-15", 50,
                         clock="2026-03-15T00:00:00Z")
        report_mortality(group_c, grower_id, "2026-03-15", 51,
                         reason_code="DISEASE")

        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=2000,
                           min_weight_lbs=240, max_weight_lbs=320)
        loads = [
            (group_b, 475, 147250, "T-1"),
            (group_b, 475, 147250, "T-2"),
            (group_c, 475, 147250, "T-3"),
            (group_c, 474, 146940, "T-4"),
        ]
        booked = [book_load(g, slot["id"], n) for g, n, _w, _t in loads]
        set_clock("2026-07-11T08:00:00Z")
        washes = [
            create_verified_truck_wash("2026-07-11T08:00:00Z", truck_code=t)
            for _g, _n, _w, t in loads
        ]
        set_clock("2026-07-12T00:00:00Z")
        for load, wash in zip(booked, washes):
            dispatch_load(load["id"], wash["id"])
        set_clock("2026-07-13T00:00:00Z")
        for load, (_g, _n, weight, _t) in zip(booked, loads):
            deliver_load(load["id"], weight)

        return (get_settlement_for_group(group_b),
                get_settlement_for_group(group_c))

    def test_mortality_threshold_exact_boundary(self, api):
        """PRD §3.8: "Otherwise, if the group's `mortality_pct` is strictly
        greater than the contract's `mortality_threshold_pct`, the bonus is
        likewise zero; a mortality percentage exactly equal to the threshold
        survives the gate."
        PRD §3.4: "The group's `mortality_pct` is one hundred times
        `mortality_total` divided by `head_placed`, rounded half-up to two
        decimal places."

        50 of 1000 = 5.00% survives (bonus 1200000); 51 of 1000 = 5.10% is
        zeroed despite identical-tier performance (fcr 2.45 -> 1.00, adg 1.95
        -> 1.0). One head of mortality moves 1200000 cents.

        Design: Difficulty/boundary_precision_check/mortality_threshold_exact_boundary
        """
        sett_b, sett_c = self._run_threshold_pair(api)
        assert sett_b["mortality_pct"] == 5.0
        assert sett_b["bonus_cents"] == 1200000
        assert sett_b["total_pay_cents"] == 5200000

        assert sett_c["mortality_pct"] == 5.1
        assert sett_c["bonus_cents"] == 0
        assert sett_c["total_pay_cents"] == 4000000
        assert_settlement_pay_invariants(sett_b)
        assert_settlement_pay_invariants(sett_c)

    def test_mortality_one_below_threshold_survives(self, api):
        """PRD §3.8: "Otherwise, if the group's `mortality_pct` is strictly
        greater than the contract's `mortality_threshold_pct`, the bonus is
        likewise zero; a mortality percentage exactly equal to the threshold
        survives the gate."

        The X-1 side: 49 of 1000 = 4.90% survives with the same tier-1.00,
        factor-1.0 performance, earning the full 1200000-cent bonus.

        Design: Difficulty/boundary_precision_check/mortality_threshold_exact_boundary
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        grower_id = ctx["grower"]["id"]
        create_and_deliver_feed(group_id, 605150)
        report_mortality(group_id, grower_id, "2026-03-15", 49,
                         clock="2026-03-15T00:00:00Z")

        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=2000,
                           min_weight_lbs=240, max_weight_lbs=320)
        l1 = book_load(group_id, slot["id"], 475)
        l2 = book_load(group_id, slot["id"], 476)
        set_clock("2026-07-11T08:00:00Z")
        w1 = create_verified_truck_wash("2026-07-11T08:00:00Z", truck_code="T-1")
        w2 = create_verified_truck_wash("2026-07-11T08:00:00Z", truck_code="T-2")
        set_clock("2026-07-12T00:00:00Z")
        dispatch_load(l1["id"], w1["id"])
        dispatch_load(l2["id"], w2["id"])
        set_clock("2026-07-13T00:00:00Z")
        deliver_load(l1["id"], 147250)
        deliver_load(l2["id"], 147560)  # 476 head * 310.0 avg

        group = get_group(group_id)
        assert group["group_status"] == "CLOSED"  # 49 + 475 + 476 == 1000
        s = get_settlement_for_group(group_id)
        assert s["mortality_pct"] == 4.9
        assert s["fcr"] == 2.45
        assert s["adg_lbs"] == 1.95
        assert s["bonus_cents"] == 1200000
        assert s["total_pay_cents"] == 5200000


class TestDisputeCycle:
    def test_settlement_dispute_cycle(self, api):
        """PRD §3.8: "The owning `Grower` may dispute a `FINALIZED` settlement,
        supplying a `reason`, moving it `FINALIZED` → `DISPUTED`; ... A
        `FieldTech` refinalizes a disputed settlement with a signed
        `adjustment_cents`, moving it back `DISPUTED` → `FINALIZED` and
        recomputing `total_pay_cents`; the dispute cycle between `FINALIZED`
        and `DISPUTED` may repeat any number of rounds."
        PRD §3.8: "The `total_pay_cents` is always `base_pay_cents` plus
        `bonus_cents` plus `adjustment_cents` minus `deductions_cents`."

        Round 1 sets +25000 (total 443000); round 2 sets -10000 — the
        adjustment is REPLACED, not accumulated (total 408000, not 433000).

        Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle
        """
        ctx = setup_closed_group_with_settlement(
            head_placed=100, live_weight_lbs_total=28000, feed_lbs=60000,
            slot_overrides={"capacity_head": 200, "min_weight_lbs": 240,
                            "max_weight_lbs": 300},
        )
        grower_id = ctx["grower"]["id"]
        s = ctx["settlement"]
        assert s["settlement_status"] == "FINALIZED"
        assert s["base_pay_cents"] == 400000
        assert s["bonus_cents"] == 18000
        assert s["total_pay_cents"] == 418000

        sid = s["id"]
        grower = make_grower_headers(grower_id)

        disputed = validate_success(
            api.dispute_settlement(
                sid, dispute_settlement_payload(reason="feed tally disputed"),
                grower,
            ),
            200,
        )
        assert disputed["settlement_status"] == "DISPUTED"

        round1 = validate_success(
            api.refinalize_settlement(sid, {"adjustment_cents": 25000}, FIELDTECH),
            200,
        )
        assert round1["settlement_status"] == "FINALIZED"
        assert round1["adjustment_cents"] == 25000
        assert round1["total_pay_cents"] == 443000

        validate_success(
            api.dispute_settlement(
                sid, dispute_settlement_payload(reason="still wrong"), grower
            ),
            200,
        )
        round2 = validate_success(
            api.refinalize_settlement(sid, {"adjustment_cents": -10000}, FIELDTECH),
            200,
        )
        assert round2["adjustment_cents"] == -10000
        assert round2["total_pay_cents"] == 408000  # replaced, not accumulated

        get_success_data(api.approve_settlement(sid, ADMIN))
        paid = validate_success(api.pay_settlement(sid, ADMIN2), 200)
        assert paid["settlement_status"] == "PAID"
        assert paid["paid_by"] == "adm_2"

        grower_after = get_grower(grower_id)
        assert grower_after["lifetime_paid_cents"] == 408000

    def test_refinalize_replaces_adjustment_to_zero(self, api):
        """PRD §3.8: "A `FieldTech` refinalizes a disputed settlement with a
        signed `adjustment_cents`, moving it back `DISPUTED` → `FINALIZED` and
        recomputing `total_pay_cents`".
        PRD §3.8: "The `adjustment_cents` starts at zero at close. The
        `total_pay_cents` is always `base_pay_cents` plus `bonus_cents` plus
        `adjustment_cents` minus `deductions_cents`."

        A +25000 round followed by a 0 round returns the settlement to exactly
        its minted total of 418000 — assignment semantics, not accumulation.

        Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle
        """
        ctx = setup_closed_group_with_settlement(
            head_placed=100, live_weight_lbs_total=28000, feed_lbs=60000,
            slot_overrides={"capacity_head": 200, "min_weight_lbs": 240,
                            "max_weight_lbs": 300},
        )
        grower = make_grower_headers(ctx["grower"]["id"])
        sid = ctx["settlement"]["id"]

        api.dispute_settlement(sid, dispute_settlement_payload(), grower)
        api.refinalize_settlement(sid, {"adjustment_cents": 25000}, FIELDTECH)
        api.dispute_settlement(sid, dispute_settlement_payload(), grower)
        zeroed = validate_success(
            api.refinalize_settlement(sid, {"adjustment_cents": 0}, FIELDTECH), 200
        )
        assert zeroed["adjustment_cents"] == 0
        assert zeroed["total_pay_cents"] == 418000


class TestTerminalAndSegregation:
    def test_settlement_paid_terminal_lockdown(self, api):
        """PRD §3.8: "An `IntegratorAdmin` pays an `APPROVED` settlement,
        moving it `APPROVED` → `PAID`." — `PAID` is the terminal state.
        PRD §2.6: "State validity. The target resource must sit in a legal
        from-state for the requested transition; failures surface as
        `ERR_INVALID_STATE_TRANSITION` or one of its domain variants".

        A dispute attempt against the PAID settlement is refused and nothing
        changes.

        Design: Corner/state_machines/settlement_paid_terminal_lockdown
        """
        ctx = setup_paid_settlement(head_placed=100, live_weight_lbs_total=28000)
        s = ctx["settlement"]
        assert s["settlement_status"] == "PAID"
        assert s["total_pay_cents"] == 460000  # base 400000 + bonus 60000

        res = api.dispute_settlement(
            s["id"], dispute_settlement_payload(reason="too late"),
            make_grower_headers(ctx["grower"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409
        )

        after = validate_success(api.get_settlement(s["id"], ADMIN), 200)
        assert after["settlement_status"] == "PAID"
        assert after["total_pay_cents"] == 460000

    def test_sod_approve_pay_same_admin_rejected(self, api):
        """PRD §3.8: "Payment is segregated from approval per §2.11: the
        payer's identity must differ from `approved_by`
        (`ERR_SEGREGATION_OF_DUTIES`), and a successful payment stamps
        `paid_by` and adds the settlement's `total_pay_cents` into the grower's
        `lifetime_paid_cents`."

        Design: Corner/rbac/sod_approve_pay_same_admin_rejected
        """
        ctx = setup_closed_group_with_settlement(
            head_placed=100, live_weight_lbs_total=28000,
        )
        grower_id = ctx["grower"]["id"]
        sid = ctx["settlement"]["id"]
        get_success_data(api.approve_settlement(sid, ADMIN))  # adm_1 approves

        res = api.pay_settlement(sid, ADMIN)  # same identity cannot pay
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        paid = validate_success(api.pay_settlement(sid, ADMIN2), 200)
        assert paid["settlement_status"] == "PAID"
        assert paid["paid_by"] == "adm_2"

        grower = get_grower(grower_id)
        assert grower["lifetime_paid_cents"] == 460000
