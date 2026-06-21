"""Second assertion-angle for each depth-design instance.

Every depth instance is covered by at least two tests: the primary scenario lives
in test_01..test_04, and this file pins a second, distinct observable of the same
rule (a different field, ledger line, or boundary side) so a faithful-but-wrong
implementation has two independent chances to be caught.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    fixtures,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
)

PUB = TEST_USERS["publisher_headers"]


# ==========================================================================
# dual_variant_calc
# ==========================================================================
def test_liquidated_reserve_release_credits_period_earnings(api):
    """PRD §3.9: "Fourth, the period's earnings, `period_earnings_cents`, is the
    sum of `royalty_credited_cents`, `reserve_released_cents`, and
    `subsidiary_income_cents`."

    PRD §3.8: "The released portion flows up as a credit into the finalizing
    statement's `reserve_released_cents`."

    The period-3 statement that liquidates R1 carries reserve_released_cents
    281250 inside its period_earnings — a different committed number than the
    period-1 royalty_credited that withheld it.

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_after_reserve_liquidation
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=2000000, reserve_pct=0.25,
        reserve_hold_periods=2, agent_commission_pct=0.15, with_agent=True,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 5000, 400)
    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 200)
    s3 = fixtures.finalize_statement(p3["statement"]["id"], cid)

    assert s3["reserve_released_cents"] == 281250
    assert (
        s3["period_earnings_cents"]
        == s3["royalty_credited_cents"] + s3["reserve_released_cents"] + s3["subsidiary_income_cents"]
    )


def test_net_to_author_uses_post_recoupment_commission(api):
    """PRD §3.9: "Finally, `net_to_author_cents` is `payable_before_commission_cents`
    minus `agent_commission_cents` minus `tax_withheld_cents`."

    With payable 2406250, commission 360938 (post-recoupment base), and tax 0 at
    finalize, net_to_author = 2406250 - 360938 - 0 = 2045312.

    Design: Difficulty/dual_variant_calc/agent_commission_base_net_payable_vs_gross_earnings
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=2000000, reserve_pct=0.25,
        reserve_hold_periods=2, agent_commission_pct=0.15, with_agent=True,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    get_success_data(
        api.create_subsidiary_right(
            cid, {"right_type": "FOREIGN", "proceeds_cents": 4000000, "author_share_pct": 0.75}, PUB
        )
    )
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 6000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)

    assert s1["agent_commission_cents"] == 360938
    assert s1["net_to_author_cents"] == 2406250 - 360938


# ==========================================================================
# combinatorial_formula
# ==========================================================================
def test_straddle_reserve_credited_reflects_gross(api):
    """PRD §3.9: "First, `royalty_credited_cents` is `gross_royalty_cents` minus
    the period's `reserve_held_cents`"

    Gross 1950000 from the straddle (reserve_pct=0.25 -> reserve 487500) leaves
    royalty_credited 1462500.

    Design: Difficulty/combinatorial_formula/tiered_royalty_escalator_three_input_nonlinear
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=2
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    p2 = fixtures.run_period_to_closed(cid, fid, "P2", 2, 5000, 0)
    s2 = get_success_data(api.generate_statement(p2["id"], PUB))

    assert s2["gross_royalty_cents"] == 1950000
    assert s2["reserve_held_cents"] == 487500
    assert s2["royalty_credited_cents"] == 1462500


