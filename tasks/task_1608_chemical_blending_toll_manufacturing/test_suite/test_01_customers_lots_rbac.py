"""Customers, consignment lot intake, and role-based access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_customer,
    assert_lot,
    create_customer,
    create_tank,
    open_cleaning_record,
    setup_batch_context,
    submit_cleaning_record,
    validate_error,
    validate_success,
)

SCHED = TEST_USERS["batch_scheduler_headers"]


class TestCustomerCreation:
    def test_create_customer_applies_defaults(self, api, quality_manager_headers):
        """PRD §3.1: "A `QualityManager` onboards a customer by supplying its
        `legal_name` and, optionally, a `credit_hold` flag that defaults to
        false. The new customer begins in `ACTIVE` status with `version` 1."

        Design: Corner/entities/create_customer_required_fields_and_defaults
        """
        resp = api.create_customer({"legal_name": "Default Corp"},
                                   quality_manager_headers)
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert customer["credit_hold"] is False
        assert customer["status"] == "ACTIVE"
        assert customer["version"] == 1

        fetched = validate_success(api.get_customer(customer["id"],
                                                    quality_manager_headers))
        assert fetched["credit_hold"] is False
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == 1

    def test_create_customer_missing_legal_name_rejected(
            self, api, quality_manager_headers):
        """PRD §3.1: "A `QualityManager` onboards a customer by supplying its
        `legal_name`" — the name is required input; PRD §5 binds
        `ERR_INVALID_REQUEST` to 400 Bad Request.

        Design: Corner/entities/create_customer_missing_legal_name_returns_invalid_request
        """
        resp = api.create_customer({"credit_hold": False},
                                   quality_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_customer_returns_not_found(
            self, api, quality_manager_headers):
        """PRD §2.9: "The first identifier that does not resolve to an existing
        resource yields `ERR_NOT_FOUND` (HTTP 404), and no further checks run."

        Design: Corner/entities/get_nonexistent_customer_returns_not_found
        """
        resp = api.get_customer(NON_EXISTENT_UUID, quality_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestConsignmentLotIntake:
    def test_lot_computed_quantities_initialized(self, api):
        """PRD §3.4: "A freshly received lot starts with `quantity_kg_on_hand`
        equal to `quantity_kg_received` and `quantity_kg_committed` equal to
        zero." PRD §3.4: "The spendable balance `quantity_kg_available` is then
        `quantity_kg_on_hand` minus `quantity_kg_committed`."

        Design: Corner/entities/raw_material_lot_computed_quantities_initialized
        """
        customer = create_customer("Init Corp")
        resp = api.create_lot(
            customer["id"],
            {"material_code": "X", "ghS_class": "NON_HAZ",
             "quantity_kg_received": 250.5, "storage_zone": "Z_GENERAL",
             "received_at": "2026-08-01T00:00:00Z"},
            SCHED)
        lot = validate_success(resp, 201)
        assert_lot(lot)
        assert lot["quantity_kg_on_hand"] == 250.5
        assert lot["quantity_kg_committed"] == 0
        assert lot["quantity_kg_available"] == 250.5

    def test_flammable_lot_into_acid_zone_rejected(self, api):
        """PRD §3.4: "Intake is itself a segregation checkpoint: the lot's
        class must be one the chosen zone admits under the zone map of §2.6,
        or the receipt is rejected with `ERR_INCOMPATIBLE_SEGREGATION`."
        PRD §2.6: "`Z_ACID` only `ACID`".

        Design: Corner/entities/lot_with_invalid_storage_zone_for_ghs_returns_incompatible_segregation
        """
        customer = create_customer("ZoneTest Inc")
        resp = api.create_lot(
            customer["id"],
            {"material_code": "GAS", "ghS_class": "FLAMMABLE",
             "quantity_kg_received": 100, "storage_zone": "Z_ACID",
             "received_at": "2026-08-01T00:00:00Z"},
            SCHED)
        validate_error(resp, ApiErrorId.ERR_INCOMPATIBLE_SEGREGATION)


class TestRoleBasedAccessControl:
    def test_tank_operator_cannot_create_customer(self, api,
                                                  tank_operator_headers):
        """PRD §2.1: "A `QualityManager` owns customers, pricing agreements,
        recipes, tank registration, and the logical clock." PRD §2.1:
        "A request whose role is not permitted for the targeted operation is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/endpoints/tank_operator_cannot_create_customer
        """
        resp = api.create_customer({"legal_name": "Denied"},
                                   tank_operator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_qa_validator_cannot_release_batch(self, api, qa_validator_headers):
        """PRD §2.1: "A `BatchScheduler` owns raw-material lot intake and
        batch-job intake, release, and cancellation." PRD §2.1: "A request
        whose role is not permitted for the targeted operation is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/endpoints/qa_validator_cannot_release_batch
        """
        ctx = setup_batch_context()
        resp = api.release_batch_job(ctx["customer"]["id"], ctx["batch"]["id"],
                                     ctx["batch"]["version"],
                                     qa_validator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_sds_author_cannot_validate_cleaning(self, api, sds_author_headers):
        """PRD §2.1: "A `QAValidator` validates cleaning records and completes
        or rejects batches, and is deliberately segregated from the
        `TankOperator` who performed the work." PRD §2.1: "A request whose
        role is not permitted for the targeted operation is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/endpoints/sds_author_cannot_validate_cleaning
        """
        tank = create_tank()
        record = open_cleaning_record(tank["id"])
        submit_cleaning_record(tank["id"], record["id"])
        resp = api.validate_cleaning_record(tank["id"], record["id"], "PASS",
                                            sds_author_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
