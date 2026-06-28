"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the system in a specific state reached via 5-15 API
calls. These helpers build those preconditions from scratch (the server starts
from an empty database before every test) using only PRD-declared endpoints.

Setup calls use get_success_data() (lenient validator) so a broken precondition
surfaces as a clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: AccountHolder is entity_backed:Account, so ownership-gated
calls (cancel, payments) use make_account_holder_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_fee_schedule_payload, create_account_payload, create_transaction_payload,
    create_document_payload, create_runner_trip_payload, create_lien_packet_payload,
    create_payment_payload,
)
from .constants import CLOCK_DEFAULT, VALID_VIN
from .test_users import (
    TEST_USERS, make_account_holder_headers, make_intake_clerk_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]
LIEN_OFFICER = TEST_USERS["lien_officer_headers"]


# Required checklist by transaction_type (PRD §3.2 polymorphic checklist).
REQUIRED_CHECKLIST = {
    "TITLE": ["TITLE_CERT", "BILL_OF_SALE", "ODOMETER", "ID_PROOF"],
    "REGISTRATION": ["ID_PROOF", "INSURANCE"],
    "TRANSFER": ["TITLE_CERT", "BILL_OF_SALE", "ID_PROOF"],
    "LIEN": ["LIEN_INSTRUMENT", "ID_PROOF"],
}


# ─── Tier 0: Configuration backbone ───────────────────────────────────

def set_clock(iso: str = CLOCK_DEFAULT):
    """Set the logical clock to a known instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def publish_fee_schedule(**overrides):
    """Publish a fee schedule (CA defaults). Returns the schedule."""
    return get_success_data(
        api_client.create_fee_schedule(create_fee_schedule_payload(**overrides), ADMIN))


def create_account(account_type="RETAIL", state_code="CA", **overrides):
    """Create an account. Returns the account."""
    payload = create_account_payload(account_type=account_type, state_code=state_code, **overrides)
    return get_success_data(api_client.create_account(payload, ADMIN))


def setup_schedule_and_account(account_type="RETAIL", state_code="CA",
                               schedule_overrides=None, account_overrides=None,
                               set_clock_first=True):
    """Publish a schedule for `state_code` and open an account on it.
    Returns (schedule, account)."""
    if set_clock_first:
        set_clock()
    sched_overrides = {"state_code": state_code, **(schedule_overrides or {})}
    schedule = publish_fee_schedule(**sched_overrides)
    account = create_account(account_type=account_type, state_code=state_code,
                             **(account_overrides or {}))
    return schedule, account


def inject_ytd_count(account_id: str, ytd_completed_count: int):
    """Force an account's ytd_completed_count to a target value. Returns the account."""
    return get_success_data(api_client.inject_account_counters(
        {"account_id": account_id, "ytd_completed_count": ytd_completed_count}, ADMIN))


def inject_rejection_round(transaction_id: str, rejection_round: int):
    """Force a transaction's rejection_round to a target value. Returns the transaction."""
    return get_success_data(api_client.inject_rejection_round(
        {"transaction_id": transaction_id, "rejection_round": rejection_round}, ADMIN))


# ─── Tier 1: Transaction creation + document verification ─────────────

def create_transaction(account_id, transaction_type="REGISTRATION", vin=VALID_VIN, **overrides):
    """Open a DRAFT transaction. Returns the transaction."""
    payload = create_transaction_payload(account_id, transaction_type, vin, **overrides)
    return get_success_data(api_client.create_transaction(payload, CLERK))


def upload_and_verify_required_docs(transaction_id, transaction_type, file_prefix="f"):
    """Upload + verify every required checklist doc for the transaction_type.
    Returns the list of created document dicts."""
    docs = []
    for i, code in enumerate(REQUIRED_CHECKLIST[transaction_type]):
        doc = get_success_data(api_client.create_document(
            create_document_payload(transaction_id, code, file_ref=f"{file_prefix}{i}"), CLERK))
        api_client.verify_document(doc["id"], {"decision": "VERIFIED"}, CLERK)
        docs.append(doc)
    return docs


