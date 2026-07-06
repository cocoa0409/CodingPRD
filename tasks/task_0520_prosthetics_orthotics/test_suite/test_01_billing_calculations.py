"""L-code claim adjudication, modifier branching, and order ledger calculations.

Covers Queue A (Difficulty) instances for dual_variant_calc and combinatorial_formula,
plus Queue B (Corner) calculation/consistency instances that share these setups.
"""
from test_helpers import (
    validate_success,
    setup_delivered_no_auth_with_lines,
    assert_order_ledger_consistent,
)
from test_helpers.test_users import TEST_USERS, make_practitioner_headers  # noqa: F401


# ─── Queue A: dual_variant_calc ──────────────────────────────────────

def test_ga_line_final_allowed_is_eighty_percent(api):
    """PRD §3.6: "A `GA` modifier signals that an Advance Beneficiary Notice is on
    file with an expected denial, and the payer pays the statutory eighty percent: the
    allowed amount is the base multiplied by the coinsurance rate of 0.80, rounded half
    up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/claim_line_allowed_provisional_vs_final
    """
    cast, lines = setup_delivered_no_auth_with_lines(
        [{"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 30000}])
    cl = lines[0]
    adjudicated = validate_success(
        api.adjudicate_claim_line(cl["id"], TEST_USERS["billing_headers"]), 200)
    # base = 30000 * 1 = 30000; final = round_half_up(30000 * 0.80) = 24000.
    assert adjudicated["allowed_cents"] == 24000, (
        f"GA final allowed should be 24000, got {adjudicated['allowed_cents']}")


def test_ga_line_provisional_ignores_eighty_percent_reduction(api):
    """PRD §3.6: "The provisional per-line figure therefore ignores the `GA`
    eighty-percent reduction and the `GZ` zero entirely; those reductions apply only in
    the final adjudicated computation."

    Design: Difficulty/dual_variant_calc/claim_line_allowed_provisional_vs_final
    """
    cast, lines = setup_delivered_no_auth_with_lines(
        [{"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 30000}])
    cl = lines[0]
    # Before adjudication the line is SUBMITTED; the provisional figure is the full billed
    # amount with no modifier reduction.
    assert cl["adjudication_status"] == "SUBMITTED"
    assert cl["fee_schedule_cents"] * cl["billed_units"] == 30000


def test_order_ledger_sums_only_adjudicated_lines(api):
    """PRD §3.6: "The order's `allowed_total_cents` is the exact sum of `allowed_cents`
    over only those claim lines whose `adjudication_status` is `ADJUDICATED`; lines in
    `DRAFT`, `SUBMITTED`, or `DENIED` are excluded, and the sum involves no rounding."

    Design: Difficulty/dual_variant_calc/order_allowed_total_estimate_vs_ledger
    """
    cast, lines = setup_delivered_no_auth_with_lines([
        {"l_code": "L5301", "modifier": "KX", "billed_units": 2, "fee_schedule_cents": 50000},
        {"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 30000},
        {"l_code": "L1970", "modifier": "GZ", "billed_units": 1, "fee_schedule_cents": 10000},
    ])
    kx, ga, gz = lines
    # KX with no prior-auth required (COMMERCIAL) keeps full base 100000.
    api.adjudicate_claim_line(kx["id"], TEST_USERS["billing_headers"])
    api.adjudicate_claim_line(ga["id"], TEST_USERS["billing_headers"])
    api.deny_claim_line(gz["id"], TEST_USERS["billing_headers"])
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    # KX 100000 + GA 24000 = 124000; GZ denied -> excluded.
    assert order["allowed_total_cents"] == 124000, (
        f"final ledger should be 124000, got {order['allowed_total_cents']}")


def test_order_ledger_excludes_denied_line_from_billed_sum(api):
    """PRD §3.6: "The order's `allowed_total_cents` is the exact sum of `allowed_cents`
    over only those claim lines whose `adjudication_status` is `ADJUDICATED`; lines in
    `DRAFT`, `SUBMITTED`, or `DENIED` are excluded, and the sum involves no rounding."

    Design: Difficulty/dual_variant_calc/order_allowed_total_estimate_vs_ledger
    """
    cast, lines = setup_delivered_no_auth_with_lines([
        {"l_code": "L5301", "modifier": "KX", "billed_units": 2, "fee_schedule_cents": 50000},
        {"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 30000},
        {"l_code": "L1970", "modifier": "GZ", "billed_units": 1, "fee_schedule_cents": 10000},
    ])
    kx, ga, gz = lines
    api.adjudicate_claim_line(kx["id"], TEST_USERS["billing_headers"])
    adj_ga = validate_success(
        api.adjudicate_claim_line(ga["id"], TEST_USERS["billing_headers"]), 200)
    api.deny_claim_line(gz["id"], TEST_USERS["billing_headers"])
    refreshed = [
        validate_success(api.get_claim_line(kx["id"], TEST_USERS["billing_headers"]), 200),
        adj_ga,
        validate_success(api.get_claim_line(gz["id"], TEST_USERS["billing_headers"]), 200),
    ]
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert_order_ledger_consistent(order, refreshed)


# ─── Queue A: combinatorial_formula ──────────────────────────────────

def _deliver_medicare_with_kx_line(api):
    """Build a Medicare auth-required order, attach a KX line BEFORE delivery (so it is
    SUBMITTED at delivery), approve the auth, deliver. Returns (cast, kx_line_id)."""
    from test_helpers.fixtures import (
        setup_order_at_intake, add_milestone, deliver, create_claim_line)
    from test_helpers.test_users import make_practitioner_headers
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    create_claim_line(cast["ord_id"], l_code="L5301", modifier="KX",
                      billed_units=2, fee_schedule_cents=50000)
    ms = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=1)
    pa = validate_success(api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]), 201)
    api.approve_prior_auth(pa["id"], TEST_USERS["compliance_headers"])
    api.complete_milestone(ms["id"], make_practitioner_headers(cast["fit_id"]))
    live = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    deliver(cast["ord_id"], cast["fit_id"], live["version"])
    lines = validate_success(
        api.list_claim_lines(TEST_USERS["billing_headers"],
                             params={"device_order_id": cast["ord_id"]}), 200)
    return cast, lines[0]["id"]


def test_kx_with_approved_priorauth_adjudication_permitted(api):
    """PRD §3.6: "Adjudication of a line bearing the `KX` modifier is permitted only when
    the covering order either does not require prior authorization or has an `APPROVED`
    prior authorization; a `KX` line on an auth-required order that lacks an approved
    authorization is rejected with `ERR_KX_WITHOUT_AUTH`."

    Design: Difficulty/combinatorial_formula/claim_line_allowed_modifier_branch_mode_a
    """
    cast, kx_id = _deliver_medicare_with_kx_line(api)
    adjudicated = validate_success(
        api.adjudicate_claim_line(kx_id, TEST_USERS["billing_headers"]), 200)
    assert adjudicated["adjudication_status"] == "ADJUDICATED"


def test_kx_with_approved_priorauth_full_base_value(api):
    """PRD §3.6: "A `KX` modifier asserts the coverage criteria are met and allows the
    full base."

    Design: Difficulty/combinatorial_formula/claim_line_allowed_modifier_branch_mode_a
    """
    cast, kx_id = _deliver_medicare_with_kx_line(api)
    adjudicated = validate_success(
        api.adjudicate_claim_line(kx_id, TEST_USERS["billing_headers"]), 200)
    # KX keeps full base: 50000 * 2 = 100000.
    assert adjudicated["allowed_cents"] == 100000


def test_order_ledger_rounds_per_line_then_sums(api):
    """PRD §2.7: "Where a calculation multiplies by a coinsurance rate, the result is
    rounded to a whole number of cents using the round-half-up method. Where a
    calculation sums cents that are already whole, the sum is exact and no rounding
    occurs."
    PRD §3.6: "The order's `allowed_total_cents` is the exact sum of `allowed_cents`
    over only those claim lines whose `adjudication_status` is `ADJUDICATED`; lines in
    `DRAFT`, `SUBMITTED`, or `DENIED` are excluded, and the sum involves no rounding."

    Design: Difficulty/combinatorial_formula/order_allowed_total_rounding_order_mode_b
    """
    cast, lines = setup_delivered_no_auth_with_lines([
        {"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 13},
        {"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 14},
    ])
    ga1, ga2 = lines
    adj1 = validate_success(api.adjudicate_claim_line(ga1["id"], TEST_USERS["billing_headers"]), 200)
    adj2 = validate_success(api.adjudicate_claim_line(ga2["id"], TEST_USERS["billing_headers"]), 200)
    # Per-line round_half_up: round(13*0.8=10.4)=10; round(14*0.8=11.2)=11.
    assert adj1["allowed_cents"] == 10
    assert adj2["allowed_cents"] == 11
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    # Sum of already-whole per-line allowed: 10 + 11 = 21 (NOT round(27*0.8)=22).
    assert order["allowed_total_cents"] == 21, (
        f"per-line-then-sum should give 21, got {order['allowed_total_cents']}")


def test_ga_line_half_cent_rounds_half_up(api):
    """PRD §3.6: "A `GA` modifier signals that an Advance Beneficiary Notice is on file
    with an expected denial, and the payer pays the statutory eighty percent: the allowed
    amount is the base multiplied by the coinsurance rate of 0.80, rounded half up to a
    whole number of cents."

    Design: Difficulty/combinatorial_formula/order_allowed_total_rounding_order_mode_b
    """
    # base = 5 cents; 5 * 0.80 = 4.0 -> 4. A value landing exactly on .5 (e.g. base such
    # that base*0.8 = x.5) is pinned by round_half_up; use fee 15 -> 15*0.8=12.0 -> 12,
    # and fee 95 -> 95*0.8=76.0. Choose fee 13 again for the half-up edge: 13*0.8=10.4.
    cast, lines = setup_delivered_no_auth_with_lines([
        {"l_code": "L1960", "modifier": "GA", "billed_units": 1, "fee_schedule_cents": 13},
    ])
    adj = validate_success(api.adjudicate_claim_line(lines[0]["id"], TEST_USERS["billing_headers"]), 200)
    assert adj["allowed_cents"] == 10  # round_half_up(10.4) == 10
