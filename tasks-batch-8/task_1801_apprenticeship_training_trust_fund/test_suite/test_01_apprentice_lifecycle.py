"""Apprentice lifecycle: intake defaults, registration, indenture, wage
progression, and journeyman certification (PRD §3.2, §3.6, §3.8)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_apprentice,
    award_rti_credits,
    create_apprentice,
    create_apprentice_payload,
    create_fund,
    create_indentured_apprentice,
    create_employer,
    create_report,
    get_apprentice,
    record_registration_decision,
    report_line,
    setup_apprentice_with_hours_and_credits,
    setup_fund_employer_apprentice,
    submit_registration,
    submit_report,
    validate_error,
    validate_success,
)


def test_apprentice_create_default_state(api):
    """PRD §3.2: "A new apprentice begins with `program_status` `APPLICANT`,
    `registration_status` `UNFILED`, `registration_agency` null, both
    accumulators (`ojt_hours_accumulated`, `rti_credits_accumulated`) at zero,
    `current_wage_step` 1, and a `current_wage_rate_cents` of fifty percent of
    the journeyman base rate, rounded half-up to a whole cent."

    Design: Corner/entities/apprentice_create_default_state
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    resp = api.create_apprentice(
        create_apprentice_payload(fund["id"], employer["id"],
                                  journeyman_base_rate_cents=4000),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_apprentice(data)
    assert data["program_status"] == "APPLICANT"
    assert data["registration_status"] == "UNFILED"
    assert data["registration_agency"] is None
    assert data["ojt_hours_accumulated"] == 0
    assert data["rti_credits_accumulated"] == 0
    assert data["current_wage_step"] == 1
    assert data["current_wage_rate_cents"] == 2000, (
        "step 1 pays fifty percent of the 4000-cent journeyman base"
    )


def test_indenture_without_registration_rejected(api):
    """PRD §3.2: "It requires the registration dimension to read `REGISTERED`;
    otherwise the request is rejected with `ERR_REGISTRATION_REQUIRED`
    (HTTP 409)."

    Design: Corner/state_machines/apprentice_invalid_indenture_when_applicant_registered_path
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    apprentice = create_apprentice(fund["id"], employer["id"])
    resp = api.indenture_apprentice(apprentice["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_REQUIRED)
    after = get_apprentice(apprentice["id"])
    assert after["program_status"] == "APPLICANT"
    assert after["registration_status"] == "UNFILED"


def test_certify_cancelled_apprentice_rejected(api):
    """PRD §3.8: "Cancellation is the administrative exit, available from
    `APPLICANT`, `INDENTURED`, or `SUSPENDED`; from either terminal program
    state it is a generic invalid-state rejection."
    PRD §3.8: "Certifying an apprentice whose program is in any state other
    than `INDENTURED` is a generic invalid-state rejection."

    Design: Corner/state_machines/apprentice_cancel_terminal_lockdown
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    apprentice = create_apprentice(fund["id"], employer["id"])
    cancelled = validate_success(
        api.cancel_apprentice(apprentice["id"], ADMIN), 200,
    )
    assert cancelled["program_status"] == "CANCELLED"

    resp = api.certify_journeyman(apprentice["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_apprentice(apprentice["id"])["program_status"] == "CANCELLED"


def test_record_decision_invalid_outcome_rejected(api):
    """PRD §3.2: "Its `outcome` must be one of `REGISTERED`, `REJECTED`, or
    `REVOKED` — anything else is rejected with
    `ERR_INVALID_REGISTRATION_OUTCOME` — and an optional `agency_note` may
    accompany it."

    Design: Corner/validations/registration_record_invalid_outcome_rejected
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    apprentice = create_apprentice(fund["id"], employer["id"])
    submit_registration(apprentice["id"], "FEDERAL")

    resp = api.record_registration_decision(
        apprentice["id"], {"outcome": "MAYBE"}, ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_OUTCOME)
    after = get_apprentice(apprentice["id"])
    assert after["registration_status"] == "SUBMITTED"


def test_record_decision_on_unfiled_registration_rejected(api):
    """PRD §3.2: "The recording is accepted only in the two from-states the
    registration machine allows: an outcome of `REGISTERED` or `REJECTED`
    while the registration reads `SUBMITTED`, and an outcome of `REVOKED`
    while it reads `REGISTERED`; a recording attempted in any other
    registration state is rejected with `ERR_REGISTRATION_NOT_SUBMITTED`."

    Design: Corner/errors/error_registration_not_submitted_on_decision
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    apprentice = create_apprentice(fund["id"], employer["id"])
    resp = api.record_registration_decision(
        apprentice["id"], {"outcome": "REGISTERED"}, ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_SUBMITTED)
    assert get_apprentice(apprentice["id"])["registration_status"] == "UNFILED"


def test_revoke_suspends_indentured_apprentice(api):
    """PRD §3.2: "Recording `REVOKED` moves the registration to `REVOKED` and,
    if the apprentice is currently `INDENTURED`, automatically suspends the
    program to `SUSPENDED` — the apprentice stops accumulating creditable
    standing until a later `REGISTERED` recording reinstates them."

    Design: Difficulty/non_linear_state_machine/apprentice_parallel_dimensions_revoke_reinstate
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    apprentice = create_indentured_apprentice(fund["id"], employer["id"])

    resp = api.record_registration_decision(
        apprentice["id"], {"outcome": "REVOKED"}, ADMIN,
    )
    data = validate_success(resp, 200)
    assert data["registration_status"] == "REVOKED"
    assert data["program_status"] == "SUSPENDED", (
        "revoking the registration of an INDENTURED apprentice auto-suspends"
    )


def test_refile_and_registered_decision_reinstates(api):
    """PRD §3.2: "A filing is accepted while the registration reads `UNFILED`,
    `REJECTED`, or `REVOKED`, so a rejected or revoked registration can be
    re-filed; it moves the registration to `SUBMITTED` and sets
    `registration_agency` from the payload."
    PRD §3.2: "Recording `REGISTERED` moves the registration to `REGISTERED`
    and, if the program dimension happens to be `SUSPENDED`, reinstates the
    apprentice to `INDENTURED`."

    Design: Difficulty/non_linear_state_machine/apprentice_parallel_dimensions_revoke_reinstate
    """
    fund = create_fund()
    employer = create_employer(fund["id"])
    apprentice = create_indentured_apprentice(fund["id"], employer["id"])
    record_registration_decision(apprentice["id"], "REVOKED")

    refiled = validate_success(
        api.submit_registration(apprentice["id"], {"agency": "FEDERAL"}, ADMIN),
        200,
    )
    assert refiled["registration_status"] == "SUBMITTED"
    assert refiled["registration_agency"] == "FEDERAL"

    decided = validate_success(
        api.record_registration_decision(
            apprentice["id"], {"outcome": "REGISTERED"}, ADMIN,
        ),
        200,
    )
    assert decided["registration_status"] == "REGISTERED"
    assert decided["program_status"] == "INDENTURED", (
        "a REGISTERED decision reinstates a SUSPENDED apprentice"
    )


def test_hours_gate_met_without_credits_stays_step_1(api):
    """PRD §3.6: "Step 2 requires at least 2,000 accumulated on-the-job hours
    and at least 144 related-instruction credits; step 3 requires at least
    4,000 hours and at least 288 credits; step 4 requires at least 6,000 hours
    and at least 432 credits; step 5 requires at least 8,000 hours and at
    least 576 credits."
    PRD §3.6: "The `current_wage_step` is the highest step for which both
    gates — hours and credits — hold."

    Design: Difficulty/combinatorial_formula/combinatorial_wage_step_dual_gated_tiers
    """
    fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 2000)],
    )
    submit_report(employer, report["id"])

    after = get_apprentice(apprentice["id"])
    assert after["ojt_hours_accumulated"] == 2000
    assert after["rti_credits_accumulated"] == 0
    assert after["current_wage_step"] == 1, (
        "hours gate met but the 144-credit gate fails, so step stays 1"
    )
    assert after["current_wage_rate_cents"] == 2000


def test_dual_gates_met_advances_to_step_2(api):
    """PRD §3.4: "Each attended enrollment becomes `CREDITED`: the class's
    `rti_credit_value` is added to that apprentice's `rti_credits_accumulated`,
    and the apprentice's wage step and rate are recomputed."
    PRD §3.6: "The `current_wage_rate_cents` is the apprentice's
    `journeyman_base_rate_cents` multiplied by the step's percentage of the
    journeyman rate — fifty percent at step 1, sixty at step 2, seventy at
    step 3, eighty at step 4, and ninety at step 5 — rounded half-up to a
    whole cent."

    Design: Difficulty/combinatorial_formula/combinatorial_wage_step_dual_gated_tiers
    """
    fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 2000)],
    )
    submit_report(employer, report["id"])
    award_rti_credits(apprentice, fund["id"], 144)

    after = get_apprentice(apprentice["id"])
    assert after["rti_credits_accumulated"] == 144
    assert after["current_wage_step"] == 2, (
        "2000 hours and 144 credits satisfy both step-2 gates"
    )
    assert after["current_wage_rate_cents"] == 2400, (
        "step 2 pays sixty percent of the 4000-cent base"
    )


def test_wage_step_at_1999_hours_stays_step_1(api):
    """PRD §3.6: "Step 2 requires at least 2,000 accumulated on-the-job hours
    and at least 144 related-instruction credits; step 3 requires at least
    4,000 hours and at least 288 credits; step 4 requires at least 6,000 hours
    and at least 432 credits; step 5 requires at least 8,000 hours and at
    least 576 credits."

    Design: Difficulty/boundary_precision_check/boundary_wage_step_at_exact_2000_hours
    """
    _fund, _employer, apprentice = setup_apprentice_with_hours_and_credits(
        hours=1999, credits=144,
    )
    assert apprentice["ojt_hours_accumulated"] == 1999
    assert apprentice["rti_credits_accumulated"] == 144
    assert apprentice["current_wage_step"] == 1, (
        "one hour below the 2,000-hour threshold: 'at least' is not met"
    )
    assert apprentice["current_wage_rate_cents"] == 2000


def test_wage_step_at_exactly_2000_hours_reaches_step_2(api):
    """PRD §3.6: "Step 2 requires at least 2,000 accumulated on-the-job hours
    and at least 144 related-instruction credits; step 3 requires at least
    4,000 hours and at least 288 credits; step 4 requires at least 6,000 hours
    and at least 432 credits; step 5 requires at least 8,000 hours and at
    least 576 credits."
    PRD §3.6: "The `current_wage_rate_cents` is the apprentice's
    `journeyman_base_rate_cents` multiplied by the step's percentage of the
    journeyman rate — fifty percent at step 1, sixty at step 2, seventy at
    step 3, eighty at step 4, and ninety at step 5 — rounded half-up to a
    whole cent."

    Design: Difficulty/boundary_precision_check/boundary_wage_step_at_exact_2000_hours
    """
    _fund, _employer, apprentice = setup_apprentice_with_hours_and_credits(
        hours=2000, credits=144,
    )
    assert apprentice["ojt_hours_accumulated"] == 2000
    assert apprentice["rti_credits_accumulated"] == 144
    assert apprentice["current_wage_step"] == 2, (
        "exactly 2,000 hours meets the 'at least' threshold"
    )
    assert apprentice["current_wage_rate_cents"] == 2400


def test_certify_short_of_rti_credits_rejected(api):
    """PRD §3.8: "Three prerequisites are enforced together, and any shortfall
    is rejected with `ERR_CERTIFICATION_REQUIREMENTS_NOT_MET` (HTTP 409): the
    apprentice's `ojt_hours_accumulated` must be at least 8,000, the
    `rti_credits_accumulated` must be at least 576, and the registration
    dimension must read `REGISTERED`."

    Design: Corner/errors/error_certification_requirements_not_met
    """
    fund, _employer, apprentice = setup_apprentice_with_hours_and_credits(
        hours=8000, credits=100,
    )
    assert apprentice["ojt_hours_accumulated"] == 8000
    assert apprentice["rti_credits_accumulated"] == 100

    resp = api.certify_journeyman(apprentice["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIREMENTS_NOT_MET)
    assert get_apprentice(apprentice["id"])["program_status"] == "INDENTURED"


def test_certify_journeyman_at_full_requirements(api):
    """PRD §3.8: "Certification is the program's successful exit: an
    `INDENTURED` apprentice becomes `COMPLETED`."
    PRD §3.8: "On success the system reports the completion to the agency by
    moving the registration to `DEREGISTERED`."

    Design: Corner/errors/error_certification_succeeds_at_full_requirements
    """
    fund, _employer, apprentice = setup_apprentice_with_hours_and_credits(
        hours=8000, credits=576,
    )
    resp = api.certify_journeyman(apprentice["id"], ADMIN)
    data = validate_success(resp, 200)
    assert_apprentice(data)
    assert data["program_status"] == "COMPLETED"
    assert data["registration_status"] == "DEREGISTERED"
    assert data["current_wage_step"] == 5
    assert data["current_wage_rate_cents"] == 3600, (
        "step 5 pays ninety percent of the 4000-cent base"
    )
