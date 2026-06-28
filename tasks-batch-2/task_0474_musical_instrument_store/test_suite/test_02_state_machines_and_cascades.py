"""Depth tests for the non-linear state machines (agreement branching fork,
repair-ticket await-parts detour) and the transitive cascade chains
(consignment sale depth-3, buyout depth-2).
"""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    make_customer_headers, make_luthier_headers,
    setup_customer_and_active_agreement, setup_rto_with_n_paid_months,
    setup_ticket_awaiting_parts, setup_ticket_in_progress,
    setup_listed_consignment, read_agreement,
    buyout_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine
# ===========================================================================
class TestAgreementBranchingFork:
    def test_return_branch_makes_unit_available(self, api):
        """PRD §3.4: "the agreement transitions `ACTIVE → RETURNED`, the underlying
        unit cascades `ON_RENT → AVAILABLE` with its `reserved_for_customer_id`
        cleared, any accrued rent-to-own equity is forfeited rather than refunded"

        Design: Difficulty/non_linear_state_machine/rental_agreement_branching_fork_three_terminals
        """
        customer, agreement, unit = setup_customer_and_active_agreement(plan="RENTAL")
        returned = validate_success(
            api.return_agreement(agreement["id"], make_customer_headers(customer["id"])), 200
        )
        assert returned["status"] == "RETURNED"
        unit_after = validate_success(api.get_unit(unit["id"], SA), 200)
        assert unit_after["status"] == "AVAILABLE"

    def test_buyout_branch_sells_unit_distinct_from_return(self, api):
        """PRD §3.4: "transitions the agreement `ACTIVE → BOUGHT_OUT`; cascades the
        underlying unit `ON_RENT → SOLD` (the unit's `list_price_cents` is left
        unchanged and its `version` increments by 1)"

        Design: Difficulty/non_linear_state_machine/rental_agreement_branching_fork_three_terminals
        """
        customer, agreement, unit = setup_rto_with_n_paid_months(
            num_months=3, list_price_cents=120000, monthly_rent_cents=10000, equity_rate_pct=0.50,
        )
        av = read_agreement(agreement["id"], customer["id"])["version"]
        bought = validate_success(
            api.buyout_agreement(agreement["id"], buyout_payload(110000, av),
                                 make_customer_headers(customer["id"])),
            200,
        )
        assert bought["status"] == "BOUGHT_OUT"
        unit_after = validate_success(api.get_unit(unit["id"], SA), 200)
        # Distinct branch terminal: SOLD, not AVAILABLE
        assert unit_after["status"] == "SOLD"


class TestRepairTicketAwaitPartsDetour:
    def test_resume_returns_to_in_progress(self, api):
        """PRD §3.6: "The assigned luthier may move an in-progress ticket
        `IN_PROGRESS → AWAITING_PARTS` while waiting on a part, and later resume it
        `AWAITING_PARTS → IN_PROGRESS`."

        Design: Difficulty/non_linear_state_machine/repair_ticket_detour_awaiting_parts_cycle
        """
        ticket = setup_ticket_awaiting_parts(luthier_id="luthier-1")
        assert ticket["status"] == "AWAITING_PARTS"
        resumed = validate_success(
            api.resume_ticket(ticket["id"], make_luthier_headers("luthier-1")), 200
        )
        assert resumed["status"] == "IN_PROGRESS"

    def test_in_progress_can_reenter_await_parts(self, api):
        """PRD §3.6: "The assigned luthier may move an in-progress ticket
        `IN_PROGRESS → AWAITING_PARTS` while waiting on a part, and later resume it
        `AWAITING_PARTS → IN_PROGRESS`."

        Design: Difficulty/non_linear_state_machine/repair_ticket_detour_awaiting_parts_cycle
        """
        ticket = setup_ticket_awaiting_parts(luthier_id="luthier-1")
        # resume back to IN_PROGRESS, then detour into AWAITING_PARTS again
        validate_success(api.resume_ticket(ticket["id"], make_luthier_headers("luthier-1")), 200)
        again = validate_success(
            api.await_parts_ticket(ticket["id"], make_luthier_headers("luthier-1")), 200
        )
        assert again["status"] == "AWAITING_PARTS"


