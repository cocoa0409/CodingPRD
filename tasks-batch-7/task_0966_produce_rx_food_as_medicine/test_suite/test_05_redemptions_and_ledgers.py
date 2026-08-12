"""Redemptions, the Double-Up match, tender split, voids, and ledger
conservation (PRD §2.6, §2.8, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_redemption, assert_pool_ledger_conserved,
    assert_double_up_ledger_conserved,
    TEST_USERS, make_retailer_staff_headers,
    create_redemption_payload, create_retailer_payload,
    setup_enrollment, setup_issued_voucher, setup_settled_redemption,
    create_settled_redemption, create_retailer, get_pool, get_program,
    get_enrollment, close_cycle,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]

DEFAULT_LINES = [
    {"category": "PRODUCE_ELIGIBLE", "amount_cents": 2000},
    {"category": "STAPLE", "amount_cents": 3000},
]


def test_empty_lines_rejected_as_invalid_tender(api):
    """PRD §3.5: "An empty basket, a non-positive amount, or an unknown
    category is rejected with `ERR_INVALID_TENDER`."

    Design: Corner/errors/c_invalid_tender_rejected
    """
    ctx = setup_issued_voucher(with_retailer=True)
    retailer = ctx["retailer"]
    res = api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=[]),
        make_retailer_staff_headers(retailer["id"]))
    validate_error(res, "ERR_INVALID_TENDER")

    pool = get_pool(ctx["pool"]["id"])
    assert pool["reserved_cents"] == 12500
    assert pool["disbursed_cents"] == 0


def test_void_after_cycle_close_rejected(api):
    """PRD §3.5: "A void is allowed only while the money is still in flight:
    the benefit cycle of the debited voucher must still be OPEN, otherwise
    `ERR_VOID_NOT_ALLOWED`; a redemption whose `voucher_id` is empty — nothing
    was drawn from any voucher — may be voided while the enrollment's program
    is not CLOSED; and an already-VOIDED redemption rejects a second void with
    `ERR_VOID_NOT_ALLOWED`."

    Design: Corner/errors/c_void_after_cycle_close_rejected
    """
    ctx = setup_settled_redemption()
    close_cycle(ctx["cycle"]["id"])

    res = api.void_redemption(ctx["redemption"]["id"],
                              {"reason": "too late"}, ADMIN)
    validate_error(res, "ERR_VOID_NOT_ALLOWED")

    after = validate_success(
        api.get_redemption(ctx["redemption"]["id"], ADMIN), 200)
    assert after["status"] == "SETTLED"


def test_immediate_readback_after_redemption(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "A new redemption is born SETTLED, with `redeemed_at` stamped
    from the logical clock."

    Design: Corner/consistency_model/c_immediate_readback_after_redemption
    """
    ctx = setup_issued_voucher(with_retailer=True)
    retailer = ctx["retailer"]
    created = validate_success(api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=DEFAULT_LINES),
        make_retailer_staff_headers(retailer["id"])), 201)
    assert_redemption(created)
    assert created["match_cents"] == 2000
    assert created["voucher_applied_cents"] == 3000
    assert created["patient_pay_cents"] == 0

    fetched = validate_success(api.get_redemption(created["id"], ADMIN), 200)
    assert fetched["match_cents"] == created["match_cents"]
    assert fetched["voucher_applied_cents"] == created["voucher_applied_cents"]
    assert fetched["status"] == "SETTLED"


def test_enrollment_lifetime_counters_reconcile_after_void(api):
    """PRD §3.5: "the enrollment's `lifetime_redeemed_cents` and
    `lifetime_match_cents` grow by the applied and matched amounts
    respectively." and on void: "the enrollment's `lifetime_redeemed_cents`
    and `lifetime_match_cents` are reduced by the applied and matched
    amounts."

    Design: Corner/cross_cutting_complexity_layers/c_derived_fields_reconcile_after_void
    """
    ctx = setup_settled_redemption()
    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["lifetime_redeemed_cents"] == 3000
    assert enrollment["lifetime_match_cents"] == 2000

    validate_success(api.void_redemption(
        ctx["redemption"]["id"], {"reason": "register error"}, ADMIN), 200)

    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["lifetime_redeemed_cents"] == 0
    assert enrollment["lifetime_match_cents"] == 0


