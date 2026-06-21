"""Entity creation, computed fields, referential integrity, and request validations.

Corner queue (B): entities, validations, and errors sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, assert_festival,
    create_festival_payload, create_ticket_payload, create_parking_addon_payload,
    create_camping_addon_payload, create_wristband_payload, create_vendor_application_payload,
    create_festival, create_zone, create_stage, open_sales, go_live,
    create_on_sale_festival, create_festival_with_zone_and_stage,
    create_parking_lot, create_camping_area, sell_ticket, issue_wristband,
    activate_wristband, topup, setup_live_festival_with_active_wristband,
    setup_approved_application, gate_enter, schedule_performance,
    NON_EXISTENT_UUID, make_vendor_headers, TEST_USERS,
)

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]
_GATE = TEST_USERS["gate_attendant_headers"]


# ─── entities / create_festival_computes_total_days ───

def test_create_festival_computes_total_days(api):
    """PRD §3.1: "From the dates the server computes `total_days`, the inclusive count
    of festival days, which is the number of days obtained by subtracting the start date
    from the end date and adding one ... A new festival begins with `operational_posture`
    of `PLANNING`, `current_festival_day` of 0."

    POST /festivals with start 2026-08-01 / end 2026-08-03 yields total_days 3, posture
    PLANNING, current_festival_day 0.

    Design: Corner/entities/create_festival_computes_total_days
    """
    res = api.create_festival(create_festival_payload(name="Days F", start_date="2026-08-01",
                                                      end_date="2026-08-03"), _DIRECTOR)
    festival = validate_success(res, 201)
    assert_festival(festival)
    assert festival["total_days"] == 3
    assert festival["operational_posture"] == "PLANNING"
    assert festival["current_festival_day"] == 0


# ─── entities / get_festival_not_found ───

def test_get_festival_not_found(api):
    """PRD §2.5: "Path identifiers are validated strictly left to right: the first
    identifier in the path that does not resolve to an existing resource causes the
    request to fail with `ERR_NOT_FOUND` before any identifier further to the right is
    examined."

    GET /festivals/{nonexistent-uuid} returns ERR_NOT_FOUND with HTTP 404.

    Design: Corner/entities/get_festival_not_found
    """
    res = api.get_festival(NON_EXISTENT_UUID, _DIRECTOR)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── entities / create_ticket_missing_required_field_returns_invalid_request ───

def test_create_ticket_missing_ticket_type_invalid_request(api):
    """PRD §3.11: "the catch-all request-shape check — required fields present, enum and
    type values valid, and the kind-specific field combinations satisfied — is last at
    twenty-first, failing with `ERR_INVALID_REQUEST`."

    Selling a ticket while omitting the required ticket_type field is rejected with
    ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_ticket_missing_required_field_returns_invalid_request
    """
    festival, zone, stage = create_on_sale_festival(name="Req F")
    payload = {"day_count": 2, "purchaser_email": "x@x.com"}
    res = api.create_ticket(festival["id"], payload, _BOXOFFICE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── entities / ticket_day_count_out_of_range_returns_daycount_range ───

def test_ticket_day_count_above_total_days_rejected(api):
    """PRD §3.4: "a `day_count` that must be between 1 and the festival's `total_days`
    ... a `day_count` outside the permitted range is rejected with `ERR_DAYCOUNT_RANGE`."

    A ticket with day_count 4 on a 3-day festival is rejected with ERR_DAYCOUNT_RANGE (422).

    Design: Corner/entities/ticket_day_count_out_of_range_returns_daycount_range
    """
    festival, zone, stage = create_on_sale_festival(start_date="2026-08-01",
                                                    end_date="2026-08-03", name="Range F")
    res = api.create_ticket(festival["id"],
                            create_ticket_payload(ticket_type="GA", day_count=4,
                                                  purchaser_email="z@x.com"),
                            _BOXOFFICE)
    validate_error(res, "ERR_DAYCOUNT_RANGE", expected_status=422)


# ─── entities / addon_fk_not_found_for_bad_parking_lot ───

def test_addon_bad_parking_lot_fk_not_found(api):
    """PRD §2.5: "Every foreign key supplied in a request body must resolve to an existing
    row of the correct entity type and, where the reference is festival-scoped, must
    belong to the same festival as the operation's context; otherwise the request is
    rejected with `ERR_FK_NOT_FOUND`."

    Selling a parking add-on whose parking_lot_id does not resolve is rejected with
    ERR_FK_NOT_FOUND (422); body FK resolution precedes the OCC version check.

    Design: Corner/entities/addon_fk_not_found_for_bad_parking_lot
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-03", name="FK F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    create_stage(festival["id"])
    open_sales(festival["id"])
    ticket = sell_ticket(festival["id"], purchaser_email="fk@x.com")
    payload = create_parking_addon_payload("11111111-1111-4111-8111-111111111111",
                                           expected_lot_version=ticket["id"])
    res = api.create_addon(ticket["id"], payload, _BOXOFFICE)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=422)


