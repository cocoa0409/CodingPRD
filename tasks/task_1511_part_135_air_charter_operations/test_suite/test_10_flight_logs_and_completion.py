"""Flight logging, the automatic completion cascade, and the dual
quote-vs-final pricing divergence."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    add_leg, create_assignment, create_trip, post_flight_log,
    setup_quoted_trip, setup_dispatched_trip, setup_completed_trip,
    make_ops_admin_headers, make_sales_agent_headers,
    make_dispatch_manager_headers, make_crew_member_headers,
)

OPS_ADMIN = make_ops_admin_headers()
SALES_AGENT = make_sales_agent_headers()
DISPATCH_MANAGER = make_dispatch_manager_headers()


def _pic_headers(ctx):
    """Identity-bound headers: the trip's VETTED PIC (PRD §3.9)."""
    return make_crew_member_headers(ctx["crew"]["id"])


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / flight_log_final_leg_cascade
# ---------------------------------------------------------------------------

def _cascade_scenario():
    """Trip1 (dep 2026-08-10T10:00:00Z, one 60min leg) dispatched on a tail
    with initial 5940 / due 6000; trip2 QUOTED with a TENTATIVE assignment on
    the same tail."""
    ctx = setup_dispatched_trip(
        aircraft_overrides={"tail_number": "N400HH", "initial_airframe_minutes": 5940,
                            "next_check_due_minutes": 6000},
        legs=((60, "REVENUE", False),), customer_name="Cust H1")
    trip2, _legs2 = setup_quoted_trip(legs=((60, "REVENUE", False),),
                                      departure_at="2026-08-12T10:00:00Z",
                                      customer_name="Cust H2")
    asg2 = create_assignment(trip2["id"], ctx["aircraft"]["id"])
    assert asg2["status"] == "TENTATIVE"
    return ctx, asg2


def test_final_leg_log_completes_trip_and_holds_aircraft(api):
    """PRD §3.9: "Completion is automatic: the moment every quote leg of the
    trip has exactly one flight log, the trip moves from `DISPATCHED` to
    `COMPLETED` and the settlement machinery runs."
    PRD §3.9: "if, after accumulating the logged minutes,
    `total_airframe_minutes` has reached or passed `next_check_due_minutes`,
    or an `ACTIVE` maintenance window exists on the tail, the aircraft moves
    from `IN_TRIP` to `MAINTENANCE_HOLD` and every `TENTATIVE` assignment on
    that tail is released; otherwise it returns to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/flight_log_final_leg_cascade
    """
    ctx, _asg2 = _cascade_scenario()
    post_flight_log(ctx["trip"]["id"], ctx["legs"][0]["id"], 60,
                    "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
                    ctx["crew"]["id"])
    trip = validate_success(api_client.get_trip_request(ctx["trip"]["id"], OPS_ADMIN), 200)
    assert trip["status"] == "COMPLETED"
    # Final price: max(60, 60) * 240000 / 60 = 240000 (no discount/surcharge).
    assert trip["final_total_cents"] == 240000
    aircraft = validate_success(api_client.get_aircraft(ctx["aircraft"]["id"], OPS_ADMIN), 200)
    assert aircraft["total_airframe_minutes"] == 6000, "5940 initial + 60 logged"
    assert aircraft["status"] == "MAINTENANCE_HOLD", "6000 reached the 6000 check-due"


def test_completion_releases_tentative_and_drafts_owner_statement(api):
    """PRD §3.9: "The completion cascade resolves everything the trip
    touched. ... the aircraft moves from `IN_TRIP` to `MAINTENANCE_HOLD` and
    every `TENTATIVE` assignment on that tail is released ... An owner
    statement is drafted for the owner of the confirmed tail."
    PRD §3.9: "The `gross_cents` is the trip's `final_total_cents`. The
    `standard_share_cents` is the gross multiplied by the owner's
    `revenue_share_pct` and divided by one hundred, rounded half up."

    Design: Difficulty/transitive_cascade/flight_log_final_leg_cascade
    """
    ctx, asg2 = _cascade_scenario()
    post_flight_log(ctx["trip"]["id"], ctx["legs"][0]["id"], 60,
                    "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
                    ctx["crew"]["id"])
    asg2_after = validate_success(
        api_client.get_aircraft_assignment(asg2["id"], OPS_ADMIN), 200)
    assert asg2_after["status"] == "RELEASED", "cascade releases the other trip's TENTATIVE"
    rows, meta = validate_paginated(
        api_client.list_owner_statements(ctx["owner"]["id"], OPS_ADMIN))
    assert meta["total_count"] == 1
    stmt = rows[0]
    assert stmt["status"] == "DRAFT"
    assert stmt["gross_cents"] == 240000
    assert stmt["owner_share_cents"] == 192000, "80% of 240000"


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / trip_quote_vs_final_price_diverge
# ---------------------------------------------------------------------------

def _dual_variant_scenario():
    """LIGHT_JET trip (legs REV 120 + POS 30, planned quote 621000 at the
    rate card) completed with actuals 100 + 30 on a 240000/h tail."""
    return setup_completed_trip(
        legs=((120, "REVENUE", False), (30, "POSITIONING", False)),
        actual_minutes=[100, 30],
        owner_overrides={"name": "Owner A", "contact_email": "a@x.com",
                         "revenue_share_pct": 80, "guarantee_cents_per_block_min": 0},
        aircraft_overrides={"tail_number": "N100AA", "hourly_rate_cents": 240000},
        customer_name="Cust One")


