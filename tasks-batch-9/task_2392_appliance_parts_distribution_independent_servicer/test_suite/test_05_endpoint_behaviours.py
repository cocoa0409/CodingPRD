"""Endpoint-level behaviour: a partial branch amendment, the periodic tier review,
the purely computed credit summary, the two-directional cross-reference junction,
and the will-call precondition on order creation."""
from test_helpers import (
    CREDIT_MANAGER,
    PLATFORM_ADMIN,
    PRICING_ADMIN,
    ApiErrorId,
    add_line,
    allocate_order,
    api_client,
    approve_credit,
    branch_patch_payload,
    fulfill_order,
    list_orders,
    list_xrefs,
    make_account,
    make_branch,
    make_certification,
    make_inventory,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    make_xref,
    model_part_xref_payload,
    open_will_call_order,
    patch_account,
    read_account,
    read_line,
    read_order,
    validate_error,
    validate_success,
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

def _account_demoted_after_a_large_invoiced_order():
    """A two-tier catalog where the account has shipped 5,091,840 cents of motors
    and has since been parked on the entry tier."""
    entry = make_pricing_tier(
        tier_code="SILVER", name="Silver Contract",
        electrical=0.10, mechanical=0.10, cosmetic=0.10, sealed_system=0.10,
        min_annual_volume_cents=0,
    )
    contract = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(**STL_BRANCH)
    motor = make_part(
        part_number="W10-MOTOR", oem_code="WHIRLPOOL", description="Drive motor",
        category="MECHANICAL", list_price_cents=128000, weight_grams=9000,
    )
    account = make_account(
        contract, business_name="High Volume Service",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, motor, on_hand_units=60, reorder_point=5)

    order = open_will_call_order(account, branch, purchase_order_ref="PO-3014")
    line = add_line(order, motor, quantity=51)
    approve_credit(order)
    allocate_order(order, branch)
    fulfill_order(order, branch, tracking_ref="WILLCALL-3014")

    patch_account(account["id"], pricing_tier_id=entry["id"])
    return {
        "entry": entry, "contract": contract, "branch": branch, "part": motor,
        "account": account, "order": order, "line": line,
    }


def _account_with_one_draft_order_and_one_certification():
    """A 100,000-cent limit, a single draft order worth 20,798 cents, and one
    effective certification."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(**STL_BRANCH)
    pump = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=100000, core_liability_limit_cents=50000,
    )
    make_certification(
        account, technician_name="Dana Ruiz", oem_code="WHIRLPOOL",
        cert_level="BASIC", training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)

    order = open_will_call_order(account, branch, purchase_order_ref="PO-3015")
    return {
        "branch": branch, "part": pump, "account": account, "order": order,
        "line": add_line(order, pump, quantity=2),
    }


# ---------------------------------------------------------------------------
# Partial amendment of a branch
# ---------------------------------------------------------------------------

class TestBranchAmendment:

    def test_a_patch_touches_only_the_fields_it_carries_and_bumps_the_version(self):
        """PRD §3.3: "A branch is created with `branch_status` equal to `OPEN`; a
        `PlatformAdmin` may later amend `name`, `will_call_enabled`,
        `cutoff_hour_utc`, `overnight_surcharge_cents`, or `branch_status`."
        PRD §2.4: "Almost every resource additionally carries `updated_at`, an ISO
        8601 UTC timestamp refreshed on every mutation, and `version`, an integer
        that starts at 1 on creation and increments by exactly 1 on every mutation
        of that row — including mutations the server performs on its own initiative
        as part of a cascade, and including mutations that only change computed
        money fields."

        Design: Corner/endpoints/branch_patch_updates_will_call_settings_and_bumps_version
        """
        branch = make_branch(**STL_BRANCH)
        assert branch["version"] == 1

        response = api_client.update_branch(
            branch["id"],
            branch_patch_payload(will_call_enabled=False, cutoff_hour_utc=22),
            PLATFORM_ADMIN,
        )
        patched = validate_success(response, 200)

        assert patched["will_call_enabled"] is False
        assert patched["cutoff_hour_utc"] == 22
        assert patched["overnight_surcharge_cents"] == 300, (
            "a field the body never mentioned keeps its value"
        )
        assert patched["name"] == "St Louis DC"
        assert patched["region_code"] == "MW"
        assert patched["branch_status"] == "OPEN"
        assert patched["version"] == 2, (
            f"one amendment is exactly one mutation, got {patched['version']}"
        )


# ---------------------------------------------------------------------------
# The periodic review
# ---------------------------------------------------------------------------

class TestTierReview:

    def test_the_review_reassigns_the_largest_eligible_volume_floor(self):
        """PRD §3.5: "Second, `rolling_12m_volume_cents` is recomputed as the sum of
        `invoiced_total_cents` over the account's orders whose `settlement_status` is
        `INVOICED` or `PAID` and whose whole days elapsed since `fulfilled_at` are at
        most 365; cancelled, written-off, and unfulfilled orders never contribute."
        PRD §3.5: "Third, the account is reassigned a tier: the eligible tiers are
        those whose `min_annual_volume_cents` is less than or equal to that volume,
        and the account's `pricing_tier_id` becomes the eligible tier with the
        **largest** `min_annual_volume_cents`, breaking ties by taking the smaller
        `tier_code` in ascending order; if no tier is eligible at all, the account
        falls to the tier with the **smallest** `min_annual_volume_cents`, breaking
        ties the same way."
        PRD §3.5: "Fourth, `delinquency_score` is refreshed from the **lifetime**
        variant, and if that score is strictly below 40 the account moves from
        `ACTIVE` to `CREDIT_HOLD` with the full freeze cascade."
        PRD §3.5: "Existing lines are not repriced by a reassignment — only future
        line creations and future hand-over invoicing see the new tier."

        Design: Corner/endpoints/tier_review_promotes_the_account_to_the_highest_qualifying_tier
        """
        world = _account_demoted_after_a_large_invoiced_order()
        assert read_account(world["account"]["id"])["pricing_tier_id"] == (
            world["entry"]["id"]
        )

        response = api_client.tier_review(world["account"]["id"], CREDIT_MANAGER)
        reviewed = validate_success(response, 200)

        assert reviewed["pricing_tier_id"] == world["contract"]["id"], (
            "5,091,840 cents clears the 5,000,000-cent floor, which is the largest "
            "eligible one"
        )
        assert reviewed["rolling_12m_volume_cents"] == 5091840, (
            f"Expected the invoiced 99840 x 51, got "
            f"{reviewed['rolling_12m_volume_cents']}"
        )
        assert reviewed["account_status"] == "ACTIVE"
        assert reviewed["delinquency_score"] == 80, (
            f"a clean account with no certifications sits at the base 80, got "
            f"{reviewed['delinquency_score']}"
        )

        line = read_line(world["line"]["id"])
        assert line["unit_price_cents"] == 99840, (
            f"Expected 128000 x (1 - 0.20 - 0.02) at fifty-one units, got "
            f"{line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 5091840
        assert read_order(world["order"]["id"])["invoiced_total_cents"] == 5091840


# ---------------------------------------------------------------------------
# The computed read
# ---------------------------------------------------------------------------

class TestCreditSummary:

    def test_the_summary_reconciles_with_the_exposure_and_scoring_rules(self):
        """PRD §2.10: "The credit-summary read for an account returns
        `credit_limit_cents`, `credit_used_cents`, `available_credit_cents` (the
        limit minus the used exposure), `core_liability_cents`,
        `core_liability_limit_cents`, `delinquency_score_rolling`,
        `delinquency_score_lifetime`, `rolling_12m_volume_cents`,
        `open_order_count` (the number of that account's orders whose exposure
        currently counts toward `credit_used_cents`), and `effective_cert_count`."
        PRD §3.5: "Compute the open exposure by walking the account's orders and
        contributing, per order: `invoiced_total_cents` when `settlement_status` is
        `INVOICED`; `total_cents` when `settlement_status` is `PENDING_CREDIT` or
        `CREDIT_APPROVED` **and** `fulfillment_status` is `DRAFT`, `ALLOCATED`, or
        `HELD`; and nothing at all otherwise, which covers `PAID`,
        `CREDIT_DECLINED`, `WRITTEN_OFF`, and cancelled orders."
        PRD §3.5: "**Delinquency scoring** starts every account at a base of 80
        points and adjusts from there."
        PRD §3.5: "A bonus of five points is added for each currently effective
        technician certification, but that bonus is capped at fifteen points no
        matter how many certifications the account holds."

        Design: Corner/endpoints/credit_summary_read_reconciles_with_the_exposure_calculation
        """
        world = _account_with_one_draft_order_and_one_certification()

        response = api_client.get_credit_summary(
            world["account"]["id"], make_servicer_headers(world["account"]["id"])
        )
        summary = validate_success(response, 200)

        assert summary["credit_limit_cents"] == 100000
        assert summary["credit_used_cents"] == 20798, (
            f"Expected the draft order's 10399 x 2 to count, got "
            f"{summary['credit_used_cents']}"
        )
        assert summary["available_credit_cents"] == 79202, (
            f"Expected 100000 - 20798, got {summary['available_credit_cents']}"
        )
        assert summary["core_liability_cents"] == 0
        assert summary["core_liability_limit_cents"] == 50000
        assert summary["rolling_12m_volume_cents"] == 0, (
            "nothing has been invoiced yet"
        )
        assert summary["open_order_count"] == 1
        assert summary["effective_cert_count"] == 1
        assert summary["delinquency_score_rolling"] == 85, (
            f"Expected the base 80 plus one five-point certification bonus, got "
            f"{summary['delinquency_score_rolling']}"
        )
        assert summary["delinquency_score_lifetime"] == 85, (
            "with no penalty rows at all the two variants cannot diverge"
        )


# ---------------------------------------------------------------------------
# Traversing the cross-reference junction
# ---------------------------------------------------------------------------

class TestCrossReferenceTraversal:

    def test_one_model_reaches_two_parts_and_one_part_reaches_one_model(self):
        """PRD §2.10: "The cross-reference list can be filtered by `model_number` to
        find the parts that fit an appliance, or by `part_id` to find the models a
        part fits."
        PRD §3.1: "Each cross-reference row names the `model_number` of the
        appliance, the `part_id` it fits, the `position_code` identifying its place
        in the exploded view, and an `xref_source` of either `OEM_PUBLICATION` or
        `MANUAL_ENTRY`."

        Design: Corner/endpoints/model_part_xref_links_one_model_to_two_parts_in_both_directions
        """
        pump = make_part(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999, weight_grams=5200,
        )
        motor = make_part(
            part_number="W10-MOTOR", oem_code="WHIRLPOOL",
            description="Drive motor", category="MECHANICAL",
            list_price_cents=128000, weight_grams=9000,
        )
        first = make_xref(
            pump, model_number="WTW5000DW1", position_code="P-14",
            xref_source="OEM_PUBLICATION",
        )

        response = api_client.create_model_part_xref(
            model_part_xref_payload(
                motor["id"], model_number="WTW5000DW1", position_code="M-02",
                xref_source="MANUAL_ENTRY",
            ),
            PRICING_ADMIN,
        )
        second = validate_success(response, 201)
        assert second["part_id"] == motor["id"]
        assert second["xref_source"] == "MANUAL_ENTRY"

        by_model = list_xrefs(model_number="WTW5000DW1")
        assert len(by_model) == 2, (
            f"the appliance now fits two parts, got {len(by_model)}"
        )

        by_part = list_xrefs(part_id=pump["id"])
        assert len(by_part) == 1, (
            f"the pump is listed against one model only, got {len(by_part)}"
        )
        assert by_part[0]["id"] == first["id"]


# ---------------------------------------------------------------------------
# The will-call precondition
# ---------------------------------------------------------------------------

class TestWillCallPrecondition:

    def test_a_pickup_branch_without_a_counter_cannot_take_the_order(self):
        """PRD §3.4: "Getting that pairing wrong is rejected with
        `ERR_FULFILLMENT_MODE_MISMATCH`, and naming a pickup branch whose
        `will_call_enabled` is false is rejected with `ERR_WILL_CALL_NOT_ENABLED`."
        PRD §2.9: "The system never defers a cascade to a later request, never
        leaves a derived aggregate stale, and never partially applies a cascade: if
        the triggering write is rejected, nothing downstream of it is written
        either."

        Design: Corner/endpoints/will_call_order_on_a_branch_without_will_call_is_rejected
        """
        tier = make_pricing_tier(
            tier_code="GOLD", name="Gold Contract",
            electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
            min_annual_volume_cents=5000000,
        )
        closed_counter = make_branch(
            code="DAL", name="Dallas DC", region_code="SW",
            will_call_enabled=False, cutoff_hour_utc=18,
            overnight_surcharge_cents=100,
        )
        account = make_account(
            tier, business_name="Ace Appliance Repair",
            oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
            credit_limit_cents=10000000, core_liability_limit_cents=5000000,
        )

        response = api_client.create_part_order(
            will_call_order_payload(
                account["id"], closed_counter["id"], purchase_order_ref="PO-3016"
            ),
            make_servicer_headers(account["id"]),
        )
        validate_error(response, ApiErrorId.ERR_WILL_CALL_NOT_ENABLED)

        assert list_orders(servicer_account_id=account["id"]) == [], (
            "the refused create leaves no order behind"
        )
