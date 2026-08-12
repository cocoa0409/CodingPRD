"""Rebate settlement calculations: dual-variant provisional/final divergence
and the non-linear payable waterfall (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_order_payload,
    create_rebate_statement_payload,
    get_account_version,
    make_contractor_headers,
    place_and_pay_order,
    set_logical_clock,
    setup_account_job_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]

PERIOD_START = "2026-04-01T00:00:00Z"
PERIOD_END = "2026-07-01T00:00:00Z"


def _setup_divergence_scenario(api):
    """Two paid 6,000,000-subtotal orders (Apr 10 and May 20) with the
    statement generated mid-period on May 1."""
    set_logical_clock("2026-04-01T00:00:00Z")
    account, _, job, product = setup_account_job_product(
        company_name="Rebate Co", credit_limit_cents=100_000_000,
        jurisdiction_code="TX-OPEN", jurisdiction_name="Texas Open",
        job_name="HQ", sku="P-REB-1", product_name="Bulk Flat",
        list_price_cents=6_000_000)
    set_logical_clock("2026-04-10T00:00:00Z")
    order1 = place_and_pay_order(
        account["id"], job["id"], [{"product_id": product["id"], "quantity": 1}],
        headers=ASSOCIATE)
    set_logical_clock("2026-05-01T00:00:00Z")
    resp = api.create_rebate_statement(
        create_rebate_statement_payload(account["id"], PERIOD_START, PERIOD_END),
        ADMIN)
    stmt = validate_success(resp, expected_status=201)
    set_logical_clock("2026-05-20T00:00:00Z")
    order2 = place_and_pay_order(
        account["id"], job["id"], [{"product_id": product["id"], "quantity": 1}],
        headers=ASSOCIATE)
    set_logical_clock("2026-07-01T00:00:00Z")
    return account, stmt, order1, order2


def test_rebate_provisional_forward_looking_projection(api):
    """PRD §3.9: "The provisional estimate is computed once at generation. Let
    the period length be the whole number of days in [`period_start`,
    `period_end`), and let the elapsed days be the whole number of days in
    [`period_start`, the earlier of the logical clock now and `period_end`) —
    so once the period has closed, elapsed days equal the period length. The
    net volume so far is the merchandise basis over the account's paid-set
    orders ... That net is annualized into a projection: multiplied by the
    period length, divided by the elapsed days, and truncated down to a whole
    cent. The projection is then banded at 2% of its portion up to 10,000,000
    cents ($100,000), plus 4% of its portion between $100,000 and 30,000,000
    cents ($300,000), plus 6% of any portion above $300,000. The provisional
    amount is that banded figure prorated back to the elapsed fraction:
    multiplied by the elapsed days, divided by the period length, and
    truncated down to a whole cent. The two truncations are pinned — once at
    the projection, once at the final proration."

    One 6,000,000-cent payment 30 days into a 91-day period projects to
    floor(6000000*91/30) = 18,200,000, bands to 528,000, and prorates back to
    floor(528000*30/91) = 174,065.

    Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_divergence
    """
    account, stmt, _, _ = _setup_divergence_scenario(api)
    assert stmt["provisional_amount_cents"] == 174_065, (
        f"provisional must be 174065 (projection 18200000 banded to 528000, "
        f"prorated 30/91), got {stmt['provisional_amount_cents']}")


def test_rebate_final_chronological_straddle_diverges(api):
    """PRD §3.9: "The marginal straddle is symmetric — a payment followed by a
    full in-period refund restores both accumulators exactly — so for
    identical order data the final differs from the provisional only through
    the provisional's forward-looking projection and proration whenever volume
    crosses a band boundary mid-period. `final_amount_cents` is the rebate
    accumulator rounded half up to a whole cent, applied once at the end."

    Two 6,000,000-cent payments accrue 120,000 (first fills the 2% band) plus
    4,000,000@2% + 2,000,000@4% = 160,000 (second straddles the band
    boundary), for a chronological final of 280,000 — diverging from the
    174,065 provisional for identical order data.

    Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_divergence
    """
    account, stmt, _, _ = _setup_divergence_scenario(api)
    resp = api.finalize_rebate_statement(stmt["id"], ADMIN)
    finalized = validate_success(resp, expected_status=200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_amount_cents"] == 280_000, (
        f"chronological final must be 280000 (120000 + 80000 + 80000 straddle), "
        f"got {finalized['final_amount_cents']}")
    assert finalized["provisional_amount_cents"] == 174_065, (
        "the stored provisional is computed once at generation and is not "
        "replaced by finalization")
    assert finalized["final_amount_cents"] != finalized["provisional_amount_cents"], (
        "the two variants must diverge when volume crosses a band boundary "
        "mid-period")


def _setup_cap_scenario(api):
    """One paid 20,000,000-subtotal order in the period; statement generated
    and finalized after close, then disputed by the owning contractor."""
    set_logical_clock("2026-04-05T00:00:00Z")
    account, _, job, product = setup_account_job_product(
        company_name="Cap Co", credit_limit_cents=100_000_000,
        jurisdiction_code="AZ-OPEN", jurisdiction_name="Arizona Open",
        job_name="Mall", sku="P-CAP", product_name="Tote",
        list_price_cents=20_000_000)
    place_and_pay_order(
        account["id"], job["id"], [{"product_id": product["id"], "quantity": 1}],
        headers=ASSOCIATE)
    set_logical_clock("2026-07-01T00:00:00Z")
    resp = api.create_rebate_statement(
        create_rebate_statement_payload(account["id"], PERIOD_START, PERIOD_END),
        ADMIN)
    stmt = validate_success(resp, expected_status=201)
    resp = api.finalize_rebate_statement(stmt["id"], ADMIN)
    stmt = validate_success(resp, expected_status=200)
    resp = api.dispute_rebate_statement(
        stmt["id"], make_contractor_headers(account["id"]))
    stmt = validate_success(resp, expected_status=200)
    assert stmt["status"] == "DISPUTED"
    return account, stmt


def test_rebate_payable_cap_binds_over_adjustment(api):
    """PRD §3.9: "Finalization also computes `period_net_cents` — the same
    merchandise basis over the full period window — and `payable_cents`, the
    amount actually payable: the sum of `final_amount_cents` and
    `adjustment_cents`, capped at 5 percent of `period_net_cents` rounded half
    up, and floored at zero; the cap can bind below the banded amount, and a
    negative adjustment can drive the raw figure below zero, where the floor
    binds."

    A 20,000,000-cent net yields a 600,000 chronological final; with a
    +500,000 dispute adjustment the raw figure 1,100,000 exceeds the
    round_half_up(0.05 * 20,000,000) = 1,000,000 cap, so the cap binds.

    Design: Difficulty/combinatorial_formula/rebate_payable_cap_binds_over_adjustment
    """
    account, stmt = _setup_cap_scenario(api)
    resp = api.resolve_rebate_dispute(stmt["id"], {"adjustment_cents": 500_000}, ADMIN)
    resolved = validate_success(resp, expected_status=200)
    assert resolved["final_amount_cents"] == 600_000, (
        f"final must be 600000 (10,000,000@2% + 10,000,000@4%), "
        f"got {resolved['final_amount_cents']}")
    assert resolved["period_net_cents"] == 20_000_000
    assert resolved["payable_cents"] == 1_000_000, (
        f"cap 1,000,000 binds below final+adjustment 1,100,000, "
        f"got {resolved['payable_cents']}")


def test_rebate_dispute_cycle_returns_to_finalized(api):
    """PRD §3.9: "Settlement then follows a deliberate negotiation cycle. The
    owning `Contractor` may dispute a `FINALIZED` statement, moving it to
    `DISPUTED`; a `CorporateAdmin` resolves the dispute by supplying a signed
    `adjustment_cents`, moving `DISPUTED` back to `FINALIZED` with
    `payable_cents` recomputed under the new adjustment; each pass bumps the
    statement's `version`, and a dispute attempted from anything but
    `FINALIZED`, or a resolution from anything but `DISPUTED`, draws
    `ERR_INVALID_STATE`."

    Design: Difficulty/combinatorial_formula/rebate_payable_cap_binds_over_adjustment
    """
    account, stmt = _setup_cap_scenario(api)
    version_at_dispute = stmt["version"]
    resp = api.resolve_rebate_dispute(stmt["id"], {"adjustment_cents": 500_000}, ADMIN)
    resolved = validate_success(resp, expected_status=200)
    assert resolved["status"] == "FINALIZED", (
        f"resolution must move the statement back to FINALIZED, "
        f"got {resolved['status']}")
    assert resolved["adjustment_cents"] == 500_000
    assert resolved["version"] == version_at_dispute + 1, (
        "each pass of the negotiation cycle bumps the statement's version")
