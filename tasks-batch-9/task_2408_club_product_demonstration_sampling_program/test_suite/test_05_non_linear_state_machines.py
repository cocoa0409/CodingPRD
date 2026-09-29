"""Cyclic state machines: the coverage dimension and the invoice void cycle."""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_cents, assert_decimal2, assert_event_dimensions
from test_helpers.fixtures import (
    assign,
    credits_for_event,
    declare_no_show,
    issue_invoice,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_BILLING_HEADERS,
    ADMIN_BILLING_USER_ID,
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
)
from test_helpers.types import AssignmentRole, InvoiceAction


# ---------------------------------------------------------------------------
# UNSTAFFED -> PARTIALLY_STAFFED -> FULLY_STAFFED -> PARTIALLY_STAFFED -> FULLY_STAFFED
# ---------------------------------------------------------------------------
@pytest.fixture
def staffing_walk(api, two_dimension_event):
    """Walks the coverage dimension of one confirmed event forward twice and
    backward once, recording the event after every step."""
    event_id = two_dimension_event["event_id"]

    lead_asg = assign(
        api, event_id, two_dimension_event["lead"]["id"], AssignmentRole.LEAD
    )
    after_lead = validate_success(api.get_demo_event(event_id, STAFF_OPS_HEADERS))

    first_support = assign(
        api, event_id, two_dimension_event["support_one"]["id"], AssignmentRole.SUPPORT
    )
    after_first_support = validate_success(
        api.get_demo_event(event_id, STAFF_OPS_HEADERS)
    )

    set_clock(api, "2026-09-14T11:35:00Z")
    declare_no_show(api, first_support["id"])
    after_no_show = validate_success(api.get_demo_event(event_id, STAFF_OPS_HEADERS))

    replacement = assign(
        api,
        event_id,
        two_dimension_event["support_two"]["id"],
        AssignmentRole.SUPPORT,
        replaces_assignment_id=first_support["id"],
    )
    after_replacement = validate_success(
        api.get_demo_event(event_id, STAFF_OPS_HEADERS)
    )

    return {
        **two_dimension_event,
        "lead_assignment": lead_asg,
        "first_support_assignment": first_support,
        "replacement_assignment": replacement,
        "after_lead": after_lead,
        "after_first_support": after_first_support,
        "after_no_show": after_no_show,
        "after_replacement": after_replacement,
    }


def test_coverage_advances_while_the_booking_dimension_stands_still(api, staffing_walk):
    """PRD §2.9: "`booking_status` is the commercial dimension, moving through
    `DRAFT`, `SUBMITTED`, `CONFIRMED`, and then either `COMPLETED` or
    `CANCELLED`; it is advanced only by the event's own transition action.
    `staffing_status` is the coverage dimension, moving through `UNSTAFFED`,
    `PARTIALLY_STAFFED`, `FULLY_STAFFED`, `EXECUTED` and `CLOSED_OUT`; it is
    advanced by assignment inserts, by assignment transitions, and by
    close-out."

    Design: Difficulty/non_linear_state_machine/booking_and_staffing_dimensions_advance_independently_through_a_staffing_cycle
    """
    assert_event_dimensions(
        staffing_walk["after_lead"],
        booking_status="CONFIRMED",
        staffing_status="PARTIALLY_STAFFED",
    )
    assert_event_dimensions(
        staffing_walk["after_first_support"],
        booking_status="CONFIRMED",
        staffing_status="FULLY_STAFFED",
    )
    assert staffing_walk["after_first_support"]["required_support_count"] == 1
    assert staffing_walk["after_first_support"]["allocated_sample_cases"] == 6


def test_no_show_downgrade_opens_recovery_and_mints_a_credit(api, staffing_walk):
    """PRD §3.6: "Alongside those four hops, the no-show downgrades *this*
    event's `staffing_status` and sets its `no_show_recovery_open` to true,
    creates one cancellation credit on this event with `credit_reason`
    `DEMONSTRATOR_NO_SHOW` and `credit_status` `PENDING_APPROVAL`, valued by the
    arithmetic of §3.9, and increments the assignment's `version` by 1."

    Design: Difficulty/non_linear_state_machine/booking_and_staffing_dimensions_advance_independently_through_a_staffing_cycle
    """
    assert_event_dimensions(
        staffing_walk["after_no_show"],
        booking_status="CONFIRMED",
        staffing_status="PARTIALLY_STAFFED",
    )
    assert staffing_walk["after_no_show"]["no_show_recovery_open"] is True

    credits = credits_for_event(api, staffing_walk["event_id"])
    assert len(credits) == 1
    assert credits[0]["credit_reason"] == "DEMONSTRATOR_NO_SHOW"
    assert_cents(credits[0]["credit_amount_cents"], 33810, "credit_amount_cents")
    assert credits[0]["credit_status"] == "PENDING_APPROVAL"

    worker = validate_success(
        api.get_demonstrator(staffing_walk["support_one"]["id"], STAFF_OPS_HEADERS)
    )
    assert worker["no_show_strike_count"] == 1
    assert worker["employment_status"] == "ACTIVE"


