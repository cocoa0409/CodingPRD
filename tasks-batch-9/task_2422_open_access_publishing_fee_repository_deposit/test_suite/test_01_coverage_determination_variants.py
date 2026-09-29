"""Two-variant calculations: the coverage determination under PROVISIONAL versus
FINAL, and fund utilisation under the encumbrance versus the cash basis.

Both scenarios keep the stored rows identical and change only which variant of
the rule is run, so any divergence in the reported figures is attributable to the
variant alone.
"""

from test_helpers import (
    TEST_USERS,
    activate_agreement,
    add_coverage,
    create_eligibility_check_payload,
    decide_request,
    draft_agreement,
    get_annual_spend,
    list_determinations,
    list_request_allocations,
    open_fund,
    open_fund_request,
    publish_article,
    read_author,
    read_fund,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    start_review,
    validate_success,
)

LIBRARIAN = TEST_USERS["librarian_headers"]


# --------------------------------------------------------------------------- #
# preambles
# --------------------------------------------------------------------------- #
def _setup_hybrid_agreement_article() -> dict:
    """A HYBRID article accepted 2026-09-15 at a journal covered by an ACTIVE
    agreement whose single coverage line closes on 2026-09-30, with the logical
    clock at 2026-09-20."""
    set_clock("2026-09-20T00:00:00Z")
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    journal = register_journal(
        publisher["id"],
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Ines Ravel",
        email="ines.ravel@uni.example",
        orcid="0000-0002-1825-0097",
        department_code="BIO",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2026-12-01",
        article_quota=1,
        discount_pct=0.25,
        covered_oa_models=["HYBRID"],
    )
    coverage = add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-09-30",
    )
    agreement = activate_agreement(agreement["id"])
    article = record_article(
        journal["id"],
        author["id"],
        manuscript_title="Calcium gating in hepatic stellate cells",
        accepted_on="2026-09-15",
    )
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "agreement": agreement,
        "coverage": coverage,
        "article": article,
    }


def _setup_encumbered_allocation() -> dict:
    """A FUND_APC article whose 300000-cent request has been approved, leaving one
    ENCUMBERED allocation line and nothing DISBURSED (no invoice is raised)."""
    set_clock("2026-08-05T00:00:00Z")
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    funder = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-118",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=1000000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=300000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Flux balance under nitrogen limitation",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    request = open_fund_request(article["id"], author["id"], 300000)
    start_review(request["id"])
    request = decide_request(request["id"], "APPROVE")
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "funder": funder,
        "grant": grant,
        "fund": fund,
        "article": article,
        "determination": determination,
        "request": request,
    }


# --------------------------------------------------------------------------- #
# PROVISIONAL versus FINAL coverage determination
# --------------------------------------------------------------------------- #
def test_provisional_determination_dates_coverage_at_acceptance_and_covers_in_full(api):
    """The PROVISIONAL variant tests the windows against the article's accepted_on,
    which still sits inside the coverage line's closed window, so the article is
    covered in full at the negotiated discount.

    PRD §3.4: "First, the `reference_date` is fixed: under the `PROVISIONAL` variant it is the article's `accepted_on`; under the `FINAL` variant it is the article's `publication_date` when one has been set, and otherwise the current clock date."
    PRD §3.4: "Second, the base charge `list_base_cents` is fixed: under the `FINAL` variant, if the article carries an `apc_list_cents` value it is used, and otherwise the journal's `list_apc_cents` is used; under the `PROVISIONAL` variant the journal's `list_apc_cents` is always used, even when the article carries a quoted figure."
    PRD §3.4: "The `discount_pct_applied` is that agreement's `discount_pct`, and the discounted price is `list_base_cents` multiplied by one minus the discount, rounded half up to whole cents — this is the only rounding step in the whole determination."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    Design: Difficulty/dual_variant_calc/provisional_ta_full_vs_final_author_pays_coverage_window
    """
    scenario = _setup_hybrid_agreement_article()

    response = api.create_eligibility_check(
        scenario["article"]["id"],
        create_eligibility_check_payload("PROVISIONAL"),
        LIBRARIAN,
    )
    determination = validate_success(response, expected_status=201)

    assert determination["basis"] == "PROVISIONAL", (
        f"the requested basis must be recorded on the row, got {determination['basis']!r}"
    )
    assert determination["reference_date"] == "2026-09-15", (
        "the PROVISIONAL reference_date is the article's accepted_on, got "
        f"{determination['reference_date']!r}"
    )
    assert determination["route"] == "TA_FULL", (
        "a FULL_APC coverage line whose window contains 2026-09-15 gives route "
        f"TA_FULL, got {determination['route']!r}"
    )
    assert determination["list_base_cents"] == 380000, (
        "the PROVISIONAL base is the journal's list_apc_cents 380000, got "
        f"{determination['list_base_cents']}"
    )
    assert determination["covered_amount_cents"] == 285000, (
        "380000 at a 0.25 discount is 285000 covered cents, got "
        f"{determination['covered_amount_cents']}"
    )
    assert determination["author_share_cents"] == 0, (
        f"TA_FULL leaves the author nothing to pay, got {determination['author_share_cents']}"
    )
    assert determination["determination_reason"] == "TA_FULL_COVERAGE", (
        f"expected reason TA_FULL_COVERAGE, got {determination['determination_reason']!r}"
    )


