"""Refusals and the state they leave behind: catalog uniqueness, a count correction
that would break a reservation, a mode/location contradiction, a three-node
supersession cycle, an over-priced substitute, a no-longer-available terminal, and a
partial settlement."""
from test_helpers import (
    CREDIT_MANAGER,
    PRICING_ADMIN,
    WARRANTY_ADMIN,
    ApiErrorId,
    api_client,
    assert_inventory_units,
    inventory_adjustment_payload,
    inventory_for,
    list_order_lines,
    list_orders,
    list_parts,
    list_substitute_requests,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    order_line_payload,
    part_payload,
    payment_payload,
    read_account,
    read_line,
    read_order,
    read_part,
    read_substitute_request,
    record_supersession,
    setup_fulfilled_line,
    setup_obsolete_part_line,
    setup_supersession_chain,
    setup_will_call_order,
    validate_error,
    will_call_order_payload,
)

STL_BRANCH = {
    "code": "STL",
    "name": "St Louis DC",
    "region_code": "MW",
    "will_call_enabled": True,
    "cutoff_hour_utc": 20,
    "overnight_surcharge_cents": 300,
}


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _gold_tier():
    return make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )


def _account_with_an_empty_draft_order(purchase_order_ref):
    """A GOLD account with a will-call order still in DRAFT and no lines."""
    tier = _gold_tier()
    branch = make_branch(**STL_BRANCH)
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    return {
        "tier": tier, "branch": branch, "account": account,
        "order": open_will_call_order(
            account, branch, purchase_order_ref=purchase_order_ref
        ),
    }


def _three_parts_linked_into_a_closed_loop():
    """A -> B -> C -> A, every link legal on its own."""
    chain = setup_supersession_chain(
        [("W10-PUMP-A", 12000), ("W10-PUMP-B", 12500), ("W10-PUMP-C", 13000)]
    )
    record_supersession(chain[2], chain[0])
    return chain


# ---------------------------------------------------------------------------
# Catalog uniqueness
# ---------------------------------------------------------------------------

class TestDuplicatePartNumber:

    def test_a_second_part_reusing_the_number_is_refused_and_changes_nothing(self):
        """PRD §2.7: "47. `ERR_DUPLICATE_KEY` (409) — uniqueness holds:
        `part_number` is unique across parts, `tier_code` across pricing tiers,
        `file_version` across price files, the pair of `branch_id` and `part_id`
        across inventory records, the triple of `model_number`, `part_id`, and
        `position_code` across cross-reference rows, and the pair of
        `price_file_id` and `part_id` across price-file lines. Guards six
        operations: `POST /parts`, `POST /pricing-tiers`, `POST /price-files`,
        `POST /inventory-records`, `POST /model-part-xrefs`, and
        `POST /price-files/{id}/lines`."
        PRD §3.1: "A `PricingAdmin` creates a **Part** by supplying its
        `part_number` (unique across the catalog), the `oem_code` of the brand it
        belongs to, a human `description`, a commodity `category`, a
        `list_price_cents` greater than zero, and a `weight_grams` greater than
        zero."

        Design: Corner/errors/duplicate_part_number_is_rejected
        """
        first = make_part(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999, weight_grams=5200,
        )

        response = api_client.create_part(
            part_payload(
                part_number="W10-PUMP", oem_code="GE",
                description="Different pump entirely", category="ELECTRICAL",
                list_price_cents=999, weight_grams=100,
            ),
            PRICING_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY)

        rows = list_parts()
        assert len(rows) == 1, (
            f"the number is claimed by exactly one row, got {len(rows)}"
        )

        survivor = read_part(first["id"])
        assert survivor["oem_code"] == "WHIRLPOOL", (
            "the incumbent row is untouched by the refused create"
        )
        assert survivor["category"] == "MECHANICAL"
        assert survivor["list_price_cents"] == 12999
        assert survivor["version"] == 1


# ---------------------------------------------------------------------------
# A count correction that would break a promise
# ---------------------------------------------------------------------------

class TestInventoryAdjustmentFloor:

    def test_an_adjustment_that_would_dip_below_the_reservation_is_refused(self):
        """PRD §3.3: "An adjustment that would drive `on_hand_units` below zero, or
        below the units already reserved, is refused with `ERR_INVENTORY_NEGATIVE` —
        reservations are promises, and a count correction may not break them."
        PRD §3.3: "The delta is added to `on_hand_units`, `available_units` is
        recomputed, and `last_counted_at` is stamped with the logical clock."
        PRD §3.3: "The metric allocation actually consults is `available_units`,
        which is always `on_hand_units` minus `reserved_units`."

        Design: Corner/errors/inventory_adjustment_below_reserved_units_is_rejected
        """
        world = setup_will_call_order(
            stage="allocated", quantity=3, branch_kwargs=dict(STL_BRANCH),
            on_hand_units=5, purchase_order_ref="PO-4001",
        )
        record = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(record, on_hand=5, reserved=3, available=2)

        response = api_client.adjust_inventory_record(
            record["id"],
            inventory_adjustment_payload(-3, "cycle count shrinkage"),
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVENTORY_NEGATIVE)

        after = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(after, on_hand=5, reserved=3, available=2)
        assert after["on_hand_units"] == 5, (
            "a refused adjustment applies no part of its delta"
        )


