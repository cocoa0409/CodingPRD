"""Settlement amounts: provisional vs final variants and branch composition.

Covers PRD §3.6: provisional settlement at depart (base, backhaul discount,
pinned rounding order) and final settlement at delivery (shrink allowance,
excess shrink penalty, welfare deduction, money identity).
"""
from test_helpers import (
    TEST_USERS,
    assert_ts_eq,
    make_driver_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    allocate_all,
    assign_driver,
    attach_and_verify_paperwork,
    close_incident,
    create_load,
    create_shipper,
    get_load,
    get_settlement_of_load,
    plan_load,
    record_delivery_ticket,
    report_incident,
    set_clock,
    setup_delivered_load,
    setup_in_transit_load,
    start_review,
    wash_trailer,
)

ADMIN = TEST_USERS["admin_headers"]
CONSIGNEE = TEST_USERS["consignee_headers"]


def _build_backhaul_trip(api, first):
    """Create a valid backhaul of `first`'s delivered load on the same trailer
    and driver, then depart it. Clock discipline: only moves forward."""
    set_clock("2026-08-01T13:00:00Z")
    wash_trailer(first["trailer"]["id"], washed_at="2026-08-01T13:00:00Z",
                 method="STEAM")
    backhaul = create_load(
        first["shipper"]["id"], origin="Dodge City KS",
        destination="Amarillo TX",
        planned_departure_at="2026-08-02T08:00:00Z",
        backhaul_of_load_id=first["load"]["id"])
    allocate_all(backhaul, [c["id"] for c in first["compartments"]])
    plan_load(backhaul["id"])
    set_clock("2026-08-01T20:00:00Z")
    attach_and_verify_paperwork(get_load(backhaul["id"]))
    assign_driver(backhaul["id"], first["driver"]["id"])
    set_clock("2026-08-02T08:00:00Z")
    validate_success(
        api.depart(backhaul["id"], {"origin_temperature_f": 70},
                   make_driver_headers(first["driver"]["id"])), 200)
    return backhaul


def _first_delivered_trip():
    """A 20-head / 20000 lb trip Guymon OK -> Dodge City KS, delivered at
    2026-08-01T12:00:00Z. The clock sequence is strictly forward: paperwork is
    attached at 01:00 with a brand inspection dated 2026-07-31."""
    return setup_delivered_load(
        head_count=20, weight_lb=20000,
        origin="Guymon OK", destination="Dodge City KS",
        planned_departure_at="2026-08-01T06:00:00Z",
        planned_duration_hours=6, loaded_miles=400,
        brand_inspected_at="2026-07-31T05:00:00Z",
        paperwork_clock="2026-08-01T01:00:00Z",
        depart_at="2026-08-01T06:00:00Z",
        arrive_at="2026-08-01T11:00:00Z",
        weighed_at="2026-08-01T10:30:00Z",
        deliver_at="2026-08-01T12:00:00Z")


