"""Breadth coverage: temporal/registration validations, existence-before-state
ordering, cross-entity referential validation, RBAC role denials, the error
catalogue's violation-to-error mappings, positive OCC, and derived-field
reconciliation. (Corner queue: validations, rbac, errors,
cross_cutting_complexity_layers sections.)
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    build_user_headers,
    api_client, TEST_USERS, ApiErrorId, ZERO_UUID,
    make_inspector_headers, make_caseworker_headers,
    create_declaration_payload, create_applicant_payload, create_inspector_payload,
    create_disbursement_payload, create_appeal_payload, create_rental_period_payload,
    setup_program, setup_approved_case, setup_pending_case,
    setup_approved_case_with_two_caseworkers,
    setup_disbursing_case_with_late_dob_recoupment,
    get_line_item, disburse, current_case_version,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]


# ─── validations ───────────────────────────────────────────────────────────
def test_register_after_deadline_returns_registration_closed(api):
    """PRD §3.2: "The declaration must be `OPEN` and the request must arrive on or
    before the declaration's `registration_deadline`; if the declaration is not `OPEN`
    or the deadline has passed, registration is rejected with `ERR_REGISTRATION_CLOSED`."

    Clock advanced past the registration_deadline -> ERR_REGISTRATION_CLOSED.

    Design: Corner/validations/register_after_deadline_returns_registration_closed
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(
        create_declaration_payload(title="DR-V1", registration_deadline="2026-03-31T23:59:59Z"), ADMIN))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-04-15T00:00:00Z"}, ADMIN))
    resp = api_client.create_applicant(
        create_applicant_payload(decl["id"], household_name="Late Household"), CW)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)


