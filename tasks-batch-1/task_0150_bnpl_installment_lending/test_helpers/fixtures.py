"""Composite setup helpers for the BNPL Installment Lending suite.

Each individual pytest test runs against a freshly-restarted, empty server, so
every fixture below builds its preconditions from scratch using only PRD-declared
endpoints. Fixtures use get_success_data() (lenient) internally so setup failures
surface as clear "Setup step failed" errors.

Identity threading: Borrower and Merchant are entity-backed (PRD §2.1); after a
fixture creates one, every ownership-gated call uses make_borrower_headers(id) /
make_merchant_headers(id) with the real entity id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_merchant_payload,
    create_borrower_payload,
    create_application_payload,
    create_disclosure_acceptance_payload,
    create_loan_payload,
    create_payment_payload,
    create_autopay_mandate_payload,
    decision_payload,
    clock_payload,
)
from .test_users import make_servicer_headers, make_borrower_headers, make_merchant_headers


SERVICER = make_servicer_headers()

# Default activation clock used across time-sensitive fixtures.
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Borrower profiles used throughout the index.
# High-limit borrower: score 760, income 8_000_000 -> eligible 500000.
HIGH_LIMIT_PROFILE = {"soft_credit_score": 760, "annual_income_cents": 8_000_000}
# Mid-limit borrower: score 620, income 2_000_000 -> eligible 50000.
MID_LIMIT_PROFILE = {"soft_credit_score": 620, "annual_income_cents": 2_000_000}


# --------------------------------------------------------------------------
# Tier 0: clock control
# --------------------------------------------------------------------------
def set_clock(iso: str):
    """Advance the operator clock to the given UTC instant (PRD §3.6)."""
    return get_success_data(api_client.set_clock(clock_payload(iso), SERVICER))


# --------------------------------------------------------------------------
# Tier 1: single-entity creation
# --------------------------------------------------------------------------
def create_merchant(mdr_bps: int = 600, settlement_hold_days=None, display_name="M") -> dict:
    """Register an ACTIVE merchant. settlement_hold_days omitted -> server default."""
    overrides = {"display_name": display_name, "mdr_bps": mdr_bps}
    if settlement_hold_days is not None:
        overrides["settlement_hold_days"] = settlement_hold_days
    payload = create_merchant_payload(**overrides)
    return get_success_data(api_client.create_merchant(payload, SERVICER))


def create_borrower(email="ba@x.com", full_name="BA", **profile) -> dict:
    """Register a borrower. profile overrides soft_credit_score / annual_income_cents.
    Defaults to the high-limit profile (eligible 500000)."""
    merged = dict(HIGH_LIMIT_PROFILE)
    merged.update(profile)
    payload = create_borrower_payload(email=email, full_name=full_name, **merged)
    return get_success_data(api_client.create_borrower(payload, SERVICER))


def suspend_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.suspend_merchant(merchant_id, SERVICER))


# --------------------------------------------------------------------------
# Tier 2: application lifecycle
# --------------------------------------------------------------------------
def create_application(borrower_id: str, merchant_id: str, **overrides) -> dict:
    """Submit an application as the owning borrower."""
    payload = create_application_payload(borrower_id, merchant_id, **overrides)
    return get_success_data(
        api_client.create_application(payload, make_borrower_headers(borrower_id))
    )


def decide_application(application_id: str, decision: str) -> dict:
    """Servicer decides an application (APPROVE / COUNTER / DECLINE)."""
    return get_success_data(
        api_client.decide_application(application_id, decision_payload(decision), SERVICER)
    )


def accept_disclosure(application_id: str, borrower_id: str, accepted: bool = True) -> dict:
    """Borrower records a Reg Z disclosure acceptance for an APPROVED application."""
    payload = create_disclosure_acceptance_payload(application_id, accepted=accepted)
    return get_success_data(
        api_client.create_disclosure_acceptance(payload, make_borrower_headers(borrower_id))
    )


def activate_loan(application_id: str, borrower_id: str) -> dict:
    """Borrower activates an APPROVED+disclosed application into a Loan."""
    payload = create_loan_payload(application_id)
    return get_success_data(
        api_client.create_loan(payload, make_borrower_headers(borrower_id))
    )


# --------------------------------------------------------------------------
# Tier 3: full origination shortcut (merchant + borrower + approved+activated loan)
# --------------------------------------------------------------------------
def setup_activated_loan(
    cart_amount_cents: int = 100_000,
    plan_type: str = "PAY_IN_4",
    term_months=None,
    requested_down_payment_cents: int = 0,
    mdr_bps: int = 600,
    settlement_hold_days=None,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    borrower_profile=None,
    borrower_email="ba@x.com",
    merchant_display_name="M",
):
    """Full origination: clock -> merchant -> borrower -> application -> APPROVE
    -> accept disclosure -> activate loan.

    Returns dict with keys: merchant, borrower, application, loan
    (all the post-activation resource bodies as returned by the API).
    """
    set_clock(clock_iso)
    merchant = create_merchant(
        mdr_bps=mdr_bps, settlement_hold_days=settlement_hold_days,
        display_name=merchant_display_name,
    )
    profile = borrower_profile if borrower_profile is not None else HIGH_LIMIT_PROFILE
    borrower = create_borrower(email=borrower_email, **profile)

    app_overrides = {
        "cart_amount_cents": cart_amount_cents,
        "plan_type": plan_type,
        "requested_down_payment_cents": requested_down_payment_cents,
    }
    if term_months is not None:
        app_overrides["term_months"] = term_months
    application = create_application(borrower["id"], merchant["id"], **app_overrides)

    decide_application(application["id"], "APPROVE")
    accept_disclosure(application["id"], borrower["id"], accepted=True)
    loan = activate_loan(application["id"], borrower["id"])

    return {
        "merchant": merchant,
        "borrower": borrower,
        "application": application,
        "loan": loan,
    }


def setup_approved_application(
    cart_amount_cents: int = 100_000,
    plan_type: str = "PAY_IN_4",
    term_months=None,
    requested_down_payment_cents: int = 0,
    mdr_bps: int = 600,
    borrower_profile=None,
    borrower_email="ba@x.com",
    accept: bool = False,
):
    """Origination through APPROVED (optionally with a disclosure acceptance), but
    NOT activated. Returns dict: merchant, borrower, application[, disclosure]."""
    merchant = create_merchant(mdr_bps=mdr_bps)
    profile = borrower_profile if borrower_profile is not None else HIGH_LIMIT_PROFILE
    borrower = create_borrower(email=borrower_email, **profile)

    app_overrides = {
        "cart_amount_cents": cart_amount_cents,
        "plan_type": plan_type,
        "requested_down_payment_cents": requested_down_payment_cents,
    }
    if term_months is not None:
        app_overrides["term_months"] = term_months
    application = create_application(borrower["id"], merchant["id"], **app_overrides)
    decide_application(application["id"], "APPROVE")

    result = {"merchant": merchant, "borrower": borrower, "application": application}
    if accept:
        result["disclosure"] = accept_disclosure(application["id"], borrower["id"], True)
    return result


# --------------------------------------------------------------------------
# Tier 3b: helpers to fetch derived resources of an activated loan
# --------------------------------------------------------------------------
def get_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan(loan_id, SERVICER))


def get_borrower(borrower_id: str) -> dict:
    return get_success_data(api_client.get_borrower(borrower_id, SERVICER))


def get_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, SERVICER))


def list_installments(loan_id: str) -> list:
    data, _meta = _paginated(api_client.list_installments(SERVICER, params={"loan_id": loan_id}))
    return data


def get_settlement_for_loan(loan_id: str) -> dict:
    """Return the single MerchantSettlement row produced by activating the loan."""
    data, _meta = _paginated(
        api_client.list_merchant_settlements(SERVICER, params={"loan_id": loan_id})
    )
    assert data, f"no settlement found for loan {loan_id}"
    return data[0]


def _paginated(response):
    body = get_success_data(response)
    # get_success_data returns body['data']; meta is on the full body, but for setup
    # we only need the list. Re-read the raw json for meta.
    meta = response.json().get("meta", {})
    return body, meta


# --------------------------------------------------------------------------
# Tier 4: state progression for late-fee / delinquency / settlement tests
# --------------------------------------------------------------------------
def setup_loan_then_advance_clock(advance_to_iso: str, **loan_overrides):
    """setup_activated_loan, then advance the clock to advance_to_iso.
    Returns the dict from setup_activated_loan augmented with refreshed
    'loan' and 'installments'."""
    ctx = setup_activated_loan(**loan_overrides)
    set_clock(advance_to_iso)
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    ctx["installments"] = list_installments(ctx["loan"]["id"])
    return ctx


def setup_released_settlement(
    cart_amount_cents: int = 100_000,
    mdr_bps: int = 600,
    clock_iso: str = DEFAULT_CLOCK_ISO,
):
    """Activate a loan with settlement_hold_days=0 and release its settlement.
    Returns dict: merchant, borrower, application, loan, settlement (RELEASED)."""
    ctx = setup_activated_loan(
        cart_amount_cents=cart_amount_cents,
        mdr_bps=mdr_bps,
        settlement_hold_days=0,
        clock_iso=clock_iso,
    )
    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    released = get_success_data(
        api_client.release_merchant_settlement(settlement["id"], SERVICER)
    )
    ctx["settlement"] = released
    return ctx


def setup_autopay_loan(
    cart_amount_cents: int = 100_000,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    mdr_bps: int = 600,
):
    """Activate a loan and enable an autopay mandate on it.
    Returns dict: merchant, borrower, application, loan, mandate (ENABLED)."""
    ctx = setup_activated_loan(
        cart_amount_cents=cart_amount_cents, mdr_bps=mdr_bps, clock_iso=clock_iso
    )
    mandate = get_success_data(
        api_client.create_autopay_mandate(
            create_autopay_mandate_payload(ctx["loan"]["id"]),
            make_borrower_headers(ctx["borrower"]["id"]),
        )
    )
    ctx["mandate"] = mandate
    return ctx


def make_payment(loan_id: str, borrower_id: str, amount_cents: int, source: str = "MANUAL") -> dict:
    """Borrower pays its own loan."""
    payload = create_payment_payload(loan_id, amount_cents, source=source)
    return get_success_data(
        api_client.create_payment(payload, make_borrower_headers(borrower_id))
    )