def test_final_determination_at_publication_reroutes_to_author_pays_outside_window(api):
    """Publication re-runs the determination on the FINAL basis with the
    reference_date taken from the publication date, which now falls outside the
    coverage line's closed window: the identical data yields AUTHOR_PAYS with no
    covered amount, and the earlier PROVISIONAL row is left intact.

    PRD §3.4: "First, the `reference_date` is fixed: under the `PROVISIONAL` variant it is the article's `accepted_on`; under the `FINAL` variant it is the article's `publication_date` when one has been set, and otherwise the current clock date."
    PRD §3.4: "An agreement is a candidate when all of the following hold: it belongs to the publisher of the article's journal; its `status` is either `ACTIVE` or `EXHAUSTED`, which means `DRAFT` and `EXPIRED` agreements are never candidates; the `reference_date` falls inside its half-open window, being on or after `effective_from` and strictly before `effective_until`; the journal's `oa_model` appears in the agreement's `covered_oa_models`; the agreement passes its quota gate; and the agreement has a coverage line for exactly this journal whose `coverage_type` is `FULL_APC` or `CAPPED_APC` — a `READ_ONLY` line never funds anything — and whose closed window contains the `reference_date`, being on or after `covered_from` and on or before `covered_until`."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.4: "When no candidate exists, `discount_pct_applied` is 0 and `quota_position` is absent, and the choice turns entirely on whether the article qualifies for the institutional-fund route."
    PRD §3.6: "The third effect is the one with the widest reach: publication automatically runs a further coverage determination on the `FINAL` basis, exactly as described in §3.4 but with `reference_date` taken from the `publication_date` just set, with `list_base_cents` preferring the article's own `apc_list_cents` when it has one, and with the chronological quota gate that counts only committed tokens."
    PRD §3.6: "An article that was `FUNDED` but whose final determination routes to `AUTHOR_PAYS` moves from `FUNDED` to `SELF_FUNDED`."
    PRD §3.4: "**The effective determination of an article is the row with the highest `sequence_no`**; every earlier row remains readable but stops being effective."
    Design: Difficulty/dual_variant_calc/provisional_ta_full_vs_final_author_pays_coverage_window
    """
    scenario = _setup_hybrid_agreement_article()
    article_id = scenario["article"]["id"]
    run_eligibility_check(article_id, basis="PROVISIONAL")

    set_clock("2026-11-20T00:00:00Z")
    published = publish_article(article_id, "2026-11-20")

    assert published["eligibility_route"] == "AUTHOR_PAYS", (
        "the FINAL reference_date 2026-11-20 lies outside the coverage window, so "
        f"the route is AUTHOR_PAYS, got {published['eligibility_route']!r}"
    )
    assert published["covered_amount_cents"] == 0, (
        f"an AUTHOR_PAYS route covers nothing, got {published['covered_amount_cents']}"
    )
    assert published["author_share_cents"] == 380000, (
        "the author now carries the whole list base 380000, got "
        f"{published['author_share_cents']}"
    )
    assert published["funding_status"] == "SELF_FUNDED", (
        "FUNDED must fall back to SELF_FUNDED when the final determination routes "
        f"to AUTHOR_PAYS, got {published['funding_status']!r}"
    )
    assert published["publication_date"] == "2026-11-20", (
        f"the supplied publication_date must be stored, got {published['publication_date']!r}"
    )
    assert published["determination_count"] == 2, (
        "the FINAL determination is appended as a second row, got "
        f"{published['determination_count']}"
    )

    rows = list_determinations({"article_id": article_id})
    assert len(rows) == 2, f"expected exactly 2 determination rows, got {len(rows)}"
    by_sequence = {row["sequence_no"]: row for row in rows}

    final_row = by_sequence[2]
    assert final_row["basis"] == "FINAL", (
        f"the publication determination runs on the FINAL basis, got {final_row['basis']!r}"
    )
    assert final_row["reference_date"] == "2026-11-20", (
        "the FINAL reference_date is the publication_date, got "
        f"{final_row['reference_date']!r}"
    )
    assert final_row["route"] == "AUTHOR_PAYS", (
        f"expected route AUTHOR_PAYS on sequence_no 2, got {final_row['route']!r}"
    )
    assert final_row["list_base_cents"] == 380000, (
        f"expected list_base_cents 380000, got {final_row['list_base_cents']}"
    )
    assert final_row["covered_amount_cents"] == 0, (
        f"expected covered_amount_cents 0, got {final_row['covered_amount_cents']}"
    )
    assert final_row["author_share_cents"] == 380000, (
        f"expected author_share_cents 380000, got {final_row['author_share_cents']}"
    )
    assert final_row["determination_reason"] == "NO_COVERAGE_AUTHOR_PAYS", (
        f"expected NO_COVERAGE_AUTHOR_PAYS, got {final_row['determination_reason']!r}"
    )
    assert final_row.get("quota_position") is None, (
        "no candidate agreement means quota_position is absent, got "
        f"{final_row.get('quota_position')!r}"
    )

    provisional_row = by_sequence[1]
    assert provisional_row["basis"] == "PROVISIONAL", (
        "the append-only PROVISIONAL row is never rewritten, got basis "
        f"{provisional_row['basis']!r}"
    )
    assert provisional_row["route"] == "TA_FULL", (
        f"the PROVISIONAL row keeps route TA_FULL, got {provisional_row['route']!r}"
    )
    assert provisional_row["covered_amount_cents"] == 285000, (
        "the PROVISIONAL row keeps covered_amount_cents 285000, got "
        f"{provisional_row['covered_amount_cents']}"
    )


