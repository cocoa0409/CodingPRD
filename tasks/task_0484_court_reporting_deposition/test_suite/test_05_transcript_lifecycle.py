"""Transcript ordering, production, read-and-sign, deadline finalization, and
the cross-entity gates (job-adjourned to order; reporter-completed-assignment to
deliver-rough), plus invoice issue readiness and terminal lockdown.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_adjourned_reporter_job,
    setup_confirmed_reporter_job,
    setup_certified_transcript,
    setup_read_sign_open_transcript,
    setup_delivered_transcript,
    order_transcript,
    deliver_rough,
    certify,
    open_read_sign,
    file_errata,
    set_clock,
    create_invoice,
    issue_invoice,
    make_attorney,
    make_reporter,
    make_attorney_headers,
    make_reporter_headers,
    make_schedule_coordinator_headers,
    make_billing_clerk_headers,
    create_transcript_order_payload,
    create_certify_payload,
    create_errata_payload,
)

COORD = make_schedule_coordinator_headers()
BILLING = make_billing_clerk_headers()


# ---------------------------------------------------------------------------
# Rule 7 — cross-entity state dependencies
# ---------------------------------------------------------------------------
def test_transcript_order_requires_job_adjourned(api):
    """PRD §3.8: "The order is only valid when the referenced job's status is
    `ADJOURNED`; ordering against any other status is rejected with
    `ERR_JOB_NOT_ADJOURNED`." A CONFIRMED (not adjourned) job rejects the order.

    Design: Difficulty/cross_entity_state_dependency/transcript_order_requires_job_adjourned
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-13T09:00:00Z",
        scheduled_end="2026-06-13T11:00:00Z")
    resp = api.create_transcript_order(create_transcript_order_payload(
        job_id=sc.job_id, ordering_attorney_id=sc.attorney_id,
        turnaround_tier="STANDARD", certified_copy=True, estimated_pages=30),
        make_attorney_headers(sc.attorney_id))
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_ADJOURNED.value)