# ─── validations / spend_exceeding_balance_returns_insufficient ───

def test_spend_exceeding_balance_insufficient(api):
    """PRD §3.6: "A spend may never drive the balance negative: it requires `balance` to
    be at least the spend `amount`, and a shortfall is rejected with
    `ERR_INSUFFICIENT_BALANCE`."

    A spend of 80.00 against a 70.00 wallet balance is rejected with
    ERR_INSUFFICIENT_BALANCE (422).

    Design: Corner/validations/spend_exceeding_balance_returns_insufficient
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Spend F",
        rfid_uid="RF-SP-1", balance=70.00)
    zone_id = validate_success(api.list_zones(festival["id"], _DIRECTOR), 200)[0]["id"]
    from test_helpers import spend_payload
    res = api.spend_wristband(wristband["id"], spend_payload(80.00, zone_id), _BOXOFFICE)
    validate_error(res, "ERR_INSUFFICIENT_BALANCE", expected_status=422)


# ─── validations / sell_ticket_when_not_on_sale_posture_error ───

def test_sell_ticket_when_planning_posture_error(api):
    """PRD §2.9: "ticket sales are only permitted while the festival is `ON_SALE` ...
    When a child operation is attempted under a posture that does not permit it, the
    request is rejected with `ERR_FESTIVAL_POSTURE`."

    Selling a ticket while the festival is still PLANNING (sales not opened) is rejected
    with ERR_FESTIVAL_POSTURE (409).

    Design: Corner/validations/sell_ticket_when_not_on_sale_posture_error
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                name="NoSale F")
    res = api.create_ticket(festival["id"],
                            create_ticket_payload(ticket_type="GA", day_count=2,
                                                  purchaser_email="ns@x.com"),
                            _BOXOFFICE)
    validate_error(res, "ERR_FESTIVAL_POSTURE", expected_status=409)


# ─── validations / confirm_with_unpaid_fee_returns_fee_unpaid ───

def test_confirm_with_unpaid_fee_rejected(api):
    """PRD §3.8: "confirmation requires that `fee_paid` be at least the `booth_fee`,
    failing with `ERR_FEE_UNPAID` otherwise."

    Confirming an APPROVED application whose fee_paid is 0.00 while booth_fee is positive
    (PREMIUM/1-day = 300.00) is rejected with ERR_FEE_UNPAID (409).

    Design: Corner/validations/confirm_with_unpaid_fee_returns_fee_unpaid
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="C", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_approved_application(festival["id"], zone, booth_tier="PREMIUM",
                                             day_count=1, vendor_name="Up Co")
    res = api.confirm_application(app["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_FEE_UNPAID", expected_status=409)


# ─── validations / enter_already_inside_returns_already_inside ───

def test_enter_already_inside_rejected(api):
    """PRD §3.7: "An entry scan on a wristband that is already `INSIDE` is a double-entry
    or pass-back attempt and is rejected with `ERR_ALREADY_INSIDE`."

    Scanning ENTER on a wristband already INSIDE (festival LIVE, re-entry cap not
    reached) is rejected with ERR_ALREADY_INSIDE (409).

    Design: Corner/validations/enter_already_inside_returns_already_inside
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Inside F",
        rfid_uid="RF-IN-1", max_reentries=2)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    res = gate_enter(festival["id"], wristband["id"])
    validate_error(res, "ERR_ALREADY_INSIDE", expected_status=409)


