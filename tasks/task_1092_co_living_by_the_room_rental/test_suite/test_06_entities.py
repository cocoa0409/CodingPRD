"""Corner queue B — entity CRUD, defaults, computed fields, immutability."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    NON_EXISTENT_UUID, ApiErrorId, assert_screening_report,
    new_host, new_house, new_room, new_member, new_application, screen, decide,
    resubmit, base_portfolio, set_clock,
    create_house_payload, create_room_payload, create_application_payload,
    create_member_payload,
    admin_headers, manager_headers, make_host_headers, make_member_headers,
    compliance_headers,
)


def test_create_house_returns_201_with_zeroed_counts_and_open_posture(api):
    """PRD §3.1: "At creation the six room-state counts are all zero and
    compliance_posture is OPEN." PRD §2.4: "an integer version that starts at 1
    on creation".

    Design: Corner/entities/corner_create_house_returns_201_with_zeroed_room_counts_and_open_posture
    """
    host = new_host(api)
    house = validate_success(api.create_house(
        create_house_payload(host["id"], monthly_utility_budget_cents=60000),
        make_host_headers(host["id"])), 201)
    assert house["total_room_count"] == 0
    for f in ("vacant_room_count", "reserved_room_count", "occupied_room_count",
              "notice_pending_room_count", "out_of_service_room_count"):
        assert house[f] == 0
    assert house["compliance_posture"] == "OPEN"
    assert house["version"] == 1
    assert house["monthly_utility_budget_cents"] == 60000
    assert house["host_id"] == host["id"]


def test_get_room_by_id_returns_stored_room(api):
    """PRD §3.1: "A room is born VACANT" and carries "a computed
    available_from_date that stays null until the room enters NOTICE_PENDING."

    Design: Corner/entities/corner_get_room_by_id_returns_stored_room
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    room = new_room(api, house["id"], host["id"], "101",
                    weekly_rate_cents=25000, monthly_rate_cents=100000, private_bath=True)
    fetched = validate_success(api.get_room(room["id"], manager_headers()))
    assert fetched["room_number"] == "101"
    assert fetched["weekly_rate_cents"] == 25000 and fetched["monthly_rate_cents"] == 100000
    assert fetched["private_bath"] is True
    assert fetched["occupancy_state"] == "VACANT"
    assert fetched["available_from_date"] is None
    assert fetched["house_id"] == house["id"]


