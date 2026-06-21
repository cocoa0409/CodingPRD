"""Statement reconciliation waterfall, reserve sizing/liquidation, and the
finalize cascade chain.

Covers depth instances under dual_variant_calc, transitive_cascade, and
compensating_invariant, plus corner calculation/validation instances on
reserves and the advance-recoupment reconciliation.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    fixtures,
    TEST_USERS,
)

PUB = TEST_USERS["publisher_headers"]


# ==========================================================================
# Queue A — dual_variant_calc
# ==========================================================================
def test_royalty_credited_excludes_reserve_then_release_credited_later(api):
    """PRD §3.9: "`royalty_credited_cents` is `gross_royalty_cents` minus the
    period's `reserve_held_cents` — the royalty earned this period less the fresh
    reserve withheld from it."

    PRD §3.8: "The released portion flows up as a credit into the finalizing
    statement's `reserve_released_cents`."

    Period 1 withholds reserve 468750 (royalty_credited 1406250); period 3
    liquidates that cohort, crediting reserve_released_cents 281250 — two
    different committed numbers for the same withheld dollars.

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_after_reserve_liquidation
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS,
        advance_cents=2000000,
        reserve_pct=0.25,
        reserve_hold_periods=2,
        agent_commission_pct=0.15,
        with_agent=True,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    s1 = p1["statement"]
    assert s1["royalty_credited_cents"] == 1406250
    assert s1["reserve_held_cents"] == 468750

    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 5000, 400)

    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 200)
    s3 = fixtures.finalize_statement(p3["statement"]["id"], cid)

    assert s3["reserve_released_cents"] == 281250, (
        f"expected 281250, got {s3['reserve_released_cents']}"
    )

    reserve = fixtures.find_reserve_from_statement(s1["id"])
    assert reserve is not None
    assert reserve["status"] == "LIQUIDATED"
    assert reserve["consumed_cents"] == 187500
    assert reserve["released_cents"] == 281250


def test_agent_commission_base_is_post_recoupment_payable(api):
    """PRD §3.9: "The second bucket takes the agent's commission:
    `agent_commission_cents` is `payable_before_commission_cents` multiplied by
    the contract's `agent_commission_pct`, rounded half up to whole cents."

    PRD §3.9: "The commission base is deliberately the post-recoupment
    `payable_before_commission_cents`, not the pre-recoupment
    `period_earnings_cents`"

    period_earnings 4406250, advance fully recoups 2000000, payable 2406250;
    commission = round_half_up(2406250*0.15) = 360938, NOT 660938 (gross base).

    Design: Difficulty/dual_variant_calc/agent_commission_base_net_payable_vs_gross_earnings
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS,
        advance_cents=2000000,
        reserve_pct=0.25,
        reserve_hold_periods=2,
        agent_commission_pct=0.15,
        with_agent=True,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    right = get_success_data(
        api.create_subsidiary_right(
            cid, {"right_type": "FOREIGN", "proceeds_cents": 4000000, "author_share_pct": 0.75}, PUB
        )
    )
    assert right["author_income_cents"] == 3000000

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 6000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)

    assert s1["period_earnings_cents"] == 4406250
    assert s1["advance_recouped_cents"] == 2000000
    assert s1["payable_before_commission_cents"] == 2406250
    assert s1["agent_commission_cents"] == 360938
    assert s1["agent_commission_cents"] != 660938


# ==========================================================================
# Queue A — transitive_cascade
# ==========================================================================
def test_finalize_cascades_reserve_liquidation_then_author_credit(api):
    """PRD §3.6: "It liquidates every `HELD` `ReturnsReserve` whose hold has
    matured ... transitioning each from `HELD` to `LIQUIDATED`, setting its
    `released_cents` and `consumed_cents`, and adding the released portion into
    this statement's `reserve_released_cents` (the cascade: statement finalize
    drives reserve liquidation, which credits the author)."

    PRD §3.6: "It debits the contract's `unrecouped_advance_cents` by this
    statement's `advance_recouped_cents`, keeping the recoupment ledger in sync."

    S3 finalize flips reserve R1 (held 468750) to LIQUIDATED with released 281250;
    that release credits S3.reserve_released_cents. Advance 1000000 was already
    fully recouped at S1, so unrecouped stays 0 (release feeds payable, not
    recoupment).

    Design: Difficulty/transitive_cascade/finalize_cascades_reserve_liquidation_then_author_credit_depth3
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS,
        advance_cents=1000000,
        reserve_pct=0.25,
        reserve_hold_periods=2,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    s1 = p1["statement"]
    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 2000, 400)
    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 200)
    s3 = fixtures.finalize_statement(p3["statement"]["id"], cid)

    reserve = fixtures.find_reserve_from_statement(s1["id"])
    assert reserve is not None
    assert reserve["status"] == "LIQUIDATED"
    assert reserve["consumed_cents"] == 187500
    assert reserve["released_cents"] == 281250

    assert s3["reserve_released_cents"] == 281250

    contract = validate_success(api.get_contract(cid, PUB))
    assert contract["unrecouped_advance_cents"] == 0


