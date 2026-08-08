"""Complaint intake/review, field inspections, effective-limit resolution, and
substantiation gating (queue A boundary + queue B corner)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    resident_headers, code_officer_headers,
)
from test_helpers import fixtures as fx


# --- Effective limit + strict-exceeds boundary (queue A) ---

def test_reading_equal_to_limit_is_not_a_violation(api):
    """PRD §3.3: "the boolean `exceeds_limit`, which is true if and only if
    `measured_decibel` is strictly greater than `effective_limit_db`. A reading
    exactly equal to the limit is **not** a violation."

    Design: Difficulty/boundary_precision_check/decibel_strict_exceeds_boundary
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="11 Edge Ave")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="MACHINERY")
    fx.review(api, c["id"])
    resp = api.create_inspection(c["id"], {"measured_decibel": 65, "measured_at": "2026-06-01T12:00:00Z"},
                                 code_officer_headers())
    data = validate_success(resp, 201)
    assert data["effective_limit_db"] == 65
    assert data["exceeds_limit"] is False


def test_reading_one_decibel_above_limit_is_a_violation(api):
    """PRD §3.3: "the boolean `exceeds_limit`, which is true if and only if
    `measured_decibel` is strictly greater than `effective_limit_db`. A reading
    exactly equal to the limit is **not** a violation."

    Design: Difficulty/boundary_precision_check/decibel_strict_exceeds_boundary
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="11 Edge Ave")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="MACHINERY")
    fx.review(api, c["id"])
    resp = api.create_inspection(c["id"], {"measured_decibel": 66, "measured_at": "2026-06-01T12:00:00Z"},
                                 code_officer_headers())
    data = validate_success(resp, 201)
    assert data["exceeds_limit"] is True


def test_night_hour_resolves_to_night_limit(api):
    """PRD §3.3: "when that hour is at least `day_start_hour` and strictly less than
    `night_start_hour`, `effective_limit_db` is the policy's `day_limit_db`; otherwise
    it is the `night_limit_db`."

    Design: Corner/calculations/night_limit_applied_correct
    """
    fx.config_policy(api, "RESIDENTIAL", day_limit=55, night_limit=45)
    prop = fx.new_property(api, "RESIDENTIAL", address="110 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T23:00:00Z", noise_type="AMPLIFIED_MUSIC")
    fx.review(api, c["id"])
    resp = api.create_inspection(c["id"], {"measured_decibel": 50, "measured_at": "2026-06-01T23:00:00Z"},
                                 code_officer_headers())
    data = validate_success(resp, 201)
    assert data["effective_limit_db"] == 45
    assert data["exceeds_limit"] is True


def test_inspection_without_policy_configured_rejected(api):
    """PRD §3.3: "The system locates the single `NoiseLimitPolicy` whose `zoning_type`
    equals the parcel's `zoning_type`; if no policy is configured for that zoning, the
    reading cannot be recorded and the request is rejected with `ERR_POLICY_NOT_CONFIGURED`."

    Design: Corner/errors/inspection_policy_not_configured
    """
    prop = fx.new_property(api, "MIXED", address="119 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="OTHER")
    fx.review(api, c["id"])
    resp = api.create_inspection(c["id"], {"measured_decibel": 70, "measured_at": "2026-06-01T12:00:00Z"},
                                 code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_CONFIGURED.value)


def test_complaint_invalid_noise_type_rejected(api):
    """PRD §2.5: "enum fields within their declared set (`ERR_INVALID_ENUM`) ... all at HTTP 400."
    PRD §3.2: noise_type is "drawn from `CONSTRUCTION`, `AMPLIFIED_MUSIC`, `MACHINERY`,
    `ANIMAL`, `VEHICLE`, or `OTHER`".

    Design: Corner/entities/complaint_invalid_enum_noise_type_rejected
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="101 Main St")
    resp = api.create_complaint(
        {"property_id": prop["id"], "reported_at": "2026-06-01T12:00:00Z", "noise_type": "JACKHAMMER"},
        code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_complaints_list_pagination(api):
    """PRD §2.3: "The `limit` parameter caps how many items are returned ... Every list
    response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object."

    Design: Corner/endpoints/complaints_list_pagination
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="117 Main St")
    for d in ("2026-06-01T12:00:00Z", "2026-06-02T12:00:00Z", "2026-06-03T12:00:00Z"):
        fx.file_complaint(api, prop["id"], d, noise_type="OTHER")
    resp = api.list_complaints(code_officer_headers(), params={"property_id": prop["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_substantiate_from_received_rejected(api):
    """PRD §3.2: "Substantiation and dismissal both require the complaint to be in
    `UNDER_REVIEW`; attempting either from any other state is rejected with
    `ERR_COMPLAINT_NOT_UNDER_REVIEW`."

    Design: Corner/state_machines/substantiate_from_received_not_under_review
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="108 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="ANIMAL")
    resp = api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_UNDER_REVIEW.value)


def test_substantiate_without_inspection_rejected(api):
    """PRD §3.4: "There must be at least one inspection on record for the complaint,
    else `ERR_NO_INSPECTION_ON_RECORD`."

    Design: Corner/validations/substantiate_no_inspection_on_record
    """
    fx.config_policy(api, "RESIDENTIAL")
    prop = fx.new_property(api, "RESIDENTIAL", address="112 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="ANIMAL")
    fx.review(api, c["id"])
    resp = api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_NO_INSPECTION_ON_RECORD.value)


def test_substantiate_when_reading_within_limit_rejected(api):
    """PRD §3.4: "The latest such inspection must have exceeded the limit — its
    `measured_decibel` strictly above its `effective_limit_db` — else `ERR_NOISE_WITHIN_LIMIT`."

    Design: Corner/validations/substantiate_noise_within_limit_rejected
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="113 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="MACHINERY")
    fx.review(api, c["id"])
    fx.inspect(api, c["id"], 60, "2026-06-01T12:00:00Z")
    resp = api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_NOISE_WITHIN_LIMIT.value)


def test_resident_cannot_review_complaint(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST `/complaints/{id}/review` is authorized for CodeOfficer only.

    Design: Corner/rbac/resident_cannot_review_complaint
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="120 Main St")
    resp = api.create_complaint(
        {"property_id": prop["id"], "reported_at": "2026-06-01T12:00:00Z", "noise_type": "OTHER"},
        resident_headers())
    c = validate_success(resp, 201)
    resp2 = api.review_complaint(c["id"], resident_headers())
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_acknowledge_closed_referral_rejected(api):
    """PRD §3.9: "A `CodeOfficer` acknowledges it (`OPEN → ACKNOWLEDGED`) and later closes
    it (`ACKNOWLEDGED → CLOSED`), or closes it directly from `OPEN` ... A transition that is
    not legal from the referral's current status is rejected with `ERR_REFERRAL_INVALID_STATE`."

    Design: Corner/state_machines/referral_close_then_acknowledge_invalid_state
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="107 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="OTHER")
    r = validate_success(api.create_referral({"complaint_id": c["id"], "agency": "POLICE"},
                                             code_officer_headers()), 201)
    validate_success(api.close_referral(r["id"], code_officer_headers()), 200)
    resp = api.acknowledge_referral(r["id"], code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_REFERRAL_INVALID_STATE.value)
