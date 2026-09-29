"""Request-validation corner cases: window boundaries that must be accepted, the
ordering of rejection reasons, conditional field requirements and pagination
bounds.

Every test builds its own world from an empty database and drives the logical
clock explicitly.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_agreement_coverage_payload,
    create_article_payload,
    create_fund_request_payload,
    draft_agreement,
    make_corresponding_author_headers,
    open_fund,
    read_article,
    read_fund,
    read_grant,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    setup_publisher_with_journal,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# closed-window boundaries
# --------------------------------------------------------------------------- #
def test_acceptance_on_both_closed_window_ends_is_accepted(api, librarian_headers):
    """An acceptance date equal to both the appointment end and the award end passes.

    PRD §3.4: "The `accepted_on` date must fall inside the corresponding author's closed appointment window; an acceptance dated before `appointment_from` or after `appointment_until` is rejected with `ERR_APPOINTMENT_WINDOW_EXPIRED`."
    PRD §3.4: "And when a grant is named, that grant must be `ACTIVE` and `accepted_on` must fall inside the closed award window from `award_from` through `award_until`; otherwise the acceptance is rejected with `ERR_GRANT_NOT_ACTIVE`."
    PRD §3.4: "A newly recorded article always starts with `funding_status` `DRAFT`, while its `compliance_status` is set at creation to either `PENDING_DEPOSIT` or `EXEMPT` by the mandate rule described in §3.8, which also sets `deposit_deadline_on` and `embargo_until`."
    PRD §3.8: "If the article names no grant, or if the grant's funder has a `mandate_type` of `NONE`, the article is `EXEMPT` outright with no `deposit_deadline_on` and no `embargo_until`; an exempt article never enters the sweep and counts as satisfying its grant for roll-up purposes."
    PRD §3.8: "The `deposit_deadline_on` is the article's `accepted_on` advanced by the funder's `deposit_deadline_days` in whole calendar days."
    PRD §3.4: "When a `grant_id` is supplied, the grant's `output_count` and `mandate_status` are recomputed as part of the same request."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    PRD §3.8: "`Grant.output_count` is the number of articles referencing the grant and `Grant.compliant_output_count` is how many of those are `COMPLIANT` or `EXEMPT`."
    PRD §3.8: "In every other case it is `IN_PROGRESS`."
    Design: Corner/validations/corner_accepted_on_sitting_on_both_closed_window_ends_passes
    """
    set_clock("2026-08-31T00:00:00Z")
    base = setup_publisher_with_journal(
        publisher_code="HALDEN",
        publisher_name="Halden Open Science",
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
        appointment_until="2026-08-31",
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
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2026-08-31",
    )

    article = validate_success(
        api.create_article(
            create_article_payload(
                base["journal"]["id"],
                author["id"],
                manuscript_title="Accepted on the last day of both windows",
                accepted_on="2026-08-31",
                grant_id=grant["id"],
            ),
            librarian_headers,
        ),
        expected_status=201,
    )

    assert article["funding_status"] == "DRAFT", (
        f"a new article starts in DRAFT, got {article['funding_status']!r}"
    )
    assert article["compliance_status"] == "PENDING_DEPOSIT", (
        "the article names a grant whose funder does not mandate NONE, so it is not "
        f"exempt and starts in PENDING_DEPOSIT, got {article['compliance_status']!r}"
    )
    assert article["deposit_deadline_on"] == "2026-11-29", (
        "2026-08-31 advanced by the funder's ninety calendar days is 2026-11-29, got "
        f"{article['deposit_deadline_on']!r}"
    )
    assert article["determination_count"] == 0, (
        f"a new article has no determinations, got {article['determination_count']}"
    )

    grant_after = read_grant(grant["id"])
    assert grant_after["output_count"] == 1, (
        f"the new article references the grant, got {grant_after['output_count']}"
    )
    assert grant_after["mandate_status"] == "IN_PROGRESS", (
        "the single article is neither COMPLIANT nor EXEMPT and has not breached, got "
        f"{grant_after['mandate_status']!r}"
    )


# --------------------------------------------------------------------------- #
# rejection precedence
# --------------------------------------------------------------------------- #
def test_role_check_outranks_existence_which_outranks_body_shape(
    api, corresponding_author_headers, fund_manager_headers
):
    """Freezing a fund reports the role failure, then the missing fund, then the missing reason.

    PRD §2.11: "The rules are listed here in evaluation order, lowest number first; the first rule that fails produces the response, and no later rule is evaluated."
    PRD §2.1: "If both headers are well-formed but the named role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.11: "2. **Authorisation.** The acting role appears in the called endpoint's role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.11: "3. **Existence.** Path identifiers resolve left to right, then body foreign keys resolve in the order the endpoint declares its inputs — otherwise the matching not-found code from §2.5 (404). Applies to every endpoint that carries a path identifier or a foreign-key body field."
    PRD §2.11: "5. **Request shape.** Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD §2.5: "Requests are checked for the existence of everything they reference before any business rule is evaluated."
    PRD §2.5: "Because resolution precedes business logic, a request that names a non-existent article *and* violates a state rule is reported as a 404, not as a conflict."
    PRD §3.3: "On opening, `status` is `OPEN`, `committed_cents` and `spent_cents` are zero, `available_cents` equals `total_budget_cents`, and `freeze_reason` is absent."
    PRD §3.3: "A `FundManager` may freeze a fund manually by supplying a `reason`, which is recorded verbatim as `freeze_reason`; the fund must currently be `OPEN`, or the request is rejected with `ERR_FUND_FROZEN`."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    Design: Corner/validations/corner_unauthorized_role_outranks_existence_which_outranks_shape
    """
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=500000,
    )
    assert fund["status"] == "OPEN", (
        f"a newly opened fund is OPEN, got {fund['status']!r}"
    )

    validate_error(
        api.freeze_apc_fund(NON_EXISTENT_UUID, {}, corresponding_author_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api.freeze_apc_fund(NON_EXISTENT_UUID, {}, fund_manager_headers),
        ApiErrorId.ERR_FUND_NOT_FOUND.value,
    )
    validate_error(
        api.freeze_apc_fund(fund["id"], {}, fund_manager_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    unchanged = read_fund(fund["id"])
    assert unchanged["status"] == "OPEN", (
        f"none of the three rejected calls froze the fund, got {unchanged['status']!r}"
    )
    assert unchanged.get("freeze_reason") is None, (
        "no freeze reason was ever recorded, got "
        f"{unchanged.get('freeze_reason')!r}"
    )
    assert unchanged["version"] == 1, (
        "a rejected call is not a mutation, so the version is still 1, got "
        f"{unchanged['version']}"
    )


def test_unknown_article_is_reported_before_the_ownership_check(api):
    """A fund request naming an unknown article is not-found; naming someone else's is a forbidden owner.

    PRD §2.11: "3. **Existence.** Path identifiers resolve left to right, then body foreign keys resolve in the order the endpoint declares its inputs — otherwise the matching not-found code from §2.5 (404). Applies to every endpoint that carries a path identifier or a foreign-key body field."
    PRD §2.11: "4. **Ownership.** When `X-User-Role` is `CorrespondingAuthor`, `X-User-ID` equals the target article's `corresponding_author_id`, reached directly, or through the article of a fund request, or through the article of a deposit; on article creation it must equal the supplied `corresponding_author_id` — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to seven operations: `POST /articles`, `POST /articles/{id}/eligibility-checks`, `POST /fund-requests`, `POST /fund-requests/{id}/resubmissions`, `POST /fund-requests/{id}/withdrawal`, `POST /repository-deposits` and `POST /repository-deposits/{id}/submission`."
    PRD §2.5: "Requests are checked for the existence of everything they reference before any business rule is evaluated."
    PRD §2.5: "Each entity has its own not-found code, all of them HTTP 404: `ERR_PUBLISHER_NOT_FOUND`, `ERR_JOURNAL_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_AUTHOR_NOT_FOUND`, `ERR_FUNDER_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_FUND_REQUEST_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`."
    PRD §2.5: "Because resolution precedes business logic, a request that names a non-existent article *and* violates a state rule is reported as a 404, not as a conflict."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "This ownership check applies when a `CorrespondingAuthor` records an accepted manuscript (where the supplied `corresponding_author_id` must be the caller's own identifier), runs an eligibility check on an article, creates a fund request, resubmits one, withdraws one, creates a repository deposit, or submits a deposit for curation."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.4: "The funding dimension then follows the route: a `TA_FULL` route sets `funding_status` to `FUNDED`; a `TA_CAPPED` route sets it to `ELIGIBILITY_CHECKED` when `eligible_request_cents` is greater than zero and to `SELF_FUNDED` when `eligible_request_cents` is zero; a `FUND_APC` route sets it to `ELIGIBILITY_CHECKED`; an `AUTHOR_PAYS` route sets it to `SELF_FUNDED`."
    Design: Corner/validations/corner_unknown_article_id_returns_not_found_before_the_owner_check
    """
    base = setup_publisher_with_journal(
        publisher_code="HALDEN",
        publisher_name="Halden Open Science",
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    owner = register_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    stranger = register_author(
        full_name="Nadia Roux",
        email="nadia.roux@uni.example",
        orcid="0000-0003-4444-5555",
        department_code="CHE",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    article = record_article(
        base["journal"]["id"],
        owner["id"],
        manuscript_title="Owned by author A",
        accepted_on="2026-07-20",
    )
    determination = run_eligibility_check(article["id"], owner["id"], basis="PROVISIONAL")
    assert determination["route"] == "AUTHOR_PAYS", (
        "no grant and no agreement means the author pays, got "
        f"{determination['route']!r}"
    )
    assert read_article(article["id"])["funding_status"] == "SELF_FUNDED", (
        "an AUTHOR_PAYS outcome moves the article to SELF_FUNDED"
    )

    stranger_headers = make_corresponding_author_headers(stranger["id"])

    validate_error(
        api.create_fund_request(
            create_fund_request_payload(
                NON_EXISTENT_UUID,
                100000,
                justification="Article id does not exist.",
            ),
            stranger_headers,
        ),
        ApiErrorId.ERR_ARTICLE_NOT_FOUND.value,
    )
    validate_error(
        api.create_fund_request(
            create_fund_request_payload(
                article["id"],
                100000,
                justification="Article belongs to another author.",
            ),
            stranger_headers,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )


# --------------------------------------------------------------------------- #
# conditional field requirements
# --------------------------------------------------------------------------- #
def test_capped_amount_is_required_only_for_capped_coverage(api, agreement_admin_headers):
    """CAPPED_APC without a cap and READ_ONLY with one are both rejected; the valid pair passes.

    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    PRD §3.2: "A coverage line names a `journal_id`, a `coverage_type` of `FULL_APC`, `CAPPED_APC` or `READ_ONLY`, an optional `capped_amount_cents`, and a `covered_from` and `covered_until` pair whose window is closed at both ends."
    PRD §3.2: "`CAPPED_APC` means the agreement pays up to a per-article ceiling, and for this type `capped_amount_cents` is required and must be greater than zero; for the other two types it must be absent."
    PRD §2.11: "5. **Request shape.** Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    Design: Corner/validations/corner_capped_amount_field_conditional_requirement_rejects_both_mismatches
    """
    base = setup_publisher_with_journal(
        publisher_code="MERID",
        publisher_name="Meridian Academic Press",
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    register_journal(
        base["publisher"]["id"],
        issn="2050-084X",
        title="Meridian Journal of Marine Ecology",
        oa_model="HYBRID",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    agreement = draft_agreement(
        base["publisher"]["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    assert agreement["status"] == "DRAFT", (
        f"a newly drafted agreement has status DRAFT, got {agreement['status']!r}"
    )

    validate_error(
        api.create_agreement_coverage(
            agreement["id"],
            create_agreement_coverage_payload(
                base["journal"]["id"],
                coverage_type="CAPPED_APC",
                covered_from="2026-07-01",
                covered_until="2027-06-30",
            ),
            agreement_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.create_agreement_coverage(
            agreement["id"],
            create_agreement_coverage_payload(
                base["journal"]["id"],
                coverage_type="READ_ONLY",
                covered_from="2026-07-01",
                covered_until="2027-06-30",
                capped_amount_cents=150000,
            ),
            agreement_admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    coverage = validate_success(
        api.create_agreement_coverage(
            agreement["id"],
            create_agreement_coverage_payload(
                base["journal"]["id"],
                coverage_type="CAPPED_APC",
                covered_from="2026-07-01",
                covered_until="2027-06-30",
                capped_amount_cents=150000,
            ),
            agreement_admin_headers,
        ),
        expected_status=201,
    )
    assert coverage["coverage_type"] == "CAPPED_APC", (
        f"the accepted pair keeps its coverage type, got {coverage['coverage_type']!r}"
    )
    assert coverage["capped_amount_cents"] == 150000, (
        "the supplied cap is stored, got " f"{coverage['capped_amount_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_agreement_coverages(
            agreement["id"], agreement_admin_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        "the two rejected calls stored nothing, so only one coverage line exists, got "
        f"total_count {meta['total_count']}"
    )
    assert len(rows) == 1, f"expected exactly one coverage line, got {len(rows)}"


# --------------------------------------------------------------------------- #
# pagination bounds
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "limit, offset, expected_row_count",
    [
        pytest.param(0, 0, None, id="limit-below-one"),
        pytest.param(101, 0, None, id="limit-above-one-hundred"),
        pytest.param(10, -1, None, id="negative-offset"),
        pytest.param(1, 1, 1, id="limit-one-offset-one"),
        pytest.param(100, 0, 2, id="limit-at-the-upper-bound"),
    ],
)
def test_pagination_bounds_outside_the_declared_range_are_rejected(
    api, librarian_headers, limit, offset, expected_row_count
):
    """limit must sit in 1..100 and offset must be non-negative; the inclusive edges work.

    PRD §2.3: "`limit` controls the page size: it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100."
    PRD §2.3: "`offset` controls how many rows are skipped before the page begins: it defaults to 0 and may be no smaller than 0."
    PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.3: "When a list endpoint responds, the `meta` object carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before pagination was applied, and `has_more` as a boolean that is true exactly when rows matching the filters remain beyond the current page."
    PRD §2.11: "5. **Request shape.** Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    Design: Corner/validations/corner_pagination_bounds_outside_the_declared_range_are_rejected
    """
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    register_journal(
        publisher["id"],
        issn="2397-3374",
        title="Halden Journal of Marine Chemistry",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )

    response = api.list_publisher_journals(
        publisher["id"], librarian_headers, params={"limit": limit, "offset": offset}
    )

    if expected_row_count is None:
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        return

    rows, meta = validate_paginated(response)
    assert len(rows) == expected_row_count, (
        f"limit {limit} at offset {offset} should return {expected_row_count} "
        f"journal(s), got {len(rows)}"
    )
    assert meta["limit"] == limit, (
        f"meta echoes the requested limit, got {meta['limit']}"
    )
    assert meta["offset"] == offset, (
        f"meta echoes the requested offset, got {meta['offset']}"
    )
    assert meta["total_count"] == 2, (
        f"the publisher owns two journals, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        "no matching row remains beyond this page, got "
        f"has_more {meta['has_more']!r}"
    )
