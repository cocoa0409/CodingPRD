"""Direct-market invoicing: per-line rounding, tier selection and credit control."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allocation_entries,
    assert_invoice_figures,
    assert_retailer_ledgers,
    assert_version_unchanged,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_retailer_headers


def test_invoice_rounds_every_billed_line_before_summing_them():
    """The three billed lines round to 25458 cents, not to the 25457 of one late rounding.

    PRD: "Rounding each line first and summing afterwards is the required order; discounting the summed gross once and rounding at the end is a different figure and is wrong."

    Design: Difficulty/combinatorial_formula/invoice_total_rounds_each_line_before_summation_mode_b
    """
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"credit_limit_cents": 26453, "opening_units_ytd": 2440},
    )
    covers = state["covers"]
    order = state["order"]

    # 100 standard copies earn 10 of the 1-in-10 cover and 4 of the capped 1-in-25.
    assert_allocation_entries(order, [(covers["B"]["id"], 10), (covers["C"]["id"], 4)])
    assert order["total_units"] == 114

    invoiced = validate_success(
        api_client.invoice_retailer_order(
            order["id"], TEST_USERS["sales_director_headers"]
        )
    )

    # 21945 + 2195 + 1318 = 25458; the summed gross of 46286 at 0.55 would give 25457.
    assert_invoice_figures(
        invoiced,
        discount_tier_applied="BASIC",
        merchandise_net_cents=25458,
        handling_fee_cents=995,
        invoice_total_cents=26453,
    )
    assert invoiced["merchandise_net_cents"] != 25457
    assert invoiced["status"] == "INVOICED"
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]), open_balance_cents=26453
    )


def test_handling_fee_is_waived_only_once_the_rounded_line_nets_reach_five_hundred_dollars():
    """A 25458-cent invoice pays the flat 995 fee while a 73737-cent one pays nothing.

    PRD: "`handling_fee_cents` is then a flat $9.95 — 995 cents — except that it is waived to 0 when `merchandise_net_cents` reaches $500.00, that is 50,000 cents, or more."

    Design: Difficulty/combinatorial_formula/invoice_total_rounds_each_line_before_summation_mode_b
    """
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"credit_limit_cents": 26453, "opening_units_ytd": 2440},
        extra_orders=(({"opening_units_ytd": 2440}, {"standard_qty": 300}),),
    )
    covers = state["covers"]
    small_order, large_order = state["orders"]

    # The 300-copy order earns 30 of the 1-in-10 cover and still only 4 of the capped one.
    assert_allocation_entries(
        large_order, [(covers["B"]["id"], 30), (covers["C"]["id"], 4)]
    )
    assert large_order["total_units"] == 334

    small_invoiced = fixtures.invoice_order(small_order["id"])
    large_invoiced = fixtures.invoice_order(large_order["id"])

    assert_invoice_figures(
        small_invoiced,
        discount_tier_applied="BASIC",
        merchandise_net_cents=25458,
        handling_fee_cents=995,
        invoice_total_cents=26453,
    )
    # 65835 + 6584 + 1318 = 73737; rounding the summed gross once would give 73736.
    assert_invoice_figures(
        large_invoiced,
        discount_tier_applied="BASIC",
        merchandise_net_cents=73737,
        handling_fee_cents=0,
        invoice_total_cents=73737,
    )
    assert large_invoiced["merchandise_net_cents"] != 73736


def test_invoice_bills_at_the_tier_the_cut_off_lock_itself_promoted_the_account_to():
    """The cut-off pushes the account from `ENTRY` to `BASIC`, and the invoice bills at `BASIC`.

    PRD: "The tier is taken from the retailer's `discount_tier` as it stands at invoice time and frozen onto the order as `discount_tier_applied`; because the cut-off lock has already added this order's units to `cumulative_units_ytd`, the tier is inclusive of the very order being invoiced."

    Design: Difficulty/combinatorial_formula/invoice_total_rounds_each_line_before_summation_mode_b
    """
    state = fixtures.setup_solicited_issue_in_scripting()
    issue = state["issue"]

    retailer = fixtures.open_retailer(
        credit_limit_cents=26453, opening_units_ytd=2440
    )
    order = fixtures.draft_and_submit_order(retailer["id"], issue["id"])

    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]),
        cumulative_units_ytd=2440,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )

    fixtures.set_clock("2026-09-23T00:00:00Z")
    fixtures.foc_lock(issue["id"])

    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]),
        cumulative_units_ytd=2554,
        discount_tier="BASIC",
    )

    invoiced = fixtures.invoice_order(order["id"])
    assert_invoice_figures(
        invoiced,
        discount_tier_applied="BASIC",
        merchandise_net_cents=25458,
        invoice_total_cents=26453,
    )
    # Billing the pre-cut-off ENTRY tier would have produced 27772 cents instead.
    assert invoiced["merchandise_net_cents"] != 27772


def test_resubmitting_a_submitted_order_reports_the_state_refusal_not_the_credit_refusal():
    """An already-submitted order on an account sitting on its limit is refused for its state.

    PRD: "Beyond path resolution, several checks may be applicable to the same request, and the order in which they are evaluated is part of the contract, because it decides which error a client sees."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_fiscal_priority_27_on_order_resubmit
    """
    state = _two_issue_order_book_at_the_credit_limit()
    retailer = state["retailer"]
    open_order = state["open_order"]

    before = fixtures.read_order(open_order["id"])
    assert before["status"] == "SUBMITTED"
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]), open_balance_cents=26453
    )

    response = api_client.submit_retailer_order(
        open_order["id"], make_retailer_headers(retailer["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = fixtures.read_order(open_order["id"])
    assert after["status"] == "SUBMITTED"
    assert_version_unchanged(before, after)
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]), open_balance_cents=26453
    )


def test_a_fresh_draft_order_on_the_same_exhausted_account_hits_the_credit_refusal():
    """With the state check satisfied, the account sitting exactly on its limit is refused 402.

    PRD: "And the account must still have credit headroom: at submission the comparison is **strict**, so the retailer's `open_balance_cents` must be strictly less than its `credit_limit_cents`, and an account sitting exactly on its limit may not open new business — that refusal is `ERR_CREDIT_LIMIT_EXCEEDED` with HTTP 402."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_fiscal_priority_27_on_order_resubmit
    """
    state = _two_issue_order_book_at_the_credit_limit()
    retailer = state["retailer"]

    fresh = fixtures.draft_order(retailer["id"], state["second_issue"]["id"])
    assert fresh["status"] == "DRAFT"

    response = api_client.submit_retailer_order(
        fresh["id"], make_retailer_headers(retailer["id"])
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    assert fixtures.read_order(fresh["id"])["status"] == "DRAFT"
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]), open_balance_cents=26453
    )


def _two_issue_order_book_at_the_credit_limit() -> dict:
    """Two solicited issues, one invoiced order and one still-open order.

    The invoice takes the account's `open_balance_cents` to exactly its
    `credit_limit_cents`, so the strict submission comparison can no longer hold.
    """
    fixtures.set_clock()
    creator = fixtures.register_creator()
    title = fixtures.pitch_and_greenlight_title()
    assignment = fixtures.offer_and_accept_assignment(
        title["id"], creator["id"], "SCRIPT", booking_end_date="2026-12-01"
    )

    first_issue = fixtures.schedule_issue(
        title["id"], issue_number=1, target_on_sale_date="2026-10-14"
    )
    second_issue = fixtures.schedule_issue(
        title["id"], issue_number=2, target_on_sale_date="2026-11-04"
    )
    for issue, due in ((first_issue, "2026-09-30"), (second_issue, "2026-10-20")):
        stage = fixtures.book_stage(
            issue["id"], assignment["id"], "SCRIPT", planned_due_date=due
        )
        fixtures.start_stage(stage["id"], creator["id"])

    covers = fixtures.add_covers(first_issue["id"])
    fixtures.add_covers(second_issue["id"], (fixtures.DEFAULT_COVER_SPECS[0],))

    catalog = fixtures.open_catalog()
    solicitations = []
    for issue in (first_issue, second_issue):
        solicitation = fixtures.draft_solicitation(catalog["id"], issue["id"])
        solicitations.append(fixtures.submit_solicitation(solicitation["id"]))

    fixtures.set_clock("2026-08-21T00:00:00Z")
    fixtures.lock_catalog(catalog["id"])
    for solicitation in solicitations:
        fixtures.accept_solicitation(solicitation["id"])
    fixtures.publish_catalog(catalog["id"])

    retailer = fixtures.open_retailer(
        credit_limit_cents=26453, opening_units_ytd=2440
    )
    open_order = fixtures.draft_and_submit_order(retailer["id"], second_issue["id"])
    billed_order = fixtures.draft_and_submit_order(retailer["id"], first_issue["id"])

    fixtures.set_clock("2026-09-23T00:00:00Z")
    fixtures.foc_lock(first_issue["id"])
    billed_order = fixtures.invoice_order(billed_order["id"])

    return {
        "retailer": retailer,
        "covers": covers,
        "first_issue": fixtures.read_issue(first_issue["id"]),
        "second_issue": fixtures.read_issue(second_issue["id"]),
        "open_order": fixtures.read_order(open_order["id"]),
        "billed_order": billed_order,
    }


def test_an_invoice_landing_exactly_on_the_credit_limit_is_accepted():
    """A 26453-cent invoice against a 26453-cent limit is written and takes the balance to it.

    PRD: "That bound is inclusive — an invoice that lands exactly on the limit is accepted, and one cent more is refused with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/credit_limit_cent_boundary_lands_exactly_on_the_limit_versus_one_cent_over
    """
    state = _cent_boundary_order_book()
    exact_order = state["exact_order"]
    exact_retailer = state["exact_retailer"]

    assert exact_order["total_units"] == 114

    invoiced = validate_success(
        api_client.invoice_retailer_order(
            exact_order["id"], TEST_USERS["sales_director_headers"]
        )
    )
    assert invoiced["status"] == "INVOICED"
    assert_invoice_figures(
        invoiced, discount_tier_applied="BASIC", invoice_total_cents=26453
    )

    refreshed = fixtures.read_retailer(exact_retailer["id"])
    assert_retailer_ledgers(refreshed, open_balance_cents=26453, discount_tier="BASIC")
    assert refreshed["open_balance_cents"] == refreshed["credit_limit_cents"]


def test_an_invoice_one_cent_over_the_credit_limit_is_refused_and_writes_nothing():
    """The same 26453-cent invoice against a 26452-cent limit is refused and leaves no figures.

    PRD: "Credit control applies a second time here, and with a **different comparison** from the one at submission: the retailer's current `open_balance_cents` plus the invoice total that this operation computes must be no greater than its `credit_limit_cents`."

    Design: Difficulty/boundary_precision_check/credit_limit_cent_boundary_lands_exactly_on_the_limit_versus_one_cent_over
    """
    state = _cent_boundary_order_book()
    short_order = state["short_order"]
    short_retailer = state["short_retailer"]

    assert short_order["total_units"] == 114

    response = api_client.invoice_retailer_order(
        short_order["id"], TEST_USERS["sales_director_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    unchanged = fixtures.read_order(short_order["id"])
    assert unchanged["status"] == "FOC_LOCKED"
    assert unchanged["discount_tier_applied"] is None
    assert_invoice_figures(
        unchanged,
        merchandise_net_cents=0,
        handling_fee_cents=0,
        invoice_total_cents=0,
    )
    assert_version_unchanged(short_order, unchanged)
    assert_retailer_ledgers(
        fixtures.read_retailer(short_retailer["id"]),
        open_balance_cents=0,
        discount_tier="BASIC",
    )


def _cent_boundary_order_book() -> dict:
    """Two accounts one cent apart, each holding an identical locked 100-copy order."""
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"credit_limit_cents": 26453, "opening_units_ytd": 2440},
        extra_orders=(({"credit_limit_cents": 26452, "opening_units_ytd": 2440}, {}),),
    )
    exact_retailer, short_retailer = state["retailers"]
    exact_order, short_order = state["orders"]
    return {
        "covers": state["covers"],
        "issue": state["issue"],
        "exact_retailer": exact_retailer,
        "short_retailer": short_retailer,
        "exact_order": exact_order,
        "short_order": short_order,
    }
