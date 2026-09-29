"""Cross-cutting layers on top of the workflows: the two optimistic-concurrency
tokens, the cumulative delinquency threshold that flips an account into a freeze,
and the guarantee that a write's own response already carries its recomputed
aggregates."""
from test_helpers import (
    PRICING_ADMIN,
    ApiErrorId,
    add_line,
    allocate_order,
    api_client,
    approve_credit,
    assert_inventory_units,
    fulfill_order,
    inventory_for,
    list_order_lines,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_certification,
    make_claim,
    make_inventory,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    order_line_payload,
    read_account,
    read_certification,
    read_claim,
    read_order,
    read_part,
    record_oem_outcome,
    record_supersession,
    revoke_certification,
    run_tier_review,
    setup_will_call_order,
    submit_claim,
    supersession_payload,
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


def _pump():
    return make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )


def _order_that_already_took_one_line():
    """A will-call order whose first two-unit line has already moved it to
    version 2, with the version-1 token kept for replay."""
    tier = _gold_tier()
    branch = make_branch(**STL_BRANCH)
    part = _pump()
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(account, branch, purchase_order_ref="PO-4011")
    stale_token = order["version"]
    first_line = add_line(order, part, quantity=2, expected_version=stale_token)
    return {
        "branch": branch, "part": part, "account": account, "order": order,
        "line": first_line, "stale_token": stale_token,
    }


def _three_denied_claims_pending_on_one_account():
    """Three shipped units, three submitted claims, two of them already denied and
    the certification revoked, so the lifetime score sits at exactly 40."""
    tier = _gold_tier()
    branch = make_branch(**STL_BRANCH)
    part = _pump()
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    certification = make_certification(
        account, technician_name="R. Diaz", oem_code="WHIRLPOOL",
        cert_level="BASIC", training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    make_inventory(branch, part, on_hand_units=10, reorder_point=2)

    order = open_will_call_order(account, branch, purchase_order_ref="PO-4012")
    lines = [add_line(order, part, quantity=1) for _ in range(3)]
    approve_credit(order)
    allocate_order(order, branch)
    fulfill_order(order, branch, tracking_ref="WILLCALL-4012")

    claims = []
    for line, defect, reference in zip(
        lines,
        ("PUMP-SEIZED", "PUMP-LEAK", "PUMP-NOISE"),
        ("WP-4012-1", "WP-4012-2", "WP-4012-3"),
    ):
        claim = make_claim(
            account, line, defect_code=defect,
            appliance_model_number="WTW5000DW1",
        )
        submit_claim(claim["id"], reference)
        claims.append(claim)

    record_oem_outcome(
        claims[0]["id"], "DENIED", oem_reference="WP-4012-1",
        oem_note="no defect found",
    )
    record_oem_outcome(
        claims[1]["id"], "DENIED", oem_reference="WP-4012-2",
        oem_note="installer damage",
    )
    revoke_certification(
        certification["id"], "technician left the business"
    )
    return {
        "tier": tier, "branch": branch, "part": part, "account": account,
        "certification": certification, "order": order, "lines": lines,
        "claims": claims,
    }


# ---------------------------------------------------------------------------
# The order-version token
# ---------------------------------------------------------------------------

class TestStaleOrderVersion:

    def test_replaying_the_first_lines_token_adds_no_second_line(self):
        """PRD §2.6: "Adding a line to an order requires the request to carry
        `expected_part_order_version`, holding the `version` of the target
        `PartOrder` as the client last observed it."
        PRD §2.6: "If it does not equal the order's current `version`, the request is
        rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and no line is created."
        PRD §2.6: "Note that a second line for the same part and quantity is a
        perfectly legitimate second line — repeatability is the norm here, so the
        version check is the only defence."
        PRD §2.7: "22. `ERR_STALE_ORDER_VERSION` (412) —
        `expected_part_order_version` equals the order's current `version`. Guards
        `POST /part-orders/{id}/lines`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_part_order_version_on_line_add_returns_412
        """
        world = _order_that_already_took_one_line()
        assert world["stale_token"] == 1
        assert read_order(world["order"]["id"])["version"] == 2, (
            "the accepted line is itself a mutation of the order"
        )

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(world["part"]["id"], 1, world["stale_token"]),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION)

        order = read_order(world["order"]["id"])
        assert order["version"] == 2, (
            f"the refused add is not a mutation, got version {order['version']}"
        )
        assert order["subtotal_cents"] == 20798, (
            f"Expected the first line's 10399 x 2 alone, got "
            f"{order['subtotal_cents']}"
        )

        rows = list_order_lines(part_order_id=world["order"]["id"])
        assert len(rows) == 1, (
            f"the order still holds one line, got {len(rows)}"
        )


