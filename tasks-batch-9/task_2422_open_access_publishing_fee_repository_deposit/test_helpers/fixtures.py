"""Composite setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch here through PRD-declared endpoints only.  The module is organised in two
layers:

* single-step helpers (``register_publisher``, ``add_coverage``, ``decide_request``
  …) that wrap one endpoint call and return the resulting resource; and
* composite builders (``setup_active_agreement``, ``setup_fund_request_under_review``
  …) that walk a whole preamble and return a dictionary of everything they made.

All helpers use the lenient success reader, so a broken preamble surfaces as a
setup failure rather than as a confusing assertion deep inside a test.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_coverage_payload,
    create_apc_fund_payload,
    create_article_payload,
    create_author_payload,
    create_clock_payload,
    create_curation_decision_payload,
    create_decision_payload,
    create_eligibility_check_payload,
    create_freeze_payload,
    create_fund_request_payload,
    create_funder_payload,
    create_grant_payload,
    create_info_request_payload,
    create_journal_payload,
    create_payment_payload,
    create_publication_payload,
    create_publisher_invoice_payload,
    create_publisher_payload,
    create_repository_deposit_payload,
    create_resubmission_payload,
    create_screening_run_payload,
    create_transformative_agreement_payload,
    create_withdrawal_payload,
    make_checksum,
    make_issn,
)
from .test_users import TEST_USERS, make_corresponding_author_headers

ADMIN = TEST_USERS["agreement_admin_headers"]
LIBRARIAN = TEST_USERS["librarian_headers"]
FUND_MANAGER = TEST_USERS["fund_manager_headers"]
FUND_PAYER = TEST_USERS["fund_payer_headers"]
CURATOR = TEST_USERS["curator_headers"]


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> str:
    """Move the logical clock and return the resulting current_utc."""
    data = get_success_data(
        api_client.set_clock(create_clock_payload(to_iso8601), headers or LIBRARIAN)
    )
    return data.get("current_utc")


# --------------------------------------------------------------------------- #
# publishers and journals
# --------------------------------------------------------------------------- #
def register_publisher(publisher_code: str = "MERID", **overrides) -> dict:
    return get_success_data(
        api_client.create_publisher(
            create_publisher_payload(publisher_code=publisher_code, **overrides), ADMIN
        )
    )


def read_publisher(publisher_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_publisher(publisher_id, headers or ADMIN))


def screen_publisher(publisher_id: str, **signals) -> dict:
    """Run a screening run on the publisher; defaults produce a CLEARED verdict."""
    return get_success_data(
        api_client.create_screening_run(
            publisher_id, create_screening_run_payload(**signals), LIBRARIAN
        )
    )


def register_journal(publisher_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_journal(
            create_journal_payload(publisher_id, **overrides), ADMIN
        )
    )


def read_journal(journal_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_journal(journal_id, headers or ADMIN))


# --------------------------------------------------------------------------- #
# agreements and coverage lines
# --------------------------------------------------------------------------- #
def draft_agreement(
    publisher_id: str, expected_publisher_version: Optional[int] = None, **overrides
) -> dict:
    """Draft an agreement, reading the publisher's current version when the
    caller does not pin one explicitly."""
    if expected_publisher_version is None:
        expected_publisher_version = read_publisher(publisher_id)["version"]
    return get_success_data(
        api_client.create_transformative_agreement(
            create_transformative_agreement_payload(
                publisher_id, expected_publisher_version, **overrides
            ),
            ADMIN,
        )
    )


def read_agreement(agreement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_transformative_agreement(agreement_id, headers or ADMIN)
    )


def add_coverage(agreement_id: str, journal_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_agreement_coverage(
            agreement_id, create_agreement_coverage_payload(journal_id, **overrides), ADMIN
        )
    )


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(
        api_client.activate_transformative_agreement(agreement_id, ADMIN)
    )


# --------------------------------------------------------------------------- #
# people, mandates and awards
# --------------------------------------------------------------------------- #
def register_author(**overrides) -> dict:
    return get_success_data(
        api_client.create_author(create_author_payload(**overrides), ADMIN)
    )


def read_author(author_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_author(author_id, headers or ADMIN))


def register_funder(**overrides) -> dict:
    return get_success_data(
        api_client.create_funder(create_funder_payload(**overrides), ADMIN)
    )


def record_grant(funder_id: str, pi_author_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_grant(
            create_grant_payload(funder_id, pi_author_id, **overrides), ADMIN
        )
    )


def read_grant(grant_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_grant(grant_id, headers or ADMIN))


# --------------------------------------------------------------------------- #
# APC funds
# --------------------------------------------------------------------------- #
def open_fund(**overrides) -> dict:
    return get_success_data(
        api_client.create_apc_fund(create_apc_fund_payload(**overrides), FUND_MANAGER)
    )


def read_fund(fund_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_apc_fund(fund_id, headers or FUND_MANAGER))


def freeze_fund(fund_id: str, reason: str = "AUDIT_HOLD") -> dict:
    return get_success_data(
        api_client.freeze_apc_fund(fund_id, create_freeze_payload(reason), FUND_MANAGER)
    )


def list_fund_allocations(fund_id: str, params: Optional[Dict] = None) -> List[dict]:
    body = api_client.list_fund_allocations(fund_id, FUND_MANAGER, params=params).json()
    return body["data"]


# --------------------------------------------------------------------------- #
# articles and determinations
# --------------------------------------------------------------------------- #
def record_article(
    journal_id: str, corresponding_author_id: str, headers: Optional[dict] = None,
    **overrides
) -> dict:
    """Record an acceptance.  Defaults to the author's own headers so the
    ownership check on the supplied corresponding_author_id passes."""
    return get_success_data(
        api_client.create_article(
            create_article_payload(journal_id, corresponding_author_id, **overrides),
            headers or make_corresponding_author_headers(corresponding_author_id),
        )
    )


def read_article(article_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_article(article_id, headers or LIBRARIAN))


def run_eligibility_check(
    article_id: str,
    author_id: Optional[str] = None,
    basis: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Append a determination.  Pass ``author_id`` to act as the article's own
    corresponding author; otherwise the librarian runs the check."""
    if headers is None:
        headers = (
            make_corresponding_author_headers(author_id) if author_id else LIBRARIAN
        )
    return get_success_data(
        api_client.create_eligibility_check(
            article_id, create_eligibility_check_payload(basis), headers
        )
    )


