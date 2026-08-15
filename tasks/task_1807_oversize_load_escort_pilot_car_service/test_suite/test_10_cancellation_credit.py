"""Cancellation fees, credit holds, quote expiry, and credit reconciliation."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    set_clock,
    create_tx_job,
    list_job_legs,
    quote_job,
    accept_quote,
    get_job,
    get_carrier,
    get_assignment,
    setup_booked_job,
    setup_delivered_rear_job,
    advance_to_cleared,
    advance_to_scheduled,
    advance_to_en_route,
    offer_and_accept,
    add_permit,
    issue_permit,
    offer_assignment,
    accept_assignment,
    generate_invoice,
    finalize_invoice,
    record_payment,
    make_carrier_rep_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_accept_quote_places_credit_hold(api):
    """PRD §3.3: "A successful acceptance moves the job to `BOOKED`, stamps
    `booked_at`, and places the quoted hold: the job's `quoted_cents` now
    counts against the carrier's availability for as long as the job remains
    in `BOOKED`, `CLEARED`, `SCHEDULED`, `EN_ROUTE`, or `ON_HOLD`."

    Design: Difficulty/compensating_invariant/book_cancel_conserves_credit
    """
    carrier = register_carrier(10_000_000, "Conservation Carriers")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Cancel me", height_inches=170)
    quoted = quote_job(job["id"])
    assert quoted["quoted_cents"] == 47500  # 2.5h x 1 x 9000 + 25000 survey fee
    accept_quote(job["id"], carrier)

    row = get_carrier(carrier["id"])
    assert row["credit_available_cents"] == 9952500, "10000000 - 47500 quoted hold"


def test_book_then_cancel_conserves_credit(api):
    """PRD §2.10: "cancelling a booked job releases the hold (so a
    book-then-cancel pair conserves the carrier's available credit exactly)"
    PRD §3.6: "a job cancelled from `DRAFT` or `QUOTED` takes tier `NONE` at 0
    percent; from `BOOKED` or `CLEARED`, tier `TIER_10` at 10 percent"

    Design: Difficulty/compensating_invariant/book_cancel_conserves_credit
    """
    carrier = register_carrier(10_000_000, "Conservation Carriers")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Cancel me", height_inches=170)
    quote_job(job["id"])
    accept_quote(job["id"], carrier)

    cancelled = validate_success(
        api.cancel_job(job["id"], make_carrier_rep_headers(carrier["id"]))
    )
    assert cancelled["job_status"] == "CANCELLED"
    assert cancelled["cancel_fee_tier"] == "TIER_10"
    assert cancelled["cancel_fee_cents"] == 4750, "round_half_up(47500 x 0.10)"

    row = get_carrier(carrier["id"])
    assert row["credit_available_cents"] == 10000000, (
        "the book+cancel pair conserves credit_available_cents exactly"
    )


def test_cancellation_fee_tiers_25_and_50(api):
    """PRD §3.6: "computes the cancellation fee from the job's status
    immediately before cancellation: ... from `SCHEDULED`, tier `TIER_25` at
    25 percent; from `EN_ROUTE` or `ON_HOLD`, tier `TIER_50` at 50 percent."
    PRD §3.6: "Cancellation then releases the field: every assignment in
    `OFFERED`, `ACCEPTED`, or `ACTIVE` moves to `RELEASED` with `release_cause`
    `JOB_CANCELLED`"

    Design: Corner/calculations/cancellation_fee_tier_25_and_50
    """
    from test_helpers import read_escort

    carrier = register_carrier(10_000_000, "Fee Tier Co")
    esc = register_escort(("TX",), "Rider FT")

    # J1 driven to SCHEDULED (quoted 22500: 2.5h x 1 position x 9000).
    b1 = setup_booked_job(carrier, load_description="J1")
    b1["escort"] = esc
    advance_to_cleared(b1, permit_kwargs={"permit_number": "TX-P-33"})
    asg1 = offer_and_accept(b1, esc, "REAR")
    advance_to_scheduled(b1)

    # J2 driven to EN_ROUTE on a later window.
    b2 = setup_booked_job(
        carrier,
        load_description="J2",
        window_start_at="2026-08-11T09:00:00Z",
        window_end_at="2026-08-11T13:00:00Z",
        planned_entry_at="2026-08-11T09:00:00Z",
        planned_exit_at="2026-08-11T13:00:00Z",
    )
    b2["escort"] = esc
    advance_to_cleared(
        b2,
        permit_kwargs={"permit_number": "TX-P-34", "valid_until": "2026-08-13T00:00:00Z"},
    )
    asg2 = offer_and_accept(b2, esc, "REAR")
    advance_to_scheduled(b2)
    advance_to_en_route(b2, "2026-08-11T09:00:00Z")

    c1 = validate_success(api.cancel_job(b1["job"]["id"], DISPATCHER))
    assert c1["job_status"] == "CANCELLED"
    assert c1["cancel_fee_tier"] == "TIER_25"
    assert c1["cancel_fee_cents"] == 5625, "round_half_up(22500 x 0.25)"
    a1 = get_assignment(asg1["id"])
    assert a1["assignment_status"] == "RELEASED" and a1["release_cause"] == "JOB_CANCELLED"

    c2 = validate_success(
        api.cancel_job(b2["job"]["id"], make_carrier_rep_headers(carrier["id"]))
    )
    assert c2["job_status"] == "CANCELLED"
    assert c2["cancel_fee_tier"] == "TIER_50"
    assert c2["cancel_fee_cents"] == 11250, "round_half_up(22500 x 0.50)"
    a2 = get_assignment(asg2["id"])
    assert a2["assignment_status"] == "RELEASED" and a2["release_cause"] == "JOB_CANCELLED"

    assert read_escort(esc["id"])["active_assignment_count"] == 0


def test_cancel_terminal_lockdown(api):
    """PRD §3.6: "A job in `DELIVERED`, `CLOSED`, or `CANCELLED` cannot be
    cancelled, and neither can a job that already has an invoice in
    `FINALIZED`, `DISPUTED`, or `PAID`; both violations are rejected with
    `ERR_JOB_INVALID_STATE`."

    Design: Corner/state_machines/cancel_terminal_lockdown
    """
    carrier = register_carrier(10_000_000, "Lockdown Co")
    set_clock("2026-08-05T00:00:00Z")
    job_x = create_tx_job(carrier, load_description="X")
    quote_job(job_x["id"])
    validate_success(api.cancel_job(job_x["id"], make_carrier_rep_headers(carrier["id"])))

    bundle_y = setup_delivered_rear_job(
        carrier_credit=10_000_000,
        depart_at="2026-08-11T09:00:00Z",
        deliver_at="2026-08-11T10:00:00Z",
        escort_name="Rider L",
    )

    resp = api.cancel_job(job_x["id"], make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    resp2 = api.cancel_job(bundle_y["job"]["id"], DISPATCHER)
    validate_error(resp2, ApiErrorId.ERR_JOB_INVALID_STATE)
    assert get_job(bundle_y["job"]["id"])["job_status"] == "DELIVERED"


def test_state_beats_fiscal_on_accept_quote(api):
    """PRD §2.11: "7. State preconditions: the target resource must be in a
    state that permits the operation, per the transition rules of §3, else the
    matching invalid-state error (HTTP 409) ... 13. Carrier credit:
    `ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED` (HTTP 402)."
    PRD §3.3: "The job must be in `QUOTED`, else `ERR_JOB_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_accept_quote
    """
    carrier = register_carrier(100, "Broke Trailers LLC")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Tall box", height_inches=170)
    quoted = quote_job(job["id"])
    assert quoted["quoted_cents"] == 47500
    validate_success(api.cancel_job(job["id"], make_carrier_rep_headers(carrier["id"])))

    # The job is CANCELLED and credit (100) cannot cover the quote (47500);
    # the state precondition (item 7) must win over the fiscal check (item 13).
    resp = api.accept_quote(job["id"], make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)
    assert resp.status_code == 409


def test_rejected_accept_quote_places_no_hold(api):
    """PRD §2.10: "A carrier's `credit_available_cents` equals its
    `credit_limit_cents`, minus the sum of `quoted_cents` over that carrier's
    jobs currently in `BOOKED`, `CLEARED`, `SCHEDULED`, `EN_ROUTE`, or
    `ON_HOLD` status"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_accept_quote
    """
    carrier = register_carrier(100, "Broke Trailers LLC")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Tall box", height_inches=170)
    quote_job(job["id"])
    validate_success(api.cancel_job(job["id"], make_carrier_rep_headers(carrier["id"])))

    resp = api.accept_quote(job["id"], make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    assert get_job(job["id"])["job_status"] == "CANCELLED"
    assert get_carrier(carrier["id"])["credit_available_cents"] == 100, (
        "no credit hold was placed by the rejected acceptance"
    )


def test_credit_insufficient_fires_402(api):
    """PRD §3.3: "Finally, the carrier's `credit_available_cents` per §2.10
    must be at least the job's `quoted_cents`; if accepting would push the
    carrier's outstanding quoted holds plus outstanding billed invoices above
    its `credit_limit_cents`, the acceptance is rejected with
    `ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_insufficient_fires_402
    """
    carrier = register_carrier(100, "Tiny Limit Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Too pricey")
    quoted = quote_job(job["id"])
    assert quoted["quoted_cents"] == 22500

    resp = api.accept_quote(job["id"], make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED)
    assert resp.status_code == 402
    assert get_job(job["id"])["job_status"] == "QUOTED", "job remains QUOTED; no hold placed"
    assert get_carrier(carrier["id"])["credit_available_cents"] == 100


def test_quote_expired_at_exact_ttl(api):
    """PRD §3.3: "The acceptance must arrive before `quote_expires_at`; an
    attempt at or after that instant is rejected with `ERR_QUOTE_EXPIRED`."

    Design: Corner/validations/quote_expired_at_exact_ttl
    """
    carrier = register_carrier(10_000_000, "Expiry Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description="Expiring",
        window_start_at="2026-08-12T09:00:00Z",
        window_end_at="2026-08-12T13:00:00Z",
        planned_entry_at="2026-08-12T09:00:00Z",
        planned_exit_at="2026-08-12T13:00:00Z",
    )
    quoted = quote_job(job["id"])
    assert quoted["quote_expires_at"] == "2026-08-08T00:00:00.000Z"

    set_clock("2026-08-08T00:00:00Z")
    resp = api.accept_quote(job["id"], make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
    assert get_job(job["id"])["job_status"] == "QUOTED"


def test_computed_read_credit_reconciliation(api):
    """PRD §2.10: "Availability is a computed field, re-evaluated whenever its
    inputs move: accepting a quote consumes availability, cancelling a booked
    job releases the hold (so a book-then-cancel pair conserves the carrier's
    available credit exactly), finalizing an invoice moves its total into the
    outstanding set, disputing keeps it there, and recording payment or writing
    the invoice off removes it — payment additionally credits the carrier's
    year-to-date billed total, while write-off does not."
    PRD §3.8: "when the underlying job is `DELIVERED`, closes the job by moving
    it to `CLOSED`."

    Design: Corner/endpoints/computed_read_credit_reconciliation
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z")
    carrier = bundle["carrier"]
    job_id = bundle["job"]["id"]

    inv = generate_invoice(job_id, "bc-1")
    # Delivered jobs leave the quoted-hold set; DRAFT invoices are not outstanding.
    assert get_carrier(carrier["id"])["credit_available_cents"] == 10000000

    finalize_invoice(inv["id"], "bc-2")
    assert get_carrier(carrier["id"])["credit_available_cents"] == 9961480, (
        "10000000 - 38520 while FINALIZED"
    )

    record_payment(inv["id"], 38520)
    row = get_carrier(carrier["id"])
    assert row["credit_available_cents"] == 10000000
    assert row["ytd_billed_cents"] == 38520
    assert get_job(job_id)["job_status"] == "CLOSED"
