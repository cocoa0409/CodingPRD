"""Multi-hop cascade unwinds: the schedule slip and the title cancellation."""

from test_helpers import (
    api_client,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_retailer_ledgers,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


def _slipping_order_book(
    target_on_sale_date: str = "2026-12-02",
    on_sale_month: str = "2026-12",
    foc_clock: str = "2026-11-11T00:00:00Z",
) -> dict:
    """An issue in `SCRIPTING`, listed and published, with one order locked at cut-off.

    The single `SCRIPT` stage is still `IN_PROGRESS` and due 2026-08-20, so one
    delivery instant decides how much slip the issue carries.
    """
    return fixtures.setup_locked_order_book(
        issue_overrides={"target_on_sale_date": target_on_sale_date},
        catalog_overrides={"on_sale_month": on_sale_month},
        retailer_overrides={"opening_units_ytd": 2440},
        foc_clock=foc_clock,
    )


def _invoiced_order_book() -> dict:
    """A solicited issue whose only order has been locked at cut-off and invoiced.

    The `SCRIPT` assignment carries a 25,000-cent advance and its stage is
    `IN_PROGRESS`, so the assignment itself is `ACTIVE` with work in flight.
    """
    state = fixtures.setup_solicited_issue_in_scripting(
        assignment_overrides={"advance_cents": 25000}
    )
    issue_id = state["issue"]["id"]
    retailer = fixtures.open_retailer(opening_units_ytd=2440)
    order = fixtures.draft_and_submit_order(retailer["id"], issue_id)
    fixtures.set_clock("2026-09-23T00:00:00Z")
    fixtures.foc_lock(issue_id)
    order = fixtures.invoice_order(order["id"])
    state.update(
        {
            "retailer": fixtures.read_retailer(retailer["id"]),
            "order": order,
            "issue": fixtures.read_issue(issue_id),
        }
    )
    return state


# ═══════════════════════════════════════════════════════
# The late-delivery slip cascade
# ═══════════════════════════════════════════════════════

def test_eighty_three_days_of_slip_withdraws_the_published_listing_from_the_catalog():
    """The `SLIPPED` posture withdraws the listing and drops the issue out of `FOC_LOCKED`.

    PRD: "Hop two, caused by the posture becoming `SLIPPED`, withdraws the book from the catalog: every solicitation of that issue whose status is `SUBMITTED` or `ACCEPTED` moves to `WITHDRAWN` with `withdrawn_reason` set to the literal string `AUTO_SLIP`, and the issue's commercial dimension returns to `UNSOLICITED` if it was `SOLICITED` or `FOC_LOCKED`."

    Design: Difficulty/transitive_cascade/late_delivery_cascades_stage_to_issue_to_solicitation_to_order_to_retailer_tier
    """
    state = _slipping_order_book()
    assert_issue_dimensions(
        state["issue"],
        production_status="SCRIPTING",
        commercial_status="FOC_LOCKED",
        schedule_health="ON_TRACK",
    )
    assert state["solicitation"]["status"] == "ACCEPTED"

    validate_success(
        api_client.deliver_production_stage(
            state["stage"]["id"],
            factories.deliver_payload(delivered_pages=22),
            state["creator_headers"],
        )
    )

    # Hop one: 2026-08-20 due, delivered 2026-11-11, so 83 whole calendar days late.
    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["status"] == "DELIVERED"
    assert stage["slip_days"] == 83
    issue = fixtures.read_issue(state["issue"]["id"])
    assert issue["total_slip_days"] == 83
    assert_issue_dimensions(issue, schedule_health="SLIPPED")

    # Hop two, caused by hop one.
    solicitation = fixtures.read_solicitation(state["solicitation"]["id"])
    assert solicitation["status"] == "WITHDRAWN"
    assert solicitation["withdrawn_reason"] == "AUTO_SLIP"
    assert_issue_dimensions(issue, commercial_status="UNSOLICITED")


def test_slip_withdrawal_frees_the_catalog_slot_and_cancels_the_locked_order_book():
    """The withdrawal empties the published catalog's slot and cancels the locked order.

    PRD: "Hop three, caused by those withdrawals, refreshes `accepted_slot_count` on every affected catalog and cancels the issue's order book: every retailer order of that issue whose status is `SUBMITTED` or `FOC_LOCKED` moves to `CANCELLED` with `cancel_reason` set to the literal string `AUTO_SLIP`."

    Design: Difficulty/transitive_cascade/late_delivery_cascades_stage_to_issue_to_solicitation_to_order_to_retailer_tier
    """
    state = _slipping_order_book()
    assert state["catalog"]["accepted_slot_count"] == 1
    assert state["catalog"]["status"] == "PUBLISHED"
    assert state["order"]["status"] == "FOC_LOCKED"
    assert state["order"]["total_units"] == 114

    validate_success(
        api_client.deliver_production_stage(
            state["stage"]["id"],
            factories.deliver_payload(delivered_pages=22),
            state["creator_headers"],
        )
    )

    catalog = fixtures.read_catalog(state["catalog"]["id"])
    assert catalog["accepted_slot_count"] == 0
    # The cascade acts as the system, so an already-published catalog is still recounted.
    assert catalog["status"] == "PUBLISHED"

    order = fixtures.read_order(state["order"]["id"])
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "AUTO_SLIP"
    # The frozen allocations stay on the cancelled row for the audit trail.
    assert order["total_units"] == 114


def test_slip_order_cancellation_demotes_the_retailer_from_basic_to_entry():
    """The cancelled units leave the retailer ledger, demoting the tier and emptying the issue.

    PRD: "Hop four, caused by those cancellations, refreshes each affected retailer's `cumulative_units_ytd`, re-derives that retailer's `discount_tier` from the refreshed figure — a demotion is entirely possible here — refreshes each affected retailer's `open_balance_cents`, and refreshes the issue's `total_ordered_units`."

    Design: Difficulty/transitive_cascade/late_delivery_cascades_stage_to_issue_to_solicitation_to_order_to_retailer_tier
    """
    state = _slipping_order_book()
    # 2440 opening units plus the 114 the cut-off froze puts the account at BASIC.
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]),
        cumulative_units_ytd=2554,
        open_balance_cents=0,
        discount_tier="BASIC",
    )
    assert_issue_unit_ledgers(state["issue"], total_ordered_units=114)

    validate_success(
        api_client.deliver_production_stage(
            state["stage"]["id"],
            factories.deliver_payload(delivered_pages=22),
            state["creator_headers"],
        )
    )

    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]),
        cumulative_units_ytd=2440,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_unit_ledgers(issue, total_ordered_units=0, printed_units=0, shipped_units=0)
    # The cascade never reaches across into the production dimension.
    assert_issue_dimensions(issue, production_status="SCRIPTING")


