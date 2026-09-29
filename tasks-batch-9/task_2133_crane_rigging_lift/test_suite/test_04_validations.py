"""Authentication, request shape, uniqueness, crew discriminators and the fiscal
gates, each exercised in isolation so exactly one rule can fail."""

from test_helpers import (
    ApiErrorId,
    BILLING_CLERK,
    DISPATCHER,
    LIFT_DIRECTOR,
    SAFETY_MANAGER,
    approve_plan,
    build_standard_world,
    build_user_headers,
    commit_gear,
    configure_body,
    create_gear_assignment_payload,
    gear_version,
    open_plan,
    read_customer,
    read_gear,
    read_plan,
    set_credit_hold,
    setup_closed_standard_job,
    setup_configured_plan,
    setup_surveyed_plan_with_gear,
    survey_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def test_a_request_without_the_identity_headers_is_unauthenticated(api):
    """PRD 2.1: "Every request to every endpoint — including reads and including the
    clock-driving capability — must carry two headers: `X-User-ID` and `X-User-Role`.
    If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_missing_x_user_headers_returns_unauthenticated
    """
    resp = api.raw_post("/customers", {"account_name": "Northgate Industrial"},
                        NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _, meta = validate_paginated(api.list_customers(DISPATCHER))
    assert meta["total_count"] == 0, "a rejected request must persist nothing"


def test_an_unrecognised_role_is_an_authentication_failure_not_an_authorization_one(api):
    """PRD 2.1: "The same code and status are returned when `X-User-Role` carries a
    value outside the seven roles the system recognizes, which are, spelled exactly:
    `Dispatcher`, `LiftDirector`, `Engineer`, `Operator`, `SafetyManager`,
    `BillingClerk`, and `Customer`."
    PRD 2.7: "The supplied role appears among the roles authorized for the endpoint
    being called — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every request."

    Design: Corner/validations/request_with_unknown_role_returns_unauthenticated
    """
    headers = build_user_headers("test-unknown-1", "CraneWhisperer")
    resp = api.create_customer({"account_name": "Northgate Industrial"}, headers)

    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value


def test_window_sanity_is_enforced_in_both_directions(api):
    """PRD 3.3: "Window sanity is enforced at creation: `window_end` must be strictly
    after `window_start`, and `window_start` must be at or after the logical clock. A
    window that fails either test is refused with `ERR_INVALID_WINDOW`."
    PRD 2.4: "It starts at exactly `2026-08-01T00:00:00Z` when the server boots and
    never falls back to wall-clock time."

    Design: Corner/validations/lift_plan_window_sanity_rejected_in_both_directions
    """
    world = build_standard_world()

    zero_length = api.create_lift_plan(
        {"site_id": world["site_id"], "job_reference": "JOB-BAD-1",
         "window_start": "2026-09-10T06:00:00Z", "window_end": "2026-09-10T06:00:00Z",
         "load_weight_lb": 60_000}, DISPATCHER)
    validate_error(zero_length, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

    before_clock = api.create_lift_plan(
        {"site_id": world["site_id"], "job_reference": "JOB-BAD-2",
         "window_start": "2026-07-01T00:00:00Z", "window_end": "2026-07-01T10:00:00Z",
         "load_weight_lb": 60_000}, DISPATCHER)
    validate_error(before_clock, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

    _, meta = validate_paginated(
        api.list_lift_plans(DISPATCHER, params={"site_id": world["site_id"]}))
    assert meta["total_count"] == 0


def test_a_gear_tag_is_unique_across_the_whole_inventory(api):
    """PRD 3.2: "A `SafetyManager` registers a piece of gear with a `gear_tag` that
    must be globally unique across the whole inventory — a collision is refused with
    `ERR_DUPLICATE_GEAR_TAG` — a `gear_type` drawn from `SLING`, `SHACKLE` and
    `SPREADER_BAR`, the manufacturer's `rated_wll_lb` working load limit in pounds,
    the dead `weight_lb` of the gear itself (which may be zero but not negative), and
    optionally an `inspection_interval_days` cadence that defaults to 30 days when
    omitted and must be positive."

    Design: Corner/validations/duplicate_gear_tag_is_rejected_as_conflict
    """
    validate_success(api.create_rigging_gear(
        {"gear_tag": "SL-5001", "gear_type": "SLING", "rated_wll_lb": 30_000,
         "weight_lb": 500, "inspection_interval_days": 90}, SAFETY_MANAGER), 201)

    clash = api.create_rigging_gear(
        {"gear_tag": "SL-5001", "gear_type": "SHACKLE", "rated_wll_lb": 18_000,
         "weight_lb": 60, "inspection_interval_days": 30}, SAFETY_MANAGER)
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_GEAR_TAG.value, 409)

    _, meta = validate_paginated(
        api.list_rigging_gear(DISPATCHER, params={"gear_type": "SHACKLE"}))
    assert meta["total_count"] == 0


def test_a_plan_holds_at_most_one_active_commitment_of_a_given_gear_item(api):
    """PRD 3.4: "A plan may hold at most one active commitment of any given gear item
    at a time, and a second attempt is refused with `ERR_DUPLICATE_GEAR_ASSIGNMENT`."
    PRD 3.4: "Creating the commitment recomputes the gear item's
    `committed_assignment_count` and increments that gear item's `version` by one."

    Design: Corner/validations/second_active_assignment_of_the_same_gear_to_one_plan_is_rejected
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9400")
    survey_plan(world, plan["id"])
    first = commit_gear(world, plan["id"])

    payload = create_gear_assignment_payload(
        plan["id"], world["gear_id"], gear_version(world["gear_id"]),
        leg_count=2, sling_angle_deg=90)
    validate_error(api.create_gear_assignment(payload, DISPATCHER),
                   ApiErrorId.ERR_DUPLICATE_GEAR_ASSIGNMENT.value, 409)

    assert read_gear(world["gear_id"])["committed_assignment_count"] == 1
    rows, meta = validate_paginated(
        api.list_gear_assignments(DISPATCHER, params={"lift_plan_id": plan["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["leg_count"] == 4


def test_configuring_with_no_active_commitment_reports_no_rigging_assigned(api):
    """PRD 3.4: "Withdrawing a commitment moves it from `ACTIVE` to `RELEASED` and
    recomputes the gear's `committed_assignment_count`; withdrawing anything that is
    not currently `ACTIVE` is refused with `ERR_INVALID_GEAR_STATE`."
    PRD 3.4: "The plan's `rigging_weight_lb` is the sum of the `weight_lb` of the gear
    behind every commitment on this plan whose status is `ACTIVE`; commitments that
    are `RELEASED` or `VOIDED` contribute neither weight nor a tension check. If there
    is not a single active commitment, the configure fails with
    `ERR_NO_RIGGING_ASSIGNED`."

    Design: Corner/validations/configure_with_no_active_gear_assignment_returns_no_rigging_assigned
    """
    world = build_standard_world()
    ctx = setup_surveyed_plan_with_gear(world, plan_overrides={"job_reference": "JOB-9401"})

    released = validate_success(api.release_gear_assignment(ctx["ga_id"], DISPATCHER))
    assert released["status"] == "RELEASED"
    assert read_gear(world["gear_id"])["committed_assignment_count"] == 0

    body = configure_body(world, ctx["plan_version"])
    validate_error(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER),
                   ApiErrorId.ERR_NO_RIGGING_ASSIGNED.value, 422)
    assert read_plan(ctx["plan_id"])["plan_status"] == "SURVEYED"


def test_a_rigger_in_the_operator_slot_is_a_discriminator_mismatch(api):
    """PRD 3.4: "The assigned crane may not be `OUT_OF_SERVICE`
    (`ERR_CRANE_OUT_OF_SERVICE`), and the two crew references must match their
    discriminators: `operator_id` must name a person whose `role_type` is `OPERATOR`
    and `rigger_id` must name one whose `role_type` is `RIGGER`, or the request is
    refused with `ERR_PERSONNEL_ROLE_MISMATCH`."

    Design: Corner/validations/configure_with_a_rigger_in_the_operator_slot_returns_role_mismatch
    """
    world = build_standard_world()
    ctx = setup_surveyed_plan_with_gear(world, plan_overrides={"job_reference": "JOB-9402"})

    body = configure_body(world, ctx["plan_version"], operator_id=world["rig_id"])
    validate_error(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER),
                   ApiErrorId.ERR_PERSONNEL_ROLE_MISMATCH.value, 422)

    plan = read_plan(ctx["plan_id"])
    assert plan["plan_status"] == "SURVEYED"
    assert plan["operator_id"] is None


def test_the_endorsement_gate_bites_at_release_not_at_configure(api):
    """PRD 3.8: "That operator's `endorsement_class_tons` must be greater than or
    equal to the assigned crane's `class_tons`, or it fails with
    `ERR_OPERATOR_ENDORSEMENT_INSUFFICIENT`."
    PRD 3.1: "Recertification is a dispatch action that refreshes
    `certification_number` and `certification_expires_on` and may also refresh
    `endorsement_class_tons` and `rigger_level`; the derived `status` is recomputed
    against the logical clock immediately."

    Design: Corner/validations/release_with_insufficient_operator_endorsement_is_rejected
    """
    world = build_standard_world(operator={"endorsement_class_tons": 100})
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9403"})
    assert ctx["plan"]["plan_status"] == "CONFIGURED", "configure never checks the endorsement"
    approve_plan(ctx["plan_id"])

    validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                   ApiErrorId.ERR_OPERATOR_ENDORSEMENT_INSUFFICIENT.value, 422)

    recertified = validate_success(api.recertify_personnel(
        world["op_id"], {"certification_number": "NCCCO-88421",
                         "certification_expires_on": "2027-03-31T00:00:00Z",
                         "endorsement_class_tons": 200}, DISPATCHER))
    assert recertified["endorsement_class_tons"] == 200

    released = validate_success(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR))
    assert released["plan_status"] == "RELEASED"


def test_a_lump_sum_invoice_without_an_agreed_price_is_refused(api):
    """PRD 3.9: "A `LUMP_SUM` invoice must carry a `lump_sum_cents` strictly greater
    than 0 or it is refused with `ERR_LUMP_SUM_REQUIRED`; an `HOURLY` invoice ignores
    `lump_sum_cents` entirely."

    Design: Corner/validations/lump_sum_invoice_without_an_amount_returns_lump_sum_required
    """
    world = build_standard_world()
    ctx = setup_closed_standard_job(world, with_standby=False,
                                    plan_overrides={"job_reference": "JOB-9404"})

    resp = api.create_invoice(
        {"lift_plan_id": ctx["plan_id"], "billing_mode": "LUMP_SUM",
         "on_site_hours": 5.0, "travel_hours": 1.0, "travel_miles": 10.0,
         "expected_lift_plan_version": ctx["plan_version"]}, BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_LUMP_SUM_REQUIRED.value, 422)

    _, meta = validate_paginated(
        api.list_invoices(BILLING_CLERK, params={"lift_plan_id": ctx["plan_id"]}))
    assert meta["total_count"] == 0


def test_a_credit_hold_blocks_issuance_until_it_is_cleared(api):
    """PRD 3.9: "Issuing moves a `DRAFT` — or a `DISPUTED` — invoice to `ISSUED`, and
    requires the owning customer's `credit_hold` to be false, or it is refused with
    `ERR_CUSTOMER_CREDIT_HOLD`."
    PRD 3.1: "Credit standing is not a dispatch concern — only a `BillingClerk` may
    toggle it, supplying the new `credit_hold` value and an optional `reason` that is
    stored as `credit_hold_reason` when the hold is being set. Clearing a hold leaves
    `credit_hold_reason` null."

    Design: Corner/validations/credit_hold_blocks_invoice_issue_with_payment_required
    """
    world = build_standard_world()
    ctx = setup_closed_standard_job(world, with_standby=False,
                                    plan_overrides={"job_reference": "JOB-9405"})
    invoice = validate_success(api.create_invoice(
        {"lift_plan_id": ctx["plan_id"], "billing_mode": "HOURLY",
         "on_site_hours": 2.5, "travel_hours": 1.0, "travel_miles": 0.0,
         "expected_lift_plan_version": ctx["plan_version"]}, BILLING_CLERK), 201)
    assert invoice["total_cents"] == 461_705

    set_credit_hold(world["cust_id"], True, "aged receivable")
    validate_error(api.issue_invoice(invoice["id"], BILLING_CLERK),
                   ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value, 402)

    cleared = set_credit_hold(world["cust_id"], False)
    assert cleared["credit_hold"] is False
    assert cleared["credit_hold_reason"] is None

    issued = validate_success(api.issue_invoice(invoice["id"], BILLING_CLERK))
    assert issued["status"] == "ISSUED"
    assert read_customer(world["cust_id"])["open_receivable_cents"] == 461_705
