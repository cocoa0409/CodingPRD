"""Non-linear progressions: an article's two orthogonal state dimensions advancing
independently, and a fund request looping twice through the information-request
cycle before it is approved.

Neither progression is a straight line — one row carries two dimensions that never
read each other, and one request re-enters the same two states twice.
"""

from test_helpers import (
    create_deposit,
    create_resubmission_payload,
    curate_deposit,
    decide_request,
    list_request_allocations,
    make_checksum,
    make_corresponding_author_headers,
    open_fund,
    open_fund_request,
    read_article,
    read_fund,
    read_fund_request,
    read_grant,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    request_more_information,
    resubmit_request,
    run_eligibility_check,
    set_clock,
    start_review,
    submit_deposit,
    validate_success,
)


# --------------------------------------------------------------------------- #
# preambles
# --------------------------------------------------------------------------- #
def _setup_gold_oa_article_with_fund(manuscript_title: str) -> dict:
    """A FULLY_OA article accepted 2026-08-05 under a GOLD_OA mandate, with an
    ORCID-bearing author and one open APC fund for fiscal year 2027."""
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
        manuscript_title=manuscript_title,
        accepted_on="2026-08-05",
    )
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "funder": funder,
        "grant": grant,
        "fund": fund,
        "article": article,
    }


def _ingest_accepted_manuscript(article_id: str, author_id: str) -> dict:
    """Deposit, submit and ingest the accepted manuscript on 2026-08-10."""
    set_clock("2026-08-10T00:00:00Z")
    deposit = create_deposit(
        article_id,
        author_id,
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum=make_checksum(1),
        license="CC_BY",
    )
    submit_deposit(deposit["id"], author_id)
    return curate_deposit(deposit["id"], "INGEST")


# --------------------------------------------------------------------------- #
# two independent dimensions on one article row
# --------------------------------------------------------------------------- #
def test_ingest_moves_compliance_to_embargoed_leaving_funding_untouched():
    """An eligibility check advances only the funding dimension and an ingest
    advances only the compliance dimension: after the manuscript is ingested inside
    the embargo the article reads EMBARGOED while its funding dimension is still
    exactly where the determination left it.

    PRD §3.4: "An article is unusual in carrying **two independent state dimensions on the same row**."
    PRD §3.4: "The two dimensions never read or write each other: no funding transition inspects `compliance_status`, and no compliance transition inspects `funding_status`."
    PRD §3.4: "The funding dimension then follows the route: a `TA_FULL` route sets `funding_status` to `FUNDED`; a `TA_CAPPED` route sets it to `ELIGIBILITY_CHECKED` when `eligible_request_cents` is greater than zero and to `SELF_FUNDED` when `eligible_request_cents` is zero; a `FUND_APC` route sets it to `ELIGIBILITY_CHECKED`; an `AUTHOR_PAYS` route sets it to `SELF_FUNDED`."
    PRD §3.8: "The `deposit_deadline_on` is the article's `accepted_on` advanced by the funder's `deposit_deadline_days` in whole calendar days."
    PRD §3.8: "The embargo length in months is zero when the funder's `mandate_type` is `IMMEDIATE_CC_BY`, and otherwise the smaller of the funder's `max_embargo_months` and the journal's `required_embargo_months` — the institution never applies a longer embargo than either party requires."
    PRD §3.8: "The embargo is measured from the article's `publication_date` when one exists and from its `accepted_on` when it does not, and `embargo_until` is that base date advanced by the embargo length in whole months, keeping the day of month and clamping to the last day of the target month where the original day does not exist there."
    PRD §3.8: "Otherwise the article is `EMBARGOED`, meaning the manuscript is safely in the repository but may not yet be made public."
    PRD §3.8: "On success the deposit moves from `SUBMITTED` to `INGESTED`, `ingested_at` is stamped from the logical clock, and a `persistent_identifier` is minted as the literal prefix `hdl:2027/ir.` followed by the institutional ingest counter rendered as six digits with leading zeros — the counter begins at 1, so the first ingest in the system produces `hdl:2027/ir.000001`."
    Design: Difficulty/non_linear_state_machine/article_funding_and_compliance_dimensions_advance_independently
    """
    scenario = _setup_gold_oa_article_with_fund(
        "Two-dimensional state progress in open metabolism"
    )
    article_id = scenario["article"]["id"]

    assert scenario["article"]["compliance_status"] == "PENDING_DEPOSIT", (
        "a mandated article starts in PENDING_DEPOSIT, got "
        f"{scenario['article']['compliance_status']!r}"
    )
    assert scenario["article"]["deposit_deadline_on"] == "2026-11-03", (
        "2026-08-05 advanced by 90 days is 2026-11-03, got "
        f"{scenario['article']['deposit_deadline_on']!r}"
    )

    determination = run_eligibility_check(article_id, basis="PROVISIONAL")
    assert determination["route"] == "FUND_APC", (
        "a FULLY_OA journal with no agreement but an APC-allowable grant routes "
        f"FUND_APC, got {determination['route']!r}"
    )
    assert determination["eligible_request_cents"] == 300000, (
        "the whole list base 300000 may be requested, got "
        f"{determination['eligible_request_cents']}"
    )

    after_check = read_article(article_id)
    assert after_check["funding_status"] == "ELIGIBILITY_CHECKED", (
        f"a FUND_APC route sets ELIGIBILITY_CHECKED, got {after_check['funding_status']!r}"
    )
    assert after_check["compliance_status"] == "PENDING_DEPOSIT", (
        "the funding transition must not touch the compliance dimension, got "
        f"{after_check['compliance_status']!r}"
    )

    ingested = _ingest_accepted_manuscript(article_id, scenario["author"]["id"])
    assert ingested["status"] == "INGESTED", (
        f"the curator's INGEST decision must reach INGESTED, got {ingested['status']!r}"
    )
    assert ingested.get("persistent_identifier") is not None, (
        "ingest mints a persistent identifier, got "
        f"{ingested.get('persistent_identifier')!r}"
    )

    after_ingest = read_article(article_id)
    assert after_ingest["compliance_status"] == "EMBARGOED", (
        "ingesting before the embargo elapses gives EMBARGOED, got "
        f"{after_ingest['compliance_status']!r}"
    )
    assert after_ingest["embargo_until"] == "2027-02-05", (
        "the smaller of 6 and 12 months from the acceptance date 2026-08-05 is "
        f"2027-02-05, got {after_ingest['embargo_until']!r}"
    )
    assert after_ingest["funding_status"] == "ELIGIBILITY_CHECKED", (
        "the compliance transition must not touch the funding dimension, got "
        f"{after_ingest['funding_status']!r}"
    )


