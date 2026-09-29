"""Reversals that must restore a derived total to its exact prior value."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_decimal2
from test_helpers.fixtures import issue_invoice
from test_helpers.test_users import (
    ADMIN_BILLING_HEADERS,
    ADMIN_HQ_HEADERS,
    make_club_headers,
)
from test_helpers.types import BookingAction, InvoiceAction


# ---------------------------------------------------------------------------
# REVOKE_APPROVAL returns the club-week case pool to its pre-approval total
# ---------------------------------------------------------------------------
def test_revoking_an_approval_returns_the_club_week_pool_to_its_prior_total(
    api, pool_revocation_setup
):
    """PRD §3.3: "Revocation is a full compensation and touches six things. It
    resets `pool_cases_used`, `reserve_cases_used` and `allocated_sample_cases` to
    zero, which restores the club-week pool remaining to exactly its pre-approval
    value." It also clears `approved_at` back to unset.

    Design: Difficulty/compensating_invariant/revoking_approval_returns_the_club_week_case_pool_to_its_exact_prior_total
    """
    club_id = pool_revocation_setup["club"]["id"]
    club_headers = make_club_headers(club_id)
    product_id = pool_revocation_setup["product"]["id"]
    monday = pool_revocation_setup["monday_event"]
    before = pool_revocation_setup["capacity_before"]

    assert before["week_start_date"] == "2026-09-14"
    assert monday["allocated_sample_cases"] == 6
    assert monday["pool_cases_used"] == 6
    assert monday["reserve_cases_used"] == 0
    assert before["pool_cases_used"] == 6
    assert before["pool_remaining"] == 4

    revoked = validate_success(
        api.demo_event_transition(
            monday["id"],
            {
                "action": BookingAction.REVOKE_APPROVAL,
                "reason": "manufacturer deferred the date",
            },
            club_headers,
        )
    )
    restored = validate_success(
        api.get_club_capacity(club_id, club_headers, "2026-09-14", product_id)
    )

    assert revoked["booking_status"] == "SUBMITTED"
    assert revoked["allocated_sample_cases"] == 0
    assert revoked["pool_cases_used"] == 0
    assert revoked["approved_at"] is None
    assert restored["pool_cases_used"] == 0
    assert restored["pool_remaining"] == 10


def test_released_cases_are_available_to_the_next_event_and_not_to_both(
    api, pool_revocation_setup
):
    """PRD §3.3: "Note that only events in `CONFIRMED` or `COMPLETED` consume the
    pool at all: draft, submitted and cancelled events consume nothing, which is
    precisely what makes revocation and cancellation exact compensations." The
    allocation waterfall of §3.3 must yield at least 1 case — otherwise
    `ERR_SAMPLE_POOL_EXHAUSTED` (409).

    Design: Difficulty/compensating_invariant/revoking_approval_returns_the_club_week_case_pool_to_its_exact_prior_total
    """
    club_id = pool_revocation_setup["club"]["id"]
    club_headers = make_club_headers(club_id)
    monday_id = pool_revocation_setup["monday_event"]["id"]
    wednesday_id = pool_revocation_setup["wednesday_event_id"]

    validate_success(
        api.demo_event_transition(
            monday_id,
            {
                "action": BookingAction.REVOKE_APPROVAL,
                "reason": "manufacturer deferred the date",
            },
            club_headers,
        )
    )
    wednesday = validate_success(
        api.demo_event_transition(
            wednesday_id, {"action": BookingAction.APPROVE}, club_headers
        )
    )
    assert wednesday["allocated_sample_cases"] == 10
    assert wednesday["pool_cases_used"] == 10

    # §3.3: revoking an approval already returned the Monday booking to
    # SUBMITTED, so it is directly re-approvable without a second submission.
    validate_error(
        api.demo_event_transition(
            monday_id, {"action": BookingAction.APPROVE}, club_headers
        ),
        ApiErrorId.SAMPLE_POOL_EXHAUSTED,
        409,
    )

    monday = validate_success(api.get_demo_event(monday_id, club_headers))
    assert monday["booking_status"] == "SUBMITTED"
    assert monday["allocated_sample_cases"] == 0


# ---------------------------------------------------------------------------
# VOID returns the receivable to its exact pre-issue integer
# ---------------------------------------------------------------------------
def test_issuing_the_invoice_pushes_the_receivable_past_the_credit_limit(
    api, void_receivable_invoice
):
    """PRD §3.9: "A vendor's `outstanding_balance_cents` is the sum of
    `total_due_cents` over that vendor's invoices whose `invoice_status` is
    `ISSUED`; invoices in `DRAFT`, `VOID` and `PAID` contribute exactly zero, and
    invoices of other vendors never contribute." Both sums are computed first, and
    only then are the automatic account transitions evaluated: exposure strictly
    above `credit_limit_cents` while the account is `ACTIVE` moves it to `HOLD`.

    Design: Difficulty/compensating_invariant/voiding_an_issued_invoice_returns_the_receivable_to_zero_and_clears_the_hold
    """
    invoice = void_receivable_invoice["invoice"]
    vendor_before = void_receivable_invoice["vendor_before"]

    assert_cents(invoice["subtotal_cents"], 51330, "subtotal_cents")
    assert_decimal2(invoice["volume_discount_pct"], 0.03, "volume_discount_pct")
    assert_cents(invoice["discount_cents"], 1540, "discount_cents")
    assert_cents(invoice["total_due_cents"], 49790, "total_due_cents")
    assert len(invoice["line_items"]) == 3
    assert_cents(
        vendor_before["outstanding_balance_cents"], 0, "outstanding_balance_cents"
    )
    assert vendor_before["account_status"] == "ACTIVE"

    issued = issue_invoice(api, invoice["id"])
    vendor = validate_success(
        api.get_manufacturer(
            void_receivable_invoice["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )

    assert issued["invoice_status"] == "ISSUED"
    assert_cents(
        vendor["outstanding_balance_cents"], 49790, "outstanding_balance_cents"
    )
    assert vendor["account_status"] == "HOLD"


def test_voiding_the_invoice_returns_the_receivable_to_its_pre_issue_integer(
    api, void_receivable_invoice
):
    """PRD §3.9: "It clears both `issued_by_user_id` and `issued_at` back to
    unset, recomputes `outstanding_balance_cents` — which by the conservation
    invariant of §2.9 returns to its exact pre-issue integer value — and, when the
    recomputed exposure is at or below `credit_limit_cents` while the account is on
    `HOLD`, automatically returns `account_status` to `ACTIVE`."

    Design: Difficulty/compensating_invariant/voiding_an_issued_invoice_returns_the_receivable_to_zero_and_clears_the_hold
    """
    invoice_id = void_receivable_invoice["invoice"]["id"]
    vendor_id = void_receivable_invoice["manufacturer"]["id"]
    outstanding_before = void_receivable_invoice["vendor_before"][
        "outstanding_balance_cents"
    ]

    issue_invoice(api, invoice_id)
    voided = validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.VOID}, ADMIN_BILLING_HEADERS
        )
    )
    vendor = validate_success(api.get_manufacturer(vendor_id, ADMIN_HQ_HEADERS))
    event = validate_success(
        api.get_demo_event(void_receivable_invoice["event_id"], ADMIN_HQ_HEADERS)
    )

    assert voided["invoice_status"] == "VOID"
    assert voided["issued_by_user_id"] is None
    assert voided["issued_at"] is None
    assert_cents(voided["total_due_cents"], 49790, "total_due_cents")
    assert_cents(
        vendor["outstanding_balance_cents"], 0, "outstanding_balance_cents"
    )
    assert vendor["outstanding_balance_cents"] == outstanding_before
    assert vendor["account_status"] == "ACTIVE"
    assert event["settlement_status"] == "UNBILLED"


def test_the_punctual_lead_shift_that_priced_the_voided_invoice(
    api, void_receivable_invoice
):
    """PRD §3.6: "A successful check-in writes the recorded instant to
    `check_in_at` and then sets `late_check_in` to true when that instant falls
    strictly after 10 minutes past `scheduled_start_utc`, and to false otherwise —
    the ten-minute grace period is what separates a punctual arrival from a late
    one, and a late completion later costs the worker reliability points."
    Check-out then fixes the money: "`billable_hours` is the greater of
    `hours_worked` and a four-hour minimum, so a worker who is on site for two and
    a quarter hours still bills 4.00 hours; `billable_hours` reads 0.00 until the
    assignment actually reaches `COMPLETED`."

    Design: Difficulty/compensating_invariant/voiding_an_issued_invoice_returns_the_receivable_to_zero_and_clears_the_hold
    """
    assignment = validate_success(
        api.get_assignment(void_receivable_invoice["assignment_id"], ADMIN_HQ_HEADERS)
    )

    assert assignment["late_check_in"] is False
    assert_decimal2(assignment["billable_hours"], 4.50, "billable_hours")
    assert (
        void_receivable_invoice["reconciliation"]["recon_status"] == "BALANCED"
    )
