"""Program reporting: cash vs accrual variants, share precision, grant ledger."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_accepted_delivery,
    create_agreement,
    create_approved_farm,
    create_approved_invoice,
    create_forecast_line,
    create_invoice,
    create_kitchen,
    create_product,
    create_program_year,
    create_receiving_window,
    create_verified_offering,
    setup_procurement_chain,
    sign_agreement,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def _local_invoice_10200_unpaid():
    """Standard chain; one APPROVED but unpaid invoice (subtotal 10000,
    incentive 200) whose delivery date is 2026-08-10."""
    chain = setup_procurement_chain()
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    invoice = create_approved_invoice(delivery["id"], chain.farm["id"], "INV-1")
    assert invoice["subtotal_cents"] == 10000
    assert invoice["total_cents"] == 10200
    return chain, invoice


def test_report_cash_vs_accrual_month_split(api):
    """PRD section 3.9: "A delivery accepted in August but paid in September
    therefore lands in the August accrual column and the September cash
    column — different months, different totals, same underlying data."
    PRD section 3.6: "Payment moves `APPROVED` → `PAID` (`ERR_INVOICE_NOT_PAYABLE`
    otherwise) and stamps `paid_at` with the current logical clock timestamp."

    Design: Difficulty/dual_variant_calc/report_cash_vs_accrual_month_split
    """
    chain, invoice = _local_invoice_10200_unpaid()

    august = validate_success(
        api.get_program_year_report(chain.year["id"], ADMIN, month="2026-08"), 200
    )
    assert august["accrual_local_spend_cents"] == 10000
    assert august["accrual_total_spend_cents"] == 10000
    assert august["cash_local_spend_cents"] == 0
    assert august["cash_total_spend_cents"] == 0

    advance_clock("2026-09-02T00:00:00Z")
    paid = validate_success(api.pay_invoice(invoice["id"], ADMIN), 200)
    # paid_at stamps the logical clock instant (2026-09-02), not the wall
    # clock; the PRD fixes the instant, not the fractional-digit rendering.
    assert paid["paid_at"].startswith("2026-09-02T00:00:00"), (
        f"paid_at stamps the logical clock, not the wall clock; got {paid['paid_at']}"
    )

    september = validate_success(
        api.get_program_year_report(chain.year["id"], ADMIN, month="2026-09"), 200
    )
    assert september["cash_local_spend_cents"] == 10000
    assert september["cash_total_spend_cents"] == 10000
    assert september["accrual_local_spend_cents"] == 0
    assert september["accrual_total_spend_cents"] == 0


def test_report_accrual_month_unchanged_by_later_payment(api):
    """PRD section 3.9: "The accrual basis includes invoices in `DRAFT`,
    `SUBMITTED`, `APPROVED`, or `PAID` whose delivery's `delivery_date` falls
    in the report month; the cash basis includes only `PAID` invoices whose
    `paid_at` falls in the report month."

    Design: Difficulty/dual_variant_calc/report_cash_vs_accrual_month_split
    """
    chain, invoice = _local_invoice_10200_unpaid()

    advance_clock("2026-09-02T00:00:00Z")
    validate_success(api.pay_invoice(invoice["id"], ADMIN), 200)

    # The August accrual column still counts the (now PAID) August delivery;
    # August cash stays zero because the payment landed in September.
    august = validate_success(
        api.get_program_year_report(chain.year["id"], ADMIN, month="2026-08"), 200
    )
    assert august["accrual_local_spend_cents"] == 10000
    assert august["cash_local_spend_cents"] == 0

    invoice_after = validate_success(api.get_invoice(invoice["id"], ADMIN), 200)
    assert invoice_after["status"] == "PAID"
    assert invoice_after["paid_at"].startswith("2026-09-02T00:00:00")


def test_report_computed_read_schema_zero_activity(api):
    """PRD section 3.9: "The share figures are zero when their basis total is
    zero"
    PRD section 3.9: "the final rollup sums the final match only over claims
    that have moved past `UNDER_REVIEW`, with claims still awaiting
    adjudication contributing zero."

    Design: Corner/endpoints/ep_report_computed_read_schema
    """
    year = create_program_year()
    report = validate_success(
        api.get_program_year_report(year["id"], ADMIN, month="2026-08"), 200
    )
    for field in (
        "month",
        "cash_local_spend_cents",
        "accrual_local_spend_cents",
        "cash_total_spend_cents",
        "accrual_total_spend_cents",
        "cash_local_share_pct",
        "accrual_local_share_pct",
        "meets_target_cash",
        "meets_target_accrual",
        "grant_award_cents",
        "grant_drawn_cents",
        "grant_remaining_cents",
        "match_provisional_cents",
        "match_final_cents",
    ):
        assert field in report, f"report must carry {field}"
    assert report["month"] == "2026-08"
    assert report["cash_total_spend_cents"] == 0
    assert report["accrual_total_spend_cents"] == 0
    assert report["cash_local_share_pct"] == 0
    assert report["accrual_local_share_pct"] == 0
    assert report["grant_award_cents"] == 1000000
    assert report["grant_drawn_cents"] == 0
    assert report["grant_remaining_cents"] == 1000000
    assert report["match_provisional_cents"] == 0
    assert report["match_final_cents"] == 0


def test_report_share_pct_precision(api):
    """PRD section 3.9: "The share figures are zero when their basis total is
    zero, and otherwise one hundred times the local amount divided by the
    total, rounded half-up to two decimal places; a share that meets or exceeds
    the year's `local_spend_target_pct` counts as meeting the target."
    PRD section 3.6: "Third, `incentive_credit_cents` is the subtotal
    multiplied by that rate, rounded half-up to a whole cent, when the
    agreement is local-eligible — and zero otherwise."

    Design: Corner/calculations/calc_report_share_pct_precision
    """
    year = create_program_year()
    product = create_product()
    farm_l = create_approved_farm(legal_name="Local Farm", distance_miles_to_hub=30)
    farm_n = create_approved_farm(legal_name="Far Farm", distance_miles_to_hub=150)
    off_l = create_verified_offering(farm_l["id"], year["id"], product["id"])
    off_n = create_verified_offering(farm_n["id"], year["id"], product["id"])
    create_forecast_line(year["id"], product["id"])
    kitchen = create_kitchen()
    window = create_receiving_window(kitchen["id"], capacity_deliveries=5)

    agr_l = validate_success(
        create_agreement(year["id"], off_l["id"], committed_quantity=40), 201
    )
    sign_agreement(agr_l["id"], farm_l["id"])
    agr_n = validate_success(
        create_agreement(year["id"], off_n["id"], committed_quantity=80), 201
    )
    sign_agreement(agr_n["id"], farm_n["id"])

    del_l = create_accepted_delivery(
        agr_l["id"], kitchen["id"], window["id"], farm_l["id"], "2026-08-10", 40
    )
    del_n = create_accepted_delivery(
        agr_n["id"], kitchen["id"], window["id"], farm_n["id"], "2026-08-10", 80
    )
    inv_l = create_approved_invoice(del_l["id"], farm_l["id"], "INV-L")
    assert inv_l["subtotal_cents"] == 10000
    # The non-local agreement earns no incentive credit at all.
    inv_n = validate_success(create_invoice(del_n["id"], farm_n["id"], "INV-N"), 201)
    assert inv_n["incentive_credit_cents"] == 0
    assert inv_n["subtotal_cents"] == 20000

    report = validate_success(
        api.get_program_year_report(year["id"], ADMIN, month="2026-08"), 200
    )
    assert report["accrual_local_spend_cents"] == 10000
    assert report["accrual_total_spend_cents"] == 30000
    # round_half_up(100 * 10000 / 30000, 2) = 33.33, which meets the 30 target.
    assert report["accrual_local_share_pct"] == 33.33
    assert report["meets_target_accrual"] is True
