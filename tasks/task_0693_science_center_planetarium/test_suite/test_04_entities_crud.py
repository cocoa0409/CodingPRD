"""Entity creation, retrieval, listing, defaults, computed and system fields,
immutability, and parent-type relationships.

Queue B (Corner): section entities.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_dome,
    create_classroom,
    create_show,
    create_membership,
    create_sponsor,
    record_contribution,
    assert_venue,
    assert_show_event,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
CLERK = TEST_USERS["membership_clerk_headers"]
DEV = TEST_USERS["development_officer_headers"]


def test_create_venue_returns_201_active_version_one(api):
    """PRD §3.1: "A venue is born with `status` of `ACTIVE` and stays `ACTIVE`; there
    is no other venue state."
    PRD §2.4: "a `version`, an integer that begins at 1 on creation and increments by
    one on every mutation that touches the resource".

    Design: Corner/entities/create_venue_returns_201_with_fields
    """
    resp = api.create_venue(
        {"name": "Dome Z", "venue_type": "DOME", "seated_capacity": 50, "accessible_seats": 6}, ADMIN)
    venue = validate_success(resp, expected_status=201)
    assert_venue(venue)
    assert venue["status"] == "ACTIVE"
    assert venue["version"] == 1, f"expected version 1, got {venue['version']}"
    assert venue["seated_capacity"] == 50


def test_get_show_returns_stored_entity(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.3: "A `BoxOfficeOperator` schedules a **ShowEvent** into a dome or theater
    by supplying the `venue_id`, a `title`, the window bounds `starts_at` and
    `ends_at`, a `base_price_cents`, and an optional `feature_surcharge_cents`."

    Design: Corner/entities/get_show_returns_stored_entity
    """
    dome = create_dome(seated_capacity=40, name="Dome M")
    show = create_show(dome["id"], base_price_cents=1800, title="Nebula",
                       starts_at="2026-04-30T10:00:00Z", ends_at="2026-04-30T11:00:00Z")
    fetched = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert_show_event(fetched)
    assert fetched["title"] == "Nebula"
    assert fetched["base_price_cents"] == 1800


def test_list_venues_paginated_envelope(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping in the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_venues_paginated_envelope
    """
    create_dome(seated_capacity=30, name="V1")
    api.create_venue({"name": "V2", "venue_type": "CLASSROOM", "seated_capacity": 20}, ADMIN)

    data, meta = validate_paginated(api.list_venues(ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_get_membership_not_found(api):
    """PRD §2.8: "the system validates each identifier left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_membership_not_found
    """
    resp = api.get_membership(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_show_missing_required_field_rejected(api):
    """PRD §3.10: "then the structural parse of the body with required fields present
    and correctly typed (`ERR_INVALID_REQUEST`)."

    base_price_cents is a required input field for POST /shows.

    Design: Corner/entities/create_show_missing_required_field
    """
    dome = create_dome(seated_capacity=30, name="Dome N")
    resp = api.create_show(
        {"venue_id": dome["id"], "title": "NoPrice", "starts_at": "2026-05-01T10:00:00Z",
         "ends_at": "2026-05-01T11:00:00Z"}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_show_default_feature_surcharge_is_zero(api):
    """PRD §3.3: "the `feature_surcharge_cents` is a per-seat premium for special
    presentations such as a laser-dome feature, defaults to 0, may not be negative,
    and is added on top of the base price."

    Design: Corner/entities/show_default_feature_surcharge_applied
    """
    dome = create_dome(seated_capacity=30, name="Dome O")
    show = create_show(dome["id"], base_price_cents=1200, title="PlainShow",
                       starts_at="2026-05-03T10:00:00Z", ends_at="2026-05-03T11:00:00Z")
    assert show["feature_surcharge_cents"] == 0, \
        f"expected default feature_surcharge_cents 0, got {show['feature_surcharge_cents']}"


def test_membership_astc_eligible_is_computed_from_tier(api):
    """PRD §3.2: "The card also computes a flag, `astc_eligible`, which is true exactly
    when the tier is `FAMILY` or `PATRON` — only those two tiers carry reciprocal
    benefits, and an `INDIVIDUAL` card is never ASTC-eligible."

    Design: Corner/entities/membership_astc_eligible_computed
    """
    ind = create_membership(tier="INDIVIDUAL", home_zip="90210", party_size=1,
                            primary_member_name="Ind")
    fam = create_membership(tier="FAMILY", home_zip="90210", party_size=3,
                            primary_member_name="Fam2")
    assert ind["astc_eligible"] is False, f"INDIVIDUAL must not be ASTC-eligible, got {ind['astc_eligible']}"
    assert fam["astc_eligible"] is True, f"FAMILY must be ASTC-eligible, got {fam['astc_eligible']}"


def test_venue_status_active_is_server_set(api):
    """PRD §3.1: "A venue is born with `status` of `ACTIVE` and stays `ACTIVE`; there
    is no other venue state."

    Design: Corner/entities/venue_system_fields_generated
    """
    venue = create_dome(seated_capacity=25, name="Dome P")
    assert venue["status"] == "ACTIVE", f"expected ACTIVE, got {venue['status']}"


def test_membership_invalid_tier_enum_rejected(api):
    """PRD §3.10: "then the structural parse of the body with required fields present
    and correctly typed (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "The `tier` is one of `INDIVIDUAL`, `FAMILY`, or `PATRON`."

    Design: Corner/entities/membership_invalid_tier_enum
    """
    resp = api.create_membership(
        {"primary_member_name": "Bad", "tier": "GOLD", "home_zip": "90210"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_contribution_is_append_only_received(api):
    """PRD §2.4: "A **Contribution** is an append-only installment record: once
    written it is immutable, so it carries only an `id` and a `created_at`. It has no
    `updated_at` and no `version` of its own."
    PRD §3.8: "A contribution is born `RECEIVED` and is immutable".

    Design: Corner/entities/contribution_immutable_no_version
    """
    sponsor = create_sponsor(pledged_cents=10000, sponsor_kind="DONOR", org_name="Imm")
    record_contribution(sponsor["id"], amount_cents=4000)

    data, meta = validate_paginated(api.list_contributions(sponsor["id"], DEV))
    assert len(data) == 1
    assert data[0]["status"] == "RECEIVED", f"expected RECEIVED, got {data[0]['status']}"


def test_show_in_classroom_venue_rejected(api):
    """PRD §3.1: "the system enforces this when each kind of event is created: a show
    requires a `DOME` or `THEATER` venue, a program session requires a `CLASSROOM`
    venue, and a rental requires a `RENTAL_HALL` venue. A mismatch between the
    requested event and the venue's `venue_type` is rejected with
    `ERR_VENUE_TYPE_MISMATCH`."

    Design: Corner/entities/show_create_wrong_parent_venue_type
    """
    room = create_classroom(seated_capacity=20, name="Room W")
    resp = api.create_show(
        {"venue_id": room["id"], "title": "WrongVenue", "starts_at": "2026-05-04T10:00:00Z",
         "ends_at": "2026-05-04T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_VENUE_TYPE_MISMATCH.value, expected_status=422)
