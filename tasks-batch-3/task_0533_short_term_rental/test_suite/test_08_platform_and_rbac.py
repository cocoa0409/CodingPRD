"""Platform listing reconciliation and role/ownership access control.

Covers corner queue B instances under the calculations (platform_match) and
rbac sections.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, MatchResult,
    make_host_headers, make_platform_headers, TEST_USERS,
    setup_active_permit, setup_issued_permit, create_platform,
    create_zone, create_host, create_property, create_draft_permit,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# Platform listing reconciliation
# --------------------------------------------------------------------------

def test_platform_match_matched_active_permit(api):
    """PRD §3.9: "If claimed_permit_number is non-empty and a permit with that id
    exists, that permit is taken as the resolved permit: if its property's
    street_address equals the report's street_address, then the result is
    MATCHED when the permit's status is ISSUED or ACTIVE."

    Design: Corner/calculations/platform_match_matched_active_permit
    """
    _, host, prop, permit = setup_active_permit(prop_overrides={"street_address": "PM-Match St"})
    platform = create_platform()
    data = validate_success(
        api.create_listing_report(
            {"platform_id": platform["id"], "claimed_permit_number": permit["id"],
             "street_address": "PM-Match St", "reported_nights": 4},
            make_platform_headers(platform["id"]),
        ),
        201,
    )
    assert data["match_result"] == MatchResult.MATCHED.value


def test_platform_match_address_mismatch(api):
    """PRD §3.9: "if its property's street_address equals the report's
    street_address ...; if the addresses do not agree, the result is
    ADDRESS_MISMATCH."

    Design: Corner/calculations/platform_match_address_mismatch
    """
    _, host, prop, permit = setup_issued_permit(prop_overrides={"street_address": "PM-Addr St"})
    platform = create_platform()
    data = validate_success(
        api.create_listing_report(
            {"platform_id": platform["id"], "claimed_permit_number": permit["id"],
             "street_address": "WRONG St", "reported_nights": 2},
            make_platform_headers(platform["id"]),
        ),
        201,
    )
    assert data["match_result"] == MatchResult.ADDRESS_MISMATCH.value


def test_platform_match_no_permit_by_address(api):
    """PRD §3.9: "If instead claimed_permit_number is blank or unknown or resolves
    to no permit, the system falls back to address resolution: it gathers the
    permits whose property's street_address equals the report's street_address;
    if there are none, the result is NO_PERMIT."
    PRD §3.9: "The matched_permit_id is ... null when the outcome was NO_PERMIT."

    Design: Corner/calculations/platform_match_no_permit_by_address
    """
    platform = create_platform()
    data = validate_success(
        api.create_listing_report(
            {"platform_id": platform["id"], "street_address": "PM-Nowhere St", "reported_nights": 6},
            make_platform_headers(platform["id"]),
        ),
        201,
    )
    assert data["match_result"] == MatchResult.NO_PERMIT.value
    assert data["matched_permit_id"] is None


# --------------------------------------------------------------------------
# RBAC / auth
# --------------------------------------------------------------------------

def test_host_cannot_issue_permit(api):
    """PRD §2.1: "When a request presents valid headers but the acting role is
    not permitted to perform the requested operation ... the request is rejected
    with ERR_UNAUTHORIZED (HTTP 403)."

    Issuing a permit is a CityRegistrar operation; a Host is not permitted.

    Design: Corner/rbac/host_cannot_issue_permit
    """
    zone = create_zone()
    host = create_host()
    prop = create_property(host["id"], zone["id"])
    permit = create_draft_permit(prop["id"], permit_type="WHOLE_HOME")
    validate_error(
        api.issue_permit(permit["id"], make_host_headers(host["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_non_owner_host_cannot_activate_permit(api):
    """PRD §2.1: "an entity-backed role attempts to act on a resource it does not
    own where ownership is required - the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §3.6: "only the host whose id matches the permit's owner may do so, and a
    mismatch is an ownership failure."

    Design: Corner/rbac/non_owner_host_cannot_activate_permit
    """
    _, host_a, prop, permit = setup_issued_permit()
    host_b = create_host()
    validate_error(
        api.activate_permit(permit["id"], make_host_headers(host_b["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
    the declared role names, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    validate_error(api.list_zones({}), ApiErrorId.ERR_UNAUTHENTICATED)
