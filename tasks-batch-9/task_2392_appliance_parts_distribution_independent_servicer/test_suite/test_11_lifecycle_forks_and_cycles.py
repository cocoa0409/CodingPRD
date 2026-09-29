"""Non-linear lifecycles: the bounded warranty information-request cycle, the two
independent order dimensions, and the sharply diverging substitute-decision fork."""
import pytest

from test_helpers import (
    CREDIT_MANAGER,
    WARRANTY_ADMIN,
    ApiErrorId,
    add_line,
    api_client,
    assert_inventory_units,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_part,
    make_pricing_tier,
    open_will_call_order,
    pending_substitute_request_for,
    read_claim,
    read_inventory,
    read_line,
    read_order,
    read_substitute_request,
    record_oem_outcome,
    resubmit_claim,
    setup_submitted_claim,
    setup_will_call_order,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _claim_after_two_information_requests():
    """A submitted claim that the OEM has bounced for information twice, so its
    `resubmission_count` sits at the bound of two."""
    world = setup_submitted_claim(
        quantity=1,
        cert_kwargs={
            "cert_level": "SEALED_SYSTEM",
            "training_completed_at": "2026-01-01T00:00:00Z",
            "expires_at": "2027-01-01T00:00:00Z",
        },
        oem_reference="WP-C-001",
    )
    claim_id = world["claim"]["id"]
    record_oem_outcome(claim_id, "INFO_REQUESTED", oem_note="need serial plate photo")
    resubmit_claim(claim_id, "serial plate photo attached")
    record_oem_outcome(claim_id, "INFO_REQUESTED", oem_note="need install date")
    resubmit_claim(claim_id, "install date 2026-03-02")
    record_oem_outcome(claim_id, "INFO_REQUESTED", oem_note="need dealer invoice")
    return world


def _prepay_order_awaiting_payment():
    """A PREPAY account's credit-approved will-call order for one pump."""
    return setup_will_call_order(
        stage="credit", quantity=1,
        account_kwargs={
            "business_name": "Prepay Repairs LLC",
            "credit_terms": "PREPAY",
            "core_liability_limit_cents": 5000000,
        },
    )


def _two_obsolete_lines_awaiting_a_substitute_decision():
    """One obsolete pump ordered twice on the same order, so two pending
    substitute requests sit side by side, plus one active replacement part."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    obsolete = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200, lifecycle_status="OBSOLETE",
    )
    replacement = make_part(
        part_number="W10-PUMP-B", oem_code="WHIRLPOOL",
        description="Drain pump assembly rev B", category="MECHANICAL",
        list_price_cents=13500, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(account, branch)
    line_one = add_line(order, obsolete, quantity=3)
    line_two = add_line(order, obsolete, quantity=3)
    return {
        "branch": branch, "obsolete": obsolete, "replacement": replacement,
        "account": account, "order": order,
        "line_one": line_one, "line_two": line_two,
        "request_one": pending_substitute_request_for(line_one["id"]),
        "request_two": pending_substitute_request_for(line_two["id"]),
    }


# ---------------------------------------------------------------------------
# The information-request cycle and its bound
# ---------------------------------------------------------------------------

class TestWarrantyInformationRequestCycle:

    def test_a_third_resubmission_is_refused_once_the_count_has_reached_two(self):
        """PRD §3.8: "A `WarrantyAdmin` resubmits a claim sitting in
        `OEM_INFO_REQUESTED` by supplying `additional_info`; the claim moves
        `OEM_INFO_REQUESTED → SUBMITTED`, its `resubmission_count` increments by
        one, and `submitted_at` is restamped with the logical clock."
        PRD §3.8: "The cycle is bounded: resubmission is permitted only while
        `resubmission_count` is strictly below 2, so a claim may make the round
        trip at most twice, and the third attempt is rejected with
        `ERR_RESUBMISSION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_info_requested_resubmit_cycle_bounded_at_two
        """
        world = _claim_after_two_information_requests()

        response = api_client.resubmit_warranty_claim(
            world["claim"]["id"],
            {"additional_info": "dealer invoice attached"},
            WARRANTY_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED)

        claim = read_claim(world["claim"]["id"])
        assert claim["claim_status"] == "OEM_INFO_REQUESTED", (
            f"the refused resubmission must leave the claim where it was, got "
            f"{claim['claim_status']}"
        )
        assert claim["resubmission_count"] == 2, (
            f"Expected resubmission_count to stay at the bound 2, got "
            f"{claim['resubmission_count']}"
        )

    def test_the_claim_amount_locked_at_first_submission_survives_the_cycle(self):
        """PRD §3.8: "Submission stamps `submitted_at` with the logical clock and
        **locks** the claim amount: `claim_amount_cents` is the line's
        `invoiced_unit_price_cents` multiplied by the line's `quantity` minus its
        `returned_units`, so that the OEM is never billed for units the
        distributor has already taken back for credit."
        PRD §3.8: "That figure reads the invoiced unit price, never the quoted
        one, and it is frozen at first submission — units returned afterwards do
        not change it, and a resubmission does not recompute it."

        Design: Difficulty/non_linear_state_machine/warranty_claim_info_requested_resubmit_cycle_bounded_at_two
        """
        world = _claim_after_two_information_requests()

        claim = read_claim(world["claim"]["id"])
        assert claim["claim_amount_cents"] == 10399, (
            f"Expected the amount locked at first submission, 10399, got "
            f"{claim['claim_amount_cents']}"
        )
        assert claim["resubmission_count"] == 2
        assert claim["claim_status"] == "OEM_INFO_REQUESTED"


# ---------------------------------------------------------------------------
# Two dimensions on one row, advancing independently
# ---------------------------------------------------------------------------

class TestOrderDimensionsAdvanceIndependently:

    def test_a_prepaid_order_reaches_paid_while_its_physical_side_is_still_draft(self):
        """PRD §3.4: "Neither dimension's transitions are triggered by the other;
        they only read each other as preconditions. A prepaid order can reach
        `PAID` while its `fulfillment_status` is still `DRAFT`, `ALLOCATED`, or
        `HELD`."
        PRD §3.5: "The payment path from `CREDIT_APPROVED` to `PAID` is how a
        `PREPAY` account settles before shipment, and the path from `INVOICED` to
        `PAID` is how a NET-terms account settles after it."

        Design: Difficulty/non_linear_state_machine/part_order_settlement_and_fulfillment_dimensions_advance_independently
        """
        world = _prepay_order_awaiting_payment()
        order_id = world["order"]["id"]
        branch_headers = make_branch_counter_rep_headers(world["branch"]["id"])

        response = api_client.post_payment(
            order_id,
            {"amount_cents": 10399, "payment_reference": "CARD-PP-1"},
            CREDIT_MANAGER,
        )
        paid = validate_success(response, 200)
        assert paid["settlement_status"] == "PAID"
        assert paid["fulfillment_status"] == "DRAFT", (
            f"payment must not move the physical dimension, got "
            f"{paid['fulfillment_status']}"
        )

        allocated = validate_success(
            api_client.allocate_part_order(order_id, branch_headers), 200
        )
        assert allocated["fulfillment_status"] == "ALLOCATED"
        assert allocated["settlement_status"] == "PAID", (
            f"allocation must not move the money dimension, got "
            f"{allocated['settlement_status']}"
        )

        shipped = validate_success(
            api_client.fulfill_part_order(
                order_id, {"tracking_ref": "WILLCALL-PP-1"}, branch_headers
            ),
            200,
        )
        assert shipped["fulfillment_status"] == "FULFILLED"
        assert shipped["settlement_status"] == "PAID"

    def test_hand_over_locks_the_invoiced_total_without_re_invoicing_a_prepaid_order(self):
        """PRD §3.6: "And on the money dimension, an order for an account on NET
        terms moves `CREDIT_APPROVED → INVOICED` in the same request, at which
        point its contribution to exposure switches from `total_cents` to
        `invoiced_total_cents`; a `PREPAY` order, already `PAID`, stays `PAID`."
        PRD §3.6: "Each shipping line decrements its holding inventory record's
        `on_hand_units` and `reserved_units` by the line's `quantity`."

        Design: Difficulty/non_linear_state_machine/part_order_settlement_and_fulfillment_dimensions_advance_independently
        """
        world = _prepay_order_awaiting_payment()
        order_id = world["order"]["id"]
        branch_headers = make_branch_counter_rep_headers(world["branch"]["id"])

        validate_success(
            api_client.post_payment(
                order_id,
                {"amount_cents": 10399, "payment_reference": "CARD-PP-1"},
                CREDIT_MANAGER,
            ),
            200,
        )
        validate_success(api_client.allocate_part_order(order_id, branch_headers), 200)
        validate_success(
            api_client.fulfill_part_order(
                order_id, {"tracking_ref": "WILLCALL-PP-1"}, branch_headers
            ),
            200,
        )

        order = read_order(order_id)
        assert order["settlement_status"] != "INVOICED", (
            "a prepaid order that is already PAID is never invoiced"
        )
        assert order["invoiced_total_cents"] == 10399, (
            f"Expected the ship-date total 10399 to be locked, got "
            f"{order['invoiced_total_cents']}"
        )
        assert order["price_variance_cents"] == 0, (
            f"no price file moved between order and ship date, got "
            f"{order['price_variance_cents']}"
        )

        record = read_inventory(world["inventory"]["id"])
        assert_inventory_units(record, on_hand=9, reserved=0, available=9)


# ---------------------------------------------------------------------------
# The substitute-decision fork
# ---------------------------------------------------------------------------

class TestSubstituteDecisionFork:

    def test_approving_a_substitute_resolves_the_line_onto_the_offered_part(self):
        """PRD §3.7: "On approval, `request_status` moves `PENDING → APPROVED`,
        `proposed_substitute_part_id` is set to the offered part,
        `price_variance_pct` is written, and the line moves
        `SUBSTITUTE_PENDING → RESOLVED` with its `resolved_part_id` rewritten to
        the substitute and its `unit_price_cents` and `extended_price_cents`
        recomputed off the substitute; the line's `supersession_hops` is left
        unchanged, because a substitution is not a supersession hop."
        PRD §3.7: "The **price variance** is the substitute part's current
        `list_price_cents` minus the obsolete part's current `list_price_cents`,
        divided by the obsolete part's current `list_price_cents`, rounded half up
        to four decimal places."

        Design: Difficulty/non_linear_state_machine/substitute_decision_fork_approve_resolves_reject_cancels
        """
        world = _two_obsolete_lines_awaiting_a_substitute_decision()

        response = api_client.decide_substitute_request(
            world["request_one"]["id"],
            {
                "decision": "APPROVE",
                "substitute_part_id": world["replacement"]["id"],
                "decision_note": "form-fit-function equivalent",
            },
            WARRANTY_ADMIN,
        )
        validate_success(response, 200)

        request = read_substitute_request(world["request_one"]["id"])
        assert request["request_status"] == "APPROVED"
        assert request["source"] == "CHAIN_TERMINAL_OBSOLETE", (
            f"the request was opened by line resolution, got {request['source']}"
        )
        assert request["proposed_substitute_part_id"] == world["replacement"]["id"]
        assert request["price_variance_pct"] == pytest.approx(0.0385, abs=0.0001), (
            f"Expected (13500 - 12999) / 12999 rounded to 0.0385, got "
            f"{request['price_variance_pct']}"
        )

        line = read_line(world["line_one"]["id"])
        assert line["line_status"] == "RESOLVED"
        assert line["resolved_part_id"] == world["replacement"]["id"]
        assert line["unit_price_cents"] == 10800, (
            f"Expected 13500 x 0.80 = 10800, got {line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 32400

    def test_rejecting_a_substitute_cancels_the_line_and_zeroes_its_extended_price(self):
        """PRD §3.7: "On rejection, `request_status` moves
        `PENDING → REJECTED`, `proposed_substitute_part_id` stays null,
        `price_variance_pct` stays null, and the line moves
        `SUBSTITUTE_PENDING → CANCELLED` with its `extended_price_cents` set to
        zero."
        PRD §3.4: "The `subtotal_cents` is the sum of `extended_price_cents` over
        the order's lines whose `line_status` is `RESOLVED`, `ALLOCATED`,
        `BACKORDERED`, `SHIPPED`, or `RETURNED` — which is to say it excludes
        `CANCELLED` lines and excludes `SUBSTITUTE_PENDING` lines, and that
        exclusion is precisely why an obsolescence cascade lowers an order's
        total."

        Design: Difficulty/non_linear_state_machine/substitute_decision_fork_approve_resolves_reject_cancels
        """
        world = _two_obsolete_lines_awaiting_a_substitute_decision()

        validate_success(
            api_client.decide_substitute_request(
                world["request_one"]["id"],
                {
                    "decision": "APPROVE",
                    "substitute_part_id": world["replacement"]["id"],
                    "decision_note": "form-fit-function equivalent",
                },
                WARRANTY_ADMIN,
            ),
            200,
        )
        validate_success(
            api_client.decide_substitute_request(
                world["request_two"]["id"],
                {"decision": "REJECT", "decision_note": "no equivalent stocked"},
                WARRANTY_ADMIN,
            ),
            200,
        )

        request = read_substitute_request(world["request_two"]["id"])
        assert request["request_status"] == "REJECTED"
        assert request["proposed_substitute_part_id"] is None
        assert request["price_variance_pct"] is None

        line = read_line(world["line_two"]["id"])
        assert line["line_status"] == "CANCELLED"
        assert line["extended_price_cents"] == 0

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 32400, (
            f"only the substituted line still counts, so 32400, got "
            f"{order['subtotal_cents']}"
        )
        assert order["total_cents"] == 32400
        assert order["fulfillment_status"] == "DRAFT"
