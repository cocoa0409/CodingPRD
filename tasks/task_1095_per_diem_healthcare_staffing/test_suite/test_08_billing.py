"""Billing: invoice generation, the round-per-line-then-sum total, markup tiers,
the issue/void money-conservation compensating pair, segregation of duties,
payment-amount match, period overlap, and the facility-version OCC guard.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLER = TEST_USERS["billing_agent_headers"]
BILLER_BETA = TEST_USERS["billing_agent_beta_headers"]


def _setup_two_verified_same_period(name):
    """Two verified timesheets (gross 86250 and 56250) for one facility in the
    2026-06-08..2026-06-15 period, leaving pending_pay_cents 142500. Returns
    (fac_id, cl_id, asg_a, asg_b, ts_a, ts_b)."""
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": name}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=2)
    sh_a = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    sh_b = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-09T07:00:00Z", scheduled_end="2026-06-09T15:00:00Z")
    ca = fx.place_claim(sh_a["id"], cl_id)
    aa = fx.award(sh_a["id"], fac_id, claim_id=ca["id"])
    fx.confirm(aa["id"], cl_id)
    cb = fx.place_claim(sh_b["id"], cl_id)
    ab = fx.award(sh_b["id"], fac_id, claim_id=cb["id"])
    fx.confirm(ab["id"], cl_id)
    fx.set_clock("2026-06-09T16:00:00Z")
    ts_a = fx.submit_timesheet(aa["id"], cl_id, clock_in="2026-06-08T07:00:00Z", clock_out="2026-06-08T19:00:00Z", break_minutes=30)
    ts_b = fx.submit_timesheet(ab["id"], cl_id, clock_in="2026-06-09T07:00:00Z", clock_out="2026-06-09T15:00:00Z", break_minutes=30)
    fx.verify_timesheet(ts_a["id"], fac_id)
    fx.verify_timesheet(ts_b["id"], fac_id)
    return fac_id, cl_id, aa["id"], ab["id"], ts_a["id"], ts_b["id"]


# --------------------------------------------------------------------------- #
# Difficulty: round-per-line-then-sum
# --------------------------------------------------------------------------- #
def test_invoice_round_per_line_then_sum_total(api):
    """PRD 2.6: "a facility's bill is assembled by rounding each invoice line to whole
    cents first and then summing the rounded lines. The alternative of summing exact
    products and rounding once is explicitly not used and would produce different
    totals whenever two lines each carry a half-cent remainder."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_mode_b
    """
    fac_id, cl_id, _, _, ts_a, ts_b = _setup_two_verified_same_period("Lakeview")
    invoice = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    assert invoice["markup_tier"] == "TIER_1"
    assert invoice["markup_multiplier"] == 1.45
    assert invoice["bill_total_cents"] == 206626
    assert invoice["bill_total_cents"] != 206625
    assert invoice["margin_cents"] == 64126


def test_invoice_line_level_rounding_and_pay_totals(api):
    """PRD 3.8: "`bill_cents` is `pay_cents` times the frozen `markup_multiplier`,
    rounded half-up to whole cents *per line*."
    PRD 3.8: "`bill_total_cents` is the sum of the lines' already-rounded `bill_cents` —
    rounding each line first and then summing, not summing exact products and rounding
    once."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_mode_b
    """
    fac_id, cl_id, _, _, ts_a, ts_b = _setup_two_verified_same_period("Lakeview")
    invoice = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    assert invoice["line_count"] == 2
    assert invoice["lines"][0]["pay_cents"] == 86250 and invoice["lines"][0]["bill_cents"] == 125063
    assert invoice["lines"][1]["pay_cents"] == 56250 and invoice["lines"][1]["bill_cents"] == 81563
    assert invoice["pay_total_cents"] == 142500
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["pending_pay_cents"] == 0
    assert validate_success(api.get_timesheet(ts_a, ADMIN), 200)["status"] == "INVOICED"
    assert validate_success(api.get_timesheet(ts_b, ADMIN), 200)["status"] == "INVOICED"


# --------------------------------------------------------------------------- #
# Difficulty: issue then void restores the three facility money counters
# --------------------------------------------------------------------------- #
def test_issue_then_void_restores_money_counters(api):
    """PRD 3.8: "Issuance moves the invoice `DRAFT → ISSUED` ... then increases the
    facility's `outstanding_balance_cents` and `lifetime_billed_cents` each by
    `bill_total_cents` and bumps both the facility's and the invoice's `version`."
    PRD 3.8: "When the invoice being voided had already been issued, the void
    additionally decreases the facility's `outstanding_balance_cents` and
    `lifetime_billed_cents` each by `bill_total_cents`, restoring both to their
    pre-issue values."

    Design: Difficulty/compensating_invariant/issue_then_void_restores_facility_money_counters
    """
    fac_id, cl_id, _, _, ts_a, ts_b = _setup_two_verified_same_period("Brookline")
    invoice = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    assert invoice["pay_total_cents"] == 142500 and invoice["bill_total_cents"] == 206626

    fx.issue_invoice(invoice["id"], BILLER)
    after_issue = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert after_issue["outstanding_balance_cents"] == 206626
    assert after_issue["lifetime_billed_cents"] == 206626
    assert after_issue["pending_pay_cents"] == 0

    voided = validate_success(api.void_invoice(invoice["id"], {"reason": "wrong billing period, will regenerate"}, BILLER), 200)
    assert voided["status"] == "VOID"
    after_void = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert after_void["outstanding_balance_cents"] == 0
    assert after_void["lifetime_billed_cents"] == 0
    assert after_void["pending_pay_cents"] == 142500


def test_void_returns_timesheets_and_assignments_to_billable(api):
    """PRD 3.8: "A void moves the invoice to `VOID`, storing the `reason` into
    `void_reason`, returns every line's timesheet `INVOICED → VERIFIED` with its
    `invoice_id` cleared, returns every corresponding assignment's pay axis
    `INVOICED → PAYABLE`, increases the facility's `pending_pay_cents` by
    `pay_total_cents`, and bumps the facility's and the invoice's `version`."

    Design: Difficulty/compensating_invariant/issue_then_void_restores_facility_money_counters
    """
    fac_id, cl_id, asg_a, asg_b, ts_a, ts_b = _setup_two_verified_same_period("Brookline")
    invoice = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    fx.issue_invoice(invoice["id"], BILLER)
    validate_success(api.void_invoice(invoice["id"], {"reason": "wrong billing period, will regenerate"}, BILLER), 200)

    for ts_id in (ts_a, ts_b):
        ts = validate_success(api.get_timesheet(ts_id, ADMIN), 200)
        assert ts["status"] == "VERIFIED" and ts["invoice_id"] is None
    for asg_id in (asg_a, asg_b):
        asg = validate_success(api.get_assignment(asg_id, make_scheduler_headers(fac_id)), 200)
        assert asg["pay_status"] == "PAYABLE"
    attached, meta = validate_paginated(api.list_invoice_timesheets(invoice["id"], BILLER))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# Corner
# --------------------------------------------------------------------------- #
def test_markup_tier_switches_to_tier_two_after_first_invoice_issued(api):
    """PRD 3.8: "The tier is chosen once from the facility's `lifetime_billed_cents` as
    it stands *before* this invoice contributes to it — draft invoices contribute
    nothing, and the invoice being generated has not yet been issued."
    PRD 3.8: "when the basis is from 200000 through 499999 cents, the tier is `TIER_2`
    and the multiplier is 1.38".

    Design: Corner/calculations/markup_tier_switches_to_tier_two_after_first_invoice_issued
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(
        facility_overrides={"name": "Quarry Health"},
        rate_overrides={"base_pay_rate_cents_per_hour": 20000},
        clinician_overrides={"full_name": "Rhys Calder", "email": "rhys.calder@example.com"},
        clock=None,
    )
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]

    order1 = fx.new_order(fac_id)
    sh1 = fx.add_shift(order1["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    order2 = fx.new_order(fac_id, window_start="2026-06-15T00:00:00Z", window_end="2026-06-22T00:00:00Z")
    sh2 = fx.add_shift(order2["id"], fac_id, scheduled_start="2026-06-15T07:00:00Z", scheduled_end="2026-06-15T19:00:00Z")

    c1 = fx.place_claim(sh1["id"], cl_id)
    a1 = fx.award(sh1["id"], fac_id, claim_id=c1["id"])
    fx.confirm(a1["id"], cl_id)
    c2 = fx.place_claim(sh2["id"], cl_id)
    a2 = fx.award(sh2["id"], fac_id, claim_id=c2["id"])
    fx.confirm(a2["id"], cl_id)

    fx.set_clock("2026-06-08T19:30:00Z")
    ts1 = fx.submit_timesheet(a1["id"], cl_id, clock_in="2026-06-08T07:00:00Z", clock_out="2026-06-08T19:00:00Z", break_minutes=30)
    v1 = fx.verify_timesheet(ts1["id"], fac_id)
    assert v1["gross_pay_cents"] == 230000
    inv1 = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    assert inv1["markup_tier"] == "TIER_1" and inv1["bill_total_cents"] == 333500
    issued1 = fx.issue_invoice(inv1["id"], BILLER)
    assert issued1["status"] == "ISSUED"

    fx.set_clock("2026-06-15T19:30:00Z")
    ts2 = fx.submit_timesheet(a2["id"], cl_id, clock_in="2026-06-15T07:00:00Z", clock_out="2026-06-15T19:00:00Z", break_minutes=30)
    v2 = fx.verify_timesheet(ts2["id"], fac_id)
    assert v2["gross_pay_cents"] == 230000
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["lifetime_billed_cents"] == 333500

    inv2 = fx.generate_invoice(fac_id, period_start="2026-06-15T00:00:00Z", period_end="2026-06-22T00:00:00Z")
    assert inv2["markup_tier"] == "TIER_2"
    assert inv2["markup_multiplier"] == 1.38
    assert inv2["bill_total_cents"] == 317400
    assert inv2["pay_total_cents"] == 230000 and inv2["margin_cents"] == 87400
    assert inv2["status"] == "DRAFT"


def test_invoice_with_no_verified_timesheets_returns_no_billable(api):
    """PRD 3.8: "At least one billable timesheet must fall in the period, or it fails
    with `ERR_NO_BILLABLE_TIMESHEETS`."

    Design: Corner/validations/invoice_with_no_verified_timesheets_returns_no_billable
    """
    fx.set_clock("2026-06-16T00:00:00Z")
    fac = fx.new_facility(name="Coriander")
    fx.add_rate_card(fac["id"])
    fac_id = fac["id"]
    facility = validate_success(api.get_facility(fac_id, BILLER), 200)
    assert facility["pending_pay_cents"] == 0
    resp = api.create_invoice(
        {"facility_id": fac_id, "period_start": "2026-06-08T00:00:00Z", "period_end": "2026-06-15T00:00:00Z",
         "expected_facility_version": facility["version"]},
        BILLER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_TIMESHEETS.value, 422)
    invoices, meta = validate_paginated(api.list_facility_invoices(fac_id, BILLER))
    assert meta["total_count"] == 0


def test_invoice_period_overlap_returns_error(api):
    """PRD 3.8: "The requested period must not intersect the period of any existing
    invoice of the facility in `DRAFT`, `ISSUED`, or `SETTLED` status, or it fails with
    `ERR_INVOICE_PERIOD_OVERLAP`."

    Design: Corner/validations/invoice_period_overlapping_existing_draft_returns_error
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Dovetail"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order1 = fx.new_order(fac_id)
    sh1 = fx.add_shift(order1["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    order2 = fx.new_order(fac_id, window_start="2026-06-15T00:00:00Z", window_end="2026-06-22T00:00:00Z")
    sh2 = fx.add_shift(order2["id"], fac_id, scheduled_start="2026-06-16T07:00:00Z", scheduled_end="2026-06-16T19:00:00Z")
    c1 = fx.place_claim(sh1["id"], cl_id); a1 = fx.award(sh1["id"], fac_id, claim_id=c1["id"]); fx.confirm(a1["id"], cl_id)
    c2 = fx.place_claim(sh2["id"], cl_id); a2 = fx.award(sh2["id"], fac_id, claim_id=c2["id"]); fx.confirm(a2["id"], cl_id)

    fx.set_clock("2026-06-08T19:30:00Z")
    ts1 = fx.submit_timesheet(a1["id"], cl_id, clock_in="2026-06-08T07:00:00Z", clock_out="2026-06-08T19:00:00Z", break_minutes=30)
    fx.verify_timesheet(ts1["id"], fac_id)
    inv1 = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")

    fx.set_clock("2026-06-16T19:30:00Z")
    ts2 = fx.submit_timesheet(a2["id"], cl_id, clock_in="2026-06-16T07:00:00Z", clock_out="2026-06-16T19:00:00Z", break_minutes=30)
    fx.verify_timesheet(ts2["id"], fac_id)

    facility = validate_success(api.get_facility(fac_id, BILLER), 200)
    resp = api.create_invoice(
        {"facility_id": fac_id, "period_start": "2026-06-10T00:00:00Z", "period_end": "2026-06-17T00:00:00Z",
         "expected_facility_version": facility["version"]},
        BILLER,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP.value, 409)
    assert err["error_id"] != ApiErrorId.ERR_NO_BILLABLE_TIMESHEETS.value
    assert validate_success(api.get_invoice(inv1["id"], BILLER), 200)["status"] == "DRAFT"
    assert validate_success(api.get_timesheet(ts2["id"], ADMIN), 200)["status"] == "VERIFIED"
    invoices, meta = validate_paginated(api.list_facility_invoices(fac_id, BILLER))
    assert meta["total_count"] == 1


def test_settle_with_wrong_amount_returns_payment_mismatch(api):
    """PRD 3.8: "The supplied `paid_amount_cents` must equal the invoice's
    `bill_total_cents` exactly, or it is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/settle_with_wrong_amount_returns_payment_amount_mismatch
    """
    bundle = fx.setup_verified_timesheet(facility_overrides={"name": "Ember Hill"})
    fac_id = bundle["facility"]["id"]
    invoice = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    assert invoice["bill_total_cents"] == 125063
    issued = fx.issue_invoice(invoice["id"], BILLER)
    assert issued["due_at"] == "2026-07-08T19:30:00.000Z"

    resp = api.settle_invoice(invoice["id"], {"paid_amount_cents": 125000}, BILLER_BETA)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 422)
    inv = validate_success(api.get_invoice(invoice["id"], BILLER), 200)
    assert inv["status"] == "ISSUED" and inv["settled_by_user_id"] is None
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["outstanding_balance_cents"] == 125063


def test_settle_by_same_agent_that_issued_returns_segregation_of_duties(api):
    """PRD 2.1: "a settlement whose `X-User-ID` equals the invoice's
    `issued_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/settle_by_same_agent_that_issued_returns_segregation_of_duties
    """
    bundle = fx.setup_verified_timesheet(facility_overrides={"name": "Gladewater"})
    fac_id = bundle["facility"]["id"]
    invoice = fx.generate_invoice(fac_id, period_start="2026-06-08T00:00:00Z", period_end="2026-06-15T00:00:00Z")
    assert invoice["bill_total_cents"] == 125063
    fx.issue_invoice(invoice["id"], BILLER)  # issued by biller-alpha

    resp = api.settle_invoice(invoice["id"], {"paid_amount_cents": 125063}, BILLER)  # same agent
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    inv = validate_success(api.get_invoice(invoice["id"], BILLER), 200)
    assert inv["status"] == "ISSUED"
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["outstanding_balance_cents"] == 125063


def test_invoice_generate_with_stale_facility_version_returns_412(api):
    """PRD 2.5: "When `expected_facility_version` does not equal the facility's current
    `version`, generation is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412), and
    the biller must re-read the facility first."

    Design: Corner/cross_cutting/invoice_generate_with_stale_facility_version_returns_412
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Junegrass"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=2)
    sh_a = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    sh_b = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-09T07:00:00Z", scheduled_end="2026-06-09T15:00:00Z")
    ca = fx.place_claim(sh_a["id"], cl_id); aa = fx.award(sh_a["id"], fac_id, claim_id=ca["id"]); fx.confirm(aa["id"], cl_id)
    cb = fx.place_claim(sh_b["id"], cl_id); ab = fx.award(sh_b["id"], fac_id, claim_id=cb["id"]); fx.confirm(ab["id"], cl_id)
    fx.set_clock("2026-06-09T16:00:00Z")
    ts_a = fx.submit_timesheet(aa["id"], cl_id, clock_in="2026-06-08T07:00:00Z", clock_out="2026-06-08T19:00:00Z", break_minutes=30)
    ts_b = fx.submit_timesheet(ab["id"], cl_id, clock_in="2026-06-09T07:00:00Z", clock_out="2026-06-09T15:00:00Z", break_minutes=30)
    fx.verify_timesheet(ts_a["id"], fac_id)
    stale_version = validate_success(api.get_facility(fac_id, BILLER), 200)["version"]  # read before 2nd verify
    fx.verify_timesheet(ts_b["id"], fac_id)  # bumps facility version

    stale = api.create_invoice(
        {"facility_id": fac_id, "period_start": "2026-06-08T00:00:00Z", "period_end": "2026-06-15T00:00:00Z",
         "expected_facility_version": stale_version},
        BILLER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412)

    fresh_version = validate_success(api.get_facility(fac_id, BILLER), 200)["version"]
    retry = api.create_invoice(
        {"facility_id": fac_id, "period_start": "2026-06-08T00:00:00Z", "period_end": "2026-06-15T00:00:00Z",
         "expected_facility_version": fresh_version},
        BILLER,
    )
    invoice = validate_success(retry, 201)
    assert invoice["line_count"] == 2
    assert invoice["bill_total_cents"] == 206626
    assert validate_success(api.get_timesheet(ts_a["id"], ADMIN), 200)["status"] == "INVOICED"
    assert validate_success(api.get_timesheet(ts_b["id"], ADMIN), 200)["status"] == "INVOICED"
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["pending_pay_cents"] == 0
