"""Quoting, fiscal gates, and export-document consistency (PRD §2.8, §3.1, §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_version_incremented,
    create_item_payload, create_design_payload, approve_design_payload,
    packing_list_line, create_packing_list_payload,
    invoice_line, create_commercial_invoice_payload,
    create_customer, create_job, add_item, create_wood_batch,
    submit_and_approve_design, accept_quote, make_customer_headers,
    setup_quoted_job_with_item, setup_job_with_approved_design,
    setup_packing_job_with_crate, setup_closed_job_with_completed_booking,
    setup_delivered_job,
    assert_packing_list, assert_commercial_invoice,
    STD100,
)
from test_helpers import TEST_USERS

SR = TEST_USERS["sales_rep_headers"]
CD = TEST_USERS["crating_designer_headers"]
SF = TEST_USERS["shop_foreman_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Pinned quote evaluation order (difficulty: combinatorial_formula)
# ---------------------------------------------------------------------------

def _setup_quoted_shop_job_with_design():
    return setup_job_with_approved_design(
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000},
        batch_overrides={"received_board_feet": 5000, "stamps_acquired": 4})


def test_quote_breakdown_lines_and_subtotal(api, sales_rep_headers):
    """PRD §3.1: "The provisional quote is a computed read with a pinned evaluation order: line components first, then the subtotal, then the handling fee keyed on that subtotal, then the fuel surcharge, then the total. The wood component multiplies the job's `total_board_feet` by 350 cents per board foot, then applies a volume discount to the whole wood cost — ten percent when the job consumes at least 500 board feet, five percent when it consumes at least 200, nothing below that — rounding the discounted figure half-up to whole cents."

    Design: Difficulty/combinatorial_formula/job_total_price_pinned_evaluation_order
    """
    ctx = _setup_quoted_shop_job_with_design()
    quote = validate_success(api.get_quote(ctx["job"]["id"], sales_rep_headers), 200)
    assert quote["total_board_feet"] == 56
    assert quote["total_chargeable_weight_kg"] == pytest.approx(96.0, abs=0.001), \
        "dimensional 96.0 exceeds actual 40"
    assert quote["estimated_labor_hours"] == 1, "ceil(0.48 * 1.5)"
    assert quote["subtotal_cents"] == 29000, \
        "wood 56*350=19600 (no discount below 200 bf) + labor 1*8500 + protection 900 + hazmat 0"


def test_quote_handling_fuel_and_total(api, sales_rep_headers):
    """PRD §3.1: "The handling fee is three percent of the subtotal when the subtotal reaches 2000000 cents, five percent when it reaches 500000 cents, and eight percent otherwise, rounded half-up to whole cents. The fuel surcharge is nine percent of the subtotal plus handling, again rounded half-up. The quote total is subtotal plus handling plus fuel."

    Design: Difficulty/combinatorial_formula/job_total_price_pinned_evaluation_order
    """
    ctx = _setup_quoted_shop_job_with_design()
    quote = validate_success(api.get_quote(ctx["job"]["id"], sales_rep_headers), 200)
    assert quote["handling_fee_cents"] == 2320, \
        "8% tier keyed on the subtotal 29000, not on the total"
    assert quote["fuel_surcharge_cents"] == 2819, \
        "9% of (subtotal + handling) = 9% of 31320 = 2818.8 -> round half-up 2819"
    assert quote["quoted_price_cents"] == 34139


# ---------------------------------------------------------------------------
# ONSITE quote mode constants (corner: calculations)
# ---------------------------------------------------------------------------

def test_quote_onsite_mode_hours_and_labor(api, sales_rep_headers):
    """PRD §3.1: "`estimated_labor_hours` takes the total item volume in cubic meters, multiplies by the mode's hours-per-cubic-meter rate (one and a half for `SHOP`, two and a half for `ONSITE`), and rounds up to the next whole hour."
    PRD §3.1: "The labor component multiplies `estimated_labor_hours` by the mode's hourly rate (8500 cents for `SHOP`, 12000 cents for `ONSITE`) and adds a flat travel charge of 15000 cents for `ONSITE` jobs only."

    Design: Corner/calculations/quote_onsite_mode_multiplier
    """
    ctx = setup_job_with_approved_design(
        mode="ONSITE", incoterm="EXW",
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000})
    quote = validate_success(api.get_quote(ctx["job"]["id"], sales_rep_headers), 200)
    assert quote["estimated_labor_hours"] == 2, "ceil(0.48 * 2.5)"
    assert quote["labor_cost_cents"] == 39000, "2 * 12000 + 15000 travel flat"


def test_quote_onsite_mode_total(api, sales_rep_headers):
    """PRD §3.1: "The handling fee is three percent of the subtotal when the subtotal reaches 2000000 cents, five percent when it reaches 500000 cents, and eight percent otherwise, rounded half-up to whole cents. The fuel surcharge is nine percent of the subtotal plus handling, again rounded half-up. The quote total is subtotal plus handling plus fuel."

    Design: Corner/calculations/quote_onsite_mode_multiplier
    """
    ctx = setup_job_with_approved_design(
        mode="ONSITE", incoterm="EXW",
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000})
    quote = validate_success(api.get_quote(ctx["job"]["id"], sales_rep_headers), 200)
    assert quote["subtotal_cents"] == 59500, "wood 19600 + labor 39000 + protection 900"
    assert quote["handling_fee_cents"] == 4760
    assert quote["fuel_surcharge_cents"] == 5783
    assert quote["quoted_price_cents"] == 70043


# ---------------------------------------------------------------------------
# Credit ceiling at acceptance (corner: validations)
# ---------------------------------------------------------------------------

def test_accept_quote_beyond_credit_limit_rejected(api):
    """PRD §3.1: "adding this job's quoted price to `open_exposure_cents` would not exceed `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Corner/validations/credit_limit_exceeded_on_accept
    """
    ctx = setup_job_with_approved_design(
        customer_overrides={"name": "Credit Co", "site_code": "CRD-01",
                            "credit_limit_cents": 30000},
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000})
    res = api.accept_quote(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=422)


def test_rejected_accept_quote_leaves_exposure_and_state_untouched(api):
    """PRD §3.1: "Acceptance freezes `quoted_price_cents` as a snapshot of the provisional quote at that instant, adds it to the customer's `open_exposure_cents`, moves the job from `QUOTED` to `DESIGN`".

    Design: Corner/validations/credit_limit_exceeded_on_accept
    """
    ctx = setup_job_with_approved_design(
        customer_overrides={"name": "Credit Co", "site_code": "CRD-01",
                            "credit_limit_cents": 30000},
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000})
    api.accept_quote(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    customer = validate_success(api.get_customer(ctx["customer"]["id"], SR), 200)
    assert customer["open_exposure_cents"] == 0, "no partial mutation on a rejected accept"
    job = validate_success(api.get_packing_job(ctx["job"]["id"], SR), 200)
    assert job["status"] == "QUOTED"


# ---------------------------------------------------------------------------
# State-vs-fiscal priority at accept (difficulty: priority_pair_validation_conflict)
# ---------------------------------------------------------------------------

def _setup_double_accept_with_lowered_credit():
    customer, job, item = setup_quoted_job_with_item(
        customer_overrides={"name": "Prio Co", "site_code": "PRI-01",
                            "credit_limit_cents": 40000},
        item_overrides={"description": "Pump assembly", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 500000})
    accept_quote(customer, job["id"])
    get_success_data(api_client.patch_customer(
        customer["id"], {"credit_limit_cents": 1000}, SR))
    return {"customer": customer, "job": job, "item": item}


def test_second_accept_quote_reports_state_error(api):
    """PRD §2.8: "Beyond resolution, every request walks a single validation ladder, and when a request would fail several checks the failure earliest in this ladder is the one reported. The tiers, in order: ... 6. **Lifecycle state guards** — the job-state guard `ERR_JOB_INVALID_STATE` ... 11. **Fiscal ceilings** — credit exposure (`ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/accept_quote_state_beats_fiscal
    """
    ctx = _setup_double_accept_with_lowered_credit()
    res = api.accept_quote(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    # Both the job-state guard (already DESIGN) and the credit ceiling
    # (limit 1000 < exposure 34139) fail; the earlier ladder tier is reported.
    validate_error(res, "ERR_JOB_INVALID_STATE", expected_status=409)


def test_second_accept_quote_leaves_job_in_design(api):
    """PRD §3.1: "the customer may accept the quote. Acceptance freezes `quoted_price_cents` as a snapshot of the provisional quote at that instant, adds it to the customer's `open_exposure_cents`, moves the job from `QUOTED` to `DESIGN`".

    Design: Difficulty/priority_pair_validation_conflict/accept_quote_state_beats_fiscal
    """
    ctx = _setup_double_accept_with_lowered_credit()
    api.accept_quote(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    job = validate_success(api.get_packing_job(ctx["job"]["id"], SR), 200)
    assert job["status"] == "DESIGN"


# ---------------------------------------------------------------------------
# Job PATCH OCC (corner: cross_cutting_layers)
# ---------------------------------------------------------------------------

def test_job_patch_increments_version_and_applies_terms(api, sales_rep_headers):
    """PRD §3.1: "the job's `mode` and `incoterm` may be revised while `QUOTED`, subject to the optimistic-concurrency rule of §2.7, and each such revision recomputes the live quote."
    PRD §2.4: "`version` (integer): a system-managed integer that increments with every modification to the resource".

    Design: Corner/cross_cutting_layers/job_version_increments_on_patch
    """
    customer = create_customer(name="Ver Co", site_code="VER-01")
    job = create_job(customer)
    assert job["version"] == 1
    patched = validate_success(api.patch_packing_job(
        job["id"], {"expected_packing_job_version": job["version"], "incoterm": "DDP"},
        sales_rep_headers), 200)
    assert_version_incremented(patched["version"], job["version"])
    assert patched["version"] == 2
    assert patched["incoterm"] == "DDP"


def test_job_patch_with_stale_version_rejected(api, sales_rep_headers):
    """PRD §2.7: "Revising a quoted job's terms is legitimate at any time while the job remains `QUOTED`, but the request must carry `expected_packing_job_version` equal to the job's current `version`. If the job's version no longer matches — for example because an item was captured after the caller's last read — the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the quote basis is stale."

    Design: Corner/cross_cutting_layers/occ_stale_job_patch
    """
    customer = create_customer(name="OCC Job Co", site_code="OCJ-01")
    job = create_job(customer)
    get_success_data(api_client.patch_packing_job(
        job["id"], {"expected_packing_job_version": job["version"], "incoterm": "DDP"}, SR))
    res = api.patch_packing_job(
        job["id"], {"expected_packing_job_version": job["version"], "incoterm": "EXW"},
        sales_rep_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    job_after = validate_success(api.get_packing_job(job["id"], sales_rep_headers), 200)
    assert job_after["incoterm"] == "DDP", "the rejected PATCH must not mutate the job"


# ---------------------------------------------------------------------------
# Packing list upsert (corner: endpoints)
# ---------------------------------------------------------------------------

def _setup_design_job_with_crate():
    return setup_job_with_approved_design(
        item_overrides={"description": "CNC spindle", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 200000},
        batch_overrides={"received_board_feet": 5000, "stamps_acquired": 2},
        accept=True)


def _add_crate(ctx):
    crate = get_success_data(api_client.create_crate(
        ctx["item"]["id"], {"design_id": ctx["design"]["id"]}, SF))
    ctx["crate"] = crate
    return ctx


def test_packing_list_upsert_replaces_lines_wholesale(api, sales_rep_headers):
    """PRD §3.7: "each upserted — created or replaced in full — only while the document itself is `DRAFT` or `AMENDING`".
    PRD §3.7: "The document's `total_gross_weight_kg` is the sum of its lines' gross weights, kept to two decimal places."

    Design: Corner/endpoints/packing_list_upsert_replaces_lines
    """
    ctx = _add_crate(_setup_design_job_with_crate())
    pl1 = validate_success(api.upsert_packing_list(
        ctx["job"]["id"], create_packing_list_payload([packing_list_line(
            ctx["crate"]["id"], "CNC spindle", 1, 40.0, 140.8)]),
        sales_rep_headers), 201)
    assert pl1["total_gross_weight_kg"] == pytest.approx(140.8, abs=0.001)

    pl2 = validate_success(api.upsert_packing_list(
        ctx["job"]["id"], create_packing_list_payload([packing_list_line(
            ctx["crate"]["id"], "CNC spindle x2", 2, 80.0, 281.6)]),
        sales_rep_headers), 201)
    assert pl2["total_gross_weight_kg"] == pytest.approx(281.6, abs=0.001)
    assert pl2["id"] == pl1["id"], "the upsert replaces the same document, not a new row"
    assert pl2["status"] == "DRAFT"


def test_packing_list_upsert_leaves_single_document_per_job(api, sales_rep_headers):
    """PRD §3.7: "Two documents travel with every export job, each existing at most once per job (a second create is rejected with `ERR_DUPLICATE`), and each upserted — created or replaced in full — only while the document itself is `DRAFT` or `AMENDING`".

    Design: Corner/endpoints/packing_list_upsert_replaces_lines
    """
    ctx = _add_crate(_setup_design_job_with_crate())
    api.upsert_packing_list(ctx["job"]["id"], create_packing_list_payload([packing_list_line(
        ctx["crate"]["id"], "CNC spindle", 1, 40.0, 140.8)]), SR)
    api.upsert_packing_list(ctx["job"]["id"], create_packing_list_payload([packing_list_line(
        ctx["crate"]["id"], "CNC spindle x2", 2, 80.0, 281.6)]), SR)
    data, meta = validate_paginated(api.list_packing_lists(
        sales_rep_headers, params={"packing_job_id": ctx["job"]["id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Commercial invoice per-line duty rounding (difficulty: combinatorial_formula)
# ---------------------------------------------------------------------------

def _setup_design_job_with_two_crates():
    customer = create_customer(name="Duty Co", site_code="DTY-01")
    job = create_job(customer, mode="SHOP", incoterm="EXW")
    item1 = add_item(job["id"], description="Valve A", weight_kg=50,
                     declared_value_cents=10100)
    item2 = add_item(job["id"], description="Valve B", weight_kg=50,
                     declared_value_cents=10300)
    batch = create_wood_batch(received_board_feet=5000, stamps_acquired=4)
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    accept_quote(customer, job["id"])
    crate1 = get_success_data(api_client.create_crate(item1["id"], {"design_id": d1["id"]}, SF))
    crate2 = get_success_data(api_client.create_crate(item2["id"], {"design_id": d2["id"]}, SF))
    return {"customer": customer, "job": job, "crate1": crate1, "crate2": crate2}


def test_invoice_per_line_rounding_produces_pinned_totals(api, sales_rep_headers):
    """PRD §3.7: "`invoice_total_cents` sums, over all lines, each line's quantity multiplied by its unit price and rounded half-up to whole cents — rounding each line first and summing second, never the reverse — and `duty_total_cents` sums, over all lines, each rounded line total multiplied by its `duty_rate_bp`, divided by 10000, and rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/invoice_duty_per_line_rounding_order
    """
    ctx = _setup_design_job_with_two_crates()
    invoice = validate_success(api.upsert_commercial_invoice(
        ctx["job"]["id"], create_commercial_invoice_payload([
            invoice_line(ctx["crate1"]["id"], "Valve A", 1, 10100, 750),
            invoice_line(ctx["crate2"]["id"], "Valve B", 1, 10300, 750),
        ]), sales_rep_headers), 201)
    assert_commercial_invoice(invoice)
    assert invoice["invoice_total_cents"] == 20400
    assert invoice["duty_total_cents"] == 1531, \
        "per-line: round(757.5)=758 + round(772.5)=773"


def test_invoice_duty_total_differs_from_forbidden_sum_then_round(api, sales_rep_headers):
    """PRD §3.7: "rounding each line first and summing second, never the reverse".

    Design: Difficulty/combinatorial_formula/invoice_duty_per_line_rounding_order
    """
    ctx = _setup_design_job_with_two_crates()
    invoice = validate_success(api.upsert_commercial_invoice(
        ctx["job"]["id"], create_commercial_invoice_payload([
            invoice_line(ctx["crate1"]["id"], "Valve A", 1, 10100, 750),
            invoice_line(ctx["crate2"]["id"], "Valve B", 1, 10300, 750),
        ]), sales_rep_headers), 201)
    # The forbidden sum-then-round order yields round(20400 * 0.075) = 1530.
    assert invoice["duty_total_cents"] != 1530
    assert invoice["duty_total_cents"] == 1531


# ---------------------------------------------------------------------------
# Release-time consistency checks in pinned sub-order (corner: validations)
# ---------------------------------------------------------------------------

def _setup_finalized_docs(pl_lines, ci_lines, item_overrides=None):
    ctx = _add_crate(setup_job_with_approved_design(
        item_overrides=item_overrides or {"description": "Valve A", "weight_kg": 50,
                                          "declared_value_cents": 10000},
        batch_overrides={"received_board_feet": 5000, "stamps_acquired": 2},
        accept=True))
    get_success_data(api_client.upsert_packing_list(
        ctx["job"]["id"], create_packing_list_payload(pl_lines(ctx)), SR))
    get_success_data(api_client.upsert_commercial_invoice(
        ctx["job"]["id"], create_commercial_invoice_payload(ci_lines(ctx)), SR))
    get_success_data(api_client.finalize_docs(ctx["job"]["id"], SR))
    return ctx


def test_release_docs_crate_set_mismatch_rejected(api, compliance_officer_headers):
    """PRD §3.7: "First, the set of crate identifiers in the packing list's lines must equal the set in the invoice's lines (otherwise `ERR_DOC_CRATE_MISMATCH`)."

    Design: Corner/validations/doc_crate_set_mismatch_on_release
    """
    # Two crates on the job; the packing list covers crate1 only while the
    # invoice covers both.
    customer = create_customer(name="Doc Co", site_code="DOC-01")
    job = create_job(customer)
    item1 = add_item(job["id"], description="Valve A", weight_kg=50,
                     declared_value_cents=10000)
    item2 = add_item(job["id"], description="Valve B", weight_kg=50,
                     declared_value_cents=10000)
    batch = create_wood_batch(received_board_feet=5000, stamps_acquired=2)
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    accept_quote(customer, job["id"])
    crate1 = get_success_data(api_client.create_crate(item1["id"], {"design_id": d1["id"]}, SF))
    crate2 = get_success_data(api_client.create_crate(item2["id"], {"design_id": d2["id"]}, SF))
    get_success_data(api_client.upsert_packing_list(
        job["id"], create_packing_list_payload([
            packing_list_line(crate1["id"], "Valve A", 1, 50.0, 98.6)]), SR))
    get_success_data(api_client.upsert_commercial_invoice(
        job["id"], create_commercial_invoice_payload([
            invoice_line(crate1["id"], "Valve A", 1, 10000),
            invoice_line(crate2["id"], "Valve B", 1, 10000)]), SR))
    get_success_data(api_client.finalize_docs(job["id"], SR))
    res = api.release_docs(job["id"], compliance_officer_headers)
    validate_error(res, "ERR_DOC_CRATE_MISMATCH", expected_status=422)
    pls, _ = validate_paginated(api.list_packing_lists(CO, params={"packing_job_id": job["id"]}))
    cis, _ = validate_paginated(api.list_commercial_invoices(CO, params={"packing_job_id": job["id"]}))
    assert pls[0]["status"] == "FINALIZED" and cis[0]["status"] == "FINALIZED", \
        "a rejected release must not move either document"


def test_release_docs_quantity_mismatch_rejected(api, compliance_officer_headers):
    """PRD §3.7: "Second, crate by crate, the quantity on the packing list must equal the quantity on the invoice (otherwise `ERR_DOC_QUANTITY_MISMATCH`)."

    Design: Corner/validations/doc_quantity_mismatch_on_release
    """
    ctx = _setup_finalized_docs(
        lambda c: [packing_list_line(c["crate"]["id"], "Valve A", 1, 50.0, 98.6)],
        lambda c: [invoice_line(c["crate"]["id"], "Valve A", 2, 5000)])
    res = api.release_docs(ctx["job"]["id"], compliance_officer_headers)
    validate_error(res, "ERR_DOC_QUANTITY_MISMATCH", expected_status=422)


def test_release_docs_weight_mismatch_rejected(api, compliance_officer_headers):
    """PRD §3.7: "Third, the packing list's `total_gross_weight_kg` must lie within half a kilogram of the sum of the crates' `gross_weight_kg` (otherwise `ERR_DOC_WEIGHT_MISMATCH`)."

    Design: Corner/validations/doc_weight_mismatch_on_release
    """
    ctx = _setup_finalized_docs(
        lambda c: [packing_list_line(c["crate"]["id"], "Valve A", 1, 50.0, 9999.0)],
        lambda c: [invoice_line(c["crate"]["id"], "Valve A", 1, 10000)])
    res = api.release_docs(ctx["job"]["id"], compliance_officer_headers)
    validate_error(res, "ERR_DOC_WEIGHT_MISMATCH", expected_status=422)


def test_release_docs_undervalued_invoice_rejected(api, compliance_officer_headers):
    """PRD §3.7: "Fourth, the invoice's `invoice_total_cents` must reach at least ninety-five percent of the sum of the job's items' `declared_value_cents` (otherwise `ERR_INVOICE_UNDERVALUED`)."

    Design: Corner/validations/invoice_undervalued_on_release
    """
    ctx = _setup_finalized_docs(
        lambda c: [packing_list_line(c["crate"]["id"], "CNC spindle", 1, 40.0, 140.8)],
        lambda c: [invoice_line(c["crate"]["id"], "CNC spindle", 1, 100000)],
        item_overrides={"description": "CNC spindle", "length_cm": 100, "width_cm": 80,
                        "height_cm": 60, "weight_kg": 40, "declared_value_cents": 200000})
    res = api.release_docs(ctx["job"]["id"], compliance_officer_headers)
    validate_error(res, "ERR_INVOICE_UNDERVALUED", expected_status=422)


# ---------------------------------------------------------------------------
# Provisional vs final quote variants (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------

def test_close_computes_final_invoice_from_completed_labor(api, sales_rep_headers):
    """PRD §3.9: "Closing computes the final invoice: `invoiced_total_cents` — null until this moment — takes the FINAL variant of the quote formula of §3.1, identical in structure except that the labor component is the sum of `total_cost_cents` over the job's `COMPLETED` labor bookings, actual hours at actual rates with each booking's travel surcharge, rather than the volume-derived estimate".
    PRD §3.6: "Each booking computes its own economics: `hours` is the interval's duration in seconds divided by 3600 and rounded to two decimals; `rate_cents_per_hour` is 8500 for `SHOP` work and 12000 for `ONSITE`; `travel_surcharge_cents` is a flat 15000 per `ONSITE` booking and zero for `SHOP`; and `total_cost_cents` is the hours-times-rate figure rounded half-up to whole cents plus the travel surcharge."

    Design: Difficulty/dual_variant_calc/job_quote_provisional_vs_final_labor
    """
    ctx = setup_closed_job_with_completed_booking()
    closed = validate_success(api.close_job(ctx["job"]["id"], sales_rep_headers), 200)
    assert closed["status"] == "CLOSED"
    # FINAL variant: actual 3.0h SHOP = 25500 -> subtotal 19600+25500+900 = 46000;
    # handling 8% = 3680; fuel 9% of 49680 = 4471 (round half-up of 4471.2).
    assert closed["invoiced_total_cents"] == 54151


def test_final_invoice_diverges_from_frozen_provisional_quote(api, sales_rep_headers):
    """PRD §3.9: "the same cargo therefore produces a different total whenever actual hours diverge from the estimate."
    PRD §3.1: "Acceptance freezes `quoted_price_cents` as a snapshot of the provisional quote at that instant".

    Design: Difficulty/dual_variant_calc/job_quote_provisional_vs_final_labor
    """
    ctx = setup_closed_job_with_completed_booking()
    closed = validate_success(api.close_job(ctx["job"]["id"], sales_rep_headers), 200)
    # Provisional snapshot at accept: est labor 1h*8500 -> subtotal 29000,
    # handling 2320, fuel 2819 -> 34139.
    assert closed["quoted_price_cents"] == 34139
    assert closed["invoiced_total_cents"] != closed["quoted_price_cents"], \
        "identical item data, two algorithm variants diverging on the labor input set"