def test_per_format_then_sum_higher_priced_pair(api):
    """PRD §3.7: "each format's subtotal rounded to whole cents, and only then are
    the per-format subtotals added together. This per-format-then-sum order is
    canonical and can legitimately differ by a cent from the alternative of summing
    raw values and rounding once"

    Two formats at 555c, 1 unit each, tier-1 0.10: per-unit 55.5c rounds up to 56;
    56+56 = 112, whereas round(111.0) would be 111. Per-format-then-sum pins 112.

    Design: Difficulty/combinatorial_formula/per_format_then_sum_rounding_order_pinned
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    title = fixtures.add_title(contract["id"], name="Pair Book")
    fa = fixtures.add_format(title["id"], format_type="HARDCOVER", list_price_cents=555)
    fb = fixtures.add_format(title["id"], format_type="EBOOK", list_price_cents=555)
    get_success_data(api.activate_contract(contract["id"], PUB))
    get_success_data(api.publish_title(title["id"], PUB))

    period = fixtures.open_period(contract["id"], "P1", 1)
    fixtures.post_sales(period["id"], fa["id"], units_sold=1)
    fixtures.post_sales(period["id"], fb["id"], units_sold=1)
    fixtures.close_period(period["id"])

    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    assert s1["gross_royalty_cents"] == 112


# ==========================================================================
# non_linear_state_machine
# ==========================================================================
def test_tax_and_net_payable_lines_emitted_only_at_pay(api):
    """PRD §3.6: "It emits the `TAX_WITHHELD` and final `NET_PAYABLE`
    `StatementLine` rows and advances the contract's `version` by one."

    PRD §3.6: "`TAX_WITHHELD` and the final `NET_PAYABLE` are emitted at pay."

    Before pay there is no TAX_WITHHELD line; after pay both TAX_WITHHELD and
    NET_PAYABLE appear.

    Design: Difficulty/non_linear_state_machine/statement_branching_draft_finalized_paid_divergent_side_effects
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1,
        agent_commission_pct=0, tax_withholding_pct=0.10,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 1000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)

    before = validate_success(api.list_statement_lines(s1["id"], PUB, params={"line_type": "TAX_WITHHELD"}))
    assert before == [], "no TAX_WITHHELD line before pay"

    fixtures.pay_statement(s1["id"], cid)
    tax_lines = validate_success(api.list_statement_lines(s1["id"], PUB, params={"line_type": "TAX_WITHHELD"}))
    net_lines = validate_success(api.list_statement_lines(s1["id"], PUB, params={"line_type": "NET_PAYABLE"}))
    assert any(ln["amount_cents"] == -30000 for ln in tax_lines), "TAX_WITHHELD deduction emitted at pay"
    assert net_lines, "NET_PAYABLE line emitted at pay"


def test_voided_right_keeps_no_statement_id_and_excludes_income(api):
    """PRD §3.4: "A `REGISTERED` right that never closed — a deal that fell
    through — may be voided by the Publisher, moving its `status` to `VOID`. Once a
    right is `VOID`, its `author_income_cents` is excluded from every future
    statement, so the would-be credit simply never posts."

    The voided right never gets a statement_id stamp; only the kept right does.

    Design: Difficulty/non_linear_state_machine/subsidiary_right_branching_statemented_or_void
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    r_void = get_success_data(
        api.create_subsidiary_right(cid, {"right_type": "FOREIGN", "proceeds_cents": 1000000, "author_share_pct": 0.50}, PUB)
    )
    r_keep = get_success_data(
        api.create_subsidiary_right(cid, {"right_type": "AUDIO", "proceeds_cents": 800000, "author_share_pct": 0.50}, PUB)
    )
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    get_success_data(api.void_subsidiary_right(r_void["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)

    voided = validate_success(api.get_subsidiary_right(r_void["id"], PUB))
    assert voided["status"] == "VOID"
    assert voided["statement_id"] in (None, "")
    assert s1["subsidiary_income_cents"] == 400000  # only the kept right's income


# ==========================================================================
# transitive_cascade
# ==========================================================================
def test_finalize_creates_new_held_reserve_while_liquidating_old(api):
    """PRD §3.6: "It creates a new `ReturnsReserve` in `HELD`, sized at this
    period's withheld `reserve_held_cents`."

    The depth-3 finalize both liquidates R1 (HELD->LIQUIDATED) and creates a fresh
    HELD reserve for period 3's own withholding — the cascade does not consume the
    new reserve.

    Design: Difficulty/transitive_cascade/finalize_cascades_reserve_liquidation_then_author_credit_depth3
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=1000000, reserve_pct=0.25, reserve_hold_periods=2
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 2000, 400)
    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 200)
    s3 = fixtures.finalize_statement(p3["statement"]["id"], cid)

    old_reserve = fixtures.find_reserve_from_statement(p1["statement"]["id"])
    new_reserve = fixtures.find_reserve_from_statement(s3["id"])
    assert old_reserve["status"] == "LIQUIDATED"
    assert new_reserve is not None
    assert new_reserve["status"] == "HELD"


