"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds all required
preconditions from scratch using only PRD-declared endpoints. The runner restarts
the server before every test (empty DB, logical clock reset to
2026-05-01T00:00:00Z), so nothing carries over.

Setup calls use get_success_data() (lenient) so a broken precondition surfaces as
a clear "Setup failed" rather than a confusing assertion failure.

Role identities: Treasurer / Cashier / CollectionsOfficer / ReliefOfficer are
opaque (PRD 2.1); the shared constants suffice except where a four-eyes SoD
equality is under test, in which case a distinct X-User-ID is threaded via the
make_* header builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_tax_year_payload, create_escrow_agent_payload, create_parcel_payload,
    create_tax_bill_payload, create_relief_application_payload, create_payment_payload,
    create_refund_payload, create_referral_payload, decide_payload, sell_payload,
)
from .test_users import (
    TEST_USERS, make_treasurer_headers, make_collections_headers, make_relief_headers,
)

TREASURER = TEST_USERS["treasurer_headers"]
CASHIER = TEST_USERS["cashier_headers"]
COLLECTIONS = TEST_USERS["collections_headers"]
RELIEF = TEST_USERS["relief_headers"]


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def set_clock(api, iso: str):
    """Set the server logical clock to the given ISO 8601 instant (PRD 2.8)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, TREASURER))


# ----------------------------------------------------------------------
# Tier 1: base reference entities
# ----------------------------------------------------------------------
def create_tax_year(api, **overrides) -> dict:
    return get_success_data(api.create_tax_year(create_tax_year_payload(**overrides), TREASURER))


def create_escrow_agent(api, **overrides) -> dict:
    return get_success_data(api.create_escrow_agent(create_escrow_agent_payload(**overrides), TREASURER))


def create_parcel(api, **overrides) -> dict:
    return get_success_data(api.create_parcel(create_parcel_payload(**overrides), CASHIER))


def issue_bill(api, parcel_id, tax_year_id) -> dict:
    return get_success_data(api.create_tax_bill(create_tax_bill_payload(parcel_id, tax_year_id), TREASURER))


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------
def get_bill(api, bill_id, headers=TREASURER) -> dict:
    return get_success_data(api.get_tax_bill(bill_id, headers))


def bill_version(api, bill_id, headers=TREASURER) -> int:
    return get_bill(api, bill_id, headers)["version"]


def installments_by_bill(api, bill_id, headers=TREASURER) -> dict:
    """Return {sequence: installment} for the bill (via GET /installments?bill_id)."""
    resp = api.list_installments(headers, params={"bill_id": bill_id})
    data = get_success_data(resp)
    return {inst["sequence"]: inst for inst in data}


def installment_seq(api, bill_id, seq, headers=TREASURER) -> dict:
    return installments_by_bill(api, bill_id, headers)[seq]


def ledger_entries(api, bill_id, headers=TREASURER) -> list:
    return get_success_data(api.list_ledger_entries(bill_id, headers))


# ----------------------------------------------------------------------
# Payments
# ----------------------------------------------------------------------
def post_payment(api, bill_id, amount_cents, headers=CASHIER, **overrides) -> dict:
    return get_success_data(
        api.create_payment(create_payment_payload(bill_id, amount_cents, **overrides), headers))


def reverse_payment(api, payment_id, user_id="tr-1") -> dict:
    return get_success_data(api.reverse_payment(payment_id, make_treasurer_headers(user_id)))


# ----------------------------------------------------------------------
# Tier 2: composite bill setups
# ----------------------------------------------------------------------
def setup_year_parcel_bill(api, assessed_value_cents=20000000, parcel_number="APN-1",
                           property_class="RESIDENTIAL", ty_overrides=None) -> tuple:
    """Fresh tax year + parcel + issued bill. Returns (tax_year, parcel, bill)."""
    ty = create_tax_year(api, **(ty_overrides or {}))
    parcel = create_parcel(api, parcel_number=parcel_number,
                           assessed_value_cents=assessed_value_cents,
                           property_class=property_class)
    bill = issue_bill(api, parcel["id"], ty["id"])
    return ty, parcel, bill


def setup_first_installment_paid(api, assessed_value_cents=20000000, parcel_number="APN-1") -> tuple:
    """Bill with installment 1 paid in full at the default clock.

    Returns (tax_year, parcel, bill_after_payment)."""
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents, parcel_number)
    inst1 = installment_seq(api, bill["id"], 1)
    post_payment(api, bill["id"], inst1["principal_due_cents"])
    return ty, parcel, get_bill(api, bill["id"])


def setup_delinquent_second_installment(api, assessed_value_cents=5000000,
                                        clock="2026-09-16", parcel_number="APN-1") -> tuple:
    """Installment 1 paid, then clock advanced so installment 2 is DELINQUENT.

    Returns (tax_year, parcel, bill_after_clock)."""
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents, parcel_number)
    set_clock(api, clock)
    return ty, parcel, get_bill(api, bill["id"])


# ----------------------------------------------------------------------
# Tier 3: tax-sale referral setups
# ----------------------------------------------------------------------
def open_referral(api, bill_id, opener_user_id="co-1") -> dict:
    """Open a referral on a delinquent bill, echoing the current bill version."""
    ver = bill_version(api, bill_id, make_collections_headers(opener_user_id))
    payload = create_referral_payload(bill_id, ver)
    return get_success_data(api.create_referral(payload, make_collections_headers(opener_user_id)))


def setup_referred_bill(api, assessed_value_cents=5000000, clock="2026-09-16",
                        opener_user_id="co-1", parcel_number="APN-1") -> tuple:
    """Delinquent bill (principal >= threshold) with an open REFERRED referral.

    Returns (tax_year, parcel, bill, referral)."""
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents, clock, parcel_number)
    referral = open_referral(api, bill["id"], opener_user_id)
    return ty, parcel, get_bill(api, bill["id"]), referral


def redeem_referral(api, referral_id, user_id="co-1") -> dict:
    return get_success_data(api.redeem_referral(referral_id, make_collections_headers(user_id)))


def sell_referral(api, referral_id, sale_price_cents=None, user_id="tr-1") -> dict:
    return get_success_data(
        api.sell_referral(referral_id, sell_payload(sale_price_cents), make_treasurer_headers(user_id)))


# ----------------------------------------------------------------------
# Tier 4: relief-application setups
# ----------------------------------------------------------------------
def submit_relief(api, parcel_id, tax_year_id, relief_class, relief_type,
                  claimed_amount_cents=None, headers=CASHIER, **overrides) -> dict:
    payload = create_relief_application_payload(
        parcel_id, tax_year_id, relief_class, relief_type, claimed_amount_cents, **overrides)
    return get_success_data(api.create_relief_application(payload, headers))


def review_relief(api, app_id, user_id="ro-1") -> dict:
    return get_success_data(api.review_relief(app_id, make_relief_headers(user_id)))


def request_info(api, app_id, user_id="ro-1") -> dict:
    return get_success_data(api.request_info_relief(app_id, make_relief_headers(user_id)))


def resubmit_relief(api, app_id, headers=CASHIER) -> dict:
    return get_success_data(api.resubmit_relief(app_id, headers))


def decide_relief(api, app_id, decision, user_id="ro-1") -> dict:
    return get_success_data(
        api.decide_relief(app_id, decide_payload(decision), make_relief_headers(user_id)))


def setup_under_review_relief(api, parcel_id, tax_year_id, relief_class, relief_type,
                              claimed_amount_cents=None, **overrides) -> dict:
    """Submit a relief application and move it to UNDER_REVIEW."""
    app = submit_relief(api, parcel_id, tax_year_id, relief_class, relief_type,
                        claimed_amount_cents, **overrides)
    review_relief(api, app["id"])
    return app


# ----------------------------------------------------------------------
# Tier 5: refund setups
# ----------------------------------------------------------------------
def file_refund(api, bill_id, amount_cents, expected_version=None,
                mode="GROSS_OVERPAYMENT", requester_user_id="tr-1") -> dict:
    """File a refund as a Treasurer (four-eyes: decide with a different user)."""
    if expected_version is None:
        expected_version = bill_version(api, bill_id)
    payload = create_refund_payload(bill_id, amount_cents, expected_version, mode)
    return get_success_data(api.create_refund(payload, make_treasurer_headers(requester_user_id)))


def decide_refund(api, refund_id, decision, decider_user_id="tr-2") -> dict:
    return get_success_data(
        api.decide_refund(refund_id, decide_payload(decision), make_treasurer_headers(decider_user_id)))


def setup_overpaid_bill(api, assessed_value_cents=20000000, payment_cents=500000,
                        parcel_number="APN-1") -> tuple:
    """Bill overpaid by a single large payment. Returns (tax_year, parcel, bill)."""
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents, parcel_number)
    post_payment(api, bill["id"], payment_cents, tender_type="ACH")
    return ty, parcel, get_bill(api, bill["id"])