def publish_article(article_id: str, publication_date: str) -> dict:
    return get_success_data(
        api_client.publish_article(
            article_id, create_publication_payload(publication_date), LIBRARIAN
        )
    )


def list_determinations(params: Optional[Dict] = None) -> List[dict]:
    body = api_client.list_eligibility_determinations(LIBRARIAN, params=params).json()
    return body["data"]


# --------------------------------------------------------------------------- #
# fund requests
# --------------------------------------------------------------------------- #
def open_fund_request(
    article_id: str, author_id: str, requested_cents: int, **overrides
) -> dict:
    return get_success_data(
        api_client.create_fund_request(
            create_fund_request_payload(article_id, requested_cents, **overrides),
            make_corresponding_author_headers(author_id),
        )
    )


def read_fund_request(request_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_fund_request(request_id, headers or FUND_MANAGER)
    )


def start_review(request_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.start_fund_request_review(request_id, headers or LIBRARIAN)
    )


def request_more_information(request_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fund_request_info_request(
            request_id, create_info_request_payload(**overrides), LIBRARIAN
        )
    )


def resubmit_request(
    request_id: str, author_id: str, requested_cents: int, **overrides
) -> dict:
    return get_success_data(
        api_client.create_fund_request_resubmission(
            request_id,
            create_resubmission_payload(requested_cents, **overrides),
            make_corresponding_author_headers(author_id),
        )
    )


def decide_request(
    request_id: str,
    decision: str = "APPROVE",
    reason: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.decide_fund_request(
            request_id,
            create_decision_payload(decision, reason),
            headers or FUND_MANAGER,
        )
    )


def withdraw_request(request_id: str, author_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.withdraw_fund_request(
            request_id,
            create_withdrawal_payload(**overrides),
            make_corresponding_author_headers(author_id),
        )
    )


def list_request_allocations(
    request_id: str, params: Optional[Dict] = None
) -> List[dict]:
    body = api_client.list_fund_request_allocations(
        request_id, FUND_MANAGER, params=params
    ).json()
    return body["data"]


