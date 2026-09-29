"""Compensating transactions: releasing cash encumbrances and handing back an
agreement quota token.

Both scenarios take a side effect that has already been applied and reverse it
exactly, one on the fund ledgers and one on the non-monetary quota of a
transformative agreement.
"""

from test_helpers import (
    activate_agreement,
    add_coverage,
    create_publication_payload,
    create_withdrawal_payload,
    decide_request,
    draft_agreement,
    make_corresponding_author_headers,
    open_fund,
    open_fund_request,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    start_review,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# private preambles
# --------------------------------------------------------------------------- #
def _setup_approved_request_across_two_funds() -> dict:
    """A 460000 cent fund-route request approved across two eligible funds, with a
    third fund that the affiliation filter excludes from the waterfall."""
    set_clock("2026-08-05T00:00:00Z")
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=460000,
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
        grant_number="NRC-2026-601",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    department_fund = open_fund(
        fund_code="OA-DEPT-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=300000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=200000,
    )
    central_fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=1000000,
        priority_rank=2,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=250000,
    )
    graduate_fund = open_fund(
        fund_code="OA-GRAD-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=1000000,
        priority_rank=3,
        eligible_affiliation_statuses=["ELIGIBLE_GRAD"],
        per_article_cap_cents=250000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Waterfall compensation across two funds",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    request = open_fund_request(
        article["id"],
        author["id"],
        460000,
        justification="Full list APC of a fully OA venue.",
    )
    start_review(request["id"])
    approved = decide_request(request["id"], "APPROVE")
    return {
        "author": author,
        "article": article,
        "determination": determination,
        "department_fund": department_fund,
        "central_fund": central_fund,
        "graduate_fund": graduate_fund,
        "request": approved,
    }


