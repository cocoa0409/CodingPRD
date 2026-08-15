"""Composite setup helpers for the dispute / chargeback lifecycle.

Every fixture builds its preconditions from scratch via the public endpoints,
using get_success_data() so setup failures surface as clear "Setup step failed"
errors. Ownership-gated calls thread the real CardAccount id through
make_cardholder_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK
from .factories import (
    classify_payload,
    create_card_account_payload,
    create_card_transaction_payload,
    create_chargeback_payload,
    create_dispute_payload,
    create_representment_payload,
    resolve_payload,
    review_representment_payload,
)
from .test_users import (
    TEST_USERS,
    make_cardholder_headers,
    make_investigator_headers,
)

ADMIN = TEST_USERS["bank_admin_headers"]
INTAKE = TEST_USERS["intake_agent_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
ANALYST = TEST_USERS["chargeback_analyst_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression — clock, account, transaction, dispute, classify
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_account(balance=100000, name="Test Cardholder", clock=CLOCK["ACCOUNT_OPEN"]):
    """Set the logical clock (when given) and open an ACTIVE account."""
    if clock is not None:
        set_clock(clock)
    data = get_success_data(api_client.create_card_account(
        create_card_account_payload(cardholder_name=name,
                                    initial_balance_cents=balance),
        ADMIN,
    ))
    return data


def create_transaction(account_id, amount=10000, txn_type="ECOMMERCE",
                       network="VISA", posted_at=CLOCK["TXN_POSTED"]):
    """Seed a POSTED transaction against an account."""
    return get_success_data(api_client.create_card_transaction(
        create_card_transaction_payload(
            account_id, amount_cents=amount, transaction_type=txn_type,
            network=network, posted_at=posted_at,
        ),
        ADMIN,
    ))


def file_dispute(transaction_id, account_id, claim_amount_cents,
                 error_type="INCORRECT_AMOUNT", claimed_delay=5,
                 received_clock=CLOCK["DISPUTE_RECEIVED"], by_intake_agent=None):
    """File a dispute (transaction POSTED -> DISPUTED, case RECEIVED).

    Filed by the owning Cardholder by default; pass by_intake_agent=<op id>
    to file as an IntakeAgent (stamps intake_agent_id).
    """
    if received_clock is not None:
        set_clock(received_clock)
    payload = create_dispute_payload(
        transaction_id, claim_amount_cents,
        error_type=error_type, claimed_report_delay_days=claimed_delay,
    )
    if by_intake_agent is not None:
        from .test_users import make_intake_agent_headers
        headers = make_intake_agent_headers(by_intake_agent)
    else:
        headers = make_cardholder_headers(account_id)
    return get_success_data(api_client.create_dispute(payload, headers))


def classify_case(dispute_id, is_fraud=False, verified_delay=5,
                  investigator_id="ops-inv-1"):
    """RECEIVED -> CLASSIFIED. Returns the classified case."""
    return get_success_data(api_client.classify_dispute(
        dispute_id,
        classify_payload(is_fraud_claim=is_fraud,
                         verified_report_delay_days=verified_delay),
        make_investigator_headers(investigator_id),
    ))


def grant_credit(dispute_id):
    """Grant the provisional credit (case must be CLASSIFIED)."""
    return get_success_data(api_client.grant_provisional_credit(dispute_id, INTAKE))


def get_account(account_id):
    return get_success_data(api_client.get_card_account(account_id, FINANCE))


def get_case(dispute_id):
    return get_success_data(api_client.get_dispute(dispute_id, FINANCE))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — account + transaction + dispute (+ classify)
# ---------------------------------------------------------------------------

def setup_account_with_dispute(balance=100000, amount=10000,
                               txn_type="ECOMMERCE", network="VISA",
                               error_type="INCORRECT_AMOUNT", claim=None,
                               claimed_delay=5, classify=False,
                               is_fraud=False, verified_delay=5,
                               posted_at=CLOCK["TXN_POSTED"],
                               account_open=CLOCK["ACCOUNT_OPEN"],
                               received_clock=CLOCK["DISPUTE_RECEIVED"]):
    """Old account + POSTED txn + RECEIVED dispute (optionally CLASSIFIED).

    Returns (account, txn, case).
    """
    account = create_account(balance=balance, clock=account_open)
    txn = create_transaction(account["id"], amount=amount, txn_type=txn_type,
                             network=network, posted_at=posted_at)
    case = file_dispute(txn["id"], account["id"], claim or amount,
                        error_type=error_type, claimed_delay=claimed_delay,
                        received_clock=received_clock)
    if classify:
        case = classify_case(case["id"], is_fraud=is_fraud,
                             verified_delay=verified_delay)
    return account, txn, case


def setup_classified_case_with_credit(balance=100000, amount=10000,
                                      txn_type="ECOMMERCE", network="VISA",
                                      error_type="INCORRECT_AMOUNT",
                                      claim=None, claimed_delay=5,
                                      is_fraud=False, verified_delay=5):
    """Account + txn + CLASSIFIED case + GRANTED provisional credit.

    Returns (account, txn, case, credit).
    """
    account, txn, case = setup_account_with_dispute(
        balance=balance, amount=amount, txn_type=txn_type, network=network,
        error_type=error_type, claim=claim, claimed_delay=claimed_delay,
        classify=True, is_fraud=is_fraud, verified_delay=verified_delay,
    )
    credit = grant_credit(case["id"])
    return account, txn, case, credit


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — chargeback filing, representment,
# second presentment, escalation-ready state
# ---------------------------------------------------------------------------

def file_chargeback(dispute_id, reason_code="V13_1", amount_cents=None,
                    filed_clock=CLOCK["CHARGEBACK_FILED"]):
    """File a chargeback against a CLASSIFIED case. Returns the Chargeback."""
    if filed_clock is not None:
        set_clock(filed_clock)
    overrides = {}
    if amount_cents is not None:
        overrides["amount_cents"] = amount_cents
    return get_success_data(api_client.create_chargeback(
        create_chargeback_payload(dispute_id, reason_code, **overrides),
        ANALYST,
    ))


def setup_filed_chargeback(balance=100000, amount=10000,
                           txn_type="ECOMMERCE", network="VISA",
                           error_type="SERVICE_NOT_RECEIVED", claim=None,
                           claimed_delay=10, is_fraud=False, verified_delay=10,
                           reason_code="V13_1", grant_credit_first=False):
    """CLASSIFIED case (optionally with credit) + FILED chargeback.

    Returns (account, txn, case, chargeback).
    """
    if grant_credit_first:
        account, txn, case, _credit = setup_classified_case_with_credit(
            balance=balance, amount=amount, txn_type=txn_type, network=network,
            error_type=error_type, claim=claim, claimed_delay=claimed_delay,
            is_fraud=is_fraud, verified_delay=verified_delay,
        )
    else:
        account, txn, case = setup_account_with_dispute(
            balance=balance, amount=amount, txn_type=txn_type, network=network,
            error_type=error_type, claim=claim, claimed_delay=claimed_delay,
            classify=True, is_fraud=is_fraud, verified_delay=verified_delay,
        )
    chargeback = file_chargeback(case["id"], reason_code=reason_code)
    return account, txn, case, chargeback


def register_representment(chargeback_id, merchant_ref="MR-1", doc_ref="doc-1"):
    """Register a representment: chargeback FILED -> REPRESENTED."""
    return get_success_data(api_client.create_representment(
        chargeback_id,
        create_representment_payload(
            merchant_ref=merchant_ref,
            evidence_documents=[{"doc_type": "RECEIPT", "reference": doc_ref}],
        ),
        ANALYST,
    ))


def review_representment(chargeback_id, decision="REJECT"):
    return get_success_data(api_client.review_representment(
        chargeback_id, review_representment_payload(decision=decision), ANALYST,
    ))


def setup_second_presented(balance=100000, amount=10000,
                           txn_type="ECOMMERCE", network="VISA",
                           error_type="SERVICE_NOT_RECEIVED", claim=None,
                           claimed_delay=10, is_fraud=False, verified_delay=10,
                           reason_code="V13_1", grant_credit_first=False):
    """FILED -> REPRESENTED -> (REJECT) SECOND_PRESENTED.

    Returns (account, txn, case, chargeback).
    """
    account, txn, case, chargeback = setup_filed_chargeback(
        balance=balance, amount=amount, txn_type=txn_type, network=network,
        error_type=error_type, claim=claim, claimed_delay=claimed_delay,
        is_fraud=is_fraud, verified_delay=verified_delay,
        reason_code=reason_code, grant_credit_first=grant_credit_first,
    )
    register_representment(chargeback["id"])
    review_representment(chargeback["id"], decision="REJECT")
    return account, txn, case, chargeback


# ---------------------------------------------------------------------------
# Tier 4: reversal-flow state — case in REVERSAL_PENDING with notice cooling
# ---------------------------------------------------------------------------

def setup_reversal_pending(balance=100000, amount=10000, txn_type="ECOMMERCE",
                           network="VISA", error_type="INCORRECT_AMOUNT",
                           claim=None, claimed_delay=5, is_fraud=False,
                           verified_delay=5,
                           resolve_clock=CLOCK["RESOLVE_NO_ERROR"],
                           after_clock=CLOCK["COOLING_3BD"]):
    """Classified case + GRANTED credit + NO_ERROR resolution -> REVERSAL_PENDING.

    Leaves the clock at after_clock (default: 3 business days after the
    REVERSAL_NOTICE, so cooling is satisfied). Returns
    (account, txn, case, credit).
    """
    account, txn, case, credit = setup_classified_case_with_credit(
        balance=balance, amount=amount, txn_type=txn_type, network=network,
        error_type=error_type, claim=claim, claimed_delay=claimed_delay,
        is_fraud=is_fraud, verified_delay=verified_delay,
    )
    if resolve_clock is not None:
        set_clock(resolve_clock)
    get_success_data(api_client.resolve_dispute(
        case["id"], resolve_payload(outcome="NO_ERROR"), INVESTIGATOR,
    ))
    if after_clock is not None:
        set_clock(after_clock)
    return account, txn, get_case(case["id"]), credit


# ---------------------------------------------------------------------------
# Tier 5: terminal states — merchant-favor resolution (with/without credit)
# ---------------------------------------------------------------------------

def setup_resolved_merchant_favor_no_credit(balance=50000, amount=5000,
                                            error_type="INCORRECT_AMOUNT",
                                            claimed_delay=5,
                                            verified_delay=5):
    """Classified case resolved NO_ERROR with no credit ever granted.

    Case lands in RESOLVED_MERCHANT_FAVOR; transaction SETTLED.
    Returns (account, txn, case).
    """
    account, txn, case = setup_account_with_dispute(
        balance=balance, amount=amount, error_type=error_type,
        claim=amount, claimed_delay=claimed_delay, classify=True,
        is_fraud=False, verified_delay=verified_delay,
    )
    get_success_data(api_client.resolve_dispute(
        case["id"], resolve_payload(outcome="NO_ERROR"), INVESTIGATOR,
    ))
    return account, txn, get_case(case["id"])


def setup_resolved_merchant_favor_via_reversal(balance=100000, amount=20000,
                                               txn_type="ECOMMERCE",
                                               error_type="INCORRECT_AMOUNT",
                                               claimed_delay=5,
                                               is_fraud=False, verified_delay=5):
    """Credit granted, NO_ERROR, 3-business-day cooling, credit reversed.

    Case lands in RESOLVED_MERCHANT_FAVOR via the reversal cascade.
    Returns (account, txn, case, credit).
    """
    account, txn, case, credit = setup_reversal_pending(
        balance=balance, amount=amount, txn_type=txn_type,
        error_type=error_type, claim=amount, claimed_delay=claimed_delay,
        is_fraud=is_fraud, verified_delay=verified_delay,
    )
    get_success_data(api_client.reverse_provisional_credit(credit["id"], FINANCE))
    return account, txn, get_case(case["id"]), credit


def setup_representment_accepted_case(balance=50000, amount=12000,
                                      reason_code="V13_1"):
    """Chargeback representment ACCEPTED with no open credit.

    Chargeback CLOSED_LOST; case RESOLVED_MERCHANT_FAVOR with the auto
    LOSS_RECOGNIZED entry for the filing fee. Returns
    (account, txn, case, chargeback).
    """
    account, txn, case, chargeback = setup_filed_chargeback(
        balance=balance, amount=amount, claim=amount, reason_code=reason_code,
    )
    register_representment(chargeback["id"])
    review_representment(chargeback["id"], decision="ACCEPT")
    return account, txn, get_case(case["id"]), chargeback
