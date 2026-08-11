"""The register: accounts, properties, wells, technicians and shared ownership."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_account,
    assert_close,
    assert_instant_equals,
    assert_pagination_meta,
    fixtures,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_account_creation_returns_every_declared_field(api):
    """PRD 2.4: "On server start the clock reads exactly `2026-05-01T00:00:00Z` and it
    must never fall back to real time."
    PRD 3.1: "A freshly created account starts with `balance_cents` 0,
    `lifetime_invoiced_cents` 0, `lifetime_paid_cents` 0 and `credit_hold` false."
    PRD 2.5: "Nineteen of the twenty-one entity kinds additionally carry `updated_at` —
    an instant refreshed from the logical clock on every mutation of that row — and
    `version`, an integer that starts at 1 when the row is created."

    Design: Corner/entities/corner_account_creation_returns_all_declared_fields
    """
    clock0 = validate_success(api.get_clock(ADMIN))
    assert_instant_equals(clock0["current_utc"], "2026-05-01T00:00:00Z", "current_utc")

    response = api.create_account(
        {
            "legal_name": "Corner Account One",
            "billing_jurisdiction_code": "JUR_ALPHA",
            "contact_email": "one@corner.example",
            "membership_tier": "SELECT",
        },
        ADMIN,
    )
    account = validate_success(response, 201)
    assert_account(account)
    assert account["legal_name"] == "Corner Account One"
    assert account["membership_tier"] == "SELECT"
    assert account["balance_cents"] == 0
    assert account["lifetime_invoiced_cents"] == 0
    assert account["lifetime_paid_cents"] == 0
    assert account["credit_hold"] is False
    assert account["version"] == 1


def test_account_membership_tier_defaults_to_none(api):
    """PRD 3.1: "When `membership_tier` is omitted it defaults to `NONE`; the other
    members are `SELECT` and `PREMIER`."
    PRD 3.1: "A freshly created account starts with `balance_cents` 0,
    `lifetime_invoiced_cents` 0, `lifetime_paid_cents` 0 and `credit_hold` false."

    Design: Corner/entities/corner_account_membership_tier_defaults_to_none
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = validate_success(
        api.create_account(
            {
                "legal_name": "Default Tier Co",
                "billing_jurisdiction_code": "JUR_BRAVO",
                "contact_email": "def@corner.example",
            },
            ADMIN,
        ),
        201,
    )
    assert account["membership_tier"] == "NONE"
    assert account["credit_hold"] is False


