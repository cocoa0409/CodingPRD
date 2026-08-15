"""Settlement waterfall, royalty, dispute cycle, segregation of duties (PRD §2.8, §2.11, §3.7)."""
from test_helpers import (
    ApiErrorId,
    S1_FIGURES,
    S1_ROYALTY,
    add_passing_check,
    add_stop,
    advance_stop,
    approve_settlement,
    cancel_performance,
    certify_stop,
    contract_stop,
    create_tour,
    create_venue,
    dispute_settlement,
    get_stop_settlement,
    get_tour,
    make_producer_headers,
    make_treasurer_headers,
    pay_settlement,
    play_performance,
    schedule_performance,
    set_settlement_figures,
    setup_closed_stop_with_settlement,
    setup_ready_stop,
    setup_submitted_settlement,
    submit_settlement,
    validate_error,
    validate_success,
    wrap_stop,
)

# Guarantee 0, split 70, audited 1,000,000 / taxes 0 / levies 0 ->
# venue payment 700,000, producer share 300,000 (entirely below the 1,000,000
# bracket boundary).
SMALL_FIGURES = {"audited_gross_cents": 1_000_000, "taxes_cents": 0, "levies_cents": 0}


def _s1_stop_overrides():
    return {"guarantee_cents": 4_000_000, "split_pct": 70, "advance_sales_cents": 6_500_000}


def test_provisional_estimate_frozen_at_certify(api):
    """PRD §3.3: "at the moment of certification the server sets `estimated_venue_payment_cents` to the larger of the stop’s `guarantee_cents` and `split_pct` percent of `advance_sales_cents` rounded half-up to whole cents."
    PRD §3.3: "This provisional estimate deliberately treats advance sales as the
    adjusted-gross proxy — no taxes or levies are deducted — and it is frozen at
    certification; the final settlement in §3.7 will recompute the same terms
    against audited actuals."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_payment
    """
    ctx = setup_closed_stop_with_settlement(stop_overrides=_s1_stop_overrides())
    stop = ctx["stop"]

    # max(4,000,000, round_half_up(0.70 x 6,500,000)) = 4,550,000
    assert stop["estimated_venue_payment_cents"] == 4_550_000, (
        "Provisional estimate must be frozen at certification from advance sales"
    )


def test_final_waterfall_differs_from_provisional(api):
    """PRD §3.7: "First, `adjusted_gross_cents` is the audited gross minus taxes
    minus levies — taxes deducted first, levies second, always in that order."
    PRD §3.7: "Second, `venue_payment_cents` is the larger of the stop’s `guarantee_cents` and `split_pct` percent of the adjusted gross rounded half-up to whole cents — the guarantee-versus-split election resolved in the venue’s favor, and the only step of the waterfall that rounds."
    PRD §3.7: "Third, `producer_share_cents` is the adjusted gross minus the
    venue payment — a figure that may legitimately go negative when the
    guarantee exceeds the adjusted gross, the producer covering the shortfall."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_payment
    """
    ctx = setup_closed_stop_with_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    set_settlement_figures(s["id"], S1_FIGURES["audited_gross_cents"],
                           S1_FIGURES["taxes_cents"], S1_FIGURES["levies_cents"])
    submitted = submit_settlement(s["id"], "trs-1")

    assert submitted["adjusted_gross_cents"] == 5_500_000
    # max(4,000,000, round_half_up(0.70 x 5,500,000) = 3,850,000) = 4,000,000
    assert submitted["venue_payment_cents"] == 4_000_000
    assert submitted["producer_share_cents"] == 1_500_000

    stop = ctx["stop"]
    assert stop["estimated_venue_payment_cents"] == 4_550_000
    assert submitted["venue_payment_cents"] != stop["estimated_venue_payment_cents"], (
        "Identical terms, two variants: provisional (no deductions) vs final waterfall"
    )


