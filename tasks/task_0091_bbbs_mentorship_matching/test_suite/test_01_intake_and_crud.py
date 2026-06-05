"""Intake, CRUD, listing, and guardian-update OCC.

Queue-B (Corner) entity-section and cross-cutting translations.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_volunteer,
    assert_child,
    factories as f,
    fixtures as fx,
)
from test_helpers.constants import NONEXISTENT_UUID

COORD = fx.COORD
SPECIALIST = fx.SPECIALIST


def test_create_volunteer_returns_201_with_defaults(api):
    """PRD §3.1: "A newly registered volunteer begins in `APPLIED` with an
    `active_match_count` of 0 and no `cleared_check_id`."
    PRD §2.4: "an integer `version` that begins at 1".

    Design: Corner/entities/create_volunteer_returns_201_with_defaults
    """
    fx.set_clock(fx.REF_CLOCK)
    resp = api.create_volunteer(
        f.create_volunteer_payload(full_name="V Create", max_weekly_hours=3), COORD
    )
    data = validate_success(resp, 201)
    assert_volunteer(data)
    assert data["status"] == "APPLIED"
    assert data["active_match_count"] == 0
    assert data["cleared_check_id"] is None
    assert data["version"] == 1


def test_get_volunteer_not_found_returns_404(api):
    """PRD §5: `ERR_NOT_FOUND` maps to HTTP 404.
    PRD §2.6: "existence of every referenced resource, validated left-to-right
    along the URL path ... yielding `ERR_NOT_FOUND`".

    Design: Corner/entities/get_volunteer_not_found_returns_404
    """
    fx.set_clock(fx.REF_CLOCK)
    resp = api.get_volunteer(NONEXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_child_missing_required_age_returns_invalid_request(api):
    """PRD §3.3: "A child (a Little) is enrolled under a guardian's `guardian_id`
    with a `first_name`, an `age` that must be between 6 and 16 inclusive at
    enrollment".
    PRD §2.6: "presence, typing, enum membership, and numeric range of
    request-body fields, yielding `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_child_missing_required_age_returns_invalid_request
    """
    fx.set_clock(fx.REF_CLOCK)
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Req")
    payload = f.create_child_payload(guardian["id"], first_name="NoAge")
    del payload["age"]
    resp = api.create_child(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_child_age_out_of_range_returns_invalid_request(api):
    """PRD §3.3: "an `age` that must be between 6 and 16 inclusive at enrollment".
    PRD §2.6: "numeric range of request-body fields, yielding `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_child_age_out_of_range_returns_invalid_request
    """
    fx.set_clock(fx.REF_CLOCK)
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Age")
    resp = api.create_child(
        f.create_child_payload(guardian["id"], first_name="Young", age=5), SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_child_with_bad_guardian_fk_returns_404(api):
    """PRD §2.6: "existence of every referenced resource, validated left-to-right
    along the URL path and then for any body foreign keys, yielding `ERR_NOT_FOUND`".

    Design: Corner/entities/create_child_with_bad_guardian_fk_returns_404
    """
    fx.set_clock(fx.REF_CLOCK)
    resp = api.create_child(
        f.create_child_payload(NONEXISTENT_UUID, first_name="Orphan", age=9), SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_child_system_fields_ignored_on_input(api):
    """PRD §3.3: "A child begins `WAITLISTED` with no `open_proposal_id`."

    Design: Corner/entities/child_system_fields_ignored_on_input
    """
    fx.set_clock(fx.REF_CLOCK)
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Sys")
    payload = f.create_child_payload(
        guardian["id"], first_name="Sys", gender="FEMALE", interest_tags=["ARTS"]
    )
    # Attempt to seed system-managed fields; they must be ignored.
    payload["status"] = "MATCHED"
    payload["open_proposal_id"] = NONEXISTENT_UUID
    resp = api.create_child(payload, SPECIALIST)
    data = validate_success(resp, 201)
    assert_child(data)
    assert data["status"] == "WAITLISTED"
    assert data["open_proposal_id"] is None


def test_list_volunteers_pagination_envelope(api):
    """PRD §2.3: "the `meta` object additionally carries `limit`, `offset`,
    `total_count` (the total number of matching records before the page window
    is applied), and `has_more` (true when records remain beyond the current
    window)."

    Design: Corner/entities/list_volunteers_pagination_envelope
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_volunteer(set_clock_first=False, full_name="V L1")
    fx.create_volunteer(set_clock_first=False, full_name="V L2", gender="FEMALE",
                        home_zip="10002", interest_tags=["ARTS"])
    resp = api.list_volunteers(COORD, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_volunteers_bad_limit_returns_invalid_request(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/list_volunteers_bad_limit_returns_invalid_request
    """
    fx.set_clock(fx.REF_CLOCK)
    resp = api.list_volunteers(COORD, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_guardian_patch_increments_version_and_records_consent(api):
    """PRD §2.5: "the guardian update simply requires the field as part of its
    normal mutation contract and increments the guardian's `version` by one on
    success."
    PRD §3.3: "A guardian record can be updated — chiefly to record that consent
    is now on file".

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_guardian_patch
    """
    fx.set_clock(fx.REF_CLOCK)
    guardian = fx.create_guardian(consent_on_file=False, full_name="G Occ")
    assert guardian["version"] == 1
    resp = api.update_guardian(
        guardian["id"],
        {"consent_on_file": True, "expected_guardian_version": guardian["version"]},
        COORD,
    )
    data = validate_success(resp, 200)
    assert data["version"] == 2
    assert data["consent_on_file"] is True
