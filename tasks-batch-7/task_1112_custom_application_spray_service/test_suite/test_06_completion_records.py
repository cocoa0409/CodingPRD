"""Completion fan-out, application-record review loop, invoice math variants,
and rinsate accounting."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    create_customer, create_field, create_product, create_product_p2,
    create_prescription, approve_prescription, create_applicator,
    create_equipment, post_calibration, create_work_order,
    create_rinsate_record_payload, schedule_work_order, must_schedule,
    post_weather, set_clock, must_start, complete_work_order,
    get_record_for_work_order, get_invoice_for_work_order, certify_record,
    base_environment, scheduled_environment, in_progress_environment,
    completed_environment, certified_environment,
    make_applicator_headers, make_grower_headers,
    EXPECTED, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _rounding_environment(api):
    """10-acre job: rate 1000c/acre, P3 (1001c, 0%) @0.25 + P4 (999c, 0%) @0.25."""
    cust = create_customer(name="Round Farm", billing_email="r@farm.test",
                           rate_per_acre_cents=1000, credit_limit_cents=1000000)
    field = create_field(cust["id"], label="West 10", crop="SOY", acres=10)
    p3 = create_product(name="P3", epa_registration_no="EPA-300-3",
                        required_buffer_ft=0, unit_cost_cents=1001, markup_pct=0)
    p4 = create_product_p2(name="P4", epa_registration_no="EPA-400-4",
                           rei_hours=24, max_wind_mph=10, min_temp_f=40, max_temp_f=85,
                           unit_cost_cents=999, markup_pct=0)
    rx = approve_prescription(create_prescription(field["id"], [
        {"product_id": p3["id"], "rate_per_acre": 0.25},
        {"product_id": p4["id"], "rate_per_acre": 0.25},
    ], carrier_gpa=10))
    ap = create_applicator()
    eq = create_equipment()
    post_calibration(eq["id"], ap["id"])
    wo = create_work_order(cust["id"], field["id"], rx["id"], acres_to_treat=10)
    return {"customer": cust, "field": field, "p3": p3, "p4": p4,
            "prescription": rx, "applicator": ap, "equipment": eq, "work_order": wo}


def test_invoice_per_line_rounding_order_at_schedule(api):
    """PRD §2.6: "Invoice mathematics rounds half-up to whole cents, and the
    rounding order is pinned: each product line of an invoice is rounded to
    whole cents first, the lines are then summed, and the service fee is
    rounded independently of the lines. Summing raw values and rounding once at
    the end is a different, non-conforming algorithm."
    PRD §3.4: "The provisional amount mirrors the invoice formula of §3.9 run
    over prescribed rates"

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
    """
    env = _rounding_environment(api)
    scheduled = must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"])
    # Per-line half-up: 10000 + round(2502.5) + round(2497.5) = 10000+2503+2498.
    assert scheduled["estimated_total_cents"] == EXPECTED["ROUNDING_ORDER_TOTAL"], \
        f"expected 15001 (per-line rounding), got {scheduled['estimated_total_cents']}"
    assert scheduled["estimated_total_cents"] != 15000, \
        "sum-then-round (15000) is a non-conforming algorithm"


def test_invoice_per_line_rounding_order_in_final_variant(api):
    """PRD §3.6: "computes the work order invoice's `final_amount_cents` as the
    final variant of the invoice formula — the same per-line-then-summed,
    half-up-to-whole-cents structure as the provisional, but run over the
    record's `actual_rate_per_acre` figures instead of the prescribed rates"

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
    """
    env = _rounding_environment(api)
    ap = env["applicator"]["id"]
    must_schedule(env["work_order"]["id"], ap, env["equipment"]["id"])
    post_weather(ap)
    set_clock("2026-05-10T08:00:00Z")
    must_start(env["work_order"]["id"], ap)
    set_clock("2026-05-10T10:30:00Z")
    get_success_data(complete_work_order(env["work_order"]["id"], ap, [
        {"product_id": env["p3"]["id"], "actual_rate_per_acre": 0.25},
        {"product_id": env["p4"]["id"], "actual_rate_per_acre": 0.25},
    ]))
    invoice = get_invoice_for_work_order(env["work_order"]["id"])
    assert invoice["provisional_amount_cents"] == EXPECTED["ROUNDING_ORDER_TOTAL"]

    record = get_record_for_work_order(env["work_order"]["id"])
    certify_record(record["id"])
    invoice = get_success_data(api.get_invoice(invoice["id"], ADMIN))
    assert invoice["final_amount_cents"] == EXPECTED["ROUNDING_ORDER_TOTAL"], \
        "final variant must apply the same pinned per-line rounding"


def test_invoice_provisional_vs_final_amounts(api):
    """PRD §3.5: "A DRAFT Invoice is created for the work order with
    `provisional_amount_cents` equal to the provisional invoice amount from
    §3.4 (recomputed at completion from prescribed rates)."
    PRD §3.6: "the final diverges from the provisional whenever actuals
    differed"

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_amounts
    """
    env = completed_environment(actual_rates={"p1": 1.6, "p2": 0.4})
    invoice = env["invoice"]
    assert invoice["provisional_amount_cents"] == EXPECTED["PROVISIONAL_100AC"], \
        f"provisional must be 1065000, got {invoice['provisional_amount_cents']}"

    wo = validate_success(api.get_work_order(env["work_order"]["id"], DISPATCHER), 200)
    assert wo["estimated_total_cents"] == EXPECTED["PROVISIONAL_100AC"], \
        "schedule-time estimate equals the completion-time provisional"

    certify_record(env["record"]["id"])
    invoice = get_success_data(api.get_invoice(invoice["id"], ADMIN))
    assert invoice["final_amount_cents"] == EXPECTED["FINAL_100AC_P1_1_6"], \
        f"final must be 1120000, got {invoice['final_amount_cents']}"
    assert invoice["final_amount_cents"] - invoice["provisional_amount_cents"] == 55000, \
        "the two variants diverge by exactly the rate change on identical acreage"


def test_invoice_final_amount_null_until_certification(api):
    """PRD §3.9: "Every completed job carries exactly one Invoice, created
    `DRAFT` at completion with `provisional_amount_cents` set from prescribed
    rates and `final_amount_cents` null until the application record is
    certified."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_amounts
    """
    env = completed_environment()
    invoice = env["invoice"]
    assert invoice["status"] == "DRAFT"
    assert invoice["provisional_amount_cents"] == EXPECTED["PROVISIONAL_100AC"]
    assert invoice["final_amount_cents"] is None, \
        "final_amount_cents must stay null until certification"


def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.4: "Cancellation is available from `DRAFT` or `SCHEDULED` to the
    terminal `CANCELLED` state, by the owning `Grower` or a `Dispatcher`,
    incrementing `version`."
    PRD §2.9: "the target resource is in a valid from-state for the
    requested transition, and linked-entity state preconditions hold
    (prescription approved, applicator active, record certified), surfacing
    as `ERR_INVALID_STATE`"

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    env = base_environment(num_products=1, approve=False)
    wo_id = env["work_order"]["id"]
    validate_success(api.cancel_work_order(wo_id, DISPATCHER), 200)
    res = api.cancel_work_order(wo_id, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_complete_from_scheduled_returns_invalid_state(api):
    """PRD §2.9: "the target resource is in a valid from-state for the
    requested transition, and linked-entity state preconditions hold
    (prescription approved, applicator active, record certified), surfacing
    as `ERR_INVALID_STATE`"
    PRD §3.5: "Completion is the applicator's sworn statement. The assigned
    applicator finishes the job by submitting `lines`" — completion is the
    IN_PROGRESS to COMPLETED transition.

    Design: Corner/state_machines/complete_from_scheduled_returns_invalid_state
    """
    env = scheduled_environment(num_products=1)
    res = complete_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              [{"product_id": env["p1"]["id"], "actual_rate_per_acre": 1.5}])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_complete_creates_application_record_snapshot(api):
    """PRD §3.5: "Exactly one ApplicationRecord is created for the work order,
    born `SUBMITTED`, snapshotting the submitted `lines`, the `applicator_id`,
    and the `started_at` / `completed_at` pair."
    PRD §3.6: "The ApplicationRecord is the compliance copy of the job —
    exactly one per work order, discovered through the `work_order_id` filter
    on the record list."

    Design: Corner/state_machines/complete_creates_application_record_snapshot
    """
    env = completed_environment(num_products=1)
    wo_id = env["work_order"]["id"]

    data, meta = validate_paginated(api.list_application_records(
        COMPLIANCE, params={"work_order_id": wo_id}))
    assert len(data) == 1, "exactly one record per work order"
    record = data[0]
    assert record["status"] == "SUBMITTED"
    assert record["applicator_id"] == env["applicator"]["id"], "applicator snapshot"
    assert record["started_at"] == "2026-05-10T08:00:00.000Z"
    assert record["completed_at"] == "2026-05-10T10:30:00.000Z"
    assert record["lines"] == [{"product_id": env["p1"]["id"], "actual_rate_per_acre": 1.5}]


def test_application_record_return_resubmit_cycle(api):
    """PRD §3.6: "Resubmission replaces the lines wholesale, clears
    `returned_note`, restores `SUBMITTED`, and increments `version`."
    PRD §3.6: "It lives in three states: born `SUBMITTED`, it may be
    `CERTIFIED` (terminal), sent back to `RETURNED`, and a returned record may
    be resubmitted to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/application_record_return_resubmit_cycle
    """
    env = completed_environment()
    record = env["record"]
    assert record["status"] == "SUBMITTED"
    ap = env["applicator"]["id"]

    returned = validate_success(api.return_application_record(
        record["id"], {"returned_note": "rates illegible"}, COMPLIANCE), 200)
    assert returned["status"] == "RETURNED"

    resubmitted = validate_success(api.resubmit_application_record(
        record["id"],
        {"lines": [{"product_id": env["p1"]["id"], "actual_rate_per_acre": 1.6},
                   {"product_id": env["p2"]["id"], "actual_rate_per_acre": 0.4}]},
        make_applicator_headers(ap)), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["returned_note"] is None, "resubmission clears returned_note"
    rates = {line["product_id"]: line["actual_rate_per_acre"]
             for line in resubmitted["lines"]}
    assert rates[env["p1"]["id"]] == 1.6, "resubmission replaces the lines wholesale"

    certified = certify_record(record["id"])
    assert certified["status"] == "CERTIFIED"


def test_return_requires_note_and_resubmit_requires_performer(api):
    """PRD §3.6: "a `ComplianceOfficer` returns the record with a
    `returned_note` explaining the deficiency; an empty or missing note is
    `ERR_VALIDATION`."
    PRD §3.6: "The performing applicator — and only that applicator, matched by
    `X-User-ID` against the record's `applicator_id` else `ERR_FORBIDDEN` — may
    then resubmit"

    Design: Difficulty/non_linear_state_machine/application_record_return_resubmit_cycle
    """
    env = completed_environment()
    record = env["record"]
    ap2 = create_applicator(display_name="Bob", license_no="L-200")

    res = api.return_application_record(record["id"], {"returned_note": ""}, COMPLIANCE)
    validate_error(res, "ERR_VALIDATION", expected_status=400)

    validate_success(api.return_application_record(
        record["id"], {"returned_note": "rates illegible"}, COMPLIANCE), 200)
    res2 = api.resubmit_application_record(
        record["id"],
        {"lines": [{"product_id": env["p1"]["id"], "actual_rate_per_acre": 1.5},
                   {"product_id": env["p2"]["id"], "actual_rate_per_acre": 0.4}]},
        make_applicator_headers(ap2["id"]))
    validate_error(res2, "ERR_FORBIDDEN", expected_status=403)


def test_applicator_cannot_certify_own_record(api):
    """PRD §3.6: "the certifier's `X-User-ID` must differ from the record's
    `applicator_id`; certifying one's own work is rejected with
    `ERR_SEGREGATION_OF_DUTIES`. (An applicator certifying a colleague's record
    is legitimate and common on small crews.)"

    Design: Corner/rbac/applicator_cannot_certify_own_record
    """
    env = completed_environment(num_products=1)
    ap2 = create_applicator(display_name="Bob", license_no="L-200",
                            license_categories=["HERBICIDE"])

    res = api.certify_application_record(
        env["record"]["id"], make_applicator_headers(env["applicator"]["id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    certified = validate_success(api.certify_application_record(
        env["record"]["id"], make_applicator_headers(ap2["id"])), 200)
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == ap2["id"]


def test_rinsate_partial_load_rounds_up(api):
    """PRD §3.5: "the load count is that total divided by the sprayer's
    `tank_capacity_gal`, rounded up to a whole number; `rinsate_generated_gal`
    is the load count times `tank_capacity_gal` times two percent — two
    hundredths of a tank per load — rounded half-up to one decimal place; and
    `rinsate_balance_gal` opens equal to `rinsate_generated_gal`."

    Design: Corner/calculations/rinsate_partial_load_rounds_up
    """
    # 50 acres * 12 gpa = 600 gal; ceil(600/400) = 2 loads; 2*400*0.02 = 16.0.
    env = completed_environment(num_products=1, acres_to_treat=50)
    wo = env["work_order"]
    assert wo["rinsate_generated_gal"] == pytest.approx(EXPECTED["RINSATE_50AC_GAL"]), \
        f"expected 16.0 gal from 2 rounded-up loads, got {wo['rinsate_generated_gal']}"
    assert wo["rinsate_balance_gal"] == pytest.approx(EXPECTED["RINSATE_50AC_GAL"])


def test_rei_until_takes_max_across_completions(api):
    """PRD §3.5: "The field's `rei_until` advances to the later of its existing
    value and `completed_at` plus the largest `rei_hours` among the applied
    products — the lockout never moves earlier — and the Field's `version`
    increments."

    Design: Corner/calculations/rei_until_takes_max_across_completions
    """
    env = completed_environment(acres_to_treat=40)  # completed 2026-05-10T10:30:00Z
    ap = env["applicator"]["id"]

    wo2 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=40)
    must_schedule(wo2["id"], ap, env["equipment"]["id"],
                  scheduled_start="2026-05-13T08:00:00Z",
                  scheduled_end="2026-05-13T11:00:00Z")
    post_weather(ap, observed_at="2026-05-13T07:30:00Z")
    set_clock("2026-05-13T08:00:00Z")
    must_start(wo2["id"], ap)
    set_clock("2026-05-13T10:30:00Z")
    get_success_data(complete_work_order(wo2["id"], ap, [
        {"product_id": env["p1"]["id"], "actual_rate_per_acre": 1.5},
        {"product_id": env["p2"]["id"], "actual_rate_per_acre": 0.4},
    ]))

    field = validate_success(api.get_field(env["field"]["id"], ADMIN), 200)
    assert field["rei_until"] == "2026-05-15T10:30:00.000Z", \
        ("max(2026-05-12T10:30:00Z, 2026-05-13T10:30:00Z + 48h) must win; "
         f"got {field['rei_until']}")


def test_rinsate_disposal_field_and_manifest_rules(api):
    """PRD §3.7: "A `FIELD_DISPOSAL` must name a `disposal_field_id`, and it
    must equal the work order's own `field_id` — rinsate may be land-applied
    only back onto the field it came from, and any other destination is
    `ERR_DISPOSAL_FIELD_MISMATCH`. A `CONTAINMENT_DISPOSAL` instead requires a
    `manifest_no`, the containment manifest number for the hauler."

    Design: Corner/validations/rinsate_disposal_field_and_manifest_rules
    """
    env = completed_environment()
    ap = env["applicator"]["id"]
    wo_id = env["work_order"]["id"]
    other_field = create_field(env["customer"]["id"], label="South 20", crop="SOY")

    res1 = api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "FIELD_DISPOSAL", 5.0,
                                      disposal_field_id=other_field["id"]),
        make_applicator_headers(ap))
    validate_error(res1, "ERR_DISPOSAL_FIELD_MISMATCH", expected_status=409)

    res2 = api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "CONTAINMENT_DISPOSAL", 5.0),
        make_applicator_headers(ap))
    validate_error(res2, "ERR_VALIDATION", expected_status=400)

    wo = validate_success(api.get_work_order(wo_id, DISPATCHER), 200)
    assert wo["rinsate_balance_gal"] == pytest.approx(EXPECTED["RINSATE_100AC_GAL"]), \
        "rejected disposals must not move the balance"


def test_rinsate_balance_returns_to_zero(api):
    """PRD §3.7: "The server stamps `recorded_at` from the logical clock,
    decrements the work order's `rinsate_balance_gal` by `volume_gal`, and
    increments the WorkOrder's `version`."
    PRD §3.7: "a `volume_gal` that must be positive (else `ERR_VALIDATION`) and
    no greater than the order's current `rinsate_balance_gal` (else
    `ERR_RINSATE_OVER_DISPOSAL`)."

    Design: Difficulty/compensating_invariant/rinsate_balance_returns_to_zero
    """
    env = completed_environment()
    ap = env["applicator"]["id"]
    wo_id = env["work_order"]["id"]
    assert env["work_order"]["rinsate_generated_gal"] == pytest.approx(24.0)
    assert env["work_order"]["rinsate_balance_gal"] == pytest.approx(24.0)

    validate_success(api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "FIELD_DISPOSAL", 10.0,
                                      disposal_field_id=env["field"]["id"]),
        make_applicator_headers(ap)), 201)
    validate_success(api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "CONTAINMENT_DISPOSAL", 14.0,
                                      manifest_no="MAN-1"),
        make_applicator_headers(ap)), 201)

    wo = validate_success(api.get_work_order(wo_id, DISPATCHER), 200)
    assert wo["rinsate_balance_gal"] == pytest.approx(0.0), \
        "10.0 + 14.0 compensates the generated 24.0 exactly"

    res = api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "CONTAINMENT_DISPOSAL", 0.1,
                                      manifest_no="MAN-2"),
        make_applicator_headers(ap))
    validate_error(res, "ERR_RINSATE_OVER_DISPOSAL", expected_status=409)


def test_rinsate_zero_volume_and_exact_full_disposal(api):
    """PRD §3.7: "a `volume_gal` that must be positive (else `ERR_VALIDATION`)
    and no greater than the order's current `rinsate_balance_gal` (else
    `ERR_RINSATE_OVER_DISPOSAL`)."

    Design: Difficulty/compensating_invariant/rinsate_balance_returns_to_zero
    """
    env = completed_environment()
    ap = env["applicator"]["id"]
    wo_id = env["work_order"]["id"]

    res = api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "CONTAINMENT_DISPOSAL", 0,
                                      manifest_no="MAN-0"),
        make_applicator_headers(ap))
    validate_error(res, "ERR_VALIDATION", expected_status=400)

    # Disposing exactly the current balance is allowed (not greater than it).
    validate_success(api.create_rinsate_record(
        create_rinsate_record_payload(wo_id, "CONTAINMENT_DISPOSAL", 24.0,
                                      manifest_no="MAN-1"),
        make_applicator_headers(ap)), 201)
    wo = validate_success(api.get_work_order(wo_id, DISPATCHER), 200)
    assert wo["rinsate_balance_gal"] == pytest.approx(0.0)


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §3.6: "The ApplicationRecord is the compliance copy of the job —
    exactly one per work order, discovered through the `work_order_id` filter
    on the record list."
    PRD §3.9: "Invoices can be listed and filtered by `work_order_id` or
    `status`."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns
    resources sorted by `created_at` in ascending order."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    env = completed_environment(num_products=1)
    wo_id = env["work_order"]["id"]

    orders, _ = validate_paginated(api.list_work_orders(DISPATCHER))
    assert any(o["id"] == wo_id for o in orders), \
        "the created work order is reachable in the work-order list"

    records, _ = validate_paginated(api.list_application_records(
        COMPLIANCE, params={"work_order_id": wo_id}))
    assert len(records) == 1, "the 1:1 record resolves as a single-element array"
    assert records[0]["work_order_id"] == wo_id

    invoices, _ = validate_paginated(api.list_invoices(ADMIN, params={"work_order_id": wo_id}))
    assert len(invoices) == 1
    assert invoices[0]["work_order_id"] == wo_id
    assert invoices[0]["status"] == "DRAFT"
