"""Invoice arithmetic: per-line tax rounding, the promotion engine and the service-fee tier."""
from test_helpers import (
    ApiErrorId,
    apply_promo,
    apply_promo_payload,
    create_account,
    create_plan,
    create_promo,
    create_subscription,
    first_issued_invoice,
    get_invoice,
    invoice_lines,
    line_of_type,
    make_registrant_headers,
    register_domain,
    validate_error,
)


# =========================================================================
# Per-line tax rounding, then sum  (Difficulty/combinatorial_formula)
# =========================================================================

def test_invoice_tax_is_the_sum_of_per_line_rounded_taxes(api):
    """PRD §3.8: "Tax is charged at 8.25 percent and **the rounding happens per line item,
    before summing**."
    PRD §3.8: "The invoice's `tax_cents` is the sum of those already-rounded per-line
    figures — it is emphatically *not* the whole-invoice discounted base multiplied by the
    rate and rounded once, and the two orders differ by a cent on many real invoices."

    A one-year .xyz registration with WHOIS privacy bills 199 + 999 = 1198 cents. Rounding
    per line gives 16 + 82 = 98; rounding once over 1198 would give 99.

    Design: Difficulty/combinatorial_formula/per_line_tax_rounding_then_sum_beats_invoice_wide_rounding
    """
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(account, "budgetsite", "xyz", whois_privacy=True, auto_renew=False)

    invoice = first_issued_invoice(account["id"], headers)

    assert invoice["subtotal_cents"] == 1198
    assert invoice["tax_cents"] == 98, (
        "per-line rounding then sum yields 98, not the invoice-wide 99"
    )
    assert invoice["service_fee_cents"] == 0
    assert invoice["total_cents"] == 1296


def test_registration_and_privacy_lines_each_carry_their_own_rounded_tax(api):
    """PRD §3.8: "For each line, `line_tax_cents` is the line's subtotal minus its discount,
    multiplied by 0.0825, rounded half up to whole cents."
    PRD §3.2: "That invoice carries a `DOMAIN_REGISTRATION` line whose `quantity` is the
    number of years and whose `unit_price_cents` is the base year price; when privacy was
    requested it also carries a `PRIVACY_FEE` line of 999 cents per year of the term."

    Design: Difficulty/combinatorial_formula/per_line_tax_rounding_then_sum_beats_invoice_wide_rounding
    """
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(account, "budgetsite", "xyz", whois_privacy=True, auto_renew=False)

    invoice = first_issued_invoice(account["id"], headers)
    lines = invoice_lines(invoice["id"], account)

    registration = line_of_type(lines, "DOMAIN_REGISTRATION")
    assert registration["quantity"] == 1
    assert registration["unit_price_cents"] == 199
    assert registration["line_subtotal_cents"] == 199
    assert registration["line_tax_cents"] == 16, "round_half_up(199 * 0.0825) == 16"

    privacy = line_of_type(lines, "PRIVACY_FEE")
    assert privacy["line_subtotal_cents"] == 999
    assert privacy["line_tax_cents"] == 82, "round_half_up(999 * 0.0825) == 82"

    assert registration["line_tax_cents"] + privacy["line_tax_cents"] == invoice["tax_cents"]


# =========================================================================
# Promo cap, then service-fee tier  (Difficulty/combinatorial_formula)
# =========================================================================

def _ultimate_hosting_invoice():
    """ULTIMATE plan at 20999 cents → a single-line ISSUED HOSTING_PLAN invoice."""
    plan = create_plan(
        plan_code="ULT-1", tier="ULTIMATE", storage_quota_mb=20480,
        bandwidth_quota_mb=51200, monthly_price_cents=20999, included_mailboxes=25,
        included_ssl=True, overage_rate_cents_per_gb=150,
    )
    account = create_account()
    create_subscription(account, plan)
    invoice = first_issued_invoice(account["id"], make_registrant_headers(account["id"]))
    return account, invoice


