"""Grower settlement: two-pass rounding variants, the pinned fee/advance
waterfall, dispute cycles, approval gating, and segregation of duties
(PRD §3.8, §3.4, §3.1, §2.1)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_settlement_payload,
    create_open_season,
    close_intake,
    create_grower,
    get_grower,
    create_bin,
    create_spot_lot,
    grade_lot,
    store_lot,
    get_lot,
    get_season,
    get_settlement,
    create_draft_settlement,
    issue_provisional,
    begin_settlement_review,
    approve_settlement,
    pay_settlement,
    dispute_settlement_by_grower,
    revise_settlement,
    setup_binned_contract_lots,
    setup_binned_spot_lots,
    settlement_reaching,
    make_clerk_headers,
    set_clock,
)

ADMIN = TEST_USERS["mill_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]

TWO_LOT_SPECS = [
    {"gross": 22010, "tare": 12000, "date": "2026-08-10"},
    {"gross": 22030, "tare": 12000, "date": "2026-08-11"},
]

THREE_LOT_SPECS = [
    {"gross": 22010, "tare": 12000, "date": "2026-08-10"},
    {"gross": 22030, "tare": 12000, "date": "2026-08-11"},
    {"gross": 22050, "tare": 12000, "date": "2026-08-12"},
]


def _two_lot_scenario():
    """Contract 250.00 base 1000 adj 0; two BINNED lots, dry 100.10 + 100.30."""
    return setup_binned_contract_lots(
        TWO_LOT_SPECS, contracted_cwt=250.00, base_price_cents_per_cwt=1000)


# ---------------------------------------------------------------------------
# Dual variant: per-line (provisional) vs aggregate (final) checkoff rounding
# ---------------------------------------------------------------------------

def test_provisional_statement_rounds_checkoff_per_line(api):
    """PRD §3.8: "In the provisional (per-line rounding) variant,
    `provisional_gross_cents` is the sum of the member lots' individually
    rounded `line_value_cents`; `provisional_drying_cents` is the sum of their
    `drying_charge_cents`; `provisional_checkoff_cents` is the sum, over each
    line, of that line's value multiplied by the half-of-one-percent checkoff
    rate (0.005) and rounded half-up to whole cents per line"

    Design: Difficulty/dual_variant_calc/settlement_checkoff_per_line_vs_aggregate
    """
    scn = _two_lot_scenario()
    close_intake(scn["season"]["id"])
    draft = create_draft_settlement(scn["season"]["id"], scn["grower"]["id"])
    # line values 100100 and 100300; per-line checkoff 501 + 502 = 1003.
    assert draft["provisional_gross_cents"] == 200400
    assert draft["provisional_drying_cents"] == 0
    assert draft["provisional_checkoff_cents"] == 1003
    assert draft["provisional_advance_repay_cents"] == 0
    assert draft["provisional_net_cents"] == 199397  # 200400 - 0 - 1003 - 0


def test_final_statement_rounds_checkoff_once_on_aggregate(api):
    """PRD §3.8: "`final_checkoff_cents` applies the 0.005 rate to the exact
    aggregate gross and rounds half-up a single time"
    PRD §3.8: "Because the provisional variant rounds per line and the final
    variant rounds once on the aggregate, the two statements for the same lots
    can legitimately differ by cents."

    Design: Difficulty/dual_variant_calc/settlement_checkoff_per_line_vs_aggregate
    """
    scn = _two_lot_scenario()
    approved = settlement_reaching(scn, "approved")
    # Aggregate: gross 200400 exact; checkoff round(200400 * 0.005) = 1002.
    assert approved["final_gross_cents"] == 200400
    assert approved["final_drying_cents"] == 0
    assert approved["final_checkoff_cents"] == 1002
    assert approved["final_net_cents"] == 199398
    assert approved["final_net_cents"] - approved["provisional_net_cents"] == 1


# ---------------------------------------------------------------------------
# Combinatorial: nested rounding order over three lines
# ---------------------------------------------------------------------------

def test_three_line_provisional_checkoff_sums_per_line_roundings(api):
    """PRD §3.8: "`provisional_checkoff_cents` is the sum, over each line, of
    that line's value multiplied by the half-of-one-percent checkoff rate
    (0.005) and rounded half-up to whole cents per line"
    PRD §3.8: "and `provisional_net_cents` is gross minus drying, minus
    checkoff, minus advance repayment."

    Design: Difficulty/combinatorial_formula/settlement_three_line_rounding_order
    """
    scn = setup_binned_contract_lots(
        THREE_LOT_SPECS, contracted_cwt=400.00, base_price_cents_per_cwt=1000)
    close_intake(scn["season"]["id"])
    draft = create_draft_settlement(scn["season"]["id"], scn["grower"]["id"])
    # lines 100100 / 100300 / 100500 -> per-line checkoff 501 + 502 + 503.
    assert draft["provisional_checkoff_cents"] == 1506
    assert draft["provisional_net_cents"] == 299394  # 300900 - 1506


def test_three_line_final_checkoff_rounds_aggregate_once(api):
    """PRD §3.8: "`final_gross_cents` is the sum of the member lots' exact line
    values — dry weight times price, unrounded — rounded half-up to whole cents
    exactly once at the end"
    PRD §3.8: "`final_checkoff_cents` applies the 0.005 rate to the exact
    aggregate gross and rounds half-up a single time"

    Design: Difficulty/combinatorial_formula/settlement_three_line_rounding_order
    """
    scn = setup_binned_contract_lots(
        THREE_LOT_SPECS, contracted_cwt=400.00, base_price_cents_per_cwt=1000)
    approved = settlement_reaching(scn, "approved")
    # round_half_up(300900 * 0.005) = round_half_up(1504.5) = 1505.
    assert approved["final_checkoff_cents"] == 1505
    assert approved["final_net_cents"] == 299395  # 300900 - 1505
    assert approved["final_net_cents"] - approved["provisional_net_cents"] == 1


# ---------------------------------------------------------------------------
# Combinatorial: the pinned gross -> drying -> checkoff -> advance -> net order
# ---------------------------------------------------------------------------

def _advance_scenario():
    """Grower with advance 119500; contract 200.00 base 1200; one BINNED lot
    dry 100.00 (line value 120000)."""
    return setup_binned_contract_lots(
        [{"gross": 22000, "tare": 12000}],
        contracted_cwt=200.00, base_price_cents_per_cwt=1200,
        farm_code="FARM-003", legal_name="Prairie Rice Co",
        advance_issued_cents=119500)


def test_advance_repayment_sized_after_checkoff(api):
    """PRD §3.8: "The draft's provisional statement follows a pinned evaluation
    order — gross, then drying, then checkoff, then advance repayment, then net
    — and the order is never rearranged, because the fee and the advance
    repayment would otherwise be circular."
    PRD §3.8: "`final_advance_repay_cents` is the lesser of the outstanding
    advance at approval time and the positive remainder after drying and
    checkoff; and `final_net_cents` — the amount actually paid — is the
    remainder after all three deductions."

    Design: Difficulty/combinatorial_formula/settlement_advance_waterfall_order_pinned
    """
    scn = _advance_scenario()
    approved = settlement_reaching(scn, "approved")
    # checkoff 600; advance min(119500, 120000 - 0 - 600) = 119400; net 0.
    assert approved["final_gross_cents"] == 120000
    assert approved["final_checkoff_cents"] == 600
    assert approved["final_advance_repay_cents"] == 119400
    assert approved["final_net_cents"] == 0


def test_pay_debits_advance_and_credits_grower(api):
    """PRD §3.8: "Paying an `APPROVED` settlement moves it to the terminal
    `PAID` and touches the grower's account in the same breath:
    `advance_outstanding_cents` falls by `final_advance_repay_cents`,
    `cumulative_paid_cents` grows by `final_net_cents`, and the grower's
    `version` increments."

    Design: Difficulty/combinatorial_formula/settlement_advance_waterfall_order_pinned
    """
    scn = _advance_scenario()
    paid = settlement_reaching(scn, "paid")
    assert paid["status"] == "PAID"
    grower = get_grower(scn["grower"]["id"])
    assert grower["advance_outstanding_cents"] == 100  # 119500 - 119400
    assert grower["cumulative_paid_cents"] == 0  # final_net was 0


# ---------------------------------------------------------------------------
# Non-linear machine: the dispute -> revise -> re-issue cycle
# ---------------------------------------------------------------------------

def test_dispute_and_revise_cycle_back_to_draft(api):
    """PRD §3.8: "A settlement in `PROVISIONAL_ISSUED` or `APPROVED` may be
    disputed — by a `SettlementClerk`, by the `GrowerRep` whose grower the
    settlement pays, or automatically by the regrade cascade of §3.4"
    PRD §3.8: "Revision then moves the settlement `DISPUTED` → `DRAFT`,
    recomputing the provisional amounts over the same frozen `lot_ids` with the
    lots' current values"

    Design: Difficulty/non_linear_state_machine/settlement_dispute_revise_cycle
    """
    scn = _two_lot_scenario()
    issued = settlement_reaching(scn, "issued")

    disputed = dispute_settlement_by_grower(issued["id"], scn["grower"]["id"])
    assert disputed["status"] == "DISPUTED"

    revised = revise_settlement(issued["id"])
    assert revised["status"] == "DRAFT"
    assert revised["provisional_net_cents"] == 199397, (
        "recomputed identically over the same frozen lot_ids"
    )


def test_full_dispute_loop_still_converges_to_paid(api):
    """PRD §3.8: "The cycle of issue, approve or dispute, and revise repeats
    until the statement stands `PAID`, and only a season whose settlements are
    all `PAID` may settle for good."
    PRD §3.2: "the latter accumulates the net amounts of the grower's paid
    settlements."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_revise_cycle
    """
    scn = _two_lot_scenario()
    issued = settlement_reaching(scn, "issued")
    dispute_settlement_by_grower(issued["id"], scn["grower"]["id"])
    revise_settlement(issued["id"])
    issue_provisional(issued["id"])
    begin_settlement_review(scn["season"]["id"])
    approve_settlement(issued["id"], "clerk-2")
    paid = pay_settlement(issued["id"], "clerk-1")

    assert paid["status"] == "PAID"
    assert paid["final_net_cents"] == 199398
    grower = get_grower(scn["grower"]["id"])
    assert grower["cumulative_paid_cents"] == 199398, (
        "exactly one payment despite the dispute loop"
    )


# ---------------------------------------------------------------------------
# Cross-entity dependency: approve gated by the season state
# ---------------------------------------------------------------------------

def _issued_settlement_scenario():
    """One BINNED contract lot (dry 100.10); settlement PROVISIONAL_ISSUED while
    the season sits in INTAKE_CLOSED."""
    scn = setup_binned_contract_lots(
        [{"gross": 22010, "tare": 12000}],
        contracted_cwt=250.00, base_price_cents_per_cwt=1000)
    settlement = settlement_reaching(scn, "issued")
    return scn, settlement


def test_approve_rejected_while_season_not_in_review(api):
    """PRD §3.8: "Approving requires the settlement in `PROVISIONAL_ISSUED`, the
    season squarely in `SETTLEMENT_REVIEW` (`ERR_SEASON_NOT_SETTLEMENT_REVIEW`),
    and an approver whose `X-User-ID` differs from `created_by_user_id`
    (`ERR_SOD_APPROVER_IS_CREATOR`)."

    Design: Difficulty/cross_entity_state_dependency/settlement_approve_gated_by_season_review
    """
    scn, settlement = _issued_settlement_scenario()
    resp = api_client.approve_settlement(settlement["id"], make_clerk_headers("clerk-2"))
    validate_error(resp, ApiErrorId.ERR_SEASON_NOT_SETTLEMENT_REVIEW)


def test_approve_succeeds_once_season_enters_review(api):
    """PRD §3.8: "Approving requires the settlement in `PROVISIONAL_ISSUED`, the
    season squarely in `SETTLEMENT_REVIEW` (`ERR_SEASON_NOT_SETTLEMENT_REVIEW`)"
    PRD §3.8: "Approval also moves every member lot `BINNED` → `SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/settlement_approve_gated_by_season_review
    """
    scn, settlement = _issued_settlement_scenario()
    begin_settlement_review(scn["season"]["id"])
    approved = approve_settlement(settlement["id"], "clerk-2")
    assert approved["status"] == "APPROVED"
    assert get_lot(scn["lots"][0]["id"])["status"] == "SETTLED"


# ---------------------------------------------------------------------------
# Compensating invariant: money conserved across a dispute cycle from APPROVED
# ---------------------------------------------------------------------------

def _approved_settlement_scenario():
    scn = _two_lot_scenario()
    settlement = settlement_reaching(scn, "approved")
    return scn, settlement


def test_dispute_from_approved_reverts_lots_and_season(api):
    """PRD §3.8: "Disputing an `APPROVED` settlement returns every member lot
    from `SETTLED` to `BINNED`, unwinding the settlement's hold on the grain,
    and in either case a season standing in `SETTLEMENT_REVIEW` reverts to
    `INTAKE_CLOSED`."

    Design: Difficulty/compensating_invariant/dispute_cycle_preserves_paid_money
    """
    scn, settlement = _approved_settlement_scenario()
    assert settlement["final_net_cents"] == 199398

    disputed = dispute_settlement_by_grower(settlement["id"], scn["grower"]["id"],
                                            dispute_reason="grower contests checkoff")
    assert disputed["status"] == "DISPUTED"
    assert get_season(scn["season"]["id"])["status"] == "INTAKE_CLOSED"
    for lot in scn["lots"]:
        assert get_lot(lot["id"])["status"] == "BINNED"


def test_dispute_cycle_preserves_paid_money_exactly_once(api):
    """PRD §3.8: "Paying an `APPROVED` settlement moves it to the terminal
    `PAID` and touches the grower's account in the same breath:
    `advance_outstanding_cents` falls by `final_advance_repay_cents`,
    `cumulative_paid_cents` grows by `final_net_cents`, and the grower's
    `version` increments."
    PRD §3.2: "the latter accumulates the net amounts of the grower's paid
    settlements."

    Design: Difficulty/compensating_invariant/dispute_cycle_preserves_paid_money
    """
    scn, settlement = _approved_settlement_scenario()
    dispute_settlement_by_grower(settlement["id"], scn["grower"]["id"],
                                 dispute_reason="grower contests checkoff")
    revise_settlement(settlement["id"])
    issue_provisional(settlement["id"])
    begin_settlement_review(scn["season"]["id"])
    approve_settlement(settlement["id"], "clerk-2")
    paid = pay_settlement(settlement["id"], "clerk-1")

    assert paid["status"] == "PAID"
    grower = get_grower(scn["grower"]["id"])
    assert grower["cumulative_paid_cents"] == 199398, (
        "cumulative_paid_cents must equal the single final_net_cents after a "
        "full dispute cycle — never double-paid, never a cent leaked"
    )


# ---------------------------------------------------------------------------
# Transitive cascade: lot regrade -> settlement dispute -> season revert
# ---------------------------------------------------------------------------

REGRADE_ADJUSTMENTS = {"US_NO_1": 0, "US_NO_2": -25, "US_NO_3": -60,
                       "US_NO_4": -110, "US_NO_5": -175, "SAMPLE": -300}


def _review_scenario_with_binned_lot():
    """Contract lot (net 363.00, M 18.5 -> US_NO_2, dry 338.24) BINNED;
    settlement PROVISIONAL_ISSUED; season SETTLEMENT_REVIEW."""
    scn = setup_binned_contract_lots(
        [{"gross": 48300, "tare": 12000, "handheld": 18.0, "official": 18.5,
          "fm": 0.4, "dmg": 0.4, "brk": 2.0}],
        contracted_cwt=400.00, base_price_cents_per_cwt=1500,
        grade_adjustments=dict(REGRADE_ADJUSTMENTS),
        farm_code="FARM-001", legal_name="Delta Farms")
    close_intake(scn["season"]["id"])
    draft = create_draft_settlement(scn["season"]["id"], scn["grower"]["id"])
    # gross 498904 - drying 10709 - checkoff round(498904*0.005)=2495 - 0.
    assert draft["provisional_net_cents"] == 485700
    issue_provisional(draft["id"])
    season = begin_settlement_review(scn["season"]["id"])
    assert season["status"] == "SETTLEMENT_REVIEW"
    return scn, draft


def test_regrade_reprices_lot_and_auto_disputes_settlement(api, quality_lab_tech_headers):
    """PRD §3.4: "if it names one in `PROVISIONAL_ISSUED`, the settlement is
    thrown into `DISPUTED` with `dispute_reason` automatically set to
    `LOT_REGRADED`"
    PRD §3.4: "Regrading is permitted while a lot stands in `GRADED` or
    `BINNED`, takes the same four laboratory inputs, and recomputes every
    grading-derived field"

    Design: Difficulty/transitive_cascade/regrade_disputes_settlement_reverts_season
    """
    scn, settlement = _review_scenario_with_binned_lot()
    regraded = validate_success(
        api.regrade_lot(
            scn["lots"][0]["id"],
            {"moisture_pct_official": 18.5, "foreign_matter_pct": 0.6,
             "damage_pct": 0.6, "broken_pct": 4.0},
            quality_lab_tech_headers,
        )
    )
    # Link 1: lot repriced in place (dry unchanged; score 7.0 -> US_NO_3).
    assert regraded["status"] == "BINNED"
    assert regraded["grade"] == "US_NO_3"
    assert regraded["line_value_cents"] == 487066  # 338.24 * (1500 - 60)

    # Link 2: the containing settlement is auto-disputed by the lot mutation.
    after = get_settlement(settlement["id"])
    assert after["status"] == "DISPUTED"
    assert after["dispute_reason"] == "LOT_REGRADED"


def test_regrade_cascade_reverts_season_to_intake_closed(api, quality_lab_tech_headers):
    """PRD §3.4: "if it names one in `PROVISIONAL_ISSUED`, the settlement is
    thrown into `DISPUTED` with `dispute_reason` automatically set to
    `LOT_REGRADED`, and a season standing in `SETTLEMENT_REVIEW` reverts to
    `INTAKE_CLOSED` as §3.1 describes."
    PRD §3.1: "the moment any settlement in the season enters `DISPUTED` —
    whether by an explicit dispute or by the regrade cascade of §3.4 — the
    season automatically reverts to `INTAKE_CLOSED` so the disputed statement
    can be revised and re-approved."

    Design: Difficulty/transitive_cascade/regrade_disputes_settlement_reverts_season
    """
    scn, settlement = _review_scenario_with_binned_lot()
    validate_success(
        api.regrade_lot(
            scn["lots"][0]["id"],
            {"moisture_pct_official": 18.5, "foreign_matter_pct": 0.6,
             "damage_pct": 0.6, "broken_pct": 4.0},
            quality_lab_tech_headers,
        )
    )
    # Link 3: the season reverted because the settlement entered DISPUTED.
    assert get_season(scn["season"]["id"])["status"] == "INTAKE_CLOSED"


# ---------------------------------------------------------------------------
# Corner: segregation of duties at approval
# ---------------------------------------------------------------------------

def test_sod_approver_must_differ_from_creator(api):
    """PRD §2.1: "the approving operator's `X-User-ID` must differ from the
    settlement's `created_by_user_id`, enforcing segregation of duties; a
    self-approval attempt is rejected with `ERR_SOD_APPROVER_IS_CREATOR`
    (HTTP 403)."
    PRD §3.8: "The draft also records `created_by_user_id` from the acting
    clerk's `X-User-ID`, the seed of the segregation-of-duties check at
    approval."

    Design: Corner/rbac/sod_approver_must_differ_from_creator
    """
    scn = setup_binned_spot_lots([{"gross": 22000, "tare": 12000}])
    close_intake(scn["season"]["id"])
    draft = create_draft_settlement(scn["season"]["id"], scn["grower"]["id"],
                                    clerk_user_id="clerk-1")
    assert draft["created_by_user_id"] == "clerk-1"
    issue_provisional(draft["id"], "clerk-1")
    begin_settlement_review(scn["season"]["id"])

    resp = api_client.approve_settlement(draft["id"], make_clerk_headers("clerk-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_APPROVER_IS_CREATOR)

    approved = approve_settlement(draft["id"], "clerk-2")
    assert approved["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Corner: settlement membership snapshot filters
# ---------------------------------------------------------------------------

def test_settlement_input_set_filters(api):
    """PRD §3.8: "Drafting snapshots the eligible lots: lots standing in
    `BINNED`, belonging to that grower and season, whose `graded_date` falls
    within the period (both ends inclusive), and whose `settlement_id` is still
    null. The snapshot is frozen into the settlement's `lot_ids` — membership
    never changes thereafter — and each member lot's `settlement_id` is stamped,
    removing it from future eligibility."
    PRD §3.4: "Grading stamps the lot's `graded_date` with the calendar date of
    the season's logical clock, and that date becomes the key for
    settlement-period eligibility in §3.8."

    Design: Corner/calculations/settlement_input_set_filters
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"])

    lot_a = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                            tare_weight_lbs=12000, scheduled_date="2026-08-10")
    grade_lot(lot_a["id"])  # clock still 2026-08-01 -> graded_date in period
    store_lot(lot_a["id"], bin_["id"])

    set_clock(season["id"], "2026-09-10T00:00:00Z")
    lot_b = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                            tare_weight_lbs=12000, scheduled_date="2026-09-10")
    grade_lot(lot_b["id"])  # graded_date 2026-09-10 -> outside the period
    store_lot(lot_b["id"], bin_["id"])

    close_intake(season["id"])
    draft = create_draft_settlement(season["id"], grower["id"])
    assert draft["lot_ids"] == [lot_a["id"]], (
        "only the lot graded inside 2026-08-01..2026-08-31 is eligible"
    )
    assert draft["provisional_gross_cents"] == 130000  # 100.00 cwt * 1300
    assert get_lot(lot_b["id"])["settlement_id"] is None, (
        "the out-of-period lot remains eligible for a later period"
    )


