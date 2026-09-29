"""Billing disputes: the SLA clock, the escalation cycle, withdrawal and the sweep."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DISPUTE_AMOUNT_EXCEEDS_BALANCE,
    ERR_DISPUTE_SLA_EXPIRED,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_ESCALATION_LIMIT_REACHED,
    ERR_INVALID_CREDIT_AMOUNT,
    ERR_INVALID_DISPUTE_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_invoice_dimensions,
    assert_ledger_entry,
    assert_money,
    assert_reserve_summary,
)
from test_helpers.constants import (
    RATED_TOTAL_PRELIMINARY,
    RESERVE_BUCKET_DISPUTED,
    RESERVE_BUCKET_UNCOLLECTIBLE,
    SWEEP_RESOLVER_ID,
    T_2026_10_01,
    T_2026_11_30,
    T_2026_12_01,
)
from test_helpers.factories import (
    dispute_payload,
    escalate_dispute_payload,
    resolve_denied_payload,
    resolve_sustained_payload,
    withdraw_dispute_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    read_carrier,
    read_dispute,
    read_invoice,
    read_ledger,
    read_reserve_summary,
    setup_dispute,
    setup_issued_invoice,
)
from test_helpers.test_users import (
    USER_ACCESS_BILLING_ANALYST,
    USER_DISPUTE_RESOLUTION_OFFICER,
    dispute_resolution_officer_headers,
)

DISPUTED = 10.00
OPEN_AFTER_CREDIT = 22.47
ISSUE_RESERVE = 1.62
DISPUTED_RESERVE = 0.45
DUE_AFTER_TWO_ESCALATIONS = "2026-10-31T00:00:00.000Z"
FULL_BALANCE_DISPUTE = 32.47
OVERSIZED_DISPUTE = 999.99


def test_dispute_listing_pages_a_filtered_slice_in_creation_order(api, analyst_headers):
    """Two disputes on one invoice page one at a time in filing order.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside `meta`. `total_count` is the number of rows matching the request's filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."
    PRD 3.9: "Its clock is set from the reason code: `sla_days` is **30** calendar days for `RATE_APPLICATION`, **60** for `JURISDICTION_FACTOR` and **45** for `USAGE_DISCREPANCY`."
    PRD 3.9: "The second hop increases the invoice's `disputed_amount_usd` by the new dispute's `disputed_amount_usd` and moves the invoice's `dispute_status` to `DISPUTED` — from `NONE` for a first dispute, or from `RESOLVED` for a re-dispute filed inside the window, which requires the clock to be at or before `dispute_deadline_at` and leaves `payment_status` and any partial payments already applied entirely untouched."

    Design: Corner/entities/dispute_listing_pages_a_filtered_slice_in_creation_order
    """
    state = setup_dispute(api)
    first = state["dispute"]
    second = validate_success(
        api.create_dispute(
            dispute_payload(
                state["invoice_id"],
                disputed_amount_usd=5.00,
                reason_code="JURISDICTION_FACTOR",
                supporting_detail="Reported interstate percentage understates the signalled sample",
            ),
            state["rep_headers"],
        ),
        expected_status=201,
    )

    page_one, meta_one = validate_paginated(
        api.list_disputes(
            analyst_headers,
            {"invoice_id": state["invoice_id"], "limit": 1, "offset": 0},
        )
    )
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 1
    assert meta_one["offset"] == 0
    assert len(page_one) == 1
    assert page_one[0]["id"] == first["id"]
    assert_money(page_one[0]["disputed_amount_usd"], DISPUTED)
    assert page_one[0]["reason_code"] == "RATE_APPLICATION"
    assert page_one[0]["sla_days"] == 30

    page_two, meta_two = validate_paginated(
        api.list_disputes(
            analyst_headers,
            {"invoice_id": state["invoice_id"], "limit": 1, "offset": 1},
        )
    )
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 1
    assert len(page_two) == 1
    assert page_two[0]["id"] == second["id"]
    assert_money(page_two[0]["disputed_amount_usd"], 5.00)
    assert page_two[0]["reason_code"] == "JURISDICTION_FACTOR"
    assert page_two[0]["sla_days"] == 60
    assert page_two[0]["created_at"] >= page_one[0]["created_at"]

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["disputed_amount_usd"], 15.00)
    assert invoice["dispute_status"] == "DISPUTED"


def test_resolving_a_dispute_that_was_never_acknowledged_is_refused(
    api, officer_headers
):
    """A SUBMITTED dispute has no resolution transition, so the officer is refused.

    PRD 3.9: "**Resolution** is also the `DisputeResolutionOfficer`'s, may only be performed from `UNDER_REVIEW`, requires the logical clock to be **strictly before** `resolution_due_at` — at or after that instant the dispute can only be deemed allowed by the sweep, and a resolution attempt is refused with `ERR_DISPUTE_SLA_EXPIRED` — and requires the acting `X-User-ID` to differ from the invoice's `issued_by_user_id`."
    PRD 3.9: "Acknowledgement, resolution, escalation and withdrawal each require the dispute to be in a status from which their transition exists, and every other status is refused with `ERR_INVALID_DISPUTE_STATE`: acknowledgement only from `SUBMITTED` or `ESCALATED`, resolution only from `UNDER_REVIEW`, escalation only from `RESOLVED_DENIED`, and withdrawal only from `SUBMITTED`, `UNDER_REVIEW` or `ESCALATED`."
    PRD 2.11: "Because the regulator requires disputed access revenue to be held in full until the dispute closes, the persisted `disputed_reserve_balance_usd` on the carrier equals the whole `disputed_receivable_usd`, and every reserve ledger entry in the `DISPUTED_REVENUE` bucket moves that regulatory figure."

    Design: Corner/state_machines/resolving_a_dispute_that_was_never_acknowledged_is_refused
    """
    state = setup_dispute(api)
    assert state["dispute"]["status"] == "SUBMITTED"

    response = api.resolve_dispute(
        state["dispute_id"], resolve_sustained_payload(DISPUTED), officer_headers
    )
    validate_error(response, ERR_INVALID_DISPUTE_STATE, expected_status=409)

    unchanged = read_dispute(api, state["dispute_id"])
    assert unchanged["status"] == "SUBMITTED"
    assert_money(unchanged["credited_amount_usd"], 0.00)
    assert unchanged["resolved_at"] is None

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["dispute_status"] == "DISPUTED"
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], DISPUTED)


def test_sweep_at_exactly_the_resolution_due_instant_deems_the_dispute_allowed(
    api, admin_headers
):
    """The due instant is inclusive for the sweep, so the credit is granted in full.

    PRD 3.9: "A `PlatformAdmin` runs it with no payload, and it walks every dispute whose `status` is `SUBMITTED`, `UNDER_REVIEW` or `ESCALATED` and whose `resolution_due_at` the logical clock has **reached or passed** — the comparison is inclusive, so a sweep at exactly the due instant deems the dispute allowed, which is precisely the boundary the resolve operation excludes."
    PRD 3.9: "Each swept dispute moves to `RESOLVED_DEEMED_ALLOWED`, which is terminal, from whichever open status it held; its `credited_amount_usd` is set to its full `disputed_amount_usd`, its `resolved_at` is stamped, and its `resolved_by_user_id` is set to the literal string `SYSTEM_SWEEP`."
    PRD 3.9: "Each affected invoice has its `credited_amount_usd` increased by the full disputed amount, its `open_balance_usd` reduced, its `disputed_amount_usd` recomputed and its `dispute_status` moved `DISPUTED → RESOLVED`, and its `lifecycle_status` may auto-move to `CLOSED` under the derivation of §2.10."
    PRD 3.9: "The sweep reports `swept_count`, the number of disputes it moved, and `total_credited_usd`, the total credit it granted."

    Design: Corner/calculations/sweep_at_exactly_the_resolution_due_instant_deems_the_dispute_allowed
    """
    state = setup_dispute(api, acknowledge=True)
    assert state["dispute"]["resolution_due_at"] == T_2026_10_01
    advance_clock(api, T_2026_10_01)

    summary_data = validate_success(
        api.run_dispute_deadline_sweep({}, admin_headers), expected_status=201
    )
    assert summary_data["swept_count"] == 1
    assert_money(summary_data["total_credited_usd"], DISPUTED)

    dispute = read_dispute(api, state["dispute_id"])
    assert dispute["status"] == "RESOLVED_DEEMED_ALLOWED"
    assert_money(dispute["credited_amount_usd"], DISPUTED)
    assert dispute["resolved_by_user_id"] == SWEEP_RESOLVER_ID
    assert dispute["resolution_due_at"] == T_2026_10_01
    assert dispute["escalation_round"] == 0

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["credited_amount_usd"], DISPUTED)
    assert_money(invoice["open_balance_usd"], OPEN_AFTER_CREDIT)
    assert_money(invoice["disputed_amount_usd"], 0.00)
    assert_invoice_dimensions(invoice, "ISSUED", "UNPAID", "RESOLVED")

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=OPEN_AFTER_CREDIT,
        disputed_receivable_usd=0.00,
        tier_pct=2.00,
        uncollectible_reserve_balance_usd=DISPUTED_RESERVE,
    )


def test_sweep_with_nothing_past_due_reports_zero_and_changes_nothing(
    api, admin_headers
):
    """A sweep run a month before the due instant moves no row at all.

    PRD 3.9: "A `PlatformAdmin` runs it with no payload, and it walks every dispute whose `status` is `SUBMITTED`, `UNDER_REVIEW` or `ESCALATED` and whose `resolution_due_at` the logical clock has **reached or passed** — the comparison is inclusive, so a sweep at exactly the due instant deems the dispute allowed, which is precisely the boundary the resolve operation excludes."
    PRD 3.9: "`filed_at` is stamped from the logical clock and `resolution_due_at` is `filed_at` plus `sla_days` days."
    PRD 3.9: "The sweep reports `swept_count`, the number of disputes it moved, and `total_credited_usd`, the total credit it granted."

    Design: Corner/endpoints/sweep_with_nothing_past_due_reports_zero_and_changes_nothing
    """
    state = setup_dispute(api)

    summary_data = validate_success(
        api.run_dispute_deadline_sweep({}, admin_headers), expected_status=201
    )
    assert summary_data["swept_count"] == 0
    assert_money(summary_data["total_credited_usd"], 0.00)

    dispute = read_dispute(api, state["dispute_id"])
    assert dispute["status"] == "SUBMITTED"
    assert_money(dispute["credited_amount_usd"], 0.00)
    assert dispute["resolved_by_user_id"] is None
    assert dispute["resolution_due_at"] == T_2026_10_01
    assert dispute["sla_days"] == 30

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["dispute_status"] == "DISPUTED"
    assert_money(invoice["disputed_amount_usd"], DISPUTED)

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], DISPUTED)
    assert_money(carrier["uncollectible_reserve_balance_usd"], DISPUTED_RESERVE)


def _deny(api, state, officer_headers):
    """Take the dispute under review and deny it, returning the denied row."""
    validate_success(
        api.acknowledge_dispute(state["dispute_id"], {}, officer_headers),
        expected_status=200,
    )
    return validate_success(
        api.resolve_dispute(
            state["dispute_id"], resolve_denied_payload(), officer_headers
        ),
        expected_status=200,
    )


def _escalate(api, state):
    """Escalate the denied dispute as the counterparty's representative."""
    return validate_success(
        api.escalate_dispute(
            state["dispute_id"], escalate_dispute_payload(), state["rep_headers"]
        ),
        expected_status=200,
    )


