"""Corner-coverage breadth: invalid transitions, parallel settlement dimension,
farm-out reject, the business-rule error catalogue, list filters, and RBAC.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_account,
    create_vehicle_class,
    create_chauffeur,
    create_vehicle,
    create_affiliate,
    create_reservation,
    create_quoted_reservation,
    create_confirmed_reservation,
    quote_reservation,
    confirm_reservation,
    assign_in_house,
    dispatch_trip,
    suspend_affiliate,
    setup_completed_reservation,
    setup_offered_farmout,
    reject_farmout,
    invoice_reservation,
    api_client,
    TEST_USERS,
    make_corporate_booker_headers,
    make_affiliate_partner_headers,
    make_chauffeur_headers,
    create_assignment_payload,
    create_farm_out_order_payload,
    create_flight_tracking_payload,
    trip_event_payload,
    billing_event_payload,
    decision_event_payload,
    wait_event_payload,
)

ADMIN = TEST_USERS["dispatch_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Corner/state_machines/sm_cancel_already_cancelled_returns_invalid_state
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_returns_invalid_state():
    """PRD §3.7: "A reservation may be cancelled from any non-terminal trip state —
    DRAFT, QUOTED, CONFIRMED, ASSIGNED, or EN_ROUTE"

    Design: Corner/state_machines/sm_cancel_already_cancelled_returns_invalid_state
    """
    set_clock("2026-08-04T09:00:00Z")
    account = create_account(cancellation_grace_minutes=120)
    vclass = create_vehicle_class()
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-08-04T20:00:00Z",
                                       planned_drop_at="2026-08-04T21:00:00Z", estimated_miles=10)
    validate_success(api_client.create_trip_event(quoted["id"], trip_event_payload("CANCEL"), DISPATCHER), 200)
    resp = api_client.create_trip_event(quoted["id"], trip_event_payload("CANCEL"), DISPATCHER)
    validate_error(resp, "ERR_INVALID_STATE")
    res = validate_success(api_client.get_reservation(quoted["id"], DISPATCHER), 200)
    assert res["trip_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner/state_machines/sm_complete_from_confirmed_invalid_state
# ---------------------------------------------------------------------------
def test_complete_from_confirmed_returns_invalid_state():
    """PRD §3.4: "Completion advances the reservation PASSENGER_ABOARD → COMPLETED
    and may be triggered by a Dispatcher or the assigned Chauffeur; it requires the
    reservation to be PASSENGER_ABOARD."

    Design: Corner/state_machines/sm_complete_from_confirmed_invalid_state
    """
    account = create_account()
    vclass = create_vehicle_class()
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-05T12:00:00Z",
                                             planned_drop_at="2026-08-05T13:00:00Z", estimated_miles=10)
    resp = api_client.create_trip_event(confirmed["id"], trip_event_payload("COMPLETE"), DISPATCHER)
    validate_error(resp, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Corner/state_machines/sm_settle_unbilled_returns_invalid_state
# ---------------------------------------------------------------------------
def test_settle_unbilled_reservation_returns_invalid_state():
    """PRD §3.8: "Both settle and write-off require the reservation to be INVOICED
    and are rejected with ERR_INVALID_STATE otherwise."

    Design: Corner/state_machines/sm_settle_unbilled_returns_invalid_state
    """
    account = create_account()
    vclass = create_vehicle_class()
    res = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                             pickup_at="2026-08-06T12:00:00Z",
                             planned_drop_at="2026-08-06T13:00:00Z", estimated_miles=10)
    resp = api_client.create_billing_event(res["id"], billing_event_payload("SETTLE"), DISPATCHER)
    validate_error(resp, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Corner/state_machines/sm_parallel_dimensions_complete_then_invoice_independent
# ---------------------------------------------------------------------------
def test_parallel_dimensions_complete_then_invoice():
    """PRD §3.8: "The financial axis of a reservation advances independently of its
    trip axis. A Dispatcher invoices a reservation, moving its settlement_status
    UNBILLED → INVOICED."

    Design: Corner/state_machines/sm_parallel_dimensions_complete_then_invoice_independent
    """
    set_clock("2026-08-07T09:00:00Z")
    ctx = setup_completed_reservation(
        "2026-08-07T12:05:00Z", "2026-08-07T12:10:00Z",
        account_overrides={"negotiated_discount_pct": 0, "default_gratuity_pct": 20},
        class_overrides={"code": "SEDAN", "base_fare_cents": 5000, "per_mile_cents": 250,
                         "hourly_rate_cents": 12000, "wait_per_minute_cents": 200,
                         "included_wait_minutes": 15},
        res_overrides={"pickup_at": "2026-08-07T12:00:00Z",
                       "planned_drop_at": "2026-08-07T13:00:00Z", "estimated_miles": 10},
    )
    invoiced = invoice_reservation(ctx["reservation_id"])
    assert invoiced["trip_status"] == "COMPLETED"
    assert invoiced["settlement_status"] == "INVOICED"


# ---------------------------------------------------------------------------
# Corner/state_machines/sm_farmout_reject_keeps_reservation_in_house
# ---------------------------------------------------------------------------
def test_farmout_reject_keeps_reservation_in_house():
    """PRD §3.5: "A reject or a recall leaves the reservation CONFIRMED with
    fulfillment_mode still IN_HOUSE and refreshes the affiliate's open_farmouts;
    the order ends REJECTED or RECALLED respectively."

    Design: Corner/state_machines/sm_farmout_reject_keeps_reservation_in_house
    """
    ctx = setup_offered_farmout(res_overrides={"pickup_at": "2026-08-08T12:00:00Z",
                                               "planned_drop_at": "2026-08-08T13:00:00Z",
                                               "estimated_miles": 10})
    order = reject_farmout(ctx["farm_out_order"]["id"], ctx["affiliate_id"], decline_reason="no driver")
    assert order["status"] == "REJECTED"
    res = validate_success(api_client.get_reservation(ctx["reservation_id"], DISPATCHER), 200)
    assert res["trip_status"] == "CONFIRMED"
    assert res["fulfillment_mode"] == "IN_HOUSE"


# ---------------------------------------------------------------------------
# Corner/calculations/calc_affiliate_payout_hourly
# ---------------------------------------------------------------------------
def test_affiliate_payout_hourly_ceil_basis():
    """PRD §3.5: "For an HOURLY trip the fare base is hourly_rate_cents times the
    charter_hours rounded up to whole hours; otherwise it is base_fare_cents plus
    the rounded product of per_mile_cents and estimated_miles."

    Design: Corner/calculations/calc_affiliate_payout_hourly
    """
    account = create_account()
    vclass = create_vehicle_class(code="SUV", base_fare_cents=7000, per_mile_cents=300,
                                  hourly_rate_cents=15000, wait_per_minute_cents=250)
    affiliate = create_affiliate(name="Bay Black Car", market_code="SFO", payout_share_pct=60)
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="HOURLY",
                                             pickup_at="2026-08-12T18:00:00Z",
                                             planned_drop_at="2026-08-12T22:00:00Z", charter_hours=3.2)
    order = validate_success(
        api_client.create_farm_out_order(
            create_farm_out_order_payload(confirmed["id"], affiliate["id"], confirmed["version"]),
            DISPATCHER,
        ),
        201,
    )
    assert order["offered_payout_cents"] == 36000, (
        f"ceil(3.2)=4 * 15000=60000 * 60% = 36000, got {order['offered_payout_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner/validations/val_flight_tracking_on_non_airport_returns_409
# ---------------------------------------------------------------------------
def test_flight_tracking_on_non_airport_returns_409():
    """PRD §3.6: "Flight tracking may be attached only to a reservation whose
    trip_type is AIRPORT, and at most one tracking record may exist per reservation;
    a non-airport reservation or a second tracking attempt is rejected with
    ERR_FLIGHT_NOT_APPLICABLE."

    Design: Corner/validations/val_flight_tracking_on_non_airport_returns_409
    """
    account = create_account()
    vclass = create_vehicle_class()
    res = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                             pickup_at="2026-08-13T12:00:00Z",
                             planned_drop_at="2026-08-13T13:00:00Z", estimated_miles=10)
    resp = api_client.create_flight_tracking(
        create_flight_tracking_payload(res["id"], flight_number="UA9",
                                       scheduled_arrival_at="2026-08-13T11:30:00Z"),
        DISPATCHER,
    )
    validate_error(resp, "ERR_FLIGHT_NOT_APPLICABLE")


# ---------------------------------------------------------------------------
# Corner/validations/val_wait_boarded_before_arrived_returns_409
# ---------------------------------------------------------------------------
def test_wait_boarded_before_arrived_returns_409():
    """PRD §3.4: "Wait events must arrive in order: a PASSENGER_BOARDED requires an
    existing CHAUFFEUR_ARRIVED with an earlier occurred_at, and an occurred_at that
    predates the prior event — or a duplicate CHAUFFEUR_ARRIVED, or a
    PASSENGER_BOARDED before any arrival — is rejected with ERR_WAIT_SEQUENCE."

    Design: Corner/validations/val_wait_boarded_before_arrived_returns_409
    """
    account = create_account()
    vclass = create_vehicle_class()
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-W1")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-14T12:00:00Z",
                                             planned_drop_at="2026-08-14T13:00:00Z", estimated_miles=10)
    assign_in_house(confirmed["id"], drv["id"], veh["id"], confirmed["version"])
    dispatch_trip(confirmed["id"], drv["id"])  # EN_ROUTE, no wait events yet
    resp = api_client.create_wait_event(
        confirmed["id"], wait_event_payload("PASSENGER_BOARDED", "2026-08-14T12:05:00Z"),
        make_chauffeur_headers(drv["id"]),
    )
    validate_error(resp, "ERR_WAIT_SEQUENCE")


# ---------------------------------------------------------------------------
# Corner/validations/val_trip_type_fields_hourly_missing_hours_returns_422
# ---------------------------------------------------------------------------
def test_hourly_without_charter_hours_returns_422():
    """PRD §3.2: "a POINT_TO_POINT or AIRPORT reservation must supply an
    estimated_miles greater than zero, and an HOURLY reservation must supply a
    charter_hours greater than zero; a violation is rejected with ERR_TRIP_TYPE_FIELDS."

    Design: Corner/validations/val_trip_type_fields_hourly_missing_hours_returns_422
    """
    account = create_account()
    vclass = create_vehicle_class(code="SUV", base_fare_cents=7000, per_mile_cents=300,
                                  hourly_rate_cents=15000, wait_per_minute_cents=250)
    resp = api_client.create_reservation(
        {"corporate_account_id": account["id"], "trip_type": "HOURLY", "vehicle_class_id": vclass["id"],
         "pickup_at": "2026-08-15T18:00:00Z", "planned_drop_at": "2026-08-15T20:00:00Z",
         "charter_hours": 0},
        DISPATCHER,
    )
    validate_error(resp, "ERR_TRIP_TYPE_FIELDS")


# ---------------------------------------------------------------------------
# Corner/validations/val_fulfillment_conflict_farmout_after_assignment_returns_409
# ---------------------------------------------------------------------------
def test_farmout_after_active_assignment_returns_fulfillment_conflict():
    """PRD §3.5: "An offer is rejected with ERR_FULFILLMENT_CONFLICT if the
    reservation already holds an ACTIVE assignment or an OFFERED/ACCEPTED order"

    Design: Corner/validations/val_fulfillment_conflict_farmout_after_assignment_returns_409
    """
    account = create_account()
    vclass = create_vehicle_class()
    affiliate = create_affiliate(name="Bay Black Car", market_code="SFO", payout_share_pct=70)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-F1")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-16T12:00:00Z",
                                             planned_drop_at="2026-08-16T13:00:00Z", estimated_miles=10)
    assign_in_house(confirmed["id"], drv["id"], veh["id"], confirmed["version"])
    res = validate_success(api_client.get_reservation(confirmed["id"], DISPATCHER), 200)
    resp = api_client.create_farm_out_order(
        create_farm_out_order_payload(confirmed["id"], affiliate["id"], res["version"]), DISPATCHER
    )
    validate_error(resp, "ERR_FULFILLMENT_CONFLICT")


# ---------------------------------------------------------------------------
# Corner/validations/val_farmout_offer_to_suspended_affiliate_returns_409
# ---------------------------------------------------------------------------
def test_farmout_offer_to_suspended_affiliate_returns_409():
    """PRD §3.5: "with ERR_AFFILIATE_INELIGIBLE if the target affiliate's status is
    SUSPENDED rather than ACTIVE."

    Design: Corner/validations/val_farmout_offer_to_suspended_affiliate_returns_409
    """
    account = create_account()
    vclass = create_vehicle_class()
    affiliate = create_affiliate(name="Bay Black Car", market_code="SFO", payout_share_pct=70)
    suspend_affiliate(affiliate["id"])
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-24T12:00:00Z",
                                             planned_drop_at="2026-08-24T13:00:00Z", estimated_miles=10)
    resp = api_client.create_farm_out_order(
        create_farm_out_order_payload(confirmed["id"], affiliate["id"], confirmed["version"]), DISPATCHER
    )
    validate_error(resp, "ERR_AFFILIATE_INELIGIBLE")
    res = validate_success(api_client.get_reservation(confirmed["id"], DISPATCHER), 200)
    assert res["trip_status"] == "CONFIRMED"
    assert res["fulfillment_mode"] == "IN_HOUSE"


# ---------------------------------------------------------------------------
# Corner/endpoints/endpoint_list_reservations_by_account_filter
# ---------------------------------------------------------------------------
def test_list_reservations_filtered_by_account():
    """PRD §2.5: "a reservation's history is reachable through its account and class
    filters"

    Design: Corner/endpoints/endpoint_list_reservations_by_account_filter
    """
    account = create_account()
    vclass = create_vehicle_class()
    create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                       pickup_at="2026-08-17T12:00:00Z", planned_drop_at="2026-08-17T13:00:00Z",
                       estimated_miles=10)
    create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                       pickup_at="2026-08-17T14:00:00Z", planned_drop_at="2026-08-17T15:00:00Z",
                       estimated_miles=8)
    resp = api_client.list_reservations(DISPATCHER, params={"corporate_account_id": account["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 reservations for the account, got {len(data)}"


# ---------------------------------------------------------------------------
# Corner/endpoints/endpoint_list_assignments_by_chauffeur_filter
# ---------------------------------------------------------------------------
def test_list_assignments_filtered_by_chauffeur():
    """PRD §2.5: "a chauffeur's current work is discoverable by filtering
    assignments on chauffeur_id."

    Design: Corner/endpoints/endpoint_list_assignments_by_chauffeur_filter
    """
    account = create_account()
    vclass = create_vehicle_class()
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-L1")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-18T12:00:00Z",
                                             planned_drop_at="2026-08-18T13:00:00Z", estimated_miles=10)
    assign_in_house(confirmed["id"], drv["id"], veh["id"], confirmed["version"])
    resp = api_client.list_assignments(DISPATCHER, params={"chauffeur_id": drv["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 assignment for the chauffeur, got {len(data)}"


# ---------------------------------------------------------------------------
# Corner/rbac/rbac_corporatebooker_cannot_assign_returns_403
# ---------------------------------------------------------------------------
def test_corporate_booker_cannot_create_assignment():
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_FORBIDDEN."
    PRD §4: "authorization is enforced per the roles listed below" — and the
    endpoint table authorizes POST /assignments for Dispatcher only.

    Design: Corner/rbac/rbac_corporatebooker_cannot_assign_returns_403
    """
    account = create_account()
    vclass = create_vehicle_class()
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-R1")
    booker = make_corporate_booker_headers(account["id"])
    res = validate_success(
        api_client.create_reservation(
            {"corporate_account_id": account["id"], "trip_type": "POINT_TO_POINT",
             "vehicle_class_id": vclass["id"], "pickup_at": "2026-08-19T12:00:00Z",
             "planned_drop_at": "2026-08-19T13:00:00Z", "estimated_miles": 10},
            booker,
        ),
        201,
    )
    quote_reservation(res["id"], headers=booker)
    confirmed = confirm_reservation(res["id"], headers=booker)
    resp = api_client.create_assignment(
        create_assignment_payload(res["id"], drv["id"], veh["id"], confirmed["version"]), booker
    )
    validate_error(resp, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Corner/rbac/rbac_affiliatepartner_cannot_accept_others_offer_returns_403
# ---------------------------------------------------------------------------
def test_affiliate_partner_cannot_accept_others_offer():
    """PRD §2.1: "AffiliatePartner acts on behalf of exactly one affiliate operator.
    When X-User-Role is AffiliatePartner, X-User-ID is the id of the acting
    Affiliate; ownership checks on a farm-out offer compare the order's affiliate_id
    to X-User-ID, so a partner may only accept or reject offers addressed to their
    own affiliate."

    Design: Corner/rbac/rbac_affiliatepartner_cannot_accept_others_offer_returns_403
    """
    account = create_account()
    vclass = create_vehicle_class()
    affA = create_affiliate(name="Aff A", market_code="SFO", payout_share_pct=70)
    affB = create_affiliate(name="Aff B", market_code="SFO", payout_share_pct=65)
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-20T12:00:00Z",
                                             planned_drop_at="2026-08-20T13:00:00Z", estimated_miles=10)
    order = validate_success(
        api_client.create_farm_out_order(
            create_farm_out_order_payload(confirmed["id"], affA["id"], confirmed["version"]), DISPATCHER
        ),
        201,
    )
    resp = api_client.create_decision_event(
        order["id"], decision_event_payload("ACCEPT"), make_affiliate_partner_headers(affB["id"])
    )
    validate_error(resp, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Corner/rbac/rbac_missing_headers_returns_401
# ---------------------------------------------------------------------------
def test_unknown_role_returns_401():
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: X-User-ID, which identifies the acting user, and X-User-Role, which
    declares the capacity in which they are acting. If either header is missing, or
    if X-User-Role does not name a role the system recognizes, the request is
    rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/rbac_missing_headers_returns_401
    """
    bad_headers = {"X-User-ID": "someone", "X-User-Role": "NoSuchRole",
                   "Content-Type": "application/json"}
    from test_helpers import NON_EXISTENT_UUID as NEU
    resp = api_client.get_reservation(NEU, bad_headers)
    validate_error(resp, "ERR_UNAUTHENTICATED")
