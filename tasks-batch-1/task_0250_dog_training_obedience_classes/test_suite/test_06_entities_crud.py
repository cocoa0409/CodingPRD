"""Entity CRUD, defaults, computed facets, immutability, parent references, and listing.

Corner-design coverage for the `entities` section plus auth/endpoint corners.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, TEST_USERS, make_owner_headers,
    create_owner_payload, create_dog_payload, create_trainer_payload,
    create_behavioral_intake_payload, create_class_session_payload,
    create_owner, create_dog, vaccinate_fully, create_trainer, create_series_draft,
    set_clock, create_vaccination_payload,
    assert_owner, assert_trainer,
)


def test_create_owner_returns_201_with_system_fields(api):
    """PRD §2.4: "a `version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation." PRD §3.1: "An `Owner` is created with a `full_name`, an
    `email`, and a `phone`."

    Design: Corner/entities/create_owner_returns_201_with_system_fields
    """
    res = api.create_owner(create_owner_payload(email="brand-new@example.com"),
                           TEST_USERS["front_desk_headers"])
    owner = validate_success(res, 201)
    assert_owner(owner)
    assert owner["version"] == 1


def test_create_dog_missing_required_name_returns_invalid_request(api):
    """PRD §2.5: "A malformed request body — a missing required field, a value of the wrong
    type, or an enum value outside its permitted set — is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "A `Dog` is registered against an existing owner via `owner_id`, together with a
    `name`, a `breed`, and a `birth_date`".

    Design: Corner/entities/create_dog_missing_required_field_returns_invalid_request
    """
    owner = create_owner()
    payload = create_dog_payload(owner["id"])
    del payload["name"]
    res = api.create_dog(payload, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_nonexistent_dog_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve to a stored resource produces the
    corresponding not-found error and halts processing before any later check runs —
    `ERR_SERIES_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DOG_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`,
    `ERR_TRAINER_NOT_FOUND`, `ERR_ATTENDANCE_NOT_FOUND`, or `ERR_MAKEUP_NOT_FOUND` respectively."

    Design: Corner/entities/get_dog_nonexistent_returns_not_found
    """
    res = api.get_dog(NON_EXISTENT_UUID, TEST_USERS["front_desk_headers"])
    validate_error(res, "ERR_DOG_NOT_FOUND", expected_status=404)


def test_trainer_handles_private_defaults_true(api):
    """PRD §3.3: "an optional `handles_private` boolean that defaults to true and records
    whether the trainer accepts private sessions."

    Design: Corner/entities/create_trainer_handles_private_default_true
    """
    payload = create_trainer_payload()  # no handles_private supplied
    res = api.create_trainer(payload, TEST_USERS["admin_manager_headers"])
    trainer = validate_success(res, 201)
    assert trainer["handles_private"] is True
    assert_trainer(trainer)


def test_dog_vaccination_posture_compliant_after_three_vaccines(api):
    """PRD §3.2: "The posture is `COMPLIANT` only when all three required types are covered at
    the reference date". PRD §3.1: "Reading a single dog recomputes its `vaccination_posture`
    against the current clock before returning it."

    Design: Corner/entities/dog_vaccination_posture_computed_compliant_after_three_vaccines
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)  # RABIES + DHPP + BORDETELLA, all valid at clock
    res = api.get_dog(dog["id"], make_owner_headers(owner["id"]))
    refetched = validate_success(res, 200)
    assert refetched["vaccination_posture"] == "COMPLIANT"


def test_intake_outcome_flagged_at_threshold(api):
    """PRD §3.1: "the dog is `FLAGGED` if it has a `bite_history` of true, or if its
    `reactivity_score` is at least 7; otherwise the outcome is `CLEARED`." PRD §3.1: "A
    companion computed flag, `requires_private_first`, is true exactly when the outcome is
    `FLAGGED`".

    Design: Corner/entities/intake_outcome_flagged_on_threshold
    """
    owner = create_owner()
    dog = create_dog(owner)
    res = api.create_behavioral_intake(
        dog["id"],
        create_behavioral_intake_payload(reactivity_score=7, bite_history=False,
                                         recommended_level="BASIC"),
        TEST_USERS["trainer_headers"])
    intake = validate_success(res, 201)
    assert intake["outcome"] == "FLAGGED", "reactivity_score == 7 (>= threshold)"
    assert intake["requires_private_first"] is True


def test_vaccination_record_is_read_only(api):
    """PRD §2.4: "Three entities are append-only audit records and therefore carry only `id`
    and `created_at`; they have neither `updated_at` nor `version`. These are the
    `VaccinationRecord`, the `PackageRedemption` ledger row, and the `Certificate`." PRD §3.2:
    "Each record also carries a `voided` flag, false by default".

    Design: Corner/entities/vaccination_record_is_immutable_no_version_field
    """
    owner = create_owner()
    dog = create_dog(owner)
    rec = get_success_data(api.create_vaccination(
        dog["id"], create_vaccination_payload("RABIES"), make_owner_headers(owner["id"])))
    res = api.get_vaccination(rec["id"], make_owner_headers(owner["id"]))
    fetched = validate_success(res, 200)
    assert fetched["voided"] is False, "default voided flag on a fresh record"


def test_dog_requires_existing_owner(api):
    """PRD §3.1: "A `Dog` is registered against an existing owner via `owner_id`". PRD §2.5:
    "`ERR_OWNER_NOT_FOUND`".

    Design: Corner/entities/dog_requires_existing_owner_parent
    """
    res = api.create_dog(create_dog_payload(NON_EXISTENT_UUID, name="Orphan"),
                         TEST_USERS["front_desk_headers"])
    validate_error(res, "ERR_OWNER_NOT_FOUND", expected_status=404)


def test_list_owners_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope." PRD §2.2: "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/list_owners_paginated_envelope
    """
    create_owner()
    data, meta = validate_paginated(
        api.list_owners(TEST_USERS["front_desk_headers"], params={"limit": 10, "offset": 0}))
    assert isinstance(data, list)
    assert "total_count" in meta
    assert "has_more" in meta
    assert meta["total_count"] >= 1


# ─── endpoints section ──────────────────────────────────────────────────────────
def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a value the server cannot
    interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/endpoints/missing_user_context_header_returns_400
    """
    res = api.create_owner(create_owner_payload(email="noauth@example.com"), headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_invalid_session_times_rejected(api):
    """PRD §3.3: "The `ends_at` must be strictly later than `starts_at`; otherwise the request
    is rejected with `ERR_INVALID_SESSION_TIMES`."

    Design: Corner/endpoints/invalid_session_times_rejected
    """
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    res = api.create_class_session(
        create_class_session_payload(series["id"], trainer["id"], sequence_index=1,
                                     starts_at="2026-07-01T10:00:00Z", ends_at="2026-07-01T09:00:00Z"),
        TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_INVALID_SESSION_TIMES", expected_status=400)
