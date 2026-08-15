"""Payroll settlement: the DRAFT rework cycle, segregation of duties, the
pinned gross-pay evaluation order, per-charge share rounding, the weekly
guarantee boundary, and the half-open period scope (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    adjudicate_to_approved,
    api_client,
    assert_settlement,
    complete_trip,
    create_driver,
    create_manual_accessorial,
    create_settlement_for,
    create_tractor,
    dispatch_trip,
    get_trip,
    make_load_planner_headers,
    make_payroll_clerk_headers,
    plan_trip,
    screen_load,
    set_clock,
    setup_accepted_load,
    setup_dispatched_trip,
    setup_settlement_after_invoice,
    tender_load,
    validate_error,
    validate_success,
)

LOAD_PLANNER = make_load_planner_headers()
PAYROLL_1 = make_payroll_clerk_headers("payroll-1")
PAYROLL_2 = make_payroll_clerk_headers("payroll-2")


def test_settlement_reject_rework_cycle(api):
    """PRD §3.9: "Submission moves a `DRAFT` settlement to `PENDING_APPROVAL`
    (from any other state, `ERR_SETTLEMENT_NOT_DRAFT`)."
    PRD §3.9: "A settlement that needs rework is instead rejected from
    `PENDING_APPROVAL` back to `DRAFT` — again,
    `ERR_SETTLEMENT_NOT_PENDING_APPROVAL` from any other state — where
    recalculation may begin again."

    Design: Corner/state_machines/settlement_reject_rework_cycle
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-C18")
    stl = create_settlement_for(driver["id"])
    assert stl["status"] == "DRAFT"
    sid = stl["id"]
    s1 = validate_success(api_client.submit_settlement(sid, PAYROLL_1))
    assert s1["status"] == "PENDING_APPROVAL"
    s2 = validate_success(api_client.reject_settlement(sid, PAYROLL_2))
    assert s2["status"] == "DRAFT"
    s3 = validate_success(api_client.submit_settlement(sid, PAYROLL_1))
    assert s3["status"] == "PENDING_APPROVAL"


def test_mark_paid_from_draft_rejected(api):
    """PRD §3.9: "Finally, marking an `APPROVED` settlement paid — from any
    other state, `ERR_SETTLEMENT_NOT_APPROVED` — lands it in the terminal
    `PAID` state."

    Design: Corner/state_machines/settlement_mark_paid_from_draft_rejected
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-C19")
    stl = create_settlement_for(driver["id"])
    resp = api_client.mark_settlement_paid(stl["id"], PAYROLL_2)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_APPROVED)


def test_submit_and_recalculate_are_draft_only(api):
    """PRD §3.9: "The recalculation is OCC-guarded by
    `expected_settlement_version` per §2.8 and increments the settlement's
    `version`; recalculating in any other status is rejected with
    `ERR_SETTLEMENT_NOT_DRAFT`. Submission moves a `DRAFT` settlement to
    `PENDING_APPROVAL` (from any other state, `ERR_SETTLEMENT_NOT_DRAFT`)."

    Design: Corner/errors/settlement_draft_only_guards
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-R11")
    stl = create_settlement_for(driver["id"])
    sid = stl["id"]
    validate_success(api_client.submit_settlement(sid, PAYROLL_1))
    validate_error(api_client.submit_settlement(sid, PAYROLL_1),
                   ApiErrorId.ERR_SETTLEMENT_NOT_DRAFT)
    resp = api_client.recalculate_settlement(
        sid, {"expected_settlement_version": stl["version"]}, PAYROLL_1)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_DRAFT)


