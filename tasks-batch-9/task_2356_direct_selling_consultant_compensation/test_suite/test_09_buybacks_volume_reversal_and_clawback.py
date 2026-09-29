"""Statutory buybacks and reversals: the five-step settlement, the cascade a refund fires through
a closed period, and the two quantities the system conserves while doing it."""

from test_helpers import (
    assert_buyback_request,
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
CONTROLLER = TEST_USERS["finance_controller_headers"]

INITIAL_CLOCK = "2026-08-01T00:00:00Z"


def _approved_buyback_over_a_paid_run(api):
    """The three-generation period paid and disclosed, with 100 of C's 120 units awaiting refund.

    The settlement is priced at request time, so every figure below is already fixed before the
    controller decides.
    """
    state = fx.setup_paid_run(api)
    state["disclosure"] = fx.draft_and_publish_disclosure(api, state["run"])
    assert state["disclosure"]["status"] == "PUBLISHED", "the run's distribution was published"

    buyback = fx.request_buyback(
        api,
        state["env"],
        state["c"],
        fx.buyback_lines_from_order(state["env"], state["order_c"], "SERUM", 100),
    )
    assert_buyback_request(buyback)
    assert buyback["requested_volume_points"] == 2000, "100 units at twenty points each"
    assert buyback["eligible_wholesale_cents"] == 200000, "100 units at 2,000 cents wholesale"
    assert buyback["gross_refund_cents"] == 180000, "9,000 basis points of the eligible wholesale"
    assert buyback["restocking_fee_bp"] == 500, "180,000 is strictly above the 45,000 free limit"
    assert buyback["restocking_fee_cents"] == 9000, "500 basis points of the gross refund"
    assert buyback["commission_clawback_cents"] == 19333, (
        "23,200 of bonus times 2,000 returned points over 2,400 net points, rounded half up"
    )
    assert buyback["net_refund_cents"] == 151667, "180,000 less 9,000 of fee and 19,333 of clawback"
    assert buyback["unrecovered_clawback_cents"] == 0, "the gross refund absorbed both deductions"
    assert buyback["volume_reversal_period_code"] == "2026-08", "taken from the referenced order"
    assert buyback["status"] == "REQUESTED", "a new request starts at REQUESTED"

    state["buyback"] = fx.approve_buyback(api, buyback)
    assert state["buyback"]["status"] == "APPROVED", "finance approved the return"
    return state


def test_the_refund_returns_the_units_and_moves_the_qualification_row(api):
    """Executing the refund writes the order's returned quantity and both status dimensions, and
    the same 2,000 points come off the consultant's qualification row.

    PRD: "On the order side, each referenced order line's `returned_quantity` is increased by the
    buyback quantity, and the order's `returned_volume_points` — the sum over its lines of
    `volume_points_per_unit` multiplied by `returned_quantity` — and `refunded_cents` — the
    cumulative `net_refund_cents` of refunded buybacks drawn against it — are recomputed; the
    order's `payment_status` becomes `REFUNDED_FULL` when every line is fully returned and
    `REFUNDED_PARTIAL` otherwise, and its `fulfillment_status` becomes `RETURNED_FULL` or
    `RETURNED_PARTIAL` on the same test."

    Design: Difficulty/transitive_cascade/buyback_refund_cascades_order_to_qualification_to_period_to_run_to_disclosure
    """
    state = _approved_buyback_over_a_paid_run(api)
    refunded = fx.refund_buyback(api, state["buyback"])
    assert refunded["status"] == "REFUNDED", "the approved request was executed"
    assert_instant(refunded["refunded_at"], INITIAL_CLOCK, "refunded_at")
    assert refunded["unrecovered_clawback_cents"] == 0, "no receivable survived the settlement"

    order = validate_success(api.get_product_order(state["order_c"]["id"], CONTROLLER))
    assert order["returned_volume_points"] == 2000, "the returned units carry their points back out"
    assert order["payment_status"] == "REFUNDED_PARTIAL", "100 of 120 units is a partial return"
    assert order["fulfillment_status"] == "RETURNED_PARTIAL", "fulfillment follows the same test"
    assert order["refunded_cents"] == 151667, "the order records the net refund drawn against it"
    assert order["total_volume_points"] == 2400, "the original purchase is not rewritten"

    row = fx.qualification_of(api, state["c"]["id"], state["period"]["id"])
    assert row["personal_volume_points"] == 2400, "what was purchased stays on the row"
    assert row["returned_volume_points"] == 2000, "what came back is recorded separately"
    assert row["net_personal_volume_points"] == 400, "2,400 purchased less 2,000 returned"
    assert row["group_volume_points"] == 2400, (
        "group volume stays frozen at its locked value because the period is CLOSED"
    )


def test_a_correction_reaching_a_closed_period_flags_the_run_and_supersedes_the_disclosure(api):
    """The same refund raises correction_pending on the closed period, flags the paid run and
    supersedes the published disclosure, with no silent restatement anywhere.

    PRD: "When it is `LOCKED` or `CLOSED`, the frozen aggregates are left alone and the correction
    is made visible instead: the period's `correction_pending` is set to true, every commission run
    of that period whose `status` is `PAID` has `correction_flagged` set to true, and every
    `PUBLISHED` income disclosure statement of such a run moves `PUBLISHED → SUPERSEDED` with
    `supersede_reason` set to `PERIOD_CORRECTION`."

    Design: Difficulty/transitive_cascade/buyback_refund_cascades_order_to_qualification_to_period_to_run_to_disclosure
    """
    state = _approved_buyback_over_a_paid_run(api)
    fx.refund_buyback(api, state["buyback"])

    period = fx.read_period(api, state["period"]["id"])
    assert period["status"] == "CLOSED", "the period was never reopened by the refund"
    assert period["correction_pending"] is True, "the correction is made visible on the period"
    assert period["total_net_personal_volume_points"] == 1100, (
        "600 plus 100 plus 400, derived from the rows after the reversal"
    )

    run = validate_success(api.get_commission_run(state["run"]["id"], CONTROLLER))
    assert run["status"] == "PAID", "the paid run is flagged, never silently recalculated"
    assert run["correction_flagged"] is True, "the flag is the visible consequence on the run"
    assert run["gross_total_cents"] == 47500, "the run's own figures are left exactly as paid"

    disclosure = validate_success(
        api.get_income_disclosure_statement(state["disclosure"]["id"], CONTROLLER)
    )
    assert disclosure["status"] == "SUPERSEDED", "a corrected period cannot stand as published"
    assert disclosure["supersede_reason"] == "PERIOD_CORRECTION", "the reason names the route"
    assert disclosure["superseded_by_id"] is None, (
        "superseded_by_id is set only when a newer statement replaces this one"
    )

    consultant = fx.read_consultant(api, state["c"]["id"])
    assert consultant["clawback_balance_cents"] == 0, "nothing was left unrecovered to book"
    assert consultant["payout_hold"] is False, "a zero balance re-derives the hold as false"


def test_returned_points_are_conserved_on_every_row_the_refund_touches(api):
    """The same 2,000 points appear on the request, on the order and on the qualification row, and
    the row's purchased total still equals its net plus its returned points.

    PRD: "On the volume side, the consultant's qualification row for the period named by
    `volume_reversal_period_code` has its `returned_volume_points` increased by
    `requested_volume_points` and its `net_personal_volume_points` recomputed."

    Design: Difficulty/compensating_invariant/buyback_refund_conserves_volume_points_across_order_and_qualification
    """
    state = _approved_buyback_over_a_paid_run(api)
    period_before = fx.read_period(api, state["period"]["id"])
    assert period_before["total_net_personal_volume_points"] == 3100, (
        "600 plus 100 plus 2,400 before anything is returned"
    )

    refunded = fx.refund_buyback(api, state["buyback"])
    order = validate_success(api.get_product_order(state["order_c"]["id"], ANALYST))
    row = fx.qualification_of(api, state["c"]["id"], state["period"]["id"])

    assert refunded["requested_volume_points"] == 2000, "the request names the points"
    assert order["returned_volume_points"] == 2000, "the order carries the same number back out"
    assert row["returned_volume_points"] == 2000, "and so does the qualification row"
    assert row["personal_volume_points"] == row["net_personal_volume_points"] + row[
        "returned_volume_points"
    ], "purchased equals net plus returned on the row, with nothing lost in between"
    assert order["returned_volume_points"] <= order["total_volume_points"], (
        "no more points can come back than went in"
    )

    period_after = fx.read_period(api, state["period"]["id"])
    assert period_after["total_net_personal_volume_points"] == 1100, (
        "the period total falls by exactly the 2,000 points that were returned"
    )
    assert period_after["correction_pending"] is True, "the closed period records the correction"
    assert fx.qualification_of(api, state["a"]["id"], state["period"]["id"])[
        "group_volume_points"
    ] == 3100, "A's group volume is still the value frozen at the lock"


def test_reopening_after_the_correction_recomputes_group_volume_to_the_same_total(api):
    """Reversing the run and reopening the period makes the aggregates live again, and every
    recomputed group total agrees with the sum of net personal volume beneath it.

    PRD: "On success `status` becomes `REOPENED` in the transition `CLOSED → REOPENED`,
    `reopen_count` is incremented by 1, `correction_pending` is set to false, and
    `group_volume_points` and `active_leg_count` become live again and are recomputed immediately
    from the current genealogy and volume rather than from whatever was frozen at the last lock."

    Design: Difficulty/compensating_invariant/buyback_refund_conserves_volume_points_across_order_and_qualification
    """
    state = _approved_buyback_over_a_paid_run(api)
    fx.refund_buyback(api, state["buyback"])

    reversed_run = fx.reverse_run(api, state["run"], "buyback correction, period will be reopened")
    assert reversed_run["status"] == "REVERSED", "a reversed run no longer blocks the reopen"

    reopened = fx.reopen_period(api, state["period"], "apply the returned volume to group totals")
    assert reopened["status"] == "REOPENED", "the closed period is exitable through REOPENED"
    assert reopened["reopen_count"] == 1, "reopen_count is incremented by one"
    assert reopened["correction_pending"] is False, "the reopen absorbs the pending correction"
    assert reopened["total_net_personal_volume_points"] == 1100, (
        "the total is the same 1,100 the correction left behind"
    )

    period_id = state["period"]["id"]
    top = fx.qualification_of(api, state["a"]["id"], period_id)
    middle = fx.qualification_of(api, state["b"]["id"], period_id)
    leaf = fx.qualification_of(api, state["c"]["id"], period_id)
    assert leaf["group_volume_points"] == 400, "C's subtree is now just her own net volume"
    assert middle["group_volume_points"] == 500, "B's own 100 plus C's 400"
    assert top["group_volume_points"] == 1100, "A's own 600 plus the 500 beneath her"
    assert (
        top["net_personal_volume_points"]
        + middle["net_personal_volume_points"]
        + leaf["net_personal_volume_points"]
        == top["group_volume_points"]
        == 1100
    ), "the recomputed root group volume equals the sum of the period's net personal volume"


def test_reversal_moves_every_disbursed_cent_from_lifetime_paid_into_clawback(api):
    """The reversal creates no money and destroys none: each earner's lifetime total falls by
    exactly what their clawback balance rises by, and the hold follows the balance.

    PRD: "For each statement whose `payout_status` was `PAID`, the consultant's
    `lifetime_commission_paid_cents` is decreased by that statement's `paid_cents` and their
    `clawback_balance_cents` is increased by the same amount, after which `payout_hold` is set to
    true when `clawback_balance_cents` is above 0 — disbursed money becomes a receivable."

    Design: Difficulty/compensating_invariant/reversal_conserves_commission_cents_between_lifetime_paid_and_clawback
    """
    state = fx.setup_paid_run(api)
    before = {
        label: fx.read_consultant(api, state[label]["id"]) for label in ("a", "b", "c")
    }
    assert before["a"]["lifetime_commission_paid_cents"] == 23800, "A was disbursed in full"
    assert before["c"]["lifetime_commission_paid_cents"] == 23200, "C was disbursed in full"
    assert before["b"]["lifetime_commission_paid_cents"] == 0, "B fell below the minimum payout"
    assert before["b"]["carry_forward_cents"] == 500, "B's 500 cents were carried instead"
    assert before["a"]["payout_hold"] is False, "nobody owes anything before the reversal"
    ledger_before = sum(
        row["lifetime_commission_paid_cents"]
        + row["clawback_balance_cents"]
        + row["carry_forward_cents"]
        for row in before.values()
    )
    assert ledger_before == 47500, "the ledger holds exactly the run's gross total"

    reversed_run = fx.reverse_run(api, state["run"])
    assert reversed_run["status"] == "REVERSED", "a paid run is exitable through REVERSED"
    assert reversed_run["reversed_total_cents"] == 47000, "what had been paid becomes reversed"

    after = {label: fx.read_consultant(api, state[label]["id"]) for label in ("a", "b", "c")}
    assert after["a"]["lifetime_commission_paid_cents"] == 0, "A's lifetime total was undone"
    assert after["a"]["clawback_balance_cents"] == 23800, "and became a receivable of equal size"
    assert after["a"]["payout_hold"] is True, "a positive balance re-derives the hold as true"
    assert after["c"]["lifetime_commission_paid_cents"] == 0, "C's lifetime total was undone"
    assert after["c"]["clawback_balance_cents"] == 23200, "and became a receivable of equal size"
    assert after["c"]["payout_hold"] is True, "C is on hold for the same reason"
    for label in ("a", "c"):
        assert (
            before[label]["lifetime_commission_paid_cents"]
            == after[label]["clawback_balance_cents"]
        ), f"{label}: the cents moved from one term to the other without changing size"


def test_reversal_releases_a_carried_statement_and_voids_all_three(api):
    """B was never paid, so the reversal releases her carry-forward instead of creating a debt, and
    every statement of the run ends VOIDED on both status fields.

    PRD: "For each statement whose `payout_status` was `CARRIED_FORWARD`, the consultant's
    `carry_forward_cents` is decreased by that statement's `carry_forward_cents`."

    Design: Difficulty/compensating_invariant/reversal_conserves_commission_cents_between_lifetime_paid_and_clawback
    """
    state = fx.setup_paid_run(api)
    fx.reverse_run(api, state["run"])

    middle = fx.read_consultant(api, state["b"]["id"])
    assert middle["carry_forward_cents"] == 0, "the 500 cents were released, not turned into debt"
    assert middle["clawback_balance_cents"] == 0, "money never disbursed cannot be reclaimed"
    assert middle["lifetime_commission_paid_cents"] == 0, "B was never paid in the first place"
    assert middle["payout_hold"] is False, "a zero balance leaves the hold false"

    ledger_after = sum(
        fx.read_consultant(api, state[label]["id"])["lifetime_commission_paid_cents"]
        + fx.read_consultant(api, state[label]["id"])["clawback_balance_cents"]
        + fx.read_consultant(api, state[label]["id"])["carry_forward_cents"]
        for label in ("a", "b", "c")
    )
    assert ledger_after == 47000, (
        "the ledger now holds the 47,000 that was disbursed, the 500 carried having been released"
    )

    for label, expected_gross in (("a", 23800), ("b", 500), ("c", 23200)):
        statement = fx.statement_of(
            api, state["run"]["id"], state[label]["id"], status="VOIDED"
        )
        assert statement["status"] == "VOIDED", f"{label}: every active statement is voided"
        assert statement["payout_status"] == "VOIDED", f"{label}: the payout status is voided too"
        assert statement["gross_commission_cents"] == expected_gross, (
            f"{label}: the voided statement still records what it had computed"
        )


def test_the_restocking_fee_is_tiered_on_the_gross_refund_so_returning_more_nets_less(api):
    """Twenty-five units land exactly on the free limit and are refunded whole, while twenty-six
    cross it and pay a fee that leaves the consultant 540 cents worse off.

    PRD: "The tier is keyed on the **gross** refund of step one, before anything is netted;
    re-deriving the tier from the net refund is the classic error and produces a different fee."

    Design: Corner/calculations/restocking_fee_is_tiered_on_the_gross_refund_not_the_purchase
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Stock")
    order = fx.place_and_pay_order(
        api, env, ann, [("SERUM", 60)], order_type="PERSONAL_INVENTORY"
    )
    assert order["total_due_cents"] == 139800, "sixty SERUM in TX cost 139,800 cents"
    assert order["total_volume_points"] == 1200, "sixty units at twenty points each"
    assert k.PLAN_DEFAULTS["restock_free_limit_cents"] == 45000, "the limit the two returns straddle"

    at_limit = fx.request_buyback(
        api, env, ann, fx.buyback_lines_from_order(env, order, "SERUM", 25)
    )
    over_limit = fx.request_buyback(
        api, env, ann, fx.buyback_lines_from_order(env, order, "SERUM", 26)
    )

    assert at_limit["requested_volume_points"] == 500, "twenty-five units at twenty points each"
    assert at_limit["gross_refund_cents"] == 45000, "9,000 basis points of 50,000 wholesale"
    assert at_limit["restocking_fee_bp"] == 0, "landing exactly on the free limit costs nothing"
    assert at_limit["restocking_fee_cents"] == 0, "a zero rate produces a zero fee"
    assert at_limit["commission_clawback_cents"] == 0, "no commission statement exists to claw back"
    assert at_limit["net_refund_cents"] == 45000, "the whole gross refund is paid over"
    assert at_limit["unrecovered_clawback_cents"] == 0, "there is nothing left to recover"

    assert over_limit["gross_refund_cents"] == 46800, "9,000 basis points of 52,000 wholesale"
    assert over_limit["restocking_fee_bp"] == 500, "strictly above the limit charges the fee"
    assert over_limit["restocking_fee_cents"] == 2340, "500 basis points of the gross refund"
    assert over_limit["net_refund_cents"] == 44460, "46,800 less the 2,340-cent fee"
    assert at_limit["net_refund_cents"] - over_limit["net_refund_cents"] == 540, (
        "returning one more unit hands back 540 cents less, a cliff created by the gross-refund tier"
    )

    fx.refund_buyback(api, fx.approve_buyback(api, at_limit))
    settled = validate_success(api.get_buyback_request(at_limit["id"], CONTROLLER))
    assert settled["status"] == "REFUNDED", "the free-limit return was executed"
    assert_instant(settled["refunded_at"], INITIAL_CLOCK, "refunded_at")

    after = validate_success(api.get_product_order(order["id"], ADMIN))
    assert after["payment_status"] == "REFUNDED_PARTIAL", "25 of 60 units came back"
    assert after["fulfillment_status"] == "RETURNED_PARTIAL", "fulfillment follows the same test"
    assert after["returned_volume_points"] == 500, "the returned points are recorded on the order"
    assert after["refunded_cents"] == 45000, "the order records the net refund paid against it"

    consultant = fx.read_consultant(api, ann["id"])
    assert consultant["clawback_balance_cents"] == 0, "nothing was under-recovered"
    assert consultant["payout_hold"] is False, "so no receivable and no hold were created"


def test_a_buyback_line_must_name_an_eligible_resalable_inventory_line(api):
    """Four different lines are refused in turn — wrong order type, ineligible product, more units
    than remain, and damaged stock — and the line that satisfies all four is priced.

    PRD: "Every line's `product_order_id` must name an order belonging to the same consultant,
    whose `order_type` is `PERSONAL_INVENTORY`, whose `payment_status` is `PAID` or
    `REFUNDED_PARTIAL`, and whose lines actually contain the referenced `product_id`; any of those
    failing is `ERR_BUYBACK_LINE_INVALID`, since only the consultant's own paid inventory purchases
    may be returned."

    Design: Corner/endpoints/buyback_lines_must_link_to_an_eligible_inventory_order_line
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Stock")
    inventory = fx.place_and_pay_order(
        api, env, ann, [("SERUM", 10), ("SAMPLE", 10)],
        order_type="PERSONAL_INVENTORY", reference="PAY-INV",
    )
    supply = fx.place_and_pay_order(
        api, env, ann, [("SERUM", 5)], order_type="BUSINESS_SUPPLY", reference="PAY-SUP"
    )
    assert inventory["total_due_cents"] == 25460, "ten SERUM and ten SAMPLE in TX"
    assert supply["total_due_cents"] == 12645, "five SERUM in TX"

    def request(lines):
        return api.create_buyback_request(f.buyback_request_payload(ann["id"], lines), ADMIN)

    validate_error(
        request(fx.buyback_lines_from_order(env, supply, "SERUM", 1)),
        "ERR_BUYBACK_LINE_INVALID",
        422,
    )
    validate_error(
        request(fx.buyback_lines_from_order(env, inventory, "SAMPLE", 1)),
        "ERR_PRODUCT_NOT_BUYBACK_ELIGIBLE",
        422,
    )
    validate_error(
        request(fx.buyback_lines_from_order(env, inventory, "SERUM", 11)),
        "ERR_BUYBACK_QUANTITY_EXCEEDED",
        422,
    )
    validate_error(
        request(fx.buyback_lines_from_order(env, inventory, "SERUM", 5, condition="DAMAGED")),
        "ERR_BUYBACK_CONDITION_INVALID",
        422,
    )

    accepted = validate_success(
        request(fx.buyback_lines_from_order(env, inventory, "SERUM", 10)), 201
    )
    assert_buyback_request(accepted)
    assert accepted["requested_volume_points"] == 200, "ten units at twenty points each"
    assert accepted["eligible_wholesale_cents"] == 20000, "ten units at 2,000 cents wholesale"
    assert accepted["gross_refund_cents"] == 18000, "9,000 basis points of the eligible wholesale"
    assert accepted["net_refund_cents"] == 18000, "below the free limit, with no statement to claw"
    assert accepted["volume_reversal_period_code"] == "2026-08", (
        "the reversal period comes from the source order, not from the clock or the request body"
    )
    assert accepted["status"] == "REQUESTED", "a priced request awaits the finance decision"
