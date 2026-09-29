"""Composed invoice pricing, payroll charge rollup and media lifecycle cycling.

Three concerns share this module because each one turns on a *pinned evaluation
order* rather than on a single formula.  The procurement invoice rounds its
regional handling surcharge per line and only then sums, so a one-cent
divergence separates the pinned order from the forbidden one.  The payroll
charge rollup selects its fee-waiver tier from the pre-waiver figure and never
re-derives it from the post-waiver figure, so a charge that falls back below a
tier floor keeps the tier it was assigned.  And a media line's own status loop
runs a bounded number of times with an escalating fee, while the parent
election's two state axes -- funding and fulfillment -- advance without either
one reading the other.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_EMPTY_ORDER_BATCH,
    ERR_REISSUE_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_account_conservation,
    assert_election_axes,
    assert_instant_equals,
    assert_invoice_totals,
    assert_ledger_matches_account,
    assert_ledger_sequence,
    assert_media_line,
    assert_unchanged,
)
from test_helpers.constants import REGION_AUS, REGION_CHI, REGION_SEA, REGION_SFO
from test_helpers.test_users import (
    PROGRAM_ADMIN,
    make_order_desk_headers,
    make_payroll_processor_headers,
)

SEAL_OPERATOR = "desk-sealer"
DESK_HEADERS = make_order_desk_headers(SEAL_OPERATOR)
PAYROLL_OPERATOR = "pay-rollup"
PAYROLL_HEADERS = make_payroll_processor_headers(PAYROLL_OPERATOR)


# =============================================================================
# Module-local scenario builders.  Every test starts against an empty database,
# so each of these walks the documented endpoints from scratch.
# =============================================================================
def _build_priced_batch(api, line_count, unit_price_cents, region_code=REGION_SFO):
    """An OPEN batch of ``line_count`` single-unit lines, then sealed and priced.

    Each line belongs to a distinct employee so no supersede can silently drop
    one, which keeps the priced line count exactly ``line_count``.
    """
    scenario = fx.make_batch_with_n_lines(
        api,
        line_count,
        region_code=region_code,
        unit_price_cents=unit_price_cents,
        seal_user_id=SEAL_OPERATOR,
    )
    scenario["batch"] = validate_success(
        api.seal_order_batch(scenario["batch"]["id"], DESK_HEADERS)
    )
    return scenario


def _build_payroll_rollup(api, pretax_amounts):
    """An employer whose 2026-08 window is LOCKED over one FUNDED election per
    amount in ``pretax_amounts``, plus a DRAFT payroll file for that month.

    The group limit and the category cap both sit above every requested amount,
    so the exclusion split passes each request through untouched and the payroll
    aggregates are exactly the requested figures.

    Returns ``{"employer", "category", "window", "elections", "payroll_file"}``.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 32500}
        ],
        legal_name="Austin Commuter Trust",
        region_code=REGION_AUS,
        transit_group_limit_cents=32500,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
        pretax_ratio_cap_pct=100,
    )
    employer = built["employer"]
    category = built["categories"][0]
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )

    elections = []
    for index, amount_cents in enumerate(pretax_amounts, start=1):
        enrolled = fx.make_enrolled_employee(
            api,
            employer["id"],
            category["id"],
            PROGRAM_ADMIN,
            external_ref=f"PR-{index:02d}",
            work_region_code=REGION_AUS,
        )
        elections.append(
            fx.make_election(
                api,
                enrolled["employee"]["id"],
                window["id"],
                category["id"],
                enrolled["account"]["id"],
                pretax_amount_cents=amount_cents,
                posttax_amount_cents=0,
                media_quantity=0,
            )
        )

    window = validate_success(api.lock_election_window(window["id"], PROGRAM_ADMIN))
    payroll_file = fx.make_draft_payroll_file(
        api, employer["id"], "2026-08", PAYROLL_OPERATOR
    )
    return {
        "employer": employer,
        "category": category,
        "window": window,
        "elections": elections,
        "payroll_file": payroll_file,
    }


