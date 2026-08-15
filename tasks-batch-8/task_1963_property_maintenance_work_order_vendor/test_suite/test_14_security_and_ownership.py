"""Authentication, role authorization, and entity-backed ownership checks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_part,
    create_property,
    create_property_payload,
    create_purchase_request,
    create_resident,
    create_technician,
    create_vendor,
    create_work_order,
    create_work_order_payload,
    current_work_order_version,
    dispatch_payload,
    get_purchase_request,
    get_work_order,
    make_resident_headers,
    make_technician_headers,
    make_vendor_headers,
    setup_assigned_work_order,
    setup_completed_work_order,
    setup_in_progress_work_order,
    setup_property_resident_technician,
    validate_error,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestAuthentication:
    def test_request_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the operational capacity in which they are acting. The system recognizes five roles, spelled exactly as follows: `Resident`, `Dispatcher`, `Technician`, `Vendor`, and `PropertyManager`. A request that is missing either header, or that supplies a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_property(create_property_payload(name="NoAuth"), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_resident_cannot_dispatch(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted on the targeted endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the dispatch endpoint authorizes only the Dispatcher role.

        Design: Corner/rbac/resident_cannot_dispatch
        """
        bundle = setup_property_resident_technician("Rbac1 Property", unit_number="601")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Leak",
        )
        resp = api.dispatch_work_order(
            wo["id"],
            dispatch_payload(
                assignment_type="IN_HOUSE",
                technician_id=bundle["technician"]["id"],
                scheduled_start_at="2026-08-01T10:00:00Z",
                scheduled_end_at="2026-08-01T12:00:00Z",
                entry_authorization="RESIDENT_CONSENT",
            ),
            make_resident_headers(bundle["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_work_order(wo["id"])["status"] == "TRIAGED"

    def test_technician_cannot_approve_purchase_request(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted on the targeted endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the purchase-request events endpoint authorizes only the PropertyManager role.

        Design: Corner/rbac/technician_cannot_approve_purchase_request
        """
        bundle = setup_assigned_work_order("Rbac2 Property", unit_number="602")
        part = create_part(bundle["property"]["id"], sku="PMP-3", name="Pump",
                           unit_cost_cents=30000, reorder_level=0, initial_stock=0)
        tech = make_technician_headers(bundle["technician"]["id"])
        wo_id = bundle["work_order"]["id"]
        # Over the default threshold so the request is born PENDING.
        pr = create_purchase_request(
            wo_id, part["id"], quantity=2, quoted_unit_cost_cents=30000,
            shipping_fee_cents=0,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr["status"] == "PENDING"
        resp = api.purchase_request_event(pr["id"], {"event_type": "APPROVE"}, tech)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_purchase_request(pr["id"])["status"] == "PENDING"

    def test_dispatcher_cannot_sign_off(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted on the targeted endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "Resident sign-off is a self-transition: while the work order is `IN_PROGRESS`, the reporting resident — and only the reporting resident, matching `X-User-ID` against the work order's `resident_id` — records approval, which sets `resident_signoff` to true and leaves the status at `IN_PROGRESS`."

        Design: Corner/rbac/dispatcher_cannot_sign_off
        """
        bundle = setup_in_progress_work_order("Rbac3 Property", unit_number="603")
        wo = bundle["work_order"]
        resp = api.sign_off_work_order(wo["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_work_order(wo["id"])["resident_signoff"] is False

    def test_manager_cannot_file_work_order(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted on the targeted endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the work-order intake endpoint authorizes only the Resident role.

        Design: Corner/rbac/manager_cannot_file_work_order
        """
        prop = create_property("Rbac6 Property")
        resident = create_resident(prop["id"], unit_number="606", full_name="R Rbac6",
                                   email="rrbac6@x.com")
        resp = api.create_work_order(
            create_work_order_payload(
                property_id=prop["id"], resident_id=resident["id"],
                category="PLUMBING", priority="ROUTINE", description="Manager filing",
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestEntityBackedOwnership:
    def test_vendor_cannot_start_inhouse_work_order(self, api):
        """PRD §3.4: "The caller must be the assigned party: on an in-house job the caller's `X-User-ID` must equal `assigned_technician_id`, and on a vendor job it must equal `assigned_vendor_id`; anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/vendor_cannot_start_inhouse_work_order
        """
        bundle = setup_assigned_work_order("Rbac4 Property", unit_number="604")
        vendor = create_vendor(bundle["property"]["id"], company_name="V Co",
                               trade="PLUMBING",
                               insurance_valid_until="2027-01-01T00:00:00Z")
        wo = bundle["work_order"]
        assert wo["assignment_type"] == "IN_HOUSE"
        resp = api.start_work_order(
            wo["id"],
            {"resident_consent_confirmed": True},
            make_vendor_headers(vendor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_work_order(wo["id"])["status"] == "ASSIGNED"

    def test_technician_cannot_start_unassigned_order(self, api):
        """PRD §3.4: "The caller must be the assigned party: on an in-house job the caller's `X-User-ID` must equal `assigned_technician_id`, and on a vendor job it must equal `assigned_vendor_id`; anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/technician_cannot_start_unassigned_order
        """
        bundle = setup_assigned_work_order("Rbac5 Property", unit_number="605")
        other_tech = create_technician(bundle["property"]["id"], full_name="T B",
                                       trade="PLUMBING")
        wo = bundle["work_order"]
        assert wo["assigned_technician_id"] == bundle["technician"]["id"]
        resp = api.start_work_order(
            wo["id"],
            {"resident_consent_confirmed": True},
            make_technician_headers(other_tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_work_order(wo["id"])["status"] == "ASSIGNED"

    def test_reopen_by_other_resident_forbidden(self, api):
        """PRD §3.5: "A resident caller must be the reporting resident or the request fails `ERR_NOT_RESOURCE_OWNER`."
        PRD §2.1: "a resident signing off, reopening, cancelling, disputing, or paying does so against their own records only, and any mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/reopen_by_other_resident_forbidden
        """
        bundle = setup_completed_work_order(property_name="Own Property",
                                            unit_number="410")
        other_resident = create_resident(
            bundle["property"]["id"], unit_number="411", full_name="R B", email="rb@x.com"
        )
        wo = bundle["work_order"]
        assert wo["status"] == "COMPLETED"
        resp = api.reopen_work_order(
            wo["id"], {}, make_resident_headers(other_resident["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_work_order(wo["id"])["status"] == "COMPLETED"

    def test_create_work_order_for_other_resident_forbidden(self, api):
        """PRD §3.2: "If the payload's `resident_id` does not match the caller's `X-User-ID`, the create is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/create_work_order_for_other_resident_forbidden
        """
        prop = create_property("Own2 Property")
        res_a = create_resident(prop["id"], unit_number="412", full_name="R A",
                                email="ra2@x.com")
        res_b = create_resident(prop["id"], unit_number="413", full_name="R B",
                                email="rb2@x.com")
        resp = api.create_work_order(
            create_work_order_payload(
                property_id=prop["id"], resident_id=res_b["id"],
                category="PLUMBING", priority="ROUTINE", description="Forged filing",
            ),
            make_resident_headers(res_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