# --------------------------------------------------------------------------- #
# invoices
# --------------------------------------------------------------------------- #
def receive_invoice(
    publisher_id: str,
    article_id: str,
    invoice_number: str,
    invoice_amount_cents: int,
    claimed_discount_pct: float,
    vat_pct: float,
    invoice_date: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_publisher_invoice(
            create_publisher_invoice_payload(
                publisher_id,
                article_id,
                invoice_number,
                invoice_amount_cents,
                claimed_discount_pct,
                vat_pct,
                invoice_date,
                **overrides,
            ),
            LIBRARIAN,
        )
    )


def read_invoice(invoice_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_publisher_invoice(invoice_id, headers or LIBRARIAN)
    )


def validate_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.validate_publisher_invoice(invoice_id, LIBRARIAN))


def approve_invoice_for_payment(invoice_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.approve_publisher_invoice_payment(invoice_id, headers or FUND_MANAGER)
    )


def pay_invoice(
    invoice_id: str, payment_reference: str = "WIRE-88001",
    headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.pay_publisher_invoice(
            invoice_id, create_payment_payload(payment_reference), headers or FUND_PAYER
        )
    )


def carry_invoice_to_paid(
    publisher_id: str,
    article_id: str,
    invoice_number: str,
    invoice_amount_cents: int,
    claimed_discount_pct: float,
    vat_pct: float,
    invoice_date: str,
    payment_reference: str = "WIRE-88001",
) -> dict:
    """Receive → validate → approve for payment → pay.  Returns the paid invoice."""
    invoice = receive_invoice(
        publisher_id,
        article_id,
        invoice_number,
        invoice_amount_cents,
        claimed_discount_pct,
        vat_pct,
        invoice_date,
    )
    validate_invoice(invoice["id"])
    approve_invoice_for_payment(invoice["id"])
    return pay_invoice(invoice["id"], payment_reference)


# --------------------------------------------------------------------------- #
# repository deposits
# --------------------------------------------------------------------------- #
def create_deposit(
    article_id: str,
    author_id: str,
    expected_article_version: Optional[int] = None,
    **overrides,
) -> dict:
    if expected_article_version is None:
        expected_article_version = read_article(article_id)["version"]
    return get_success_data(
        api_client.create_repository_deposit(
            create_repository_deposit_payload(
                article_id, expected_article_version, **overrides
            ),
            make_corresponding_author_headers(author_id),
        )
    )


def read_deposit(deposit_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_repository_deposit(deposit_id, headers or CURATOR)
    )


def submit_deposit(deposit_id: str, author_id: str) -> dict:
    return get_success_data(
        api_client.submit_repository_deposit(
            deposit_id, make_corresponding_author_headers(author_id)
        )
    )


def curate_deposit(
    deposit_id: str, decision: str = "INGEST", curation_note: Optional[str] = None
) -> dict:
    return get_success_data(
        api_client.decide_repository_deposit_curation(
            deposit_id, create_curation_decision_payload(decision, curation_note), CURATOR
        )
    )


def list_article_deposits(article_id: str, params: Optional[Dict] = None) -> List[dict]:
    body = api_client.list_article_deposits(article_id, CURATOR, params=params).json()
    return body["data"]


# --------------------------------------------------------------------------- #
# ops and analytics
# --------------------------------------------------------------------------- #
def run_compliance_sweep() -> dict:
    return get_success_data(api_client.create_compliance_sweep(LIBRARIAN))


def get_annual_spend(
    fiscal_year: int, basis: Optional[str] = None, publisher_id: Optional[str] = None
) -> dict:
    params: Dict[str, object] = {"fiscal_year": fiscal_year}
    if basis is not None:
        params["basis"] = basis
    if publisher_id is not None:
        params["publisher_id"] = publisher_id
    return get_success_data(api_client.get_annual_spend(FUND_MANAGER, params=params))


# --------------------------------------------------------------------------- #
# composite builders
# --------------------------------------------------------------------------- #
def setup_publisher_with_journal(
    publisher_code: str = "MERID",
    publisher_name: str = "Meridian Academic Press",
    screen: bool = False,
    screening_signals: Optional[dict] = None,
    **journal_overrides,
) -> dict:
    """Register a publisher and one journal under it.  Set ``screen=True`` to run a
    screening run (defaults produce CLEARED) before the journal is registered."""
    publisher = register_publisher(publisher_code=publisher_code, name=publisher_name)
    if screen:
        publisher = screen_publisher(publisher["id"], **(screening_signals or {}))
    journal = register_journal(publisher["id"], **journal_overrides)
    return {"publisher": publisher, "journal": journal}


