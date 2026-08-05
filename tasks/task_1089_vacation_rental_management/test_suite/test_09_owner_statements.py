"""Owner-statement splits, provisional vs final divergence, cascade recompute, money
conservation on reopen, and pay/finalize gating.

NOTE ON EXPECTED VALUES: the statement bookings are created while the clock reads
2026-06-01 with check-in dates 2026-06-05/06/07 — a whole-day gap of 4/5/6 days, which is
<= LAST_MINUTE_DAYS (7). PRD §3.3 therefore mandates the 0.85 last-minute factor, so each
booking's nightly_subtotal is round_half_up(10010 * 0.85) = 8509, not 10010. The expected
monetary totals below are the PRD-faithful values (gross 25527, mgmt 3828, payout 21699 /
16699); the distinguishing behaviour of each rule is unchanged.
"""
from test_helpers import (
    validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_work_order_payload, assert_statement_money_conservation, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: management fee rounded per booking then summed
# --------------------------------------------------------------------------- #
def test_statement_gross_rental_sums_nightly_subtotals(api):
    """PRD §3.8: "From these it computes `gross_rental_cents` as the sum of the qualifying
    bookings' `nightly_subtotal_cents`".

    Design: Difficulty/combinatorial_formula/mgmt_fee_round_per_booking_then_sum
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    assert ctx["statement"]["gross_rental_cents"] == 25527, f"got {ctx['statement']['gross_rental_cents']}"


def test_statement_mgmt_fee_rounded_per_booking(api):
    """PRD §2.5: "the management fee is rounded **per booking** before the per-booking amounts
    are summed."
    PRD §3.8: "`mgmt_fee_cents` as the sum of a per-booking management fee, where each
    booking's fee is its `nightly_subtotal_cents` times the owner's `default_management_fee_pct`
    divided by one hundred, rounded half-up per booking before summing".

    Design: Difficulty/combinatorial_formula/mgmt_fee_round_per_booking_then_sum
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    # round_half_up(8509 * 0.15)=1276 per booking, *3 = 3828 (sum-then-round would be 3829)
    assert ctx["statement"]["mgmt_fee_cents"] == 3828, f"got {ctx['statement']['mgmt_fee_cents']}"


# --------------------------------------------------------------------------- #
# Difficulty: provisional vs final payout divergence
# --------------------------------------------------------------------------- #
def test_statement_provisional_payout_at_generation(api):
    """PRD §3.8: "The `owner_payout_cents` is the gross rental minus the management fee minus
    the work-order owner charges."
    PRD §3.8: "While the statement is `DRAFT`, the split is **provisional**:
    `work_order_owner_charges_cents` counts only the work orders already approved and linked at
    generation time, so the payout is provisional."

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_diverge
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    # gross 25527 - mgmt 3828 - 0 charges = 21699
    assert ctx["statement"]["owner_payout_cents"] == 21699, f"got {ctx['statement']['owner_payout_cents']}"
    assert ctx["statement"]["status"] == "DRAFT"


def test_statement_final_payout_differs_after_wo_approval(api):
    """PRD §3.8: "Finalizing recomputes the **final** split, re-aggregating to include any
    owner-billable work orders approved between generation and finalize — the final payout
    differs from the provisional one whenever those charges changed."

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_diverge
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    fixtures.create_approved_owner_work_order(api, ctx["property"]["id"], ctx["owner"]["id"], cost_cents=5000)
    final = get_success_data(api.finalize_statement(ctx["statement"]["id"], PM))
    # 25527 - 3828 - 5000 = 16699, diverging from the provisional 21699
    assert final["owner_payout_cents"] == 16699, f"got {final['owner_payout_cents']}"
    assert final["status"] == "FINALIZED"


# --------------------------------------------------------------------------- #
# Difficulty: work-order approve posts line and recomputes payout (depth-2 cascade)
# --------------------------------------------------------------------------- #
def test_work_order_approve_recomputes_statement_payout(api):
    """PRD §3.7: "the system posts a `WORK_ORDER_CHARGE` statement line with an `amount_cents`
    equal to the negative of the work order's `cost_cents` ... and recomputes the statement's
    `work_order_owner_charges_cents` and `owner_payout_cents` to reflect the new charge."

    Design: Difficulty/transitive_cascade/work_order_approve_posts_line_recomputes_payout
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    assert ctx["statement"]["owner_payout_cents"] == 21699
    wo = fixtures.create_completed_owner_work_order(api, ctx["property"]["id"], cost_cents=5000)
    get_success_data(api.approve_work_order(wo["id"], PM))
    statement = get_success_data(api.get_owner_statement(ctx["statement"]["id"], PM))
    assert statement["work_order_owner_charges_cents"] == 5000, f"got {statement['work_order_owner_charges_cents']}"
    assert statement["owner_payout_cents"] == 16699, f"got {statement['owner_payout_cents']}"


def test_work_order_approve_links_statement_id(api):
    """PRD §3.7: "appends it to the owner's `DRAFT` statement for the property's current
    period, sets the work order's `owner_statement_id` to that statement".

    Design: Difficulty/transitive_cascade/work_order_approve_posts_line_recomputes_payout
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    wo = fixtures.create_completed_owner_work_order(api, ctx["property"]["id"], cost_cents=5000)
    approved = get_success_data(api.approve_work_order(wo["id"], PM))
    assert approved["owner_statement_id"] == ctx["statement"]["id"], (
        f"expected link to {ctx['statement']['id']}, got {approved['owner_statement_id']}")


# --------------------------------------------------------------------------- #
# Difficulty: money conservation on reopen
# --------------------------------------------------------------------------- #
def _finalized_statement_with_owner_charge(api):
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=15, base_nightly_rate_cents=10010,
                                                  occupancy_tax_pct=0, num_bookings=3)
    fixtures.create_approved_owner_work_order(api, ctx["property"]["id"], ctx["owner"]["id"], cost_cents=5000)
    get_success_data(api.finalize_statement(ctx["statement"]["id"], PM))
    return ctx


