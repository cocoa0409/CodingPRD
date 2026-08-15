"""API-wide discipline: envelope, pagination, errors, RBAC, clock, versioning."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, plan_batch, blend_and_record,
    qa_verdict, place_order, quote_run,
    make_customer_contact_headers, make_product_developer_headers,
    make_label_reviewer_headers, make_blend_operator_headers,
    make_qa_inspector_headers, make_finance_clerk_headers,
    make_production_planner_headers, make_warehouse_lead_headers,
    make_customer_service_rep_headers, make_plant_manager_headers,
    DEV_USER, REV_USER, OP_USER, QA_USER,
)

PM = TEST_USERS["plant_manager_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
DEV = TEST_USERS["product_developer_headers"]
REV = TEST_USERS["label_reviewer_headers"]
OP = TEST_USERS["blend_operator_headers"]
QA = TEST_USERS["qa_inspector_headers"]
PLAN = TEST_USERS["production_planner_headers"]
WH = TEST_USERS["warehouse_lead_headers"]
CSR = TEST_USERS["customer_service_rep_headers"]


class TestPaginationAndEnvelope:
    def test_list_pagination_defaults_and_meta(self, api):
        """PRD §2.3: "The `limit` parameter bounds the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter states how many items to skip and defaults to 0. ... The `meta`
        object of a list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/list_pagination_and_envelope_shape
        """
        for i in range(11):
            get_success_data(api.create_container_lot(
                factories.create_container_lot_payload(
                    container_type="CAN_330", quantity_received=100,
                    supplier_lot_code=f"SUP-PG-{i + 1:02d}"), WH))
        data, meta = validate_paginated(api.list_container_lots(PM))
        assert len(data) == 10
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        page2, meta2 = validate_paginated(api.list_container_lots(PM, params={"offset": 10}))
        assert len(page2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False

    def test_error_envelope_shape(self, api):
        """PRD §2.2: the error body carries "response_type": "error" and a `data`
        object whose `error_id` is "a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/list_pagination_and_envelope_shape
        """
        resp = api.get_container_lot(NON_EXISTENT_UUID, PM)
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_CONTAINER_LOT_NOT_FOUND"
        assert resp.status_code == 404


class TestFkReverseListings:
    def test_reverse_listings_reachable(self, api):
        """PRD §3.1: "each account exposes reverse listings of its production
        runs, its shipment orders, and its pallet account — the last returned as
        an array holding zero or one element." and §3.3: "each tank exposes a
        reverse listing of its batches." and §3.5: "Each batch exposes reverse
        listings of the process runs executed against it and of the production
        runs that have been linked to it."

        Design: Corner/endpoints/fk_reverse_reachability_arrays
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        blend_and_record(batch["id"], 12.1)
        qa_verdict(batch["id"], "PASS")
        prun = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
        run = quote_run(customer["id"], formula["id"])
        order = place_order(customer["id"], formula["id"], channel="DIRECT_RETAIL",
                            requested_delivery_date="2026-08-15", units_requested=100)
        pallet_accounts = get_success_data(api.get_customer_pallet_account(customer["id"], PM))
        assert isinstance(pallet_accounts, list) and len(pallet_accounts) == 1
        runs = get_success_data(api.list_customer_production_runs(customer["id"], PM))
        assert [r["id"] for r in runs] == [run["id"]]
        orders = get_success_data(api.list_customer_shipment_orders(customer["id"], PM))
        assert [o["id"] for o in orders] == [order["id"]]
        formulas = get_success_data(api.list_formulas(PM, params={"customer_id": customer["id"]}))
        assert [f["id"] for f in formulas] == [formula["id"]]
        batches = get_success_data(api.list_tank_batches(tank["id"], PM))
        assert [b["id"] for b in batches] == [batch["id"]]
        pruns = get_success_data(api.list_batch_process_runs(batch["id"], PM))
        assert [p["id"] for p in pruns] == [prun["id"]]
        # nothing linked to the batch yet; no ledger entries posted yet
        assert get_success_data(api.list_batch_production_runs(batch["id"], PM)) == []
        entries = get_success_data(api.list_pallet_entries(pallet_accounts[0]["id"], PM))
        assert entries == []