def test_account_read_with_unknown_id_returns_account_not_found(api):
    """PRD 2.6: "An unresolved `account_id` is `ERR_ACCOUNT_NOT_FOUND`."
    PRD 2.6: "Each identifier — whether it arrives as a path segment at G3 or as a body
    field at G9A — has exactly one error that answers a value which does not resolve to
    a stored row, and all of them are HTTP 404."

    Design: Corner/entities/corner_account_get_with_unknown_id_returns_not_found
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    validate_error(
        api.get_account(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404
    )


def test_property_missing_required_field_is_a_payload_failure(api):
    """PRD 2.7: "A missing required field, or one of the wrong JSON type, is
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/corner_property_missing_required_field_returns_invalid_request
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Missing Field Co", "JUR_ALPHA", "mf@corner.example"
    )
    validate_error(
        api.create_property(
            {
                "account_id": account["id"],
                "address_line": "1 Missing",
                "jurisdiction_code": "JUR_ALPHA",
                "distance_miles": 10.0,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )
    rows, _ = validate_paginated(
        api.list_properties(ADMIN, params={"account_id": account["id"]})
    )
    assert rows == [], "A refused creation must leave no property behind"


def test_property_service_zone_is_derived_at_every_band_edge(api):
    """PRD 3.1: "A distance of exactly 15.0 is `ZONE_1`, 15.01 is `ZONE_2`, exactly 60.0
    is `ZONE_3` and 60.01 is `OUT_OF_AREA`."
    PRD 3.1: "The resulting `service_zone` is stored on the property at creation and
    re-derived on every read of it."

    Design: Corner/entities/corner_property_service_zone_is_computed_at_every_boundary
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Zone Boundary Co", "JUR_ALPHA", "zb@corner.example")

    expectations = [
        ("15 Zone", 15.0, "ZONE_1"),
        ("15.01 Zone", 15.01, "ZONE_2"),
        ("60 Zone", 60.0, "ZONE_3"),
        ("60.01 Zone", 60.01, "OUT_OF_AREA"),
    ]
    for address, miles, zone in expectations:
        created = validate_success(
            api.create_property(
                {
                    "account_id": account["id"],
                    "address_line": address,
                    "jurisdiction_code": "JUR_ALPHA",
                    "distance_miles": miles,
                    "household_size": 2,
                },
                ADMIN,
            ),
            201,
        )
        assert created["service_zone"] == zone, (
            f"{miles} miles must band to {zone}, got {created['service_zone']}"
        )
        assert fixtures.get_property(created["id"])["service_zone"] == zone


def test_well_profile_rejects_an_undeclared_well_type(api):
    """PRD 2.7: "`well_type` — on well-profile creation. Members: `DRILLED`, `DRIVEN`,
    `DUG`."
    PRD 2.7: "`ERR_INVALID_ENUM` (HTTP 400) is reserved for enum-typed **body** fields
    on **mutating** endpoints, and the set of fields that route to it is closed."

    Design: Corner/entities/corner_well_profile_invalid_enum_value_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Enum Co", "JUR_ALPHA", "en@corner.example")
    prop = fixtures.new_property(account["id"], "1 Enum", "JUR_ALPHA", 10.0, 2)
    validate_error(
        api.create_well_profile(
            {
                "property_id": prop["id"],
                "jurisdiction_code": "JUR_ALPHA",
                "well_type": "PUNCHED",
                "depth_feet": 100.0,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_ENUM.value,
        400,
    )


def test_well_profile_body_foreign_key_fails_at_the_business_gate(api):
    """PRD 2.6: "Sub-gate **G9A** resolves body-referenced foreign keys; a body field
    naming a row that does not exist fails *here*, with that entity's `*_NOT_FOUND`
    error, and never at G3."
    PRD 2.6: "An unresolved `property_id` is `ERR_PROPERTY_NOT_FOUND`."

    Design: Corner/entities/corner_well_profile_body_fk_unknown_property_not_found_at_g9
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    validate_error(
        api.create_well_profile(
            {
                "property_id": "11111111-2222-4333-8444-555555555555",
                "jurisdiction_code": "JUR_ALPHA",
                "well_type": "DRILLED",
                "depth_feet": 100.0,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_PROPERTY_NOT_FOUND.value,
        404,
    )


def test_technician_listing_paginates_with_the_declared_envelope(api):
    """PRD 2.3: "The `meta` block of a list response carries `limit` and `offset` as they
    were actually applied (after defaulting), `total_count` as the number of rows
    matching the filters *before* the slice is taken, and `has_more`, which is true
    exactly when the sum of `offset` and `limit` is strictly less than `total_count`."
    PRD 2.3: "Unless an endpoint explicitly says otherwise, every list is sorted by
    `created_at` ascending — oldest first."

    Design: Corner/entities/corner_technician_listing_paginates_with_envelope_fields
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    fixtures.new_technician("Tech A", "APPRENTICE", "JUR_ALPHA")
    tech_b = fixtures.new_technician("Tech B", "JOURNEYMAN", "JUR_ALPHA")
    tech_c = fixtures.new_technician("Tech C", "MASTER", "JUR_ALPHA")

    rows, meta = validate_paginated(
        api.list_technicians(ADMIN, params={"limit": 2, "offset": 1})
    )
    assert_pagination_meta(meta, limit=2, offset=1, total_count=3)
    assert ids_of(rows) == [tech_b["id"], tech_c["id"]]


def test_shared_well_agreement_links_a_well_and_an_account(api):
    """PRD 3.1: "A `PlatformAdmin` or `BillingClerk` records a share by naming a
    `well_profile_id`, an `account_id` and a `split_pct` between 0.01 and 100.00
    inclusive, expressed in percent with two decimals."
    PRD 3.1: "Each agreement's `status` starts `ACTIVE` and the only other member is
    `TERMINATED`."

    Design: Corner/entities/corner_shared_well_agreement_links_two_aggregates
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account_a = fixtures.new_account("Share A", "JUR_ALPHA", "a@share.example")
    account_b = fixtures.new_account("Share B", "JUR_ALPHA", "b@share.example")
    prop = fixtures.new_property(account_a["id"], "1 Share", "JUR_ALPHA", 10.0, 2)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)

    agreement = validate_success(
        api.create_shared_well_agreement(
            {
                "well_profile_id": well["id"],
                "account_id": account_b["id"],
                "split_pct": 60.00,
            },
            BILLING,
        ),
        201,
    )
    assert agreement["status"] == "ACTIVE"
    assert_close(agreement["split_pct"], 60.00, "SharedWellAgreement.split_pct")

    by_well, _ = validate_paginated(
        api.list_shared_well_agreements(BILLING, params={"well_profile_id": well["id"]})
    )
    assert ids_of(by_well) == [agreement["id"]]

    by_account, _ = validate_paginated(
        api.list_shared_well_agreements(BILLING, params={"account_id": account_b["id"]})
    )
    assert ids_of(by_account) == [agreement["id"]]


def test_well_profile_default_drawdown_derives_the_duty_cycle(api):
    """PRD 3.1: "A drawdown of 12.0 gallons gives 2.50; 10.0 gives 3.00; 6.0 gives 5.00;
    5.0 gives 6.00; 4.0 gives 7.50."
    PRD 3.1: "a ratio of at most 3.00 is `LOW`, a ratio above 3.00 and at most 6.00 is
    `MODERATE`, and anything above 6.00 is `HIGH`."
    PRD 3.1: "A new well profile also starts with `potability_status` `UNKNOWN`,
    `treatment_media` `NONE`, and `measured_yield_gpm`, `hardness_gpg`,
    `last_inspection_completed_at` and `advisory_reason` all null."

    Design: Corner/entities/corner_well_profile_defaults_drawdown_and_derives_duty_cycle
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Default Drawdown Co", "JUR_ALPHA", "dd@corner.example"
    )
    prop = fixtures.new_property(account["id"], "6 Default", "JUR_ALPHA", 10.0, 2)

    well = validate_success(
        api.create_well_profile(
            {
                "property_id": prop["id"],
                "jurisdiction_code": "JUR_ALPHA",
                "well_type": "DRIVEN",
                "depth_feet": 60.0,
            },
            ADMIN,
        ),
        201,
    )
    assert_close(
        well["pressure_tank_drawdown_gallons"],
        6.0,
        "WellProfile.pressure_tank_drawdown_gallons",
    )
    assert_close(well["duty_cycle_ratio"], 5.00, "WellProfile.duty_cycle_ratio")
    assert well["duty_cycle_class"] == "MODERATE"
    assert well["potability_status"] == "UNKNOWN"
    assert well["measured_yield_gpm"] is None


def test_shared_well_agreement_terminates_and_frees_the_split(api):
    """PRD 3.1: "Terminating an agreement sets its `status` to `TERMINATED` and raises
    its `version` by 1; because the 100.00 identity is enforced only on creation, a
    termination may legitimately leave a well under-allocated."
    PRD 3.11: "The candidate shares are the `ACTIVE` agreements on the well, ordered by
    `created_at` ascending; `TERMINATED` agreements are excluded."

    Design: Corner/state_machines/corner_shared_well_agreement_terminate
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account_a = fixtures.new_account("Term A", "JUR_ALPHA", "ta@corner.example")
    account_b = fixtures.new_account("Term B", "JUR_ALPHA", "tb@corner.example")
    account_c = fixtures.new_account("Term C", "JUR_ALPHA", "tcc@corner.example")
    prop = fixtures.new_property(account_a["id"], "16 Term", "JUR_ALPHA", 10.0, 2)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    agreement_b = fixtures.new_shared_well_agreement(well["id"], account_b["id"], 100.00)

    terminated = validate_success(
        api.terminate_shared_well_agreement(agreement_b["id"], ADMIN)
    )
    assert terminated["status"] == "TERMINATED"

    agreement_c = validate_success(
        api.create_shared_well_agreement(
            {
                "well_profile_id": well["id"],
                "account_id": account_c["id"],
                "split_pct": 100.00,
            },
            BILLING,
        ),
        201,
    )
    assert agreement_c["status"] == "ACTIVE"

    active, _ = validate_paginated(
        api.list_shared_well_agreements(
            BILLING, params={"well_profile_id": well["id"], "status": "ACTIVE"}
        )
    )
    assert ids_of(active) == [agreement_c["id"]]


def test_shared_well_party_ceiling_binds_before_the_percentage_ceiling(api):
    """PRD 3.1: "Second, after the write the `ACTIVE` shares on the well must not
    **exceed** 100.00 in total and must not number more than `SHARED_WELL_MAX_PARTIES`
    (4); a violation of either is refused with `ERR_SHARED_WELL_SPLIT_INVALID`."
    PRD 3.1: "Under-allocation is deliberately *permitted* at creation time — the
    exact-100.00 identity is required only for the split to actually be applied when
    invoices are built, as Section 3.11 describes."

    Design: Corner/validations/corner_validation_shared_well_party_count_ceiling
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    accounts = [
        fixtures.new_account(f"Party {n} Co", "JUR_ALPHA", f"p{n}@corner.example")
        for n in range(1, 6)
    ]
    prop = fixtures.new_property(accounts[0]["id"], "5 Parties", "JUR_ALPHA", 10.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)

    fourth = None
    for account in accounts[:4]:
        fourth = validate_success(
            api.create_shared_well_agreement(
                {
                    "well_profile_id": well["id"],
                    "account_id": account["id"],
                    "split_pct": 20.00,
                },
                BILLING,
            ),
            201,
        )
    assert fourth["status"] == "ACTIVE"
    assert_close(fourth["split_pct"], 20.00, "SharedWellAgreement.split_pct")

    validate_error(
        api.create_shared_well_agreement(
            {
                "well_profile_id": well["id"],
                "account_id": accounts[4]["id"],
                "split_pct": 10.00,
            },
            BILLING,
        ),
        ApiErrorId.ERR_SHARED_WELL_SPLIT_INVALID.value,
        422,
    )

    rows, _ = validate_paginated(
        api.list_shared_well_agreements(BILLING, params={"well_profile_id": well["id"]})
    )
    assert len(rows) == 4
    rows_five, _ = validate_paginated(
        api.list_shared_well_agreements(
            BILLING, params={"account_id": accounts[4]["id"]}
        )
    )
    assert rows_five == []


def test_response_envelope_has_three_distinct_shapes(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/endpoints/corner_endpoint_success_envelope_object_array_and_error_shapes
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account_1 = fixtures.new_account("Envelope One Co", "JUR_ALPHA", "e1@corner.example")
    account_2 = fixtures.new_account(
        "Envelope Two Co", "JUR_BRAVO", "e2@corner.example", membership_tier="PREMIER"
    )

    single = api.get_account(account_2["id"], ADMIN)
    body = single.json()
    assert body["response_type"] == "object"
    assert body["data"]["legal_name"] == "Envelope Two Co"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    listing = api.list_accounts(ADMIN, params={"limit": 10, "offset": 0})
    list_body = listing.json()
    assert list_body["response_type"] == "array"
    rows, meta = validate_paginated(listing)
    assert ids_of(rows) == [account_1["id"], account_2["id"]]
    assert_pagination_meta(meta, limit=10, offset=0, total_count=2)

    missing = api.get_account(UNKNOWN_UUID, ADMIN)
    assert missing.json()["response_type"] == "error"
    error = validate_error(missing, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)
    assert error["message"].strip()


def test_technician_list_filters_combine_conjunctively(api):
    """PRD 2.3: "List endpoints also accept the optional filter parameters named for them
    in Section 4. A filter parameter is an exact-match filter on the named field."
    PRD 4.6: "Request: optional filters `tier`, `status`, `home_jurisdiction_code`, plus
    `limit` and `offset`."

    Design: Corner/endpoints/corner_endpoint_technician_list_filters_combine_conjunctively
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    tf1 = fixtures.new_technician("Filter Master Alpha", "MASTER", "JUR_ALPHA", "AVAILABLE")
    tf2 = fixtures.new_technician("Filter Master Off", "MASTER", "JUR_ALPHA", "OFF_DUTY")
    tf3 = fixtures.new_technician(
        "Filter Journeyman Bravo", "JOURNEYMAN", "JUR_BRAVO", "AVAILABLE"
    )
    tf4 = fixtures.new_technician(
        "Filter Apprentice Alpha", "APPRENTICE", "JUR_ALPHA", "AVAILABLE"
    )

    masters, meta = validate_paginated(
        api.list_technicians(DISPATCHER, params={"tier": "MASTER"})
    )
    assert ids_of(masters) == [tf1["id"], tf2["id"]]
    assert meta["total_count"] == 2

    available, _ = validate_paginated(
        api.list_technicians(DISPATCHER, params={"status": "AVAILABLE"})
    )
    assert ids_of(available) == [tf1["id"], tf3["id"], tf4["id"]]

    bravo, _ = validate_paginated(
        api.list_technicians(DISPATCHER, params={"home_jurisdiction_code": "JUR_BRAVO"})
    )
    assert ids_of(bravo) == [tf3["id"]]

    combined, combined_meta = validate_paginated(
        api.list_technicians(
            DISPATCHER,
            params={
                "tier": "MASTER",
                "status": "AVAILABLE",
                "home_jurisdiction_code": "JUR_ALPHA",
            },
        )
    )
    assert ids_of(combined) == [tf1["id"]]
    assert_pagination_meta(combined_meta, limit=10, offset=0, total_count=1)


def test_pagination_window_bounds_are_inclusive_on_the_passing_side(api):
    """PRD 2.3: "`limit` defaults to 10 when omitted, and must be an integer of at least
    1 and at most 100. `offset` defaults to 0 when omitted, and must be an integer of at
    least 0; there is no upper bound on `offset`. A `limit` of 0, a `limit` above 100, a
    negative `offset`, or a value of either that is not an integer is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/corner_validation_pagination_limit_and_offset_boundaries
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    t1 = fixtures.new_technician("Page Tech One", "APPRENTICE", "JUR_ALPHA", "AVAILABLE")
    t2 = fixtures.new_technician("Page Tech Two", "JOURNEYMAN", "JUR_BRAVO", "AVAILABLE")
    t3 = fixtures.new_technician("Page Tech Three", "MASTER", "JUR_ALPHA", "OFF_DUTY")

    rows, meta = validate_paginated(api.list_technicians(ADMIN, params={"limit": 1}))
    assert ids_of(rows) == [t1["id"]]
    assert_pagination_meta(meta, limit=1, offset=0, total_count=3)

    rows, meta = validate_paginated(api.list_technicians(ADMIN, params={"limit": 100}))
    assert ids_of(rows) == [t1["id"], t2["id"], t3["id"]]
    assert_pagination_meta(meta, limit=100, offset=0, total_count=3)

    rows, meta = validate_paginated(api.list_technicians(ADMIN, params={"offset": 3}))
    assert rows == []
    assert_pagination_meta(meta, limit=10, offset=3, total_count=3)

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_technicians(ADMIN, params=params),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            400,
        )


def test_technician_availability_patch_blocks_the_next_dispatch(api):
    """PRD 3.1: "Availability is mutable by a `PlatformAdmin` or a `Dispatcher` and bumps
    the row's `version` by 1."
    PRD 3.8: "**Dispatch** takes `TRIAGED → DISPATCHED`: the dispatcher names a
    `technician_id`, which must resolve (or the answer is `ERR_TECHNICIAN_NOT_FOUND` at
    the business gate) and whose `status` must be `AVAILABLE` (or the answer is
    `ERR_TECHNICIAN_UNAVAILABLE`)."

    Design: Corner/endpoints/corner_technician_patch_toggles_availability_and_blocks_dispatch
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Offduty Co",
        email="od@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="4 Offduty",
        technician_name="Offduty Tech",
    )
    ticket = fixtures.new_emergency_ticket(
        world["property_id"], world["well_id"], world["account_id"], 2.0
    )
    validate_success(api.triage_ticket(ticket["id"], DISPATCHER))

    patched = validate_success(
        api.patch_technician(world["technician_id"], {"status": "OFF_DUTY"}, ADMIN)
    )
    assert patched["status"] == "OFF_DUTY"
    assert patched["version"] == 2

    validate_error(
        api.dispatch_ticket(
            ticket["id"], {"technician_id": world["technician_id"]}, DISPATCHER
        ),
        ApiErrorId.ERR_TECHNICIAN_UNAVAILABLE.value,
        409,
    )
    after = fixtures.get_ticket(ticket["id"])
    assert after["dispatch_status"] == "TRIAGED"
    assert after["assigned_technician_id"] is None