def test_promo_discount_is_capped_then_the_service_fee_is_keyed_on_the_post_discount_subtotal(api):
    """PRD §3.8: "**Five:** the invoice's `discount_cents` is the smaller of that raw
    discount and the code's `max_discount_cents`."
    PRD §3.8: "The processing fee is keyed on the invoice's subtotal *after* the discount —
    that is, `subtotal_cents` minus `discount_cents` — and never on the pre-discount figure,
    and the fee itself never enters the discount base."
    PRD §3.8: "When it is at least 5000 cents but below 20000 cents, `service_fee_cents` is
    299."

    Design: Difficulty/combinatorial_formula/promo_cap_then_service_fee_tier_evaluation_order
    """
    create_promo(
        "SAVE20", discount_type="PERCENT", discount_value=0.20,
        applies_to_item_types=["HOSTING_PLAN"], min_subtotal_cents=10000,
        max_discount_cents=3000,
    )
    account, invoice = _ultimate_hosting_invoice()

    updated = apply_promo(invoice, account, "SAVE20")

    assert updated["subtotal_cents"] == 20999
    assert updated["discount_cents"] == 3000, (
        "the raw 20% discount of 4200 is capped at max_discount_cents"
    )
    assert updated["service_fee_cents"] == 299, (
        "the fee tier is keyed on the post-discount 17999, not on the pre-discount 20999"
    )


def test_promo_application_recomputes_tax_total_and_records_the_applied_code(api):
    """PRD §3.8: "The invoice's `total_cents` is therefore `subtotal_cents` minus
    `discount_cents` plus `service_fee_cents` plus `tax_cents`. Every invoice runs this same
    total calculation at creation (with a zero discount) and re-runs it whenever a promotion
    is applied."
    PRD §3.8: "A second application legitimately replaces the first: `applied_promo_code` is
    overwritten and the discount recomputed from scratch. The invoice's `version`
    increments."

    Design: Difficulty/combinatorial_formula/promo_cap_then_service_fee_tier_evaluation_order
    """
    create_promo(
        "SAVE20", discount_type="PERCENT", discount_value=0.20,
        applies_to_item_types=["HOSTING_PLAN"], min_subtotal_cents=10000,
        max_discount_cents=3000,
    )
    account, invoice = _ultimate_hosting_invoice()

    updated = apply_promo(invoice, account, "SAVE20")

    assert updated["tax_cents"] == 1485, "round_half_up((20999 - 3000) * 0.0825) == 1485"
    assert updated["total_cents"] == 19783, "20999 - 3000 + 299 + 1485"
    assert updated["applied_promo_code"] == "SAVE20"
    assert updated["version"] == invoice["version"] + 1


# =========================================================================
# Empty eligible-line set  (Difficulty/boundary_precision_check)
# =========================================================================

def test_promo_with_no_eligible_line_item_is_rejected(api):
    """PRD §3.8: "**Two:** the eligible lines are those whose `item_type` appears in the
    code's `applies_to_item_types`, and the eligible subtotal is the sum of their line
    subtotals; if there are no eligible lines, or the eligible subtotal is zero, the request
    is refused with `ERR_PROMO_NOT_APPLICABLE`."

    Design: Difficulty/boundary_precision_check/promo_with_no_eligible_line_items_rejected
    """
    create_promo(
        "HOSTONLY", discount_type="PERCENT", discount_value=0.25,
        applies_to_item_types=["HOSTING_PLAN"], min_subtotal_cents=0,
        max_discount_cents=5000,
    )
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)

    resp = api.apply_promo(
        invoice["id"], apply_promo_payload("HOSTONLY", invoice["version"]), headers
    )

    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_APPLICABLE.value, 422)


def test_rejected_promo_leaves_the_invoice_totals_untouched(api):
    """PRD §3.8: "**Two:** the eligible lines are those whose `item_type` appears in the
    code's `applies_to_item_types`, and the eligible subtotal is the sum of their line
    subtotals; if there are no eligible lines, or the eligible subtotal is zero, the request
    is refused with `ERR_PROMO_NOT_APPLICABLE`."
    PRD §3.8: "each is born `ISSUED` with `discount_cents` and `service_fee_cents` at 0,
    `applied_promo_code` null, `amount_paid_cents` and `amount_refunded_cents` at 0, and a
    `billing_period_id` that is set only on the bandwidth-overage invoice raised at a period
    close and is null on every other invoice."

    Design: Difficulty/boundary_precision_check/promo_with_no_eligible_line_items_rejected
    """
    create_promo(
        "HOSTONLY", discount_type="PERCENT", discount_value=0.25,
        applies_to_item_types=["HOSTING_PLAN"], min_subtotal_cents=0,
        max_discount_cents=5000,
    )
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)

    api.apply_promo(
        invoice["id"], apply_promo_payload("HOSTONLY", invoice["version"]), headers
    )

    after = get_invoice(invoice["id"], account)
    assert after["discount_cents"] == 0
    assert after["applied_promo_code"] is None
    assert after["total_cents"] == 1298, "1199 subtotal + 99 tax, no service fee"