# ---------------------------------------------------------------------------
# Depth instance: per-line rounding of the Double-Up match
# ---------------------------------------------------------------------------

def _multiplier_half_context():
    """Program with double_up_multiplier 0.5; enrollment household 1 STANDARD
    T1 -> face 10000; voucher ISSUED."""
    return setup_issued_voucher(
        with_retailer=True,
        program_overrides={"double_up_multiplier": 0.5},
        household_size=1)


def test_double_up_match_rounds_per_line_then_sums(api):
    """PRD §2.6: "The Double-Up match, by contrast, rounds each
    produce-eligible line individually and then sums the rounded line matches;
    rounding the unrounded sum instead yields different numbers and is not
    permitted."

    Design: Difficulty/combinatorial_formula/double_up_match_per_line_rounding
    """
    ctx = _multiplier_half_context()
    retailer = ctx["retailer"]
    lines = [
        {"category": "PRODUCE_ELIGIBLE", "amount_cents": 101},
        {"category": "PRODUCE_ELIGIBLE", "amount_cents": 101},
        {"category": "PRODUCE_ELIGIBLE", "amount_cents": 103},
    ]
    redemption = validate_success(api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=lines),
        make_retailer_staff_headers(retailer["id"])), 201)
    # Per-line round-half-up: 51 + 51 + 52 == 154; round(305 * 0.5) == 153
    # would be the forbidden sum-then-round order.
    assert redemption["match_cents"] == 154


def test_double_up_tender_split_after_per_line_rounding(api):
    """PRD §3.5: "The `voucher_applied_cents` is the smaller of that voucher's
    `remaining_cents` and the subtotal minus the match — or zero when no
    ISSUED voucher exists, in which case the redemption's `voucher_id` is left
    empty; otherwise `voucher_id` records the voucher actually debited.
    Whatever is left is the patient's own money: `patient_pay_cents` equals
    the subtotal minus the match minus the voucher-applied amount."
    PRD §2.6: "The Double-Up match, by contrast, rounds each produce-eligible
    line individually and then sums the rounded line matches; rounding the
    unrounded sum instead yields different numbers and is not permitted."

    Design: Difficulty/combinatorial_formula/double_up_match_per_line_rounding
    """
    ctx = _multiplier_half_context()
    retailer = ctx["retailer"]
    lines = [
        {"category": "PRODUCE_ELIGIBLE", "amount_cents": 101},
        {"category": "PRODUCE_ELIGIBLE", "amount_cents": 101},
        {"category": "PRODUCE_ELIGIBLE", "amount_cents": 103},
    ]
    redemption = validate_success(api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=lines),
        make_retailer_staff_headers(retailer["id"])), 201)
    assert redemption["subtotal_cents"] == 305
    assert redemption["match_cents"] == 154
    assert redemption["voucher_applied_cents"] == 151  # min(10000, 305 - 154)
    assert redemption["patient_pay_cents"] == 0


# ---------------------------------------------------------------------------
# Depth instance: daily match cap boundary
# ---------------------------------------------------------------------------

def _daily_cap_context():
    """Program with double_up_daily_cap_cents 1000, multiplier 1.0; enrollment
    household 2 -> face 12500; voucher ISSUED."""
    return setup_issued_voucher(
        with_retailer=True,
        program_overrides={"double_up_daily_cap_cents": 1000})


def test_daily_match_cap_exact_boundary_allowed(api):
    """PRD §3.5: "The cap is inclusive at the boundary — a redemption that
    brings the day's matched total exactly to the cap is allowed — and hitting
    a cap clamps the match to the remaining amount rather than producing an
    error."

    Design: Difficulty/boundary_precision_check/daily_match_cap_exact_boundary
    """
    ctx = _daily_cap_context()
    retailer = ctx["retailer"]
    r1 = create_settled_redemption(
        ctx, lines=[{"category": "PRODUCE_ELIGIBLE", "amount_cents": 600}])
    assert r1["match_cents"] == 600

    r2 = validate_success(api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=[{"category": "PRODUCE_ELIGIBLE",
                                          "amount_cents": 400}]),
        make_retailer_staff_headers(retailer["id"])), 201)
    # Cumulative 600 + 400 == 1000 == cap exactly: allowed in full.
    assert r2["match_cents"] == 400


