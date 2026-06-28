"""Provisional and final entry pricing: duty, MPF floor/ceiling, HMF, excise tax,
USMCA preference variants, and the pinned round-per-line-then-sum order.

All monetary expected values are integer cents and are copied verbatim from the
design indices (no recomputation here).
"""
import test_helpers as h


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc
# ---------------------------------------------------------------------------
def test_provisional_vs_final_diverge_on_unverified_usmca(api):
    """PRD §3.4: "any line whose `preference_claim` is `USMCA` has its `line_duty_cents` set to 0 regardless of the entry's country of origin".
    PRD §3.9: "A line claiming `USMCA` earns its zero duty — `line_duty_cents` of 0 and `preference_verified` set to true — only when the entry's `country_of_origin` is one of the FTA-eligible origins, namely `MX` or `CA`; otherwise the full base duty is restored as `line_duty_cents` and `preference_verified` is set to false."

    Provisional trusts the USMCA apparel claim (duty 0, MPF waived) so the
    provisional total is just the HMF on 400000 (520). At liquidation the CN
    origin is not FTA-eligible, so the 1650bps apparel duty (66000) is restored,
    MPF is no longer waived (floor 3215), giving 69735.

    Design: Difficulty/dual_variant_calc/entry_provisional_vs_final_charges_diverge_on_unverified_usmca
    """
    ctx = h.setup_released_entry(
        api,
        lines=[{"hts_code": "6109100012", "customs_value_cents": 400_000,
                "quantity": 10, "preference_claim": "USMCA"}],
        country_of_origin="CN",
    )
    entry = ctx["entry"]
    assert entry["provisional_total_cents"] == 520, entry
    liquidated = h.liquidate_entry(api, entry["id"], h.OFFICER)
    assert liquidated["final_total_cents"] == 69735, liquidated
    assert liquidated["total_duties_owed_cents"] == 69735, liquidated


def test_provisional_total_trusts_usmca_claim_at_filing(api):
    """PRD §3.4: "In the provisional variant a `USMCA` preference claim is trusted unconditionally — any line whose `preference_claim` is `USMCA` has its `line_duty_cents` set to 0 regardless of the entry's country of origin".
    PRD §3.4: "The merchandise processing fee is waived entirely, set to 0, when every line on the entry carries a verified preference for the variant being computed; in the provisional variant that means every line claims `USMCA`."

    A single USMCA apparel line (cv 400000) from CN gives duty 0 and waived MPF,
    so provisional_total_cents is only the HMF (400000 * 13bps = 520).

    Design: Difficulty/dual_variant_calc/entry_provisional_vs_final_charges_diverge_on_unverified_usmca
    """
    ctx = h.setup_filed_entry(
        api,
        lines=[{"hts_code": "6109100012", "customs_value_cents": 400_000,
                "quantity": 10, "preference_claim": "USMCA"}],
        country_of_origin="CN",
    )
    assert ctx["entry"]["provisional_total_cents"] == 520, ctx["entry"]


def test_psc_grant_adjustment_on_no_preference_general_entry(api):
    """PRD §3.10: "the `adjustment_cents` is the `corrected_value_delta_cents` multiplied by the general rate of 500 basis points, divided by 10000, rounded half up, with the sign preserved so that a negative delta yields a refund."
    PRD §3.10: "The grant then adds the `adjustment_cents` to the entry's
    `final_total_cents` and sets the entry's `total_duties_owed_cents` to that new
    final total".

    Delta +200000 on a no-preference general entry -> adjustment 10000; the
    liquidated final (54800) becomes 64800.

    Design: Difficulty/dual_variant_calc/psc_grant_adjustment_vs_zero_when_preference_verified
    """
    ctx = h.setup_liquidated_entry_with_psc(api, corrected_value_delta_cents=200_000)
    granted = h.validate_success(api.grant_psc(ctx["psc"]["id"], h.OFFICER))
    assert granted["adjustment_cents"] == 10000, granted
    assert granted["status"] == "GRANTED", granted
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry["final_total_cents"] == 64800, entry


