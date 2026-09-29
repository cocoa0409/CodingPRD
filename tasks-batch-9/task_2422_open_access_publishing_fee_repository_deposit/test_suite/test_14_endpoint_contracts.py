"""Endpoint-contract corners: create/read round trips, empty action bodies, the
four-phase sweep, parent-scoped sub-resource reads, derived read roll-ups and the
narrow reject branch of the funding decision.

Every test builds its whole world from scratch against an empty database and
drives the logical clock explicitly.
"""

from test_helpers import (
    TEST_USERS,
    activate_agreement,
    add_coverage,
    create_apc_fund_payload,
    create_decision_payload,
    create_deposit,
    curate_deposit,
    draft_agreement,
    make_librarian_headers,
    open_fund,
    open_fund_request,
    read_agreement,
    read_article,
    read_author,
    read_fund,
    read_grant,
    read_publisher,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    submit_deposit,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["agreement_admin_headers"]
LIBRARIAN = TEST_USERS["librarian_headers"]
FUND_MANAGER = TEST_USERS["fund_manager_headers"]
CURATOR = TEST_USERS["curator_headers"]


# --------------------------------------------------------------------------- #
# private preamble helpers
# --------------------------------------------------------------------------- #
def _register_halden_journal() -> dict:
    """Publisher HALDEN with one FULLY_OA journal charging 300000 cents."""
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
    return {"publisher": publisher, "journal": journal}


def _register_berg_author() -> dict:
    return register_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )


def _setup_submitted_fund_request(manuscript_title: str, justification: str) -> dict:
    """Clock at 2026-08-10, a GOLD_OA funder with an ACTIVE grant, a FULLY_OA
    journal at 300000 cents, one OPEN fund, and an article routed FUND_APC whose
    fund request sits in SUBMITTED."""
    set_clock("2026-08-10T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()
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
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=400000,
    )
    article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title=manuscript_title,
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    request = open_fund_request(
        article["id"], author["id"], 300000, justification=justification
    )
    return {
        "publisher": base["publisher"],
        "journal": base["journal"],
        "author": author,
        "funder": funder,
        "grant": grant,
        "fund": fund,
        "article": article,
        "determination": determination,
        "request": request,
    }


# --------------------------------------------------------------------------- #
# APC fund create → read → empty allocation list
# --------------------------------------------------------------------------- #
def test_new_fund_reads_back_unused_and_lists_no_allocations(api):
    """A freshly opened fund reports a wholly unused ledger and its allocations
    sub-resource answers with an empty page rather than a 404.

    PRD §4: "Operations that mint a brand-new, independently addressable resource — registering a publisher, journal, agreement, coverage line, author, funder, grant or fund; recording an article; appending an eligibility determination; opening a fund request; receiving an invoice; creating a deposit — return `201 Created`."
    PRD §3.3: "On opening, `status` is `OPEN`, `committed_cents` and `spent_cents` are zero, `available_cents` equals `total_budget_cents`, and `freeze_reason` is absent."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    PRD §2.3: "When a list endpoint responds, the `meta` object carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before pagination was applied, and `has_more` as a boolean that is true exactly when rows matching the filters remain beyond the current page."
    Design: Corner/endpoints/corner_fund_create_then_read_then_empty_allocation_list
    """
    payload = create_apc_fund_payload(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY", "ELIGIBLE_POSTDOC"],
        per_article_cap_cents=400000,
    )
    created = validate_success(
        api.create_apc_fund(payload, FUND_MANAGER), expected_status=201
    )
    assert created["available_cents"] == 500000, (
        "available_cents must equal total_budget_cents on opening, got "
        f"{created['available_cents']}"
    )
    assert created["status"] == "OPEN", (
        f"a newly opened fund must be OPEN, got {created['status']!r}"
    )
    assert created["version"] == 1, (
        f"version must start at 1 on creation, got {created['version']!r}"
    )

    read_back = validate_success(api.get_apc_fund(created["id"], FUND_MANAGER))
    assert read_back["committed_cents"] == 0, (
        f"committed_cents must be zero on opening, got {read_back['committed_cents']}"
    )
    assert read_back["spent_cents"] == 0, (
        f"spent_cents must be zero on opening, got {read_back['spent_cents']}"
    )
    assert read_back.get("freeze_reason") is None, (
        f"freeze_reason must be absent on opening, got {read_back.get('freeze_reason')!r}"
    )
    assert read_back["per_article_cap_cents"] == 400000, (
        "per_article_cap_cents must read back as supplied, got "
        f"{read_back['per_article_cap_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_fund_allocations(
            created["id"], FUND_MANAGER, params={"limit": 10, "offset": 0}
        )
    )
    assert rows == [], f"a fund with no allocations must list no rows, got {rows!r}"
    assert meta["total_count"] == 0, (
        f"total_count must be 0 for an unused fund, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"has_more must be false when no rows remain, got {meta['has_more']!r}"
    )


