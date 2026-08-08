"""Composite setup helpers for the RCM firm API.

Every helper drives only PRD-declared endpoints and uses the lenient
get_success_data validator so setup failures surface as clear "Setup failed"
errors. The test harness restarts the server (empty DB) before every test, so
each helper rebuilds all preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import (
    make_account_manager_headers, make_coder_headers, make_biller_headers,
    make_denial_specialist_headers, make_payment_poster_headers,
    make_credentialing_specialist_headers,
)

FAR_FUTURE_EXPIRATION = "2027-01-01T00:00:00Z"
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"

AM = make_account_manager_headers()
CRED = make_credentialing_specialist_headers()
PP = make_payment_poster_headers()
DS = make_denial_specialist_headers()


# ---- Granular building blocks ----
def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, AM))


def new_practice(api, **overrides):
    return get_success_data(api.create_practice(f.create_practice_payload(**overrides), AM))


def new_payer(api, **overrides):
    return get_success_data(api.create_payer(f.create_payer_payload(**overrides), AM))


def new_provider(api, practice_id, **overrides):
    return get_success_data(api.create_provider(
        f.create_provider_payload(practice_id, **overrides), CRED))


def submit_provider(api, provider_id):
    return get_success_data(api.submit_credentialing(provider_id, CRED))


def approve_provider(api, provider_id, expiration_date=FAR_FUTURE_EXPIRATION):
    submit_provider(api, provider_id)
    return get_success_data(api.decide_credentialing(
        provider_id, {"decision": "APPROVE", "expiration_date": expiration_date}, CRED))


def new_enrollment(api, provider_id, payer_id, effective_date="2026-01-01T00:00:00Z",
                   **overrides):
    return get_success_data(api.create_enrollment(
        f.create_enrollment_payload(provider_id, payer_id, effective_date, **overrides), CRED))


def new_active_enrollment(api, provider_id, payer_id, effective_date="2026-01-01T00:00:00Z"):
    enr = new_enrollment(api, provider_id, payer_id, effective_date)
    return get_success_data(api.activate_enrollment(enr["id"], CRED))


def new_fee_schedule_with_lines(api, practice_id, prices=None,
                                effective_date="2026-01-01T00:00:00Z", end_date=None):
    """Create a DRAFT fee schedule and add priced lines (not activated)."""
    if prices is None:
        prices = {"99213": 10000}
    payload = f.create_fee_schedule_payload(practice_id, effective_date)
    if end_date is not None:
        payload["end_date"] = end_date
    fs = get_success_data(api.create_fee_schedule(payload, AM))
    for cpt, allowed in prices.items():
        get_success_data(api.add_fee_schedule_line(
            fs["id"], f.create_fee_schedule_line_payload(cpt, allowed), AM))
    return fs


def activate_fee_schedule(api, fee_schedule_id, expected_practice_version):
    return get_success_data(api.activate_fee_schedule(
        fee_schedule_id, {"expected_practice_version": expected_practice_version}, AM))


def new_active_fee_schedule(api, practice_id, expected_practice_version, prices=None,
                            effective_date="2026-01-01T00:00:00Z", end_date=None):
    fs = new_fee_schedule_with_lines(api, practice_id, prices, effective_date, end_date)
    return activate_fee_schedule(api, fs["id"], expected_practice_version)


def new_claim(api, practice_id, provider_id, payer_id, **overrides):
    return get_success_data(api.create_claim(
        f.create_claim_payload(practice_id, provider_id, payer_id, **overrides),
        make_coder_headers()))


def add_claim_line(api, claim_id, **overrides):
    return get_success_data(api.add_claim_line(
        claim_id, f.create_claim_line_payload(**overrides), make_coder_headers()))


def scrub_claim(api, claim_id, coder_user_id="coder-1"):
    return get_success_data(api.scrub_claim(claim_id, make_coder_headers(coder_user_id)))


def submit_claim(api, claim_id, biller_user_id="biller-1"):
    return get_success_data(api.submit_claim(claim_id, make_biller_headers(biller_user_id)))


def accept_claim(api, claim_id):
    return get_success_data(api.accept_claim(claim_id, make_biller_headers()))


def new_remittance(api, payer_id, total_amount_cents=10000, remittance_ref="RA-1"):
    return get_success_data(api.create_remittance(
        f.create_remittance_payload(payer_id, remittance_ref, total_amount_cents), PP))


def new_posting(api, remittance_id, claim_id, expected_claim_version,
                insurance_paid_cents=0, patient_responsibility_cents=0, adjustment_cents=0):
    return get_success_data(api.create_posting(
        remittance_id,
        f.create_posting_payload(claim_id, expected_claim_version, insurance_paid_cents,
                                 patient_responsibility_cents, adjustment_cents),
        PP))


def new_denial(api, claim_id, **overrides):
    return get_success_data(api.create_denial(
        claim_id, f.create_denial_payload(**overrides), DS))


def new_appeal(api, denial_id, **overrides):
    return get_success_data(api.create_appeal(
        denial_id, f.create_appeal_payload(**overrides), DS))


def new_statement(api, claim_id):
    return get_success_data(api.create_statement(f.create_statement_payload(claim_id), PP))


# ---- Composite context builders ----
def setup_billing_context(api, *, clock=DEFAULT_CLOCK, billing_fee_pct=0.06,
                          timely_filing_days=90, appeal_window_days=60,
                          prices=None, fs_effective="2026-01-01T00:00:00Z", fs_end=None,
                          credential="approved", provider_expiration=FAR_FUTURE_EXPIRATION,
                          enrollment="active",
                          enrollment_effective="2026-01-01T00:00:00Z"):
    """Build practice + payer + provider + enrollment + ACTIVE fee schedule.

    credential: "approved" | "submitted" | "none"
    enrollment: "active" | "pending" | "none"
    Returns a context dict.
    """
    if clock is not None:
        set_clock(api, clock)
    practice = new_practice(api, billing_fee_pct=billing_fee_pct)
    payer = new_payer(api, timely_filing_days=timely_filing_days,
                      appeal_window_days=appeal_window_days)
    provider = new_provider(api, practice["id"])

    if credential == "approved":
        provider = approve_provider(api, provider["id"], provider_expiration)
    elif credential == "submitted":
        provider = submit_provider(api, provider["id"])

    enr = None
    if enrollment == "active":
        enr = new_active_enrollment(api, provider["id"], payer["id"], enrollment_effective)
    elif enrollment == "pending":
        enr = new_enrollment(api, provider["id"], payer["id"], enrollment_effective)

    fee_schedule = new_active_fee_schedule(
        api, practice["id"], practice["version"], prices, fs_effective, fs_end)

    return {
        "practice": practice,
        "payer": payer,
        "provider": provider,
        "enrollment": enr,
        "fee_schedule": fee_schedule,
    }


def setup_scrubbed_claim(api, *, deductible_remaining_cents=0, coinsurance_pct=0.20,
                         copay_cents=0, service_date="2026-05-15T00:00:00Z",
                         lines=None, coder_user_id="coder-1", **ctx_kwargs):
    """Full context + a claim scrubbed. lines: list of dicts {cpt_code, units,
    charge_amount_cents}. Returns ctx with 'claim' added."""
    ctx = setup_billing_context(api, **ctx_kwargs)
    claim = new_claim(api, ctx["practice"]["id"], ctx["provider"]["id"], ctx["payer"]["id"],
                      service_date=service_date,
                      deductible_remaining_cents=deductible_remaining_cents,
                      coinsurance_pct=coinsurance_pct, copay_cents=copay_cents)
    if lines is None:
        lines = [{"cpt_code": "99213", "units": 1, "charge_amount_cents": 15000}]
    for ln in lines:
        add_claim_line(api, claim["id"], **ln)
    claim = scrub_claim(api, claim["id"], coder_user_id)
    ctx["claim"] = claim
    ctx["coder_user_id"] = coder_user_id
    return ctx


def setup_accepted_claim(api, *, coder_user_id="coder-1", biller_user_id="biller-1",
                         **kwargs):
    """Scrubbed -> submitted -> accepted. Returns ctx with 'claim' (accepted) and
    'claim_version' (version after accept, for OCC postings)."""
    ctx = setup_scrubbed_claim(api, coder_user_id=coder_user_id, **kwargs)
    submit_claim(api, ctx["claim"]["id"], biller_user_id)
    claim = accept_claim(api, ctx["claim"]["id"])
    ctx["claim"] = claim
    ctx["claim_version"] = claim["version"]
    ctx["biller_user_id"] = biller_user_id
    return ctx


def setup_denied_claim(api, *, denial_code="CO-97", denied_amount_cents=5000,
                       denial_date="2026-05-20T00:00:00Z", **kwargs):
    """Accepted -> denied. Returns ctx with 'claim' (denied) and 'denial'."""
    ctx = setup_accepted_claim(api, **kwargs)
    denial = new_denial(api, ctx["claim"]["id"], denial_code=denial_code,
                        denied_amount_cents=denied_amount_cents, denial_date=denial_date)
    ctx["denial"] = denial
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], AM))
    return ctx


def setup_drafted_appeal(api, *, level=1, narrative="Records support medical necessity.",
                         **kwargs):
    """Denied -> appeal drafted (still DRAFT). Returns ctx with 'appeal'."""
    ctx = setup_denied_claim(api, **kwargs)
    appeal = new_appeal(api, ctx["denial"]["id"], level=level, narrative=narrative)
    ctx["appeal"] = appeal
    return ctx


def setup_appealed_claim(api, **kwargs):
    """Denied -> appeal drafted -> submitted (claim now APPEALED). Returns ctx with
    'appeal' (SUBMITTED), 'denial', and refreshed 'claim'."""
    ctx = setup_drafted_appeal(api, **kwargs)
    appeal = get_success_data(api.submit_appeal(ctx["appeal"]["id"], DS))
    ctx["appeal"] = appeal
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], AM))
    ctx["denial"] = get_success_data(api.get_denial(ctx["denial"]["id"], AM))
    return ctx


def setup_sent_statement(api, *, deductible_remaining_cents=3000, coinsurance_pct=0.20,
                         copay_cents=2000, send_clock="2026-06-01T00:00:00Z", **kwargs):
    """Scrubbed claim with a positive patient balance -> statement created and SENT.
    Returns ctx with 'statement' and 'claim'."""
    ctx = setup_scrubbed_claim(api, deductible_remaining_cents=deductible_remaining_cents,
                               coinsurance_pct=coinsurance_pct, copay_cents=copay_cents,
                               **kwargs)
    stmt = new_statement(api, ctx["claim"]["id"])
    stmt = get_success_data(api.send_statement(stmt["id"], PP))
    ctx["statement"] = stmt
    return ctx
