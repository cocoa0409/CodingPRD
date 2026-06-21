"""Owner / Sitter / Pet / EmergencyContact / BackgroundCheck onboarding tests
and append-only GpsTrack semantics. Listing-pagination envelope test for
list_owners. These tests cover queue B corner instances rooted in the
'entities' / 'endpoints' sections of the corner design.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    create_owner_payload,
    create_sitter_payload,
    create_pet_payload,
    create_background_check_payload,
    create_emergency_contact_payload,
    create_gps_track_payload,
    fresh_email,
    fresh_phone,
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    setup_in_progress_booking,
    flag_bg_check,
    register_sitter,
    create_pending_bg_check,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def test_owner_registration_returns_201_with_wallet_zero_and_version_one(api):
    """PRD §3.1: "The submitted `email` must be unique across owners and
    non-empty, the `phone` is captured in E.164 form, and the new `Owner`
    row starts with `wallet_credit_cents` of 0."
    PRD §2.4: "an integer `version` field that starts at 1 on creation
    and increments by exactly 1 on every mutation that changes the row."

    Design: Corner/entities/owner_creation_minimum_required_fields_succeeds
    """
    payload = create_owner_payload(email="corner_owner@example.com",
                                    full_name="Corner Owner",
                                    phone="+12025559001")
    res = api.register_owner(payload, ANONYMOUS)
    owner = validate_success(res, expected_status=201)
    assert is_valid_uuid(owner["id"])
    assert owner["version"] == 1
    assert owner["wallet_credit_cents"] == 0
    assert owner["email"] == "corner_owner@example.com"


def test_owner_register_missing_email_invalid_request(api):
    """PRD §2.7: "Request bodies that violate the basic shape contract —
    missing a required field, supplying the wrong type, an enum value
    outside the declared set, or a negative integer where a non-negative
    integer is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/owner_register_missing_required_field_invalid_request
    """
    payload = {"full_name": "No Email", "phone": "+12025559002"}
    res = api.register_owner(payload, ANONYMOUS)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_sitter_register_fresh_defaults(api):
    """PRD §3.1: "the new `Sitter` row is created in the `APPLIED` status
    with `tier` `BRONZE`, `tier_score` 10, and zero counters for
    `total_completed_bookings`, `total_rating_sum`, `total_rating_count`,
    `claim_count`, and `pending_payout_cents`."

    Design: Corner/entities/sitter_register_fresh_defaults
    """
    payload = create_sitter_payload(email="fresh_sitter@example.com",
                                     full_name="Fresh Sitter",
                                     phone="+12025559003")
    sitter = validate_success(api.register_sitter(payload, ANONYMOUS), expected_status=201)
    assert sitter["status"] == "APPLIED"
    assert sitter["tier"] == "BRONZE"
    assert sitter["tier_score"] == 10
    assert sitter["claim_count"] == 0
    assert sitter["total_completed_bookings"] == 0
    assert sitter["total_rating_sum"] == 0
    assert sitter["total_rating_count"] == 0
    assert sitter["pending_payout_cents"] == 0
    assert sitter["suspended_at"] is None


def test_owner_retrieval_returns_full_entity(api):
    """PRD §2.4: "Every persisted resource carries an `id`, which is a
    server-minted UUID."

    Design: Corner/entities/owner_retrieval_returns_full_entity
    """
    payload = create_owner_payload(email="ret_owner@example.com",
                                    full_name="Ret Owner",
                                    phone="+12025559004")
    created = validate_success(api.register_owner(payload, ANONYMOUS), expected_status=201)
    res = api.get_owner(created["id"], make_owner_headers(created["id"]))
    retrieved = validate_success(res, expected_status=200)
    assert retrieved["id"] == created["id"]
    assert retrieved["email"] == "ret_owner@example.com"


def test_pet_creation_with_nonexistent_owner_fk_not_found(api):
    """PRD §2.7: "Foreign keys passed in a `POST` request body — `owner_id`,
    `sitter_id`, `pet_id`, `booking_id` — are validated against their
    parent tables; a non-existent reference is rejected with
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/pet_creation_referenced_owner_not_found
    """
    real_owner = validate_success(api.register_owner(create_owner_payload(), ANONYMOUS), 201)
    bogus_owner_id = "00000000-0000-0000-0000-000000000000"
    payload = {"owner_id": bogus_owner_id, "name": "Ghost", "species": "DOG", "weight_kg": 10}
    res = api.create_pet(payload, make_owner_headers(real_owner["id"]))
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_pet_invalid_species_enum_rejected(api):
    """PRD §3.1: "Each `Pet` row carries the owning `owner_id`, a `name`,
    a `species` (one of `DOG` or `CAT`), a strictly positive `weight_kg`,
    and free-text `medical_notes` (defaulting to the empty string)."
    PRD §2.7: "Request bodies that violate the basic shape contract —
    missing a required field, supplying the wrong type, an enum value
    outside the declared set, or a negative integer where a non-negative
    integer is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/pet_invalid_species_enum
    """
    owner = validate_success(api.register_owner(create_owner_payload(), ANONYMOUS), 201)
    payload = {"owner_id": owner["id"], "name": "Ham", "species": "HAMSTER", "weight_kg": 0.5}
    res = api.create_pet(payload, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_gps_track_is_append_only_no_version_no_updated_at(api):
    """PRD §2.4: "One entity is intentionally append-only: `GpsTrack` rows
    are written once and never modified, so `GpsTrack` carries only `id`
    and `created_at` — both `updated_at` and `version` are absent."
    PRD §3.5: "GPS-track rows are append-only — once written they are
    never modified — so they carry only `id` and `created_at`, no
    `updated_at` and no `version`."

    Design: Corner/entities/gps_track_immutable_no_version_field
    """
    owner, sitter, pet, mg, booking, kh = setup_in_progress_booking(
        clock_iso="2026-06-21T08:00:00Z",
        mg_scheduled_at="2026-06-21T07:30:00Z",
        booking_start_at="2026-06-21T09:00:00Z",
        booking_end_at="2026-06-21T09:30:00Z",
        service_type="WALK_30MIN",
    )
    payload = create_gps_track_payload(booking["id"], "2026-06-21T09:05:00Z",
                                        latitude=40.7128, longitude=-74.0060)
    res = api.create_gps_track(payload, make_sitter_headers(sitter["id"]))
    track = validate_success(res, expected_status=201)
    assert is_valid_uuid(track["id"])
    assert "version" not in track, f"GpsTrack must NOT carry version field; got {track!r}"
    assert "updated_at" not in track, f"GpsTrack must NOT carry updated_at field; got {track!r}"


def test_emergency_contact_priority_one_uniqueness_rejected(api):
    """PRD §3.1: "At most one emergency contact per owner may have
    `priority` of 1; attempting to create a second primary contact for
    the same owner is rejected with `ERR_PRIMARY_CONTACT_EXISTS`."

    Design: Corner/validations/emergency_contact_priority_one_uniqueness
    """
    owner = validate_success(api.register_owner(create_owner_payload(), ANONYMOUS), 201)
    headers = make_owner_headers(owner["id"])
    # First primary contact succeeds.
    first = validate_success(api.create_emergency_contact(
        create_emergency_contact_payload(owner["id"], full_name="Primary",
                                          phone="+12025559054",
                                          relationship="SPOUSE", priority=1),
        headers,
    ), expected_status=201)
    assert first["priority"] == 1
    # Second priority=1 must be rejected.
    res = api.create_emergency_contact(
        create_emergency_contact_payload(owner["id"], full_name="Second Primary",
                                          phone="+12025559055",
                                          relationship="FRIEND", priority=1),
        headers,
    )
    validate_error(res, "ERR_PRIMARY_CONTACT_EXISTS")


def test_list_owners_pagination_envelope(api):
    """PRD §2.3: "All list endpoints accept two query parameters, `limit`
    and `offset`."
    PRD §2.3: "The pagination block in `meta` exposes the four pagination
    fields `limit`, `offset`, `total_count` (the total number of records
    that satisfy the request's filters, irrespective of pagination), and
    `has_more` (a boolean that is true exactly when
    `offset + limit < total_count`)."

    Design: Corner/endpoints/list_owners_pagination_envelope
    """
    # Create three owners.
    for i in range(3):
        validate_success(api.register_owner(
            create_owner_payload(email=f"olist{i}@example.com", full_name=f"O{i}"),
            ANONYMOUS,
        ), expected_status=201)
    res = api.list_owners(PLATFORM_ADMIN, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 2
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True