# ─── validations / performance_inverted_interval_returns_invalid_interval ───

def test_performance_inverted_interval_rejected(api):
    """PRD §3.3: "the interval must be well-formed: `ends_at` must be strictly later than
    `starts_at`, or the request is rejected with `ERR_INVALID_INTERVAL`."

    A performance with ends_at earlier than starts_at is rejected with
    ERR_INVALID_INTERVAL (422).

    Design: Corner/validations/performance_inverted_interval_returns_invalid_interval
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="Inv F")
    stage = create_stage(festival["id"], name="Main", changeover_minutes=30)
    from test_helpers import create_performance_payload
    res = api.create_performance(stage["id"], create_performance_payload(
        "Bad", "2026-08-01T20:00:00Z", "2026-08-01T19:00:00Z"), _DIRECTOR)
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


# ─── validations / duplicate_rfid_returns_duplicate_rfid ───

def test_duplicate_rfid_rejected(api):
    """PRD §3.6: "A `BoxOffice` operator issues one against a festival by supplying its
    `rfid_uid`, the physical tag UID, which must be unique among non-void wristbands
    within the same festival; a collision with an existing non-void tag is rejected with
    `ERR_DUPLICATE_RFID`."

    Issuing a second wristband re-using an rfid_uid already held by a non-void wristband
    in the same festival is rejected with ERR_DUPLICATE_RFID (409).

    Design: Corner/validations/duplicate_rfid_returns_duplicate_rfid
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="Dup F")
    issue_wristband(festival["id"], "DUP-1")
    res = api.create_wristband(festival["id"], create_wristband_payload("DUP-1"), _BOXOFFICE)
    validate_error(res, "ERR_DUPLICATE_RFID", expected_status=409)


# ─── errors / stale_lot_version_on_parking_addon ───

def test_stale_lot_version_on_second_parking_addon(api):
    """PRD §2.6: "When a parking add-on is sold, the request must carry
    `expected_lot_version`, which the server checks against the target parking lot's
    current `version`; a mismatch is rejected with `ERR_STALE_LOT_VERSION` and an HTTP
    status of 412, because the caller's view of sold count versus capacity is out of
    date and committing would risk overselling the lot."

    A second parking sale carrying the lot version from before the first sale (which
    advanced the lot's version) is rejected with ERR_STALE_LOT_VERSION (412).

    Design: Corner/errors/stale_lot_version_on_parking_addon
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="LotOcc F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    create_stage(festival["id"])
    lot = create_parking_lot(festival["id"], capacity=5, price_per_pass=25.00)
    open_sales(festival["id"])
    t1 = sell_ticket(festival["id"], purchaser_email="lo1@x.com")
    t2 = sell_ticket(festival["id"], purchaser_email="lo2@x.com")
    stale_version = lot["version"]
    from test_helpers import sell_parking_addon
    sell_parking_addon(t1["id"], lot["id"], stale_version)
    res = api.create_addon(t2["id"], create_parking_addon_payload(lot["id"], stale_version),
                           _BOXOFFICE)
    validate_error(res, "ERR_STALE_LOT_VERSION", expected_status=412)


# ─── errors / camping_addon_missing_area_returns_invalid_request ───

def test_camping_addon_missing_area_invalid_request(api):
    """PRD §3.4: "Supplying the wrong combination — a camping add-on without its
    `camping_area_id` and `nights`, or a parking add-on without its `parking_lot_id` —
    is rejected with `ERR_INVALID_REQUEST`."

    A CAMPING add-on supplied without camping_area_id or nights is rejected with
    ERR_INVALID_REQUEST (422).

    Design: Corner/errors/camping_addon_missing_area_returns_invalid_request
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-03", name="CampReq F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    create_stage(festival["id"])
    create_camping_area(festival["id"], capacity=10, price_per_night=30.00)
    open_sales(festival["id"])
    ticket = sell_ticket(festival["id"], purchaser_email="cr@x.com")
    res = api.create_addon(ticket["id"], {"kind": "CAMPING"}, _BOXOFFICE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)