def test_retired_title_is_terminal_and_formats_inactive(api):
    """PRD §3.2: "Retiring a title moves it from `PUBLISHED` to the terminal
    `OUT_OF_PRINT` state ... `OUT_OF_PRINT` is terminal for a title."

    After retire, the title reads OUT_OF_PRINT and its format reads active=false
    on a fresh GET.

    Design: Difficulty/transitive_cascade/title_retire_cascades_format_deactivation_depth2
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    tid = base["title"]["id"]
    fid = base["format"]["id"]

    validate_success(api.retire_title(tid, PUB))

    title = validate_success(api.get_title(tid, PUB))
    assert title["status"] == "OUT_OF_PRINT"
    formats = validate_success(api.list_formats(tid, PUB))
    assert next(f for f in formats if f["id"] == fid)["active"] is False


# ==========================================================================
# priority_pair_validation_conflict
# ==========================================================================
def test_pay_nonexistent_statement_is_not_found(api):
    """PRD §2.10: "Resource existence follows: any unresolved path identifier or
    body foreign key yields `ERR_NOT_FOUND`."

    Paying a non-existent statement id returns ERR_NOT_FOUND, not a state error,
    confirming existence is checked before the FINALIZED-state precondition of pay.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_state_on_finalize
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    resp = api.pay_statement(NON_EXISTENT_UUID, {"expected_contract_version": contract["version"]}, PUB)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_close_out_of_order_leaves_period_open(api):
    """PRD §3.3: "Once a period is `CLOSED`, no further sales records may be posted
    into it."

    PRD §3.3: "closing a period while an earlier-`sequence` sibling has not yet
    been statemented violates the ascending-sequence rule and is rejected with
    `ERR_PERIOD_SEQUENCE_VIOLATION`"

    The rejected period stays OPEN (the close did not partially apply).

    Design: Difficulty/priority_pair_validation_conflict/period_sequence_temporal_before_state_on_close
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    cid = base["contract"]["id"]
    fixtures.open_period(cid, "P1", 1)
    p2 = fixtures.open_period(cid, "P2", 2)

    resp = api.close_sales_period(p2["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_PERIOD_SEQUENCE_VIOLATION.value)

    reread = validate_success(api.get_sales_period(p2["id"], PUB))
    assert reread["status"] == "OPEN"


# ==========================================================================
# boundary_precision_check
# ==========================================================================
def test_exactly_5000_units_stay_in_tier_one(api):
    """PRD §3.7: "the `upper_unit` is the inclusive index at which it ends"

    Net 5000 from baseline 0 stays entirely in tier-1: 5000*0.10*3000 = 1500000;
    the inclusive upper bound 5000 is the last tier-1 unit.

    Design: Difficulty/boundary_precision_check/tier_boundary_5000_inclusive_vs_5001_crosses
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 5000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    assert s1["gross_royalty_cents"] == 1500000


