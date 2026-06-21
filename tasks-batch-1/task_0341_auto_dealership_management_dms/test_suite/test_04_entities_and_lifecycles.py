"""CRUD, creation defaults, immutability, and state-machine corner cases.

Corner queue (B) sections: entities, state_machines.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, fixtures,
    assert_vehicle, assert_deal, assert_deal_jacket_document,
)
from test_helpers import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]
TITLE = TEST_USERS["title_clerk_headers"]


# ===========================================================================
# entities
# ===========================================================================
class TestEntityCreation:
    def test_vehicle_create_returns_201_with_system_fields(self, api):
        """PRD §3.1: "A new vehicle is born in status `AVAILABLE`."
        PRD §2.4: "a `version`, an integer that begins at 1 on creation and
        increments by one on every mutation."

        Design: Corner/entities/vehicle_create_returns_201_with_system_fields
        """
        veh = validate_success(api.create_vehicle(f.create_vehicle_payload(
            condition="NEW", make="ACME", model="SED", model_year=2026,
            msrp_cents=2200000, list_price_cents=2000000), INV), expected_status=201)
        assert_vehicle(veh)
        assert veh["status"] == "AVAILABLE"
        assert veh["version"] == 1

    def test_vehicle_get_not_found_returns_404(self, api):
        """PRD §2.6: "The system validates path identifiers left to right: the
        deal in the path must resolve before the product line under it is
        considered, and the first identifier that does not resolve produces
        `ERR_NOT_FOUND`."

        Design: Corner/entities/vehicle_get_not_found_returns_404
        """
        resp = api.get_vehicle(NON_EXISTENT_UUID, INV)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_vehicle_create_missing_required_vin_returns_422(self, api):
        """PRD §2.8: "Request well-formedness is checked next — required fields
        present, enum values valid, a VIN exactly 17 characters, and numeric
        fields within their declared ranges — with violations yielding
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/vehicle_create_missing_required_vin_returns_422
        """
        payload = f.create_vehicle_payload(condition="NEW", make="ACME", model="SED",
                                           model_year=2026, msrp_cents=2200000, list_price_cents=2000000)
        payload.pop("vin")
        resp = api.create_vehicle(payload, INV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_vehicle_create_bad_vin_length_returns_422(self, api):
        """PRD §3.1: "A `vin` must be exactly 17 characters of uppercase
        alphanumerics excluding the letters I, O, and Q; a malformed VIN is an
        `ERR_INVALID_REQUEST`, and a VIN that already exists in inventory is
        rejected with `ERR_VIN_DUPLICATE`."

        Design: Corner/entities/vehicle_create_bad_vin_length_returns_422
        """
        resp = api.create_vehicle(f.create_vehicle_payload(
            vin="SHORTVIN", condition="NEW", make="ACME", model="SED",
            model_year=2026, msrp_cents=2200000, list_price_cents=2000000), INV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_vehicle_create_bad_condition_enum_returns_422(self, api):
        """PRD §2.8: "Request well-formedness is checked next — required fields
        present, enum values valid, a VIN exactly 17 characters, and numeric
        fields within their declared ranges — with violations yielding
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/vehicle_create_bad_condition_enum_returns_422
        """
        resp = api.create_vehicle(f.create_vehicle_payload(
            condition="SALVAGE", make="ACME", model="SED", model_year=2026,
            msrp_cents=2200000, list_price_cents=2000000), INV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_vehicle_duplicate_vin_returns_409(self, api):
        """PRD §3.1: "A `vin` must be exactly 17 characters of uppercase
        alphanumerics excluding the letters I, O, and Q; a malformed VIN is an
        `ERR_INVALID_REQUEST`, and a VIN that already exists in inventory is
        rejected with `ERR_VIN_DUPLICATE`."

        Design: Corner/entities/vehicle_duplicate_vin_returns_409
        """
        vin = f.unique_vin()
        get_success_data(api.create_vehicle(f.create_vehicle_payload(
            vin=vin, condition="NEW", make="ACME", model="SED", model_year=2026,
            msrp_cents=2200000, list_price_cents=2000000), INV))
        resp = api.create_vehicle(f.create_vehicle_payload(
            vin=vin, condition="USED", make="ACME", model="CPE", model_year=2024,
            msrp_cents=1800000, list_price_cents=1600000), INV)
        validate_error(resp, ApiErrorId.ERR_VIN_DUPLICATE.value)

    def test_deal_create_fk_not_found_returns_404(self, api):
        """PRD §2.6: "foreign keys supplied in a request body — such as
        `vehicle_id`, `customer_id`, `deal_id`, `finance_product_id`, or
        `lender_program_id` — must reference existing resources; a body foreign
        key that points at nothing is rejected with `ERR_FK_NOT_FOUND`."

        Design: Corner/entities/deal_create_fk_not_found_returns_404
        """
        cust = fixtures.create_customer(credit_tier="TIER_B")
        resp = api.create_deal(f.create_deal_payload(
            NON_EXISTENT_UUID, cust["id"], deal_type="FINANCE",
            sale_price_cents=2000000, tax_rate_bps=725), SALES)
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)

    def test_deal_computed_defaults_zero_on_create(self, api):
        """PRD §3.3: "A deal opens in status `DRAFT`, with version 1 and all
        computed totals defaulting to zero."

        Design: Corner/entities/deal_computed_defaults_zero_on_create
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        deal = validate_success(api.create_deal(f.create_deal_payload(
            veh["id"], cust["id"], deal_type="FINANCE", sale_price_cents=2000000,
            tax_rate_bps=725), SALES), expected_status=201)
        assert_deal(deal)
        assert deal["status"] == "DRAFT"
        assert deal["rebate_cents"] == 0
        assert deal["fi_products_total_cents"] == 0
        assert deal["trade_equity_cents"] == 0

    def test_dealjacketdocument_immutable_no_version_field(self, api):
        """PRD §2.4: "A deal-jacket document carries only an `id` and a
        `created_at`; it has neither an `updated_at` nor a `version` field,
        because once written it is never modified."

        Design: Corner/entities/dealjacketdocument_immutable_no_version_field
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        doc = validate_success(api.upload_document(
            deal["id"], {"doc_type": "CREDIT_APP", "uri": "s3://j/doc.pdf"}, SALES), expected_status=201)
        assert_deal_jacket_document(doc)


# ===========================================================================
# state_machines
# ===========================================================================
class TestStateMachines:
    def test_deal_initial_state_is_draft(self, api):
        """PRD §3.3: "A deal opens in status `DRAFT`, with version 1 and all
        computed totals defaulting to zero."

        Design: Corner/state_machines/deal_initial_state_is_draft
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        deal = validate_success(api.create_deal(f.create_deal_payload(
            veh["id"], cust["id"], deal_type="FINANCE", sale_price_cents=2000000,
            tax_rate_bps=725), SALES), expected_status=201)
        assert deal["status"] == "DRAFT"

    def test_deal_submit_to_lender_from_draft_invalid_state(self, api):
        """PRD §3.5: "A `SalesManager` submits a desked deal to the lender,
        advancing `DESKING → SUBMITTED_TO_LENDER`."
        PRD §2.8: "state-transition legality (`ERR_INVALID_STATE` when the target
        is not in a state from which the requested transition is defined)".

        Design: Corner/state_machines/deal_submit_to_lender_from_draft_invalid_state
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        resp = api.submit_to_lender(deal["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_deal_terminal_dead_lockdown(self, api):
        """PRD §3.3: "A deal may be killed from `DRAFT` (transitioning
        `DRAFT → DEAD` with only a version bump) or from `DESKING` (transitioning
        `DESKING → DEAD`)".
        PRD §2.8: "state-transition legality (`ERR_INVALID_STATE` when the target
        is not in a state from which the requested transition is defined)".

        Design: Corner/state_machines/deal_terminal_dead_lockdown
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        get_success_data(api.kill_deal(deal["id"], SALES))
        resp = api.desk_deal(deal["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_testdrive_complete_twice_invalid_state(self, api):
        """PRD §3.2: "A completion or cancellation attempted on a drive that is
        not `SCHEDULED` is an `ERR_INVALID_STATE`."

        Design: Corner/state_machines/testdrive_complete_twice_invalid_state
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B", drivers_license_valid=True)
        td = get_success_data(api.book_test_drive(
            {"vehicle_id": veh["id"], "customer_id": cust["id"],
             "start_at": "2026-06-20T09:00:00.000Z", "end_at": "2026-06-20T09:30:00.000Z"}, SALES))
        get_success_data(api.complete_test_drive(td["id"], SALES))
        resp = api.complete_test_drive(td["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_title_dmv_reject_missing_reason_returns_422(self, api):
        """PRD §3.7: "A rejection advances `SUBMITTED → REJECTED`: the request
        must carry a `rejection_reason`, or it is rejected with
        `ERR_REJECTION_REASON_REQUIRED`".

        Design: Corner/state_machines/title_dmv_reject_missing_reason_returns_422
        """
        ctx = fixtures.create_submitted_title(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725))
        resp = api.dmv_result(ctx["title_registration_id"], {"result": "REJECT"}, TITLE)
        validate_error(resp, ApiErrorId.ERR_REJECTION_REASON_REQUIRED.value)

    def test_recondition_complete_from_available_invalid_state(self, api):
        """PRD §3.1: "Once the work is done, an `InventoryClerk` marks
        reconditioning complete, transitioning the vehicle `RECON → AVAILABLE`
        and incrementing the vehicle's `version` by one, after which the car can
        be listed and sold like any other."
        PRD §2.8: "state-transition legality (`ERR_INVALID_STATE` when the target
        is not in a state from which the requested transition is defined)".

        Design: Corner/state_machines/recondition_complete_from_available_invalid_state
        """
        veh = fixtures.create_vehicle(condition="USED", model="CPE", model_year=2023,
                                      msrp_cents=1800000, list_price_cents=1600000)
        resp = api.recondition_complete(veh["id"], INV)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_unwind_blocked_by_accepted_title(self, api):
        """PRD §3.6: "Unwind is blocked if any title registration for the deal has
        reached `ACCEPTED`: in that case the request is rejected with
        `ERR_TITLE_ALREADY_ACCEPTED`, because the state has already perfected the
        title."

        Design: Corner/state_machines/unwind_blocked_by_accepted_title
        """
        ctx = fixtures.create_submitted_title(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725))
        get_success_data(api.dmv_result(ctx["title_registration_id"], {"result": "ACCEPT"}, TITLE))
        resp = api.unwind_deal(ctx["deal_id"], FIN)
        validate_error(resp, ApiErrorId.ERR_TITLE_ALREADY_ACCEPTED.value)