def test_replacement_assignment_re_enters_fully_staffed_and_closes_recovery(
    api, staffing_walk
):
    """PRD §3.4: "From `PARTIALLY_STAFFED`, the same fully-covered recomputation
    moves coverage to `FULLY_STAFFED` and likewise sets `no_show_recovery_open`
    to false — this is the step that closes the revision cycle a no-show or a
    release opened." The shift the assignment occupies is derived, not supplied:
    `scheduled_start_utc` is the event's `event_window_start_utc` less 45 minutes
    of setup lead, and `scheduled_end_utc` is the event's `event_window_end_utc`
    plus 75 minutes of teardown.

    Design: Difficulty/non_linear_state_machine/booking_and_staffing_dimensions_advance_independently_through_a_staffing_cycle
    """
    final_event = staffing_walk["after_replacement"]
    assert_event_dimensions(
        final_event, booking_status="CONFIRMED", staffing_status="FULLY_STAFFED"
    )
    assert final_event["no_show_recovery_open"] is False

    replacement = validate_success(
        api.get_assignment(
            staffing_walk["replacement_assignment"]["id"], STAFF_OPS_HEADERS
        )
    )
    failed = validate_success(
        api.get_assignment(
            staffing_walk["first_support_assignment"]["id"], STAFF_OPS_HEADERS
        )
    )
    lead = validate_success(
        api.get_assignment(staffing_walk["lead_assignment"]["id"], STAFF_OPS_HEADERS)
    )

    assert failed["assignment_status"] == "NO_SHOW"
    assert replacement["assignment_status"] == "ASSIGNED"
    assert replacement["replaces_assignment_id"] == failed["id"]
    assert lead["assignment_status"] == "ASSIGNED"
    assert replacement["scheduled_start_utc"].startswith("2026-09-14T11:15:00")
    assert replacement["scheduled_end_utc"].startswith("2026-09-14T17:15:00")


# ---------------------------------------------------------------------------
# DRAFT -> ISSUED -> VOID -> DRAFT -> ISSUED on one invoice row
# ---------------------------------------------------------------------------
def test_first_issue_bills_the_rates_in_force_at_that_moment(
    api, void_redraft_invoice
):
    """PRD §3.9: "Issuance stamps `issued_by_user_id` with the acting
    `X-User-ID` and `issued_at` with the logical clock's current instant." The
    event's `settlement_status` is recomputed to `INVOICED` and the event's
    `version` increments by 1; the invoice's own `version` increments by 1.

    Design: Difficulty/non_linear_state_machine/invoice_void_redraft_reissue_cycle_recomputes_from_current_rates
    """
    issued = issue_invoice(api, void_redraft_invoice["invoice"]["id"])

    assert issued["invoice_status"] == "ISSUED"
    assert_cents(issued["total_due_cents"], 76591, "total_due_cents")
    assert issued["issued_by_user_id"] == ADMIN_BILLING_USER_ID
    assert issued["issued_at"] is not None

    event = validate_success(
        api.get_demo_event(void_redraft_invoice["event_id"], ADMIN_HQ_HEADERS)
    )
    assert event["settlement_status"] == "INVOICED"


def test_void_returns_the_invoice_to_an_unstamped_state(api, void_redraft_invoice):
    """PRD §3.9: "Voiding an issued invoice moves `invoice_status` from `ISSUED`
    to `VOID`. It clears both `issued_by_user_id` and `issued_at` back to unset,
    recomputes `outstanding_balance_cents` — which by the conservation invariant
    of §2.9 returns to its exact pre-issue integer value — and, when the
    recomputed exposure is at or below `credit_limit_cents` while the account is
    on `HOLD`, automatically returns `account_status` to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/invoice_void_redraft_reissue_cycle_recomputes_from_current_rates
    """
    invoice_id = void_redraft_invoice["invoice"]["id"]
    issue_invoice(api, invoice_id)
    voided = validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.VOID}, ADMIN_BILLING_HEADERS
        )
    )

    assert voided["invoice_status"] == "VOID"
    assert voided["issued_by_user_id"] is None
    assert voided["issued_at"] is None

    event = validate_success(
        api.get_demo_event(void_redraft_invoice["event_id"], ADMIN_HQ_HEADERS)
    )
    assert event["settlement_status"] == "UNBILLED"