# ===========================================================================
# Difficulty / transitive_cascade
# ===========================================================================
class TestConsignmentSellCascade:
    def test_sell_cascades_listing_unit_and_credit(self, api):
        """PRD §3.7: "On sale the system computes the consignor payout, transitions
        the listing `LISTED → SOLD`, cascades the linked unit `CONSIGNED → SOLD`,
        credits the consignor, and increments the listing's `version`."
        PRD §3.7: "the consignor payout is the ask price minus that commission."

        Design: Difficulty/transitive_cascade/consignment_sell_cascade_depth3
        """
        consignor, listing = setup_listed_consignment(ask_price_cents=150000, commission_pct=0.20)
        sold = validate_success(api.sell_consignment(listing["id"], SA), 200)
        assert sold["status"] == "SOLD"
        # ask 150000 - round(150000*0.20)=30000 -> payout 120000
        assert sold["consignor_payout_cents"] == 120000
        cust = validate_success(api.get_customer(consignor["id"], SA), 200)
        assert cust["store_credit_cents"] == 120000

    def test_sell_cascades_unit_to_sold(self, api):
        """PRD §3.7: "cascades the linked unit `CONSIGNED → SOLD`"

        Design: Difficulty/transitive_cascade/consignment_sell_cascade_depth3
        """
        consignor, listing = setup_listed_consignment(ask_price_cents=150000, commission_pct=0.20)
        # locate the backing CONSIGNED unit via the listing filter
        units, _ = _list_units_for_listing(api, listing["id"])
        assert len(units) == 1
        unit_id = units[0]["id"]
        assert units[0]["status"] == "CONSIGNED"
        validate_success(api.sell_consignment(listing["id"], SA), 200)
        unit_after = validate_success(api.get_unit(unit_id, SA), 200)
        assert unit_after["status"] == "SOLD"


class TestBuyoutCascade:
    def test_buyout_cascades_unit_to_sold(self, api):
        """PRD §3.4: "transitions the agreement `ACTIVE → BOUGHT_OUT`; cascades the
        underlying unit `ON_RENT → SOLD`"

        Design: Difficulty/transitive_cascade/buyout_cascade_unit_sold_depth2
        """
        customer, agreement, unit = setup_rto_with_n_paid_months(
            num_months=3, list_price_cents=120000, monthly_rent_cents=10000, equity_rate_pct=0.50,
        )
        av = read_agreement(agreement["id"], customer["id"])["version"]
        bought = validate_success(
            api.buyout_agreement(agreement["id"], buyout_payload(110000, av),
                                 make_customer_headers(customer["id"])),
            200,
        )
        assert bought["status"] == "BOUGHT_OUT"
        unit_after = validate_success(api.get_unit(unit["id"], SA), 200)
        assert unit_after["status"] == "SOLD"

    def test_buyout_appends_buyout_payment_record(self, api):
        """PRD §3.4: "the system appends a `PaymentRecord` with `kind` `BUYOUT`,
        `status` `POSTED`, and `amount_cents` equal to the payoff quote"

        Design: Difficulty/transitive_cascade/buyout_cascade_unit_sold_depth2
        """
        customer, agreement, unit = setup_rto_with_n_paid_months(
            num_months=3, list_price_cents=120000, monthly_rent_cents=10000, equity_rate_pct=0.50,
        )
        cust_headers = make_customer_headers(customer["id"])
        av = read_agreement(agreement["id"], customer["id"])["version"]
        validate_success(api.buyout_agreement(agreement["id"], buyout_payload(110000, av), cust_headers), 200)
        records = get_success_data(api.list_agreement_payments(agreement["id"], cust_headers))
        buyouts = [r for r in records if r["kind"] == "BUYOUT"]
        assert len(buyouts) == 1
        assert buyouts[0]["amount_cents"] == 110000
        assert buyouts[0]["status"] == "POSTED"


def _list_units_for_listing(api, listing_id):
    from test_helpers import validate_paginated
    resp = api.list_units(SA, params={"consignment_listing_id": listing_id})
    return validate_paginated(resp)
