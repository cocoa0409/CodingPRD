"""Authentication, authorization, ownership, and segregation-of-duties corners.

Queue B (Corner): validations/* and rbac/*.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    make_vendor_headers,
    make_property_manager_headers,
    validate_error,
    ApiErrorId,
)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the four recognized roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    prop = fx.new_property(api, name="Harbor", address="10 Dock Rd", guest_parking_capacity=3)
    resp = api.get_property(prop["id"], fx.TEST_USERS["anonymous_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_resident_cannot_triage_service_request(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to invoke the target endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Triage is PropertyManager-only; a Resident calling it is rejected with
    ERR_UNAUTHORIZED.

    Design: Corner/validations/resident_cannot_triage_service_request_returns_403
    """
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Al", "email": "al@x.com"})
    resident_id = base["resident"]["id"]
    sr = fx.new_service_request(api, base["unit"]["id"], resident_id, trade="GENERAL", description="x")
    resp = api.triage_service_request(sr["id"], {}, make_resident_headers(resident_id))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_resident_cannot_cancel_another_residents_booking(api):
    """PRD §2.1: "A resident acting on a resource they do not own is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Resident B cancelling Resident A's booking is rejected with
    ERR_NOT_RESOURCE_OWNER.

    Design: Corner/validations/resident_cannot_cancel_others_booking_returns_403
    """
    prop = fx.new_property(api, name="Harbor", address="10 Dock Rd", guest_parking_capacity=3)
    unit_a = fx.new_unit(api, prop["id"], unit_number="B3")
    unit_b = fx.new_unit(api, prop["id"], unit_number="B4")
    res_a = fx.new_resident(api, unit_a["id"], full_name="Ada", email="ada2@x.com")
    res_b = fx.new_resident(api, unit_b["id"], full_name="Bo", email="bo2@x.com")
    fx.set_clock(api, "2026-05-20T00:00:00Z")
    amenity = fx.new_amenity(api, prop["id"], name="Gym", amenity_type="GYM", capacity=1,
                             base_rate_cents_per_hour=1000, deposit_cents=0,
                             buffer_minutes=0, open_minute=0, close_minute=1440)
    booking = fx.new_booking(api, amenity["id"], res_a["id"],
                             "2026-06-12T10:00:00Z", "2026-06-12T11:00:00Z",
                             expected_version=amenity["version"])
    resp = api.cancel_booking(booking["id"], make_resident_headers(res_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_invoice_approver_same_as_triager_returns_403(api):
    """PRD §3.5: "the approving manager's `X-User-ID` must differ from the
    `triaged_by_user_id` who triaged it; an approver who is the same person as
    the triager is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/invoice_approver_same_as_triager_returns_403
    """
    ctx = fx.setup_started_request(
        api, trade="PLUMBING", estimated_hours=1,
        triage_user="pm_1", assign_user="pm_1",
        vendor_overrides={"name": "PlumbCo", "trades": ["PLUMBING"], "hourly_rate_cents": 8000},
    )
    fx.get_success_data(api.complete_service_request(
        ctx["sr"]["id"], {"labor_hours": 1}, make_vendor_headers(ctx["vendor"]["id"])))
    resp = api.approve_invoice_service_request(ctx["sr"]["id"], make_property_manager_headers("pm_1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_vendor_cannot_create_property(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to invoke the target endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    POST /properties is PropertyManager-only; a Vendor calling it is rejected
    with ERR_UNAUTHORIZED.

    Design: Corner/rbac/vendor_cannot_create_property_returns_403
    """
    vendor = fx.new_vendor(api, name="V", trades=["GENERAL"], hourly_rate_cents=5000)
    resp = api.create_property(
        {"name": "Rogue", "address": "x", "guest_parking_capacity": 1},
        make_vendor_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
