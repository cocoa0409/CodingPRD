"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient success reader so a broken preamble
surfaces as a setup failure rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADMIN_USER_ID, ANALYST_USER_ID, CLOCK_START, COMPLIANCE_USER_ID, FUNDER_USER_ID,
)
from .factories import (
    STANDARD_TIERS, create_agreement_payload, create_application_payload,
    create_contract_payload, create_dealer_payload, create_document_payload,
    create_rate_sheet_payload, create_reserve_adjustment_payload,
    create_review_payload, create_scorecard_payload,
)
from .test_users import (
    ADMIN, ANALYST, COMPLIANCE, FUNDER, make_credit_analyst_headers,
    make_dealer_principal_headers, make_funding_specialist_headers,
)

# The base funding package the PRD requires of every contract.
BASE_REQUIRED_DOC_TYPES = [
    "RETAIL_INSTALLMENT_CONTRACT",
    "TITLE_APPLICATION",
    "INSURANCE_BINDER",
]
INCOME_DOC_TYPE = "INCOME_VERIFICATION"


# --- Tier 0: primitives ----------------------------------------------------

def set_clock(to_iso8601, headers=None) -> dict:
    """Reposition the logical clock; mutates no entity."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or ADMIN))


def onboard_dealer(**overrides) -> dict:
    return get_success_data(
        api_client.create_dealer(create_dealer_payload(**overrides), ADMIN)
    )


def read_dealer(dealer_id, headers=None) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, headers or ADMIN))


def dealer_version(dealer_id) -> int:
    return read_dealer(dealer_id)["version"]


def draft_agreement(dealer_id, expected_dealer_version=None, **overrides) -> dict:
    if expected_dealer_version is None:
        expected_dealer_version = dealer_version(dealer_id)
    payload = create_agreement_payload(dealer_id, expected_dealer_version, **overrides)
    return get_success_data(api_client.create_agreement(payload, ADMIN))


def countersign_agreement(agreement_id, dealer_id, signer_name="R. Ridge") -> dict:
    return get_success_data(
        api_client.countersign_agreement(
            agreement_id, {"signer_name": signer_name},
            make_dealer_principal_headers(dealer_id),
        )
    )


def create_draft_rate_sheet(**overrides) -> dict:
    return get_success_data(
        api_client.create_rate_sheet(create_rate_sheet_payload(**overrides), ADMIN)
    )


def append_tiers(rate_sheet_id, tiers=None) -> list:
    rows = []
    for tier in (tiers if tiers is not None else STANDARD_TIERS):
        rows.append(
            get_success_data(api_client.create_tier(rate_sheet_id, dict(tier), ADMIN))
        )
    return rows


def publish_sheet(rate_sheet_id) -> dict:
    return get_success_data(api_client.publish_rate_sheet(rate_sheet_id, ADMIN))


def create_published_rate_sheet(tiers=None, **sheet_overrides) -> dict:
    """Create a DRAFT sheet, append its tier rows, and publish it."""
    sheet = create_draft_rate_sheet(**sheet_overrides)
    rows = append_tiers(sheet["id"], tiers)
    sheet = publish_sheet(sheet["id"])
    return {"rate_sheet": sheet, "tiers": rows}


# --- Tier 1: an onboarded, countersigned, priced dealership ---------------

def setup_program(clock=CLOCK_START, dealer_overrides=None, agreement_overrides=None,
                  sheet_overrides=None, tiers=None) -> dict:
    """Active dealership + countersigned agreement + published price list.

    Returns a dict carrying `dealer`, `dealer_id`, `agreement`, `rate_sheet`,
    `tiers` and `dealer_headers` (bound to the dealership's own id).
    """
    if clock is not None:
        set_clock(clock)
    dealer = onboard_dealer(**(dealer_overrides or {}))
    agreement = draft_agreement(dealer["id"], **(agreement_overrides or {}))
    agreement = countersign_agreement(agreement["id"], dealer["id"])
    sheet = create_published_rate_sheet(tiers=tiers, **(sheet_overrides or {}))
    dealer = read_dealer(dealer["id"])
    return {
        "dealer": dealer,
        "dealer_id": dealer["id"],
        "agreement": agreement,
        "rate_sheet": sheet["rate_sheet"],
        "tiers": sheet["tiers"],
        "dealer_headers": make_dealer_principal_headers(dealer["id"]),
    }


def setup_program_without_agreement(clock=CLOCK_START, dealer_overrides=None,
                                    sheet_overrides=None, tiers=None) -> dict:
    """Onboarded dealership in PROSPECT plus a published price list."""
    if clock is not None:
        set_clock(clock)
    dealer = onboard_dealer(**(dealer_overrides or {}))
    sheet = create_published_rate_sheet(tiers=tiers, **(sheet_overrides or {}))
    return {
        "dealer": dealer,
        "dealer_id": dealer["id"],
        "rate_sheet": sheet["rate_sheet"],
        "tiers": sheet["tiers"],
        "dealer_headers": make_dealer_principal_headers(dealer["id"]),
    }


# --- Tier 2: application lifecycle ----------------------------------------

def submit_application(dealer_id, **overrides) -> dict:
    payload = create_application_payload(dealer_id, **overrides)
    return get_success_data(
        api_client.create_application(payload, make_dealer_principal_headers(dealer_id))
    )


def read_application(application_id, headers=None) -> dict:
    return get_success_data(api_client.get_application(application_id, headers or ADMIN))


def decision_application(application_id, outcome="APPROVE",
                         analyst_user_id=ANALYST_USER_ID, **extra) -> dict:
    payload = {"outcome": outcome}
    payload.update(extra)
    return get_success_data(
        api_client.decision_application(
            application_id, payload, make_credit_analyst_headers(analyst_user_id)
        )
    )


def resubmit_application(application_id, dealer_id, **fields) -> dict:
    return get_success_data(
        api_client.resubmit_application(
            application_id, dict(fields), make_dealer_principal_headers(dealer_id)
        )
    )


def submit_and_approve(dealer_id, analyst_user_id=ANALYST_USER_ID, **overrides) -> dict:
    application = submit_application(dealer_id, **overrides)
    return decision_application(
        application["id"], "APPROVE", analyst_user_id=analyst_user_id
    )


# --- Tier 3: contract lifecycle -------------------------------------------

def book_contract(application_id, dealer_id, **overrides) -> dict:
    payload = create_contract_payload(application_id, **overrides)
    return get_success_data(
        api_client.create_contract(payload, make_dealer_principal_headers(dealer_id))
    )


def read_contract(contract_id, headers=None) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers or ADMIN))


def upload_document(contract_id, dealer_id, doc_type, document_reference=None) -> dict:
    payload = create_document_payload(doc_type, document_reference)
    return get_success_data(
        api_client.upload_document(
            contract_id, payload, make_dealer_principal_headers(dealer_id)
        )
    )


def upload_package(contract_id, dealer_id, doc_types=None, prefix="IMG") -> dict:
    """Upload one document per required type. Returns {doc_type: document}."""
    documents = {}
    for doc_type in (doc_types if doc_types is not None else BASE_REQUIRED_DOC_TYPES):
        documents[doc_type] = upload_document(
            contract_id, dealer_id, doc_type, f"{prefix}-{doc_type}"
        )
    return documents


def verify_document(document_id, outcome="VERIFY", defect_code=None,
                    funder_user_id=FUNDER_USER_ID) -> dict:
    payload = {"outcome": outcome}
    if defect_code is not None:
        payload["defect_code"] = defect_code
    return get_success_data(
        api_client.verify_document(
            document_id, payload, make_funding_specialist_headers(funder_user_id)
        )
    )


def verify_package(documents, funder_user_id=FUNDER_USER_ID) -> None:
    for document in documents.values():
        verify_document(document["id"], funder_user_id=funder_user_id)


def fund_contract(contract_id, funding_date=CLOCK_START,
                  funder_user_id=FUNDER_USER_ID) -> dict:
    return get_success_data(
        api_client.fund_contract(
            contract_id, {"funding_date": funding_date},
            make_funding_specialist_headers(funder_user_id),
        )
    )


# --- Tier 4: full funding shortcuts ---------------------------------------

def setup_booked_contract(program, application_overrides=None, contract_apr_bps=749,
                          contract_date=CLOCK_START, analyst_user_id=ANALYST_USER_ID,
                          doc_prefix="IMG") -> dict:
    """Approved application + booked contract + a fully uploaded package."""
    dealer_id = program["dealer_id"]
    application = submit_and_approve(
        dealer_id, analyst_user_id=analyst_user_id, **(application_overrides or {})
    )
    contract = book_contract(
        application["id"], dealer_id,
        contract_apr_bps=contract_apr_bps, contract_date=contract_date,
    )
    documents = upload_package(contract["id"], dealer_id, prefix=doc_prefix)
    return {"application": application, "contract": contract, "documents": documents}


def setup_docs_verified_contract(program, **kwargs) -> dict:
    """Booked contract whose whole required package has been verified."""
    funder_user_id = kwargs.pop("funder_user_id", FUNDER_USER_ID)
    booked = setup_booked_contract(program, **kwargs)
    verify_package(booked["documents"], funder_user_id=funder_user_id)
    booked["contract"] = read_contract(booked["contract"]["id"])
    return booked


def setup_funded_contract(program, funding_date=CLOCK_START,
                          funder_user_id=FUNDER_USER_ID, **kwargs) -> dict:
    """Booked, verified and funded contract. Returns application/contract/documents."""
    ready = setup_docs_verified_contract(program, funder_user_id=funder_user_id, **kwargs)
    ready["contract"] = fund_contract(
        ready["contract"]["id"], funding_date=funding_date, funder_user_id=funder_user_id
    )
    return ready


def setup_program_with_funded_contract(**program_kwargs) -> dict:
    """The most common preamble: an active program with one funded contract."""
    contract_kwargs = program_kwargs.pop("contract_kwargs", {}) or {}
    program = setup_program(**program_kwargs)
    funded = setup_funded_contract(program, **contract_kwargs)
    program.update(funded)
    return program


# --- Tier 5: ledger, events, demands, supervision -------------------------

def post_reserve_adjustment(dealer_id, amount_cents, expected_dealer_version=None,
                            reason="OPENING_RESERVE_BALANCE") -> dict:
    if expected_dealer_version is None:
        expected_dealer_version = dealer_version(dealer_id)
    payload = create_reserve_adjustment_payload(
        amount_cents, expected_dealer_version, reason=reason
    )
    return get_success_data(
        api_client.create_reserve_adjustment(dealer_id, payload, ADMIN)
    )


def list_reserve_entries(headers=None, **params) -> list:
    response = api_client.list_reserve_entries(headers or ADMIN, params=params or None)
    return get_success_data(response)


def record_chargeback_event(contract_id, event_type, event_date) -> dict:
    return get_success_data(
        api_client.create_chargeback_event(
            contract_id, {"event_type": event_type, "event_date": event_date}, ADMIN
        )
    )


def issue_buyback_demand(contract_id, reason="DOC_DEFECT") -> dict:
    return get_success_data(
        api_client.create_buyback_demand(
            {"contract_id": contract_id, "reason": reason}, ADMIN
        )
    )


def act_on_buyback_demand(demand_id, action, dealer_id=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    headers = ADMIN if action in ("SETTLE", "WITHDRAW") else make_dealer_principal_headers(dealer_id)
    return get_success_data(api_client.buyback_demand_action(demand_id, payload, headers))


def dealer_status_action(dealer_id, action, reason=None, headers=None) -> dict:
    payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    if headers is None:
        headers = COMPLIANCE if action in ("COMPLIANCE_HOLD", "RELEASE_HOLD") else ADMIN
    return get_success_data(api_client.dealer_status_action(dealer_id, payload, headers))


def compute_scorecard(dealer_id, **overrides) -> dict:
    payload = create_scorecard_payload(**overrides)
    return get_success_data(api_client.create_scorecard(dealer_id, payload, ADMIN))


def finalize_scorecard(scorecard_id) -> dict:
    return get_success_data(api_client.finalize_scorecard(scorecard_id, ADMIN))


def run_fair_lending_review(dealer_id, **overrides) -> dict:
    payload = create_review_payload(dealer_id, **overrides)
    return get_success_data(api_client.create_fair_lending_review(payload, COMPLIANCE))


def fund_contracts_for_cohort_study(program, specs) -> list:
    """Fund one contract per spec, in the order given.

    Each spec is a dict of application overrides plus `contract_apr_bps`,
    used to build a book of contracts with known markups and cohorts.
    """
    funded = []
    for index, spec in enumerate(specs):
        spec = dict(spec)
        contract_apr_bps = spec.pop("contract_apr_bps", 749)
        funding_date = spec.pop("funding_date", CLOCK_START)
        contract_date = spec.pop("contract_date", funding_date)
        spec.setdefault("applicant_reference", f"APP-CO-{index}")
        funded.append(
            setup_funded_contract(
                program,
                application_overrides=spec,
                contract_apr_bps=contract_apr_bps,
                contract_date=contract_date,
                funding_date=funding_date,
                doc_prefix=f"IMG{index}",
            )
        )
    return funded
