"""Composite setup helpers for the Public Library API.

Most interesting test claims require the system to be in a specific state that
takes 5–15 API calls to reach (e.g., a reader with a verified identity, an
active card, a borrowed loan that is now overdue, a fine that has accrued, a
queue head that promoted on return). This module encapsulates those preambles
so each test can focus on its single assertion.

Identity threading (mandatory per PRD §2.1): every fixture that creates a
Reader threads make_reader_headers(reader["id"]) into downstream
ownership-gated calls. Falling back to the shared constant would make every
ownership check reject the request and mask the implementation's behavior.

Fixtures use get_success_data (lenient validator) so setup failures produce
clear "Setup failed" errors rather than confusing assertion mismatches.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    acquire_new_book_title_payload,
    advance_clock_payload,
    blacklist_reader_payload,
    create_book_title_payload,
    create_copy_payload,
    create_ill_request_payload,
    create_loan_payload,
    create_reader_payload,
    create_reservation_payload,
    create_suggestion_payload,
    decide_suggestion_payload,
    dispatch_ill_payload,
    emit_event_payload,
    identity_verified_event_payload,
    ill_availability_event_payload,
    ill_delivered_event_payload,
    ill_return_initiated_event_payload,
    issue_card_payload,
    pay_fine_payload,
    payment_confirmed_event_payload,
    recall_loan_payload,
    return_loan_payload,
    waive_fine_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_fine_officer_headers,
    make_ill_coordinator_headers,
    make_librarian_headers,
    make_reader_headers,
)


# ─────────────────────────────────────────────────────────────
# Convenience header aliases (opaque roles — safe as shared constants)
# ─────────────────────────────────────────────────────────────

LIBRARIAN_HEADERS = TEST_USERS["librarian_headers"]
LIBRARIAN_HEADERS_ALT = TEST_USERS["librarian_headers_alt"]
FINE_OFFICER_HEADERS = TEST_USERS["fine_officer_headers"]
ILL_COORDINATOR_HEADERS = TEST_USERS["ill_coordinator_headers"]
ADMIN_HEADERS = TEST_USERS["admin_headers"]


# =============================================================================
# Tier 0: Time-helpers and atomic single-entity creation
# =============================================================================


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime) -> str:
    """Render a datetime as an ISO 8601 string with millisecond precision and Z suffix."""
    s = ts.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return s.replace("+00:00", "Z")


def advance_clock_days(days: int) -> Dict[str, Any]:
    """Advance the simulated clock by `days` whole days (PRD §2.12)."""
    res = api_client.advance_clock(advance_clock_payload(f"P{days}D"), ADMIN_HEADERS)
    return get_success_data(res)


def run_sweep() -> Dict[str, Any]:
    """Trigger PRD §3.9 operational sweep."""
    res = api_client.run_sweep(ADMIN_HEADERS)
    return get_success_data(res)


def create_book_title(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: Librarian creates a BookTitle."""
    res = api_client.create_book_title(
        create_book_title_payload(**overrides), LIBRARIAN_HEADERS
    )
    return get_success_data(res)


