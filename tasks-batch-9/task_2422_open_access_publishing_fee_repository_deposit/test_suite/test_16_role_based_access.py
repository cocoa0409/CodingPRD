"""Role-based access control.

Covers the endpoints that admit exactly one role, the endpoints that admit two
declared roles, the identity comparison that keeps approving and paying an
invoice in two different hands, and the split of the deposit workflow between the
author who deposits and the curator who decides.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_apc_fund_payload,
    create_article_payload,
    create_curation_decision_payload,
    create_payment_payload,
    create_repository_deposit_payload,
    create_deposit,
    approve_invoice_for_payment,
    list_article_deposits,
    make_corresponding_author_headers,
    read_article,
    read_deposit,
    read_invoice,
    receive_invoice,
    record_article,
    register_author,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    validate_error,
    validate_invoice,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["agreement_admin_headers"]
LIBRARIAN_HEADERS = TEST_USERS["librarian_headers"]
FUND_MANAGER_HEADERS = TEST_USERS["fund_manager_headers"]
CURATOR_HEADERS = TEST_USERS["curator_headers"]
UNRELATED_AUTHOR_HEADERS = TEST_USERS["corresponding_author_headers"]
FUND_APPROVER_HEADERS = TEST_USERS["fund_solo_headers"]
FUND_PAYER_HEADERS = TEST_USERS["fund_other_headers"]

FUND_PAYLOAD = create_apc_fund_payload(
    fund_code="OA-CENTRAL-2027",
    fiscal_year=2027,
    period_from="2026-07-01",
    period_to="2027-06-30",
    total_budget_cents=500000,
    priority_rank=1,
    eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
    per_article_cap_cents=400000,
)

ROLES_BARRED_FROM_FUND_CREATION = [
    ("AgreementAdmin", ADMIN_HEADERS),
    ("ScholCommLibrarian", LIBRARIAN_HEADERS),
    ("RepositoryCurator", CURATOR_HEADERS),
    ("CorrespondingAuthor", UNRELATED_AUTHOR_HEADERS),
]


# --------------------------------------------------------------------------- #
# local preambles
# --------------------------------------------------------------------------- #
def _setup_venue_and_author() -> dict:
    """One publisher, one fully open access journal and one appointed author."""
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
    return {"publisher": publisher, "journal": journal, "author": author}


def _setup_invoice_approved_for_payment(approver_headers: dict) -> dict:
    """An author-pays article whose 300000-cent invoice has been validated and
    then approved for payment by ``approver_headers``."""
    scenario = _setup_venue_and_author()
    article = record_article(
        scenario["journal"]["id"],
        scenario["author"]["id"],
        headers=LIBRARIAN_HEADERS,
        manuscript_title="Segregation of duties",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(article["id"], basis="PROVISIONAL")
    invoice = receive_invoice(
        scenario["publisher"]["id"],
        article["id"],
        "HALDEN-8001",
        300000,
        0.0,
        0.0,
        "2026-08-12",
    )
    validate_invoice(invoice["id"])
    scenario["article"] = read_article(article["id"])
    scenario["invoice"] = approve_invoice_for_payment(invoice["id"], approver_headers)
    return scenario


def _setup_draft_deposit() -> dict:
    """An accepted manuscript with one DRAFT deposit created by its author."""
    scenario = _setup_venue_and_author()
    article = record_article(
        scenario["journal"]["id"],
        scenario["author"]["id"],
        headers=LIBRARIAN_HEADERS,
        manuscript_title="Split duties on deposits",
        accepted_on="2026-08-05",
    )
    deposit = create_deposit(
        article["id"],
        scenario["author"]["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="ee55ff6677889900aa11bb22cc33dd44ee55ff6677889900aa11bb22cc33dd44",
        license="CC_BY",
    )
    scenario["article"] = read_article(article["id"])
    scenario["deposit"] = deposit
    return scenario


# --------------------------------------------------------------------------- #
# POST /apc-funds admits the FundManager alone
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "role_name, headers",
    ROLES_BARRED_FROM_FUND_CREATION,
    ids=[role for role, _ in ROLES_BARRED_FROM_FUND_CREATION],
)
def test_apc_fund_creation_rejects_every_role_other_than_the_fund_manager(
    api, role_name, headers
):
    """Opening an APC fund is a FundManager operation, so each of the other four
    declared roles is refused with ERR_UNAUTHORIZED even though the payload is the
    one a FundManager creates successfully.

    PRD §2.1: "If both headers are well-formed but the named role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.3: "Institutional money lives in APC funds opened by a `FundManager`."
    PRD §4: "| `POST` | `/apc-funds` | Open an APC fund for a fiscal year with a waterfall priority rank | `FundManager` |"
    Design: Corner/rbac/corner_fund_creation_is_exclusive_and_rejects_the_four_other_roles
    """
    response = api.create_apc_fund(FUND_PAYLOAD, headers)

    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert error["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value, (
        f"opening an APC fund as {role_name} must be refused with ERR_UNAUTHORIZED, "
        f"got {error['error_id']!r}"
    )


def test_apc_fund_creation_succeeds_for_the_fund_manager(api):
    """The identical payload that the other four roles are refused opens the fund
    when the acting role is the FundManager, which is what makes the endpoint
    genuinely single-role rather than open to any staff role.

    PRD §3.3: "Institutional money lives in APC funds opened by a `FundManager`."
    PRD §3.3: "On opening, `status` is `OPEN`, `committed_cents` and `spent_cents` are zero, `available_cents` equals `total_budget_cents`, and `freeze_reason` is absent."
    PRD §4: "| `POST` | `/apc-funds` | Open an APC fund for a fiscal year with a waterfall priority rank | `FundManager` |"
    Design: Corner/rbac/corner_fund_creation_is_exclusive_and_rejects_the_four_other_roles
    """
    fund = validate_success(
        api.create_apc_fund(FUND_PAYLOAD, FUND_MANAGER_HEADERS), expected_status=201
    )

    assert fund["status"] == "OPEN", (
        f"a freshly opened fund must be OPEN, got {fund['status']!r}"
    )
    assert fund["fund_code"] == "OA-CENTRAL-2027", (
        f"fund_code should be recorded verbatim, got {fund['fund_code']!r}"
    )
    assert fund["committed_cents"] == 0, (
        f"committed_cents must start at zero, got {fund['committed_cents']}"
    )
    assert fund["spent_cents"] == 0, (
        f"spent_cents must start at zero, got {fund['spent_cents']}"
    )
    assert fund["available_cents"] == 500000, (
        f"available_cents must equal total_budget_cents 500000, got "
        f"{fund['available_cents']}"
    )
    assert fund.get("freeze_reason") is None, (
        f"freeze_reason must be absent on opening, got {fund.get('freeze_reason')!r}"
    )

    reread = validate_success(api.get_apc_fund(fund["id"], FUND_MANAGER_HEADERS))
    assert reread["id"] == fund["id"], "the fund opened by the FundManager must persist"
    assert reread["status"] == "OPEN", (
        f"the persisted fund must still be OPEN, got {reread['status']!r}"
    )


# --------------------------------------------------------------------------- #
# shared operations admit either declared role
# --------------------------------------------------------------------------- #
def test_article_recording_accepts_either_the_librarian_or_the_corresponding_author(api):
    """An acceptance may be recorded by the scholarly communications librarian or
    by the corresponding author named in the payload; both calls create a distinct
    article, and the author's call also satisfies the ownership check.

    PRD §3.4: "An accepted manuscript may be recorded either by its `CorrespondingAuthor` or by a `ScholCommLibrarian` on the author's behalf."
    PRD §2.1: "This ownership check applies when a `CorrespondingAuthor` records an accepted manuscript (where the supplied `corresponding_author_id` must be the caller's own identifier), runs an eligibility check on an article, creates a fund request, resubmits one, withdraws one, creates a repository deposit, or submits a deposit for curation."
    PRD §4: "| `POST` | `/articles` | Record an accepted manuscript | `CorrespondingAuthor`, `ScholCommLibrarian` |"
    Design: Corner/rbac/corner_shared_operations_accept_either_declared_role
    """
    set_clock("2026-08-10T00:00:00Z")
    scenario = _setup_venue_and_author()
    journal_id = scenario["journal"]["id"]
    author_id = scenario["author"]["id"]

    by_librarian = validate_success(
        api.create_article(
            create_article_payload(
                journal_id,
                author_id,
                manuscript_title="Recorded by the library",
                accepted_on="2026-08-05",
            ),
            LIBRARIAN_HEADERS,
        ),
        expected_status=201,
    )
    by_author = validate_success(
        api.create_article(
            create_article_payload(
                journal_id,
                author_id,
                manuscript_title="Recorded by the author",
                accepted_on="2026-08-06",
            ),
            make_corresponding_author_headers(author_id),
        ),
        expected_status=201,
    )

    assert by_librarian["id"] != by_author["id"], (
        "the two acceptances must be two independently addressable articles, "
        f"both came back as {by_librarian['id']!r}"
    )
    assert by_author["corresponding_author_id"] == author_id, (
        "the article recorded by the author must name that author as corresponding "
        f"author, got {by_author['corresponding_author_id']!r}"
    )
    assert by_librarian["corresponding_author_id"] == author_id, (
        "the article recorded by the librarian must name the supplied corresponding "
        f"author, got {by_librarian['corresponding_author_id']!r}"
    )


def test_annual_spend_report_accepts_either_the_fund_manager_or_the_librarian(api):
    """The annual spend report answers both declared roles with the same figures:
    two accepted articles that carry no effective determination yet contribute
    nothing to the determination-derived counts.

    PRD §3.9: "The annual spend report is the other reporting surface, available to a `FundManager` or a `ScholCommLibrarian`."
    PRD §3.9: "From the determination ledger, the report takes the effective determination of every article whose `accepted_on` falls inside the fiscal-year window: `ta_articles_covered` counts those whose route is `TA_FULL` or `TA_CAPPED`, and `ta_savings_cents` sums, over exactly that same subset, the `list_base_cents` less the `covered_amount_cents` less the `author_share_cents` of each determination — the portion of list price that the negotiated discount removed altogether."
    PRD §3.9: "Across the whole determination population, `hybrid_article_count` counts those whose journal has an `oa_model` of `HYBRID` and `fully_oa_article_count` counts those whose journal has an `oa_model` of `FULLY_OA`."
    PRD §4: "| `GET` | `/analytics/annual-spend` | Annual spend report and negotiation analytics for a fiscal year, on the encumbrance or cash basis | `FundManager`, `ScholCommLibrarian` |"
    Design: Corner/rbac/corner_shared_operations_accept_either_declared_role
    """
    set_clock("2026-08-10T00:00:00Z")
    scenario = _setup_venue_and_author()
    record_article(
        scenario["journal"]["id"],
        scenario["author"]["id"],
        headers=LIBRARIAN_HEADERS,
        manuscript_title="Recorded by the library",
        accepted_on="2026-08-05",
    )
    record_article(
        scenario["journal"]["id"],
        scenario["author"]["id"],
        manuscript_title="Recorded by the author",
        accepted_on="2026-08-06",
    )

    by_fund_manager = validate_success(
        api.get_annual_spend(FUND_MANAGER_HEADERS, params={"fiscal_year": 2027})
    )
    by_librarian = validate_success(
        api.get_annual_spend(LIBRARIAN_HEADERS, params={"fiscal_year": 2027})
    )

    assert by_fund_manager["fully_oa_article_count"] == 0, (
        "no article has an effective determination yet, so fully_oa_article_count "
        f"must be 0 for the FundManager, got {by_fund_manager['fully_oa_article_count']}"
    )
    assert by_librarian["fully_oa_article_count"] == 0, (
        "no article has an effective determination yet, so fully_oa_article_count "
        f"must be 0 for the ScholCommLibrarian, got "
        f"{by_librarian['fully_oa_article_count']}"
    )
    assert (
        by_fund_manager["fully_oa_article_count"]
        == by_librarian["fully_oa_article_count"]
    ), "both authorised roles must be answered with identical figures"


# --------------------------------------------------------------------------- #
# segregation of duties on the payment path
# --------------------------------------------------------------------------- #
def test_the_operator_who_approved_an_invoice_cannot_also_pay_it(api):
    """Both calls are made in the FundManager role, so the role gate passes; what
    fails is the identity comparison against the recorded approver. The refused
    attempt leaves the invoice approved and unpaid, and a different FundManager
    then pays it.

    PRD §2.9: "A `FundManager` first approves a validated invoice for payment, and the acting `X-User-ID` is recorded on the invoice as `payment_approved_by_user_id`."
    PRD §2.9: "A `FundManager` then pays the approved invoice — but the paying operator's `X-User-ID` must differ from the recorded `payment_approved_by_user_id`."
    PRD §2.9: "An attempt by the same operator to both approve and pay is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "A different `FundManager` then pays it, supplying the bank `payment_reference`, which moves the invoice from `APPROVED_FOR_PAYMENT` to `PAID`."
    Design: Corner/rbac/corner_same_user_cannot_pay_an_invoice_they_approved
    """
    set_clock("2026-08-12T00:00:00Z")
    scenario = _setup_invoice_approved_for_payment(FUND_APPROVER_HEADERS)
    invoice_id = scenario["invoice"]["id"]

    assert scenario["invoice"]["status"] == "APPROVED_FOR_PAYMENT", (
        "payment approval must move the invoice to APPROVED_FOR_PAYMENT, got "
        f"{scenario['invoice']['status']!r}"
    )
    assert scenario["invoice"]["payment_approved_by_user_id"] == "fm-solo-09", (
        "the approving operator's X-User-ID must be recorded as "
        f"payment_approved_by_user_id, got "
        f"{scenario['invoice']['payment_approved_by_user_id']!r}"
    )

    refused = api.pay_publisher_invoice(
        invoice_id, create_payment_payload("WIRE-88001"), FUND_APPROVER_HEADERS
    )
    error = validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert error["error_id"] == ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, (
        "the approving operator must not be allowed to pay, got "
        f"{error['error_id']!r}"
    )

    still_approved = read_invoice(invoice_id)
    assert still_approved["status"] == "APPROVED_FOR_PAYMENT", (
        "the refused payment must leave the invoice in APPROVED_FOR_PAYMENT, got "
        f"{still_approved['status']!r}"
    )
    assert still_approved.get("payment_reference") is None, (
        "the refused payment must not record a payment_reference, got "
        f"{still_approved.get('payment_reference')!r}"
    )

    paid = validate_success(
        api.pay_publisher_invoice(
            invoice_id, create_payment_payload("WIRE-88002"), FUND_PAYER_HEADERS
        )
    )
    assert paid["status"] == "PAID", (
        f"a different FundManager must be able to pay, got {paid['status']!r}"
    )
    assert paid["payment_reference"] == "WIRE-88002", (
        f"the supplied payment_reference must be recorded, got "
        f"{paid['payment_reference']!r}"
    )
    assert paid["payment_approved_by_user_id"] == "fm-solo-09", (
        "payment must not overwrite the recorded approver, got "
        f"{paid['payment_approved_by_user_id']!r}"
    )


# --------------------------------------------------------------------------- #
# the deposit workflow is split between two roles
# --------------------------------------------------------------------------- #
def test_repository_curator_cannot_create_or_submit_a_manuscript_deposit(api):
    """Depositing is the author's half of the workflow: the curator who will later
    decide the submission may neither create a deposit nor submit one, and the
    author's DRAFT deposit is untouched by either refusal.

    PRD §3.8: "Deposits are created by the `CorrespondingAuthor`."
    PRD §3.8: "The author submits the draft for curation, which requires the deposit to be in `DRAFT` and which moves it from `DRAFT` to `SUBMITTED` while stamping `submitted_at` from the logical clock."
    PRD §2.1: "If both headers are well-formed but the named role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Authentication is evaluated before authorisation, and both are evaluated before anything else about the request is inspected."
    PRD §4: "| `POST` | `/repository-deposits` | Create a manuscript deposit for an article; concurrency-guarded on the article's version | `CorrespondingAuthor` |"
    PRD §4: "| `POST` | `/repository-deposits/{id}/submission` | Submit a draft deposit for curation | `CorrespondingAuthor` |"
    Design: Corner/rbac/corner_deposit_authoring_and_curation_are_split_between_two_roles
    """
    set_clock("2026-08-12T00:00:00Z")
    scenario = _setup_draft_deposit()
    article = scenario["article"]
    deposit_id = scenario["deposit"]["id"]

    create_refused = api.create_repository_deposit(
        create_repository_deposit_payload(
            article["id"],
            article["version"],
            version_label="VERSION_OF_RECORD",
            file_checksum="ff6677889900aa11bb22cc33dd44ee55ff6677889900aa11bb22cc33dd44ee55",
            license="CC_BY",
        ),
        CURATOR_HEADERS,
    )
    create_error = validate_error(create_refused, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert create_error["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value, (
        "a RepositoryCurator must not create a deposit, got "
        f"{create_error['error_id']!r}"
    )

    submit_refused = api.submit_repository_deposit(deposit_id, CURATOR_HEADERS)
    submit_error = validate_error(submit_refused, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert submit_error["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value, (
        "a RepositoryCurator must not submit a deposit for curation, got "
        f"{submit_error['error_id']!r}"
    )

    unchanged = read_deposit(deposit_id)
    assert unchanged["status"] == "DRAFT", (
        f"the author's deposit must still be DRAFT, got {unchanged['status']!r}"
    )
    assert unchanged.get("submitted_at") is None, (
        "a refused submission must not stamp submitted_at, got "
        f"{unchanged.get('submitted_at')!r}"
    )

    deposits = list_article_deposits(article["id"])
    assert len(deposits) == 1, (
        f"the refused create must not add a deposit, the article carries "
        f"{len(deposits)} deposits"
    )
    assert deposits[0]["id"] == deposit_id, (
        "the single deposit of the article must be the one the author created"
    )


def test_corresponding_author_cannot_take_the_curation_decision_on_their_deposit(api):
    """Curation is the curator's half of the workflow: the author who created and
    submitted the deposit may not ingest it themselves.

    PRD §3.8: "A `RepositoryCurator` then decides, supplying a `decision` of either `RETURN` or `INGEST` together with an optional `curation_note`."
    PRD §2.1: "If both headers are well-formed but the named role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| `POST` | `/repository-deposits/{id}/curation-decision` | Curator branch: ingest the deposit (minting a handle) or return it to the author | `RepositoryCurator` |"
    Design: Corner/rbac/corner_deposit_authoring_and_curation_are_split_between_two_roles
    """
    set_clock("2026-08-12T00:00:00Z")
    scenario = _setup_draft_deposit()
    deposit_id = scenario["deposit"]["id"]
    author_id = scenario["author"]["id"]

    refused = api.decide_repository_deposit_curation(
        deposit_id,
        create_curation_decision_payload("INGEST"),
        make_corresponding_author_headers(author_id),
    )
    error = validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert error["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value, (
        "a CorrespondingAuthor must not take the curation decision, got "
        f"{error['error_id']!r}"
    )

    unchanged = read_deposit(deposit_id)
    assert unchanged["status"] == "DRAFT", (
        f"the refused curation decision must leave the deposit DRAFT, got "
        f"{unchanged['status']!r}"
    )
    assert unchanged.get("persistent_identifier") is None, (
        "no persistent identifier may be minted by a refused curation decision, got "
        f"{unchanged.get('persistent_identifier')!r}"
    )
    assert unchanged.get("ingested_at") is None, (
        f"ingested_at must stay absent, got {unchanged.get('ingested_at')!r}"
    )