# =========================================================================
# Corner instances
# =========================================================================

def test_flat_promo_waterfalls_across_eligible_lines_in_created_at_order(api):
    """PRD §3.8: "**Six:** the discount is allocated across the eligible lines as a
    waterfall, taking them in `created_at` ascending order and giving each line the smaller
    of the remaining undistributed discount and that line's own `line_subtotal_cents`, until
    the discount is exhausted."
    PRD §3.8: "**Four:** the raw discount is, for a `PERCENT` code, the eligible subtotal
    multiplied by `discount_value` and rounded half up to whole cents; for a `FLAT` code,
    the smaller of `discount_value` and the eligible subtotal."

    Design: Corner/calculations/flat_promo_waterfalls_across_eligible_lines_in_created_at_order
    """
    create_promo(
        "FLAT30", discount_type="FLAT", discount_value=3000,
        applies_to_item_types=["DOMAIN_REGISTRATION", "PRIVACY_FEE"],
        min_subtotal_cents=0, max_discount_cents=3000,
    )
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(
        account, "example", "com", term_years=2, whois_privacy=True, auto_renew=False
    )
    invoice = first_issued_invoice(account["id"], headers)

    updated = apply_promo(invoice, account, "FLAT30")
    lines = invoice_lines(invoice["id"], account)

    assert updated["subtotal_cents"] == 4396, "2 * 1199 registration + 2 * 999 privacy"
    assert updated["discount_cents"] == 3000

    registration = line_of_type(lines, "DOMAIN_REGISTRATION")
    assert registration["line_subtotal_cents"] == 2398
    assert registration["line_discount_cents"] == 2398, "the first line is filled entirely"
    assert registration["line_tax_cents"] == 0

    privacy = line_of_type(lines, "PRIVACY_FEE")
    assert privacy["line_subtotal_cents"] == 1998
    assert privacy["line_discount_cents"] == 602, "the remaining 602 spills into line two"
    assert privacy["line_tax_cents"] == 115, "round_half_up((1998 - 602) * 0.0825) == 115"

    assert updated["tax_cents"] == 115
    assert updated["service_fee_cents"] == 0, "post-discount subtotal 1396 is below 5000"
    assert updated["total_cents"] == 1511


def test_promo_below_the_pre_discount_minimum_subtotal_is_rejected(api):
    """PRD §3.8: "Only then — **three** — is the minimum gate applied, against the
    *pre-discount* whole-invoice subtotal: if `subtotal_cents` is below the code's
    `min_subtotal_cents`, the answer is `ERR_PROMO_MIN_NOT_MET`."

    Design: Corner/validations/promo_below_min_subtotal_rejected
    """
    create_promo(
        "BIG50", discount_type="PERCENT", discount_value=0.50,
        applies_to_item_types=["DOMAIN_REGISTRATION"], min_subtotal_cents=5000,
        max_discount_cents=5000,
    )
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])
    register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)

    resp = api.apply_promo(
        invoice["id"], apply_promo_payload("BIG50", invoice["version"]), headers
    )
    validate_error(resp, ApiErrorId.ERR_PROMO_MIN_NOT_MET.value, 422)

    after = get_invoice(invoice["id"], account)
    assert after["discount_cents"] == 0
    assert after["applied_promo_code"] is None
    assert after["total_cents"] == 1298


def test_second_apply_promo_with_a_stale_invoice_version_is_rejected(api):
    """PRD §2.6: "Applying a promotion to an invoice must likewise carry
    `expected_invoice_version`, a non-optional field holding the client's last observed
    `version` of the target `Invoice`. A mismatch against the invoice's current `version` is
    rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_expected_invoice_version_on_apply_promo_returns_412
    """
    create_promo(
        "DOM10", discount_type="PERCENT", discount_value=0.10,
        applies_to_item_types=["DOMAIN_REGISTRATION"], min_subtotal_cents=0,
        max_discount_cents=5000,
    )
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)
    stale_version = invoice["version"]

    first = apply_promo(invoice, account, "DOM10", stale_version)
    assert first["discount_cents"] == 120, "round_half_up(1199 * 0.10) == 120"
    assert first["applied_promo_code"] == "DOM10"

    resp = api.apply_promo(
        invoice["id"], apply_promo_payload("DOM10", stale_version), headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_INVOICE_VERSION.value, 412)

    after = get_invoice(invoice["id"], account)
    assert after["version"] == stale_version + 1, "bumped once by the successful apply only"
    assert after["discount_cents"] == 120