def test_register_damage_date_outside_incident_period_422(api):
    """PRD §3.2: "Separately, the household's `damage_date` must fall within the
    inclusive incident period — that is, on or after `incident_start` and on or before
    `incident_end`; a damage date outside that window is rejected with
    `ERR_DAMAGE_DATE_OUT_OF_PERIOD`."

    damage_date before incident_start -> ERR_DAMAGE_DATE_OUT_OF_PERIOD (422).

    Design: Corner/validations/register_damage_date_outside_incident_period_422
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(
        create_declaration_payload(title="DR-V2", incident_start="2026-01-01T00:00:00Z",
                                   incident_end="2026-02-28T23:59:59Z"), ADMIN))
    resp = api_client.create_applicant(
        create_applicant_payload(decl["id"], household_name="Early Household",
                                 damage_date="2025-12-01T00:00:00Z"), CW)
    validate_error(resp, ApiErrorId.ERR_DAMAGE_DATE_OUT_OF_PERIOD.value)


def test_existence_checked_before_state_on_inspect(api):
    """PRD §3.12: "Existence comes third, evaluated left to right — path identifiers
    before body foreign keys — yielding the resource-specific not-found error. State
    preconditions come next: the target resource must be in a legal state for the
    requested transition (for example `ERR_CASE_NOT_PENDING`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, `ERR_REFERRAL_NOT_OPEN`)".

    inspect on a non-existent assessment id returns ERR_ASSESSMENT_NOT_FOUND (existence,
    404) — the existence check precedes any state check.

    Design: Corner/validations/existence_checked_before_state_on_inspect
    """
    insp = get_success_data(api_client.create_inspector(
        create_inspector_payload(full_name="V3 Insp", badge_number="INS-V3"), ADMIN))
    insp_h = make_inspector_headers(insp["id"])
    resp = api_client.inspect_assessment(
        ZERO_UUID,
        {"habitability": "HABITABLE", "verified_repair_cost_cents": 100_000,
         "verified_personal_property_cents": 0, "verified_rental_months": 0},
        insp_h,
    )
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value)


def test_disbursement_line_item_wrong_case_referential(api):
    """PRD §3.8: "The named `line_item_id` must belong to the same case as
    `ihp_case_id` and must be in `APPROVED` status; a line item that is not approved or
    that belongs to a different case is rejected with `ERR_LINE_ITEM_NOT_APPROVED`."

    A disbursement whose line_item_id belongs to a DIFFERENT case than ihp_case_id ->
    ERR_LINE_ITEM_NOT_APPROVED.

    Design: Corner/validations/disbursement_line_item_wrong_case_referential
    """
    # Two approved cases A and B share one declaration + inspector + caseworker.
    ctxa = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-V4"},
        inspector_badge="INS-V4", cw_employee_id="CW-V4",
        applicant_overrides={
            "household_name": "V4 A",
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
    cw_h = ctxa["caseworker_headers"]
    # Build case B under the same program (reuse decl + caseworker + inspector).
    from test_helpers import create_assessment_payload, inspect_assessment_payload, create_ihp_case_payload
    app_b = get_success_data(api_client.create_applicant(
        create_applicant_payload(ctxa["decl"]["id"], household_name="V4 B",
                                 damage_date="2026-01-16T00:00:00Z",
                                 reported_repair_cost_cents=900_000,
                                 reported_personal_property_cents=400_000,
                                 reported_rental_months=2), cw_h))
    asm_b = get_success_data(api_client.create_assessment(
        create_assessment_payload(app_b["id"], ctxa["inspector"]["id"],
                                  scheduled_start="2026-02-12T09:00:00Z",
                                  scheduled_end="2026-02-12T10:00:00Z"), ctxa["inspector_headers"]))
    get_success_data(api_client.inspect_assessment(
        asm_b["id"], inspect_assessment_payload(habitability="UNINHABITABLE",
                                                verified_repair_cost_cents=900_000,
                                                verified_personal_property_cents=400_000,
                                                verified_rental_months=2), ctxa["inspector_headers"]))
    get_success_data(api_client.verify_assessment(asm_b["id"], cw_h))
    case_b = get_success_data(api_client.create_ihp_case(
        create_ihp_case_payload(app_b["id"], asm_b["id"], monthly_fmr_cents=120_000), cw_h))
    case_b = get_success_data(api_client.approve_ihp_case(case_b["id"], cw_h))
    b_repair_li = get_line_item(case_b["id"], "REPAIR_ASSISTANCE", cw_h)
    # Disbursement names case A but case B's line item.
    resp = api_client.create_disbursement(
        create_disbursement_payload(ctxa["case"]["id"], b_repair_li["id"],
                                    ctxa["case"]["version"], amount_cents=100_000), cw_h)
    validate_error(resp, ApiErrorId.ERR_LINE_ITEM_NOT_APPROVED.value)


# ─── rbac ──────────────────────────────────────────────────────────────────
def test_inspector_cannot_create_declaration_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST | `/disaster-relief/declarations` | Create a disaster declaration |
    ProgramAdmin".

    An Inspector invoking POST /declarations (a ProgramAdmin-only op) -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/inspector_cannot_create_declaration_forbidden
    """
    insp = get_success_data(api_client.create_inspector(
        create_inspector_payload(full_name="Rb1 Insp", badge_number="INS-RB1"), ADMIN))
    insp_h = make_inspector_headers(insp["id"])
    resp = api_client.create_declaration(create_declaration_payload(title="DR-RB1"), insp_h)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_caseworker_cannot_inspect_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST | `/disaster-relief/assessments/{id}/inspect` | Record inspection
    results | Inspector".

    A Caseworker invoking inspect (an Inspector-only op) -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/caseworker_cannot_inspect_forbidden
    """
    from test_helpers import setup_scheduled_assessment
    ctx = setup_scheduled_assessment(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-RB2"},
        inspector_badge="INS-RB2", cw_employee_id="CW-RB2",
        applicant_overrides={"household_name": "Rb2 Household"},
    )
    resp = api_client.inspect_assessment(
        ctx["assessment"]["id"],
        {"habitability": "UNINHABITABLE", "verified_repair_cost_cents": 1_000_000,
         "verified_personal_property_cents": 500_000, "verified_rental_months": 3},
        ctx["caseworker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_unknown_role_returns_missing_or_invalid_auth(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH`."

    A request whose X-User-Role is an unknown value -> ERR_MISSING_OR_INVALID_AUTH (401).

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    bad = build_user_headers("nobody-1", "Nobody")
    resp = api_client.list_declarations(bad)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_AUTH.value)


# ─── errors ────────────────────────────────────────────────────────────────
def test_close_registration_on_already_closed_declaration(api):
    """PRD §3.1: "A `ProgramAdmin` later closes registration, moving it
    `OPEN → REGISTRATION_CLOSED`; this requires the declaration to be `OPEN` (otherwise
    `ERR_DECLARATION_NOT_OPEN`) and thereafter blocks creation of any new applicant
    against it."

    close-registration on an already-REGISTRATION_CLOSED declaration ->
    ERR_DECLARATION_NOT_OPEN.

    Design: Corner/errors/error_declaration_not_open_on_double_close_registration
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-ER1"), ADMIN))
    get_success_data(api_client.close_registration(decl["id"], ADMIN))
    resp = api_client.close_registration(decl["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DECLARATION_NOT_OPEN.value)


def test_close_blocked_by_open_disbursing_case(api):
    """PRD §3.1: "From `REGISTRATION_CLOSED` the same role finally closes the
    declaration outright, moving it `REGISTRATION_CLOSED → CLOSED`; this requires the
    declaration to be in `REGISTRATION_CLOSED` (otherwise
    `ERR_DECLARATION_NOT_REGISTRATION_CLOSED`) and requires that no `IhpCase` under the
    declaration is in `DISBURSING` (otherwise `ERR_OPEN_DISBURSING_CASES`)."

    close on a REGISTRATION_CLOSED declaration with a DISBURSING case ->
    ERR_OPEN_DISBURSING_CASES.

    Design: Corner/errors/error_open_disbursing_cases_blocks_close
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER2"},
        inspector_badge="INS-ER2", cw_employee_id="CW-ER2",
        applicant_overrides={
            "household_name": "Er2 Household",
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
    case = ctx["case"]
    decl_id = ctx["decl"]["id"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    disburse(case["id"], repair_li["id"], case["version"], 100_000, cw_h)  # case -> DISBURSING
    get_success_data(api_client.close_registration(decl_id, ADMIN))
    resp = api_client.close_declaration(decl_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_DISBURSING_CASES.value)


def test_record_outcome_on_decided_referral(api):
    """PRD §3.7: "A `Caseworker` or `ProgramAdmin` later records the SBA's decision,
    which requires the referral to be `REFERRED` (otherwise `ERR_REFERRAL_NOT_OPEN`)."

    record-outcome on an already-DECLINED referral -> ERR_REFERRAL_NOT_OPEN.

    Design: Corner/errors/error_referral_not_open_on_double_outcome
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER3"},
        inspector_badge="INS-ER3", cw_employee_id="CW-ER3",
        applicant_overrides={
            "household_name": "Er3 Household",
            "reported_repair_cost_cents": 2_000_000,
            "reported_personal_property_cents": 1_500_000, "reported_rental_months": 0,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 2_000_000,
            "verified_personal_property_cents": 1_500_000, "verified_rental_months": 0,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    ref = get_success_data(api_client.create_sba_referral({"ihp_case_id": ctx["case"]["id"]}, cw_h))
    get_success_data(api_client.record_sba_outcome(ref["id"], {"outcome": "DECLINED"}, cw_h))
    resp = api_client.record_sba_outcome(
        ref["id"], {"outcome": "APPROVED", "sba_loan_amount_cents": 100_000}, cw_h)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_OPEN.value)


def test_record_recovery_on_waived_recoupment(api):
    """PRD §3.9: "A `ProgramAdmin` records recoveries against an established debt. ...
    Recording a recovery requires the recoupment to be `ESTABLISHED` (otherwise
    `ERR_RECOUPMENT_NOT_ESTABLISHED`)".

    record-recovery on a WAIVED recoupment -> ERR_RECOUPMENT_NOT_ESTABLISHED.

    Design: Corner/errors/error_recoupment_waive_then_record_recovery_blocked
    """
    ctx = setup_disbursing_case_with_late_dob_recoupment(
        decl_overrides={"title": "DR-ER4"}, inspector_badge="INS-ER4", cw_employee_id="CW-ER4")
    recoup_id = ctx["recoupment"]["id"]
    get_success_data(api_client.waive_recoupment(recoup_id, ADMIN))
    resp = api_client.record_recovery(recoup_id, {"amount_cents": 100_000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RECOUPMENT_NOT_ESTABLISHED.value)


def test_invalid_appeal_outcome_422(api):
    """PRD §3.10: "The `outcome` must be `GRANTED` or `DENIED`; anything else is
    `ERR_INVALID_APPEAL_OUTCOME`."

    decide with an outcome that is neither GRANTED nor DENIED ->
    ERR_INVALID_APPEAL_OUTCOME (422).

    Design: Corner/errors/error_invalid_appeal_outcome_422
    """
    ctx = setup_approved_case_with_two_caseworkers(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER5"},
        inspector_badge="INS-ER5", cw1_employee_id="CW-ER5A", cw2_employee_id="CW-ER5B",
        applicant_overrides={
            "household_name": "Er5 Household",
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
    case = ctx["case"]
    appeal = get_success_data(api_client.create_appeal(
        create_appeal_payload(case["id"], case["version"], reason="review"), ctx["cw1_headers"]))
    resp = api_client.decide_appeal(appeal["id"], {"outcome": "MAYBE"}, ctx["cw2_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_APPEAL_OUTCOME.value)


def test_disbursement_exceeds_obligation_pure_fiscal(api):
    """PRD §3.8: "The amount must not exceed the case's `remaining_obligation_cents`; an
    over-draw is rejected with `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION` (HTTP 402)."

    On an AWARD_APPROVED case (state passes) a disbursement amount exceeding remaining
    obligation -> ERR_DISBURSEMENT_EXCEEDS_OBLIGATION (402), the fiscal check in isolation.

    Design: Corner/errors/error_disbursement_exceeds_obligation_pure_fiscal
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER6"},
        inspector_badge="INS-ER6", cw_employee_id="CW-ER6",
        applicant_overrides={
            "household_name": "Er6 Household",
            "damage_date": "2026-01-18T00:00:00Z",
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
    case = ctx["case"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    resp = api_client.create_disbursement(
        create_disbursement_payload(case["id"], repair_li["id"], case["version"], amount_cents=5_000_000),
        cw_h,
    )
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_OBLIGATION.value)


def test_invalid_sba_outcome_missing_loan_amount(api):
    """PRD §3.7: "The `outcome` must be either `APPROVED` or `DECLINED`; if it is
    anything else, or if it is `APPROVED` without an `sba_loan_amount_cents`, the
    request is rejected with `ERR_INVALID_SBA_OUTCOME`."

    record-outcome APPROVED without sba_loan_amount_cents -> ERR_INVALID_SBA_OUTCOME (422).

    Design: Corner/errors/error_invalid_sba_outcome_missing_loan_amount
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER7"},
        inspector_badge="INS-ER7", cw_employee_id="CW-ER7",
        applicant_overrides={
            "household_name": "Er7 Household",
            "reported_repair_cost_cents": 2_000_000,
            "reported_personal_property_cents": 1_500_000, "reported_rental_months": 0,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 2_000_000,
            "verified_personal_property_cents": 1_500_000, "verified_rental_months": 0,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    ref = get_success_data(api_client.create_sba_referral({"ihp_case_id": ctx["case"]["id"]}, cw_h))
    resp = api_client.record_sba_outcome(ref["id"], {"outcome": "APPROVED"}, cw_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_SBA_OUTCOME.value)


def test_close_already_closed_rental_period(api):
    """PRD §3.11: "A `Caseworker` or `ProgramAdmin` closes a period, moving it
    `ACTIVE → CLOSED`; this requires the period to be `ACTIVE` (otherwise
    `ERR_RENTAL_PERIOD_NOT_ACTIVE`)".

    close on an already-CLOSED rental period -> ERR_RENTAL_PERIOD_NOT_ACTIVE.

    Design: Corner/errors/error_rental_period_not_active_on_double_close
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER8"},
        inspector_badge="INS-ER8", cw_employee_id="CW-ER8",
        applicant_overrides={
            "household_name": "Er8 Household", "household_size": 3,
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
    rp = get_success_data(api_client.create_rental_period(
        create_rental_period_payload(ctx["case"]["id"]), cw_h))
    get_success_data(api_client.close_rental_period(rp["id"], cw_h))
    resp = api_client.close_rental_period(rp["id"], cw_h)
    validate_error(resp, ApiErrorId.ERR_RENTAL_PERIOD_NOT_ACTIVE.value)


def test_rental_period_create_on_pending_case_not_fundable(api):
    """PRD §3.11: "A `Caseworker` or `ProgramAdmin` opens one with the `ihp_case_id`
    funding the coverage and a window bounded by `period_start` (inclusive) and
    `period_end` (exclusive, and required to be strictly after `period_start`). The
    funding case must be `AWARD_APPROVED` or `DISBURSING` (otherwise
    `ERR_CASE_NOT_FUNDABLE_FOR_RENTAL`)."

    rental-period create on an ELIGIBILITY_PENDING (not yet approved) case ->
    ERR_CASE_NOT_FUNDABLE_FOR_RENTAL.

    Design: Corner/errors/error_case_not_fundable_for_rental_on_pending_case
    """
    ctx = setup_pending_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-ER9"},
        inspector_badge="INS-ER9", cw_employee_id="CW-ER9",
        applicant_overrides={
            "household_name": "Er9 Household", "household_size": 3,
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
    resp = api_client.create_rental_period(
        create_rental_period_payload(ctx["case"]["id"]), cw_h)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FUNDABLE_FOR_RENTAL.value)


# ─── cross_cutting_complexity_layers ───────────────────────────────────────
def _approved_case_for_occ(badge, cw, title):
    return setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": title},
        inspector_badge=badge, cw_employee_id=cw,
        applicant_overrides={
            "household_name": "Cc Household", "household_size": 4,
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


def test_disbursement_with_current_version_succeeds(api):
    """PRD §2.7: "The first is creating a `Disbursement`. The create request must carry
    `expected_ihp_case_version` matching the target case's current `version`."
    PRD §3.8: "On success the disbursement is recorded `PAID`, the case's
    `disbursed_total_cents` increases by the paid amount, `remaining_obligation_cents`
    is recomputed, and the case's `version` increments by one."

    A disbursement carrying the current version succeeds (201, PAID) and advances the
    case version.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_disbursement_succeeds
    """
    ctx = _approved_case_for_occ("INS-CC1", "CW-CC1", "DR-CC1")
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    data = validate_success(
        api_client.create_disbursement(
            create_disbursement_payload(case["id"], repair_li["id"], case["version"], amount_cents=300_000),
            cw_h),
        expected_status=201,
    )
    assert data["disb_status"] == "PAID", data["disb_status"]
    refreshed = get_success_data(api_client.get_ihp_case(case["id"], cw_h))
    assert refreshed["disbursed_total_cents"] == 300_000, refreshed["disbursed_total_cents"]
    assert refreshed["version"] > case["version"], (refreshed["version"], case["version"])


def test_remaining_obligation_reconciled_after_disbursement(api):
    """PRD §2.9: "the remaining obligation is always the approved total minus what has
    already been paid: `disbursed_total_cents` plus `remaining_obligation_cents` always
    equals `total_approved_cents`."
    PRD §3.8: "On success the disbursement is recorded `PAID`, the case's
    `disbursed_total_cents` increases by the paid amount, `remaining_obligation_cents`
    is recomputed, and the case's `version` increments by one."

    After a 300,000 disbursement on a 1,540,000 case, disbursed_total is 300,000 and
    remaining_obligation reconciles to 1,240,000.

    Design: Corner/cross_cutting_complexity_layers/derived_remaining_obligation_reconciled_after_disbursement
    """
    ctx = _approved_case_for_occ("INS-CC2", "CW-CC2", "DR-CC2")
    cw_h = ctx["caseworker_headers"]
    case = ctx["case"]
    assert case["total_approved_cents"] == 1_540_000, case["total_approved_cents"]
    repair_li = get_line_item(case["id"], "REPAIR_ASSISTANCE", cw_h)
    disburse(case["id"], repair_li["id"], case["version"], 300_000, cw_h)
    refreshed = get_success_data(api_client.get_ihp_case(case["id"], cw_h))
    assert refreshed["disbursed_total_cents"] == 300_000, refreshed["disbursed_total_cents"]
    assert refreshed["remaining_obligation_cents"] == 1_240_000, refreshed["remaining_obligation_cents"]
