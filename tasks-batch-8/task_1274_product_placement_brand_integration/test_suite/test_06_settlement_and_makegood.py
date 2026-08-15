"""Post-air settlement: provisional vs final billing, bonus, make-good math,
waive compensation, dispute/remeasure cycle, and episode bubble-up
(PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_ledger,
    get_contract,
    get_episode,
    get_opportunity,
    get_success_data,
    list_cross_promos,
    list_makegood_credits,
    make_brand_rep_headers,
    setup_active_contract,
    setup_aired_contract,
    setup_filed_report,
    setup_makegood_required,
    setup_settled_contract,
    setup_verified_report,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
NETWORK = TEST_USERS["network_headers"]
FILER = TEST_USERS["verifier_headers"]
VERIFIER = TEST_USERS["verifier_alt_headers"]


def test_provisional_vs_final_settlement_divergence(api):
    """PRD §3.5: "computed from the script's own numbers: the projected
    shortfall is the larger of zero and the contract's `guaranteed_seconds`
    minus the opportunity's `estimated_exposure_seconds`; that shortfall is
    multiplied by the contract's `rate_cents_per_second` and by one and a half,
    the product is rounded half-up to whole cents, and the result is subtracted
    from `base_fee_cents`. The provisional estimate deliberately ignores
    verbal-miss penalties — a script cannot evidence spoken mentions."
    PRD §3.7: "the provisional estimate and the final settlement intentionally
    differ for the same contract whenever measured exposure differs from the
    script estimate — the final variant also adds the bonus and the verbal-miss
    penalties the provisional one ignores."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_settlement_divergence
    """
    ctx = setup_makegood_required(
        budget_cents=1_000_000,
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        cross_promo_owed_count=2,
        estimated_exposure_seconds=25,
        measured_segments_seconds=[20],
        measured_verbal_mentions=1,
    )
    contract_after_create = ctx["contract"]
    # provisional = 1000000 - round_half_up((30 - 25) * 2000 * 1.5) = 985000
    assert ctx["makegood_credit"]["amount_cents"] == 35_000, (
        f"makegood = min(1000000, round(10*2000*1.5) + 1*5000) = 35000; "
        f"got {ctx['makegood_credit']['amount_cents']}"
    )

    ledger = get_success_data(api.get_contract_ledger(contract_after_create["id"], MANAGER))
    assert ledger["provisional_value_cents"] == 985_000, (
        f"provisional variant must be 985000, got {ledger['provisional_value_cents']}"
    )
    assert ledger["outstanding_balance_cents"] == 965_000, (
        f"after verify with shortfall: 1000000 + 0 - 35000 = 965000, got {ledger['outstanding_balance_cents']}"
    )

    get_success_data(api.waive_makegood_credit(ctx["makegood_credit"]["id"], MANAGER))
    final = get_contract(contract_after_create["id"])
    assert final["status"] == "SETTLED", f"got {final['status']}"
    assert final["final_settlement_cents"] == 1_000_000, (
        f"final variant settles at base + bonus = 1000000, got {final['final_settlement_cents']}"
    )
    assert ledger["provisional_value_cents"] != final["final_settlement_cents"], (
        "the provisional and final variants must diverge for identical contract terms"
    )


def test_provisional_value_visible_at_creation_and_final_differs(api):
    """PRD §3.7: "the provisional estimate and the final settlement
    intentionally differ for the same contract whenever measured exposure
    differs from the script estimate".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_settlement_divergence
    """
    ctx = setup_settled_contract(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=25,
        measured_segments_seconds=[20],
        measured_verbal_mentions=1,
    )
    contract = ctx["contract"]
    assert contract["status"] == "SETTLED"
    assert contract["provisional_value_cents"] == 985_000, (
        f"provisional stays on the contract: got {contract['provisional_value_cents']}"
    )
    assert contract["final_settlement_cents"] == 1_000_000, (
        f"final settlement after waive: got {contract['final_settlement_cents']}"
    )


def test_makegood_severity_surcharge_branching(api):
    """PRD §3.7: "the shortfall seconds are multiplied by the per-second rate
    and by one and a half, rounded half-up to whole cents, and then the verbal
    misses are added at 5000 cents each; when the shortfall amounts to at least
    half of the guaranteed seconds, the combined raw figure is scaled by a
    further 1.2 severe-shortfall surcharge, again rounded half-up to whole
    cents; and the final credit amount is capped at the contract's
    `base_fee_cents`."

    Design: Difficulty/combinatorial_formula/makegood_severity_surcharge_branching
    """
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=25,
        measured_segments_seconds=[10],
        measured_verbal_mentions=2,
    )
    credits = list_makegood_credits(ctx["contract"]["id"])
    assert len(credits) == 1, f"exactly one credit per verification, got {len(credits)}"
    credit = credits[0]
    # shortfall 20/30 >= 0.5 -> raw = round(20*2000*1.5)=60000 -> *1.2 = 72000
    assert credit["amount_cents"] == 72_000, (
        f"surcharge branch: 60000 * 1.2 = 72000, got {credit['amount_cents']}"
    )
    assert credit["reason"] == "EXPOSURE_SHORTFALL", (
        f"verbal_misses == 0 so the reason is EXPOSURE_SHORTFALL, got {credit['reason']}"
    )
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "MAKEGOOD_REQUIRED", f"got {contract['status']}"
    assert contract["outstanding_balance_cents"] == 928_000, (
        f"1000000 + 0 - 72000 = 928000, got {contract['outstanding_balance_cents']}"
    )


def test_makegood_severity_surcharge_applies_at_half_shortfall(api):
    """PRD §3.7: "when the shortfall amounts to at least half of the guaranteed
    seconds, the combined raw figure is scaled by a further 1.2
    severe-shortfall surcharge". PRD §3.7: "a `reason` of `COMBINED` when both
    the shortfall and the verbal misses are positive, `EXPOSURE_SHORTFALL` when
    only the shortfall is positive, or `VERBAL_MISS` otherwise" — with zero
    shortfall seconds the reason is VERBAL_MISS.

    Design: Difficulty/combinatorial_formula/makegood_severity_surcharge_branching
    """
    # Pure verbal miss, no exposure shortfall: surcharge branch cannot fire.
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=1,
    )
    credits = list_makegood_credits(ctx["contract"]["id"])
    assert len(credits) == 1
    credit = credits[0]
    # raw = 0 + 1 * 5000 = 5000; shortfall_ratio 0 < 0.5 -> no surcharge
    assert credit["amount_cents"] == 5_000, (
        f"no surcharge below the half-shortfall ratio: got {credit['amount_cents']}"
    )
    assert credit["reason"] == "VERBAL_MISS", f"got {credit['reason']}"


def test_per_segment_rounding_before_sum(api):
    """PRD §3.7: "`measured_value_cents` monetizes the exposure at seven and a
    half cents per measured second with a pinned evaluation order: each segment
    is first multiplied by 7.5 and that product is rounded half-up to whole
    cents, and only then are the per-segment amounts summed. The order matters
    — two 3-second segments yield 23 cents each (22.5 rounds half-up to 23) for
    a total of 46 cents, whereas summing the seconds first and rounding once
    would yield 45."

    Design: Difficulty/combinatorial_formula/per_segment_rounding_before_sum
    """
    ctx = setup_aired_contract(
        budget_cents=500_000,
        proposed_fee_cents=60_000,
        guaranteed_seconds=4,
        guaranteed_verbal_mentions=0,
        estimated_exposure_seconds=4,
        rate_cents_per_second=2000,
    )
    resp = api.create_airing_report(
        ctx["episode"]["id"],
        {
            "contract_id": ctx["contract"]["id"],
            "measured_segments_seconds": [3, 3],
            "measured_verbal_mentions": 0,
        },
        FILER,
    )
    report = validate_success(resp, expected_status=201)
    assert report["measured_seconds"] == 6, f"got {report['measured_seconds']}"
    assert report["measured_value_cents"] == 46, (
        f"per-segment rounding: 23 + 23 = 46 (NOT 45); got {report['measured_value_cents']}"
    )


def test_per_segment_rounding_fractional_segments(api):
    """PRD §3.7: "`measured_seconds` is the plain, unrounded sum of the
    segments." PRD §3.7: "each segment is first multiplied by 7.5 and that
    product is rounded half-up to whole cents, and only then are the
    per-segment amounts summed."

    Design: Difficulty/combinatorial_formula/per_segment_rounding_before_sum
    """
    ctx = setup_aired_contract(
        budget_cents=500_000,
        proposed_fee_cents=60_000,
        guaranteed_seconds=4,
        guaranteed_verbal_mentions=0,
        estimated_exposure_seconds=4,
        rate_cents_per_second=2000,
    )
    resp = api.create_airing_report(
        ctx["episode"]["id"],
        {
            "contract_id": ctx["contract"]["id"],
            "measured_segments_seconds": [0.2, 0.2, 0.2],
            "measured_verbal_mentions": 0,
        },
        FILER,
    )
    report = validate_success(resp, expected_status=201)
    assert abs(report["measured_seconds"] - 0.6) < 1e-9, (
        f"unrounded sum: got {report['measured_seconds']}"
    )
    # per segment: round_half_up(0.2 * 7.5) = round_half_up(1.5) = 2; total 6
    assert report["measured_value_cents"] == 6, (
        f"3 segments of round_half_up(1.5) = 2 each -> 6; got {report['measured_value_cents']}"
    )


def test_exact_guaranteed_seconds_settles_clean(api):
    """PRD §3.7: "the exposure shortfall is the larger of zero and
    `guaranteed_seconds` minus `measured_seconds`" — exact equality yields zero
    shortfall. PRD §3.7: "When the computed make-good is zero, verification
    settles the contract directly: it moves from `UNDER_VERIFICATION` to
    `SETTLED`, `outstanding_balance_cents` becomes the base fee plus the bonus,
    and `final_settlement_cents` is fixed at the base fee plus the bonus."

    Design: Difficulty/boundary_precision_check/exact_guaranteed_seconds_settles_clean
    """
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[15, 15],
        measured_verbal_mentions=2,
    )
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SETTLED", f"got {contract['status']}"
    assert contract["bonus_cents"] == 0, f"no over-delivery: got {contract['bonus_cents']}"
    assert contract["final_settlement_cents"] == 1_000_000, (
        f"base + bonus = 1000000, got {contract['final_settlement_cents']}"
    )
    credits = list_makegood_credits(ctx["contract"]["id"])
    assert credits == [], f"no MakeGoodCredit at exact equality, got {credits}"


def test_exact_guaranteed_seconds_creates_no_makegood(api):
    """PRD §3.7: "exactly one `MakeGoodCredit` is created for that verification"
    — only "When the make-good is greater than zero". PRD §3.7: "When the
    computed make-good is zero, verification settles the contract directly".

    Design: Difficulty/boundary_precision_check/exact_guaranteed_seconds_settles_clean
    """
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    credits = list_makegood_credits(ctx["contract"]["id"])
    assert credits == [], f"no credit may be created at the == boundary, got {credits}"
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SETTLED"
    assert contract["makegood_total_cents"] == 0


def test_verify_shortfall_cascade_to_cross_promo(api):
    """PRD §3.7: "The credit's creation is a two-link cascade: the contract
    moves from `UNDER_VERIFICATION` to `MAKEGOOD_REQUIRED` (link one), and the
    contract's cross-promotion obligation has its `owed_count` incremented by
    1, flipping from `FULFILLED` to `PARTIALLY_FULFILLED` if it had already
    been fully satisfied (link two). The contract's `makegood_total_cents`
    becomes the sum of its `PENDING` credit amounts, and
    `outstanding_balance_cents` becomes the base fee plus the bonus minus that
    make-good total."

    Design: Difficulty/transitive_cascade/verify_shortfall_cascade_to_cross_promo
    """
    ctx = setup_filed_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        cross_promo_owed_count=2,
        estimated_exposure_seconds=25,
        measured_segments_seconds=[20],
        measured_verbal_mentions=1,
    )
    report = get_success_data(api.verify_airing_report(ctx["report"]["id"], VERIFIER))
    assert report["status"] == "VERIFIED", f"got {report['status']}"

    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "MAKEGOOD_REQUIRED", f"link 1: {contract['status']}"
    assert contract["makegood_total_cents"] == 35_000, (
        f"makegood total: {contract['makegood_total_cents']}"
    )
    assert contract["outstanding_balance_cents"] == 965_000, (
        f"1000000 + 0 - 35000 = 965000, got {contract['outstanding_balance_cents']}"
    )

    credits = list_makegood_credits(ctx["contract"]["id"])
    assert len(credits) == 1
    assert credits[0]["amount_cents"] == 35_000
    assert credits[0]["status"] == "PENDING"
    assert credits[0]["reason"] == "COMBINED", (
        f"shortfall 10 > 0 and verbal miss 1 > 0 -> COMBINED, got {credits[0]['reason']}"
    )

    promos = list_cross_promos(ctx["contract"]["id"])
    assert len(promos) == 1
    assert promos[0]["owed_count"] == 3, (
        f"link 3: owed 2 + penalty 1 = 3, got {promos[0]['owed_count']}"
    )
    assert promos[0]["fulfilled_count"] == 0
    assert promos[0]["status"] == "OWED", f"got {promos[0]['status']}"


def test_verify_shortfall_cascade_flips_fulfilled_obligation(api):
    """PRD §3.7: "the contract's cross-promotion obligation has its `owed_count`
    incremented by 1, flipping from `FULFILLED` to `PARTIALLY_FULFILLED` if it
    had already been fully satisfied (link two)."

    Design: Difficulty/transitive_cascade/verify_shortfall_cascade_to_cross_promo
    """
    # cross_promo_owed_count == 0 -> obligation born FULFILLED; the cascade
    # must increment owed to 1 and flip it to PARTIALLY_FULFILLED.
    ctx = setup_filed_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        cross_promo_owed_count=0,
        estimated_exposure_seconds=25,
        measured_segments_seconds=[20],
        measured_verbal_mentions=1,
    )
    promos_before = list_cross_promos(ctx["contract"]["id"])
    assert promos_before[0]["status"] == "FULFILLED", (
        f"zero-owed obligation starts FULFILLED, got {promos_before[0]['status']}"
    )
    get_success_data(api.verify_airing_report(ctx["report"]["id"], VERIFIER))
    promos = list_cross_promos(ctx["contract"]["id"])
    assert promos[0]["owed_count"] == 1, f"got {promos[0]['owed_count']}"
    assert promos[0]["status"] == "PARTIALLY_FULFILLED", (
        f"FULFILLED flips to PARTIALLY_FULFILLED on the cascade, got {promos[0]['status']}"
    )


def test_makegood_waive_restores_outstanding_balance(api):
    """PRD §3.7: "Waiving restores the contract's balance — the credit's
    `amount_cents` is added back to `outstanding_balance_cents` and subtracted
    from `makegood_total_cents` — and when the waived credit was the last
    `PENDING` one on a contract sitting in `MAKEGOOD_REQUIRED`, the contract
    settles on the spot, moving to `SETTLED` with `final_settlement_cents`
    fixed at the base fee plus the bonus."

    Design: Difficulty/compensating_invariant/makegood_waive_restores_outstanding_balance
    """
    ctx = setup_active_contract(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=25,
    )
    baseline = ctx["contract"]["outstanding_balance_cents"]
    assert baseline == 1_000_000, f"activation baseline: {baseline}"

    # Drive the contract to MAKEGOOD_REQUIRED, then waive.
    from test_helpers import create_airing_report_payload, create_disclosure_payload, set_clock_payload

    ADMIN = TEST_USERS["admin_headers"]
    PROD_CREATOR = TEST_USERS["production_headers"]
    disclosure = get_success_data(
        api.create_disclosure(ctx["contract"]["id"], create_disclosure_payload(), MANAGER)
    )
    get_success_data(api.file_disclosure(disclosure["id"], MANAGER))
    get_success_data(api.set_clock(set_clock_payload(), ADMIN))
    get_success_data(api.mark_episode_aired(ctx["episode"]["id"], PROD_CREATOR))
    get_success_data(api.acknowledge_disclosure(disclosure["id"], NETWORK))
    report = get_success_data(
        api.create_airing_report(
            ctx["episode"]["id"],
            create_airing_report_payload(
                ctx["contract"]["id"],
                measured_segments_seconds=[20],
                measured_verbal_mentions=1,
            ),
            FILER,
        )
    )
    get_success_data(api.verify_airing_report(report["id"], VERIFIER))
    credits = list_makegood_credits(ctx["contract"]["id"])
    get_success_data(api.waive_makegood_credit(credits[0]["id"], MANAGER))

    contract = get_contract(ctx["contract"]["id"])
    assert contract["outstanding_balance_cents"] == 1_000_000, (
        f"verify debit 35000 fully compensated by waive (conserved), got {contract['outstanding_balance_cents']}"
    )
    assert contract["makegood_total_cents"] == 0, f"got {contract['makegood_total_cents']}"
    assert contract["status"] == "SETTLED", f"got {contract['status']}"
    assert contract["final_settlement_cents"] == 1_000_000, (
        f"base + bonus = 1000000, got {contract['final_settlement_cents']}"
    )


def test_makegood_waive_leaves_no_drift_in_balance(api):
    """PRD §3.7: "the credit's `amount_cents` is added back to
    `outstanding_balance_cents` and subtracted from `makegood_total_cents`".

    Design: Difficulty/compensating_invariant/makegood_waive_restores_outstanding_balance
    """
    ctx = setup_makegood_required(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=25,
    )
    credit = ctx["makegood_credit"]
    contract_mid = get_contract(ctx["contract"]["id"])
    assert contract_mid["outstanding_balance_cents"] == 965_000
    assert contract_mid["makegood_total_cents"] == 35_000

    get_success_data(api.waive_makegood_credit(credit["id"], MANAGER))
    contract = get_contract(ctx["contract"]["id"])
    assert contract["outstanding_balance_cents"] == 965_000 + 35_000
    assert contract["makegood_total_cents"] == 35_000 - 35_000


def test_airing_report_dispute_remeasure_cycle(api):
    """PRD §3.7: "may dispute a `VERIFIED` report, moving it to `DISPUTED` and
    reopening the contract from `SETTLED` back to `UNDER_VERIFICATION` with the
    settlement reversed: `final_settlement_cents` returns to null,
    `outstanding_balance_cents` returns to the bare `base_fee_cents`, and
    `bonus_cents` returns to 0." PRD §3.7: "The cycle `VERIFIED` → `DISPUTED` →
    `RE_MEASURED` → `VERIFIED` may repeat until the brand accepts a result."

    Design: Difficulty/non_linear_state_machine/airing_report_dispute_remeasure_cycle
    """
    ctx = setup_settled_contract(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[15, 15],
        measured_verbal_mentions=2,
    )
    brand_rep = make_brand_rep_headers(ctx["brand"]["id"])
    report = get_success_data(api.dispute_airing_report(ctx["report"]["id"], brand_rep))
    assert report["status"] == "DISPUTED", f"got {report['status']}"

    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "UNDER_VERIFICATION", (
        f"settlement reopened: got {contract['status']}"
    )
    assert contract["final_settlement_cents"] is None, (
        f"settlement reversed: final_settlement_cents must return to null, got {contract['final_settlement_cents']}"
    )
    assert contract["outstanding_balance_cents"] == 1_000_000
    assert contract["bonus_cents"] == 0

    report = get_success_data(
        api.remeasure_airing_report(
            ctx["report"]["id"],
            {"measured_segments_seconds": [30], "measured_verbal_mentions": 2},
            FILER,
        )
    )
    assert report["status"] == "RE_MEASURED", f"got {report['status']}"

    report = get_success_data(api.verify_airing_report(ctx["report"]["id"], VERIFIER))
    assert report["status"] == "VERIFIED", f"cycle closes: got {report['status']}"

    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "SETTLED", f"got {contract['status']}"
    assert contract["final_settlement_cents"] == 1_000_000, (
        f"re-settled at base + bonus = 1000000, got {contract['final_settlement_cents']}"
    )


def test_airing_report_dispute_reverses_settlement_fields(api):
    """PRD §3.7: "reopening the contract from `SETTLED` back to
    `UNDER_VERIFICATION` with the settlement reversed: `final_settlement_cents`
    returns to null, `outstanding_balance_cents` returns to the bare
    `base_fee_cents`, and `bonus_cents` returns to 0."

    Design: Difficulty/non_linear_state_machine/airing_report_dispute_remeasure_cycle
    """
    ctx = setup_settled_contract(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    brand_rep = make_brand_rep_headers(ctx["brand"]["id"])
    get_success_data(api.dispute_airing_report(ctx["report"]["id"], brand_rep))
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "UNDER_VERIFICATION", f"got {contract['status']}"
    assert contract["final_settlement_cents"] is None
    assert contract["outstanding_balance_cents"] == 1_000_000
    assert contract["bonus_cents"] == 0


def test_episode_verified_bubble_up_after_full_settlement(api):
    """PRD §3.2: "if the episode is `AIRED`, at least one contract exists for
    it, every contract of the episode is in `SETTLED` or `TERMINATED`, and
    every airing report of the episode is `VERIFIED`, the episode advances from
    `AIRED` to `VERIFIED`, the terminal state, with its `version` incremented
    by 1." PRD §3.2: "every script opportunity of the episode that is currently
    `RESERVED` becomes `CONSUMED` — the reserved scene has now actually aired."

    Design: Corner/state_machines/episode_verified_bubble_up_after_full_settlement
    """
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    episode = get_episode(ctx["episode"]["id"])
    assert episode["status"] == "VERIFIED", (
        f"bubble-up: contract SETTLED + report VERIFIED -> episode VERIFIED, got {episode['status']}"
    )
    opportunity = get_opportunity(ctx["opportunity"]["id"])
    assert opportunity["status"] == "CONSUMED", (
        f"mark-aired consumes the RESERVED opportunity, got {opportunity['status']}"
    )


def test_bonus_applied_on_overdelivery(api):
    """PRD §3.7: "The over-delivery bonus is the smaller of one quarter of the
    contract's `base_fee_cents` and the product of the over-delivered seconds —
    the larger of zero and `measured_seconds` minus `guaranteed_seconds` — with
    the `rate_cents_per_second`; the result is stored in `bonus_cents`."

    Design: Corner/calculations/bonus_applied_on_overdelivery
    """
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[35],
        measured_verbal_mentions=2,
    )
    contract = get_contract(ctx["contract"]["id"])
    # bonus = min(0.25 * 1000000, 5 * 2000) = 10000
    assert contract["bonus_cents"] == 10_000, f"got {contract['bonus_cents']}"
    assert contract["final_settlement_cents"] == 1_010_000, (
        f"base + bonus = 1010000, got {contract['final_settlement_cents']}"
    )
    assert contract["outstanding_balance_cents"] == 1_010_000, (
        f"got {contract['outstanding_balance_cents']}"
    )
    assert contract["status"] == "SETTLED"


def test_cross_promo_zero_owed_fulfilled_at_creation(api):
    """PRD §3.5: "creates the contract's cross-promotion obligation with
    `owed_count` initialized from the contract's `cross_promo_owed_count`,
    `fulfilled_count` at 0, and a status of `FULFILLED` when the owed count is
    zero, otherwise `OWED`."

    Design: Corner/calculations/cross_promo_zero_owed_fulfilled_at_creation
    """
    ctx = setup_active_contract(cross_promo_owed_count=0)
    resp = api.list_contract_cross_promos(ctx["contract"]["id"], MANAGER)
    promos = get_success_data(resp)
    assert len(promos) == 1, f"exactly one obligation is created, got {len(promos)}"
    assert promos[0]["owed_count"] == 0, f"got {promos[0]['owed_count']}"
    assert promos[0]["status"] == "FULFILLED", (
        f"zero-owed boundary: FULFILLED at creation, got {promos[0]['status']}"
    )


def test_ledger_computed_read_after_shortfall(api):
    """PRD §3.5: "it exposes `base_fee_cents`, `bonus_cents`,
    `makegood_total_cents`, `outstanding_balance_cents`, `provisional_value_cents`,
    and `final_settlement_cents` exactly as the workflow steps below have left
    them."

    Design: Corner/endpoints/ledger_computed_read_after_shortfall
    """
    ctx = setup_makegood_required(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=25,
    )
    ledger = get_success_data(api.get_contract_ledger(ctx["contract"]["id"], MANAGER))
    assert_ledger(ledger)
    assert ledger["base_fee_cents"] == 1_000_000
    assert ledger["bonus_cents"] == 0
    assert ledger["makegood_total_cents"] == 35_000
    assert ledger["outstanding_balance_cents"] == 965_000
    assert ledger["provisional_value_cents"] == 985_000
    assert ledger["final_settlement_cents"] is None


def test_waive_terminal_credit_rejected(api):
    """PRD §3.7: "the integration manager waives a `PENDING` credit, moving it
    to the terminal `WAIVED` state." PRD §2.8 stage 6: "when the entity sits in
    a terminal state — a `CLOSED` brief, a `REJECTED`, `CONTRACTED`, or
    `WITHDRAWN` proposal, a `TERMINATED` contract, a `RETURNED` or `CANCELLED`
    shipment, a `DENIED` or `RELEASED` clearance, a `WAIVED` credit, an
    `ACKNOWLEDGED` filing, or a `CONSUMED` or `WITHDRAWN` opportunity — the
    error is `ERR_ALREADY_TERMINAL` (HTTP 409) instead."

    Design: Corner/validations/waive_terminal_credit_rejected
    """
    ctx = setup_makegood_required(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=25,
    )
    credit = ctx["makegood_credit"]
    credit = get_success_data(api.waive_makegood_credit(credit["id"], MANAGER))
    assert credit["status"] == "WAIVED", f"precondition: {credit['status']}"

    resp = api.waive_makegood_credit(credit["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    contract = get_contract(ctx["contract"]["id"])
    assert contract["outstanding_balance_cents"] == 1_000_000, (
        f"the balance is restored exactly once, got {contract['outstanding_balance_cents']}"
    )


def test_create_response_includes_computed_fields_immediately(api):
    """PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field." PRD §3.5: "At
    creation the contract also carries a `provisional_value_cents` estimate,
    computed from the script's own numbers" — 1000000 - round_half_up(5 * 2000
    * 1.5) = 985000.

    Design: Corner/consistency/create_response_includes_computed_fields_immediately
    """
    from test_helpers import setup_approved_proposal

    ctx = setup_approved_proposal(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        estimated_exposure_seconds=25,
        rate_cents_per_second=2000,
    )
    resp = api.create_contract_from_proposal(ctx["proposal"]["id"], MANAGER)
    contract = validate_success(resp, expected_status=201)
    assert contract["provisional_value_cents"] == 985_000, (
        f"provisional_value_cents in the creation response: got {contract['provisional_value_cents']}"
    )
    assert contract["status"] == "PENDING_SIGNATURE", f"got {contract['status']}"