def verify_documents(transaction_id):
    """Run the checklist evaluation. Returns the transaction."""
    return get_success_data(api_client.verify_documents(transaction_id, CLERK))


def quote_transaction(transaction_id, expected_version):
    """Compute an ESTIMATE quote. Returns the FeeQuote."""
    return get_success_data(api_client.quote_transaction(
        transaction_id, {"expected_transaction_version": expected_version}, ANALYST))


def create_transaction_verified_and_quoted(account_id, transaction_type="REGISTRATION",
                                           vin=VALID_VIN, txn_overrides=None):
    """Open a transaction, verify its required docs (-> document_status VERIFIED),
    and compute the first ESTIMATE quote (-> lifecycle QUOTED).
    Returns (transaction, quote). The returned transaction is re-fetched so its
    version reflects the post-quote state."""
    txn = create_transaction(account_id, transaction_type, vin, **(txn_overrides or {}))
    upload_and_verify_required_docs(txn["id"], transaction_type)
    after_verify = verify_documents(txn["id"])
    quote = quote_transaction(txn["id"], after_verify["version"])
    txn = get_success_data(api_client.get_transaction(txn["id"], ANALYST))
    return txn, quote


# ─── Tier 2: Submission + runner-trip queue ───────────────────────────

def submit_transaction(transaction_id, submitting_user_id=None):
    """Submit a QUOTED/REJECTED transaction. If submitting_user_id is given, stamp
    that IntakeClerk X-User-ID (for segregation-of-duties scenarios). Returns the
    created Submission."""
    headers = make_intake_clerk_headers(submitting_user_id) if submitting_user_id else CLERK
    return get_success_data(api_client.submit_transaction(transaction_id, headers))


def create_planned_trip(**overrides):
    """Create a PLANNED runner trip. Returns the trip."""
    return get_success_data(
        api_client.create_runner_trip(create_runner_trip_payload(**overrides), DISPATCHER))


def attach_leg(trip_id, submission_id, expected_trip_version):
    """Attach a QUEUED submission to a PLANNED trip. Returns the RunnerLeg."""
    return get_success_data(api_client.attach_leg(
        trip_id, {"submission_id": submission_id,
                  "expected_runnertrip_version": expected_trip_version}, DISPATCHER))


def setup_submitted_with_leg(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                             submitting_user_id=None, txn_overrides=None,
                             trip_overrides=None):
    """Drive a transaction to SUBMITTED with its submission attached to a PLANNED
    trip as one leg. Returns (transaction, submission, trip, leg)."""
    txn, _quote = create_transaction_verified_and_quoted(
        account_id, transaction_type, vin, txn_overrides=txn_overrides)
    submission = submit_transaction(txn["id"], submitting_user_id=submitting_user_id)
    trip = create_planned_trip(**(trip_overrides or {}))
    leg = attach_leg(trip["id"], submission["id"], trip["version"])
    txn = get_success_data(api_client.get_transaction(txn["id"], ANALYST))
    trip = get_success_data(api_client.get_runner_trip(trip["id"], DISPATCHER))
    return txn, submission, trip, leg


def setup_trip_dispatched(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                          submitting_user_id=None, txn_overrides=None, trip_overrides=None):
    """SUBMITTED transaction whose trip has been DISPATCHED (leg FILED), not yet
    RETURNED. Returns (transaction, submission, trip, leg)."""
    txn, submission, trip, leg = setup_submitted_with_leg(
        account_id, transaction_type, vin, submitting_user_id=submitting_user_id,
        txn_overrides=txn_overrides, trip_overrides=trip_overrides)
    api_client.dispatch_trip(trip["id"], DISPATCHER)
    trip = get_success_data(api_client.get_runner_trip(trip["id"], DISPATCHER))
    return txn, submission, trip, leg