def test_zero_net_period_zero_credited_and_net(api):
    """PRD §3.9: "First, `royalty_credited_cents` is `gross_royalty_cents` minus
    the period's `reserve_held_cents`"

    PRD §3.9: "Finally, `net_to_author_cents` is `payable_before_commission_cents`
    minus `agent_commission_cents` minus `tax_withheld_cents`."

    An empty period settles to all-zero monetary fields.

    Design: Difficulty/boundary_precision_check/zero_net_units_empty_period_yields_zero_reserve
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 0, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)
    assert s1["royalty_credited_cents"] == 0
    assert s1["net_to_author_cents"] == 0


# ==========================================================================
# cross_entity_state_dependency
# ==========================================================================
def test_draft_contract_period_close_does_not_advance_contract(api):
    """PRD §3.1: "Activation is the gate that turns a draft into a live accounting
    entity."

    PRD §3.3: "The Publisher closes an `OPEN` period — transitioning its `status`
    from `OPEN` to `CLOSED` — only while the owning contract is `ACTIVE` and only
    when every lower-`sequence` period of the same contract is already
    `STATEMENTED`"

    Because the contract is still DRAFT, the close fails and the contract remains
    DRAFT (no state leaked).

    Design: Difficulty/cross_entity_state_dependency/period_close_requires_contract_active
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    title = fixtures.add_title(contract["id"], name="Draft Period Book")
    fixtures.add_format(title["id"], list_price_cents=3000)
    period = fixtures.open_period(contract["id"], "P1", 1)

    resp = api.close_sales_period(period["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    reread = validate_success(api.get_contract(contract["id"], PUB))
    assert reread["status"] == "DRAFT"


def test_inactive_format_post_creates_no_record(api):
    """PRD §3.3: "only against a format that is still `active`; a record aimed at a
    non-open period, an inactive format, or a non-active contract is rejected with
    `ERR_PERIOD_NOT_OPEN` (HTTP 409)."

    The rejected post leaves the format with no sales records.

    Design: Difficulty/cross_entity_state_dependency/sales_record_requires_active_format
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    tid = base["title"]["id"]
    fid = base["format"]["id"]
    validate_success(api.retire_title(tid, PUB))
    period = fixtures.open_period(cid, "P1", 1)

    resp = api.create_sales_record(period["id"], {"format_id": fid, "units_sold": 5, "units_returned": 0}, PUB)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    records = validate_success(api.list_period_sales_records(period["id"], PUB))
    assert records == []


# ==========================================================================
# resource_temporal_overlap
# ==========================================================================
def test_distinct_sequence_period_succeeds_alongside_duplicate_block(api):
    """PRD §3.3: "periods are processed and statemented in ascending `sequence`.
    A period opens in `OPEN` `status`. The `sequence` must be unique within the
    owning contract"

    A second period at sequence=1 collides, but a period at sequence=2 is accepted
    — the collision is point-specific, not a blanket second-period ban.

    Design: Difficulty/resource_temporal_overlap/period_sequence_point_occupation_collision
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    cid = base["contract"]["id"]
    fixtures.open_period(cid, "P1", 1)

    dup = api.create_sales_period(cid, {"label": "dup", "sequence": 1}, PUB)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_PERIOD_SEQUENCE.value)

    ok = validate_success(api.create_sales_period(cid, {"label": "P2", "sequence": 2}, PUB), 201)
    assert ok["sequence"] == 2


def test_tier_gap_cover_also_rejected_on_activate(api):
    """PRD §3.1: "A tier schedule that is not a gapless, non-overlapping cover from
    1 with exactly one open top tier is rejected with `ERR_TIER_COVERAGE_INVALID`
    (HTTP 422)"

    A schedule with a gap ([1..5000] then [5002..] leaving 5001 uncovered) is
    rejected for the same coverage rule that catches overlap.

    Design: Difficulty/resource_temporal_overlap/royalty_tier_range_overlap_collision_on_activate
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(
        contract["id"],
        [{"lower_unit": 1, "upper_unit": 5000, "rate": 0.10}, {"lower_unit": 5002, "rate": 0.125}],
    )
    title = fixtures.add_title(contract["id"], name="Gap Book")
    fixtures.add_format(title["id"], list_price_cents=3000)

    resp = api.activate_contract(contract["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_TIER_COVERAGE_INVALID.value)


# ==========================================================================
# compensating_invariant
# ==========================================================================
def test_reserve_release_equals_statement_credit(api):
    """PRD §3.8: "The released portion flows up as a credit into the finalizing
    statement's `reserve_released_cents`."

    The reserve's released_cents (281250) equals the credit the finalizing
    statement reports as reserve_released_cents — the conserved dollars move
    intact from reserve to statement.

    Design: Difficulty/compensating_invariant/reserve_conservation_held_equals_released_plus_consumed
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=2
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 2000, 400)
    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 200)
    s3 = fixtures.finalize_statement(p3["statement"]["id"], cid)

    reserve = fixtures.find_reserve_from_statement(p1["statement"]["id"])
    assert reserve["released_cents"] == s3["reserve_released_cents"] == 281250


def test_void_excludes_income_from_period_earnings(api):
    """PRD §3.9: "`subsidiary_income_cents` is the sum of `author_income_cents`
    over the subsidiary rights credited on this statement ... voided rights
    contribute nothing. Fourth, the period's earnings, `period_earnings_cents`, is
    the sum of `royalty_credited_cents`, `reserve_released_cents`, and
    `subsidiary_income_cents`."

    With the only right voided, period_earnings reflects royalty alone (30000),
    with subsidiary_income contributing 0.

    Design: Difficulty/compensating_invariant/subsidiary_void_conserves_author_income_baseline
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    right = get_success_data(
        api.create_subsidiary_right(cid, {"right_type": "FOREIGN", "proceeds_cents": 1000000, "author_share_pct": 0.50}, PUB)
    )
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    get_success_data(api.void_subsidiary_right(right["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)

    assert s1["subsidiary_income_cents"] == 0
    assert s1["period_earnings_cents"] == s1["royalty_credited_cents"] == 30000
