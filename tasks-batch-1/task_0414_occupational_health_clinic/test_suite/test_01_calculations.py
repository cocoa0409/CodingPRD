"""Calculation rules: OSHA recordability, invoice totals/discounts, surveillance outcomes,
encounter billing snapshot pricing. Translates difficulty queue (combinatorial_formula,
boundary_precision_check, dual_variant_calc) plus corner-design calculation instances.
"""
from test_helpers import (
    get_success_data,
    TEST_USERS, make_clinician_headers, make_mro_headers,
    panel, setup_employer_with_active_protocol, create_worker,
    setup_checked_in_encounter, setup_surveillance_exam,
    setup_employer_with_n_completed_physicals, create_draft_invoice,
    create_completed_physical_for_employer, issue_clearance,
    advance_drug_screen_to_at_lab, advance_drug_screen_to_lab_reported,
    advance_drug_screen_to_mro_review,
    create_drug_screen_payload, create_injury_case_payload,
    add_work_status,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]


# ─── OSHA recordability (PRD §3.10) ───────────────────

def test_osha_fatality_outranks_all(api):
    """PRD §3.10: "if `treatment_level` is `FATALITY`, the case is recordable and `osha_column`
    is `DEATH`" and "the first matching rule wins".

    Design: Corner/calculations/osha_fatality_outranks_all
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "FATALITY", days_away=0, days_restricted=0), CLIN))
    assert ic["osha_column"] == "DEATH"
    assert ic["is_osha_recordable"] is True


def test_osha_first_aid_not_recordable(api):
    """PRD §3.10: "the remaining case, `treatment_level` of `FIRST_AID` — the case is not
    recordable and `osha_column` is `NOT_RECORDABLE`".

    Design: Corner/calculations/osha_first_aid_not_recordable
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "FIRST_AID", days_away=0, days_restricted=0), CLIN))
    assert ic["is_osha_recordable"] is False
    assert ic["osha_column"] == "NOT_RECORDABLE"


def test_osha_medical_treatment_other_recordable(api):
    """PRD §3.10: "if `treatment_level` is `MEDICAL_TREATMENT`, the case is recordable and
    `osha_column` is `OTHER_RECORDABLE`".

    Design: Corner/calculations/osha_medical_treatment_other_recordable
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "MEDICAL_TREATMENT", days_away=0, days_restricted=0), CLIN))
    assert ic["osha_column"] == "OTHER_RECORDABLE"
    assert ic["is_osha_recordable"] is True


def test_osha_away_dominates_restricted_column(api):
    """PRD §3.10: "Because precedence is strict, an injury with both at least 1 day away and at
    least 1 day restricted is logged under `DAYS_AWAY`, the more severe column, not under
    `RESTRICTED_TRANSFER`."

    Design: Difficulty/dual_variant_calc/osha_column_away_dominates_restricted
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "WELDER", 9000, 0)],
                                               job_category="WELDER")
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "LOST_TIME", days_away=3, days_restricted=5), CLIN))
    assert ic["is_osha_recordable"] is True
    assert ic["osha_column"] == "DAYS_AWAY"


def test_osha_away_dominates_restricted_column_recompute(api):
    """PRD §3.10: "Because precedence is strict, an injury with both at least 1 day away and at
    least 1 day restricted is logged under `DAYS_AWAY`, the more severe column, not under
    `RESTRICTED_TRANSFER`."

    Design: Difficulty/dual_variant_calc/osha_column_away_dominates_restricted
    """
    # A second translation: same precedence, exercised at the boundary days_away=1, days_restricted=1.
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "LOST_TIME", days_away=1, days_restricted=1), CLIN))
    assert ic["osha_column"] == "DAYS_AWAY"
    assert ic["is_osha_recordable"] is True


