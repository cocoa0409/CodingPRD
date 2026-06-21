"""Corner — entities section.

CRUD, system-minted fields, default values, type constraints, computed-field
isolation, immutability of ComplianceEvent.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    set_clock,
    create_forming_business_entity,
    create_registered_agent_for,
    make_compliance_officer_headers,
    make_anonymous_headers,
)


def test_create_business_entity_with_all_required_fields_returns_201(api):
    """PRD §3.1: "On creation the entity is persisted with `status` set to
    `FORMING`, `compliance_posture` provisionally set to `GOOD_STANDING`,
    `franchise_tax_paid_through_year` initialized to 0, and
    `cumulative_franchise_tax_paid_cents` initialized to 0."
    PRD §3.1: "The server stamps `formed_at` from the current clock UTC and
    returns the created resource."

    Design: Corner/entities/create_business_entity_with_all_required_fields_returns_201
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_business_entity(
        {
            "legal_name": "ALPHA LLC",
            "entity_type": "LLC",
            "formation_state_code": "DE",
            "revenue_band": "ZERO",
        },
        make_anonymous_headers(),
    )
    body = validate_success(res, 201)
    assert body["status"] == "FORMING"
    assert body["compliance_posture"] == "GOOD_STANDING"
    assert body["version"] == 1
    # PRD §2.4: timestamps are ISO 8601 UTC. The test pins the clock to
    # 2026-01-01T00:00:00Z and asserts formed_at carries that instant in any
    # PRD-compliant ISO 8601 UTC form (with or without fractional digits).
    assert body["formed_at"].startswith("2026-01-01T00:00:00")
    assert body["formed_at"].endswith("Z")


