"""Entity creation/validation corners, listing & pagination, RBAC, and the OCC
stale-version guards.

Corner queue: entities, endpoints, rbac, cross_cutting_complexity_layers (OCC).
"""
from test_helpers import (
    api_client as _api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    make_guest_headers,
    setup_basic,
    create_hotel,
    create_room_type,
    create_rate_plan,
    create_corporate_account,
    create_guest,
    create_room,
    create_group_block,
    get_folio_for_reservation,
)
api = _api_client
RM = TEST_USERS["revenue_manager_headers"]
FDA = TEST_USERS["front_desk_headers"]
NA = TEST_USERS["night_auditor_headers"]

NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"


# ===========================================================================
# Corner/entities/create_hotel_returns_201_with_defaults_applied
# ===========================================================================
def test_create_hotel_applies_defaults():
    """PRD §3.1: "A new property opens with `posture` set to `OPEN`, `audit_epoch` at 0,
    and `version` at 1."
    PRD §3.1: "an allowance of 0.10 means a room type's sellable count is computed against
    1.10 times its physical inventory." (default omitted -> 0.0 per §1.1 default.)

    Design: Corner/entities/create_hotel_returns_201_with_defaults_applied
    """
    resp = api.create_hotel({"name": "Defaults Inn",
                             "current_business_date": "2026-07-01"}, RM)
    hotel = validate_success(resp, expected_status=201)
    assert hotel["posture"] == "OPEN", hotel
    assert hotel["audit_epoch"] == 0, hotel
    assert hotel["overbooking_allowance_pct"] == 0.0, hotel
    assert hotel["version"] == 1, hotel


# ===========================================================================
# Corner/entities/get_hotel_nonexistent_returns_not_found
# ===========================================================================
def test_get_hotel_nonexistent_returns_not_found():
    """PRD §2.5: "When a path-referenced resource identified by `{id}` does not exist
    within the resolved hotel scope, the request is rejected with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_hotel_nonexistent_returns_not_found
    """
    resp = api.get_hotel(NON_EXISTENT_UUID, RM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner/entities/create_room_type_missing_required_field_returns_invalid_request
# ===========================================================================
def test_create_room_type_missing_base_rate_returns_invalid_request():
    """PRD §3.1: "Each `RoomType` is created against a `hotel_id` with a `code` ..., a
    `tier_rank` ..., a `physical_inventory` count of at least 1 saleable rooms, and a
    `base_rate_cents` of at least 0 that is the default nightly rate before any rate-plan
    adjustment."
    PRD §3.3: "where a required field is missing ... is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/create_room_type_missing_required_field_returns_invalid_request
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    resp = api.create_room_type({
        "hotel_id": hotel["id"], "code": "KING", "tier_rank": 1,
        "physical_inventory": 3}, RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/create_reservation_bad_fk_returns_reference_not_found
# ===========================================================================
def test_create_reservation_bad_guest_fk_returns_reference_not_found():
    """PRD §2.5: "When a foreign-key field supplied in a request body — any of `hotel_id`,
    `guest_id`, `rate_plan_id`, `room_type_id`, `group_block_id`, `room_id`, `folio_id`,
    or `corporate_account_id` — points at a resource that does not exist, the request is
    rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

    Design: Corner/entities/create_reservation_bad_fk_returns_reference_not_found
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    rt = create_room_type(hotel["id"], code="KING", tier_rank=1,
                          physical_inventory=3, base_rate_cents=20000)
    plan = create_rate_plan(hotel["id"])
    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": NON_EXISTENT_UUID,
        "room_type_id": rt["id"], "rate_plan_id": plan["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-02"}, FDA)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Corner/entities/reservation_nights_computed_field_correct