def test_title_retire_cascades_format_deactivation_then_blocks_sales(api):
    """PRD §3.2: "Retiring a title moves it from `PUBLISHED` to the terminal
    `OUT_OF_PRINT` state ... Retirement cascades downward: every `Format` of the
    retired title has its `active` flag set to false, so no further sales records
    may be posted against those formats."

    PRD §3.3: "a record aimed at a non-open period, an inactive format, or a
    non-active contract is rejected with `ERR_PERIOD_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/transitive_cascade/title_retire_cascades_format_deactivation_depth2
    """
    from test_helpers import validate_error, ApiErrorId

    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    tid = base["title"]["id"]
    fid = base["format"]["id"]

    period = fixtures.open_period(cid, "P1", 1)

    title = validate_success(api.retire_title(tid, PUB))
    assert title["status"] == "OUT_OF_PRINT"

    fmt = validate_success(api.list_formats(tid, PUB))
    target = next(f for f in fmt if f["id"] == fid)
    assert target["active"] is False

    resp = api.create_sales_record(period["id"], {"format_id": fid, "units_sold": 10, "units_returned": 0}, PUB)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)


# ==========================================================================
# Queue A — compensating_invariant
# ==========================================================================
def test_reserve_conservation_held_equals_released_plus_consumed(api):
    """PRD §3.8: "The system charges the smaller of those actual return units and
    the reserve's `reserve_units`, sets `consumed_cents` to that charged count
    multiplied by the reserve's full-precision `reserve_unit_value_cents` rounded
    half up to whole cents, and sets `released_cents` to `reserve_held_cents`
    minus `consumed_cents`. Because released equals held minus consumed exactly,
    the reserve is conserved to the cent."

    Held 468750 with 600 cohort returns liquidates to released 281250 +
    consumed 187500 = 468750 exactly; no cent drifts out.

    Design: Difficulty/compensating_invariant/reserve_conservation_held_equals_released_plus_consumed
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS,
        advance_cents=0,
        reserve_pct=0.25,
        reserve_hold_periods=2,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    s1 = p1["statement"]
    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 2000, 400)
    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 200)
    fixtures.finalize_statement(p3["statement"]["id"], cid)

    reserve = fixtures.find_reserve_from_statement(s1["id"])
    assert reserve is not None
    assert reserve["reserve_held_cents"] == 468750
    assert reserve["released_cents"] == 281250
    assert reserve["consumed_cents"] == 187500
    assert reserve["released_cents"] + reserve["consumed_cents"] == reserve["reserve_held_cents"]


def test_subsidiary_void_conserves_author_income_baseline(api):
    """PRD §3.4: "Once a right is `VOID`, its `author_income_cents` is excluded
    from every future statement, so the would-be credit simply never posts."

    PRD §3.9: "`subsidiary_income_cents` is the sum of `author_income_cents` over
    the subsidiary rights credited on this statement ... voided rights contribute
    nothing."

    A FOREIGN right (income 500000) registered then voided leaves the statement's
    subsidiary_income_cents at the never-registered baseline of 0.

    Design: Difficulty/compensating_invariant/subsidiary_void_conserves_author_income_baseline
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    right = get_success_data(
        api.create_subsidiary_right(
            cid, {"right_type": "FOREIGN", "proceeds_cents": 1000000, "author_share_pct": 0.50}, PUB
        )
    )
    assert right["author_income_cents"] == 500000

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    voided = validate_success(api.void_subsidiary_right(right["id"], PUB))
    assert voided["status"] == "VOID"

    s1 = fixtures.finalize_statement(s1["id"], cid)
    assert s1["subsidiary_income_cents"] == 0


