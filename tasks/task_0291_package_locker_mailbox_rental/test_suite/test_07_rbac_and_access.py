"""Role-based access control and list pagination.

Covers corner-design 'rbac' instances and the package-list pagination instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_facility_operator_headers, make_compliance_officer_headers, make_customer_headers,
    make_role_headers,
    setup_active_agreement, setup_submitted_form, create_facility,
)

OP = make_facility_operator_headers()
CO = make_compliance_officer_headers()


# ---------------------------------------------------------------------------
# Corner: rbac / customer_cannot_verify_form_returns_forbidden
# ---------------------------------------------------------------------------
def test_customer_cannot_verify_form_returns_forbidden(api):
    """PRD §2.1: "A ComplianceOfficer reviews recipient authorizations: they alone
    verify or reject a Form 1583, and they may also place a customer on a compliance
    hold."

    Design: Corner/rbac/customer_cannot_verify_form_returns_forbidden
    """
    base = setup_submitted_form()
    cust_headers = make_customer_headers(base["customer"]["id"])
    resp = api.verify_form_1583(base["form"]["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    after = validate_success(api.get_form_1583(base["form"]["id"], OP))
    assert after["status"] == "SUBMITTED", "form stays SUBMITTED when a Customer cannot verify"


# ---------------------------------------------------------------------------
# Corner: rbac / compliance_officer_cannot_receive_package_returns_forbidden
# ---------------------------------------------------------------------------
def test_compliance_officer_cannot_receive_package_returns_forbidden(api):
    """PRD §2.1: "A FacilityOperator is front-desk and back-office staff: they own
    the facility record, locker and mailbox inventory, package receiving, the
    logical-clock sweeps, and billing capture."

    Design: Corner/rbac/compliance_officer_cannot_receive_package_returns_forbidden
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="Depot")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "UPS", "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, CO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Corner: rbac / missing_headers_returns_unauthenticated
# ---------------------------------------------------------------------------
def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "The system recognizes exactly three roles, spelled precisely as
    FacilityOperator, Customer, and ComplianceOfficer. A request missing either
    header, or carrying an X-User-Role value that is not one of these three, is
    rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    fac = create_facility(name="Depot")
    ghost_headers = make_role_headers("Ghost", "ghost-1")
    resp = api.get_facility(fac["id"], ghost_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / pagination_packages_list
# ---------------------------------------------------------------------------
def test_pagination_packages_list(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults
    to 10, may not be smaller than 1, and may not exceed 100."
    PRD §2.3: "List responses populate the limit, offset, total_count, and has_more
    fields in the envelope's meta object, where total_count reflects the full count
    matching the filters before pagination and has_more indicates whether further
    items remain beyond the current page."

    Design: Corner/cross_cutting_complexity_layers/pagination_packages_list
    """
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=1, with_locker=True, locker_size="MEDIUM", name="Depot")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    # Three MEDIUM lockers total (one from setup + two more), three packages.
    get_success_data(api.create_locker_unit({"facility_id": fac_id, "label": "L2", "size_tier": "MEDIUM"}, OP))
    get_success_data(api.create_locker_unit({"facility_id": fac_id, "label": "L3", "size_tier": "MEDIUM"}, OP))
    for _ in range(3):
        get_success_data(api.create_package(
            {"facility_id": fac_id, "rental_agreement_id": agr_id, "carrier": "UPS",
             "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, OP))

    resp = api.list_packages(OP, params={"rental_agreement_id": agr_id, "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, "limit=2 returns 2 items"
    assert meta["total_count"] == 3, "total_count reflects all 3 packages"
    assert meta["has_more"] is True, "has_more is true with a third item beyond the page"
