"""Author registration and ORCID binding (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    api_client,
    assert_author,
    create_author_payload,
    make_author_headers,
    orcid_verified_event_payload,
    register_author,
    validate_error,
    validate_success,
)


def test_register_author_minimal_required_fields(api, platform_admin_headers):
    """PRD §3.1: "Authors enter the system through registration, where
    full_name, email, and institution are required and orcid_id and
    recent_collaborator_ids are optional."
    """
    payload = create_author_payload()
    payload.pop("orcid_id", None)
    res = api.create_author(payload, platform_admin_headers)
    author = validate_success(res, expected_status=201)
    assert_author(author)
    assert author["full_name"] == payload["full_name"]
    assert author["email"] == payload["email"]
    assert author["institution"] == payload["institution"]


def test_register_author_initial_orcid_verified_false(api, platform_admin_headers):
    """PRD §3.1: "A freshly registered author always has orcid_verified
    set to false."
    """
    res = api.create_author(create_author_payload(), platform_admin_headers)
    author = validate_success(res, expected_status=201)
    assert author["orcid_verified"] is False


@pytest.mark.parametrize("missing", ["full_name", "email", "institution"])
def test_register_author_missing_required_field(api, platform_admin_headers, missing):
    """PRD §3.1: "full_name, email, and institution are required ..."
    Missing required field returns ERR_VALIDATION (HTTP 400 — generic
    malformed-input per PRD §5 catalogue).
    """
    payload = create_author_payload()
    payload.pop(missing, None)
    res = api.create_author(payload, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


@pytest.mark.parametrize("bad_orcid", [
    "1234-5678",                  # too short
    "0000-0000-0000-000",         # short final group
    "AAAA-BBBB-CCCC-DDDD",        # non-digits
    "0000_0000_0000_0000",        # wrong separator
])
def test_register_author_invalid_orcid_format_rejected(
        api, platform_admin_headers, bad_orcid):
    """PRD §3.1: "the orcid_id, when supplied, must match the canonical
    0000-0000-0000-0000 shape (four groups of four digits separated by
    hyphens) ..."
    """
    payload = create_author_payload(orcid_id=bad_orcid)
    res = api.create_author(payload, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_register_two_authors_same_email_rejected(api, platform_admin_headers):
    """PRD §3.1: "The email of an Author is globally unique among Author
    rows ..."
    """
    payload = create_author_payload()
    res1 = api.create_author(payload, platform_admin_headers)
    validate_success(res1, expected_status=201)
    res2 = api.create_author(payload, platform_admin_headers)
    validate_error(res2, ApiErrorId.ERR_VALIDATION.value)


def test_register_two_authors_same_orcid_rejected(api, platform_admin_headers):
    """PRD §3.1: "the orcid_id, when supplied, ... must be unique among
    rows that supply one."
    """
    orcid = TEST_DEFAULTS["VALID_ORCID"]
    p1 = create_author_payload(orcid_id=orcid)
    p2 = create_author_payload(orcid_id=orcid)
    res1 = api.create_author(p1, platform_admin_headers)
    validate_success(res1, expected_status=201)
    res2 = api.create_author(p2, platform_admin_headers)
    validate_error(res2, ApiErrorId.ERR_VALIDATION.value)


def test_orcid_verified_event_flips_flag(api, platform_admin_headers):
    """PRD §3.1: "the platform receives an event carrying the author_id
    and orcid_id, and when the supplied orcid_id matches the stored value
    the system flips orcid_verified to true."
    """
    orcid = "0000-0001-0001-0001"
    res = api.create_author(create_author_payload(orcid_id=orcid),
                            platform_admin_headers)
    author = validate_success(res, expected_status=201)
    assert author["orcid_verified"] is False

    ev_res = api.orcid_verified_event(
        orcid_verified_event_payload(author_id=author["id"], orcid_id=orcid),
        platform_admin_headers,
    )
    updated = validate_success(ev_res, expected_status=200)
    assert updated["orcid_verified"] is True


def test_orcid_verified_event_mismatched_orcid_does_not_flip(
        api, platform_admin_headers):
    """PRD §3.1: "when the supplied orcid_id matches the stored value the
    system flips orcid_verified to true." A mismatched orcid_id therefore
    must not flip the flag.
    """
    orcid = "0000-0001-0001-0002"
    res = api.create_author(create_author_payload(orcid_id=orcid),
                            platform_admin_headers)
    author = validate_success(res, expected_status=201)

    ev_res = api.orcid_verified_event(
        orcid_verified_event_payload(
            author_id=author["id"], orcid_id="0000-9999-9999-9999",
        ),
        platform_admin_headers,
    )
    # Implementation may return 200 with the unchanged author OR 422 —
    # either is PRD-faithful as long as the flag does not flip. Re-fetch
    # to verify.
    re_res = api.get_author(author["id"], platform_admin_headers)
    refreshed = validate_success(re_res, expected_status=200)
    assert refreshed["orcid_verified"] is False