# --------------------------------------------------------------------------- #
# start-review: empty body, reviewer stamped
# --------------------------------------------------------------------------- #
def test_start_review_accepts_an_empty_body_and_stamps_the_reviewing_librarian(api):
    """Taking a submitted request into review needs no body: the path id and the
    acting identity are enough, and only the review fields move.

    PRD §3.5: "A new request has `status` `SUBMITTED` and `revision_round` of zero, with `info_needed`, `response_note`, `reviewed_by_user_id`, `decided_by_user_id` and `decision_reason` all absent, `approved_cents` and `author_share_cents` at zero and `fully_funded` false."
    PRD §3.5: "Creating it advances the article's funding dimension from `ELIGIBILITY_CHECKED` to `FUNDING_REQUESTED`."
    PRD §3.5: "A `ScholCommLibrarian` takes a submitted request into review, moving it from `SUBMITTED` to `UNDER_REVIEW` and recording the acting `X-User-ID` as `reviewed_by_user_id`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    Design: Corner/endpoints/corner_start_review_action_takes_an_empty_body_and_stamps_the_reviewer
    """
    scenario = _setup_submitted_fund_request(
        "Awaiting review", "Fully OA journal, gold mandate."
    )
    assert scenario["request"].get("reviewed_by_user_id") is None, (
        "a newly submitted request carries no reviewer, got "
        f"{scenario['request'].get('reviewed_by_user_id')!r}"
    )

    reviewer_headers = make_librarian_headers("librarian-reviewer-07")
    reviewed = validate_success(
        api.start_fund_request_review(
            scenario["request"]["id"], reviewer_headers, payload={}
        )
    )
    assert reviewed["status"] == "UNDER_REVIEW", (
        f"start-review must move SUBMITTED to UNDER_REVIEW, got {reviewed['status']!r}"
    )
    assert reviewed["reviewed_by_user_id"] == "librarian-reviewer-07", (
        "reviewed_by_user_id must record the acting X-User-ID, got "
        f"{reviewed['reviewed_by_user_id']!r}"
    )
    assert reviewed.get("decided_by_user_id") is None, (
        "decided_by_user_id must stay absent until a decision is taken, got "
        f"{reviewed.get('decided_by_user_id')!r}"
    )
    assert reviewed["revision_round"] == 0, (
        f"revision_round must stay 0, got {reviewed['revision_round']}"
    )
    assert reviewed["requested_cents"] == 300000, (
        f"requested_cents must be untouched at 300000, got {reviewed['requested_cents']}"
    )

    fund = read_fund(scenario["fund"]["id"])
    assert fund["committed_cents"] == 0, (
        f"review alone encumbers nothing, got committed_cents {fund['committed_cents']}"
    )
    article = read_article(scenario["article"]["id"])
    assert article["funding_status"] == "FUNDING_REQUESTED", (
        "the article stays FUNDING_REQUESTED while under review, got "
        f"{article['funding_status']!r}"
    )