def test_osha_restricted_duty_treatment_resolves_restricted_transfer(api):
    """PRD §3.10: "otherwise, if `days_restricted` is at least 1 or `treatment_level` is
    `RESTRICTED_DUTY`, the case is recordable and `osha_column` is `RESTRICTED_TRANSFER`".

    Design: Difficulty/combinatorial_formula/osha_precedence_three_input_branch
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "RESTRICTED_DUTY", days_away=0, days_restricted=0), CLIN))
    assert ic["osha_column"] == "RESTRICTED_TRANSFER"
    assert ic["is_osha_recordable"] is True


def test_osha_days_restricted_branch_via_or(api):
    """PRD §3.10: "otherwise, if `days_restricted` is at least 1 or `treatment_level` is
    `RESTRICTED_DUTY`, the case is recordable and `osha_column` is `RESTRICTED_TRANSFER`".

    Design: Difficulty/combinatorial_formula/osha_precedence_three_input_branch
    """
    # The OR branch reached via days_restricted>=1 with a non-restricted treatment_level and zero days_away.
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "MEDICAL_TREATMENT", days_away=0, days_restricted=2), CLIN))
    assert ic["osha_column"] == "RESTRICTED_TRANSFER"
    assert ic["is_osha_recordable"] is True


# ─── Invoice totals & volume discount (PRD §3.13, §2.9) ─

def test_invoice_discount_round_once_then_subtract(api):
    """PRD §3.13: "The `discount_cents` is computed by multiplying `subtotal_cents` by the
    applicable rate and rounding that single product to whole cents using round-half-up; this
    rounding is performed exactly once, never per line item. The `total_cents` is then
    `subtotal_cents` minus `discount_cents` and is never negative."
    PRD §3.13: "if the count is at least 5 but fewer than 10 the rate is five percent".

    Design: Difficulty/combinatorial_formula/invoice_discount_round_once_then_subtract
    """
    # 5 PHYSICAL @ 12345 -> subtotal 61725; 61725*0.05 = 3086.25 -> round_half_up 3086; total 58639.
    emp, wkr, encs = setup_employer_with_n_completed_physicals(5, price_cents=12345,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 61725
    assert inv["discount_cents"] == 3086
    assert inv["total_cents"] == 58639


def test_invoice_discount_round_once_then_subtract_alt_price(api):
    """PRD §3.13: "The `discount_cents` is computed by multiplying `subtotal_cents` by the
    applicable rate and rounding that single product to whole cents using round-half-up; this
    rounding is performed exactly once, never per line item. The `total_cents` is then
    `subtotal_cents` minus `discount_cents` and is never negative."
    PRD §3.13: "if the count is at least 5 but fewer than 10 the rate is five percent".

    Design: Difficulty/combinatorial_formula/invoice_discount_round_once_then_subtract
    """
    # 5 PHYSICAL @ 10101 -> subtotal 50505; 50505*0.05 = 2525.25 -> round_half_up 2525; total 47980.
    # Per-line rounding would give 5*round(505.05)=5*505=2525 here too, so use a price whose
    # single-product rounding diverges: 5 @ 12349 -> subtotal 61745; *0.05 = 3087.25 -> 3087;
    # per-line 5*round(617.45)=5*617=3085 -> total would wrongly be 58660 vs correct 58658.
    emp, wkr, encs = setup_employer_with_n_completed_physicals(5, price_cents=12349,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 61745
    assert inv["discount_cents"] == 3087
    assert inv["total_cents"] == 58658


def test_invoice_count_tier_at_five_boundary(api):
    """PRD §3.13: "if the count is at least 5 but fewer than 10 the rate is five percent".
    PRD §3.13: "A volume discount keyed on the count of selected line items — not on the
    subtotal amount — is then applied."

    Design: Difficulty/boundary_precision_check/invoice_discount_count_tier_at_five
    """
    # Exactly 5 PHYSICAL @ 10000 -> subtotal 50000, discount 2500, total 47500.
    emp, wkr, encs = setup_employer_with_n_completed_physicals(5, price_cents=10000,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 50000
    assert inv["discount_cents"] == 2500
    assert inv["total_cents"] == 47500


def test_invoice_count_tier_at_five_boundary_alt_price(api):
    """PRD §3.13: "if the count is at least 5 but fewer than 10 the rate is five percent".
    PRD §3.13: "A volume discount keyed on the count of selected line items — not on the
    subtotal amount — is then applied."

    Design: Difficulty/boundary_precision_check/invoice_discount_count_tier_at_five
    """
    # Second translation at the n==5 boundary with a different price: 5 @ 20000 -> subtotal
    # 100000, 5% -> discount 5000, total 95000.
    emp, wkr, encs = setup_employer_with_n_completed_physicals(5, price_cents=20000,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 100000
    assert inv["discount_cents"] == 5000
    assert inv["total_cents"] == 95000


def test_invoice_tier_below_five_no_discount(api):
    """PRD §3.13: "If the count is fewer than 5 the discount rate is zero".
    PRD §3.13: "The `total_cents` is then `subtotal_cents` minus `discount_cents` and is never
    negative."

    Design: Corner/calculations/invoice_tier_below_five_no_discount
    """
    # Exactly 4 PHYSICAL @ 10000 -> below TIER1_MIN(5); discount 0, total 40000.
    emp, wkr, encs = setup_employer_with_n_completed_physicals(4, price_cents=10000,
                                                               current_date="2026-03-15")
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 40000
    assert inv["discount_cents"] == 0
    assert inv["total_cents"] == 40000


def test_invoice_input_set_excludes_injury_and_out_of_period(api):
    """PRD §3.13: "Line-item selection includes every encounter for the employer that is
    `COMPLETED`, whose `is_billed` is false, whose `billable_amount_cents` is greater than 0,
    and whose completion date — the date portion of its `updated_at` at the moment it completed —
    falls within the inclusive period from `period_start` to `period_end`."
    PRD §3.9: "On reaching `COMPLETED`, an `INJURY` encounter has its `billable_amount_cents`
    set to 0".

    Design: Corner/calculations/invoice_input_set_excludes_injury_and_out_of_period
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", 9000, 0)], current_date="2026-03-15")
    wkr = create_worker(emp["id"], job_category="OP")
    # One billable PHYSICAL completed.
    ep = create_completed_physical_for_employer(emp["id"], wkr["id"], price_cents=9000)
    # One INJURY completed (billable 0) — created, closed via FULL_DUTY, then completed.
    inj_enc = get_success_data(api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"], "encounter_type": "INJURY"}, CLIN))
    get_success_data(api.check_in_encounter(inj_enc["id"], CLIN))
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(inj_enc["id"], "FIRST_AID", injury_date="2026-03-02",
                                   days_away=0, days_restricted=0), CLIN))
    add_work_status(ic["id"], "FULL_DUTY", "2026-03-05", "2026-03-05")
    get_success_data(api.complete_encounter(inj_enc["id"], CLIN))
    inv = create_draft_invoice(emp["id"])
    assert inv["subtotal_cents"] == 9000
    assert inv["total_cents"] == 9000
    assert ep["id"] in inv["line_item_encounter_ids"]
    assert inj_enc["id"] not in inv["line_item_encounter_ids"]