# --------------------------------------------------------------------------- #
# ENCUMBRANCE versus CASH utilisation basis
# --------------------------------------------------------------------------- #
def test_encumbrance_basis_counts_the_promised_allocation_as_utilised():
    """On the encumbrance basis a promised-but-unpaid allocation line already
    consumes the allowance, so the report's headline total carries the encumbered
    300000 cents and the author's committed figure matches.

    PRD §2.8: "Under the `ENCUMBRANCE_INCLUSIVE` variant, utilisation is the sum of `amount_cents` over lines whose status is `ENCUMBERED` or `DISBURSED`, so money promised but not yet paid already consumes the author's allowance."
    PRD §2.8: "`Author.apc_committed_cents` is the `ENCUMBRANCE_INCLUSIVE` figure for that author in the current fiscal year, and `Author.apc_disbursed_cents` is the `CASH_BASIS` figure for the same scope."
    PRD §3.9: "From the allocation ledger, the report takes every allocation line whose fund carries the requested `fiscal_year`: `total_committed_cents` is the sum of `amount_cents` over lines whose status is `ENCUMBERED`, and `total_disbursed_cents` is the same sum over lines whose status is `DISBURSED`; released lines are excluded from both."
    PRD §3.9: "The headline `total_allocated_cents` then depends on the `basis`: on the encumbrance basis it is `total_committed_cents` plus `total_disbursed_cents`, and on the cash basis it is `total_disbursed_cents` alone."
    PRD §3.4: "If it qualifies, the `route` is `FUND_APC`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is likewise the whole `list_base_cents`, and `determination_reason` is `NO_COVERAGE_FUND_ELIGIBLE`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    Design: Difficulty/dual_variant_calc/encumbrance_vs_cash_basis_fund_utilisation_divergence
    """
    scenario = _setup_encumbered_allocation()

    assert scenario["determination"]["route"] == "FUND_APC", (
        "a FULLY_OA journal under an active GOLD_OA grant routes to FUND_APC, got "
        f"{scenario['determination']['route']!r}"
    )
    assert scenario["determination"]["eligible_request_cents"] == 300000, (
        "the whole list base is requestable on the FUND_APC route, got "
        f"{scenario['determination']['eligible_request_cents']}"
    )
    assert scenario["request"]["approved_cents"] == 300000, (
        f"the waterfall should approve 300000, got {scenario['request']['approved_cents']}"
    )

    report = get_annual_spend(2027, basis="ENCUMBRANCE")
    assert report["total_allocated_cents"] == 300000, (
        "on the encumbrance basis total_allocated_cents is committed plus disbursed, "
        f"expected 300000, got {report['total_allocated_cents']}"
    )
    assert report["total_committed_cents"] == 300000, (
        f"expected total_committed_cents 300000, got {report['total_committed_cents']}"
    )
    assert report["total_disbursed_cents"] == 0, (
        "nothing has been paid, so total_disbursed_cents is 0, got "
        f"{report['total_disbursed_cents']}"
    )

    fund = read_fund(scenario["fund"]["id"])
    assert fund["committed_cents"] == 300000, (
        f"the fund should carry 300000 committed cents, got {fund['committed_cents']}"
    )
    assert fund["spent_cents"] == 0, (
        f"no money has left the institution, got spent_cents {fund['spent_cents']}"
    )
    assert fund["available_cents"] == 700000, (
        f"1000000 less 300000 committed is 700000 available, got {fund['available_cents']}"
    )
    assert fund["status"] == "OPEN", (
        f"300000 is far below the 98 percent freeze threshold, got {fund['status']!r}"
    )

    author = read_author(scenario["author"]["id"])
    assert author["apc_committed_cents"] == 300000, (
        "apc_committed_cents is the ENCUMBRANCE_INCLUSIVE figure, expected 300000, got "
        f"{author['apc_committed_cents']}"
    )
    assert author["apc_disbursed_cents"] == 0, (
        "apc_disbursed_cents is the CASH_BASIS figure, expected 0, got "
        f"{author['apc_disbursed_cents']}"
    )

    allocations = list_request_allocations(scenario["request"]["id"])
    assert len(allocations) == 1, f"expected exactly 1 allocation line, got {len(allocations)}"
    assert allocations[0]["amount_cents"] == 300000, (
        f"expected amount_cents 300000, got {allocations[0]['amount_cents']}"
    )
    assert allocations[0]["sequence_index"] == 1, (
        f"expected sequence_index 1, got {allocations[0]['sequence_index']}"
    )
    assert allocations[0]["status"] == "ENCUMBERED", (
        f"a fresh allocation line is ENCUMBERED, got {allocations[0]['status']!r}"
    )