def test_psc_grant_adjustment_zero_when_preference_verified(api):
    """PRD §3.10: "If every line of the entry has `preference_verified` true, the
    value change is duty-free under USMCA and the `adjustment_cents` is 0."

    On an MX-origin entry whose only USMCA line liquidates with
    preference_verified true, a granted PSC carrying a +200000 delta yields
    adjustment_cents 0 (the value change is duty-free), so the final total is
    unchanged.

    Design: Difficulty/dual_variant_calc/psc_grant_adjustment_vs_zero_when_preference_verified
    """
    ctx = h.setup_liquidated_entry(
        api,
        lines=[{"hts_code": "6109100012", "customs_value_cents": 400_000,
                "quantity": 1, "preference_claim": "USMCA"}],
        country_of_origin="MX",
    )
    final_before = ctx["entry"]["final_total_cents"]
    psc = h.submit_psc(
        api, ctx["entry"]["id"], ctx["entry_version"],
        broker_headers=ctx["base"]["broker"], corrected_value_delta_cents=200_000,
    )
    granted = h.validate_success(api.grant_psc(psc["id"], h.OFFICER))
    assert granted["adjustment_cents"] == 0, granted
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry["final_total_cents"] == final_before, entry


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula
# ---------------------------------------------------------------------------
def test_mpf_floor_clamps_small_dutiable_value(api):
    """PRD §3.4: "the fee is then the raw figure clamped to be no less than 3215
    cents and no more than 62333 cents — that is, the larger of 3215 and the raw
    figure, then the smaller of that and 62333."

    A tiny general ch94 line (cv 50000) gives mpf_raw 175, which clamps UP to the
    floor 3215; total = duty 2500 + MPF 3215 + HMF 65 = 5780.

    Design: Difficulty/combinatorial_formula/mpf_floor_ceiling_nonlinear_min_max
    """
    ctx = h.setup_filed_entry(
        api,
        lines=[{"hts_code": "9403600080", "customs_value_cents": 50_000,
                "quantity": 1, "preference_claim": "NONE"}],
    )
    assert ctx["entry"]["provisional_total_cents"] == 5780, ctx["entry"]


def test_mpf_ceiling_clamps_large_dutiable_value(api):
    """PRD §3.4: "the fee is then the raw figure clamped to be no less than 3215
    cents and no more than 62333 cents — that is, the larger of 3215 and the raw
    figure, then the smaller of that and 62333."

    A large machinery ch85 line (cv 20000000) gives mpf_raw 70000, which clamps
    DOWN to the ceiling 62333; total = duty 500000 + MPF 62333 + HMF 26000 = 588333.

    Design: Difficulty/combinatorial_formula/mpf_floor_ceiling_nonlinear_min_max
    """
    ctx = h.setup_filed_entry(
        api,
        lines=[{"hts_code": "8501100000", "customs_value_cents": 20_000_000,
                "quantity": 1, "preference_claim": "NONE"}],
        bond_limit_cents=1_000_000_000,
    )
    assert ctx["entry"]["provisional_total_cents"] == 588333, ctx["entry"]


def test_duty_rounds_per_line_then_sums(api):
    """PRD §2.5: "the rounding happens per line and only then are the rounded line
    figures summed — the system rounds each line's duty to an integer cent first
    and adds those integers, never the reverse of summing exact values and rounding
    once at the end."

    Two apparel ch62 lines (dv 500070 and 300070 at 1650bps) round per line to
    82512 and 49512 (sum 132024); the sum-then-round path would give 132023. The
    pinned order makes the duty component 132024 and provisional_total_cents 136279.

    Design: Difficulty/combinatorial_formula/duty_round_per_line_then_sum_order_pinned
    """
    base = h.setup_base(api)
    entry, lines = h.create_draft_entry_with_lines(
        api,
        base,
        [{"hts_code": "6203420000", "customs_value_cents": 500_070,
          "quantity": 1, "preference_claim": "NONE"},
         {"hts_code": "6203420000", "customs_value_cents": 300_070,
          "quantity": 1, "preference_claim": "NONE"}],
    )
    filed = h.file_entry(api, entry["id"], base["broker"])
    line_a = h.validate_success(api.get_entry(filed["id"], base["broker"]))  # touch
    listed, _ = h.validate_paginated(api.list_lines(entry["id"], base["broker"]))
    by_id = {l["id"]: l for l in listed}
    assert by_id[lines[0]["id"]]["line_duty_cents"] == 82512, by_id[lines[0]["id"]]
    assert by_id[lines[1]["id"]]["line_duty_cents"] == 49512, by_id[lines[1]["id"]]
    assert filed["provisional_total_cents"] == 136279, filed


