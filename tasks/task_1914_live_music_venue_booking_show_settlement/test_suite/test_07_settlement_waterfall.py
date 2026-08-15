"""Settlement waterfall: draft vs submitted freeze, VERSUS branch, recoupment."""
from test_helpers import (
    ACCT,
    PROM,
    VM,
    ApiErrorId,
    approve_expense,
    assert_settlement,
    assert_settlement_invariants,
    create_artist,
    create_draft_settlement,
    create_on_sale_show,
    create_show_night_show,
    create_show_with_deal,
    record_ancillary,
    reject_expense,
    sell_tickets,
    set_clock,
    submit_expense,
    submit_settlement,
    validate_error,
    validate_success,
)


def test_artist_payout_provisional_vs_final_on_show(api):
    """PRD §3.7: "A draft is provisional by construction: it reflects the
    show's current sales, receipts, ancillary rows, and support payouts,
    and mutating any of those inputs and returning the settlement to
    `DRAFT` recomputes every field. Submission freezes it."
    PRD §3.6: "Approving a receipt while a settlement draft exists
    recomputes the draft's `recoupable_expenses_cents` — but only a draft;
    a submitted settlement is frozen, per §3.7."
    PRD §3.7: "From this moment the settlement's computed fields are frozen:
    later expense approvals, refunds, or ancillary postings do not alter a
    `SUBMITTED` settlement — corrections must go through the dispute loop
    instead."

    Design: Difficulty/dual_variant_calc/artist_payout_provisional_vs_final_on_show
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        artist=None, agent=None,
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=20000, support_budget_cents=0,
            bar_split_pct=0.10, merch_split_pct=0.20,
        ),
        show_overrides=dict(show_date="2026-09-15",
                            doors_at_utc="2026-09-15T19:00:00Z",
                            curfew_at_utc="2026-09-15T23:00:00Z"),
        show_night_clock="2026-09-15T20:00:00Z",
    )
    # Sell 50 tickets at 2000 = 100000 gross
    sell_tickets(show["id"], tier["id"], 50)
    # First expense: 5000 APPROVED recoupable, before draft
    r1 = submit_expense(show["id"], amount_cents=5000, category="SOUND",
                        receipt_reference="R1", is_recoupable=True)
    approve_expense(show["id"], r1["id"])
    # Draft the settlement — snapshot recoupable=5000 → net_door=95000
    draft = create_draft_settlement(show["id"])
    assert draft["status"] == "DRAFT"
    assert draft["recoupable_expenses_cents"] == 5000
    assert draft["net_door_cents"] == 95000

    # Approve a SECOND expense while the settlement is still DRAFT: per
    # PRD §3.6 the draft recomputes (5000 + 8000 = 13000, under the 20000
    # cap), so the provisional draft now reflects recoupable=13000 →
    # net_door=87000.
    r2 = submit_expense(show["id"], amount_cents=8000, category="LIGHTS",
                        receipt_reference="R2", is_recoupable=True)
    approve_expense(show["id"], r2["id"])

    redrafted = validate_success(api.get_show_settlement(show["id"], PROM), 200)
    assert redrafted["status"] == "DRAFT"
    assert redrafted["recoupable_expenses_cents"] == 13000
    assert redrafted["net_door_cents"] == 87000

    # Submission freezes the recomputed draft figures.
    submitted = submit_settlement(show["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["recoupable_expenses_cents"] == 13000
    assert submitted["net_door_cents"] == 87000


def test_artist_payout_draft_snapshot_stable_under_late_expense_approval(api):
    """PRD §3.7: "later expense approvals, refunds, or ancillary postings do
    not alter a `SUBMITTED` settlement — corrections must go through the
    dispute loop instead."

    Design: Difficulty/dual_variant_calc/artist_payout_provisional_vs_final_on_show
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=20000, support_budget_cents=0,
            bar_split_pct=0.10, merch_split_pct=0.20,
        ),
        show_overrides=dict(show_date="2026-09-16",
                            doors_at_utc="2026-09-16T19:00:00Z",
                            curfew_at_utc="2026-09-16T23:00:00Z"),
        show_night_clock="2026-09-16T20:00:00Z",
    )
    sell_tickets(show["id"], tier["id"], 50)
    r1 = submit_expense(show["id"], amount_cents=5000)
    approve_expense(show["id"], r1["id"])
    draft = create_draft_settlement(show["id"])
    settlement_id = draft["id"]

    submitted = submit_settlement(show["id"])
    assert submitted["id"] == settlement_id

    # Post-submission mutation must not alter the SUBMITTED snapshot.
    r2 = submit_expense(show["id"], amount_cents=8000)
    # The show is in SHOW_NIGHT, so VM can approve.
    approve_expense(show["id"], r2["id"])

    fetched = validate_success(api.get_show_settlement(show["id"], PROM), 200)
    assert fetched["status"] == "SUBMITTED"
    assert fetched["recoupable_expenses_cents"] == 5000
    assert fetched["net_door_cents"] == 95000


