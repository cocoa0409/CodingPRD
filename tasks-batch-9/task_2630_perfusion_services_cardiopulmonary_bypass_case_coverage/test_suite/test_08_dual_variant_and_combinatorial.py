"""Dual-variant money and competence figures, and the two combinatorial formulas."""
from test_helpers import (
    add_perfusionist,
    adjudicate_ce_activity,
    assert_case_dimensions,
    assert_ce_hours,
    assert_cents,
    assert_contract_ledger,
    assert_line_codes_ascending,
    assert_pack_line,
    assert_readiness_score,
    assign_perfusionist,
    build_pack_line_item,
    close_case,
    close_incident_report,
    closed_case_setup,
    configure_pack,
    create_case,
    create_ce_activity,
    create_certification,
    create_contract,
    create_device,
    create_incident_report,
    create_perfusionist,
    create_preference_card,
    create_slot,
    create_surgeon,
    end_bypass,
    off_bypass_setup,
    open_checklist,
    read_case,
    read_contract,
    read_incident_report,
    read_perfusionist,
    review_incident_report,
    settle_month,
    staffed_setup,
    start_bypass,
    submit_incident_report,
    verify_checklist,
)

# The shared fixture's card prices three lines at 1055, 1155 and 1255 cents, and
# the contract discounts a tenth then marks up a fifth.
PACK_TOTAL_CENTS = 3741


