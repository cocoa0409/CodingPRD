"""User-context headers, role-based access control, and not-found taxonomy."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_cardiologist,
    create_device_lot,
    create_device_lot_payload,
    create_case_payload,
    create_recovery_bed,
    create_room,
    get_lot,
    make_interventional_cardiologist_headers,
    post_case,
    restock_payload,
    schedule_case_payload,
    validate_error,
    validate_paginated,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]
NURSE_MANAGER = TEST_USERS["nurse_manager_headers"]
REGISTRY = TEST_USERS["registry_coordinator_headers"]


class TestUserContextHeaders:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which that user acts. A request that is missing either header, or carries a
        malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        # Only X-User-ID is sent; the X-User-Role header is absent.
        resp = api.list_cases({"X-User-ID": "test-scheduler-1"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400)


class TestValidationPriority:
    def test_priority_authz_beats_not_found(self, api):
        """PRD §2.10: "Rejection checks run in a fixed priority order, so a request
        that would fail several checks always reports the earliest applicable one.
        First come the user-context headers of §2.1
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization
        against §4 (`ERR_INSUFFICIENT_PERMISSIONS`), then existence of every path
        identifier — left to right — followed by body foreign keys (the nine
        not-found errors of §2.8)."
        PRD §4: "| POST | `/cath-lab/cases/{id}/cancel` | Cancel a non-terminal case
        | CathLabScheduler |"

        Design: Corner/validations/priority_authz_beats_not_found
        """
        # RegistryCoordinator may not cancel; the unknown id is never reached.
        resp = api.cancel_case(NON_EXISTENT_UUID, REGISTRY)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)


class TestRbacDeny:
    def test_technologist_cannot_schedule_case(self, api):
        """PRD §2.1: "Each operation in §4 names the roles permitted to invoke it;
        a request whose role is not among them is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/cath-lab/cases/{id}/schedule` | Schedule or reschedule
        a case onto a room | CathLabScheduler |"

        Design: Corner/rbac/technologist_cannot_schedule_case
        """
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed = create_recovery_bed("Bed 1")
        case = post_case(physician["id"])
        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(room["id"], "2026-08-10T09:00:00Z",
                                  bed_id=bed["id"]),
            TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        current = api.get_case(case["id"], SCHEDULER).json()["data"]
        assert current["status"] == "POSTED"

    def test_scheduler_cannot_restock_lot(self, api):
        """PRD §2.1: "Each operation in §4 names the roles permitted to invoke it;
        a request whose role is not among them is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/cath-lab/device-lots/{id}/restock` | Add units to a lot
        (version-gated) | CathLabTechnologist |"

        Design: Corner/rbac/scheduler_cannot_restock_lot
        """
        lot = create_device_lot(lot_number="LOT-H", quantity_on_hand=2,
                                reorder_threshold=1)
        resp = api.restock_device_lot(
            lot["id"], restock_payload(5, lot["version"]), SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        current = get_lot(lot["id"])
        assert current["quantity_on_hand"] == 2
        assert current["version"] == lot["version"], "the denied write is not applied"

    def test_cardiologist_cannot_create_device_lot(self, api):
        """PRD §2.1: "Each operation in §4 names the roles permitted to invoke it;
        a request whose role is not among them is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/cath-lab/device-lots` | Register a device/implant lot |
        CathLabTechnologist |"

        Design: Corner/rbac/cardiologist_cannot_create_device_lot
        """
        physician = create_cardiologist()
        resp = api.create_device_lot(
            create_device_lot_payload(lot_number="LOT-I", quantity_on_hand=2,
                                      reorder_threshold=1),
            make_interventional_cardiologist_headers(physician["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)

    def test_registry_coordinator_cannot_create_case(self, api):
        """PRD §2.1: "Each operation in §4 names the roles permitted to invoke it;
        a request whose role is not among them is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/cath-lab/cases` | Post a cath case; a STEMI case
        activates immediately | CathLabScheduler, InterventionalCardiologist |"

        Design: Corner/rbac/registry_coordinator_cannot_create_case
        """
        physician = create_cardiologist()
        resp = api.create_case(
            create_case_payload(performing_physician_id=physician["id"]), REGISTRY)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)


class TestRbacAllow:
    def test_all_roles_can_read_shared_get_endpoints(self, api):
        """PRD §2.1: "Each operation in §4 names the roles permitted to invoke it;
        a request whose role is not among them is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| GET | `/cath-lab/cases` | List cath cases | All roles |"

        Design: Corner/rbac/all_roles_can_read_shared_get_endpoints
        """
        physician = create_cardiologist()
        post_case(physician["id"])
        all_headers = [
            SCHEDULER,
            make_interventional_cardiologist_headers(physician["id"]),
            TECHNOLOGIST,
            NURSE_MANAGER,
            REGISTRY,
        ]
        for headers in all_headers:
            data, meta = validate_paginated(api.list_cases(headers))
            assert meta["total_count"] == 1, (
                f"role {headers['X-User-Role']} must read the shared list")
            assert len(data) == 1


class TestNotFoundTaxonomy:
    def test_remaining_not_found_errors_triggerable(self, api):
        """PRD §2.8: "Identifiers embedded in a request path are validated in a
        strict left-to-right order, and the request is rejected with the not-found
        error of the first identifier that fails to resolve: an unknown room yields
        `ERR_ROOM_NOT_FOUND`, a staff member `ERR_STAFF_NOT_FOUND`, a case
        `ERR_CASE_NOT_FOUND`, a device lot `ERR_LOT_NOT_FOUND`, a recovery bed
        `ERR_BED_NOT_FOUND`, a staff assignment `ERR_ASSIGNMENT_NOT_FOUND`, a
        device usage `ERR_USAGE_NOT_FOUND`, a dose record
        `ERR_DOSE_RECORD_NOT_FOUND`, and a registry submission
        `ERR_SUBMISSION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/remaining_not_found_errors_triggerable
        """
        resp = api.release_staff_assignment(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
                       expected_status=404)
        resp = api.implant_device_usage(NON_EXISTENT_UUID, TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_USAGE_NOT_FOUND, expected_status=404)
        resp = api.get_recovery_bed(NON_EXISTENT_UUID, NURSE_MANAGER)
        validate_error(resp, ApiErrorId.ERR_BED_NOT_FOUND, expected_status=404)
        resp = api.void_dose_record(NON_EXISTENT_UUID, TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_DOSE_RECORD_NOT_FOUND,
                       expected_status=404)
        resp = api.get_registry_submission(NON_EXISTENT_UUID, REGISTRY)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_FOUND,
                       expected_status=404)