def test_settlement_empty_period_rejected(api):
    """PRD §3.8: "A period with no eligible lots is refused with
    `ERR_SETTLEMENT_PERIOD_EMPTY` (HTTP 422)."

    Design: Corner/validations/settlement_empty_period_rejected
    """
    season = create_open_season()
    grower = create_grower(season["id"], farm_code="FARM-009",
                           legal_name="Empty Acres")
    close_intake(season["id"])
    resp = api_client.create_settlement(
        create_settlement_payload(season["id"], grower["id"]),
        make_clerk_headers("clerk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_EMPTY)


def test_settlement_pay_from_draft_rejected(api):
    """PRD §3.8: "Paying an `APPROVED` settlement moves it to the terminal
    `PAID`"
    PRD §2.7: "State-machine legality. The target resource's current state
    permits the requested transition; the error id varies by entity
    (`ERR_INVALID_SEASON_STATE`, `ERR_INVALID_LOT_STATE`, ... and their kin,
    409)."

    Design: Corner/validations/settlement_pay_from_draft_rejected
    """
    scn = setup_binned_spot_lots([{"gross": 22000, "tare": 12000}])
    close_intake(scn["season"]["id"])
    draft = create_draft_settlement(scn["season"]["id"], scn["grower"]["id"])
    resp = api_client.pay_settlement(draft["id"], make_clerk_headers("clerk-1"))
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE)