def _build_funded_in_transit_election(api):
    """One FUNDED election whose single media line has been shipped, so the
    funding axis reads FUNDED while the fulfillment axis reads IN_TRANSIT."""
    scenario = fx.make_procurement_chain(
        api,
        region_code=REGION_SEA,
        media_quantity=1,
        pretax_amount_cents=8000,
        unit_price_cents=8000,
        seal_user_id=SEAL_OPERATOR,
        release_user_id="desk-releaser",
        stop_after="released",
        media_overrides={"media_type": "SMART_CARD_LOAD", "replacement_fee_cents": 600},
    )
    scenario["window"] = validate_success(
        api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN)
    )
    scenario["order"] = validate_success(
        api.ship_media_order(
            scenario["order"]["id"], {"tracking_ref": "TRK-SEA-0001"}, DESK_HEADERS
        )
    )
    scenario["election"] = fx.read_election(api, scenario["election"]["id"])
    return scenario


def _build_shipped_line_over_spendable_account(api):
    """A still-PENDING election whose media line sits in SHIPPED, over an
    account seeded with 5000 cents so replacement fees are payable."""
    return fx.make_procurement_chain(
        api,
        region_code=REGION_CHI,
        media_quantity=1,
        pretax_amount_cents=1000,
        unit_price_cents=1000,
        seal_user_id=SEAL_OPERATOR,
        release_user_id="desk-releaser",
        stop_after="shipped",
        account_overrides={"opening_rollover_cents": 5000},
        media_overrides={"replacement_fee_cents": 500},
    )


def _report_undelivered(api, order_id, reason):
    return validate_success(
        api.report_media_order_undelivered(order_id, {"reason": reason}, DESK_HEADERS)
    )


def _reissue(api, order_id, payload=None):
    return validate_success(api.reissue_media_order(order_id, payload or {}, DESK_HEADERS))


def _ship(api, order_id, tracking_ref):
    return validate_success(
        api.ship_media_order(order_id, {"tracking_ref": tracking_ref}, DESK_HEADERS)
    )


# =============================================================================
# Invoice pricing: the surcharge rounds per line and only then sums
# =============================================================================
def test_01_three_odd_priced_san_francisco_lines_round_their_surcharge_line_by_line(api):
    """Three identical 1007-cent lines in the 7.5 percent San Francisco region
    each round 75.525 cents of handling surcharge up to 76, so the invoice
    subtotal is 3249 -- one cent above the 3248 that summing the gross amounts
    first and rounding a single aggregate surcharge would produce.

    PRD §2.8: "Second, the regional handling surcharge on a procurement batch is rounded to whole cents **per line** and only then summed; summing the gross amounts first and rounding a single aggregate surcharge is forbidden."
    PRD §3.6: "For each priced line, `line_gross_cents` is `unit_price_cents_snapshot` multiplied by `quantity`"
    PRD §3.6: "`line_surcharge_cents` is that gross amount multiplied by the batch region's handling surcharge percentage and divided by one hundred, **rounded half up to whole cents for that line alone**; and `line_total_cents` is the gross plus the rounded surcharge."
    PRD §3.6: "The regional surcharge percentages are 7.5 percent for `US-CA-SFO`, 6.25 percent for `US-NY-NYC`, 5.0 percent for `US-IL-CHI`, 4.0 percent for `US-WA-SEA` and 2.5 percent for `US-TX-AUS`."
    PRD §3.6: "`subtotal_cents` is the plain integer sum of their `line_total_cents` values"
    PRD §3.6: "Summing the gross amounts first and rounding one aggregate surcharge is forbidden and will produce the wrong invoice."
    PRD §3.6: "The batch then moves `OPEN → SEALED`, `sealed_by_user_id` records the acting `X-User-ID`, `sealed_at` records the current logical clock instant"

    Design: Difficulty/combinatorial_formula/order_batch_invoice_per_line_rounding_then_sum_mode_b
    """
    scenario = _build_priced_batch(api, 3, 1007, region_code=REGION_SFO)

    for order in scenario["orders"]:
        priced = fx.read_media_order(api, order["id"])
        assert_media_line(priced, 1007, 76, 1083)

    batch = scenario["batch"]
    assert_invoice_totals(batch, line_count=3, subtotal_cents=3249, discount_cents=0, total_cents=3249)
    assert batch["total_cents"] != 3248, (
        "3248 is the forbidden sum-the-gross-then-round-once answer"
    )
    assert batch["status"] == "SEALED"
    assert batch["sealed_by_user_id"] == SEAL_OPERATOR
    assert_instant_equals(batch["sealed_at"], "2026-08-01T00:00:00Z", "sealed_at")


