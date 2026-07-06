"""Petition CRUD defaults, input validation, not-found routing, and access control.

Translates queue-B corner instances from sections entities / validations / rbac.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_user_payload, create_petition_payload,
    edit_petition_payload,
    register_member, create_draft_petition,
    TEST_USERS, NO_AUTH_HEADERS, make_member_headers,
)

MODERATOR = TEST_USERS["moderator_headers"]
GUEST = TEST_USERS["guest_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_create_petition_returns_201_with_default_status_and_counters(api):
    """PRD §3.1: "On creation the petition's `author_user_id` is set to the acting
    `X-User-ID`, its `status` begins at `DRAFT`, and its `moderation_status` begins at `PENDING`."

    Design: Corner/entities/create_petition_returns_201_defaults
    """
    author = register_member()
    resp = api.create_petition(
        create_petition_payload(title="New", category="OTHER", goal=50),
        make_member_headers(author["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["moderation_status"] == "PENDING"
    assert data["author_user_id"] == author["id"]
    assert data["verified_signature_count"] == 0
    assert data["pending_signature_count"] == 0


def test_create_petition_missing_goal_rejected(api):
    """PRD §2.5: "well-formedness of the request body — required fields present, enums
    within their allowed set, integers within their declared bounds, and every window_end
    strictly greater than its window_start (ERR_VALIDATION, 422)."

    Design: Corner/entities/create_petition_missing_goal_returns_validation
    """
    author = register_member()
    payload = create_petition_payload()
    del payload["goal"]
    resp = api.create_petition(payload, make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_create_petition_bad_category_enum_rejected(api):
    """PRD §3.1: "The category must be one of ENVIRONMENT, POLITICS, HEALTH, EDUCATION,
    or OTHER, and the goal — the target number of verified signatures — must be at least 1."

    Design: Corner/entities/create_petition_bad_category_enum_returns_validation
    """
    author = register_member()
    resp = api.create_petition(
        create_petition_payload(category="SPORTS", goal=5),
        make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_get_unknown_petition_returns_not_found(api):
    """PRD §2.5: "a missing resource yields the entity-specific not-found error —
    ERR_USER_NOT_FOUND, ERR_PETITION_NOT_FOUND, ... each with HTTP 404."

    Design: Corner/entities/get_petition_not_found
    """
    resp = api.get_petition("00000000-0000-4000-8000-000000000000", GUEST)
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_FOUND.value, expected_status=404)


def test_get_unknown_signature_returns_not_found(api):
    """PRD §2.5: "a missing resource yields the entity-specific not-found error —
    ERR_USER_NOT_FOUND, ERR_PETITION_NOT_FOUND, ERR_TARGET_NOT_FOUND,
    ERR_REPRESENTATIVE_NOT_FOUND, ERR_SIGNATURE_NOT_FOUND, ... each with HTTP 404."

    Design: Corner/entities/get_signature_not_found
    """
    resp = api.get_signature("00000000-0000-4000-8000-000000000001", GUEST)
    validate_error(resp, ApiErrorId.ERR_SIGNATURE_NOT_FOUND.value, expected_status=404)


def test_get_unknown_donation_returns_not_found(api):
    """PRD §2.5: "a missing resource yields the entity-specific not-found error — ...
    ERR_DONATION_NOT_FOUND, ... each with HTTP 404."

    Design: Corner/entities/get_donation_not_found
    """
    resp = api.get_donation("00000000-0000-4000-8000-000000000002", GUEST)
    validate_error(resp, ApiErrorId.ERR_DONATION_NOT_FOUND.value, expected_status=404)


def test_get_unknown_target_returns_not_found(api):
    """PRD §2.5: "a missing resource yields the entity-specific not-found error — ...
    ERR_TARGET_NOT_FOUND, ... each with HTTP 404."

    Design: Corner/entities/get_target_not_found
    """
    resp = api.get_target("00000000-0000-4000-8000-000000000003", GUEST)
    validate_error(resp, ApiErrorId.ERR_TARGET_NOT_FOUND.value, expected_status=404)


def test_get_unknown_representative_returns_not_found(api):
    """PRD §2.5: "a missing resource yields the entity-specific not-found error — ...
    ERR_REPRESENTATIVE_NOT_FOUND, ... each with HTTP 404."

    Design: Corner/entities/get_representative_not_found
    """
    resp = api.get_representative("00000000-0000-4000-8000-000000000004", GUEST)
    validate_error(resp, ApiErrorId.ERR_REPRESENTATIVE_NOT_FOUND.value, expected_status=404)


@pytest.mark.parametrize("getter,error_id", [
    (lambda a: a.get_campaign("00000000-0000-4000-8000-000000000005", GUEST),
     ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value),
    (lambda a: a.get_comment("00000000-0000-4000-8000-000000000006", GUEST),
     ApiErrorId.ERR_COMMENT_NOT_FOUND.value),
    (lambda a: a.get_promotion("00000000-0000-4000-8000-000000000007", GUEST),
     ApiErrorId.ERR_PROMOTION_NOT_FOUND.value),
    (lambda a: a.get_delivery_meeting("00000000-0000-4000-8000-000000000008", GUEST),
     ApiErrorId.ERR_MEETING_NOT_FOUND.value),
    (lambda a: a.get_user("00000000-0000-4000-8000-000000000009", GUEST),
     ApiErrorId.ERR_USER_NOT_FOUND.value),
])
def test_get_unknown_resource_returns_entity_specific_not_found(api, getter, error_id):
    """PRD §2.5: "a missing resource yields the entity-specific not-found error —
    ERR_USER_NOT_FOUND, ERR_PETITION_NOT_FOUND, ERR_TARGET_NOT_FOUND,
    ERR_REPRESENTATIVE_NOT_FOUND, ERR_SIGNATURE_NOT_FOUND, ERR_COMMENT_NOT_FOUND,
    ERR_CAMPAIGN_NOT_FOUND, ERR_DONATION_NOT_FOUND, ERR_PROMOTION_NOT_FOUND, or
    ERR_MEETING_NOT_FOUND — each with HTTP 404."

    Design: Corner/entities/get_campaign_and_comment_and_promotion_and_meeting_and_user_not_found
    """
    validate_error(getter(api), error_id, expected_status=404)


def test_moderator_cannot_create_petition(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/validations/authz_moderator_cannot_create_petition
    """
    resp = api.create_petition(
        create_petition_payload(title="X", category="OTHER", goal=5), MODERATOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_missing_role_header_is_unauthenticated(api):
    """PRD §2.1: "When either header is missing, or X-User-Role is not one of the declared
    role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_role_header
    """
    resp = api.create_petition(
        create_petition_payload(title="X", category="OTHER", goal=5), NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_member_cannot_edit_others_petition(api):
    """PRD §2.1: "A Member acting on a resource they do not own is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/validations/member_cannot_edit_others_petition_ownership
    """
    author = register_member()
    other = register_member()
    pet = create_draft_petition(author["id"])
    resp = api.edit_petition(
        pet["id"], edit_petition_payload(pet["version"], title="Hacked"),
        make_member_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)


def test_patch_with_stale_version_rejected(api):
    """PRD §2.6: "Editing a petition's fields is guarded the same way: that request also
    carries expected_petition_version, and a mismatch with the petition's current version
    is likewise rejected with ERR_STALE_PETITION_VERSION (HTTP 412)."

    Design: Corner/validations/patch_stale_petition_version_occ_conflict
    """
    author = register_member()
    pet = create_draft_petition(author["id"])
    original_version = pet["version"]
    # First edit advances the version.
    get_success_data(api.edit_petition(
        pet["id"], edit_petition_payload(original_version, title="Edit1"),
        make_member_headers(author["id"])))
    # Second edit re-uses the now-stale original version.
    resp = api.edit_petition(
        pet["id"], edit_petition_payload(original_version, title="Edit2"),
        make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_PETITION_VERSION.value, expected_status=412)


def test_member_cannot_revoke_signature(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_revoke_signature
    """
    from test_helpers import publish_petition, register_and_sign
    ctx = publish_petition(goal=10)
    sig = register_and_sign(ctx["petition_id"])
    resp = api.revoke_signature(sig["id"], {}, make_member_headers(sig["_signer_id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_member_cannot_settle_donation(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_settle_donation
    """
    from test_helpers import setup_campaign, donate
    ctx = setup_campaign()
    donor = register_member()
    don = donate(ctx["campaign_id"], donor["id"], 3000)
    resp = api.transition_donation(
        don["id"], {"to_status": "SETTLED"}, make_member_headers(donor["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