def test_list_rooms_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "total_count (the number of rows matching the filters before
    pagination), and has_more (true when rows remain beyond the current page)."

    Design: Corner/entities/corner_list_rooms_paginates_with_total_count_and_has_more
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    for n, wk, mo in [("101", 25000, 100000), ("102", 20000, 80000), ("103", 30000, 120000)]:
        new_room(api, house["id"], host["id"], n, weekly_rate_cents=wk, monthly_rate_cents=mo,
                 private_bath=False)
    page1, meta1 = validate_paginated(
        api.list_rooms(manager_headers(), params={"house_id": house["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api.list_rooms(manager_headers(), params={"house_id": house["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False


def test_get_membership_with_unknown_uuid_returns_not_found(api):
    """PRD §2.5: "The not-found code is specific to the entity that failed to
    resolve: ... ERR_MEMBERSHIP_NOT_FOUND ... all at HTTP 404."

    Design: Corner/entities/corner_get_membership_with_unknown_uuid_returns_membership_not_found
    """
    new_host(api)
    resp = api.get_membership(NON_EXISTENT_UUID, manager_headers())
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND.value)


def test_create_room_missing_required_weekly_rate_returns_invalid_request(api):
    """PRD §3.1: "a weekly_rate_cents and a monthly_rate_cents (both strictly
    greater than zero ...)". PRD §2.5: "Shape of the request body and query
    string — required fields present ... (ERR_INVALID_REQUEST)."

    Design: Corner/entities/corner_create_room_missing_required_weekly_rate_returns_invalid_request
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    resp = api.create_room({"house_id": house["id"], "room_number": "101",
                            "monthly_rate_cents": 100000}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    fetched = validate_success(api.get_house(house["id"], manager_headers()))
    assert fetched["total_room_count"] == 0


def test_create_room_omitting_private_bath_defaults_to_false(api):
    """PRD §3.1: "an optional private_bath boolean that defaults to false."

    Design: Corner/entities/corner_create_room_omitting_private_bath_defaults_to_false
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    room = validate_success(api.create_room(
        {"house_id": house["id"], "room_number": "101",
         "weekly_rate_cents": 25000, "monthly_rate_cents": 100000},
        make_host_headers(host["id"])), 201)
    assert room["private_bath"] is False
    assert room["occupancy_state"] == "VACANT"
    house_after = validate_success(api.get_house(house["id"], manager_headers()))
    assert house_after["total_room_count"] == 1 and house_after["vacant_room_count"] == 1


def test_required_income_derives_from_room_rate_not_declared_income(api):
    """PRD §3.2: "That declared figure is captured for the record but is never
    used to qualify anyone — only a vendor-verified figure ever qualifies an
    applicant." PRD §3.2: "required_income_cents, the bar the applicant's income
    must reach: the monthly_equivalent_cents multiplied by an income multiple of
    three, rounded half up to whole cents."

    Design: Corner/entities/corner_application_required_income_derives_from_room_rate_not_declared_income
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    room = new_room(api, house["id"], host["id"], "101",
                    weekly_rate_cents=25000, monthly_rate_cents=100000)
    member = new_member(api, full_name="Cyd Alvarez", email="cyd@resident.example",
                        declared_monthly_income_cents=1)
    app = new_application(api, member["id"], room["id"],
                          requested_move_in_date="2026-05-10", billing_cycle="WEEKLY")
    report = screen(api, app["id"], verified_monthly_income_cents=400000,
                    report_reference="SCR-C1")
    stored = validate_success(api.get_application(app["id"], compliance_headers()))
    assert stored["monthly_equivalent_cents"] == 108333
    assert stored["required_income_cents"] == 324999
    assert stored["status"] == "SCREENED" and stored["screening_round"] == 1
    assert report["sequence_number"] == 1
    assert validate_success(api.get_member(member["id"], manager_headers()))[
        "declared_monthly_income_cents"] == 1


def test_screening_report_is_append_only_with_no_version_field(api):
    """PRD §3.2: "A screening report is an append-only ledger row: it carries only
    id and created_at, no updated_at and no version." PRD §3.2: "The listing of
    an application's screening rounds returns them oldest first, ordered by
    created_at and then by sequence_number."

    Design: Corner/entities/corner_screening_report_is_append_only_with_no_version_field
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    room = new_room(api, house["id"], host["id"], "101",
                    weekly_rate_cents=25000, monthly_rate_cents=100000)
    member = new_member(api, full_name="Cyd Alvarez", email="cyd@resident.example",
                        declared_monthly_income_cents=100000)
    app = new_application(api, member["id"], room["id"],
                          requested_move_in_date="2026-05-10", billing_cycle="WEEKLY")
    report1 = screen(api, app["id"], verified_monthly_income_cents=100000, report_reference="SCR-C1")
    decide(api, app["id"], decision="APPROVE")   # income below bar, no cosigner -> CONDITIONAL
    resubmit(api, app["id"], member["id"])
    report2 = screen(api, app["id"], background_result="FLAGGED",
                     verified_monthly_income_cents=400000, report_reference="SCR-C2")
    assert report2["id"] != report1["id"]
    assert report2["sequence_number"] == 2
    rows, meta = validate_paginated(api.list_screening_reports(app["id"], manager_headers()))
    assert len(rows) == 2
    for r in rows:
        assert_screening_report(r)
        assert "version" not in r
    stored = validate_success(api.get_application(app["id"], compliance_headers()))
    assert stored["screening_round"] == 2 and stored["status"] == "SCREENED"


def test_create_application_with_invalid_billing_cycle_returns_invalid_request(api):
    """PRD §3.2: "a billing_cycle of either WEEKLY or MONTHLY." PRD §2.5: "enum
    members recognised ... (ERR_INVALID_REQUEST)."

    Design: Corner/entities/corner_create_application_with_invalid_billing_cycle_enum_returns_invalid_request
    """
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=60000)
    room = new_room(api, house["id"], host["id"], "101",
                    weekly_rate_cents=25000, monthly_rate_cents=100000)
    member = new_member(api, full_name="Cyd Alvarez", email="cyd@resident.example",
                        declared_monthly_income_cents=400000)
    resp = api.create_application(
        {"member_id": member["id"], "room_id": room["id"],
         "requested_move_in_date": "2026-05-10", "billing_cycle": "BIWEEKLY"},
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    rows, meta = validate_paginated(
        api.list_applications(manager_headers(), params={"member_id": member["id"]}))
    assert meta["total_count"] == 0


def test_create_room_under_unknown_house_returns_house_not_found(api):
    """PRD §2.5: "Resolution of every foreign key supplied in the request body,
    on house creation, room creation ... (ERR_HOST_NOT_FOUND, ERR_HOUSE_NOT_FOUND,
    ...)."

    Design: Corner/entities/corner_create_room_under_unknown_house_returns_house_not_found
    """
    host = new_host(api)
    resp = api.create_room(
        create_room_payload(NON_EXISTENT_UUID, "101"), make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_HOUSE_NOT_FOUND.value)


def test_member_system_fields_are_server_minted(api):
    """PRD §2.4: "Every stored resource carries a server-minted id, formatted as a
    UUID with no type prefix ... an integer version that starts at 1 on creation."
    PRD §3.2: "a freshly onboarded member has zero strike points and stands in
    band GOOD."

    Design: Corner/entities/corner_member_system_fields_are_server_minted
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    member = validate_success(api.create_member(
        create_member_payload(full_name="Cyd Alvarez", email="cyd@resident.example",
                              declared_monthly_income_cents=400000),
        admin_headers()), 201)
    assert is_valid_uuid(member["id"]) and "_" not in member["id"]
    assert member["version"] == 1
    assert member["created_at"] == "2026-06-01T00:00:00.000Z"
    assert member["strike_points"] == 0 and member["standing_band"] == "GOOD"


def test_duplicate_room_number_within_house_rejected_but_allowed_across_houses(api):
    """PRD §3.1: "A second room reusing an existing room_number in the same house
    is rejected with ERR_DUPLICATE_ROOM_NUMBER."

    Design: Corner/entities/corner_duplicate_room_number_within_house_returns_duplicate_room_number
    """
    host = new_host(api)
    houseA = new_house(api, host["id"], label="Peachtree A", monthly_utility_budget_cents=60000)
    houseB = new_house(api, host["id"], label="Peachtree B", address_line1="14 Peachtree St",
                       monthly_utility_budget_cents=45000)
    new_room(api, houseA["id"], host["id"], "101",
             weekly_rate_cents=25000, monthly_rate_cents=100000)
    dup = api.create_room(create_room_payload(houseA["id"], "101", weekly_rate_cents=26000,
                                              monthly_rate_cents=104000, private_bath=False),
                          make_host_headers(host["id"]))
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_ROOM_NUMBER.value)
    assert validate_success(api.get_house(houseA["id"], manager_headers()))["total_room_count"] == 1
    roomB = validate_success(api.create_room(
        create_room_payload(houseB["id"], "101", weekly_rate_cents=26000,
                            monthly_rate_cents=104000, private_bath=False),
        make_host_headers(host["id"])), 201)
    assert roomB["room_number"] == "101"
    assert validate_success(api.get_house(houseB["id"], manager_headers()))["total_room_count"] == 1
