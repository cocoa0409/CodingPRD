"""Entity creation, reads, listing, defaults, snapshots and field-level rejections."""

import pytest

from test_helpers import (
    COUNSELOR,
    NON_EXISTENT_UUID,
    OMIT,
    ADMIN,
    ApiErrorId,
    amend_order_payload,
    api_client,
    assert_common_fields,
    assert_order,
    assert_service_member,
    create_capacity_block_payload,
    create_counseling_session,
    create_order,
    create_order_payload,
    create_service_member,
    create_service_member_payload,
    create_tsp,
    complete_counseling,
    get_success_data,
    read_capacity_block,
    set_clock,
    setup_booked_shipment,
    setup_second_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

READ_PATHS = [
    ("get_service_member", ApiErrorId.ERR_SERVICE_MEMBER_NOT_FOUND),
    ("get_order", ApiErrorId.ERR_ORDER_NOT_FOUND),
    ("get_counseling_session", ApiErrorId.ERR_COUNSELING_SESSION_NOT_FOUND),
    ("get_entitlement", ApiErrorId.ERR_ENTITLEMENT_NOT_FOUND),
    ("get_tsp", ApiErrorId.ERR_TSP_NOT_FOUND),
    ("get_capacity_block", ApiErrorId.ERR_CAPACITY_BLOCK_NOT_FOUND),
    ("get_shipment", ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
    ("get_pro_gear_declaration", ApiErrorId.ERR_PRO_GEAR_DECLARATION_NOT_FOUND),
    ("get_sit_authorization", ApiErrorId.ERR_SIT_AUTHORIZATION_NOT_FOUND),
    ("get_claim", ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("get_claim_item", ApiErrorId.ERR_CLAIM_ITEM_NOT_FOUND),
    ("get_ppm_submission", ApiErrorId.ERR_PPM_SUBMISSION_NOT_FOUND),
    ("get_notification", ApiErrorId.ERR_NOTIFICATION_NOT_FOUND),
]


def _member_only():
    """One registered member on an otherwise empty database."""
    set_clock()
    return create_service_member()


def _member_with_two_shipments():
    """An authorized entitlement carrying a household-goods and a baggage shipment."""
    scenario = setup_booked_shipment()
    scenario["shipment_2"] = setup_second_shipment(
        scenario,
        shipment_code="SHP-C02",
        shipment_method="UB",
        requested_pickup_date="2026-08-18T00:00:00Z",
        requested_delivery_date="2026-08-25T00:00:00Z",
    )
    return scenario


def _order_attempt(member_id, **overrides):
    return api_client.create_order(
        create_order_payload(member_id, **overrides), COUNSELOR
    )


class TestEntityCreationAndReads:
    """A created member, and the reads that return it and its orders."""

    def test_registering_a_member_returns_the_created_record(self):
        """The counselor's registration is created with a zero shipment count.

        "The member's `active_shipment_count` starts at 0; the system maintains it as the
        count of that member's shipments whose `movement_status` is neither `DELIVERED` nor
        `CANCELLED`"

        Design: Corner/entities/service_member_created_with_system_and_computed_fields_returns_201
        """
        set_clock()

        member = validate_success(
            api_client.create_service_member(create_service_member_payload(), COUNSELOR),
            201,
        )
        assert_service_member(member)
        assert member["dod_id"] == "7000000001"
        assert member["rank_code"] == "E6"
        assert member["branch"] == "ARMY"
        assert member["dependents_count"] == 2
        assert member["spouse_present"] is True
        assert member["active_shipment_count"] == 0
        assert member["version"] == 1

    def test_the_member_and_order_reads_return_what_was_stored(self):
        """The order carries the member's dependent count as an issuance snapshot.

        "Issuance also snapshots the member's current `dependents_count` into
        `dependents_count_at_issue`, and sets `status` to `ISSUED`, `amendment_count` to 0
        and `last_amendment_reason` to null."

        Design: Corner/entities/member_and_order_reads_return_the_stored_and_snapshotted_values
        """
        member = _member_only()
        order = create_order(member["id"], order_number="ORD-C-02")

        member_read = validate_success(
            api_client.get_service_member(member["id"], COUNSELOR), 200
        )
        order_read = validate_success(api_client.get_order(order["id"], COUNSELOR), 200)

        assert member_read["full_name"] == "Dana Reyes"
        assert member_read["email"] == "dana.reyes@example.mil"
        assert_order(order_read)
        assert order_read["service_member_id"] == member["id"]
        assert order_read["order_number"] == "ORD-C-02"
        assert order_read["dependents_count_at_issue"] == 2
        assert order_read["is_dependent_restricted"] is False
        assert order_read["status"] == "ISSUED"
        assert order_read["amendment_count"] == 0
        assert order_read["last_amendment_reason"] is None

    def test_the_shipment_list_pages_through_two_records(self):
        """One shipment per page reports a total of two and a truthful has_more.

        "`offset` sets how many records are skipped before the page begins; when omitted it
        defaults to 0 and it may not be negative. Both are echoed in the `meta` object of
        the envelope alongside `total_count` (the number of records matching the request
        before the page window is applied) and `has_more` (true when records remain beyond
        the current window)."

        Design: Corner/entities/shipment_list_paginates_with_total_count_and_has_more
        """
        scenario = _member_with_two_shipments()

        first_rows, first_meta = validate_paginated(
            api_client.list_shipments(COUNSELOR, params={"limit": 1, "offset": 0})
        )
        second_rows, second_meta = validate_paginated(
            api_client.list_shipments(COUNSELOR, params={"limit": 1, "offset": 1})
        )

        assert len(first_rows) == 1
        assert first_meta["total_count"] == 2
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        assert len(second_rows) == 1
        assert second_meta["total_count"] == 2
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False

        assert {first_rows[0]["id"], second_rows[0]["id"]} == {
            scenario["shipment"]["id"],
            scenario["shipment_2"]["id"],
        }

        member = get_success_data(
            api_client.get_service_member(scenario["member"]["id"], COUNSELOR)
        )
        assert member["active_shipment_count"] == 2

    def test_every_read_path_names_its_own_missing_entity(self):
        """Thirteen unknown identifiers produce thirteen distinct not-found codes.

        "identifiers are resolved strictly left to right, and the first unresolvable
        identifier determines the 404 that is returned: `ERR_SERVICE_MEMBER_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_COUNSELING_SESSION_NOT_FOUND`,
        `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_TSP_NOT_FOUND`, `ERR_CAPACITY_BLOCK_NOT_FOUND`,
        `ERR_SHIPMENT_NOT_FOUND`, `ERR_PRO_GEAR_DECLARATION_NOT_FOUND`,
        `ERR_SIT_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_CLAIM_ITEM_NOT_FOUND`, `ERR_PPM_SUBMISSION_NOT_FOUND` or
        `ERR_NOTIFICATION_NOT_FOUND`."

        Design: Corner/entities/unknown_ids_on_every_read_path_return_their_entity_not_found
        """
        set_clock()

        for method_name, error_id in READ_PATHS:
            response = getattr(api_client, method_name)(NON_EXISTENT_UUID, COUNSELOR)
            validate_error(response, error_id.value, 404)


class TestOrderCreationRejections:
    """Bad parents, missing fields, ignored system fields and out-of-range values."""

    def test_an_order_for_an_unknown_member_is_not_found(self):
        """A live member exists, but the order names somebody else entirely.

        "Orders are issued against a member. The issuing counselor or administrator supplies
        `service_member_id`, the printed `order_number` (4 to 32 characters, unique across
        all orders — a collision yields `ERR_DUPLICATE_ORDER_NUMBER`)"

        Design: Corner/entities/order_create_with_unknown_service_member_id_not_found
        """
        member = _member_only()

        validate_error(
            _order_attempt(NON_EXISTENT_UUID),
            ApiErrorId.ERR_SERVICE_MEMBER_NOT_FOUND.value,
            404,
        )

        _, meta = validate_paginated(
            api_client.list_service_member_orders(member["id"], COUNSELOR)
        )
        assert meta["total_count"] == 0

    def test_an_order_without_mileage_is_an_invalid_request(self):
        """Mileage is not optional, so the order never comes into being.

        "Mileage must be greater than zero and no more than 12,000."

        Design: Corner/entities/order_create_missing_required_distance_returns_invalid_request
        """
        member = _member_only()

        validate_error(
            _order_attempt(member["id"], distance_miles=OMIT),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(
            api_client.list_service_member_orders(member["id"], COUNSELOR)
        )
        assert meta["total_count"] == 0

    def test_client_supplied_system_fields_are_ignored(self):
        """A client asking for a closed order with seven amendments gets neither.

        "A counselor or administrator may amend a set of orders, moving `status` from
        `ISSUED` to `AMENDED` (or from `AMENDED` to `AMENDED` again, a self-loop)."

        Design: Corner/entities/order_create_extra_field_status_input_ignored
        """
        member = _member_only()

        order = validate_success(
            _order_attempt(
                member["id"],
                id="11111111-1111-4111-8111-111111111111",
                status="CLOSED",
                amendment_count=7,
                dependents_count_at_issue=9,
            ),
            201,
        )
        assert order["id"] != "11111111-1111-4111-8111-111111111111"
        assert order["status"] == "ISSUED"
        assert order["amendment_count"] == 0
        assert order["dependents_count_at_issue"] == 2

        amended = validate_success(
            api_client.amend_order(
                order["id"],
                amend_order_payload(
                    amendment_reason="ORDERS REISSUED",
                    report_no_later_than_date_override="2026-10-15T00:00:00Z",
                ),
                COUNSELOR,
            ),
            200,
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1

    def test_bad_enums_and_out_of_range_numbers_are_rejected(self):
        """An invented branch, zero mileage and a negative capacity are all refused.

        "`branch` must be one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINE_CORPS`,
        `SPACE_FORCE` or `COAST_GUARD`."

        Design: Corner/entities/enum_and_numeric_range_violations_are_rejected
        """
        member = _member_only()
        tsp = create_tsp()

        validate_error(
            api_client.create_service_member(
                create_service_member_payload(
                    dod_id="7000000002", branch="COAST_GUARD_RESERVE"
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            _order_attempt(member["id"], distance_miles=0),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api_client.create_capacity_block(
                create_capacity_block_payload(tsp["id"], total_capacity_lbs=-12000),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(
            api_client.list_tsp_capacity_blocks(tsp["id"], ADMIN)
        )
        assert meta["total_count"] == 0


class TestDefaultsAndComputedFields:
    """Omitted optional fields and server-derived instants."""

    def test_omitted_optional_fields_take_their_declared_defaults(self):
        """No dependents, no spouse, a 0.15 reserve and an 8,500 pound general pool.

        "it may carry a `short_notice_reserve_pct` between 0 and 0.5 inclusive, which
        defaults to 0.15"

        Design: Corner/entities/omitted_optional_fields_fall_back_to_declared_defaults
        """
        set_clock("2026-10-26T00:00:00Z")
        tsp = create_tsp()

        member = create_service_member(
            rank_code="E5",
            branch="NAVY",
            dependents_count=OMIT,
            spouse_present=OMIT,
        )
        assert member["dependents_count"] == 0
        assert member["spouse_present"] is False

        order = create_order(
            member["id"],
            issue_date="2026-10-01T00:00:00Z",
            report_no_later_than_date="2026-12-01T00:00:00Z",
            distance_miles=2600,
        )
        assert order["is_dependent_restricted"] is False
        assert order["dependents_count_at_issue"] == 0

        block = validate_success(
            api_client.create_capacity_block(
                create_capacity_block_payload(
                    tsp["id"],
                    week_start_date="2026-11-02T00:00:00Z",
                    total_capacity_lbs=10000,
                    short_notice_reserve_pct=OMIT,
                ),
                ADMIN,
            ),
            201,
        )
        assert block["short_notice_reserve_pct"] == pytest.approx(0.15, abs=0.0001)
        assert block["effective_reserve_pct"] == pytest.approx(0.15, abs=0.0001)
        assert block["peak_season"] is False
        assert block["general_pool_lbs"] == 8500
        assert block["short_notice_pool_lbs"] == 1500
        assert block["week_end_date"] == "2026-11-09T00:00:00Z"

        stored = read_capacity_block(block["id"])
        assert stored["committed_general_lbs"] == 0
        assert stored["committed_short_notice_lbs"] == 0
        assert stored["committed_lbs"] == 0
        assert stored["status"] == "OPEN"

    def test_the_counseling_deadline_is_derived_at_booking(self):
        """Orders reporting 1 October give a 17 September deadline, met on 3 August.

        "`is_late_counseling` is set true when `completed_at` falls strictly after
        `counseling_deadline_at` — completing exactly at the deadline is not late."

        Design: Corner/entities/counseling_deadline_is_computed_from_the_report_date
        """
        member = _member_only()
        order = create_order(member["id"])

        session = create_counseling_session(order["id"], session_type="VIRTUAL")
        assert_common_fields(session, "CounselingSession")
        assert session["counseling_deadline_at"] == "2026-09-17T00:00:00Z"
        assert session["status"] == "SCHEDULED"
        assert session["completed_at"] is None
        assert session["is_late_counseling"] is False

        complete_counseling(session["id"])
        completed = get_success_data(
            api_client.get_counseling_session(session["id"], COUNSELOR)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] == "2026-08-03T00:00:00Z"
        assert completed["is_late_counseling"] is False