def test_third_escalation_exceeds_the_escalation_limit(api, officer_headers):
    """Two escalations are the cap, so the third round is refused.

    PRD 3.9: "Escalations are capped at **two**: the round the escalation would create, which is the dispute's current `escalation_round` plus one, must be no greater than two, and an attempt beyond that is refused with `ERR_ESCALATION_LIMIT_REACHED`."
    PRD 3.9: "Escalation increments `escalation_round` by 1 and extends `resolution_due_at` by **fifteen days from its previous due instant**, not from the current clock."
    PRD 3.9: "A **denied** dispute moves `UNDER_REVIEW → RESOLVED_DENIED`. Its `resolved_at` and `resolved_by_user_id` are likewise stamped and no credit is posted; the invoice's `disputed_amount_usd` is reduced by the dispute's `disputed_amount_usd` and its `dispute_status` moves `DISPUTED → RESOLVED`; and a `DISPUTE_RELEASE` reserve ledger entry is appended for the released provision."

    Design: Corner/errors/third_escalation_exceeds_the_escalation_limit
    """
    state = setup_dispute(api)
    _deny(api, state, officer_headers)
    first = _escalate(api, state)
    assert first["escalation_round"] == 1
    _deny(api, state, officer_headers)
    second = _escalate(api, state)
    assert second["escalation_round"] == 2
    assert second["resolution_due_at"] == DUE_AFTER_TWO_ESCALATIONS
    _deny(api, state, officer_headers)

    response = api.escalate_dispute(
        state["dispute_id"],
        escalate_dispute_payload(
            escalation_note="Third escalation to the regulatory affairs committee"
        ),
        state["rep_headers"],
    )
    validate_error(response, ERR_ESCALATION_LIMIT_REACHED, expected_status=409)

    unchanged = read_dispute(api, state["dispute_id"])
    assert unchanged["escalation_round"] == 2
    assert unchanged["resolution_due_at"] == DUE_AFTER_TWO_ESCALATIONS
    assert unchanged["status"] == "RESOLVED_DENIED"
    assert_money(unchanged["credited_amount_usd"], 0.00)

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(
        invoice["disputed_amount_usd"],
        0.00,
        "disputed_amount_usd after the third denial and the refused escalation",
    )
    assert invoice["dispute_status"] == "RESOLVED"
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)
    assert_money(invoice["credited_amount_usd"], 0.00)