def _setup_exhausted_agreement_holding_one_token() -> dict:
    """An agreement with a quota of one, exhausted by the single provisional
    determination that holds its only token, with the clock advanced past the end of
    the coverage window but still inside the agreement window."""
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
    add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-09-30",
    )
    activate_agreement(agreement["id"])
    article = record_article(
        journal["id"],
        author["id"],
        manuscript_title="Quota tokens are returned, not spent",
        accepted_on="2026-09-15",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    return {
        "publisher": publisher,
        "author": author,
        "agreement": agreement,
        "article": article,
        "determination": determination,
    }


# --------------------------------------------------------------------------- #
# releasing cash encumbrances on withdrawal
# --------------------------------------------------------------------------- #
def test_approval_waterfall_encumbers_two_funds_and_skips_the_ineligible_one(
    api, fund_manager_headers
):
    """The pre-withdrawal state that the compensation has to reverse: two encumbered
    lines totalling 450000 cents, with the graduate-only fund untouched.

    PRD §3.4: "If it qualifies, the `route` is `FUND_APC`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is likewise the whole `list_base_cents`, and `determination_reason` is `NO_COVERAGE_FUND_ELIGIBLE`."
    PRD §3.5: "The candidate funds are those whose `status` is `OPEN` — frozen funds are excluded outright — whose `fiscal_year` equals the fiscal year of the current clock date, whose period contains the clock date so that `period_from` is on or before it and `period_to` is on or after it, and whose `eligible_affiliation_statuses` list contains the author's `affiliation_status`."
    PRD §3.5: "Candidates are drawn in ascending `priority_rank`, with `created_at` ascending as the tie-break of last resort; ties cannot actually arise because a fiscal year admits each rank only once."
    PRD §3.5: "Otherwise the fund's own availability is computed as `total_budget_cents` less `committed_cents` less `spent_cents`, and the amount taken from this fund is the smallest of three quantities: the amount still to be filled, that availability, and the fund's `per_article_cap_cents`."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    PRD §3.5: "Otherwise `FundRequest.approved_cents` is set to that total, `FundRequest.author_share_cents` becomes `requested_cents` less the approved total, and `FundRequest.fully_funded` is true exactly when the approved total equals `requested_cents`."
    PRD §3.5: "The request moves from `UNDER_REVIEW` to `APPROVED`."
    Design: Difficulty/compensating_invariant/withdrawal_releases_encumbrances_restoring_fund_ledgers
    """
    scenario = _setup_approved_request_across_two_funds()

    assert scenario["determination"]["eligible_request_cents"] == 460000, (
        f"the whole 460000 cent list base is requestable on the FUND_APC route, "
        f"got {scenario['determination']['eligible_request_cents']}"
    )

    request = validate_success(
        api.get_fund_request(scenario["request"]["id"], fund_manager_headers)
    )
    assert request["approved_cents"] == 450000, (
        f"200000 from the first fund plus 250000 from the second is 450000, "
        f"got {request['approved_cents']}"
    )
    assert request["author_share_cents"] == 10000, (
        f"author_share_cents should be 460000 - 450000 = 10000, "
        f"got {request['author_share_cents']}"
    )
    assert request["fully_funded"] is False, (
        f"450000 falls short of the 460000 requested, so fully_funded is false, "
        f"got {request['fully_funded']}"
    )
    assert request["status"] == "APPROVED", (
        f"the request should sit in APPROVED, got {request['status']}"
    )

    rows, _meta = validate_paginated(
        api.list_fund_request_allocations(
            scenario["request"]["id"], fund_manager_headers
        )
    )
    assert len(rows) == 2, f"the waterfall should write exactly 2 lines, got {len(rows)}"
    assert rows[0]["sequence_index"] == 1, (
        f"the first line drawn carries sequence_index 1, got {rows[0]['sequence_index']}"
    )
    assert rows[0]["fund_id"] == scenario["department_fund"]["id"], (
        "priority_rank 1 is drawn first"
    )
    assert rows[0]["amount_cents"] == 200000, (
        f"the first fund contributes its 200000 cent per-article cap, "
        f"got {rows[0]['amount_cents']}"
    )
    assert rows[1]["sequence_index"] == 2, (
        f"the second line drawn carries sequence_index 2, got {rows[1]['sequence_index']}"
    )
    assert rows[1]["fund_id"] == scenario["central_fund"]["id"], (
        "priority_rank 2 is drawn second"
    )
    assert rows[1]["amount_cents"] == 250000, (
        f"the second fund contributes its 250000 cent per-article cap, "
        f"got {rows[1]['amount_cents']}"
    )

    graduate_rows, _graduate_meta = validate_paginated(
        api.list_fund_allocations(scenario["graduate_fund"]["id"], fund_manager_headers)
    )
    assert graduate_rows == [], (
        f"the graduate-only fund does not admit this author's affiliation status, so it "
        f"must never be drawn on, got {graduate_rows}"
    )


def test_withdrawing_an_approved_request_releases_every_encumbrance_and_restores_the_ledgers(
    api, fund_manager_headers
):
    """Withdrawal from `APPROVED` releases both lines and returns both funds and the
    author's committed figure to exactly their pre-approval values.

    PRD §3.5: "Withdrawing from `APPROVED` is a compensating transaction: every allocation line of the request whose `status` is `ENCUMBERED` becomes `RELEASED` with its `released_reason` set to the literal value `REQUEST_WITHDRAWN`, each affected fund's `committed_cents` and `available_cents` are recomputed so that the encumbered total returns to exactly its pre-approval value, the author's `apc_committed_cents` is recomputed, and the article's funding dimension returns to `ELIGIBILITY_CHECKED`."
    PRD §3.5: "Released lines are permanent: freezing a fund and releasing an encumbrance are both one-way, and a released line never counts towards utilisation on either basis."
    PRD §2.8: "Released lines never count towards utilisation under either basis."
    PRD §2.8: "`Author.apc_committed_cents` is the `ENCUMBRANCE_INCLUSIVE` figure for that author in the current fiscal year, and `Author.apc_disbursed_cents` is the `CASH_BASIS` figure for the same scope."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §3.3: "Freezing removes a fund from the waterfall permanently — `FROZEN` is terminal, and there is no path back to `OPEN`."
    Design: Difficulty/compensating_invariant/withdrawal_releases_encumbrances_restoring_fund_ledgers
    """
    scenario = _setup_approved_request_across_two_funds()

    withdrawn = validate_success(
        api.withdraw_fund_request(
            scenario["request"]["id"],
            create_withdrawal_payload("Author secured external payment."),
            make_corresponding_author_headers(scenario["author"]["id"]),
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"the request should move to WITHDRAWN, got {withdrawn['status']}"
    )

    rows, _meta = validate_paginated(
        api.list_fund_request_allocations(
            scenario["request"]["id"], fund_manager_headers
        )
    )
    assert len(rows) == 2, (
        f"released lines are permanent records, so 2 lines remain, got {len(rows)}"
    )
    for row in rows:
        assert row["status"] == "RELEASED", (
            f"every ENCUMBERED line becomes RELEASED, got {row['status']}"
        )
        assert row["released_reason"] == "REQUEST_WITHDRAWN", (
            f"released_reason must be the literal REQUEST_WITHDRAWN, "
            f"got {row['released_reason']!r}"
        )

    department_fund = validate_success(
        api.get_apc_fund(scenario["department_fund"]["id"], fund_manager_headers)
    )
    assert department_fund["committed_cents"] == 0, (
        f"the first fund's committed_cents returns to 0, "
        f"got {department_fund['committed_cents']}"
    )
    assert department_fund["spent_cents"] == 0, (
        f"nothing was ever disbursed, got {department_fund['spent_cents']}"
    )
    assert department_fund["available_cents"] == 300000, (
        f"available_cents returns to the whole 300000 cent budget, "
        f"got {department_fund['available_cents']}"
    )
    assert department_fund["status"] == "OPEN", (
        f"the first fund never crossed its freeze threshold, "
        f"got {department_fund['status']}"
    )

    central_fund = validate_success(
        api.get_apc_fund(scenario["central_fund"]["id"], fund_manager_headers)
    )
    assert central_fund["committed_cents"] == 0, (
        f"the second fund's committed_cents returns to 0, "
        f"got {central_fund['committed_cents']}"
    )
    assert central_fund["spent_cents"] == 0, (
        f"nothing was ever disbursed, got {central_fund['spent_cents']}"
    )
    assert central_fund["available_cents"] == 1000000, (
        f"available_cents returns to the whole 1000000 cent budget, "
        f"got {central_fund['available_cents']}"
    )

    graduate_fund = validate_success(
        api.get_apc_fund(scenario["graduate_fund"]["id"], fund_manager_headers)
    )
    assert graduate_fund["committed_cents"] == 0, (
        f"the never-drawn fund stays at 0, got {graduate_fund['committed_cents']}"
    )

    author = validate_success(
        api.get_author(scenario["author"]["id"], fund_manager_headers)
    )
    assert author["apc_committed_cents"] == 0, (
        f"released lines count towards no basis, so apc_committed_cents returns to 0, "
        f"got {author['apc_committed_cents']}"
    )
    assert author["apc_disbursed_cents"] == 0, (
        f"nothing was ever disbursed, got {author['apc_disbursed_cents']}"
    )

    article = validate_success(
        api.get_article(scenario["article"]["id"], fund_manager_headers)
    )
    assert article["funding_status"] == "ELIGIBILITY_CHECKED", (
        f"withdrawal returns the funding dimension to ELIGIBILITY_CHECKED, "
        f"got {article['funding_status']}"
    )


# --------------------------------------------------------------------------- #
# handing an agreement quota token back
# --------------------------------------------------------------------------- #
def test_provisional_determination_holds_the_only_quota_token_and_exhausts_the_agreement(
    api, agreement_admin_headers
):
    """The state that the compensation later reverses: a single provisional TA_FULL
    determination holds the agreement's only token, so the agreement is exhausted.

    PRD §3.2: "Each eligibility determination that selects an agreement holds one quota token on it, and the agreement's `articles_used` counts the tokens currently held."
    PRD §3.2: "When a determination is written and the recomputed `articles_used` reaches or exceeds `article_quota`, the agreement moves itself from `ACTIVE` to `EXHAUSTED`, which decreases the publisher's `active_agreement_count` by one and increments the publisher's `version` by one."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    PRD §3.4: "The `quota_position` is the number of tokens already held on that agreement plus one, making it a one-based index of where this article sits in the agreement's quota."
    PRD §2.10: "`TransformativeAgreement.articles_used` is the number of articles whose effective eligibility determination names this agreement and whose determination route is either `TA_FULL` or `TA_CAPPED`."
    Design: Difficulty/compensating_invariant/final_determination_returns_agreement_quota_token_to_zero
    """
    scenario = _setup_exhausted_agreement_holding_one_token()

    assert scenario["determination"]["route"] == "TA_FULL", (
        f"the provisional check falls inside the coverage window, so the route is "
        f"TA_FULL, got {scenario['determination']['route']}"
    )
    assert scenario["determination"]["quota_position"] == 1, (
        f"this article takes the agreement's first quota position, "
        f"got {scenario['determination']['quota_position']}"
    )

    agreement = validate_success(
        api.get_transformative_agreement(
            scenario["agreement"]["id"], agreement_admin_headers
        )
    )
    assert agreement["articles_used"] == 1, (
        f"one token is held on the agreement, got {agreement['articles_used']}"
    )
    assert agreement["status"] == "EXHAUSTED", (
        f"articles_used has reached the quota of 1, so the agreement is EXHAUSTED, "
        f"got {agreement['status']}"
    )


def test_final_determination_at_publication_returns_the_quota_token_and_reactivates_the_agreement(
    api, librarian_headers, agreement_admin_headers, fund_manager_headers
):
    """Publishing outside the coverage window makes the provisional TA_FULL row
    non-effective, which hands the token back and revives the agreement — while the
    superseded row itself is left exactly as written.

    PRD §3.6: "The third effect is the one with the widest reach: publication automatically runs a further coverage determination on the `FINAL` basis, exactly as described in §3.4 but with `reference_date` taken from the `publication_date` just set, with `list_base_cents` preferring the article's own `apc_list_cents` when it has one, and with the chronological quota gate that counts only committed tokens."
    PRD §3.6: "Because a new determination has become effective, `articles_used` is recomputed on the agreement the previous determination had selected, releasing its quota token, and on whichever agreement the final determination selects."
    PRD §3.6: "An agreement sitting in `EXHAUSTED` whose recomputed `articles_used` has fallen below its `article_quota` moves back to `ACTIVE`, provided the clock date is still strictly before its `effective_until`; the publisher's `active_agreement_count` is recomputed and the publisher's `version` is incremented by one whenever an agreement's status changes this way."
    PRD §3.2: "When a token is released — because a later determination for that article stopped the earlier one being effective — the recomputed `articles_used` may fall back below `article_quota`, and if the clock date is still strictly before the agreement's `effective_until` the agreement moves itself from `EXHAUSTED` back to `ACTIVE`, increasing the publisher's `active_agreement_count` by one and again incrementing the publisher's `version` by one."
    PRD §3.4: "An agreement is a candidate when all of the following hold: it belongs to the publisher of the article's journal; its `status` is either `ACTIVE` or `EXHAUSTED`, which means `DRAFT` and `EXPIRED` agreements are never candidates; the `reference_date` falls inside its half-open window, being on or after `effective_from` and strictly before `effective_until`; the journal's `oa_model` appears in the agreement's `covered_oa_models`; the agreement passes its quota gate; and the agreement has a coverage line for exactly this journal whose `coverage_type` is `FULL_APC` or `CAPPED_APC` — a `READ_ONLY` line never funds anything — and whose closed window contains the `reference_date`, being on or after `covered_from` and on or before `covered_until`."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.4: "**The effective determination of an article is the row with the highest `sequence_no`**; every earlier row remains readable but stops being effective."
    PRD §2.4: "A coverage line, once added to an agreement, is a fixed statement of what that agreement pays for that journal over that window; a determination, once written, is a permanent record of what the office decided on a particular date, and it is superseded by writing a further determination rather than by editing the existing one."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    PRD §2.10: "`Publisher.active_agreement_count` is the number of that publisher's transformative agreements whose `status` is `ACTIVE`."
    PRD §3.3: "A newly registered author has zero `apc_committed_cents`, zero `apc_disbursed_cents` and zero `linked_output_count`."
    Design: Difficulty/compensating_invariant/final_determination_returns_agreement_quota_token_to_zero
    """
    scenario = _setup_exhausted_agreement_holding_one_token()
    set_clock("2026-11-20T00:00:00Z")

    article = validate_success(
        api.publish_article(
            scenario["article"]["id"],
            create_publication_payload("2026-11-20"),
            librarian_headers,
        )
    )

    assert article["eligibility_route"] == "AUTHOR_PAYS", (
        f"the final reference date of 2026-11-20 falls outside the coverage window, so "
        f"the route becomes AUTHOR_PAYS, got {article['eligibility_route']}"
    )
    assert article["determination_count"] == 2, (
        f"publication appends a second determination, got {article['determination_count']}"
    )

    agreement = validate_success(
        api.get_transformative_agreement(
            scenario["agreement"]["id"], agreement_admin_headers
        )
    )
    assert agreement["articles_used"] == 0, (
        f"the released token leaves no effective TA-route determination on the "
        f"agreement, got {agreement['articles_used']}"
    )
    assert agreement["status"] == "ACTIVE", (
        f"articles_used has fallen below the quota while the clock is still before "
        f"2026-12-01, so the agreement returns to ACTIVE, got {agreement['status']}"
    )

    publisher = validate_success(
        api.get_publisher(scenario["publisher"]["id"], agreement_admin_headers)
    )
    assert publisher["active_agreement_count"] == 1, (
        f"the revived agreement is counted as active again, "
        f"got {publisher['active_agreement_count']}"
    )

    rows, _meta = validate_paginated(
        api.list_eligibility_determinations(
            librarian_headers, params={"agreement_id": scenario["agreement"]["id"]}
        )
    )
    assert len(rows) == 1, (
        f"only the retained provisional row still names the agreement, got {len(rows)}"
    )
    assert rows[0]["id"] == scenario["determination"]["id"], (
        "the retained row must be the original provisional determination"
    )
    assert rows[0]["quota_position"] == 1, (
        f"the superseded row keeps its quota_position of 1, got {rows[0]['quota_position']}"
    )
    assert rows[0]["route"] == "TA_FULL", (
        f"the compensating path never rewrites the superseded row, got {rows[0]['route']}"
    )

    invoice_rows, _invoice_meta = validate_paginated(
        api.list_publisher_invoices(librarian_headers)
    )
    assert invoice_rows == [], (
        f"the quota token is non-monetary: no invoice exists anywhere, got {invoice_rows}"
    )

    author = validate_success(
        api.get_author(scenario["author"]["id"], fund_manager_headers)
    )
    assert author["apc_committed_cents"] == 0, (
        f"no institutional money was ever committed, got {author['apc_committed_cents']}"
    )
    assert author["apc_disbursed_cents"] == 0, (
        f"no institutional money was ever disbursed, got {author['apc_disbursed_cents']}"
    )
