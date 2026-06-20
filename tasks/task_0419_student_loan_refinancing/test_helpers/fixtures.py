"""Composite setup helpers for the Student Loan Refi API.

Every fixture builds its own preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before every
test. Fixtures use the lenient get_success_data() validator so a setup failure
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: Borrower and Cosigner are entity-backed roles, so any
ownership-gated call uses make_borrower_headers(borrower["id"]) /
make_cosigner_headers(cosigner["id"]) with the real entity id.
"""
import uuid
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
    make_cosigner_headers,
    make_underwriter_headers,
    make_disbursement_officer_headers,
    make_servicing_agent_headers,
)
from .factories import (
    create_borrower_payload,
    create_abs_pool_payload,
    create_rate_grid_entry_payload,
    create_application_payload,
    create_cosigner_payload,
    lock_offer_payload,
    create_disbursement_payload,
    create_payment_payload,
    create_forbearance_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 0: bootstrap primitives
# ---------------------------------------------------------------------------
def create_rate_grid_entry(**overrides):
    payload = create_rate_grid_entry_payload(**overrides)
    return get_success_data(api_client.create_rate_grid_entry(payload, ADMIN))


def create_abs_pool(**overrides):
    payload = create_abs_pool_payload(**overrides)
    return get_success_data(api_client.create_abs_pool(payload, ADMIN))


def create_borrower(**overrides):
    payload = create_borrower_payload(**overrides)
    return get_success_data(api_client.create_borrower(payload, TEST_USERS["borrower_headers"]))


def create_application(borrower, **overrides):
    payload = create_application_payload(borrower_id=borrower["id"], **overrides)
    headers = make_borrower_headers(borrower["id"])
    return get_success_data(api_client.create_application(payload, headers))


def invite_cosigner(borrower, application, **overrides):
    payload = create_cosigner_payload(application_id=application["id"], **overrides)
    headers = make_borrower_headers(borrower["id"])
    return get_success_data(api_client.create_cosigner(payload, headers))


def consent_cosigner(cosigner):
    headers = make_cosigner_headers(cosigner["id"])
    return get_success_data(api_client.consent_cosigner(cosigner["id"], headers))


def prequalify(borrower, application):
    headers = make_borrower_headers(borrower["id"])
    return get_success_data(api_client.prequalify_application(application["id"], headers))


def get_application(application_id):
    return get_success_data(api_client.get_application(application_id, ADMIN))


def list_offers(borrower, application_id):
    headers = make_borrower_headers(borrower["id"])
    return get_success_data(api_client.list_offers(headers, params={"application_id": application_id}))


# ---------------------------------------------------------------------------
# Tier 1: application reaching a target lifecycle state
# ---------------------------------------------------------------------------
def setup_prequalified_application(
    *,
    grid_overrides=None,
    borrower_overrides=None,
    application_overrides=None,
    with_cosigner=False,
    cosigner_overrides=None,
    cosigner_consents=False,
):
    """Bootstrap a grid cell + borrower + application, optionally attach a
    cosigner, then prequalify. Returns a dict with borrower, application
    (the post-prequalify view), offers list, and cosigner (if any).
    """
    grid = create_rate_grid_entry(**(grid_overrides or {}))
    borrower = create_borrower(**(borrower_overrides or {}))
    application = create_application(borrower, **(application_overrides or {}))

    cosigner = None
    if with_cosigner:
        cosigner = invite_cosigner(borrower, application, **(cosigner_overrides or {}))
        if cosigner_consents:
            consent_cosigner(cosigner)

    prequalify(borrower, application)
    application = get_application(application["id"])
    offers = list_offers(borrower, application["id"])
    return {
        "grid": grid,
        "borrower": borrower,
        "application": application,
        "offers": offers,
        "cosigner": cosigner,
    }


def setup_locked_application(
    *,
    autopay_elected=False,
    grid_overrides=None,
    borrower_overrides=None,
    application_overrides=None,
    with_cosigner=False,
    cosigner_overrides=None,
):
    """Prequalify then lock the first offer. Cosigner (if attached) consents so
    the lock is not blocked. Returns the prequalified bundle plus locked_offer
    and the post-lock application (UNDER_REVIEW)."""
    bundle = setup_prequalified_application(
        grid_overrides=grid_overrides,
        borrower_overrides=borrower_overrides,
        application_overrides=application_overrides,
        with_cosigner=with_cosigner,
        cosigner_overrides=cosigner_overrides,
        cosigner_consents=with_cosigner,
    )
    borrower = bundle["borrower"]
    application = bundle["application"]
    offer = bundle["offers"][0]
    headers = make_borrower_headers(borrower["id"])
    payload = lock_offer_payload(application["version"], autopay_elected=autopay_elected)
    locked_offer = get_success_data(api_client.lock_offer(offer["id"], payload, headers))
    bundle["locked_offer"] = locked_offer
    bundle["application"] = get_application(application["id"])
    return bundle


def setup_approved_application(
    *,
    underwriter_id=None,
    autopay_elected=False,
    grid_overrides=None,
    borrower_overrides=None,
    application_overrides=None,
    with_cosigner=False,
    cosigner_overrides=None,
):
    """Lock then approve under an Underwriter. Returns the bundle plus
    underwriter_id used and the post-approve application (APPROVED)."""
    bundle = setup_locked_application(
        autopay_elected=autopay_elected,
        grid_overrides=grid_overrides,
        borrower_overrides=borrower_overrides,
        application_overrides=application_overrides,
        with_cosigner=with_cosigner,
        cosigner_overrides=cosigner_overrides,
    )
    uw_id = underwriter_id or _uid("uw")
    uw_headers = make_underwriter_headers(uw_id)
    get_success_data(api_client.approve_application(bundle["application"]["id"], uw_headers))
    bundle["underwriter_id"] = uw_id
    bundle["application"] = get_application(bundle["application"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 2/3: funded loan
# ---------------------------------------------------------------------------
def setup_funded_loan(
    *,
    underwriter_id=None,
    officer_id=None,
    autopay_elected=True,
    pool_overrides=None,
    grid_overrides=None,
    borrower_overrides=None,
    application_overrides=None,
    with_cosigner=False,
    cosigner_overrides=None,
    clock_at=None,
):
    """Full lifecycle through a funded Loan. Creates an eligible OPEN pool,
    approves, then funds under a DisbursementOfficer (distinct from the
    underwriter). Returns the bundle plus pool, loan, officer_id.

    If clock_at is supplied, the clock is set before any bootstrap so the
    loan's last_accrual_at lands on a known instant.
    """
    if clock_at is not None:
        set_clock(clock_at)
    pool = create_abs_pool(**(pool_overrides or {}))
    bundle = setup_approved_application(
        underwriter_id=underwriter_id,
        autopay_elected=autopay_elected,
        grid_overrides=grid_overrides,
        borrower_overrides=borrower_overrides,
        application_overrides=application_overrides,
        with_cosigner=with_cosigner,
        cosigner_overrides=cosigner_overrides,
    )
    do_id = officer_id or _uid("do")
    do_headers = make_disbursement_officer_headers(do_id)
    loan = get_success_data(api_client.fund_application(bundle["application"]["id"], do_headers))
    bundle["pool"] = pool
    bundle["loan"] = loan
    bundle["officer_id"] = do_id
    return bundle


def get_loan(loan_id):
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def get_cosigner(cosigner_id):
    return get_success_data(api_client.get_cosigner(cosigner_id, ADMIN))


def get_offer(offer_id):
    return get_success_data(api_client.get_offer(offer_id, ADMIN))


def get_abs_pool(pool_id):
    return get_success_data(api_client.get_abs_pool(pool_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: disbursements on a funded loan
# ---------------------------------------------------------------------------
def schedule_disbursement(loan, officer_id, **overrides):
    headers = make_disbursement_officer_headers(officer_id)
    payload = create_disbursement_payload(loan["id"], **overrides)
    return get_success_data(api_client.create_disbursement(payload, headers))


def send_disbursement(disbursement_id, officer_id):
    headers = make_disbursement_officer_headers(officer_id)
    return get_success_data(api_client.send_disbursement(disbursement_id, headers))


def confirm_disbursement(disbursement_id, officer_id):
    headers = make_disbursement_officer_headers(officer_id)
    return get_success_data(api_client.confirm_disbursement(disbursement_id, headers))


# ---------------------------------------------------------------------------
# Tier 3/4: servicing actions
# ---------------------------------------------------------------------------
def post_payment(loan, amount_cents, due_date, *, paid_at=None, servicing_agent_id=None):
    sa_id = servicing_agent_id or _uid("sa")
    headers = make_servicing_agent_headers(sa_id)
    payload = create_payment_payload(amount_cents, due_date, **({"paid_at": paid_at} if paid_at else {}))
    return get_success_data(api_client.create_payment(loan["id"], payload, headers))


def start_forbearance(loan, *, servicing_agent_id=None, **overrides):
    sa_id = servicing_agent_id or _uid("sa")
    headers = make_servicing_agent_headers(sa_id)
    payload = create_forbearance_payload(**overrides)
    return get_success_data(api_client.start_forbearance(loan["id"], payload, headers))


def mark_delinquent(loan, *, servicing_agent_id=None):
    sa_id = servicing_agent_id or _uid("sa")
    headers = make_servicing_agent_headers(sa_id)
    return get_success_data(api_client.mark_delinquent(loan["id"], headers))


def list_forbearance_plans(loan_id, *, status=None, servicing_agent_id=None):
    sa_id = servicing_agent_id or _uid("sa")
    headers = make_servicing_agent_headers(sa_id)
    params = {"loan_id": loan_id}
    if status:
        params["status"] = status
    return get_success_data(api_client.list_forbearance_plans(headers, params=params))


# ---------------------------------------------------------------------------
# Tier 4: drive a cosigner to release-eligible (3 on-time payments)
# ---------------------------------------------------------------------------
def setup_loan_with_eligible_cosigner(
    *,
    base_clock="2026-06-01T00:00:00Z",
    payment_amount_cents=40_000,
    pool_overrides=None,
):
    """Fund a loan that has a CONSENTED cosigner, then post 3 consecutive
    on-time payments across monthly clock advances so on_time_streak reaches
    COSIGNER_RELEASE_STREAK (3) and cosigner_release_status becomes ELIGIBLE.
    Returns the funded bundle (with loan re-read), the cosigner re-read, and
    servicing_agent_id used for all payments.
    """
    bundle = setup_funded_loan(
        clock_at=base_clock,
        autopay_elected=False,
        pool_overrides=pool_overrides,
        with_cosigner=True,
    )
    loan = bundle["loan"]
    sa_id = _uid("sa")
    schedule = [
        ("2026-06-01T00:00:00Z", "2026-06-01T00:00:00Z"),
        ("2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ("2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"),
    ]
    for due, paid in schedule:
        set_clock(paid)
        post_payment(loan, payment_amount_cents, due, paid_at=paid, servicing_agent_id=sa_id)
    bundle["loan"] = get_loan(loan["id"])
    bundle["cosigner"] = get_cosigner(bundle["cosigner"]["id"])
    bundle["servicing_agent_id"] = sa_id
    return bundle