def test_twenty_one_days_of_slip_stops_at_at_risk_without_unwinding_anything():
    """A slip that only reaches `AT_RISK` leaves listing, order and tier exactly as they were.

    PRD: "When and only when that derivation turns the posture into `SLIPPED`, a four-hop cascade unwinds the book's commercial commitments inside the same request."

    Design: Difficulty/transitive_cascade/late_delivery_cascades_stage_to_issue_to_solicitation_to_order_to_retailer_tier
    """
    state = _slipping_order_book(
        target_on_sale_date="2026-09-30",
        on_sale_month="2026-09",
        foc_clock="2026-09-09T00:00:00Z",
    )

    # Due 2026-08-20 and delivered 2026-09-10 is exactly twenty-one days of slip.
    fixtures.set_clock("2026-09-10T00:00:00Z")
    validate_success(
        api_client.deliver_production_stage(
            state["stage"]["id"],
            factories.deliver_payload(delivered_pages=22),
            state["creator_headers"],
        )
    )

    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["slip_days"] == 21
    issue = fixtures.read_issue(state["issue"]["id"])
    assert issue["total_slip_days"] == 21
    assert_issue_dimensions(
        issue,
        production_status="SCRIPTING",
        commercial_status="FOC_LOCKED",
        schedule_health="AT_RISK",
    )
    assert_issue_unit_ledgers(issue, total_ordered_units=114)

    assert fixtures.read_solicitation(state["solicitation"]["id"])["status"] == "ACCEPTED"
    assert fixtures.read_catalog(state["catalog"]["id"])["accepted_slot_count"] == 1
    assert fixtures.read_order(state["order"]["id"])["status"] == "FOC_LOCKED"
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]),
        cumulative_units_ytd=2554,
        discount_tier="BASIC",
    )