def test_resolving_a_dispute_at_its_due_instant_is_refused_to_the_officer(
    api, officer_headers
):
    """The officer's window is exclusive of the due instant the sweep owns.

    PRD 3.9: "**Resolution** is also the `DisputeResolutionOfficer`'s, may only be performed from `UNDER_REVIEW`, requires the logical clock to be **strictly before** `resolution_due_at` — at or after that instant the dispute can only be deemed allowed by the sweep, and a resolution attempt is refused with `ERR_DISPUTE_SLA_EXPIRED` — and requires the acting `X-User-ID` to differ from the invoice's `issued_by_user_id`."
    PRD 3.9: "Missing the SLA therefore deems the dispute allowed in the counterparty's favour, which is exactly why the due instant is an inclusive boundary for the sweep and an exclusive one for the officer."

    Design: Corner/errors/resolving_a_dispute_at_its_due_instant_is_refused_to_the_officer
    """
    state = setup_dispute(api, acknowledge=True)
    assert state["dispute"]["status"] == "UNDER_REVIEW"
    assert state["dispute"]["resolution_due_at"] == T_2026_10_01
    advance_clock(api, T_2026_10_01)

    response = api.resolve_dispute(
        state["dispute_id"],
        resolve_sustained_payload(
            DISPUTED, resolution_note="Rate element misapplied; full credit granted"
        ),
        officer_headers,
    )
    validate_error(response, ERR_DISPUTE_SLA_EXPIRED, expected_status=409)

    unchanged = read_dispute(api, state["dispute_id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert_money(unchanged["credited_amount_usd"], 0.00)
    assert unchanged["resolved_at"] is None

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)


def test_denied_dispute_with_a_positive_credit_is_refused(api, officer_headers):
    """A denial that grants money contradicts itself and is refused.

    PRD 3.9: "A `decision` of `SUSTAINED` requires `credited_amount_usd` to be greater than 0.00 and no greater than the dispute's `disputed_amount_usd`; a `decision` of `DENIED` requires `credited_amount_usd` to be exactly 0.00. Any other pairing is refused with `ERR_INVALID_CREDIT_AMOUNT`, and that decision-dependent ceiling is enforced as a fiscal rule rather than as a range check on the field."
    PRD 2.11: "Because the regulator requires disputed access revenue to be held in full until the dispute closes, the persisted `disputed_reserve_balance_usd` on the carrier equals the whole `disputed_receivable_usd`, and every reserve ledger entry in the `DISPUTED_REVENUE` bucket moves that regulatory figure."

    Design: Corner/errors/denied_dispute_with_a_positive_credit_is_refused
    """
    state = setup_dispute(api, acknowledge=True)

    response = api.resolve_dispute(
        state["dispute_id"],
        resolve_denied_payload(
            credited_amount_usd=5.00,
            resolution_note="Rate element was applied correctly; no credit is due",
        ),
        officer_headers,
    )
    validate_error(response, ERR_INVALID_CREDIT_AMOUNT, expected_status=422)

    unchanged = read_dispute(api, state["dispute_id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert_money(unchanged["credited_amount_usd"], 0.00)

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["dispute_status"] == "DISPUTED"
    assert_money(invoice["disputed_amount_usd"], DISPUTED)

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], DISPUTED)


def test_invoice_issuer_cannot_resolve_a_dispute_on_that_invoice(api, officer_headers):
    """The issuing identity is barred from resolving; another officer id is not.

    PRD 2.9: "The user whose `X-User-ID` was stamped into an invoice's `issued_by_user_id` at issuance may neither resolve a billing dispute filed against that invoice nor write that invoice's balance off, even while holding the `DisputeResolutionOfficer` or `RevenueAssuranceController` role that otherwise authorises the operation."
    PRD 2.9: "In both cases the acting `X-User-ID` must differ from the invoice's `issued_by_user_id`; when it does not, the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.9: "A **sustained** dispute moves `UNDER_REVIEW → RESOLVED_SUSTAINED`, which is terminal. Its `resolved_at` and `resolved_by_user_id` are stamped; the invoice's `credited_amount_usd` increases by the granted credit and its `open_balance_usd` falls by the same amount; the invoice's `disputed_amount_usd` is reduced by the dispute's `disputed_amount_usd` and its `dispute_status` moves `DISPUTED → RESOLVED` once no open dispute remains against it; the reserve recomputation re-runs and both a `DISPUTE_RELEASE` reserve ledger entry and an `UNCOLLECTIBLE_ADJUSTMENT` reserve ledger entry are appended, each with `source_event` `BILLING_DISPUTE_RESOLVED`; and if the credit drives `open_balance_usd` to 0.00 the invoice's `payment_status` auto-moves to `PAID`."

    Design: Corner/rbac/invoice_issuer_cannot_resolve_a_dispute_on_that_invoice
    """
    state = setup_dispute(api, acknowledge=True)
    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["issued_by_user_id"] == USER_ACCESS_BILLING_ANALYST

    payload = resolve_sustained_payload(
        DISPUTED, resolution_note="Rate element misapplied; full credit granted"
    )
    refused = api.resolve_dispute(
        state["dispute_id"],
        payload,
        dispute_resolution_officer_headers(USER_ACCESS_BILLING_ANALYST),
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    allowed = validate_success(
        api.resolve_dispute(state["dispute_id"], payload, officer_headers),
        expected_status=200,
    )
    assert allowed["status"] == "RESOLVED_SUSTAINED"
    assert_money(allowed["credited_amount_usd"], DISPUTED)
    assert allowed["resolved_by_user_id"] == USER_DISPUTE_RESOLUTION_OFFICER

    settled = read_invoice(api, state["invoice_id"])
    assert_money(settled["credited_amount_usd"], DISPUTED)
    assert_money(settled["open_balance_usd"], OPEN_AFTER_CREDIT)
    assert settled["dispute_status"] == "RESOLVED"

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=OPEN_AFTER_CREDIT,
        net_receivable_usd=OPEN_AFTER_CREDIT,
        tier_pct=2.00,
        uncollectible_reserve_balance_usd=DISPUTED_RESERVE,
    )


def test_dispute_filed_after_the_window_reports_the_closed_window_not_the_amount(api):
    """One day past the deadline the temporal refusal preempts the fiscal ceiling.

    PRD 3.9: "The logical clock must be at or before the invoice's `dispute_deadline_at` — a dispute filed at **exactly** the deadline instant is accepted, while one instant later is refused with `ERR_DISPUTE_WINDOW_CLOSED`."
    PRD 2.7: "Temporal window checks follow — first the four that carry HTTP 422 (tariff window ordering, measurement period ordering, usage period ordering and closure, the dispute filing window, and the committed due date), then the three that carry HTTP 409 (agreement effective date reached, dispute SLA not yet expired, invoice due date reached)."
    PRD 2.7: "Fiscal amount checks are always last: the empty-invoice refusal, the overpayment refusal, the dispute-amount ceiling and the credit-amount decision match."
    PRD 3.8: "Issuance stamps `issued_at` from the logical clock, sets `dispute_deadline_at` to that instant plus **90 days** (the dispute filing window), and records the acting `X-User-ID` in `issued_by_user_id`, which is the anchor for the segregation-of-duties rule of §2.9."

    Design: Difficulty/priority_pair_validation_conflict/closed_dispute_window_temporal_beats_fiscal_amount_error
    """
    state = setup_issued_invoice(api)
    assert state["invoice"]["dispute_deadline_at"] == T_2026_11_30
    advance_clock(api, T_2026_12_01)

    response = api.create_dispute(
        dispute_payload(
            state["invoice_id"],
            disputed_amount_usd=OVERSIZED_DISPUTE,
            reason_code="USAGE_DISCREPANCY",
            supporting_detail="Full period disputed after the filing window closed",
        ),
        state["rep_headers"],
    )
    validate_error(response, ERR_DISPUTE_WINDOW_CLOSED, expected_status=422)

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["dispute_status"] == "NONE"
    assert_money(invoice["disputed_amount_usd"], 0.00)
    assert invoice["dispute_deadline_at"] == T_2026_11_30

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], 0.00)
    assert_money(carrier["net_receivable_usd"], RATED_TOTAL_PRELIMINARY)


