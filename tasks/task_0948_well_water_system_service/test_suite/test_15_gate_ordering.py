"""The nine-gate global write order, probed one adjacent pair at a time."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    assert_money,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def _credit_hold_world():
    """An account on credit hold and a second quote left in DRAFT."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Quarry Ridge Co",
        email="ap@quarryridge.example",
        membership_tier="NONE",
        address_line="1 Quarry Ridge",
        distance_miles=8.0,
        household_size=2,
        depth_feet=400.0,
        drawdown=8.0,
        technician_name="Mira Solis",
    )
    part = fixtures.new_part("CTL-500000", "CONTROL", 500000, on_hand_qty=5)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 16.0, 60.0, 8.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 2,
        "REPAIR", 60, "2026-06-03T12:00:00Z", "JOURNEYMAN",
    )
    fixtures.approve_quote(staged["quote_id"], world["account_id"])
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        quote_id=staged["quote_id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-03T12:00:00Z", "2026-06-03T14:00:00Z"
    )
    fixtures.set_clock("2026-06-03T12:00:00Z")
    fixtures.start_work_order(work_order["id"], world["technician_id"])
    fixtures.post_parts(work_order["id"], world["technician_id"], part["id"], 2)
    fixtures.complete_work_order(work_order["id"], world["technician_id"], 60)
    fixtures.issue_invoice(fixtures.first_invoice_of(work_order["id"])["id"])

    second = fixtures.new_quote(
        world["property_id"], world["well_id"], inspection["id"], "REPAIR", 60,
        "2026-06-04T12:00:00Z", "JOURNEYMAN",
    )
    world["second_quote_id"] = second["id"]
    return world


def test_the_state_gate_answers_before_the_credit_hold_gate(api):
    """PRD 2.6: "A request that violates several gates is answered with the error of the
    lowest-numbered gate it violates, and no later gate is evaluated."
    PRD 2.6: "5. **G5 — Entity state.** The addressed row's stored state satisfies the
    requested transition's originating state, **on every axis the transition touches**.
    Failure: that entity's invalid-state error."
    PRD 3.6: "The owning account's `credit_hold` must be false, or the answer is
    `ERR_ACCOUNT_ON_CREDIT_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_credit_hold_on_quote_approve
    """
    world = _credit_hold_world()
    validate_error(
        api.approve_quote(world["second_quote_id"], world["customer_headers"]),
        ApiErrorId.ERR_QUOTE_INVALID_STATE.value,
        409,
    )


def test_the_account_really_is_on_credit_hold_when_the_state_gate_wins(api):
    """PRD 2.12: "On every write that touches `balance_cents`, `credit_hold` is re-derived
    as true when `balance_cents` is **strictly greater** than `CREDIT_HOLD_THRESHOLD_CENTS`
    (500000 cents) and false otherwise; a balance of exactly 500000 does not put an account
    on hold."
    PRD 3.6: "The quote opens in `DRAFT` with `parts_subtotal_cents`,
    `labor_subtotal_cents`, `permit_fee_cents`, `tax_cents` and `total_cents` all 0, and
    `sent_at`, `approved_at` and `approved_total_cents` all null."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_credit_hold_on_quote_approve
    """
    world = _credit_hold_world()
    api.approve_quote(world["second_quote_id"], world["customer_headers"])

    account = fixtures.get_account(world["account_id"])
    assert_money(account["balance_cents"], 1275050, "Account.balance_cents")
    assert account["credit_hold"] is True

    quote = fixtures.get_quote(world["second_quote_id"])
    assert quote["status"] == "DRAFT"
    assert quote["approved_at"] is None