def setup_active_agreement(
    publisher_code: str = "MERID",
    agreement_code: str = "TA-MERID-H1",
    effective_from: str = "2026-07-01",
    effective_until: str = "2027-07-01",
    article_quota: int = 1,
    discount_pct: float = 0.05,
    covered_oa_models: Optional[List[str]] = None,
    coverage_type: str = "FULL_APC",
    covered_from: str = "2026-07-01",
    covered_until: str = "2027-06-30",
    capped_amount_cents: Optional[int] = None,
    journal_overrides: Optional[dict] = None,
    activate: bool = True,
) -> dict:
    """Publisher + journal + drafted agreement + one coverage line, activated by
    default.  Returns publisher, journal, agreement (post-activation) and coverage."""
    base = setup_publisher_with_journal(
        publisher_code=publisher_code, **(journal_overrides or {})
    )
    agreement = draft_agreement(
        base["publisher"]["id"],
        agreement_code=agreement_code,
        effective_from=effective_from,
        effective_until=effective_until,
        article_quota=article_quota,
        discount_pct=discount_pct,
        covered_oa_models=covered_oa_models,
    )
    coverage = add_coverage(
        agreement["id"],
        base["journal"]["id"],
        coverage_type=coverage_type,
        covered_from=covered_from,
        covered_until=covered_until,
        capped_amount_cents=capped_amount_cents,
    )
    if activate:
        agreement = activate_agreement(agreement["id"])
    return {
        "publisher": base["publisher"],
        "journal": base["journal"],
        "agreement": agreement,
        "coverage": coverage,
    }


def setup_author_with_grant(
    author_overrides: Optional[dict] = None,
    funder_overrides: Optional[dict] = None,
    grant_overrides: Optional[dict] = None,
) -> dict:
    """Author + funder + grant with that author as principal investigator."""
    author = register_author(**(author_overrides or {}))
    funder = register_funder(**(funder_overrides or {}))
    grant = record_grant(funder["id"], author["id"], **(grant_overrides or {}))
    return {"author": author, "funder": funder, "grant": grant}


def setup_covered_article(
    accepted_on: str = "2026-08-05",
    agreement_overrides: Optional[dict] = None,
    author_overrides: Optional[dict] = None,
    article_overrides: Optional[dict] = None,
    with_grant: bool = False,
    funder_overrides: Optional[dict] = None,
    grant_overrides: Optional[dict] = None,
) -> dict:
    """An accepted manuscript at a journal covered by an active agreement.
    No determination has been run yet."""
    scenario = setup_active_agreement(**(agreement_overrides or {}))
    author = register_author(**(author_overrides or {}))
    scenario["author"] = author
    grant_id = None
    if with_grant:
        funder = register_funder(**(funder_overrides or {}))
        grant = record_grant(funder["id"], author["id"], **(grant_overrides or {}))
        scenario["funder"] = funder
        scenario["grant"] = grant
        grant_id = grant["id"]
    scenario["article"] = record_article(
        scenario["journal"]["id"],
        author["id"],
        accepted_on=accepted_on,
        grant_id=grant_id,
        **(article_overrides or {}),
    )
    return scenario


def setup_fund_route_article(
    accepted_on: str = "2026-08-05",
    list_apc_cents: int = 300000,
    publisher_code: str = "MERID",
    author_overrides: Optional[dict] = None,
    funder_overrides: Optional[dict] = None,
    grant_overrides: Optional[dict] = None,
    article_overrides: Optional[dict] = None,
    run_check: bool = True,
) -> dict:
    """An article that qualifies for the institutional-fund route: a fully open
    access journal with no agreement cover, an active grant, and a funder with a
    GOLD_OA mandate that allows APC payment.  Runs the eligibility check by
    default so the article sits in ELIGIBILITY_CHECKED on the FUND_APC route."""
    base = setup_publisher_with_journal(
        publisher_code=publisher_code,
        oa_model="FULLY_OA",
        list_apc_cents=list_apc_cents,
    )
    author = register_author(**(author_overrides or {}))
    funder_kwargs = {"mandate_type": "GOLD_OA", "apc_allowable": True}
    funder_kwargs.update(funder_overrides or {})
    funder = register_funder(**funder_kwargs)
    grant = record_grant(funder["id"], author["id"], **(grant_overrides or {}))
    article = record_article(
        base["journal"]["id"],
        author["id"],
        accepted_on=accepted_on,
        grant_id=grant["id"],
        **(article_overrides or {}),
    )
    scenario = {
        "publisher": base["publisher"],
        "journal": base["journal"],
        "author": author,
        "funder": funder,
        "grant": grant,
        "article": article,
    }
    if run_check:
        scenario["determination"] = run_eligibility_check(article["id"], author["id"])
        scenario["article"] = read_article(article["id"])
    return scenario


