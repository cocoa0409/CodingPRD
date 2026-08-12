"""Device orders, units, and models: unit conservation, trial lifecycle and
conversion fee, selector determinism, catalog constraints, the default clock,
and immediate consistency."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_client_payload, create_referral_payload, create_evaluation_payload,
    create_device_model_payload, create_device_unit_payload, create_device_order_payload,
    create_client_with_accepted_referral, create_finalized_evaluation,
    create_device_model, create_device_unit, place_order, place_and_allocate_order,
    setup_client_with_finalized_evaluation,
    set_clock, run_daily,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


def _setup_three_unit_trial(api):
    """Pia Wex scenario: MAGNIFIER model with three NEW units; TRIAL order
    (trial_days 14) placed."""
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u1 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-U1", condition="NEW"), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-U2", condition="NEW"), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-U3", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14), SPECIALIST))
    return m, u1, o


def test_unit_conservation_on_allocate(api):
    """PRD §2.4: "The conservation law is that `total_count` changes only when a
    new unit is received into stock — allocating, loaning, repairing, returning,
    or retiring a unit merely shifts it between status buckets."
    PRD §2.4: "when a unit leaves `IN_STOCK` (allocation, loan, repair start,
    retirement) `in_stock_count` decrements".

    Design: Difficulty/compensating_invariant/ci_unit_account_conservation
    """
    m, u1, o = _setup_three_unit_trial(api)
    before = get_success_data(api.get_device_model(m["id"], ADMIN))
    assert before["in_stock_count"] == 3 and before["total_count"] == 3
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u1["id"]}, SPECIALIST))
    after = get_success_data(api.get_device_model(m["id"], ADMIN))
    assert after["in_stock_count"] == 2, "forward action shifts bucket only"
    assert after["total_count"] == 3


def test_unit_conservation_on_return_restores(api):
    """PRD §2.4: "when a unit returns to `IN_STOCK` (trial return, loan return,
    QA pass) it increments."
    PRD §2.4: "The conservation law is that `total_count` changes only when a
    new unit is received into stock".

    Design: Difficulty/compensating_invariant/ci_unit_account_conservation
    """
    m, u1, o = _setup_three_unit_trial(api)
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u1["id"]}, SPECIALIST))
    get_success_data(api.return_device_order(o["id"], SPECIALIST))
    end = get_success_data(api.get_device_model(m["id"], ADMIN))
    assert end["in_stock_count"] == 3, "compensating return restores in_stock"
    assert end["total_count"] == 3, "total conserved throughout"


def _setup_allocated_purchase_simple(api, name="Conv Pur"):
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-CP", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    return c, m, u, o


def test_convert_on_purchase_order_rejected(api):
    """PRD §3.4: "**Conversion** moves the order `ACTIVE → CONVERTED` and is
    available only when `fulfillment_type` is `TRIAL` (a purchase or loaner order
    reports `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/sm_order_convert_on_purchase_rejected
    """
    c, m, u, o = _setup_allocated_purchase_simple(api)
    resp = api.convert_device_order(o["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_return_on_purchase_order_rejected(api):
    """PRD §3.4: "**Return** moves the order to `RETURNED` from either `ACTIVE`
    or `EXPIRED`, provided the order is a `TRIAL` or `LOANER` — purchase orders
    can never be returned (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/sm_order_convert_on_purchase_rejected
    """
    c, m, u, o = _setup_allocated_purchase_simple(api)
    resp = api.return_device_order(o["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_allocated_trial(api, trial_days=14, serial="SN-TE", warranty_cents=None):
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no=serial, condition="NEW"), ADMIN))
    overrides = {"fulfillment_type": "TRIAL", "trial_days": trial_days}
    if warranty_cents is not None:
        overrides["warranty_cents"] = warranty_cents
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], **overrides), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    return c, m, u, o


def test_trial_expires_via_run_daily(api):
    """PRD §2.6: "A device order whose `fulfillment_type` is `TRIAL`, whose
    status is `ACTIVE`, and whose `trial_ends_at` is strictly before the current
    clock transitions `ACTIVE → EXPIRED`."

    Design: Corner/state_machines/sm_trial_expiry_via_run_daily
    """
    c, m, u, o = _setup_allocated_trial(api)
    set_clock("2026-05-16T00:00:00Z")
    run_daily()
    order = get_success_data(api.get_device_order(o["id"], SPECIALIST))
    assert order["status"] == "EXPIRED", "2026-05-16 > trial_ends_at 2026-05-15"


def test_expired_trial_can_still_be_returned(api):
    """PRD §3.4: "**Return** moves the order to `RETURNED` from either `ACTIVE`
    or `EXPIRED`".
    PRD §3.4: "Returning pushes the unit back to `IN_STOCK` from `DEPLOYED` or
    `ON_LOAN`".

    Design: Corner/state_machines/sm_trial_expiry_via_run_daily
    """
    c, m, u, o = _setup_allocated_trial(api)
    set_clock("2026-05-16T00:00:00Z")
    run_daily()
    returned = get_success_data(api.return_device_order(o["id"], SPECIALIST))
    assert returned["status"] == "RETURNED"
    unit = get_success_data(api.get_device_unit(u["id"], SPECIALIST))
    assert unit["status"] == "IN_STOCK"


def _setup_loaner_order(api):
    """Client with FINALIZED CCTV evaluation; LOANER-condition unit; LOANER order."""
    c, r, ev = setup_client_with_finalized_evaluation(category="CCTV")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-LC", condition="LOANER"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="LOANER"), SPECIALIST))
    return c, m, u, o


def test_loaner_order_allocation_creates_loan(api):
    """PRD §3.4: "For a `LOANER` order, a **LoanAgreement** is created recording
    the `device_order_id`, the client copied from the order, a `loaned_at` of
    now, a `due_at` exactly 30 days later, and status `ACTIVE`."
    PRD §2.6: "At startup its value is exactly `2026-05-01T00:00:00Z`".

    Design: Corner/state_machines/sm_loaner_order_lifecycle_creates_and_returns_loan
    """
    c, m, u, o = _setup_loaner_order(api)
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    loans = get_success_data(api.list_loan_agreements(SPECIALIST, params={"device_order_id": o["id"]}))
    assert len(loans) == 1
    loan = loans[0]
    assert loan["status"] == "ACTIVE"
    assert loan["due_at"] == "2026-05-31T00:00:00Z", "default clock 2026-05-01 + 30 days"


def test_loaner_order_return_returns_loan_and_restocks(api):
    """PRD §3.4: "for a loaner order additionally transitions the linked
    LoanAgreement from `ACTIVE` or `OVERDUE` to `RETURNED` with `returned_at`
    stamped."
    PRD §3.4: "Returning pushes the unit back to `IN_STOCK`".

    Design: Corner/state_machines/sm_loaner_order_lifecycle_creates_and_returns_loan
    """
    c, m, u, o = _setup_loaner_order(api)
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    loans = get_success_data(api.list_loan_agreements(SPECIALIST, params={"device_order_id": o["id"]}))
    loan_id = loans[0]["id"]
    get_success_data(api.return_device_order(o["id"], SPECIALIST))
    loan = get_success_data(api.get_loan_agreement(loan_id, SPECIALIST))
    assert loan["status"] == "RETURNED"
    unit = get_success_data(api.get_device_unit(u["id"], SPECIALIST))
    assert unit["status"] == "IN_STOCK"


def test_loan_overdue_via_run_daily_with_overdue_days(api):
    """PRD §2.6: "A loan agreement in `ACTIVE` whose `due_at` is strictly before
    the current clock transitions `ACTIVE → OVERDUE`, with `overdue_days`
    recomputed as the whole days past `due_at`."

    Design: Corner/state_machines/sm_loan_overdue_via_run_daily
    """
    c, m, u, o = _setup_loaner_order(api)
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    loans = get_success_data(api.list_loan_agreements(SPECIALIST, params={"device_order_id": o["id"]}))
    loan_id = loans[0]["id"]
    set_clock("2026-06-03T00:00:00Z")
    run_daily()
    loan = get_success_data(api.get_loan_agreement(loan_id, SPECIALIST))
    assert loan["status"] == "OVERDUE"
    assert loan["overdue_days"] == 3, "2026-06-03 minus due_at 2026-05-31"


def test_trial_conversion_fee_pinned_order(api):
    """PRD §3.4: "the trial credit is the smaller of two quantities: the model's
    `list_price_cents` multiplied by 2 percent per day used and rounded half-up
    to a whole cent, or the model's `list_price_cents` multiplied by 30 percent
    and rounded half-up".
    PRD §3.4: "the service fee is 12 percent of the device subtotal — computed on
    the subtotal, **not** on the final total — rounded half-up to a whole cent.
    Finally, `conversion_total_cents` is the device subtotal plus the service fee
    plus the order's `warranty_cents`."

    Design: Corner/calculations/calc_trial_conversion_fee_pinned_order
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="CCTV")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-FC", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14,
        warranty_cents=5000), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    set_clock("2026-05-11T00:00:00Z")
    converted = get_success_data(api.convert_device_order(o["id"], SPECIALIST))
    assert converted["status"] == "CONVERTED"
    # credit min(round(100000*0.02*10)=20000, round(100000*0.30)=30000) = 20000
    # subtotal 80000; fee round(80000*0.12) = 9600; total 80000+9600+5000 = 94600
    assert converted["conversion_total_cents"] == 94600, (
        f"got {converted['conversion_total_cents']}")


def test_trial_auto_select_prefers_loaner_condition(api):
    """PRD §3.4: "Among eligible units, ranking is by condition tier — for trial
    and loaner, `LOANER` beats `REFURB` beats `NEW`; for purchase, `NEW` beats
    `REFURB` — and ties break by `created_at` ascending, never by `id`."

    Design: Corner/calculations/calc_selector_trial_prefers_loaner_condition
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u_new = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-N1", condition="NEW"), ADMIN))
    u_loaner = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-L1", condition="LOANER"), ADMIN))
    o_trial = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14), SPECIALIST))
    allocated = get_success_data(api.allocate_device_order(o_trial["id"], {}, SPECIALIST))
    assert allocated["device_unit_id"] == u_loaner["id"], "LOANER ranks first for TRIAL"


def test_purchase_auto_select_excludes_loaner_condition(api):
    """PRD §3.4: "eligibility requires a unit of the order's model in
    `IN_STOCK`, with `condition` restricted to `NEW` or `REFURB` for a `PURCHASE`
    order, while `TRIAL` and `LOANER` orders may draw from `LOANER`, `REFURB`, or
    `NEW` units."

    Design: Corner/calculations/calc_selector_trial_prefers_loaner_condition
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u_new = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-N1", condition="NEW"), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-L1", condition="LOANER"), ADMIN))
    o_pur = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    allocated = get_success_data(api.allocate_device_order(o_pur["id"], {}, SPECIALIST))
    assert allocated["device_unit_id"] == u_new["id"], "LOANER excluded for PURCHASE"


def test_allocate_with_empty_pool_rejected(api):
    """PRD §3.4: "An empty pool rejects the allocation with
    `ERR_NO_ELIGIBLE_UNIT`."
    PRD §3.4: "A new order is `PLACED`".

    Design: Corner/calculations/calc_selector_empty_pool_returns_no_eligible_unit
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14), SPECIALIST))
    resp = api.allocate_device_order(o["id"], {}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_UNIT)
    order = get_success_data(api.get_device_order(o["id"], SPECIALIST))
    assert order["status"] == "PLACED", "no partial allocation"


def _setup_two_trials(api):
    """Two TRIAL orders (trial_days 14) allocated at the default clock, so
    trial_ends_at = 2026-05-15T00:00:00Z for both."""
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u1 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-TB1", condition="NEW"), ADMIN))
    u2 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-TB2", condition="NEW"), ADMIN))
    o1 = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14), SPECIALIST))
    o2 = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14), SPECIALIST))
    get_success_data(api.allocate_device_order(o1["id"], {"device_unit_id": u1["id"]}, SPECIALIST))
    get_success_data(api.allocate_device_order(o2["id"], {"device_unit_id": u2["id"]}, SPECIALIST))
    return o1, o2


def test_convert_at_exact_trial_end_allowed(api):
    """PRD §3.4: "only while the current logical clock is on or before
    `trial_ends_at` — exact equality with the trial end is still allowed".

    Design: Corner/validations/val_trial_convert_exact_boundary
    """
    o1, o2 = _setup_two_trials(api)
    set_clock("2026-05-15T00:00:00Z")
    converted = get_success_data(api.convert_device_order(o1["id"], SPECIALIST))
    assert converted["status"] == "CONVERTED", "now == trial_ends_at is allowed"


def test_convert_one_second_past_trial_end_rejected(api):
    """PRD §3.4: "even one instant later is rejected with `ERR_TRIAL_EXPIRED`
    (HTTP 409)."

    Design: Corner/validations/val_trial_convert_exact_boundary
    """
    o1, o2 = _setup_two_trials(api)
    set_clock("2026-05-15T00:00:01Z")
    resp = api.convert_device_order(o2["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_TRIAL_EXPIRED)


def test_order_category_mismatch_rejected(api):
    """PRD §3.4: "the model's `category` must equal the evaluation's
    `recommended_category`, or the placement is rejected with
    `ERR_CATEGORY_MISMATCH`."

    Design: Corner/validations/val_category_mismatch_rejected
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="CCTV")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    resp = api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH)


def test_explicit_unit_not_available_rejected(api):
    """PRD §3.4: "The caller may name an explicit `device_unit_id`, which must
    be a unit of this order's model currently `IN_STOCK` — anything else is
    `ERR_UNIT_NOT_AVAILABLE`."

    Design: Corner/validations/val_explicit_unit_not_available_rejected
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-UA", condition="NEW"), ADMIN))
    o1 = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o1["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    o2 = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    resp = api.allocate_device_order(o2["id"], {"device_unit_id": u["id"]}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE)


def test_duplicate_serial_rejected(api):
    """PRD §3.3: "Receiving a **DeviceUnit** records its `device_model_id`, a
    manufacturer `serial_no` that is unique across all units in the system".
    PRD §2.7: "3. **Body schema** — required fields present, types correct, enum
    members valid, numeric ranges honored (`ERR_VALIDATION`, HTTP 400)".

    Design: Corner/entities/ent_unit_duplicate_serial_rejected
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-DUP", condition="NEW"), ADMIN))
    resp = api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-DUP", condition="REFURB"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_model_computed_counts_start_at_zero(api):
    """PRD §3.3: "At creation both catalog counters, `in_stock_count` and
    `total_count`, are 0."
    PRD §2.4: "Two integer counters live on every DeviceModel and are recomputed
    on each DeviceUnit status change".

    Design: Corner/entities/ent_device_model_computed_counts_input_ignored

    Note: PRD is silent on whether supplying computed counters in a create
    payload is ignored or rejected, so this test only asserts the PRD-pinned
    creation values on a well-formed request.
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    assert m["in_stock_count"] == 0
    assert m["total_count"] == 0


def test_immediate_visibility_after_unit_receipt(api):
    """PRD §3.3: "Every unit is born `IN_STOCK`, and both counters on its model
    recompute (increment) at receipt."
    PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/consistency_model/cm_immediate_visibility_after_mutation
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-IM", condition="NEW"), ADMIN))
    assert u["status"] == "IN_STOCK", "visible in the create response itself"
    model = get_success_data(api.get_device_model(m["id"], ADMIN))
    assert model["in_stock_count"] == 1 and model["total_count"] == 1


def test_default_clock_stamps_allocation(api):
    """PRD §2.6: "At startup its value is exactly `2026-05-01T00:00:00Z`, and it
    never falls back to wall-clock time."
    PRD §3.4: "`dispensed_at` is stamped with the current logical clock. For a
    `TRIAL` order, `trial_ends_at` is computed as `dispensed_at` plus
    `trial_days`."

    Design: Corner/complexity_layers/layer_clock_default_time
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-CD", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="TRIAL", trial_days=14), SPECIALIST))
    allocated = get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    assert allocated["dispensed_at"] == "2026-05-01T00:00:00Z"
    assert allocated["trial_ends_at"] == "2026-05-15T00:00:00Z"


def test_filtered_list_units_by_status_and_model(api):
    """PRD §3.3: "Units can be listed with `device_model_id`, `status`, and
    `condition` filters".

    Design: Corner/endpoints/ep_filtered_list_device_units_by_status
    """
    c, r, ev = setup_client_with_finalized_evaluation(category="MAGNIFIER")
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u1 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-F1", condition="NEW"), ADMIN))
    u2 = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-F2", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u2["id"]}, SPECIALIST))
    data, meta = validate_paginated(api.list_device_units(
        ADMIN, params={"device_model_id": m["id"], "status": "IN_STOCK"}))
    assert len(data) == 1 and data[0]["id"] == u1["id"], "the DEPLOYED unit is filtered out"
    assert meta["total_count"] == 1


def test_model_predecessors_reverse_lookup(api):
    """PRD §3.3: "A model may name a `successor_model_id` pointing at a newer
    model as an upgrade path, or leave it null; the models pointing *at* a given
    model can be enumerated through its predecessors collection."

    Design: Corner/endpoints/ep_fk_reverse_model_predecessors
    """
    ma = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    mb = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 4x", category="MAGNIFIER", list_price_cents=20000,
        successor_model_id=ma["id"]), ADMIN))
    preds = get_success_data(api.list_model_predecessors(ma["id"], ADMIN))
    assert isinstance(preds, list) and len(preds) == 1
    assert preds[0]["id"] == mb["id"]
