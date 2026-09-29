"""Operations gated on the state of a neighbouring row: the owning account's
standing, the covering certification, and the acting branch's posture."""
from test_helpers import (
    WARRANTY_ADMIN,
    ApiErrorId,
    add_line,
    api_client,
    approve_credit,
    assert_inventory_units,
    inventory_for,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_certification,
    make_claim,
    make_inventory,
    make_part,
    make_pricing_tier,
    open_will_call_order,
    patch_account,
    patch_branch,
    read_account,
    read_certification,
    read_claim,
    read_line,
    read_order,
    revoke_certification,
    setup_catalog,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _credit_approved_order_whose_account_is_frozen():
    """A credit-approved will-call order whose owning account was then moved to
    CREDIT_HOLD while the order was still in DRAFT."""
    world = setup_catalog(
        branch_kwargs={
            "code": "STL", "name": "St Louis DC", "region_code": "MW",
            "will_call_enabled": True, "cutoff_hour_utc": 20,
            "overnight_surcharge_cents": 300,
        },
        on_hand_units=10,
        account_kwargs={"core_liability_limit_cents": 5000000},
    )
    order = open_will_call_order(world["account"], world["branch"])
    world["order"] = order
    world["line"] = add_line(order, world["part"], quantity=1)
    approve_credit(order)
    patch_account(world["account"]["id"], account_status="CREDIT_HOLD")
    return world


def _shipped_compressor_claim_whose_certification_was_revoked():
    """A sealed-system compressor shipped under a SEALED_SYSTEM certification, a
    draft claim raised against it, and the certification then revoked."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    compressor = make_part(
        part_number="W10-COMP", oem_code="WHIRLPOOL",
        description="Sealed system compressor", category="SEALED_SYSTEM",
        list_price_cents=320000, weight_grams=12000,
        core_required=True, core_deposit_cents=8500,
    )
    account = make_account(
        tier, business_name="Sealed System Pros",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    cert = make_certification(
        account, technician_name="Dana Ruiz", oem_code="WHIRLPOOL",
        cert_level="SEALED_SYSTEM",
        training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    make_inventory(branch, compressor, on_hand_units=5, reorder_point=1)

    order = open_will_call_order(account, branch)
    line = add_line(order, compressor, quantity=1)
    approve_credit(order)
    branch_headers = make_branch_counter_rep_headers(branch["id"])
    validate_success(api_client.allocate_part_order(order["id"], branch_headers), 200)
    validate_success(
        api_client.fulfill_part_order(
            order["id"], {"tracking_ref": "WILLCALL-COMP"}, branch_headers
        ),
        200,
    )

    claim = make_claim(
        account, line, defect_code="COMPRESSOR_FAIL",
        appliance_model_number="WRS325SDHZ",
    )
    revoke_certification(cert["id"], "technician left the company")
    return {
        "branch": branch, "part": compressor, "account": account, "cert": cert,
        "order": order, "line": line, "claim": claim,
    }


def _credit_approved_order_whose_pickup_branch_is_frozen():
    """A credit-approved will-call order for two pumps whose pickup branch was
    then put into COUNT_FREEZE."""
    world = setup_catalog(
        branch_kwargs={
            "code": "STL", "name": "St Louis DC", "region_code": "MW",
            "will_call_enabled": True, "cutoff_hour_utc": 20,
            "overnight_surcharge_cents": 300,
        },
        on_hand_units=10,
        account_kwargs={"core_liability_limit_cents": 5000000},
    )
    order = open_will_call_order(world["account"], world["branch"])
    world["order"] = order
    world["line"] = add_line(order, world["part"], quantity=2)
    approve_credit(order)
    patch_branch(world["branch"]["id"], branch_status="COUNT_FREEZE")
    return world


# ---------------------------------------------------------------------------
# Account standing gates allocation
# ---------------------------------------------------------------------------

class TestAllocationDependsOnAccountStanding:

    def test_a_frozen_account_cannot_have_its_order_allocated(self):
        """PRD §2.7: "8. `ERR_SERVICER_NOT_ACTIVE` (409) — the owning account's
        `account_status` is `ACTIVE`. Accounts in `CREDIT_HOLD` or `SUSPENDED` may
        not open orders, add lines, be allocated, be shipped, or file warranty
        claim submissions. Guards five operations: `POST /part-orders`,
        `POST /part-orders/{id}/lines`, `POST /part-orders/{id}/allocate`,
        `POST /part-orders/{id}/fulfill`, and `POST /warranty-claims/{id}/submit`."
        PRD §3.6: "The order must be in `DRAFT` with a `settlement_status` of
        either `CREDIT_APPROVED` or `PAID`, its account must be `ACTIVE`, and it
        must have at least one line whose `line_status` is not `CANCELLED` — an
        order with nothing left in it is rejected with `ERR_ORDER_HAS_NO_LINES`
        rather than allocating an empty shipment."

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_while_owning_servicer_account_is_on_credit_hold
        """
        world = _credit_approved_order_whose_account_is_frozen()

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SERVICER_NOT_ACTIVE)

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "DRAFT"
        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=0, available=10)

    def test_the_same_allocation_succeeds_once_the_account_is_active_again(self):
        """PRD §3.2: "An account's `account_status` is one of `ACTIVE`,
        `CREDIT_HOLD`, or `SUSPENDED`, and it cycles between the first two."
        PRD §3.2: "Orders of the same account that are already `FULFILLED` or
        `CANCELLED`, and orders still in `DRAFT`, are left exactly as they were."
        PRD §3.6: "Each line that finds a branch moves `RESOLVED → ALLOCATED`,
        records the winning branch as its `allocation_branch_id`, raises that
        inventory record's `reserved_units` by the line's `quantity`, has its
        `available_units` recomputed, and increments that inventory record's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_while_owning_servicer_account_is_on_credit_hold
        """
        world = _credit_approved_order_whose_account_is_frozen()
        validate_error(
            api_client.allocate_part_order(
                world["order"]["id"],
                make_branch_counter_rep_headers(world["branch"]["id"]),
            ),
            ApiErrorId.ERR_SERVICER_NOT_ACTIVE,
        )

        patch_account(world["account"]["id"], account_status="ACTIVE")
        allocated = validate_success(
            api_client.allocate_part_order(
                world["order"]["id"],
                make_branch_counter_rep_headers(world["branch"]["id"]),
            ),
            200,
        )
        assert allocated["fulfillment_status"] == "ALLOCATED"

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "ALLOCATED"
        assert line["allocation_branch_id"] == world["branch"]["id"]

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=1, available=9)

        order = read_order(world["order"]["id"])
        assert order["total_cents"] == 10399


# ---------------------------------------------------------------------------
# Certification standing gates warranty submission
# ---------------------------------------------------------------------------

class TestWarrantySubmissionDependsOnCertification:

    def test_submission_is_refused_once_the_covering_certification_is_revoked(self):
        """PRD §3.2: "Revocation moves `cert_status` from `ACTIVE` to `REVOKED`,
        or from `EXPIRED` to `REVOKED`, and immediately makes `is_effective` false
        — which in turn gates new order lines for that OEM and level and blocks
        warranty-claim submissions that depended on it."
        PRD §3.8: "Exceeding the ninety-day window is rejected with
        `ERR_WARRANTY_PERIOD_EXPIRED`; lacking the certification is rejected with
        `ERR_TECHNICIAN_CERT_REQUIRED`, which makes a revocation by the warranty
        desk immediately felt on the claim side as well as the ordering side."

        Design: Difficulty/cross_entity_state_dependency/warranty_submission_blocked_after_the_covering_certification_is_revoked
        """
        world = _shipped_compressor_claim_whose_certification_was_revoked()

        response = api_client.submit_warranty_claim(
            world["claim"]["id"], {"oem_reference": "WP-SS-001"}, WARRANTY_ADMIN
        )
        validate_error(response, ApiErrorId.ERR_TECHNICIAN_CERT_REQUIRED)

        cert = read_certification(world["cert"]["id"])
        assert cert["cert_status"] == "REVOKED"
        assert cert["is_effective"] is False

        claim = read_claim(world["claim"]["id"])
        assert claim["claim_status"] == "DRAFT", (
            f"the refused submission leaves the claim in DRAFT, got "
            f"{claim['claim_status']}"
        )
        assert claim["submitted_at"] is None

    def test_the_shipment_that_the_claim_hangs_off_is_left_fully_intact(self):
        """PRD §3.6: "Each shipping line also snapshots `core_deposit_cents` from
        its resolved part when that part has `core_required` true, and 0 when it
        does not."
        PRD §3.6: "The account's `core_liability_cents` rises by each shipped
        line's `core_deposit_cents` multiplied by its `quantity` for core-required
        parts, and `credit_used_cents` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/warranty_submission_blocked_after_the_covering_certification_is_revoked
        """
        world = _shipped_compressor_claim_whose_certification_was_revoked()
        validate_error(
            api_client.submit_warranty_claim(
                world["claim"]["id"], {"oem_reference": "WP-SS-001"}, WARRANTY_ADMIN
            ),
            ApiErrorId.ERR_TECHNICIAN_CERT_REQUIRED,
        )

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "SHIPPED"
        assert line["core_deposit_cents"] == 8500, (
            f"Expected the snapshotted deposit 8500, got {line['core_deposit_cents']}"
        )

        order = read_order(world["order"]["id"])
        assert order["invoiced_total_cents"] == 296500, (
            f"Expected 288000 ship-date subtotal plus 8500 deposit, got "
            f"{order['invoiced_total_cents']}"
        )

        account = read_account(world["account"]["id"])
        assert account["core_liability_cents"] == 8500


# ---------------------------------------------------------------------------
# Branch posture gates allocation
# ---------------------------------------------------------------------------

class TestAllocationDependsOnBranchPosture:

    def test_a_branch_in_count_freeze_cannot_reserve_stock(self):
        """PRD §2.7: "9. `ERR_BRANCH_NOT_OPEN` (409) — every branch the operation
        acts through has `branch_status` equal to `OPEN`. A branch in
        `COUNT_FREEZE` blocks reservations and receipts; a `CLOSED` branch blocks
        everything. Guards four operations: `POST /part-orders/{id}/allocate`,
        `POST /part-orders/{id}/fulfill`,
        `POST /return-authorizations/{id}/receive`, and
        `POST /inventory-records/{id}/adjustments`."
        PRD §3.3: "The three postures are `OPEN`, `COUNT_FREEZE`, and `CLOSED`,
        and only an `OPEN` branch is ever an allocation candidate — putting a
        branch into `COUNT_FREEZE` or `CLOSED` silently removes it from future
        candidate sets without disturbing reservations it already holds."

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_while_the_pickup_branch_is_in_count_freeze
        """
        world = _credit_approved_order_whose_pickup_branch_is_frozen()

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BRANCH_NOT_OPEN)

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert read_line(world["line"]["id"])["line_status"] == "RESOLVED"
        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=0, available=10)

    def test_reopening_the_branch_lets_the_same_allocation_through(self):
        """PRD §3.3: "A branch is created with `branch_status` equal to `OPEN`; a
        `PlatformAdmin` may later amend `name`, `will_call_enabled`,
        `cutoff_hour_utc`, `overnight_surcharge_cents`, or `branch_status`."
        PRD §3.6: "For a `WILL_CALL` order the candidate set is further narrowed
        to the single position at the order's `pickup_branch_id`, and that branch
        must additionally have `will_call_enabled` true."

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_while_the_pickup_branch_is_in_count_freeze
        """
        world = _credit_approved_order_whose_pickup_branch_is_frozen()
        validate_error(
            api_client.allocate_part_order(
                world["order"]["id"],
                make_branch_counter_rep_headers(world["branch"]["id"]),
            ),
            ApiErrorId.ERR_BRANCH_NOT_OPEN,
        )

        patch_branch(world["branch"]["id"], branch_status="OPEN")
        allocated = validate_success(
            api_client.allocate_part_order(
                world["order"]["id"],
                make_branch_counter_rep_headers(world["branch"]["id"]),
            ),
            200,
        )
        assert allocated["fulfillment_status"] == "ALLOCATED"

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=2, available=8)

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 20798
        assert order["freight_cents"] == 0

        account = read_account(world["account"]["id"])
        assert account["account_status"] == "ACTIVE", (
            "the account was never frozen in this scenario"
        )