def test_quoted_and_final_variants_diverge(api):
    """PRD §3.9: "This dual pricing is deliberate: the quoted number reflects
    planned minutes at the rate card with discount and surcharge, while the
    final number reflects logged actuals at the tail's own rate with the
    60-minute minimum on revenue legs — the two diverge whenever actuals
    differ from plan, the tail's rate differs from the card, or the minimum
    bites."
    QUOTED variant: legs 500000 + 75000 = 575000, surcharge 46000 -> 621000.
    FINAL variant: max(100,60)*240000/60 = 400000 plus 30*240000*0.6/60 =
    72000 -> 472000, no discount and no surcharge.

    Design: Difficulty/dual_variant_calc/trip_quote_vs_final_price_diverge
    """
    ctx = _dual_variant_scenario()
    trip = ctx["trip"]
    assert trip["status"] == "COMPLETED"
    assert trip["quoted_total_cents"] == 621000, "QUOTED variant at the rate card"
    assert trip["final_total_cents"] == 472000, "FINAL variant at the tail rate"
    assert trip["quoted_total_cents"] != trip["final_total_cents"]


def test_completion_drafts_statement_off_final_price(api):
    """PRD §3.9: "The `gross_cents` is the trip's `final_total_cents`." and
    "The `owner_share_cents` is the greater of the standard share and the
    guarantee floor, and the `operator_retained_cents` is the residual gross
    minus the owner share, which may legitimately go negative when the
    guarantee binds."
    Owner at 80% with no guarantee: share 377600, retained 94400.

    Design: Difficulty/dual_variant_calc/trip_quote_vs_final_price_diverge
    """
    ctx = _dual_variant_scenario()
    assert len(ctx["statements"]) == 1
    stmt = ctx["statements"][0]
    assert stmt["gross_cents"] == 472000
    assert stmt["owner_share_cents"] == 377600
    assert stmt["operator_retained_cents"] == 94400
    assert stmt["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B: errors / flight_log_leg_trip_mismatch_rejected
# ---------------------------------------------------------------------------

def test_flight_log_with_leg_of_another_trip_rejected(api):
    """PRD §3.9: "The trip must be `DISPATCHED` (`ERR_INVALID_STATE`); the
    leg must belong to the named trip (`ERR_LEG_TRIP_MISMATCH`); and a leg
    may be logged exactly once — a second log against the same leg is
    rejected with `ERR_DUPLICATE_FLIGHT_LOG`."

    Design: Corner/errors/flight_log_leg_trip_mismatch_rejected
    """
    ctx = setup_dispatched_trip(aircraft_overrides={"tail_number": "N800LM"},
                                customer_name="Cust LM")
    trip2 = create_trip(customer_name="Cust L2", destination_icao="KPHX",
                        departure_at="2026-08-11T10:00:00Z")
    leg2 = add_leg(trip2["id"], block_minutes=45, destination_icao="KPHX")
    resp = api_client.create_flight_log(
        {"trip_request_id": ctx["trip"]["id"], "quote_leg_id": leg2["id"],
         "actual_block_minutes": 60, "departed_at": "2026-08-10T10:00:00Z",
         "arrived_at": "2026-08-10T11:00:00Z"},
        _pic_headers(ctx))
    validate_error(resp, ApiErrorId.ERR_LEG_TRIP_MISMATCH)


# ---------------------------------------------------------------------------
# Queue B: errors / duplicate_flight_log_rejected
# ---------------------------------------------------------------------------

def test_duplicate_flight_log_rejected(api):
    """PRD §3.9: "a leg may be logged exactly once — a second log against the
    same leg is rejected with `ERR_DUPLICATE_FLIGHT_LOG`."
    (Two-leg itinerary: after the first leg is logged the trip is still
    DISPATCHED, so the duplicate gate — not the state gate — is exercised.)

    Design: Corner/errors/duplicate_flight_log_rejected
    """
    ctx = setup_dispatched_trip(
        legs=((60, "REVENUE", False), (60, "REVENUE", False)),
        aircraft_overrides={"tail_number": "N900DL"}, customer_name="Cust DL2")
    leg1 = ctx["legs"][0]
    post_flight_log(ctx["trip"]["id"], leg1["id"], 60,
                    "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
                    ctx["crew"]["id"])
    trip = validate_success(api_client.get_trip_request(ctx["trip"]["id"], OPS_ADMIN), 200)
    assert trip["status"] == "DISPATCHED", "second leg not yet logged"
    resp = api_client.create_flight_log(
        {"trip_request_id": ctx["trip"]["id"], "quote_leg_id": leg1["id"],
         "actual_block_minutes": 62, "departed_at": "2026-08-10T10:00:00Z",
         "arrived_at": "2026-08-10T11:02:00Z"},
        _pic_headers(ctx))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FLIGHT_LOG)


# ---------------------------------------------------------------------------
# Queue B: state_machines / cancel_completed_trip_rejected
# ---------------------------------------------------------------------------

def test_cancel_completed_trip_rejected(api):
    """PRD §3.4: "Cancelling from `COMPLETED`, `CANCELLED`, or `EXPIRED` — or
    a `CUSTOMER` cancellation from `DISPATCHED` — is rejected with
    `ERR_TRIP_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_completed_trip_rejected
    """
    ctx = setup_completed_trip(aircraft_overrides={"tail_number": "N700CL"},
                               customer_name="Cust CL")
    assert ctx["trip"]["status"] == "COMPLETED"
    resp = api_client.cancel_trip(ctx["trip"]["id"], {"reason": "CUSTOMER"}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_CANCELLABLE)
    trip = validate_success(api_client.get_trip_request(ctx["trip"]["id"], OPS_ADMIN), 200)
    assert trip["status"] == "COMPLETED"
    assert trip["final_total_cents"] == 240000, "60 logged minutes at 240000/h"