def test_fund_approval_moves_funding_to_funded_leaving_compliance_embargoed():
    """With the article already EMBARGOED, opening and approving a fully funded
    request walks the funding dimension to FUNDED and leaves the compliance
    dimension exactly as the ingest set it.

    PRD §3.4: "The two dimensions never read or write each other: no funding transition inspects `compliance_status`, and no compliance transition inspects `funding_status`."
    PRD §3.5: "Creating it advances the article's funding dimension from `ELIGIBILITY_CHECKED` to `FUNDING_REQUESTED`."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `FUNDED` when the request was fully funded and to `PARTIALLY_FUNDED` when it was not."
    PRD §2.10: "`FundRequest.approved_cents` is the sum of `amount_cents` over that request's allocation lines whose status is `ENCUMBERED` or `DISBURSED`; `FundRequest.author_share_cents` is `requested_cents` less `approved_cents` as at decision time; `FundRequest.fully_funded` is true exactly when `approved_cents` equals `requested_cents`."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    PRD §3.8: "`Grant.output_count` is the number of articles referencing the grant and `Grant.compliant_output_count` is how many of those are `COMPLIANT` or `EXEMPT`."
    PRD §3.8: "In every other case it is `IN_PROGRESS`."
    PRD §3.3: "Whenever an allocation is encumbered or disbursed against a fund, the fund is re-examined: if `committed_cents` plus `spent_cents` reaches or exceeds ninety-eight percent of `total_budget_cents` — computed as `total_budget_cents` multiplied by 0.98 and rounded half up to whole cents — the fund moves from `OPEN` to `FROZEN` with `freeze_reason` set to the literal value `AUTO_THRESHOLD`."
    Design: Difficulty/non_linear_state_machine/article_funding_and_compliance_dimensions_advance_independently
    """
    scenario = _setup_gold_oa_article_with_fund(
        "Two-dimensional state progress in open metabolism"
    )
    article_id = scenario["article"]["id"]
    author_id = scenario["author"]["id"]
    run_eligibility_check(article_id, basis="PROVISIONAL")
    _ingest_accepted_manuscript(article_id, author_id)

    request = open_fund_request(article_id, author_id, 300000)
    start_review(request["id"])
    decided = decide_request(request["id"], "APPROVE")

    assert decided["approved_cents"] == 300000, (
        f"the waterfall should approve the whole 300000, got {decided['approved_cents']}"
    )
    assert decided["fully_funded"] is True, (
        "approved_cents equals requested_cents, so fully_funded is true, got "
        f"{decided['fully_funded']!r}"
    )

    article = read_article(article_id)
    assert article["funding_status"] == "FUNDED", (
        f"a fully funded approval moves the article to FUNDED, got {article['funding_status']!r}"
    )
    assert article["compliance_status"] == "EMBARGOED", (
        "the funding approval must leave the compliance dimension at EMBARGOED, got "
        f"{article['compliance_status']!r}"
    )
    assert article["latest_deposit_ordinal"] == 1, (
        "one deposit exists, so latest_deposit_ordinal is 1, got "
        f"{article['latest_deposit_ordinal']}"
    )

    grant = read_grant(scenario["grant"]["id"])
    assert grant["output_count"] == 1, (
        f"one article references the grant, got output_count {grant['output_count']}"
    )
    assert grant["compliant_output_count"] == 0, (
        "an EMBARGOED article is neither COMPLIANT nor EXEMPT, got "
        f"{grant['compliant_output_count']}"
    )
    assert grant["mandate_status"] == "IN_PROGRESS", (
        f"the mandate is still in progress, got {grant['mandate_status']!r}"
    )

    fund = read_fund(scenario["fund"]["id"])
    assert fund["status"] == "OPEN", (
        "300000 committed against a 1000000 budget is far below the 980000 "
        f"auto-freeze threshold, got {fund['status']!r}"
    )


