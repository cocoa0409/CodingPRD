"""Standing up the program registry, and the access ladder that guards it."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_property,
    assert_property_owner,
    assert_zone,
    bootstrap_registry,
    create_owner,
    create_property,
    create_zone,
    create_property_payload,
    file_complaint,
    make_inspector_headers,
    make_property_owner_headers,
    make_supervisor_headers,
    schedule_visit,
    set_clock,
    setup_triaged_complaint,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


def test_new_zone_starts_normal_with_zero_counters(api):
    """PRD §3.1: "A newly created zone always starts with `posture` `NORMAL`,
    `rodent_index` 0.00, and its three counters — `open_complaint_count`,
    `chronic_property_count` and `active_station_count` — all at 0, with
    `last_index_recomputed_at` null until the first recompute occurs."
    PRD §2.4: "`version` begins at 1 the moment the record is created and
    increases by exactly 1 on each mutation that the specification says bumps it;
    `updated_at` is refreshed to the current logical clock on every mutation."

    Design: Corner/entities/corner_zone_creation_returns_derived_defaults
    """
    set_clock("2026-05-04T09:00:00Z")
    resp = api.create_zone(
        {"name": "Riverside", "code": "Z-RIV", "population_density_per_sqkm": 4200},
        ADMIN,
    )
    zone = validate_success(resp, 201)
    assert_zone(zone)
    assert zone["posture"] == "NORMAL"
    assert zone["rodent_index"] == pytest.approx(0.00, abs=0.001)
    assert zone["open_complaint_count"] == 0
    assert zone["chronic_property_count"] == 0
    assert zone["active_station_count"] == 0
    assert zone["version"] == 1
    assert zone["last_index_recomputed_at"] is None
    assert zone["created_at"] == "2026-05-04T09:00:00.000Z"


def test_reading_an_unknown_parcel_answers_property_not_found(api):
    """PRD §2.5: "Every resource referenced by the request must exist, checked
    left to right: the path identifiers first, in the order they appear in the
    URL, then the foreign keys named in the body, in the order they are listed
    for that endpoint. The rejection is 404 and names the missing kind —
    `ERR_ZONE_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
    `ERR_OFFICER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
    `ERR_STATION_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/entities/corner_property_get_unknown_id_returns_not_found
    """
    set_clock("2026-05-04T09:00:00Z")
    resp = api.get_property("11111111-2222-3333-4444-555555555555", ADMIN)
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_owner_and_parcel_optional_fields_take_their_declared_defaults(api):
    """PRD §3.1: "`notice_preference` records the channel the owner prefers and
    is one of `FIRST_CLASS_MAIL`, `CERTIFIED_MAIL` or `PERSONAL_SERVICE`,
    defaulting to `CERTIFIED_MAIL` when omitted; it is a record of preference and
    does not by itself constrain how a notice is actually served."
    PRD §3.1: "`hardship_certified` marks an owner who holds a certified
    financial-hardship exemption and defaults to false; it is the sole gate on
    the hardship discount described in §3.7."
    PRD §3.1: "Every new owner starts with `outstanding_balance_cents` 0 and
    `lifetime_paid_cents` 0."
    PRD §3.1: "An optional `unit_count` records the dwelling or tenant units on
    the parcel; it must be at least 1 and defaults to 1."
    PRD §3.1: "A new parcel is born at `version` 1 with `chronic_score` 0.00,
    `provisional_chronic_score` 0.00, `chronic_flag` false, `open_order_count` 0,
    `lien_encumbered` false and `last_inspection_at` null."

    Design: Corner/entities/corner_property_unit_count_and_owner_defaults_applied
    """
    set_clock("2026-05-04T09:00:00Z")
    zone = create_zone()

    owner_resp = api.create_property_owner(
        {
            "full_name": "Dana Ruiz",
            "email": "dana@example.com",
            "mailing_address": "12 Elm St",
        },
        ADMIN,
    )
    owner = validate_success(owner_resp, 201)
    assert_property_owner(owner)
    assert owner["notice_preference"] == "CERTIFIED_MAIL"
    assert owner["hardship_certified"] is False
    assert owner["outstanding_balance_cents"] == 0
    assert owner["lifetime_paid_cents"] == 0

    prop_resp = api.create_property(
        create_property_payload(
            zone["id"], owner["id"], property_type="VACANT_LOT"
        ),
        ADMIN,
    )
    prop = validate_success(prop_resp, 201)
    assert_property(prop)
    assert prop["unit_count"] == 1
    assert prop["version"] == 1
    assert prop["chronic_score"] == pytest.approx(0.00, abs=0.001)
    assert prop["provisional_chronic_score"] == pytest.approx(0.00, abs=0.001)
    assert prop["chronic_flag"] is False
    assert prop["open_order_count"] == 0
    assert prop["lien_encumbered"] is False
    assert prop["last_inspection_at"] is None


def test_parcel_registration_rejects_an_unknown_zone(api):
    """PRD §3.1: "A parcel is registered inside a zone, the payload naming the
    `zone_id` that contains it and the `owner_id` billed for cost recovery,
    together with a street `address_line`, an assessor `parcel_number` that must
    be unique across all parcels (a collision yields `ERR_DUPLICATE_CODE`), and a
    `property_type` drawn from `RESIDENTIAL_SINGLE`, `RESIDENTIAL_MULTI`,
    `COMMERCIAL_FOOD`, `COMMERCIAL_OTHER` or `VACANT_LOT`."
    PRD §2.5: "The rejection is 404 and names the missing kind —
    `ERR_ZONE_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
    `ERR_OFFICER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
    `ERR_STATION_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/entities/corner_property_rejects_unknown_zone_id
    """
    set_clock("2026-05-04T09:00:00Z")
    owner = create_owner()
    resp = api.create_property(
        create_property_payload(
            "99999999-8888-7777-6666-555555555555", owner["id"]
        ),
        ADMIN,
    )
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND.value)


def test_reusing_a_parcel_number_is_rejected(api):
    """PRD §3.1: "A parcel is registered inside a zone, the payload naming the
    `zone_id` that contains it and the `owner_id` billed for cost recovery,
    together with a street `address_line`, an assessor `parcel_number` that must
    be unique across all parcels (a collision yields `ERR_DUPLICATE_CODE`), and a
    `property_type` drawn from `RESIDENTIAL_SINGLE`, `RESIDENTIAL_MULTI`,
    `COMMERCIAL_FOOD`, `COMMERCIAL_OTHER` or `VACANT_LOT`."

    Design: Corner/entities/corner_duplicate_parcel_number_rejected
    """
    env = bootstrap_registry(inspectors=0, with_supervisor=False)
    resp = api.create_property(
        create_property_payload(
            env["zone_id"], env["owner_id"],
            address_line="16 Elm St", parcel_number="APN-1001",
            property_type="COMMERCIAL_OTHER",
        ),
        ADMIN,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value)

    rows, meta = validate_paginated(
        api.list_properties(ADMIN, params={"zone_id": env["zone_id"]})
    )
    assert meta["total_count"] == 1, "the rejected parcel must not be persisted"
    assert len(rows) == 1


def test_missing_headers_and_unauthorised_role_are_distinct_failures(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value
    that is not one of those six strings, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration. If both
    headers are well formed but the named role is not among the roles authorised
    for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD §3.2: "A `Supervisor` triages a complaint that is still in `RECEIVED`,
    supplying the `severity` they judge correct — one of `ROUTINE`, `HIGH` or
    `CRITICAL` — and optionally some `triage_notes`."

    Design: Corner/validations/corner_missing_and_wrong_role_headers_rejected
    """
    env = bootstrap_registry(inspectors=1, with_supervisor=False)
    complaint = file_complaint(env["prop_id"])

    unauthenticated = api.get_complaint(complaint["id"], {})
    assert unauthenticated.status_code == 401
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value)

    unauthorised = api.triage_complaint(
        complaint["id"], {"severity": "HIGH"}, make_inspector_headers(env["insp_id"])
    )
    assert unauthorised.status_code == 403
    validate_error(unauthorised, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert after["status"] == "RECEIVED"
    assert after["triaged_at"] is None


def test_each_unknown_identifier_answers_its_own_not_found_error(api):
    """PRD §2.5: "Every resource referenced by the request must exist, checked
    left to right: the path identifiers first, in the order they appear in the
    URL, then the foreign keys named in the body, in the order they are listed
    for that endpoint. The rejection is 404 and names the missing kind —
    `ERR_ZONE_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
    `ERR_OFFICER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
    `ERR_STATION_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/validations/corner_unknown_ids_answer_their_own_not_found_error
    """
    env, complaint = setup_triaged_complaint(bootstrap_kwargs={"inspectors": 0})
    sup = make_supervisor_headers(env["sup_id"])
    missing = "00000000-0000-4000-8000-00000000000"

    checks = [
        (api.get_property_owner(missing + "1", ADMIN), ApiErrorId.ERR_OWNER_NOT_FOUND),
        (
            api.create_inspection(
                {
                    "kind": "INITIAL",
                    "complaint_id": complaint["id"],
                    "officer_id": missing + "2",
                    "scheduled_start": "2026-05-05T09:00:00Z",
                    "scheduled_end": "2026-05-05T10:00:00Z",
                },
                sup,
            ),
            ApiErrorId.ERR_OFFICER_NOT_FOUND,
        ),
        (api.get_complaint(missing + "3", CLERK), ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_inspection(missing + "4", sup), ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api.get_abatement_order(missing + "5", sup), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (
            api.record_service_result(
                missing + "6", {"service_outcome": "DELIVERED"}, CLERK
            ),
            ApiErrorId.ERR_NOTICE_NOT_FOUND,
        ),
        (api.get_bait_station(missing + "7", ADMIN), ApiErrorId.ERR_STATION_NOT_FOUND),
        (api.get_invoice(missing + "8", ADMIN), ApiErrorId.ERR_INVOICE_NOT_FOUND),
    ]
    for resp, error_id in checks:
        assert resp.status_code == 404, f"expected 404 for {error_id.value}"
        validate_error(resp, error_id.value)

    after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert after["status"] == "TRIAGED"
    rows, meta = validate_paginated(api.list_inspections(sup))
    assert meta["total_count"] == 0, "no inspection may have been created"


def test_owner_may_only_file_a_complaint_on_their_own_parcel(api):
    """PRD §2.1: "When a caller holds a role the endpoint permits but is reaching
    for someone else's resource — a `PropertyOwner` reading another owner's
    parcel, invoice or owner record, filing a complaint on a parcel they do not
    own, or paying an invoice that is not theirs; an `Inspector` starting,
    completing or attaching an assessment to an inspection assigned to a
    different officer — the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.2: "Every complaint is born in status `RECEIVED`."

    Design: Corner/rbac/corner_owner_can_only_file_on_own_parcel
    """
    set_clock("2026-05-04T09:00:00Z")
    zone = create_zone()
    owner_one = create_owner()
    owner_two = create_owner(
        full_name="Lee Park", email="lee@example.com", mailing_address="14 Elm St"
    )
    parcel_one = create_property(zone["id"], owner_one["id"])
    parcel_two = create_property(
        zone["id"], owner_two["id"],
        address_line="14 Elm St", parcel_number="APN-1002",
        property_type="RESIDENTIAL_SINGLE",
    )

    owner_one_headers = make_property_owner_headers(owner_one["id"])
    foreign = api.create_complaint(
        {
            "property_id": parcel_two["id"],
            "complaint_type": "HARBORAGE",
            "reporter_type": "OWNER",
            "description": "Neighbour woodpile",
            "reporter_name": "Dana Ruiz",
        },
        owner_one_headers,
    )
    assert foreign.status_code == 403
    validate_error(foreign, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    own = api.create_complaint(
        {
            "property_id": parcel_one["id"],
            "complaint_type": "HARBORAGE",
            "reporter_type": "OWNER",
            "description": "Woodpile on my own lot",
            "reporter_name": "Dana Ruiz",
        },
        owner_one_headers,
    )
    complaint = validate_success(own, 201)
    assert complaint["status"] == "RECEIVED"

    zone_after = validate_success(api.get_zone(zone["id"], ADMIN))
    assert zone_after["open_complaint_count"] == 1


def test_inspector_cannot_start_another_officers_visit(api):
    """PRD §3.3: "The assigned officer, acting as `Inspector`, starts the visit;
    only they may do so, since `X-User-ID` must equal the visit's `officer_id`."
    PRD §2.1: "When a caller holds a role the endpoint permits but is reaching
    for someone else's resource — a `PropertyOwner` reading another owner's
    parcel, invoice or owner record, filing a complaint on a parcel they do not
    own, or paying an invoice that is not theirs; an `Inspector` starting,
    completing or attaching an assessment to an inspection assigned to a
    different officer — the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/corner_inspector_cannot_act_on_another_officers_visit
    """
    env, complaint = setup_triaged_complaint(
        bootstrap_kwargs={"inspectors": 2}
    )
    visit = schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z",
        complaint_id=complaint["id"],
    )
    set_clock("2026-05-05T09:00:00Z")

    intruder = api.start_inspection(visit["id"], make_inspector_headers(env["insp2_id"]))
    assert intruder.status_code == 403
    validate_error(intruder, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    owner_of_visit = api.start_inspection(
        visit["id"], make_inspector_headers(env["insp1_id"])
    )
    started = validate_success(owner_of_visit, 200)
    assert started["status"] == "IN_PROGRESS"
