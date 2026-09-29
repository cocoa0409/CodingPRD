"""Decisions that turn entirely on another entity's state.

In both scenarios the request under test is structurally identical across the two
calls; only the state of the agreement, or of the APC fund, has moved in between.
"""

from test_helpers import (
    ApiErrorId,
    create_decision_payload,
    create_eligibility_check_payload,
    create_freeze_payload,
    add_coverage,
    draft_agreement,
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
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# private preambles
# --------------------------------------------------------------------------- #
def _setup_article_under_a_drafted_agreement() -> dict:
    """A hybrid journal article whose publisher already carries a fully drafted —
    but not yet activated — agreement with a matching coverage line."""
    set_clock("2026-08-05T00:00:00Z")
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
        effective_until="2027-07-01",
        article_quota=3,
        discount_pct=0.25,
        covered_oa_models=["HYBRID"],
    )
    coverage = add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2027-06-30",
    )
    article = record_article(
        journal["id"],
        author["id"],
        manuscript_title="Draft agreements do not fund articles",
        accepted_on="2026-08-05",
    )
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "agreement": agreement,
        "coverage": coverage,
        "article": article,
    }


def _setup_two_requests_under_review_on_one_fund() -> dict:
    """Two fund-route articles by two eligible faculty authors, each with a request
    for 300000 cents taken into review, drawing on a single open fund."""
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
    first_author = register_author(
        full_name="Ada Kerr",
        email="ada.kerr@uni.example",
        orcid="0000-0006-5555-6666",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    second_author = register_author(
        full_name="Ben Oyelaran",
        email="ben.oyelaran@uni.example",
        orcid="0000-0006-7777-8888",
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
    first_grant = record_grant(
        funder["id"],
        first_author["id"],
        grant_number="NRC-2026-501",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    second_grant = record_grant(
        funder["id"],
        second_author["id"],
        grant_number="NRC-2026-502",
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
    first_article = record_article(
        journal["id"],
        first_author["id"],
        grant_id=first_grant["id"],
        manuscript_title="First claim on the open fund",
        accepted_on="2026-08-05",
    )
    second_article = record_article(
        journal["id"],
        second_author["id"],
        grant_id=second_grant["id"],
        manuscript_title="Second claim after the freeze",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(first_article["id"], basis="PROVISIONAL")
    run_eligibility_check(second_article["id"], basis="PROVISIONAL")
    first_request = open_fund_request(
        first_article["id"],
        first_author["id"],
        300000,
        justification="Gold OA fee, first author.",
    )
    second_request = open_fund_request(
        second_article["id"],
        second_author["id"],
        300000,
        justification="Gold OA fee, second author.",
    )
    start_review(first_request["id"])
    start_review(second_request["id"])
    return {
        "fund": fund,
        "first_article": first_article,
        "second_article": second_article,
        "first_request": first_request,
        "second_request": second_request,
    }


# --------------------------------------------------------------------------- #
# the eligibility route depends on the agreement's status
# --------------------------------------------------------------------------- #
def test_eligibility_check_routes_to_author_pays_while_the_agreement_is_still_draft(
    api, librarian_headers
):
    """A drafted agreement with a matching coverage line is never a candidate, so
    the check concludes that the author pays.

    PRD §3.4: "Fourth, the candidate agreements are assembled."
    PRD §3.4: "An agreement is a candidate when all of the following hold: it belongs to the publisher of the article's journal; its `status` is either `ACTIVE` or `EXHAUSTED`, which means `DRAFT` and `EXPIRED` agreements are never candidates; the `reference_date` falls inside its half-open window, being on or after `effective_from` and strictly before `effective_until`; the journal's `oa_model` appears in the agreement's `covered_oa_models`; the agreement passes its quota gate; and the agreement has a coverage line for exactly this journal whose `coverage_type` is `FULL_APC` or `CAPPED_APC` — a `READ_ONLY` line never funds anything — and whose closed window contains the `reference_date`, being on or after `covered_from` and on or before `covered_until`."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.4: "The row that is written carries the `article_id`, a per-article one-based `sequence_no` equal to the article's `determination_count` plus one, the `basis` used, the `reference_date` the windows were tested against, the `route` chosen, the `agreement_id` and `coverage_id` of whatever was matched, the `list_base_cents` the pricing worked from, the `discount_pct_applied`, the `covered_amount_cents`, the `author_share_cents`, the `eligible_request_cents`, a pinned `determination_reason` code, and a `quota_position`."
    PRD §3.4: "The funding dimension then follows the route: a `TA_FULL` route sets `funding_status` to `FUNDED`; a `TA_CAPPED` route sets it to `ELIGIBILITY_CHECKED` when `eligible_request_cents` is greater than zero and to `SELF_FUNDED` when `eligible_request_cents` is zero; a `FUND_APC` route sets it to `ELIGIBILITY_CHECKED`; an `AUTHOR_PAYS` route sets it to `SELF_FUNDED`."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    Design: Difficulty/cross_entity_state_dependency/eligibility_route_depends_on_agreement_draft_versus_active
    """
    scenario = _setup_article_under_a_drafted_agreement()

    assert scenario["agreement"]["status"] == "DRAFT", (
        f"the agreement must still be DRAFT for this scenario, "
        f"got {scenario['agreement']['status']}"
    )

    determination = validate_success(
        api.create_eligibility_check(
            scenario["article"]["id"],
            create_eligibility_check_payload("PROVISIONAL"),
            librarian_headers,
        ),
        expected_status=201,
    )

    assert determination["route"] == "AUTHOR_PAYS", (
        f"a DRAFT agreement is never a candidate, so the route must be AUTHOR_PAYS, "
        f"got {determination['route']}"
    )
    assert determination["covered_amount_cents"] == 0, (
        f"an AUTHOR_PAYS determination covers nothing, "
        f"got {determination['covered_amount_cents']}"
    )
    assert determination.get("agreement_id") is None, (
        f"no agreement was matched, so agreement_id must be absent, "
        f"got {determination.get('agreement_id')!r}"
    )
    assert determination["determination_reason"] == "NO_COVERAGE_AUTHOR_PAYS", (
        f"the pinned reason for an uncovered author-pays article is "
        f"NO_COVERAGE_AUTHOR_PAYS, got {determination['determination_reason']}"
    )

    article = validate_success(
        api.get_article(scenario["article"]["id"], librarian_headers)
    )
    assert article["funding_status"] == "SELF_FUNDED", (
        f"an AUTHOR_PAYS route sets funding_status to SELF_FUNDED, "
        f"got {article['funding_status']}"
    )


def test_eligibility_check_routes_to_ta_full_once_the_same_agreement_is_activated(
    api, librarian_headers, agreement_admin_headers
):
    """Activating the agreement — and nothing else — turns the identical re-check
    into full agreement cover at the discounted price.

    PRD §3.2: "Activation by an `AgreementAdmin` moves the agreement from `DRAFT` to `ACTIVE`."
    PRD §3.4: "An agreement is a candidate when all of the following hold: it belongs to the publisher of the article's journal; its `status` is either `ACTIVE` or `EXHAUSTED`, which means `DRAFT` and `EXPIRED` agreements are never candidates; the `reference_date` falls inside its half-open window, being on or after `effective_from` and strictly before `effective_until`; the journal's `oa_model` appears in the agreement's `covered_oa_models`; the agreement passes its quota gate; and the agreement has a coverage line for exactly this journal whose `coverage_type` is `FULL_APC` or `CAPPED_APC` — a `READ_ONLY` line never funds anything — and whose closed window contains the `reference_date`, being on or after `covered_from` and on or before `covered_until`."
    PRD §3.4: "The `discount_pct_applied` is that agreement's `discount_pct`, and the discounted price is `list_base_cents` multiplied by one minus the discount, rounded half up to whole cents — this is the only rounding step in the whole determination."
    PRD §3.4: "The `quota_position` is the number of tokens already held on that agreement plus one, making it a one-based index of where this article sits in the agreement's quota."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    PRD §3.4: "The determination is inserted, `Article.determination_count` rises by one, and the article's own `eligibility_route`, `covered_amount_cents` and `author_share_cents` are refreshed from the newly effective row."
    PRD §3.4: "The funding dimension then follows the route: a `TA_FULL` route sets `funding_status` to `FUNDED`; a `TA_CAPPED` route sets it to `ELIGIBILITY_CHECKED` when `eligible_request_cents` is greater than zero and to `SELF_FUNDED` when `eligible_request_cents` is zero; a `FUND_APC` route sets it to `ELIGIBILITY_CHECKED`; an `AUTHOR_PAYS` route sets it to `SELF_FUNDED`."
    PRD §2.10: "`TransformativeAgreement.articles_used` is the number of articles whose effective eligibility determination names this agreement and whose determination route is either `TA_FULL` or `TA_CAPPED`."
    PRD §3.2: "When a determination is written and the recomputed `articles_used` reaches or exceeds `article_quota`, the agreement moves itself from `ACTIVE` to `EXHAUSTED`, which decreases the publisher's `active_agreement_count` by one and increments the publisher's `version` by one."
    Design: Difficulty/cross_entity_state_dependency/eligibility_route_depends_on_agreement_draft_versus_active
    """
    scenario = _setup_article_under_a_drafted_agreement()
    run_eligibility_check(scenario["article"]["id"], basis="PROVISIONAL")

    activated = validate_success(
        api.activate_transformative_agreement(
            scenario["agreement"]["id"], agreement_admin_headers
        )
    )
    assert activated["status"] == "ACTIVE", (
        f"activation moves the agreement to ACTIVE, got {activated['status']}"
    )

    determination = validate_success(
        api.create_eligibility_check(
            scenario["article"]["id"],
            create_eligibility_check_payload("PROVISIONAL"),
            librarian_headers,
        ),
        expected_status=201,
    )

    assert determination["route"] == "TA_FULL", (
        f"an ACTIVE agreement with a FULL_APC line for this journal routes to TA_FULL, "
        f"got {determination['route']}"
    )
    assert determination["covered_amount_cents"] == 285000, (
        f"the discounted price of 380000 at 0.25 is 285000, "
        f"got {determination['covered_amount_cents']}"
    )
    assert determination["author_share_cents"] == 0, (
        f"full agreement cover leaves the author nothing to pay, "
        f"got {determination['author_share_cents']}"
    )
    assert determination["agreement_id"] == scenario["agreement"]["id"], (
        "the determination must name the agreement that was matched"
    )
    assert determination["coverage_id"] == scenario["coverage"]["id"], (
        "the determination must name the coverage line that was matched"
    )
    assert determination["quota_position"] == 1, (
        f"no token was held before this determination, so quota_position is 1, "
        f"got {determination['quota_position']}"
    )
    assert determination["sequence_no"] == 2, (
        f"this is the article's second determination, so sequence_no is 2, "
        f"got {determination['sequence_no']}"
    )

    article = validate_success(
        api.get_article(scenario["article"]["id"], librarian_headers)
    )
    assert article["determination_count"] == 2, (
        f"determination_count should be 2, got {article['determination_count']}"
    )
    assert article["funding_status"] == "FUNDED", (
        f"a TA_FULL route sets funding_status to FUNDED, got {article['funding_status']}"
    )
    assert article["covered_amount_cents"] == 285000, (
        f"the article's covered_amount_cents is refreshed from the newly effective row, "
        f"got {article['covered_amount_cents']}"
    )

    agreement = validate_success(
        api.get_transformative_agreement(
            scenario["agreement"]["id"], agreement_admin_headers
        )
    )
    assert agreement["articles_used"] == 1, (
        f"exactly one effective TA-route determination names the agreement, "
        f"got {agreement['articles_used']}"
    )
    assert agreement["status"] == "ACTIVE", (
        f"one token of a quota of three keeps the agreement ACTIVE, "
        f"got {agreement['status']}"
    )


# --------------------------------------------------------------------------- #
# the funding decision depends on the fund's status
# --------------------------------------------------------------------------- #
def test_fund_request_approval_against_an_open_fund_encumbers_and_funds_the_article(
    api, fund_manager_headers
):
    """While the fund is OPEN it is a waterfall candidate, so the approval fills the
    whole request.

    PRD §3.5: "The candidate funds are those whose `status` is `OPEN` — frozen funds are excluded outright — whose `fiscal_year` equals the fiscal year of the current clock date, whose period contains the clock date so that `period_from` is on or before it and `period_to` is on or after it, and whose `eligible_affiliation_statuses` list contains the author's `affiliation_status`."
    PRD §3.5: "Otherwise the fund's own availability is computed as `total_budget_cents` less `committed_cents` less `spent_cents`, and the amount taken from this fund is the smallest of three quantities: the amount still to be filled, that availability, and the fund's `per_article_cap_cents`."
    PRD §3.5: "Otherwise `FundRequest.approved_cents` is set to that total, `FundRequest.author_share_cents` becomes `requested_cents` less the approved total, and `FundRequest.fully_funded` is true exactly when the approved total equals `requested_cents`."
    PRD §3.5: "The request moves from `UNDER_REVIEW` to `APPROVED`."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `FUNDED` when the request was fully funded and to `PARTIALLY_FUNDED` when it was not."
    Design: Difficulty/cross_entity_state_dependency/fund_decision_depends_on_apc_fund_open_versus_frozen
    """
    scenario = _setup_two_requests_under_review_on_one_fund()

    decided = validate_success(
        api.decide_fund_request(
            scenario["first_request"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        )
    )

    assert decided["approved_cents"] == 300000, (
        f"the open fund can take the whole 300000 cent ceiling, "
        f"got {decided['approved_cents']}"
    )
    assert decided["fully_funded"] is True, (
        f"approved_cents equals requested_cents, so fully_funded must be true, "
        f"got {decided['fully_funded']}"
    )
    assert decided["status"] == "APPROVED", (
        f"an approval moves the request from UNDER_REVIEW to APPROVED, "
        f"got {decided['status']}"
    )

    article = validate_success(
        api.get_article(scenario["first_article"]["id"], fund_manager_headers)
    )
    assert article["funding_status"] == "FUNDED", (
        f"a fully funded request moves the article to FUNDED, "
        f"got {article['funding_status']}"
    )


def test_fund_request_approval_after_the_fund_is_frozen_is_refused_with_no_fund_capacity(
    api, fund_manager_headers
):
    """A manual freeze removes the only candidate fund, so the second, structurally
    identical approval finds no capacity and writes nothing.

    PRD §3.3: "Freezing removes a fund from the waterfall permanently — `FROZEN` is terminal, and there is no path back to `OPEN`."
    PRD §3.3: "A `FundManager` may freeze a fund manually by supplying a `reason`, which is recorded verbatim as `freeze_reason`; the fund must currently be `OPEN`, or the request is rejected with `ERR_FUND_FROZEN`."
    PRD §3.5: "The candidate funds are those whose `status` is `OPEN` — frozen funds are excluded outright — whose `fiscal_year` equals the fiscal year of the current clock date, whose period contains the clock date so that `period_from` is on or before it and `period_to` is on or after it, and whose `eligible_affiliation_statuses` list contains the author's `affiliation_status`."
    PRD §3.5: "If it is zero — no eligible open fund could contribute a single cent — the approval is refused with `ERR_NO_FUND_CAPACITY` (HTTP 409) and nothing is written."
    PRD §3.5: "A new request has `status` `SUBMITTED` and `revision_round` of zero, with `info_needed`, `response_note`, `reviewed_by_user_id`, `decided_by_user_id` and `decision_reason` all absent, `approved_cents` and `author_share_cents` at zero and `fully_funded` false."
    PRD §3.5: "Creating it advances the article's funding dimension from `ELIGIBILITY_CHECKED` to `FUNDING_REQUESTED`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    Design: Difficulty/cross_entity_state_dependency/fund_decision_depends_on_apc_fund_open_versus_frozen
    """
    scenario = _setup_two_requests_under_review_on_one_fund()
    validate_success(
        api.decide_fund_request(
            scenario["first_request"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        )
    )

    frozen = validate_success(
        api.freeze_apc_fund(
            scenario["fund"]["id"],
            create_freeze_payload("AUDIT_HOLD"),
            fund_manager_headers,
        )
    )
    assert frozen["status"] == "FROZEN", (
        f"a manual freeze moves the fund to FROZEN, got {frozen['status']}"
    )
    assert frozen["freeze_reason"] == "AUDIT_HOLD", (
        f"the supplied reason is recorded verbatim, got {frozen['freeze_reason']!r}"
    )
    assert frozen["committed_cents"] == 300000, (
        f"freezing moves no money, so committed_cents stays at 300000, "
        f"got {frozen['committed_cents']}"
    )

    validate_error(
        api.decide_fund_request(
            scenario["second_request"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        ),
        ApiErrorId.ERR_NO_FUND_CAPACITY.value,
    )

    request = validate_success(
        api.get_fund_request(scenario["second_request"]["id"], fund_manager_headers)
    )
    assert request["status"] == "UNDER_REVIEW", (
        f"a refused approval writes nothing, so the request stays UNDER_REVIEW, "
        f"got {request['status']}"
    )
    assert request["approved_cents"] == 0, (
        f"approved_cents must remain 0, got {request['approved_cents']}"
    )
    assert request["fully_funded"] is False, (
        f"fully_funded must remain false, got {request['fully_funded']}"
    )

    article = validate_success(
        api.get_article(scenario["second_article"]["id"], fund_manager_headers)
    )
    assert article["funding_status"] == "FUNDING_REQUESTED", (
        f"the article's funding dimension stays where the request creation left it, "
        f"got {article['funding_status']}"
    )

    fund = validate_success(api.get_apc_fund(scenario["fund"]["id"], fund_manager_headers))
    assert fund["committed_cents"] == 300000, (
        f"the frozen fund's committed_cents is untouched by the refusal, "
        f"got {fund['committed_cents']}"
    )
    assert fund["available_cents"] == 700000, (
        f"available_cents should be 1000000 - 300000 - 0 = 700000, "
        f"got {fund['available_cents']}"
    )

    rows, _meta = validate_paginated(
        api.list_fund_request_allocations(
            scenario["second_request"]["id"], fund_manager_headers
        )
    )
    assert rows == [], f"the refused approval must create no allocation line, got {rows}"