class TestNotFoundSweep:
    @pytest.mark.parametrize("getter,error_id", [
        ("get_customer", ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        ("get_formula", ApiErrorId.ERR_FORMULA_NOT_FOUND),
        ("get_label_review", ApiErrorId.ERR_LABEL_REVIEW_NOT_FOUND),
        ("get_tank", ApiErrorId.ERR_TANK_NOT_FOUND),
        ("get_batch", ApiErrorId.ERR_BATCH_NOT_FOUND),
        ("get_process_run", ApiErrorId.ERR_PROCESS_RUN_NOT_FOUND),
        ("get_container_lot", ApiErrorId.ERR_CONTAINER_LOT_NOT_FOUND),
        ("get_line", ApiErrorId.ERR_LINE_NOT_FOUND),
        ("get_production_run", ApiErrorId.ERR_PRODUCTION_RUN_NOT_FOUND),
        ("get_finished_lot", ApiErrorId.ERR_LOT_NOT_FOUND),
        ("get_zone", ApiErrorId.ERR_ZONE_NOT_FOUND),
        ("get_shipment_order", ApiErrorId.ERR_SHIPMENT_ORDER_NOT_FOUND),
        ("get_pallet_account", ApiErrorId.ERR_PALLET_ACCOUNT_NOT_FOUND),
    ])
    def test_get_unknown_id_returns_domain_404(self, api, getter, error_id):
        """PRD §2.6: "Resource identifiers in the path are validated strictly left
        to right, and the first miss surfaces as that resource's not-found error:
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`,
        `ERR_LABEL_REVIEW_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
        `ERR_PROCESS_RUN_NOT_FOUND`, `ERR_CONTAINER_LOT_NOT_FOUND`,
        `ERR_LINE_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_ZONE_NOT_FOUND`, `ERR_SHIPMENT_ORDER_NOT_FOUND`, or
        `ERR_PALLET_ACCOUNT_NOT_FOUND`."

        Design: Corner/entities/not_found_reads_across_entities
        """
        resp = getattr(api, getter)(NON_EXISTENT_UUID, PM)
        validate_error(resp, error_id)
        assert resp.status_code == 404


class TestInvalidRequestSweep:
    def test_missing_fields_and_bad_enums_rejected(self, api):
        """PRD §2.6: "payloads that are malformed in a basic sense — a missing
        required field, a value of the wrong type, or an enum member outside its
        documented set — are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/required_fields_and_enum_validation
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        # missing credit_limit_cents
        resp = api.create_customer(
            {"name": "NoLimit", "minimum_run_units": 100, "pallet_deposit_cents": 2000}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        # process_type outside its documented set
        resp = api.create_formula(
            factories.create_formula_payload(customer["id"], process_type="ULTRA"), DEV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # channel outside its documented set
        resp = api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer["id"], formula["id"], channel="WHOLESALE",
                requested_delivery_date="2026-08-15", units_requested=100), CSR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # missing tank_id
        payload = factories.create_batch_payload(formula["id"], "placeholder")
        payload.pop("tank_id")
        resp = api.create_batch(payload, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestHeaderValidation:
    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request missing either header, or carrying an empty
        value for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/empty_user_context_header_rejected
        """
        bad_headers = {"X-User-ID": "", "X-User-Role": "PlantManager",
                       "Content-Type": "application/json"}
        resp = api.create_customer(factories.create_customer_payload(), bad_headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400
        # control: a normal opaque PlantManager context succeeds
        ok = validate_success(api.create_customer(factories.create_customer_payload(), PM), 201)
        assert ok["status"] == "PENDING_CREDIT"


class TestRoleDenial:
    def test_role_denial_beats_existence(self, api):
        """PRD §2.6: "a request whose role is wrong never reaches the existence
        checks."

        Design: Corner/validations/role_denial_beats_existence_check
        """
        # QAInspector is not listed on approve-credit; the id does not even exist
        resp = api.approve_credit(NON_EXISTENT_UUID, QA)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403
        # BlendOperator is not listed on confirm
        resp = api.confirm_run(NON_EXISTENT_UUID, OP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403

    def test_role_denial_sweep_on_exclusive_operations(self, api):
        """PRD §2.1: "Attempting an operation outside one's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/role_denial_sweep_on_exclusive_operations
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        order = place_order(customer["id"], formula["id"], channel="DIRECT_RETAIL",
                            requested_delivery_date="2026-08-15", units_requested=100)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        denials = [
            # FinanceClerk cannot create formulas
            api.create_formula(factories.create_formula_payload(customer["id"]), FIN),
            # ProductDeveloper cannot approve credit
            api.approve_credit(customer["id"], DEV),
            # PlantManager cannot post payments
            api.post_payment(customer["id"], {"amount_cents": 100}, PM),
            # BlendOperator cannot give QA verdicts
            api.qa_verdict(batch["id"], {"verdict": "PASS"}, OP),
            # QAInspector cannot record blends
            api.record_blend(batch["id"], {"measured_brix": 12.0}, QA),
            # ProductionPlanner cannot allocate orders
            api.allocate_order(order["id"],
                               {"expected_shipment_order_version": order["version"]}, PLAN),
            # WarehouseLead cannot run ops epochs
            api.post_ops_run(WH),
            # CustomerServiceRep cannot pick
            api.pick_order(order["id"], CSR),
            # LabelComplianceReviewer cannot submit label reviews
            api.submit_label_review(
                formula["id"], {"expected_formula_version": formula["version"]}, REV),
        ]
        for resp in denials:
            validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
            assert resp.status_code == 403


class TestCustomerContactScope:
    def test_contact_scoped_to_own_customer(self, api):
        """PRD §2.1: "When `X-User-Role` is `CustomerContact`, the `X-User-ID` is
        the `id` of the acting `CustomerAccount`; ownership checks on any resource
        that references a customer compare the resource's `customer_id` field to
        `X-User-ID`, and a `CustomerContact` attempting to act for any other
        customer is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/customer_contact_ownership_scope
        """
        customer_a = create_customer(name="OwnA")
        customer_b = create_customer(name="OwnB")
        formula_a = create_formula(customer_a["id"], approve=False)
        formula_b = create_formula(customer_b["id"], approve=False)
        own = get_success_data(api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_a["id"], formula_a["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-15", units_requested=100),
            make_customer_contact_headers(customer_a["id"])))
        assert own["status"] == "PLACED"
        resp = api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_b["id"], formula_b["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-15", units_requested=100),
            make_customer_contact_headers(customer_a["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403
        # a CustomerServiceRep is not ownership-scoped
        via_csr = get_success_data(api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_b["id"], formula_b["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-15", units_requested=100), CSR))
        assert via_csr["status"] == "PLACED"


class TestVersionIncrements:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` (integer): a system-managed counter that
        increments by one on every mutation, including mutations the server
        applies itself as side effects of another operation."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        customer = get_success_data(api.create_customer(
            factories.create_customer_payload(), PM))
        v0 = customer["version"]
        approved = get_success_data(api.approve_credit(customer["id"], FIN))
        assert approved["version"] == v0 + 1
        suspended = get_success_data(api.suspend_customer(customer["id"], FIN))
        assert suspended["version"] == approved["version"] + 1
        lot = get_success_data(api.create_container_lot(
            factories.create_container_lot_payload(
                container_type="PET_1000", quantity_received=900,
                supplier_lot_code="SUP-VER"), WH))
        verdict = get_success_data(api.container_qc_verdict(lot["id"], {"verdict": "PASS"}, QA))
        assert verdict["version"] == lot["version"] + 1


class TestLogicalClock:
    def test_default_clock_and_regression(self, api):
        """PRD §2.4: "Before any clock-setting call, the clock reads exactly
        2026-08-01T00:00:00Z. A `PlantManager` advances it by supplying
        `to_iso8601`; the supplied instant must be at or after the current reading
        — setting an earlier instant is rejected with `ERR_CLOCK_REGRESSION` — and
        the response reports the resulting `current_utc`."

        Design: Corner/cross_cutting_layers/logical_clock_default_and_regression
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        # 2026-07-31 precedes the untouched clock's date; 2026-08-01 does not —
        # together they pin the default reading to 2026-08-01
        resp = api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer["id"], formula["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-07-31", units_requested=100), CSR)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_DATE_IN_PAST)
        ok = get_success_data(api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer["id"], formula["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-01", units_requested=100), CSR))
        assert ok["status"] == "PLACED"
        # setting to the same instant twice is allowed (never moves backwards)
        c1 = get_success_data(api.set_clock({"to_iso8601": "2026-08-05T00:00:00Z"}, PM))
        c2 = get_success_data(api.set_clock({"to_iso8601": "2026-08-05T00:00:00Z"}, PM))
        assert c1["current_utc"] == c2["current_utc"]
        assert "2026-08-05" in c1["current_utc"]
        resp = api.set_clock({"to_iso8601": "2026-08-04T00:00:00Z"}, PM)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
        assert resp.status_code == 422


class TestImmediateVisibility:
    def test_mutation_responses_carry_updated_resource(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." and §3.3: "Recording the blend (`BLENDING` → `AWAITING_QA`)
        captures the measured sugar content into `measured_brix` and stamps
        `blended_by_user_id` with the acting operator"

        Design: Corner/consistency_model/immediate_visibility_in_mutation_responses
        """
        customer = get_success_data(api.create_customer(
            factories.create_customer_payload(), PM))
        approved = get_success_data(api.approve_credit(customer["id"], FIN))
        assert approved["status"] == "ACTIVE"
        assert approved["version"] == customer["version"] + 1
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        get_success_data(api.start_blend(batch["id"], OP))
        recorded = get_success_data(api.record_blend(batch["id"], {"measured_brix": 12.1}, OP))
        assert recorded["status"] == "AWAITING_QA"
        assert recorded["measured_brix"] == 12.1
        assert recorded["blended_by_user_id"] == OP_USER
