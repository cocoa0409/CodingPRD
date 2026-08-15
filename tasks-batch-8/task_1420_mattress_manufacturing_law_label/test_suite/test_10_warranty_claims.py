"""Warranty claims: sag gate, age-based variants, credit math, payout (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_warranty_claim,
    create_warranty_claim_payload,
    list_ledger,
    setup_delivered_order,
    setup_filed_claim,
    setup_approved_claim,
    make_retailer_headers,
)

PM = TEST_USERS["plant_manager_headers"]


def test_claim_approved_at_twelve_months_pays_full_replacement(api):
    """PRD §3.9: "That age selects the `credit_variant`: `FULL_REPLACEMENT`
    when `age_months` is at most 12, `PRORATED` when it exceeds 12. A full
    replacement pays the unit's entire `purchase_price_cents` regardless of
    sag depth."
    PRD §3.9: "First, `age_months` is the number of whole 30-day months
    between the unit's `delivered_at` and the logical clock at approval."

    Design: Difficulty/dual_variant_calc/warranty_full_replacement_vs_prorated_divergence
    """
    # Delivered 2026-08-02T00:00:00Z; approval at 2027-07-28 is 360 days = 12
    # whole 30-day months.
    ctx = setup_approved_claim(
        claim_type="SAG_DEFECT", measured_sag_inches=2.0,
        unit_price_cents=200000, approve_clock="2027-07-28T00:00:00Z",
    )
    claim = ctx["claim"]
    assert_warranty_claim(claim)
    assert claim["status"] == "APPROVED"
    assert claim["age_months"] == 12
    assert claim["credit_variant"] == "FULL_REPLACEMENT"
    assert claim["credit_cents"] == 200000


def test_claim_approved_at_thirteen_months_pays_prorated(api):
    """PRD §3.9: "That age selects the `credit_variant`: `FULL_REPLACEMENT`
    when `age_months` is at most 12, `PRORATED` when it exceeds 12."
    PRD §3.9: "The prorated variant computes two guard rails around a linear
    amount: the linear amount is the purchase price multiplied by (120 −
    `age_months`) and divided by 120, rounded half up to integer cents, and it
    may go negative once the unit is past the 120-month term; the floor amount
    is the purchase price multiplied by one tenth, rounded half up to integer
    cents."
    PRD §3.9: "The prorated credit is the larger of the floor amount and the
    smaller of the purchase price and the linear amount — the price cap binds
    first, the floor binds last, so a claim past the term still pays the
    ten-percent floor while a mid-life claim strictly underpays a full
    replacement."

    Design: Difficulty/dual_variant_calc/warranty_full_replacement_vs_prorated_divergence
    """
    # Approval at 2027-08-27 is 390 days after delivery = 13 whole months.
    # linear = round(200000 * 107 / 120) = 178333; floor 20000 does not bind.
    ctx = setup_approved_claim(
        claim_type="SAG_DEFECT", measured_sag_inches=2.0,
        unit_price_cents=200000, approve_clock="2027-08-27T00:00:00Z",
    )
    claim = ctx["claim"]
    assert claim["age_months"] == 13
    assert claim["credit_variant"] == "PRORATED"
    assert claim["credit_cents"] == 178333


def test_prorated_credit_floor_binds_near_term_end(api):
    """PRD §3.9: "The prorated credit is the larger of the floor amount and
    the smaller of the purchase price and the linear amount — the price cap
    binds first, the floor binds last, so a claim past the term still pays the
    ten-percent floor while a mid-life claim strictly underpays a full
    replacement."

    Design: Difficulty/combinatorial_formula/warranty_prorated_nested_floor_binding
    """
    # Approval at 2035-12-13 is 3420 days = 114 whole months after delivery.
    # linear = round(200000 * 6 / 120) = 10000 < floor 20000 -> floor binds.
    ctx = setup_approved_claim(
        claim_type="SAG_DEFECT", measured_sag_inches=2.0,
        unit_price_cents=200000, approve_clock="2035-12-13T00:00:00Z",
        cert_expires_on="2040-01-01T00:00:00Z",
    )
    claim = ctx["claim"]
    assert claim["credit_cents"] == 20000, (
        f"With the linear amount below the 10% floor, the floor must bind: "
        f"got {claim['credit_cents']}"
    )


def test_prorated_variant_and_age_recorded_past_term(api):
    """PRD §3.9: "Approving a claim (`FILED` → `APPROVED`; guarded by
    `ERR_CLAIM_NOT_FILED`) computes the credit at approval time, not filing
    time. First, `age_months` is the number of whole 30-day months between the
    unit's `delivered_at` and the logical clock at approval. That age selects
    the `credit_variant`: `FULL_REPLACEMENT` when `age_months` is at most 12,
    `PRORATED` when it exceeds 12."

    Design: Difficulty/combinatorial_formula/warranty_prorated_nested_floor_binding
    """
    ctx = setup_approved_claim(
        claim_type="SAG_DEFECT", measured_sag_inches=2.0,
        unit_price_cents=200000, approve_clock="2035-12-13T00:00:00Z",
        cert_expires_on="2040-01-01T00:00:00Z",
    )
    claim = ctx["claim"]
    assert claim["age_months"] == 114
    assert claim["credit_variant"] == "PRORATED"


def test_sag_defect_at_exactly_1_5_inches_accepted(api):
    """PRD §3.9: "A `SAG_DEFECT` claim additionally requires
    `measured_sag_inches` of at least 1.5 inches, boundary inclusive; a
    shallower sag is rejected with `ERR_SAG_BELOW_THRESHOLD` (422)."

    Design: Difficulty/boundary_precision_check/sag_threshold_inclusive_1_5
    """
    ctx = setup_delivered_order(quantity=1)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            unit_id=ctx["units"][0]["id"], retailer_id=ctx["retailer"]["id"],
            claim_type="SAG_DEFECT", measured_sag_inches=1.5,
        ),
        make_retailer_headers(ctx["retailer"]["id"]),
    )
    claim = validate_success(resp, expected_status=201)
    assert claim["status"] == "FILED"
    assert claim["measured_sag_inches"] == 1.5


def test_sag_defect_below_1_5_inches_rejected(api):
    """PRD §3.9: "A `SAG_DEFECT` claim additionally requires
    `measured_sag_inches` of at least 1.5 inches, boundary inclusive; a
    shallower sag is rejected with `ERR_SAG_BELOW_THRESHOLD` (422)."

    Design: Difficulty/boundary_precision_check/sag_threshold_inclusive_1_5
    """
    ctx = setup_delivered_order(quantity=1)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            unit_id=ctx["units"][0]["id"], retailer_id=ctx["retailer"]["id"],
            claim_type="SAG_DEFECT", measured_sag_inches=1.49,
        ),
        make_retailer_headers(ctx["retailer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SAG_BELOW_THRESHOLD)


def test_claim_pay_posts_warranty_payout_adjustment(api):
    """PRD §3.9: "Otherwise the payout posts a `CreditAdjustment` for
    `+credit_cents` with source `WARRANTY_PAYOUT` and `source_id` set to the
    claim, recomputes the retailer's balance, and increments the retailer's
    `version`."

    Design: Difficulty/transitive_cascade/warranty_pay_ledger_cascade
    """
    ctx = setup_approved_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5,
                               unit_price_cents=200000)
    paid = validate_success(api.pay_warranty_claim(ctx["claim"]["id"], PM))
    assert paid["status"] == "PAID"

    ledger = list_ledger(ctx["retailer"]["id"])
    assert len(ledger) == 1
    entry = ledger[0]
    assert entry["amount_cents"] == 200000
    assert entry["source"] == "WARRANTY_PAYOUT"
    assert entry["source_id"] == ctx["claim"]["id"]


def test_claim_pay_recomputes_balance_and_bumps_version(api):
    """PRD §3.9: "Otherwise the payout posts a `CreditAdjustment` for
    `+credit_cents` with source `WARRANTY_PAYOUT` and `source_id` set to the
    claim, recomputes the retailer's balance, and increments the retailer's
    `version`."

    Design: Difficulty/transitive_cascade/warranty_pay_ledger_cascade
    """
    ctx = setup_approved_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5,
                               unit_price_cents=200000)
    retailer_id = ctx["retailer"]["id"]
    version_before = ctx["retailer"]["version"]

    validate_success(api.pay_warranty_claim(ctx["claim"]["id"], PM))

    retailer = get_success_data(api.get_retailer(retailer_id, PM))
    assert retailer["credit_balance_cents"] == 200000
    assert retailer["version"] == version_before + 1


def test_pay_on_filed_claim_rejected(api):
    """PRD §3.9: "Paying an approved claim (`APPROVED` → `PAID`; guarded by
    `ERR_CLAIM_NOT_APPROVED`) runs the fiscal cap: if the retailer's
    `credit_balance_cents` plus the claim's `credit_cents` would exceed
    `credit_limit_cents`, the payout is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

    Design: Corner/state_machines/claim_pay_from_filed_rejected
    """
    ctx = setup_filed_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5)
    assert ctx["claim"]["status"] == "FILED"

    resp = api.pay_warranty_claim(ctx["claim"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_APPROVED)

    ledger = list_ledger(ctx["retailer"]["id"])
    assert ledger == [], "A rejected payout must not record any ledger entry"
    retailer = get_success_data(api.get_retailer(ctx["retailer"]["id"], PM))
    assert retailer["credit_balance_cents"] == 0


def test_denied_claim_cannot_be_approved(api):
    """PRD §3.9: "Denial moves `FILED` → `DENIED` under the same
    `ERR_CLAIM_NOT_FILED` guard."
    PRD §3.9: "Approving a claim (`FILED` → `APPROVED`; guarded by
    `ERR_CLAIM_NOT_FILED`) computes the credit at approval time, not filing
    time."

    Design: Corner/state_machines/denied_claim_terminal_lockdown
    """
    ctx = setup_filed_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5)
    denied = validate_success(api.deny_warranty_claim(ctx["claim"]["id"], PM))
    assert denied["status"] == "DENIED"

    resp = api.approve_warranty_claim(ctx["claim"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FILED)


def test_pay_rejected_when_credit_limit_would_be_exceeded(api):
    """PRD §3.9: "Paying an approved claim (`APPROVED` → `PAID`; guarded by
    `ERR_CLAIM_NOT_APPROVED`) runs the fiscal cap: if the retailer's
    `credit_balance_cents` plus the claim's `credit_cents` would exceed
    `credit_limit_cents`, the payout is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (402)."
    PRD §3.1: "In both cases, a posting that would push the balance above the
    limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) and nothing
    is recorded."

    Design: Corner/validations/claim_pay_credit_limit_rejected
    """
    # FULL_REPLACEMENT credit 200000 against a 100000-cent limit.
    ctx = setup_approved_claim(
        claim_type="WORKMANSHIP", measured_sag_inches=0.5,
        unit_price_cents=200000, credit_limit_cents=100000,
    )
    assert ctx["claim"]["credit_cents"] == 200000

    resp = api.pay_warranty_claim(ctx["claim"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    claim = get_success_data(api.get_warranty_claim(ctx["claim"]["id"], PM))
    assert claim["status"] == "APPROVED"
    assert list_ledger(ctx["retailer"]["id"]) == []
