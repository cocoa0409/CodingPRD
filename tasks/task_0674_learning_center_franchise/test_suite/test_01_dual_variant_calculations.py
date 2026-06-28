"""Dual-variant calculations: diagnostic placement (STRICT vs SUPPORTIVE) and
royalty owed (ROYALTY_FLOOR vs COMBINED_FLOOR).

Queue A — Difficulty/dual_variant_calc.
"""
from test_helpers import (
    get_success_data, validate_success,
    setup_operating_center_with_subject, create_family, create_student,
    create_enrollment, place_enrollment, create_and_place_enrollment,
    create_and_issue_invoice, create_family as _cf,
    make_center_director_headers,
)
from test_helpers import api_client as api

DIRECTOR = make_center_director_headers()


# ===========================================================================
# placement_strict_vs_supportive_diverge_on_same_diagnostic
# ===========================================================================
def test_placement_strict_lands_at_target_index():
    """PRD §3.3: "Under the default `STRICT` policy, the placement level is exactly
    the level at the target index."
    PRD §3.3: "Compute a target index as the score divided by that band width,
    rounded down to a whole number, then capped so it is no greater than N minus 1;
    this index is zero-based into the rank-sorted list."

    With 4 levels (band width 25) and diagnostic_raw_score=50, target index =
    floor(50/25)=2 -> rank-3 level (L3).

    Design: Difficulty/dual_variant_calc/placement_strict_vs_supportive_diverge_on_same_diagnostic
    """
    center, _ag, subject, levels = setup_operating_center_with_subject(num_levels=4)
    family = create_family(center["id"])
    student = create_student(family["id"])
    en = create_enrollment(center["id"], student["id"], subject["id"], diagnostic_raw_score=50)
    placed = place_enrollment(en["id"], placement_policy="STRICT")
    assert placed["current_level_id"] == levels[2]["id"], \
        f"STRICT score=50 over 4 levels should land at rank-3 level (index 2)"


def test_placement_supportive_lands_one_level_below_strict():
    """PRD §3.3: "Under the `SUPPORTIVE` policy, the placement level is the level one
    position below the target index — that is, at the index obtained by subtracting 1
    from the target index but never going below 0 — so that for the same
    `diagnostic_raw_score`, `SUPPORTIVE` lands a student a level lower than `STRICT`
    whenever the target index is greater than 0, and on the same entry level otherwise."

    With 4 levels (band 25) and score=50, target index 2; SUPPORTIVE -> index 1 (L2),
    which differs from STRICT's index 2 (L3).

    Design: Difficulty/dual_variant_calc/placement_strict_vs_supportive_diverge_on_same_diagnostic
    """
    center, _ag, subject, levels = setup_operating_center_with_subject(num_levels=4)
    family = create_family(center["id"])
    st_strict = create_student(family["id"], full_name="Kid Strict")
    st_supp = create_student(family["id"], full_name="Kid Supp")
    en_strict = create_enrollment(center["id"], st_strict["id"], subject["id"], diagnostic_raw_score=50)
    en_supp = create_enrollment(center["id"], st_supp["id"], subject["id"], diagnostic_raw_score=50)

    strict_resp = api.place_enrollment(en_strict["id"], {"placement_policy": "STRICT"}, DIRECTOR)
    supp_resp = api.place_enrollment(en_supp["id"], {"placement_policy": "SUPPORTIVE"}, DIRECTOR)
    strict_data = validate_success(strict_resp)
    supp_data = validate_success(supp_resp)

    assert strict_data["current_level_id"] == levels[2]["id"], "STRICT -> L3 (index 2)"
    assert supp_data["current_level_id"] == levels[1]["id"], "SUPPORTIVE -> L2 (index 1)"
    assert strict_data["current_level_id"] != supp_data["current_level_id"], \
        "STRICT and SUPPORTIVE must diverge for identical diagnostic_raw_score=50"


# ===========================================================================
# royalty_floor_on_royalty_only_vs_combined_diverge_same_tuition
# ===========================================================================
def _setup_paid_solo_invoice(royalty_basis):
    """OPERATING center (tuition 15000) + ROYALTY_FLOOR/COMBINED_FLOOR agreement
    (rate 1000 bps, marketing 200 bps, min 50000), one ACTIVE solo enrollment,
    invoice issued and ready to pay. Returns the issued invoice + family."""
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000,
        agreement_overrides={"royalty_rate_bps": 1000, "marketing_fee_bps": 200,
                             "minimum_monthly_royalty_cents": 50000,
                             "royalty_basis": royalty_basis})
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    invoice = create_and_issue_invoice(family["id"], center["id"], "2026-05")
    return invoice, family


def test_royalty_floor_on_royalty_only_binds_floor_then_adds_marketing():
    """PRD §3.7: "Under `ROYALTY_FLOOR`, the floor applies to the percentage royalty
    alone: `royalty_owed_cents` is the greater of the percentage royalty and
    `minimum_monthly_royalty_cents`, plus the marketing amount."

    tuition 15000, rate 1000bps -> pct 1500 < min 50000 -> floor 50000; marketing
    200bps -> 300; royalty_owed = 50000 + 300 = 50300.

    Design: Difficulty/dual_variant_calc/royalty_floor_on_royalty_only_vs_combined_diverge_same_tuition
    """
    invoice, _family = _setup_paid_solo_invoice("ROYALTY_FLOOR")
    # total_due = tuition 15000 + enrollment fee 5000 = 20000
    paid = validate_success(api.pay_invoice(invoice["id"], {"amount_cents": 20000}, DIRECTOR))
    assert paid["royalty_owed_cents"] == 50300, \
        f"ROYALTY_FLOOR: max(1500,50000)+300=50300, got {paid['royalty_owed_cents']}"


def test_royalty_combined_floor_binds_on_pct_plus_marketing():
    """PRD §3.7: "Under `COMBINED_FLOOR`, the floor applies to the percentage royalty
    and marketing combined: `royalty_owed_cents` is the greater of (the percentage
    royalty plus the marketing amount) and `minimum_monthly_royalty_cents`."
    PRD §3.7: "For identical tuition the two variants diverge whenever the percentage
    royalty is below the minimum and the marketing amount is above zero."

    tuition 15000: pct 1500 + marketing 300 = 1800 < min 50000 -> 50000, differing
    from ROYALTY_FLOOR's 50300.

    Design: Difficulty/dual_variant_calc/royalty_floor_on_royalty_only_vs_combined_diverge_same_tuition
    """
    invoice, _family = _setup_paid_solo_invoice("COMBINED_FLOOR")
    paid = validate_success(api.pay_invoice(invoice["id"], {"amount_cents": 20000}, DIRECTOR))
    assert paid["royalty_owed_cents"] == 50000, \
        f"COMBINED_FLOOR: max(1500+300,50000)=50000, got {paid['royalty_owed_cents']}"