def setup_fund_request_under_review(
    requested_cents: int = 300000,
    fund_specs: Optional[List[dict]] = None,
    **scenario_overrides,
) -> dict:
    """A FUND_APC article whose request has been taken into review, with one or
    more APC funds open.  ``fund_specs`` is a list of ``create_apc_fund_payload``
    keyword dictionaries drawn in ascending priority_rank."""
    scenario = setup_fund_route_article(**scenario_overrides)
    specs = fund_specs if fund_specs is not None else [{}]
    scenario["funds"] = [open_fund(**spec) for spec in specs]
    if scenario["funds"]:
        scenario["fund"] = scenario["funds"][0]
    request = open_fund_request(
        scenario["article"]["id"], scenario["author"]["id"], requested_cents
    )
    scenario["request"] = start_review(request["id"])
    return scenario


def setup_approved_fund_request(
    requested_cents: int = 300000,
    fund_specs: Optional[List[dict]] = None,
    decision_reason: Optional[str] = None,
    **scenario_overrides,
) -> dict:
    """As ``setup_fund_request_under_review``, carried through an approval so the
    request holds ENCUMBERED allocation lines."""
    scenario = setup_fund_request_under_review(
        requested_cents=requested_cents, fund_specs=fund_specs, **scenario_overrides
    )
    scenario["request"] = decide_request(
        scenario["request"]["id"], "APPROVE", decision_reason
    )
    scenario["allocations"] = list_request_allocations(scenario["request"]["id"])
    scenario["article"] = read_article(scenario["article"]["id"])
    return scenario


def setup_deposit_ready_article(
    accepted_on: str = "2026-08-05",
    orcid: Optional[str] = None,
    funder_overrides: Optional[dict] = None,
    journal_overrides: Optional[dict] = None,
    author_overrides: Optional[dict] = None,
    publisher_code: str = "MERID",
) -> dict:
    """An accepted manuscript under a mandate, with an author who carries an ORCID
    iD so a deposit of the work can be ingested."""
    base = setup_publisher_with_journal(
        publisher_code=publisher_code, **(journal_overrides or {})
    )
    author_kwargs = {"orcid": orcid if orcid is not None else "0000-0002-1825-0097"}
    author_kwargs.update(author_overrides or {})
    author = register_author(**author_kwargs)
    funder = register_funder(**(funder_overrides or {}))
    grant = record_grant(funder["id"], author["id"])
    article = record_article(
        base["journal"]["id"], author["id"], accepted_on=accepted_on, grant_id=grant["id"]
    )
    return {
        "publisher": base["publisher"],
        "journal": base["journal"],
        "author": author,
        "funder": funder,
        "grant": grant,
        "article": article,
    }


def setup_ingested_deposit(
    version_label: str = "ACCEPTED_MANUSCRIPT",
    license: str = "CC_BY",
    file_checksum: Optional[str] = None,
    ingest_at: Optional[str] = None,
    **scenario_overrides,
) -> dict:
    """A deposit carried from creation through submission to ingest.  Pass
    ``ingest_at`` to move the logical clock immediately before the curation
    decision."""
    scenario = setup_deposit_ready_article(**scenario_overrides)
    deposit = create_deposit(
        scenario["article"]["id"],
        scenario["author"]["id"],
        version_label=version_label,
        license=license,
        file_checksum=file_checksum if file_checksum is not None else make_checksum(1),
    )
    submit_deposit(deposit["id"], scenario["author"]["id"])
    if ingest_at is not None:
        set_clock(ingest_at)
    scenario["deposit"] = curate_deposit(deposit["id"], "INGEST")
    scenario["article"] = read_article(scenario["article"]["id"])
    return scenario