def test_daily_match_cap_clamps_next_redemption_to_zero(api):
    """PRD §3.5: "The cap is inclusive at the boundary — a redemption that
    brings the day's matched total exactly to the cap is allowed — and hitting
    a cap clamps the match to the remaining amount rather than producing an
    error."

    Design: Difficulty/boundary_precision_check/daily_match_cap_exact_boundary
    """
    ctx = _daily_cap_context()
    retailer = ctx["retailer"]
    create_settled_redemption(
        ctx, lines=[{"category": "PRODUCE_ELIGIBLE", "amount_cents": 600}])
    create_settled_redemption(
        ctx, lines=[{"category": "PRODUCE_ELIGIBLE", "amount_cents": 400}])

    r3 = validate_success(api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=[{"category": "PRODUCE_ELIGIBLE",
                                          "amount_cents": 500}]),
        make_retailer_staff_headers(retailer["id"])), 201)
    assert r3["match_cents"] == 0
    assert r3["voucher_applied_cents"] == 500


# ---------------------------------------------------------------------------
# Depth instance: funding-pool conservation across redemption and void
# ---------------------------------------------------------------------------

def test_pool_ledger_conserved_across_settlement(api):
    """PRD §2.8: "`available_cents` is whatever is left — the committed amount
    minus disbursed minus reserved. Issuance moves money from available into
    reserved; settlement moves it from reserved into disbursed; voucher expiry
    and voucher voiding release it from reserved back into available."

    Design: Difficulty/compensating_invariant/funding_pool_conservation_across_redemption_void
    """
    ctx = setup_issued_voucher(with_retailer=True)
    pool = get_pool(ctx["pool"]["id"])
    assert (pool["available_cents"], pool["reserved_cents"],
            pool["disbursed_cents"]) == (487500, 12500, 0)
    assert_pool_ledger_conserved(pool)

    create_settled_redemption(ctx)
    pool = get_pool(ctx["pool"]["id"])
    assert (pool["available_cents"], pool["reserved_cents"],
            pool["disbursed_cents"]) == (487500, 9500, 3000)
    assert_pool_ledger_conserved(pool)


def test_pool_ledger_conserved_across_void(api):
    """PRD §2.8: "`available_cents` is whatever is left — the committed amount
    minus disbursed minus reserved."
    PRD §3.5: "The compensation is exact: the voucher's `redeemed_cents` is
    reduced by the applied amount, returning it from EXHAUSTED to ISSUED if
    its remaining cents become positive again; the pool's `disbursed_cents` is
    reduced by the applied amount and its `reserved_cents` increased by it,
    since the voucher stands ISSUED once more; the program's
    `double_up_matched_cents` is reduced by the match and
    `double_up_remaining_cents` restored; and the enrollment's
    `lifetime_redeemed_cents` and `lifetime_match_cents` are reduced by the
    applied and matched amounts."

    Design: Difficulty/compensating_invariant/funding_pool_conservation_across_redemption_void
    """
    ctx = setup_settled_redemption()
    validate_success(api.void_redemption(
        ctx["redemption"]["id"], {"reason": "register error"},
        make_retailer_staff_headers(ctx["retailer"]["id"])), 200)

    pool = get_pool(ctx["pool"]["id"])
    assert (pool["available_cents"], pool["reserved_cents"],
            pool["disbursed_cents"]) == (487500, 12500, 0)
    assert_pool_ledger_conserved(pool)


# ---------------------------------------------------------------------------
# Depth instance: Double-Up pool conservation across redemption and void
# ---------------------------------------------------------------------------

def _du_pool_5000_context():
    return setup_settled_redemption(
        program_overrides={"double_up_pool_cents": 5000})


