"""Composed formulas: the three-stage surveillance interval rule and the per-line
coinsurance rounding waterfall."""
from test_helpers import (
    active_recommendation,
    apply_block_action,
    book_slot,
    check_in,
    claim_for_booking,
    complete_exam,
    confirm_prep,
    create_block,
    finalize_report,
    move_clock,
    open_episode,
    read_claim,
    read_episode,
    read_report,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    specimen,
    staff_block,
    start_exam,
)

PLAN_P3 = {
    "plan_code": "P3",
    "payer_name": "Northline Benefit",
    "diagnostic_coinsurance_pct": 0.175,
    "deductible_cents": 0,
    "out_of_pocket_max_cents": 500000,
    "polypectomy_carveout": "DIAGNOSTIC_CONVERTED",
    "anesthesia_bundled": False,
}


def _mac_exam(plan_overrides, patient_overrides, findings, specimens):
    """Stand up a covered MAC block, run a 45-minute exam through to completion,
    then receive and finalize a pathology report with the given specimens."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**plan_overrides)
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician()
    patient = register_patient(plan["id"], **patient_overrides)
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    claim = claim_for_booking(booking["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], **findings)
    report = receive_report(booking["id"], specimens)
    finalize_report(report["id"])
    return {
        "episode_id": episode["id"],
        "booking_id": booking["id"],
        "report_id": report["id"],
        "claim_id": claim["id"],
    }


def _increased_risk_mixed_polyp_exam():
    return _mac_exam(
        {"plan_code": "P1", "payer_name": "Meridian Health"},
        {"birth_date": "1975-04-10", "family_history_crc": True},
        {"prep_quality_bbps": 7, "polyps_removed_count": 3,
         "largest_polyp_mm": 8, "specimen_count": 4},
        [
            specimen("A", "TUBULAR_ADENOMA", 6),
            specimen("B", "TUBULAR_ADENOMA", 4),
            specimen("C", "TUBULAR_ADENOMA", 3),
            specimen("D", "SESSILE_SERRATED_LESION", 8),
        ],
    )


def _single_small_adenoma_exam():
    return _mac_exam(
        PLAN_P3,
        {"birth_date": "1975-04-10"},
        {"prep_quality_bbps": 8, "polyps_removed_count": 1,
         "largest_polyp_mm": 5, "specimen_count": 1},
        [specimen("A", "TUBULAR_ADENOMA", 5)],
    )


def test_findings_counters_are_derived_only_from_the_two_adenoma_histologies():
    """`largest_adenoma_mm` is the greatest `size_mm` among the adenoma specimens — those
    two adenoma histologies only — and is 0 when there are none.

    `villous_component` is true when any specimen's `histology` is
    `TUBULOVILLOUS_ADENOMA`.

    Design: Difficulty/combinatorial_formula/surveillance_interval_nested_min_selects_60_months
    """
    scenario = _increased_risk_mixed_polyp_exam()
    report = read_report(scenario["report_id"])
    episode = read_episode(scenario["episode_id"])

    assert report["adenoma_count"] == 3
    assert report["sessile_serrated_count"] == 1
    assert report["largest_adenoma_mm"] == 6
    assert report["villous_component"] is False
    assert report["adenocarcinoma_present"] is False
    assert episode["risk_tier_snapshot"] == "INCREASED"


def test_sessile_serrated_base_of_sixty_months_ties_with_the_increased_risk_cap():
    """Otherwise, if the aggregate sessile serrated count is at least 1, the base is 60
    months.

    Stage two applies the patient risk cap, read from the episode's frozen
    `risk_tier_snapshot` rather than the patient's live tier: the cap is 120 months for
    `AVERAGE`, 60 months for `INCREASED`, and 24 months for `HIGH`, and the stage-two
    result is the smaller of the stage-one base and that cap.

    Design: Difficulty/combinatorial_formula/surveillance_interval_nested_min_selects_60_months
    """
    scenario = _increased_risk_mixed_polyp_exam()
    recommendation = active_recommendation(scenario["episode_id"])

    assert recommendation["computed_interval_months"] == 60
    assert recommendation["assigned_interval_months"] == 60
    assert recommendation["basis"] == "GUIDELINE"
    assert recommendation["attesting_endoscopist_id"] is None
    assert recommendation["pathology_report_id"] == scenario["report_id"]
    assert recommendation["next_due_date"] == "2031-09-15"


def test_guideline_recommendation_is_copied_onto_the_episode_by_the_cascade():
    """Hop three: because that recommendation now exists, the episode's
    `assigned_interval_months` and `due_date` are set from the recommendation's
    `assigned_interval_months` and `next_due_date`, and the episode moves
    `PATHOLOGY_PENDING → CLOSED_SURVEILLANCE_SET`.

    Design: Difficulty/combinatorial_formula/surveillance_interval_nested_min_selects_60_months
    """
    scenario = _increased_risk_mixed_polyp_exam()
    episode = read_episode(scenario["episode_id"])

    assert episode["assigned_interval_months"] == 60
    assert episode["due_date"] == "2031-09-15"
    assert episode["clinical_status"] == "CLOSED_SURVEILLANCE_SET"


def test_coinsurance_is_rounded_once_per_line_before_the_lines_are_summed():
    """Where a fraction multiplies a cent amount — a coverage percentage or a coinsurance
    percentage — the product is rounded to zero decimal places using round-half-up, and
    **the rounding is applied once per line item and the rounded results are then
    summed**.

    Per-line rounding then summation is normative; summing then rounding diverges by a
    cent at coinsurance fractions such as 0.175.

    Design: Difficulty/combinatorial_formula/claim_per_line_rounding_yields_39367
    """
    scenario = _single_small_adenoma_exam()
    claim = read_claim(scenario["claim_id"])

    assert claim["classification"] == "DIAGNOSTIC"
    assert claim["deductible_applied_cents"] == 0
    assert claim["coinsurance_cents"] == 39367
    assert claim["patient_responsibility_cents"] == 39367
    assert claim["plan_paid_cents"] == 185583


def test_tier_addon_lands_on_the_first_line_of_the_ordered_line_item_array():
    """Step one builds `line_items` as an ordered array of objects each holding a `code`
    and an `allowed_cents`, in exactly the order facility, professional, anesthesia.

    The tier carries an addon of 0 cents for `TIER_1`, 8500 cents for `TIER_2`, and
    19000 cents for `TIER_3`; the addon is added to the `allowed_cents` of the first line
    in the array, and `allowed_amount_cents` becomes `base_allowed_cents` plus the addon.

    Design: Difficulty/combinatorial_formula/claim_per_line_rounding_yields_39367
    """
    scenario = _single_small_adenoma_exam()
    claim = read_claim(scenario["claim_id"])

    assert claim["base_allowed_cents"] == 216450
    assert claim["complexity_tier"] == "TIER_2"
    assert claim["allowed_amount_cents"] == 224950
    assert [line["code"] for line in claim["line_items"]] == [
        "FACILITY", "PROFESSIONAL", "ANESTHESIA",
    ]
    assert [line["allowed_cents"] for line in claim["line_items"]] == [
        129250, 55250, 40450,
    ]
