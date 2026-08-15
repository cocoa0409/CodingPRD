"""Authentication, role authorization, entity-backed identity, ownership, and
the segregation-of-duties pairings."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_authorized_user,
    create_container,
    create_dose_order_payload,
    create_isotope,
    create_isotope_product_payload,
    create_room,
    get_order,
    make_authorized_user_headers,
    make_radiopharmacist_headers,
    make_rso_headers,
    make_technologist_headers,
    set_clock,
    setup_f18_department,
    setup_f18_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their operational
        capacity. ... A request whose headers are missing or whose role is not
        one of these five is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        res = api.create_isotope_product(create_isotope_product_payload(), headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


class TestExclusiveOperations:
    def test_technologist_cannot_create_isotope_product(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." and PRD §4: isotope-product
        registration is a `DepartmentAdmin` operation.

        Design: Corner/rbac/technologist_cannot_create_isotope_product
        """
        res = api.create_isotope_product(
            create_isotope_product_payload(), make_technologist_headers("tech-1")
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    def test_radiopharmacist_cannot_certify_container(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." and PRD §4: clearance certification is
        a `RadiationSafetyOfficer` operation.

        Design: Corner/rbac/radiopharmacist_cannot_certify_container
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        room = create_room(name="Waste-Store")
        container = create_container(iso["id"], room["id"], "rso-1")
        validate_success(
            api.seal_waste_container(
                container["id"],
                {"expected_container_version": container["version"]},
                make_rso_headers("rso-1"),
            ),
            200,
        )
        res = api.certify_waste_container_clearance(
            container["id"], make_radiopharmacist_headers("rp-1")
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


class TestEntityBackedIdentity:
    def test_authorized_user_identity_must_reference_row(self, api):
        """PRD §2.1: "When `X-User-Role` is `AuthorizedUser`, `X-User-ID` is the
        `id` of the acting `AuthorizedUser` record; ownership checks on any
        resource that references an `AuthorizedUser` compare the resource's
        foreign-key field — for a dose order, its `authorized_user_id` — to
        `X-User-ID`, and the identifier must reference an existing
        `AuthorizedUser` row or the call fails with `ERR_NOT_FOUND`."

        No AuthorizedUser rows exist, so the entity-backed identity resolves to
        nothing.

        Design: Corner/rbac/authorized_user_identity_must_reference_row
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        res = api.create_dose_order(
            create_dose_order_payload(ctx["patient"]["id"], ctx["isotope"]["id"]),
            make_authorized_user_headers(NON_EXISTENT_UUID),
        )
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestPrescriberOwnership:
    def test_au_cannot_cancel_other_prescribers_order(self, api):
        """PRD §3.3: "Cancellation belongs to the prescriber alone: the caller's
        `X-User-ID` must equal the order's `authorized_user_id`, otherwise the
        call is rejected with `ERR_FORBIDDEN_ROLE`."

        A second authorized user on the same license attempts the cancel.

        Design: Corner/rbac/au_cannot_cancel_other_prescribers_order
        """
        ctx = setup_f18_order()
        au2 = create_authorized_user(ctx["license"]["id"], full_name="Dr. B")

        res = api.cancel_dose_order(
            ctx["order"]["id"],
            {"reason": "not mine"},
            make_authorized_user_headers(au2["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
        assert get_order(ctx["order"]["id"])["status"] == "ORDERED"


class TestSealCertifySegregation:
    def test_sealer_cannot_certify_same_container(self, api):
        """PRD §2.7: "The officer who certifies a waste container's clearance
        must not be the officer who sealed it: the certifying `X-User-ID` must
        differ from the container's `sealed_by_user_id`. ... Violating any of
        the three pairings is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Segregation of duties sits in the safety family of the PRD §2.9
        pipeline, ahead of the clearance-timing check, so the rejection is
        observable without advancing the clock.

        Design: Corner/rbac/sealer_cannot_certify_same_container
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        room = create_room(name="Waste-Store")
        container = create_container(iso["id"], room["id"], "rso-1")
        validate_success(
            api.seal_waste_container(
                container["id"],
                {"expected_container_version": container["version"]},
                make_rso_headers("rso-1"),
            ),
            200,
        )
        res = api.certify_waste_container_clearance(container["id"], make_rso_headers("rso-1"))
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