def setup_trip_returned(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                        submitting_user_id=None, txn_overrides=None, trip_overrides=None):
    """SUBMITTED transaction whose trip is RETURNED (decisions can now be recorded).
    Returns (transaction, submission, trip, leg)."""
    txn, submission, trip, leg = setup_trip_dispatched(
        account_id, transaction_type, vin, submitting_user_id=submitting_user_id,
        txn_overrides=txn_overrides, trip_overrides=trip_overrides)
    api_client.return_trip(trip["id"], DISPATCHER)
    trip = get_success_data(api_client.get_runner_trip(trip["id"], DISPATCHER))
    return txn, submission, trip, leg


# ─── Tier 3: DMV decisions -> APPROVED / REJECTED / COMPLETED ─────────

def record_decision(submission_id, outcome, rejection_reason=None):
    """Record a DMV decision on an ASSIGNED submission whose trip is RETURNED.
    Returns the Submission."""
    payload = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api_client.submission_decision(submission_id, payload, DISPATCHER))


def setup_approved_transaction(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                               submitting_user_id=None, txn_overrides=None, trip_overrides=None):
    """Drive a transaction all the way to APPROVED (submission ACCEPTED).
    Returns (transaction, submission, trip, leg)."""
    txn, submission, trip, leg = setup_trip_returned(
        account_id, transaction_type, vin, submitting_user_id=submitting_user_id,
        txn_overrides=txn_overrides, trip_overrides=trip_overrides)
    record_decision(submission["id"], "ACCEPTED")
    txn = get_success_data(api_client.get_transaction(txn["id"], ANALYST))
    submission = get_success_data(api_client.get_submission(submission["id"], DISPATCHER))
    return txn, submission, trip, leg


def complete_transaction(transaction_id):
    """Complete an APPROVED transaction (settles the FINAL quote). Returns the transaction."""
    return get_success_data(api_client.complete_transaction(transaction_id, ANALYST))


def setup_completed_transaction(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                                txn_overrides=None):
    """Drive a transaction to COMPLETED. Returns (transaction, submission, settled_quote)."""
    txn, submission, _trip, _leg = setup_approved_transaction(
        account_id, transaction_type, vin, txn_overrides=txn_overrides)
    txn = complete_transaction(txn["id"])
    # The SETTLED FINAL quote is the active quote after completion.
    settled_quote = get_success_data(api_client.get_fee_quote(txn["active_quote_id"], ANALYST))
    return txn, submission, settled_quote


def record_charge_payment(account_id, transaction_id, amount_cents):
    """Record a CHARGE payment from the owning AccountHolder. Returns the Payment."""
    headers = make_account_holder_headers(account_id)
    return get_success_data(api_client.create_payment(
        account_id, create_payment_payload(transaction_id, amount_cents, "CHARGE"), headers))


def setup_completed_and_charged(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                                txn_overrides=None):
    """Drive a transaction to COMPLETED and record a CHARGE payment for the SETTLED
    total (RETAIL prepaid: balance nets to 0). Returns (transaction, settled_quote, payment)."""
    txn, _submission, settled_quote = setup_completed_transaction(
        account_id, transaction_type, vin, txn_overrides=txn_overrides)
    payment = record_charge_payment(account_id, txn["id"], settled_quote["total_cents"])
    return txn, settled_quote, payment


# ─── Tier 4: Lien lifecycle ───────────────────────────────────────────

def create_lien_packet(transaction_id, **overrides):
    """Create a DRAFT lien packet. Returns the packet."""
    return get_success_data(api_client.create_lien_packet(
        create_lien_packet_payload(transaction_id, **overrides), LIEN_OFFICER))


