"""Estimate quoting and invoice billing — the dual-mode pricing engine.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, and the
invoice-money compensating invariant.
Queue B (Corner): estimate/invoice calculation correctness and constants.
"""
from test_helpers import (
    validate_success, ApiErrorId, TEST_USERS, make_customer_headers, make_technician_headers,
    assert_invoice_total_consistent,
    make_customer, make_technician, make_sku, stock_truck, make_membership_plan,
    enroll_membership, make_job, current_job_version, quote_and_accept,
    dispatch_tech, depart_and_arrive, record_usage, void_usage, complete_job, invoice_job,
    set_clock,
)

DISP = TEST_USERS["dispatcher_headers"]


# ─── Queue A: dual_variant_calc ───────────────────────────────────────────
def test_dual_variant_quote_forward_looking_vs_invoice_actual(api):
    """PRD §3.3: "The quoted total is a forward-looking projection built only from the
    estimate's own inputs ... if no technician has been dispatched yet, the system uses
    the default zone rate of 12000 cents per hour. This quote deliberately uses estimated
    hours and materials, never realized actuals."
    PRD §3.7: "Unlike the forward-looking quote, the invoice is chronological and built
    from realized work — the non-voided material usages, the accepted estimate, the job's
    snapshotted membership, and the job's priority."

    Design: Difficulty/dual_variant_calc/dual_variant_quote_estimate_vs_invoice_actual
    """
    cust = make_customer(full_name="Q Cust", email="dv1@x.com", service_zip="10001", phone="555")
    tech = make_technician(full_name="Master T", license_class="MASTER", service_zone="100",
                           hourly_rate_cents=12000, on_call=False)
    sku = make_sku(sku_code="DV1-SKU", description="Wire", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=5, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")

    # TIME_MATERIALS estimate, no technician dispatched at quote time -> DEFAULT_HOURLY_RATE 12000.
    est, _ = quote_and_accept(job["id"], cust["id"], pricing_mode="TIME_MATERIALS",
                              estimated_labor_hours=3, estimated_material_cents=4500)
    assert est["quoted_total_cents"] == 40500  # rhu(3*12000)+4500

    disp = dispatch_tech(job["id"], tech["id"], "2026-07-01T09:00:00Z", "2026-07-01T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    record_usage(job["id"], tech["id"], sku["id"], 3)
    complete_job(job["id"], tech["id"], actual_labor_hours=2)

    invoiced = invoice_job(job["id"])
    # 24000 labor + 3000 material + 8900 dispatch + 248 tax (rhu(3000*0.0825)=247.5 -> 248)
    assert invoiced["total_due_cents"] == 36148
    assert est["quoted_total_cents"] != invoiced["total_due_cents"]


def test_dual_variant_quote_uses_estimated_not_actual_hours(api):
    """PRD §3.3: "This quote deliberately uses estimated hours and materials, never realized
    actuals."
    PRD §3.7 step 1: "for `TIME_MATERIALS`, the labor subtotal is the `actual_labor_hours`
    supplied on completion multiplied by the technician's `hourly_rate_cents`, rounded half
    up to whole cents."

    Design: Difficulty/dual_variant_calc/dual_variant_quote_estimate_vs_invoice_actual
    """
    cust = make_customer(full_name="Q2 Cust", email="dv1b@x.com", service_zip="10001", phone="555")
    tech = make_technician(full_name="Master T2", license_class="MASTER", service_zone="100",
                           hourly_rate_cents=12000, on_call=False)
    sku = make_sku(sku_code="DV1B-SKU", description="Wire", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=5, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    est, _ = quote_and_accept(job["id"], cust["id"], pricing_mode="TIME_MATERIALS",
                              estimated_labor_hours=3, estimated_material_cents=4500)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-01T09:00:00Z", "2026-07-01T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    record_usage(job["id"], tech["id"], sku["id"], 3)
    complete_job(job["id"], tech["id"], actual_labor_hours=2)  # actual 2h, not estimated 3h
    invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    # invoice labor uses ACTUAL hours (2 * 12000), not the estimated 3h that drove the quote.
    assert inv["labor_subtotal_cents"] == 24000
    assert inv["material_subtotal_cents"] == 3000


def test_dual_variant_member_vs_nonmember_invoice(api):
    """PRD §3.7 step 3: "If the job carries a non-null `membership_id` and that membership's
    plan has `waives_dispatch_fee` set true, the dispatch fee is 0; otherwise it is the full
    8900 cents."
    PRD §3.7 step 5: "if the job carries a non-null `membership_id`, the discount is the
    `labor_subtotal_cents` multiplied by that plan's `labor_discount_pct`, rounded half up
    to whole cents; if the job has no membership, the discount is 0."

    Design: Difficulty/dual_variant_calc/dual_variant_member_vs_nonmember_invoice
    """
    plan = make_membership_plan(name="Premier", tier="PREMIER", monthly_fee_cents=2999,
                                labor_discount_pct=0.20, waives_dispatch_fee=True, priority_dispatch=True)
    mem = make_customer(full_name="Mem Cust", email="dv2m@x.com", service_zip="20001", phone="555")
    enroll_membership(mem["id"], plan["id"])
    non = make_customer(full_name="Non Cust", email="dv2n@x.com", service_zip="20002", phone="555")
    tech = make_technician(full_name="Z Tech", license_class="JOURNEYMAN", service_zone="200",
                           hourly_rate_cents=11000, on_call=False)

    mjob = make_job(mem["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(mjob["id"], mem["id"], pricing_mode="FLAT_RATE", flat_rate_cents=40000)
    mdisp = dispatch_tech(mjob["id"], tech["id"], "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
    depart_and_arrive(mdisp["id"], tech["id"])
    complete_job(mjob["id"], tech["id"])
    minv = invoice_job(mjob["id"])
    # labor 40000 - rhu(40000*0.20)=8000 + 0 material + 0 dispatch (waived) = 32000
    assert minv["total_due_cents"] == 32000

    njob = make_job(non["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(njob["id"], non["id"], pricing_mode="FLAT_RATE", flat_rate_cents=40000)
    ndisp = dispatch_tech(njob["id"], tech["id"], "2026-07-02T11:00:00Z", "2026-07-02T12:00:00Z")
    depart_and_arrive(ndisp["id"], tech["id"])
    complete_job(njob["id"], tech["id"])
    ninv = invoice_job(njob["id"])
    # labor 40000 - 0 + 0 material + 8900 dispatch = 48900
    assert ninv["total_due_cents"] == 48900
    assert minv["total_due_cents"] != ninv["total_due_cents"]


def test_dual_variant_member_discount_and_dispatch_fee_components(api):
    """PRD §3.7: "A member-billed job (one with a non-null `membership_id`) differs from a
    non-member job in exactly two ways: the labor discount is subtracted, and the dispatch fee
    may be waived per the plan's flags; a non-member job receives no discount and always pays
    the full dispatch fee."

    Design: Difficulty/dual_variant_calc/dual_variant_member_vs_nonmember_invoice
    """
    plan = make_membership_plan(name="Premier2", tier="PREMIER", monthly_fee_cents=2999,
                                labor_discount_pct=0.20, waives_dispatch_fee=True, priority_dispatch=True)
    mem = make_customer(full_name="Mem2", email="dv2m2@x.com", service_zip="20001", phone="555")
    enroll_membership(mem["id"], plan["id"])
    non = make_customer(full_name="Non2", email="dv2n2@x.com", service_zip="20002", phone="555")
    tech = make_technician(full_name="Z Tech2", license_class="JOURNEYMAN", service_zone="200",
                           hourly_rate_cents=11000, on_call=False)

    mjob = make_job(mem["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(mjob["id"], mem["id"], pricing_mode="FLAT_RATE", flat_rate_cents=40000)
    mdisp = dispatch_tech(mjob["id"], tech["id"], "2026-07-02T13:00:00Z", "2026-07-02T14:00:00Z")
    depart_and_arrive(mdisp["id"], tech["id"])
    complete_job(mjob["id"], tech["id"])
    invoice_job(mjob["id"])
    minv = validate_success(api.list_invoices(DISP, params={"job_id": mjob["id"]}), 200)[0]
    assert minv["discount_cents"] == 8000      # rhu(40000*0.20)
    assert minv["dispatch_fee_cents"] == 0     # waived for this member plan

    njob = make_job(non["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(njob["id"], non["id"], pricing_mode="FLAT_RATE", flat_rate_cents=40000)
    ndisp = dispatch_tech(njob["id"], tech["id"], "2026-07-02T15:00:00Z", "2026-07-02T16:00:00Z")
    depart_and_arrive(ndisp["id"], tech["id"])
    complete_job(njob["id"], tech["id"])
    invoice_job(njob["id"])
    ninv = validate_success(api.list_invoices(DISP, params={"job_id": njob["id"]}), 200)[0]
    assert ninv["discount_cents"] == 0         # no membership -> no discount
    assert ninv["dispatch_fee_cents"] == 8900  # full dispatch fee


# ─── Queue A: combinatorial_formula ───────────────────────────────────────
def test_combinatorial_invoice_round_then_sum_half_up(api):
    """PRD §2.8: "the result is rounded half up to the nearest whole cent. Each such
    rounding step is applied independently at the point it occurs; the system rounds at
    each step and then sums, rather than summing exact intermediate values and rounding
    once at the end."
    PRD §3.7 step 5: "the discount is the `labor_subtotal_cents` multiplied by that plan's
    `labor_discount_pct`, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/combinatorial_invoice_round_then_sum_half_up
    """
    plan = make_membership_plan(name="Eighth", tier="BASIC", monthly_fee_cents=1000,
                                labor_discount_pct=0.125, waives_dispatch_fee=True, priority_dispatch=False)
    cust = make_customer(full_name="Round Cust", email="cf1@x.com", service_zip="30001", phone="555")
    enroll_membership(cust["id"], plan["id"])
    tech = make_technician(full_name="M3 Tech", license_class="MASTER", service_zone="300",
                           hourly_rate_cents=13000, on_call=False)
    sku = make_sku(sku_code="CF1-SKU", description="Conduit", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=10, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="TIME_MATERIALS",
                     estimated_labor_hours=2.5, estimated_material_cents=4000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-03T09:00:00Z", "2026-07-03T12:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    record_usage(job["id"], tech["id"], sku["id"], 4)
    complete_job(job["id"], tech["id"], actual_labor_hours=2.5)

    invoiced = invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    assert inv["labor_subtotal_cents"] == 32500      # rhu(2.5*13000)
    assert inv["discount_cents"] == 4063             # rhu(32500*0.125)=rhu(4062.5) half-up
    assert inv["tax_cents"] == 330                   # rhu(4000*0.0825)=rhu(330.0)
    assert invoiced["total_due_cents"] == 32767      # (32500-4063)+4000+0+0+330
    assert_invoice_total_consistent(inv)


def test_combinatorial_invoice_tax_independent_half_up_step(api):
    """PRD §2.8: "Each such rounding step is applied independently at the point it occurs;
    the system rounds at each step and then sums, rather than summing exact intermediate
    values and rounding once at the end."
    PRD §3.7 step 6: "the taxable material base ... multiplied by the tax rate of 0.0825,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/combinatorial_invoice_round_then_sum_half_up
    """
    cust = make_customer(full_name="Tax Cust", email="cf1tax@x.com", service_zip="30001", phone="555")
    tech = make_technician(full_name="MTax Tech", license_class="JOURNEYMAN", service_zone="300",
                           hourly_rate_cents=10000, on_call=False)
    sku = make_sku(sku_code="CFTAX-SKU", description="Conduit", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=10, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-03T13:00:00Z", "2026-07-03T16:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    record_usage(job["id"], tech["id"], sku["id"], 4)  # taxable base 4000
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    assert inv["tax_cents"] == 330   # rhu(4000*0.0825)=rhu(330.0) computed as its own step
    assert_invoice_total_consistent(inv)


def test_combinatorial_invoice_pinned_eval_order_discount_off_labor(api):
    """PRD §3.7: "Its component fields are computed in a pinned order, because later steps
    depend on earlier ones."
    PRD §3.7 step 5: "the discount is the `labor_subtotal_cents` multiplied by that plan's
    `labor_discount_pct`, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/combinatorial_invoice_pinned_eval_order_discount_then_total
    """
    plan = make_membership_plan(name="Tenth", tier="BASIC", monthly_fee_cents=1000,
                                labor_discount_pct=0.10, waives_dispatch_fee=True, priority_dispatch=False)
    cust = make_customer(full_name="Order Cust", email="cf2@x.com", service_zip="31001", phone="555")
    enroll_membership(cust["id"], plan["id"])
    tech = make_technician(full_name="M31 Tech", license_class="MASTER", service_zone="310",
                           hourly_rate_cents=10000, on_call=False)
    sku = make_sku(sku_code="CF2-SKU", description="Box", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=5, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="TIME_MATERIALS",
                     estimated_labor_hours=2, estimated_material_cents=1000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-04T09:00:00Z", "2026-07-04T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    record_usage(job["id"], tech["id"], sku["id"], 1)
    complete_job(job["id"], tech["id"], actual_labor_hours=2)

    invoiced = invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    assert inv["labor_subtotal_cents"] == 20000
    assert inv["discount_cents"] == 2000             # rhu(20000*0.10) — off labor, not total
    assert inv["tax_cents"] == 83                     # rhu(1000*0.0825)=rhu(82.5)
    assert invoiced["total_due_cents"] == 19083       # (20000-2000)+1000+0+0+83
    assert_invoice_total_consistent(inv)


def test_combinatorial_grand_total_consumes_discount_from_labor(api):
    """PRD §3.7 step 7: "the labor subtotal minus the discount, plus the material subtotal,
    plus the dispatch fee, plus the emergency surcharge, plus the tax."
    PRD §3.7 step 5: "the discount is the `labor_subtotal_cents` multiplied by that plan's
    `labor_discount_pct`."

    Design: Difficulty/combinatorial_formula/combinatorial_invoice_pinned_eval_order_discount_then_total
    """
    plan = make_membership_plan(name="Tenth2", tier="BASIC", monthly_fee_cents=1000,
                                labor_discount_pct=0.10, waives_dispatch_fee=True, priority_dispatch=False)
    cust = make_customer(full_name="Order2", email="cf2b@x.com", service_zip="31001", phone="555")
    enroll_membership(cust["id"], plan["id"])
    tech = make_technician(full_name="M31b", license_class="MASTER", service_zone="310",
                           hourly_rate_cents=10000, on_call=False)
    sku = make_sku(sku_code="CF2B-SKU", description="Box", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=5, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="TIME_MATERIALS",
                     estimated_labor_hours=2, estimated_material_cents=1000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-04T13:00:00Z", "2026-07-04T15:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    record_usage(job["id"], tech["id"], sku["id"], 1)
    complete_job(job["id"], tech["id"], actual_labor_hours=2)
    invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    # total reconciles to (labor - discount) + material + fees + tax, with discount keyed off labor.
    assert inv["labor_subtotal_cents"] == 20000
    assert inv["discount_cents"] == 2000
    assert inv["total_cents"] == (20000 - 2000) + 1000 + 0 + 0 + 83
    assert_invoice_total_consistent(inv)


# ─── Queue A: compensating invariant on invoice money ─────────────────────
def test_void_excludes_line_from_invoice_money(api):
    """PRD §3.5: "voiding a line sets `voided` to true, restores the truck stock, and
    excludes the line from any future invoice."
    PRD §3.7 step 2: "the sum of `line_total_cents` across all of the job's `MaterialUsage`
    lines whose `voided` flag is false."

    Design: Difficulty/compensating_invariant/invariant_void_excludes_line_from_invoice_money
    """
    cust = make_customer(full_name="CI2 Cust", email="ci2@x.com", service_zip="91001", phone="555")
    tech = make_technician(full_name="CI2 Tech", license_class="JOURNEYMAN", service_zone="910",
                           hourly_rate_cents=10000, on_call=False)
    sku = make_sku(sku_code="CI2-SKU", description="Plate", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=10, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-19T09:00:00Z", "2026-07-19T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    usage_x = record_usage(job["id"], tech["id"], sku["id"], 3)  # 3000
    record_usage(job["id"], tech["id"], sku["id"], 2)            # 2000 (survives)
    void_usage(usage_x["id"], tech["id"])
    complete_job(job["id"], tech["id"])

    invoiced = invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    assert inv["material_subtotal_cents"] == 2000   # only surviving usage Y; X voided -> 0
    assert inv["tax_cents"] == 165                   # rhu(2000*0.0825)=rhu(165.0)
    assert invoiced["total_due_cents"] == 21065      # FLAT 10000 + 2000 material + 8900 dispatch + 165 tax
    assert_invoice_total_consistent(inv)


def test_void_excludes_line_from_taxable_base(api):
    """PRD §3.7 step 6: "the taxable material base — the sum of `line_total_cents` over the
    non-voided usages whose SKU has `taxable` set true — multiplied by the tax rate of 0.0825,
    rounded half up to whole cents."
    PRD §3.5: "voiding a line ... excludes the line from any future invoice."

    Design: Difficulty/compensating_invariant/invariant_void_excludes_line_from_invoice_money
    """
    cust = make_customer(full_name="VT Cust", email="ci2tax@x.com", service_zip="91001", phone="555")
    tech = make_technician(full_name="VT Tech", license_class="JOURNEYMAN", service_zone="910",
                           hourly_rate_cents=10000, on_call=False)
    sku = make_sku(sku_code="VT-SKU", description="Plate", unit_price_cents=1000, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=10, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-20T09:00:00Z", "2026-07-20T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    usage_x = record_usage(job["id"], tech["id"], sku["id"], 3)  # 3000 taxable, then voided
    record_usage(job["id"], tech["id"], sku["id"], 2)            # 2000 taxable, survives
    void_usage(usage_x["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    # taxable base is only the surviving 2000 line; voided 3000 line excluded.
    assert inv["tax_cents"] == 165   # rhu(2000*0.0825)
    assert_invoice_total_consistent(inv)


# ─── Queue B: calculations corner ─────────────────────────────────────────
def test_estimate_quoted_total_flat_rate_verbatim(api):
    """PRD §3.3: "When the `pricing_mode` is `FLAT_RATE`, the `quoted_total_cents` equals
    the `flat_rate_cents` verbatim, and the estimated hours and materials are ignored."

    Design: Corner/calculations/estimate_quoted_total_flat_rate_correct
    """
    cust = make_customer(full_name="QF Cust", email="qf@x.com", service_zip="26001", phone="1")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    resp = api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0,
         "flat_rate_cents": 25000, "estimated_labor_hours": 99, "estimated_material_cents": 99999},
        DISP,
    )
    data = validate_success(resp, 201)
    assert data["quoted_total_cents"] == 25000


def test_estimate_quoted_total_time_materials_default_rate(api):
    """PRD §3.3: "When the `pricing_mode` is `TIME_MATERIALS`, the system computes a labor
    figure by multiplying `estimated_labor_hours` by an hourly rate and rounding the product
    half up to whole cents, then adds the `estimated_material_cents` ... if no technician has
    been dispatched yet, the system uses the default zone rate of 12000 cents per hour."

    Design: Corner/calculations/estimate_quoted_total_time_materials_default_rate
    """
    cust = make_customer(full_name="QT Cust", email="qt@x.com", service_zip="27001", phone="1")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    resp = api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "TIME_MATERIALS", "expected_job_version": v0,
         "estimated_labor_hours": 4, "estimated_material_cents": 2000},
        DISP,
    )
    data = validate_success(resp, 201)
    assert data["quoted_total_cents"] == 50000  # rhu(4*12000)+2000


def test_invoice_emergency_surcharge_applied(api):
    """PRD §3.7 step 4: "15000 cents when the job's `priority` is `EMERGENCY`, and 0 otherwise."
    PRD §3.7 step 3: "the base trip fee is 8900 cents."

    Design: Corner/calculations/invoice_emergency_surcharge_applied
    """
    cust = make_customer(full_name="EM Cust", email="em@x.com", service_zip="28001", phone="1")
    tech = make_technician(full_name="EM Tech", license_class="MASTER", service_zone="280",
                           hourly_rate_cents=10000, on_call=True)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="EMERGENCY")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=20000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-08T09:00:00Z", "2026-08-08T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoiced = invoice_job(job["id"])
    inv = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)[0]
    assert inv["emergency_surcharge_cents"] == 15000
    assert inv["dispatch_fee_cents"] == 8900
    assert invoiced["total_due_cents"] == 43900  # 20000 + 8900 + 15000


def test_material_usage_line_total_correct(api):
    """PRD §3.5: "Each line's `line_total_cents` is computed at the moment of recording as
    the `quantity` multiplied by that SKU's `unit_price_cents` at usage time."

    Design: Corner/calculations/material_usage_line_total_correct
    """
    cust = make_customer(full_name="ML Cust", email="ml@x.com", service_zip="29001", phone="1")
    tech = make_technician(full_name="ML Tech", license_class="JOURNEYMAN", service_zone="290",
                           hourly_rate_cents=9000, on_call=False)
    sku = make_sku(sku_code="ML-SKU", description="GFCI", unit_price_cents=1500, taxable=True)
    stock_truck(tech["id"], sku["id"], quantity_on_hand=20, reorder_threshold=0)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-09T09:00:00Z", "2026-08-09T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    resp = api.create_material_usage(
        {"job_id": job["id"], "technician_id": tech["id"], "sku_id": sku["id"], "quantity": 7},
        make_technician_headers(tech["id"]),
    )
    data = validate_success(resp, 201)
    assert data["line_total_cents"] == 10500  # 7 * 1500


def test_derived_field_total_due_reconciled_at_invoice(api):
    """PRD §3.3: "`total_due_cents` is initialized to 0."
    PRD §3.7: "Invoicing creates an `Invoice` (one per job) by running the billing
    calculation, then sets the job's `total_due_cents` to the invoice's grand total."

    Design: Corner/cross_cutting_concerns/derived_field_total_due_reconciled_at_invoice
    """
    cust = make_customer(full_name="DF Cust", email="df@x.com", service_zip="51001", phone="1")
    tech = make_technician(full_name="DF Tech", license_class="JOURNEYMAN", service_zone="510",
                           hourly_rate_cents=9000, on_call=False)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-18T09:00:00Z", "2026-08-18T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    completed = complete_job(job["id"], tech["id"])
    assert completed["total_due_cents"] == 0
    invoiced = invoice_job(job["id"])
    assert invoiced["total_due_cents"] == 18900  # 10000 + 8900 dispatch


def test_immediate_consistency_invoice_visible_same_response(api):
    """PRD §3.7: "Invoicing creates an `Invoice` ... then sets the job's `total_due_cents`
    to the invoice's grand total, stamps the job's `warranty_until` to the current server
    time plus the warranty window, and advances the job's `status` from `COMPLETED` to
    `INVOICED`."

    Design: Corner/consistency_model/immediate_consistency_invoice_visible_same_response
    """
    set_clock("2026-08-19T08:00:00Z")
    cust = make_customer(full_name="IM Cust", email="im@x.com", service_zip="53001", phone="1")
    tech = make_technician(full_name="IM Tech", license_class="JOURNEYMAN", service_zone="530",
                           hourly_rate_cents=9000, on_call=False)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-19T09:00:00Z", "2026-08-19T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    resp = api.invoice_service_job(job["id"], DISP)
    data = validate_success(resp, 200)
    assert data["status"] == "INVOICED"
    assert data["total_due_cents"] == 18900  # 10000 + 8900
    assert data["warranty_until"] is not None
