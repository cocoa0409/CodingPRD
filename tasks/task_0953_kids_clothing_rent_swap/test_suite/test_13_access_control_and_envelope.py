"""Authentication, role denial, the existence rungs and the response envelope."""

from test_helpers import (
    ADMIN,
    BILLING,
    GRADER,
    LOGISTICS,
    PLANNER,
    WAREHOUSE,
    ApiErrorId,
    allocate_unit,
    create_box,
    create_open_cycle,
    create_plan,
    create_plan_payload,
    create_shipping_label_payload,
    create_style,
    create_unit,
    get_box,
    get_unit,
    make_grader_headers,
    make_member_headers,
    make_role_headers,
    set_clock,
    setup_plan_and_member,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}


class TestAuthenticationRungs:
    def test_a_request_with_no_identity_headers_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to every endpoint — reads included — must
        carry two headers: `X-User-ID` and `X-User-Role`. If either header is
        absent or present but empty, the request is refused with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6 rung 1: "`X-User-Role` and `X-User-ID` are both present and
        non-empty. Otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/corner_err_missing_user_headers_returns_unauthenticated
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.list_plans(NO_IDENTITY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_an_undeclared_role_name_is_rejected_before_any_permission_check(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the
        eight role names below, the request is refused with `ERR_UNKNOWN_ROLE`
        (HTTP 401)."
        PRD §2.1: "The eight declared roles are `PlatformAdmin`, `Member`,
        `WarehouseOperator`, `GradingTechnician`, `CleaningVendor`,
        `LogisticsCoordinator`, `BillingAgent`, and `MerchandisePlanner`."

        Design: Corner/errors/corner_err_unknown_role_header_is_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.list_plans(make_role_headers("Courier", "courier-1"))
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)


class TestExistenceRungs:
    def test_an_unknown_cycle_identifier_is_not_found(self, api):
        """PRD §2.6 rung 7: "The `Cycle`, `Box` or `BoxItem` identifier in the
        path resolves, validated left-to-right. Otherwise
        `ERR_CYCLE_NOT_FOUND` (404). Applies to all cycle, box and box-item
        endpoints."

        Design: Corner/errors/corner_err_cycle_not_found_on_unknown_path_id
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_cycle_invoice("12121212-3434-5656-7878-909090909090", BILLING)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)

    def test_an_unknown_trade_in_identifier_is_not_found(self, api):
        """PRD §2.6 rung 10: "The `TradeInSubmission` or `TradeInItem` identifier
        in the path resolves. Otherwise `ERR_TRADE_IN_NOT_FOUND` (404). Applies
        to trade-in endpoints."

        Design: Corner/errors/corner_err_trade_in_not_found_on_unknown_path_id
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_trade_in_submission("13131313-2424-3535-4646-575757575757", ADMIN)
        validate_error(resp, ApiErrorId.ERR_TRADE_IN_NOT_FOUND.value, 404)

    def test_an_unknown_assessment_identifier_is_not_found(self, api):
        """PRD §2.6 rung 11: "The `ConditionAssessment` or `ProcessingJob`
        identifier in the path resolves. Otherwise `ERR_ASSESSMENT_NOT_FOUND`
        (404). Applies to condition-assessment and processing-job endpoints."

        Design: Corner/errors/corner_err_assessment_not_found_on_unknown_path_id
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_condition_assessment("14141414-2525-3636-4747-585858585858",
                                            make_grader_headers("grader-nf"))
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value, 404)

    def test_an_unknown_capsule_identifier_uses_the_generic_resource_code(self, api):
        """PRD §2.6 rung 12: "The `Capsule`, `CapsuleAllocation`, `BuyOutOrder`,
        `PauseRequest`, `LostShipmentClaim`, `CreditLedgerEntry` or
        `ChargeLedgerEntry` identifier in the path resolves. Otherwise
        `ERR_RESOURCE_NOT_FOUND` (404). Applies to capsule, allocation,
        buy-out, pause, claim and ledger endpoints."

        Design: Corner/errors/corner_err_resource_not_found_on_unknown_capsule_id
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_capsule("15151515-2626-3737-4848-595959595959", PLANNER)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)


class TestRoleDenial:
    def test_a_household_may_not_author_a_plan(self, api):
        """PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "Commercial terms live on a **plan**, and a plan is authored by
        a `PlatformAdmin`."

        Design: Corner/rbac/corner_rbac_member_cannot_create_a_plan
        """
        _, member = setup_plan_and_member()
        resp = api.create_plan(
            create_plan_payload(tier="PLUS", slots_per_box=5, swaps_per_cycle=3,
                                monthly_fee_cents=9900),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)
        _, meta = validate_paginated(api.list_plans(ADMIN, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 1

    def test_a_warehouse_operator_may_not_mint_a_shipping_label(self, api):
        """PRD §2.1: "A `LogisticsCoordinator` mints, voids, expires and reissues
        shipping labels; creates, departs, marks-lost and returns shipments;
        ships packed boxes; attaches inbound labels to trade-in submissions; and
        runs lost-shipment claims up to the approve/deny fork."
        PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_warehouse_operator_cannot_mint_a_label
        """
        _, member = setup_plan_and_member()
        resp = api.create_shipping_label(
            create_shipping_label_payload(member["id"], "OUTBOUND"), WAREHOUSE
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)
        _, meta = validate_paginated(api.list_shipping_labels(LOGISTICS,
                                                              {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_a_billing_agent_may_not_allocate_stock_into_a_box(self, api):
        """PRD §2.1: "A `BillingAgent` runs the money side: late assessment, cycle
        closing, the credit and charge ledgers, trade-in finalisation, buy-out
        payment, pause activation and claim settlement."
        PRD §3.3: "Allocation is a `WarehouseOperator` action against an `OPEN`
        cycle's `DRAFT` box, and it takes either an explicit `unit_id` or a
        `style_id` that hands the choice to the box-fill selector."

        Design: Corner/rbac/corner_rbac_billing_agent_cannot_confirm_a_grade_or_allocate
        """
        _, member = setup_plan_and_member()
        style = create_style(sku="SKU-R5-5", name="Billing Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])

        resp = api.allocate_into_box(box["id"], {"unit_id": unit["id"]}, BILLING)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)
        assert get_unit(unit["id"])["state"] == "IN_STOCK"
        assert get_box(box["id"])["slots_free"] == 1

    def test_a_merchandise_planner_may_not_drive_the_logical_clock(self, api):
        """PRD §2.1: "A `PlatformAdmin` operates the platform itself: it authors
        plans, registers and activates members, schedules cycles, opens them,
        closes the swap window, applies the default disposition to an un-elected
        trade-in garment, denies pause requests, and drives the logical clock."
        PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_merchandise_planner_cannot_run_the_clock
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.set_clock("2027-01-01T00:00:00Z", PLANNER)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)


class TestResponseEnvelope:
    def test_the_success_and_error_envelopes_carry_their_declared_shapes(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/consistency_model/corner_consistency_response_envelope_shape_on_success_and_error
        """
        plan = create_plan()

        ok = api.get_plan(plan["id"], ADMIN)
        body = ok.json()
        assert ok.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["data"]["tier"] == "CORE"

        missing = api.get_plan("99999999-8888-7777-6666-555555555555", ADMIN)
        error_body = missing.json()
        assert missing.status_code == 404
        assert error_body["response_type"] == "error"
        error = validate_error(missing, ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)
        assert isinstance(error["message"], str) and error["message"].strip()