# ═══════════════════════════════════════════════════════
# The title-cancellation unwind
# ═══════════════════════════════════════════════════════

def test_title_cancellation_closes_both_dimensions_of_its_live_issue():
    """Cancelling the title sets the issue's production and commercial dimensions alike.

    PRD: "Every issue of the title whose commercial dimension is not already `CANCELLED` has both dimensions set to `CANCELLED`."

    Design: Difficulty/transitive_cascade/title_cancellation_cascades_to_issue_to_invoiced_order_to_retailer_credit
    """
    state = _invoiced_order_book()
    assert_issue_dimensions(
        state["issue"], production_status="SCRIPTING", commercial_status="FOC_LOCKED"
    )

    title = validate_success(
        api_client.cancel_title(
            state["title"]["id"],
            factories.title_cancel_payload(reason="creative team collapsed"),
            TEST_USERS["editor_in_chief_headers"],
        )
    )
    assert title["status"] == "CANCELLED"
    assert title["cancel_reason"] == "creative team collapsed"

    assert_issue_dimensions(
        fixtures.read_issue(state["issue"]["id"]),
        production_status="CANCELLED",
        commercial_status="CANCELLED",
    )


def test_cancelled_issue_takes_its_in_flight_stage_and_invoiced_order_with_it():
    """The issue cancellation cancels its `IN_PROGRESS` stage and its `INVOICED` order.

    PRD: "Caused by that, for each issue just cancelled: its print runs in `PLANNED` status move to `CANCELLED` with `cancel_reason` set to the literal string `AUTO_TITLE_CANCEL`; its production stages in `NOT_STARTED`, `IN_PROGRESS`, `DELIVERED` or `KICKED_BACK` status move to `CANCELLED`, while `APPROVED` stages are deliberately left alone so that the title's `production_cost_cents` does not move; and its retailer orders in `DRAFT`, `SUBMITTED`, `FOC_LOCKED` or `INVOICED` status move to `CANCELLED` with `cancel_reason` set to `AUTO_TITLE_CANCEL`, while orders that have already shipped are left untouched under the non-returnable terms of §2.11."

    Design: Difficulty/transitive_cascade/title_cancellation_cascades_to_issue_to_invoiced_order_to_retailer_credit
    """
    state = _invoiced_order_book()
    assert state["stage"]["status"] == "IN_PROGRESS"
    assert state["order"]["status"] == "INVOICED"
    assert state["order"]["invoice_total_cents"] == 26453

    validate_success(
        api_client.cancel_title(
            state["title"]["id"],
            factories.title_cancel_payload(),
            TEST_USERS["editor_in_chief_headers"],
        )
    )

    assert fixtures.read_stage(state["stage"]["id"])["status"] == "CANCELLED"
    order = fixtures.read_order(state["order"]["id"])
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "AUTO_TITLE_CANCEL"
    # The audit figures survive on the cancelled row even though they left the ledger.
    assert order["invoice_total_cents"] == 26453
    # The stage was never approved, so no page fee was ever frozen and none is reversed.
    assert fixtures.read_title(state["title"]["id"])["production_cost_cents"] == 0


