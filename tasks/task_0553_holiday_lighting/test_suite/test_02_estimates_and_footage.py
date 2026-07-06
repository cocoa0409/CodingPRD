"""Design estimates and tiered footage pricing.

Covers the quoted footage calculation (tiers x complexity multiplier + accessories +
product base), the dual quoted-vs-final variant reconciled at install completion,
estimate creation defaults, the accept state guard, and estimate listing.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_estimate, setup_active_contract,
    setup_quoted_estimate, setup_accepted_estimate, setup_started_install_job,
)
from test_helpers.factories import create_estimate_payload
from test_helpers.test_users import make_customer_headers, make_crewlead_headers

SALES = TEST_USERS["salesrep_headers"]


# ── Difficulty/combinatorial_formula/footage_quote_tiered_multiplier_mode_a ───

def test_quoted_total_permanent_moderate_with_accessories(api):
    """PRD §3.2: "It then charges the lit footage across three tiers: the first 100 feet
    at 300 cents per foot, the next 100 feet (those from the 101st through the 200th) at
    250 cents per foot, and every foot beyond 200 at 200 cents per foot. The sum of those
    three tier charges is the raw footage cost, which is then multiplied by a complexity
    factor — 1.00 for `SIMPLE`, 1.15 for `MODERATE`, or 1.30 for `COMPLEX` — with the
    result of that single multiplication rounded half up to whole cents (rounding is
    applied only to the multiplied footage cost, not to the base or the accessories)."
    PRD §3.2: "The quoted total is the base plus the rounded complexity-adjusted footage
    cost plus the accessory cost."

    PERMANENT base 40000 + round(42500*1.15)=48875 + 4*1200=4800 = 93675.

    Design: Difficulty/combinatorial_formula/footage_quote_tiered_multiplier_mode_a
    """
    _, quoted = setup_quoted_estimate(product_line="PERMANENT", estimated_footage=150,
                                      roofline_complexity="MODERATE", accessory_count=4)
    assert quoted["quoted_total_cents"] == 93675, quoted


def test_quote_transition_sets_quoted_status(api):
    """PRD §3.2: "A `SalesRep` moves an estimate from `DRAFT` to `QUOTED`, permitted only
    when the estimate is in `DRAFT`"
    PRD §3.2: "The quoted price is a tiered footage calculation written to
    `quoted_total_cents`."

    Design: Difficulty/combinatorial_formula/footage_quote_tiered_multiplier_mode_a
    """
    _, quoted = setup_quoted_estimate(product_line="PERMANENT", estimated_footage=150,
                                      roofline_complexity="MODERATE", accessory_count=4)
    assert quoted["status"] == "QUOTED", quoted


# ── Difficulty/dual_variant_calc/estimate_quoted_vs_final_footage ────────────

def _dual_variant_completed_estimate(api):
    """Build a PERMANENT estimate quoted at 93675, accepted, installed at 170 ft, and
    return the estimate as read after the linked install job completes."""
    set_clock("2026-06-01T00:00:00Z")
    _, contract = setup_active_contract(contract_type="PERMANENT_PURCHASE",
                                        base_season_fee_cents=80000,
                                        early_bird_cutoff="2026-08-15T00:00:00Z",
                                        customer_overrides={"name": "Ann Owner",
                                                            "service_address": "1 Elm St",
                                                            "roofline_feet": 220})
    cust_id = contract["customer_id"]
    _, accepted = setup_accepted_estimate(
        customer_id=cust_id, contract_id=contract["id"], product_line="PERMANENT",
        estimated_footage=150, roofline_complexity="MODERATE", accessory_count=4)
    ctx = setup_started_install_job(estimate_id=accepted["id"], contract=contract)
    validate_success(api.complete_job(
        ctx["job"]["id"], {"completed_footage": 170},
        make_crewlead_headers(ctx["crew"]["id"])), 200)
    return accepted["id"], accepted["quoted_total_cents"]


def test_install_completion_recomputes_final_from_measured_footage(api):
    """PRD §3.2: "the estimate's `measured_footage` is set to the job's actually installed
    footage, and its `final_total_cents` is recomputed using the very same tiered footage
    formula and the same base, complexity factor, and accessory charge as the quote —
    except that the footage driving the tiers is now the `measured_footage` rather than
    the projection."

    measured 170 -> PERMANENT 40000 + round(47500*1.15)=54625 + 4800 = 99425.

    Design: Difficulty/dual_variant_calc/estimate_quoted_vs_final_footage
    """
    est_id, _ = _dual_variant_completed_estimate(api)
    est = validate_success(api.get_estimate(est_id, SALES), 200)
    assert est["measured_footage"] == 170, est
    assert est["final_total_cents"] == 99425, est
    assert est["status"] == "INVOICED", est


def test_final_total_diverges_from_quoted_when_footage_differs(api):
    """PRD §3.2: "Whenever the measured footage differs from the estimated footage, the
    final total diverges from the quoted total."

    Quoted (estimated 150) is 93675; final (measured 170) is 99425, and they differ.

    Design: Difficulty/dual_variant_calc/estimate_quoted_vs_final_footage
    """
    est_id, quoted_total = _dual_variant_completed_estimate(api)
    est = validate_success(api.get_estimate(est_id, SALES), 200)
    assert quoted_total == 93675, quoted_total
    assert est["final_total_cents"] == 99425, est
    assert est["final_total_cents"] != est["quoted_total_cents"], est


# ── Corner/calculations/footage_quote_seasonal_complex_correct_result ────────

def test_quoted_total_seasonal_complex_no_accessories(api):
    """PRD §3.2: "It begins from a base that depends on the product line: 15000 cents for
    a `SEASONAL` design, or 40000 cents for a `PERMANENT` design."
    PRD §3.2: "The sum of those three tier charges is the raw footage cost, which is then
    multiplied by a complexity factor — 1.00 for `SIMPLE`, 1.15 for `MODERATE`, or 1.30
    for `COMPLEX` — with the result of that single multiplication rounded half up to whole
    cents (rounding is applied only to the multiplied footage cost, not to the base or the
    accessories)."

    SEASONAL 15000 + round(65000*1.30)=84500 + 0 = 99500 for 250 ft COMPLEX.

    Design: Corner/calculations/footage_quote_seasonal_complex_correct_result
    """
    _, quoted = setup_quoted_estimate(product_line="SEASONAL", estimated_footage=250,
                                      roofline_complexity="COMPLEX", accessory_count=0)
    assert quoted["quoted_total_cents"] == 99500, quoted


# ── Corner/entities/estimate_system_fields_generated ─────────────────────────

def test_estimate_created_in_draft_with_defaults(api):
    """PRD §3.2: "An estimate opens in `DRAFT` `status`; its `quoted_total_cents`,
    `measured_footage`, and `final_total_cents` are all unset until the relevant
    milestone."
    PRD §3.2: "an `accessory_count` for add-ons such as timers, stakes, and wreaths,
    defaulting to 0."

    Design: Corner/entities/estimate_system_fields_generated
    """
    customer = create_customer(name="Sys Owner", service_address="104 Main St",
                               roofline_feet=100)
    est = validate_success(api.create_estimate(create_estimate_payload(
        customer["id"], product_line="SEASONAL", estimated_footage=120,
        roofline_complexity="SIMPLE"), SALES), 201)
    assert est["status"] == "DRAFT", est
    assert est["accessory_count"] == 0, est


# ── Corner/state_machines/accept_non_quoted_estimate_returns_invalid_state ────

def test_accept_draft_estimate_rejected(api):
    """PRD §3.2: "The owner named on the estimate accepts a quoted estimate, moving it from
    `QUOTED` to `ACCEPTED`; this is permitted only while the estimate is in `QUOTED`
    (otherwise `ERR_ESTIMATE_NOT_QUOTED`), and the acting `Customer`'s `X-User-ID` must
    equal the estimate's `customer_id` or the request is rejected as unauthorized."

    The owning customer accepts a DRAFT (never-quoted) estimate -> ERR_ESTIMATE_NOT_QUOTED.

    Design: Corner/state_machines/accept_non_quoted_estimate_returns_invalid_state
    """
    customer = create_customer(name="Acc Owner", service_address="106 Main St",
                               roofline_feet=140)
    est = create_estimate(customer["id"], product_line="SEASONAL",
                          estimated_footage=120, roofline_complexity="SIMPLE")
    resp = api.accept_estimate(est["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_QUOTED.value, 409)


# ── Corner/endpoints/estimates_list_by_customer_fk ───────────────────────────

def test_estimates_list_returns_customer_estimate(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, all list endpoints return
    resources sorted by their creation timestamp (`created_at`) in ascending order."
    PRD §2.3: "Every list response includes the following fields inside the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/estimates_list_by_customer_fk
    """
    customer = create_customer(name="Est Owner", service_address="121 Main St",
                               roofline_feet=100)
    est = create_estimate(customer["id"], product_line="SEASONAL",
                          estimated_footage=100, roofline_complexity="SIMPLE")
    data, meta = validate_paginated(
        api.list_estimates(SALES, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 1, meta
    assert len(data) == 1 and data[0]["id"] == est["id"], data
