"""Gates whose outcome lives on a neighbouring entity, not on the target."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_decimal2
from test_helpers.fixtures import read_reconciliation
from test_helpers.test_users import (
    ADMIN_BILLING_HEADERS,
    ADMIN_BILLING_USER_ID,
    ADMIN_HQ_HEADERS,
    make_club_headers,
)
from test_helpers.types import BookingAction, ClubStatus, InvoiceAction


# ---------------------------------------------------------------------------
# Club.club_status crossed with DemoEvent.event_type
# ---------------------------------------------------------------------------
def test_restricted_club_refuses_the_food_approval_but_admits_the_non_food_one(
    api, restricted_club_events
):
    """PRD §2.8: "`APPROVE` requires the hosting club's `club_status` to be
    `OPEN`, or `RESTRICTED` together with an `event_type` of `NON_FOOD_DEMO`. A
    `CLOSED` club blocks every approval; a `RESTRICTED` club blocks
    `FOOD_SAMPLING` approvals only. Either refusal is `ERR_CLUB_NOT_OPEN` (409)."

    Design: Difficulty/cross_entity_state_dependency/restricted_club_status_blocks_food_approval_while_admitting_non_food
    """
    club_headers = make_club_headers(restricted_club_events["club"]["id"])
    assert restricted_club_events["restricted_club"]["club_status"] == "RESTRICTED"

    food = validate_success(
        api.get_demo_event(restricted_club_events["food_event_id"], club_headers)
    )
    non_food = validate_success(
        api.get_demo_event(restricted_club_events["non_food_event_id"], club_headers)
    )
    assert food["event_type"] == "FOOD_SAMPLING"
    assert non_food["event_type"] == "NON_FOOD_DEMO"

    validate_error(
        api.demo_event_transition(
            restricted_club_events["food_event_id"],
            {"action": BookingAction.APPROVE},
            club_headers,
        ),
        ApiErrorId.CLUB_NOT_OPEN,
        409,
    )

    approved = validate_success(
        api.demo_event_transition(
            restricted_club_events["non_food_event_id"],
            {"action": BookingAction.APPROVE},
            club_headers,
        )
    )
    assert approved["booking_status"] == "CONFIRMED"
    assert approved["allocated_sample_cases"] == 2


def test_reopening_the_club_unblocks_the_byte_identical_food_approval(
    api, restricted_club_events
):
    """PRD §3.3: "Approval is the single densest gate in the system, and it moves
    `booking_status` from `SUBMITTED` to `CONFIRMED`." Beyond the state and
    ownership requirements, approval demands all of the following, and §2.8 fixes
    the order in which failures are reported: the vendor's `account_status` is
    `ACTIVE`; the club's `club_status` is `OPEN`, or is `RESTRICTED` while the
    event's `event_type` is `NON_FOOD_DEMO`.

    Design: Difficulty/cross_entity_state_dependency/restricted_club_status_blocks_food_approval_while_admitting_non_food
    """
    club_id = restricted_club_events["club"]["id"]
    club_headers = make_club_headers(club_id)
    food_event_id = restricted_club_events["food_event_id"]

    validate_error(
        api.demo_event_transition(
            food_event_id, {"action": BookingAction.APPROVE}, club_headers
        ),
        ApiErrorId.CLUB_NOT_OPEN,
        409,
    )
    validate_success(
        api.demo_event_transition(
            restricted_club_events["non_food_event_id"],
            {"action": BookingAction.APPROVE},
            club_headers,
        )
    )
    validate_success(
        api.update_club(club_id, {"club_status": ClubStatus.OPEN}, ADMIN_HQ_HEADERS)
    )

    approved = validate_success(
        api.demo_event_transition(
            food_event_id, {"action": BookingAction.APPROVE}, club_headers
        )
    )
    assert approved["booking_status"] == "CONFIRMED"
    assert approved["allocated_sample_cases"] == 4
    assert approved["approved_at"] is not None
    assert approved["staffing_status"] == "UNSTAFFED"

    capacity = validate_success(
        api.get_club_capacity(club_id, club_headers, "2026-09-14")
    )
    assert capacity["confirmed_count"] == 2


# ---------------------------------------------------------------------------
# SampleReconciliation.recon_status gating EventInvoice.ISSUE
# ---------------------------------------------------------------------------
def test_flagged_variance_on_the_reconciliation_blocks_the_invoice_issue(
    api, variance_blocked_invoice
):
    """PRD §2.8: "Issuing an invoice requires the event's reconciliation to be in
    `BALANCED` or `WRITTEN_OFF`, and posting a `FINAL` lift measurement requires a
    reconciliation row to exist at all. Either failure is
    `ERR_RECONCILIATION_UNRESOLVED` (409)."

    Design: Difficulty/cross_entity_state_dependency/variance_flagged_reconciliation_on_another_entity_blocks_invoice_issue
    """
    recon = variance_blocked_invoice["reconciliation"]
    invoice = variance_blocked_invoice["invoice"]

    assert recon["variance_units"] == 10
    assert_decimal2(recon["variance_pct"], 4.17, "variance_pct")
    assert recon["recon_status"] == "VARIANCE_FLAGGED"
    assert_cents(invoice["subtotal_cents"], 60500, "subtotal_cents")
    assert len(invoice["line_items"]) == 4
    assert_cents(invoice["total_due_cents"], 60500, "total_due_cents")

    validate_error(
        api.invoice_transition(
            invoice["id"], {"action": InvoiceAction.ISSUE}, ADMIN_BILLING_HEADERS
        ),
        ApiErrorId.RECONCILIATION_UNRESOLVED,
        409,
    )

    unchanged = validate_success(api.get_invoice(invoice["id"], ADMIN_HQ_HEADERS))
    vendor = validate_success(
        api.get_manufacturer(
            variance_blocked_invoice["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )
    assert unchanged["invoice_status"] == "DRAFT"
    assert unchanged["issued_at"] is None
    assert_cents(vendor["outstanding_balance_cents"], 0, "outstanding_balance_cents")


def test_writing_off_the_variance_books_shrink_and_unblocks_issuance(
    api, variance_blocked_invoice
):
    """PRD §3.7: "It moves `recon_status` to `WRITTEN_OFF`, sets
    `write_off_cost_cents` to the absolute value of `variance_units` multiplied by
    the product's `unit_cost_cents`, rounded half-up to whole cents, and
    increments the reconciliation's `version` by 1." Resolution is a head-office
    write-off, legal only from `VARIANCE_FLAGGED`.

    Design: Difficulty/cross_entity_state_dependency/variance_flagged_reconciliation_on_another_entity_blocks_invoice_issue
    """
    invoice_id = variance_blocked_invoice["invoice"]["id"]

    validate_error(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.ISSUE}, ADMIN_BILLING_HEADERS
        ),
        ApiErrorId.RECONCILIATION_UNRESOLVED,
        409,
    )
    written_off = validate_success(
        api.write_off_reconciliation(
            variance_blocked_invoice["reconciliation"]["id"],
            {"note": "10 units unaccounted, shrink booked"},
            ADMIN_HQ_HEADERS,
        )
    )
    assert_cents(written_off["write_off_cost_cents"], 2100, "write_off_cost_cents")
    assert written_off["recon_status"] == "WRITTEN_OFF"

    issued = validate_success(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.ISSUE}, ADMIN_BILLING_HEADERS
        )
    )
    vendor = validate_success(
        api.get_manufacturer(
            variance_blocked_invoice["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )
    event = validate_success(
        api.get_demo_event(variance_blocked_invoice["event_id"], ADMIN_HQ_HEADERS)
    )
    stored_recon = read_reconciliation(api, variance_blocked_invoice["event_id"])

    assert issued["invoice_status"] == "ISSUED"
    assert issued["issued_by_user_id"] == ADMIN_BILLING_USER_ID
    assert_cents(
        vendor["outstanding_balance_cents"], 60500, "outstanding_balance_cents"
    )
    assert event["settlement_status"] == "INVOICED"
    assert stored_recon["recon_status"] == "WRITTEN_OFF"