def test_02_five_line_batch_rounds_its_bulk_discount_exactly_once_on_the_subtotal(api):
    """Five 1007-cent San Francisco lines each carry 76 cents of per-line
    surcharge for a 5415-cent subtotal, and the 1.5 percent five-to-nine-line
    bulk discount rounds 81.225 up to 81 exactly once against that subtotal,
    leaving a 5334-cent invoice.

    PRD §2.8: "Third, the bulk discount on a batch is rounded exactly once, applied to the already-summed subtotal."
    PRD §3.6: "`line_surcharge_cents` is that gross amount multiplied by the batch region's handling surcharge percentage and divided by one hundred, **rounded half up to whole cents for that line alone**; and `line_total_cents` is the gross plus the rounded surcharge."
    PRD §3.6: "A bulk discount follows, keyed on the line count: batches of 4 lines or fewer earn no discount at all, batches of 5 through 9 lines earn 1.5 percent, and batches of 10 or more lines earn 3.0 percent."
    PRD §3.6: "`discount_cents` is `subtotal_cents` multiplied by that percentage and divided by one hundred, rounded half up exactly once against the already-summed subtotal, and `total_cents` is `subtotal_cents` minus `discount_cents`."

    Design: Difficulty/combinatorial_formula/order_batch_invoice_per_line_rounding_then_sum_mode_b
    """
    scenario = _build_priced_batch(api, 5, 1007, region_code=REGION_SFO)

    surcharges = [fx.read_media_order(api, o["id"])["line_surcharge_cents"] for o in scenario["orders"]]
    assert surcharges == [76, 76, 76, 76, 76], (
        f"every line rounds its own 75.525 cents up to 76, got {surcharges}"
    )

    batch = scenario["batch"]
    assert_invoice_totals(batch, line_count=5, subtotal_cents=5415, discount_cents=81, total_cents=5334)
    assert batch["status"] == "SEALED"


