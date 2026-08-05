"""Parcels, noise-limit policies, append-only records, and role gating (queue B corner)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_property, assert_inspection,
    create_property_payload, create_noise_policy_payload,
    system_admin_headers, permit_clerk_headers, code_officer_headers,
    NON_EXISTENT_UUID,
)
from test_helpers import fixtures as fx


def test_register_property_initializes_posture(api):
    """PRD §3.1: "On registration the parcel's derived posture is initialized:
    `substantiated_violation_count` is 0, `chronic_status` is `NONE`, and
    `abatement_status` is `NONE`."

    Design: Corner/entities/property_create_returns_all_fields
    """
    resp = api.create_property(create_property_payload(address="100 Main St", zoning_type="RESIDENTIAL"),
                               code_officer_headers())
    data = validate_success(resp, 201)
    assert_property(data)
    assert data["chronic_status"] == "NONE"
    assert data["abatement_status"] == "NONE"
    assert data["substantiated_violation_count"] == 0
    assert data["version"] == 1


def test_get_unknown_property_returns_not_found(api):
    """PRD §2.5: "every id in the path is resolved left to right ... else the
    corresponding not-found error at HTTP 404: `ERR_PROPERTY_NOT_FOUND`".

    Design: Corner/entities/property_get_not_found
    """
    resp = api.get_property(NON_EXISTENT_UUID, code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_register_property_missing_zoning_rejected(api):
    """PRD §3.1: "A `CodeOfficer` or a `SystemAdmin` registers a `Property` by
    supplying its street `address` and its `zoning_type`, which must be one of
    `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, or `MIXED`."
    PRD §2.5: "required fields present and correctly typed (`ERR_VALIDATION`)".

    Design: Corner/entities/property_missing_required_zoning_returns_validation
    """
    resp = api.create_property({"address": "no zoning"}, code_officer_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_duplicate_policy_for_zoning_rejected(api):
    """PRD §3.1: "At most one policy may exist per zoning; an attempt to configure a
    second policy for a zoning already covered is rejected with `ERR_DUPLICATE_POLICY`."

    Design: Corner/entities/policy_duplicate_zoning_rejected
    """
    validate_success(api.create_noise_policy(
        create_noise_policy_payload(zoning_type="COMMERCIAL", day_limit_db=65, night_limit_db=55),
        system_admin_headers()), 201)
    resp = api.create_noise_policy(
        create_noise_policy_payload(zoning_type="COMMERCIAL", day_limit_db=70, night_limit_db=60),
        system_admin_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY.value)


def test_inspection_is_append_only_no_version_field(api):
    """PRD §2.4: "Two resources are **append-only records** and therefore carry only
    `id` and `created_at` — they have neither `updated_at` nor `version` ... The first
    is `Inspection`, an immutable field reading."

    Design: Corner/entities/inspection_is_immutable_no_version_field
    """
    fx.config_policy(api, "RESIDENTIAL")
    prop = fx.new_property(api, "RESIDENTIAL", address="102 Main St")
    c = fx.file_complaint(api, prop["id"], "2026-06-01T12:00:00Z", noise_type="ANIMAL")
    fx.review(api, c["id"])
    resp = api.create_inspection(c["id"], {"measured_decibel": 70, "measured_at": "2026-06-01T12:00:00Z"},
                                 code_officer_headers())
    data = validate_success(resp, 201)
    assert_inspection(data)
    assert "version" not in data
    assert "updated_at" not in data


def test_permitclerk_cannot_register_property(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST `/properties` is authorized for CodeOfficer, SystemAdmin only.

    Design: Corner/rbac/permitclerk_cannot_create_property
    """
    resp = api.create_property(create_property_payload(address="121 Main St", zoning_type="COMMERCIAL"),
                               permit_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
