"""Units: creation, reads, registration supersession, and unit-version OCC.

Sources: Corner/entities, Corner/endpoints, Corner/cross_cutting_complexity_layers.
"""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    assert_unit, assert_registration,
    make_landlord_headers,
    create_landlord_payload, create_unit_payload, create_registration_payload,
    create_rent_adjustment_payload,
    create_landlord, create_unit, publish_aga, setup_landlord_and_unit,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


def test_unit_creation_initializes_lawful_rent(api):
    """PRD §3.2: "At creation the unit's `current_lawful_rent_cents` is initialized to
    `base_rent_cents`, its `banked_pct` is 0, its `stabilization_status` is `STABILIZED`,
    and its `decrease_active` flag is false."

    Design: Corner/entities/unit_creation_initializes_lawful_rent
    """
    landlord = create_landlord(api)
    resp = api.create_unit(
        create_unit_payload(landlord["id"], address="1 Init St #1", bedrooms=2,
                            base_rent_cents=285000),
        make_landlord_headers(landlord["id"]))
    data = validate_success(resp, expected_status=201)
    assert_unit(data)
    assert data["current_lawful_rent_cents"] == 285000
    assert data["stabilization_status"] == "STABILIZED"
    assert data["banked_pct"] == 0
    assert data["decrease_active"] is False


def test_unit_get_nonexistent_returns_not_found(api):
    """PRD §2.8: "A missing resource yields the entity-specific not-found error:
    `ERR_UNIT_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`,
    `ERR_HEARING_OFFICER_NOT_FOUND` ... (all 404)."

    Design: Corner/entities/unit_get_nonexistent_returns_not_found
    """
    resp = api.get_unit(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)


def test_unit_create_missing_base_rent_returns_validation(api):
    """PRD §2.8: "Field validation — required fields present and well-typed, enum
    values valid, and type-specific fields present ... A failure here is ERR_VALIDATION (400)."

    Design: Corner/entities/unit_create_missing_base_rent_returns_validation
    """
    landlord = create_landlord(api)
    payload = {"landlord_id": landlord["id"], "address": "2 Miss St", "bedrooms": 1}
    resp = api.create_unit(payload, make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_units_list_by_landlord_paginated(api):
    """PRD §2.3: "The meta block of a list response reports limit, offset, total_count
    (the full count of matching resources before the page window is applied), and
    has_more (true when more resources exist beyond the current page)."

    Design: Corner/entities/units_list_by_landlord_paginated
    """
    landlord = create_landlord(api)
    create_unit(api, landlord["id"], address="3 List St #1", bedrooms=1, base_rent_cents=200000)
    create_unit(api, landlord["id"], address="3 List St #2", bedrooms=2, base_rent_cents=250000)
    resp = api.list_units(CLERK, params={"landlord_id": landlord["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_registration_supersedes_prior_active(api):
    """PRD §3.2: "if a prior ACTIVE registration already exists for the unit, filing a
    new one transitions that prior registration from ACTIVE to SUPERSEDED, and the
    unit's version is incremented by one."

    Design: Corner/endpoints/registration_supersedes_prior_active
    """
    base = setup_landlord_and_unit(api)
    unit = base["unit"]
    reg1 = validate_success(api.create_registration(
        unit["id"],
        create_registration_payload(2025, 300000, unit["version"]),
        CLERK), expected_status=201)
    # unit.version advanced to 2 after the first registration
    unit_v2 = validate_success(api.get_unit(unit["id"], CLERK))["version"]
    reg2 = validate_success(api.create_registration(
        unit["id"],
        create_registration_payload(2026, 309000, unit_v2),
        CLERK), expected_status=201)

    regs = validate_paginated(api.list_registrations(unit["id"], CLERK))[0]
    by_id = {r["id"]: r for r in regs}
    assert by_id[reg1["id"]]["status"] == "SUPERSEDED"
    assert by_id[reg2["id"]]["status"] == "ACTIVE"


def test_registrations_subresource_lists_children(api):
    """PRD §3.2: "A unit's registrations may be listed through the unit; the path unit
    id resolves first."

    Design: Corner/endpoints/registrations_subresource_lists_children
    """
    base = setup_landlord_and_unit(api)
    unit = base["unit"]
    validate_success(api.create_registration(
        unit["id"], create_registration_payload(2026, 300000, unit["version"]), CLERK),
        expected_status=201)
    data, _ = validate_paginated(api.list_registrations(unit["id"], CLERK))
    assert len(data) == 1
    assert data[0]["unit_id"] == unit["id"]
    assert_registration(data[0])


def test_rent_adjustment_by_non_owner_landlord_rejected(api):
    """PRD §2.1: "When an owner-scoped operation is invoked by the correct role but by a
    principal who does not own or is not a party to the target resource, the request is
    rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403). This ownership check applies to
    applying a rent adjustment to a unit..."

    Design: Corner/endpoints/rent_adjustment_by_non_owner_landlord_rejected
    """
    l1 = create_landlord(api)
    l2 = create_landlord(api)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, l1["id"], base_rent_cents=300000, bedrooms=2)
    resp = api.create_rent_adjustment(
        unit["id"],
        create_rent_adjustment_payload("2026-06-01", 309000, False, unit["version"]),
        make_landlord_headers(l2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_occ_registration_stale_version_rejected(api):
    """PRD §2.5: "If that value does not equal the unit's current version — because
    another registration or a rent adjustment has advanced the unit since the client
    read it — the request is rejected with ERR_STALE_VERSION (HTTP 412), rather than
    superseding an active registration the client never observed."

    Design: Corner/cross_cutting_complexity_layers/occ_registration_stale_version_rejected
    """
    base = setup_landlord_and_unit(api)
    unit = base["unit"]
    stale_version = unit["version"]
    validate_success(api.create_registration(
        unit["id"], create_registration_payload(2025, 300000, stale_version), CLERK),
        expected_status=201)
    resp = api.create_registration(
        unit["id"], create_registration_payload(2026, 309000, stale_version), CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_rent_adjustment_stale_version_rejected(api):
    """PRD §2.5: "If it does not equal the unit's current version — because a prior
    adjustment, a passthrough grant, or a service decrease has already changed the
    lawful rent — the adjustment is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_rent_adjustment_stale_version_rejected
    """
    l = create_landlord(api)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, l["id"], base_rent_cents=300000, bedrooms=2)
    stale_version = unit["version"]
    lheaders = make_landlord_headers(l["id"])
    validate_success(api.create_rent_adjustment(
        unit["id"], create_rent_adjustment_payload("2026-06-01", 306000, False, stale_version),
        lheaders))
    resp = api.create_rent_adjustment(
        unit["id"], create_rent_adjustment_payload("2026-07-01", 309000, False, stale_version),
        lheaders)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_rent_adjustment_bumps_unit_version(api):
    """PRD §2.5: "Both guarded operations increment `Unit.version` by one on success."
    PRD §3.3: "On success the unit's `current_lawful_rent_cents` becomes the proposed new rent"

    Design: Corner/cross_cutting_complexity_layers/rent_adjustment_bumps_unit_version
    """
    l = create_landlord(api)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, l["id"], base_rent_cents=300000, bedrooms=2)
    assert unit["version"] == 1
    data = validate_success(api.create_rent_adjustment(
        unit["id"], create_rent_adjustment_payload("2026-06-01", 306000, False, unit["version"]),
        make_landlord_headers(l["id"])))
    assert data["version"] == 2
    assert data["current_lawful_rent_cents"] == 306000