def test_artist_payout_versus_mode_a_multi_input_conditional(api):
    """PRD §3.7: "Under `VERSUS`, the deal pays the guarantee plus a marginal
    split of the net door above the threshold: the door-split component is
    the excess of `net_door_cents` over `versus_threshold_cents` — floored
    at zero — multiplied by `artist_split_pct` and rounded half up. The
    comparator is strictly greater than: when the net door exceeds the
    threshold, `artist_door_share_cents` is the guarantee plus that
    component, `guarantee_paid_cents` is the guarantee, and `bonus_cents` is
    the component; when the net door is equal to or below the threshold,
    there is no bonus at all — `artist_door_share_cents` and
    `guarantee_paid_cents` are both exactly the guarantee, and `bonus_cents`
    is zero."

    Design: Difficulty/combinatorial_formula/artist_payout_versus_mode_a_multi_input_conditional
    """
    set_clock()
    # Use deposit_pct=0.0 so deposit_credit_cents == 0 and artist_total_due
    # reduces to artist_door_share + bar_artist_share.
    zero_deposit_artist = create_artist(deposit_pct=0.0)
    artist, agent, show, deal, tier = create_show_night_show(
        artist=zero_deposit_artist,
        offer_overrides=dict(
            deal_kind="VERSUS", guarantee_cents=80000, artist_split_pct=0.60,
            versus_threshold_cents=100000, expense_budget_cents=10000,
            support_budget_cents=0, bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(show_date="2026-09-20",
                            doors_at_utc="2026-09-20T19:00:00Z",
                            curfew_at_utc="2026-09-20T23:00:00Z"),
        show_night_clock="2026-09-20T20:00:00Z",
    )
    # Sell 60 × 2000 = 120000 gross
    sell_tickets(show["id"], tier["id"], 60)
    # Approved recoupable receipt of 15000, but expense_budget caps at 10000.
    r = submit_expense(show["id"], amount_cents=15000, category="SOUND",
                       receipt_reference="E1", is_recoupable=True)
    approve_expense(show["id"], r["id"])

    settlement = create_draft_settlement(show["id"])
    assert_settlement(settlement)
    assert_settlement_invariants(settlement)
    assert settlement["recoupable_expenses_cents"] == 10000
    assert settlement["net_door_cents"] == 110000
    # bonus = round_half_up((110000 - 100000) * 0.60) = 6000
    assert settlement["bonus_cents"] == 6000
    assert settlement["artist_door_share_cents"] == 86000
    assert settlement["deposit_credit_cents"] == 0
    assert settlement["artist_total_due_cents"] == 86000


def test_versus_above_threshold_computes_marginal_bonus(api):
    """PRD §3.7: "The split is a marginal rate on the increment above the
    threshold, never an average rate over the whole net door."

    Design: Difficulty/combinatorial_formula/artist_payout_versus_mode_a_multi_input_conditional
    """
    set_clock()
    # Artist with zero deposit_pct so deposit_credit_cents == 0.
    zero_dep = create_artist(deposit_pct=0.0)
    artist, agent, show, deal, tier = create_show_night_show(
        artist=zero_dep,
        offer_overrides=dict(
            deal_kind="VERSUS", guarantee_cents=50000, artist_split_pct=0.50,
            versus_threshold_cents=60000, expense_budget_cents=0,
            support_budget_cents=0, bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(show_date="2026-09-21",
                            doors_at_utc="2026-09-21T19:00:00Z",
                            curfew_at_utc="2026-09-21T23:00:00Z"),
        show_night_clock="2026-09-21T20:00:00Z",
    )
    # Zero-deposit artist means no deposit paid; sell 50 × 2000 = 100000.
    # net_door=100000; excess = 40000; bonus = 40000 * 0.50 = 20000.
    sell_tickets(show["id"], tier["id"], 50)
    settlement = create_draft_settlement(show["id"])
    assert settlement["net_door_cents"] == 100000
    assert settlement["bonus_cents"] == 20000
    assert settlement["artist_door_share_cents"] == 70000


def test_expense_recoupment_over_cap_truncation_mode_b(api):
    """PRD §3.6: "Receipts fit whole until the cap is reached; the first
    receipt that would push the cumulative total over the cap is truncated
    so its recoupable portion lands exactly on the cap, and every later
    receipt recoups at zero. The settlement's `recoupable_expenses_cents` is
    that cumulative total — the full sum when under the cap, exactly the
    cap when over — and the per-receipt ordering matters whenever a
    per-receipt recoupment breakdown is reported."

    Design: Difficulty/combinatorial_formula/expense_recoupment_over_cap_truncation_mode_b
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=20000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=10000, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(room="LOUNGE", show_date="2026-09-25",
                            doors_at_utc="2026-09-25T19:00:00Z",
                            curfew_at_utc="2026-09-25T23:00:00Z",
                            total_capacity=200),
        tier_overrides=dict(face_price_cents=1000, capacity=200, tier_order=1),
        show_night_clock="2026-09-25T20:00:00Z",
    )
    # 10 × 1000 = 10000 gross
    sell_tickets(show["id"], tier["id"], 10)
    # Three receipts in created_at order: 6000, 5000, 4000 — sum 15000 > cap 10000
    r1 = submit_expense(show["id"], amount_cents=6000, category="SOUND",
                        receipt_reference="R1", is_recoupable=True)
    r2 = submit_expense(show["id"], amount_cents=5000, category="LIGHTS",
                        receipt_reference="R2", is_recoupable=True)
    r3 = submit_expense(show["id"], amount_cents=4000, category="BACKLINE",
                        receipt_reference="R3", is_recoupable=True)
    for r in (r1, r2, r3):
        approve_expense(show["id"], r["id"])

    settlement = create_draft_settlement(show["id"])
    # cumulative: 6000 → 6000+5000 would breach; truncate R2 to 4000 → 10000;
    # R3 recoups 0.
    assert settlement["recoupable_expenses_cents"] == 10000
    assert settlement["net_door_cents"] == 0
    assert settlement["artist_door_share_cents"] == 20000


def test_expense_recoupment_under_cap_recoups_full_sum(api):
    """PRD §3.6: "The settlement's `recoupable_expenses_cents` is that
    cumulative total — the full sum when under the cap, exactly the cap
    when over — and the per-receipt ordering matters whenever a per-receipt
    recoupment breakdown is reported."

    Design: Difficulty/combinatorial_formula/expense_recoupment_over_cap_truncation_mode_b
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=20000, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(show_date="2026-09-26",
                            doors_at_utc="2026-09-26T19:00:00Z",
                            curfew_at_utc="2026-09-26T23:00:00Z"),
        show_night_clock="2026-09-26T20:00:00Z",
    )
    sell_tickets(show["id"], tier["id"], 20)  # 20 × 2000 = 40000
    r1 = submit_expense(show["id"], amount_cents=5000)
    r2 = submit_expense(show["id"], amount_cents=6000)
    approve_expense(show["id"], r1["id"])
    approve_expense(show["id"], r2["id"])

    settlement = create_draft_settlement(show["id"])
    assert settlement["recoupable_expenses_cents"] == 11000
    assert settlement["net_door_cents"] == 29000


def test_versus_threshold_exact_boundary_no_bonus(api):
    """PRD §3.7: "The comparator is strictly greater than: when the net door
    exceeds the threshold, `artist_door_share_cents` is the guarantee plus
    that component, `guarantee_paid_cents` is the guarantee, and
    `bonus_cents` is the component; when the net door is equal to or below
    the threshold, there is no bonus at all — `artist_door_share_cents` and
    `guarantee_paid_cents` are both exactly the guarantee, and `bonus_cents`
    is zero."

    Design: Difficulty/boundary_precision_check/versus_threshold_exact_boundary_no_bonus
    """
    set_clock()
    # Deposit_pct 0 so deposit_credit_cents == 0
    zero_dep = create_artist(deposit_pct=0.0)
    artist, agent, show, deal, tier = create_show_night_show(
        artist=zero_dep,
        offer_overrides=dict(
            deal_kind="VERSUS", guarantee_cents=50000, artist_split_pct=0.60,
            versus_threshold_cents=100000, expense_budget_cents=0,
            support_budget_cents=0, bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(room="LOUNGE", show_date="2026-11-05",
                            doors_at_utc="2026-11-05T19:00:00Z",
                            curfew_at_utc="2026-11-05T23:00:00Z",
                            total_capacity=200),
        tier_overrides=dict(face_price_cents=2000, capacity=200, tier_order=1),
        show_night_clock="2026-11-05T20:00:00Z",
    )
    # Exactly 50 × 2000 = 100000 gross == threshold exactly
    sell_tickets(show["id"], tier["id"], 50)
    settlement = create_draft_settlement(show["id"])
    assert settlement["net_door_cents"] == 100000
    assert settlement["bonus_cents"] == 0
    assert settlement["artist_door_share_cents"] == 50000
    assert settlement["guarantee_paid_cents"] == 50000


def test_versus_one_cent_above_threshold_pays_bonus(api):
    """PRD §3.7: "The comparator is strictly greater than: when the net door
    exceeds the threshold, `artist_door_share_cents` is the guarantee plus
    that component, `guarantee_paid_cents` is the guarantee, and
    `bonus_cents` is the component; when the net door is equal to or below
    the threshold, there is no bonus at all — `artist_door_share_cents` and
    `guarantee_paid_cents` are both exactly the guarantee, and `bonus_cents`
    is zero."

    Design: Difficulty/boundary_precision_check/versus_threshold_exact_boundary_no_bonus
    """
    set_clock()
    # Construct net_door = threshold + 1 cent. Use face_price 2001 and 50 tickets:
    # 50 × 2001 = 100050 → 50 cents over. To get exactly 1 cent over, use
    # face 2000 for 50 tickets plus a single ticket at face 2001 — but tiers
    # are priced per-row; simpler: 100001 gross via face=100001 × 1 ticket.
    zero_dep = create_artist(deposit_pct=0.0)
    artist, agent, show, deal, tier = create_show_night_show(
        artist=zero_dep,
        offer_overrides=dict(
            deal_kind="VERSUS", guarantee_cents=50000, artist_split_pct=0.60,
            versus_threshold_cents=100000, expense_budget_cents=0,
            support_budget_cents=0, bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(room="LOUNGE", show_date="2026-11-06",
                            doors_at_utc="2026-11-06T19:00:00Z",
                            curfew_at_utc="2026-11-06T23:00:00Z",
                            total_capacity=200),
        tier_overrides=dict(face_price_cents=100001, capacity=10, tier_order=1),
        show_night_clock="2026-11-06T20:00:00Z",
    )
    sell_tickets(show["id"], tier["id"], 1)  # gross = 100001
    settlement = create_draft_settlement(show["id"])
    assert settlement["net_door_cents"] == 100001
    # bonus = round_half_up((100001 - 100000) * 0.60) = round_half_up(0.6) = 1
    assert settlement["bonus_cents"] == 1
    assert settlement["artist_door_share_cents"] == 50001


def test_bar_split_rounding_half_up(api):
    """PRD §3.7: "The bar share `bar_artist_share_cents` is the night's total
    bar gross minus total bar cost — floored at zero — multiplied by the
    deal's `bar_split_pct`, rounded half up."
    PRD §2.5: "Wherever a calculation prescribes a rounding step, that step
    rounds half up to the nearest whole cent; products and sums that are not
    explicit rounding steps are never rounded, so intermediate values flow
    through the waterfall at full precision."

    Design: Corner/calculations/bar_split_rounding_half_up
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0.15, merch_split_pct=0,
        ),
        show_overrides=dict(show_date="2027-01-20",
                            doors_at_utc="2027-01-20T19:00:00Z",
                            curfew_at_utc="2027-01-20T23:00:00Z"),
        show_night_clock="2027-01-20T20:00:00Z",
    )
    # bar_gross=10001, bar_cost=0, split=0.15 → 1500.15 → half-up → 1500
    record_ancillary(show["id"], kind="BAR", gross_cents=10001, cost_cents=0)
    settlement = create_draft_settlement(show["id"])
    assert settlement["bar_artist_share_cents"] == 1500


def test_merch_split_does_not_deduct_cost(api):
    """PRD §3.7: "The merch share `merch_venue_share_cents` is the total
    merch gross multiplied by `merch_split_pct`, rounded half up, with the
    merch cost deliberately not deducted."
    PRD §3.6: "For merch, the cost is the artist's own cost of goods and is
    deliberately not deducted when the venue's merch split is computed
    (§3.7)."

    Design: Corner/calculations/merch_split_does_not_deduct_cost
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0.20,
        ),
        show_overrides=dict(show_date="2027-01-22",
                            doors_at_utc="2027-01-22T19:00:00Z",
                            curfew_at_utc="2027-01-22T23:00:00Z"),
        show_night_clock="2027-01-22T20:00:00Z",
    )
    # merch_gross=10000, merch_cost=3000, split=0.20 → venue share = 2000
    # (NOT (10000-3000)*0.20 = 1400)
    record_ancillary(show["id"], kind="MERCH", gross_cents=10000, cost_cents=3000)
    settlement = create_draft_settlement(show["id"])
    assert settlement["merch_venue_share_cents"] == 2000


def test_expense_filter_excludes_rejected(api):
    """PRD §3.6: "Only `APPROVED` receipts flagged recoupable participate,
    and they are applied oldest-first by `created_at` against the deal
    snapshot's `expense_budget_cents` — never the current offer's terms."
    PRD §3.6: "a receipt marked not recoupable is house-only and is never
    deducted from the door."

    Design: Corner/calculations/expense_filter_excludes_rejected
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=20000, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(show_date="2027-01-25",
                            doors_at_utc="2027-01-25T19:00:00Z",
                            curfew_at_utc="2027-01-25T23:00:00Z"),
        show_night_clock="2027-01-25T20:00:00Z",
    )
    r1 = submit_expense(show["id"], amount_cents=5000, category="SOUND",
                        receipt_reference="E1", is_recoupable=True)
    r2 = submit_expense(show["id"], amount_cents=8000, category="LIGHTS",
                        receipt_reference="E2", is_recoupable=True)
    r3 = submit_expense(show["id"], amount_cents=3000, category="HOSPITALITY",
                        receipt_reference="E3", is_recoupable=False)
    approve_expense(show["id"], r1["id"])
    reject_expense(show["id"], r2["id"], reason="No invoice")
    approve_expense(show["id"], r3["id"])

    settlement = create_draft_settlement(show["id"])
    # Only APPROVED + recoupable counts → 5000 (R2 rejected, R3 house-only).
    assert settlement["recoupable_expenses_cents"] == 5000


def test_settlement_approve_segregation_of_duties(api):
    """PRD §3.7: "Approval belongs to the `Accountant`, and segregation of
    duties is enforced by identity: the approver's `X-User-ID` must differ
    from the settlement's `submitted_by_user_id`, and a match is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/state_machines/settlement_approve_segregation_of_duties
    """
    set_clock()
    artist, agent, show, deal, tier = create_show_night_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=5000, support_budget_cents=0,
            bar_split_pct=0.10, merch_split_pct=0.20,
        ),
        show_overrides=dict(show_date="2026-12-30",
                            doors_at_utc="2026-12-30T19:00:00Z",
                            curfew_at_utc="2026-12-30T23:00:00Z"),
        show_night_clock="2026-12-30T20:00:00Z",
    )
    create_draft_settlement(show["id"])
    # Submit as opaque Promoter user "prom_1".
    submit_settlement(show["id"], promoter_user_id="prom_1")

    # An Accountant presenting the SAME opaque user id cannot approve.
    resp = api.approve_settlement(
        show["id"],
        {"X-User-ID": "prom_1", "X-User-Role": "Accountant",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

    fetched = validate_success(api.get_show_settlement(show["id"], PROM), 200)
    assert fetched["status"] == "SUBMITTED"