# ─── Surveillance outcome (PRD §3.12) ─────────────────

def test_surveillance_sts_at_threshold_ten(api):
    """PRD §3.12: "the shift in hearing is the `current_threshold_db` minus the
    `baseline_threshold_db`; if that shift is at least 10 decibels the outcome is `STS` (a
    standard threshold shift)".

    Design: Difficulty/boundary_precision_check/sts_shift_at_threshold_ten
    """
    # baseline 30, current 40 -> shift 10 (== threshold) -> STS.
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="AUDIOMETRIC", job_category="MACHINIST",
        exam_overrides={"baseline_threshold_db": 30, "current_threshold_db": 40})
    ex = get_success_data(api.record_surveillance_exam(ex["id"], CLIN))
    assert ex["outcome"] == "STS"


def test_surveillance_sts_at_threshold_ten_repeat(api):
    """PRD §3.12: "the shift in hearing is the `current_threshold_db` minus the
    `baseline_threshold_db`; if that shift is at least 10 decibels the outcome is `STS` (a
    standard threshold shift)".

    Design: Difficulty/boundary_precision_check/sts_shift_at_threshold_ten
    """
    # Same >= boundary with different absolute values: baseline 25, current 35 -> shift 10 -> STS.
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="AUDIOMETRIC", job_category="MACHINIST",
        exam_overrides={"baseline_threshold_db": 25, "current_threshold_db": 35})
    ex = get_success_data(api.record_surveillance_exam(ex["id"], CLIN))
    assert ex["outcome"] == "STS"


def test_surveillance_sts_below_threshold_is_pass(api):
    """PRD §3.12: "if that shift is at least 10 decibels the outcome is `STS` (a standard
    threshold shift), and otherwise — including a zero or negative shift — the outcome is `PASS`."

    Design: Corner/calculations/surveillance_sts_below_threshold_is_pass
    """
    # baseline 30, current 39 -> shift 9 (< threshold) -> PASS.
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="AUDIOMETRIC", job_category="MACHINIST",
        exam_overrides={"baseline_threshold_db": 30, "current_threshold_db": 39})
    ex = get_success_data(api.record_surveillance_exam(ex["id"], CLIN))
    assert ex["outcome"] == "PASS"