def test_cash_basis_reports_zero_allocated_against_the_same_encumbered_ledger():
    """Run against the identical ledger, the cash basis drops the encumbered line
    from the headline figure altogether: total_allocated_cents falls to zero while
    total_committed_cents still reports the promise — a 300000-cent divergence.

    PRD §2.8: "Under the `CASH_BASIS` variant, utilisation is the sum of `amount_cents` over lines whose status is `DISBURSED` only, so the identical ledger reports a strictly smaller — and frequently zero — figure."
    PRD §2.8: "The annual spend report exposes the choice to the caller through its `basis` query parameter, where the value `ENCUMBRANCE` selects the `ENCUMBRANCE_INCLUSIVE` variant and is the default when the parameter is omitted, and the value `CASH` selects the `CASH_BASIS` variant."
    PRD §3.9: "The headline `total_allocated_cents` then depends on the `basis`: on the encumbrance basis it is `total_committed_cents` plus `total_disbursed_cents`, and on the cash basis it is `total_disbursed_cents` alone."
    PRD §3.9: "From the allocation ledger, the report takes every allocation line whose fund carries the requested `fiscal_year`: `total_committed_cents` is the sum of `amount_cents` over lines whose status is `ENCUMBERED`, and `total_disbursed_cents` is the same sum over lines whose status is `DISBURSED`; released lines are excluded from both."
    Design: Difficulty/dual_variant_calc/encumbrance_vs_cash_basis_fund_utilisation_divergence
    """
    _setup_encumbered_allocation()

    encumbrance = get_annual_spend(2027, basis="ENCUMBRANCE")
    cash = get_annual_spend(2027, basis="CASH")

    assert cash["total_allocated_cents"] == 0, (
        "on the cash basis total_allocated_cents is the disbursed sum alone, "
        f"expected 0, got {cash['total_allocated_cents']}"
    )
    assert cash["total_committed_cents"] == 300000, (
        "the committed figure is basis-independent, expected 300000, got "
        f"{cash['total_committed_cents']}"
    )
    assert cash["total_disbursed_cents"] == 0, (
        f"expected total_disbursed_cents 0, got {cash['total_disbursed_cents']}"
    )
    assert encumbrance["total_allocated_cents"] - cash["total_allocated_cents"] == 300000, (
        "the two bases must diverge by the encumbered 300000 cents, got "
        f"{encumbrance['total_allocated_cents']} versus {cash['total_allocated_cents']}"
    )
