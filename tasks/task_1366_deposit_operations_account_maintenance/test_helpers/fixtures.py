"""Composite setup helpers for multi-step test preconditions.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its default 2026-08-01T00:00:00Z). Setup
calls use get_success_data so failures surface as clear "Setup failed"
errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    conversion_payload,
    create_account_payload,
    deceased_case_payload,
    document_payload,
    garnishment_payload,
    initiate_release_payload,
    resolve_payload,
    review_payload,
    signer_payload,
    statement_cycle_payload,
    title_change_payload,
    transaction_payload,
)
from .test_users import MANAGER, MANAGER_2, OFFICER, OFFICER_1


def _ok(step, resp):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "error_id" in data:
        raise AssertionError(
            f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — single-call primitives reused everywhere
# ---------------------------------------------------------------------------

def open_account(opening_deposit_cents=5000, product_code="SAVINGS",
                 rate_bps=0, ownership_type="INDIVIDUAL",
                 primary_owner_name="Owner O", owner_tax_id="T-1",
                 pod_beneficiary_name=None, headers=OFFICER):
    """Open a deposit account. Returns the created account (version 1)."""
    payload = create_account_payload(
        primary_owner_name=primary_owner_name,
        owner_tax_id=owner_tax_id,
        ownership_type=ownership_type,
        product_code=product_code,
        rate_bps=rate_bps,
        opening_deposit_cents=opening_deposit_cents,
        pod_beneficiary_name=pod_beneficiary_name,
    )
    return _ok("open_account", api_client.create_account(payload, headers))


def get_account(account_id, headers=MANAGER):
    return _ok("get_account", api_client.get_account(account_id, headers))


def set_clock(to_iso8601, headers=MANAGER):
    return _ok("set_clock",
               api_client.set_clock({"to_iso8601": to_iso8601}, headers))


def run_sweep(headers=MANAGER):
    """Run the daily sweep at the current clock date. Returns sweep tallies."""
    return _ok("run_daily_sweep", api_client.run_daily_sweep(headers))


def post_transaction(account_id, txn_type, amount_cents, headers=OFFICER,
                     **overrides):
    return _ok(
        "post_transaction",
        api_client.post_transaction(
            account_id, transaction_payload(txn_type, amount_cents,
                                            **overrides), headers),
    )


def post_federal_benefit(account_id, amount_cents, posted_date,
                         headers=OFFICER):
    """Post a FEDERAL_BENEFIT_DEPOSIT credit with an explicit value date."""
    return post_transaction(
        account_id, "FEDERAL_BENEFIT_DEPOSIT", amount_cents, headers,
        customer_initiated=False, posted_date=posted_date,
    )


# ---------------------------------------------------------------------------
# Tier 2 — documents and signers
# ---------------------------------------------------------------------------

def submit_document(account_id, doc_type, reference_number, headers=OFFICER):
    return _ok("submit_document",
               api_client.submit_document(
                   account_id, document_payload(doc_type, reference_number),
                   headers))


def review_document(document_id, decision, headers=MANAGER, **overrides):
    return _ok("review_document",
               api_client.review_document(
                   document_id, review_payload(decision, **overrides),
                   headers))


def add_verified_document(account_id, doc_type, reference_number):
    """Submit a document and review it VERIFIED. Returns the document."""
    doc = submit_document(account_id, doc_type, reference_number)
    return review_document(doc["id"], "VERIFIED")


def add_active_signer(account_id, reference_number="SC-1", full_name="Sig S",
                      tax_id="TS-1", signer_role="AUTHORIZED_SIGNER"):
    """Stand up a VERIFIED SIGNATURE_CARD and add an ACTIVE signer on it."""
    add_verified_document(account_id, "SIGNATURE_CARD", reference_number)
    return _ok("add_signer",
               api_client.add_signer(
                   account_id,
                   signer_payload(reference_number, full_name=full_name,
                                  tax_id=tax_id, signer_role=signer_role),
                   OFFICER))


# ---------------------------------------------------------------------------
# Tier 3 — title changes, deceased cases, garnishments, conversions, cycles
# ---------------------------------------------------------------------------

def file_title_change(account_id, requested_ownership_type,
                      expected_account_version, pod_beneficiary_name=None,
                      headers=OFFICER_1):
    """File a title change (OCC-guarded). Returns the SUBMITTED request."""
    return _ok("file_title_change",
               api_client.file_title_change(
                   account_id,
                   title_change_payload(requested_ownership_type,
                                        expected_account_version,
                                        pod_beneficiary_name=pod_beneficiary_name),
                   headers))


def report_deceased_case(account_id, date_of_death, decedent_name="Dec D",
                         reported_by="Kin D", headers=OFFICER):
    return _ok("report_deceased_case",
               api_client.report_deceased_case(
                   account_id,
                   deceased_case_payload(date_of_death,
                                         decedent_name=decedent_name,
                                         reported_by=reported_by),
                   headers))


def verify_deceased_case(case_id, headers=MANAGER):
    return _ok("verify_deceased_case",
               api_client.verify_deceased_case(case_id, headers))


def register_garnishment(account_id, amount_cents, served_date,
                         exemption_method="FEDERAL_LOOKBACK",
                         order_type="GARNISHMENT", creditor_name="CredCo",
                         headers=OFFICER_1):
    """Register a garnishment/levy; the hold lands atomically. Returns order."""
    return _ok("register_garnishment",
               api_client.register_garnishment(
                   account_id,
                   garnishment_payload(amount_cents, served_date,
                                       exemption_method,
                                       order_type=order_type,
                                       creditor_name=creditor_name),
                   headers))


def resolve_garnishment(order_id, resolution, headers=MANAGER_2, **overrides):
    return _ok("resolve_garnishment",
               api_client.resolve_garnishment(
                   order_id, resolve_payload(resolution, **overrides),
                   headers))


def schedule_conversion(account_id, to_product_code, new_rate_bps,
                        effective_date, headers=OFFICER):
    return _ok("schedule_conversion",
               api_client.schedule_conversion(
                   account_id,
                   conversion_payload(to_product_code, new_rate_bps,
                                      effective_date),
                   headers))


def schedule_statement_cycle(account_id, cycle_start, cycle_end,
                             headers=OFFICER):
    return _ok("schedule_statement_cycle",
               api_client.schedule_statement_cycle(
                   account_id, statement_cycle_payload(cycle_start, cycle_end),
                   headers))


# ---------------------------------------------------------------------------
# Tier 4 — composite lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_verified_estate(opening_deposit_cents=100000, rate_bps=0,
                          product_code="SAVINGS",
                          primary_owner_name="Dec D", owner_tax_id="T-D",
                          date_of_death="2026-08-01", reported_by="Kin D",
                          doc_prefix=""):
    """Account + VERIFIED DEATH_CERTIFICATE and LETTERS_TESTAMENTARY +
    VERIFIED deceased case. Returns (account, case)."""
    acct = open_account(opening_deposit_cents=opening_deposit_cents,
                        rate_bps=rate_bps, product_code=product_code,
                        primary_owner_name=primary_owner_name,
                        owner_tax_id=owner_tax_id)
    add_verified_document(acct["id"], "DEATH_CERTIFICATE",
                          f"{doc_prefix}DC-1")
    add_verified_document(acct["id"], "LETTERS_TESTAMENTARY",
                          f"{doc_prefix}LT-1")
    case = report_deceased_case(acct["id"], date_of_death,
                                decedent_name=primary_owner_name,
                                reported_by=reported_by)
    case = verify_deceased_case(case["id"])
    return acct, case


def make_dormant_account(opening_deposit_cents=100000, rate_bps=0,
                         product_code="SAVINGS", **account_overrides):
    """Open an account at the default clock, advance the clock exactly 365
    days, and sweep it into DORMANT (entry fee posts). Returns the account
    as read after the sweep."""
    acct = open_account(opening_deposit_cents=opening_deposit_cents,
                        rate_bps=rate_bps, product_code=product_code,
                        **account_overrides)
    set_clock("2027-08-01T00:00:00Z")
    run_sweep()
    return get_account(acct["id"])


def close_with_fresh_version(account_id, headers=OFFICER):
    """Re-read the account and close it with the current version (OCC)."""
    acct = get_account(account_id)
    return _ok("close_account",
               api_client.close_account(
                   account_id,
                   {"expected_account_version": acct["version"]},
                   headers))


def initiate_release(case_id, release_variant,
                     estate_representative_name="Exec E", headers=OFFICER_1):
    return _ok("initiate_release",
               api_client.initiate_release(
                   case_id,
                   initiate_release_payload(
                       release_variant,
                       estate_representative_name=estate_representative_name),
                   headers))
