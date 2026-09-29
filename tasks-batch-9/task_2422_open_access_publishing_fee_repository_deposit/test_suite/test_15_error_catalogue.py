"""Error-catalogue corners: authentication before authorisation, one not-found
code per entity, one conflict code per uniqueness rule, and the invoice, fund-flow,
deposit and temporal refusals each reported at their own identifier.

Every test builds its whole world from scratch against an empty database.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_agreement_coverage_payload,
    create_apc_fund_payload,
    create_article_payload,
    create_author_payload,
    create_curation_decision_payload,
    create_decision_payload,
    create_deposit,
    create_freeze_payload,
    create_fund_request_payload,
    create_journal_payload,
    create_publication_payload,
    create_publisher_invoice_payload,
    create_publisher_payload,
    create_repository_deposit_payload,
    create_resubmission_payload,
    create_transformative_agreement_payload,
    draft_agreement,
    freeze_fund,
    make_corresponding_author_headers,
    open_fund,
    open_fund_request,
    pay_invoice,
    publish_article,
    read_article,
    read_deposit,
    read_fund,
    read_fund_request,
    read_publisher,
    receive_invoice,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    start_review,
    submit_deposit,
    validate_error,
    validate_invoice,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["agreement_admin_headers"]
LIBRARIAN = TEST_USERS["librarian_headers"]
FUND_MANAGER = TEST_USERS["fund_manager_headers"]
FUND_PAYER = TEST_USERS["fund_payer_headers"]
CURATOR = TEST_USERS["curator_headers"]

NO_HEADERS: dict = {}
UNDECLARED_ROLE_HEADERS = build_user_headers("provost-office-01", "ProvostOffice")


# --------------------------------------------------------------------------- #
# private preamble helpers
# --------------------------------------------------------------------------- #
def _register_halden_journal(oa_model: str = "FULLY_OA") -> dict:
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model=oa_model,
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


def _register_gold_funder() -> dict:
    return register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )


def _open_central_fund() -> dict:
    return open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=400000,
    )


# --------------------------------------------------------------------------- #
# authentication precedes everything
# --------------------------------------------------------------------------- #
def test_absent_and_undeclared_role_headers_both_return_unauthenticated(api):
    """A request with no identity headers and a request naming a role outside the
    five declared ones both fail authentication, and neither persists a row.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "Authentication is evaluated before authorisation, and both are evaluated before anything else about the request is inspected."
    PRD §3.1: "An `AgreementAdmin` registers a publisher by supplying its legal `name`, which must be between 1 and 200 characters, a short `publisher_code` of between 2 and 16 uppercase alphanumeric characters that must be unique across all publishers and that later appears inside minted DOIs and in negotiation reporting, and a `country_code` of exactly two uppercase letters giving the ISO 3166-1 alpha-2 country of incorporation."
    Design: Corner/errors/corner_missing_role_header_returns_unauthenticated
    """
    payload = create_publisher_payload(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )

    validate_error(
        api.create_publisher(payload, NO_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    validate_error(
        api.create_publisher(payload, UNDECLARED_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    # Neither rejected call may have persisted a publisher: the code is still free.
    accepted = validate_success(
        api.create_publisher(payload, ADMIN), expected_status=201
    )
    assert accepted["publisher_code"] == "MERID", (
        "the publisher_code must still be available after two authentication "
        f"failures, got {accepted['publisher_code']!r}"
    )


# --------------------------------------------------------------------------- #
# authorisation on the funding decision
# --------------------------------------------------------------------------- #
def test_curator_cannot_decide_a_fund_request_but_a_fund_manager_can(api):
    """The decision endpoint refuses a declared-but-unauthorised role, leaving the
    request reviewable, and accepts the identical body from a FundManager.

    PRD §2.1: "If both headers are well-formed but the named role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.5: "The funding decision belongs to a `FundManager`, never to the reviewer."
    PRD §3.5: "Otherwise `FundRequest.approved_cents` is set to that total, `FundRequest.author_share_cents` becomes `requested_cents` less the approved total, and `FundRequest.fully_funded` is true exactly when the approved total equals `requested_cents`."
    PRD §3.5: "The request moves from `UNDER_REVIEW` to `APPROVED`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    Design: Corner/errors/corner_wrong_role_on_a_fund_decision_returns_unauthorized
    """
    set_clock("2026-08-10T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()
    funder = _register_gold_funder()
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )
    fund = _open_central_fund()
    article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="Role gate on the decision endpoint",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(article["id"], basis="PROVISIONAL")
    request = open_fund_request(
        article["id"], author["id"], 300000, justification="Central fund support requested."
    )
    start_review(request["id"])

    validate_error(
        api.decide_fund_request(
            request["id"],
            create_decision_payload("APPROVE", "Curator attempting a funding decision."),
            CURATOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    assert read_fund_request(request["id"])["status"] == "UNDER_REVIEW", (
        "an unauthorised decision attempt must leave the request UNDER_REVIEW"
    )

    approved = validate_success(
        api.decide_fund_request(
            request["id"],
            create_decision_payload("APPROVE", "Approved by the fund manager."),
            FUND_MANAGER,
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the FundManager's identical body must succeed, got {approved['status']!r}"
    )
    assert approved["approved_cents"] == 300000, (
        f"the waterfall must approve the whole 300000, got {approved['approved_cents']}"
    )
    assert read_fund(fund["id"])["committed_cents"] == 300000, (
        "the approved amount must be encumbered against the fund"
    )


# --------------------------------------------------------------------------- #
# one not-found code per entity
# --------------------------------------------------------------------------- #
NOT_FOUND_PROBES = [
    (
        lambda api: api.get_publisher("00000000-0000-4000-8000-000000000001", ADMIN),
        ApiErrorId.ERR_PUBLISHER_NOT_FOUND,
    ),
    (
        lambda api: api.get_journal("00000000-0000-4000-8000-000000000002", ADMIN),
        ApiErrorId.ERR_JOURNAL_NOT_FOUND,
    ),
    (
        lambda api: api.get_transformative_agreement(
            "00000000-0000-4000-8000-000000000003", ADMIN
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND,
    ),
    (
        lambda api: api.list_eligibility_determinations(
            LIBRARIAN,
            params={
                "coverage_id": "00000000-0000-4000-8000-000000000004",
                "limit": 10,
                "offset": 0,
            },
        ),
        ApiErrorId.ERR_COVERAGE_NOT_FOUND,
    ),
    (
        lambda api: api.get_author("00000000-0000-4000-8000-000000000005", ADMIN),
        ApiErrorId.ERR_AUTHOR_NOT_FOUND,
    ),
    (
        lambda api: api.get_funder("00000000-0000-4000-8000-000000000006", ADMIN),
        ApiErrorId.ERR_FUNDER_NOT_FOUND,
    ),
    (
        lambda api: api.get_grant("00000000-0000-4000-8000-000000000007", FUND_MANAGER),
        ApiErrorId.ERR_GRANT_NOT_FOUND,
    ),
    (
        lambda api: api.get_apc_fund(
            "00000000-0000-4000-8000-000000000008", FUND_MANAGER
        ),
        ApiErrorId.ERR_FUND_NOT_FOUND,
    ),
    (
        lambda api: api.get_article("00000000-0000-4000-8000-000000000009", LIBRARIAN),
        ApiErrorId.ERR_ARTICLE_NOT_FOUND,
    ),
    (
        lambda api: api.get_eligibility_determination(
            "00000000-0000-4000-8000-00000000000a", LIBRARIAN
        ),
        ApiErrorId.ERR_DETERMINATION_NOT_FOUND,
    ),
    (
        lambda api: api.get_fund_request(
            "00000000-0000-4000-8000-00000000000b", FUND_MANAGER
        ),
        ApiErrorId.ERR_FUND_REQUEST_NOT_FOUND,
    ),
    (
        lambda api: api.get_publisher_invoice(
            "00000000-0000-4000-8000-00000000000c", FUND_MANAGER
        ),
        ApiErrorId.ERR_INVOICE_NOT_FOUND,
    ),
    (
        lambda api: api.get_repository_deposit(
            "00000000-0000-4000-8000-00000000000d", CURATOR
        ),
        ApiErrorId.ERR_DEPOSIT_NOT_FOUND,
    ),
]


@pytest.mark.parametrize(
    "call, expected_error",
    NOT_FOUND_PROBES,
    ids=[probe[1].value for probe in NOT_FOUND_PROBES],
)
def test_every_entity_lookup_reports_its_own_not_found_code(api, call, expected_error):
    """Against an empty database each entity lookup answers with the not-found
    code minted for that entity, including the coverage id accepted as a filter.

    PRD §2.5: "Each entity has its own not-found code, all of them HTTP 404: `ERR_PUBLISHER_NOT_FOUND`, `ERR_JOURNAL_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_AUTHOR_NOT_FOUND`, `ERR_FUNDER_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_FUND_REQUEST_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`."
    PRD §2.5: "Identifiers supplied as list filters are resolved on the same terms."
    Design: Corner/errors/corner_every_entity_lookup_has_its_own_not_found_code
    """
    error_data = validate_error(call(api), expected_error.value)
    assert error_data["error_id"] == expected_error.value, (
        f"expected {expected_error.value}, got {error_data['error_id']!r}"
    )


# --------------------------------------------------------------------------- #
# one conflict code per uniqueness rule
# --------------------------------------------------------------------------- #
def test_each_uniqueness_rule_reports_its_own_conflict_code(api):
    """Five uniqueness rules, five distinct 409 identifiers — and the duplicate
    agreement code is offered on an abutting window so the overlap rule cannot
    fire in its place.

    PRD §2.11: "**Codes unique.** `publisher_code`, `funder_code`, `fund_code` and `grant_number` are each unique within their own entity — otherwise `ERR_DUPLICATE_CODE` (409)."
    PRD §2.11: "**ISSN unique.** `issn` is unique across journals — otherwise `ERR_DUPLICATE_ISSN` (409)."
    PRD §2.11: "**ORCID unique.** `orcid` is unique among authors that have one; authors without an ORCID iD do not collide with each other. Otherwise `ERR_DUPLICATE_ORCID` (409)."
    PRD §2.11: "**Agreement code unique.** `agreement_code` is unique across transformative agreements — otherwise `ERR_DUPLICATE_AGREEMENT_CODE` (409)."
    PRD §2.11: "**Fund priority unique per year.** The pair of `fiscal_year` and `priority_rank` is unique across APC funds — otherwise `ERR_DUPLICATE_FUND_PRIORITY` (409)."
    PRD §3.2: "Because two agreements with the same publisher must not be in force at once, a draft whose half-open window intersects the half-open window of any other `DRAFT`, `ACTIVE` or `EXHAUSTED` agreement of that publisher is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`; a draft that begins exactly on the day another agreement's window ends is a permitted hand-over rather than an overlap."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    Design: Corner/errors/corner_each_uniqueness_rule_has_its_own_conflict_code
    """
    meridian = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    halden = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        meridian["id"],
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Ilse Vermeer",
        email="ilse.vermeer@uni.example",
        orcid="0000-0002-1111-2222",
        department_code="CEL",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    fund = _open_central_fund()
    agreement = draft_agreement(
        meridian["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2026-10-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    publisher_version = read_publisher(meridian["id"])["version"]
    assert publisher_version == 2, (
        f"drafting an agreement bumps the publisher to version 2, got {publisher_version}"
    )

    validate_error(
        api.create_publisher(
            create_publisher_payload(
                publisher_code="MERID",
                name="Meridian Press Duplicate",
                country_code="NL",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
    )
    validate_error(
        api.create_journal(
            create_journal_payload(
                halden["id"],
                issn="2041-1723",
                title="Halden Journal of Signalling",
                oa_model="FULLY_OA",
                list_apc_cents=300000,
                required_embargo_months=12,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_ISSN.value,
    )
    validate_error(
        api.create_author(
            create_author_payload(
                full_name="Ilse Vermeer Duplicate",
                email="ilse.vermeer.2@uni.example",
                orcid="0000-0002-1111-2222",
                department_code="CEL",
                affiliation_status="ELIGIBLE_FACULTY",
                appointment_from="2024-01-01",
                appointment_until="2028-12-31",
                annual_cap_cents=500000,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_ORCID.value,
    )
    validate_error(
        api.create_transformative_agreement(
            create_transformative_agreement_payload(
                meridian["id"],
                publisher_version,
                agreement_code="TA-MERID-2027",
                effective_from="2026-10-01",
                effective_until="2027-01-01",
                article_quota=5,
                discount_pct=0.20,
                covered_oa_models=["HYBRID"],
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_AGREEMENT_CODE.value,
    )
    validate_error(
        api.create_apc_fund(
            create_apc_fund_payload(
                fund_code="OA-DEPT-2027",
                fiscal_year=2027,
                period_from="2026-07-01",
                period_to="2027-06-30",
                total_budget_cents=200000,
                priority_rank=1,
                eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
                per_article_cap_cents=200000,
            ),
            FUND_MANAGER,
        ),
        ApiErrorId.ERR_DUPLICATE_FUND_PRIORITY.value,
    )
    validate_error(
        api.create_apc_fund(
            create_apc_fund_payload(
                fund_code="OA-CENTRAL-2027",
                fiscal_year=2028,
                period_from="2027-07-01",
                period_to="2028-06-30",
                total_budget_cents=200000,
                priority_rank=9,
                eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
                per_article_cap_cents=200000,
            ),
            FUND_MANAGER,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
    )

    agreements, agreements_meta = validate_paginated(
        api.list_publisher_agreements(
            meridian["id"], ADMIN, params={"limit": 10, "offset": 0}
        )
    )
    assert agreements_meta["total_count"] == 1, (
        "the duplicate draft must not have been written, got total_count "
        f"{agreements_meta['total_count']}"
    )
    assert [row["id"] for row in agreements] == [agreement["id"]], (
        "only the original agreement may exist for Meridian"
    )
    assert read_fund(fund["id"])["priority_rank"] == 1, (
        "the surviving fund keeps priority_rank 1"
    )
    assert validate_success(api.get_journal(journal["id"], ADMIN))["publisher_id"] == (
        meridian["id"]
    ), "the ISSN stays with the journal that claimed it first"
    assert validate_success(api.get_author(author["id"], ADMIN))["orcid"] == (
        "0000-0002-1111-2222"
    ), "the ORCID iD stays with the author that claimed it first"


# --------------------------------------------------------------------------- #
# invoice-side refusals
# --------------------------------------------------------------------------- #
def test_invoice_duplicate_state_currency_and_republication_errors_are_distinct(api):
    """One paid invoice on a published article separates four refusals: duplicate
    number, invalid invoice state, a non-USD currency and a second publication.

    PRD §3.7: "The `invoice_number` must not already have been used by the same publisher, though two different publishers may reuse a number freely; a collision is rejected with `ERR_DUPLICATE_INVOICE_NUMBER`."
    PRD §2.11: "**Invoice state.** Validation requires the invoice's `status` to be `RECEIVED`; payment approval requires `VALIDATED`; payment requires `APPROVED_FOR_PAYMENT`. Otherwise `ERR_INVOICE_INVALID_STATE` (409)."
    PRD §3.7: "Only `USD` is accepted as `currency`; any other value is a malformed request."
    PRD §2.11: "**Request shape.** Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`. Otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.6: "The article must not already have a `publication_date`, or the request is refused with `ERR_ARTICLE_ALREADY_PUBLISHED`."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.7: "Otherwise, if `variance_cents` is exactly zero the outcome is `MATCH`."
    Design: Corner/errors/corner_invoice_errors_cover_duplicate_currency_state_and_republication
    """
    set_clock("2026-08-12T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()

    first_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        manuscript_title="Invoice error surface, first article",
        accepted_on="2026-08-05",
    )
    first_determination = run_eligibility_check(first_article["id"], basis="PROVISIONAL")
    assert first_determination["route"] == "AUTHOR_PAYS", (
        "an unfunded article at an uncovered journal routes AUTHOR_PAYS, got "
        f"{first_determination['route']!r}"
    )
    second_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        manuscript_title="Invoice error surface, second article",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(second_article["id"], basis="PROVISIONAL")

    invoice = receive_invoice(
        base["publisher"]["id"],
        first_article["id"],
        "HALDEN-5001",
        300000,
        0.0,
        0.0,
        "2026-08-12",
    )
    assert invoice["validation_outcome"] == "MATCH", (
        f"a bill equal to the expected amount is a MATCH, got {invoice['validation_outcome']!r}"
    )
    validate_invoice(invoice["id"])
    validate_success(
        api.approve_publisher_invoice_payment(invoice["id"], FUND_MANAGER, payload={})
    )
    paid = pay_invoice(invoice["id"], "WIRE-77001")
    assert paid["status"] == "PAID", (
        f"the invoice must reach PAID, got {paid['status']!r}"
    )
    published = publish_article(first_article["id"], "2026-08-12")
    assert published.get("doi") is not None, "publication must mint a DOI"

    validate_error(
        api.create_publisher_invoice(
            create_publisher_invoice_payload(
                base["publisher"]["id"],
                second_article["id"],
                "HALDEN-5001",
                300000,
                0.0,
                0.0,
                "2026-08-12",
            ),
            LIBRARIAN,
        ),
        ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER.value,
    )
    validate_error(
        api.validate_publisher_invoice(invoice["id"], LIBRARIAN, payload={}),
        ApiErrorId.ERR_INVOICE_INVALID_STATE.value,
    )
    validate_error(
        api.create_publisher_invoice(
            create_publisher_invoice_payload(
                base["publisher"]["id"],
                second_article["id"],
                "HALDEN-5002",
                300000,
                0.0,
                0.0,
                "2026-08-12",
                currency="EUR",
            ),
            LIBRARIAN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.publish_article(
            first_article["id"], create_publication_payload("2026-08-20"), LIBRARIAN
        ),
        ApiErrorId.ERR_ARTICLE_ALREADY_PUBLISHED.value,
    )

    assert validate_success(
        api.get_publisher_invoice(invoice["id"], LIBRARIAN)
    )["status"] == "PAID", "the paid invoice is untouched by the failed re-validation"
    assert read_article(first_article["id"])["publication_date"] == "2026-08-12", (
        "the original publication_date must survive the second attempt"
    )
    _, invoices_meta = validate_paginated(
        api.list_publisher_invoices(
            LIBRARIAN,
            params={
                "publisher_id": base["publisher"]["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert invoices_meta["total_count"] == 1, (
        f"no rejected invoice may have been written, got {invoices_meta['total_count']}"
    )


# --------------------------------------------------------------------------- #
# fund-flow refusals
# --------------------------------------------------------------------------- #
def test_fund_flow_eligibility_amount_state_and_freeze_errors_are_distinct(api):
    """Five fund-flow refusals on one dataset: no determination, one cent over the
    ceiling, a resubmission from the wrong state, a second freeze and an
    unfunded article at payment approval.

    PRD §3.5: "The request is admitted only when an effective determination exists for the article and its `eligible_request_cents` is greater than zero — otherwise `ERR_ELIGIBILITY_NOT_DETERMINED` — and only when `requested_cents` does not exceed that `eligible_request_cents`, an excess being rejected with `ERR_REQUEST_EXCEEDS_ELIGIBLE`."
    PRD §3.5: "The author answers by resubmitting, which requires the request to be in `INFO_REQUESTED` — any other state yields `ERR_REQUEST_NOT_RESUBMITTABLE` — and which supplies a fresh `requested_cents` together with a `response_note`."
    PRD §3.3: "A `FundManager` may freeze a fund manually by supplying a `reason`, which is recorded verbatim as `freeze_reason`; the fund must currently be `OPEN`, or the request is rejected with `ERR_FUND_FROZEN`."
    PRD §3.7: "A `FundManager` approves a `VALIDATED` invoice for payment, which requires the invoiced article's `funding_status` to be one of `FUNDED`, `PARTIALLY_FUNDED` or `SELF_FUNDED` — an article still in `DRAFT`, `ELIGIBILITY_CHECKED`, `FUNDING_REQUESTED` or `DECLINED` yields `ERR_ARTICLE_NOT_FUNDED` — and which moves the invoice from `VALIDATED` to `APPROVED_FOR_PAYMENT` while recording the acting `X-User-ID` as `payment_approved_by_user_id`."
    PRD §3.4: "If it qualifies, the `route` is `FUND_APC`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is likewise the whole `list_base_cents`, and `determination_reason` is `NO_COVERAGE_FUND_ELIGIBLE`."
    Design: Corner/errors/corner_fund_flow_errors_cover_eligibility_amount_state_and_freeze
    """
    set_clock("2026-08-12T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()
    funder = _register_gold_funder()
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )
    fund = _open_central_fund()
    frozen = freeze_fund(fund["id"], "AUDIT_HOLD")
    assert frozen["status"] == "FROZEN", (
        f"the manual freeze must move the fund to FROZEN, got {frozen['status']!r}"
    )
    assert frozen["freeze_reason"] == "AUDIT_HOLD", (
        f"the supplied reason is recorded verbatim, got {frozen['freeze_reason']!r}"
    )

    undetermined_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="No determination yet",
        accepted_on="2026-08-05",
    )
    assert undetermined_article["determination_count"] == 0, (
        "a fresh article carries no determination, got "
        f"{undetermined_article['determination_count']}"
    )
    determined_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="Determined and requested",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(determined_article["id"], basis="PROVISIONAL")
    assert determination["eligible_request_cents"] == 300000, (
        "the fund route may request the whole list charge, got "
        f"{determination['eligible_request_cents']}"
    )
    over_ceiling_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="One cent over the ceiling",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(over_ceiling_article["id"], basis="PROVISIONAL")
    request = open_fund_request(
        determined_article["id"],
        author["id"],
        300000,
        justification="Central fund support requested.",
    )
    assert request["status"] == "SUBMITTED", (
        f"a new request starts SUBMITTED, got {request['status']!r}"
    )
    invoice = receive_invoice(
        base["publisher"]["id"],
        determined_article["id"],
        "HALDEN-6001",
        300000,
        0.0,
        0.0,
        "2026-08-12",
    )
    validated = validate_invoice(invoice["id"])
    assert validated["status"] == "VALIDATED", (
        f"a matching invoice validates, got {validated['status']!r}"
    )

    author_headers = make_corresponding_author_headers(author["id"])
    validate_error(
        api.create_fund_request(
            create_fund_request_payload(
                undetermined_article["id"],
                100000,
                justification="No determination has been run.",
            ),
            author_headers,
        ),
        ApiErrorId.ERR_ELIGIBILITY_NOT_DETERMINED.value,
    )
    validate_error(
        api.create_fund_request(
            create_fund_request_payload(
                over_ceiling_article["id"],
                300001,
                justification="One cent above the ceiling.",
            ),
            author_headers,
        ),
        ApiErrorId.ERR_REQUEST_EXCEEDS_ELIGIBLE.value,
    )
    validate_error(
        api.create_fund_request_resubmission(
            request["id"],
            create_resubmission_payload(
                200000, response_note="Resubmitting without an information request."
            ),
            author_headers,
        ),
        ApiErrorId.ERR_REQUEST_NOT_RESUBMITTABLE.value,
    )
    validate_error(
        api.freeze_apc_fund(fund["id"], create_freeze_payload("AUDIT_HOLD"), FUND_MANAGER),
        ApiErrorId.ERR_FUND_FROZEN.value,
    )
    validate_error(
        api.approve_publisher_invoice_payment(invoice["id"], FUND_MANAGER, payload={}),
        ApiErrorId.ERR_ARTICLE_NOT_FUNDED.value,
    )

    unchanged = read_fund_request(request["id"])
    assert unchanged["status"] == "SUBMITTED", (
        f"the refused resubmission leaves the request SUBMITTED, got {unchanged['status']!r}"
    )
    assert unchanged["requested_cents"] == 300000, (
        f"the refused resubmission leaves the amount at 300000, got {unchanged['requested_cents']}"
    )
    assert unchanged["revision_round"] == 0, (
        f"the refused resubmission closes no revision cycle, got {unchanged['revision_round']}"
    )
    assert validate_success(
        api.get_publisher_invoice(invoice["id"], LIBRARIAN)
    )["status"] == "VALIDATED", "the refused approval leaves the invoice VALIDATED"
    assert read_article(determined_article["id"])["funding_status"] == (
        "FUNDING_REQUESTED"
    ), "the article stays FUNDING_REQUESTED throughout"
    _, requests_meta = validate_paginated(
        api.list_article_fund_requests(
            determined_article["id"], FUND_MANAGER, params={"limit": 10, "offset": 0}
        )
    )
    assert requests_meta["total_count"] == 1, (
        f"the one admitted request is the only one, got {requests_meta['total_count']}"
    )
    _, refused_meta = validate_paginated(
        api.list_article_fund_requests(
            over_ceiling_article["id"], FUND_MANAGER, params={"limit": 10, "offset": 0}
        )
    )
    assert refused_meta["total_count"] == 0, (
        f"the over-ceiling request wrote nothing, got {refused_meta['total_count']}"
    )
    assert read_article(over_ceiling_article["id"])["funding_status"] == (
        "ELIGIBILITY_CHECKED"
    ), "the refused request leaves that article at ELIGIBILITY_CHECKED"


# --------------------------------------------------------------------------- #
# deposit-side refusals
# --------------------------------------------------------------------------- #
def test_deposit_license_orcid_and_open_version_errors_are_distinct(api):
    """Three deposit refusals: a licence the mandate forbids, an ingest without an
    ORCID iD, and a second open deposit while one is still DRAFT.

    PRD §3.8: "The chosen `license` must satisfy the funder's `license_required` as spelled out in rule 16 of §2.11, or the deposit is refused with `ERR_LICENSE_NOT_PERMITTED`."
    PRD §2.11: "**Deposit licence permitted.** The deposit's `license` satisfies the funder's `license_required`: a requirement of `CC_BY` admits only `CC_BY`; a requirement of `CC_BY_OR_NC` admits `CC_BY` or `CC_BY_NC`; a requirement of `ANY` admits every licence value."
    PRD §3.8: "Ingesting the deposit is the moment the institution takes custody, and it first requires author profile linkage: the article's corresponding author must have a non-null `orcid`, or the ingest is refused with `ERR_ORCID_REQUIRED`."
    PRD §3.8: "At most one deposit per article may be open at a time — that is, sitting in `DRAFT` or `SUBMITTED` — so a second open deposit is refused with `ERR_DEPOSIT_VERSION_CONFLICT`."
    PRD §3.8: "The author submits the draft for curation, which requires the deposit to be in `DRAFT` and which moves it from `DRAFT` to `SUBMITTED` while stamping `submitted_at` from the logical clock."
    Design: Corner/errors/corner_deposit_errors_cover_license_orcid_and_open_version
    """
    set_clock("2026-08-12T00:00:00Z", ADMIN)
    base = _register_halden_journal()
    author = _register_berg_author()
    author_without_orcid = register_author(
        full_name="Anon Contributor",
        email="anon.contributor@uni.example",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    assert author_without_orcid.get("orcid") is None, (
        "the second author must carry no ORCID iD, got "
        f"{author_without_orcid.get('orcid')!r}"
    )
    funder = _register_gold_funder()
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )

    licence_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="License gate",
        accepted_on="2026-08-05",
    )
    orcid_article = record_article(
        base["journal"]["id"],
        author_without_orcid["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="Profile linkage gate",
        accepted_on="2026-08-05",
    )
    open_draft_article = record_article(
        base["journal"]["id"],
        author["id"],
        headers=LIBRARIAN,
        grant_id=grant["id"],
        manuscript_title="Open draft gate",
        accepted_on="2026-08-05",
    )

    orcid_deposit = create_deposit(
        orcid_article["id"],
        author_without_orcid["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        license="CC_BY",
        file_checksum="aa11bb22cc33dd44ee55ff6677889900aa11bb22cc33dd44ee55ff6677889900",
    )
    submitted = submit_deposit(orcid_deposit["id"], author_without_orcid["id"])
    assert submitted["status"] == "SUBMITTED", (
        f"the deposit must reach SUBMITTED before curation, got {submitted['status']!r}"
    )
    open_draft = create_deposit(
        open_draft_article["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        license="CC_BY",
        file_checksum="bb22cc33dd44ee55ff6677889900aa11bb22cc33dd44ee55ff6677889900aa11",
    )
    assert open_draft["status"] == "DRAFT", (
        f"a created deposit starts DRAFT, got {open_draft['status']!r}"
    )
    open_draft_article_now = read_article(open_draft_article["id"])
    assert open_draft_article_now["latest_deposit_ordinal"] == 1, (
        "the first deposit takes ordinal 1, got "
        f"{open_draft_article_now['latest_deposit_ordinal']}"
    )

    validate_error(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                licence_article["id"],
                licence_article["version"],
                version_label="ACCEPTED_MANUSCRIPT",
                file_checksum="cc33dd44ee55ff6677889900aa11bb22cc33dd44ee55ff6677889900aa11bb22",
                license="CC_BY_NC_ND",
            ),
            make_corresponding_author_headers(author["id"]),
        ),
        ApiErrorId.ERR_LICENSE_NOT_PERMITTED.value,
    )
    validate_error(
        api.decide_repository_deposit_curation(
            orcid_deposit["id"], create_curation_decision_payload("INGEST"), CURATOR
        ),
        ApiErrorId.ERR_ORCID_REQUIRED.value,
    )
    validate_error(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                open_draft_article["id"],
                open_draft_article_now["version"],
                version_label="VERSION_OF_RECORD",
                file_checksum="dd44ee55ff6677889900aa11bb22cc33dd44ee55ff6677889900aa11bb22cc33",
                license="CC_BY",
            ),
            make_corresponding_author_headers(author["id"]),
        ),
        ApiErrorId.ERR_DEPOSIT_VERSION_CONFLICT.value,
    )

    still_submitted = read_deposit(orcid_deposit["id"])
    assert still_submitted["status"] == "SUBMITTED", (
        f"a refused ingest leaves the deposit SUBMITTED, got {still_submitted['status']!r}"
    )
    assert still_submitted.get("persistent_identifier") is None, (
        "a refused ingest mints no persistent identifier, got "
        f"{still_submitted.get('persistent_identifier')!r}"
    )
    assert read_article(orcid_article["id"])["compliance_status"] == "PENDING_DEPOSIT", (
        "a refused ingest leaves the compliance dimension at PENDING_DEPOSIT"
    )
    _, licence_meta = validate_paginated(
        api.list_article_deposits(
            licence_article["id"], CURATOR, params={"limit": 10, "offset": 0}
        )
    )
    assert licence_meta["total_count"] == 0, (
        f"the refused licence wrote no deposit, got total_count {licence_meta['total_count']}"
    )
    _, open_meta = validate_paginated(
        api.list_article_deposits(
            open_draft_article["id"], CURATOR, params={"limit": 10, "offset": 0}
        )
    )
    assert open_meta["total_count"] == 1, (
        f"the article keeps its single open deposit, got total_count {open_meta['total_count']}"
    )


# --------------------------------------------------------------------------- #
# temporal and referential inputs
# --------------------------------------------------------------------------- #
def test_temporal_and_referential_inputs_are_rejected_at_their_own_codes(api):
    """An acceptance a day past the appointment, a coverage line naming another
    publisher's journal, and a zero-length agreement window each land on their
    own identifier.

    PRD §3.4: "The `accepted_on` date must fall inside the corresponding author's closed appointment window; an acceptance dated before `appointment_from` or after `appointment_until` is rejected with `ERR_APPOINTMENT_WINDOW_EXPIRED`."
    PRD §3.2: "The journal named must belong to the same publisher as the agreement, or the line is rejected with `ERR_COVERAGE_JOURNAL_PUBLISHER_MISMATCH`."
    PRD §3.2: "The agreement's window is half-open: `effective_from` is included and `effective_until` is excluded, and `effective_until` must be strictly after `effective_from`."
    PRD §2.11: "**Request shape.** Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`. Otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    Design: Corner/errors/corner_temporal_and_referential_inputs_are_rejected_at_their_own_codes
    """
    meridian = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    halden = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    halden_version = halden["version"]
    meridian_journal = register_journal(
        meridian["id"],
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    halden_journal = register_journal(
        halden["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="HYBRID",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    expiring_author = register_author(
        full_name="Rosa Delgado",
        email="rosa.delgado@uni.example",
        orcid="0000-0004-8888-9999",
        department_code="CEL",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2026-07-04",
        annual_cap_cents=500000,
    )
    agreement = draft_agreement(
        meridian["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    assert read_publisher(meridian["id"])["version"] == 2, (
        "drafting an agreement bumps the publisher to version 2"
    )

    validate_error(
        api.create_article(
            create_article_payload(
                meridian_journal["id"],
                expiring_author["id"],
                manuscript_title="One day past the appointment",
                accepted_on="2026-07-05",
            ),
            LIBRARIAN,
        ),
        ApiErrorId.ERR_APPOINTMENT_WINDOW_EXPIRED.value,
    )
    validate_error(
        api.create_agreement_coverage(
            agreement["id"],
            create_agreement_coverage_payload(
                halden_journal["id"],
                coverage_type="FULL_APC",
                covered_from="2026-07-01",
                covered_until="2027-06-30",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_COVERAGE_JOURNAL_PUBLISHER_MISMATCH.value,
    )
    validate_error(
        api.create_transformative_agreement(
            create_transformative_agreement_payload(
                halden["id"],
                halden_version,
                agreement_code="TA-HALDEN-2027",
                effective_from="2026-07-01",
                effective_until="2026-07-01",
                article_quota=5,
                discount_pct=0.10,
                covered_oa_models=["HYBRID"],
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, coverage_meta = validate_paginated(
        api.list_agreement_coverages(
            agreement["id"], ADMIN, params={"limit": 10, "offset": 0}
        )
    )
    assert coverage_meta["total_count"] == 0, (
        f"the mismatched coverage line wrote nothing, got {coverage_meta['total_count']}"
    )
    _, article_meta = validate_paginated(
        api.list_articles(LIBRARIAN, params={"limit": 10, "offset": 0})
    )
    assert article_meta["total_count"] == 0, (
        f"the refused acceptance wrote no article, got {article_meta['total_count']}"
    )