class TestProvisionalVsFinalDivergence:
    def test_provisional_at_depart_assumes_on_weight_delivery(self, api):
        """PRD §3.6: "`provisional_amount_cents` equals `base_amount_cents`: the
        provisional figure assumes an on-weight delivery, with no shrink penalty
        and no welfare deduction."
        PRD §3.6: "Its `base_amount_cents` is the load's
        `rate_per_loaded_mile_cents` multiplied by `loaded_miles`, rounded half
        up to integer cents; when `is_backhaul` is true, that rounded product is
        then multiplied by 0.85 — a 15 percent backhaul discount — and rounded
        half up again."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_excess_shrink
        """
        ctx = setup_in_transit_load()
        settlement = get_settlement_of_load(ctx["load"]["id"])
        assert settlement["status"] == "PRELIMINARY"
        assert settlement["base_amount_cents"] == 150000  # 300 c/mi * 500 mi
        assert settlement["provisional_amount_cents"] == 150000

    def test_final_after_delivery_applies_excess_shrink_branch(self, api):
        """PRD §3.6: "The load's shrink allowance in pounds,
        `shrink_allowance_lb`, is `declared_weight_lb` multiplied by
        `effective_shrink_pct` and divided by 100, rounded half up to a whole
        pound. `shrink_lb` is the shortfall — `declared_weight_lb` minus
        `effective_delivered_weight_lb`, floored at zero. `excess_shrink_lb` is
        the part of the shortfall beyond the allowance — `shrink_lb` minus
        `shrink_allowance_lb`, floored at zero. The `shrink_penalty_cents` is
        `excess_shrink_lb` multiplied by 2.5 cents per pound, rounded half up."
        PRD §3.6: "The `final_amount_cents` is `provisional_amount_cents` minus
        `shrink_penalty_cents` minus `welfare_deduction_cents`, floored at
        zero."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_excess_shrink
        """
        # 40 head / 40000 lb, rate 300 c/mi x 500 mi, shipper default 2.0%
        # delivered at net 38800 lb -> allowance 800, shrink 1200, excess 400
        ctx = setup_delivered_load(net_lb=38800)
        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["provisional_amount_cents"] == 150000
        assert s["base_amount_cents"] == 150000
        assert s["shrink_allowance_lb"] == 800
        assert s["shrink_lb"] == 1200
        assert s["excess_shrink_lb"] == 400
        assert s["shrink_penalty_cents"] == 1000
        assert s["final_amount_cents"] == 149000
        # variant divergence: the final variant applies the excess-shrink
        # branch that the provisional variant structurally ignores
        assert s["final_amount_cents"] != s["provisional_amount_cents"]
        assert s["provisional_amount_cents"] - s["final_amount_cents"] == 1000
        assert s["status"] == "PENDING"
        assert_ts_eq(s["dispute_deadline_at"], "2026-08-04T16:30:00Z",
                     "dispute_deadline_at")


