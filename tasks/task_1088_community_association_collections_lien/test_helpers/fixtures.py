"""Composite setup helpers for the collections/lien domain.

Every fixture builds its preconditions from scratch (the server DB is empty
before each test) using only PRD-declared endpoints, and uses the lenient
get_success_data() so setup problems surface as clear "Setup failed" errors.

Officer identity threading: liens and foreclosure referrals record the acting
X-User-ID. The maker-checker SoD requires the referring officer to differ from
the recording officer, so these helpers accept explicit officer user_ids.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_trust_accountant_headers,
)
from .factories import (
    create_association_payload,
    create_account_payload,
    create_assessment_payload,
    create_payment_payload,
    create_notice_payload,
    create_payment_plan_payload,
    create_lien_payload,
    create_foreclosure_referral_payload,
    create_bankruptcy_case_payload,
    create_remittance_payload,
)

AGENT = TEST_USERS["collections_agent_headers"]
TRUSTEE = TEST_USERS["trust_accountant_headers"]


# --- primitives ---------------------------------------------------------------

def set_clock(api, iso, headers=AGENT):
    return get_success_data(api.set_clock(iso, headers))


def create_association(api, **overrides):
    return get_success_data(api.create_association(create_association_payload(**overrides), AGENT))


def create_account(api, association_id, **overrides):
    return get_success_data(
        api.create_account(create_account_payload(association_id, **overrides), AGENT))


def create_assessment(api, account_id, amount_cents, **overrides):
    return get_success_data(
        api.create_assessment(create_assessment_payload(account_id, amount_cents, **overrides), AGENT))


def create_payment(api, account_id, amount_cents, received_date, **overrides):
    return get_success_data(
        api.create_payment(create_payment_payload(account_id, amount_cents, received_date, **overrides), AGENT))


def account_version(api, account_id):
    return get_success_data(api.get_account(account_id, AGENT))["version"]


def association_version(api, association_id):
    return get_success_data(api.get_association(association_id, TRUSTEE))["version"]


# --- Tier 1/2: association + account, optionally delinquent -------------------

def setup_account(api, assoc_overrides=None, acct_overrides=None):
    """Active association + one CURRENT account. Returns (association, account)."""
    assoc = create_association(api, **(assoc_overrides or {}))
    acct = create_account(api, assoc["id"], **(acct_overrides or {}))
    return assoc, acct


def setup_delinquent_account(api, amount_cents=200000, due_date="2026-01-01T00:00:00Z",
                             charge_type="REGULAR", assoc_overrides=None, acct_overrides=None):
    """Association + account with one overdue assessment, marked DELINQUENT.
    Returns dict(association, account, assessment)."""
    assoc, acct = setup_account(api, assoc_overrides, acct_overrides)
    asm = create_assessment(api, acct["id"], amount_cents,
                            charge_type=charge_type, due_date=due_date)
    acct = get_success_data(api.transition_account(acct["id"], "DELINQUENT", AGENT))
    return {"association": assoc, "account": acct, "assessment": asm}


# --- Tier 3: notice lifecycle ------------------------------------------------

def setup_sent_intent_to_lien(api, amount_cents=200000, sent_date="2026-01-01T00:00:00Z",
                              due_date="2026-01-01T00:00:00Z"):
    """Delinquent account with an INTENT_TO_LIEN notice moved to SENT at `sent_date`.
    Clock is left at `sent_date`. Returns dict(association, account, assessment, notice)."""
    set_clock(api, sent_date)
    base = setup_delinquent_account(api, amount_cents=amount_cents, due_date=due_date)
    notice = get_success_data(
        api.create_notice(create_notice_payload(base["account"]["id"], "INTENT_TO_LIEN"), AGENT))
    notice = get_success_data(api.transition_notice(notice["id"], "SENT", AGENT))
    base["notice"] = notice
    return base


def setup_recorded_lien(api, amount_cents=200000, sent_date="2026-01-01T00:00:00Z",
                        record_date="2026-02-01T00:00:00Z", officer_id="officer-1"):
    """Drive an account to LIEN: intent-to-lien sent, validation period elapsed,
    lien recorded by `officer_id`. Clock left at `record_date`.
    Returns dict(association, account, assessment, notice, lien, officer_id)."""
    base = setup_sent_intent_to_lien(api, amount_cents=amount_cents, sent_date=sent_date)
    set_clock(api, record_date)
    officer = make_compliance_officer_headers(officer_id)
    lien = get_success_data(api.create_lien(create_lien_payload(base["account"]["id"]), officer))
    base["lien"] = lien
    base["officer_id"] = officer_id
    return base


def setup_filed_referral(api, amount_cents=200000, sent_date="2026-01-01T00:00:00Z",
                         record_date="2026-02-01T00:00:00Z",
                         recorder_id="officer-1", referrer_id="officer-2"):
    """Drive an account to FORECLOSURE: lien recorded by recorder_id, referral
    created by referrer_id (SoD) then FILED. Returns dict with lien, referral."""
    base = setup_recorded_lien(api, amount_cents=amount_cents, sent_date=sent_date,
                               record_date=record_date, officer_id=recorder_id)
    referrer = make_compliance_officer_headers(referrer_id)
    ref = get_success_data(api.create_foreclosure_referral(
        create_foreclosure_referral_payload(base["account"]["id"], base["lien"]["id"]), referrer))
    ref = get_success_data(api.transition_foreclosure_referral(ref["id"], "FILED", referrer))
    base["referral"] = ref
    base["referrer_id"] = referrer_id
    return base


# --- Tier 3: payment plans ---------------------------------------------------

def setup_active_plan(api, amount_cents=60000, total_amount_cents=60000, installment_cents=20000,
                      num_installments=3, first_due_date="2026-06-01T00:00:00Z",
                      due_date="2026-01-01T00:00:00Z", clock="2026-05-01T00:00:00Z"):
    """Account DELINQUENT with an ACTIVE payment plan. Clock left at `clock`.
    Returns dict(association, account, assessment, plan)."""
    set_clock(api, clock)
    base = setup_delinquent_account(api, amount_cents=amount_cents, due_date=due_date)
    v = account_version(api, base["account"]["id"])
    plan = get_success_data(api.create_payment_plan(create_payment_plan_payload(
        base["account"]["id"], total_amount_cents, installment_cents, num_installments,
        first_due_date, v), AGENT))
    plan = get_success_data(api.transition_payment_plan(plan["id"], "ACTIVE", AGENT))
    base["plan"] = plan
    return base


def setup_draft_plan(api, amount_cents=90000, total_amount_cents=60000, installment_cents=20000,
                     num_installments=3, first_due_date="2026-06-01T00:00:00Z",
                     due_date="2026-01-01T00:00:00Z", clock="2026-05-01T00:00:00Z"):
    """Account DELINQUENT with one DRAFT plan (not activated). Returns dict with plan
    and the current account version for a follow-on create."""
    set_clock(api, clock)
    base = setup_delinquent_account(api, amount_cents=amount_cents, due_date=due_date)
    v = account_version(api, base["account"]["id"])
    plan = get_success_data(api.create_payment_plan(create_payment_plan_payload(
        base["account"]["id"], total_amount_cents, installment_cents, num_installments,
        first_due_date, v), AGENT))
    base["plan"] = plan
    base["account_version"] = account_version(api, base["account"]["id"])
    return base


# --- Tier 4: remittance targeting --------------------------------------------

def setup_remittance_pool(api, management_fee_pct=20.0, payments=None):
    """Association + one account with a set of payments.

    `payments` is a list of dicts: {amount, received_date, reverse (bool)}.
    Returns dict(association, account, payment_ids, association_version).
    """
    assoc = create_association(api, name="Pool HOA", management_fee_pct=management_fee_pct)
    acct = create_account(api, assoc["id"])
    ids = []
    for p in (payments or []):
        pay = create_payment(api, acct["id"], p["amount"], p["received_date"])
        if p.get("reverse"):
            get_success_data(api.reverse_payment(pay["id"], "NSF", AGENT))
        ids.append(pay["id"])
    return {
        "association": assoc,
        "account": acct,
        "payment_ids": ids,
        "association_version": association_version(api, assoc["id"]),
    }


def create_remittance(api, association_id, period_start, period_end, expected_version,
                      basis=None):
    payload = create_remittance_payload(association_id, period_start, period_end, expected_version)
    if basis is not None:
        payload["basis"] = basis
    return get_success_data(api.create_remittance(payload, TRUSTEE))


# --- Tier: bankruptcy --------------------------------------------------------

def file_bankruptcy(api, account_id, filed_date, officer_id="officer-2",
                    chapter="CH13", case_number="26-0001"):
    officer = make_compliance_officer_headers(officer_id)
    return get_success_data(api.create_bankruptcy_case(
        create_bankruptcy_case_payload(account_id, filed_date, chapter=chapter,
                                       case_number=case_number), officer))
