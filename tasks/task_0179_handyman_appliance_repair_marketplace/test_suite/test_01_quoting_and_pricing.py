"""Quoting paths and the dual-variant / part / invoice pricing engine.

Covers the instant-vs-in-home quote divergence, part-line markup clamp formula, per-line
labor rounding, the free-trip-fee waiver boundary, and the corner-level calculation claims.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_customer_headers, make_pro_headers, TEST_USERS,
    create_category, create_customer, create_cleared_pro, create_pro, create_window,
    create_job, accepted_instant_job, estimate_requested_job, instant_quoted_job,
    in_progress_job, issued_invoice_for_in_progress_job,
    submit_quote_payload, accept_quote_payload, book_window_payload,
    create_part_line_payload, create_visit_payload, create_labor_line_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# =====================================================================
# Difficulty: dual_variant_calc / instant_vs_in_home_quote_diverge_same_job
# =====================================================================

class TestInstantVsInHomeQuoteDiverge:
    """The same HOURLY job priced by INSTANT vs IN_HOME yields different numbers."""

    def _setup(self):
        cat = create_category(code="HVAC_TUNE", name="HVAC Tune-Up", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["hvac"])
        cust = create_customer(email="c1@x.com", full_name="C One", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                                 email="p1@x.com", full_name="P One", truck_stock_markup_pct=0.35)
        return cat, cust, pro

    def test_instant_quote_is_sight_unseen_flat(self, api):
        """PRD §3.3: "This produces a `Quote` whose `quote_type` is `INSTANT` and whose
        `priced_amount_cents` is simply the category's `instant_quote_flat_cents` — a single
        sight-unseen flat number with no parts, no per-hour labor, and no trip fee folded in".

        Design: Difficulty/dual_variant_calc/instant_vs_in_home_quote_diverge_same_job
        """
        cat, cust, pro = self._setup()
        job = create_job(cust["id"], cat["id"], "30301")
        res = api.instant_quote(job["id"], make_customer_headers(cust["id"]))
        quote = validate_success(res, 201)
        assert quote["priced_amount_cents"] == 15000

    def test_in_home_hourly_quote_is_labor_plus_trip(self, api):
        """PRD §3.3: "for an `HOURLY` category the labor component is `estimated_labor_hours`
        multiplied by the category's `hourly_rate_cents`, rounded half-up to whole cents. To that
        labor component the system adds the trip fee computed for this job and this professional".

        Design: Difficulty/dual_variant_calc/instant_vs_in_home_quote_diverge_same_job
        """
        cat, cust, pro = self._setup()
        job = estimate_requested_job(cust["id"], cat["id"], "30301")
        res = api.submit_quote(job["id"], submit_quote_payload(estimated_labor_hours=2.5),
                               make_pro_headers(pro["id"]))
        quote = validate_success(res, 201)
        # labor 2.5*9000 = 22500; trip local 2500; total 25000
        assert quote["priced_amount_cents"] == 25000

    def test_instant_and_in_home_diverge_by_10000(self, api):
        """PRD §3.3: "for an `HOURLY` category the labor component is `estimated_labor_hours`
        multiplied by the category's `hourly_rate_cents`, rounded half-up to whole cents. To that
        labor component the system adds the trip fee computed for this job and this professional".

        Design: Difficulty/dual_variant_calc/instant_vs_in_home_quote_diverge_same_job
        """
        cat, cust, pro = self._setup()
        job_instant = create_job(cust["id"], cat["id"], "30301")
        q_instant = validate_success(
            api.instant_quote(job_instant["id"], make_customer_headers(cust["id"])), 201)
        job_home = estimate_requested_job(cust["id"], cat["id"], "30301")
        q_home = validate_success(
            api.submit_quote(job_home["id"], submit_quote_payload(estimated_labor_hours=2.5),
                             make_pro_headers(pro["id"])), 201)
        assert q_instant["priced_amount_cents"] == 15000
        assert q_home["priced_amount_cents"] == 25000
        assert q_home["priced_amount_cents"] - q_instant["priced_amount_cents"] == 10000


# =====================================================================
# Difficulty: combinatorial_formula / part_markup_cap_floor_nonlinear_mode_a
# =====================================================================

class TestPartMarkupCapFloorFormula:
    """Truck-stock markup is base + clamp(round(base*pct), FLOOR, CAP)."""

    def _in_progress(self, markup_pct):
        cat = create_category(code="APPL_FIX", name="Appliance Fix", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["appliance"])
        cust = create_customer(email="c3@x.com", full_name="C Three", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["appliance"], home_zip_code="30301",
                                 email="p3@x.com", full_name="P Three",
                                 truck_stock_markup_pct=markup_pct)
        job, window = in_progress_job(cust["id"], cat["id"], pro,
                                      "2026-06-02T10:00:00.000Z", "2026-06-02T12:00:00.000Z",
                                      "2026-06-02T10:30:00.000Z")
        return job, pro

    def test_truck_markup_clamped_to_cap(self, api):
        """PRD §3.6: "that markup is then capped so it never exceeds 5,000 cents, and floored so
        it is never less than 300 cents; the line total is the base plus this capped-and-floored
        markup (the cap is applied first, then the floor raises any too-small markup back up to
        the 300-cent minimum)."

        Design: Difficulty/combinatorial_formula/part_markup_cap_floor_nonlinear_mode_a
        """
        job, pro = self._in_progress(0.35)
        res = api.create_part_line(
            job["id"], create_part_line_payload("Compressor", 30000, 2, from_truck_stock=True),
            make_pro_headers(pro["id"]))
        pl = validate_success(res, 201)
        # base 60000; raw markup round(60000*0.35)=21000 -> capped to 5000; total 65000
        assert pl["line_total_cents"] == 65000

    def test_truck_markup_normal_band_no_clamp(self, api):
        """PRD §3.6: "If the part came `from_truck_stock`, the system computes a markup equal to
        the base multiplied by the professional's `truck_stock_markup_pct`, rounded half-up to
        whole cents; that markup is then capped so it never exceeds 5,000 cents, and floored so it
        is never less than 300 cents".

        Design: Difficulty/combinatorial_formula/part_markup_cap_floor_nonlinear_mode_a
        """
        job, pro = self._in_progress(0.35)
        res = api.create_part_line(
            job["id"], create_part_line_payload("Belt", 4000, 2, from_truck_stock=True),
            make_pro_headers(pro["id"]))
        pl = validate_success(res, 201)
        # base 8000; markup round(8000*0.35)=2800 (within band); total 10800
        assert pl["line_total_cents"] == 10800


# =====================================================================
# Difficulty: combinatorial_formula / invoice_per_line_round_then_sum_mode_b
# =====================================================================

class TestInvoicePerLineRoundThenSum:
    """HOURLY invoice rounds each labor line then sums (per-line rounding pinned)."""

    def _setup_two_labor_lines(self):
        cat = create_category(code="ELEC_HR", name="Electric Hourly", pricing_model="HOURLY",
                              hourly_rate_cents=9000, skill_tags=["electric"])
        cust = create_customer(email="c4@x.com", full_name="C Four", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["electric"], home_zip_code="30301",
                                 email="p4@x.com", full_name="P Four")
        window = create_window(pro["id"], "2026-06-03T10:00:00.000Z", "2026-06-03T14:00:00.000Z", "30301")
        job = estimate_requested_job(cust["id"], cat["id"], "30301")
        cust_h = make_customer_headers(cust["id"])
        pro_h = make_pro_headers(pro["id"])
        q = get_success_data(api_client.submit_quote(
            job["id"], submit_quote_payload(estimated_labor_hours=4.0), pro_h))
        api_client.accept_quote(job["id"], accept_quote_payload(q["id"]), cust_h)
        get_success_data(api_client.book_window(
            window["id"], book_window_payload(job["id"], window["version"]), cust_h))
        api_client.create_visit(job["id"], create_visit_payload(window["id"], "2026-06-03T10:30:00.000Z"), pro_h)
        api_client.create_labor_line(job["id"], create_labor_line_payload(1.5), pro_h)
        api_client.create_labor_line(job["id"], create_labor_line_payload(2.5), pro_h)
        inv = get_success_data(api_client.create_invoice(job["id"], pro_h))
        return job, pro, inv

    def test_labor_subtotal_is_per_line_round_then_sum(self, api):
        """PRD §3.7: "for an `HOURLY` category it is the sum over the job's labor lines, where
        each line is rounded half-up to whole cents *before* the lines are summed (per-line
        rounding, then aggregation)."

        Design: Difficulty/combinatorial_formula/invoice_per_line_round_then_sum_mode_b
        """
        job, pro, inv = self._setup_two_labor_lines()
        res = api.issue_invoice(inv["id"], make_pro_headers(pro["id"]))
        issued = validate_success(res, 200)
        # 1.5*9000=13500 ; 2.5*9000=22500 ; sum 36000
        assert issued["labor_subtotal_cents"] == 36000
        assert issued["parts_subtotal_cents"] == 0

    def test_invoice_total_adds_local_trip_fee(self, api):
        """PRD §3.7: "if the job's `address_zip_code` equals the professional's `home_zip_code`
        the base trip fee is 2,500 cents, otherwise it is 6,000 cents." PRD §3.7: "The grand
        `total_cents` is the labor subtotal plus the parts subtotal plus the (possibly waived)
        trip fee."

        Design: Difficulty/combinatorial_formula/invoice_per_line_round_then_sum_mode_b
        """
        job, pro, inv = self._setup_two_labor_lines()
        res = api.issue_invoice(inv["id"], make_pro_headers(pro["id"]))
        issued = validate_success(res, 200)
        assert issued["trip_fee_cents"] == 2500
        assert issued["total_cents"] == 38500


# =====================================================================
# Difficulty: boundary_precision_check / free_trip_threshold_exact_40000_waives_fee
# =====================================================================

class TestFreeTripThresholdBoundary:
    """At labor+parts == 40000 the trip-fee waiver fires (>= boundary)."""

    def _flat_job_in_progress(self, flat_fee):
        cat = create_category(code="FLAT_40K", name="Flat 40k", pricing_model="FLAT",
                              flat_task_fee_cents=flat_fee, instant_quote_eligible=True,
                              instant_quote_flat_cents=flat_fee, skill_tags=["plumb"])
        cust = create_customer(email="c11@x.com", full_name="C Eleven", zip_code="30301")
        # pro home ZIP 99999 != job ZIP 30301 -> remote trip base 6000 (waived if threshold met)
        pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="99999",
                                 email="p11@x.com", full_name="P Eleven")
        job, window = in_progress_job(cust["id"], cat["id"], pro,
                                      "2026-06-06T10:00:00.000Z", "2026-06-06T12:00:00.000Z",
                                      "2026-06-06T10:30:00.000Z")
        pro_h = make_pro_headers(pro["id"])
        inv = get_success_data(api_client.create_invoice(job["id"], pro_h))
        return job, pro, inv

    def test_at_threshold_40000_waives_trip_fee(self, api):
        """PRD §3.7: "That base is then waived to zero in either of two situations: the job is a
        warranty callback, or the sum of the labor subtotal and the parts subtotal is at least
        40,000 cents."

        Design: Difficulty/boundary_precision_check/free_trip_threshold_exact_40000_waives_fee
        """
        job, pro, inv = self._flat_job_in_progress(40000)
        issued = validate_success(api.issue_invoice(inv["id"], make_pro_headers(pro["id"])), 200)
        assert issued["labor_subtotal_cents"] == 40000
        assert issued["trip_fee_cents"] == 0
        assert issued["total_cents"] == 40000

    def test_below_threshold_keeps_trip_fee(self, api):
        """PRD §3.7: "That base is then waived to zero in either of two situations: the job is a
        warranty callback, or the sum of the labor subtotal and the parts subtotal is at least
        40,000 cents."

        Design: Difficulty/boundary_precision_check/free_trip_threshold_exact_40000_waives_fee
        """
        job, pro, inv = self._flat_job_in_progress(39900)
        issued = validate_success(api.issue_invoice(inv["id"], make_pro_headers(pro["id"])), 200)
        # 39900 < 40000 -> waiver does NOT fire; remote base 6000 applies
        assert issued["labor_subtotal_cents"] == 39900
        assert issued["trip_fee_cents"] == 6000
        assert issued["total_cents"] == 45900


# =====================================================================
# Corner: calculations
# =====================================================================

def _appliance_in_progress(markup_pct, code, email_c, email_p, win_day):
    cat = create_category(code=code, name="Calc Cat", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["appliance"])
    cust = create_customer(email=email_c, full_name="C Calc", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["appliance"], home_zip_code="30301",
                             email=email_p, full_name="P Calc", truck_stock_markup_pct=markup_pct)
    job, window = in_progress_job(cust["id"], cat["id"], pro,
                                  f"2026-{win_day}T10:00:00.000Z", f"2026-{win_day}T12:00:00.000Z",
                                  f"2026-{win_day}T10:30:00.000Z")
    return job, pro


def test_part_line_truck_stock_markup_normal_band(api):
    """PRD §3.6: "If the part came `from_truck_stock`, the system computes a markup equal to the
    base multiplied by the professional's `truck_stock_markup_pct`, rounded half-up to whole
    cents; that markup is then capped so it never exceeds 5,000 cents, and floored so it is never
    less than 300 cents; the line total is the base plus this capped-and-floored markup".

    Design: Corner/calculations/part_line_truck_stock_markup_normal_band
    """
    job, pro = _appliance_in_progress(0.35, "CALC_TRK", "ccalc1@x.com", "pcalc1@x.com", "06-12")
    res = api.create_part_line(
        job["id"], create_part_line_payload("Belt", 4000, 2, from_truck_stock=True),
        make_pro_headers(pro["id"]))
    pl = validate_success(res, 201)
    assert pl["line_total_cents"] == 10800


def test_part_line_truck_stock_floor_band(api):
    """PRD §3.6: "that markup is then capped so it never exceeds 5,000 cents, and floored so it is
    never less than 300 cents; the line total is the base plus this capped-and-floored markup (the
    cap is applied first, then the floor raises any too-small markup back up to the 300-cent
    minimum)."

    Design: Corner/calculations/part_line_truck_stock_floor_band
    """
    job, pro = _appliance_in_progress(0.05, "CALC_FLR", "ccalc2@x.com", "pcalc2@x.com", "06-13")
    res = api.create_part_line(
        job["id"], create_part_line_payload("Screw kit", 1000, 2, from_truck_stock=True),
        make_pro_headers(pro["id"]))
    pl = validate_success(res, 201)
    # base 2000; raw markup round(2000*0.05)=100 -> floored to 300; total 2300
    assert pl["line_total_cents"] == 2300


def test_part_line_special_order_flat_handling_fee(api):
    """PRD §3.6: "If the part did not come from truck stock — a special order — there is no
    percentage markup at all; instead a flat handling fee of 1,500 cents is added to the base to
    form the line total."

    Design: Corner/calculations/part_line_special_order_flat_handling_fee
    """
    job, pro = _appliance_in_progress(0.35, "CALC_SPC", "ccalc3@x.com", "pcalc3@x.com", "06-14")
    res = api.create_part_line(
        job["id"], create_part_line_payload("OEM board", 4000, 2, from_truck_stock=False),
        make_pro_headers(pro["id"]))
    pl = validate_success(res, 201)
    # base 8000 + 1500 handling = 9500
    assert pl["line_total_cents"] == 9500


def test_in_home_quote_flat_category_excludes_parts(api):
    """PRD §3.3: "for a `FLAT` category the labor component is the category's `flat_task_fee_cents`
    ... To that labor component the system adds the trip fee computed for this job and this
    professional (described in §3.7), and the sum is the quoted total. Parts are unknown at
    estimate time and are deliberately excluded from the in-home quote".

    Design: Corner/calculations/in_home_quote_flat_category_excludes_parts
    """
    cat = create_category(code="CALC_IHF", name="Calc IH Flat", pricing_model="FLAT",
                          flat_task_fee_cents=12000, skill_tags=["plumb"])
    cust = create_customer(email="ccalc4@x.com", full_name="C Calc4", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="pcalc4@x.com", full_name="P Calc4")
    job = estimate_requested_job(cust["id"], cat["id"], "30301")
    res = api.submit_quote(job["id"], submit_quote_payload(), make_pro_headers(pro["id"]))
    quote = validate_success(res, 201)
    # labor flat 12000 + local trip 2500 = 14500; parts excluded
    assert quote["priced_amount_cents"] == 14500
    assert quote["quote_type"] == "IN_HOME"