# ---------------------------------------------------------------------------
# The part-version token
# ---------------------------------------------------------------------------

class TestStalePartVersion:

    def test_replaying_the_first_supersessions_token_leaves_the_pointer_alone(self):
        """PRD §2.6: "Recording a supersession pointer on a part requires the request
        to carry `expected_part_version`, holding the `version` of the target `Part`
        as the client last observed it."
        PRD §2.6: "If it does not equal the part's current `version`, the request is
        rejected with `ERR_STALE_PART_VERSION` (HTTP 412) and no pointer is written."
        PRD §2.6: "A supersession legitimately overwrites any pointer already
        recorded, so a sequential retry would succeed; the version check is what stops
        a writer from silently clobbering a chain link — or a lifecycle change applied
        by a price-file publication — that it never saw."
        PRD §2.7: "23. `ERR_STALE_PART_VERSION` (412) — `expected_part_version`
        equals the part's current `version`. Guards `POST /parts/{id}/supersession`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_part_version_on_supersession_returns_412
        """
        replacement = make_part(
            part_number="W10-PUMP-B", oem_code="WHIRLPOOL",
            description="Drain pump rev B", category="MECHANICAL",
            list_price_cents=12500, weight_grams=5200,
        )
        rival = make_part(
            part_number="W10-PUMP-C", oem_code="WHIRLPOOL",
            description="Drain pump rev C", category="MECHANICAL",
            list_price_cents=13000, weight_grams=5200,
        )
        original = make_part(
            part_number="W10-PUMP-A", oem_code="WHIRLPOOL",
            description="Drain pump rev A", category="MECHANICAL",
            list_price_cents=12000, weight_grams=5200,
        )
        stale_token = original["version"]
        assert stale_token == 1

        linked = record_supersession(
            original, replacement, expected_part_version=stale_token
        )
        assert linked["version"] == 2

        response = api_client.record_supersession(
            original["id"],
            supersession_payload(rival["id"], stale_token),
            PRICING_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_STALE_PART_VERSION)

        part = read_part(original["id"])
        assert part["version"] == 2, (
            f"the refused write is not a mutation, got version {part['version']}"
        )
        assert part["superseded_by_part_id"] == replacement["id"], (
            "the pointer the writer never saw is not clobbered"
        )
        assert part["lifecycle_status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# The cumulative delinquency threshold
# ---------------------------------------------------------------------------

class TestDelinquencyThreshold:

    def test_a_score_of_exactly_forty_survives_and_one_more_denial_freezes(self):
        """PRD §3.5: "**Delinquency scoring** starts every account at a base of 80
        points and adjusts from there."
        PRD §3.5: "Fifteen points are deducted for each overdue invoice, twenty for
        each denied warranty claim, and eight for each credited no-longer-needed
        return."
        PRD §3.5: "A bonus of five points is added for each currently effective
        technician certification, but that bonus is capped at fifteen points no matter
        how many certifications the account holds."
        PRD §3.5: "A denied warranty claim is one whose `claim_status` is
        `OEM_DENIED` or `VOID`."
        PRD §3.5: "The **lifetime** variant applies no window filter at all and
        counts every qualifying row regardless of age, which means that on identical
        data it yields a score less than or equal to the rolling variant whenever any
        penalty row predates the window."
        PRD §3.5: "Fourth, `delinquency_score` is refreshed from the **lifetime**
        variant, and if that score is strictly below 40 the account moves from
        `ACTIVE` to `CREDIT_HOLD` with the full freeze cascade."

        Design: Corner/cross_cutting_complexity_layers/delinquency_hold_fires_one_penalty_past_the_threshold
        """
        world = _three_denied_claims_pending_on_one_account()

        at_threshold = run_tier_review(world["account"]["id"])
        assert at_threshold["delinquency_score"] == 40, (
            f"Expected the base 80 less two twenty-point denials with no "
            f"certification bonus, got {at_threshold['delinquency_score']}"
        )
        assert at_threshold["account_status"] == "ACTIVE", (
            "exactly 40 is not strictly below 40"
        )

        record_oem_outcome(
            world["claims"][2]["id"], "DENIED", oem_reference="WP-4012-3",
            oem_note="outside coverage",
        )
        frozen = run_tier_review(world["account"]["id"])

        assert frozen["delinquency_score"] == 20, (
            f"Expected one more twenty-point deduction, got "
            f"{frozen['delinquency_score']}"
        )
        assert frozen["account_status"] == "CREDIT_HOLD", (
            f"20 is strictly below the threshold, got {frozen['account_status']}"
        )
        assert frozen["pricing_tier_id"] == world["tier"]["id"], (
            "the only tier in the book is where an unqualified account lands"
        )

        assert read_certification(world["certification"]["id"])["is_effective"] is (
            False
        )
        assert read_claim(world["claims"][2]["id"])["claim_status"] == "OEM_DENIED"

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "FULFILLED", (
            "a shipped order is outside the freeze cascade"
        )
        assert order["settlement_status"] == "INVOICED"


# ---------------------------------------------------------------------------
# What the writing response already knows
# ---------------------------------------------------------------------------

class TestAllocationResponseFreshness:

    def test_the_allocate_response_body_already_shows_the_recomputed_totals(self):
        """PRD §2.9: "When they do, every affected row is mutated in the same
        request, and every one of those mutations refreshes `updated_at` and
        increments `version`."
        PRD §2.9: "The system never defers a cascade to a later request, never leaves
        a derived aggregate stale, and never partially applies a cascade: if the
        triggering write is rejected, nothing downstream of it is written either."
        PRD §3.6: "The order then recomputes `freight_cents` and `total_cents`, and
        the account's `credit_used_cents` is recomputed."
        PRD §3.6: "If at least one line ended `ALLOCATED`, the order moves
        `DRAFT → ALLOCATED`."

        Design: Corner/consistency_model/allocation_response_already_carries_the_recomputed_totals
        """
        world = setup_will_call_order(
            stage="credit", quantity=3, branch_kwargs=dict(STL_BRANCH),
            on_hand_units=10,
            account_kwargs={"core_liability_limit_cents": 5000000},
            purchase_order_ref="PO-4013",
        )

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        written = validate_success(response, 200)

        assert written["fulfillment_status"] == "ALLOCATED"
        assert written["settlement_status"] == "CREDIT_APPROVED", (
            "the physical move leaves the money dimension where it was"
        )
        assert written["subtotal_cents"] == 31197, (
            f"Expected the quoted 10399 x 3, got {written['subtotal_cents']}"
        )
        assert written["freight_cents"] == 0
        assert written["total_cents"] == 31197, (
            "the response body itself carries the recomputed total"
        )
        assert written["core_deposit_total_cents"] == 0

        assert_inventory_units(
            inventory_for(world["branch"]["id"], world["part"]["id"]),
            on_hand=10, reserved=3, available=7,
        )
        assert read_account(world["account"]["id"])["credit_used_cents"] == 31197
