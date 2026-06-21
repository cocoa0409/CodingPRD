"""Non-linear state cycles, branching, transitive cascades, and compensating
invariants. (Difficulty queue: non_linear_state_machine, transitive_cascade,
compensating_invariant.)
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    api_client, TEST_USERS,
    create_appeal_payload, create_sba_referral_payload, create_dob_record_payload,
    setup_approved_case, setup_approved_case_with_two_caseworkers,
    get_line_item, disburse, current_case_version,
    assert_obligation_invariant,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ─── non_linear_state_machine / ihp_case_appeal_cycle_back_to_award_approved ─
def test_appeal_grant_cycles_case_back_to_award_approved(api):
    """PRD §3.10: "A **granted** appeal advances the appeal `SUBMITTED → GRANTED` and
    the case `UNDER_APPEAL → AWARD_APPROVED` regardless of what `pre_appeal_status`
    held."
    PRD §3.10: "An appeal may be filed only against a case that is `AWARD_APPROVED` or
    `DENIED` (otherwise `ERR_CASE_NOT_APPEALABLE`), and the `expected_ihp_case_version`
    must match the case's current `version` (otherwise `ERR_STALE_CASE_VERSION`)."

    Approve (total 1,540,000) -> file appeal -> UNDER_APPEAL -> grant -> the case
    re-enters AWARD_APPROVED, closing the cycle.

    Design: Difficulty/non_linear_state_machine/ihp_case_appeal_cycle_back_to_award_approved
    """
    ctx = setup_approved_case_with_two_caseworkers(
        clock="2026-02-14T00:00:00Z",
        decl_overrides={"title": "DR-D"},
        inspector_badge="INS-D", cw1_employee_id="CW-D1", cw2_employee_id="CW-D2",
        applicant_overrides={
            "household_name": "Delta Household", "household_size": 4,
            "annual_income_cents": 3_500_000, "damage_date": "2026-01-18T00:00:00Z",
            "reported_repair_cost_cents": 900_000,
            "reported_personal_property_cents": 400_000,
            "reported_rental_months": 2,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 900_000,
            "verified_personal_property_cents": 400_000,
            "verified_rental_months": 2,
        },
        monthly_fmr_cents=120_000,
    )
    case_id = ctx["case"]["id"]
    case_v = ctx["case"]["version"]
    appeal = get_success_data(api_client.create_appeal(
        create_appeal_payload(case_id, case_v, reason="verified repair underestimated",
                              requested_repair_cost_cents=1_500_000),
        ctx["cw1_headers"],
    ))
    decided = validate_success(api_client.decide_appeal(
        appeal["id"], {"outcome": "GRANTED"}, ctx["cw2_headers"]))
    assert decided["status"] == "GRANTED", decided["status"]
    # The case re-enters AWARD_APPROVED, closing the appeal cycle.
    case = get_success_data(api_client.get_ihp_case(case_id, ctx["cw2_headers"]))
    assert case["status"] == "AWARD_APPROVED", case["status"]


def test_appeal_grant_raises_total_approved_via_override(api):
    """PRD §3.10: "The award is recomputed in the final variant, but with the appeal's
    `requested_repair_cost_cents` substituted for the inspector-verified repair cost
    where the appellant supplied one; `gross_eligible_cents`, `capped_eligible_cents`,
    and `net_eligible_cents` are recomputed, the line items are re-approved through the
    cap-and-offset waterfall of §3.6, and `total_approved_cents` is reconciled."

    Original total 1,540,000 (repair 900,000 + rental 240,000 + personal 400,000);
    appeal override repair 1,500,000 raises total to 2,140,000.

    Design: Difficulty/non_linear_state_machine/ihp_case_appeal_cycle_back_to_award_approved
    """
    ctx = setup_approved_case_with_two_caseworkers(
        clock="2026-02-14T00:00:00Z",
        decl_overrides={"title": "DR-D"},
        inspector_badge="INS-Db", cw1_employee_id="CW-D1b", cw2_employee_id="CW-D2b",
        applicant_overrides={
            "household_name": "Delta Household", "household_size": 4,
            "annual_income_cents": 3_500_000, "damage_date": "2026-01-18T00:00:00Z",
            "reported_repair_cost_cents": 900_000,
            "reported_personal_property_cents": 400_000,
            "reported_rental_months": 2,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 900_000,
            "verified_personal_property_cents": 400_000,
            "verified_rental_months": 2,
        },
        monthly_fmr_cents=120_000,
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["total_approved_cents"] == 1_540_000, ctx["case"]["total_approved_cents"]
    appeal = get_success_data(api_client.create_appeal(
        create_appeal_payload(case_id, ctx["case"]["version"], reason="underestimated",
                              requested_repair_cost_cents=1_500_000),
        ctx["cw1_headers"],
    ))
    get_success_data(api_client.decide_appeal(appeal["id"], {"outcome": "GRANTED"}, ctx["cw2_headers"]))
    case = get_success_data(api_client.get_ihp_case(case_id, ctx["cw2_headers"]))
    assert case["total_approved_cents"] == 2_140_000, case["total_approved_cents"]


# ─── non_linear_state_machine / sba_referral_branching_divergent_side_effects ─
def _approved_case_for_sba(badge, cw, **app):
    return setup_approved_case(
        clock="2026-02-16T00:00:00Z",
        decl_overrides={"title": "DR-SBA"},
        inspector_badge=badge, cw_employee_id=cw,
        applicant_overrides=app,
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 2_000_000,
            "verified_personal_property_cents": 1_500_000,
            "verified_rental_months": 0,
        },
        monthly_fmr_cents=100_000,
    )


def test_sba_approved_branch_creates_sba_loan_dob(api):
    """PRD §3.7: "An approved outcome advances the referral `REFERRED → SBA_APPROVED`
    and triggers a three-hop cascade. First, an `SBA_LOAN` `DobRecord` is created on
    the applicant for the `sba_loan_amount_cents` SBA approved."

    SBA APPROVED with loan 600,000 creates an SBA_LOAN DobRecord and raises
    total_dob_cents to 600,000.

    Design: Difficulty/non_linear_state_machine/sba_referral_branching_divergent_side_effects
    """
    app = {"household_name": "Sigma Household", "household_size": 2,
           "annual_income_cents": 9_000_000, "damage_date": "2026-01-25T00:00:00Z",
           "reported_repair_cost_cents": 2_000_000,
           "reported_personal_property_cents": 1_500_000, "reported_rental_months": 0}
    ctx = _approved_case_for_sba("INS-SBA", "CW-SBA", **app)
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    ref = get_success_data(api_client.create_sba_referral(
        create_sba_referral_payload(ctx["case"]["id"]), cw_h))
    decided = validate_success(api_client.record_sba_outcome(
        ref["id"], {"outcome": "APPROVED", "sba_loan_amount_cents": 600_000}, cw_h))
    assert decided["status"] == "SBA_APPROVED", decided["status"]
    dobs, _ = validate_paginated(api_client.list_dob_records(
        cw_h, params={"applicant_id": app_id, "source_type": "SBA_LOAN"}))
    assert len(dobs) == 1, f"Expected one SBA_LOAN DOB, got {len(dobs)}"
    assert dobs[0]["amount_cents"] == 600_000, dobs[0]["amount_cents"]
    applicant = get_success_data(api_client.get_applicant(app_id, cw_h))
    assert applicant["total_dob_cents"] == 600_000, applicant["total_dob_cents"]


def test_sba_declined_branch_creates_no_dob(api):
    """PRD §3.7: "A declined outcome advances the referral `REFERRED → SBA_DECLINED`
    and has no further effect — no DOB record is created and the household remains
    eligible for its full IHP award; this is the divergent, no-cascade branch."

    The divergent branch: DECLINED produces SBA_DECLINED and leaves total_dob_cents 0.

    Design: Difficulty/non_linear_state_machine/sba_referral_branching_divergent_side_effects
    """
    app = {"household_name": "Sigma2 Household", "household_size": 2,
           "annual_income_cents": 9_000_000, "damage_date": "2026-01-25T00:00:00Z",
           "reported_repair_cost_cents": 2_000_000,
           "reported_personal_property_cents": 1_500_000, "reported_rental_months": 0}
    ctx = _approved_case_for_sba("INS-SBAd", "CW-SBAd", **app)
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    ref = get_success_data(api_client.create_sba_referral(
        create_sba_referral_payload(ctx["case"]["id"]), cw_h))
    decided = validate_success(api_client.record_sba_outcome(
        ref["id"], {"outcome": "DECLINED"}, cw_h))
    assert decided["status"] == "SBA_DECLINED", decided["status"]
    dobs, meta = validate_paginated(api_client.list_dob_records(
        cw_h, params={"applicant_id": app_id}))
    assert meta["total_count"] == 0, f"DECLINED branch must create no DOB, got {meta['total_count']}"
    applicant = get_success_data(api_client.get_applicant(app_id, cw_h))
    assert applicant["total_dob_cents"] == 0, applicant["total_dob_cents"]


# ─── transitive_cascade / sba_approval_three_hop_to_recoupment ─────────────
def _disbursed_case_with_pre_approval_dob(badge, cw):
    """Approved+fully-disbursed case: gross 1,800,000, at-award INSURANCE DOB 400,000
    (pre-approve) => net 1,400,000, disbursed 1,400,000 (REPAIR 900,000 + PERSONAL
    500,000). Returns ctx with case, applicant, caseworker_headers.
    """
    from test_helpers import setup_verified_assessment, create_ihp_case_payload
    ctx = setup_verified_assessment(
        clock="2026-02-05T00:00:00Z",
        decl_overrides={"title": "DR-CASC"},
        inspector_badge=badge, cw_employee_id=cw,
        applicant_overrides={
            "household_name": "Cascade Household", "household_size": 3,
            "annual_income_cents": 3_000_000, "damage_date": "2026-01-20T00:00:00Z",
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        scheduled_start="2026-02-06T09:00:00Z", scheduled_end="2026-02-06T10:00:00Z",
    )
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    get_success_data(api_client.create_dob_record(
        create_dob_record_payload(app_id, source_type="INSURANCE",
                                  amount_cents=400_000, received_at="2026-02-05T00:00:00Z"), ADMIN))
    case = get_success_data(api_client.create_ihp_case(
        create_ihp_case_payload(app_id, ctx["assessment"]["id"], monthly_fmr_cents=100_000), cw_h))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, ADMIN))
    case = get_success_data(api_client.approve_ihp_case(case["id"], cw_h))
    case_id = case["id"]
    v = case["version"]
    repair_li = get_line_item(case_id, "REPAIR_ASSISTANCE", cw_h)
    disburse(case_id, repair_li["id"], v, 900_000, cw_h)
    v = current_case_version(case_id, cw_h)
    pp_li = get_line_item(case_id, "PERSONAL_PROPERTY", cw_h)
    disburse(case_id, pp_li["id"], v, 500_000, cw_h)
    ctx["case"] = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    return ctx


def test_sba_approval_three_hop_establishes_late_dob_recoupment(api):
    """PRD §3.7: "Third, if the case's `disbursed_total_cents` now exceeds the freshly
    recomputed `net_eligible_cents`, a `LATE_DOB` `Recoupment` is established for the
    overpayment."
    PRD §3.9: "At establishment, the debt is the larger of zero and the case's
    `disbursed_total_cents` minus its freshly recomputed `net_eligible_cents` — where
    "freshly recomputed" means after the triggering cascade has run (the at-recoupment
    DOB variant for SBA-driven and late-DOB-driven recoupments, and the appeal-override
    final award for appeal reductions)."

    SBA APPROVED loan 600,000 drops net to 800,000 while disbursed is 1,400,000 =>
    a LATE_DOB Recoupment of debt 600,000 is auto-established.

    Design: Difficulty/transitive_cascade/sba_approval_three_hop_to_recoupment
    """
    ctx = _disbursed_case_with_pre_approval_dob("INS-CASC", "CW-CASC")
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    ref = get_success_data(api_client.create_sba_referral(
        create_sba_referral_payload(case_id), cw_h))
    get_success_data(api_client.record_sba_outcome(
        ref["id"], {"outcome": "APPROVED", "sba_loan_amount_cents": 600_000}, cw_h))
    recoups, _ = validate_paginated(api_client.list_recoupments(
        ADMIN, params={"ihp_case_id": case_id, "origin": "LATE_DOB"}))
    assert len(recoups) == 1, f"Expected one LATE_DOB recoupment, got {len(recoups)}"
    assert recoups[0]["origin"] == "LATE_DOB", recoups[0]["origin"]
    assert recoups[0]["debt_amount_cents"] == 600_000, recoups[0]["debt_amount_cents"]


def test_sba_approval_cascade_lowers_net_eligible(api):
    """PRD §3.7: "Second, the applicant's `total_dob_cents` is recomputed and, because
    an SBA loan is by nature a late-arriving duplication, the case's `dob_offset_cents`
    and `net_eligible_cents` are recomputed in the at-recoupment variant."

    After the SBA loan cascade, net_eligible_cents drops to 800,000 (capped 1,800,000
    minus total at-recoupment offset 1,000,000).

    Design: Difficulty/transitive_cascade/sba_approval_three_hop_to_recoupment
    """
    ctx = _disbursed_case_with_pre_approval_dob("INS-CASCb", "CW-CASCb")
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    ref = get_success_data(api_client.create_sba_referral(
        create_sba_referral_payload(case_id), cw_h))
    get_success_data(api_client.record_sba_outcome(
        ref["id"], {"outcome": "APPROVED", "sba_loan_amount_cents": 600_000}, cw_h))
    case = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    assert case["net_eligible_cents"] == 800_000, case["net_eligible_cents"]



# ─── compensating_invariant / disbursement_void_preserves_obligation_total ──
def _approved_case_two_repair_disbursements(badge, cw):
    """Approved case total 1,540,000, disbursed 500,000 then 600,000 (both REPAIR)
    => disbursed 1,100,000, remaining 440,000. Returns ctx + disb2 id.
    """
    ctx = setup_approved_case(
        clock="2026-02-14T00:00:00Z",
        decl_overrides={"title": "DR-INV1"},
        inspector_badge=badge, cw_employee_id=cw,
        applicant_overrides={
            "household_name": "Inv1 Household", "household_size": 4,
            "annual_income_cents": 3_500_000, "damage_date": "2026-01-18T00:00:00Z",
            "reported_repair_cost_cents": 900_000,
            "reported_personal_property_cents": 400_000, "reported_rental_months": 2,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 900_000,
            "verified_personal_property_cents": 400_000, "verified_rental_months": 2,
        },
        monthly_fmr_cents=120_000,
    )
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    v = ctx["case"]["version"]
    repair_li = get_line_item(case_id, "REPAIR_ASSISTANCE", cw_h)
    disburse(case_id, repair_li["id"], v, 500_000, cw_h)
    v = current_case_version(case_id, cw_h)
    disb2 = disburse(case_id, repair_li["id"], v, 600_000, cw_h)
    ctx["disb2_id"] = disb2["id"]
    return ctx


def test_void_disbursement_restores_disbursed_and_remaining(api):
    """PRD §3.8: "A `ProgramAdmin` may void a `PAID` disbursement, moving it
    `PAID → VOIDED`; this requires the disbursement to be `PAID` (otherwise
    `ERR_DISBURSEMENT_NOT_PAID`). Voiding is a compensating action: it subtracts the
    voided amount from `disbursed_total_cents` and recomputes `remaining_obligation_cents`,
    so the obligation invariant of §2.9 is preserved."

    Voiding the 600,000 disbursement returns disbursed to 500,000 and remaining to
    1,040,000.

    Design: Difficulty/compensating_invariant/disbursement_void_preserves_obligation_total
    """
    ctx = _approved_case_two_repair_disbursements("INS-INV1", "CW-INV1")
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    get_success_data(api_client.void_disbursement(ctx["disb2_id"], ADMIN))
    case = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    assert case["disbursed_total_cents"] == 500_000, case["disbursed_total_cents"]
    assert case["remaining_obligation_cents"] == 1_040_000, case["remaining_obligation_cents"]


def test_void_disbursement_preserves_obligation_invariant(api):
    """PRD §2.9: "the remaining obligation is always the approved total minus what has
    already been paid: `disbursed_total_cents` plus `remaining_obligation_cents` always
    equals `total_approved_cents`."

    After the void, total_approved is unchanged (1,540,000) and the obligation
    invariant still holds.

    Design: Difficulty/compensating_invariant/disbursement_void_preserves_obligation_total
    """
    ctx = _approved_case_two_repair_disbursements("INS-INV1b", "CW-INV1b")
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    get_success_data(api_client.void_disbursement(ctx["disb2_id"], ADMIN))
    case = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    assert case["total_approved_cents"] == 1_540_000, case["total_approved_cents"]
    assert_obligation_invariant(case)


# ─── compensating_invariant / dob_reverse_preserves_total_dob_quantity ─────
def _approved_case_with_two_dobs(badge, cw):
    """Approved case for an applicant with a 400,000 INSURANCE DOB; then a second
    600,000 OTHER_FEDERAL DOB is recorded (total_dob peaks at 1,000,000). Returns ctx
    with the second DOB id.
    """
    from test_helpers import setup_verified_assessment, create_ihp_case_payload
    ctx = setup_verified_assessment(
        clock="2026-02-16T00:00:00Z",
        decl_overrides={"title": "DR-INV2"},
        inspector_badge=badge, cw_employee_id=cw,
        applicant_overrides={
            "household_name": "Inv2 Household", "household_size": 2,
            "annual_income_cents": 3_000_000, "damage_date": "2026-01-17T00:00:00Z",
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        scheduled_start="2026-02-17T09:00:00Z", scheduled_end="2026-02-17T10:00:00Z",
    )
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    get_success_data(api_client.create_dob_record(
        create_dob_record_payload(app_id, source_type="INSURANCE",
                                  amount_cents=400_000, received_at="2026-02-16T00:00:00Z"), ADMIN))
    case = get_success_data(api_client.create_ihp_case(
        create_ihp_case_payload(app_id, ctx["assessment"]["id"], monthly_fmr_cents=100_000), cw_h))
    case = get_success_data(api_client.approve_ihp_case(case["id"], cw_h))
    dob2 = get_success_data(api_client.create_dob_record(
        create_dob_record_payload(app_id, source_type="OTHER_FEDERAL",
                                  amount_cents=600_000, received_at="2026-02-16T00:00:00Z"), ADMIN))
    ctx["case"] = case
    ctx["dob2_id"] = dob2["id"]
    return ctx


def test_dob_reverse_restores_total_dob_cents(api):
    """PRD §3.5: "Reversal subtracts that record's `amount_cents` from the applicant's
    `total_dob_cents` — a compensating action that keeps the total honest — and, when
    the linked case is `AWARD_APPROVED` or `DISBURSING`, recomputes the case's
    `dob_offset_cents` and `net_eligible_cents`."
    PRD §2.9: "On the `Applicant`, `total_dob_cents` is the running sum of
    duplication-of-benefits amounts recorded against that household (the precise rule
    appears in §3.5)."

    total_dob peaks at 1,000,000 then returns to 400,000 after reversing the 600,000
    record.

    Design: Difficulty/compensating_invariant/dob_reverse_preserves_total_dob_quantity
    """
    ctx = _approved_case_with_two_dobs("INS-INV2", "CW-INV2")
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    peak = get_success_data(api_client.get_applicant(app_id, cw_h))
    assert peak["total_dob_cents"] == 1_000_000, peak["total_dob_cents"]
    get_success_data(api_client.reverse_dob_record(ctx["dob2_id"], ADMIN))
    after = get_success_data(api_client.get_applicant(app_id, cw_h))
    assert after["total_dob_cents"] == 400_000, after["total_dob_cents"]


def test_dob_reverse_restores_case_dob_offset(api):
    """PRD §3.5: "Reversal subtracts that record's `amount_cents` from the applicant's
    `total_dob_cents` — a compensating action that keeps the total honest — and, when
    the linked case is `AWARD_APPROVED` or `DISBURSING`, recomputes the case's
    `dob_offset_cents` and `net_eligible_cents`."

    The case's dob_offset_cents returns to 400,000 after the reversal (conserved
    quantity unchanged across record + reverse).

    Design: Difficulty/compensating_invariant/dob_reverse_preserves_total_dob_quantity
    """
    ctx = _approved_case_with_two_dobs("INS-INV2b", "CW-INV2b")
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    get_success_data(api_client.reverse_dob_record(ctx["dob2_id"], ADMIN))
    case = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    assert case["dob_offset_cents"] == 400_000, case["dob_offset_cents"]
