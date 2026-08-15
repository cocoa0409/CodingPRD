"""Per-entity not-found errors, authentication priority over existence, and RBAC denials for exclusive operations."""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    create_customer, create_line, create_spec, create_draft_order, create_lot,
    schedule_order_payload, create_mold_payload,
    api_client, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["plant_admin"]
ENGINEER = TEST_USERS["process_engineer"]
TECH = TEST_USERS["quality_technician"]
SCHEDULER = TEST_USERS["production_scheduler"]
LOGISTICS = TEST_USERS["logistics_coordinator"]


class TestNotFound:
    """PRD §2.6: "Each entity has its own not-found error" (all HTTP 404)."""

    def test_get_missing_bottle_spec_returns_not_found(self, api):
        """PRD §2.6: "Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_BOTTLE_SPEC_NOT_FOUND`, `ERR_QUALIFICATION_RUN_NOT_FOUND`" (all HTTP 404).

Design: Corner/entities/get_missing_bottle_spec_returns_not_found"""
        res = api.get_bottle_spec(NON_EXISTENT_UUID, ENGINEER)
        validate_error(res, ApiErrorId.ERR_BOTTLE_SPEC_NOT_FOUND)

    def test_get_missing_customer_returns_not_found(self, api):
        """PRD §2.6: "Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_BOTTLE_SPEC_NOT_FOUND`, `ERR_QUALIFICATION_RUN_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_customer_returns_not_found"""
        res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)

    def test_get_missing_qualification_run_returns_not_found(self, api):
        """PRD §2.6: "Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_BOTTLE_SPEC_NOT_FOUND`, `ERR_QUALIFICATION_RUN_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_qualification_run_returns_not_found"""
        res = api.get_qualification_run(NON_EXISTENT_UUID, ENGINEER)
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_RUN_NOT_FOUND)

    def test_get_missing_mold_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_QUALIFICATION_RUN_NOT_FOUND`, `ERR_MOLD_NOT_FOUND`, `ERR_CAVITY_BLOCKOUT_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_mold_returns_not_found"""
        res = api.get_mold(NON_EXISTENT_UUID, ENGINEER)
        validate_error(res, ApiErrorId.ERR_MOLD_NOT_FOUND)

    def test_get_missing_cavity_blockout_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_QUALIFICATION_RUN_NOT_FOUND`, `ERR_MOLD_NOT_FOUND`, `ERR_CAVITY_BLOCKOUT_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_cavity_blockout_returns_not_found"""
        res = api.get_cavity_blockout(NON_EXISTENT_UUID, ENGINEER)
        validate_error(res, ApiErrorId.ERR_CAVITY_BLOCKOUT_NOT_FOUND)

    def test_get_missing_machine_line_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_CAVITY_BLOCKOUT_NOT_FOUND`, `ERR_MACHINE_LINE_NOT_FOUND`, `ERR_SCHEDULE_SLOT_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_machine_line_returns_not_found"""
        res = api.get_machine_line(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(res, ApiErrorId.ERR_MACHINE_LINE_NOT_FOUND)

    def test_get_missing_schedule_slot_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_CAVITY_BLOCKOUT_NOT_FOUND`, `ERR_MACHINE_LINE_NOT_FOUND`, `ERR_SCHEDULE_SLOT_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_schedule_slot_returns_not_found"""
        res = api.get_schedule_slot(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(res, ApiErrorId.ERR_SCHEDULE_SLOT_NOT_FOUND)

    def test_get_missing_material_lot_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_SCHEDULE_SLOT_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`, `ERR_PRODUCTION_ORDER_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_material_lot_returns_not_found"""
        res = api.get_material_lot(NON_EXISTENT_UUID, TECH)
        validate_error(res, ApiErrorId.ERR_MATERIAL_LOT_NOT_FOUND)

    def test_get_missing_production_order_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_SCHEDULE_SLOT_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`, `ERR_PRODUCTION_ORDER_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_production_order_returns_not_found"""
        res = api.get_production_order(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(res, ApiErrorId.ERR_PRODUCTION_ORDER_NOT_FOUND)

    def test_get_missing_production_run_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_PRODUCTION_ORDER_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_QUALITY_TEST_LOT_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_production_run_returns_not_found"""
        res = api.get_production_run(NON_EXISTENT_UUID, ENGINEER)
        validate_error(res, ApiErrorId.ERR_PRODUCTION_RUN_NOT_FOUND)

    def test_get_missing_quality_lot_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_PRODUCTION_ORDER_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_QUALITY_TEST_LOT_NOT_FOUND`" (all HTTP 404).

Design: Corner/errors/get_missing_quality_lot_returns_not_found"""
        res = api.get_quality_test_lot(NON_EXISTENT_UUID, TECH)
        validate_error(res, ApiErrorId.ERR_QUALITY_TEST_LOT_NOT_FOUND)

    def test_get_missing_shipment_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_QUALITY_TEST_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, and `ERR_DOCK_APPOINTMENT_NOT_FOUND` (all HTTP 404)".

Design: Corner/errors/get_missing_shipment_returns_not_found"""
        res = api.get_shipment(NON_EXISTENT_UUID, LOGISTICS)
        validate_error(res, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)

    def test_get_missing_dock_appointment_returns_not_found(self, api):
        """PRD §2.6: PRD §2.6 lists "`ERR_QUALITY_TEST_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, and `ERR_DOCK_APPOINTMENT_NOT_FOUND` (all HTTP 404)".

Design: Corner/errors/get_missing_dock_appointment_returns_not_found"""
        res = api.get_dock_appointment(NON_EXISTENT_UUID, LOGISTICS)
        validate_error(res, ApiErrorId.ERR_DOCK_APPOINTMENT_NOT_FOUND)


class TestAuthenticationPriority:
    def test_missing_auth_on_missing_spec_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing, does not name one of the declared roles, or whose `X-User-ID` header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
PRD §2.9: "Authentication comes first" and "a failure at an earlier stage masks every later stage".

Design: Corner/validations/missing_auth_on_missing_spec_returns_unauthenticated"""
        # no auth headers AND a non-existent spec id: P1 must mask P4
        res = api.get_bottle_spec(NON_EXISTENT_UUID, None)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacDenials:
    def test_quality_technician_cannot_schedule_order(self, api):
        """PRD §2.1: "Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." §4 lists only ProductionScheduler for POST /plant/production-orders/{id}/schedule.

Design: Corner/rbac/quality_tech_cannot_schedule_order"""
        customer = create_customer()
        line = create_line()
        spec = create_spec(customer["id"], label_type="NONE")
        order = create_draft_order(spec["id"], quantity_ordered=1000)
        res = api.schedule_production_order(
            order["id"],
            schedule_order_payload(line["id"], "2026-08-02T10:00:00Z",
                                   "2026-08-02T12:00:00Z", order["version"]),
            TECH)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_logistics_cannot_create_mold(self, api):
        """PRD §2.1: "a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." §4 lists only PlantAdmin for POST /plant/molds.

Design: Corner/rbac/logistics_cannot_create_mold"""
        res = api.create_mold(create_mold_payload(), LOGISTICS)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