def test_surveillance_respirator_full_facepiece_fail_below_threshold(api):
    """PRD §3.12: "a `FULL_FACEPIECE` requires a fit factor of at least 500; if the measured
    `fit_factor` meets or exceeds the required minimum the outcome is `PASS`, and otherwise it
    is `FAIL`."

    Design: Corner/calculations/surveillance_respirator_full_facepiece_fail_below_threshold
    """
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="RESPIRATOR_FIT", job_category="WELDER", price_cents=4000,
        exam_overrides={"fit_factor": 499, "respirator_class": "FULL_FACEPIECE"})
    ex = get_success_data(api.record_surveillance_exam(ex["id"], CLIN))
    assert ex["outcome"] == "FAIL"


# ─── Encounter billing snapshot pricing (PRD §3.9) ────

def test_billable_uses_snapshot_not_current_protocol_price(api):
    """PRD §3.9: "If the employer activated a newer protocol that re-priced the same panel code
    after this encounter was scheduled, the encounter still bills at the snapshotted price; the
    snapshotted and current prices may legitimately diverge for the same `panel_code`."

    Design: Difficulty/dual_variant_calc/billable_snapshot_vs_current_protocol_price
    """
    emp, p1 = setup_employer_with_active_protocol(
        panels=[panel("DRUG_NON_DOT", "DRIVER", 12000, 0)],
        dot_regulated=False, mro_user_id="mro-1", legal_name="Acme")
    wkr = create_worker(emp["id"], job_category="DRIVER")
    # Schedule the drug-screen encounter (snapshots P1 @ 12000).
    enc = get_success_data(api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "DRUG_SCREEN", "panel_code": "DRUG_NON_DOT"},
        make_clinician_headers("clin-1")))
    # Activate a NEW protocol P2 that re-prices the same panel at 20000.
    emp_now = get_success_data(api.get_employer(emp["id"], ADMIN))
    p2 = get_success_data(api.create_protocol(
        {"employer_id": emp["id"], "effective_date": "2026-02-01",
         "panels": [panel("DRUG_NON_DOT", "DRIVER", 20000, 0)]}, ADMIN))
    get_success_data(api.activate_protocol(
        p2["id"], {"expected_employer_version": emp_now["version"]}, ADMIN))
    # Run the screen to VERIFIED and issue a FIT clearance.
    get_success_data(api.check_in_encounter(enc["id"], make_clinician_headers("clin-1")))
    ds = get_success_data(api.create_drug_screen(
        create_drug_screen_payload(enc["id"], specimen_seal_intact=True),
        make_clinician_headers("clin-1")))
    advance_drug_screen_to_at_lab(ds["id"])
    advance_drug_screen_to_lab_reported(ds["id"], lab_result="NEGATIVE", clinician_id="clin-1")
    advance_drug_screen_to_mro_review(ds["id"], mro_user_id="mro-1")
    get_success_data(api.mro_verify(ds["id"], {"mro_verified_result": "NEGATIVE"},
                                    make_mro_headers("mro-1")))
    issue_clearance(enc["id"], "FIT", clinician_id="clin-1")
    completed = get_success_data(api.complete_encounter(enc["id"], make_clinician_headers("clin-1")))
    assert completed["billable_amount_cents"] == 12000
    assert completed["protocol_id"] == p1["id"]
    assert completed["status"] == "COMPLETED"


def test_billable_snapshot_independent_of_later_activation_second(api):
    """PRD §3.9: "The snapshotted `protocol_id` is authoritative here — not the employer's
    current active protocol."

    Design: Difficulty/dual_variant_calc/billable_snapshot_vs_current_protocol_price
    """
    # Second translation on the PHYSICAL panel: snapshot 9000 stays despite a re-price to 30000.
    emp, p1 = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", 9000, 0)], legal_name="Snap Co")
    wkr = create_worker(emp["id"], job_category="OP")
    enc = get_success_data(api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "PHYSICAL", "panel_code": "PHYSICAL"},
        make_clinician_headers("clin-1")))
    emp_now = get_success_data(api.get_employer(emp["id"], ADMIN))
    p2 = get_success_data(api.create_protocol(
        {"employer_id": emp["id"], "effective_date": "2026-02-01",
         "panels": [panel("PHYSICAL", "OP", 30000, 0)]}, ADMIN))
    get_success_data(api.activate_protocol(
        p2["id"], {"expected_employer_version": emp_now["version"]}, ADMIN))
    get_success_data(api.check_in_encounter(enc["id"], make_clinician_headers("clin-1")))
    issue_clearance(enc["id"], "FIT", clinician_id="clin-1")
    completed = get_success_data(api.complete_encounter(enc["id"], make_clinician_headers("clin-1")))
    assert completed["billable_amount_cents"] == 9000
    assert completed["protocol_id"] == p1["id"]