def test_royalty_marginal_not_flat(api):
    """PRD §3.7: "Before recoupment, the portion of the share up to the
    threshold is charged at 6 percent and any portion above the threshold at 9
    percent; after recoupment, the portions are charged at 8 percent and 11
    percent respectively."
    PRD §3.7: "The reading is strictly marginal — only the share above the
    threshold pays the higher rate; a flat reading that charged the higher rate
    on the entire share would overstate the royalty whenever the share exceeds
    the threshold and is not how this system computes it."

    Design: Difficulty/dual_variant_calc/royalty_marginal_vs_flat_pinned
    """
    ctx = setup_closed_stop_with_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    set_settlement_figures(s["id"], S1_FIGURES["audited_gross_cents"],
                           S1_FIGURES["taxes_cents"], S1_FIGURES["levies_cents"])
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")

    # Marginal: 6% x 1,000,000 + 9% x 500,000 = 60,000 + 45,000 = 105,000.
    # A flat reading (9% x 1,500,000 = 135,000) is rejected.
    assert approved["producer_share_cents"] == 1_500_000
    assert approved["royalty_cents"] == S1_ROYALTY
    assert approved["royalty_cents"] != 135_000


def test_royalty_marginal_post_recoup_rates(api):
    """PRD §3.7: "Before recoupment, the portion of the share up to the
    threshold is charged at 6 percent and any portion above the threshold at 9
    percent; after recoupment, the portions are charged at 8 percent and 11
    percent respectively."
    PRD §3.7: "Approving — by a `Producer` or `Treasurer` other than the recorded `submitted_by`, per the segregation rule of §2.11 — records the caller as `approved_by` and computes `royalty_cents` as a marginal two-bracket royalty over `producer_share_cents`, using the tour’s `royalty_tier_threshold_cents` as the bracket boundary and the tour’s `recouped` flag at the instant of approval as the rate selector."

    Design: Difficulty/dual_variant_calc/royalty_marginal_vs_flat_pinned
    """
    # Tour that recoups on its first wrapped stop (capitalization 100,000).
    tour_over = {"capitalization_cents": 100_000}
    stop0_over = {"guarantee_cents": 0, "split_pct": 70}
    ctx0 = setup_closed_stop_with_settlement(tour_overrides=tour_over,
                                             stop_overrides=stop0_over)
    s0 = ctx0["settlement"]
    set_settlement_figures(s0["id"], 500_000, 0, 0)   # share 150,000
    submit_settlement(s0["id"], "trs-1")
    approve_settlement(s0["id"], "prod-1")            # royalty 9,000 (pre-recoup)
    pay_settlement(s0["id"], "trs-1")
    wrap_stop(ctx0["stop"]["id"])                     # net 141,000 >= 100,000
    assert get_tour(ctx0["tour"]["id"])["recouped"] is True

    # Second stop, identical margin shape but a 2,000,000 share, approved AFTER
    # the recoupment flip -> 8%/11% marginal brackets.
    stop1 = add_stop(ctx0["tour"]["id"], ctx0["venue"]["id"],
                     play_week_start="2026-09-15", play_week_end="2026-09-20",
                     load_in_date="2026-09-14", travel_in_days=1,
                     guarantee_cents=0, split_pct=50)
    contract_stop(stop1["id"])
    advance_stop(stop1["id"])
    add_passing_check(stop1["id"])
    certify_stop(stop1["id"])
    perf = schedule_performance(stop1["id"], perf_date="2026-09-16")
    play_performance(perf["id"], 1_000_000)
    s1 = get_stop_settlement(stop1["id"])
    set_settlement_figures(s1["id"], 4_000_000, 0, 0)  # vp 2,000,000, share 2,000,000
    submit_settlement(s1["id"], "trs-1")
    approved = approve_settlement(s1["id"], "prod-1")

    # Marginal post-recoup: 8% x 1,000,000 + 11% x 1,000,000 = 190,000.
    # A flat reading (11% x 2,000,000 = 220,000) is rejected.
    assert approved["producer_share_cents"] == 2_000_000
    assert approved["royalty_cents"] == 190_000
    assert approved["royalty_cents"] != 220_000


