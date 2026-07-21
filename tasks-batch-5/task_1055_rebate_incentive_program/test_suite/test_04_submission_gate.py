"""The submission gate: temporal windows, serial dedupe, the per-offer cap and withdrawal."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    attach_receipt,
    create_active_program,
    create_dealer_claimant,
    create_published_offer,
    make_dealer_headers,
    open_claim,
    read_claim,
    read_claimant,
    read_offer,
    read_program,
    set_clock,
    setup_catalogue,
    setup_draft_claim,
    setup_submitted_claim,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
TWO_UNITS = [{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 1000}]
TEN_UNITS = [{"sku": "TOOLS-A", "quantity": 10, "unit_price_cents": 2000}]


def test_purchase_exactly_at_the_offer_end_date_is_outside_the_window(api):
    """PRD §3.4: "Every receipt's `purchase_date` must also fall inside the offer's
    half-open window, and a purchase exactly at `effective_end_date` is refused
    with `ERR_PURCHASE_OUTSIDE_OFFER_WINDOW` (HTTP 422)."

    Design: Corner/validations/purchase_exactly_at_offer_end_date_is_outside_the_window
    """
    ctx = setup_draft_claim(
        clock="2026-09-15T00:00:00Z",
        program_overrides={"name": "Edge Window Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Edge Window Offer"},
        purchase_date="2026-09-01T00:00:00Z",
        serial_number="SN-EDG-1",
        lines=TWO_UNITS,
    )
    resp = api.submit_claim(ctx["claim"]["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_PURCHASE_OUTSIDE_OFFER_WINDOW.value)
    assert read_claim(ctx["claim"]["id"])["adjudication_status"] == "DRAFT"


def test_fourth_submission_on_one_offer_exceeds_the_claim_cap(api):
    """PRD §3.4: "At submission, the count of this claimant's *other* claims on the
    same offer whose adjudication state is anything other than `DRAFT`,
    `WITHDRAWN` or `VOIDED` must be strictly less than 3; the claim being
    submitted is not itself counted. A fourth submission against the same offer is
    refused with `ERR_CLAIM_CAP_EXCEEDED` (HTTP 409), and withdrawing one of the
    three frees the slot again."

    Design: Corner/validations/fourth_submit_on_one_offer_exceeds_the_claim_cap
    """
    ctx = setup_catalogue(
        program_overrides={"name": "Cap Count Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Cap Count Offer"},
    )
    for index in range(1, 4):
        claim = open_claim(ctx["offer"]["id"], ctx["claimant"])
        attach_receipt(
            claim["id"], ctx["claimant"], serial_number=f"SN-CC-{index}", lines=TWO_UNITS
        )
        validate_success(api.submit_claim(claim["id"], ctx["headers"]))

    fourth = open_claim(ctx["offer"]["id"], ctx["claimant"])
    attach_receipt(fourth["id"], ctx["claimant"], serial_number="SN-CC-4", lines=TWO_UNITS)

    resp = api.submit_claim(fourth["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED.value)

    assert read_claim(fourth["id"])["adjudication_status"] == "DRAFT"
    assert read_claimant(ctx["claimant"]["id"])["open_claim_count"] == 3
    assert read_offer(ctx["offer"]["id"])["active_claim_count"] == 3


def test_second_withdraw_on_a_withdrawn_claim_is_refused(api):
    """PRD §3.6: "A review attempt from a state that does not declare the
    transition is refused with `ERR_CLAIM_NOT_REVIEWABLE`, and any adjudication
    action attempted against a claim already resting in `APPROVED`, `REVOKED`,
    `WITHDRAWN` or `VOIDED` is refused with `ERR_CLAIM_ALREADY_TERMINAL`."

    Design: Corner/state_machines/second_withdraw_on_terminal_claim_is_rejected
    """
    ctx = setup_submitted_claim(
        program_overrides={"name": "Withdraw Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Withdraw Offer"},
        lines=TWO_UNITS,
    )
    validate_success(api.withdraw_claim(ctx["claim"]["id"], ctx["headers"]))

    resp = api.withdraw_claim(ctx["claim"]["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL.value)

    assert read_claim(ctx["claim"]["id"])["adjudication_status"] == "WITHDRAWN"
    assert read_claimant(ctx["claimant"]["id"])["open_claim_count"] == 0
    assert read_offer(ctx["offer"]["id"])["active_claim_count"] == 0


# --------------------------------------------------------------------------- #
# The offer-close grace window (Claim depends on Offer)
# --------------------------------------------------------------------------- #

def _grace_window_setup():
    ctx = setup_catalogue(
        clock="2026-07-10T00:00:00Z",
        program_overrides={"name": "Grace Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Grace Offer"},
    )
    early = open_claim(ctx["offer"]["id"], ctx["claimant"])
    attach_receipt(
        early["id"],
        ctx["claimant"],
        serial_number="SN-GRC-1",
        purchase_date="2026-06-15T00:00:00Z",
        lines=TWO_UNITS,
    )
    late = open_claim(ctx["offer"]["id"], ctx["claimant"])
    attach_receipt(
        late["id"],
        ctx["claimant"],
        serial_number="SN-GRC-2",
        purchase_date="2026-06-15T00:00:00Z",
        lines=[{"sku": "TOOLS-B", "quantity": 2, "unit_price_cents": 1000}],
    )
    validate_success(api_client.close_offer(ctx["offer"]["id"], ADMIN))
    ctx["early"] = early
    ctx["late"] = late
    return ctx


def test_submission_on_grace_day_fifteen_is_accepted(api):
    """PRD §3.2: "`CLOSED` is terminal for an offer, but it is not immediately the
    end of claiming: submissions against a closed offer are still accepted for a
    grace period of 15 whole days measured from `closed_at`, inclusive of the
    fifteenth day."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_offer_close_grace_window
    """
    ctx = _grace_window_setup()
    set_clock("2026-07-25T00:00:00Z")

    submitted = validate_success(api.submit_claim(ctx["early"]["id"], ctx["headers"]))
    assert submitted["adjudication_status"] == "SUBMITTED"
    assert submitted["provisional_rebate_cents"] == 100
    assert read_offer(ctx["offer"]["id"])["status"] == "CLOSED"


def test_submission_on_grace_day_sixteen_is_refused(api):
    """PRD §3.2: "On day 16 the door shuts and a submission attempt reports
    `ERR_OFFER_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_offer_close_grace_window
    """
    ctx = _grace_window_setup()
    set_clock("2026-07-25T00:00:00Z")
    validate_success(api.submit_claim(ctx["early"]["id"], ctx["headers"]))

    set_clock("2026-07-26T00:00:00Z")
    resp = api.submit_claim(ctx["late"]["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_CLOSED.value)
    assert read_claim(ctx["late"]["id"])["adjudication_status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Serial-number dedupe over a closed 365-day window
# --------------------------------------------------------------------------- #

def _dedupe_setup():
    program = create_active_program(name="Serial Program", budget_total_cents=100000000)
    offer = create_published_offer(
        program["id"],
        name="Serial Offer",
        sku_scope="TOOLS",
        effective_start_date="2026-06-01T00:00:00Z",
        effective_end_date="2027-09-01T00:00:00Z",
    )
    claimant_a = create_dealer_claimant(legal_name="Serial A", email="sa@ser.example")
    claimant_b = create_dealer_claimant(legal_name="Serial B", email="sb@ser.example")

    claim_a = open_claim(offer["id"], claimant_a)
    attach_receipt(
        claim_a["id"],
        claimant_a,
        serial_number="SN-365",
        purchase_date="2026-06-15T00:00:00Z",
        lines=TWO_UNITS,
    )
    validate_success(api_client.submit_claim(claim_a["id"], make_dealer_headers(claimant_a["id"])))

    set_clock("2027-06-25T00:00:00Z")
    claim_b = open_claim(offer["id"], claimant_b)
    attach_receipt(
        claim_b["id"],
        claimant_b,
        serial_number="SN-365",
        purchase_date="2027-06-15T00:00:00Z",
        lines=TWO_UNITS,
    )
    return {
        "claimant_a": claimant_a,
        "claimant_b": claimant_b,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "headers_b": make_dealer_headers(claimant_b["id"]),
    }


def test_serials_exactly_365_days_apart_still_collide(api):
    """PRD §3.4: "No receipt of the claim being submitted may share a
    `serial_number` with a receipt attached to a *different* claim that is
    currently in `SUBMITTED`, `UNDER_REVIEW`, `HELD` or `APPROVED`, when the two
    receipts' `purchase_date` values lie within 365 whole days of one another.
    That window is a closed interval measured in both directions — 365 days apart
    in either direction still collides, 366 days apart does not."

    Design: Difficulty/resource_temporal_overlap/receipt_serial_dedupe_uses_closed_365_day_window
    """
    ctx = _dedupe_setup()
    resp = api.submit_claim(ctx["claim_b"]["id"], ctx["headers_b"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECEIPT_SERIAL.value)

    assert read_claim(ctx["claim_b"]["id"])["adjudication_status"] == "DRAFT"
    assert read_claim(ctx["claim_a"]["id"])["adjudication_status"] == "SUBMITTED"


def test_duplicate_serial_rejection_increments_the_claimant_counter(api):
    """PRD §3.4: "A collision is refused with `ERR_DUPLICATE_RECEIPT_SERIAL` (HTTP
    409), and the rejection carries a lasting consequence: before the error is
    returned, the claimant's `duplicate_attempt_count` is incremented, and that
    counter feeds the fraud score permanently."

    Design: Difficulty/resource_temporal_overlap/receipt_serial_dedupe_uses_closed_365_day_window
    """
    ctx = _dedupe_setup()
    resp = api.submit_claim(ctx["claim_b"]["id"], ctx["headers_b"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECEIPT_SERIAL.value)

    assert read_claimant(ctx["claimant_b"]["id"])["duplicate_attempt_count"] == 1


# --------------------------------------------------------------------------- #
# Precedence: the claim window is evaluated before the dedupe check
# --------------------------------------------------------------------------- #

def _window_versus_dedupe_setup():
    set_clock("2026-07-01T00:00:00Z")
    program = create_active_program(
        name="Dedupe Priority Program", budget_total_cents=100000000
    )
    offer = create_published_offer(
        program["id"],
        name="Long Offer",
        sku_scope="TOOLS",
        effective_start_date="2026-03-01T00:00:00Z",
        effective_end_date="2026-09-01T00:00:00Z",
    )
    claimant_a = create_dealer_claimant(legal_name="Dealer A", email="a@ded.example")
    claimant_b = create_dealer_claimant(legal_name="Dealer B", email="b@ded.example")

    claim_a = open_claim(offer["id"], claimant_a)
    attach_receipt(
        claim_a["id"],
        claimant_a,
        serial_number="SN-CONFLICT",
        purchase_date="2026-06-15T00:00:00Z",
        lines=TWO_UNITS,
    )
    validate_success(api_client.submit_claim(claim_a["id"], make_dealer_headers(claimant_a["id"])))

    claim_b = open_claim(offer["id"], claimant_b)
    attach_receipt(
        claim_b["id"],
        claimant_b,
        serial_number="SN-CONFLICT",
        purchase_date="2026-04-01T00:00:00Z",
        lines=TWO_UNITS,
    )
    set_clock("2026-07-05T00:00:00Z")
    return {
        "claimant_b": claimant_b,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "headers_b": make_dealer_headers(claimant_b["id"]),
    }


def test_stale_purchase_reports_the_claim_window_before_the_dedupe_check(api):
    """PRD §2.8: "13. Temporal windows, in this internal order: the claim window
    (`ERR_CLAIM_WINDOW_EXPIRED`), the offer purchase window
    (`ERR_PURCHASE_OUTSIDE_OFFER_WINDOW`), the offer grace window
    (`ERR_OFFER_WINDOW_CLOSED`), then the appeal window
    (`ERR_APPEAL_WINDOW_EXPIRED`)."
    PRD §3.4: "Every receipt's `purchase_date` must be recent enough: the whole
    days between a receipt's `purchase_date` and the logical clock must be at most
    90, so a purchase exactly 90 days old is still claimable and one 91 days old is
    refused with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_claim_window_beats_referential_dedupe_on_submit
    """
    ctx = _window_versus_dedupe_setup()
    resp = api.submit_claim(ctx["claim_b"]["id"], ctx["headers_b"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED.value)

    assert read_claim(ctx["claim_b"]["id"])["adjudication_status"] == "DRAFT"
    assert read_claim(ctx["claim_a"]["id"])["adjudication_status"] == "SUBMITTED"


def test_window_rejection_leaves_the_duplicate_counter_untouched(api):
    """PRD §2.8: "14. Referential business checks, in this internal order:
    serial-number dedupe (`ERR_DUPLICATE_RECEIPT_SERIAL`), channel compatibility
    (`ERR_CHANNEL_MISMATCH`), then offer-window overlap
    (`ERR_OFFER_WINDOW_OVERLAP`)."
    PRD §3.4: "A collision is refused with `ERR_DUPLICATE_RECEIPT_SERIAL` (HTTP
    409), and the rejection carries a lasting consequence: before the error is
    returned, the claimant's `duplicate_attempt_count` is incremented, and that
    counter feeds the fraud score permanently."

    Design: Difficulty/priority_pair_validation_conflict/temporal_claim_window_beats_referential_dedupe_on_submit
    """
    ctx = _window_versus_dedupe_setup()
    resp = api.submit_claim(ctx["claim_b"]["id"], ctx["headers_b"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED.value)

    assert read_claimant(ctx["claimant_b"]["id"])["duplicate_attempt_count"] == 0, (
        "The dedupe check never runs, so its counter side effect must not fire"
    )


# --------------------------------------------------------------------------- #
# Slot-count conservation across submit and withdraw
# --------------------------------------------------------------------------- #

def test_submission_raises_slot_counters_and_the_accrual_reserve(api):
    """PRD §3.4: "It increments the claimant's `open_claim_count` by one and the
    offer's `active_claim_count` by one."
    PRD §3.1: "Third, `reserve_cents` is fifteen hundredths of
    `pending_provisional_cents`, rounded half up to whole cents."

    Design: Difficulty/compensating_invariant/submit_then_withdraw_restores_claim_slot_counters_exactly
    """
    ctx = setup_submitted_claim(
        program_overrides={"name": "Slot Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Slot Offer"},
        lines=TEN_UNITS,
    )
    assert ctx["claim"]["provisional_rebate_cents"] == 1600
    assert read_claimant(ctx["claimant"]["id"])["open_claim_count"] == 1
    assert read_offer(ctx["offer"]["id"])["active_claim_count"] == 1

    program = read_program(ctx["program"]["id"])
    assert program["pending_provisional_cents"] == 1600
    assert program["reserve_cents"] == 240
    assert program["available_cents"] == 999760


def test_withdrawal_restores_slot_counters_and_reserve_exactly(api):
    """PRD §3.4: "Withdrawing a `SUBMITTED` claim decrements the claimant's
    `open_claim_count` by one and the offer's `active_claim_count` by one, and
    recomputes the program's `pending_provisional_cents` and `reserve_cents` —
    restoring both conserved counters to exactly their pre-submission values."

    Design: Difficulty/compensating_invariant/submit_then_withdraw_restores_claim_slot_counters_exactly
    """
    ctx = setup_submitted_claim(
        program_overrides={"name": "Slot Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Slot Offer"},
        lines=TEN_UNITS,
    )
    withdrawn = validate_success(api.withdraw_claim(ctx["claim"]["id"], ctx["headers"]))
    assert withdrawn["adjudication_status"] == "WITHDRAWN"

    assert read_claimant(ctx["claimant"]["id"])["open_claim_count"] == 0
    assert read_offer(ctx["offer"]["id"])["active_claim_count"] == 0

    program = read_program(ctx["program"]["id"])
    assert program["pending_provisional_cents"] == 0
    assert program["reserve_cents"] == 0
    assert program["available_cents"] == 1000000