# --------------------------------------------------------------------------- #
# the information-request revision loop
# --------------------------------------------------------------------------- #
def test_two_information_request_cycles_reach_revision_round_two(api):
    """Each completed SUBMITTED to UNDER_REVIEW to INFO_REQUESTED to SUBMITTED cycle
    adds one to revision_round and replaces requested_cents outright, so after two
    loops the request reads round 2 at 260000 cents.

    PRD §3.5: "A `ScholCommLibrarian` takes a submitted request into review, moving it from `SUBMITTED` to `UNDER_REVIEW` and recording the acting `X-User-ID` as `reviewed_by_user_id`."
    PRD §3.5: "If something is unclear, the same librarian raises an information request, moving `UNDER_REVIEW` to `INFO_REQUESTED` and recording the question as `info_needed`."
    PRD §3.5: "Resubmission replaces `requested_cents` outright, records the `response_note`, increases `revision_round` by one, and returns the request to `SUBMITTED`."
    PRD §3.5: "The `SUBMITTED` → `UNDER_REVIEW` → `INFO_REQUESTED` → `SUBMITTED` cycle may repeat without limit, and `revision_round` is simply the count of completed cycles."
    PRD §3.5: "The new amount is re-checked against the effective determination's `eligible_request_cents` exactly as at creation, so an author cannot escalate the ask through the revision loop; an excess is again `ERR_REQUEST_EXCEEDS_ELIGIBLE`."
    PRD §3.5: "A new request has `status` `SUBMITTED` and `revision_round` of zero, with `info_needed`, `response_note`, `reviewed_by_user_id`, `decided_by_user_id` and `decision_reason` all absent, `approved_cents` and `author_share_cents` at zero and `fully_funded` false."
    Design: Difficulty/non_linear_state_machine/fund_request_revision_cycle_reaches_round_two_then_approves
    """
    scenario = _setup_gold_oa_article_with_fund(
        "Revision cycles in metabolic flux reporting"
    )
    author_id = scenario["author"]["id"]
    determination = run_eligibility_check(scenario["article"]["id"], basis="PROVISIONAL")
    assert determination["eligible_request_cents"] == 300000, (
        "expected eligible_request_cents 300000, got "
        f"{determination['eligible_request_cents']}"
    )

    request = open_fund_request(scenario["article"]["id"], author_id, 300000)
    assert request["revision_round"] == 0, (
        f"a new request starts at revision_round 0, got {request['revision_round']}"
    )
    assert request["status"] == "SUBMITTED", (
        f"a new request starts in SUBMITTED, got {request['status']!r}"
    )

    under_review = start_review(request["id"])
    assert under_review["status"] == "UNDER_REVIEW", (
        f"start-review moves SUBMITTED to UNDER_REVIEW, got {under_review['status']!r}"
    )
    info_requested = request_more_information(
        request["id"], info_needed="Confirm whether the funder will pay part of the fee."
    )
    assert info_requested["status"] == "INFO_REQUESTED", (
        "an information request moves UNDER_REVIEW to INFO_REQUESTED, got "
        f"{info_requested['status']!r}"
    )

    response = api.create_fund_request_resubmission(
        request["id"],
        create_resubmission_payload(
            280000, response_note="Funder contributes nothing; trimming the request."
        ),
        make_corresponding_author_headers(author_id),
    )
    resubmitted = validate_success(response)
    assert resubmitted["status"] == "SUBMITTED", (
        f"resubmission returns the request to SUBMITTED, got {resubmitted['status']!r}"
    )
    assert resubmitted["revision_round"] == 1, (
        f"the first completed cycle gives revision_round 1, got {resubmitted['revision_round']}"
    )

    start_review(request["id"])
    request_more_information(
        request["id"],
        info_needed="Attach the publisher quotation for the trimmed amount.",
    )
    second = resubmit_request(
        request["id"],
        author_id,
        260000,
        response_note="Quotation attached; final amount 260000.",
    )
    assert second["revision_round"] == 2, (
        f"the second completed cycle gives revision_round 2, got {second['revision_round']}"
    )
    assert second["requested_cents"] == 260000, (
        "resubmission replaces requested_cents outright, expected 260000, got "
        f"{second['requested_cents']}"
    )


