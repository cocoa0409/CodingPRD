"""Entity creation, validation, defaults, and listing corners.

Each test translates exactly one corner-design instance from §1.9 (entities section).
"""
import pytest
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    assert_member,
    create_member_payload,
    create_trip_payload,
    create_eligibility_span_payload,
    NON_EXISTENT_UUID,
)

COORD = TEST_USERS["coordinator_headers"]


def test_create_member_minimal_returns_201_eligible(api):
    """PRD 3.1: "A new member begins with `eligibility_status` of `ELIGIBLE`, a
    `noshow_strike_count` of 0, and `standing_orders_paused` set to false."
    PRD 2.4: "The `version` is an integer that begins at its initial value and
    increments by one on each mutation".

    Design: Corner/entities/create_member_minimal_returns_201_eligible
    """
    resp = api.create_member(
        create_member_payload(medicaid_id="M-EN1", full_name="Ent One",
                              mobility_level="AMBULATORY", home_county="C1"),
        COORD,
    )
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["eligibility_status"] == "ELIGIBLE"
    assert data["noshow_strike_count"] == 0
    assert data["standing_orders_paused"] is False
    assert data["version"] == 1


def test_get_member_not_found_returns_404(api):
    """PRD 2.6: "The first identifier in the path that does not resolve to an
    existing resource causes the request to be rejected with `ERR_NOT_FOUND`
    (HTTP 404)".

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_member_missing_required_field_returns_400(api):
    """PRD 3.1: "A `Coordinator` creates a member by supplying a `medicaid_id`
    (the state identifier, unique among members), a `full_name`, the member's
    `mobility_level` (the highest modality the member is approved to require, one
    of `AMBULATORY`, `WHEELCHAIR`, or `STRETCHER`), and a `home_county` code."
    PRD 5: ERR_INVALID_REQUEST -> 400 for malformed or missing-required-field bodies.

    Design: Corner/entities/create_member_missing_required_field_returns_400
    """
    resp = api.create_member(
        {"medicaid_id": "M-MR1", "full_name": "Miss Req", "home_county": "C1"},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_member_invalid_enum_returns_400(api):
    """PRD 2.10: "and finally, malformed-or-out-of-domain field values
    (`ERR_INVALID_REQUEST`)."
    PRD 3.1: mobility_level is "one of `AMBULATORY`, `WHEELCHAIR`, or `STRETCHER`".

    Design: Corner/entities/create_member_invalid_enum_returns_400
    """
    resp = api.create_member(
        create_member_payload(medicaid_id="M-EN2", full_name="Bad Enum",
                              mobility_level="GURNEY", home_county="C1"),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_trip_default_is_round_trip_true(api):
    """PRD 3.3: "The request may set `is_round_trip` (a return leg is required;
    defaults to true)".

    Design: Corner/entities/trip_default_is_round_trip_true
    """
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-DF1", full_name="Def One",
                              mobility_level="AMBULATORY", home_county="C1"), COORD))
    # is_round_trip omitted -> default true.
    resp = api.create_trip(
        create_trip_payload(member["id"], modality="AMBULATORY",
                            requested_level_of_service="ROUTINE",
                            appointment_at="2026-03-02T09:00:00Z",
                            scheduled_loaded_miles=8),
        COORD,
    )
    data = validate_success(resp, 201)
    assert data["is_round_trip"] is True


def test_trip_system_fields_initialized_on_create(api):
    """PRD 3.3: "A new trip begins with `trip_status` of `DRAFT` and
    `billing_status` of `UNBILLED`, and its computed money fields —
    `claimed_cost_cents`, `encounter_cost_cents`, and
    `reconciliation_variance_cents` — all start at 0".

    Design: Corner/entities/trip_system_fields_ignored_on_input
    """
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-SF1", full_name="Sys One",
                              mobility_level="AMBULATORY", home_county="C1"), COORD))
    resp = api.create_trip(
        create_trip_payload(member["id"], modality="AMBULATORY",
                            requested_level_of_service="ROUTINE",
                            appointment_at="2026-03-02T09:00:00Z",
                            scheduled_loaded_miles=8, is_round_trip=False),
        COORD,
    )
    data = validate_success(resp, 201)
    assert data["trip_status"] == "DRAFT"
    assert data["billing_status"] == "UNBILLED"
    assert data["claimed_cost_cents"] == 0


def test_eligibility_span_immutable_no_version_field(api):
    """PRD 2.4: "Two entity types are immutable append-only records and therefore
    carry only `id` and `created_at` — they have neither `updated_at` nor
    `version`. The first is the **EligibilitySpan**".

    Design: Corner/entities/eligibility_span_immutable_no_version_field
    """
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-IM1", full_name="Imm One",
                              mobility_level="AMBULATORY", home_county="C1"), COORD))
    resp = api.create_eligibility_span(
        create_eligibility_span_payload(member["id"], level_of_service="ROUTINE",
                                        coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end="2027-01-01T00:00:00Z"),
        COORD,
    )
    data = validate_success(resp, 201)
    assert "id" in data
    assert "created_at" in data
    assert "version" not in data, "EligibilitySpan must not expose version"
    assert "updated_at" not in data, "EligibilitySpan must not expose updated_at"


def test_create_trip_fk_member_not_found_returns_422(api):
    """PRD 2.10: "then existence of every foreign-key identifier supplied in the
    body (`ERR_FK_NOT_FOUND`)".
    PRD 5: ERR_FK_NOT_FOUND -> 422.

    Design: Corner/entities/create_trip_fk_member_not_found_returns_422
    """
    resp = api.create_trip(
        {"member_id": NON_EXISTENT_UUID, "modality": "AMBULATORY",
         "requested_level_of_service": "ROUTINE",
         "appointment_at": "2026-03-02T09:00:00Z",
         "scheduled_loaded_miles": 8, "is_round_trip": False},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_list_members_trips_pagination_envelope(api):
    """PRD 2.3: "Every list response surfaces `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_members_trips_pagination_envelope
    """
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-LS1", full_name="Lst One",
                              mobility_level="AMBULATORY", home_county="C1"), COORD))
    for appt in ("2026-03-02T09:00:00Z", "2026-03-03T09:00:00Z"):
        get_success_data(api.create_trip(
            create_trip_payload(member["id"], modality="AMBULATORY",
                                requested_level_of_service="ROUTINE",
                                appointment_at=appt, scheduled_loaded_miles=8,
                                is_round_trip=False), COORD))
    resp = api.list_member_trips(member["id"], COORD)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
