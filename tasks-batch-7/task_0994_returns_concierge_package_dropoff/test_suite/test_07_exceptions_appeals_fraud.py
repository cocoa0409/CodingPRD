"""Exception cases: opening guards, the INSPECTING <-> EXCEPTION_PENDING
cycle, per-kind resolve cascades, the appeal/reopen loop with its limit,
segregation of duties, and the shopper fraud-strike ladder."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_payload,
    book_pickup,
    create_exception_case_payload,
    create_location,
    create_order,
    create_return_item_line,
    create_return_order_payload,
    create_slot,
    drive_pickup_collect,
    fulfill_order_via_pickup,
    get_order,
    inspect_item,
    list_order_items,
    make_location_operator_headers,
    make_support_agent_headers,
    open_exception,
    reserve_slot,
    resolve_exception,
    resolve_exception_payload,
    setup_commercial_spine,
    start_investigation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT_A = make_support_agent_headers("agent-a")
AGENT_B = make_support_agent_headers("agent-b")
AGENT_C = make_support_agent_headers("agent-c")


def _pickup_spine(email, **plan_overrides):
    merged = {"pickup_enabled": True}
    merged.update(plan_overrides)
    return setup_commercial_spine(plan_overrides=merged, shopper_email=email,
                                  with_zone=True)


def _in_transit_order(spine, sku="EX"):
    """HOME_PICKUP order collected by the courier (IN_TRANSIT)."""
    order = create_order(spine, method="HOME_PICKUP", boxless=True,
                         items=[create_return_item_line(sku=sku)])
    appointment = book_pickup(order, spine["zone"])
    drive_pickup_collect(appointment["id"])
    return order


class TestExceptionOpening:

    def test_second_open_exception_on_same_order_rejected(self, api):
        """PRD §3.9: "Only one exception may be live on an order at a time —
        a second open attempt while any case sits in `OPEN`, `INVESTIGATING`,
        `AWAITING_SHOPPER`, or `REOPENED` is refused with
        `ERR_EXCEPTION_OPEN_EXISTS`."

        Design: Corner/validations/second_open_exception_on_same_order_rejected
        """
        spine = _pickup_spine("sxo@x.com")
        order = _in_transit_order(spine, sku="XO")
        open_exception(order["id"], "LOST_PARCEL", note="first",
                       opener_headers=AGENT_A)
        resp = api.create_exception_case(
            create_exception_case_payload(order["id"], "LOST_PARCEL", "second"),
            AGENT_B,
        )
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_OPEN_EXISTS)

    def test_error_cross_merchant_item_reference(self, api):
        """PRD §2.8: "references never cross merchant boundaries — surfacing
        as `ERR_MERCHANT_SUSPENDED`, `ERR_SHOPPER_RESTRICTED`,
        `ERR_BILLING_CYCLE_NOT_OPEN`, `ERR_ROUTE_ORIGIN_MISMATCH`, or
        `ERR_CROSS_MERCHANT_REFERENCE`."

        Design: Corner/errors/error_cross_merchant_item_reference
        """
        from test_helpers import create_merchant, create_billing_cycle
        spine = _pickup_spine("sxm@x.com")
        plan = spine["plan"]
        merchant_b = create_merchant(plan["id"], legal_name="M-XB")
        create_billing_cycle(merchant_b["id"])

        order_a = create_order(spine, method="HOME_PICKUP", boxless=True,
                               items=[create_return_item_line(sku="XA")])
        items_a = list_order_items(order_a["id"])

        # Order B belongs to merchant B (a different merchant than order A).
        order_b = create_order(
            {"shopper": spine["shopper"], "merchant": merchant_b,
             "shopper_headers": spine["shopper_headers"]},
            method="HOME_PICKUP", boxless=True,
            items=[create_return_item_line(sku="XB")],
        )
        appointment = book_pickup(order_b, spine["zone"])
        drive_pickup_collect(appointment["id"])

        resp = api.create_exception_case(
            create_exception_case_payload(
                order_b["id"], "DAMAGED_ITEM", "cross-merchant item",
                return_item_id=items_a[0]["id"],
            ),
            AGENT_A,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_MERCHANT_REFERENCE)


class TestInspectingExceptionCycle:

    def test_return_order_inspecting_exception_pending_cycle(self, api):
        """PRD §3.8: "with no further open exceptions and at least one item
        still `PENDING`, the order returns `EXCEPTION_PENDING` → `INSPECTING`".
        PRD §3.8: "An order may loop between `INSPECTING` and
        `EXCEPTION_PENDING` many times before settling."
        PRD §3.9: "opening cascades to the order: an order in `DROPPED_OFF`,
        `IN_TRANSIT`, or `INSPECTING` moves to `EXCEPTION_PENDING`."

        Design: Difficulty/non_linear_state_machine/return_order_inspecting_exception_pending_cycle
        """
        spine = _pickup_spine("sc@x.com", free_returns=False)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[
                create_return_item_line(sku="CA", unit_price_cents=4000,
                                        longest_side_cm=20, weight_grams=200),
                create_return_item_line(sku="CB", unit_price_cents=2500,
                                        longest_side_cm=20, weight_grams=200),
            ],
        )
        item_a, item_b = items[0], items[1]
        inspect_item(item_a["id"], "DAMAGED")

        case = open_exception(
            order["id"], "DAMAGED_ITEM", note="dispute damage",
            return_item_id=item_a["id"], opener_headers=AGENT_A,
        )
        mid = get_order(order["id"])
        assert mid["status"] == "EXCEPTION_PENDING"

        case = start_investigation(case["id"], headers=AGENT_A)
        resolved = resolve_exception(case["id"], "REJECTED",
                                     headers=AGENT_B, note="damage confirmed")
        assert resolved["status"] == "RESOLVED_REJECTED"

        # Item B still PENDING -> the order cycles back to INSPECTING.
        back = get_order(order["id"])
        assert back["status"] == "INSPECTING"

        inspect_item(item_b["id"], "NEW")
        end = get_order(order["id"])
        assert end["status"] == "REFUND_POSTED"
        # A DAMAGED 50% of 4000 = 2000 refund; B NEW full 2500.
        assert end["refund_final_cents"] == 4500

    def test_wrong_item_last_inspect_auto_creates_exception(self, api):
        """PRD §3.8: "If any item's inspected condition is `WRONG_ITEM`, the
        system auto-creates an exception of kind `WRONG_ITEM` — recorded as
        opened by `system` — and the order moves `INSPECTING` →
        `EXCEPTION_PENDING`."

        Design: Corner/state_machines/wrong_item_last_inspect_auto_creates_exception
        """
        from test_helpers import api_client
        spine = _pickup_spine("swi@x.com")
        order, items = fulfill_order_via_pickup(
            spine,
            items=[create_return_item_line(sku="WI", unit_price_cents=4000)],
        )
        inspect_item(items[0]["id"], "WRONG_ITEM")

        cases = validate_success(
            api_client.list_order_exception_cases(order["id"], ADMIN)
        )
        assert len(cases) == 1
        case = cases[0]
        assert case["kind"] == "WRONG_ITEM"
        assert case["opened_by_user_id"] == "system"
        assert case["status"] == "OPEN"

        order_after = get_order(order["id"])
        assert order_after["status"] == "EXCEPTION_PENDING"


class TestDepthFourCascade:

    def test_exception_approve_damaged_depth4_cascade(self, api):
        """PRD §3.9: "An approved `DAMAGED_ITEM` case rewrites the linked
        item's condition from `DAMAGED` to `DEFECTIVE`."
        PRD §3.9: "In every remaining resolve path, the order re-evaluates as
        described in §3.8: back to `INSPECTING` when uninspected items remain,
        or onward through `RESOLVED` — where `refund_final_cents` is
        recomputed with the now-current conditions and the `FINAL` entry
        appended — to `REFUND_POSTED`, with the covering billing cycle's
        `refunds_accrued_cents` refreshed."

        Design: Difficulty/transitive_cascade/exception_approve_damaged_depth4_cascade
        """
        from test_helpers import api_client
        spine = _pickup_spine("s4@x.com", free_returns=False)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[
                create_return_item_line(sku="A4", unit_price_cents=4000,
                                        longest_side_cm=20, weight_grams=200),
                create_return_item_line(sku="B4", unit_price_cents=2500,
                                        longest_side_cm=20, weight_grams=200),
            ],
        )
        item_a, item_b = items[0], items[1]
        inspect_item(item_a["id"], "DAMAGED")

        case = open_exception(
            order["id"], "DAMAGED_ITEM", note="contest damage",
            return_item_id=item_a["id"], opener_headers=AGENT_A,
        )
        # Last pending item inspected while the exception is open: the order
        # stays EXCEPTION_PENDING (resolution deferred).
        inspect_item(item_b["id"], "NEW")
        case = start_investigation(case["id"], headers=AGENT_A)

        resolve_exception(case["id"], "APPROVED", headers=AGENT_B,
                          note="merchant fault")

        # Link 1: item condition flipped DAMAGED -> DEFECTIVE (deduction 0).
        item_a_after = validate_success(api.get_return_item(item_a["id"], ADMIN))
        assert item_a_after["condition"] == "DEFECTIVE"
        assert item_a_after["deduction_cents"] == 0

        # Links 2-3: order re-evaluates to RESOLVED -> FINAL 4000 + 2500 ->
        # REFUND_POSTED.
        order_after = get_order(order["id"])
        assert order_after["status"] == "REFUND_POSTED"
        assert order_after["refund_final_cents"] == 6500

        # Link 4: covering cycle's refunds_accrued_cents refreshed.
        cycles = validate_success(
            api_client.list_merchant_billing_cycles(spine["merchant"]["id"], ADMIN)
        )
        assert cycles[0]["refunds_accrued_cents"] == 6500


class TestOversizeReroute:

    def test_oversize_reject_approve_reroutes_order_to_home_pickup(self, api):
        """PRD §3.9: "An approved `OVERSIZE_REJECT` case reroutes the order:
        it returns `EXCEPTION_PENDING` → `INITIATED` with `method` rewritten
        to `HOME_PICKUP`, the active label voided, and any held reservation
        released with its slot emptied, so the oversize parcel re-enters the
        network through the pickup path."

        Design: Corner/state_machines/oversize_reject_approve_reroutes_order_to_home_pickup
        """
        from test_helpers import api_client
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": True}, shopper_email="sor@x.com"
        )
        location = create_location(name="L-OR", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")
        order = create_order(
            spine, method="LOCKER_QR",
            items=[create_return_item_line(sku="OR", longest_side_cm=140)],
        )
        reservation = reserve_slot(order, slot, spine["shopper_headers"])
        # Deposit the package (order -> DROPPED_OFF).
        from test_helpers import api_client as _ac
        validate_success(
            _ac.consume_slot_reservation(
                reservation["id"], make_location_operator_headers(location["id"])
            )
        )

        case = open_exception(
            order["id"], "OVERSIZE_REJECT", note="does not fit locker",
            opener_headers=make_location_operator_headers(location["id"]),
        )
        case = start_investigation(case["id"], headers=AGENT_A)
        resolve_exception(case["id"], "APPROVED", headers=AGENT_B)

        order_after = get_order(order["id"])
        assert order_after["status"] == "INITIATED"
        assert order_after["method"] == "HOME_PICKUP"

        # The reservation was already CONSUMED by the physical deposit — the
        # reroute does not rewind a completed deposit.
        reservation_after = validate_success(
            api_client.get_slot_reservation(reservation["id"], ADMIN)
        )
        assert reservation_after["status"] == "CONSUMED"


class TestAppealLoop:

    def test_exception_case_appeal_reopen_cycle(self, api):
        """PRD §3.9: "the shopper may appeal a resolved case by submitting an
        `appeal_note`, moving it to `REOPENED` and incrementing `appeal_count`
        by one — but only while fewer than two appeals have been filed, with a
        third attempt refused as `ERR_APPEAL_LIMIT_REACHED`."
        PRD §3.9: "the same action also re-enters investigation from
        `REOPENED` after an appeal."

        Design: Difficulty/non_linear_state_machine/exception_case_appeal_reopen_cycle
        """
        from test_helpers import api_client
        spine = _pickup_spine("sa@x.com")
        order = _in_transit_order(spine, sku="AP")
        items = list_order_items(order["id"])

        case = open_exception(
            order["id"], "DAMAGED_ITEM", note="opened",
            return_item_id=items[0]["id"], opener_headers=AGENT_A,
        )
        case = start_investigation(case["id"], headers=AGENT_A)
        resolved = resolve_exception(case["id"], "REJECTED", headers=AGENT_B)
        assert resolved["status"] == "RESOLVED_REJECTED"

        shopper_headers = spine["shopper_headers"]

        # First appeal: RESOLVED_REJECTED -> REOPENED.
        appealed1 = validate_success(
            api_client.appeal_exception_case(
                case["id"], appeal_payload("please recheck"), shopper_headers
            )
        )
        assert appealed1["status"] == "REOPENED"

        case = start_investigation(case["id"], headers=AGENT_A)
        resolved2 = resolve_exception(case["id"], "APPROVED", headers=AGENT_B,
                                      note="upheld")
        assert resolved2["status"] == "RESOLVED_APPROVED"

        # Second appeal: appeal_count reaches 2.
        appealed2 = validate_success(
            api_client.appeal_exception_case(
                case["id"], appeal_payload("second appeal"), shopper_headers
            )
        )
        assert appealed2["appeal_count"] == 2

        case = start_investigation(case["id"], headers=AGENT_A)
        resolved3 = resolve_exception(case["id"], "APPROVED", headers=AGENT_B)
        assert resolved3["status"] == "RESOLVED_APPROVED"

        # Third appeal: refused (appeal_count already 2).
        blocked = api_client.appeal_exception_case(
            case["id"], appeal_payload("third appeal must fail"), shopper_headers
        )
        validate_error(blocked, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)


class TestSegregationOfDuties:

    def test_segregation_of_duties_exception_resolver(self, api):
        """PRD §3.9: "the resolver must differ from the opener — a resolver
        whose identity equals `opened_by_user_id` is refused with
        `ERR_SOD_RESOLVER_EQUALS_OPENER`, and that differing identity is
        recorded in `resolved_by_user_id`".

        Design: Corner/roles/segregation_of_duties_exception_resolver
        """
        spine = _pickup_spine("ssd@x.com")
        order = _in_transit_order(spine, sku="SD")
        case = open_exception(order["id"], "LOST_PARCEL",
                              note="opened by a", opener_headers=AGENT_A)
        case = start_investigation(case["id"], headers=AGENT_A)

        # Same agent as opener -> refused.
        blocked = api.resolve_exception_case(
            case["id"],
            resolve_exception_payload("APPROVED", case["version"]),
            AGENT_A,
        )
        validate_error(blocked, ApiErrorId.ERR_SOD_RESOLVER_EQUALS_OPENER)

        # A different agent succeeds and is recorded as resolver.
        from test_helpers import api_client
        fresh = validate_success(api_client.get_exception_case(case["id"], AGENT_B))
        resolved = validate_success(
            api.resolve_exception_case(
                case["id"],
                resolve_exception_payload("APPROVED", fresh["version"]),
                AGENT_B,
            )
        )
        assert resolved["status"] == "RESOLVED_APPROVED"
        assert resolved["resolved_by_user_id"] == "agent-b"


class TestFraudStrikes:

    def test_fraud_strikes_restrict_and_unrestrict_cycle(self, api):
        """PRD §3.3: "each time a `LABEL_FRAUD` exception resolves `APPROVED`
        against the shopper, their `fraud_strikes` increments by one, and the
        moment the count reaches two the shopper's `status` automatically
        becomes `RESTRICTED`. Exactly one strike leaves the shopper `ACTIVE`;
        the second strike restricts. A `RESTRICTED` shopper cannot create new
        return orders — attempts are refused with `ERR_SHOPPER_RESTRICTED` —
        until a `SupportAgent` or `PlatformAdmin` lifts the restriction,
        moving `RESTRICTED` → `ACTIVE` and resetting `fraud_strikes` to
        zero."

        Design: Corner/roles/fraud_strikes_restrict_and_unrestrict_cycle
        """
        from test_helpers import api_client
        spine = _pickup_spine("sfr@x.com")
        shopper_id = spine["shopper"]["id"]

        order1 = _in_transit_order(spine, sku="F1")
        case1 = open_exception(order1["id"], "LABEL_FRAUD", note="fraud 1",
                               opener_headers=AGENT_A)
        start_investigation(case1["id"], headers=AGENT_A)

        order2 = _in_transit_order(spine, sku="F2")
        case2 = open_exception(order2["id"], "LABEL_FRAUD", note="fraud 2",
                               opener_headers=AGENT_A)
        start_investigation(case2["id"], headers=AGENT_A)

        resolve_exception(case1["id"], "APPROVED", headers=AGENT_B)
        mid = validate_success(api_client.get_shopper(shopper_id, AGENT_A))
        assert mid["status"] == "ACTIVE"
        assert mid["fraud_strikes"] == 1

        resolve_exception(case2["id"], "APPROVED", headers=AGENT_B)
        end = validate_success(api_client.get_shopper(shopper_id, AGENT_A))
        assert end["status"] == "RESTRICTED"
        assert end["fraud_strikes"] == 2

        blocked = api.create_return_order(
            create_return_order_payload(
                shopper_id, spine["merchant"]["id"], method="HOME_PICKUP",
                boxless=True,
                items=[create_return_item_line(sku="F3")],
            ),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_SHOPPER_RESTRICTED)

        restored = validate_success(
            api_client.unrestrict_shopper(shopper_id, AGENT_C)
        )
        assert restored["status"] == "ACTIVE"
        assert restored["fraud_strikes"] == 0


class TestTerminalOrder:

    def test_cancel_terminal_order_returns_already_terminal(self, api):
        """PRD §2.8: "the target resource is in a valid from-state for the
        requested transition and terminal resources reject everything, else
        `ERR_INVALID_STATE` or `ERR_ALREADY_TERMINAL`."
        PRD §3.3: "While still `INITIATED` or `LABEL_ISSUED`, the shopper (or
        a `SupportAgent`) may cancel the order, moving it to the terminal
        `CANCELLED`".

        Design: Corner/state_machines/cancel_terminal_order_returns_already_terminal
        """
        from test_helpers import fulfill_order_to_refund_posted
        spine = _pickup_spine("stc@x.com")
        order, _projection = fulfill_order_to_refund_posted(
            spine, items=[create_return_item_line(sku="TC")]
        )
        resp = api.cancel_return_order(order["id"], spine["shopper_headers"])
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