def test_redraft_recomputes_the_whole_line_set_from_current_data(
    api, void_redraft_invoice
):
    """PRD §3.9: "Redrafting moves `invoice_status` from `VOID` back to `DRAFT`
    and rebuilds the invoice against current data. It re-runs the whole line-item
    computation and overwrites every `line_items` entry along with
    `base_fee_cents`, `addon_fee_cents`, `staffing_fee_cents`,
    `sample_handling_fee_cents`, `subtotal_cents`,
    `monthly_completed_event_count`, `volume_discount_pct`, `discount_cents` and
    `total_due_cents`."

    Design: Difficulty/non_linear_state_machine/invoice_void_redraft_reissue_cycle_recomputes_from_current_rates
    """
    invoice_id = void_redraft_invoice["invoice"]["id"]
    first_issue = issue_invoice(api, invoice_id)
    validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.VOID}, ADMIN_BILLING_HEADERS
        )
    )
    validate_success(
        api.update_demonstrator(
            void_redraft_invoice["lead"]["id"], {"hourly_rate_cents": 3000}, STAFF_OPS_HEADERS
        )
    )
    redrafted = validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.REDRAFT}, ADMIN_BILLING_HEADERS
        )
    )

    assert redrafted["invoice_status"] == "DRAFT"
    assert_cents(first_issue["total_due_cents"], 76591, "first issue total_due_cents")
    assert_cents(redrafted["total_due_cents"], 79734, "redrafted total_due_cents")
    assert_cents(redrafted["base_fee_cents"], 48300, "base_fee_cents")
    assert_cents(redrafted["addon_fee_cents"], 2200, "addon_fee_cents")
    assert_cents(redrafted["staffing_fee_cents"], 24200, "staffing_fee_cents")
    assert_cents(
        redrafted["sample_handling_fee_cents"], 7500, "sample_handling_fee_cents"
    )
    assert_cents(redrafted["subtotal_cents"], 82200, "subtotal_cents")
    assert_decimal2(redrafted["volume_discount_pct"], 0.03, "volume_discount_pct")
    assert_cents(redrafted["discount_cents"], 2466, "discount_cents")
    assert len(redrafted["line_items"]) == 6


def test_reissue_after_redraft_posts_the_new_total_to_the_receivable(
    api, void_redraft_invoice
):
    """PRD §3.9: "Because `VOID` re-enters `DRAFT`, the cycle `DRAFT → ISSUED →
    VOID → DRAFT → ISSUED` is legal and may repeat without limit." A vendor's
    `outstanding_balance_cents` is the sum of `total_due_cents` over that
    vendor's invoices whose `invoice_status` is `ISSUED`; invoices in `DRAFT`,
    `VOID` and `PAID` contribute exactly zero, and invoices of other vendors
    never contribute.

    Design: Difficulty/non_linear_state_machine/invoice_void_redraft_reissue_cycle_recomputes_from_current_rates
    """
    invoice_id = void_redraft_invoice["invoice"]["id"]
    issue_invoice(api, invoice_id)
    validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.VOID}, ADMIN_BILLING_HEADERS
        )
    )
    validate_success(
        api.update_demonstrator(
            void_redraft_invoice["lead"]["id"], {"hourly_rate_cents": 3000}, STAFF_OPS_HEADERS
        )
    )
    validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.REDRAFT}, ADMIN_BILLING_HEADERS
        )
    )
    reissued = issue_invoice(api, invoice_id)

    assert reissued["invoice_status"] == "ISSUED"
    assert_cents(reissued["total_due_cents"], 79734, "total_due_cents")
    assert reissued["issued_by_user_id"] == ADMIN_BILLING_USER_ID

    vendor = validate_success(
        api.get_manufacturer(
            void_redraft_invoice["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )
    event = validate_success(
        api.get_demo_event(void_redraft_invoice["event_id"], ADMIN_HQ_HEADERS)
    )
    assert_cents(
        vendor["outstanding_balance_cents"], 79734, "outstanding_balance_cents"
    )
    assert vendor["account_status"] == "ACTIVE"
    assert event["settlement_status"] == "INVOICED"


def test_billable_hours_apply_the_four_hour_floor_only_where_needed(
    api, void_redraft_invoice
):
    """PRD §3.6: "`billable_hours` is the greater of `hours_worked` and a
    four-hour minimum, so a worker who is on site for two and a quarter hours
    still bills 4.00 hours; `billable_hours` reads 0.00 until the assignment
    actually reaches `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/invoice_void_redraft_reissue_cycle_recomputes_from_current_rates
    """
    lead = validate_success(
        api.get_assignment(void_redraft_invoice["lead_assignment_id"], STAFF_OPS_HEADERS)
    )
    support = validate_success(
        api.get_assignment(
            void_redraft_invoice["support_assignment_id"], STAFF_OPS_HEADERS
        )
    )

    assert_decimal2(lead["billable_hours"], 4.50, "lead billable_hours")
    assert_decimal2(support["hours_worked"], 3.00, "support hours_worked")
    assert_decimal2(support["billable_hours"], 4.00, "support billable_hours")
    assert void_redraft_invoice["reconciliation"]["recon_status"] == "BALANCED"