def test_self_approval_violates_segregation_of_duty(api):
    """PRD §3.9: "Approval is where segregation of duties bites: the approver's
    `X-User-ID` must differ from the settlement's `created_by_id`, and a
    self-approval is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403)".
    PRD §3.9: "A successful approval stamps `approved_by_id` with the
    approver's `X-User-ID` and moves the settlement to `APPROVED`."

    Design: Corner/validations/sod_same_user_approve_rejected
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-V9")
    stl = create_settlement_for(driver["id"], user_id="payroll-1")
    assert stl["created_by_id"] == "payroll-1"
    sid = stl["id"]
    validate_success(api_client.submit_settlement(sid, PAYROLL_1))
    validate_error(api_client.approve_settlement(sid, PAYROLL_1),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTY)
    approved = validate_success(api_client.approve_settlement(sid, PAYROLL_2))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_id"] == "payroll-2"


def test_settlement_full_lifecycle_to_paid(api):
    """PRD §3.9: "A successful approval stamps `approved_by_id` with the
    approver's `X-User-ID` and moves the settlement to `APPROVED`."
    PRD §3.9: "Finally, marking an `APPROVED` settlement paid — from any other
    state, `ERR_SETTLEMENT_NOT_APPROVED` — lands it in the terminal `PAID`
    state." (Reject from PAID: `ERR_SETTLEMENT_NOT_PENDING_APPROVAL`.)

    Design: Corner/rbac/settlement_full_lifecycle_to_paid
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-B5")
    stl = create_settlement_for(driver["id"], user_id="payroll-1")
    sid = stl["id"]
    s1 = validate_success(api_client.submit_settlement(sid, PAYROLL_1))
    assert s1["status"] == "PENDING_APPROVAL"
    s2 = validate_success(api_client.approve_settlement(sid, PAYROLL_2))
    assert s2["status"] == "APPROVED"
    assert s2["approved_by_id"] == "payroll-2"
    s3 = validate_success(api_client.mark_settlement_paid(sid, PAYROLL_2))
    assert s3["status"] == "PAID"
    validate_error(api_client.reject_settlement(sid, PAYROLL_2),
                   ApiErrorId.ERR_SETTLEMENT_NOT_PENDING_APPROVAL)