def test_royalty_min_max_branch_share(api):
    """PRD §3.7: "Before recoupment, the portion of the share up to the
    threshold is charged at 6 percent and any portion above the threshold at 9
    percent; after recoupment, the portions are charged at 8 percent and 11
    percent respectively."
    PRD §3.7: "Each bracket’s amount is rounded half-up to whole cents individually, and the royalty is the sum of the two rounded brackets."

    Design: Difficulty/combinatorial_formula/royalty_tiered_min_max_branch_mode_a
    """
    ctx = setup_closed_stop_with_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    set_settlement_figures(s["id"], S1_FIGURES["audited_gross_cents"],
                           S1_FIGURES["taxes_cents"], S1_FIGURES["levies_cents"])
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")

    # min(share, T) sliced at 6%, max(0, share - T) sliced at 9%:
    # round(0.06 x 1,000,000) + round(0.09 x 500,000) = 60,000 + 45,000.
    assert approved["producer_share_cents"] == 1_500_000
    assert approved["royalty_cents"] == 105_000


def test_royalty_min_max_branch_below_threshold(api):
    """PRD §3.7: "Before recoupment, the portion of the share up to the
    threshold is charged at 6 percent and any portion above the threshold at 9
    percent; after recoupment, the portions are charged at 8 percent and 11
    percent respectively."

    Design: Difficulty/combinatorial_formula/royalty_tiered_min_max_branch_mode_a
    """
    ctx = setup_closed_stop_with_settlement(
        stop_overrides={"guarantee_cents": 0, "split_pct": 70})
    s = ctx["settlement"]
    set_settlement_figures(s["id"], SMALL_FIGURES["audited_gross_cents"],
                           SMALL_FIGURES["taxes_cents"], SMALL_FIGURES["levies_cents"])
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")

    # Share 300,000 lies entirely below T=1,000,000: the upper bracket is empty.
    assert approved["producer_share_cents"] == 300_000
    assert approved["royalty_cents"] == 18_000  # 6% x 300,000


def test_royalty_tier_threshold_exact_boundary(api):
    """PRD §3.7: "The reading is strictly marginal — only the share above the
    threshold pays the higher rate; a flat reading that charged the higher rate
    on the entire share would overstate the royalty whenever the share exceeds
    the threshold and is not how this system computes it."

    Design: Difficulty/boundary_precision_check/royalty_tier_threshold_exact
    """
    ctx = setup_closed_stop_with_settlement(
        stop_overrides={"guarantee_cents": 2_400_000, "split_pct": 70})
    s = ctx["settlement"]
    # adjusted 3,400,000 - venue payment 2,400,000 = share exactly T = 1,000,000.
    set_settlement_figures(s["id"], 3_400_000, 0, 0)
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")

    assert approved["producer_share_cents"] == 1_000_000
    # Exact equality belongs to the lower bracket: the T2 slice is zero cents.
    assert approved["royalty_cents"] == 60_000


def test_royalty_tier_threshold_one_cent_over(api):
    """PRD §3.7: "The reading is strictly marginal — only the share above the
    threshold pays the higher rate; a flat reading that charged the higher rate
    on the entire share would overstate the royalty whenever the share exceeds
    the threshold and is not how this system computes it."
    PRD §3.7: "Each bracket’s amount is rounded half-up to whole cents individually, and the royalty is the sum of the two rounded brackets."

    Design: Difficulty/boundary_precision_check/royalty_tier_threshold_exact
    """
    ctx = setup_closed_stop_with_settlement(
        stop_overrides={"guarantee_cents": 2_400_000, "split_pct": 70})
    s = ctx["settlement"]
    # adjusted 3,400,010 - 2,400,000 = share 1,000,010 == T + 10.
    set_settlement_figures(s["id"], 3_400_010, 0, 0)
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")

    assert approved["producer_share_cents"] == 1_000_010
    # 60,000 + round_half_up(0.09 x 10) = 60,000 + 1.
    assert approved["royalty_cents"] == 60_001