def create_copy(book_title_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: Librarian adds a Copy under a title."""
    res = api_client.create_copy(
        book_title_id, create_copy_payload(**overrides), LIBRARIAN_HEADERS
    )
    return get_success_data(res)


def create_book_title_with_copy(
    *,
    subject_category: str = "GENERAL",
    title_overrides: Optional[Dict[str, Any]] = None,
    copy_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """PRD §3.1: title + one AVAILABLE copy. Convenience for borrow-flow tests."""
    title = create_book_title(
        subject_category=subject_category, **(title_overrides or {})
    )
    copy = create_copy(title["id"], **(copy_overrides or {}))
    return title, copy


def create_unverified_reader(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: register a reader (identity_verified starts false)."""
    res = api_client.create_reader(
        create_reader_payload(**overrides), LIBRARIAN_HEADERS
    )
    return get_success_data(res)


def emit_identity_verified(reader_id: str) -> None:
    """PRD §3.2 / §3.9: Admin posts IDENTITY_VERIFIED event for the reader."""
    res = api_client.emit_event(
        identity_verified_event_payload(reader_id), ADMIN_HEADERS
    )
    get_success_data(res)


def create_verified_reader(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: register a reader AND verify identity. Returns the reader as
    observed post-verification."""
    reader = create_unverified_reader(**overrides)
    emit_identity_verified(reader["id"])
    res = api_client.get_reader(reader["id"], LIBRARIAN_HEADERS)
    return get_success_data(res)


def issue_card(
    reader_id: str,
    *,
    card_type: str = "REGULAR",
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.2: Librarian issues a card to a verified reader."""
    overrides: Dict[str, Any] = {"card_type": card_type}
    if valid_from is not None:
        overrides["valid_from"] = valid_from
    if valid_until is not None:
        overrides["valid_until"] = valid_until
    res = api_client.issue_card(
        reader_id, issue_card_payload(**overrides), LIBRARIAN_HEADERS
    )
    return get_success_data(res)


def create_verified_reader_with_card(
    *, card_type: str = "REGULAR", **reader_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """PRD §3.2: reader + verified + active card. Most tests start here."""
    reader = create_verified_reader(**reader_overrides)
    card = issue_card(reader["id"], card_type=card_type)
    return reader, card


# =============================================================================
# Tier 1: State Progression — basic borrow / return cycle
# =============================================================================


def create_active_loan(
    *,
    subject_category: str = "GENERAL",
    card_type: str = "REGULAR",
    reader: Optional[Dict[str, Any]] = None,
    card: Optional[Dict[str, Any]] = None,
    title: Optional[Dict[str, Any]] = None,
    copy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.3: Take a reader+card and a title+copy through to BORROWED.

    Returns a dict with keys: reader, card, title, copy, loan.
    Any pre-created entities passed in are reused (so cumulative state can be
    built up across calls)."""
    if reader is None or card is None:
        reader, card = create_verified_reader_with_card(card_type=card_type)
    if title is None or copy is None:
        title, copy = create_book_title_with_copy(subject_category=subject_category)

    res = api_client.create_loan(
        create_loan_payload(copy["id"], card["id"], channel="COUNTER"),
        make_reader_headers(reader["id"]),
    )
    loan = get_success_data(res)
    return {
        "reader": reader,
        "card": card,
        "title": title,
        "copy": copy,
        "loan": loan,
    }


def return_loan_on_time(loan_id: str, reader_id: str) -> Dict[str, Any]:
    """PRD §3.4: return a loan before its effective due date — no fine."""
    res = api_client.return_loan(
        loan_id, return_loan_payload(), make_reader_headers(reader_id)
    )
    return get_success_data(res)


# =============================================================================
# Tier 2: Compound builders — overdue, fine accrual, recall
# =============================================================================


def create_overdue_loan(
    *,
    subject_category: str = "GENERAL",
    card_type: str = "REGULAR",
    days_past_due: int = 5,
) -> Dict[str, Any]:
    """PRD §3.4: create a BORROWED loan, then advance clock so it is overdue by
    `days_past_due` whole days. Loan is still in BORROWED (not yet returned).

    Returns: {reader, card, title, copy, loan}.
    The simulated clock has been advanced past the loan's due_at by exactly
    days_past_due whole days.
    """
    ctx = create_active_loan(
        subject_category=subject_category, card_type=card_type
    )
    # loan_duration_days is pinned at issuance (PRD §3.2). Advance by
    # loan_duration_days + days_past_due so now() > due_at by exactly
    # days_past_due.
    advance_clock_days(ctx["card"]["loan_duration_days"] + days_past_due)
    return ctx


def _discover_fine_for_loan(
    loan_id: str, reader_id: str
) -> Optional[Dict[str, Any]]:
    """PRD §3.6 expresses Fine creation via the LOAN_RETURNED / FINE_ACCRUED
    audit-log events. Look up the Fine row by scanning the audit log (Admin
    role) and then GET it via the FineOfficer / Admin role.

    Returns None if no FINE_ACCRUED entry is associated with this loan_id —
    callers should treat that as "no fine was created" (PRD §3.6: lazy
    creation only if days_overdue > 0).
    """
    res = api_client.list_audit_logs(
        ADMIN_HEADERS, params={"event_type": "FINE_ACCRUED", "limit": 100}
    )
    raw = res.json() if hasattr(res, "json") else {}
    entries = (raw.get("data") if isinstance(raw, dict) else None) or []
    # Walk newest entries first — most useful when many fines exist.
    for entry in reversed(entries):
        payload = entry.get("payload") or {}
        # PRD §2.8: payload snapshots relevant fields. The Fine row carries
        # loan_id (PRD §3.6), so a FINE_ACCRUED entry's subject_id is the
        # Fine.id and its payload either includes loan_id directly or carries
        # an `after` block where loan_id lives.
        nested = payload.get("after") if isinstance(payload, dict) else None
        candidate_loan = (
            payload.get("loan_id")
            or (nested.get("loan_id") if isinstance(nested, dict) else None)
        )
        if (
            candidate_loan == loan_id
            and entry.get("subject_type") == "Fine"
            and entry.get("subject_id")
        ):
            return get_success_data(
                api_client.get_fine(
                    entry["subject_id"], make_reader_headers(reader_id)
                )
            )
    return None


def create_loan_then_return_late(
    *,
    subject_category: str = "GENERAL",
    card_type: str = "REGULAR",
    days_past_due: int = 5,
) -> Dict[str, Any]:
    """PRD §3.4 + §3.6: Borrow → clock advance → return late, producing an
    OVERDUE_CLOSED loan and a finalized PENDING Fine.

    Returns: {reader, card, title, copy, loan (OVERDUE_CLOSED), fine}.
    `fine` may be None if PRD §3.6's "no fine if days_overdue <= 0" branch fires
    (e.g., when days_past_due is 0 due to rounding); callers that expect a fine
    should pin days_past_due >= 1.
    """
    ctx = create_overdue_loan(
        subject_category=subject_category,
        card_type=card_type,
        days_past_due=days_past_due,
    )
    returned_loan = get_success_data(
        api_client.return_loan(
            ctx["loan"]["id"],
            return_loan_payload(),
            make_reader_headers(ctx["reader"]["id"]),
        )
    )
    fine = _discover_fine_for_loan(ctx["loan"]["id"], ctx["reader"]["id"])
    return {**ctx, "loan": returned_loan, "fine": fine}


def create_recalled_loan(
    *, subject_category: str = "GENERAL", card_type: str = "REGULAR"
) -> Dict[str, Any]:
    """PRD §3.4: Borrow → advance past due_at → recall (overdue path; no
    reservation needed). Returns a loan in RECALL_PENDING."""
    ctx = create_overdue_loan(
        subject_category=subject_category, card_type=card_type, days_past_due=1
    )
    res = api_client.recall_loan(
        ctx["loan"]["id"], recall_loan_payload(), LIBRARIAN_HEADERS
    )
    recalled_loan = get_success_data(res)
    ctx["loan"] = recalled_loan
    return ctx


# =============================================================================
# Tier 3: Reservation flows
# =============================================================================


def create_loan_with_pending_reservation(
    *, subject_category: str = "GENERAL"
) -> Dict[str, Any]:
    """PRD §3.5: Reader A borrows the only copy. Reader B then files a
    reservation against the same title — reservation enters QUEUED (no
    available copy to promote).

    Returns: {reader_a, card_a, reader_b, card_b, title, copy, loan,
              reservation}.
    """
    title, copy = create_book_title_with_copy(subject_category=subject_category)
    reader_a, card_a = create_verified_reader_with_card()
    reader_b, card_b = create_verified_reader_with_card()

    loan = get_success_data(
        api_client.create_loan(
            create_loan_payload(copy["id"], card_a["id"], channel="COUNTER"),
            make_reader_headers(reader_a["id"]),
        )
    )
    reservation = get_success_data(
        api_client.create_reservation(
            create_reservation_payload(title["id"], card_b["id"], channel="ONLINE"),
            make_reader_headers(reader_b["id"]),
        )
    )
    return {
        "reader_a": reader_a,
        "card_a": card_a,
        "reader_b": reader_b,
        "card_b": card_b,
        "title": title,
        "copy": copy,
        "loan": loan,
        "reservation": reservation,
    }


def setup_ready_for_pickup_reservation(
    *, subject_category: str = "GENERAL"
) -> Dict[str, Any]:
    """PRD §3.5: end up with a Reservation in READY_FOR_PICKUP (the cascade
    that fires when A's return promotes B's QUEUED reservation).

    Returns: {reader_a, card_a, reader_b, card_b, title, copy, reservation
              (READY_FOR_PICKUP)}.
    """
    ctx = create_loan_with_pending_reservation(subject_category=subject_category)
    # A returns on time — cascade promotes B's reservation.
    get_success_data(
        api_client.return_loan(
            ctx["loan"]["id"],
            return_loan_payload(),
            make_reader_headers(ctx["reader_a"]["id"]),
        )
    )
    promoted = get_success_data(
        api_client.get_reservation(
            ctx["reservation"]["id"], make_reader_headers(ctx["reader_b"]["id"])
        )
    )
    ctx["reservation"] = promoted
    return ctx


# =============================================================================
# Tier 4: Fine workflow — accrual, payment, waiver
# =============================================================================


def emit_payment_confirmed(
    fine_id: str, idempotency_key: str, amount_cents: Optional[int] = None
) -> None:
    """PRD §3.6 / §3.9: emit a PAYMENT_CONFIRMED event so a subsequent pay can
    succeed."""
    res = api_client.emit_event(
        payment_confirmed_event_payload(
            fine_id, idempotency_key=idempotency_key, amount_cents=amount_cents
        ),
        ADMIN_HEADERS,
    )
    get_success_data(res)


def pay_fine_full(fine: Dict[str, Any], reader_id: str) -> Dict[str, Any]:
    """PRD §3.6: post PAYMENT_CONFIRMED then pay the full outstanding amount.
    Returns the resulting Fine (settlement_status should be SETTLED)."""
    outstanding = fine["outstanding_cents"]
    key = f"pay-{fine['id']}-full"
    emit_payment_confirmed(fine["id"], key, outstanding)
    res = api_client.pay_fine(
        fine["id"],
        pay_fine_payload(outstanding, idempotency_key=key),
        make_reader_headers(reader_id),
    )
    return get_success_data(res)


def waive_fine_amount(
    fine_id: str,
    waive_cents: int,
    *,
    reason: str = "HOLIDAY",
) -> Dict[str, Any]:
    """PRD §3.6: FineOfficer applies a waiver."""
    res = api_client.waive_fine(
        fine_id,
        waive_fine_payload(waive_cents, reason=reason),
        FINE_OFFICER_HEADERS,
    )
    return get_success_data(res)


# =============================================================================
# Tier 5: ILL workflow (PRD §3.7) — shipping_cost_cents under test control so
# cent-precision boundaries can be hit.
# =============================================================================


def submit_ill_request(
    reader: Dict[str, Any],
    card: Dict[str, Any],
    target_marc_control_number: str,
    *,
    partner_library_code: str = "PL_A",
    shipping_cost_cents: int = 1000,
) -> Dict[str, Any]:
    """PRD §3.7: Reader submits an ILL request via their own card."""
    res = api_client.create_ill_request(
        create_ill_request_payload(
            card["id"],
            partner_library_code=partner_library_code,
            target_marc_control_number=target_marc_control_number,
            shipping_cost_cents=shipping_cost_cents,
        ),
        make_reader_headers(reader["id"]),
    )
    return get_success_data(res)


def setup_ill_at_partner(
    *,
    shipping_cost_cents: int = 1000,
    partner_max_days: int = 14,
) -> Dict[str, Any]:
    """PRD §3.7: progress an ILL request all the way to AT_PARTNER.

    Steps: catalog title locally (so dispatch has a Copy with the right
    marc_control_number) → reader+card → submit request → AVAILABILITY event →
    approve → dispatch (Copy goes IN_TRANSIT_ILL) → ILL_DELIVERED event.

    Returns: {reader, card, title, copy, ill_request (AT_PARTNER),
              agreed_loan_days}.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    req = submit_ill_request(
        reader,
        card,
        title["marc_control_number"],
        shipping_cost_cents=shipping_cost_cents,
    )
    # Availability event
    get_success_data(
        api_client.emit_event(
            ill_availability_event_payload(
                req["id"], available=True, partner_max_days=partner_max_days
            ),
            ADMIN_HEADERS,
        )
    )
    # Approve
    req = get_success_data(
        api_client.approve_ill(req["id"], None, ILL_COORDINATOR_HEADERS)
    )
    # Dispatch
    req = get_success_data(
        api_client.dispatch_ill(
            req["id"], dispatch_ill_payload(copy["id"]), ILL_COORDINATOR_HEADERS
        )
    )
    # Delivered (advances IN_TRANSIT -> AT_PARTNER)
    get_success_data(
        api_client.emit_event(
            ill_delivered_event_payload(req["id"]), ADMIN_HEADERS
        )
    )
    agreed = min(partner_max_days, 21)
    return {
        "reader": reader,
        "card": card,
        "title": title,
        "copy": copy,
        "ill_request": req,
        "agreed_loan_days": agreed,
    }


def setup_ill_returned_transit(
    *,
    shipping_cost_cents: int = 1000,
    partner_max_days: int = 14,
) -> Dict[str, Any]:
    """PRD §3.7: progress an ILL request to RETURNED_TRANSIT.

    Steps continue from AT_PARTNER: advance clock past in_transit_from +
    agreed_loan_days → emit ILL_RETURN_INITIATED event.
    """
    ctx = setup_ill_at_partner(
        shipping_cost_cents=shipping_cost_cents, partner_max_days=partner_max_days
    )
    # Advance by agreed_loan_days whole days so now >= in_transit_from + agreed.
    advance_clock_days(ctx["agreed_loan_days"])
    get_success_data(
        api_client.emit_event(
            ill_return_initiated_event_payload(ctx["ill_request"]["id"]),
            ADMIN_HEADERS,
        )
    )
    return ctx


# =============================================================================
# Tier 6: Acquisition-suggestion workflow (PRD §3.8)
# =============================================================================


def setup_under_review_suggestion(
    *,
    suggested_isbn: str = "9781234567897",
) -> Dict[str, Any]:
    """PRD §3.8: submit and start-review a suggestion. Returns
    {reader, card, suggestion (UNDER_REVIEW)}."""
    reader, card = create_verified_reader_with_card()
    res = api_client.create_suggestion(
        create_suggestion_payload(
            card["id"], suggested_isbn=suggested_isbn, suggested_title="Suggested Title"
        ),
        make_reader_headers(reader["id"]),
    )
    suggestion = get_success_data(res)
    res = api_client.start_review_suggestion(
        suggestion["id"], None, LIBRARIAN_HEADERS
    )
    suggestion = get_success_data(res)
    return {"reader": reader, "card": card, "suggestion": suggestion}


# =============================================================================
# Tier 7: Cumulative-state targeting — for boundary-precision tests
# =============================================================================


def setup_card_with_n_active_loans_and_m_reservations(
    *,
    card_type: str = "REGULAR",
    n_loans: int = 0,
    m_reservations: int = 0,
) -> Dict[str, Any]:
    """PRD §3.3 quota: build a card with exactly N active loans (BORROWED) and
    M active reservations (QUEUED) so the strict-vs-chronological readings can
    be tested.

    Each loan consumes a fresh BookTitle (so reservations don't trip the
    duplicate-reservation rule). Reservations are placed against BookTitles
    whose only copy is currently ON_LOAN (to keep the reservation in QUEUED
    rather than auto-promoting it to READY_FOR_PICKUP).

    Returns: {reader, card, loans, reservations}.
    """
    reader, card = create_verified_reader_with_card(card_type=card_type)
    reader_headers = make_reader_headers(reader["id"])

    loans: List[Dict[str, Any]] = []
    for _ in range(n_loans):
        title, copy = create_book_title_with_copy()
        loan = get_success_data(
            api_client.create_loan(
                create_loan_payload(copy["id"], card["id"], channel="COUNTER"),
                reader_headers,
            )
        )
        loans.append(loan)

    reservations: List[Dict[str, Any]] = []
    # For a reservation to stay QUEUED, the title must have no AVAILABLE copy.
    # Easiest: create a title with one copy and have a different reader borrow it.
    for _ in range(m_reservations):
        title, copy = create_book_title_with_copy()
        # Mint a fresh reader+card to consume the only copy.
        other_reader, other_card = create_verified_reader_with_card()
        get_success_data(
            api_client.create_loan(
                create_loan_payload(copy["id"], other_card["id"], channel="COUNTER"),
                make_reader_headers(other_reader["id"]),
            )
        )
        reservation = get_success_data(
            api_client.create_reservation(
                create_reservation_payload(title["id"], card["id"], channel="ONLINE"),
                reader_headers,
            )
        )
        reservations.append(reservation)

    return {
        "reader": reader,
        "card": card,
        "loans": loans,
        "reservations": reservations,
    }