def test_duty_round_per_line_observable_on_line_records(api):
    """PRD §2.5: "This round-per-line-then-sum order is pinned and is observable
    wherever multiple lines contribute to an entry's duty total."

    Each apparel line's stored line_duty_cents is independently rounded half up
    (82512 and 49512); their integer sum (132024) — not the rounded exact sum
    (132023) — is what feeds the entry total.

    Design: Difficulty/combinatorial_formula/duty_round_per_line_then_sum_order_pinned
    """
    base = h.setup_base(api)
    entry, lines = h.create_draft_entry_with_lines(
        api,
        base,
        [{"hts_code": "6203420000", "customs_value_cents": 500_070,
          "quantity": 1, "preference_claim": "NONE"},
         {"hts_code": "6203420000", "customs_value_cents": 300_070,
          "quantity": 1, "preference_claim": "NONE"}],
    )
    filed = h.file_entry(api, entry["id"], base["broker"])
    listed, _ = h.validate_paginated(api.list_lines(entry["id"], base["broker"]))
    duties = sorted(l["line_duty_cents"] for l in listed)
    assert duties == [49512, 82512], duties


# ---------------------------------------------------------------------------
# Queue B — calculations section
# ---------------------------------------------------------------------------
def test_provisional_charges_machinery_components_correct(api):
    """PRD §3.4: "chapter "84" or "85" (machinery and electronics) uses 250 basis
    points". MPF "equal to the total dutiable value multiplied by 35 basis points";
    HMF "equals the total dutiable value multiplied by 13 basis points".

    A single machinery ch85 line (cv 1000000) yields duty 25000, MPF 3500,
    HMF 1300, tax 0; provisional_total_cents == 29800.

    Design: Corner/calculations/provisional_charges_general_machinery_components_correct
    """
    ctx = h.setup_filed_entry(
        api, lines=[{"hts_code": "8501100000", "customs_value_cents": 1_000_000,
                     "quantity": 1}]
    )
    listed, _ = h.validate_paginated(
        api.list_lines(ctx["entry"]["id"], ctx["base"]["broker"])
    )
    assert listed[0]["line_duty_cents"] == 25000, listed[0]
    assert ctx["entry"]["provisional_total_cents"] == 29800, ctx["entry"]


def test_fda_line_adds_excise_tax_component(api):
    """PRD §3.4: "a tax component applies when any line on the entry has a `pga_flag` of `FDA`, serving as an excise proxy: it equals the total dutiable value multiplied by 200 basis points, divided by 10000, rounded half up".

    An FDA-flagged general line (cv 200000) adds tax 4000; with duty 10000,
    MPF floor 3215, HMF 260, the provisional total is 17475.

    Design: Corner/calculations/fda_line_adds_excise_tax_component
    """
    ctx = h.setup_filed_entry_with_pending_pga(api, fda_line_value=200_000)
    assert ctx["entry"]["provisional_total_cents"] == 17475, ctx["entry"]


def test_ftz_06_entry_waives_hmf_component(api):
    """PRD §3.4: "the harbor maintenance fee applies to every entry whose `entry_type` is not `FTZ_06`" ... "for an `FTZ_06` entry the harbor maintenance fee is 0."

    An FTZ_06 general ch94 line (cv 1000000) zeroes HMF: duty 50000 + MPF 3500 +
    HMF 0 + tax 0 = provisional_total_cents 53500.

    Design: Corner/calculations/ftz_06_entry_waives_hmf_component
    """
    ctx = h.setup_filed_entry(
        api,
        lines=[{"hts_code": "9403600080", "customs_value_cents": 1_000_000,
                "quantity": 1}],
        entry_type="FTZ_06",
    )
    assert ctx["entry"]["provisional_total_cents"] == 53500, ctx["entry"]