def test_reopen_preserves_money_conservation(api):
    """PRD §3.8: "Reopening moves a statement `FINALIZED → DRAFT` as a compensating action:
    it removes the derived `TAX_REMITTANCE` line and reverts to the provisional split,
    preserving the money-conservation invariant".
    PRD §2.8: "gross rental minus management fee minus work-order owner charges equals the
    owner payout."

    Design: Difficulty/compensating_invariant/statement_money_conservation_on_reopen
    """
    ctx = _finalized_statement_with_owner_charge(api)
    reopened = get_success_data(api.reopen_statement(ctx["statement"]["id"], PM))
    assert reopened["status"] == "DRAFT"
    assert reopened["gross_rental_cents"] == 25527
    assert reopened["mgmt_fee_cents"] == 3828
    assert reopened["work_order_owner_charges_cents"] == 5000
    assert reopened["owner_payout_cents"] == 16699
    assert_statement_money_conservation(reopened)


def test_reopen_reverts_tax_remittance_to_zero(api):
    """PRD §3.8: "Reopening moves a statement `FINALIZED → DRAFT` as a compensating action:
    it removes the derived `TAX_REMITTANCE` line and reverts to the provisional split".
    PRD §3.8: "Finalizing advances the statement `DRAFT → FINALIZED`, sets `tax_remitted_cents`
    to the sum of `occupancy_tax_cents` over the qualifying bookings (this value is set only at
    finalize)".

    Design: Difficulty/compensating_invariant/statement_money_conservation_on_reopen
    """
    ctx = _finalized_statement_with_owner_charge(api)
    reopened = get_success_data(api.reopen_statement(ctx["statement"]["id"], PM))
    assert reopened["tax_remitted_cents"] == 0, f"expected tax reverted to 0, got {reopened['tax_remitted_cents']}"