def test_trip_completing_at_period_end_belongs_to_next_period(api):
    """PRD §3.9: "Trips in scope are the driver's trips in `COMPLETED` status
    whose `completed_at` falls at or after `period_start` and strictly before
    `period_end` — a trip completing exactly at `period_end` belongs to the
    next period."
    PRD §3.9: "Only then does the weekly minimum apply: when the driver is not
    `TERMINATED` and at least one `COMPLETED` trip falls in scope,
    `guarantee_top_up_cents` is the greater of zero and 120000 cents — a $1,200
    weekly floor — minus the subtotal; in every other case it is zero".

    Design: Corner/calculations/settlement_half_open_window_boundary
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-C31", unit_number="T-C31")
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"],
                  clock_to="2026-08-08T00:00:00Z",
                  arrive_delivery_at="2026-08-07T23:00:00Z",
                  delivered_at="2026-08-08T00:00:00Z")
    trip = get_trip(ctx["trip"]["id"])
    assert trip["final_pay_cents"] == 65100

    s1 = create_settlement_for(ctx["driver"]["id"],
                               period_start="2026-08-01T00:00:00Z",
                               period_end="2026-08-08T00:00:00Z")
    assert_settlement(s1)
    assert s1["trip_pay_cents"] == 0, "trip completing exactly at period_end is out"
    assert s1["guarantee_top_up_cents"] == 0, "no trip in scope -> not eligible"
    assert s1["gross_pay_cents"] == 0

    s2 = create_settlement_for(ctx["driver"]["id"],
                               period_start="2026-08-08T00:00:00Z",
                               period_end="2026-08-15T00:00:00Z")
    assert_settlement(s2)
    assert s2["trip_pay_cents"] == 65100
    assert s2["guarantee_top_up_cents"] == 54900
    assert s2["gross_pay_cents"] == 120000


# ---------------------------------------------------------------------------
# Two-lumper chain: per-charge rounding of the driver's accessorial share
# ---------------------------------------------------------------------------

def _two_completed_lumper_loads():
    """Driver completes two 350-actual-mile trips (final pay 21700 each), each
    load carrying one BILLED LUMPER of 3013 cents."""
    ctx = setup_accepted_load(
        lane_overrides={"origin_state": "TX", "destination_state": "LA",
                        "loaded_miles": 300, "rpm_floor_cents": 100},
        load_overrides={"rate_cents": 100000, "weight_lbs": 30000,
                        "pickup_appt_at": "2026-08-02T08:00:00Z",
                        "delivery_appt_at": "2026-08-02T20:00:00Z"})
    driver = create_driver(cdl_number="CDL-4")
    tractor = create_tractor(unit_number="T-4", odometer_miles=200000)
    route = [{"state_code": "TX", "miles": 200},
             {"state_code": "LA", "miles": 150}]

    for day, odo_base in (("2026-08-02", 200000), ("2026-08-03", 200350)):
        load = ctx["load"] if day == "2026-08-02" else tender_load(
            ctx["customer"]["id"], ctx["lane"]["id"], rate_cents=100000,
            weight_lbs=30000, pickup_appt_at=f"{day}T08:00:00Z",
            delivery_appt_at=f"{day}T20:00:00Z")
        if day != "2026-08-02":
            screen_load(load["id"])
            validate_success(api_client.accept_load(load["id"], LOAD_PLANNER))
        trip = plan_trip(load["id"], driver["id"], tractor["id"],
                         planned_deadhead_miles=50,
                         planned_start_at=f"{day}T06:00:00Z",
                         route_states=route)
        dispatch_trip(trip["id"])
        complete_trip(trip["id"], driver["id"],
                      clock_to=f"{day}T19:30:00Z",
                      arrive_pickup_at=f"{day}T08:00:00Z",
                      depart_pickup_at=f"{day}T09:00:00Z",
                      arrive_delivery_at=f"{day}T19:00:00Z",
                      delivered_at=f"{day}T19:30:00Z",
                      odometer_pickup=odo_base + 50,
                      odometer_delivery=odo_base + 350,
                      delivery_state="LA")
        done = get_trip(trip["id"])
        assert done["final_pay_cents"] == 21700, "350 * 62"
        charge = create_manual_accessorial(load["id"], type="LUMPER",
                                           quantity=3013)
        adjudicate_to_approved(charge["id"])
        invoice = validate_success(
            api_client.create_load_invoice(load["id"], LOAD_PLANNER),
            expected_status=201)
        validate_success(api_client.issue_invoice(invoice["id"], LOAD_PLANNER))
    ctx["driver"] = driver
    return ctx


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / settlement_per_charge_rounding_order
# ---------------------------------------------------------------------------

def test_accessorial_share_rounds_per_charge_then_sums(api):
    """PRD §3.9: "for each `BILLED` AccessorialCharge, the `amount_cents` is
    multiplied by 2500 basis points — twenty-five percent — and rounded half up
    to whole cents per charge, and only then are the per-charge amounts summed;
    summing first and rounding once would produce a different, non-conforming
    figure."
    (Two LUMPERs of 3013: 753 + 753 = 1506; sum-then-round would give
    round_half_up(6026 * 0.25) = 1507.)

    Design: Difficulty/combinatorial_formula/settlement_per_charge_rounding_order
    """
    ctx = _two_completed_lumper_loads()
    stl = create_settlement_for(ctx["driver"]["id"])
    assert stl["accessorial_share_cents"] == 1506


def test_per_charge_share_feeds_guarantee_top_up(api):
    """PRD §3.9: "The subtotal is `trip_pay_cents` plus
    `accessorial_share_cents` plus `manual_adjustment_cents`, and it is
    computed first, deliberately excluding any guarantee. Only then does the
    weekly minimum apply: when the driver is not `TERMINATED` and at least one
    `COMPLETED` trip falls in scope, `guarantee_top_up_cents` is the greater of
    zero and 120000 cents — a $1,200 weekly floor — minus the subtotal".
    PRD §3.9: "in every other case it is zero, and a subtotal of exactly 120000
    cents yields a top-up of zero. `gross_pay_cents` is the subtotal plus the
    top-up."
    (43400 + 1506 = 44906; top-up 120000 - 44906 = 75094; gross 120000.)

    Design: Difficulty/combinatorial_formula/settlement_per_charge_rounding_order
    """
    ctx = _two_completed_lumper_loads()
    stl = create_settlement_for(ctx["driver"]["id"])
    assert_settlement(stl)
    assert stl["trip_pay_cents"] == 43400
    assert stl["guarantee_top_up_cents"] == 75094
    assert stl["gross_pay_cents"] == 120000


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / settlement_guarantee_topup_evaluation_order
# ---------------------------------------------------------------------------

def test_top_up_computed_against_subtotal_excluding_itself(api):
    """PRD §3.9: "The subtotal is `trip_pay_cents` plus
    `accessorial_share_cents` plus `manual_adjustment_cents`, and it is
    computed first, deliberately excluding any guarantee. Only then does the
    weekly minimum apply: when the driver is not `TERMINATED` and at least one
    `COMPLETED` trip falls in scope, `guarantee_top_up_cents` is the greater of
    zero and 120000 cents — a $1,200 weekly floor — minus the subtotal".
    (65100 + 1500 = 66600; top-up 120000 - 66600 = 53400.)

    Design: Difficulty/combinatorial_formula/settlement_guarantee_topup_evaluation_order
    """
    ctx = setup_settlement_after_invoice(cdl_number="CDL-5", unit_number="T-5")
    stl = ctx["settlement"]
    assert_settlement(stl)
    assert stl["trip_pay_cents"] == 65100
    assert stl["accessorial_share_cents"] == 1500
    assert stl["guarantee_top_up_cents"] == 53400


def test_gross_equals_subtotal_plus_top_up(api):
    """PRD §3.9: "The subtotal is `trip_pay_cents` plus
    `accessorial_share_cents` plus `manual_adjustment_cents`, and it is
    computed first, deliberately excluding any guarantee."
    PRD §3.9: "in every other case it is zero, and a subtotal of exactly 120000
    cents yields a top-up of zero. `gross_pay_cents` is the subtotal plus the
    top-up."
    (66600 + 53400 = 120000; the guarantee absorbs the shortfall exactly.)

    Design: Difficulty/combinatorial_formula/settlement_guarantee_topup_evaluation_order
    """
    ctx = setup_settlement_after_invoice(cdl_number="CDL-5", unit_number="T-5")
    stl = ctx["settlement"]
    assert stl["gross_pay_cents"] == 120000
    assert stl["gross_pay_cents"] == (
        stl["trip_pay_cents"] + stl["accessorial_share_cents"]
        + stl["manual_adjustment_cents"] + stl["guarantee_top_up_cents"])


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / settlement_guarantee_exact_minimum_boundary
# ---------------------------------------------------------------------------

def _setup_exact_minimum_settlement():
    """PERCENTAGE 4000bp driver; rate 300000; national pump at the 300-cent
    baseline (FSC 0) -> final pay exactly 120000, subtotal exactly at the
    weekly minimum."""
    ctx = setup_accepted_load(rate_cents=300000, pump_price_cents=300)
    assert ctx["load"]["fuel_surcharge_cents"] == 0
    ctx["driver"] = create_driver(cdl_number="CDL-13", pay_model="PERCENTAGE",
                                  pay_percentage_bp=4000)
    ctx["tractor"] = create_tractor(unit_number="T-15")
    ctx["trip"] = plan_trip(ctx["load"]["id"], ctx["driver"]["id"],
                            ctx["tractor"]["id"])
    dispatch_trip(ctx["trip"]["id"])
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"],
                  clock_to="2026-08-03T19:00:00Z",
                  arrive_pickup_at="2026-08-02T08:00:00Z",
                  depart_pickup_at="2026-08-02T09:00:00Z",
                  arrive_delivery_at="2026-08-03T17:00:00Z",
                  delivered_at="2026-08-03T19:00:00Z",
                  odometer_delivery=101000)
    trip = get_trip(ctx["trip"]["id"])
    assert trip["final_pay_cents"] == 120000
    return ctx


def test_subtotal_exactly_at_minimum_yields_zero_top_up(api):
    """PRD §3.9: "in every other case it is zero, and a subtotal of exactly
    120000 cents yields a top-up of zero."
    PRD §3.2: "the excess is the amount by which the national row's
    `avg_pump_price_cents` exceeds that baseline, floored at zero, so a
    national average at or below 300 cents yields no surcharge at all."

    Design: Difficulty/boundary_precision_check/settlement_guarantee_exact_minimum_boundary
    """
    ctx = _setup_exact_minimum_settlement()
    stl = create_settlement_for(ctx["driver"]["id"])
    assert_settlement(stl)
    assert stl["trip_pay_cents"] == 120000
    assert stl["guarantee_top_up_cents"] == 0


def test_gross_pinned_at_weekly_minimum_boundary(api):
    """PRD §3.9: "Only then does the weekly minimum apply: when the driver is
    not `TERMINATED` and at least one `COMPLETED` trip falls in scope,
    `guarantee_top_up_cents` is the greater of zero and 120000 cents — a $1,200
    weekly floor — minus the subtotal". (Subtotal exactly at the floor -> gross
    equals the floor, 120000.)

    Design: Difficulty/boundary_precision_check/settlement_guarantee_exact_minimum_boundary
    """
    ctx = _setup_exact_minimum_settlement()
    stl = create_settlement_for(ctx["driver"]["id"])
    assert stl["gross_pay_cents"] == 120000