def test_double_up_ledger_after_settlement(api):
    """PRD §2.8: "`double_up_pool_cents` is the total incentive budget
    configured at creation, `double_up_matched_cents` accumulates the match
    granted by settled, non-voided redemptions, and
    `double_up_remaining_cents` is the budget minus the matched sum."

    Design: Difficulty/compensating_invariant/double_up_pool_conservation_across_redemption_void
    """
    ctx = _du_pool_5000_context()
    program = get_program(ctx["program"]["id"])
    assert program["double_up_matched_cents"] == 2000
    assert program["double_up_remaining_cents"] == 3000
    assert_double_up_ledger_conserved(program)


def test_double_up_ledger_restored_after_void(api):
    """PRD §2.8: "`double_up_matched_cents` accumulates the match granted by
    settled, non-voided redemptions, and `double_up_remaining_cents` is the
    budget minus the matched sum."
    PRD §3.5: "The compensation is exact: the voucher's `redeemed_cents` is
    reduced by the applied amount, returning it from EXHAUSTED to ISSUED if
    its remaining cents become positive again; the pool's `disbursed_cents` is
    reduced by the applied amount and its `reserved_cents` increased by it,
    since the voucher stands ISSUED once more; the program's
    `double_up_matched_cents` is reduced by the match and
    `double_up_remaining_cents` restored; and the enrollment's
    `lifetime_redeemed_cents` and `lifetime_match_cents` are reduced by the
    applied and matched amounts."

    Design: Difficulty/compensating_invariant/double_up_pool_conservation_across_redemption_void
    """
    ctx = _du_pool_5000_context()
    validate_success(api.void_redemption(
        ctx["redemption"]["id"], {"reason": "register error"}, ADMIN), 200)

    program = get_program(ctx["program"]["id"])
    assert program["double_up_matched_cents"] == 0
    assert program["double_up_remaining_cents"] == 5000
    assert_double_up_ledger_conserved(program)


# ---------------------------------------------------------------------------
# Depth instance: redemption blocked when the retailer is suspended
# ---------------------------------------------------------------------------

def test_redemption_rejected_when_retailer_suspended(api):
    """PRD §3.5: "The retailer must be ACTIVE (`ERR_RETAILER_SUSPENDED`
    otherwise) and the enrollment must be ACTIVE (`ERR_ENROLLMENT_NOT_ACTIVE`
    otherwise)."
    PRD §3.1: "Suspending a retailer blocks new redemptions there with
    `ERR_RETAILER_SUSPENDED`; already-settled redemptions are unaffected."

    Design: Difficulty/cross_entity_state_dependency/redemption_blocked_when_retailer_suspended
    """
    ctx = setup_issued_voucher(with_retailer=True)
    retailer = ctx["retailer"]
    validate_success(api.suspend_retailer(retailer["id"], ADMIN), 200)

    res = api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=[{"category": "PRODUCE_ELIGIBLE",
                                          "amount_cents": 500}]),
        make_retailer_staff_headers(retailer["id"]))
    validate_error(res, "ERR_RETAILER_SUSPENDED")


def test_rejected_redemption_leaves_enrollment_counters_untouched(api):
    """PRD §3.5: "The retailer must be ACTIVE (`ERR_RETAILER_SUSPENDED`
    otherwise)."
    PRD §3.3: "When all three hold, the referral becomes APPROVED and an
    enrollment is created in one motion: its `program_id` and `patient_id` are
    copied from the referral, its `referral_id` points back to the originating
    referral, its `household_size` is a snapshot of the patient's household
    size at approval time, its `engagement_tier` starts at T1, its lifetime
    counters `lifetime_redeemed_cents` and `lifetime_match_cents` start at
    zero, and `lapsed_at` is empty."

    Design: Difficulty/cross_entity_state_dependency/redemption_blocked_when_retailer_suspended
    """
    ctx = setup_issued_voucher(with_retailer=True)
    retailer = ctx["retailer"]
    validate_success(api.suspend_retailer(retailer["id"], ADMIN), 200)

    res = api.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=[{"category": "PRODUCE_ELIGIBLE",
                                          "amount_cents": 500}]),
        make_retailer_staff_headers(retailer["id"]))
    validate_error(res, "ERR_RETAILER_SUSPENDED")

    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["lifetime_redeemed_cents"] == 0
    assert enrollment["lifetime_match_cents"] == 0