# ---------------------------------------------------------------------------
# Transcript lifecycle — corner instances (state_machines)
# ---------------------------------------------------------------------------
def test_new_transcript_order_initial_state_ordered(api):
    """PRD §3.8: "A new order enters `status` `ORDERED` with `final_pages` null,
    `read_sign_deadline` null, and `errata_round` at 0."

    Design: Corner/state_machines/newly_created_transcript_order_initial_state_ordered
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-07-09T09:00:00Z",
        scheduled_end="2026-07-09T11:00:00Z")
    to = order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                          estimated_pages=30)
    assert to["status"] == "ORDERED", f"new order should be ORDERED, got {to['status']}"
    assert to["errata_round"] == 0, f"new order errata_round should be 0, got {to['errata_round']}"


def test_finalize_deadline_auto_waives_to_signed(api):
    """PRD §3.10: "After the logical clock has advanced to or past the
    `read_sign_deadline`, a `ScheduleCoordinator` may finalize the deadline, which
    auto-waives the signature and moves the order to `SIGNED`." A CERTIFIED
    transcript with the clock past the deadline finalizes to SIGNED.

    Design: Corner/state_machines/finalize_deadline_auto_waives_signature_to_signed
    """
    sc, _ = setup_certified_transcript(
        jurisdiction="STATE_CA", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=30, final_pages=30)
    # certify ran with clock at the session-end (2026-06-01T11:00:00Z by default);
    # advance well past the 30-day deadline.
    set_clock("2026-08-15T00:00:00Z")
    to = validate_success(api.finalize_deadline(sc.transcript_order_id, COORD))
    assert to["status"] == "SIGNED", (
        f"finalize-deadline should auto-waive to SIGNED, got {to['status']}")


def test_second_errata_without_reopen_rejected(api):
    """PRD §3.10: "While the window is open, an `Attorney` may file an **errata**
    sheet, which advances the order from `READ_SIGN_OPEN` to `ERRATA_FILED`."
    PRD §3.10: "Filing errata requires the order to be `READ_SIGN_OPEN`." A second
    errata while already ERRATA_FILED (no re-open) is rejected as invalid state.

    Design: Corner/state_machines/errata_idempotency_second_errata_without_reopen_fails
    """
    sc, _ = setup_read_sign_open_transcript(
        jurisdiction="STATE_CA", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=30, final_pages=30)
    file_errata(sc, corrections=[{"page": 1, "line": 1, "from_text": "a", "to_text": "b"}],
                reason="first")
    resp = api.file_errata(sc.transcript_order_id, create_errata_payload(
        corrections=[{"page": 2, "line": 2, "from_text": "c", "to_text": "d"}],
        reason="second-without-reopen"), make_attorney_headers(sc.attorney_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Transcript / invoice validations (corner)
# ---------------------------------------------------------------------------
def test_certify_with_zero_pages_rejected(api):
    """PRD §3.8: "Certification is only available when `certified_copy` is true and
    requires a supplied `final_pages` of at least 1; a final page count below 1 is
    rejected with `ERR_INVALID_PAGE_COUNT`."

    Design: Corner/validations/certify_with_zero_pages_returns_invalid_page_count
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-07-23T09:00:00Z",
        scheduled_end="2026-07-23T11:00:00Z")
    order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                     estimated_pages=30)
    deliver_rough(sc)
    resp = api.certify_transcript(
        sc.transcript_order_id, create_certify_payload(final_pages=0),
        make_reporter_headers(sc.reporter_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGE_COUNT.value)


def test_errata_after_deadline_by_party_rejected_window_closed(api):
    """PRD §3.10: "requires the logical clock to be strictly before the
    `read_sign_deadline` (an errata filed at or after the deadline is rejected
    with `ERR_READ_SIGN_WINDOW_CLOSED`)." The ordering attorney (a case party)
    filing errata after the deadline is rejected on the closed window.

    Design: Corner/validations/errata_after_deadline_in_window_party_returns_window_closed
    """
    sc, _ = setup_read_sign_open_transcript(
        jurisdiction="STATE_CA", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=30, final_pages=30)
    set_clock("2026-09-01T00:00:00Z")  # past the 30-day deadline
    resp = api.file_errata(sc.transcript_order_id, create_errata_payload(
        corrections=[{"page": 1, "line": 1, "from_text": "x", "to_text": "y"}],
        reason="late but party"), make_attorney_headers(sc.attorney_id))
    validate_error(resp, ApiErrorId.ERR_READ_SIGN_WINDOW_CLOSED.value)


def test_issue_invoice_before_transcript_delivered_rejected(api):
    """PRD §3.14: "Issuance is permitted only from `DRAFT` and additionally
    requires that the linked transcript order's status is `DELIVERED` and that the
    recomputed `total_cents` is greater than 0; if the transcript is not yet
    delivered or the total would be zero, the issue is rejected with
    `ERR_INVOICE_NOT_READY`." A SIGNED-but-not-DELIVERED transcript blocks issue.

    Design: Corner/validations/issue_invoice_before_transcript_delivered_returns_invoice_not_ready
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-07-26T09:00:00Z",
        scheduled_end="2026-07-26T11:00:00Z")
    order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                     estimated_pages=30)
    deliver_rough(sc)
    certify(sc, final_pages=30)
    # open read-and-sign, then sign (case party) but do NOT deliver.
    open_read_sign(sc)
    validate_success(api.sign_transcript(
        sc.transcript_order_id, make_attorney_headers(sc.attorney_id)))
    create_invoice(sc)
    resp = api.issue_invoice(sc.invoice_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_READY.value)


def test_void_paid_invoice_terminal_lockdown_rejected(api):
    """PRD §3.14: "An invoice can also be voided from either `DRAFT` or `ISSUED`
    (its status must be one of those two), moving it to `VOID`. `PAID` and `VOID`
    are terminal. Any invoice transition attempted from a status that does not
    define it is rejected with `ERR_INVALID_STATE`." Voiding a PAID invoice is
    rejected.

    Design: Corner/state_machines/pay_paid_invoice_terminal_lockdown
    """
    sc, inv = _setup_paid_invoice(api)
    resp = api.void_invoice(inv["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def _setup_paid_invoice(api):
    sc, _ = setup_delivered_transcript(
        jurisdiction="STATE_NY", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=40, final_pages=40,
        hourly_appearance_cents=10000)
    create_invoice(sc)
    issue_invoice(sc)
    inv = validate_success(api.pay_invoice(sc.invoice_id, BILLING))
    return sc, inv
