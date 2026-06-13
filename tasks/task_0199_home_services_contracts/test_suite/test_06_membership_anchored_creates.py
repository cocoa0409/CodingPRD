"""Membership-anchored creates: the active-membership precondition, optimistic
concurrency on visit/offer creates, site-owner referential check, and the
refrigerant/part visit-state guard.

Covers Difficulty queue: cross_entity_state_dependency (visit-create requires ACTIVE);
plus corner cross_cutting_complexity_layers (OCC) and validations.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    TEST_USERS,
    make_technician_headers,
    create_service_visit_payload,
    create_membership_payload,
    create_renewal_offer_payload,
    create_refrigerant_log_payload,
    ApiErrorId,
    create_and_activate_membership,
    create_plan,
    create_customer,
    create_site,
    create_membership,
    setup_active_membership_with_equipment_and_tech,
    book_visit,
    dispatch_visit,
)

ADMIN = TEST_USERS["contract_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty / cross_entity_state_dependency — visit requires ACTIVE membership
# ===========================================================================
def test_visit_create_against_pending_membership_rejected(api):
    """PRD §3.5: "The referenced membership must be in `ACTIVE` status at booking time, or
    the request is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_create_requires_membership_active_membership_pair
    """
    from test_helpers import set_clock
    set_clock()
    plan = create_plan()
    customer = create_customer()
    site = create_site(customer["id"])
    membership = create_membership(customer["id"], site["id"], plan["id"])  # PENDING_ACTIVATION, version 1
    assert membership["status"] == "PENDING_ACTIVATION"
    payload = create_service_visit_payload(membership["id"], membership["version"], visit_kind="SEASONAL")
    validate_error(api.create_service_visit(payload, DISPATCHER), ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_visit_create_against_active_membership_succeeds(api):
    """PRD §3.5: "On a successful create the visit's `site_id` is copied from the
    membership's site, the visit opens in `SCHEDULED` status, and for priority visits the
    service-level evaluation described in Section 3.6 runs immediately."

    Design: Difficulty/cross_entity_state_dependency/visit_create_requires_membership_active_membership_pair
    """
    ctx = create_and_activate_membership()
    payload = create_service_visit_payload(ctx["membership"]["id"], ctx["membership"]["version"], visit_kind="SEASONAL")
    visit = validate_success(api.create_service_visit(payload, DISPATCHER), 201)
    assert visit["status"] == "SCHEDULED", f"visit against ACTIVE membership opens SCHEDULED, got {visit['status']}"
    assert visit["site_id"] == ctx["site"]["id"], "site_id copied from the membership's site"


# ===========================================================================
# Corner / cross_cutting_complexity_layers — OCC stale version
# ===========================================================================
def test_visit_create_with_stale_membership_version_rejected(api):
    """PRD §2.8: "Booking a service visit must carry `expected_membership_version`, a
    non-optional field that holds the `version` of the target `Membership` the client last
    observed. If that value does not match the membership's current `version` at the time
    the create is processed, the request is rejected with `ERR_STALE_VERSION` and HTTP
    status 412."

    Design: Corner/cross_cutting_complexity_layers/visit_create_stale_membership_version_returns_412
    """
    ctx = create_and_activate_membership()
    stale_version = ctx["membership"]["version"]
    # suspend + reinstate each bump the version, so stale_version is now behind.
    validate_success(api.suspend_membership(ctx["membership"]["id"], ADMIN), 200)
    validate_success(api.reinstate_membership(ctx["membership"]["id"], ADMIN), 200)
    payload = create_service_visit_payload(ctx["membership"]["id"], stale_version, visit_kind="SEASONAL")
    validate_error(api.create_service_visit(payload, DISPATCHER), ApiErrorId.ERR_STALE_VERSION.value)


def test_visit_create_with_current_membership_version_succeeds(api):
    """PRD §2.8: "If that value does not match the membership's current `version` at the
    time the create is processed, the request is rejected with `ERR_STALE_VERSION` and
    HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/visit_create_correct_membership_version_succeeds
    """
    ctx = create_and_activate_membership()
    payload = create_service_visit_payload(ctx["membership"]["id"], ctx["membership"]["version"], visit_kind="SEASONAL")
    visit = validate_success(api.create_service_visit(payload, DISPATCHER), 201)
    assert visit["status"] == "SCHEDULED", "current-version create is the OCC happy path"


def test_renewal_offer_create_with_stale_membership_version_rejected(api):
    """PRD §2.8: "Creating a renewal offer likewise must carry `expected_membership_version`
    holding the client's last observed `version` of the target `Membership`. If it does
    not match the membership's current `version`, the create is rejected with
    `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/renewal_offer_create_stale_membership_version_returns_412
    """
    ctx = create_and_activate_membership()
    stale_version = ctx["membership"]["version"] - 1  # deliberately one behind
    payload = create_renewal_offer_payload(ctx["plan"]["id"], stale_version)
    validate_error(api.create_renewal_offer(ctx["membership"]["id"], payload, ADMIN),
                   ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Corner / validations — site owner mismatch on membership create
# ===========================================================================
def test_membership_create_site_owner_mismatch_rejected(api):
    """PRD §3.2: "A new membership is only well-formed when the referenced site actually
    belongs to the named customer: if the site's `customer_id` does not equal the
    membership's `customer_id`, the create is rejected with `ERR_SITE_OWNER_MISMATCH`."

    Design: Corner/validations/membership_create_site_owner_mismatch
    """
    plan = create_plan()
    cust_a = create_customer(email="owner-a@example.com")
    cust_b = create_customer(email="owner-b@example.com")
    site_a = create_site(cust_a["id"])
    # Membership cites customer B but a site owned by A.
    payload = create_membership_payload(cust_b["id"], site_a["id"], plan["id"])
    validate_error(api.create_membership(payload, ADMIN), ApiErrorId.ERR_SITE_OWNER_MISMATCH.value)


# ===========================================================================
# Corner / validations — refrigerant post against a non-ON_SITE (EN_ROUTE) visit
# ===========================================================================
def test_refrigerant_post_against_en_route_visit_rejected(api):
    """PRD §3.7: "The visit must be `ON_SITE` when the log is posted, or the post is
    rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (the same code guards both
    visit-create-against-inactive-membership and refrigerant/part posting against a
    non-`ON_SITE` visit)."

    Design: Corner/validations/refrigerant_post_on_non_onsite_visit_membership_not_active_path
    """
    ctx = setup_active_membership_with_equipment_and_tech(equipment_overrides={"refrigerant_type": "R410A"})
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    tech_id = ctx["technician"]["id"]
    dispatch_visit(visit["id"], tech_id)
    # Depart -> EN_ROUTE (not yet ON_SITE).
    validate_success(api.depart_service_visit(visit["id"], make_technician_headers(tech_id)), 200)
    validate_error(
        api.post_refrigerant_log(visit["id"], create_refrigerant_log_payload(ctx["equipment"]["id"], "RECOVER", 100),
                                 make_technician_headers(tech_id)),
        ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value,
    )