# ==========================================================================
# Queue B — corner calculations / reconciliation
# ==========================================================================
def test_reserve_liquidation_excess_returns_capped(api):
    """PRD §3.8: "The system charges the smaller of those actual return units and
    the reserve's `reserve_units`, sets `consumed_cents` to that charged count
    multiplied by the reserve's full-precision `reserve_unit_value_cents` rounded
    half up to whole cents, and sets `released_cents` to `reserve_held_cents`
    minus `consumed_cents`."

    Cohort returns 1600 exceed reserve_units 1500: charged = min(1600,1500)=1500,
    consumed capped at 468750, released 0.

    Design: Corner/calculations/reserve_liquidation_excess_returns_capped
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS,
        advance_cents=0,
        reserve_pct=0.25,
        reserve_hold_periods=2,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)
    s1 = p1["statement"]
    fixtures.run_period_to_finalize(cid, fid, "P2", 2, 3000, 900)
    p3 = fixtures.run_period_to_draft_statement(cid, fid, "P3", 3, 1000, 700)
    s3 = fixtures.finalize_statement(p3["statement"]["id"], cid)

    reserve = fixtures.find_reserve_from_statement(s1["id"])
    assert reserve is not None
    assert reserve["consumed_cents"] == 468750
    assert reserve["released_cents"] == 0
    assert s3["reserve_released_cents"] == 0


def test_provisional_does_not_debit_committed_does(api):
    """PRD §3.5: "These draft figures are explicitly provisional: nothing is
    committed, no reserve flips, no right is stamped, and the numbers are
    recomputed against live state when the statement is finalized."

    PRD §3.6: "It debits the contract's `unrecouped_advance_cents` by this
    statement's `advance_recouped_cents`, keeping the recoupment ledger in sync."

    Generate leaves unrecouped at 1000000; finalize debits 300000 to 700000.

    Design: Corner/calculations/variant_selection_provisional_then_committed
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=1000000, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 1000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    before = validate_success(api.get_contract(cid, PUB))
    assert before["unrecouped_advance_cents"] == 1000000

    s1 = fixtures.finalize_statement(s1["id"], cid)
    assert s1["advance_recouped_cents"] == 300000

    after = validate_success(api.get_contract(cid, PUB))
    assert after["unrecouped_advance_cents"] == 700000


def test_unrecouped_advance_reconciled_across_two_finalizes(api):
    """PRD §3.9: "The first bucket recoups the advance: `advance_recouped_cents`
    is the smaller of `period_earnings_cents` and the contract's
    `unrecouped_advance_cents` read at finalize time, never negative."

    PRD §3.6: "It debits the contract's `unrecouped_advance_cents` by this
    statement's `advance_recouped_cents`"

    Advance 500000: period1 royalty 300000 recoups 300000 (-> 200000 left);
    period2 royalty 300000 recoups only the remaining 200000 (-> 0), leaving
    payable 100000.

    Design: Corner/cross_cutting_complexity_layers/derived_unrecouped_advance_reconciled_across_two_finalizes
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=500000, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_finalize(cid, fid, "P1", 1, 1000, 0)
    assert p1["statement"]["advance_recouped_cents"] == 300000

    p2 = fixtures.run_period_to_draft_statement(cid, fid, "P2", 2, 1000, 0)
    s2 = fixtures.finalize_statement(p2["statement"]["id"], cid)
    assert s2["advance_recouped_cents"] == 200000
    assert s2["payable_before_commission_cents"] == 100000

    contract = validate_success(api.get_contract(cid, PUB))
    assert contract["unrecouped_advance_cents"] == 0