def test_settlement_dispute_cycle_rearms_submitter(api):
    """PRD §2.11: "Resubmission of a disputed settlement records a fresh
    `submitted_by`, re-arming the submit-approve segregation check against the
    new submitter."
    PRD §3.7: "The settlement’s status machine permits the following moves, any other transition drawing `ERR_SETTLEMENT_INVALID_STATE`: from `DRAFT` to `SUBMITTED`; from `SUBMITTED` either to `APPROVED` or — by a `Producer` supplying a `dispute_reason`, whose absence draws `ERR_INVALID_REQUEST` — to `DISPUTED`; from `DISPUTED` back to `SUBMITTED` (the `Treasurer` may re-set figures in the same submission, the waterfall recomputes from the current figures, and the new caller is recorded as `submitted_by`, re-arming the segregation check); from `DISPUTED` to `VOID` by a `Producer`; and from `APPROVED` to `PAID`."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle
    """
    ctx = setup_submitted_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    disputed = dispute_settlement(s["id"], "levies misclassified")
    assert disputed["status"] == "DISPUTED"

    resubmitted = submit_settlement(s["id"], "trs-2")
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submitted_by"] == "trs-2", (
        "Resubmission re-arms the segregation check against the new submitter"
    )


def test_settlement_dispute_cycle_royalty_accrued_once(api):
    """PRD §3.7: "The computed `royalty_cents` is added into the tour’s `royalty_accrued_cents`, which at all times equals the sum of royalties over settlements in `APPROVED` or `PAID`."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle
    """
    ctx = setup_submitted_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    dispute_settlement(s["id"], "levies misclassified")
    submit_settlement(s["id"], "trs-2")
    approved = approve_settlement(s["id"], "prod-1")

    assert approved["royalty_cents"] == S1_ROYALTY
    tour = get_tour(ctx["tour"]["id"])
    assert tour["royalty_accrued_cents"] == S1_ROYALTY, (
        "Royalty accrues exactly once across the dispute cycle"
    )


def test_settlement_void_is_terminal(api):
    """PRD §3.7: "`PAID` and `VOID` are terminal."
    PRD §3.7: "The settlement’s status machine permits the following moves, any other transition drawing `ERR_SETTLEMENT_INVALID_STATE`"

    Design: Corner/state_machines/settlement_void_is_terminal
    """
    ctx = setup_submitted_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    dispute_settlement(s["id"], "audit query")
    resp_void = api.put_settlement(s["id"], {"status": "VOID"},
                                   make_producer_headers("prod-1"))
    assert validate_success(resp_void)["status"] == "VOID"

    resp = api.put_settlement(s["id"], {"status": "SUBMITTED"},
                              make_treasurer_headers("trs-1"))
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE)


def test_settlement_submit_incomplete_returns_error(api):
    """PRD §3.7: "Submission by the `Treasurer` requires all three audited
    figures to be present; submitting without any of them is rejected with
    `ERR_SETTLEMENT_INCOMPLETE`."
    PRD §3.7: "which may be written while the settlement is `DRAFT` or
    `DISPUTED`; writing figures alone preserves the status and changes nothing
    else."

    Design: Corner/validations/settlement_submit_incomplete_returns_error
    """
    ctx = setup_closed_stop_with_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]

    figures_only = validate_success(api.put_settlement(
        s["id"], {"audited_gross_cents": 6_000_000}, make_treasurer_headers("trs-1")))
    assert figures_only["status"] == "DRAFT", "Recording figures alone preserves DRAFT"

    resp = api.put_settlement(s["id"], {"status": "SUBMITTED"},
                              make_treasurer_headers("trs-1"))
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INCOMPLETE)


