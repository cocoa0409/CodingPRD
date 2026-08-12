"""Valuation coverage: deductible-tier premiums, supersede, OCC (PRD 2.7, 3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_valuation_coverage,
    create_valuation_coverage_payload,
    elect_coverage,
    get_success_data,
    setup_registered_order,
    validate_error,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


def test_valuation_premium_deductible_tiers(api):
    """PRD section 3.3: "The premium divides the declared value into whole
    one-hundred-dollar units (10000 cents each), rounding any remainder up to the
    next unit; multiplies the unit count by 85 cents; multiplies by the deductible
    factor — 1.00 for a deductible of 0, 0.85 for 25000, and 0.70 for 50000; and
    rounds the result half up to integer cents. A new election supersedes the
    order's currently `ELECTED` coverage into `SUPERSEDED` at any time before
    dispatch, and bumps the order's `version`; at dispatch the elected coverage
    locks (§3.4)."

    Design: Corner/calculations/valuation_premium_deductible_tiers
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)

    cov1 = elect_coverage(
        ctx, coverage_type="FULL_VALUE_PROTECTION",
        declared_value_cents=6000000, deductible_cents=0, as_role="customer",
    )
    assert_valuation_coverage(cov1)
    # 600 units * 85 * 1.00
    assert cov1["premium_cents"] == 51000, f"got {cov1['premium_cents']}"

    cov2 = elect_coverage(
        ctx, coverage_type="FULL_VALUE_PROTECTION",
        declared_value_cents=6000000, deductible_cents=25000, as_role="customer",
    )
    # 600 units * 85 * 0.85
    assert cov2["premium_cents"] == 43350, f"got {cov2['premium_cents']}"
    cov1_after = get_success_data(api.get_valuation_coverage(cov1["id"], ADMIN))
    assert cov1_after["status"] == "SUPERSEDED", "re-election supersedes the prior ELECTED coverage"

    cov3 = elect_coverage(
        ctx, coverage_type="FULL_VALUE_PROTECTION",
        declared_value_cents=6000000, deductible_cents=50000, as_role="customer",
    )
    # 600 units * 85 * 0.70
    assert cov3["premium_cents"] == 35700, f"got {cov3['premium_cents']}"
    cov2_after = get_success_data(api.get_valuation_coverage(cov2["id"], ADMIN))
    assert cov2_after["status"] == "SUPERSEDED"
    assert cov3["status"] == "ELECTED"


def test_valuation_elect_rejected_stale_order_version(api):
    """PRD section 2.7: "Two write operations against a move order are protected
    by optimistic concurrency control: issuing an estimate on an order, and
    electing a valuation coverage on an order. Each requires the request to carry
    `expected_order_version`, a non-optional field holding the `version` of the
    order as the client last observed it. If the order's current `version` no
    longer matches — because another writer has advanced it since that read — the
    write is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The protection
    exists because each of these writes supersedes an existing record: a newer
    estimate legitimately supersedes any prior issued or accepted estimate, and a
    new election legitimately supersedes the currently elected coverage, so a
    writer holding a stale order version would otherwise replace a revision it
    never observed."

    Design: Corner/cross_cutting_layers/valuation_elect_rejected_stale_order_version
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    stale_version = ctx["order"]["version"]

    cov1 = elect_coverage(ctx, coverage_type="RELEASED_VALUE")
    assert cov1["status"] == "ELECTED"

    # Replay the pre-election version: rejected even though re-election is
    # legitimate at the current version.
    resp = api.create_valuation_coverage(
        ctx["order"]["id"],
        create_valuation_coverage_payload(
            stale_version,
            coverage_type="FULL_VALUE_PROTECTION",
            declared_value_cents=6000000,
            deductible_cents=0,
        ),
        ctx["booking_h"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)

    cov1_after = get_success_data(api.get_valuation_coverage(cov1["id"], ADMIN))
    assert cov1_after["status"] == "ELECTED", (
        "the rejected stale write must not supersede the elected coverage"
    )
