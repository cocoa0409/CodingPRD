"""Who may act, and on whose rows: a role outside an endpoint's list, a servicer
reaching across accounts, a counter rep reaching across branches, the waiver
cross-check against the credit approver, and the break-glass operator that the
branch-scope rule does not bind."""
import pytest

from test_helpers import (
    CREDIT_MANAGER,
    CREDIT_MANAGER_TWO,
    PLATFORM_ADMIN,
    ApiErrorId,
    add_line,
    add_price_file_line,
    allocate_order,
    api_client,
    assert_inventory_units,
    inventory_for,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_part,
    make_price_file,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    read_line,
    read_order,
    read_part,
    read_price_file,
    read_return_authorization,
    request_return,
    setup_fulfilled_line,
    setup_will_call_order,
    validate_error,
    validate_success,
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


def _draft_price_file_raising_one_price():
    """A DRAFT price file that would take W10-PUMP from 12999 to 15999, plus a
    servicer identity to try to publish it with."""
    tier = _gold_tier()
    part = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    price_file = make_price_file(20260801, effective_at="2026-08-01T00:00:00Z")
    add_price_file_line(price_file, part, 15999)
    return {
        "part": part, "account": account, "price_file": price_file,
    }


def _two_accounts_one_of_which_owns_an_order():
    """Ace and Bell both buy on the same tier; only Bell has an order."""
    tier = _gold_tier()
    branch = make_branch(**STL_BRANCH)
    part = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    onlooker = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    owner = make_account(
        tier, business_name="Bell Appliance Service",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(owner, branch, purchase_order_ref="PO-5002")
    return {
        "branch": branch, "part": part, "onlooker": onlooker, "owner": owner,
        "order": order, "line": add_line(order, part, quantity=2),
    }


def _credit_cleared_order_at_st_louis(purchase_order_ref):
    """Three units approved on credit, still DRAFT, waiting for a counter."""
    return setup_will_call_order(
        stage="credit", quantity=3, branch_kwargs=dict(STL_BRANCH),
        on_hand_units=10, purchase_order_ref=purchase_order_ref,
    )


# ---------------------------------------------------------------------------
# A role that is not on the endpoint's list
# ---------------------------------------------------------------------------

class TestRoleAuthorization:

    def test_a_servicer_cannot_publish_the_price_book(self):
        """PRD §2.1: "If the headers are well-formed but the declared role is not
        listed among the authorized roles for the endpoint being called, the request
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `PricingAdmin` owns the catalog and the price book: parts,
        supersession links, model cross-references, pricing tiers, and price-file
        publication and rollback; it never touches accounts, orders, or money."
        PRD §3.7: "A new file starts with `price_file_status` equal to `DRAFT`, a
        `line_count` of zero, and `published_at` null."

        Design: Corner/rbac/servicer_cannot_publish_a_price_file_returns_403
        """
        world = _draft_price_file_raising_one_price()

        response = api_client.publish_price_file(
            world["price_file"]["id"],
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        price_file = read_price_file(world["price_file"]["id"])
        assert price_file["price_file_status"] == "DRAFT", (
            f"the refused publish leaves the file in draft, got "
            f"{price_file['price_file_status']}"
        )
        assert price_file["published_at"] is None

        part = read_part(world["part"]["id"])
        assert part["list_price_cents"] == 12999, (
            f"no repricing hop ran, got {part['list_price_cents']}"
        )
        assert part["version"] == 1


# ---------------------------------------------------------------------------
# One servicer reaching for another servicer's row
# ---------------------------------------------------------------------------

class TestAccountScope:

    def test_a_servicer_reading_another_accounts_order_is_refused(self):
        """PRD §2.1: "A `Servicer` acting on a `PartOrder`, `OrderLine`,
        `SubstituteRequest`, `ReturnAuthorization`, `WarrantyClaim`, or
        `ServicerAccount` that belongs to a different account is rejected with
        `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.7: "6. `ERR_ACCOUNT_SCOPE_VIOLATION` (403) — when the acting role is
        `Servicer`, `X-User-ID` equals the `servicer_account_id` of the targeted
        order, line, substitute request, return authorization, warranty claim, or
        account. Guards nine operations: `POST /part-orders`,
        `POST /part-orders/{id}/lines`, `POST /part-orders/{id}/cancel`,
        `POST /order-lines/{id}/cancel`, `POST /substitute-requests/{id}/withdraw`,
        `POST /return-authorizations`, `GET /part-orders/{id}`,
        `GET /servicer-accounts/{id}`, and
        `GET /servicer-accounts/{id}/credit-summary`."

        Design: Corner/rbac/servicer_cannot_read_another_servicers_order_returns_403
        """
        world = _two_accounts_one_of_which_owns_an_order()

        response = api_client.get_part_order(
            world["order"]["id"], make_servicer_headers(world["onlooker"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION)

        owned = validate_success(
            api_client.get_part_order(
                world["order"]["id"], make_servicer_headers(world["owner"]["id"])
            ),
            200,
        )
        assert owned["total_cents"] == 20798, (
            f"the owning servicer sees the 10399 x 2 order, got "
            f"{owned['total_cents']}"
        )
        assert owned["servicer_account_id"] == world["owner"]["id"]


# ---------------------------------------------------------------------------
# One branch reaching for another branch's work
# ---------------------------------------------------------------------------

class TestBranchScope:

    def test_only_the_pickup_branch_may_allocate_a_will_call_order(self):
        """PRD §2.1: "When `X-User-Role` is `BranchCounterRep`, `X-User-ID` is the
        `id` of the acting `Branch`."
        PRD §2.1: "Ownership checks compare `X-User-ID` to whichever branch foreign
        key the operation acts through: `pickup_branch_id` when a `WILL_CALL` order
        is allocated or handed over, an `allocation_branch_id` of one of the order's
        allocated lines when an `OVERNIGHT_DROP_SHIP` order is handed over,
        `return_branch_id` when a return is physically received, and `branch_id` when
        an inventory position is opened or adjusted."
        PRD §3.6: "The acting branch matters: for a `WILL_CALL` order the caller's
        `X-User-ID` must be the order's `pickup_branch_id`, that branch must be
        `OPEN`, and its `will_call_enabled` must be true; for an
        `OVERNIGHT_DROP_SHIP` order the caller's `X-User-ID` must resolve to a branch
        whose `branch_status` is `OPEN`."

        Design: Corner/rbac/branch_rep_cannot_allocate_for_another_branch_returns_403
        """
        world = _credit_cleared_order_at_st_louis("PO-5003")
        other_counter = make_branch(
            code="DAL", name="Dallas DC", region_code="SW",
            will_call_enabled=True, cutoff_hour_utc=18,
            overnight_surcharge_cents=100,
        )

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(other_counter["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BRANCH_SCOPE_VIOLATION)

        assert read_order(world["order"]["id"])["fulfillment_status"] == "DRAFT"
        line = read_line(world["line"]["id"])
        assert line["line_status"] == "RESOLVED"
        assert line["allocation_branch_id"] is None
        assert_inventory_units(
            inventory_for(world["branch"]["id"], world["part"]["id"]),
            on_hand=10, reserved=0, available=10,
        )

        allocated = allocate_order(world["order"], world["branch"])
        assert allocated["fulfillment_status"] == "ALLOCATED", (
            "the pickup branch's own counter is entitled to the same call"
        )
        assert_inventory_units(
            inventory_for(world["branch"]["id"], world["part"]["id"]),
            on_hand=10, reserved=3, available=7,
        )


# ---------------------------------------------------------------------------
# The waiver cross-check
# ---------------------------------------------------------------------------

class TestSegregationOfDuties:

    def test_the_operator_who_approved_the_credit_cannot_waive_the_fee(self):
        """PRD §2.8: "When a credit decision is taken on an order, the acting
        operator's `X-User-ID` is stored on the order as `credit_decided_by_user_id`."
        PRD §2.8: "Later, if a return authorization against a line of that same
        order is approved with `waive_restocking_fee` set to true, the approving
        operator's `X-User-ID` must differ from that stored value."
        PRD §2.8: "If they match, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.9: "Finally, if `fee_waived` is true, the rate collapses to 0
        regardless of everything above."
        PRD §3.9: "Approval moves it `REQUESTED → APPROVED`, records `fee_waived`
        from the supplied flag, and computes all four money figures."

        Design: Corner/rbac/credit_approver_cannot_also_waive_the_restocking_fee
        """
        world = setup_fulfilled_line(
            quantity=1, branch_kwargs=dict(STL_BRANCH), on_hand_units=10,
            account_kwargs={"core_liability_limit_cents": 5000000},
            purchase_order_ref="PO-5004", tracking_ref="WILLCALL-5004",
        )
        assert read_order(world["order"]["id"])["credit_decided_by_user_id"] == (
            "cm-user-1"
        )
        authorization = request_return(
            world["account"], world["line"], 1, "NO_LONGER_NEEDED",
            world["branch"],
        )

        waiver = {
            "decision": "APPROVE",
            "waive_restocking_fee": True,
            "decision_note": "goodwill waiver by the credit approver",
        }
        response = api_client.decide_return_authorization(
            authorization["id"], waiver, CREDIT_MANAGER
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        refused = read_return_authorization(authorization["id"])
        assert refused["ra_status"] == "REQUESTED", (
            f"the refused decision decides nothing, got {refused['ra_status']}"
        )
        assert refused["fee_waived"] is False

        approved = validate_success(
            api_client.decide_return_authorization(
                authorization["id"], waiver, CREDIT_MANAGER_TWO
            ),
            200,
        )
        assert approved["ra_status"] == "APPROVED", (
            "a second operator may issue the identical waiver"
        )
        assert approved["fee_waived"] is True
        assert approved["restocking_fee_pct"] == pytest.approx(0.0, abs=1e-9)
        assert approved["restocking_fee_cents"] == 0
        assert approved["credit_amount_cents"] == 10399, (
            f"the whole invoiced unit price comes back, got "
            f"{approved['credit_amount_cents']}"
        )


# ---------------------------------------------------------------------------
# The operator the branch-scope rule does not bind
# ---------------------------------------------------------------------------

class TestBreakGlassAllocation:

    def test_the_platform_admin_allocates_without_being_a_branch(self):
        """PRD §2.1: "A `PlatformAdmin` registers branches and controls the logical
        clock, and is additionally permitted on every business write as a break-glass
        operator — but it is still bound by the segregation-of-duties rule on
        restocking-fee waivers described in §2.8."
        PRD §2.7: "7. `ERR_BRANCH_SCOPE_VIOLATION` (403) — when the acting role is
        `BranchCounterRep`, `X-User-ID` equals the branch the operation acts for, as
        described in §2.1. Guards five operations:
        `POST /part-orders/{id}/allocate`, `POST /part-orders/{id}/fulfill`,
        `POST /return-authorizations/{id}/receive`, `POST /inventory-records`, and
        `POST /inventory-records/{id}/adjustments`."
        PRD §3.6: "Each line that finds a branch moves `RESOLVED → ALLOCATED`,
        records the winning branch as its `allocation_branch_id`, raises that
        inventory record's `reserved_units` by the line's `quantity`, has its
        `available_units` recomputed, and increments that inventory record's
        `version`."
        PRD §3.6: "A `WILL_CALL` order never carries freight at all: its
        `freight_cents` is zero, full stop, because the customer collects."

        Design: Corner/rbac/platform_admin_break_glass_allocates_without_a_branch_identity
        """
        world = _credit_cleared_order_at_st_louis("PO-5005")

        response = api_client.allocate_part_order(
            world["order"]["id"], PLATFORM_ADMIN
        )
        order = validate_success(response, 200)

        assert order["fulfillment_status"] == "ALLOCATED", (
            f"the break-glass operator is not held to a branch identity, got "
            f"{order['fulfillment_status']}"
        )
        assert order["freight_cents"] == 0
        assert order["total_cents"] == 31197, (
            f"Expected the quoted 10399 x 3, got {order['total_cents']}"
        )

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "ALLOCATED"
        assert line["allocation_branch_id"] == world["branch"]["id"]

        assert_inventory_units(
            inventory_for(world["branch"]["id"], world["part"]["id"]),
            on_hand=10, reserved=3, available=7,
        )
