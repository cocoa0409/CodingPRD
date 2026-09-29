"""Order, certification and substitute-request lifecycles: the states a row opens
in, the transitions the tables do not contain, terminal lockdowns, and the side
effects a single status change fires on neighbouring rows."""
from test_helpers import (
    CREDIT_MANAGER,
    WARRANTY_ADMIN,
    ApiErrorId,
    add_line,
    allocate_order,
    api_client,
    approve_credit,
    assert_inventory_units,
    cancellation_payload,
    fulfill_order,
    inventory_for,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_certification,
    make_inventory,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    pending_substitute_request_for,
    read_account,
    read_certification,
    read_line,
    read_order,
    read_substitute_request,
    revocation_payload,
    revoke_certification,
    setup_catalog,
    setup_fulfilled_line,
    setup_will_call_order,
    substitute_withdrawal_payload,
    validate_error,
    validate_success,
    will_call_order_payload,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _account_with_one_invoiced_and_one_draft_order():
    """One account carrying a fulfilled order invoiced at 31,197 cents and a
    second order still in DRAFT at 20,798 cents."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    pump = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)

    invoiced = open_will_call_order(account, branch, purchase_order_ref="PO-2004A")
    invoiced_line = add_line(invoiced, pump, quantity=3)
    approve_credit(invoiced)
    allocate_order(invoiced, branch)
    fulfill_order(invoiced, branch, tracking_ref="WILLCALL-2004A")

    draft = open_will_call_order(account, branch, purchase_order_ref="PO-2004B")
    draft_line = add_line(draft, pump, quantity=2)
    return {
        "branch": branch, "part": pump, "account": account,
        "invoiced_order": invoiced, "invoiced_line": invoiced_line,
        "draft_order": draft, "draft_line": draft_line,
    }


def _line_resolved_onto_an_obsolete_part():
    """A single-line order whose requested part is already OBSOLETE, so the line
    landed in SUBSTITUTE_PENDING with a PENDING substitute request."""
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
        part_number="W10-OLDPUMP", oem_code="WHIRLPOOL",
        description="Obsolete drain pump", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200, lifecycle_status="OBSOLETE",
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(account, branch, purchase_order_ref="PO-2005")
    line = add_line(order, obsolete, quantity=1)
    return {
        "branch": branch, "part": obsolete, "account": account,
        "order": order, "line": line,
        "request": pending_substitute_request_for(line["id"]),
    }


# ---------------------------------------------------------------------------
# Where an order starts
# ---------------------------------------------------------------------------

class TestOrderOpeningState:

    def test_a_new_order_opens_on_both_dimensions_initial_states_at_once(self):
        """PRD §3.4: "The physical dimension is `fulfillment_status`, which starts
        at `DRAFT` and ranges over `DRAFT`, `ALLOCATED`, `HELD`, `FULFILLED`, and
        `CANCELLED`, with `FULFILLED` and `CANCELLED` terminal."
        PRD §3.4: "The money dimension is `settlement_status`, which starts at
        `PENDING_CREDIT` and ranges over `PENDING_CREDIT`, `CREDIT_APPROVED`,
        `CREDIT_DECLINED`, `INVOICED`, `PAID`, and `WRITTEN_OFF`, with `PAID`,
        `CREDIT_DECLINED`, and `WRITTEN_OFF` terminal."
        PRD §3.4: "A new order starts with `pricing_basis` equal to `ORDER_DATE`
        and with `subtotal_cents`, `core_deposit_total_cents`, `freight_cents`, and
        `total_cents` all at zero; `invoiced_total_cents`, `fulfilled_at`,
        `tracking_ref`, and `credit_decided_by_user_id` all start null."
        PRD §3.4: "A `hold_reason` of `SUBSTITUTE_PENDING`, `CREDIT_HOLD`, or
        `BACKORDER` accompanies `HELD` and is null whenever `fulfillment_status` is
        anything else."

        Design: Corner/state_machines/new_part_order_starts_draft_and_pending_credit
        """
        world = setup_catalog(
            branch_kwargs={
                "code": "STL", "name": "St Louis DC", "region_code": "MW",
                "will_call_enabled": True, "cutoff_hour_utc": 20,
                "overnight_surcharge_cents": 300,
            },
            account_kwargs={"core_liability_limit_cents": 5000000},
        )

        response = api_client.create_part_order(
            will_call_order_payload(
                world["account"]["id"], world["branch"]["id"],
                purchase_order_ref="PO-2001",
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        order = validate_success(response, 201)

        assert order["fulfillment_status"] == "DRAFT"
        assert order["settlement_status"] == "PENDING_CREDIT"
        assert order["hold_reason"] is None
        assert order["pricing_basis"] == "ORDER_DATE"
        assert order["subtotal_cents"] == 0
        assert order["core_deposit_total_cents"] == 0
        assert order["freight_cents"] == 0
        assert order["total_cents"] == 0
        assert order["invoiced_total_cents"] is None
        assert order["fulfilled_at"] is None
        assert order["tracking_ref"] is None
        assert order["credit_decided_by_user_id"] is None
        assert order["purchase_order_ref"] == "PO-2001"
        assert order["version"] == 1, (
            f"a freshly created row opens at version 1, got {order['version']}"
        )


# ---------------------------------------------------------------------------
# Transitions the tables do not contain
# ---------------------------------------------------------------------------

class TestOrderTransitionsThatDoNotExist:

    def test_hand_over_cannot_be_reached_straight_from_draft(self):
        """PRD §3.6: "The order must be `ALLOCATED` and its account must be
        `ACTIVE`."
        PRD §2.7: "11. `ERR_ORDER_STATE_INVALID` (409) — allocation requires
        `fulfillment_status` equal to `DRAFT` and `settlement_status` in
        `CREDIT_APPROVED` or `PAID`; hand-over requires `fulfillment_status` equal
        to `ALLOCATED`; order cancellation requires `fulfillment_status` to be one
        of `DRAFT`, `ALLOCATED`, or `HELD`. Guards three operations:
        `POST /part-orders/{id}/allocate`, `POST /part-orders/{id}/fulfill`, and
        `POST /part-orders/{id}/cancel`."

        Design: Corner/state_machines/fulfilling_a_draft_order_cannot_skip_allocation
        """
        world = setup_will_call_order(
            stage="credit", quantity=3,
            branch_kwargs={
                "code": "STL", "name": "St Louis DC", "region_code": "MW",
                "will_call_enabled": True, "cutoff_hour_utc": 20,
                "overnight_surcharge_cents": 300,
            },
            on_hand_units=10,
            account_kwargs={"core_liability_limit_cents": 5000000},
            purchase_order_ref="PO-2002",
        )

        response = api_client.fulfill_part_order(
            world["order"]["id"],
            {"tracking_ref": "WILLCALL-2002"},
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ORDER_STATE_INVALID)

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "DRAFT", (
            f"the refused hand-over leaves the order in DRAFT, got "
            f"{order['fulfillment_status']}"
        )
        assert order["fulfilled_at"] is None
        assert order["invoiced_total_cents"] is None
        assert order["tracking_ref"] is None

        assert read_line(world["line"]["id"])["line_status"] == "RESOLVED", (
            "an unallocated line is still merely resolved"
        )

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=0, available=10)


class TestFulfilledIsTerminal:

    def test_a_shipped_order_can_no_longer_be_cancelled(self):
        """PRD §3.4: "Cancelling the whole order is available to the `Servicer`
        that owns it and to a `CreditManager` without ownership restriction, again
        with a `cancellation_reason`. It is permitted from `DRAFT`, from
        `ALLOCATED`, and from `HELD`, and in all three cases only while
        `settlement_status` is not `INVOICED`."
        PRD §2.7: "11. `ERR_ORDER_STATE_INVALID` (409) — allocation requires
        `fulfillment_status` equal to `DRAFT` and `settlement_status` in
        `CREDIT_APPROVED` or `PAID`; hand-over requires `fulfillment_status` equal
        to `ALLOCATED`; order cancellation requires `fulfillment_status` to be one
        of `DRAFT`, `ALLOCATED`, or `HELD`. Guards three operations:
        `POST /part-orders/{id}/allocate`, `POST /part-orders/{id}/fulfill`, and
        `POST /part-orders/{id}/cancel`."

        Design: Corner/state_machines/cancelling_a_fulfilled_order_is_locked_out
        """
        world = setup_fulfilled_line(
            quantity=3,
            branch_kwargs={
                "code": "STL", "name": "St Louis DC", "region_code": "MW",
                "will_call_enabled": True, "cutoff_hour_utc": 20,
                "overnight_surcharge_cents": 300,
            },
            on_hand_units=10,
            account_kwargs={"core_liability_limit_cents": 5000000},
            purchase_order_ref="PO-2003",
            tracking_ref="WILLCALL-2003",
        )

        response = api_client.cancel_part_order(
            world["order"]["id"],
            cancellation_payload("servicer changed their mind"),
            CREDIT_MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_ORDER_STATE_INVALID)

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "FULFILLED"
        assert order["settlement_status"] == "INVOICED"
        assert order["invoiced_total_cents"] == 31197, (
            f"Expected the locked 10399 x 3 invoice, got "
            f"{order['invoiced_total_cents']}"
        )

        assert read_line(world["line"]["id"])["line_status"] == "SHIPPED"

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 31197, (
            f"the refused cancellation leaves the invoiced exposure standing, got "
            f"{account['credit_used_cents']}"
        )

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=7, reserved=0, available=7)


class TestRevocationIsTerminal:

    def test_a_second_revocation_is_refused_and_does_not_bump_the_version_again(self):
        """PRD §3.2: "`REVOKED` is a terminal lockdown with no further transitions,
        and attempting to revoke an already-revoked certification is rejected with
        `ERR_CERT_ALREADY_REVOKED`."
        PRD §3.2: "Revocation moves `cert_status` from `ACTIVE` to `REVOKED`, or
        from `EXPIRED` to `REVOKED`, and immediately makes `is_effective` false —
        which in turn gates new order lines for that OEM and level and blocks
        warranty-claim submissions that depended on it."
        PRD §2.4: "Almost every resource additionally carries `updated_at`, an ISO
        8601 UTC timestamp refreshed on every mutation, and `version`, an integer
        that starts at 1 on creation and increments by exactly 1 on every mutation
        of that row — including mutations the server performs on its own initiative
        as part of a cascade, and including mutations that only change computed
        money fields."

        Design: Corner/state_machines/revoking_an_already_revoked_certification_cannot_repeat
        """
        tier = make_pricing_tier(
            tier_code="GOLD", name="Gold Contract",
            electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
            min_annual_volume_cents=5000000,
        )
        account = make_account(
            tier, business_name="Ace Appliance Repair",
            oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
            credit_limit_cents=10000000, core_liability_limit_cents=5000000,
        )
        cert = make_certification(
            account, technician_name="R. Diaz", oem_code="WHIRLPOOL",
            cert_level="ADVANCED",
            training_completed_at="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
        )

        revoked = revoke_certification(cert["id"], "technician left the business")
        assert revoked["cert_status"] == "REVOKED"
        assert revoked["version"] == 2, (
            f"the first revocation is one mutation, got version {revoked['version']}"
        )

        response = api_client.revoke_technician_certification(
            cert["id"],
            revocation_payload("duplicate revocation attempt"),
            WARRANTY_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_CERT_ALREADY_REVOKED)

        after = read_certification(cert["id"])
        assert after["version"] == 2, (
            f"a refused request is not a mutation, so the version stays at 2, got "
            f"{after['version']}"
        )
        assert after["cert_status"] == "REVOKED"
        assert after["is_effective"] is False


# ---------------------------------------------------------------------------
# One status change firing two different cascades
# ---------------------------------------------------------------------------

class TestSuspensionCascade:

    def test_suspension_writes_off_the_invoice_and_cancels_the_open_order(self):
        """PRD §3.2: "Suspension is the harshest cascade in the system: every order
        of the account whose `settlement_status` is `INVOICED` moves to
        `WRITTEN_OFF`, every order whose `fulfillment_status` is `DRAFT`,
        `ALLOCATED`, or `HELD` moves to `CANCELLED` with all of its reservations
        released, and the account's `credit_used_cents` is then recomputed."
        PRD §3.5: "Compute the open exposure by walking the account's orders and
        contributing, per order: `invoiced_total_cents` when `settlement_status` is
        `INVOICED`; `total_cents` when `settlement_status` is `PENDING_CREDIT` or
        `CREDIT_APPROVED` **and** `fulfillment_status` is `DRAFT`, `ALLOCATED`, or
        `HELD`; and nothing at all otherwise, which covers `PAID`,
        `CREDIT_DECLINED`, `WRITTEN_OFF`, and cancelled orders."
        PRD §2.9: "Implementers should not generalise a cascade beyond the rows the
        relevant subsection names."

        Design: Corner/state_machines/suspending_an_account_cancels_open_orders_and_writes_off_invoiced_ones
        """
        world = _account_with_one_invoiced_and_one_draft_order()

        before = read_account(world["account"]["id"])
        assert before["credit_used_cents"] == 51995, (
            f"Expected 31197 invoiced plus 20798 still open, got "
            f"{before['credit_used_cents']}"
        )

        response = api_client.update_servicer_account(
            world["account"]["id"], {"account_status": "SUSPENDED"}, CREDIT_MANAGER
        )
        patched = validate_success(response, 200)
        assert patched["account_status"] == "SUSPENDED"

        invoiced = read_order(world["invoiced_order"]["id"])
        assert invoiced["settlement_status"] == "WRITTEN_OFF", (
            f"the invoiced order is written off, got "
            f"{invoiced['settlement_status']}"
        )
        assert invoiced["fulfillment_status"] == "FULFILLED", (
            "an already-shipped order is not un-shipped by a suspension"
        )
        assert read_line(world["invoiced_line"]["id"])["line_status"] == "SHIPPED"

        draft = read_order(world["draft_order"]["id"])
        assert draft["fulfillment_status"] == "CANCELLED", (
            f"the still-open order is cancelled, got {draft['fulfillment_status']}"
        )
        assert read_line(world["draft_line"]["id"])["line_status"] == "CANCELLED"

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 0, (
            f"neither a written-off nor a cancelled order contributes exposure, got "
            f"{account['credit_used_cents']}"
        )

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=7, reserved=0, available=7)


# ---------------------------------------------------------------------------
# The servicer's own way out of a substitute request
# ---------------------------------------------------------------------------

class TestSubstituteWithdrawal:

    def test_the_servicer_withdrawal_backorders_the_line_rather_than_resolving_it(self):
        """PRD §3.7: "A `Servicer` may instead withdraw its own pending request,
        supplying a `withdrawal_reason`; ownership is checked against the owning
        order's `servicer_account_id`. Withdrawal moves `request_status` to
        `WITHDRAWN` and moves the line `SUBSTITUTE_PENDING → BACKORDERED`, leaving
        it priced off the obsolete part while the servicer sources it elsewhere."
        PRD §3.7: "The first is line resolution: a supersession walk that
        terminates on a part whose `lifecycle_status` is `OBSOLETE` leaves the line
        in `SUBSTITUTE_PENDING`, priced off that terminal part, and opens a request
        whose `obsolete_part_id` is that part and whose `source` is
        `CHAIN_TERMINAL_OBSOLETE`."

        Design: Corner/state_machines/withdrawing_a_pending_substitute_request_backorders_the_line
        """
        world = _line_resolved_onto_an_obsolete_part()
        assert world["request"]["request_status"] == "PENDING"
        assert read_line(world["line"]["id"])["line_status"] == "SUBSTITUTE_PENDING"

        response = api_client.withdraw_substitute_request(
            world["request"]["id"],
            substitute_withdrawal_payload("servicer sourced the part elsewhere"),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_success(response, 200)

        request = read_substitute_request(world["request"]["id"])
        assert request["request_status"] == "WITHDRAWN"
        assert request["source"] == "CHAIN_TERMINAL_OBSOLETE"
        assert request["obsolete_part_id"] == world["part"]["id"]
        assert request["proposed_substitute_part_id"] is None

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "BACKORDERED", (
            f"the servicer form of the withdrawal backorders the line rather than "
            f"resolving it, got {line['line_status']}"
        )
        assert line["resolved_part_id"] == world["part"]["id"], (
            "the line stays priced off the obsolete part"
        )
        assert line["supersession_hops"] == 0
        assert line["unit_price_cents"] == 10399, (
            f"Expected the untouched 12999 x 0.80 quote, got "
            f"{line['unit_price_cents']}"
        )

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "DRAFT", (
            "an order that was never held is not released by the withdrawal"
        )
