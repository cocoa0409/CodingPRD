"""Multi-hop cascades that reach entities the request never named."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_decimal2
from test_helpers.fixtures import (
    credits_for_event,
    declare_no_show,
    issue_invoice,
    read_reconciliation,
)
from test_helpers.test_users import (
    ADMIN_BILLING_HEADERS,
    ADMIN_BILLING_USER_ID,
    ADMIN_CONTROLLER_HEADERS,
    ADMIN_CONTROLLER_USER_ID,
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
)
from test_helpers.types import CreditDecision


# ---------------------------------------------------------------------------
# One no-show -> strike 3 -> ON_LEAVE -> a second event loses its staffing
# ---------------------------------------------------------------------------
@pytest.fixture
def third_strike_declared(api, third_strike_state):
    """Declares the third no-show, which is the only request made."""
    declare_no_show(api, third_strike_state["first_assignment_id"], note="third strike")
    return third_strike_state


def test_third_no_show_stands_the_worker_down_automatically(api, third_strike_declared):
    """PRD §3.4: "The second hop, caused by the first, is the automatic
    stand-down: when the recomputed `no_show_strike_count` has reached 3 or more
    and the worker's `employment_status` is still `ACTIVE`, that
    `employment_status` is set to `ON_LEAVE`." The first hop recomputes the
    worker's `no_show_strike_count`, `reliability_score_rolling_90` and
    `reliability_score_program_to_date`.

    Design: Difficulty/transitive_cascade/third_strike_cascades_to_on_leave_then_releases_a_future_event_staffing
    """
    worker = validate_success(
        api.get_demonstrator(
            third_strike_declared["demonstrator"]["id"], STAFF_OPS_HEADERS
        )
    )

    assert worker["no_show_strike_count"] == 3
    assert worker["employment_status"] == "ON_LEAVE"
    assert_decimal2(
        worker["reliability_score_rolling_90"], 64.00, "reliability_score_rolling_90"
    )
    assert_decimal2(
        worker["reliability_score_program_to_date"],
        64.00,
        "reliability_score_program_to_date",
    )
    assert worker["completed_event_count"] == 0


def test_stand_down_releases_the_untouched_future_event_and_bumps_its_version(
    api, third_strike_declared
):
    """PRD §3.4: "The third hop, caused by the second, sweeps the worker's other
    commitments: every other assignment of that worker whose `assignment_status`
    is `ASSIGNED` or `CONFIRMED` and whose event's `event_date` falls on or after
    the logical clock's UTC date is set to `RELEASED`. The fourth hop, caused by
    the third, propagates to those other events: each of them recomputes its
    `staffing_status` downward — from `FULLY_STAFFED` to `PARTIALLY_STAFFED` or
    to `UNSTAFFED` as the remaining rows dictate — and increments its own
    `version`."

    Design: Difficulty/transitive_cascade/third_strike_cascades_to_on_leave_then_releases_a_future_event_staffing
    """
    before = third_strike_declared["second_event_before"]
    assert before["staffing_status"] == "FULLY_STAFFED"

    released = validate_success(
        api.get_assignment(
            third_strike_declared["second_assignment_id"], STAFF_OPS_HEADERS
        )
    )
    after = validate_success(
        api.get_demo_event(third_strike_declared["second_event_id"], STAFF_OPS_HEADERS)
    )

    assert released["assignment_status"] == "RELEASED"
    assert after["staffing_status"] == "UNSTAFFED"
    assert after["version"] == before["version"] + 1
    assert after["booking_status"] == "CONFIRMED"


def test_trigger_event_keeps_its_booking_but_loses_coverage_and_gains_a_credit(
    api, third_strike_declared
):
    """PRD §3.4: "Alongside those four hops, the no-show downgrades *this*
    event's `staffing_status` and sets its `no_show_recovery_open` to true,
    creates one cancellation credit on this event with `credit_reason`
    `DEMONSTRATOR_NO_SHOW` and `credit_status` `PENDING_APPROVAL`, valued by the
    arithmetic of §3.9, and increments the assignment's `version` by 1."

    Design: Difficulty/transitive_cascade/third_strike_cascades_to_on_leave_then_releases_a_future_event_staffing
    """
    first_event = validate_success(
        api.get_demo_event(third_strike_declared["first_event_id"], STAFF_OPS_HEADERS)
    )
    failed = validate_success(
        api.get_assignment(
            third_strike_declared["first_assignment_id"], STAFF_OPS_HEADERS
        )
    )

    assert failed["assignment_status"] == "NO_SHOW"
    assert first_event["staffing_status"] == "UNSTAFFED"
    assert first_event["no_show_recovery_open"] is True
    assert first_event["booking_status"] == "CONFIRMED"

    credits = credits_for_event(api, third_strike_declared["first_event_id"])
    assert len(credits) == 1
    credit = credits[0]
    assert credit["credit_reason"] == "DEMONSTRATOR_NO_SHOW"
    assert_cents(credit["billable_base_cents"], 48300, "billable_base_cents")
    assert credit["notice_hours"] == 0
    assert_decimal2(credit["notice_tier_pct"], 0.70, "notice_tier_pct")
    assert_cents(credit["credit_amount_cents"], 33810, "credit_amount_cents")

    host = validate_success(
        api.get_demo_event(third_strike_declared["history_host_id"], ADMIN_HQ_HEADERS)
    )
    assert host["staffing_status"] == "UNSTAFFED"


# ---------------------------------------------------------------------------
# One credit approval -> invoice total -> receivable rollup -> credit hold
# ---------------------------------------------------------------------------
def test_issuance_over_the_credit_limit_moves_the_account_to_hold(
    api, credit_cascade_state
):
    """PRD §3.9: "It then cascades: the vendor's `outstanding_balance_cents` is
    recomputed, and when the recomputed exposure exceeds the vendor's
    `credit_limit_cents` while `account_status` is `ACTIVE`, that
    `account_status` is automatically moved to `HOLD`."

    Design: Difficulty/transitive_cascade/credit_approval_cascades_through_invoice_to_receivable_and_releases_credit_hold
    """
    invoice = issue_invoice(api, credit_cascade_state["invoice"]["id"])
    vendor = validate_success(
        api.get_manufacturer(
            credit_cascade_state["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )
    event = validate_success(
        api.get_demo_event(credit_cascade_state["event_id"], ADMIN_HQ_HEADERS)
    )

    assert_cents(invoice["subtotal_cents"], 66260, "subtotal_cents")
    assert len(invoice["line_items"]) == 4
    assert invoice["issued_by_user_id"] == ADMIN_BILLING_USER_ID
    assert_cents(
        vendor["outstanding_balance_cents"], 66260, "outstanding_balance_cents"
    )
    assert vendor["account_status"] == "HOLD"
    assert event["staffing_status"] == "CLOSED_OUT"

    recon = read_reconciliation(api, credit_cascade_state["event_id"])
    assert recon["units_delivered"] == 240
    assert recon["recon_status"] == "BALANCED"


def test_approving_the_credit_lands_it_on_the_issued_invoice(
    api, credit_cascade_state
):
    """PRD §3.9: "The second hop, caused by the first, recomputes the touched
    invoice's `total_due_cents` as `subtotal_cents` less `discount_cents` less
    the new `credit_applied_cents`, floored at zero, and increments that
    invoice's `version`." The first hop places the money: when an invoice for the
    event has `invoice_status` `DRAFT` or `ISSUED`, `applied_to_invoice_id` is
    set to that invoice and that invoice's `credit_applied_cents` increases by
    this credit's `credit_amount_cents`.

    Design: Difficulty/transitive_cascade/credit_approval_cascades_through_invoice_to_receivable_and_releases_credit_hold
    """
    invoice_id = credit_cascade_state["invoice"]["id"]
    issue_invoice(api, invoice_id)
    validate_success(
        api.decide_credit(
            credit_cascade_state["credit_id"],
            {"decision": CreditDecision.APPROVE, "note": "no-show credit granted"},
            ADMIN_CONTROLLER_HEADERS,
        )
    )

    credit = validate_success(
        api.get_credit(credit_cascade_state["credit_id"], ADMIN_HQ_HEADERS)
    )
    invoice = validate_success(api.get_invoice(invoice_id, ADMIN_HQ_HEADERS))

    assert_cents(credit["credit_amount_cents"], 33810, "credit_amount_cents")
    assert credit["credit_status"] == "APPLIED"
    assert credit["approved_by_user_id"] == ADMIN_CONTROLLER_USER_ID
    assert credit["applied_to_invoice_id"] == invoice_id
    assert_cents(invoice["credit_applied_cents"], 33810, "credit_applied_cents")
    assert_cents(invoice["total_due_cents"], 32450, "total_due_cents")
    assert invoice["invoice_status"] == "ISSUED"


def test_reduced_invoice_total_re_rolls_the_receivable_and_lifts_the_hold(
    api, credit_cascade_state
):
    """PRD §3.9: "The third hop, caused by the second, recomputes the vendor's
    `outstanding_balance_cents` from the issued-invoice rollup. The fourth hop,
    caused by the third, returns the vendor's `account_status` from `HOLD` to
    `ACTIVE` when the recomputed exposure is at or below `credit_limit_cents`."

    Design: Difficulty/transitive_cascade/credit_approval_cascades_through_invoice_to_receivable_and_releases_credit_hold
    """
    issue_invoice(api, credit_cascade_state["invoice"]["id"])
    validate_success(
        api.decide_credit(
            credit_cascade_state["credit_id"],
            {"decision": CreditDecision.APPROVE, "note": "no-show credit granted"},
            ADMIN_CONTROLLER_HEADERS,
        )
    )

    vendor = validate_success(
        api.get_manufacturer(
            credit_cascade_state["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )
    event = validate_success(
        api.get_demo_event(credit_cascade_state["event_id"], ADMIN_HQ_HEADERS)
    )

    assert_cents(
        vendor["outstanding_balance_cents"], 32450, "outstanding_balance_cents"
    )
    assert vendor["account_status"] == "ACTIVE"
    assert_cents(vendor["credit_note_balance_cents"], 0, "credit_note_balance_cents")
    assert event["settlement_status"] == "INVOICED"


def test_the_issuing_operator_may_not_also_approve_the_events_credit(
    api, credit_cascade_state
):
    """PRD §2.10: "Concretely: when an invoice for the credit's event is in
    `ISSUED` or `PAID`, the `X-User-ID` on the credit decision must differ from
    the `issued_by_user_id` recorded on that invoice, and a match is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/transitive_cascade/credit_approval_cascades_through_invoice_to_receivable_and_releases_credit_hold
    """
    invoice_id = credit_cascade_state["invoice"]["id"]
    issue_invoice(api, invoice_id)

    validate_error(
        api.decide_credit(
            credit_cascade_state["credit_id"],
            {"decision": CreditDecision.APPROVE},
            ADMIN_BILLING_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    credit = validate_success(
        api.get_credit(credit_cascade_state["credit_id"], ADMIN_HQ_HEADERS)
    )
    invoice = validate_success(api.get_invoice(invoice_id, ADMIN_HQ_HEADERS))
    assert credit["credit_status"] == "PENDING_APPROVAL"
    assert_cents(invoice["credit_applied_cents"], 0, "credit_applied_cents")
    assert invoice["invoice_status"] == "ISSUED"