# ===========================================================================
def test_reservation_nights_and_effective_type_computed_on_create():
    """PRD §3.3: "The server computes `nights` as the number of days from `arrival_date`
    to `departure_date` (which must be at least 1), sets `effective_room_type_id` equal to
    the booked `room_type_id` ... A new reservation is created in `HELD` status."

    2026-07-01..2026-07-04 -> nights == 3; effective_room_type_id == room_type_id; HELD.

    Design: Corner/entities/reservation_nights_computed_field_correct
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    rt = create_room_type(hotel["id"], code="KING", tier_rank=1,
                          physical_inventory=3, base_rate_cents=20000)
    plan = create_rate_plan(hotel["id"])
    guest = create_guest(hotel["id"])
    res = validate_success(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": rt["id"],
        "rate_plan_id": plan["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-04"}, FDA), expected_status=201)
    assert res["nights"] == 3, res
    assert res["status"] == "HELD", res
    assert res["effective_room_type_id"] == rt["id"], res


# ===========================================================================
# Corner/entities/create_reservation_departure_not_after_arrival_returns_invalid_request
# ===========================================================================
def test_create_reservation_same_day_departure_returns_invalid_request():
    """PRD §3.3: "The `departure_date` must be strictly later than the `arrival_date`; a
    request where it is not ... is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_reservation_departure_not_after_arrival_returns_invalid_request
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    rt = create_room_type(hotel["id"], code="KING", tier_rank=1,
                          physical_inventory=3, base_rate_cents=20000)
    plan = create_rate_plan(hotel["id"])
    guest = create_guest(hotel["id"])
    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": rt["id"],
        "rate_plan_id": plan["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-01"}, FDA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/duplicate_room_number_per_hotel_returns_duplicate_resource
# ===========================================================================
def test_duplicate_room_number_per_hotel_returns_duplicate_resource():
    """PRD §2.10: "A `RoomType`'s `code`, a `Room`'s `room_number`, a `RatePlan`'s `code`,
    and a `Guest`'s `email` must each be unique per hotel. An attempt to create a resource
    that would collide with an existing value on one of these is rejected with
    `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Corner/entities/duplicate_room_number_per_hotel_returns_duplicate_resource
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    rt = create_room_type(hotel["id"], code="KING", tier_rank=1,
                          physical_inventory=3, base_rate_cents=20000)
    create_room(hotel["id"], rt["id"], room_number="101")
    resp = api.create_room({
        "hotel_id": hotel["id"], "room_type_id": rt["id"], "room_number": "101"}, RM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


# ===========================================================================
# Corner/endpoints/pagination_invalid_limit_returns_pagination_invalid
# ===========================================================================
def test_pagination_limit_above_max_returns_pagination_invalid():
    """PRD §2.3: "A `limit` below 1, a `limit` above 100, or an `offset` below 0 is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/endpoints/pagination_invalid_limit_returns_pagination_invalid
    """
    create_hotel(current_business_date="2026-07-01")
    resp = api.list_room_types(RM, params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


# ===========================================================================
# Corner/endpoints/list_rooms_filtered_by_room_type_returns_array
# ===========================================================================
def test_list_rooms_filtered_by_room_type_returns_array():
    """PRD §2.5: "Rooms may be filtered by `hotel_id`, `room_type_id`,
    `assigned_reservation_id`, and `housekeeping_status`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope".

    Design: Corner/endpoints/list_rooms_filtered_by_room_type_returns_array
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    rt = create_room_type(hotel["id"], code="KING", tier_rank=1,
                          physical_inventory=3, base_rate_cents=20000)
    room = create_room(hotel["id"], rt["id"], room_number="131")

    resp = api.list_rooms(FDA, params={"room_type_id": rt["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, data
    assert data[0]["id"] == room["id"], data
    assert "total_count" in meta and "has_more" in meta, meta


# ===========================================================================
# Corner/rbac/guest_cannot_create_hotel_returns_forbidden
# ===========================================================================
def test_guest_cannot_create_hotel_returns_forbidden():
    """PRD §2.1: "A `RevenueManager` exclusively creates hotels, room types, rooms, rate
    plans, and corporate accounts".
    PRD §2.1: "When an authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/guest_cannot_create_hotel_returns_forbidden
    """
    guest_headers = make_guest_headers("00000000-0000-4000-8000-000000000001")
    resp = api.create_hotel({"name": "Nope",
                             "current_business_date": "2026-07-01"}, guest_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Corner/rbac/front_desk_cannot_run_night_audit_returns_forbidden
# ===========================================================================
def test_front_desk_cannot_open_night_audit_returns_forbidden():
    """PRD §2.1: "A `NightAuditor` exclusively opens, completes, and aborts night audit
    runs."

    A FrontDeskAgent opening a night audit run returns ERR_FORBIDDEN.

    Design: Corner/rbac/front_desk_cannot_run_night_audit_returns_forbidden
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    resp = api.create_night_audit_run(
        {"hotel_id": hotel["id"], "expected_hotel_version": hotel["version"]}, FDA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Corner/rbac/missing_auth_headers_returns_unauthenticated
# ===========================================================================
def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing or malformed in either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    no_auth = {"Content-Type": "application/json"}
    resp = api.create_hotel({"name": "NoAuth",
                             "current_business_date": "2026-07-01"}, no_auth)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_assign_room_stale_version_returns_stale_room_version
# ===========================================================================
def test_assign_room_with_stale_room_version_returns_stale_room_version():
    """PRD §2.6: "When a room is assigned to a reservation, the request must carry
    `expected_room_version` matching the target `Room`'s current `version`; if another
    agent has advanced that room's `version` since the caller last read it ... the request
    is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412)."

    Room created (v1) then INSPECTED via housekeeping (v2); assign-room replaying v1 is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_assign_room_stale_version_returns_stale_room_version
    """
    b = setup_basic()
    room = create_room(b["hotel"]["id"], b["room_type"]["id"], room_number="141")
    stale_v = room["version"]  # v1
    get_success_data(api.room_housekeeping(
        room["id"], {"target": "INSPECTED", "expected_room_version": stale_v}, RM))  # -> v2
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-02"}, FDA))
    get_success_data(api.confirm_reservation(res["id"], FDA))

    resp = api.assign_room(res["id"],
        {"room_id": room["id"], "expected_room_version": stale_v}, FDA)
    validate_error(resp, ApiErrorId.ERR_STALE_ROOM_VERSION.value)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_block_pickup_stale_block_returns_stale_block_version
# ===========================================================================
def test_block_pickup_with_stale_block_version_returns_stale_block_version():
    """PRD §2.6: "When a reservation is created as a pickup from a group block, the request
    must carry `expected_group_block_version` matching the target `GroupBlock`'s current
    `version`; if the block's allotment was advanced since the caller last read it — by
    another pickup or by a cutoff wash that legitimately changed the block — the create is
    rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412)."

    First pickup bumps the block v1 -> v2; a second pickup replaying v1 is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_block_pickup_stale_block_returns_stale_block_version
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=9, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Conf",
                               arrival_date="2026-07-08", departure_date="2026-07-10",
                               cutoff_date="2026-07-07", blocked_rooms=4)
    stale_v = block["version"]  # v1
    guest1 = create_guest(hotel["id"], full_name="Ef E")
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest1["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": stale_v}, FDA))  # bumps block -> v2
    guest2 = create_guest(hotel["id"], full_name="Fg F")

    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest2["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": stale_v}, FDA)
    validate_error(resp, ApiErrorId.ERR_STALE_BLOCK_VERSION.value)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_void_incidental_stale_folio_returns_stale_version
