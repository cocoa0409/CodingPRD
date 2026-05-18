"""Composite setup helpers — multi-step preambles tests can reuse.

The dispute pipeline is long: consumer create -> furnisher register ->
credit_report create -> tradeline_item seed -> dispute submit ->
start_investigation -> furnisher_response -> issue_result_notice.
Tests that target a specific state in the middle of this sequence
should reuse the helpers below.

IDENTITY THREADING (PRD §2.1) — applied throughout this module:

- Consumer and Furnisher are ENTITY-BACKED. After this module creates
  one via the corresponding POST endpoint, ANY subsequent call whose
  authorization depends on owning the resource (i.e., the Consumer
  acting on their own disputes / credit_reports / regulatory_complaints
  / freezes / locks, or the Furnisher acting on their own tradelines /
  hard_inquiries) MUST thread the entity's real id into the header via
  make_consumer_headers(consumer["id"]) or
  make_furnisher_headers(furnisher["id"]). Falling back to
  CONSUMER_FALLBACK_ID / FURNISHER_FALLBACK_ID for ownership-gated
  calls would always fail (ERR_FORBIDDEN_FOR_ROLE), cascading "Setup
  failed" into every dependent test.

- BureauOperator, CFPBOperator, and PlatformAdmin are OPAQUE. Calls
  by these roles use the shared TEST_USERS constants.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    additional_info_payload,
    clock_advance_payload,
    create_consumer_payload,
    create_credit_freeze_payload,
    create_credit_lock_payload,
    create_credit_report_payload,
    create_dispute_payload,
    create_furnisher_payload,
    create_hard_inquiry_payload,
    create_regulatory_complaint_payload,
    create_tradeline_item_payload,
    furnisher_response_payload,
    lift_credit_freeze_payload,
    random_account_ref,
    supporting_doc,
)
from .test_users import (
    TEST_USERS,
    make_consumer_headers,
    make_furnisher_headers,
)


# ===========================================================================
# Clock control — PRD §2.4, §2.11
# ===========================================================================
def advance_clock(
    days: int,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.4: 'advances the logical clock by
    that many days; advancing the clock does not by itself fire any
    deadlines'."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(days=days), headers,
    )
    return get_success_data(resp)


def run_sweep(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_sweep/run. PRD §2.11: 'walks every FurnisherInquiry
    whose response is still PENDING and whose
    reverification_deadline_day is strictly less than the current
    clock day'."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.sweep_run(headers)
    return get_success_data(resp)


def read_clock_day(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> int:
    """GET /_clock. Returns the integer clock day."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_clock(headers)
    data = get_success_data(resp)
    return int(data["day"])


