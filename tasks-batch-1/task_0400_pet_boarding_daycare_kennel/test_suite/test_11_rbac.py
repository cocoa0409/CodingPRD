"""Role-based access control corners: forbidden ops, ownership, missing auth.

Translates corner (B) rbac instances. The Owner role is entity-backed, so
ownership-gated Owner calls thread the actual Owner.id via make_owner_headers().
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_error,
    create_facility, create_owner, create_pet,
    create_run_payload, create_reservation_payload,
    make_owner_headers,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_owner_cannot_create_run(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN`."
    PRD §4 (endpoint table): "POST `/facilities/{id}/runs` | Create a Run | FacilityManager".

    An Owner calling the FacilityManager-only run-create endpoint -> ERR_FORBIDDEN.

    Design: Corner/rbac/owner_cannot_create_run
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    res = api_client.create_run(
        facility["id"], create_run_payload(label="Owner-Run", kind="DAYCARE_PEN",
                                           size_class="LARGE", daycare_capacity=5),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_owner_cannot_cancel_other_owners_reservation(api):
    """PRD §2.1: "An `Owner` who attempts to read or mutate a pet, reservation, or package
    whose `owner_id` is not their own `X-User-ID` is rejected with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.8: "when the caller is an `Owner` they must own the reservation or the cancel is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Owner B cancelling Owner A's reservation -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/owner_cannot_cancel_other_owners_reservation
    """
    facility = create_facility(deposit_policy="NONE")
    ownA = create_owner(facility["id"])
    ownB = create_owner(facility["id"])
    petA = create_pet(ownA["id"], weight_kg=6)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(petA["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR))
    out = api_client.cancel_reservation(res["id"], make_owner_headers(ownB["id"]))
    validate_error(out, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the operational capacity under which the
    request is made. A request missing either header, or carrying a malformed one, is
    rejected with `ERR_MISSING_AUTH`."

    The same reachable GET, issued with no auth headers, is rejected ERR_MISSING_AUTH.

    Design: Corner/rbac/missing_auth_header_rejected
    """
    facility = create_facility()
    out = api.get_facility(facility["id"], headers={})
    validate_error(out, "ERR_MISSING_AUTH", expected_status=401)
