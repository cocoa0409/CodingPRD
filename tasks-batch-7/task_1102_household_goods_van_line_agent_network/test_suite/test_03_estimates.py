"""Estimates: pinned component rounding, revision chain, kind lock, expiry, OCC (PRD 2.7, 3.3)."""
from test_helpers import (
    SIMPLE_TARIFF_BANDS,
    ApiErrorId,
    TEST_USERS,
    assert_estimate,
    create_estimate_payload,
    create_order_payload,
    get_success_data,
    issue_estimate,
    register_order,
    set_clock,
    setup_network,
    setup_registered_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["van_line_admin_headers"]

# Tariff shape that makes rounding order observable: base 4555, single band at
# multiplier 1.25, fuel surcharge 0.075.
ROUNDING_TARIFF = {
    "base_rate_cents_per_cwt": 4555,
    "mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.25}],
    "fuel_surcharge_pct": 0.075,
}


def _setup_rounding_order():
    ctx = setup_registered_order(
        pricing_mode="NON_BINDING", mileage=300, tariff_overrides=ROUNDING_TARIFF
    )
    return ctx


def test_estimate_component_rounding_per_component(api):
    """PRD section 3.3: "The linehaul component converts the estimated weight to
    hundredweight — pounds divided by 100, rounding any remainder up to the next
    hundredweight — selects the single tariff mileage band containing the order's
    mileage (lower bound inclusive, upper bound exclusive, final band inclusive),
    multiplies the hundredweight by the tariff's `base_rate_cents_per_cwt` and by
    that band's `rate_multiplier`, and rounds half up to integer cents; the result
    is `linehaul_cents`. The fuel component, `fuel_surcharge_cents`, is the rounded
    linehaul multiplied by the tariff's `fuel_surcharge_pct`, again rounded half up
    to integer cents."
    PRD section 2.6: "All monetary values in the system are exact integer cents;
    no floating-point money is ever stored or returned. Wherever a multiplication
    or percentage produces a fractional cent, the result is rounded half up to the
    nearest whole cent."

    Design: Difficulty/combinatorial_formula/estimate_total_component_rounding_order
    """
    ctx = _setup_rounding_order()
    estimate = issue_estimate(ctx, estimated_weight_lbs=8050)
    assert_estimate(estimate)
    # 8050 lbs -> 81 cwt; round_half_up(81 * 4555 * 1.25) = round_half_up(461193.75)
    assert estimate["linehaul_cents"] == 461194, (
        f"linehaul must be rounded per component, got {estimate['linehaul_cents']}"
    )
    # round_half_up(461194 * 0.075) = round_half_up(34589.55)
    assert estimate["fuel_surcharge_cents"] == 34590, (
        f"fuel must be computed from the ROUNDED linehaul, got {estimate['fuel_surcharge_cents']}"
    )


def test_estimate_component_rounding_total_is_sum_of_rounded(api):
    """PRD section 3.3: "Adding the estimate's `packing_services_cents` — already
    integer cents — yields `estimated_charges_cents` as the sum of the individually
    rounded components; per §2.6, summing unrounded components and rounding once is
    forbidden."
    PRD section 3.3: "The valuation component, `valuation_premium_cents`, snapshots
    the premium of the order's currently `ELECTED` valuation coverage, and is 0
    when no coverage is elected at issuance."
    PRD section 3.3: "computes `revision_number` as one greater than the superseded
    estimate's revision (1 for the first estimate on an order)"

    Design: Difficulty/combinatorial_formula/estimate_total_component_rounding_order
    """
    ctx = _setup_rounding_order()
    estimate = issue_estimate(ctx, estimated_weight_lbs=8050)
    # Sum of rounded components: 461194 + 34590 + 0 + 0 = 495784.
    # The forbidden sum-then-round would give round(495783.28...) = 495783.
    assert estimate["estimated_charges_cents"] == 495784, (
        f"total must be the sum of rounded components, got {estimate['estimated_charges_cents']}"
    )
    assert estimate["valuation_premium_cents"] == 0, "no coverage elected -> premium 0"
    assert estimate["revision_number"] == 1, "first estimate on an order has revision 1"


def test_estimate_create_missing_required_weight_rejected(api):
    """PRD section 3.3: "The payload carries `estimate_kind`, which must equal the
    order's `pricing_mode` (a mismatch is rejected with `ERR_ESTIMATE_KIND_MISMATCH`,
    HTTP 422); `estimated_weight_lbs` of at least 1; an optional
    `packing_services_cents` defaulting to 0 and never negative; and
    `expected_order_version` per the concurrency rule of §2.7."
    PRD section 2.10: "Request-body well-formedness — required fields present,
    types correct, enum values in range, unknown fields rejected, and structural
    rules such as gross weight being at least the tare weight, the end hour being
    later than the start hour, and the deductible being one of its allowed values
    (HTTP 400)."

    Design: Corner/entities/estimate_create_rejected_missing_required_weight
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    # estimated_weight_lbs and expected_order_version both omitted.
    resp = api.create_estimate(ctx["order"]["id"], {"estimate_kind": "BINDING"}, ctx["booking_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(
        api.list_estimates(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 0, "no estimate may be created by the rejected write"


def test_estimate_revision_chain_and_supersede(api):
    """PRD section 3.3: "The new estimate supersedes any prior `ISSUED` or
    `ACCEPTED` estimate on the same order — the prior estimate becomes `SUPERSEDED`
    with its `version` bumped, and when the superseded estimate had been `ACCEPTED`,
    the order's latched `estimated_weight_lbs` reverts to null until the replacement
    estimate is accepted. The new estimate records the replaced estimate as
    `supersedes_estimate_id` (null on the first estimate), computes
    `revision_number` as one greater than the superseded estimate's revision (1 for
    the first estimate on an order), stamps `issued_at` from the logical clock, and
    sets `expires_at` thirty days after issuance."
    PRD section 2.3: "The estimate list accepts `order_id`, `supersedes_estimate_id`,
    and `status`."

    Design: Corner/entities/self_referential_estimate_revision_chain
    """
    # Single band at multiplier 1.0 so the pinned formula below is 90 cwt *
    # 4500 * 1.0 + fuel + packing (the default bands would apply 1.2 at 900 mi).
    ctx = setup_registered_order(
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": SIMPLE_TARIFF_BANDS},
    )
    e1 = issue_estimate(ctx, estimated_weight_lbs=8000)
    assert e1["supersedes_estimate_id"] is None
    assert e1["revision_number"] == 1

    e2 = issue_estimate(ctx, estimated_weight_lbs=9000, packing_services_cents=5000)
    assert e2["revision_number"] == 2, f"second estimate revision must be 2, got {e2['revision_number']}"
    assert e2["supersedes_estimate_id"] == e1["id"]

    e1_after = get_success_data(api.get_estimate(e1["id"], ADMIN))
    assert e1_after["status"] == "SUPERSEDED"

    data, meta = validate_paginated(
        api.list_estimates(ADMIN, params={"supersedes_estimate_id": e1["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == e2["id"]

    # PRD formula on 90 cwt, single band multiplier 1.0, fuel 10%: 405000 + 40500
    # + packing 5000 = 450500 (released-value premium is 0 with none elected).
    assert e2["estimated_charges_cents"] == 450500, (
        f"expected 450500 per the pinned component formula, got {e2['estimated_charges_cents']}"
    )


def test_estimate_kind_must_match_pricing_mode(api):
    """PRD section 3.3: "The payload carries `estimate_kind`, which must equal the
    order's `pricing_mode` (a mismatch is rejected with `ERR_ESTIMATE_KIND_MISMATCH`,
    HTTP 422); `estimated_weight_lbs` of at least 1; an optional
    `packing_services_cents` defaulting to 0 and never negative; and
    `expected_order_version` per the concurrency rule of §2.7."

    Design: Corner/validations/estimate_kind_must_match_pricing_mode
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    version = ctx["order"]["version"]
    payload = create_estimate_payload(
        version, estimate_kind="NON_BINDING", estimated_weight_lbs=8000
    )
    resp = api.create_estimate(ctx["order"]["id"], payload, ctx["booking_h"])
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_KIND_MISMATCH)

    data, meta = validate_paginated(
        api.list_estimates(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 0


def test_estimate_accept_from_declined_rejected(api):
    """PRD section 3.3: "The customer answers an estimate while it is `ISSUED`."
    PRD section 3.3: "Declining moves an `ISSUED` estimate to the terminal
    `DECLINED`."
    PRD section 3.2: "Weight fields (`estimated_weight_lbs`, `actual_weight_lbs`,
    `authoritative_weight_ticket_id`), the delivery window (`earliest_delivery_date`,
    `latest_delivery_date`), and the delivery money fields (`final_charges_cents`,
    `delivery_amount_due_cents`, `deferred_balance_cents`,
    `collected_at_delivery_cents`, `delivered_at`) all remain null until the
    lifecycle point that produces them."

    Design: Corner/state_machines/estimate_accept_from_declined_rejected
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    estimate = issue_estimate(ctx, estimated_weight_lbs=8000)
    declined = get_success_data(api.decline_estimate(estimate["id"], ctx["cust_h"]))
    assert declined["status"] == "DECLINED"

    resp = api.accept_estimate(estimate["id"], ctx["cust_h"])
    validate_error(resp, ApiErrorId.ERR_TRANSITION_NOT_ALLOWED)

    current = get_success_data(api.get_estimate(estimate["id"], ADMIN))
    assert current["status"] == "DECLINED", "a declined estimate is terminal"
    order = get_success_data(api.get_order(ctx["order"]["id"], ADMIN))
    assert order["estimated_weight_lbs"] is None, (
        "no acceptance happened, so the order's estimated weight stays null"
    )


def test_estimate_accept_expiry_boundary(api):
    """PRD section 3.3: "The customer answers an estimate while it is `ISSUED`.
    Acceptance additionally requires the order to still be `REGISTERED` (otherwise
    `ERR_ORDER_NOT_REGISTERED`) and the logical clock to be no later than
    `expires_at`; an accept attempted after expiry is rejected with
    `ERR_ESTIMATE_EXPIRED` (HTTP 422) and the estimate flips to `EXPIRED` within
    the same rejection."
    PRD section 3.3: "stamps `issued_at` from the logical clock, and sets
    `expires_at` thirty days after issuance."

    Design: Corner/validations/estimate_accept_expiry_boundary
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    e1 = issue_estimate(ctx, estimated_weight_lbs=5000)
    order2 = register_order(ctx, pricing_mode="BINDING", mileage=900)
    ctx["order"] = order2
    e2 = issue_estimate(ctx, estimated_weight_lbs=5000)

    # Issued at 2026-05-01T00:00:00Z -> expires_at 2026-05-31T00:00:00Z.
    set_clock("2026-05-31T00:00:00Z")
    accepted = get_success_data(api.accept_estimate(e1["id"], ctx["cust_h"]))
    assert accepted["status"] == "ACCEPTED", "accept at exactly expires_at must succeed"

    set_clock("2026-05-31T00:00:01Z")
    resp = api.accept_estimate(e2["id"], ctx["cust_h"])
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_EXPIRED)
    expired = get_success_data(api.get_estimate(e2["id"], ADMIN))
    assert expired["status"] == "EXPIRED", (
        "the failed accept flips the estimate to EXPIRED within the same rejection"
    )


def test_estimate_create_rejected_stale_order_version(api):
    """PRD section 2.7: "Two write operations against a move order are protected
    by optimistic concurrency control: issuing an estimate on an order, and
    electing a valuation coverage on an order. Each requires the request to carry
    `expected_order_version`, a non-optional field holding the `version` of the
    order as the client last observed it. If the order's current `version` no
    longer matches — because another writer has advanced it since that read — the
    write is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD section 2.4: "`version` (integer): a system-managed integer that increments
    by one on every mutation of the resource, including mutations produced by
    cascade side effects originating on another resource."

    Design: Corner/cross_cutting_layers/estimate_create_rejected_stale_order_version
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    stale_version = ctx["order"]["version"]

    e1 = issue_estimate(ctx, estimated_weight_lbs=5000)
    mid = get_success_data(api.get_order(ctx["order"]["id"], ADMIN))
    assert mid["version"] == stale_version + 1, (
        "a successful estimate create advances the order version by exactly one"
    )

    # Replay the pre-mutation version.
    resp = api.create_estimate(
        ctx["order"]["id"],
        create_estimate_payload(stale_version, estimate_kind="BINDING", estimated_weight_lbs=6000),
        ctx["booking_h"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)

    # Retry with the fresh version succeeds and supersedes e1.
    e2 = issue_estimate(ctx, estimated_weight_lbs=6000)
    assert e2["revision_number"] == 2
    e1_after = get_success_data(api.get_estimate(e1["id"], ADMIN))
    assert e1_after["status"] == "SUPERSEDED"
    final = get_success_data(api.get_order(ctx["order"]["id"], ADMIN))
    assert final["version"] == mid["version"] + 1
