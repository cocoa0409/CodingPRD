"""Authentication, role-based access control, and segregation of duties (PRD §2.1, §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_customer_payload, create_quality_test_payload, create_lot_payload,
    create_voc_permit_payload,
    create_customer, create_spec, get_permit,
    setup_lot_release_ready,
    build_user_headers,
    TEST_USERS, make_quality_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
CHEM = TEST_USERS["chemist_headers"]
QC = TEST_USERS["qc_headers"]
QM = TEST_USERS["qm_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside this
        declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        res = api._request("GET", f"/ecoat/lots/{NON_EXISTENT_UUID}", headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)

    def test_undeclared_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside this
        declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        headers = build_user_headers("test-intruder-1", "SuperUser")
        res = api.get_lot(NON_EXISTENT_UUID, headers)
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


class TestRoleDenials:
    def test_line_scheduler_cannot_record_quality_test(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the
        roles authorized for the target operation is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §3.6: "With cure passed, the `QcInspector` samples the lot and records
        **QualityTest** events, supplying the `lot_id`, a `test_type` of `ADHESION` or
        `IMPACT`, and the `measured_value` — the cross-hatch class for adhesion, joules
        for impact."

        Design: Corner/rbac/line_scheduler_cannot_record_quality_test
        """
        payload = create_quality_test_payload(
            NON_EXISTENT_UUID, test_type="ADHESION", measured_value=3
        )
        res = api.create_quality_test(payload, SCHED)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_process_chemist_cannot_close_permit(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the
        roles authorized for the target operation is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §3.9: "Closing a period is a `PlantAdmin` act with two preconditions: the
        permit must still be `ACTIVE` or `EXCEEDED` — closing a `CLOSED` permit is
        rejected with `ERR_PERMIT_PERIOD_CLOSED` — and the current logical clock must
        have passed `period_end`, else `ERR_PERMIT_NOT_EXPIRED`."

        Design: Corner/rbac/process_chemist_cannot_close_permit
        """
        permit = validate_success(
            api.create_voc_permit(create_voc_permit_payload(), ADMIN), 201
        )
        res = api.close_voc_permit(permit["id"], CHEM)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
        permit_after = get_permit(permit["id"])
        assert permit_after["status"] == "ACTIVE"

    def test_quality_manager_cannot_create_lots(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the
        roles authorized for the target operation is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §3.3: "A `LineScheduler` books a **Lot** by naming the `customer_id`, the
        `spec_id` of the coating standard the parts must meet, and the `part_quantity`
        received, which must be greater than zero."

        Design: Corner/rbac/quality_manager_cannot_create_lots
        """
        customer = create_customer()
        spec = create_spec(customer["id"])
        payload = create_lot_payload(customer["id"], spec["id"], part_quantity=10)
        res = api.create_lot(payload, QM)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


class TestSegregationOfDuties:
    def test_recording_operator_cannot_release_the_lot(self, api):
        """PRD §2.1: "One comparison against recorded operator identity does exist, and
        it is the segregation-of-duties rule: the `QualityManager` who releases a lot
        must not be the operator who recorded that lot's quality tests. A release
        attempted by the same operator identifier is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the full rule is specified in §3.6."

        Design: Corner/rbac/segregation_of_duties_release_rejected
        """
        ctx = setup_lot_release_ready()  # tests recorded by operator qc-1
        res = api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qc-1"))
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    def test_independent_quality_manager_release_succeeds(self, api):
        """PRD §3.6: "And the segregation-of-duties rule of §2.1 bites here: the
        releasing manager's `X-User-ID` must differ from the `recorded_by_user_id` of
        every quality test on the lot in the current cure epoch, so the person who
        measured the lot can never be the person who ships it — a violation is
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_release_rejected
        """
        ctx = setup_lot_release_ready()  # tests recorded by operator qc-1
        res_same = api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qc-1"))
        validate_error(res_same, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        released = validate_success(
            api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qm-2")), 200
        )
        assert released["status"] == "RELEASED"