def test_every_single_resource_read_owns_its_entity_specific_not_found(api):
    """PRD 2.6: "Each identifier — whether it arrives as a path segment at G3 or as a body
    field at G9A — has exactly one error that answers a value which does not resolve to a
    stored row, and all of them are HTTP 404."
    PRD 2.6: "An unresolved `well_profile_id` is `ERR_WELL_PROFILE_NOT_FOUND`. An
    unresolved `shared_well_agreement_id` is `ERR_SHARED_WELL_AGREEMENT_NOT_FOUND`."

    Design: Corner/endpoints/corner_every_path_id_not_found_sweep
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    probes = [
        (api.get_well_profile, ApiErrorId.ERR_WELL_PROFILE_NOT_FOUND.value),
        (api.get_shared_well_agreement, ApiErrorId.ERR_SHARED_WELL_AGREEMENT_NOT_FOUND.value),
        (api.get_technician, ApiErrorId.ERR_TECHNICIAN_NOT_FOUND.value),
        (api.get_part_catalog_item, ApiErrorId.ERR_PART_CATALOG_ITEM_NOT_FOUND.value),
        (api.get_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND.value),
        (api.get_water_test, ApiErrorId.ERR_WATER_TEST_NOT_FOUND.value),
        (
            api.get_treatment_recommendation,
            ApiErrorId.ERR_TREATMENT_RECOMMENDATION_NOT_FOUND.value,
        ),
        (api.get_quote, ApiErrorId.ERR_QUOTE_NOT_FOUND.value),
        (api.get_quote_line, ApiErrorId.ERR_QUOTE_LINE_NOT_FOUND.value),
        (api.get_work_order, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value),
        (api.get_emergency_ticket, ApiErrorId.ERR_EMERGENCY_TICKET_NOT_FOUND.value),
        (api.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND.value),
        (
            api.get_parts_consumption_entry,
            ApiErrorId.ERR_PARTS_CONSUMPTION_ENTRY_NOT_FOUND.value,
        ),
        (api.get_warranty_coverage, ApiErrorId.ERR_WARRANTY_COVERAGE_NOT_FOUND.value),
        (api.get_callback_claim, ApiErrorId.ERR_CALLBACK_CLAIM_NOT_FOUND.value),
        (api.get_maintenance_plan, ApiErrorId.ERR_MAINTENANCE_PLAN_NOT_FOUND.value),
        (api.get_maintenance_visit, ApiErrorId.ERR_MAINTENANCE_VISIT_NOT_FOUND.value),
        (api.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND.value),
        (api.get_invoice_line, ApiErrorId.ERR_INVOICE_LINE_NOT_FOUND.value),
        (api.get_property, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value),
    ]
    for read, expected in probes:
        validate_error(read(UNKNOWN_UUID_ALT, ADMIN), expected, 404)


def test_an_unrecognised_role_outranks_both_the_role_and_the_path_gate(api):
    """PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the seven
    role names below spelled exactly, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD 2.6: "1. **G1 — Authentication.** `X-User-Role` is present and is one of the seven
    declared roles, and `X-User-ID` is present. Failure: `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/corner_error_unauthenticated_outranks_role_and_path_existence
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    validate_error(
        api.get_account(UNKNOWN_UUID, ANONYMOUS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_account(
            {
                "legal_name": "Should Not Exist",
                "billing_jurisdiction_code": "JUR_ALPHA",
                "contact_email": "nope@corner.example",
            },
            ANONYMOUS,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    rows, meta = validate_paginated(api.list_accounts(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_the_role_gate_answers_before_path_existence(api):
    """PRD 2.6: "2. **G2 — Role.** The declared role appears in the endpoint's
    authorised-role list. Failure: `ERR_UNAUTHORIZED`."
    PRD 2.6: "3. **G3 — Path existence.** Every `{id}` segment in the request *path*
    resolves to a stored row, validated left to right. Failure: the `*_NOT_FOUND` error of
    the entity that failed."
    PRD 4.21: "Roles: `BillingClerk`. Success: 200, the updated `Invoice` in `ISSUED` with
    `issued_at` stamped."

    Design: Corner/errors/corner_error_role_gate_outranks_path_existence
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    validate_error(
        api.issue_invoice(UNKNOWN_UUID, ESTIMATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.issue_invoice(UNKNOWN_UUID, BILLING),
        ApiErrorId.ERR_INVOICE_NOT_FOUND.value,
        404,
    )


def test_one_malformed_body_is_answered_by_whichever_higher_gate_it_trips(api):
    """PRD 2.6: "A request that violates several gates is answered with the error of the
    lowest-numbered gate it violates, and no later gate is evaluated."
    PRD 2.7: "At G8 the server checks that every required body field is present and carries
    the declared JSON type. A missing required field, or one of the wrong JSON type, is
    `ERR_VALIDATION` (HTTP 400)."
    PRD 3.9: "A movement from the wrong fulfilment state is
    `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`; from the wrong billing state it is
    `ERR_WORK_ORDER_INVALID_BILLING_STATE`."

    Design: Corner/errors/corner_error_path_and_state_gates_outrank_payload_validation
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Gate Order Co",
        email="go@corner.example",
        address_line="3 Gates",
        technician_tier="MASTER",
        technician_name="Gate Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        20000,
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )

    validate_error(
        api.complete_work_order(UNKNOWN_UUID, {}, world["technician_headers"]),
        ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.complete_work_order(work_order["id"], {}, world["technician_headers"]),
        ApiErrorId.ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE.value,
        409,
    )

    fixtures.schedule_work_order(
        work_order["id"], "2026-06-03T12:00:00Z", "2026-06-03T14:00:00Z"
    )
    fixtures.set_clock("2026-06-03T12:00:00Z")
    fixtures.start_work_order(work_order["id"], world["technician_id"])

    validate_error(
        api.complete_work_order(work_order["id"], {}, world["technician_headers"]),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )
    stored = fixtures.get_work_order(work_order["id"])
    assert stored["fulfillment_status"] == "IN_PROGRESS"
    assert stored["actual_end_at"] is None
    assert_money(stored["labor_charge_cents"], 0, "WorkOrder.labor_charge_cents")


def test_the_state_gate_outranks_the_authorisation_gate_until_the_customer_pays_up(api):
    """PRD 2.6: "5. **G5 — Entity state.** The addressed row's stored state satisfies the
    requested transition's originating state, **on every axis the transition touches**.
    Failure: that entity's invalid-state error."
    PRD 3.9: "**Completion** takes `IN_PROGRESS → COMPLETED` and is the largest cascade in
    the system. It may only be done by the assigned technician, requires
    `actual_labor_minutes` between 0 and 720 inclusive in the body, and is refused with
    `ERR_AUTHORIZATION_REQUIRED` when the pipeline is `EMERGENCY` and the ticket's
    authorisation axis is still `PENDING`."
    PRD 3.9: "Because an invoice exists, the work order's billing axis moves
    `NOT_BILLABLE → PENDING_INVOICE`; and when the pipeline is `EMERGENCY`, the ticket's
    dispatch axis moves `DIAGNOSED → RESOLVED`."

    Design: Corner/errors/corner_error_state_gate_outranks_authorization_required_then_authorize_clears_it
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Authorize Order Co",
        email="ao@corner.example",
        address_line="402 Authorize",
        technician_tier="MASTER",
        technician_name="Authorize Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        200000,
    )
    assert_money(ticket["preauth_cap_cents"], 75000, "EmergencyTicket.preauth_cap_cents")
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )

    validate_error(
        api.complete_work_order(
            work_order["id"], {"actual_labor_minutes": 60}, world["technician_headers"]
        ),
        ApiErrorId.ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE.value,
        409,
    )

    fixtures.schedule_work_order(
        work_order["id"], "2026-06-03T12:00:00Z", "2026-06-03T14:00:00Z"
    )
    fixtures.set_clock("2026-06-03T12:00:00Z")
    fixtures.start_work_order(work_order["id"], world["technician_id"])

    validate_error(
        api.complete_work_order(
            work_order["id"], {"actual_labor_minutes": 60}, world["technician_headers"]
        ),
        ApiErrorId.ERR_AUTHORIZATION_REQUIRED.value,
        402,
    )

    authorised = fixtures.authorize_ticket(ticket["id"], world["account_id"])
    assert authorised["authorization_status"] == "AUTHORIZED"

    completed = validate_success(
        api.complete_work_order(
            work_order["id"], {"actual_labor_minutes": 60}, world["technician_headers"]
        )
    )
    assert completed["fulfillment_status"] == "COMPLETED"
    assert completed["billable_minutes"] == 60
    assert_money(completed["labor_charge_cents"], 13500, "WorkOrder.labor_charge_cents")
    assert fixtures.get_ticket(ticket["id"])["dispatch_status"] == "RESOLVED"


def test_the_scope_gate_answers_before_the_availability_check(api):
    """PRD 2.6: "4. **G4 — Actor scope.** Ownership and assignment for the two
    entity-backed roles, as described in Section 2.1. Failure:
    `ERR_ACTOR_SCOPE_VIOLATION`."
    PRD 3.2: "Two conditions guard it beyond the state itself: the acting `X-User-ID` must
    equal the inspection's `technician_id`, and the technician's own `status` must be
    `AVAILABLE` — an `OFF_DUTY` technician is refused with `ERR_TECHNICIAN_UNAVAILABLE`."

    Design: Corner/errors/corner_error_scope_gate_outranks_technician_unavailable_on_inspection_start
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Scope Order Co", "JUR_ALPHA", "sq@corner.example")
    prop = fixtures.new_property(account["id"], "2 Scope", "JUR_ALPHA", 10.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    assigned = fixtures.new_technician("Assigned Tech", "JOURNEYMAN", "JUR_ALPHA")
    stranger = fixtures.new_technician("Stranger Tech", "JOURNEYMAN", "JUR_ALPHA")
    inspection = fixtures.schedule_inspection(
        well["id"], assigned["id"], "2026-06-01T10:00:00Z"
    )
    validate_success(
        api.patch_technician(assigned["id"], {"status": "OFF_DUTY"}, ADMIN)
    )

    validate_error(
        api.start_inspection(
            inspection["id"], fixtures.make_technician_headers(stranger["id"])
        ),
        ApiErrorId.ERR_ACTOR_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.start_inspection(
            inspection["id"], fixtures.make_technician_headers(assigned["id"])
        ),
        ApiErrorId.ERR_TECHNICIAN_UNAVAILABLE.value,
        409,
    )

    validate_success(
        api.patch_technician(assigned["id"], {"status": "AVAILABLE"}, ADMIN)
    )
    started = validate_success(
        api.start_inspection(
            inspection["id"], fixtures.make_technician_headers(assigned["id"])
        )
    )
    assert started["status"] == "IN_PROGRESS"
    assert fixtures.get_technician(assigned["id"])["status"] == "AVAILABLE"