def test_settlement_zero_gross_zero_royalty(api):
    """PRD §3.4: "A dark week — every performance cancelled, with at least one
    existing — closes directly from `READY` and produces its `DRAFT` settlement
    with `system_gross_cents` of 0."
    PRD §3.7: "Third, `producer_share_cents` is the adjusted gross minus the
    venue payment — a figure that may legitimately go negative when the
    guarantee exceeds the adjusted gross, the producer covering the shortfall."
    PRD §3.7: "When the producer share is zero or negative, the royalty is zero."

    Design: Corner/calculations/settlement_zero_gross_zero_royalty
    """
    ctx = setup_ready_stop(stop_overrides=_s1_stop_overrides())
    stop_id = ctx["stop"]["id"]
    perf = schedule_performance(stop_id, perf_date="2026-09-08")
    cancel_performance(perf["id"])

    s = get_stop_settlement(stop_id)
    assert s is not None and s["status"] == "DRAFT"
    assert s["system_gross_cents"] == 0

    set_settlement_figures(s["id"], 0, 0, 0)
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")

    # The guarantee floor: the venue still takes 4,000,000 at zero gross.
    assert approved["venue_payment_cents"] == 4_000_000
    assert approved["producer_share_cents"] == -4_000_000
    assert approved["royalty_cents"] == 0


def test_sod_beats_state_submitter_approve(api):
    """PRD §2.11: "The user who submits a settlement is recorded as
    `submitted_by`; approval of that settlement by the same `X-User-ID` is
    rejected with `ERR_SOD_SUBMIT_APPROVE` (HTTP 403)."
    PRD §2.8: "on settlement approval and payment the segregation-of-duties
    checks (`ERR_SOD_SUBMIT_APPROVE`, `ERR_SOD_APPROVE_PAY`), which are
    authorization-class rejections evaluated before any existence or state
    question."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_state_on_approve
    """
    ctx = setup_submitted_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    dispute_settlement(s["id"], "levies misclassified")  # submitted_by stays trs-1

    # The DISPUTED settlement fails BOTH checks for the submitter: SoD (auth)
    # fires before the state guard.
    resp = api.put_settlement(s["id"], {"status": "APPROVED"},
                              make_treasurer_headers("trs-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_SUBMIT_APPROVE)


def test_sod_beats_state_non_submitter_sees_state_error(api):
    """PRD §2.11: "The user who submits a settlement is recorded as
    `submitted_by`; approval of that settlement by the same `X-User-ID` is
    rejected with `ERR_SOD_SUBMIT_APPROVE` (HTTP 403)."
    PRD §3.7: "The settlement’s status machine permits the following moves, any other transition drawing `ERR_SETTLEMENT_INVALID_STATE`"

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_state_on_approve
    """
    ctx = setup_submitted_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    dispute_settlement(s["id"], "levies misclassified")

    # A non-submitter passes SoD, so the state guard surfaces (approve is not
    # legal from DISPUTED).
    resp = api.put_settlement(s["id"], {"status": "APPROVED"},
                              make_treasurer_headers("trs-2"))
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE)


def test_sod_pay_same_user_rejected(api):
    """PRD §2.11: "The user who approves is recorded as `approved_by`; payment by
    the same `X-User-ID` is rejected with `ERR_SOD_APPROVE_PAY` (HTTP 403)."
    PRD §2.11: "Approval and payment may be performed by either a `Producer` or
    a `Treasurer` — the segregation check, not the role, is what separates the
    two steps."

    Design: Corner/rbac/sod_pay_same_user_rejected
    """
    ctx = setup_submitted_settlement(stop_overrides=_s1_stop_overrides())
    s = ctx["settlement"]
    approve_settlement(s["id"], "prod-1")

    resp = api.put_settlement(s["id"], {"status": "PAID"},
                              make_producer_headers("prod-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_APPROVE_PAY)

    paid = validate_success(api.put_settlement(s["id"], {"status": "PAID"},
                                               make_treasurer_headers("trs-1")))
    assert paid["status"] == "PAID"
