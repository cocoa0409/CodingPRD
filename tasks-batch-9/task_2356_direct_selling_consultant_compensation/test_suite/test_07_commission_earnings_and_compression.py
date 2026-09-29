"""What a statement earns: marginal bonus bands, the cap and haircut order, the senior bump,
override compression and the withholding tier."""

from test_helpers import (
    assert_commission_run,
    assert_commission_statement,
    constants as k,
    factories as f,
    fixtures as fx,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
CONTROLLER = TEST_USERS["finance_controller_headers"]


def _calculated_run(api, period):
    """Lock, close and calculate in one go, returning the CALCULATED run."""
    closed = fx.lock_and_close(api, period)
    return fx.calculate_run(api, fx.create_run(api, closed))


def _five_thousand_point_earner(api, probation: bool):
    """A root consultant with 5,000 net personal volume points, optionally on PROBATION."""
    env = fx.setup_environment(api)
    nora = fx.enroll_root(api, env, "nora@example.com", "Nora Root")
    if probation:
        case = fx.sanction_consultant(
            api,
            nora,
            sanction_level="PROBATION",
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-20T00:00:00Z",
        )
        assert case["status"] == "SANCTIONED", "the sanction was imposed"
    order = fx.place_and_pay_order(
        api, env, nora, [("SERUM", 250)], order_type="BUSINESS_SUPPLY"
    )
    assert order["total_due_cents"] == 582500, (
        "500,000 merchandise plus 82,500 tax with no shipping above the free threshold"
    )
    assert order["total_volume_points"] == 5000, "250 units at twenty points each"
    run = _calculated_run(api, env["periods"]["2026-08"])
    return env, nora, run


def test_the_cap_binds_the_banded_sum_before_the_probation_haircut(api):
    """5,000 points band out to 57,000 cents, the cap cuts that to 50,000 and only then does the
    probation haircut halve it to 25,000.

    PRD: "Step four applies the probation haircut **after** the cap: when the earning consultant's
    `status` is `PROBATION`, `pv_bonus_cents` is the capped amount multiplied by the plan's
    `probation_keep_bp`, divided by 10,000 and rounded half up; for every other status
    `pv_bonus_cents` is the capped amount unchanged."

    Design: Difficulty/combinatorial_formula/pv_bonus_band_sum_then_cap_then_probation_haircut_order
    """
    env, nora, run = _five_thousand_point_earner(api, probation=True)
    consultant = fx.read_consultant(api, nora["id"])
    assert consultant["status"] == "PROBATION", "the sanction put her on probation"
    assert consultant["highest_sanction_order"] == 2, "PROBATION sits at ladder position two"

    row = fx.qualification_of(api, nora["id"], env["periods"]["2026-08"]["id"])
    assert row["net_personal_volume_points"] == 5000, "the whole order posted"
    assert row["group_volume_points"] == 5000, "a root with no downline is its own subtree"
    assert row["active_leg_count"] == 0, "there is no downline to count as a leg"

    statement = fx.statement_of(api, run["id"], nora["id"])
    assert_commission_statement(statement)
    assert statement["paid_as_rank_code"] == "CONSULTANT", (
        "5,000 personal points cannot reach DIRECTOR without an active leg"
    )
    assert statement["pv_bonus_cents"] == 25000, (
        "2,500 plus 9,000 plus 45,500 is 57,000, capped to 50,000, then kept at 5,000 basis points"
    )
    assert statement["pv_bonus_cents"] != 28500, (
        "28,500 is what applying the haircut before the cap would pay"
    )
    assert statement["pv_bonus_cents"] != 50000, (
        "50,000 is what ignoring the PROBATION status would pay"
    )
    assert statement["retail_profit_cents"] == 0, "no retail customer order was placed"
    assert statement["override_total_cents"] == 0, "CONSULTANT pays no override levels"
    assert statement["gross_commission_cents"] == 25000, "the bonus is the whole gross"
    assert statement["withhold_rate_bp"] == 2500, "25,000 is strictly above the 20,000 threshold"
    assert statement["net_payable_cents"] == 25000, "nothing is owed, so nothing is withheld"
    assert run["gross_total_cents"] == 25000, "the run's gross is its one statement's gross"


def test_the_same_volume_without_probation_stops_at_the_cap(api):
    """Identical volume on an ACTIVE consultant is capped at 50,000 cents and left there, so the
    difference between the two runs is the haircut alone.

    PRD: "Step three caps the result: the capped amount is the smaller of the plan's
    `pv_bonus_cap_cents` and the sum of the banded total and the bump."

    Design: Difficulty/combinatorial_formula/pv_bonus_band_sum_then_cap_then_probation_haircut_order
    """
    env, nora, run = _five_thousand_point_earner(api, probation=False)
    assert fx.read_consultant(api, nora["id"])["status"] == "ACTIVE", "no sanction was imposed"
    assert k.PLAN_DEFAULTS["pv_bonus_cap_cents"] == 50000, "the cap the banded sum runs into"
    assert k.PLAN_DEFAULTS["probation_keep_bp"] == 5000, "the haircut that is not applied here"

    statement = fx.statement_of(api, run["id"], nora["id"])
    assert statement["pv_bonus_cents"] == 50000, (
        "the 57,000-cent banded sum is capped, and an ACTIVE status keeps the capped amount"
    )
    assert statement["gross_commission_cents"] == 50000, "the bonus is the whole gross"
    assert statement["withhold_rate_bp"] == 2500, "50,000 is above the withholding threshold"
    assert statement["withholding_cents"] == 0, "withholding is capped by a clawback balance of 0"
    assert statement["net_payable_cents"] == 50000, "the whole capped bonus is payable"
    assert run["gross_total_cents"] == 50000, "the run's gross follows the statement"


def test_dynamic_compression_pulls_the_grandchild_up_to_the_first_paid_level(api):
    """With the middle node below the payline, DYNAMIC pays the grandchild's 2,400 points at level
    one's 800 basis points and forfeits nothing.

    PRD: "Under `DYNAMIC` compression the paid level of a payline-qualified descendant is its
    genealogical level minus its skipped count: the descendant is paid at the level it would occupy
    if every non-qualified ancestor between it and the earner were removed from the tree, so deep
    volume is pulled up into a nearer, better-paying band."

    Design: Difficulty/dual_variant_calc/override_compression_dynamic_vs_static_divergence
    """
    state = fx.setup_closed_three_generation(api)
    run = fx.calculate_run(api, fx.create_run(api, state["period"]))
    assert_commission_run(run)
    assert run["compression_mode_snapshot"] == "DYNAMIC", "the plan's default mode was snapshotted"

    top = fx.statement_of(api, run["id"], state["a"]["id"])
    assert top["pv_bonus_cents"] == 4600, (
        "3,400 of banded bonus plus a 1,200-cent bump on the whole 600 points"
    )
    assert top["override_total_cents"] == 19200, (
        "2,400 points at 800 basis points, the grandchild compressed up to level one"
    )
    middle = fx.statement_of(api, run["id"], state["b"]["id"])
    assert middle["override_total_cents"] == 0, "a CONSULTANT paid-as rung pays no override levels"

    assert run["forfeited_to_company_cents"] == 0, (
        "under DYNAMIC a non-qualified node generates neither a payment nor a forfeiture"
    )
    assert run["gross_total_cents"] == 47500, "the three statements together"
    assert run["distributable_pool_cents"] == 47500, "gross plus a forfeiture of zero"


def test_static_compression_pays_the_literal_level_and_forfeits_the_skipped_gap(api):
    """Recalculating the identical volume under STATIC halves the override to level two's 400 basis
    points and books the skipped node's entitlement as forfeiture instead.

    PRD: "In exchange, the entitlement attached to a gap does not vanish: for every **non**-qualified
    descendant whose genealogical level is at or below the earner's `override_levels`, the amount
    that node would have generated at its own genealogical level is added to the run's
    `forfeited_to_company_cents` instead of being paid to anyone."

    Design: Difficulty/dual_variant_calc/override_compression_dynamic_vs_static_divergence
    """
    state = fx.setup_closed_three_generation(api)
    run = fx.calculate_run(api, fx.create_run(api, state["period"]))
    dynamic_override = fx.statement_of(api, run["id"], state["a"]["id"])["override_total_cents"]
    assert dynamic_override == 19200, "the DYNAMIC baseline before the mode is changed"

    rejected = validate_success(
        api.decide_commission_run_approval(
            run["id"],
            f.approval_decision_payload("REJECT", "recalculate under STATIC compression"),
            CONTROLLER,
        )
    )
    assert rejected["status"] == "DRAFT", "a rejection sends the run back for recalculation"
    assert rejected["compression_mode_snapshot"] is None, "the rejection clears the snapshot"
    assert rejected["gross_total_cents"] == 0, "the rejection resets every run total"

    patched = validate_success(
        api.update_compensation_plan(
            state["env"]["plan"]["id"], {"compression_mode": "STATIC"}, ADMIN
        )
    )
    assert patched["compression_mode"] == "STATIC", "the plan now selects the static algorithm"

    recalculated = fx.calculate_run(api, run)
    assert recalculated["compression_mode_snapshot"] == "STATIC", "the second snapshot differs"
    assert recalculated["calculation_sequence"] == 2, "each calculate increments the sequence"

    top = fx.statement_of(api, run["id"], state["a"]["id"])
    assert top["override_total_cents"] == 9600, (
        "2,400 points at level two's 400 basis points, with no compression at all"
    )
    assert dynamic_override - top["override_total_cents"] == 9600, (
        "the two variants disagree by 9,600 cents of payout on byte-identical volume"
    )
    assert fx.statement_of(api, run["id"], state["b"]["id"])["override_total_cents"] == 0, (
        "the middle node still pays no override under either variant"
    )

    assert recalculated["forfeited_to_company_cents"] == 800, (
        "the skipped node's 100 points at level one's 800 basis points go to the company"
    )
    assert recalculated["gross_total_cents"] == 37900, "the statements lost the compression gain"
    assert recalculated["distributable_pool_cents"] == 38700, (
        "gross plus forfeited is the honest measure of what the plan distributed"
    )


def test_bonus_bands_are_marginal_and_the_minimum_gate_pays_nothing_below_it(api):
    """Four earners sit at 99, 500, 501 and 1,501 points, proving the gate short-circuits, the
    first edge is inclusive and each further point is paid at its own band's rate.

    PRD: "If `net_personal_volume_points` is below the plan's `pv_bonus_min_points`,
    `pv_bonus_cents` is 0 and the calculation stops."

    Design: Corner/calculations/personal_volume_bonus_band_edges_and_the_minimum_gate
    """
    env = fx.setup_environment(api)
    profiles = {
        "P": ("pat@example.com", "Pat Root", 99, 12529),
        "Q": ("quinn@example.com", "Quinn Root", 500, 58250),
        "R": ("rae@example.com", "Rae Root", 501, 58367),
        "S": ("sam@example.com", "Sam Root", 1501, 174867),
    }
    people = {}
    for label, (email, name, units, total) in profiles.items():
        consultant = fx.enroll_consultant(api, env, email, name)
        order = fx.place_and_pay_order(
            api, env, consultant, [("SAMPLE", units)], order_type="BUSINESS_SUPPLY",
            reference=f"PAY-{label}",
        )
        assert order["total_volume_points"] == units, f"{label}: one point per SAMPLE unit"
        assert order["total_due_cents"] == total, f"{label}: the documented order total"
        people[label] = consultant

    run = _calculated_run(api, env["periods"]["2026-08"])
    assert run["statement_count"] == 4, "one statement per qualification row"
    assert run["gross_total_cents"] == 16522, (
        "the four statements together: 0 plus 2,500 plus 2,509 plus 11,513"
    )

    below = fx.statement_of(api, run["id"], people["P"]["id"])
    assert below["net_personal_volume_points"] == 99, "one point below the minimum gate"
    assert below["pv_bonus_cents"] == 0, (
        "the schedule short-circuits below the gate rather than paying 99 points at 500 basis points"
    )
    assert below["gross_commission_cents"] == 0, "nothing else earns on a bare personal order"

    at_edge = fx.statement_of(api, run["id"], people["Q"]["id"])
    assert at_edge["net_personal_volume_points"] == 500, "exactly the first band's ceiling"
    assert at_edge["pv_bonus_cents"] == 2500, "500 points at 500 basis points, the edge inclusive"

    one_over = fx.statement_of(api, run["id"], people["R"]["id"])
    assert one_over["net_personal_volume_points"] == 501, "one point into the second band"
    assert one_over["pv_bonus_cents"] == 2509, (
        "2,500 for the first 500 points plus 9 for the marginal point, not 4,509 at an average rate"
    )

    all_bands = fx.statement_of(api, run["id"], people["S"]["id"])
    assert all_bands["net_personal_volume_points"] == 1501, "one point into the third band"
    assert all_bands["pv_bonus_cents"] == 11513, "2,500 plus 9,000 plus 13, so all three bands pay"
    assert all_bands["gross_commission_cents"] == 11513, (
        "no retail profit and no override anywhere in this flat organisation"
    )


def test_the_senior_bump_rides_the_whole_volume_and_level_one_pays_five_hundred_bp(api):
    """A paid as SENIOR_CONSULTANT takes a bump on all 300 of her points, not on her top band, and
    her one payline-qualified child pays her at level one's rate.

    PRD: "Step two adds a rank bump computed on the **whole** volume rather than on the top band
    alone: when `paid_as_rank_code` is not null and its `rank_order` is at least 2 — that is,
    `SENIOR_CONSULTANT` or higher — the bump is the full `net_personal_volume_points` multiplied by
    `point_value_cents`, multiplied by the plan's `senior_rank_bump_bp`, divided by 10,000 and
    rounded half up once; otherwise the bump is 0."

    Design: Corner/calculations/senior_rank_bump_and_level_one_override_constants_applied
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    bob = fx.enroll_consultant(
        api, env, "bob@example.com", "Bob Mid", sponsor_consultant_id=alice["id"]
    )
    alice = fx.adjust_rank(api, alice, "SENIOR_CONSULTANT")
    order_a = fx.place_and_pay_order(
        api, env, alice, [("SERUM", 15)], order_type="BUSINESS_SUPPLY", reference="PAY-A"
    )
    order_b = fx.place_and_pay_order(
        api, env, bob, [("SERUM", 45)], order_type="BUSINESS_SUPPLY", reference="PAY-B"
    )
    assert order_a["total_due_cents"] == 34950, "fifteen SERUM in TX cost 34,950 cents"
    assert order_b["total_due_cents"] == 104850, "forty-five SERUM in TX cost 104,850 cents"

    run = _calculated_run(api, env["periods"]["2026-08"])
    upline = fx.statement_of(api, run["id"], alice["id"])
    assert upline["paid_as_rank_code"] == "SENIOR_CONSULTANT", (
        "she holds the second rung and qualified for it, so the bump unlocks"
    )
    assert upline["pv_bonus_cents"] == 2100, (
        "1,500 of banded bonus plus a 600-cent bump on the whole 300 points"
    )
    assert upline["override_total_cents"] == 4500, "900 downline points at 500 basis points"
    assert len(upline["override_breakdown"]) == 1, "one paid downline node, one element"
    element = upline["override_breakdown"][0]
    assert element["source_consultant_id"] == bob["id"], "the child is the source"
    assert element["paid_level"] == 1, "a direct child sits at level one"
    assert element["volume_points"] == 900, "the child's own net personal volume"
    assert element["amount_cents"] == 4500, "the element carries the amount it contributed"
    assert upline["gross_commission_cents"] == 6600, "bonus plus override"

    downline = fx.statement_of(api, run["id"], bob["id"])
    assert downline["paid_as_rank_code"] == "CONSULTANT", "she has no active leg of her own"
    assert downline["pv_bonus_cents"] == 6100, (
        "2,500 for the first band plus 3,600 for the next 400 points, with no bump at rung one"
    )
    assert downline["override_total_cents"] == 0, "CONSULTANT carries no override levels"

    assert run["gross_total_cents"] == 12700, "both statements together"
    assert run["forfeited_to_company_cents"] == 0, "no level was wasted, so nothing was forfeited"
    assert run["compression_mode_snapshot"] == "DYNAMIC", "the plan's default mode"


def test_the_withholding_tier_flips_one_cent_above_the_threshold_yet_recovers_nothing(api):
    """A gross of exactly 20,000 keeps the low rate while 20,100 moves to the high rate, and
    neither statement withholds a cent because neither consultant owes anything.

    PRD: "`withhold_rate_bp` is the plan's `withhold_high_bp` when `gross_commission_cents` is
    strictly above the plan's `withhold_tier_threshold_cents`, and the plan's `withhold_low_bp`
    when it is at or below that threshold — a statement sitting exactly on the threshold takes the
    low rate."

    Design: Corner/calculations/withholding_rate_tier_flips_one_cent_above_the_threshold
    """
    env = fx.setup_environment(api)
    xena = fx.enroll_consultant(api, env, "xena@example.com", "Xena Root")
    yuri = fx.enroll_consultant(api, env, "yuri@example.com", "Yuri Root")
    order_x = fx.place_and_pay_order(
        api, env, xena, [("SERUM", 5), ("CATALOG", 95)], order_type="RETAIL_CUSTOMER",
        reference="PAY-X",
    )
    order_y = fx.place_and_pay_order(
        api, env, yuri, [("SERUM", 5), ("CATALOG", 96)], order_type="RETAIL_CUSTOMER",
        reference="PAY-Y",
    )
    assert order_x["total_due_cents"] == 23713, "the documented total for the smaller order"
    assert order_y["total_due_cents"] == 23829, "one more catalogue unit costs 116 cents more"

    run = _calculated_run(api, env["periods"]["2026-08"])
    on_threshold = fx.statement_of(api, run["id"], xena["id"])
    assert on_threshold["retail_profit_cents"] == 19500, (
        "2,000 cents of margin on each of five SERUM plus 100 on each of ninety-five catalogues"
    )
    assert on_threshold["pv_bonus_cents"] == 500, "100 points at the first band's 500 basis points"
    assert on_threshold["gross_commission_cents"] == 20000, "exactly the tier threshold"
    assert on_threshold["withhold_rate_bp"] == 1000, "landing on the threshold keeps the low tier"
    assert on_threshold["withholding_cents"] == 0, (
        "withholding is the smaller of the tier amount and a clawback balance of 0"
    )
    assert on_threshold["net_payable_cents"] == 20000, "the whole gross is payable"

    above_threshold = fx.statement_of(api, run["id"], yuri["id"])
    assert above_threshold["retail_profit_cents"] == 19600, "one more catalogue unit of margin"
    assert above_threshold["gross_commission_cents"] == 20100, "one hundred cents above the tier"
    assert above_threshold["withhold_rate_bp"] == 2500, "strictly above the threshold takes 2,500"
    assert above_threshold["withholding_cents"] == 0, (
        "the rate is recorded for audit even when nothing is recovered"
    )
    assert above_threshold["net_payable_cents"] == 20100, "the whole gross is payable here too"

    assert run["withheld_total_cents"] == 0, "the run recovered nothing at either rate"
    assert run["net_payable_total_cents"] == 40100, "both statements are payable in full"


def test_retail_profit_counts_only_paid_retail_customer_orders(api):
    """An unpaid retail order and a paid business-supply order are both excluded from retail
    profit, while personal volume counts every paid order whatever its type.

    PRD: "`retail_profit_cents` is computed over the orders whose `consultant_id` is the
    statement's consultant, whose `posted_period_code` equals the run's `period_code`, whose
    `order_type` is `RETAIL_CUSTOMER`, and whose `payment_status` is `PAID` or `REFUNDED_PARTIAL`."

    Design: Corner/calculations/retail_profit_only_counts_paid_retail_customer_orders
    """
    env = fx.setup_environment(api)
    xena = fx.enroll_consultant(api, env, "xena@example.com", "Xena Root")
    period = env["periods"]["2026-08"]

    paid_retail = fx.place_and_pay_order(
        api, env, xena, [("SERUM", 5), ("CATALOG", 95)], order_type="RETAIL_CUSTOMER",
        reference="PAY-R1",
    )
    assert paid_retail["total_due_cents"] == 23713, "the paid retail order"
    pending_retail = fx.place_order(
        api, env, xena, [("SERUM", 3)], order_type="RETAIL_CUSTOMER"
    )
    assert pending_retail["payment_status"] == "PENDING", "the second retail order is left unpaid"
    paid_supply = fx.place_and_pay_order(
        api, env, xena, [("SERUM", 4)], order_type="BUSINESS_SUPPLY", reference="PAY-B1"
    )
    assert paid_supply["total_due_cents"] == 10315, "the paid business-supply order"

    fx.lock_period(api, period)
    row = fx.qualification_of(api, xena["id"], period["id"])
    assert row["personal_volume_points"] == 180, (
        "100 points from the paid retail order and 80 from the paid supply order"
    )
    assert row["retail_volume_points"] == 100, "the catalogue units carry no points"
    assert row["inventory_volume_points"] == 0, "no personal-inventory order exists"

    fx.close_period(api, period)
    run = fx.calculate_run(api, fx.create_run(api, fx.read_period(api, period["id"])))
    statement = fx.statement_of(api, run["id"], xena["id"])
    assert statement["retail_profit_cents"] == 19500, (
        "only the paid retail order contributes: 25,500 would include the unpaid one and 27,500 "
        "would include the business supply"
    )
    assert statement["net_personal_volume_points"] == 180, (
        "personal volume follows payment alone, not the order type"
    )
    assert statement["pv_bonus_cents"] == 900, "180 points at the first band's 500 basis points"
    assert statement["gross_commission_cents"] == 20400, "retail profit plus the bonus"
    assert statement["withhold_rate_bp"] == 2500, "20,400 is above the withholding threshold"


def test_the_compression_snapshot_is_taken_at_calculate_not_at_run_creation(api):
    """A run opened while the plan was DYNAMIC records no mode at all, and picks up STATIC from
    the plan as it stands at the moment calculate runs.

    PRD: "The run then records `compression_mode_snapshot` as the plan's current
    `compression_mode`, increments `calculation_sequence` by 1, sets `calculated_by_user_id` to the
    calling analyst's `X-User-ID`, refreshes `gross_total_cents`, `forfeited_to_company_cents`,
    `distributable_pool_cents`, `withheld_total_cents`, `net_payable_total_cents` and
    `statement_count`, and moves to `CALCULATED`."

    Design: Corner/calculations/compression_variant_is_selected_at_calculate_time_not_at_run_creation
    """
    state = fx.setup_single_earner_closed_period(api)
    run = fx.create_run(api, state["period"])
    assert run["status"] == "DRAFT", "the run was opened while the plan was still DYNAMIC"
    assert run["compression_mode_snapshot"] is None, (
        "creation records no mode: only calculate populates the snapshot"
    )

    before_patch = validate_success(
        api.get_compensation_plan(state["env"]["plan"]["id"], ADMIN)
    )
    patched = validate_success(
        api.update_compensation_plan(
            state["env"]["plan"]["id"], {"compression_mode": "STATIC"}, ADMIN
        )
    )
    assert patched["compression_mode"] == "STATIC", "the plan was patched between the two steps"
    assert patched["version"] == before_patch["version"] + 1, (
        "the patch incremented the plan's version by exactly 1; the enrollments that built this "
        "fixture had already bumped it by mutating consultant_count"
    )

    calculated = fx.calculate_run(api, run)
    assert calculated["compression_mode_snapshot"] == "STATIC", (
        "the variant is chosen by the plan value read at calculate time"
    )
    assert calculated["calculation_sequence"] == 1, "the first calculation of this run"
    assert calculated["calculated_by_user_id"] == k.ANALYST_USER_ID, "the analyst is recorded"
    assert calculated["gross_total_cents"] == 3400, (
        "a single-node tree earns the same under either mode, so only the snapshot reveals it"
    )
    assert calculated["forfeited_to_company_cents"] == 0, "there is no downline gap to forfeit"