# --------------------------------------------------------------------------- #
# the compliance sweep runs all four phases in one call
# --------------------------------------------------------------------------- #
def test_compliance_sweep_runs_every_phase_once_and_reports_four_counters(api):
    """One sweep on 2027-03-01 expires an agreement, closes a grant, flags a
    missed deposit deadline and releases an elapsed embargo — one row each.

    PRD §3.8: "The `deposit_deadline_on` is the article's `accepted_on` advanced by the funder's `deposit_deadline_days` in whole calendar days."
    PRD §3.8: "The embargo length in months is zero when the funder's `mandate_type` is `IMMEDIATE_CC_BY`, and otherwise the smaller of the funder's `max_embargo_months` and the journal's `required_embargo_months` — the institution never applies a longer embargo than either party requires."
    PRD §3.8: "The deposit's own `embargo_until` is copied from the article as at ingest."
    PRD §3.9: "Phase one expires agreements: every transformative agreement in `DRAFT`, `ACTIVE` or `EXHAUSTED` whose `effective_until` is on or before the clock date moves to `EXPIRED`, with the publisher's `active_agreement_count` recomputed and the publisher's `version` incremented for those that were `ACTIVE`."
    PRD §3.9: "Phase two closes grants: every `ACTIVE` grant whose `award_until` is strictly before the clock date moves to `CLOSED`."
    PRD §3.9: "Phase three catches missed deposit deadlines: every article whose `compliance_status` is still `PENDING_DEPOSIT` and whose `deposit_deadline_on` is strictly before the clock date moves to `NON_COMPLIANT`, and the owning grant's `mandate_status` moves to `BREACHED`."
    PRD §3.9: "Phase four releases elapsed embargoes: every article whose `compliance_status` is `EMBARGOED` and whose `embargo_until` is on or before the clock date moves to `COMPLIANT`, with the grant's `compliant_output_count` and `mandate_status` recomputed."
    PRD §3.8: "Otherwise, if the grant has at least one article and every one of them is `COMPLIANT` or `EXEMPT`, the `mandate_status` is `SATISFIED`."
    PRD §3.9: "Its response carries `swept_at_utc` as the logical-clock instant of the run, `agreements_expired_count`, `grants_closed_count`, `articles_marked_non_compliant_count` and `articles_promoted_compliant_count`, each being the number of rows the corresponding phase actually changed."
    Design: Corner/endpoints/corner_compliance_sweep_runs_all_four_phases_in_one_call
    """
    set_clock("2026-08-10T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()
    funder = register_funder(
        name="Nordic Green Foundation",
        funder_code="NGF",
        mandate_type="GREEN_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="ANY",
        apc_allowable=False,
    )
    grant_missed = record_grant(
        funder["id"],
        author["id"],
        grant_number="NGF-2026-11",
        award_from="2026-01-01",
        award_until="2026-09-30",
        apc_budget_cents=500000,
    )
    grant_embargoed = record_grant(
        funder["id"],
        author["id"],
        grant_number="NGF-2026-12",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=500000,
    )
    agreement = draft_agreement(
        base["publisher"]["id"],
        agreement_code="TA-HALDEN-2026H2",
        effective_from="2026-07-01",
        effective_until="2026-09-01",
        article_quota=5,
        discount_pct=0.10,
        covered_oa_models=["FULLY_OA"],
    )
    add_coverage(
        agreement["id"],
        base["journal"]["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-08-31",
    )
    activated = activate_agreement(agreement["id"])
    assert activated["status"] == "ACTIVE", (
        f"the agreement must be ACTIVE before the sweep, got {activated['status']!r}"
    )

    article_missed = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant_missed["id"],
        manuscript_title="Deadline missed",
        accepted_on="2026-08-05",
    )
    assert article_missed["deposit_deadline_on"] == "2026-11-03", (
        "accepted_on 2026-08-05 plus 90 days is 2026-11-03, got "
        f"{article_missed['deposit_deadline_on']!r}"
    )
    assert article_missed["compliance_status"] == "PENDING_DEPOSIT", (
        "an undeposited mandated article starts PENDING_DEPOSIT, got "
        f"{article_missed['compliance_status']!r}"
    )

    article_embargoed = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant_embargoed["id"],
        manuscript_title="Deposited under embargo",
        accepted_on="2026-08-05",
    )
    deposit = create_deposit(
        article_embargoed["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        license="CC_BY",
        file_checksum="8f1d2c4b6a9e0f3d5c7b1a2e4f6d8c0b2a4e6f8d1c3b5a7e9f0d2c4b6a8e0f1d",
    )
    submit_deposit(deposit["id"], author["id"])
    ingested = curate_deposit(deposit["id"], "INGEST", "Metadata complete.")
    assert ingested["status"] == "INGESTED", (
        f"the deposit must reach INGESTED, got {ingested['status']!r}"
    )
    assert ingested["embargo_until"] == "2027-02-05", (
        "a six-month embargo from 2026-08-05 ends 2027-02-05, got "
        f"{ingested['embargo_until']!r}"
    )
    assert ingested.get("persistent_identifier") is not None, (
        "ingest must mint a persistent_identifier"
    )

    current_utc = set_clock("2027-03-01T00:00:00Z", LIBRARIAN)
    sweep = validate_success(api.create_compliance_sweep(LIBRARIAN, payload={}))
    assert sweep["swept_at_utc"] == current_utc, (
        "swept_at_utc must be the logical-clock instant of the run, got "
        f"{sweep['swept_at_utc']!r} against clock {current_utc!r}"
    )
    assert sweep["swept_at_utc"].startswith("2027-03-01T00:00:00"), (
        f"the sweep ran at 2027-03-01T00:00:00Z, got {sweep['swept_at_utc']!r}"
    )
    assert sweep["agreements_expired_count"] == 1, (
        f"exactly one agreement expires, got {sweep['agreements_expired_count']}"
    )
    assert sweep["grants_closed_count"] == 1, (
        f"exactly one grant closes, got {sweep['grants_closed_count']}"
    )
    assert sweep["articles_marked_non_compliant_count"] == 1, (
        "exactly one article misses its deadline, got "
        f"{sweep['articles_marked_non_compliant_count']}"
    )
    assert sweep["articles_promoted_compliant_count"] == 1, (
        "exactly one embargo has elapsed, got "
        f"{sweep['articles_promoted_compliant_count']}"
    )

    assert read_agreement(agreement["id"])["status"] == "EXPIRED", (
        "the agreement whose effective_until is 2026-09-01 must be EXPIRED"
    )
    publisher = read_publisher(base["publisher"]["id"])
    assert publisher["active_agreement_count"] == 0, (
        "expiring out of ACTIVE decrements active_agreement_count, got "
        f"{publisher['active_agreement_count']}"
    )
    missed = read_grant(grant_missed["id"])
    assert missed["status"] == "CLOSED", (
        f"a grant whose award_until has passed must be CLOSED, got {missed['status']!r}"
    )
    assert missed["mandate_status"] == "BREACHED", (
        f"a missed deposit deadline breaches the grant, got {missed['mandate_status']!r}"
    )
    assert read_article(article_missed["id"])["compliance_status"] == "NON_COMPLIANT", (
        "the article past its deadline must be NON_COMPLIANT"
    )
    assert read_article(article_embargoed["id"])["compliance_status"] == "COMPLIANT", (
        "the article whose embargo elapsed must be promoted to COMPLIANT"
    )
    embargoed_grant = read_grant(grant_embargoed["id"])
    assert embargoed_grant["status"] == "ACTIVE", (
        "a grant whose award window has not ended stays ACTIVE, got "
        f"{embargoed_grant['status']!r}"
    )
    assert embargoed_grant["compliant_output_count"] == 1, (
        f"the promoted article counts once, got {embargoed_grant['compliant_output_count']}"
    )
    assert embargoed_grant["mandate_status"] == "SATISFIED", (
        "every article of the grant is COMPLIANT, so the mandate is SATISFIED, got "
        f"{embargoed_grant['mandate_status']!r}"
    )
    assert validate_success(
        api.get_repository_deposit(deposit["id"], CURATOR)
    )["status"] == "INGESTED", "the sweep leaves the ingested deposit alone"


# --------------------------------------------------------------------------- #
# sub-resource lists are scoped to their parent
# --------------------------------------------------------------------------- #
def test_grant_sub_resource_lists_are_scoped_to_their_parent(api):
    """Three grants across two funders and two principal investigators: each
    nested list returns only the rows belonging to its own parent.

    PRD §3.3: "Grants may be listed by the author who is their principal investigator, narrowed by `pi_author_id` and `status`, and by their funder, narrowed by `funder_id` and `status`."
    PRD §2.3: "When a list endpoint responds, the `meta` object carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before pagination was applied, and `has_more` as a boolean that is true exactly when rows matching the filters remain beyond the current page."
    Design: Corner/endpoints/corner_sub_resource_lists_are_scoped_to_their_parent
    """
    author_a = _register_berg_author()
    author_b = register_author(
        full_name="Nadia Roux",
        email="nadia.roux@uni.example",
        orcid="0000-0003-4444-5555",
        department_code="CEL",
        affiliation_status="ELIGIBLE_POSTDOC",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=300000,
    )
    funder_one = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    funder_two = register_funder(
        name="Nordic Green Foundation",
        funder_code="NGF",
        mandate_type="GREEN_OA",
        max_embargo_months=12,
        deposit_deadline_days=120,
        license_required="ANY",
        apc_allowable=False,
    )
    grant_one = record_grant(
        funder_one["id"],
        author_a["id"],
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )
    grant_two = record_grant(
        funder_two["id"],
        author_a["id"],
        grant_number="NGF-2026-11",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=500000,
    )
    grant_three = record_grant(
        funder_one["id"],
        author_b["id"],
        grant_number="NRC-2026-0452",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=250000,
    )

    author_rows, author_meta = validate_paginated(
        api.list_author_grants(
            author_a["id"], FUND_MANAGER, params={"limit": 10, "offset": 0}
        )
    )
    author_ids = [row["id"] for row in author_rows]
    assert author_meta["total_count"] == 2, (
        f"author A is PI on exactly two grants, got total_count {author_meta['total_count']}"
    )
    assert grant_one["id"] in author_ids and grant_two["id"] in author_ids, (
        f"author A's grants must both appear, got {author_ids!r}"
    )
    assert grant_three["id"] not in author_ids, (
        f"author B's grant must not appear in author A's list, got {author_ids!r}"
    )

    funder_rows, funder_meta = validate_paginated(
        api.list_funder_grants(
            funder_one["id"], FUND_MANAGER, params={"limit": 10, "offset": 0}
        )
    )
    funder_ids = [row["id"] for row in funder_rows]
    assert funder_meta["total_count"] == 2, (
        f"funder one awarded exactly two grants, got total_count {funder_meta['total_count']}"
    )
    assert grant_one["id"] in funder_ids and grant_three["id"] in funder_ids, (
        f"funder one's grants must both appear, got {funder_ids!r}"
    )
    assert grant_two["id"] not in funder_ids, (
        f"the other funder's grant must not appear, got {funder_ids!r}"
    )

    assert read_grant(grant_two["id"])["funder_id"] == funder_two["id"], (
        "the grant excluded from funder one's list belongs to funder two"
    )
    assert read_grant(grant_three["id"])["pi_author_id"] == author_b["id"], (
        "the grant excluded from author A's list has author B as principal investigator"
    )


# --------------------------------------------------------------------------- #
# reading a grant reports the recomputed roll-up
# --------------------------------------------------------------------------- #
def test_grant_read_reports_the_recomputed_output_roll_up(api):
    """A grant with one ingested article and one still awaiting deposit reads
    back output_count 2, compliant_output_count 1 and mandate_status IN_PROGRESS.

    PRD §3.8: "The embargo length in months is zero when the funder's `mandate_type` is `IMMEDIATE_CC_BY`, and otherwise the smaller of the funder's `max_embargo_months` and the journal's `required_embargo_months` — the institution never applies a longer embargo than either party requires."
    PRD §3.8: "Otherwise, if the clock date is **on or after** `embargo_until`, the article is `COMPLIANT`; the embargo releases on its stated date rather than the day after."
    PRD §2.10: "`Grant.output_count` is the number of articles referencing the grant; `Grant.compliant_output_count` is the number of those whose `compliance_status` is `COMPLIANT` or `EXEMPT`."
    PRD §3.8: "Otherwise, if the grant has at least one article and every one of them is `COMPLIANT` or `EXEMPT`, the `mandate_status` is `SATISFIED`."
    PRD §3.8: "In every other case it is `IN_PROGRESS`."
    PRD §2.10: "`Author.linked_output_count` is the number of that author's articles' deposits whose `status` is `INGESTED`, counted across deposits whose article has this author as corresponding author."
    Design: Corner/endpoints/corner_grant_read_reports_the_recomputed_output_roll_up
    """
    set_clock("2026-08-10T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()
    funder = register_funder(
        name="Open Horizon Council",
        funder_code="OHC",
        mandate_type="IMMEDIATE_CC_BY",
        max_embargo_months=0,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="OHC-2026-04",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )
    ingested_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="Ingested immediately",
        accepted_on="2026-08-05",
    )
    pending_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="Still awaiting deposit",
        accepted_on="2026-08-05",
    )
    deposit = create_deposit(
        ingested_article["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        license="CC_BY",
        file_checksum="1a2b3c4d5e6f7081920a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60",
    )
    submit_deposit(deposit["id"], author["id"])
    curated = curate_deposit(deposit["id"], "INGEST")
    assert curated["status"] == "INGESTED", (
        f"the deposit must reach INGESTED, got {curated['status']!r}"
    )

    grant_read = validate_success(api.get_grant(grant["id"], FUND_MANAGER))
    assert grant_read["output_count"] == 2, (
        f"two articles reference the grant, got output_count {grant_read['output_count']}"
    )
    assert grant_read["compliant_output_count"] == 1, (
        "only the ingested article is COMPLIANT, got compliant_output_count "
        f"{grant_read['compliant_output_count']}"
    )
    assert grant_read["mandate_status"] == "IN_PROGRESS", (
        "one article is still PENDING_DEPOSIT, so the mandate is IN_PROGRESS, got "
        f"{grant_read['mandate_status']!r}"
    )
    assert grant_read["status"] == "ACTIVE", (
        f"the award window has not ended, got status {grant_read['status']!r}"
    )

    first = read_article(ingested_article["id"])
    assert first["compliance_status"] == "COMPLIANT", (
        "a zero-month embargo releases at once, got "
        f"{first['compliance_status']!r}"
    )
    assert first["embargo_until"] == "2026-08-05", (
        "a zero-month embargo from accepted_on 2026-08-05 ends the same day, got "
        f"{first['embargo_until']!r}"
    )
    assert read_article(pending_article["id"])["compliance_status"] == "PENDING_DEPOSIT", (
        "the undeposited article stays PENDING_DEPOSIT"
    )
    assert read_author(author["id"])["linked_output_count"] == 1, (
        "exactly one deposit of this author's articles is INGESTED"
    )


# --------------------------------------------------------------------------- #
# the reject branch of the funding decision
# --------------------------------------------------------------------------- #
def test_decision_reject_branch_writes_no_allocation_and_declines_the_article(api):
    """REJECT records the decision, declines the article's funding dimension and
    leaves every fund ledger exactly where it was.

    PRD §3.5: "The decision payload carries a `decision` of either `APPROVE` or `REJECT` and an optional `reason`, and in both branches the acting `X-User-ID` is recorded as `decided_by_user_id` and the supplied reason as `decision_reason`."
    PRD §3.5: "A rejection is the simpler branch and its effects are deliberately narrow: the request moves from `UNDER_REVIEW` to `REJECTED`, the `decision_reason` is recorded, no allocation line is created, and no fund ledger anywhere changes."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `DECLINED`."
    PRD §2.8: "`Author.apc_committed_cents` is the `ENCUMBRANCE_INCLUSIVE` figure for that author in the current fiscal year, and `Author.apc_disbursed_cents` is the `CASH_BASIS` figure for the same scope."
    Design: Corner/endpoints/corner_decision_reject_branch_creates_no_allocations
    """
    scenario = _setup_submitted_fund_request(
        "Rejected on policy grounds", "Requesting central fund support."
    )
    validate_success(
        api.start_fund_request_review(scenario["request"]["id"], LIBRARIAN, payload={})
    )

    decided = validate_success(
        api.decide_fund_request(
            scenario["request"]["id"],
            create_decision_payload(
                "REJECT", "Author has alternative publisher funding."
            ),
            FUND_MANAGER,
        )
    )
    assert decided["status"] == "REJECTED", (
        f"REJECT must move UNDER_REVIEW to REJECTED, got {decided['status']!r}"
    )
    assert decided["decision_reason"] == "Author has alternative publisher funding.", (
        f"the supplied reason must be recorded, got {decided['decision_reason']!r}"
    )
    assert decided["decided_by_user_id"] == "fm-approver-01", (
        "decided_by_user_id must record the acting X-User-ID, got "
        f"{decided['decided_by_user_id']!r}"
    )
    assert decided["fully_funded"] is False, (
        f"a rejected request is not fully funded, got {decided['fully_funded']!r}"
    )

    rows, meta = validate_paginated(
        api.list_fund_request_allocations(
            scenario["request"]["id"], FUND_MANAGER, params={"limit": 10, "offset": 0}
        )
    )
    assert rows == [], f"a rejection writes no allocation line, got {rows!r}"
    assert meta["total_count"] == 0, (
        f"a rejection writes no allocation line, got total_count {meta['total_count']}"
    )

    article = read_article(scenario["article"]["id"])
    assert article["funding_status"] == "DECLINED", (
        f"the rejected article must be DECLINED, got {article['funding_status']!r}"
    )
    fund = read_fund(scenario["fund"]["id"])
    assert fund["committed_cents"] == 0, (
        f"no fund ledger moves on a rejection, got committed_cents {fund['committed_cents']}"
    )
    assert fund["available_cents"] == 500000, (
        f"the fund keeps its whole budget available, got {fund['available_cents']}"
    )
    assert fund["status"] == "OPEN", (
        f"the fund stays OPEN after a rejection, got {fund['status']!r}"
    )
    assert read_author(scenario["author"]["id"])["apc_committed_cents"] == 0, (
        "a rejection encumbers nothing against the author's cap"
    )