def test_cancelled_invoiced_order_unwinds_the_retailer_credit_and_the_issue_units():
    """The invoice leaves the open balance and the units leave the tier calculation.

    PRD: "Caused in turn by those order cancellations, each affected retailer's `cumulative_units_ytd`, `discount_tier` and `open_balance_cents` are recomputed, and each affected issue's `total_ordered_units` is recomputed."

    Design: Difficulty/transitive_cascade/title_cancellation_cascades_to_issue_to_invoiced_order_to_retailer_credit
    """
    state = _invoiced_order_book()
    assert_retailer_ledgers(
        state["retailer"],
        cumulative_units_ytd=2554,
        open_balance_cents=26453,
        discount_tier="BASIC",
    )
    assert_issue_unit_ledgers(state["issue"], total_ordered_units=114)

    validate_success(
        api_client.cancel_title(
            state["title"]["id"],
            factories.title_cancel_payload(),
            TEST_USERS["editor_in_chief_headers"],
        )
    )

    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]),
        cumulative_units_ytd=2440,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=0
    )


def test_cancellation_terminates_the_assignment_that_still_owns_work_in_flight():
    """The roster branch terminates an `ACTIVE` assignment a hand-driven call could not.

    PRD: "One branch releases the creative roster: every creative assignment of the title whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE` moves to `TERMINATED` with `terminated_reason` set to the literal string `AUTO_TITLE_CANCEL`, and then, caused by those terminations, each affected creator's `active_assignment_count` is recomputed."

    Design: Difficulty/transitive_cascade/title_cancellation_cascades_to_issue_to_invoiced_order_to_retailer_credit
    """
    state = _invoiced_order_book()
    assignment_id = state["assignment"]["id"]
    assert fixtures.read_assignment(assignment_id)["status"] == "ACTIVE"
    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 1

    validate_success(
        api_client.cancel_title(
            state["title"]["id"],
            factories.title_cancel_payload(),
            TEST_USERS["editor_in_chief_headers"],
        )
    )

    assignment = fixtures.read_assignment(assignment_id)
    assert assignment["status"] == "TERMINATED"
    assert assignment["terminated_reason"] == "AUTO_TITLE_CANCEL"
    # A terminated advance is not written off by the cascade.
    assert assignment["unrecouped_advance_cents"] == 25000

    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 0
    assert fixtures.read_title(state["title"]["id"])["committed_share_bps"] == 0


def test_title_cancellation_leaves_the_accepted_listing_and_its_catalog_slot_alone():
    """Unlike the slip cascade, the title unwind never reaches the catalog solicitation.

    PRD: "A catalog's `accepted_slot_count` equals the count of that catalog's solicitations whose status is `ACCEPTED`; `DRAFT`, `SUBMITTED` and `WITHDRAWN` rows never occupy a slot."

    Design: Difficulty/transitive_cascade/title_cancellation_cascades_to_issue_to_invoiced_order_to_retailer_credit
    """
    state = _invoiced_order_book()
    assert state["solicitation"]["status"] == "ACCEPTED"
    assert state["catalog"]["accepted_slot_count"] == 1

    validate_success(
        api_client.cancel_title(
            state["title"]["id"],
            factories.title_cancel_payload(),
            TEST_USERS["editor_in_chief_headers"],
        )
    )

    solicitation = fixtures.read_solicitation(state["solicitation"]["id"])
    assert solicitation["status"] == "ACCEPTED"
    assert solicitation["withdrawn_reason"] is None
    catalog = fixtures.read_catalog(state["catalog"]["id"])
    assert catalog["accepted_slot_count"] == 1
    assert catalog["status"] == "PUBLISHED"
    # The issue itself is gone even though its listing is not.
    assert_issue_dimensions(
        fixtures.read_issue(state["issue"]["id"]), commercial_status="CANCELLED"
    )