def test_case_fee_provisional_and_final_diverge_on_the_reported_pump_time():
    """The card's standard minutes price the assignment and the reported minutes price the close.

    PRD 3.4: The **provisional fee** and the **final fee** are the same calculation run with a different minute source, and that single divergence is the whole difference between them.
    PRD 3.4: The provisional variant, run at assignment time when no actual pump time exists, takes its minutes from `standard_pump_minutes` on the preference card the selector of §3.5 picks for the case's surgeon and procedure, and it ignores any `pump_time_minutes` on the case even if one is somehow present.
    PRD 3.4: The final variant, run at case close, takes its minutes from the case's reported `pump_time_minutes`.
    PRD 3.4: Otherwise the number of units is the whole-number result, rounded down, of the excess minutes over that threshold divided by 30 — one unit per half hour of prolonged perfusion — plus one.
    PRD 3.4: The fee in cents is then the contract's `per_case_fee_cents` multiplied by one plus the acuity fraction plus the surcharge fraction, rounded half up to a whole number of cents exactly once, at the end, on the fully multiplied product — never term by term.
    PRD 3.10: The final variant of the case fee is computed and written to `final_fee_cents`, the fiscal dimension moves `PROVISIONAL_ACCRUED → FINAL_ACCRUED`, and the contract ledger absorbs **only the delta**: `accrued_case_fee_cents` changes by `final_fee_cents` minus `accrued_fee_cents`, after which `accrued_fee_cents` is set equal to `final_fee_cents`.

    Design: Difficulty/dual_variant_calc/case_fee_provisional_vs_final_diverges_on_actual_pump_time
    """
    env = off_bypass_setup(
        end_bypass_overrides={
            "pump_time_minutes": 210,
            "cross_clamp_minutes": 95,
            "lowest_hematocrit_pct": 24,
            "adverse_event_count": 0,
        }
    )
    case_id = env["case"]["id"]

    # The provisional variant took its minutes from the card's 150, which is below
    # the 180-minute threshold, so no prolonged units accrued.
    provisional = read_case(case_id)
    assert_cents(provisional["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert provisional["final_fee_cents"] is None
    assert_cents(provisional["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_case_dimensions(provisional, "OFF_BYPASS", "PROVISIONAL_ACCRUED")
    assert provisional["pump_time_minutes"] == 210
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)

    closed = close_case(case_id, env["chief"]["id"])
    # 210 reported minutes clear the threshold by 30, so the units are one whole
    # half-hour plus one, and 400000 * (1 + 0 + 2 * 0.15) is 520000.
    assert_cents(closed["final_fee_cents"], 520000, "final_fee_cents")
    assert_cents(closed["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert closed["final_fee_cents"] - closed["provisional_fee_cents"] == 120000
    assert_cents(closed["accrued_fee_cents"], 520000, "accrued_fee_cents")
    assert_case_dimensions(closed, "CLOSED", "FINAL_ACCRUED")

    # The contract absorbed only the delta, and the case kept its accrual slot.
    assert_contract_ledger(read_contract(env["contract"]["id"]), 520000, 1)


def test_case_fee_variants_agree_when_the_reported_minutes_stay_under_the_threshold():
    """A shorter case closes at the very figure it was provisionally accrued at, moving no ledger.

    PRD 3.4: The **provisional fee** and the **final fee** are the same calculation run with a different minute source, and that single divergence is the whole difference between them.
    PRD 3.4: The final variant, run at case close, takes its minutes from the case's reported `pump_time_minutes`.
    PRD 3.4: If the minute figure is strictly below the contract's `prolonged_pump_threshold_minutes`, no prolonged-perfusion units accrue.
    PRD 3.4: The boundary is inclusive on purpose: a case whose minutes exactly equal the threshold earns one unit, and a case one minute short of it earns none.
    PRD 3.10: The final variant of the case fee is computed and written to `final_fee_cents`, the fiscal dimension moves `PROVISIONAL_ACCRUED → FINAL_ACCRUED`, and the contract ledger absorbs **only the delta**: `accrued_case_fee_cents` changes by `final_fee_cents` minus `accrued_fee_cents`, after which `accrued_fee_cents` is set equal to `final_fee_cents`.
    PRD 3.10: The delta may be negative, when the actual pump time fell into a lower prolonged-unit bucket than the card's standard time, and the ledger then falls accordingly; `accrued_case_count` does not change, because the case has occupied its accrual slot since assignment.
    PRD 3.10: The assigned perfusionist's `career_case_count` rises by exactly one, which re-derives their `readiness_score` under the admission variant.

    Design: Difficulty/dual_variant_calc/case_fee_provisional_vs_final_diverges_on_actual_pump_time
    """
    env = off_bypass_setup(
        end_bypass_overrides={
            "pump_time_minutes": 179,
            "cross_clamp_minutes": 60,
            "lowest_hematocrit_pct": 26,
            "adverse_event_count": 0,
        }
    )
    case_id = env["case"]["id"]
    before = read_contract(env["contract"]["id"])
    assert_contract_ledger(before, 400000, 1)

    closed = close_case(case_id, env["chief"]["id"])
    # One minute short of the threshold earns no unit at all, so the final variant
    # returns the same 400000 the provisional variant did.
    assert_cents(closed["final_fee_cents"], 400000, "final_fee_cents")
    assert closed["final_fee_cents"] - closed["provisional_fee_cents"] == 0
    assert_cents(closed["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_case_dimensions(closed, "CLOSED", "FINAL_ACCRUED")
    assert closed["pump_time_minutes"] == 179

    # A zero delta leaves the ledger exactly where the assignment put it, and the
    # accrued case count never moves at close.
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)
    # The closing perfusionist banked the case in their career count.
    assert read_perfusionist(env["p1"]["id"])["career_case_count"] == 151


def _competence_fixture(verify_third_claim):
    """Stand up one perfusionist with 27 verified credit hours plus a 9-hour third claim.

    The third claim is adjudicated only when the caller asks for it, so the same
    stored data can be read once with pending credits outstanding and once
    without. A case is taken through to `OFF_BYPASS` and a report naming that
    perfusionist is filed by a colleague and submitted, ready for review.
    """
    contract = create_contract()
    surgeon = create_surgeon()
    create_preference_card(surgeon["id"])
    p1 = create_perfusionist(career_case_count=130)
    chief = create_perfusionist(
        full_name="Nadia Oyelaran",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )
    p2 = create_perfusionist(
        full_name="Tom Vasquez", employee_code="EMP-1003", career_case_count=90
    )
    create_certification(p1["id"])
    first = create_ce_activity(p1["id"], credit_hours=20, activity_date="2026-02-01T00:00:00Z")
    adjudicate_ce_activity(first["id"], "VERIFIED")
    second = create_ce_activity(
        p1["id"],
        category="TECHNICAL",
        credit_hours=7,
        activity_date="2026-03-01T00:00:00Z",
        accreditation_body="AMSECT",
    )
    adjudicate_ce_activity(second["id"], "VERIFIED")
    third = create_ce_activity(
        p1["id"], category="SAFETY", credit_hours=9, activity_date="2026-04-01T00:00:00Z"
    )
    if verify_third_claim:
        adjudicate_ce_activity(third["id"], "VERIFIED")
    backup = create_device(contract["id"], asset_tag="HLM-002")
    primary = create_device(
        contract["id"], asset_tag="HLM-001", backup_device_id=backup["id"]
    )
    create_slot(contract["id"], p1["id"], chief_id=chief["id"])
    case = create_case(contract["id"], surgeon["id"], chief_id=chief["id"])
    case = assign_perfusionist(case["id"], p1["id"], case["version"], chief["id"])
    configure_pack(case["id"], primary["id"], p1["id"])
    checklist = open_checklist(case["id"], p1["id"], hematocrit_pct=26)
    verify_checklist(checklist["id"], p1["id"])
    start_bypass(case["id"], p1["id"])
    end_bypass(
        case["id"],
        p1["id"],
        pump_time_minutes=210,
        cross_clamp_minutes=95,
        lowest_hematocrit_pct=24,
        adverse_event_count=1,
    )
    report = create_incident_report(
        case["id"],
        p1["id"],
        p2["id"],
        severity="MAJOR",
        category="GAS_EXCHANGE",
        narrative="Oxygenator gas transfer degraded during rewarming.",
    )
    submit_incident_report(report["id"], p2["id"])
    return {
        "contract": contract,
        "p1": p1,
        "chief": chief,
        "p2": p2,
        "case": case,
        "report": report,
    }


def test_readiness_admission_counts_pending_credits_and_the_frozen_audit_figure_does_not():
    """Identical stored data scores 0.830 as an admission and 0.720 as a quality audit.

    PRD 3.2: The **admission** variant counts the holder's verified credits plus their pending credits — the group is willing to admit a perfusionist on the strength of education they have claimed but the back office has not yet adjudicated.
    PRD 3.2: The **audit** variant counts verified credits only.
    PRD 3.2: Everything else is identical: a credit ratio, being the smaller of 1.0 and the counted credits divided by the certification's `cycle_credit_requirement`; an experience ratio, being the smaller of 1.0 and the holder's `career_case_count` divided by a career target of 150 completed cases; and a fatigue penalty, being eight hundredths for each case counted in `consecutive_case_count_24h` plus two hundredths for each hour counted in `ecmo_hours_rolling_7d`.
    PRD 3.2: The raw score is fifty-five hundredths of the credit ratio plus forty-five hundredths of the experience ratio, minus the fatigue penalty.
    PRD 3.9: Accepting for review moves the report `SUBMITTED → UNDER_REVIEW` and, crucially, **freezes** the audit variant of the involved perfusionist's readiness score onto the report as `reviewed_readiness_score`.

    Design: Difficulty/dual_variant_calc/readiness_admission_counts_pending_ce_audit_does_not
    """
    env = _competence_fixture(verify_third_claim=False)
    p1_id = env["p1"]["id"]

    holder = read_perfusionist(p1_id)
    assert_ce_hours(holder["ce_credits_verified"], 27.0)
    assert_ce_hours(holder["ce_credits_pending"], 9.0)
    # The admission variant counts 27 verified plus 9 pending against the 45-hour
    # cycle: 0.55 * (36 / 45) + 0.45 * (130 / 150) with no fatigue is 0.830.
    assert_readiness_score(holder["readiness_score"], 0.830)
    assert holder["readiness_variant_last"] == "ADMISSION"

    reviewed = review_incident_report(
        env["report"]["id"], env["chief"]["id"], "ACCEPT_FOR_REVIEW", review_note="quality review opened"
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    # The audit variant drops the 9 still-submitted hours: 0.55 * (27 / 45) plus
    # the same experience term is 0.720, a 0.110 divergence from the same row.
    assert_readiness_score(reviewed["reviewed_readiness_score"], 0.720)
    frozen = read_incident_report(env["report"]["id"])
    assert_readiness_score(frozen["reviewed_readiness_score"], 0.720)
    assert abs(0.830 - frozen["reviewed_readiness_score"] - 0.110) < 1e-9


def test_readiness_variants_agree_once_every_claim_has_been_verified():
    """With nothing left pending the audit figure frozen onto the report equals the admission score.

    PRD 3.2: The **admission** variant counts the holder's verified credits plus their pending credits — the group is willing to admit a perfusionist on the strength of education they have claimed but the back office has not yet adjudicated.
    PRD 3.2: The **audit** variant counts verified credits only.
    PRD 3.2: The raw score is fifty-five hundredths of the credit ratio plus forty-five hundredths of the experience ratio, minus the fatigue penalty.
    PRD 3.9: Accepting for review moves the report `SUBMITTED → UNDER_REVIEW` and, crucially, **freezes** the audit variant of the involved perfusionist's readiness score onto the report as `reviewed_readiness_score`.

    Design: Difficulty/dual_variant_calc/readiness_admission_counts_pending_ce_audit_does_not
    """
    env = _competence_fixture(verify_third_claim=True)
    p1_id = env["p1"]["id"]

    holder = read_perfusionist(p1_id)
    assert_ce_hours(holder["ce_credits_verified"], 36.0)
    assert_ce_hours(holder["ce_credits_pending"], 0.0)
    assert_readiness_score(holder["readiness_score"], 0.830)
    assert holder["readiness_variant_last"] == "ADMISSION"

    reviewed = review_incident_report(
        env["report"]["id"], env["chief"]["id"], "ACCEPT_FOR_REVIEW", review_note="all credits adjudicated"
    )
    # The one input the variants differ on is now empty, so the audit figure lands
    # on the same 0.830 and the divergence collapses to nothing.
    assert_readiness_score(reviewed["reviewed_readiness_score"], 0.830)
    assert reviewed["reviewed_readiness_score"] == holder["readiness_score"]
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["return_count"] == 0


def test_pack_cost_rounds_each_line_before_summing_the_already_rounded_totals():
    """Three lines each round on their own, and the pack total is the exact sum of those roundings.

    PRD 2.6: Rounding, wherever it is required, is round half up: a value exactly halfway between two representable results rounds away from zero to the larger magnitude.
    PRD 2.6: A disposable pack is rounded once **per line item**, and the pack total is the sum of those already-rounded line totals; rounding the sum of unrounded line values is a different number whenever two or more lines carry fractional remainders, and the per-line result is the normative one.
    PRD 3.5: For each materialised line, the gross value is its `quantity` multiplied by its `unit_cost_cents`; the discounted value is that gross multiplied by one minus the contract's `disposable_discount_pct`; the marked-up value is the discounted value multiplied by one plus the contract's `disposable_markup_pct`; and the line's `line_total_cents` is that marked-up value rounded half up to a whole number of cents.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    Design: Difficulty/combinatorial_formula/pack_cost_rounds_per_line_then_sums
    """
    env = staffed_setup()

    pack = configure_pack(env["case"]["id"], env["d1"]["id"], env["p1"]["id"])
    assert pack["applied_preference_card_id"] == env["card"]["id"]
    lines = pack["line_items"]
    assert len(lines) == 3
    assert_line_codes_ascending(lines)
    # 1055 * 0.9 * 1.2 is 1139.4, 1155 gives 1247.4 and 1255 gives 1355.4.
    assert_pack_line(lines[0], "A_OXYGENATOR", 1, 1055, 1139, False)
    assert_pack_line(lines[1], "B_TUBING_PACK", 1, 1155, 1247, False)
    assert_pack_line(lines[2], "C_CANNULA_SET", 1, 1255, 1355, False)

    assert_cents(pack["pack_cost_cents"], PACK_TOTAL_CENTS, "pack_cost_cents")
    assert pack["pack_cost_cents"] == 1139 + 1247 + 1355
    # Rounding the unrounded aggregate of 3742.2 instead would answer 3742.
    assert pack["pack_cost_cents"] != 3742


def test_pack_lines_that_land_exactly_on_a_half_cent_round_away_from_zero_one_by_one():
    """Two lines that each end in half a cent round up individually and sum a cent above the aggregate.

    PRD 2.6: Rounding, wherever it is required, is round half up: a value exactly halfway between two representable results rounds away from zero to the larger magnitude.
    PRD 2.6: A disposable pack is rounded once **per line item**, and the pack total is the sum of those already-rounded line totals; rounding the sum of unrounded line values is a different number whenever two or more lines carry fractional remainders, and the per-line result is the normative one.
    PRD 3.5: For each materialised line, the gross value is its `quantity` multiplied by its `unit_cost_cents`; the discounted value is that gross multiplied by one minus the contract's `disposable_discount_pct`; the marked-up value is the discounted value multiplied by one plus the contract's `disposable_markup_pct`; and the line's `line_total_cents` is that marked-up value rounded half up to a whole number of cents.
    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    Design: Difficulty/combinatorial_formula/pack_cost_rounds_per_line_then_sums
    """
    env = staffed_setup(
        contract_overrides={"disposable_discount_pct": 0.0, "disposable_markup_pct": 0.25},
        card_overrides={
            "pack_line_items": [
                build_pack_line_item("A_OXYGENATOR", 1, 1006),
                build_pack_line_item("B_TUBING_PACK", 1, 1002),
            ],
            "required_safety_check_codes": ["ACT_BASELINE"],
        },
    )

    pack = configure_pack(env["case"]["id"], env["d1"]["id"], env["p1"]["id"])
    lines = pack["line_items"]
    assert len(lines) == 2
    # 1006 * 1.25 is exactly 1257.5 and 1002 * 1.25 is exactly 1252.5, so each
    # line rounds away from zero to 1258 and 1253.
    assert_pack_line(lines[0], "A_OXYGENATOR", 1, 1006, 1258, False)
    assert_pack_line(lines[1], "B_TUBING_PACK", 1, 1002, 1253, False)

    assert_cents(pack["pack_cost_cents"], 2511, "pack_cost_cents")
    # The unrounded values sum to exactly 2510.0, so an aggregate rounding would
    # answer 2510 and lose the cent the per-line rule earns.
    assert pack["pack_cost_cents"] != 2510


def _closed_case_with_systemic_report(per_case_fee_cents, acuity):
    """Close one case, then run a report on it all the way to a systemic finding.

    The report is filed only after the case has closed, because a live report
    blocks closure. The filer is a third perfusionist so that neither the review
    nor the close collides with the segregation-of-duties rule.
    """
    env = closed_case_setup(
        contract_overrides={"per_case_fee_cents": per_case_fee_cents},
        case_overrides={"acuity": acuity},
        end_bypass_overrides={
            "pump_time_minutes": 150,
            "cross_clamp_minutes": 70,
            "lowest_hematocrit_pct": 25,
            "adverse_event_count": 1,
        },
    )
    p2 = add_perfusionist(env, "p2", full_name="Ines Bauer", employee_code="EMP-1013")
    report = create_incident_report(
        env["case"]["id"],
        env["p1"]["id"],
        p2["id"],
        severity="MAJOR",
        category="CIRCUIT",
        narrative="Arterial line pressure spiked during rewarming and needed manual correction.",
    )
    submit_incident_report(report["id"], p2["id"])
    review_incident_report(report["id"], env["chief"]["id"], "ACCEPT_FOR_REVIEW")
    env["report"] = close_incident_report(
        report["id"], env["chief"]["id"], "SYSTEMIC", closing_note="circuit handling retraining"
    )
    return env


def test_settlement_tiers_on_the_pre_credit_gross_and_then_invoices_the_settled_case():
    """A gross of 5100000 tiers at three percent and both credits come off that gross.

    PRD 3.10: `case_fee_gross_cents` is the sum of `final_fee_cents` over the contract's cases whose `billing_status` is `FINAL_ACCRUED` and whose `bypass_ended_at` falls inside the period — cases still `PROVISIONAL_ACCRUED`, cases already `INVOICED` and cases `CREDITED` are all excluded, so a case is billed exactly once in its life.
    PRD 3.10: `coverage_fee_cents` is the contract's `monthly_coverage_fee_cents` when its `staffing_model` is `COVERAGE_PLUS_PER_CASE` or `FULL_COVERAGE`, and 0 for a `PER_CASE` contract.
    PRD 3.10: The three added together give `pre_credit_gross_cents`.
    PRD 3.10: The tier key is that pre-credit gross, and this matters.
    PRD 3.10: `volume_credit_pct` is 0.00 below 5000000 cents, 0.03 from 5000000 cents inclusive, and 0.06 from 10000000 cents inclusive — the boundaries are inclusive, so a pre-credit gross of exactly 5000000 earns 0.03.
    PRD 3.10: `volume_credit_cents` is the pre-credit gross multiplied by that percentage with round-half-up applied once.
    PRD 3.10: `quality_credit_cents` is 150000 cents multiplied by the number of incident reports of this contract's cases whose `finding` is `SYSTEMIC` and whose `updated_at` falls inside the period — the reports are counted by when they were last written, which for a closed report is its closure.
    PRD 3.10: `net_settlement_cents` is the pre-credit gross minus both credits, an exact integer subtraction with no further rounding, floored at 0 so a month whose credits exceed its gross settles at zero rather than negative.
    PRD 3.10: As a side effect every settled case moves `FINAL_ACCRUED → INVOICED` with its `accrued_fee_cents` left **unchanged**, which is why invoicing does not disturb the contract's `accrued_case_fee_cents` at all: the ledger tracks what has been earned, and settlement only records that it has been billed.

    Design: Difficulty/combinatorial_formula/settlement_credit_tier_keyed_on_pre_credit_gross
    """
    env = _closed_case_with_systemic_report(3120000, "EMERGENT")
    # An emergent case lifts the 3120000 base by a quarter to 3900000, and the
    # reported 150 pump minutes stay under the prolonged threshold.
    assert_cents(env["case"]["final_fee_cents"], 3900000, "final_fee_cents")
    assert env["report"]["finding"] == "SYSTEMIC"

    run = settle_month(env["contract"]["id"], "2026-08")

    assert run["period"] == "2026-08"
    assert run["case_count"] == 1
    assert_cents(run["case_fee_gross_cents"], 3900000, "case_fee_gross_cents")
    assert_cents(run["ecmo_gross_cents"], 0, "ecmo_gross_cents")
    assert_cents(run["coverage_fee_cents"], 1200000, "coverage_fee_cents")
    assert_cents(run["pre_credit_gross_cents"], 5100000, "pre_credit_gross_cents")
    assert abs(float(run["volume_credit_pct"]) - 0.03) < 1e-9, (
        f"expected volume_credit_pct 0.03, got {run['volume_credit_pct']}"
    )
    assert_cents(run["volume_credit_cents"], 153000, "volume_credit_cents")
    assert_cents(run["quality_credit_cents"], 150000, "quality_credit_cents")
    assert_cents(run["net_settlement_cents"], 4797000, "net_settlement_cents")
    assert isinstance(run["contract_version"], int)

    case = read_case(env["case"]["id"])
    assert_case_dimensions(case, "CLOSED", "INVOICED")
    assert_cents(case["accrued_fee_cents"], 3900000, "accrued_fee_cents")
    contract = read_contract(env["contract"]["id"])
    assert contract["last_settlement_period"] == "2026-08"
    assert_contract_ledger(contract, 3900000, 1)


def test_a_pre_credit_gross_of_exactly_the_tier_boundary_still_earns_the_tier():
    """A gross of exactly 5000000 takes the inclusive three percent and nets below the boundary.

    PRD 3.10: `volume_credit_pct` is 0.00 below 5000000 cents, 0.03 from 5000000 cents inclusive, and 0.06 from 10000000 cents inclusive — the boundaries are inclusive, so a pre-credit gross of exactly 5000000 earns 0.03.
    PRD 3.10: `volume_credit_cents` is the pre-credit gross multiplied by that percentage with round-half-up applied once.
    PRD 3.10: `net_settlement_cents` is the pre-credit gross minus both credits, an exact integer subtraction with no further rounding, floored at 0 so a month whose credits exceed its gross settles at zero rather than negative.
    PRD 3.10: Because the tier was chosen from the pre-credit figure, applying the credits may carry the net below the tier boundary without re-tiering: a pre-credit gross of 5000000 earns a volume credit of 150000 and, with one systemic report, a quality credit of 150000, netting 4700000 while still having been tiered at 0.03.

    Design: Difficulty/combinatorial_formula/settlement_credit_tier_keyed_on_pre_credit_gross
    """
    env = _closed_case_with_systemic_report(3800000, "ELECTIVE")
    assert_cents(env["case"]["final_fee_cents"], 3800000, "final_fee_cents")

    run = settle_month(env["contract"]["id"], "2026-08")

    assert_cents(run["case_fee_gross_cents"], 3800000, "case_fee_gross_cents")
    assert_cents(run["coverage_fee_cents"], 1200000, "coverage_fee_cents")
    assert_cents(run["pre_credit_gross_cents"], 5000000, "pre_credit_gross_cents")
    assert abs(float(run["volume_credit_pct"]) - 0.03) < 1e-9, (
        f"the boundary of 5000000 is inclusive, got pct {run['volume_credit_pct']}"
    )
    assert_cents(run["volume_credit_cents"], 150000, "volume_credit_cents")
    assert_cents(run["quality_credit_cents"], 150000, "quality_credit_cents")
    # The net of 4700000 sits below the boundary, and no re-tiering follows it.
    assert_cents(run["net_settlement_cents"], 4700000, "net_settlement_cents")
    assert_case_dimensions(read_case(env["case"]["id"]), "CLOSED", "INVOICED")
