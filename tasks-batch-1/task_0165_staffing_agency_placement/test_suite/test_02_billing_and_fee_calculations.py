"""Invoice totals (tiered pricing, pinned rounding/eval order) and conversion fees.

Translates Difficulty/combinatorial_formula, calculation corners, and the
immediate-consistency corner. Literal expected values are copied from the design
indices (round_half_up, integer cents).
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    assert_invoice_total_consistent,
    setup_active_placement,
    create_and_approve_timesheet, create_draft_invoice, add_line_item,
    drive_submission_to_offer_extended, create_placement, start_placement,
    create_skill, create_client, create_open_job_order, create_candidate,
    create_timesheet, submit_timesheet, approve_timesheet,
    make_account_manager_headers, make_recruiter_headers,
)

AM = make_account_manager_headers()
RECRUITER = make_recruiter_headers()


def test_invoice_total_tier1_discount_and_post_discount_fee(api):
    """PRD 3.8: "the `subtotal_cents` is the sum of `line_total_cents` across the
    invoice's line items; since each line total was already rounded to whole cents
    when it was copied from its timesheet, this is a sum of already-rounded per-line
    amounts, not a rounding of the raw sum."
    PRD 3.8: "a subtotal of at least 500000 cents and below 2000000 cents earns three percent"
    PRD 3.8: "the `processing_fee_cents` is that discounted amount multiplied by a
    processing-fee rate of one and one-half percent, rounded half-up to whole cents — note
    the fee is keyed on the post-discount amount, which is why the evaluation order is pinned."
    PRD 3.8: "the `total_cents` is the subtotal minus the volume discount plus the processing fee."

    Two 40h timesheets (bill 12000 -> 480000 each): subtotal 960000 (tier-1 3%),
    discount round_half_up(960000*0.03)=28800, fee round_half_up(931200*0.015)=13968,
    total 945168.

    Design: Difficulty/combinatorial_formula/invoice_total_rounding_and_eval_order
    """
    scen = setup_active_placement(placement_overrides={"end_date": "2026-12-15T00:00:00Z"})
    pl, cand, cl = scen["placement"], scen["candidate"], scen["client"]
    ts1 = create_and_approve_timesheet(
        pl["id"], cand["id"], cl["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    ts2 = create_and_approve_timesheet(
        pl["id"], cand["id"], cl["id"], "2026-06-22T00:00:00Z", "2026-06-29T00:00:00Z", 40)
    inv = create_draft_invoice(cl["id"])
    add_line_item(inv["id"], ts1["id"])
    add_line_item(inv["id"], ts2["id"])
    invoice = validate_success(api.get_invoice(inv["id"], AM))
    assert invoice["subtotal_cents"] == 960000, f"subtotal {invoice['subtotal_cents']}"
    assert invoice["volume_discount_cents"] == 28800, f"discount {invoice['volume_discount_cents']}"
    assert invoice["processing_fee_cents"] == 13968, f"fee {invoice['processing_fee_cents']}"
    assert invoice["total_cents"] == 945168, f"total {invoice['total_cents']}"


def test_invoice_subtotal_is_sum_of_already_rounded_line_totals(api):
    """PRD 3.8: "the `subtotal_cents` is the sum of `line_total_cents` across the invoice's line
    items; since each line total was already rounded to whole cents when it was copied from its
    timesheet, this is a sum of already-rounded per-line amounts, not a rounding of the raw sum."
    PRD 3.8: "the `total_cents` is the subtotal minus the volume discount plus the processing fee."

    The same two-40h-timesheet invoice (each line 480000): subtotal 960000 == 480000 + 480000, and
    the five-step total identity total == subtotal - discount + fee holds (945168).

    Design: Difficulty/combinatorial_formula/invoice_total_rounding_and_eval_order
    """
    scen = setup_active_placement(placement_overrides={"end_date": "2026-12-15T00:00:00Z"})
    pl, cand, cl = scen["placement"], scen["candidate"], scen["client"]
    ts1 = create_and_approve_timesheet(
        pl["id"], cand["id"], cl["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    ts2 = create_and_approve_timesheet(
        pl["id"], cand["id"], cl["id"], "2026-06-22T00:00:00Z", "2026-06-29T00:00:00Z", 40)
    inv = create_draft_invoice(cl["id"])
    li1 = add_line_item(inv["id"], ts1["id"])
    li2 = add_line_item(inv["id"], ts2["id"])
    assert li1["line_total_cents"] == 480000, f"line 1 total {li1['line_total_cents']}"
    assert li2["line_total_cents"] == 480000, f"line 2 total {li2['line_total_cents']}"
    invoice = validate_success(api.get_invoice(inv["id"], AM))
    assert invoice["subtotal_cents"] == li1["line_total_cents"] + li2["line_total_cents"] == 960000
    assert_invoice_total_consistent(invoice)
    assert invoice["total_cents"] == 945168, f"total {invoice['total_cents']}"


def test_invoice_total_recomputed_visible_immediately_after_line_item(api):
    """PRD 3.8: "a subtotal below 500000 cents earns no discount (a rate of zero)"
    PRD 3.8: "the `processing_fee_cents` is that discounted amount multiplied by a
    processing-fee rate of one and one-half percent, rounded half-up to whole cents"
    PRD 3.8: "When the line is created, its `line_total_cents` is copied from the
    timesheet's `bill_cents` at that moment, and the invoice's totals are recomputed."

    A single 40h line item (bill 480000): subtotal 480000, tier-0 0% discount,
    fee round_half_up(480000*0.015)=7200, total 487200 — visible on the next GET.

    Design: Corner/consistency_model/line_item_add_recomputes_invoice_total_same_response_cycle
    """
    scen = setup_active_placement()
    pl, cand, cl = scen["placement"], scen["candidate"], scen["client"]
    ts = create_and_approve_timesheet(
        pl["id"], cand["id"], cl["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    inv = create_draft_invoice(cl["id"])
    add_line_item(inv["id"], ts["id"])
    invoice = validate_success(api.get_invoice(inv["id"], AM))
    assert invoice["subtotal_cents"] == 480000, f"subtotal {invoice['subtotal_cents']}"
    assert invoice["volume_discount_cents"] == 0, f"discount {invoice['volume_discount_cents']}"
    assert invoice["processing_fee_cents"] == 7200, f"fee {invoice['processing_fee_cents']}"
    assert invoice["total_cents"] == 487200, f"total {invoice['total_cents']}"


def test_timesheet_overtime_pay_bill_margin_at_50_hours(api):
    """PRD 3.6: "The regular portion of the week is the lesser of the hours worked and 40;
    the overtime portion is whatever exceeds 40."
    PRD 3.6: "the candidate's `pay_rate_cents` (copied from the placement) applies to the
    regular portion, and one and one-half times that pay rate applies to the overtime portion;
    the regular component and the overtime component are summed first and the total is then
    rounded half-up to whole cents."
    PRD 3.6: "The week's `margin_cents` is the `bill_cents` minus the `pay_cents`."

    50h (bill 12000, pay 8000): pay = 40*8000 + 10*8000*1.5 = 440000;
    bill = 40*12000 + 10*12000*1.5 = 660000; margin = 220000.

    Design: Corner/calculations/timesheet_pay_overtime_50h
    """
    scen = setup_active_placement()
    pl, cand = scen["placement"], scen["candidate"]
    ts = create_timesheet(
        pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 50)
    assert ts["pay_cents"] == 440000, f"pay {ts['pay_cents']}"
    assert ts["bill_cents"] == 660000, f"bill {ts['bill_cents']}"
    assert ts["margin_cents"] == 220000, f"margin {ts['margin_cents']}"


def test_conversion_fee_temp_to_perm_no_tenure_discount_within_band(api):
    """PRD 3.7: "For a `TEMP_TO_PERM` placement the effective rate is the client's
    `conversion_fee_pct` multiplied by a tenure factor that rewards long temp tenure:
    the tenure factor is 1.0 when the candidate has worked fewer than 13 weeks, and 0.5
    when they have worked 13 weeks or more, where weeks worked is the count of the
    placement's timesheets in `APPROVED` or `INVOICED` status."
    PRD 3.7: "the final `fee_cents` is at least 250000 cents and at most 5000000 cents"

    base 10000000 * 0.20 * 1.0 (0 approved timesheets < 13 weeks) = 2000000, inside
    [250000, 5000000] -> fee_cents == 2000000, status BILLED.

    Design: Difficulty/combinatorial_formula/conversion_fee_clamp_and_branch
    """
    scen = setup_active_placement(
        client_overrides={"name": "Mercy", "conversion_fee_pct": 0.20},
        job_order_overrides={
            "title": "Nurse", "employment_type": "TEMP_TO_PERM",
            "required_skill_code": "RN", "bill_rate_cents": 9000,
            "target_pay_rate_cents": 6000, "annual_salary_cents": 10000000,
        },
        candidate_overrides={"full_name": "Nina RN", "skill_codes": ["RN"], "base_pay_rate_cents": 6000},
        skill=("RN", "CLINICAL"),
        submitted_pay_rate_cents=6000)
    pl, cl = scen["placement"], scen["client"]
    get_success_data(api.convert_placement(pl["id"], {"annual_salary_cents": 10000000}, AM))
    fees, _meta = _list_conversion_fees(api, placement_id=pl["id"])
    assert len(fees) == 1, f"expected exactly one conversion fee, got {len(fees)}"
    fee = fees[0]
    assert fee["fee_cents"] == 2000000, f"fee_cents {fee['fee_cents']}"
    assert fee["status"] == "BILLED", f"status {fee['status']}"
    converted = validate_success(api.get_placement(pl["id"], scen["recruiter"]))
    assert converted["conversion_status"] == "CONVERTED"
    assert converted["assignment_status"] == "ENDED"


def test_conversion_fee_records_client_id_and_billed_status(api):
    """PRD 3.7: "Every conversion fee records the `placement_id` it bills against and copies the
    `client_id` from that placement's job order."
    PRD 3.7: "A conversion fee is created, in `status` `BILLED` ordinarily, or in `status` `WAIVED`
    when the request sets `waive` to true."

    Converting a TEMP_TO_PERM placement (base 10000000, pct 0.20, no tenure discount) produces a
    BILLED fee whose placement_id and client_id match the converted placement and its client.

    Design: Difficulty/combinatorial_formula/conversion_fee_clamp_and_branch
    """
    scen = setup_active_placement(
        client_overrides={"name": "Mercy", "conversion_fee_pct": 0.20},
        job_order_overrides={
            "title": "Nurse", "employment_type": "TEMP_TO_PERM",
            "required_skill_code": "RN", "bill_rate_cents": 9000,
            "target_pay_rate_cents": 6000, "annual_salary_cents": 10000000,
        },
        candidate_overrides={"full_name": "Nina RN", "skill_codes": ["RN"], "base_pay_rate_cents": 6000},
        skill=("RN", "CLINICAL"),
        submitted_pay_rate_cents=6000)
    pl, cl = scen["placement"], scen["client"]
    get_success_data(api.convert_placement(pl["id"], {"annual_salary_cents": 10000000}, AM))
    fees, _meta = _list_conversion_fees(api, placement_id=pl["id"])
    assert len(fees) == 1, f"expected exactly one conversion fee, got {len(fees)}"
    fee = fees[0]
    assert fee["placement_id"] == pl["id"], f"fee placement_id {fee['placement_id']!r}"
    assert fee["client_id"] == cl["id"], f"fee client_id {fee['client_id']!r}"
    assert fee["status"] == "BILLED", f"status {fee['status']}"
    assert fee["fee_cents"] == 2000000, f"fee_cents {fee['fee_cents']}"


def test_direct_placement_conversion_fee_clamped_up_to_minimum(api):
    """PRD 3.7: "A `DIRECT` placement does not go through the convert endpoint; instead,
    a conversion fee is created automatically at the moment the `DIRECT` placement is created."
    PRD 3.7: "For a `DIRECT` placement the effective rate is simply the client's `conversion_fee_pct`."
    PRD 3.7: "the final `fee_cents` is at least 250000 cents and at most 5000000 cents — that is,
    the raw fee is first floored at the minimum of 250000 and then capped at the maximum of 5000000,
    with the rounding performed before the clamp."

    annual_salary 1000000 * 0.20 = 200000 raw, below MIN 250000 -> clamped up to 250000, BILLED.

    Design: Corner/calculations/direct_placement_conversion_fee_min_clamp
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Lowball", conversion_fee_pct=0.20)
    job_order, jo_v = create_open_job_order(
        cl["id"], title="Perm Dev", employment_type="DIRECT",
        bill_rate_cents=0, target_pay_rate_cents=0, annual_salary_cents=1000000)
    cand = create_candidate(full_name="Perm Cara", skill_codes=["JAVA"], base_pay_rate_cents=0)
    sub, _iv = drive_submission_to_offer_extended(job_order, cand, cl, submitted_pay_rate_cents=0)
    pl = create_placement(
        sub["id"], jo_v, start_date="2026-06-15T00:00:00Z",
        end_date="2026-06-16T00:00:00Z", standard_weekly_hours=40)
    fees, _meta = _list_conversion_fees(api, placement_id=pl["id"])
    assert len(fees) == 1, f"expected exactly one conversion fee, got {len(fees)}"
    assert fees[0]["fee_cents"] == 250000, f"fee_cents {fees[0]['fee_cents']}"
    assert fees[0]["status"] == "BILLED", f"status {fees[0]['status']}"
    assert pl["placement_type"] == "DIRECT"
    assert pl["assignment_status"] == "ENDED"