def test_03_a_batch_holding_no_lines_cannot_be_priced_at_all(api):
    """Sealing is what prices the invoice, so a batch with nothing in it is
    refused outright and stays OPEN with all four invoice figures at zero.

    PRD §3.6: "Sealing requires the batch to be `OPEN`, the current logical clock instant to fall strictly before the governing window's `cutoff_at`, and at least one media line in the batch to be `PENDING` — an empty batch cannot be sealed and is refused with `ERR_EMPTY_ORDER_BATCH`."
    PRD §3.6: "A new batch opens in `status` `OPEN` with `line_count`, `subtotal_cents`, `discount_cents` and `total_cents` all zero and both `sealed_by_user_id` and `released_by_user_id` null"

    Design: Difficulty/combinatorial_formula/order_batch_invoice_per_line_rounding_then_sum_mode_b
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[{"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}],
        region_code=REGION_SFO,
    )
    window = fx.make_open_window(api, built["employer"]["id"], PROGRAM_ADMIN)
    batch = fx.make_open_batch(api, window["id"], REGION_SFO, SEAL_OPERATOR)
    assert_invoice_totals(batch, line_count=0, subtotal_cents=0, discount_cents=0, total_cents=0)

    validate_error(api.seal_order_batch(batch["id"], DESK_HEADERS), ERR_EMPTY_ORDER_BATCH)

    after = fx.read_batch(api, batch["id"])
    assert after["status"] == "OPEN", "a refused seal leaves the batch open"
    assert after["sealed_by_user_id"] is None
    assert after["sealed_at"] is None
    assert_unchanged(batch, after, "line_count", "subtotal_cents", "discount_cents", "total_cents")


# =============================================================================
# Payroll charge rollup: the waiver tier is read from the pre-waiver figure
# =============================================================================
def test_04_fee_waiver_tier_survives_the_charge_dropping_back_below_its_floor(api):
    """Two funded participants contribute 45500 cents of excluded pre-tax; the
    5000-cent administration minimum lifts the pre-waiver charge to 50500, just
    500 above the 50000-cent tier floor, so a 25 percent waiver of the admin fee
    is 1250 and the employer is charged 49250 -- even though 49250 itself would
    have earned no waiver at all.

    PRD §3.9: "Generation then runs a five-step rollup whose evaluation order is pinned, because one step looks circular and is not."
    PRD §3.9: "`participant_count` is the number of distinct `employee_id` values across that scope"
    PRD §3.9: "`total_pretax_cents` is the sum of `excluded_amount_cents` across the scope, and `total_posttax_cents` the sum of `posttax_effective_cents`."
    PRD §3.9: "**Step two** derives the administration fee from headcount alone: `admin_fee_cents` is the larger of a 5000-cent monthly minimum — fifty dollars — and the participant count multiplied by 425 cents per participant."
    PRD §3.9: "**Step three** computes `pre_waiver_charge_cents` as `total_pretax_cents` plus `total_posttax_cents` plus `admin_fee_cents`."
    PRD §3.9: "**Step four** selects the fee waiver tier, and it selects it *from `pre_waiver_charge_cents` and from nothing else*: a pre-waiver charge below 50000 cents earns no waiver, a pre-waiver charge from 50000 cents up to but not including 200000 cents earns a 25 percent waiver, and a pre-waiver charge of 200000 cents or more earns a 50 percent waiver."
    PRD §3.9: "**Step five** sets `employer_charge_cents` to `pre_waiver_charge_cents` minus `fee_waiver_cents`, and the tier is **never** re-derived from that final figure — a charge that drops below a tier boundary because of its own waiver keeps the tier it was assigned."

    Design: Difficulty/combinatorial_formula/payroll_fee_waiver_tier_pinned_to_pre_waiver_charge_mode_c
    """
    scenario = _build_payroll_rollup(api, [30000, 15500])

    generated = validate_success(
        api.generate_payroll_file(scenario["payroll_file"]["id"], PAYROLL_HEADERS)
    )

    assert generated["participant_count"] == 2
    assert generated["total_pretax_cents"] == 45500, (
        f"30000 + 15500 of excluded pre-tax, got {generated['total_pretax_cents']}"
    )
    assert generated["total_posttax_cents"] == 0
    assert generated["admin_fee_cents"] == 5000, (
        "two participants at 425 cents is 850, so the 5000-cent minimum wins"
    )
    assert generated["pre_waiver_charge_cents"] == 50500
    assert generated["fee_waiver_cents"] == 1250, (
        f"25 percent of the 5000-cent admin fee, got {generated['fee_waiver_cents']}"
    )
    assert generated["employer_charge_cents"] == 49250
    assert generated["employer_charge_cents"] != 50500, (
        "50500 is what re-selecting the tier from the post-waiver figure would produce"
    )
    assert generated["status"] == "GENERATED"

    for election in scenario["elections"]:
        assert fx.read_election(api, election["id"])["funding_status"] == "FUNDED", (
            "only FUNDED or SETTLED elections are in scope for the rollup"
        )


def test_05_a_pre_waiver_charge_landing_exactly_on_the_tier_floor_earns_the_waiver(api):
    """A pre-waiver charge of exactly 50000 cents sits on the inclusive floor of
    the 25 percent tier, so the 5000-cent admin fee is waived by 1250 and the
    employer is charged 48750.

    PRD §3.9: "**Step three** computes `pre_waiver_charge_cents` as `total_pretax_cents` plus `total_posttax_cents` plus `admin_fee_cents`."
    PRD §3.9: "**Step four** selects the fee waiver tier, and it selects it *from `pre_waiver_charge_cents` and from nothing else*: a pre-waiver charge below 50000 cents earns no waiver, a pre-waiver charge from 50000 cents up to but not including 200000 cents earns a 25 percent waiver, and a pre-waiver charge of 200000 cents or more earns a 50 percent waiver."
    PRD §3.9: "`fee_waiver_cents` is the `admin_fee_cents` multiplied by that waiver percentage and divided by one hundred, rounded half up exactly once."

    Design: Difficulty/combinatorial_formula/payroll_fee_waiver_tier_pinned_to_pre_waiver_charge_mode_c
    """
    scenario = _build_payroll_rollup(api, [30000, 15000])

    generated = validate_success(
        api.generate_payroll_file(scenario["payroll_file"]["id"], PAYROLL_HEADERS)
    )

    assert generated["total_pretax_cents"] == 45000
    assert generated["admin_fee_cents"] == 5000
    assert generated["pre_waiver_charge_cents"] == 50000, (
        f"the tier floor itself, got {generated['pre_waiver_charge_cents']}"
    )
    assert generated["fee_waiver_cents"] == 1250, "the 50000-cent floor is inclusive"
    assert generated["employer_charge_cents"] == 48750
    assert generated["status"] == "GENERATED"


def test_06_a_pre_waiver_charge_one_cent_short_of_the_floor_earns_nothing(api):
    """One cent below the floor the tier flips: a 49999-cent pre-waiver charge
    earns no waiver at all, so the waiver is zero and the employer is charged
    the whole 49999.

    PRD §3.9: "**Step four** selects the fee waiver tier, and it selects it *from `pre_waiver_charge_cents` and from nothing else*: a pre-waiver charge below 50000 cents earns no waiver, a pre-waiver charge from 50000 cents up to but not including 200000 cents earns a 25 percent waiver, and a pre-waiver charge of 200000 cents or more earns a 50 percent waiver."
    PRD §3.9: "**Step five** sets `employer_charge_cents` to `pre_waiver_charge_cents` minus `fee_waiver_cents`, and the tier is **never** re-derived from that final figure — a charge that drops below a tier boundary because of its own waiver keeps the tier it was assigned."
    PRD §3.9: "**Step two** derives the administration fee from headcount alone: `admin_fee_cents` is the larger of a 5000-cent monthly minimum — fifty dollars — and the participant count multiplied by 425 cents per participant."

    Design: Difficulty/combinatorial_formula/payroll_fee_waiver_tier_pinned_to_pre_waiver_charge_mode_c
    """
    scenario = _build_payroll_rollup(api, [30000, 14999])

    generated = validate_success(
        api.generate_payroll_file(scenario["payroll_file"]["id"], PAYROLL_HEADERS)
    )

    assert generated["total_pretax_cents"] == 44999
    assert generated["pre_waiver_charge_cents"] == 49999
    assert generated["fee_waiver_cents"] == 0, (
        f"below 50000 nothing is waived, got {generated['fee_waiver_cents']}"
    )
    assert generated["employer_charge_cents"] == 49999, (
        "with no waiver the charge is the pre-waiver figure unchanged"
    )
    assert generated["status"] == "GENERATED"


# =============================================================================
# One election, two state axes that never read each other
# =============================================================================
def test_07_shipping_the_pass_moves_only_the_fulfillment_axis(api):
    """The window lock funds the election and credits 8000 cents; recording the
    shipment then walks the fulfillment axis ORDERED -> IN_TRANSIT while the
    funding axis stays exactly where the lock left it.

    PRD §3.3: "An election is the central allocation record of the whole system, and it is unusual in carrying **two entirely independent state dimensions on the same row**."
    PRD §3.4: "Under the **funded basis** — which runs at lock time and sets `exclusion_basis` to `FUNDED_BASIS` — the prior-consumption sum includes only siblings whose `funding_status` is exactly `FUNDED`."
    PRD §3.4: "One ledger entry is appended to that election's benefit account with `entry_type` `CONTRIBUTION`, a positive `amount_cents` equal to the election's `total_amount_cents`"
    PRD §3.7: "At the election level this is the `ORDERED → IN_TRANSIT` step, which holds when no media order of the election is `UNDELIVERED` and at least one is `SHIPPED`."

    Design: Difficulty/non_linear_state_machine/election_funding_and_fulfillment_axes_advance_independently
    """
    scenario = _build_funded_in_transit_election(api)

    election = scenario["election"]
    assert_election_axes(election, funding_status="FUNDED", fulfillment_status="IN_TRANSIT")
    assert election["excluded_amount_cents"] == 8000
    assert election["exclusion_basis"] == "FUNDED_BASIS"

    order = fx.read_media_order(api, scenario["order"]["id"])
    assert order["status"] == "SHIPPED"
    assert order["tracking_ref"] == "TRK-SEA-0001"
    assert order["replacement_count"] == 0
    assert order["replacement_fee_charged_cents"] == 0

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["contributed_cents"] == 8000
    assert account["available_balance_cents"] == 8000
    assert account["fee_charged_cents"] == 0, "a shipment moves no money at all"
    assert_account_conservation(account)
    assert_ledger_sequence(fx.read_ledger(api, account["id"]), [("CONTRIBUTION", 8000, 8000)])


def test_08_a_lost_pass_leaves_the_funded_money_exactly_where_it_was(api):
    """Reporting the shipped pass undelivered drives the fulfillment axis to
    REPLACEMENT_PENDING, and the funding axis does not so much as flinch: the
    election is still FUNDED for the same 8000 cents and the account is
    byte-identical.

    PRD §3.3: "The two axes never read or write each other: an election sitting in `REPLACEMENT_PENDING` because a pass was stolen is still perfectly fundable, and an election sitting in `FUNDED` does not advance one step of fulfillment on its own."
    PRD §3.7: "In both cases the parent election's `fulfillment_status` is re-derived to `REPLACEMENT_PENDING` — reached as `IN_TRANSIT → REPLACEMENT_PENDING` from the shipped path and as `DELIVERED → REPLACEMENT_PENDING` from the delivered path"
    PRD §3.7: "Otherwise, if any candidate order has `status` `UNDELIVERED`, the result is `REPLACEMENT_PENDING`."

    Design: Difficulty/non_linear_state_machine/election_funding_and_fulfillment_axes_advance_independently
    """
    scenario = _build_funded_in_transit_election(api)
    account_before = fx.read_account(api, scenario["account"]["id"])

    order = _report_undelivered(api, scenario["order"]["id"], "LOST")
    assert order["status"] == "UNDELIVERED"
    assert order["undelivered_reason"] == "LOST"

    election = fx.read_election(api, scenario["election"]["id"])
    assert_election_axes(
        election, funding_status="FUNDED", fulfillment_status="REPLACEMENT_PENDING"
    )
    assert election["excluded_amount_cents"] == 8000, (
        "the money side is untouched by a fulfillment failure"
    )
    assert election["exclusion_basis"] == "FUNDED_BASIS"

    account_after = fx.read_account(api, scenario["account"]["id"])
    assert_unchanged(
        account_before,
        account_after,
        "contributed_cents",
        "fee_charged_cents",
        "available_balance_cents",
        "ledger_entry_count",
    )
    assert_account_conservation(account_after)


def test_09_reissuing_the_pass_returns_the_fulfillment_axis_to_ordered_alone(api):
    """The reissue closes the fulfillment loop back to ORDERED and debits the
    600-cent replacement fee, and that debit is the only movement: the funding
    axis is still FUNDED for the same 8000 cents, so the two axes have now moved
    three fulfillment steps with zero funding steps between them.

    PRD §3.7: "The parent election's `fulfillment_status` is re-derived back to `ORDERED` — the `REPLACEMENT_PENDING → ORDERED` step, which holds when no media order of the election is `UNDELIVERED` after the reissue and none is yet `SHIPPED`"
    PRD §3.7: "Alongside the fee, the reissue increments the line's `replacement_count` by 1 and adds the fee to its `replacement_fee_charged_cents`, moves the line `UNDELIVERED → SUBMITTED` on the **same row with the same `quantity`**, and clears `tracking_ref` back to null so the next shipment can record a fresh one."
    PRD §3.7: "Otherwise, when the line's `replacement_count` is currently zero, the fee is the catalogue product's `replacement_fee_cents` exactly."
    PRD §3.7: "one ledger entry is appended to the electing employee's benefit account with `entry_type` `REPLACEMENT_FEE` and a negative `amount_cents` equal to the fee, with `source_entity` `MediaOrder` and `source_id` the line's identifier; the account's `fee_charged_cents` increases by the fee, `available_balance_cents` is recomputed, `ledger_entry_count` is incremented and `BenefitAccount.version` advances by 1."
    PRD §2.10: "a full cycle of report-undelivered followed by reissue mints no additional media units"

    Design: Difficulty/non_linear_state_machine/election_funding_and_fulfillment_axes_advance_independently
    """
    scenario = _build_funded_in_transit_election(api)
    _report_undelivered(api, scenario["order"]["id"], "LOST")

    order = _reissue(api, scenario["order"]["id"], {"waive_replacement_fee": False})
    assert order["status"] == "SUBMITTED"
    assert order["replacement_count"] == 1
    assert order["replacement_fee_charged_cents"] == 600
    assert order["tracking_ref"] is None, "the reissued row awaits a fresh tracking ref"
    assert order["quantity"] == 1, "the same row keeps the same quantity"

    election = fx.read_election(api, scenario["election"]["id"])
    assert_election_axes(election, funding_status="FUNDED", fulfillment_status="ORDERED")
    assert election["excluded_amount_cents"] == 8000
    assert election["entitled_media_units"] == 1

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["contributed_cents"] == 8000
    assert account["fee_charged_cents"] == 600
    assert account["available_balance_cents"] == 7400
    assert_account_conservation(account)
    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(
        entries, [("CONTRIBUTION", 8000, 8000), ("REPLACEMENT_FEE", -600, 7400)]
    )
    assert_ledger_matches_account(account, entries)


# =============================================================================
# The bounded reissue cycle on one media row
# =============================================================================
def test_10_the_first_loop_around_the_reissue_cycle_charges_the_base_fee(api):
    """One lap of SHIPPED -> UNDELIVERED -> SUBMITTED on the same media row
    charges the catalogue's base 500-cent replacement fee exactly once, leaves
    the row's quantity alone and returns the election's fulfillment axis to
    ORDERED while its funding axis stays PENDING.

    PRD §3.7: "Otherwise, when the line's `replacement_count` is currently zero, the fee is the catalogue product's `replacement_fee_cents` exactly."
    PRD §3.7: "Alongside the fee, the reissue increments the line's `replacement_count` by 1 and adds the fee to its `replacement_fee_charged_cents`, moves the line `UNDELIVERED → SUBMITTED` on the **same row with the same `quantity`**, and clears `tracking_ref` back to null so the next shipment can record a fresh one."
    PRD §2.10: "The net media units actually on order for that election is the sum of `quantity` over the election's media order rows whose `status` is `PENDING`, `SUBMITTED`, `SHIPPED`, `DELIVERED` or `UNDELIVERED`"
    PRD §2.10: "a full cycle of report-undelivered followed by reissue mints no additional media units"

    Design: Difficulty/non_linear_state_machine/media_order_reissue_cycle_third_reissue_rejected_at_limit
    """
    scenario = _build_shipped_line_over_spendable_account(api)

    _report_undelivered(api, scenario["order"]["id"], "LOST")
    order = _reissue(api, scenario["order"]["id"])

    assert order["status"] == "SUBMITTED"
    assert order["replacement_count"] == 1
    assert order["replacement_fee_charged_cents"] == 500
    assert order["tracking_ref"] is None
    assert order["quantity"] == 1, "the cycle reuses the row rather than minting units"

    election = fx.read_election(api, scenario["election"]["id"])
    assert_election_axes(election, funding_status="PENDING", fulfillment_status="ORDERED")
    assert election["entitled_media_units"] == 1

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["fee_charged_cents"] == 500
    assert account["available_balance_cents"] == 4500
    assert_account_conservation(account)
    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 5000, 5000), ("REPLACEMENT_FEE", -500, 4500)]
    )
    assert_ledger_matches_account(account, entries)


def test_11_the_second_loop_doubles_the_replacement_fee(api):
    """Round the cycle a second time and the same row's fee escalates to twice
    the catalogue figure -- 1000 cents on this pass, 1500 cumulative -- which is
    only possible if the loop counter is re-read on every lap.

    PRD §3.7: "Otherwise — meaning this is the second reissue of the same row — the fee is that `replacement_fee_cents` multiplied by two, an escalation intended to make repeated loss visible."
    PRD §3.7: "Alongside the fee, the reissue increments the line's `replacement_count` by 1 and adds the fee to its `replacement_fee_charged_cents`, moves the line `UNDELIVERED → SUBMITTED` on the **same row with the same `quantity`**, and clears `tracking_ref` back to null so the next shipment can record a fresh one."
    PRD §3.7: "one ledger entry is appended to the electing employee's benefit account with `entry_type` `REPLACEMENT_FEE` and a negative `amount_cents` equal to the fee, with `source_entity` `MediaOrder` and `source_id` the line's identifier; the account's `fee_charged_cents` increases by the fee, `available_balance_cents` is recomputed, `ledger_entry_count` is incremented and `BenefitAccount.version` advances by 1."

    Design: Difficulty/non_linear_state_machine/media_order_reissue_cycle_third_reissue_rejected_at_limit
    """
    scenario = _build_shipped_line_over_spendable_account(api)
    order_id = scenario["order"]["id"]

    _report_undelivered(api, order_id, "LOST")
    first = _reissue(api, order_id)
    assert (first["replacement_count"], first["replacement_fee_charged_cents"]) == (1, 500)

    _ship(api, order_id, "TRK-CHI-0002")
    _report_undelivered(api, order_id, "DAMAGED")
    second = _reissue(api, order_id)

    assert second["status"] == "SUBMITTED"
    assert second["replacement_count"] == 2
    assert second["replacement_fee_charged_cents"] == 1500, (
        "500 on the first lap plus 1000 on the second, got "
        f"{second['replacement_fee_charged_cents']}"
    )
    assert second["tracking_ref"] is None
    assert second["quantity"] == 1

    account = fx.read_account(api, scenario["account"]["id"])
    assert account["fee_charged_cents"] == 1500
    assert account["available_balance_cents"] == 3500
    assert account["ledger_entry_count"] == 3
    assert_account_conservation(account)
    entries = fx.read_ledger(api, account["id"])
    assert_ledger_sequence(
        entries,
        [
            ("ROLLOVER_IN", 5000, 5000),
            ("REPLACEMENT_FEE", -500, 4500),
            ("REPLACEMENT_FEE", -1000, 3500),
        ],
    )
    assert_ledger_matches_account(account, entries)


def test_12_the_third_reissue_is_refused_at_the_loop_bound(api):
    """A row that has already been reissued twice is at the allowance, so a
    third attempt is refused, no third fee is charged, and the row is left
    parked in UNDELIVERED with its counters exactly as the second lap left them.

    PRD §3.7: "It requires the line's `status` to be `UNDELIVERED` and its `replacement_count` to be strictly below the reissue allowance of 2, so a line that has already been reissued twice is refused with `ERR_REISSUE_LIMIT_EXCEEDED`."
    PRD §3.7: "Otherwise, if any candidate order has `status` `UNDELIVERED`, the result is `REPLACEMENT_PENDING`."
    PRD §3.7: "When the fee is zero, no ledger entry is written and the account is untouched."

    Design: Difficulty/non_linear_state_machine/media_order_reissue_cycle_third_reissue_rejected_at_limit
    """
    scenario = _build_shipped_line_over_spendable_account(api)
    order_id = scenario["order"]["id"]

    _report_undelivered(api, order_id, "LOST")
    _reissue(api, order_id)
    _ship(api, order_id, "TRK-CHI-0002")
    _report_undelivered(api, order_id, "DAMAGED")
    _reissue(api, order_id)
    _ship(api, order_id, "TRK-CHI-0003")
    before = _report_undelivered(api, order_id, "LOST")
    account_before = fx.read_account(api, scenario["account"]["id"])

    validate_error(
        api.reissue_media_order(order_id, {}, DESK_HEADERS), ERR_REISSUE_LIMIT_EXCEEDED
    )

    after = fx.read_media_order(api, order_id)
    assert after["status"] == "UNDELIVERED", "the refused reissue leaves the row parked"
    assert after["undelivered_reason"] == "LOST"
    assert after["replacement_count"] == 2
    assert after["replacement_fee_charged_cents"] == 1500
    assert_unchanged(
        before, after, "status", "replacement_count", "replacement_fee_charged_cents"
    )

    account_after = fx.read_account(api, scenario["account"]["id"])
    assert account_after["fee_charged_cents"] == 1500, "no third fee was charged"
    assert account_after["available_balance_cents"] == 3500
    assert account_after["ledger_entry_count"] == 3
    assert_unchanged(
        account_before,
        account_after,
        "fee_charged_cents",
        "available_balance_cents",
        "ledger_entry_count",
    )
    assert_account_conservation(account_after)

    election = fx.read_election(api, scenario["election"]["id"])
    assert_election_axes(
        election, funding_status="PENDING", fulfillment_status="REPLACEMENT_PENDING"
    )