def test_final_usmca_verified_mx_origin_zero_duty_mpf_waived(api):
    """PRD §3.9: "A line claiming `USMCA` earns its zero duty — `line_duty_cents` of 0 and `preference_verified` set to true — only when the entry's `country_of_origin` is one of the FTA-eligible origins, namely `MX` or `CA`".
    PRD §3.9: "the merchandise processing fee ad valorem at 35 basis points
    clamped between 3215 and 62333 cents, waived to 0 only when every line's
    `preference_verified` is true in this final variant".

    Origin MX with one USMCA apparel line (cv 400000): final line_duty 0,
    preference_verified true, MPF waived, HMF 520; final_total_cents == 520.

    Design: Corner/calculations/final_usmca_verified_mx_origin_zero_duty_mpf_waived
    """
    ctx = h.setup_liquidated_entry(
        api,
        lines=[{"hts_code": "6109100012", "customs_value_cents": 400_000,
                "quantity": 1, "preference_claim": "USMCA"}],
        country_of_origin="MX",
    )
    listed, _ = h.validate_paginated(
        api.list_lines(ctx["entry"]["id"], ctx["base"]["broker"])
    )
    assert listed[0]["line_duty_cents"] == 0, listed[0]
    assert listed[0]["preference_verified"] is True, listed[0]
    assert ctx["entry"]["final_total_cents"] == 520, ctx["entry"]


def test_mpf_ceiling_clamps_large_dutiable_value_corner(api):
    """PRD §3.4: "the fee is then the raw figure clamped to be no less than 3215
    cents and no more than 62333 cents — that is, the larger of 3215 and the raw
    figure, then the smaller of that and 62333."

    A machinery ch85 line cv 20000000 (mpf_raw 70000) clamps DOWN to 62333; total
    duty 500000 + MPF 62333 + HMF 26000 = 588333.

    Design: Corner/calculations/mpf_ceiling_clamps_large_dutiable_value
    """
    ctx = h.setup_filed_entry(
        api,
        lines=[{"hts_code": "8501100000", "customs_value_cents": 20_000_000,
                "quantity": 1}],
        bond_limit_cents=1_000_000_000,
    )
    assert ctx["entry"]["provisional_total_cents"] == 588333, ctx["entry"]


def test_protest_filing_kind_uses_same_adjustment_formula(api):
    """PRD §3.10: "Corrections and protests share this one formula; only the `filing_kind` label distinguishes them."

    A PROTEST with delta +200000 on a no-preference general entry yields
    adjustment_cents 10000 (general 500bps), identical to a PSC.

    Design: Corner/calculations/psc_protest_filing_kind_uses_same_adjustment_formula
    """
    ctx = h.setup_liquidated_entry_with_psc(
        api, corrected_value_delta_cents=200_000, filing_kind="PROTEST"
    )
    granted = h.validate_success(api.grant_psc(ctx["psc"]["id"], h.OFFICER))
    assert granted["adjustment_cents"] == 10000, granted
    assert granted["status"] == "GRANTED", granted


def test_entry_line_dutiable_value_computed_from_value_plus_assists(api):
    """PRD §3.3: "the line's `dutiable_value_cents` equals its `customs_value_cents`
    plus its `assists_cents`."

    A line cv 400000 + assists 50000 stores dutiable_value_cents 450000.

    Design: Corner/entities/entry_line_dutiable_value_computed_from_value_plus_assists
    """
    base = h.setup_base(api, clock=None)
    entry, _ = h.create_draft_entry_with_lines(api, base, [], attach_isf=False)
    line = h.validate_success(
        api.create_line(
            entry["id"],
            {"hts_code": "9403600080", "customs_value_cents": 400_000,
             "assists_cents": 50_000, "quantity": 1},
            base["broker"],
        ),
        expected_status=201,
    )
    assert line["dutiable_value_cents"] == 450000, line