# ===========================================================================
# Consumer + Furnisher + CreditReport + TradelineItem seeding
# ===========================================================================
def create_consumer(
    *,
    full_name: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    email: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers (PlatformAdmin per PRD §4)."""
    admin_headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.create_consumer(
        create_consumer_payload(
            full_name=full_name, ssn_last4=ssn_last4, email=email,
        ),
        admin_headers,
    )
    return get_success_data(resp)


def get_consumer(
    consumer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET /consumers/{id}. For ownership-gated reads, pass headers
    minted via make_consumer_headers(consumer_id). PlatformAdmin
    fallback is used when headers is None."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_consumer(consumer_id, headers)
    return get_success_data(resp)


def create_furnisher(
    *,
    legal_name: Optional[str] = None,
    ecoa_code: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /furnishers (PlatformAdmin per PRD §4)."""
    admin_headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.create_furnisher(
        create_furnisher_payload(legal_name=legal_name, ecoa_code=ecoa_code),
        admin_headers,
    )
    return get_success_data(resp)


def create_credit_report(
    consumer_id: str,
    *,
    bureau: str = "EQUIFAX",
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{id}/credit_reports (PlatformAdmin per PRD §4)."""
    admin_headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.create_credit_report(
        consumer_id,
        create_credit_report_payload(bureau=bureau),
        admin_headers,
    )
    return get_success_data(resp)


def get_credit_report(
    consumer_id: str,
    credit_report_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET /consumers/{cid}/credit_reports/{rid}. Defaults to
    PlatformAdmin (opaque) headers; pass consumer headers via
    make_consumer_headers for ownership-gated tests."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_credit_report(consumer_id, credit_report_id, headers)
    return get_success_data(resp)


def create_tradeline_item(
    credit_report_id: str,
    *,
    furnisher_id: str,
    furnisher_headers: Dict[str, str],
    account_ref: Optional[str] = None,
    original_dofd_day: int = 100,
    balance_cents: int = 500_000,
    payment_status: str = "LATE_90",
) -> Dict[str, Any]:
    """POST /credit_reports/{rid}/tradeline_items.

    PRD §4 authorizes PlatformAdmin OR Furnisher. PRD §2.1 makes
    Furnisher entity-backed: when the call is made by Furnisher,
    X-User-ID must equal the furnisher_id supplied in the body. The
    caller MUST therefore pass furnisher_headers minted via
    make_furnisher_headers(furnisher_id) for Furnisher-acting calls
    — or pass TEST_USERS['platform_admin_headers'] for admin-seeded
    setup. Either is faithful to PRD §4."""
    resp = api_client.create_tradeline_item(
        credit_report_id,
        create_tradeline_item_payload(
            furnisher_id=furnisher_id,
            account_ref=account_ref,
            original_dofd_day=original_dofd_day,
            balance_cents=balance_cents,
            payment_status=payment_status,
        ),
        furnisher_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Composite seed: consumer + furnisher + report + tradeline
# ===========================================================================
def setup_consumer_furnisher_report_tradeline(
    *,
    bureau: str = "EQUIFAX",
    original_dofd_day: int = 100,
    balance_cents: int = 500_000,
    payment_status: str = "LATE_90",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Standard preamble for every dispute-related test.

    Returns (consumer, furnisher, credit_report, tradeline_item).

    Steps (each via the authorized role per PRD §4):
      1. PlatformAdmin → POST /consumers
      2. PlatformAdmin → POST /furnishers
      3. PlatformAdmin → POST /consumers/{c}/credit_reports
      4. Furnisher (authenticated as the real furnisher.id via
         make_furnisher_headers) → POST
         /credit_reports/{r}/tradeline_items
    """
    consumer = create_consumer()
    furnisher = create_furnisher()
    report = create_credit_report(consumer["id"], bureau=bureau)
    tradeline = create_tradeline_item(
        report["id"],
        furnisher_id=furnisher["id"],
        furnisher_headers=make_furnisher_headers(furnisher["id"]),
        original_dofd_day=original_dofd_day,
        balance_cents=balance_cents,
        payment_status=payment_status,
    )
    return consumer, furnisher, report, tradeline


def add_extra_tradeline(
    *,
    consumer: Dict[str, Any],
    furnisher: Dict[str, Any],
    report: Dict[str, Any],
    original_dofd_day: int = 100,
    balance_cents: int = 500_000,
    payment_status: str = "LATE_90",
    account_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Add another tradeline to an existing report. Uses Furnisher
    (entity-backed) identity threading per PRD §2.1."""
    return create_tradeline_item(
        report["id"],
        furnisher_id=furnisher["id"],
        furnisher_headers=make_furnisher_headers(furnisher["id"]),
        account_ref=account_ref or random_account_ref(),
        original_dofd_day=original_dofd_day,
        balance_cents=balance_cents,
        payment_status=payment_status,
    )


# ===========================================================================
# Dispute lifecycle helpers — PRD §3.2 – §3.4
# ===========================================================================
def submit_dispute(
    *,
    consumer: Dict[str, Any],
    report: Dict[str, Any],
    tradeline: Dict[str, Any],
    channel: str = "ONLINE",
    requested_action: str = "CORRECT_BALANCE",
    requested_payload: Optional[Dict[str, Any]] = None,
    supporting_documents: Optional[List[Dict[str, str]]] = None,
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/disputes.

    Consumer is entity-backed per PRD §2.1: identity is threaded
    through make_consumer_headers(consumer['id']) by default — the
    only way the call's X-User-ID matches Consumer.id ownership."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    payload = create_dispute_payload(
        credit_report_id=report["id"],
        tradeline_item_id=tradeline["id"],
        channel=channel,
        supporting_documents=supporting_documents,
        requested_action=requested_action,
        requested_payload=requested_payload,
    )
    resp = api_client.create_dispute(consumer["id"], payload, consumer_headers)
    return get_success_data(resp)


def start_investigation(
    *,
    consumer_id: str,
    dispute_id: str,
    operator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/disputes/{did}/start_investigation
    (BureauOperator per PRD §4)."""
    operator_headers = operator_headers or TEST_USERS["bureau_operator_headers"]
    resp = api_client.start_investigation(
        consumer_id, dispute_id, operator_headers,
    )
    return get_success_data(resp)


def submit_additional_info(
    *,
    consumer: Dict[str, Any],
    dispute_id: str,
    supporting_documents: Optional[List[Dict[str, str]]] = None,
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/disputes/{did}/additional_info
    (Consumer per PRD §4)."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.submit_additional_info(
        consumer["id"], dispute_id,
        additional_info_payload(supporting_documents=supporting_documents),
        consumer_headers,
    )
    return get_success_data(resp)


def record_furnisher_response(
    *,
    consumer_id: str,
    dispute_id: str,
    response: str,
    response_payload: Optional[Dict[str, Any]] = None,
    operator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/disputes/{did}/furnisher_response
    (BureauOperator per PRD §4)."""
    operator_headers = operator_headers or TEST_USERS["bureau_operator_headers"]
    resp = api_client.record_furnisher_response(
        consumer_id, dispute_id,
        furnisher_response_payload(
            response=response, response_payload=response_payload,
        ),
        operator_headers,
    )
    return get_success_data(resp)


def issue_result_notice(
    *,
    consumer_id: str,
    dispute_id: str,
    operator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/disputes/{did}/issue_result_notice
    (BureauOperator per PRD §4)."""
    operator_headers = operator_headers or TEST_USERS["bureau_operator_headers"]
    resp = api_client.issue_result_notice(
        consumer_id, dispute_id, operator_headers,
    )
    return get_success_data(resp)


def dismiss_frivolous(
    *,
    consumer_id: str,
    dispute_id: str,
    operator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/disputes/{did}/dismiss_frivolous
    (BureauOperator per PRD §4)."""
    operator_headers = operator_headers or TEST_USERS["bureau_operator_headers"]
    resp = api_client.dismiss_frivolous(
        consumer_id, dispute_id, operator_headers,
    )
    return get_success_data(resp)


def get_dispute(
    *,
    consumer_id: str,
    dispute_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["bureau_operator_headers"]
    resp = api_client.get_dispute(consumer_id, dispute_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Full-pipeline shortcuts to terminal states.
# ===========================================================================
def _close_then_get(consumer: Dict[str, Any], dispute_id: str) -> Dict[str, Any]:
    """issue_result_notice's PRD §4 declared output is ResultNotice;
    we re-GET the dispute so callers always receive the post-transition
    Dispute row."""
    issue_result_notice(consumer_id=consumer["id"], dispute_id=dispute_id)
    return get_dispute(consumer_id=consumer["id"], dispute_id=dispute_id)


def close_dispute_verified(
    *,
    consumer: Dict[str, Any],
    report: Dict[str, Any],
    tradeline: Dict[str, Any],
    requested_action: str = "CORRECT_BALANCE",
    requested_payload: Optional[Dict[str, Any]] = None,
    channel: str = "ONLINE",
) -> Dict[str, Any]:
    """submit -> start_investigation -> furnisher_response VERIFIED ->
    issue_result_notice → returns the CLOSED_VERIFIED dispute."""
    dispute = submit_dispute(
        consumer=consumer, report=report, tradeline=tradeline,
        channel=channel, requested_action=requested_action,
        requested_payload=requested_payload,
    )
    start_investigation(consumer_id=consumer["id"], dispute_id=dispute["id"])
    record_furnisher_response(
        consumer_id=consumer["id"], dispute_id=dispute["id"],
        response="VERIFIED", response_payload={},
    )
    return _close_then_get(consumer, dispute["id"])


def close_dispute_updated(
    *,
    consumer: Dict[str, Any],
    report: Dict[str, Any],
    tradeline: Dict[str, Any],
    requested_action: str = "CORRECT_BALANCE",
    requested_payload: Optional[Dict[str, Any]] = None,
    furnisher_response_data: Optional[Dict[str, Any]] = None,
    channel: str = "ONLINE",
) -> Dict[str, Any]:
    """submit -> start_investigation -> furnisher_response UPDATED ->
    issue_result_notice → returns the CLOSED_UPDATED dispute."""
    if requested_payload is None and requested_action == "CORRECT_BALANCE":
        requested_payload = {"new_balance_cents": 100}
    dispute = submit_dispute(
        consumer=consumer, report=report, tradeline=tradeline,
        channel=channel, requested_action=requested_action,
        requested_payload=requested_payload,
    )
    start_investigation(consumer_id=consumer["id"], dispute_id=dispute["id"])
    record_furnisher_response(
        consumer_id=consumer["id"], dispute_id=dispute["id"],
        response="UPDATED",
        response_payload=furnisher_response_data or requested_payload,
    )
    return _close_then_get(consumer, dispute["id"])


def close_dispute_deleted(
    *,
    consumer: Dict[str, Any],
    report: Dict[str, Any],
    tradeline: Dict[str, Any],
    requested_action: str = "DELETE_ITEM",
    channel: str = "ONLINE",
) -> Dict[str, Any]:
    """submit -> start_investigation -> furnisher_response DELETED ->
    issue_result_notice → returns the CLOSED_DELETED dispute."""
    dispute = submit_dispute(
        consumer=consumer, report=report, tradeline=tradeline,
        channel=channel, requested_action=requested_action,
        requested_payload={} if requested_action == "DELETE_ITEM" else None,
    )
    start_investigation(consumer_id=consumer["id"], dispute_id=dispute["id"])
    record_furnisher_response(
        consumer_id=consumer["id"], dispute_id=dispute["id"],
        response="DELETED", response_payload={},
    )
    return _close_then_get(consumer, dispute["id"])


def setup_dispute_in_state(
    *,
    state: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk the dispute state machine to `state` and return
    (consumer, furnisher, report, tradeline, dispute).

    Supported targets (verbatim PRD §3.2 – §3.4 state names):
      - RECEIVED
      - UNDER_INVESTIGATION
      - RESULTS_PENDING       (uses furnisher_response = VERIFIED to leave INV)
      - CLOSED_VERIFIED
      - CLOSED_UPDATED
      - CLOSED_DELETED
      - CLOSED_DISMISSED      (uses dismiss_frivolous; requires 4+ submissions)
    """
    consumer, furnisher, report, tradeline = (
        setup_consumer_furnisher_report_tradeline()
    )
    if state == "RECEIVED":
        dispute = submit_dispute(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        return consumer, furnisher, report, tradeline, dispute

    if state == "UNDER_INVESTIGATION":
        dispute = submit_dispute(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        dispute = start_investigation(
            consumer_id=consumer["id"], dispute_id=dispute["id"],
        )
        return consumer, furnisher, report, tradeline, dispute

    if state == "RESULTS_PENDING":
        dispute = submit_dispute(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        start_investigation(consumer_id=consumer["id"], dispute_id=dispute["id"])
        record_furnisher_response(
            consumer_id=consumer["id"], dispute_id=dispute["id"],
            response="VERIFIED", response_payload={},
        )
        dispute = get_dispute(
            consumer_id=consumer["id"], dispute_id=dispute["id"],
        )
        return consumer, furnisher, report, tradeline, dispute

    if state == "CLOSED_VERIFIED":
        dispute = close_dispute_verified(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        return consumer, furnisher, report, tradeline, dispute

    if state == "CLOSED_UPDATED":
        dispute = close_dispute_updated(
            consumer=consumer, report=report, tradeline=tradeline,
            requested_payload={"new_balance_cents": 100},
        )
        return consumer, furnisher, report, tradeline, dispute

    if state == "CLOSED_DELETED":
        dispute = close_dispute_deleted(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        return consumer, furnisher, report, tradeline, dispute

    if state == "CLOSED_DISMISSED":
        # PRD §3.4 dismiss_frivolous precondition: 4th+ submission by same
        # consumer on same tradeline_item_id in trailing 365 days.
        # Submit + close three priors verified, then submit a 4th and
        # immediately dismiss_frivolous from RECEIVED.
        for _ in range(3):
            prior = submit_dispute(
                consumer=consumer, report=report, tradeline=tradeline,
            )
            start_investigation(
                consumer_id=consumer["id"], dispute_id=prior["id"],
            )
            record_furnisher_response(
                consumer_id=consumer["id"], dispute_id=prior["id"],
                response="VERIFIED", response_payload={},
            )
            _close_then_get(consumer, prior["id"])
        dispute = submit_dispute(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        dismiss_frivolous(consumer_id=consumer["id"], dispute_id=dispute["id"])
        dispute = get_dispute(
            consumer_id=consumer["id"], dispute_id=dispute["id"],
        )
        return consumer, furnisher, report, tradeline, dispute

    raise ValueError(f"Unsupported target state: {state!r}")


# ===========================================================================
# Frivolous-setup helper — submit N closed disputes on a single tradeline.
# ===========================================================================
def submit_n_closed_disputes_on_tradeline(
    *,
    consumer: Dict[str, Any],
    report: Dict[str, Any],
    tradeline: Dict[str, Any],
    n: int,
    close_as: str = "VERIFIED",
) -> List[Dict[str, Any]]:
    """Submit N disputes on the SAME tradeline, closing each via the
    selected furnisher response (default VERIFIED). Returns the list
    of closed dispute dicts.

    Useful for frivolous-threshold tests (PRD §3.2: 'more than three
    disputes against the same tradeline_item_id in the trailing 365
    logical days') and for cumulative dispute-risk-score targeting
    (PRD §3.6)."""
    closed: List[Dict[str, Any]] = []
    for _ in range(n):
        if close_as == "VERIFIED":
            closed.append(close_dispute_verified(
                consumer=consumer, report=report, tradeline=tradeline,
            ))
        elif close_as == "UPDATED":
            closed.append(close_dispute_updated(
                consumer=consumer, report=report, tradeline=tradeline,
                requested_payload={"new_balance_cents": 100},
            ))
        elif close_as == "DELETED":
            closed.append(close_dispute_deleted(
                consumer=consumer, report=report, tradeline=tradeline,
            ))
        else:
            raise ValueError(f"Unsupported close_as: {close_as!r}")
    return closed


def submit_n_closed_disputes_on_distinct_tradelines(
    *,
    consumer: Dict[str, Any],
    furnisher: Dict[str, Any],
    report: Dict[str, Any],
    n: int,
    close_as: str = "VERIFIED",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create N additional tradelines on the report and close one
    dispute on each. Returns (tradelines, closed_disputes).

    Distinct tradelines avoid hitting the frivolous threshold (>3 on
    the same tradeline within 365 days)."""
    tradelines: List[Dict[str, Any]] = []
    closed: List[Dict[str, Any]] = []
    for i in range(n):
        tl = add_extra_tradeline(
            consumer=consumer, furnisher=furnisher, report=report,
            account_ref=f"BULK-{i}-{random_account_ref()}",
        )
        tradelines.append(tl)
        if close_as == "VERIFIED":
            closed.append(close_dispute_verified(
                consumer=consumer, report=report, tradeline=tl,
            ))
        elif close_as == "UPDATED":
            closed.append(close_dispute_updated(
                consumer=consumer, report=report, tradeline=tl,
                requested_payload={"new_balance_cents": 100},
            ))
        else:
            raise ValueError(f"Unsupported close_as: {close_as!r}")
    return tradelines, closed


# ===========================================================================
# Tier 4: Threshold / boundary fixtures
# ===========================================================================
def setup_consumer_with_freeze(
    *,
    bureau: str = "EQUIFAX",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a consumer and place a CreditFreeze on `bureau`.
    Returns (consumer, freeze).

    PRD §3.11: 'If this is the consumer's first freeze across any
    bureau, the system mints a freeze_pin on the Consumer'. After this
    fixture the Consumer carries a non-null freeze_pin and the freeze
    on the named bureau is ACTIVE."""
    consumer = create_consumer()
    freeze = place_credit_freeze(consumer=consumer, bureau=bureau)
    return consumer, freeze


def place_credit_freeze(
    *,
    consumer: Dict[str, Any],
    bureau: str = "EQUIFAX",
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/credit_freezes (Consumer per PRD §4).
    Threads the real consumer.id via make_consumer_headers."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.create_credit_freeze(
        consumer["id"],
        create_credit_freeze_payload(bureau=bureau),
        consumer_headers,
    )
    return get_success_data(resp)


def lift_credit_freeze(
    *,
    consumer: Dict[str, Any],
    freeze_id: str,
    pin: str,
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/credit_freezes/{fid}/lift (Consumer)."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.lift_credit_freeze(
        consumer["id"], freeze_id,
        lift_credit_freeze_payload(pin=pin),
        consumer_headers,
    )
    return get_success_data(resp)


def place_credit_lock(
    *,
    consumer: Dict[str, Any],
    bureau: str = "EQUIFAX",
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/credit_locks (Consumer)."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.create_credit_lock(
        consumer["id"],
        create_credit_lock_payload(bureau=bureau),
        consumer_headers,
    )
    return get_success_data(resp)


def unlock_credit_lock(
    *,
    consumer: Dict[str, Any],
    lock_id: str,
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.unlock_credit_lock(
        consumer["id"], lock_id, consumer_headers,
    )
    return get_success_data(resp)


def relock_credit_lock(
    *,
    consumer: Dict[str, Any],
    lock_id: str,
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.relock_credit_lock(
        consumer["id"], lock_id, consumer_headers,
    )
    return get_success_data(resp)


def setup_furnisher_inquiry_at_deadline(
    *,
    start_clock_day: int = 0,
    bureau: str = "EQUIFAX",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a dispute that is UNDER_INVESTIGATION with forwarded_day
    = `start_clock_day`, then advance the clock to exactly the
    reverification_deadline_day (forwarded_day + 25 per PRD §3.3).
    Used for furnisher-deadline boundary tests.

    Returns (consumer, furnisher, report, tradeline, dispute).
    Caller should: advance to start_clock_day first (if non-zero),
    then call this; for boundary +1 tests, advance one more day after.
    """
    consumer, furnisher, report, tradeline = (
        setup_consumer_furnisher_report_tradeline(bureau=bureau)
    )
    dispute = submit_dispute(
        consumer=consumer, report=report, tradeline=tradeline,
    )
    dispute = start_investigation(
        consumer_id=consumer["id"], dispute_id=dispute["id"],
    )
    return consumer, furnisher, report, tradeline, dispute


# ===========================================================================
# RegulatoryComplaint helpers — PRD §3.10
# ===========================================================================
def file_regulatory_complaint(
    *,
    consumer: Dict[str, Any],
    dispute_id: str,
    narrative: str = "Bureau verification was insufficient.",
    parent_complaint_id: Optional[str] = None,
    consumer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /consumers/{cid}/regulatory_complaints (Consumer)."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    resp = api_client.create_regulatory_complaint(
        consumer["id"],
        create_regulatory_complaint_payload(
            dispute_id=dispute_id,
            narrative=narrative,
            parent_complaint_id=parent_complaint_id,
        ),
        consumer_headers,
    )
    return get_success_data(resp)


def accept_complaint(
    *,
    complaint_id: str,
    cfpb_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    cfpb_headers = cfpb_headers or TEST_USERS["cfpb_operator_headers"]
    resp = api_client.accept_complaint(complaint_id, cfpb_headers)
    return get_success_data(resp)


def reject_complaint(
    *,
    complaint_id: str,
    cfpb_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    cfpb_headers = cfpb_headers or TEST_USERS["cfpb_operator_headers"]
    resp = api_client.reject_complaint(complaint_id, cfpb_headers)
    return get_success_data(resp)


def resolve_complaint(
    *,
    complaint_id: str,
    cfpb_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    cfpb_headers = cfpb_headers or TEST_USERS["cfpb_operator_headers"]
    resp = api_client.resolve_complaint(complaint_id, cfpb_headers)
    return get_success_data(resp)


# ===========================================================================
# HardInquiry helper — PRD §3.12
# ===========================================================================
def request_hard_inquiry(
    *,
    credit_report_id: str,
    furnisher: Dict[str, Any],
    furnisher_headers: Optional[Dict[str, str]] = None,
):
    """POST /credit_reports/{rid}/hard_inquiries (Furnisher).

    Returns the raw requests.Response so callers can inspect both
    success (201, outcome=ACCEPTED) and failure (409,
    BLOCKED_BY_FREEZE / BLOCKED_BY_LOCK)."""
    furnisher_headers = furnisher_headers or make_furnisher_headers(
        furnisher["id"],
    )
    return api_client.create_hard_inquiry(
        credit_report_id,
        create_hard_inquiry_payload(requesting_furnisher_id=furnisher["id"]),
        furnisher_headers,
    )


# ===========================================================================
# Pull-free helper — PRD §3.9
# ===========================================================================
def pull_free_report(
    *,
    consumer: Dict[str, Any],
    credit_report_id: str,
    consumer_headers: Optional[Dict[str, str]] = None,
):
    """POST /consumers/{cid}/credit_reports/{rid}/pull_free.
    Returns the raw response so callers can test both success and
    ERR_NO_FREE_REPORTS_REMAINING."""
    consumer_headers = consumer_headers or make_consumer_headers(consumer["id"])
    return api_client.pull_free_credit_report(
        consumer["id"], credit_report_id, consumer_headers,
    )


__all__ = [
    # Clock + sweep
    "advance_clock",
    "run_sweep",
    "read_clock_day",
    # Seeding
    "create_consumer",
    "get_consumer",
    "create_furnisher",
    "create_credit_report",
    "get_credit_report",
    "create_tradeline_item",
    # Composite seed
    "setup_consumer_furnisher_report_tradeline",
    "add_extra_tradeline",
    # Dispute lifecycle
    "submit_dispute",
    "start_investigation",
    "submit_additional_info",
    "record_furnisher_response",
    "issue_result_notice",
    "dismiss_frivolous",
    "get_dispute",
    # Full pipeline shortcuts
    "close_dispute_verified",
    "close_dispute_updated",
    "close_dispute_deleted",
    "setup_dispute_in_state",
    "submit_n_closed_disputes_on_tradeline",
    "submit_n_closed_disputes_on_distinct_tradelines",
    # Freeze / lock
    "setup_consumer_with_freeze",
    "place_credit_freeze",
    "lift_credit_freeze",
    "place_credit_lock",
    "unlock_credit_lock",
    "relock_credit_lock",
    # Deadline boundary
    "setup_furnisher_inquiry_at_deadline",
    # Regulatory complaints
    "file_regulatory_complaint",
    "accept_complaint",
    "reject_complaint",
    "resolve_complaint",
    # Hard inquiry / pull-free
    "request_hard_inquiry",
    "pull_free_report",
]