def test_approval_from_the_third_review_entry_allocates_the_resubmitted_amount():
    """The terminating APPROVE fires from the third entry into UNDER_REVIEW and the
    waterfall draws the amount the second resubmission left in place, not the
    original ask.

    PRD §3.5: "Resubmission replaces `requested_cents` outright, records the `response_note`, increases `revision_round` by one, and returns the request to `SUBMITTED`."
    PRD §3.5: "Otherwise a request ceiling is set to the smallest of three independent limits: the request's own `requested_cents`, the effective determination's `eligible_request_cents`, and the author's remaining allowance."
    PRD §3.5: "The request moves from `UNDER_REVIEW` to `APPROVED`."
    PRD §2.10: "`FundRequest.approved_cents` is the sum of `amount_cents` over that request's allocation lines whose status is `ENCUMBERED` or `DISBURSED`; `FundRequest.author_share_cents` is `requested_cents` less `approved_cents` as at decision time; `FundRequest.fully_funded` is true exactly when `approved_cents` equals `requested_cents`."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `FUNDED` when the request was fully funded and to `PARTIALLY_FUNDED` when it was not."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    Design: Difficulty/non_linear_state_machine/fund_request_revision_cycle_reaches_round_two_then_approves
    """
    scenario = _setup_gold_oa_article_with_fund(
        "Revision cycles in metabolic flux reporting"
    )
    author_id = scenario["author"]["id"]
    run_eligibility_check(scenario["article"]["id"], basis="PROVISIONAL")
    request = open_fund_request(scenario["article"]["id"], author_id, 300000)

    start_review(request["id"])
    request_more_information(
        request["id"], info_needed="Confirm whether the funder will pay part of the fee."
    )
    resubmit_request(
        request["id"],
        author_id,
        280000,
        response_note="Funder contributes nothing; trimming the request.",
    )
    start_review(request["id"])
    request_more_information(
        request["id"],
        info_needed="Attach the publisher quotation for the trimmed amount.",
    )
    resubmit_request(
        request["id"],
        author_id,
        260000,
        response_note="Quotation attached; final amount 260000.",
    )
    start_review(request["id"])
    decided = decide_request(request["id"], "APPROVE")

    assert decided["status"] == "APPROVED", (
        f"the decision moves UNDER_REVIEW to APPROVED, got {decided['status']!r}"
    )
    assert decided["approved_cents"] == 260000, (
        f"the request ceiling is the resubmitted 260000, got {decided['approved_cents']}"
    )
    assert decided["fully_funded"] is True, (
        f"260000 approved of 260000 requested is fully funded, got {decided['fully_funded']!r}"
    )

    reread = read_fund_request(request["id"])
    assert reread["author_share_cents"] == 0, (
        f"requested_cents less approved_cents is 0, got {reread['author_share_cents']}"
    )
    article = read_article(scenario["article"]["id"])
    assert article["funding_status"] == "FUNDED", (
        f"a fully funded approval moves the article to FUNDED, got {article['funding_status']!r}"
    )

    fund = read_fund(scenario["fund"]["id"])
    assert fund["committed_cents"] == 260000, (
        f"the fund should carry 260000 committed cents, got {fund['committed_cents']}"
    )
    assert fund["available_cents"] == 740000, (
        f"1000000 less 260000 is 740000 available, got {fund['available_cents']}"
    )

    allocations = list_request_allocations(request["id"])
    assert len(allocations) == 1, f"expected exactly 1 allocation line, got {len(allocations)}"
    assert allocations[0]["amount_cents"] == 260000, (
        f"expected amount_cents 260000, got {allocations[0]['amount_cents']}"
    )
    assert allocations[0]["sequence_index"] == 1, (
        f"expected sequence_index 1, got {allocations[0]['sequence_index']}"
    )
    assert allocations[0]["status"] == "ENCUMBERED", (
        f"a fresh allocation line is ENCUMBERED, got {allocations[0]['status']!r}"
    )
