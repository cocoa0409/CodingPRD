"""API contract basics: request shape, server-minted system fields, existence
checks, and list pagination with filters (PRD §2.3, §2.4, §2.6, §2.10)."""
from test_helpers import (
    ApiErrorId,
    assert_volunteer,
    create_crop_plan_payload,
    create_volunteer_payload,
    is_valid_uuid,
    make_admin_headers,
    make_bed,
    make_participating_volunteer,
    make_volunteer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "11111111-2222-3333-4444-555555555555"


def test_volunteer_create_missing_email_rejected(api):
    """PRD §2.6: "5. **Request shape.** Required fields are present, types are
    correct, enum values are valid members, and ranges hold — an end strictly
    after its start for dates and times, `minor_count` not exceeding
    `member_count`, `capacity_youth` not exceeding `capacity_total`, quantities
    strictly positive where required, and non-empty `rejection_reason`,
    `remediation_note`, and `revoked_reason` where those are required — otherwise
    `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "A `GardenAdmin` or `Coordinator` registers a new volunteer by
    supplying the volunteer's `full_name`, `email`, and `date_of_birth`".

    Design: Corner/entities/create_missing_required_field_returns_invalid_request
    """
    err = validate_error(
        api.create_volunteer(
            {"full_name": "No Email", "date_of_birth": "1990-05-20"},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_bed_create_invalid_sun_exposure_rejected(api):
    """PRD §2.6: "5. **Request shape.** Required fields are present, types are
    correct, enum values are valid members, and ranges hold".
    PRD §3.4: "a `sun_exposure` of `FULL`, `PARTIAL`, or `SHADE`".

    Design: Corner/entities/create_with_invalid_enum_returns_invalid_request
    """
    err = validate_error(
        api.create_bed(
            {
                "bed_code": "B-X",
                "size_sq_ft": 50,
                "sun_exposure": "BRIGHT",
                "irrigation_zone": "Z1",
            },
            make_admin_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_volunteer_create_ignores_client_supplied_system_fields(api):
    """PRD §2.4: "`id` (string): a unique, server-minted UUID, with no type
    prefix."
    PRD §2.10: "Derived counters — bed `allocated_sq_ft`, slot `confirmed_count`
    and `confirmed_youth_count`, tool stock counts, season water counters,
    recipient weekly commitments, volunteer service and no-show totals — are
    maintained by the server on every mutation that affects them; clients never
    write them directly."

    Design: Corner/entities/system_fields_input_ignored_on_create
    """
    supplied_id = "00000000-0000-0000-0000-000000000000"
    created = validate_success(
        api.create_volunteer(
            {
                "id": supplied_id,
                "version": 99,
                "total_service_minutes": 5000,
                "full_name": "Fake Id",
                "email": "fake@x.com",
                "date_of_birth": "1990-05-20",
            },
            make_admin_headers(),
        ),
        expected_status=201,
    )
    assert_volunteer(created)
    assert created["id"] != supplied_id, "the server mints the id"
    assert is_valid_uuid(created["id"])
    assert created["total_service_minutes"] == 0, (
        "client-supplied derived counters are ignored"
    )


def test_get_unknown_ids_return_entity_not_found(api):
    """PRD §2.10: "A reference to a missing season yields `ERR_SEASON_NOT_FOUND`,
    a missing bed `ERR_BED_NOT_FOUND`, a missing crop plan
    `ERR_CROP_PLAN_NOT_FOUND`, a missing slot `ERR_SHIFT_SLOT_NOT_FOUND`, a
    missing signup `ERR_SIGNUP_NOT_FOUND`, a missing booking
    `ERR_GROUP_BOOKING_NOT_FOUND`, a missing key `ERR_SHED_KEY_NOT_FOUND`, a
    missing tool `ERR_TOOL_NOT_FOUND`, a missing checkout
    `ERR_TOOL_CHECKOUT_NOT_FOUND`, a missing harvest log
    `ERR_HARVEST_LOG_NOT_FOUND`, a missing recipient `ERR_RECIPIENT_NOT_FOUND`, a
    missing allocation `ERR_ALLOCATION_NOT_FOUND`, a missing irrigation schedule
    `ERR_IRRIGATION_SCHEDULE_NOT_FOUND`, a missing certification
    `ERR_CERTIFICATION_NOT_FOUND`, and a missing volunteer
    `ERR_VOLUNTEER_NOT_FOUND`."

    Design: Corner/entities/get_by_unknown_id_returns_not_found
    """
    admin = make_admin_headers()
    err = validate_error(api.get_bed(UNKNOWN_ID, admin), ApiErrorId.ERR_BED_NOT_FOUND)
    assert err["error_id"] == "ERR_BED_NOT_FOUND"
    err = validate_error(
        api.get_volunteer(UNKNOWN_ID, admin), ApiErrorId.ERR_VOLUNTEER_NOT_FOUND
    )
    assert err["error_id"] == "ERR_VOLUNTEER_NOT_FOUND"


def test_body_foreign_keys_must_exist(api):
    """PRD §2.6: "3. **Existence.** Path identifiers are validated left to right,
    and then every foreign-key reference in the request body — `volunteer_id`,
    `slot_id`, `bed_id`, `season_id`, `tool_id`, the recipient ids inside `lines`,
    `supervision_adult_signup_id`, `signup_id`, `harvest_log_id`, `crop_plan_id`,
    `holder_volunteer_id`, `proposer_volunteer_id`, `logged_by_volunteer_id`,
    `leader_volunteer_id` — otherwise the referenced entity's not-found error
    (404), such as `ERR_VOLUNTEER_NOT_FOUND`, `ERR_SHIFT_SLOT_NOT_FOUND`, or
    `ERR_RECIPIENT_NOT_FOUND`."
    PRD §2.10: "the request is rejected with the not-found error of the first
    reference that does not exist."

    Design: Corner/entities/body_fk_must_exist_returns_not_found
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()

    # Only the slot reference is missing: the outcome is unique regardless of
    # the order in which body references are checked.
    err = validate_error(
        api.create_shift_signup(
            {"slot_id": UNKNOWN_ID, "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_SHIFT_SLOT_NOT_FOUND,
    )
    assert err["error_id"] == "ERR_SHIFT_SLOT_NOT_FOUND"

    # Only the season reference is missing (bed and proposer are real).
    bed = make_bed()
    err = validate_error(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=UNKNOWN_ID,
                bed_id=bed["id"],
                proposer_volunteer_id=vol["id"],
            ),
            admin,
        ),
        ApiErrorId.ERR_SEASON_NOT_FOUND,
    )
    assert err["error_id"] == "ERR_SEASON_NOT_FOUND"


def test_volunteer_list_pagination_limit_offset_and_standing_filter(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope.
    List endpoints also accept optional field-matching filters: volunteers filter
    by `standing`, `waiver_status`, and `orientation_status`".

    Design: Corner/entities/list_pagination_limit_offset_and_filter
    """
    admin = make_admin_headers()
    ids = [
        validate_success(
            api.create_volunteer(
                create_volunteer_payload(
                    full_name=f"V {n}", email=f"v{n}@x.com", date_of_birth="1990-05-20"
                ),
                admin,
            ),
            expected_status=201,
        )["id"]
        for n in (1, 2, 3)
    ]
    validate_success(api.set_standing(ids[2], {"to_state": "PROBATION"}, admin))

    page1, meta1 = validate_paginated(api.list_volunteers(admin, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_volunteers(admin, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(api.list_volunteers(admin, params={"standing": "PROBATION"}))
    assert len(filtered) == 1
    assert meta3["total_count"] == 1
    assert filtered[0]["id"] == ids[2]
    assert filtered[0]["standing"] == "PROBATION"
