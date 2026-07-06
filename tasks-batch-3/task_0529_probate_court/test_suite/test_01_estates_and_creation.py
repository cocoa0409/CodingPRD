"""Estate creation, retrieval, listing, and computed posture fields
(Corner queue: entities section)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_estate, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


def test_create_estate_returns_201_with_computed_fields(api):
    """PRD §3.1: "from it the system immediately derives `supervision_level`, sets
    the estate's `status` to `DRAFT`, initializes every ledger field —
    `inventory_total_cents`, `marshaled_cash_cents`, `allowed_claims_total_cents`,
    and `residue_cents` — to zero". PRD §2.9: "When the gross value is at least
    5,000,000 cents, supervision is `FULL`." PRD §2.4: an integer `version` that
    "begins at 1". PRD §4: "Creation endpoints that mint a new resource return
    HTTP 201".

    Design: Corner/entities/create_estate_returns_201_with_computed_fields
    """
    resp = api.create_estate({
        "decedent_name": "Jane Doe", "date_of_death": "2026-04-01T00:00:00Z",
        "county_code": "LA", "estate_type": "INTESTATE",
        "gross_estate_value_cents": 6_000_000,
    }, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["supervision_level"] == "FULL"
    assert data["marshaled_cash_cents"] == 0
    assert data["inventory_total_cents"] == 0
    assert data["allowed_claims_total_cents"] == 0
    assert data["residue_cents"] == 0
    assert data["version"] == 1


def test_get_estate_returns_stored_entity(api):
    """PRD §3.1: "Opening an estate records the decedent's full legal name as
    `decedent_name`". PRD §2.9: "When the gross value is less than 500,000 cents,
    supervision is `INDEPENDENT`".

    Design: Corner/entities/get_estate_returns_stored_entity
    """
    est = create_estate(gross_estate_value_cents=300_000, decedent_name="Ret Test")
    got = validate_success(api.get_estate(est["id"], CLERK))
    assert got["decedent_name"] == "Ret Test"
    assert got["supervision_level"] == "INDEPENDENT"


def test_list_estates_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope." PRD §2.2: "The
    `response_type` is either 'object' for a single resource or 'array' for a list
    of resources."

    Design: Corner/entities/list_estates_paginated_envelope
    """
    create_estate(gross_estate_value_cents=300_000, decedent_name="E1")
    create_estate(gross_estate_value_cents=300_000, decedent_name="E2")
    data, meta = validate_paginated(api.list_estates(CLERK))
    assert meta["total_count"] >= 2
    assert isinstance(meta["has_more"], bool)


def test_get_estate_nonexistent_returns_not_found(api):
    """PRD §2.6: "an `id` embedded in a URL must resolve to an existing resource
    within scope, and if it does not, the request fails with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_estate_nonexistent_returns_not_found
    """
    resp = api.get_estate(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_estate_missing_required_field_returns_missing_field(api):
    """PRD §2.6: "when a required body field is missing, carries the wrong type, is
    negative or zero where a positive value is required, names an invalid enum
    member, or supplies a malformed ISO date, the request fails with
    `ERR_MISSING_FIELD` (HTTP 400)."

    gross_estate_value_cents is a required input field (PRD §3.1 declares it).

    Design: Corner/entities/create_estate_missing_required_field_returns_missing_field
    """
    resp = api.create_estate({
        "decedent_name": "NoVal", "date_of_death": "2026-04-01T00:00:00Z",
        "county_code": "LA", "estate_type": "INTESTATE",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD)


def test_create_estate_invalid_enum_returns_missing_field(api):
    """PRD §2.6: "when a required body field is missing, carries the wrong type, is
    negative or zero where a positive value is required, names an invalid enum
    member, or supplies a malformed ISO date, the request fails with
    `ERR_MISSING_FIELD` (HTTP 400)."

    estate_type is "either `TESTATE` ... or `INTESTATE`" (PRD §3.1); PROBATE is not
    a member.

    Design: Corner/entities/create_estate_invalid_enum_returns_missing_field
    """
    resp = api.create_estate({
        "decedent_name": "BadEnum", "date_of_death": "2026-04-01T00:00:00Z",
        "county_code": "LA", "estate_type": "PROBATE",
        "gross_estate_value_cents": 300_000,
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD)


def test_estate_supervision_level_limited_and_full_boundaries(api):
    """PRD §2.9: "The boundaries themselves fall upward: a gross value of exactly
    500,000 cents yields `LIMITED`, and exactly 5,000,000 cents yields `FULL`."

    Design: Corner/entities/estate_supervision_level_limited_boundary
    """
    lim = create_estate(gross_estate_value_cents=500_000, decedent_name="Lim")
    full = create_estate(gross_estate_value_cents=5_000_000, decedent_name="Full")
    assert lim["supervision_level"] == "LIMITED", (
        f"gross exactly 500000 should be LIMITED, got {lim['supervision_level']}")
    assert full["supervision_level"] == "FULL", (
        f"gross exactly 5000000 should be FULL, got {full['supervision_level']}")


def test_system_status_forced_to_draft_on_create(api):
    """PRD §3.1: "sets the estate's `status` to `DRAFT`". PRD §2.4: "Every persisted
    resource is minted with a server-generated `id`".

    status is a system field; a client-supplied value is ignored and the server
    forces DRAFT.

    Design: Corner/entities/system_fields_ignored_on_create
    """
    resp = api.create_estate({
        "decedent_name": "SysF", "date_of_death": "2026-04-01T00:00:00Z",
        "county_code": "LA", "estate_type": "INTESTATE",
        "gross_estate_value_cents": 300_000, "status": "CLOSED",
    }, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", (
        f"server should force DRAFT regardless of client input, got {data['status']}")
