"""Entity creation, required-field, type-constraint, FK, and read behaviors."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_agency_payload,
    create_talent_payload,
    create_comp_card_payload,
    create_agency,
    create_talent,
)
from test_helpers import api_client

AGENT = TEST_USERS["agent_headers"]


# ─── Creation: agency defaults ───────────────────────────────────────────────
def test_create_agency_returns_201_with_zero_derived_fields(api):
    """PRD §3.1: "A new agency starts with `escrow_balance_cents` and
    `booked_day_count` both at zero — these are the derived fields reconciled
    later as bookings and commissions move."

    Design: Corner/entities/create_agency_returns_201_with_defaults
    """
    resp = api.create_agency(
        create_agency_payload(name="Stellar", commission_rate_bps=1000), AGENT
    )
    agency = validate_success(resp, 201)
    assert agency["escrow_balance_cents"] == 0
    assert agency["booked_day_count"] == 0
    assert agency["version"] == 1


# ─── Required Fields: talent union_status omitted ────────────────────────────
def test_create_talent_missing_union_status_rejected(api):
    """PRD §3.1: "An agent creates a talent by naming the representing agency
    through `agency_id`, the performer's `full_name`, their `union_status` —
    exactly one of `SAG` or `NON_UNION` ... and a `scale_rate_cents` floor"
    PRD §2.9: "request-body shape is validated — required fields present and
    correctly typed ... failing with `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_talent_missing_union_status_returns_invalid_request
    """
    agency = create_agency()
    payload = {
        "agency_id": agency["id"],
        "full_name": "NoUnion",
        "scale_rate_cents": 100000,
    }
    resp = api.create_talent(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ─── Type Constraints: talent union_status out of set ────────────────────────
def test_create_talent_invalid_union_status_enum_rejected(api):
    """PRD §2.9: "enum values within their declared sets — failing with
    `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "their `union_status` — exactly one of `SAG` or `NON_UNION`"

    Design: Corner/entities/create_talent_invalid_enum_union_status_returns_invalid_request
    """
    agency = create_agency()
    resp = api.create_talent(
        create_talent_payload(agency["id"], full_name="BadEnum", union_status="AFTRA"),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ─── Not Found: read missing talent ──────────────────────────────────────────
def test_get_nonexistent_talent_returns_not_found(api):
    """PRD §2.6: "the server validates their existence left to right, in the order
    they appear, and rejects the request with `ERR_NOT_FOUND` at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_talent_nonexistent_returns_not_found
    """
    resp = api.get_talent(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ─── Computed Fields: first comp card is primary ─────────────────────────────
def test_first_comp_card_primary_subsequent_not(api):
    """PRD §3.1: "The first comp card created for a given talent is automatically
    marked with `is_primary` set to true; every later card for that talent has
    `is_primary` false."

    Design: Corner/entities/first_comp_card_is_primary_system_field
    """
    agency = create_agency()
    talent = create_talent(agency["id"])
    first = validate_success(
        api.create_comp_card(
            create_comp_card_payload(talent["id"], headshot_url="http://x/a.jpg"), AGENT
        ),
        201,
    )
    second = validate_success(
        api.create_comp_card(
            create_comp_card_payload(talent["id"], headshot_url="http://x/b.jpg"), AGENT
        ),
        201,
    )
    assert first["is_primary"] is True
    assert second["is_primary"] is False


# ─── Listing: talents pagination envelope ────────────────────────────────────
def test_list_talents_returns_paginated_array(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/list_talents_pagination_envelope
    """
    agency = create_agency()
    create_talent(agency["id"])
    resp = api.list_talents(AGENT)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert "total_count" in meta
    assert "has_more" in meta


# ─── Parent Relationships: talent bad agency FK ──────────────────────────────
def test_create_talent_with_unknown_agency_fk_returns_not_found(api):
    """PRD §2.6: "For a creation that supplies several foreign keys, the keys are
    checked in declaration order before any business rule runs, so a missing
    parent surfaces before any state or temporal check."

    Design: Corner/entities/create_talent_bad_agency_fk_returns_not_found
    """
    resp = api.create_talent(
        create_talent_payload(NON_EXISTENT_UUID, full_name="Orphan", union_status="SAG"),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
