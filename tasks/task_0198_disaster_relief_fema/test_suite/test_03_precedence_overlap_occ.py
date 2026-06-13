"""Validation precedence pairs, cross-entity state dependencies, resource temporal
overlap geometries, the SBA threshold boundary, and optimistic concurrency.
(Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, boundary SBA instance, occ_stale_version.)
"""
from test_helpers import (
    validate_error, get_success_data, api_client, TEST_USERS, ApiErrorId,
    create_assessment_payload, create_appeal_payload, create_sba_referral_payload,
    create_disbursement_payload, create_rental_period_payload, create_ihp_case_payload,
    setup_program, setup_scheduled_assessment, setup_verified_assessment,
    setup_pending_case, setup_approved_case, setup_approved_case_with_two_caseworkers,
    get_line_item, disburse, current_case_version,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_disbursement ─
def test_state_check_beats_fiscal_on_disbursement(api):
    """PRD §3.8: "The order in which these guards fire on a disbursement matters.
    Authentication is checked first, then role authorization, then existence of the
    path and body identifiers, then the case's state precondition, then that the line
    item is approved and on the right case, then the segregation and concurrency checks
    where applicable, then the optimistic-concurrency version match, and finally the
    fiscal ceiling against the remaining obligation."
    PRD §3.8: "The first disbursement on a case requires the case to be
    `AWARD_APPROVED` (otherwise `ERR_CASE_NOT_APPROVED`) and advances it
    `AWARD_APPROVED → DISBURSING`."

    A disbursement on an ELIGIBILITY_PENDING case with an amount that also exceeds
    obligation fails BOTH the state check and the fiscal ceiling; because state
    precedes fiscal, the state error ERR_CASE_NOT_APPROVED wins. The line_item_id is a
    real PENDING line item on the case so the (earlier) existence check passes and the
    contest is genuinely state-vs-fiscal.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursement
    """
    ctx = setup_pending_case(
        clock="2026-02-20T00:00:00Z",
        decl_overrides={"title": "DR-PC1"},
        inspector_badge="INS-PC1", cw_employee_id="CW-PC1",
        applicant_overrides={
            "household_name": "PC1 Household", "household_size": 2,
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    line_item = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    resp = api_client.create_disbursement(
        create_disbursement_payload(case["id"], line_item["id"], case["version"], amount_cents=99_999_999),
        cw_h,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_APPROVED.value)


def test_state_beats_fiscal_leaves_case_undisbursed(api):
    """PRD §3.8: "The first disbursement on a case requires the case to be
    `AWARD_APPROVED` (otherwise `ERR_CASE_NOT_APPROVED`) and advances it
    `AWARD_APPROVED → DISBURSING`."
    PRD §3.8: "On success the disbursement is recorded `PAID`, the case's
    `disbursed_total_cents` increases by the paid amount, `remaining_obligation_cents`
    is recomputed, and the case's `version` increments by one."

    When the state check ERR_CASE_NOT_APPROVED fires (priority above the fiscal gate),
    no disbursement side effect runs: the ELIGIBILITY_PENDING case stays with
    disbursed_total_cents 0. The line_item_id is a real PENDING line item so the
    earlier existence check passes and the state error is the operative failure.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursement
    """
    ctx = setup_pending_case(
        clock="2026-02-20T00:00:00Z",
        decl_overrides={"title": "DR-PC1b"},
        inspector_badge="INS-PC1b", cw_employee_id="CW-PC1b",
        applicant_overrides={
            "household_name": "PC1b Household", "household_size": 2,
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    line_item = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    resp = api_client.create_disbursement(
        create_disbursement_payload(case["id"], line_item["id"], case["version"], amount_cents=99_999_999),
        cw_h,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_APPROVED.value)
    refreshed = get_success_data(api_client.get_ihp_case(case["id"], cw_h))
    assert refreshed["disbursed_total_cents"] == 0, refreshed["disbursed_total_cents"]



# ─── cross_entity_state_dependency / case_create_requires_assessment_verified ─
def test_case_create_requires_assessment_verified(api):
    """PRD §3.3: "The applicant must be `INSPECTED` (otherwise `ERR_APPLICANT_NOT_INSPECTED`)
    and the referenced assessment must be `VERIFIED` (otherwise `ERR_ASSESSMENT_NOT_VERIFIED`)."

    Opening an IHP case against an only-INSPECTED (not yet VERIFIED) assessment is
    rejected with ERR_ASSESSMENT_NOT_VERIFIED.

    Design: Difficulty/cross_entity_state_dependency/case_create_requires_assessment_verified
    """
    ctx = setup_scheduled_assessment(
        clock="2026-02-10T00:00:00Z",
        decl_overrides={"title": "DR-CE1"},
        inspector_badge="INS-CE1", cw_employee_id="CW-CE1",
        applicant_overrides={"household_name": "CE1 Household"},
    )
    insp_h = ctx["inspector_headers"]
    cw_h = ctx["caseworker_headers"]
    from test_helpers import inspect_assessment_payload
    # Inspect (so applicant becomes INSPECTED) but do NOT verify.
    get_success_data(api_client.inspect_assessment(
        ctx["assessment"]["id"],
        inspect_assessment_payload(habitability="UNINHABITABLE",
                                   verified_repair_cost_cents=1_000_000,
                                   verified_personal_property_cents=500_000,
                                   verified_rental_months=3),
        insp_h,
    ))
    resp = api_client.create_ihp_case(
        create_ihp_case_payload(ctx["applicant"]["id"], ctx["assessment"]["id"], monthly_fmr_cents=100_000),
        cw_h,
    )
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_VERIFIED.value)


def test_case_create_succeeds_once_assessment_verified(api):
    """PRD §3.2: "Only a `VERIFIED` assessment may seed an IHP case."
    PRD §3.3: "On creation the applicant advances `INSPECTED → ELIGIBILITY_PENDING`."

    The affirmative side of the cross-entity precondition: once the assessment is
    VERIFIED, opening the IHP case succeeds (201) and the case is ELIGIBILITY_PENDING.

    Design: Difficulty/cross_entity_state_dependency/case_create_requires_assessment_verified
    """
    ctx = setup_verified_assessment(
        clock="2026-02-10T00:00:00Z",
        decl_overrides={"title": "DR-CE1b"},
        inspector_badge="INS-CE1b", cw_employee_id="CW-CE1b",
        applicant_overrides={"household_name": "CE1b Household"},
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
    )
    cw_h = ctx["caseworker_headers"]
    from test_helpers import validate_success
    data = validate_success(
        api_client.create_ihp_case(
            create_ihp_case_payload(ctx["applicant"]["id"], ctx["assessment"]["id"], monthly_fmr_cents=100_000),
            cw_h),
        expected_status=201,
    )
    assert data["status"] == "ELIGIBILITY_PENDING", data["status"]


# ─── cross_entity_state_dependency / disbursement_blocked_when_declaration_closed ─
def test_disbursement_blocked_when_declaration_closed(api):
    """PRD §3.8: "In every case the declaration must not be `CLOSED` (otherwise
    `ERR_DECLARATION_CLOSED`)."
    PRD §3.1: "Once a declaration is `CLOSED`, disbursement creation against its cases
    is blocked."

    A disbursement on an AWARD_APPROVED case whose declaration has been closed
    (OPEN -> REGISTRATION_CLOSED -> CLOSED) is rejected ERR_DECLARATION_CLOSED.

    Design: Difficulty/cross_entity_state_dependency/disbursement_blocked_when_declaration_closed
    """
    ctx = setup_approved_case(
        clock="2026-02-12T00:00:00Z",
        decl_overrides={"title": "DR-CE2"},
        inspector_badge="INS-CE2", cw_employee_id="CW-CE2",
        applicant_overrides={
            "household_name": "CE2 Household",
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    decl_id = ctx["decl"]["id"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    # Close the declaration (case never reached DISBURSING, so close is permitted).
    get_success_data(api_client.close_registration(decl_id, ADMIN))
    get_success_data(api_client.close_declaration(decl_id, ADMIN))
    resp = api_client.create_disbursement(
        create_disbursement_payload(case["id"], repair_li["id"], case["version"], amount_cents=100_000),
        cw_h,
    )
    validate_error(resp, ApiErrorId.ERR_DECLARATION_CLOSED.value)


def test_disbursement_allowed_when_declaration_not_closed(api):
    """PRD §3.8: "In every case the declaration must not be `CLOSED` (otherwise
    `ERR_DECLARATION_CLOSED`)."
    PRD §3.8: "On success the disbursement is recorded `PAID`, the case's
    `disbursed_total_cents` increases by the paid amount, `remaining_obligation_cents`
    is recomputed, and the case's `version` increments by one."

    The affirmative side of the cross-entity gate: with the declaration still OPEN, a
    disbursement on the AWARD_APPROVED case succeeds (201, PAID).

    Design: Difficulty/cross_entity_state_dependency/disbursement_blocked_when_declaration_closed
    """
    ctx = setup_approved_case(
        clock="2026-02-12T00:00:00Z",
        decl_overrides={"title": "DR-CE2b"},
        inspector_badge="INS-CE2b", cw_employee_id="CW-CE2b",
        applicant_overrides={
            "household_name": "CE2b Household",
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    from test_helpers import validate_success
    data = validate_success(
        api_client.create_disbursement(
            create_disbursement_payload(case["id"], repair_li["id"], case["version"], amount_cents=100_000),
            cw_h),
        expected_status=201,
    )
    assert data["disb_status"] == "PAID", data["disb_status"]


# ─── resource_temporal_overlap / inspector_calendar_closed_interval_plus_buffer ─
def test_inspector_double_booked_within_travel_buffer(api):
    """PRD §3.2: "The geometry is a closed interval widened by the inspector's
    `travel_buffer_minutes` on both sides: the two appointments collide when the new
    appointment's `scheduled_start` is at or before the other appointment's
    `scheduled_end` plus the buffer, and simultaneously the other appointment's
    `scheduled_start` is at or before the new appointment's `scheduled_end` plus the
    buffer."
    PRD §3.2: "A collision is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Appt 09:00-10:00 then a second appt 10:15-11:00 starts only 15 min later
    (< 30-min buffer) => ERR_INSPECTOR_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/inspector_calendar_closed_interval_plus_buffer
    """
    ctx = setup_program(
        clock="2026-02-10T00:00:00Z",
        decl_overrides={"title": "DR-TO1"},
        inspector_badge="INS-TO1", cw_employee_id="CW-TO1",
    )
    # Inspector with explicit 30-min buffer.
    from test_helpers import create_inspector_payload, make_inspector_headers, create_applicant_payload
    insp = get_success_data(api_client.create_inspector(
        create_inspector_payload(full_name="Iris TO1", badge_number="INS-TO1b", travel_buffer_minutes=30), ADMIN))
    insp_h = make_inspector_headers(insp["id"])
    cw_h = ctx["caseworker_headers"]
    app_a = get_success_data(api_client.create_applicant(
        create_applicant_payload(ctx["decl"]["id"], household_name="TO1 A"), cw_h))
    app_b = get_success_data(api_client.create_applicant(
        create_applicant_payload(ctx["decl"]["id"], household_name="TO1 B",
                                 damage_date="2026-01-16T00:00:00Z"), cw_h))
    get_success_data(api_client.create_assessment(
        create_assessment_payload(app_a["id"], insp["id"],
                                  scheduled_start="2026-02-11T09:00:00Z",
                                  scheduled_end="2026-02-11T10:00:00Z"), insp_h))
    resp = api_client.create_assessment(
        create_assessment_payload(app_b["id"], insp["id"],
                                  scheduled_start="2026-02-11T10:15:00Z",
                                  scheduled_end="2026-02-11T11:00:00Z"), insp_h)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


def test_inspector_appointment_outside_buffer_succeeds(api):
    """PRD §3.2: "The geometry is a closed interval widened by the inspector's
    `travel_buffer_minutes` on both sides: the two appointments collide when the new
    appointment's `scheduled_start` is at or before the other appointment's
    `scheduled_end` plus the buffer, and simultaneously the other appointment's
    `scheduled_start` is at or before the new appointment's `scheduled_end` plus the
    buffer."
    PRD §3.2: "Because the buffer is added to both ends and the comparison is inclusive,
    appointments that merely touch — or that fall within the buffer of one another — do
    collide."

    A second appointment starting 31 min after the first ends (just past the 30-min
    buffer) does NOT collide and is scheduled (201).

    Design: Difficulty/resource_temporal_overlap/inspector_calendar_closed_interval_plus_buffer
    """
    ctx = setup_program(
        clock="2026-02-10T00:00:00Z",
        decl_overrides={"title": "DR-TO1b"},
        inspector_badge="INS-TO1c", cw_employee_id="CW-TO1b",
    )
    from test_helpers import create_inspector_payload, make_inspector_headers, create_applicant_payload, validate_success
    insp = get_success_data(api_client.create_inspector(
        create_inspector_payload(full_name="Iris TO1b", badge_number="INS-TO1d", travel_buffer_minutes=30), ADMIN))
    insp_h = make_inspector_headers(insp["id"])
    cw_h = ctx["caseworker_headers"]
    app_a = get_success_data(api_client.create_applicant(
        create_applicant_payload(ctx["decl"]["id"], household_name="TO1b A"), cw_h))
    app_b = get_success_data(api_client.create_applicant(
        create_applicant_payload(ctx["decl"]["id"], household_name="TO1b B",
                                 damage_date="2026-01-16T00:00:00Z"), cw_h))
    get_success_data(api_client.create_assessment(
        create_assessment_payload(app_a["id"], insp["id"],
                                  scheduled_start="2026-02-11T09:00:00Z",
                                  scheduled_end="2026-02-11T10:00:00Z"), insp_h))
    # New appt starts 10:31 (gap 31 min > 30-min buffer) => no collision.
    data = validate_success(
        api_client.create_assessment(
            create_assessment_payload(app_b["id"], insp["id"],
                                      scheduled_start="2026-02-11T10:31:00Z",
                                      scheduled_end="2026-02-11T11:30:00Z"), insp_h),
        expected_status=201,
    )
    assert data["status"] == "SCHEDULED", data["status"]


# ─── resource_temporal_overlap / rental_coverage_half_open_no_buffer ───────
def test_rental_period_overlap_half_open(api):
    """PRD §3.11: "Here the interval is half-open and there is no buffer: a new period
    collides with another `ACTIVE` period of the *same* applicant when the new period's
    `period_start` is strictly before the other period's `period_end` and the other
    period's `period_start` is strictly before the new period's `period_end`."
    PRD §3.11: "A genuine overlap is rejected with `ERR_RENTAL_PERIOD_OVERLAP`."

    ACTIVE period 03-01..04-01 plus a new 03-15..05-01 overlaps =>
    ERR_RENTAL_PERIOD_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/rental_coverage_half_open_no_buffer
    """
    ctx = setup_approved_case(
        clock="2026-02-12T00:00:00Z",
        decl_overrides={"title": "DR-TO2"},
        inspector_badge="INS-TO2", cw_employee_id="CW-TO2",
        applicant_overrides={
            "household_name": "TO2 Household", "household_size": 3,
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    get_success_data(api_client.create_rental_period(
        create_rental_period_payload(case_id, period_start="2026-03-01T00:00:00Z",
                                     period_end="2026-04-01T00:00:00Z"), cw_h))
    resp = api_client.create_rental_period(
        create_rental_period_payload(case_id, period_start="2026-03-15T00:00:00Z",
                                     period_end="2026-05-01T00:00:00Z"), cw_h)
    validate_error(resp, ApiErrorId.ERR_RENTAL_PERIOD_OVERLAP.value)


def test_rental_period_exactly_adjacent_does_not_collide(api):
    """PRD §3.11: "Because both comparisons are strict and the end is exclusive, two
    periods that are exactly adjacent — where one's `period_end` equals the next one's
    `period_start` — do not collide."
    PRD §3.11: "On creation the period is born `ACTIVE`, and its `applicant_id` is
    copied from the funding case so the period attaches to the household whose rental
    timeline it occupies".

    An ACTIVE period 03-01..04-01 plus a new 04-01..05-01 (period_end == period_start)
    do NOT collide; the second period is created ACTIVE.

    Design: Difficulty/resource_temporal_overlap/rental_coverage_half_open_no_buffer
    """
    ctx = setup_approved_case(
        clock="2026-02-12T00:00:00Z",
        decl_overrides={"title": "DR-TO2b"},
        inspector_badge="INS-TO2b", cw_employee_id="CW-TO2b",
        applicant_overrides={
            "household_name": "TO2b Household", "household_size": 3,
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    get_success_data(api_client.create_rental_period(
        create_rental_period_payload(case_id, period_start="2026-03-01T00:00:00Z",
                                     period_end="2026-04-01T00:00:00Z"), cw_h))
    from test_helpers import validate_success
    data = validate_success(
        api_client.create_rental_period(
            create_rental_period_payload(case_id, period_start="2026-04-01T00:00:00Z",
                                         period_end="2026-05-01T00:00:00Z"), cw_h),
        expected_status=201,
    )
    assert data["status"] == "ACTIVE", data["status"]


# ─── boundary_precision_check / sba_income_ceiling_inclusive_loss_threshold_strict ─
def test_sba_loss_threshold_exact_does_not_qualify(api):
    """PRD §3.7: "The boundaries are exact: an income exactly equal to the $75,000
    ceiling qualifies (the comparison is at-or-below), while a verified loss exactly
    equal to the $30,000 threshold does *not* qualify (the comparison is strictly
    greater)."
    PRD §3.7: "When neither condition holds — income above the ceiling and verified
    loss at or below the threshold — the referral is rejected with `ERR_SBA_NOT_ELIGIBLE`."

    Income 8,000,000 (> ceiling) AND verified loss EXACTLY 3,000,000 (== threshold,
    not > ) => ERR_SBA_NOT_ELIGIBLE.

    Design: Difficulty/boundary_precision_check/sba_income_ceiling_inclusive_loss_threshold_strict
    """
    ctx = setup_approved_case(
        clock="2026-02-26T00:00:00Z",
        decl_overrides={"title": "DR-SBAB"},
        inspector_badge="INS-SBAB", cw_employee_id="CW-SBAB",
        applicant_overrides={
            "household_name": "SbaB Household", "household_size": 2,
            "annual_income_cents": 8_000_000, "damage_date": "2026-01-23T00:00:00Z",
            "reported_repair_cost_cents": 2_000_000,
            "reported_personal_property_cents": 1_000_000, "reported_rental_months": 0,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 2_000_000,
            "verified_personal_property_cents": 1_000_000, "verified_rental_months": 0,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    resp = api_client.create_sba_referral(create_sba_referral_payload(ctx["case"]["id"]), cw_h)
    validate_error(resp, ApiErrorId.ERR_SBA_NOT_ELIGIBLE.value)


def test_sba_loss_threshold_just_over_qualifies(api):
    """PRD §3.7: "The referral is eligibility-gated: it is permitted only if the
    applicant's `annual_income_cents` is at or below the income ceiling of $75,000
    (7,500,000 cents), or the verified total loss is strictly greater than the loss
    threshold of $30,000 (3,000,000 cents)."
    PRD §3.7: "On a successful create the verified total loss is snapshotted into
    `referred_loss_cents` and the referral is born `REFERRED`."

    Income 8,000,000 (> ceiling) but verified loss 3,000,001 (> threshold) => the
    referral is created REFERRED with referred_loss_cents 3,000,001.

    Design: Difficulty/boundary_precision_check/sba_income_ceiling_inclusive_loss_threshold_strict
    """
    ctx = setup_approved_case(
        clock="2026-02-26T00:00:00Z",
        decl_overrides={"title": "DR-SBAB2"},
        inspector_badge="INS-SBAB2", cw_employee_id="CW-SBAB2",
        applicant_overrides={
            "household_name": "SbaB2 Household", "household_size": 2,
            "annual_income_cents": 8_000_000, "damage_date": "2026-01-23T00:00:00Z",
            "reported_repair_cost_cents": 2_000_001,
            "reported_personal_property_cents": 1_000_000, "reported_rental_months": 0,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 2_000_001,
            "verified_personal_property_cents": 1_000_000, "verified_rental_months": 0,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    ref = get_success_data(api_client.create_sba_referral(
        create_sba_referral_payload(ctx["case"]["id"]), cw_h))
    assert ref["status"] == "REFERRED", ref["status"]
    assert ref["referred_loss_cents"] == 3_000_001, ref["referred_loss_cents"]


# ─── occ_stale_version / disbursement_create_stale_case_version_412 ─────────
def _approved_case_simple(badge, cw, title):
    return setup_approved_case(
        clock="2026-02-18T00:00:00Z",
        decl_overrides={"title": title},
        inspector_badge=badge, cw_employee_id=cw,
        applicant_overrides={
            "household_name": "Occ Household", "household_size": 4,
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


def test_disbursement_stale_case_version_rejected(api):
    """PRD §2.7: "The first is creating a `Disbursement`. The create request must carry
    `expected_ihp_case_version` matching the target case's current `version`. If
    another writer has advanced the case's `version` since the disbursing caseworker
    last read it — for example by recording an earlier disbursement that already
    consumed part of the remaining obligation — the create is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the caseworker from over-disbursing
    against a ledger view that no longer holds."

    The first disbursement advances the version; a second carrying the pre-disbursement
    version is rejected ERR_STALE_CASE_VERSION.

    Design: Difficulty/occ_stale_version/disbursement_create_stale_case_version_412
    """
    ctx = _approved_case_simple("INS-OCC1", "CW-OCC1", "DR-OCC1")
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    captured_v = case["version"]
    disburse(case["id"], repair_li["id"], captured_v, 300_000, cw_h)
    # Second disbursement still carrying the now-stale captured version.
    resp = api_client.create_disbursement(
        create_disbursement_payload(case["id"], repair_li["id"], captured_v, amount_cents=300_000),
        cw_h,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION.value)


def test_disbursement_with_refreshed_version_succeeds_after_first(api):
    """PRD §2.7: "The create request must carry `expected_ihp_case_version` matching the
    target case's current `version`. If another writer has advanced the case's `version`
    since the disbursing caseworker last read it — for example by recording an earlier
    disbursement that already consumed part of the remaining obligation — the create is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the caseworker from
    over-disbursing against a ledger view that no longer holds."
    PRD §3.8: "On success the disbursement is recorded `PAID`, the case's
    `disbursed_total_cents` increases by the paid amount, `remaining_obligation_cents`
    is recomputed, and the case's `version` increments by one."

    The first disbursement advances the version; re-reading the fresh version lets the
    second disbursement carry the now-current version and succeed (201).

    Design: Difficulty/occ_stale_version/disbursement_create_stale_case_version_412
    """
    ctx = _approved_case_simple("INS-OCC1b", "CW-OCC1b", "DR-OCC1b")
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    disburse(case["id"], repair_li["id"], case["version"], 300_000, cw_h)
    fresh_v = current_case_version(case["id"], cw_h)
    from test_helpers import validate_success
    data = validate_success(
        api_client.create_disbursement(
            create_disbursement_payload(case["id"], repair_li["id"], fresh_v, amount_cents=300_000),
            cw_h),
        expected_status=201,
    )
    assert data["disb_status"] == "PAID", data["disb_status"]


# ─── occ_stale_version / appeal_create_stale_case_version_412 ──────────────
def test_appeal_create_stale_case_version_rejected(api):
    """PRD §2.7: "The second is creating an `Appeal`. The create request must likewise
    carry `expected_ihp_case_version` matching the case's current `version`. If the
    case's decision or award has been re-evaluated since the appellant last read it,
    advancing the `version`, the appeal is filed against a decision that no longer
    stands and is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    After one appeal cycle re-decides the case (version advances twice), a new appeal
    carrying the originally-observed version is rejected ERR_STALE_CASE_VERSION even
    though the case is back in an appealable AWARD_APPROVED state.

    Design: Difficulty/occ_stale_version/appeal_create_stale_case_version_412
    """
    ctx = setup_approved_case_with_two_caseworkers(
        clock="2026-02-20T00:00:00Z",
        decl_overrides={"title": "DR-OCC2"},
        inspector_badge="INS-OCC2", cw1_employee_id="CW-OCC2A", cw2_employee_id="CW-OCC2B",
        applicant_overrides={
            "household_name": "Occ2 Household", "household_size": 2,
            "damage_date": "2026-01-19T00:00:00Z",
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
    cw1_h = ctx["cw1_headers"]
    cw2_h = ctx["cw2_headers"]
    case = ctx["case"]
    captured_v = case["version"]
    # Appeal A filed with the captured version succeeds; cw2 DENIES it (pre_appeal was
    # AWARD_APPROVED) so the case is restored to AWARD_APPROVED, version advanced twice.
    appeal_a = get_success_data(api_client.create_appeal(
        create_appeal_payload(case["id"], captured_v, reason="first appeal"), cw1_h))
    get_success_data(api_client.decide_appeal(appeal_a["id"], {"outcome": "DENIED"}, cw2_h))
    # New appeal carrying the stale captured version.
    resp = api_client.create_appeal(
        create_appeal_payload(case["id"], captured_v, reason="second appeal on stale view"), cw1_h)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION.value)


def test_appeal_with_current_version_succeeds(api):
    """PRD §2.7: "The second is creating an `Appeal`. The create request must likewise
    carry `expected_ihp_case_version` matching the case's current `version`."
    PRD §3.10: "Filing advances the case into `UNDER_APPEAL`: from
    `AWARD_APPROVED → UNDER_APPEAL` it records `pre_appeal_status` as `AWARD_APPROVED`,
    and from `DENIED → UNDER_APPEAL` it records `pre_appeal_status` as `DENIED`."

    The affirmative side of the appeal OCC: an appeal carrying the case's current
    version is accepted (201, SUBMITTED) and the case advances to UNDER_APPEAL.

    Design: Difficulty/occ_stale_version/appeal_create_stale_case_version_412
    """
    ctx = setup_approved_case_with_two_caseworkers(
        clock="2026-02-20T00:00:00Z",
        decl_overrides={"title": "DR-OCC2b"},
        inspector_badge="INS-OCC2b", cw1_employee_id="CW-OCC2Ab", cw2_employee_id="CW-OCC2Bb",
        applicant_overrides={
            "household_name": "Occ2b Household", "household_size": 2,
            "damage_date": "2026-01-19T00:00:00Z",
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
    cw1_h = ctx["cw1_headers"]
    case = ctx["case"]
    from test_helpers import validate_success
    data = validate_success(
        api_client.create_appeal(
            create_appeal_payload(case["id"], case["version"], reason="current-version appeal"), cw1_h),
        expected_status=201,
    )
    assert data["status"] == "SUBMITTED", data["status"]
    refreshed = get_success_data(api_client.get_ihp_case(case["id"], cw1_h))
    assert refreshed["status"] == "UNDER_APPEAL", refreshed["status"]
