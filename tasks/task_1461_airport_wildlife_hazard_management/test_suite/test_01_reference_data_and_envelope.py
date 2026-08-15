"""Reference-data creation, field validation, and list-envelope claims."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    assert_airport,
    create_airport_payload,
    create_species_payload,
    create_airport,
    NON_EXISTENT_UUID,
    ApiErrorId,
)


def test_airport_creation_required_fields_and_defaults(api, admin_headers):
    """PRD §3.1: "On creation the airport's `current_hazard_level` starts at
    `LOW`, both `strikes_trailing_12m` and `strikes_trailing_12m_high_risk`
    start at zero, and `hazard_level_updated_at` is unset until the first
    recompute."
    PRD §2.4: "a `version` integer that starts at 1 and is incremented by 1
    on every state transition or other mutation of that resource."

    Design: Corner/entities/airport_creation_required_fields_and_defaults
    """
    created = validate_success(
        api.create_airport(
            create_airport_payload(
                icao_code="KAAA", name="Alpha Airport", annual_plan_cycle_year=2026,
            ),
            admin_headers,
        ),
        201,
    )
    assert_airport(created)

    fetched = validate_success(api.get_airport(created["id"], admin_headers), 200)
    assert_airport(fetched)
    assert fetched["current_hazard_level"] == "LOW", (
        f"expected LOW on creation, got {fetched['current_hazard_level']}"
    )
    assert fetched["strikes_trailing_12m"] == 0
    assert fetched["strikes_trailing_12m_high_risk"] == 0
    assert fetched["version"] == 1


def test_airport_creation_missing_required_field_returns_400(api, admin_headers):
    """PRD §2.5: "A request that omits a required field, or supplies a value
    that falls outside the field's declared constraint range (a `body_mass_g`
    of zero, an `attractiveness_score` of eleven, an `annual_plan_cycle_year`
    outside 2000–2100, a malformed `runway_designator`, and so on), is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/airport_creation_missing_required_field_returns_400
    """
    payload = {"icao_code": "KBBB", "annual_plan_cycle_year": 2026}
    res = api.create_airport(payload, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_species_enum_guild_rejected_when_invalid(api, admin_headers):
    """PRD §2.5: "A request that supplies an enum field with a value outside
    the declared set (an unrecognized `damage_class`, `phase_of_flight`,
    `guild`, `risk_tier`, `action_type`, `method`, `habitat_feature`,
    `disposal_method`, `identification_method`, `reason_code`, `reason`,
    `agency`, or `hazard_level`) is rejected with `ERR_INVALID_ENUM`
    (HTTP 400)."

    Design: Corner/entities/species_enum_guild_rejected_when_invalid
    """
    payload = create_species_payload(
        common_name="X", scientific_name="X x", guild="INSECT",
        risk_tier="LOW", body_mass_g=10, is_protected_federally=False,
    )
    res = api.create_species(payload, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM.value, expected_status=400)


def test_strike_report_not_found_returns_404(api, admin_headers):
    """PRD §2.5: "A path identifier that does not resolve to an existing
    record is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/strike_report_not_found_returns_404
    """
    res = api.get_strike_report(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_list_airports_pagination_envelope(api, admin_headers):
    """PRD §2.3: "All list endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of
    100. `offset` defaults to 0. List results are always sorted by
    `created_at` ascending unless otherwise noted. Every list response's
    `meta` block reports `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_airports_pagination_envelope
    """
    for icao, name in (
        ("KMMM", "Mike Airport"),
        ("KNNN", "November Airport"),
        ("KOOO", "Oscar Airport"),
    ):
        create_airport(icao_code=icao, name=name)

    data, meta = validate_paginated(api.list_airports(admin_headers))
    assert len(data) == 3, f"expected 3 airports within default limit, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
