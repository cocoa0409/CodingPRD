"""Role-based access control (authentication, authorization, entity-backed ownership)
and reverse-reachability listing.

Queue B (Corner): rbac, endpoints (list reports by site).
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    make_crew_lead_headers, make_property_owner_headers,
    setup_triaged_report, setup_completed,
    register_owner, register_site, register_crew,
    file_report, triage,
    create_site_payload, create_report_payload, create_work_order_payload, create_photo_payload,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
RESIDENT = TEST_USERS["resident_headers"]


# --------------------------------------------------------------------------
# rbac / resident_cannot_dispatch_returns_unauthorized
# --------------------------------------------------------------------------
def test_resident_cannot_dispatch_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/resident_cannot_dispatch_returns_unauthorized
    """
    scn = setup_triaged_report(api, ownership_type="PUBLIC", with_material=False)
    resp = api.create_work_order(create_work_order_payload(
        scn["report_id"], scn["crew_id"], estimated_labor_hours=2.0), RESIDENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# --------------------------------------------------------------------------
# rbac / crewlead_not_owner_cannot_start_returns_ownership_mismatch
# --------------------------------------------------------------------------
def test_crewlead_not_owner_cannot_start_returns_ownership_mismatch(api):
    """PRD §2.1: "a crew lead may start, complete, or attach photos to a work order only when that
    work order's `crew_id` equals their `X-User-ID`."
    PRD §2.1: "When an entity-backed role acts on a resource it does not own, the request is rejected
    with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/crewlead_not_owner_cannot_start_returns_ownership_mismatch
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew_a = register_crew(api, name="Crew A")
    crew_b = register_crew(api, name="Crew B")
    rep = file_report(api, site["id"], severity="HIGH", surface_type="WALL")
    triage(api, rep["id"])
    wo = validate_success(api.create_work_order(create_work_order_payload(
        rep["id"], crew_a["id"], estimated_labor_hours=2.0), COORD), 201)
    validate_success(api.upload_photo(wo["id"], create_photo_payload("BEFORE", "http://p/b.jpg"),
                                      make_crew_lead_headers(crew_a["id"])), 201)
    # Crew B's lead attempts to start Crew A's work order.
    resp = api.start_work_order(wo["id"], make_crew_lead_headers(crew_b["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


# --------------------------------------------------------------------------
# rbac / propertyowner_not_owner_cannot_pay_returns_ownership_mismatch
# --------------------------------------------------------------------------
def test_propertyowner_not_owner_cannot_pay_returns_ownership_mismatch(api):
    """PRD §2.1: "an owner may consent to a notice, dispute a notice, or pay a cost recovery only when
    the underlying site's `property_owner_id` equals their `X-User-ID`."
    PRD §2.1: "When an entity-backed role acts on a resource it does not own, the request is rejected
    with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/propertyowner_not_owner_cannot_pay_returns_ownership_mismatch
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0)
    other_owner = register_owner(api, name="Owner B", contact_email="b@x.com")
    resp = api.pay_cost_recovery(scn["cost_recovery_id"], make_property_owner_headers(other_owner["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


# --------------------------------------------------------------------------
# rbac / missing_x_user_header_returns_unauthenticated
# --------------------------------------------------------------------------
def test_missing_x_user_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if
    `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_x_user_header_returns_unauthenticated
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    resp = api.get_site(site["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# --------------------------------------------------------------------------
# endpoints / list_reports_by_site_returns_children
# --------------------------------------------------------------------------
def test_list_reports_by_site_returns_children(api):
    """PRD §2.3: "reports by `site_id`, `status`, and `severity` ... These filters are the system's
    reverse-reachability mechanism — the way a caller walks from a parent entity to the children that
    reference it."

    Design: Corner/endpoints/list_reports_by_site_returns_children
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    validate_success(api.create_report(
        create_report_payload(site["id"], severity="LOW", surface_type="WALL"), CLERK), 201)
    validate_success(api.create_report(
        create_report_payload(site["id"], severity="MEDIUM", surface_type="FENCE",
                              reported_via="WEB"), CLERK), 201)
    data, meta = validate_paginated(api.list_reports(COORD, params={"site_id": site["id"]}))
    assert meta["total_count"] == 2