def test_dispute_filed_at_the_deadline_instant_reaches_the_fiscal_ceiling(api):
    """At exactly the deadline the window passes and the oversized amount is the fault.

    PRD 3.9: "The logical clock must be at or before the invoice's `dispute_deadline_at` — a dispute filed at **exactly** the deadline instant is accepted, while one instant later is refused with `ERR_DISPUTE_WINDOW_CLOSED`."
    PRD 3.9: "And the amount must fit inside the undisputed part of the balance: `disputed_amount_usd` must be no greater than the invoice's `open_balance_usd` less its current `disputed_amount_usd`, with an excess refused as `ERR_DISPUTE_AMOUNT_EXCEEDS_BALANCE`."
    PRD 2.11: "The **GAAP basis** reserves only the probable loss: `disputed_receivable_usd` multiplied by 60.00 percent (the dispute loss probability), rounded half up to two decimal places."

    Design: Difficulty/priority_pair_validation_conflict/closed_dispute_window_temporal_beats_fiscal_amount_error
    """
    state = setup_issued_invoice(api)
    advance_clock(api, T_2026_11_30)

    oversized = api.create_dispute(
        dispute_payload(
            state["invoice_id"],
            disputed_amount_usd=OVERSIZED_DISPUTE,
            reason_code="USAGE_DISCREPANCY",
            supporting_detail="Full period disputed on the last day of the window",
        ),
        state["rep_headers"],
    )
    validate_error(oversized, ERR_DISPUTE_AMOUNT_EXCEEDS_BALANCE, expected_status=422)

    accepted = validate_success(
        api.create_dispute(
            dispute_payload(
                state["invoice_id"], disputed_amount_usd=FULL_BALANCE_DISPUTE
            ),
            state["rep_headers"],
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert_money(accepted["disputed_amount_usd"], FULL_BALANCE_DISPUTE)

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["dispute_status"] == "DISPUTED"
    assert_money(invoice["disputed_amount_usd"], FULL_BALANCE_DISPUTE)

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=RATED_TOTAL_PRELIMINARY,
        disputed_receivable_usd=FULL_BALANCE_DISPUTE,
        net_receivable_usd=0.00,
        tier_pct=0.00,
        uncollectible_reserve_balance_usd=0.00,
        regulatory_disputed_reserve_usd=FULL_BALANCE_DISPUTE,
        gaap_disputed_reserve_usd=19.48,
        disputed_reserve_basis_delta_usd=12.99,
    )


def _signed_sum(entries):
    """The signed sum of a bucket's ledger amounts, at two decimals."""
    return round(sum(float(entry["amount_usd"]) for entry in entries), 2)


def test_dispute_withdrawal_returns_the_disputed_reserve_to_zero(api):
    """Withdrawal releases exactly the provision the filing booked, with no drift.

    PRD 3.9: "All three source states behave identically: `resolved_at` and `resolved_by_user_id` are stamped, `credited_amount_usd` stays 0.00, the invoice's `disputed_amount_usd` is reduced by the dispute's `disputed_amount_usd` and its `dispute_status` moves `DISPUTED → RESOLVED`, and a `DISPUTE_RELEASE` reserve ledger entry with `source_event` `BILLING_DISPUTE_WITHDRAWN` is appended that **exactly offsets every `DISPUTE_PROVISION` entry booked for this dispute** — including the escalation provision when withdrawal happens from `ESCALATED` — plus an `UNCOLLECTIBLE_ADJUSTMENT` entry restoring the pre-dispute uncollectible balance."
    PRD 3.9: "After withdrawal the carrier's `disputed_reserve_balance_usd` returns to its pre-dispute value with no drift."
    PRD 2.11: "Because entries are never rewritten, the last entry in a bucket's history always carries that bucket's current `balance_after_usd`, and the entries between any two points sum exactly to the difference between their balances."

    Design: Difficulty/compensating_invariant/dispute_withdrawal_returns_the_disputed_reserve_to_zero
    """
    state = setup_dispute(api, acknowledge=True)

    withdrawn = validate_success(
        api.withdraw_dispute(
            state["dispute_id"],
            withdraw_dispute_payload(
                withdrawal_reason="Carrier re-ran its own signaling sample and accepts the jurisdiction"
            ),
            state["rep_headers"],
        ),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert_money(withdrawn["credited_amount_usd"], 0.00)

    invoice = read_invoice(api, state["invoice_id"])
    assert invoice["dispute_status"] == "RESOLVED"
    assert_money(invoice["disputed_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)

    disputed_entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_DISPUTED
    )
    assert len(disputed_entries) == 2
    assert_ledger_entry(
        disputed_entries[0],
        entry_type="DISPUTE_PROVISION",
        source_event="BILLING_DISPUTE_SUBMITTED",
        amount_usd=DISPUTED,
        balance_after_usd=DISPUTED,
        reserve_bucket=RESERVE_BUCKET_DISPUTED,
    )
    assert_ledger_entry(
        disputed_entries[1],
        entry_type="DISPUTE_RELEASE",
        source_event="BILLING_DISPUTE_WITHDRAWN",
        amount_usd=-DISPUTED,
        balance_after_usd=0.00,
        reserve_bucket=RESERVE_BUCKET_DISPUTED,
    )

    carrier = read_carrier(api, state["carrier_id"])
    assert _signed_sum(disputed_entries) == 0.00
    assert_money(carrier["disputed_reserve_balance_usd"], 0.00)

    uncollectible_entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert len(uncollectible_entries) == 3
    assert_ledger_entry(
        uncollectible_entries[0],
        source_event="INVOICE_CREATED",
        amount_usd=ISSUE_RESERVE,
        balance_after_usd=ISSUE_RESERVE,
    )
    assert_ledger_entry(
        uncollectible_entries[1],
        entry_type="UNCOLLECTIBLE_ADJUSTMENT",
        source_event="BILLING_DISPUTE_SUBMITTED",
        amount_usd=-1.17,
        balance_after_usd=DISPUTED_RESERVE,
    )
    assert_ledger_entry(
        uncollectible_entries[2],
        entry_type="UNCOLLECTIBLE_ADJUSTMENT",
        source_event="BILLING_DISPUTE_WITHDRAWN",
        amount_usd=1.17,
        balance_after_usd=ISSUE_RESERVE,
    )
    assert _signed_sum(uncollectible_entries) == ISSUE_RESERVE
    assert_money(carrier["uncollectible_reserve_balance_usd"], ISSUE_RESERVE)

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        net_receivable_usd=RATED_TOTAL_PRELIMINARY,
        tier_pct=5.00,
        regulatory_disputed_reserve_usd=0.00,
        gaap_disputed_reserve_usd=0.00,
        disputed_reserve_basis_delta_usd=0.00,
    )


def test_withdrawal_from_escalated_offsets_both_provisions_that_were_booked(
    api, officer_headers
):
    """Across the denial-and-escalation loop the same provision nets back to zero.

    PRD 3.9: "It also returns the dispute to the open set: the invoice's `disputed_amount_usd` increases again by the dispute's `disputed_amount_usd`, the invoice's `dispute_status` moves `RESOLVED → DISPUTED`, and a `DISPUTE_PROVISION` reserve ledger entry with `source_event` `BILLING_DISPUTE_ESCALATED` is appended."
    PRD 3.9: "All three source states behave identically: `resolved_at` and `resolved_by_user_id` are stamped, `credited_amount_usd` stays 0.00, the invoice's `disputed_amount_usd` is reduced by the dispute's `disputed_amount_usd` and its `dispute_status` moves `DISPUTED → RESOLVED`, and a `DISPUTE_RELEASE` reserve ledger entry with `source_event` `BILLING_DISPUTE_WITHDRAWN` is appended that **exactly offsets every `DISPUTE_PROVISION` entry booked for this dispute** — including the escalation provision when withdrawal happens from `ESCALATED` — plus an `UNCOLLECTIBLE_ADJUSTMENT` entry restoring the pre-dispute uncollectible balance."
    PRD 2.10: "Withdrawing a billing dispute releases precisely the reserve provisions that dispute booked, with no residual drift."

    Design: Difficulty/compensating_invariant/dispute_withdrawal_returns_the_disputed_reserve_to_zero
    """
    state = setup_dispute(api)
    _deny(api, state, officer_headers)
    escalated = _escalate(api, state)
    assert escalated["status"] == "ESCALATED"
    assert read_invoice(api, state["invoice_id"])["dispute_status"] == "DISPUTED"

    withdrawn = validate_success(
        api.withdraw_dispute(
            state["dispute_id"], withdraw_dispute_payload(), state["rep_headers"]
        ),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert_money(withdrawn["credited_amount_usd"], 0.00)

    invoice = read_invoice(api, state["invoice_id"])
    assert_invoice_dimensions(invoice, "ISSUED", "UNPAID", "RESOLVED")
    assert_money(invoice["disputed_amount_usd"], 0.00)
    assert_money(invoice["credited_amount_usd"], 0.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)

    disputed_entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_DISPUTED
    )
    assert len(disputed_entries) == 4
    assert_ledger_entry(
        disputed_entries[0],
        entry_type="DISPUTE_PROVISION",
        source_event="BILLING_DISPUTE_SUBMITTED",
        amount_usd=DISPUTED,
        balance_after_usd=DISPUTED,
    )
    assert_ledger_entry(
        disputed_entries[1],
        entry_type="DISPUTE_RELEASE",
        source_event="BILLING_DISPUTE_RESOLVED",
        amount_usd=-DISPUTED,
        balance_after_usd=0.00,
    )
    assert_ledger_entry(
        disputed_entries[2],
        entry_type="DISPUTE_PROVISION",
        source_event="BILLING_DISPUTE_ESCALATED",
        amount_usd=DISPUTED,
        balance_after_usd=DISPUTED,
    )
    assert_ledger_entry(
        disputed_entries[3],
        entry_type="DISPUTE_RELEASE",
        source_event="BILLING_DISPUTE_WITHDRAWN",
        amount_usd=-DISPUTED,
        balance_after_usd=0.00,
    )
    assert _signed_sum(disputed_entries) == 0.00

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], 0.00)
    assert_money(carrier["uncollectible_reserve_balance_usd"], ISSUE_RESERVE)

    uncollectible_entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert_money(uncollectible_entries[-1]["balance_after_usd"], ISSUE_RESERVE)
    assert _signed_sum(uncollectible_entries) == ISSUE_RESERVE

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        net_receivable_usd=RATED_TOTAL_PRELIMINARY,
        tier_pct=5.00,
        regulatory_disputed_reserve_usd=0.00,
        gaap_disputed_reserve_usd=0.00,
        disputed_reserve_basis_delta_usd=0.00,
    )
