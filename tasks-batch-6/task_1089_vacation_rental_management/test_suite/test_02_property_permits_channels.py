"""Property lifecycle, permits, and cross-entity permit/property effects."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_permit_payload, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def test_offboarded_property_cannot_be_listed(api):
    """PRD §3.2: "Offboarding may be invoked from `ONBOARDING`, `LISTED`, or `UNLISTED` and
    drives the property to the terminal `OFFBOARDED` state".
    PRD §2.6: "the target resource is in a legal state for the requested transition, else
    the specific state error for that operation (see below), falling back to the generic
    `ERR_INVALID_STATE` (409) for any transition attempted from a state that does not permit it."

    Design: Corner/state_machines/offboarded_property_list_returns_invalid_state
    """
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    get_success_data(api.offboard_property(prop["id"], PM))
    resp = api.list_property(prop["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api.get_property(prop["id"], PM))["status"] == "OFFBOARDED"


def test_permit_revoke_unlists_listed_property(api):
    """PRD §3.2: "Revoking an `ACTIVE` permit moves it to `REVOKED`, and if its property was
    `LISTED`, that property is automatically driven back to `UNLISTED`."

    Design: Corner/state_machines/permit_revoke_unlists_property
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    resp = api.revoke_permit(listed["permit"]["id"], PM)
    permit = validate_success(resp, 200)
    assert permit["status"] == "REVOKED"
    assert get_success_data(api.get_property(listed["property"]["id"], PM))["status"] == "UNLISTED"


def test_list_property_without_active_permit_rejected(api):
    """PRD §3.2: "This requires the property to have a permit in `ACTIVE` status — absent
    one, the request fails with `ERR_PERMIT_NOT_ACTIVE`".

    Design: Corner/validations/list_property_without_active_permit_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    # A PENDING (never activated) permit exists.
    get_success_data(api.create_permit(create_permit_payload(prop["id"]), PM))
    resp = api.list_property(prop["id"], PM)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value)


def test_list_property_with_expired_permit_rejected(api):
    """PRD §3.2: "and additionally requires the logical clock to be at or before that
    permit's `expires_on`, else `ERR_PERMIT_EXPIRED`."

    Design: Corner/validations/list_property_with_expired_permit_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    fixtures.create_active_permit(api, prop["id"], occupancy_tax_pct=10, expires_on="2026-06-15T00:00:00Z")
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    resp = api.list_property(prop["id"], PM)
    validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED.value)