# ===========================================================================
def test_void_incidental_with_stale_folio_version_returns_stale_version():
    """PRD §2.6: "voiding an incidental requires `expected_folio_version` matching the
    owning folio ... when the supplied expected version does not equal the current
    `version` of the named resource, the write is rejected with the stated stale-version
    error before any state change is applied." (Generic ERR_STALE_VERSION, HTTP 412.)
    PRD §2.9: "Whenever a cascade touches a secondary entity — flipping a room's
    housekeeping status, recomputing a group block's pickup count, recomputing
    availability, or adding to a corporate account's outstanding balance — that secondary
    entity is itself mutated: its `updated_at` is refreshed and its `version` is
    incremented by one, exactly as for a direct write."

    Folio version captured, then a second posting recomputes (mutates) the folio, bumping
    its version; voiding the first line with the stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_void_incidental_stale_folio_returns_stale_version
    """
    b = setup_basic()
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio = get_folio_for_reservation(b["hotel"]["id"], res["id"])
    inc = get_success_data(api.create_incidental({
        "hotel_id": b["hotel"]["id"], "folio_id": folio["id"], "kind": "CHARGE",
        "description": "Minibar", "amount_cents": 1000}, FDA))
    stale_folio = validate_success(api.get_folio(folio["id"], FDA))
    stale_v = stale_folio["version"]
    # Second posting bumps the folio version past stale_v.
    get_success_data(api.create_incidental({
        "hotel_id": b["hotel"]["id"], "folio_id": folio["id"], "kind": "CHARGE",
        "description": "Parking", "amount_cents": 2000}, FDA))

    resp = api.void_incidental(inc["id"], {"expected_folio_version": stale_v}, FDA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
