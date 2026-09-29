"""Invoice line pricing, the settlement surcharge, off-posted detection and exposure.

Every expectation here is fixed by the PRD: the quantity discount tier selection and the
surcharge bands of §3.8, the unposted-brand branch of §3.8, the per-finding penalty
components of §3.9 and the two exposure variants of §3.9.
"""

from test_helpers import (
    certify_schedule,
    new_audit,
    new_invoice,
    new_invoice_line,
    new_tier,
    read_exposure,
    read_invoice,
    read_invoice_line,
    read_tier,
    read_wholesaler,
    regulator_headers,
    run_posting,
    set_clock,
    setup_certified_schedule,
    setup_draft_schedule,
    setup_effective_schedule,
    setup_licensee_base,
    submit_schedule,
    validate_paginated,
    validate_success,
    collect_audit,
)

ITEM_750_12 = {
    "size_ml": 750,
    "bottles_per_case": 12,
    "case_price_cents": 120_000,
    "unit_price_cents": 11_000,
}


def test_12_quantity_discount_ignores_tiers_whose_min_cases_exceeds_the_line_quantity(api):
    """PRD §3.8: "Otherwise the eligible tiers are every `ACTIVE` quantity discount tier of the line's item whose `min_cases` is at or below the line's `cases_quantity`."

    The item carries a two-case tier at five percent and a five-case tier at ten percent,
    and a line for three cases may only reach the two-case tier.

    Design: Corner/calculations/quantity_discount_ignores_tiers_whose_min_cases_exceeds_the_line_quantity
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    setup_draft_schedule(scene, posting_month="2026-09", item_specs=[dict(ITEM_750_12)])
    item = scene["items"][0]

    tier_two = new_tier(item["id"], scene["agent_headers"], min_cases=2, discount_pct=0.05)
    tier_five = new_tier(item["id"], scene["agent_headers"], min_cases=5, discount_pct=0.10)
    assert tier_two["discounted_case_price_cents"] == 114_000, (
        "120000 less five percent is 114000, got {}".format(
            tier_two["discounted_case_price_cents"]
        )
    )

    submit_schedule(scene["schedule"]["id"], scene["agent_headers"])
    certify_schedule(scene["schedule"]["id"], scene["certifier_headers"])
    set_clock("2026-10-01T00:00:00.000Z")
    run_posting(scene["program"]["id"])

    invoice = new_invoice(
        scene["wholesaler"]["id"],
        "2026-10-05T00:00:00Z",
        scene["agent_headers"],
        retailer_license_number="R-500",
    )
    line = new_invoice_line(
        invoice["id"], item["id"], 120_000, 11_000, scene["agent_headers"], cases_quantity=3
    )

    validated = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"]), 200
    )
    assert validated["validation_status"] == "VALIDATED", (
        "a line charged at the posted price is clean, got {}".format(
            validated["validation_status"]
        )
    )

    priced = read_invoice_line(line["id"])
    assert priced["gross_cents"] == 360_000, (
        "three cases at 120000 is a gross of 360000, got {}".format(priced["gross_cents"])
    )
    assert priced["quantity_discount_cents"] == 18_000, (
        "three cases times the 6000 cent two-case tier spread is 18000, got {}".format(
            priced["quantity_discount_cents"]
        )
    )
    assert priced["allowed_promotional_cents"] == 0, "no promotional allowance was claimed"
    assert priced["excess_promotional_cents"] == 0, "no promotional allowance was claimed"
    assert priced["allowed_depletion_cents"] == 0, "no depletion allowance was claimed"
    assert priced["excess_depletion_cents"] == 0, "no depletion allowance was claimed"
    assert priced["net_price_cents"] == 342_000, (
        "360000 less the 18000 discount is 342000, got {}".format(priced["net_price_cents"])
    )
    assert priced["posted_gross_cents"] == 360_000, (
        "the posted gross for three cases is 360000, got {}".format(
            priced["posted_gross_cents"]
        )
    )
    assert priced["variance_cents"] == 0, (
        "the charged price equals the posted price, got variance {}".format(
            priced["variance_cents"]
        )
    )
    assert priced["finding_variance_cents"] == 0, (
        "nothing is exposed on this line, got finding variance {}".format(
            priced["finding_variance_cents"]
        )
    )
    assert priced["is_off_posted"] is False, "a zero finding variance is not off posted"

    assert validated["subtotal_cents"] == 342_000, (
        "the subtotal is the sum of net line prices, got {}".format(
            validated["subtotal_cents"]
        )
    )
    assert validated["surcharge_cents"] == 0, (
        "a subtotal below 500000 attracts no surcharge, got {}".format(
            validated["surcharge_cents"]
        )
    )
    assert validated["total_cents"] == 342_000, (
        "the total is the subtotal plus the surcharge, got {}".format(
            validated["total_cents"]
        )
    )
    assert validated["total_allowance_cents"] == 0, "no allowances were claimed"
    assert validated["off_posted_line_count"] == 0, "no line is off posted"

    assert read_tier(tier_five["id"])["status"] == "ACTIVE", (
        "the ineligible five-case tier is still ACTIVE, it was merely not selected"
    )


def test_13_settlement_surcharge_band_switches_on_the_pre_surcharge_subtotal(api):
    """PRD §3.8: "The `surcharge_cents` is `subtotal_cents` multiplied by the band's rate, rounded half up to whole cents, performed exactly once; and `total_cents` is `subtotal_cents` plus `surcharge_cents`."

    Three invoices land one cent below 500,000, exactly on 500,000 and exactly on
    2,000,000 cents, which are the two band edges of §3.8.

    Design: Corner/calculations/invoice_settlement_surcharge_band_switches_on_the_pre_surcharge_subtotal_boundaries
    """
    scene = setup_effective_schedule(
        posting_month="2026-09",
        item_specs=[
            dict(ITEM_750_12),
            {
                "size_ml": 375,
                "bottles_per_case": 12,
                "case_price_cents": 12,
                "unit_price_cents": 1,
            },
        ],
        clock_before_run="2026-10-01T00:00:00Z",
    )
    item_cases = scene["items"][0]
    item_pennies = scene["items"][1]
    agent_headers = scene["agent_headers"]

    def _invoice(retailer_license_number, cases, bottles):
        invoice = new_invoice(
            scene["wholesaler"]["id"],
            "2026-10-05T00:00:00Z",
            agent_headers,
            retailer_license_number=retailer_license_number,
        )
        case_line = new_invoice_line(
            invoice["id"], item_cases["id"], 120_000, 11_000, agent_headers,
            cases_quantity=cases,
        )
        bottle_line = new_invoice_line(
            invoice["id"], item_pennies["id"], 12, 1, agent_headers,
            cases_quantity=0, bottles_quantity=bottles,
        )
        validated = validate_success(
            api.validate_retailer_invoice(invoice["id"], agent_headers), 200
        )
        return validated, case_line, bottle_line

    below_band, _, first_bottle_line = _invoice("R-501", 4, 19_999)
    assert below_band["subtotal_cents"] == 499_999, (
        "480000 plus 19999 is a subtotal of 499999, got {}".format(
            below_band["subtotal_cents"]
        )
    )
    assert below_band["surcharge_cents"] == 0, (
        "a subtotal below 500000 cents attracts a rate of 0.000, got {}".format(
            below_band["surcharge_cents"]
        )
    )
    assert below_band["total_cents"] == 499_999, (
        "the total equals the subtotal when no surcharge applies, got {}".format(
            below_band["total_cents"]
        )
    )

    middle_band, _, _ = _invoice("R-502", 4, 20_000)
    assert middle_band["subtotal_cents"] == 500_000, (
        "480000 plus 20000 is a subtotal of 500000, got {}".format(
            middle_band["subtotal_cents"]
        )
    )
    assert middle_band["surcharge_cents"] == 2_500, (
        "a subtotal of exactly 500000 attracts one half of one percent, 2500 cents, "
        "got {}".format(middle_band["surcharge_cents"])
    )
    assert middle_band["total_cents"] == 502_500, (
        "500000 plus 2500 is 502500, got {}".format(middle_band["total_cents"])
    )

    upper_band, _, _ = _invoice("R-503", 16, 80_000)
    assert upper_band["subtotal_cents"] == 2_000_000, (
        "1920000 plus 80000 is a subtotal of 2000000, got {}".format(
            upper_band["subtotal_cents"]
        )
    )
    assert upper_band["surcharge_cents"] == 20_000, (
        "a subtotal of exactly 2000000 attracts one percent, 20000 cents, got {}".format(
            upper_band["surcharge_cents"]
        )
    )
    assert upper_band["total_cents"] == 2_020_000, (
        "2000000 plus 20000 is 2020000, got {}".format(upper_band["total_cents"])
    )

    for invoice in (below_band, middle_band, upper_band):
        assert invoice["validation_status"] == "VALIDATED", (
            "every line was charged at its posted price, got {}".format(
                invoice["validation_status"]
            )
        )
        assert invoice["off_posted_line_count"] == 0, "no line is off posted"
        assert invoice["total_allowance_cents"] == 0, "no allowances were claimed"
        assert invoice["total_variance_cents"] == 0, "no variance was found"

    bottles_priced = read_invoice_line(first_bottle_line["id"])
    assert bottles_priced["gross_cents"] == 19_999, (
        "19999 loose bottles at one cent is a gross of 19999, got {}".format(
            bottles_priced["gross_cents"]
        )
    )
    assert bottles_priced["posted_gross_cents"] == 19_999, (
        "the posted gross for loose bottles uses the posted unit price, got {}".format(
            bottles_priced["posted_gross_cents"]
        )
    )
    assert bottles_priced["variance_cents"] == 0, (
        "the bottle line was charged at the posted unit price, got variance {}".format(
            bottles_priced["variance_cents"]
        )
    )


def test_17_penalty_exposure_reconciles_when_a_collected_audit_becomes_assessed(api):
    """PRD §3.9: "The exposure under this variant is the accrued figure plus the provisional figure, and it is therefore always greater than or equal to the exposure under `assessed_exposure`."

    Before assessment the 4,000 cent penalty is provisional only; assessment moves the very
    same figure into the accrued bucket without changing total exposure.

    Design: Corner/calculations/penalty_exposure_reconciles_when_a_collected_audit_becomes_assessed
    """
    scene = setup_effective_schedule(
        posting_month="2026-09",
        item_specs=[dict(ITEM_750_12)],
        clock_before_run="2026-10-01T00:00:00Z",
    )
    item = scene["items"][0]

    invoice = new_invoice(
        scene["wholesaler"]["id"], "2026-10-05T00:00:00Z", scene["agent_headers"]
    )
    new_invoice_line(
        invoice["id"], item["id"], 115_000, 11_000, scene["agent_headers"], cases_quantity=2
    )
    flagged = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"]), 200
    )
    assert flagged["validation_status"] == "FLAGGED", (
        "charging 115000 against a posted 120000 flags the invoice, got {}".format(
            flagged["validation_status"]
        )
    )
    assert flagged["total_variance_cents"] == 10_000, (
        "two cases undercharged by 5000 each is a variance of 10000, got {}".format(
            flagged["total_variance_cents"]
        )
    )

    audit = new_audit(scene["wholesaler"]["id"], scene["program"]["id"], "2026-10")
    collected = collect_audit(audit["id"])
    assert collected["base_penalty_cents"] == 4_000, (
        "10000 cents of variance at the default 0.40 rate is 4000, got {}".format(
            collected["base_penalty_cents"]
        )
    )

    before = read_exposure(scene["wholesaler"]["id"], variant="provisional_exposure")
    assert before["accrued_cents"] == 0, (
        "nothing has been assessed yet, got accrued {}".format(before["accrued_cents"])
    )
    assert before["provisional_cents"] == 4_000, (
        "a COLLECTED audit projects 4000 cents, got {}".format(before["provisional_cents"])
    )
    assert before["exposure_cents"] == 4_000, (
        "provisional exposure is accrued plus provisional, got {}".format(
            before["exposure_cents"]
        )
    )

    assessed = validate_success(
        api.assess_compliance_audit(audit["id"], regulator_headers()), 200
    )
    assert assessed["penalty_assessed_cents"] == 4_000, (
        "4000 cents at a 1.00 multiplier is 4000, got {}".format(
            assessed["penalty_assessed_cents"]
        )
    )
    assert assessed["tier_multiplier"] == 1.00, (
        "a prior_violation_count of 2 or fewer yields a tier_multiplier of 1.00, got {}".format(
            assessed["tier_multiplier"]
        )
    )
    assert assessed["prior_violation_count"] == 0, (
        "the wholesaler had no prior violations, got {}".format(
            assessed["prior_violation_count"]
        )
    )

    after = read_exposure(scene["wholesaler"]["id"], variant="provisional_exposure")
    assert after["accrued_cents"] == 4_000, (
        "the assessed penalty is now accrued, got {}".format(after["accrued_cents"])
    )
    assert after["provisional_cents"] == 0, (
        "an ASSESSED audit no longer projects anything, got {}".format(
            after["provisional_cents"]
        )
    )
    assert after["exposure_cents"] == 4_000, (
        "total exposure is unchanged by the reconciliation, got {}".format(
            after["exposure_cents"]
        )
    )

    default_variant = read_exposure(scene["wholesaler"]["id"])
    assert default_variant["variant"] == "assessed_exposure", (
        "an omitted variant reads assessed_exposure, got {}".format(
            default_variant["variant"]
        )
    )
    assert default_variant["accrued_cents"] == 4_000, (
        "the accrued figure is 4000, got {}".format(default_variant["accrued_cents"])
    )
    assert default_variant["exposure_cents"] == 4_000, (
        "assessed exposure reports the accrued figure and nothing more, got {}".format(
            default_variant["exposure_cents"]
        )
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["penalty_exposure_cents"] == 4_000, (
        "the stored penalty_exposure_cents always equals the assessed variant, got {}".format(
            wholesaler["penalty_exposure_cents"]
        )
    )


def test_19_off_posted_detection_treats_an_unposted_item_as_a_whole_gross_finding(api):
    """PRD §3.8: "If no posted price exists for that key as of that instant, the line was sold on an unposted brand: `posted_gross_cents` is 0, `variance_cents` is 0, `finding_variance_cents` is the entire `gross_cents`, and `is_off_posted` is `true`."

    The schedule is certified but not yet effective, so its items are `POSTED` and can never
    be candidates for posted-price resolution.

    Design: Corner/calculations/off_posted_detection_treats_an_item_with_no_posted_price_as_a_whole_gross_finding
    """
    scene = setup_certified_schedule(
        posting_month="2026-09",
        item_specs=[dict(ITEM_750_12)],
        clock="2026-08-01T00:00:00Z",
    )
    item = scene["items"][0]

    invoice = new_invoice(
        scene["wholesaler"]["id"],
        "2026-08-15T00:00:00Z",
        scene["agent_headers"],
        retailer_license_number="R-500",
    )
    line = new_invoice_line(
        invoice["id"], item["id"], 120_000, 11_000, scene["agent_headers"], cases_quantity=2
    )

    flagged = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"]), 200
    )
    assert flagged["validation_status"] == "FLAGGED", (
        "a sale on an unposted key flags the invoice, got {}".format(
            flagged["validation_status"]
        )
    )
    assert flagged["off_posted_line_count"] == 1, (
        "the single line is off posted, got {}".format(flagged["off_posted_line_count"])
    )
    assert flagged["total_variance_cents"] == 240_000, (
        "the whole gross of 240000 is exposed, got {}".format(
            flagged["total_variance_cents"]
        )
    )
    assert flagged["subtotal_cents"] == 240_000, (
        "the net price is unreduced, so the subtotal is 240000, got {}".format(
            flagged["subtotal_cents"]
        )
    )
    assert flagged["surcharge_cents"] == 0, (
        "a subtotal below 500000 attracts no surcharge, got {}".format(
            flagged["surcharge_cents"]
        )
    )
    assert flagged["total_cents"] == 240_000, (
        "the total equals the subtotal, got {}".format(flagged["total_cents"])
    )

    priced = read_invoice_line(line["id"])
    assert priced["gross_cents"] == 240_000, (
        "two cases at 120000 is a gross of 240000, got {}".format(priced["gross_cents"])
    )
    assert priced["posted_gross_cents"] == 0, (
        "there is no posted price to compare against, got {}".format(
            priced["posted_gross_cents"]
        )
    )
    assert priced["variance_cents"] == 0, (
        "the signed variance is 0 on an unposted line, got {}".format(
            priced["variance_cents"]
        )
    )
    assert priced["finding_variance_cents"] == 240_000, (
        "the entire gross is the finding variance, got {}".format(
            priced["finding_variance_cents"]
        )
    )
    assert priced["is_off_posted"] is True, "an unposted line is off posted"

    audit = new_audit(scene["wholesaler"]["id"], scene["program"]["id"], "2026-08")
    collected = collect_audit(audit["id"])
    assert collected["finding_count"] == 1, (
        "one off-posted line yields one finding, got {}".format(collected["finding_count"])
    )
    assert collected["total_variance_cents"] == 240_000, (
        "the audit's total variance is 240000, got {}".format(
            collected["total_variance_cents"]
        )
    )
    assert collected["base_penalty_cents"] == 96_000, (
        "240000 cents at the default 0.40 rate is 96000, got {}".format(
            collected["base_penalty_cents"]
        )
    )

    findings, meta = validate_paginated(
        api.list_audit_findings(regulator_headers(), params={"audit_id": audit["id"]})
    )
    assert meta["total_count"] == 1, (
        "exactly one finding was recorded, got total_count {}".format(meta["total_count"])
    )
    assert findings[0]["finding_type"] == "UNPOSTED_BRAND", (
        "no resolvable posted price classifies the finding UNPOSTED_BRAND, got {}".format(
            findings[0]["finding_type"]
        )
    )
    assert findings[0]["variance_cents"] == 240_000, (
        "the finding carries the line's finding variance 240000, got {}".format(
            findings[0]["variance_cents"]
        )
    )
    assert findings[0]["penalty_component_cents"] == 96_000, (
        "the finding's penalty component is 96000, got {}".format(
            findings[0]["penalty_component_cents"]
        )
    )

    assert read_invoice(invoice["id"])["audit_status"] == "UNDER_AUDIT", (
        "collection takes custody of every flagged invoice of the audited month"
    )