def setup_lien_transaction_approved(account_id, submitting_user_id="dual-actor",
                                    lender_name="First Bank", lien_amount_cents=500000):
    """A LIEN transaction with a DRAFT lien packet, driven to APPROVED (submission
    ACCEPTED), submitted by `submitting_user_id`. Returns (transaction, packet, submission)."""
    txn = create_transaction(account_id, "LIEN", VALID_VIN, declared_price_cents=0)
    packet = create_lien_packet(txn["id"], lender_name=lender_name,
                                lien_amount_cents=lien_amount_cents)
    upload_and_verify_required_docs(txn["id"], "LIEN")
    after_verify = verify_documents(txn["id"])
    quote_transaction(txn["id"], after_verify["version"])
    submission = submit_transaction(txn["id"], submitting_user_id=submitting_user_id)
    trip = create_planned_trip()
    attach_leg(trip["id"], submission["id"], trip["version"])
    api_client.dispatch_trip(trip["id"], DISPATCHER)
    api_client.return_trip(trip["id"], DISPATCHER)
    record_decision(submission["id"], "ACCEPTED")
    txn = get_success_data(api_client.get_transaction(txn["id"], ANALYST))
    packet = get_success_data(api_client.get_lien_packet(packet["id"], LIEN_OFFICER))
    submission = get_success_data(api_client.get_submission(submission["id"], DISPATCHER))
    return txn, packet, submission


def setup_lien_transaction_submitted(account_id, submitting_user_id="clerk-1"):
    """A LIEN transaction with a DRAFT lien packet driven to SUBMITTED (leg attached,
    trip DISPATCHED, NOT decided — transaction still SUBMITTED, not APPROVED).
    Returns (transaction, packet, submission, trip)."""
    txn = create_transaction(account_id, "LIEN", VALID_VIN, declared_price_cents=0)
    packet = create_lien_packet(txn["id"], lender_name="First Bank", lien_amount_cents=500000)
    upload_and_verify_required_docs(txn["id"], "LIEN")
    after_verify = verify_documents(txn["id"])
    quote_transaction(txn["id"], after_verify["version"])
    submission = submit_transaction(txn["id"], submitting_user_id=submitting_user_id)
    trip = create_planned_trip()
    attach_leg(trip["id"], submission["id"], trip["version"])
    api_client.dispatch_trip(trip["id"], DISPATCHER)
    txn = get_success_data(api_client.get_transaction(txn["id"], ANALYST))
    packet = get_success_data(api_client.get_lien_packet(packet["id"], LIEN_OFFICER))
    return txn, packet, submission, trip


# ─── Tier 5: Rework / rejection cycle ─────────────────────────────────

def setup_rejected_transaction(account_id, transaction_type="REGISTRATION", vin=VALID_VIN,
                               rejection_reason="Illegible insurance card"):
    """Drive a transaction to REJECTED via a real DMV_REJECTED decision.
    After this the transaction has rejection_round 1 and document_status INCOMPLETE.
    Returns (transaction, submission, docs) where docs are the verified docs."""
    txn = create_transaction(account_id, transaction_type, vin)
    docs = upload_and_verify_required_docs(txn["id"], transaction_type)
    after_verify = verify_documents(txn["id"])
    quote_transaction(txn["id"], after_verify["version"])
    submission = submit_transaction(txn["id"])
    trip = create_planned_trip()
    attach_leg(trip["id"], submission["id"], trip["version"])
    api_client.dispatch_trip(trip["id"], DISPATCHER)
    api_client.return_trip(trip["id"], DISPATCHER)
    record_decision(submission["id"], "DMV_REJECTED", rejection_reason=rejection_reason)
    txn = get_success_data(api_client.get_transaction(txn["id"], ANALYST))
    return txn, submission, docs


def re_verify_and_requote(transaction_id, docs):
    """For a REJECTED transaction: re-verify all docs back to VERIFIED, run
    verify-documents (-> VERIFIED), and re-quote. Returns the re-fetched transaction."""
    for doc in docs:
        api_client.verify_document(doc["id"], {"decision": "VERIFIED"}, CLERK)
    after_verify = verify_documents(transaction_id)
    quote_transaction(transaction_id, after_verify["version"])
    return get_success_data(api_client.get_transaction(transaction_id, ANALYST))