# --------------------------------------------------------------------------- #
# Difficulty: pay priority (state beats fiscal)
# --------------------------------------------------------------------------- #
def _draft_statement_with_negative_payout(api):
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=20, base_nightly_rate_cents=10000,
                                                  occupancy_tax_pct=0, num_bookings=1)
    fixtures.create_approved_owner_work_order(api, ctx["property"]["id"], ctx["owner"]["id"], cost_cents=60000)
    return ctx


def test_pay_draft_statement_returns_not_finalized(api):
    """PRD §3.8: "Paying moves a statement `FINALIZED → PAID`; it requires the statement to be
    `FINALIZED` (else `ERR_STATEMENT_NOT_FINALIZED`) and requires `owner_payout_cents` to be
    zero or greater (a negative payout is rejected with `ERR_NEGATIVE_PAYOUT`)."
    PRD §2.6: state checks (priority 5) precede the business-fiscal non-negative-payout check
    (priority 10).

    Design: Difficulty/priority_pair_validation_conflict/pay_state_beats_fiscal
    """
    ctx = _draft_statement_with_negative_payout(api)
    resp = api.pay_statement(ctx["statement"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FINALIZED.value)


def test_pay_rejected_leaves_statement_draft(api):
    """PRD §3.8: "Paying moves a statement `FINALIZED → PAID`; it requires the statement to be
    `FINALIZED` (else `ERR_STATEMENT_NOT_FINALIZED`)".

    Design: Difficulty/priority_pair_validation_conflict/pay_state_beats_fiscal
    """
    ctx = _draft_statement_with_negative_payout(api)
    api.pay_statement(ctx["statement"]["id"], PM)
    assert get_success_data(api.get_owner_statement(ctx["statement"]["id"], PM))["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Difficulty: finalize blocked by open work order
# --------------------------------------------------------------------------- #
def _draft_statement_with_open_work_order(api):
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=20, base_nightly_rate_cents=10000,
                                                  occupancy_tax_pct=0, num_bookings=1)
    get_success_data(api.create_work_order(create_work_order_payload(ctx["property"]["id"], 3000, "COMPANY"), PM))
    return ctx


def test_finalize_blocked_by_open_work_order(api):
    """PRD §3.8: "Finalizing is blocked while any work order on the owner's properties for the
    period is still in a non-terminal status (`OPEN`, `ASSIGNED`, `IN_PROGRESS`, `NEEDS_INFO`,
    or `COMPLETED`); such an attempt is rejected with `ERR_OPEN_WORK_ORDERS`."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_open_work_order
    """
    ctx = _draft_statement_with_open_work_order(api)
    resp = api.finalize_statement(ctx["statement"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_OPEN_WORK_ORDERS.value)


def test_finalize_blocked_leaves_statement_draft(api):
    """PRD §3.8: "Finalizing advances the statement `DRAFT → FINALIZED` ... Finalizing is
    blocked while any work order on the owner's properties for the period is still in a
    non-terminal status".

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_open_work_order
    """
    ctx = _draft_statement_with_open_work_order(api)
    api.finalize_statement(ctx["statement"]["id"], PM)
    assert get_success_data(api.get_owner_statement(ctx["statement"]["id"], PM))["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Corner: pay finalized statement with negative payout
# --------------------------------------------------------------------------- #
def test_pay_finalized_negative_payout_rejected(api):
    """PRD §3.8: "requires `owner_payout_cents` to be zero or greater (a negative payout is
    rejected with `ERR_NEGATIVE_PAYOUT`)."

    Design: Corner/errors/pay_finalized_negative_payout_rejected
    """
    ctx = fixtures.setup_owner_statement_scenario(api, mgmt_fee_pct=20, base_nightly_rate_cents=10000,
                                                  occupancy_tax_pct=0, num_bookings=1)
    fixtures.create_approved_owner_work_order(api, ctx["property"]["id"], ctx["owner"]["id"], cost_cents=60000)
    finalized = get_success_data(api.finalize_statement(ctx["statement"]["id"], PM))
    assert finalized["status"] == "FINALIZED"
    resp = api.pay_statement(ctx["statement"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_PAYOUT.value)
