"""Authentication, role permission, and entity-backed identity checks (PRD §2.1)."""
from test_helpers import (
    build_user_headers,
    fixtures,
    validate_error,
    validate_success,
)


class TestUnauthenticated:
    def test_missing_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_missing_headers
        """
        resp = api.list_drug_products(headers=None)
        validate_error(resp, "ERR_UNAUTHENTICATED", 401)


class TestRolePermission:
    def test_prescriber_cannot_verify_order(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorized-role list (§4); a role not permitted to call the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "`/pharmacy/medication-orders/{id}/verify` | Pharmacist verification: allergy screen, renal adjustment, dose rounding | Pharmacist"

        Design: Corner/rbac/prescriber_cannot_verify_order_forbidden
        """
        prescriber, prescriber_headers = fixtures.make_prescriber()
        ns = fixtures.setup_verified_order(route="PO", ordered_dose_mg=100.0)
        # Reuse a fresh PENDING order so the denial is observable pre-verify:
        patient = fixtures.create_patient()
        order = fixtures.place_order(patient, ns.drug, prescriber, route="PO",
                                     ordered_dose_mg=100.0)
        resp = api.verify_order(order["id"], {}, prescriber_headers)
        validate_error(resp, "ERR_FORBIDDEN", 403)
        fetched = validate_success(
            api.get_medication_order(order["id"], ns.pharmacist_headers), 200
        )
        assert fetched["verification_status"] == "PENDING"

    def test_technician_cannot_adjudicate_diversion_case(self, api, diversion_officer_headers):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorized-role list (§4); a role not permitted to call the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "`/pharmacy/diversion-cases/{id}/adjudicate` | Branching adjudication | DiversionOfficer"

        Design: Corner/rbac/technician_cannot_adjudicate_diversion_case
        """
        ns = fixtures.setup_diversion_case()
        validate_success(
            api.review_diversion_case(ns.case["id"], diversion_officer_headers), 200
        )
        resp = api.adjudicate_diversion_case(
            ns.case["id"],
            {"outcome": "CLOSED_UNSUBSTANTIATED", "note": "nope"},
            ns.technician_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN", 403)
        fetched = validate_success(
            api.get_diversion_case(ns.case["id"], diversion_officer_headers), 200
        )
        assert fetched["status"] == "UNDER_REVIEW"


class TestEntityBackedIdentity:
    def test_role_header_conflicting_with_staff_role_rejected(self, api):
        """PRD §2.1: "The remaining four roles are **entity-backed** by `StaffMember`. When `X-User-Role` is `Prescriber`, `Pharmacist`, `PharmacyTechnician`, or `Nurse`, `X-User-ID` is the `id` of the acting `StaffMember`. The server resolves the `StaffMember` row with that `id`; the row must exist, its `active` flag must be true, and its `staff_role` must equal the `X-User-Role` header value — so a call made as `Pharmacist` must present the `id` of a staff member whose `staff_role` is `PHARMACIST`. A missing row, an inactive row, or a `staff_role` that disagrees with the header is rejected with `ERR_ROLE_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/role_mismatch_staff_role_header_conflict
        """
        technician, _ = fixtures.make_technician()
        prescriber, _ = fixtures.make_prescriber()
        patient = fixtures.create_patient()
        drug = fixtures.create_drug()
        order = fixtures.place_order(patient, drug, prescriber, route="PO",
                                     ordered_dose_mg=100.0)
        # Pharmacist header carrying a TECHNICIAN staff row id.
        mismatched = build_user_headers(technician["id"], "Pharmacist")
        resp = api.verify_order(order["id"], {}, mismatched)
        validate_error(resp, "ERR_ROLE_MISMATCH", 403)
