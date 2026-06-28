"""Corner queue — entities section: student creation defaults and system-minted
fields, not-found, required-field and range validation, and the append-only
EssayVersion record.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_counselor_headers,
    make_student_headers,
    assert_student,
    assert_essay_version,
    NON_EXISTENT_UUID,
    ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


def test_create_student_returns_201_with_system_fields(api):
    """PRD §3.1: "A new student begins life with `intake_status` of `PROSPECT`, a
    `profile_strength` of 0, and `list_locked` set to false."
    PRD §2.4: "The `version` is an integer that begins at its initial value and
    increments by one on every mutation of the resource"

    Design: Corner/entities/create_student_returns_201_with_system_fields
    """
    counselor = fx.create_counselor(full_name="CC1", email="cc1@x.com", hourly_rate_cents=18000)
    ch = make_counselor_headers(counselor["id"])
    data = validate_success(
        api.create_student(
            f.create_student_payload(counselor["id"], full_name="New S", email="ns@x.com",
                                     grad_year=2027, gpa=3.4, sat_total=1280),
            ch,
        ),
        expected_status=201,
    )
    assert_student(data)
    assert data["intake_status"] == "PROSPECT"
    assert data["list_locked"] is False
    assert data["version"] == 1


def test_get_student_not_found_returns_404(api):
    """PRD §2.6: "When a path names a resource by its identifier and no such
    resource exists, the request is rejected with `ERR_NOT_FOUND`"

    Design: Corner/entities/get_student_not_found_returns_404
    """
    counselor = fx.create_counselor(full_name="CC2", email="cc2@x.com", hourly_rate_cents=18000)
    ch = make_counselor_headers(counselor["id"])
    resp = api.get_student(NON_EXISTENT_UUID, ch)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_student_missing_grad_year_invalid_request(api):
    """PRD §2.6: "A malformed body — a missing required field, an unrecognized
    enum value, or an out-of-range number — is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_student_missing_required_field_invalid_request
    """
    counselor = fx.create_counselor(full_name="CC3", email="cc3@x.com", hourly_rate_cents=18000)
    ch = make_counselor_headers(counselor["id"])
    resp = api.create_student(
        {"counselor_id": counselor["id"], "full_name": "No Grad", "email": "ng@x.com", "gpa": 3.4},
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_student_sat_total_defaults_zero(api):
    """PRD §3.1: "The counselor may also supply `sat_total`; this is either 0,
    meaning no score has been submitted yet, or a value from 400 through 1600
    inclusive, and it defaults to 0."

    Design: Corner/entities/create_student_sat_total_default_zero
    """
    counselor = fx.create_counselor(full_name="CC4", email="cc4@x.com", hourly_rate_cents=18000)
    ch = make_counselor_headers(counselor["id"])
    data = validate_success(
        api.create_student(
            {"counselor_id": counselor["id"], "full_name": "Default S", "email": "ds@x.com",
             "grad_year": 2027, "gpa": 3.4},
            ch,
        ),
        expected_status=201,
    )
    assert data["sat_total"] == 0, f"omitted sat_total should default to 0; got {data['sat_total']}"


def test_create_student_bad_gpa_range_invalid_request(api):
    """PRD §3.1: "an unweighted `gpa` on a scale where the value must be at least
    0.0 and at most 4.0."
    PRD §2.6: "A malformed body — a missing required field, an unrecognized enum
    value, or an out-of-range number — is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_student_bad_gpa_range_invalid_request
    """
    counselor = fx.create_counselor(full_name="CC5", email="cc5@x.com", hourly_rate_cents=18000)
    ch = make_counselor_headers(counselor["id"])
    resp = api.create_student(
        f.create_student_payload(counselor["id"], full_name="Bad GPA", email="bg@x.com",
                                 grad_year=2027, gpa=5.0, sat_total=1200),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_essay_version_first_version_no_is_one(api):
    """PRD §3.5: "An `EssayVersion` is an append-only snapshot carrying the
    `essay_id`, the monotonic per-essay `version_no` (starting at 1), the
    `word_count`, the full `body`, and the `submitted_by_role`."
    PRD §2.4: "Two entities are immutable append-only records and therefore carry
    only `id` and `created_at` — they have neither an `updated_at` field nor a
    `version` field."

    Design: Corner/entities/essayversion_immutable_version_no_one
    """
    counselor, student, essay = fx.setup_essay_in_review(
        word_count=500, body="draft", essay_overrides={"prompt": "P", "word_limit": 650}
    )
    ch = make_counselor_headers(counselor["id"])
    versions, meta = validate_paginated(
        api.list_essay_versions(ch, params={"essay_id": essay["id"]})
    )
    assert len(versions) == 1
    assert versions[0]["version_no"] == 1, (
        f"first submitted version should carry version_no 1; got {versions[0]['version_no']}"
    )
    assert_essay_version(versions[0])
