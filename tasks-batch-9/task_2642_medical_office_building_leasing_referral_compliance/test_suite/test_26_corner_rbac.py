"""Identity headers, cross-role refusals and tenant-portal ownership scoping.

Every test builds its own estate from scratch: the harness restarts the service
before each test, so the logical clock reads 2026-08-01T00:00:00Z and the
database is empty when a test begins.
"""
from test_helpers import (
    ApiErrorId,
    FACILITIES_ENGINEER,
    LEASING_AGENT,
    PORTFOLIO_ADMIN,
    PROPERTY_MANAGER,
    assert_parking_counters,
    assert_total_count,
    factories as fac,
    make_tenant_portal_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _headers_without(user_id=None, role=None):
    """A raw header dict carrying only the identity headers explicitly named."""
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


def test_each_role_is_refused_the_operations_another_role_owns(api):
    """Seven cross-role writes are all refused with ERR_UNAUTHORIZED and change nothing.

    PRD §2.1: "If the headers are well formed but the named role is not authorised for
    the addressed operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.8: "The acting role appears in the addressed endpoint's authorised-role list
    — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.8: "When it does, the response is determined by the **first** breach in the
    ladder below and no later check is evaluated."
    PRD §4: "Where the authorized-role column reads "All roles", every one of the six
    roles named in §2.1 may call the endpoint; where it names roles explicitly, any
    other authenticated role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/every_role_is_refused_another_roles_exclusive_operation
    """
    ctx = fx.drafted_lease(api)
    building_id = ctx["building"]["id"]
    suite_id = ctx["suite"]["id"]
    tenant_id = ctx["tenant"]["id"]
    lease_id = ctx["lease"]["id"]
    fx.file_attestation(api, lease_id, "SIGNED_LEASE")
    project = fx.open_ti_project(api, lease_id, suite_id)
    building_before = fx.read_building(api, building_id)
    building_version = building_before["version"]

    # A LeasingAgent cannot register reference data.
    validate_error(
        api.create_building(
            fac.create_building_payload(name="Rogue Tower", total_rentable_sf=50000),
            LEASING_AGENT),
        ApiErrorId.ERR_UNAUTHORIZED)

    # A PropertyManager cannot draft a deal.
    validate_error(
        api.create_lease(
            fac.create_lease_payload(building_id, suite_id, tenant_id,
                                     term_start="2027-01-01", term_end="2030-12-31"),
            PROPERTY_MANAGER),
        ApiErrorId.ERR_UNAUTHORIZED)

    # The role that owns the reference data cannot certify fair market value, and the
    # refusal is on the role rather than on the lease sitting in DRAFT.
    validate_error(
        api.certify_fmv(lease_id,
                        {"certification_note": "Portfolio admin trying to certify"},
                        PORTFOLIO_ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED)

    # Nor can it freeze the mix of the building it registered.
    validate_error(
        api.set_mix_freeze(building_id,
                           fac.mix_freeze_payload(True, "Portfolio admin trying to freeze"),
                           PORTFOLIO_ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED)

    # A LeasingAgent cannot hand over the keys.
    validate_error(
        api.commence_lease(lease_id,
                           {"commencement_note": "Leasing agent trying to hand over keys"},
                           LEASING_AGENT),
        ApiErrorId.ERR_UNAUTHORIZED)

    # The role that opened the project cannot sign off its own engineering.
    validate_error(
        api.review_ti_project(project["id"],
                              fac.ti_review_payload("UTILITY", "APPROVE"),
                              LEASING_AGENT),
        ApiErrorId.ERR_UNAUTHORIZED)

    # A LeasingAgent cannot draw on the parking pool.
    validate_error(
        api.create_parking_allocation(
            fac.create_parking_allocation_payload(building_version, building_id,
                                                  lease_id, "STAFF", 10),
            LEASING_AGENT),
        ApiErrorId.ERR_UNAUTHORIZED)

    # None of the seven refusals left a trace.
    lease_after = fx.read_lease(api, lease_id)
    assert lease_after["status"] == "DRAFT", (
        "a refused certification must not move the lease out of DRAFT, got {}".format(
            lease_after["status"]))
    building_after = fx.read_building(api, building_id)
    assert building_after["tenant_mix_posture"] != "FROZEN", (
        "a refused mix freeze must not freeze the building")
    assert_parking_counters(building_after, 0, 0,
                            building_after["total_parking_stalls"])
    assert building_after["version"] == building_version, (
        "a refused allocation must not advance the building version: expected {}, got {}"
        .format(building_version, building_after["version"]))
    project_after = fx.read_project(api, project["id"])
    assert project_after["utility_review_status"] != "APPROVED", (
        "a refused review must not approve the utility dimension, got {}".format(
            project_after["utility_review_status"]))

    leases, lease_meta = validate_paginated(
        api.list_leases(PROPERTY_MANAGER, {"building_id": building_id}))
    assert_total_count(lease_meta, 1)
    _allocations, alloc_meta = validate_paginated(
        api.list_parking_allocations(PROPERTY_MANAGER, {"building_id": building_id}))
    assert_total_count(alloc_meta, 0)

    # Every read in the surface is open to all six roles.
    validate_success(api.get_lease(lease_id, FACILITIES_ENGINEER), 200)
    validate_success(api.get_building(building_id, FACILITIES_ENGINEER), 200)
    validate_success(
        api.get_ti_project(project["id"], make_tenant_portal_headers(tenant_id)), 200)


def test_missing_or_undeclared_identity_headers_are_unauthenticated(api):
    """A suppressed header and an undeclared role string are both 401, never 403 or 400.

    PRD §2.1: "Every request to every endpoint, including reads, must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role
    the principal is acting under."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six
    declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The six roles are `PortfolioAdmin`, `LeasingAgent`, `ComplianceOfficer`,
    `PropertyManager`, `FacilitiesEngineer` and `TenantPortalUser`, spelled exactly as
    shown."
    PRD §2.8: "Both `X-User-ID` and `X-User-Role` are present and `X-User-Role` names
    one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to
    every endpoint."

    Design: Corner/rbac/absent_or_unknown_identity_headers_are_refused_before_authorization
    """
    building = fx.register_building(api)
    building_id = building["id"]
    fx.register_suite(api, building_id)

    # A read with a role but no acting principal.
    validate_error(
        api.get("/buildings/{}".format(building_id),
                headers=_headers_without(role="PortfolioAdmin")),
        ApiErrorId.ERR_UNAUTHENTICATED)

    # A read with a principal but no role.
    validate_error(
        api.get("/buildings/{}".format(building_id),
                headers=_headers_without(user_id="admin-001")),
        ApiErrorId.ERR_UNAUTHENTICATED)

    # An undeclared role string is an authentication failure, not an authorization one,
    # even though the body is otherwise valid for the single role that owns the endpoint.
    undeclared = _headers_without(user_id="admin-001", role="BuildingEngineer")
    validate_error(
        api.post("/buildings/{}/suites".format(building_id),
                 fac.create_suite_payload(suite_number="999", floor=9, rentable_sf=1000,
                                          power_amps_available=100),
                 headers=undeclared),
        ApiErrorId.ERR_UNAUTHENTICATED)

    # The same undeclared role with an empty body is still an authentication failure and
    # never a payload complaint.
    validate_error(
        api.post("/buildings/{}/suites".format(building_id), {}, headers=undeclared),
        ApiErrorId.ERR_UNAUTHENTICATED)

    # None of the four refusals created suite 999.
    suites, meta = validate_paginated(api.list_building_suites(building_id, PORTFOLIO_ADMIN))
    assert_total_count(meta, 1)
    assert [row["suite_number"] for row in suites] == ["210"], (
        "an unauthenticated request must not create a suite, got {}".format(
            [row["suite_number"] for row in suites]))


def test_tenant_portal_user_is_scoped_to_its_own_tenants_resources(api):
    """A portal user reads and books its own lease and is refused its neighbour's with 403.

    PRD §2.1: "When `X-User-Role` is `TenantPortalUser`, by contrast, `X-User-ID` is the
    `id` of the acting `Tenant`; ownership checks on any resource that references a
    tenant compare the resource's tenant reference to `X-User-ID`, resolving through the
    lease where the addressed resource is a lease, a tenant-improvement project, a line
    item, an appraisal, an invoice, a booking or a parking allocation."
    PRD §2.1: "A `TenantPortalUser` reaching a resource that resolves to a different
    tenant is refused with `ERR_UNAUTHORIZED` rather than told the resource does not
    exist, so the portal cannot be used to enumerate other practices' deals."
    PRD §2.8: "When the acting role is `TenantPortalUser`, `X-User-ID` equals the tenant
    that owns the addressed resource, resolved through the lease where the resource is a
    lease, a project, a line item, an appraisal, an invoice, a booking or an allocation
    — otherwise `ERR_UNAUTHORIZED` (403)."
    PRD §3.9: "Cancellation is admissible only while `window_start` is still later than
    the clock — a booking already under way cannot be cancelled — and it moves the
    booking `BOOKED → CANCELLED` with `cancellation_source` recorded as `REQUESTED` and
    `version` advanced."

    Design: Corner/rbac/tenant_portal_user_cannot_reach_another_tenants_resources
    """
    ctx = fx.active_lease(api)
    building_id = ctx["building"]["id"]
    tenant_a = ctx["tenant"]
    lease_a_id = ctx["lease"]["id"]

    neighbour = fx.add_lease_on_new_suite(api, ctx, tenant_overrides={
        "legal_name": "Cedar Ridge Eye Associates PC",
        "primary_specialty": "OPHTHALMOLOGY",
    })
    tenant_b = neighbour["tenant"]
    lease_b_id = neighbour["lease"]["id"]
    fx.drive_to_active(api, neighbour["lease"], tenant_b)

    space = fx.register_shared_space(api, building_id)
    space_id = space["id"]
    booking_b = fx.book(api, space_id, lease_b_id,
                        "2026-09-15T09:00:00Z", "2026-09-15T10:00:00Z", 2)

    portal_a = make_tenant_portal_headers(tenant_a["id"])

    # Its own lease reads back.
    own_lease = validate_success(api.get_lease(lease_a_id, portal_a), 200)
    assert own_lease["tenant_id"] == tenant_a["id"], (
        "the portal user's own lease must resolve to its own tenant")

    # The neighbour's lease and the neighbour's tenant record are refused, not hidden
    # behind a not-found.
    validate_error(api.get_lease(lease_b_id, portal_a), ApiErrorId.ERR_UNAUTHORIZED)
    validate_error(api.get_tenant(tenant_b["id"], portal_a), ApiErrorId.ERR_UNAUTHORIZED)

    # It may book against its own lease.
    own_booking = validate_success(
        api.create_booking(
            fac.create_booking_payload(space_id, lease_a_id,
                                       "2026-09-16T09:00:00Z", "2026-09-16T10:00:00Z", 2),
            portal_a),
        201)
    assert own_booking["status"] == "BOOKED", (
        "a new booking begins in BOOKED, got {}".format(own_booking["status"]))

    # It may not book against the neighbour's lease, and nothing is created.
    validate_error(
        api.create_booking(
            fac.create_booking_payload(space_id, lease_b_id,
                                       "2026-09-17T09:00:00Z", "2026-09-17T10:00:00Z", 2),
            portal_a),
        ApiErrorId.ERR_UNAUTHORIZED)

    # It may not cancel the neighbour's booking, which stays BOOKED.
    validate_error(api.cancel_booking(booking_b["id"], fac.cancel_booking_payload(), portal_a),
                   ApiErrorId.ERR_UNAUTHORIZED)
    neighbour_booking = validate_success(api.get_booking(booking_b["id"], LEASING_AGENT), 200)
    assert neighbour_booking["status"] == "BOOKED", (
        "a refused cancellation must leave the neighbour's booking BOOKED, got {}".format(
            neighbour_booking["status"]))

    # It may cancel its own.
    cancelled = validate_success(
        api.cancel_booking(own_booking["id"], fac.cancel_booking_payload(), portal_a), 200)
    assert cancelled["status"] == "CANCELLED", (
        "the portal user's own cancellation moves the booking to CANCELLED, got {}".format(
            cancelled["status"]))
    assert cancelled["cancellation_source"] == "REQUESTED", (
        "a tenant's own cancellation records cancellation_source REQUESTED, got {}".format(
            cancelled["cancellation_source"]))

    # The refused booking left no row behind: only the neighbour's booking is still BOOKED.
    rows, meta = validate_paginated(
        api.list_bookings(LEASING_AGENT, {"shared_space_id": space_id, "status": "BOOKED"}))
    assert_total_count(meta, 1)
    assert rows[0]["id"] == booking_b["id"], (
        "the only surviving BOOKED row must be the neighbour's own booking")
