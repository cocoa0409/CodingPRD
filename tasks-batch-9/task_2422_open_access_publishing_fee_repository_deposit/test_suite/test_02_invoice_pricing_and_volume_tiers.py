"""Invoice re-pricing: the pinned composition order of the two rounding steps, and
the volume tier drawn from paid invoices only at the inclusive tier boundary.

Both scenarios turn on the order in which the components of one expression are
evaluated, so an implementation that folds the steps together lands one whole tier
or one whole cent away from the expected amount.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    activate_agreement,
    add_coverage,
    approve_invoice_for_payment,
    create_publisher_invoice_payload,
    draft_agreement,
    pay_invoice,
    read_article,
    receive_invoice,
    record_article,
    register_author,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    validate_invoice,
    validate_success,
)

LIBRARIAN = TEST_USERS["librarian_headers"]


# --------------------------------------------------------------------------- #
# preambles
# --------------------------------------------------------------------------- #
def _setup_ta_full_article_at_half_cent_net() -> dict:
    """A TA_FULL article whose base 250500 at a 0.175 discount produces a net of
    exactly 206662.5 cents before rounding."""
    set_clock("2026-08-10T00:00:00Z")
    publisher = register_publisher(
        publisher_code="CORVID", name="Corvid Scientific", country_code="GB"
    )
    journal = register_journal(
        publisher["id"],
        issn="1748-9326",
        title="Corvid Reviews of Applied Optics",
        oa_model="HYBRID",
        list_apc_cents=250500,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Rhea Calder",
        email="rhea.calder@uni.example",
        orcid="0000-0003-4444-1212",
        department_code="PHY",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-CORVID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.175,
        covered_oa_models=["HYBRID"],
    )
    add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2027-06-30",
    )
    agreement = activate_agreement(agreement["id"])
    article = record_article(
        journal["id"],
        author["id"],
        manuscript_title="Sub-cent metrology of dielectric mirrors",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "agreement": agreement,
        "article": article,
        "determination": determination,
    }


def _setup_author_pays_publisher_with_two_paid_invoices() -> dict:
    """A publisher with no agreement, three AUTHOR_PAYS articles, and two invoices
    of net 250000 each driven all the way to PAID."""
    set_clock("2026-08-10T00:00:00Z")
    publisher = register_publisher(
        publisher_code="SELKIE", name="Selkie Press", country_code="IE"
    )
    journal = register_journal(
        publisher["id"],
        issn="2050-084X",
        title="Selkie Journal of Marine Ecology",
        oa_model="FULLY_OA",
        list_apc_cents=250000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Maeve Lynch",
        email="maeve.lynch@uni.example",
        orcid="0000-0002-7654-3210",
        department_code="MAR",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    titles = [
        "Kelp forest recovery after storm disturbance",
        "Grazing pressure on juvenile kelp",
        "Sediment turbidity and holdfast survival",
    ]
    articles = []
    determinations = []
    for title in titles:
        article = record_article(
            journal["id"], author["id"], manuscript_title=title, accepted_on="2026-08-05"
        )
        determinations.append(run_eligibility_check(article["id"], basis="PROVISIONAL"))
        articles.append(article)

    paid = []
    for article, number, reference in [
        (articles[0], "SELKIE-1001", "WIRE-77001"),
        (articles[1], "SELKIE-1002", "WIRE-77002"),
    ]:
        invoice = receive_invoice(
            publisher["id"],
            article["id"],
            number,
            265000,
            0.0,
            0.06,
            "2026-08-10",
        )
        received_net = invoice["net_cents"]
        validate_invoice(invoice["id"])
        approve_invoice_for_payment(invoice["id"])
        paid.append(
            {
                "received_net": received_net,
                "received": invoice,
                "paid": pay_invoice(invoice["id"], reference),
            }
        )
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "articles": articles,
        "determinations": determinations,
        "paid_invoices": paid,
    }


# --------------------------------------------------------------------------- #
# per-component rounding, then the sum
# --------------------------------------------------------------------------- #
def test_received_invoice_rounds_net_half_up_before_computing_vat(api):
    """The agreement fixes the entitled discount, so the net of 250500 x 0.825 =
    206662.5 rounds half up to 206663 and the VAT is taken on that rounded net;
    the sum is never rounded again, which pins the expected total at 219063 rather
    than the 219062 a single rounding of the sum would produce.

    PRD §2.7: "Wherever a fractional multiplication must be reduced to cents, the result is rounded half up: a value whose fractional part is exactly one half rounds away from zero to the next whole cent."
    PRD §2.7: "Invoice pricing in particular rounds twice — once for the net amount and once for the tax amount — and never rounds the sum of the two."
    PRD §3.7: "The `entitled_discount_pct` — the discount the institution is actually entitled to — depends on the route: when the determination's route is `TA_FULL` or `TA_CAPPED`, it is that determination's `discount_pct_applied`, because the agreement fixes the discount; when the route is `FUND_APC` or `AUTHOR_PAYS`, there is no agreement and the entitlement comes instead from the publisher's volume tier described below."
    PRD §3.7: "First, `net_cents` is the base multiplied by one minus the `entitled_discount_pct`, rounded half up to whole cents."
    PRD §3.7: "Second, `vat_cents` is that already-rounded `net_cents` multiplied by the invoice's `vat_pct`, rounded half up to whole cents — the tax is computed on the rounded net, not on the unrounded net."
    PRD §3.7: "Third, `expected_amount_cents` is `net_cents` plus `vat_cents` with no further rounding applied to the sum."
    PRD §3.7: "Summing first and rounding once is explicitly *not* the rule and can differ by up to one cent."
    PRD §3.7: "A recorded invoice starts in `status` `RECEIVED` with no `dispute_reason`, no `payment_approved_by_user_id` and no `payment_reference`, and the expected amount is priced immediately at creation."
    Design: Difficulty/combinatorial_formula/invoice_round_per_component_then_sum_at_half_cent_net
    """
    scenario = _setup_ta_full_article_at_half_cent_net()
    determination = scenario["determination"]

    assert determination["route"] == "TA_FULL", (
        f"the covered HYBRID journal gives route TA_FULL, got {determination['route']!r}"
    )
    assert determination["discount_pct_applied"] == pytest.approx(0.175, abs=0.01), (
        "the agreement's discount_pct is applied verbatim, expected 0.175, got "
        f"{determination['discount_pct_applied']}"
    )
    assert determination["list_base_cents"] == 250500, (
        f"expected list_base_cents 250500, got {determination['list_base_cents']}"
    )
    assert determination["covered_amount_cents"] == 206663, (
        "250500 x 0.825 = 206662.5 rounds half up to 206663, got "
        f"{determination['covered_amount_cents']}"
    )

    response = api.create_publisher_invoice(
        create_publisher_invoice_payload(
            scenario["publisher"]["id"],
            scenario["article"]["id"],
            "CORVID-2026-4417",
            219063,
            0.175,
            0.06,
            "2026-08-10",
        ),
        LIBRARIAN,
    )
    invoice = validate_success(response, expected_status=201)

    assert invoice["status"] == "RECEIVED", (
        f"a recorded invoice starts in RECEIVED, got {invoice['status']!r}"
    )
    assert invoice["entitled_discount_pct"] == pytest.approx(0.175, abs=0.01), (
        "the TA_FULL determination's discount is the entitlement, expected 0.175, got "
        f"{invoice['entitled_discount_pct']}"
    )
    assert invoice["net_cents"] == 206663, (
        f"net_cents must be the half-up rounded 206663, got {invoice['net_cents']}"
    )
    assert invoice["vat_cents"] == 12400, (
        "VAT is 0.06 of the rounded net 206663, expected 12400, got "
        f"{invoice['vat_cents']}"
    )
    assert invoice["expected_amount_cents"] == 219063, (
        f"206663 plus 12400 is 219063, got {invoice['expected_amount_cents']}"
    )
    assert invoice["expected_amount_cents"] != 219062, (
        "219062 is the forbidden sum-then-round result, got "
        f"{invoice['expected_amount_cents']}"
    )
    assert invoice["variance_cents"] == 0, (
        f"the billed 219063 matches the expected amount, got {invoice['variance_cents']}"
    )


def test_invoice_validation_recomputes_components_and_records_a_match(api):
    """Validation re-prices the invoice from the effective determination, arrives at
    the same 219063 expected amount, and a zero variance is a MATCH that moves the
    invoice to VALIDATED without a dispute.

    PRD §3.7: "It first recomputes the whole pricing — refreshing `entitled_discount_pct`, `net_cents`, `vat_cents`, `expected_amount_cents` and `variance_cents`, since a determination may have changed since receipt — and then branches on the recomputed `validation_outcome`."
    PRD §3.7: "Finally, `variance_cents` is the invoice's `invoice_amount_cents` less the `expected_amount_cents`, and may be negative when the publisher under-billed."
    PRD §3.7: "Otherwise, if `variance_cents` is exactly zero the outcome is `MATCH`."
    PRD §3.7: "A `MATCH` or a `WITHIN_TOLERANCE` moves the invoice from `RECEIVED` to `VALIDATED` and records no dispute."
    PRD §2.7: "Invoice pricing in particular rounds twice — once for the net amount and once for the tax amount — and never rounds the sum of the two."
    Design: Difficulty/combinatorial_formula/invoice_round_per_component_then_sum_at_half_cent_net
    """
    scenario = _setup_ta_full_article_at_half_cent_net()
    received = receive_invoice(
        scenario["publisher"]["id"],
        scenario["article"]["id"],
        "CORVID-2026-4417",
        219063,
        0.175,
        0.06,
        "2026-08-10",
    )

    response = api.validate_publisher_invoice(received["id"], LIBRARIAN)
    invoice = validate_success(response)

    assert invoice["net_cents"] == 206663, (
        f"the recomputed net_cents must still be 206663, got {invoice['net_cents']}"
    )
    assert invoice["vat_cents"] == 12400, (
        f"the recomputed vat_cents must still be 12400, got {invoice['vat_cents']}"
    )
    assert invoice["expected_amount_cents"] == 219063, (
        f"the recomputed expected amount must be 219063, got {invoice['expected_amount_cents']}"
    )
    assert invoice["expected_amount_cents"] != 219062, (
        "219062 would mean the sum was rounded once instead of each component, got "
        f"{invoice['expected_amount_cents']}"
    )
    assert invoice["variance_cents"] == 0, (
        f"expected a zero variance, got {invoice['variance_cents']}"
    )
    assert invoice["validation_outcome"] == "MATCH", (
        f"a zero variance is a MATCH, got {invoice['validation_outcome']!r}"
    )
    assert invoice["status"] == "VALIDATED", (
        f"a MATCH moves RECEIVED to VALIDATED, got {invoice['status']!r}"
    )
    assert invoice.get("dispute_reason") is None, (
        f"a MATCH records no dispute, got {invoice.get('dispute_reason')!r}"
    )


# --------------------------------------------------------------------------- #
# volume tier from paid invoices only
# --------------------------------------------------------------------------- #
def test_paid_invoices_below_the_first_tier_are_priced_at_no_entitlement():
    """With no agreement in play the entitlement comes from the volume tier, and
    the first two invoices see prior paid net spend of 0 and 250000 respectively —
    both below the 500000-cent boundary — so each is priced at no discount and each
    contributes a net of 250000 once PAID.

    PRD §3.7: "The order is: prior paid net spend is computed **from other invoices only, and only from those whose `status` is `PAID`** — the invoice being priced is excluded, and so are invoices sitting in `RECEIVED`, `VALIDATED`, `APPROVED_FOR_PAYMENT` or `DISPUTED`; then the tier is selected from that prior figure; then this invoice's `net_cents` is computed from the selected tier and is never fed back into the prior figure."
    PRD §3.7: "Tier boundaries are inclusive: prior paid net spend of fifty thousand dollars or more (5000000 cents) earns a twenty percent entitlement, at least twenty thousand dollars (2000000 cents) earns fifteen percent, at least five thousand dollars (500000 cents) earns ten percent, and anything below five thousand dollars earns nothing at all."
    PRD §3.4: "The funding dimension then follows the route: a `TA_FULL` route sets `funding_status` to `FUNDED`; a `TA_CAPPED` route sets it to `ELIGIBILITY_CHECKED` when `eligible_request_cents` is greater than zero and to `SELF_FUNDED` when `eligible_request_cents` is zero; a `FUND_APC` route sets it to `ELIGIBILITY_CHECKED`; an `AUTHOR_PAYS` route sets it to `SELF_FUNDED`."
    PRD §3.7: "A different `FundManager` then pays it, supplying the bank `payment_reference`, which moves the invoice from `APPROVED_FOR_PAYMENT` to `PAID`."
    Design: Difficulty/combinatorial_formula/volume_tier_from_paid_invoices_only_at_tier1_boundary
    """
    scenario = _setup_author_pays_publisher_with_two_paid_invoices()

    assert scenario["determinations"][0]["route"] == "AUTHOR_PAYS", (
        "no agreement and no qualifying grant gives route AUTHOR_PAYS, got "
        f"{scenario['determinations'][0]['route']!r}"
    )
    first_article = read_article(scenario["articles"][0]["id"])
    assert first_article["funding_status"] == "SELF_FUNDED", (
        f"an AUTHOR_PAYS route sets SELF_FUNDED, got {first_article['funding_status']!r}"
    )

    first, second = scenario["paid_invoices"]
    assert first["received_net"] == 250000, (
        f"the first invoice is priced at no discount, expected net 250000, got "
        f"{first['received_net']}"
    )
    assert second["received_net"] == 250000, (
        "the second invoice still sees only 250000 of prior paid net spend, so it is "
        f"also priced at no discount, got {second['received_net']}"
    )
    assert first["paid"]["status"] == "PAID", (
        f"the first invoice must reach PAID, got {first['paid']['status']!r}"
    )
    assert second["paid"]["status"] == "PAID", (
        f"the second invoice must reach PAID, got {second['paid']['status']!r}"
    )
    assert first["paid"]["entitled_discount_pct"] == pytest.approx(0.0, abs=0.01), (
        "prior paid net spend was below 500000 when the first invoice was priced, so "
        f"its entitlement is 0.0, got {first['paid']['entitled_discount_pct']}"
    )


def test_third_invoice_at_the_inclusive_tier_boundary_earns_ten_percent(api):
    """Two PAID invoices of net 250000 put prior paid net spend at exactly the
    500000-cent boundary, and because the boundary is inclusive the third invoice
    is entitled to ten percent: net 225000, VAT 13500 and an expected total of
    238500 rather than the undiscounted 265000.

    PRD §3.7: "The prior figure is the sum of `net_cents` over the same publisher's paid invoices whose `invoice_date` falls in the same institutional fiscal year as this invoice's `invoice_date`."
    PRD §3.7: "Tier boundaries are inclusive: prior paid net spend of fifty thousand dollars or more (5000000 cents) earns a twenty percent entitlement, at least twenty thousand dollars (2000000 cents) earns fifteen percent, at least five thousand dollars (500000 cents) earns ten percent, and anything below five thousand dollars earns nothing at all."
    PRD §3.7: "First, `net_cents` is the base multiplied by one minus the `entitled_discount_pct`, rounded half up to whole cents."
    PRD §3.7: "Second, `vat_cents` is that already-rounded `net_cents` multiplied by the invoice's `vat_pct`, rounded half up to whole cents — the tax is computed on the rounded net, not on the unrounded net."
    PRD §3.7: "Third, `expected_amount_cents` is `net_cents` plus `vat_cents` with no further rounding applied to the sum."
    PRD §3.7: "Otherwise, if `variance_cents` is exactly zero the outcome is `MATCH`."
    PRD §3.7: "A `MATCH` or a `WITHIN_TOLERANCE` moves the invoice from `RECEIVED` to `VALIDATED` and records no dispute."
    Design: Difficulty/combinatorial_formula/volume_tier_from_paid_invoices_only_at_tier1_boundary
    """
    scenario = _setup_author_pays_publisher_with_two_paid_invoices()
    received = receive_invoice(
        scenario["publisher"]["id"],
        scenario["articles"][2]["id"],
        "SELKIE-1003",
        238500,
        0.10,
        0.06,
        "2026-08-10",
    )

    response = api.validate_publisher_invoice(received["id"], LIBRARIAN)
    invoice = validate_success(response)

    assert invoice["entitled_discount_pct"] == pytest.approx(0.10, abs=0.01), (
        "prior paid net spend of exactly 500000 selects the ten percent tier, got "
        f"{invoice['entitled_discount_pct']}"
    )
    assert invoice["net_cents"] == 225000, (
        f"250000 less ten percent is 225000, got {invoice['net_cents']}"
    )
    assert invoice["vat_cents"] == 13500, (
        f"0.06 of 225000 is 13500, got {invoice['vat_cents']}"
    )
    assert invoice["expected_amount_cents"] == 238500, (
        f"225000 plus 13500 is 238500, got {invoice['expected_amount_cents']}"
    )
    assert invoice["expected_amount_cents"] != 265000, (
        "265000 would mean the boundary had been treated as exclusive, got "
        f"{invoice['expected_amount_cents']}"
    )
    assert invoice["variance_cents"] == 0, (
        f"the billed 238500 matches the expected amount, got {invoice['variance_cents']}"
    )
    assert invoice["validation_outcome"] == "MATCH", (
        f"a zero variance with the entitled discount claimed is a MATCH, got "
        f"{invoice['validation_outcome']!r}"
    )
    assert invoice["status"] == "VALIDATED", (
        f"a MATCH moves RECEIVED to VALIDATED, got {invoice['status']!r}"
    )
