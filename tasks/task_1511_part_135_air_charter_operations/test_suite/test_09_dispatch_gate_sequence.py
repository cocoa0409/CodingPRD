"""Dispatch: the fixed compliance-gate sequence, the state/safety/fiscal
tier ordering, and the check-hours boundary."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    screen_passenger, add_passenger, setup_quoted_trip, setup_booked_trip,
    setup_dispatch_ready, setup_trip_with_confirmed_aircraft,
    create_crew, create_vetted_crew,
    make_ops_admin_headers, make_dispatch_manager_headers,
)

OPS_ADMIN = make_ops_admin_headers()
DISPATCH_MANAGER = make_dispatch_manager_headers()


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / dispatch_state_error_beats_safety
# ---------------------------------------------------------------------------

def test_dispatch_on_quoted_trip_with_denied_passenger_returns_state_error(api):
    """PRD §2.11: "Every request is evaluated against an ordered validation
    cascade, and the first failing check determines the error returned."
    PRD §3.8: "Dispatch is the point of no return, executed by a
    `DispatchManager` against a `BOOKED` trip (any other status yields
    `ERR_TRIP_NOT_BOOKED`)."
    The QUOTED trip (never booked) also carries a DENIED passenger; the state
    tier fires before the compliance tier, so the error is
    ERR_TRIP_NOT_BOOKED, not ERR_TSA_NOT_CLEARED.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_error_beats_safety
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), passenger_count=1,
                                    customer_name="Cust P")
    pax = add_passenger(trip["id"], full_name="Bad Pax", date_of_birth="1970-01-01")
    screen_passenger(pax["id"], "DENIED")
    resp = api_client.dispatch_trip(trip["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_BOOKED)


def test_dispatch_on_quoted_trip_with_incomplete_manifest_returns_state_error(api):
    """PRD §2.11: "7. State preconditions — the target resource must be in a
    valid state for the requested transition; the 409 state-error family
    applies."
    PRD §2.11: "8. FAA and TSA compliance gates — ops-spec membership at
    assignment confirm, type qualification at crew-assignment creation, the
    full dispatch gate sequence, and the grounding-finding check at
    return-to-service; the 422 compliance family applies."
    The QUOTED trip (never booked) is also one passenger short of
    passenger_count; the state tier masks the manifest failure.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_error_beats_safety
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), passenger_count=1,
                                    customer_name="Cust P2")
    resp = api_client.dispatch_trip(trip["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_BOOKED)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / dispatch_safety_beats_fiscal
# ---------------------------------------------------------------------------

def _booked_trip_with_denied_pax(screen_outcome):
    """BOOKED trip (deposit 513000 only of 2052000 -> money tier fails),
    CONFIRMED assignment, VETTED PIC, manifest count satisfied with one
    passenger in the given screening outcome."""
    ctx = setup_dispatch_ready(
        legs=((480, "REVENUE", False),), pay_in_full=False,
        passenger_count=1, screen=False, customer_name="Cust F")
    screen_passenger(ctx["passengers"][0]["id"], screen_outcome)
    return ctx


def test_denied_passenger_and_unpaid_balance_returns_tsa_error(api):
    """PRD §3.8: "Only after all compliance gates pass does the money tier
    run: `collected_cents` must be at least the `quoted_total_cents`, or
    dispatch is rejected with `ERR_BALANCE_NOT_SETTLED`."
    PRD §3.8: "security — every passenger must hold `tsa_status` `CLEARED`
    (`ERR_TSA_NOT_CLEARED`)"
    The BOOKED trip has a DENIED passenger AND an unpaid balance; the
    compliance tier masks the money tier.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_safety_beats_fiscal
    """
    ctx = _booked_trip_with_denied_pax("DENIED")
    assert ctx["trip"]["collected_cents"] == 513000  # unpaid balance
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TSA_NOT_CLEARED)


def test_pending_passenger_and_unpaid_balance_returns_tsa_error(api):
    """PRD §3.8: "security — every passenger must hold `tsa_status` `CLEARED`
    (`ERR_TSA_NOT_CLEARED`)"
    PRD §3.8: "Only after all compliance gates pass does the money tier run:
    `collected_cents` must be at least the `quoted_total_cents`, or dispatch
    is rejected with `ERR_BALANCE_NOT_SETTLED`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_safety_beats_fiscal
    """
    # This variant uses a never-screened (PENDING) passenger; the unpaid
    # balance is again masked by the compliance tier.
    ctx = setup_dispatch_ready(
        legs=((480, "REVENUE", False),), pay_in_full=False,
        passenger_count=1, screen=False, customer_name="Cust F2")
    assert ctx["passengers"][0]["tsa_status"] == "PENDING"
    assert ctx["trip"]["collected_cents"] == 513000
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TSA_NOT_CLEARED)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / dispatch_requires_passengers_cleared
# ---------------------------------------------------------------------------

def test_pending_passenger_blocks_otherwise_valid_dispatch(api):
    """PRD §3.8: "Then the compliance tier runs in this sequence: crew
    legality — at least one crew assignment with `duty_role` `PIC` must be
    `VETTED` with both `duty_legal` and `rest_legal` true, and when the
    assigned aircraft's category is `HEAVY_JET` at least one equally vetted
    and legal `SIC` is also required, failing which the dispatch is rejected
    with `ERR_CREW_NOT_VETTED`; manifest completeness — the number of
    passenger rows on the trip must equal the trip's `passenger_count`
    (`ERR_PASSENGER_MANIFEST_INCOMPLETE`); security — every passenger must
    hold `tsa_status` `CLEARED` (`ERR_TSA_NOT_CLEARED`); permits — when the
    trip's `international` flag is true, at least one overflight permit must
    exist for the trip and every permit flagged `required` must be `GRANTED`
    (`ERR_PERMIT_NOT_GRANTED`); inspection headroom — the confirmed tail's
    `total_airframe_minutes` plus the trip's total planned block minutes must
    be at most its `next_check_due_minutes`, with equality legal and a single
    minute over rejected with `ERR_CHECK_HOURS_EXCEEDED`; and findings — no
    `OPEN` compliance finding flagged `grounding` may point at the assigned
    aircraft (`ERR_GROUNDING_FINDING_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_passengers_cleared
    """
    ctx = setup_dispatch_ready(legs=((60, "REVENUE", False),), passenger_count=1,
                               screen=False, customer_name="Cust T")
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TSA_NOT_CLEARED)


def test_dispatch_succeeds_once_passenger_cleared(api):
    """PRD §3.8: "A clean dispatch moves the trip to `DISPATCHED`, moves the
    confirmed tail from `AVAILABLE` to `IN_TRIP`, and increments the trip's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_passengers_cleared
    """
    ctx = setup_dispatch_ready(legs=((60, "REVENUE", False),), passenger_count=1,
                               screen=False, customer_name="Cust T")
    validate_error(api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER),
                   ApiErrorId.ERR_TSA_NOT_CLEARED)
    screen_passenger(ctx["passengers"][0]["id"], "CLEARED")
    dispatched = validate_success(
        api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER), 200)
    assert dispatched["status"] == "DISPATCHED"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / check_hours_equality_dispatch_allowed
# ---------------------------------------------------------------------------

def test_dispatch_at_exactly_check_hours_due_succeeds(api):
    """PRD §3.8: "inspection headroom — the confirmed tail's
    `total_airframe_minutes` plus the trip's total planned block minutes must
    be at most its `next_check_due_minutes`, with equality legal and a single
    minute over rejected with `ERR_CHECK_HOURS_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/check_hours_equality_dispatch_allowed
    """
    # 5940 accumulated + 60 planned == 6000 due: equality is legal.
    ctx = setup_dispatch_ready(
        aircraft_overrides={"tail_number": "N700CK", "initial_airframe_minutes": 5940,
                            "next_check_due_minutes": 6000},
        legs=((60, "REVENUE", False),), customer_name="Cust CK")
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    dispatched = validate_success(resp, expected_status=200)
    assert dispatched["status"] == "DISPATCHED"


def test_clean_dispatch_moves_aircraft_in_trip_and_bumps_version(api):
    """PRD §3.8: "A clean dispatch moves the trip to `DISPATCHED`, moves the
    confirmed tail from `AVAILABLE` to `IN_TRIP`, and increments the trip's
    `version`."

    Design: Difficulty/boundary_precision_check/check_hours_equality_dispatch_allowed
    """
    ctx = setup_dispatch_ready(
        aircraft_overrides={"tail_number": "N700CK", "initial_airframe_minutes": 5940,
                            "next_check_due_minutes": 6000},
        legs=((60, "REVENUE", False),), customer_name="Cust CK")
    version_before = ctx["trip"]["version"]
    dispatched = validate_success(
        api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER), 200)
    assert dispatched["version"] == version_before + 1
    aircraft = validate_success(api_client.get_aircraft(ctx["aircraft"]["id"], OPS_ADMIN), 200)
    assert aircraft["status"] == "IN_TRIP"


# ---------------------------------------------------------------------------
# Queue B: errors / dispatch gate violations
# ---------------------------------------------------------------------------

def test_dispatch_without_vetted_crew_rejected(api):
    """PRD §3.8: "crew legality — at least one crew assignment with
    `duty_role` `PIC` must be `VETTED` with both `duty_legal` and
    `rest_legal` true, and when the assigned aircraft's category is
    `HEAVY_JET` at least one equally vetted and legal `SIC` is also required,
    failing which the dispatch is rejected with `ERR_CREW_NOT_VETTED`"

    Design: Corner/errors/dispatch_without_vetted_crew_rejected
    """
    ctx = setup_dispatch_ready(legs=((60, "REVENUE", False),), with_crew=False,
                               customer_name="Cust NV")
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_VETTED)


def test_dispatch_without_confirmed_assignment_rejected(api):
    """PRD §3.8: "First, in the state tier, the trip must hold exactly one
    `CONFIRMED` aircraft assignment; zero or several yield
    `ERR_NO_CONFIRMED_ASSIGNMENT`."

    Design: Corner/errors/dispatch_without_confirmed_assignment_rejected
    """
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust NC")
    resp = api_client.dispatch_trip(trip["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_ASSIGNMENT)


def test_dispatch_with_undecided_permit_rejected(api):
    """PRD §3.8: "permits — when the trip's `international` flag is true, at
    least one overflight permit must exist for the trip and every permit
    flagged `required` must be `GRANTED` (`ERR_PERMIT_NOT_GRANTED`)"

    Design: Corner/errors/dispatch_permit_not_granted_rejected
    """
    ctx = setup_dispatch_ready(
        legs=((60, "REVENUE", False),), international=True, destination_icao="MMCZ",
        grant_permits=False, customer_name="Cust PM")
    assert ctx["trip"]["quoted_total_cents"] == 520000, "250000 legs + 20000 surcharge + 250000 intl"
    assert ctx["permits"][0]["status"] == "REQUESTED"
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_GRANTED)


def test_dispatch_one_minute_over_check_hours_rejected(api):
    """PRD §3.8: "inspection headroom — the confirmed tail's
    `total_airframe_minutes` plus the trip's total planned block minutes must
    be at most its `next_check_due_minutes`, with equality legal and a single
    minute over rejected with `ERR_CHECK_HOURS_EXCEEDED`"

    Design: Corner/errors/dispatch_check_hours_exceeded_rejected
    """
    # 5940 accumulated + 61 planned = 6001 > 6000 due.
    ctx = setup_dispatch_ready(
        aircraft_overrides={"tail_number": "N550CH", "initial_airframe_minutes": 5940,
                            "next_check_due_minutes": 6000},
        legs=((61, "REVENUE", False),), customer_name="Cust CH")
    assert ctx["trip"]["quoted_total_cents"] == 274500, "254167 legs + 20333 surcharge"
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CHECK_HOURS_EXCEEDED)


def test_dispatch_manifest_count_mismatch_rejected(api):
    """PRD §3.8: "manifest completeness — the number of passenger rows on the
    trip must equal the trip's `passenger_count`
    (`ERR_PASSENGER_MANIFEST_INCOMPLETE`)"

    Design: Corner/errors/manifest_count_mismatch_rejected
    """
    # passenger_count declared 2 but only one (CLEARED) passenger on the
    # manifest; every other gate passes.
    ctx = setup_trip_with_confirmed_aircraft(legs=((60, "REVENUE", False),),
                                             passenger_count=2, customer_name="Cust MF")
    crew = create_crew(name="Pic MF")
    create_vetted_crew(ctx["trip"]["id"], crew["id"])
    pax = add_passenger(ctx["trip"]["id"], full_name="Only Pax", date_of_birth="1991-01-01")
    screen_passenger(pax["id"], "CLEARED")
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_PASSENGER_MANIFEST_INCOMPLETE)


def test_dispatch_balance_not_settled_rejected(api):
    """PRD §3.8: "Only after all compliance gates pass does the money tier
    run: `collected_cents` must be at least the `quoted_total_cents`, or
    dispatch is rejected with `ERR_BALANCE_NOT_SETTLED`."

    Design: Corner/complexity_layers/dispatch_balance_not_settled_alone
    """
    # Every compliance gate satisfied; only the deposit (67500 of 270000) paid.
    ctx = setup_dispatch_ready(legs=((60, "REVENUE", False),), pay_in_full=False,
                               customer_name="Cust BS")
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_BALANCE_NOT_SETTLED)


def test_heavy_jet_dispatch_requires_vetted_sic(api):
    """PRD §3.8: "crew legality — at least one crew assignment with
    `duty_role` `PIC` must be `VETTED` with both `duty_legal` and
    `rest_legal` true, and when the assigned aircraft's category is
    `HEAVY_JET` at least one equally vetted and legal `SIC` is also required,
    failing which the dispatch is rejected with `ERR_CREW_NOT_VETTED`"

    Design: Corner/errors/sic_required_for_heavy_jet
    """
    ctx = setup_dispatch_ready(
        category="HEAVY_JET",
        aircraft_overrides={"tail_number": "N202HJ", "category": "HEAVY_JET",
                            "seats": 14, "hourly_rate_cents": 600000},
        crew_overrides={"name": "Pic HJ", "qualified_categories": ["HEAVY_JET"]},
        legs=((60, "REVENUE", False),), customer_name="Cust HJ")
    assert ctx["trip"]["quoted_total_cents"] == 702000, "650000 legs + 52000 surcharge"
    # Only a VETTED PIC exists; no SIC assigned.
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_VETTED)