class TestCombinatorialBranches:
    def test_backhaul_discount_applies_15_percent_to_rounded_base(self, api):
        """PRD §3.6: "Its `base_amount_cents` is the load's
        `rate_per_loaded_mile_cents` multiplied by `loaded_miles`, rounded half
        up to integer cents; when `is_backhaul` is true, that rounded product is
        then multiplied by 0.85 — a 15 percent backhaul discount — and rounded
        half up again. The rounding order is pinned: round the rate-times-miles
        product first, then apply the discount and round again; discounting the
        rate before multiplying yields different cents and is forbidden."
        PRD §3.3: "When the link is valid, the load's derived `is_backhaul` is
        true, and the settlement created at departure applies the backhaul
        discount described in §3.6."

        Design: Difficulty/combinatorial_formula/settlement_final_combines_backhaul_shrink_welfare_branches
        """
        first = _first_delivered_trip()
        backhaul = _build_backhaul_trip(api, first)

        assert get_load(backhaul["id"])["is_backhaul"] is True
        s = get_settlement_of_load(backhaul["id"])
        # round_half_up(300 * 500) = 150000, then round_half_up(150000 * 0.85)
        assert s["base_amount_cents"] == 127500
        assert s["provisional_amount_cents"] == 127500

    def test_final_combines_backhaul_excess_shrink_and_welfare_branches(
            self, api):
        """PRD §3.6: "Final settlement is computed at delivery, at a reweigh
        while `PENDING`, at dispute resolution, and at every incident close."
        PRD §3.6: "The `welfare_deduction_cents` sums `fine_cents` over the
        load's closed, non-waived welfare incidents. The `final_amount_cents` is
        `provisional_amount_cents` minus `shrink_penalty_cents` minus
        `welfare_deduction_cents`, floored at zero."
        PRD §3.7: "Otherwise the fine is a per-incident-type base in cents —
        33333 for `INJURY`, 41667 for `DOWNER`, 100000 for `DEAD_ON_ARRIVAL`,
        25000 for `ESCAPE` — multiplied by `head_count_affected` and by a
        severity multiplier — 1.5 for `MINOR`, 2.5 for `MAJOR`, 4.0 for
        `CRITICAL` — with the product rounded half up to whole cents for each
        incident before any summation."

        Design: Difficulty/combinatorial_formula/settlement_final_combines_backhaul_shrink_welfare_branches
        """
        first = _first_delivered_trip()
        backhaul = _build_backhaul_trip(api, first)
        driver_id = first["driver"]["id"]

        # welfare incident in transit: ESCAPE / MINOR / 1 head
        set_clock("2026-08-02T09:30:00Z")
        incident = report_incident(
            backhaul["id"], driver_id, incident_type="ESCAPE",
            severity="MINOR", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")

        # deliver 2000 lb short of the 40000 lb declaration
        set_clock("2026-08-02T18:00:00Z")
        validate_success(api.arrive(backhaul["id"],
                                    make_driver_headers(driver_id)), 200)
        record_delivery_ticket(backhaul["id"], 38000,
                               weighed_at="2026-08-02T17:30:00Z")
        set_clock("2026-08-02T18:30:00Z")
        validate_success(api.deliver(backhaul["id"], CONSIGNEE), 200)

        # close the incident after delivery: the settlement is not PAID, so it
        # is repriced with the welfare deduction
        start_review(incident["id"])
        closed = close_incident(incident["id"])

        s = get_settlement_of_load(backhaul["id"])
        assert get_load(backhaul["id"])["is_backhaul"] is True
        assert s["base_amount_cents"] == 127500
        assert s["provisional_amount_cents"] == 127500
        # allowance 800; shrink 2000; excess 1200 -> 1200 * 2.5 = 3000
        assert s["excess_shrink_lb"] == 1200
        assert s["shrink_penalty_cents"] == 3000
        # round_half_up(25000 * 1 * 1.5) = 37500
        assert closed["fine_cents"] == 37500
        assert s["welfare_deduction_cents"] == 37500
        # 127500 - 3000 - 37500
        assert s["final_amount_cents"] == 87000


class TestShrinkBoundaryAndResolution:
    def test_shrink_boundary_exactly_at_allowance_no_penalty(self, api):
        """PRD §3.6: "`shrink_lb` is the shortfall — `declared_weight_lb` minus
        `effective_delivered_weight_lb`, floored at zero. `excess_shrink_lb` is
        the part of the shortfall beyond the allowance — `shrink_lb` minus
        `shrink_allowance_lb`, floored at zero."
        PRD §3.6: "The `final_amount_cents` is `provisional_amount_cents` minus
        `shrink_penalty_cents` minus `welfare_deduction_cents`, floored at
        zero."

        Design: Corner/calculations/shrink_boundary_exactly_at_allowance_no_penalty
        """
        # 2.5% override on 40000 lb -> allowance 1000; delivery at exactly
        # declared - allowance leaves zero excess and zero penalty.
        ctx = setup_delivered_load(net_lb=39000, shrink_allowance_pct=2.5)
        s = ctx["settlement"]
        assert s["shrink_allowance_lb"] == 1000
        assert s["shrink_lb"] == 1000
        assert s["excess_shrink_lb"] == 0
        assert s["shrink_penalty_cents"] == 0
        assert s["final_amount_cents"] == 150000

    def test_effective_shrink_pct_override_beats_shipper_default(self, api):
        """PRD §3.3: "Shrink resolution happens at creation:
        `effective_shrink_pct` is the load's own `shrink_allowance_pct` when one
        was provided, and the shipper's `default_shrink_allowance_pct`
        otherwise."

        Design: Corner/calculations/effective_shrink_pct_override_beats_shipper_default
        """
        shipper = create_shipper()  # omitted default -> 2.0
        with_override = create_load(shipper["id"], declared_head_count=10,
                                    declared_weight_lb=10000,
                                    planned_duration_hours=5,
                                    loaded_miles=100, shrink_allowance_pct=3.0)
        without_override = create_load(shipper["id"], declared_head_count=10,
                                       declared_weight_lb=10000,
                                       planned_duration_hours=5,
                                       loaded_miles=100)
        assert with_override["effective_shrink_pct"] == 3.0
        assert without_override["effective_shrink_pct"] == 2.0


class TestWelfareFineRounding:
    def test_welfare_fine_rounds_half_up_per_incident(self, api):
        """PRD §3.7: "Otherwise the fine is a per-incident-type base in cents —
        33333 for `INJURY`, 41667 for `DOWNER`, 100000 for `DEAD_ON_ARRIVAL`,
        25000 for `ESCAPE` — multiplied by `head_count_affected` and by a
        severity multiplier — 1.5 for `MINOR`, 2.5 for `MAJOR`, 4.0 for
        `CRITICAL` — with the product rounded half up to whole cents for each
        incident before any summation."
        PRD §3.7: "Chain link 1: when the load's settlement exists and is not
        `PAID`, its `welfare_deduction_cents` is recomputed as the sum of
        `fine_cents` over the load's closed, non-waived incidents, and
        `final_amount_cents` is recomputed per §3.6."

        Design: Difficulty/combinatorial_formula/welfare_fine_aggregates_per_incident_rounded_values
        """
        # on-weight delivery (no shrink penalty); one INJURY/MINOR/1-head
        # incident reported in transit, closed after delivery
        ctx = setup_in_transit_load()
        set_clock("2026-08-02T10:00:00Z")
        incident = report_incident(
            ctx["load"]["id"], ctx["driver"]["id"], incident_type="INJURY",
            severity="MINOR", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")
        set_clock("2026-08-02T16:00:00Z")
        validate_success(
            api.arrive(ctx["load"]["id"],
                       make_driver_headers(ctx["driver"]["id"])), 200)
        record_delivery_ticket(ctx["load"]["id"], 40000)
        set_clock("2026-08-02T16:30:00Z")
        validate_success(api.deliver(ctx["load"]["id"], CONSIGNEE), 200)

        start_review(incident["id"])
        closed = close_incident(incident["id"])
        # round_half_up(33333 * 1 * 1.5) = round_half_up(49999.5) = 50000
        assert closed["fine_cents"] == 50000

        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["welfare_deduction_cents"] == 50000
        assert s["shrink_penalty_cents"] == 0
        # 150000 - 0 - 50000
        assert s["final_amount_cents"] == 100000

    def test_welfare_fine_aggregates_per_incident_rounded_values(self, api):
        """PRD §2.8: "Two pinning rules eliminate ambiguity in compound
        calculations. First, rounding is applied per line before summation:
        each allocation's `weight_lb` is rounded to a whole pound before load
        and compartment totals are summed, and each incident's `fine_cents` is
        rounded to whole cents before a settlement's welfare deduction is
        summed."
        PRD §3.7: "Otherwise the fine is a per-incident-type base in cents —
        33333 for `INJURY`, 41667 for `DOWNER`, 100000 for `DEAD_ON_ARRIVAL`,
        25000 for `ESCAPE` — multiplied by `head_count_affected` and by a
        severity multiplier — 1.5 for `MINOR`, 2.5 for `MAJOR`, 4.0 for
        `CRITICAL` — with the product rounded half up to whole cents for each
        incident before any summation."

        Design: Difficulty/combinatorial_formula/welfare_fine_aggregates_per_incident_rounded_values
        """
        # two INJURY/MINOR/1-head incidents on an on-weight delivery
        ctx = setup_in_transit_load()
        set_clock("2026-08-02T10:00:00Z")
        i1 = report_incident(ctx["load"]["id"], ctx["driver"]["id"],
                             incident_type="INJURY", severity="MINOR",
                             head_count_affected=1,
                             occurred_at="2026-08-02T09:00:00Z")
        i2 = report_incident(ctx["load"]["id"], ctx["driver"]["id"],
                             incident_type="INJURY", severity="MINOR",
                             head_count_affected=1,
                             occurred_at="2026-08-02T09:30:00Z")
        set_clock("2026-08-02T16:00:00Z")
        validate_success(
            api.arrive(ctx["load"]["id"],
                       make_driver_headers(ctx["driver"]["id"])), 200)
        record_delivery_ticket(ctx["load"]["id"], 40000)
        set_clock("2026-08-02T16:30:00Z")
        validate_success(api.deliver(ctx["load"]["id"], CONSIGNEE), 200)

        start_review(i1["id"])
        c1 = close_incident(i1["id"])
        start_review(i2["id"])
        c2 = close_incident(i2["id"])

        # each incident rounds half up to 50000 BEFORE the summation; the
        # forbidden sum-then-round order would yield 99999 instead of 100000
        assert c1["fine_cents"] == 50000
        assert c2["fine_cents"] == 50000

        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["welfare_deduction_cents"] == 100000
        assert s["shrink_penalty_cents"] == 0
        assert s["final_amount_cents"] == 50000


class TestBackhaulWindow:
    def test_backhaul_window_exactly_72h_allowed_and_1_minute_over_rejected(
            self, api):
        """PRD §3.3: "The target load must be `DELIVERED`; the target's
        `destination` must equal this load's `origin`; the target's
        `delivered_at` must be at or before this load's `planned_departure_at`;
        and the gap between that delivery and this planned departure must not
        exceed 72 hours — a gap of exactly 72 hours is acceptable. Any failure
        is rejected with `ERR_INVALID_BACKHAUL_LINK` (HTTP 422)."

        Design: Corner/calculations/backhaul_window_exactly_72h_allowed_and_1_minute_over_rejected
        """
        first = _first_delivered_trip()  # delivered 2026-08-01T12:00:00Z

        # exactly 72 hours after the target's delivery: acceptable
        ok = validate_success(
            api.create_load(
                {"shipper_id": first["shipper"]["id"], "species": "CATTLE",
                 "declared_head_count": 10, "declared_weight_lb": 10000,
                 "origin": "Dodge City KS", "destination": "Amarillo TX",
                 "planned_departure_at": "2026-08-04T12:00:00Z",
                 "planned_duration_hours": 5, "rate_per_loaded_mile_cents": 250,
                 "loaded_miles": 200,
                 "backhaul_of_load_id": first["load"]["id"]},
                TEST_USERS["dispatcher_headers"]), 201)
        assert ok["is_backhaul"] is True

        # 72 hours + 1 minute: outside the window
        resp = api.create_load(
            {"shipper_id": first["shipper"]["id"], "species": "CATTLE",
             "declared_head_count": 10, "declared_weight_lb": 10000,
             "origin": "Dodge City KS", "destination": "Amarillo TX",
             "planned_departure_at": "2026-08-04T12:01:00Z",
             "planned_duration_hours": 5, "rate_per_loaded_mile_cents": 250,
             "loaded_miles": 200,
             "backhaul_of_load_id": first["load"]["id"]},
            TEST_USERS["dispatcher_headers"])
        validate_error(resp, E.ERR_INVALID_BACKHAUL_LINK)


class TestDepartSettlementVisibility:
    def test_depart_creates_settlement_visible_immediately(self, api):
        """PRD §2.9: "Derived fields are never cached stale: every derived value
        described in §3 is recomputed within the request that triggers it, and
        reads of a driver or a trailer recompute that resource's derived fields
        at read time."
        PRD §3.6: "The settlement is created at departure in `PRELIMINARY`, one
        per load — its `load_id` is unique."

        Design: Corner/consistency_model/depart_creates_settlement_visible_immediately
        """
        ctx = setup_in_transit_load()
        rows = validate_success(
            api.get_load_settlement(ctx["load"]["id"], ADMIN))
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["status"] == "PRELIMINARY"
        assert rows[0]["provisional_amount_cents"] == 150000
        assert rows[0]["dispute_deadline_at"] is None