def test_get_business_entity_by_id_returns_stored_data(api):
    """PRD §4: "GET /business-entities/{id}: Read a single business entity."
    PRD §2.4: "Every resource other than `ComplianceEvent` carries four common
    fields that the API mints and maintains on the server side."

    Design: Corner/entities/get_business_entity_by_id_returns_stored_data
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(legal_name="BRAVO LLC")
    res = api.get_business_entity(be["id"], make_compliance_officer_headers())
    body = validate_success(res, 200)
    assert body["id"] == be["id"]
    assert body["legal_name"] == "BRAVO LLC"


def test_list_business_entities_returns_paginated_envelope(api):
    """PRD §2.3: "List endpoints accept two integer query parameters, `limit` and
    `offset`, both optional."
    PRD §2.3: "The response `meta` includes `limit`, `offset`, `total_count` (the
    total matching row count across all pages), and `has_more` (true when more
    results exist past the returned window)."

    Design: Corner/entities/list_business_entities_returns_paginated_envelope
    """
    set_clock("2026-01-01T00:00:00Z")
    create_forming_business_entity(legal_name="CHARLIE LLC")
    create_forming_business_entity(legal_name="DELTA LLC")
    res = api.list_business_entities(make_compliance_officer_headers(), params={"limit": 10})
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert meta["total_count"] >= 2


def test_get_business_entity_unknown_uuid_returns_404(api):
    """PRD §2.5: "When a path looks like
    `/business-entities/{business_entity_id}/foreign-qualifications/{foreign_qualification_id}`,
    the parent `BusinessEntity` is resolved first; if it does not exist, the
    request is rejected with `ERR_NOT_FOUND` (HTTP 404) regardless of whether the
    child id would have been valid."

    Design: Corner/entities/get_business_entity_unknown_uuid_returns_404
    """
    res = api.get_business_entity(
        "00000000-0000-0000-0000-000000000000", make_compliance_officer_headers()
    )
    validate_error(res, "ERR_NOT_FOUND")


def test_create_business_entity_missing_legal_name_returns_invalid_request(api):
    """PRD §3.1: "The `legal_name` is between 1 and 200 characters long and may
    contain uppercase ASCII letters, digits, spaces, hyphens, periods, commas,
    and ampersands — names with lowercase letters or unlisted punctuation are
    rejected with `ERR_INVALID_REQUEST`, as is a `legal_name` whose length falls
    outside the 1-to-200-character window."

    Design: Corner/entities/create_business_entity_missing_legal_name_returns_invalid_request
    """
    res = api.create_business_entity(
        {"entity_type": "LLC", "formation_state_code": "DE", "revenue_band": "ZERO"},
        make_anonymous_headers(),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_business_entity_default_revenue_band_zero(api):
    """PRD §3.1: "The optional `revenue_band` selects the franchise-tax tier and
    is one of `ZERO`, `MICRO`, `SMALL`, `MEDIUM`, or `LARGE`; when omitted the
    entity defaults to `ZERO`."

    Design: Corner/entities/create_business_entity_default_revenue_band_zero
    """
    res = api.create_business_entity(
        {
            "legal_name": "ECHO LLC",
            "entity_type": "LLC",
            "formation_state_code": "DE",
        },
        make_anonymous_headers(),
    )
    body = validate_success(res, 201)
    assert body["revenue_band"] == "ZERO"


def test_create_business_entity_invalid_state_code_returns_invalid_request(api):
    """PRD §3.1: "the `formation_state_code` is a two-letter uppercase code drawn
    from the supported set `CA`, `DE`, `NY`, `TX`, `FL`, and `WY`; any other code
    is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_business_entity_invalid_state_code_returns_invalid_request
    """
    res = api.create_business_entity(
        {
            "legal_name": "FOXTROT LLC",
            "entity_type": "LLC",
            "formation_state_code": "ZZ",
            "revenue_band": "ZERO",
        },
        make_anonymous_headers(),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_business_entity_status_computed_input_value_ignored(api):
    """PRD §3.1: "On creation the entity is persisted with `status` set to
    `FORMING`"

    Design: Corner/entities/business_entity_status_computed_input_value_ignored
    """
    # Attempting to seed status from input must not bypass the server-set value.
    res = api.create_business_entity(
        {
            "legal_name": "GOLF LLC",
            "entity_type": "LLC",
            "formation_state_code": "DE",
            "revenue_band": "ZERO",
            "status": "ACTIVE",
        },
        make_anonymous_headers(),
    )
    body = validate_success(res, 201)
    assert body["status"] == "FORMING"


def test_business_entity_id_and_timestamps_server_minted(api):
    """PRD §2.4: "The `id` is a server-minted UUID string; it never carries a
    type prefix, never echoes any input, and is the sole stable identifier for
    cross-resource references."
    PRD §2.4: "The `created_at` and `updated_at` timestamps are ISO 8601 UTC
    strings with three fractional digits"
    PRD §2.4: "The `version` is an integer that starts at 1 on insert and
    increments by exactly 1 on every successful mutation of that resource"

    Design: Corner/entities/business_entity_id_and_timestamps_server_minted
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_business_entity(
        {
            "legal_name": "HOTEL LLC",
            "entity_type": "LLC",
            "formation_state_code": "DE",
            "revenue_band": "ZERO",
        },
        make_anonymous_headers(),
    )
    body = validate_success(res, 201)
    assert is_valid_uuid(body["id"])
    assert is_iso8601_timestamp(body["formed_at"])
    assert is_iso8601_timestamp(body["created_at"])
    assert is_iso8601_timestamp(body["updated_at"])
    assert body["version"] == 1


def test_compliance_event_is_immutable_log_no_update_endpoint(api):
    """PRD §2.4: "`ComplianceEvent` is the lone exception: it is an immutable audit
    row carrying only `id`, `business_entity_id`, `event_type`, `event_payload`,
    and the server-stamped `event_at` timestamp. It has no `updated_at` and no
    `version`, because compliance events are never rewritten — they are inserted
    and then read."

    Design: Corner/entities/compliance_event_is_immutable_log_no_update_endpoint
    """
    set_clock("2026-02-01T00:00:00Z")
    be = create_forming_business_entity(legal_name="INDIA LLC")
    create_registered_agent_for(be)
    res = api.list_compliance_events(be["id"], make_compliance_officer_headers())
    data, _meta = validate_paginated(res)
    assert isinstance(data, list)
    # PRD §2.4: ComplianceEvent rows MUST omit updated_at and version.
    for ev in data:
        assert "updated_at" not in ev, "ComplianceEvent must not carry updated_at"
        assert "version" not in ev, "ComplianceEvent must not carry version"