# ---------------------------------------------------------------------------
# A mode that contradicts its location field
# ---------------------------------------------------------------------------

class TestFulfillmentModeContradiction:

    def test_a_pickup_order_carrying_a_destination_zip_is_refused(self):
        """PRD §3.4: "The mode dictates which of two location fields must be
        present: a `WILL_CALL` order must carry a `pickup_branch_id` and must not
        carry a `ship_to_zip`, while an `OVERNIGHT_DROP_SHIP` order must carry a
        `ship_to_zip` and must not carry a `pickup_branch_id`."
        PRD §3.4: "Getting that pairing wrong is rejected with
        `ERR_FULFILLMENT_MODE_MISMATCH`, and naming a pickup branch whose
        `will_call_enabled` is false is rejected with `ERR_WILL_CALL_NOT_ENABLED`."

        Design: Corner/errors/will_call_order_carrying_a_ship_to_zip_is_rejected
        """
        tier = _gold_tier()
        branch = make_branch(**STL_BRANCH)
        account = make_account(
            tier, business_name="Ace Appliance Repair",
            oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
            credit_limit_cents=10000000, core_liability_limit_cents=5000000,
        )

        response = api_client.create_part_order(
            will_call_order_payload(
                account["id"], branch["id"],
                ship_to_zip="63110", purchase_order_ref="PO-4002",
            ),
            make_servicer_headers(account["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FULFILLMENT_MODE_MISMATCH)

        assert list_orders(servicer_account_id=account["id"]) == [], (
            "a contradictory body creates no order at all"
        )


# ---------------------------------------------------------------------------
# A cycle the up-front guard cannot see
# ---------------------------------------------------------------------------

class TestSupersessionCycle:

    def test_a_three_node_loop_aborts_the_walk_when_it_revisits_the_start(self):
        """PRD §3.1: "The target must be a different part from the source, must not
        already point back at the source (an immediate two-part loop is refused up
        front), and must share the source's `oem_code`; otherwise the request is
        rejected with `ERR_SUPERSESSION_TARGET_INVALID`."
        PRD §3.1: "Resolution starts at the requested part with a hop count of zero
        and a visited set containing that part alone, then inspects the current
        part's `lifecycle_status` and behaves as follows."
        PRD §3.1: "If that part is already in the visited set, the request is
        rejected with `ERR_SUPERSESSION_CYCLE_DETECTED`."
        PRD §3.1: "Only after the cycle check does the walk increment the hop count
        by one, and if the hop count is then greater than five the request is
        rejected with `ERR_SUPERSESSION_CHAIN_TOO_LONG`."

        Design: Corner/errors/three_part_supersession_cycle_is_detected_during_resolution
        """
        chain = _three_parts_linked_into_a_closed_loop()
        head = chain[0]
        world = _account_with_an_empty_draft_order("PO-4003")

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(head["id"], 1, world["order"]["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SUPERSESSION_CYCLE_DETECTED)

        order = read_order(world["order"]["id"])
        assert order["version"] == 1, (
            f"the refused add is not a mutation of the order, got version "
            f"{order['version']}"
        )
        assert order["subtotal_cents"] == 0
        assert list_order_lines(part_order_id=order["id"]) == [], (
            "the walk aborts before any line is persisted"
        )


# ---------------------------------------------------------------------------
# A substitute priced too far from the part it replaces
# ---------------------------------------------------------------------------

class TestSubstituteVarianceCap:

    def test_an_approval_past_the_variance_cap_leaves_the_request_pending(self):
        """PRD §3.7: "The **price variance** is the substitute part's current
        `list_price_cents` minus the obsolete part's current `list_price_cents`,
        divided by the obsolete part's current `list_price_cents`, rounded half up to
        four decimal places."
        PRD §3.7: "It is signed, so a cheaper substitute produces a negative figure,
        and the cap is applied to its absolute value: a variance whose magnitude is
        strictly greater than 0.25 is rejected with `ERR_SUBSTITUTE_PRICE_VARIANCE`,
        which means a substitute more than twenty-five percent more expensive **and**
        a substitute more than twenty-five percent cheaper are both refused, while a
        magnitude of exactly 0.2500 is accepted."
        PRD §3.7: "A request starts with `request_status` equal to `PENDING`, with
        `proposed_substitute_part_id` and `price_variance_pct` both null, and with
        `decided_by_user_id` null; the `order_line_id` ties it to its line."
        PRD §3.4: "The `subtotal_cents` is the sum of `extended_price_cents` over
        the order's lines whose `line_status` is `RESOLVED`, `ALLOCATED`,
        `BACKORDERED`, `SHIPPED`, or `RETURNED` — which is to say it excludes
        `CANCELLED` lines and excludes `SUBSTITUTE_PENDING` lines, and that exclusion
        is precisely why an obsolescence cascade lowers an order's total."

        Design: Corner/errors/substitute_beyond_the_variance_cap_is_rejected
        """
        world = setup_obsolete_part_line(
            obsolete_part_kwargs={
                "part_number": "W10-OLDPUMP",
                "description": "Obsolete drain pump",
                "list_price_cents": 12999,
            },
            branch_kwargs=dict(STL_BRANCH),
            account_kwargs={"core_liability_limit_cents": 5000000},
            quantity=1, purchase_order_ref="PO-4004",
        )
        premium = make_part(
            part_number="W10-PUMP-PREM", oem_code="WHIRLPOOL",
            description="Premium replacement pump", category="MECHANICAL",
            list_price_cents=20000, weight_grams=5400,
        )

        response = api_client.decide_substitute_request(
            world["substitute_request"]["id"],
            {
                "decision": "APPROVE",
                "substitute_part_id": premium["id"],
                "decision_note": "only stock available",
            },
            WARRANTY_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_SUBSTITUTE_PRICE_VARIANCE)

        request = read_substitute_request(world["substitute_request"]["id"])
        assert request["request_status"] == "PENDING", (
            f"a variance of 0.5386 decides nothing, got "
            f"{request['request_status']}"
        )
        assert request["proposed_substitute_part_id"] is None
        assert request["price_variance_pct"] is None

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "SUBSTITUTE_PENDING"
        assert line["resolved_part_id"] == world["part"]["id"], (
            "the line stays priced off the obsolete part"
        )

        assert read_order(world["order"]["id"])["subtotal_cents"] == 0, (
            "a line awaiting a substitute contributes nothing to the subtotal"
        )


# ---------------------------------------------------------------------------
# A terminal that cannot be substituted around
# ---------------------------------------------------------------------------

class TestNoLongerAvailableTerminal:

    def test_an_nla_request_is_fatal_and_opens_no_substitute_request(self):
        """PRD §3.1: "If it is `NLA`, the request is rejected with
        `ERR_PART_NO_LONGER_AVAILABLE`."
        PRD §3.1: "`is_returnable` is true when the category is anything other than
        `ELECTRICAL` **and** the `lifecycle_status` is anything other than `NLA`;
        electrical parts are non-returnable once they leave the counter, and that
        prohibition is absolute."
        PRD §3.7: "A **substitute request** is opened whenever an order line ends up
        pointing at an obsolete part, and there are exactly two ways that happens."

        Design: Corner/errors/line_requesting_a_no_longer_available_part_is_rejected
        """
        discontinued = make_part(
            part_number="W10-OLDBELT", oem_code="WHIRLPOOL",
            description="Discontinued drive belt", category="MECHANICAL",
            list_price_cents=4500, weight_grams=300, lifecycle_status="NLA",
        )
        assert discontinued["is_returnable"] is False
        world = _account_with_an_empty_draft_order("PO-4005")

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(discontinued["id"], 1, world["order"]["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PART_NO_LONGER_AVAILABLE)

        assert list_order_lines(part_order_id=world["order"]["id"]) == []
        assert list_substitute_requests() == [], (
            "an NLA terminal is fatal, not substitutable"
        )
        assert read_order(world["order"]["id"])["version"] == 1


# ---------------------------------------------------------------------------
# Settlement is all or nothing
# ---------------------------------------------------------------------------

class TestPartialPayment:

    def test_a_payment_short_of_the_invoice_is_refused_and_the_order_stays_invoiced(self):
        """PRD §3.5: "**Payments** are posted by a `CreditManager` supplying
        `amount_cents` and an optional `payment_reference`, and partial payments are
        never accepted."
        PRD §3.5: "For an order whose `settlement_status` is `CREDIT_APPROVED` the
        amount must equal `total_cents` exactly; for one whose `settlement_status` is
        `INVOICED` it must equal `invoiced_total_cents` exactly; any other figure is
        rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."
        PRD §3.5: "Either way `settlement_status` becomes `PAID`, the order leaves
        the exposure set, and `credit_used_cents` is recomputed."

        Design: Corner/errors/partial_payment_against_an_invoice_is_rejected
        """
        world = setup_fulfilled_line(
            quantity=3, branch_kwargs=dict(STL_BRANCH), on_hand_units=10,
            account_kwargs={"core_liability_limit_cents": 5000000},
            purchase_order_ref="PO-4006", tracking_ref="WILLCALL-4006",
        )

        response = api_client.post_payment(
            world["order"]["id"],
            payment_payload(20000, payment_reference="ACH-4006-PARTIAL"),
            CREDIT_MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        order = read_order(world["order"]["id"])
        assert order["settlement_status"] == "INVOICED", (
            f"the refused payment settles nothing, got "
            f"{order['settlement_status']}"
        )
        assert order["invoiced_total_cents"] == 31197, (
            f"Expected the invoiced 10399 x 3, got {order['invoiced_total_cents']}"
        )

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 31197, (
            "the order has not left the exposure set"
        )