def test_direct_placement_zero_projected_figures(api):
    """PRD 3.6: "For a `DIRECT` placement both projected figures are 0, since there is no
    hourly billing."
    PRD 3.4: "a `DIRECT` placement is born already `ENDED` because a direct hire involves
    no temporary assignment period."

    Design: Corner/calculations/direct_placement_zero_projected_margin
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    job_order, jo_v = create_open_job_order(
        cl["id"], title="Perm Dev", employment_type="DIRECT",
        bill_rate_cents=0, target_pay_rate_cents=0, annual_salary_cents=10000000)
    cand = create_candidate(full_name="Perm Cara", skill_codes=["JAVA"], base_pay_rate_cents=0)
    sub, _iv = drive_submission_to_offer_extended(job_order, cand, cl, submitted_pay_rate_cents=0)
    pl = create_placement(
        sub["id"], jo_v, start_date="2026-06-15T00:00:00Z",
        end_date="2026-06-16T00:00:00Z", standard_weekly_hours=40)
    assert pl["placement_type"] == "DIRECT"
    assert pl["assignment_status"] == "ENDED"
    assert pl["projected_weekly_bill_cents"] == 0, f"bill {pl['projected_weekly_bill_cents']}"
    assert pl["projected_weekly_margin_cents"] == 0, f"margin {pl['projected_weekly_margin_cents']}"


def _list_conversion_fees(api, placement_id):
    """Helper: list conversion fees filtered by placement_id, returns (list, meta)."""
    from test_helpers import validate_paginated
    resp = api.list_conversion_fees(AM, params={"placement_id": placement_id})
    return validate_paginated(resp)
