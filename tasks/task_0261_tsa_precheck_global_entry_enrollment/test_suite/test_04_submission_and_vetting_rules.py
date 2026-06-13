"""Submission eligibility, fee gating, renewal rules, and validation precedence.

Translates difficulty queue A priority_pair_validation_conflict (state precedes
fiscal) and corner queue B validation instances (eligibility, disqualifying flag,
fee unpaid, renewal too early, renewal source invalid).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_applicant_headers, TEST_USERS, ApiErrorId,
    pay_payload, background_check_payload,
    setup_approved_application,
    get_application, app_version,
    create_program, create_applicant, create_center, create_slot,
    create_draft_application, set_clock,
)

ADMIN = TEST_USERS["scheduling_admin_headers"]
VETTING = TEST_USERS["vetting_officer_headers"]


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict (state precedes fiscal)
# ---------------------------------------------------------------------------

def test_invalid_state_precedes_fee_unpaid_on_background_checks(api):
    """PRD §2.9: "After schema validation comes the optimistic-concurrency check
    (`ERR_STALE_VERSION`) on the two endpoints that declare a version field, then
    the state-machine precondition that the target is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`). Only after all of the
    foregoing pass does the system evaluate the domain-specific business rules that
    govern each workflow."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_fee_unpaid_on_background_checks
    """
    set_clock()
    program = create_program()
    applicant = create_applicant(full_name="Ivy Draft")
    headers = make_applicant_headers(applicant["id"])
    # DRAFT application, never submitted and fee unpaid: opening a background check
    # fails the SUBMITTED state precondition (409) before the fee gate (402).
    app = create_draft_application(applicant["id"])
    resp = api.create_background_check(
        app["id"], background_check_payload(), VETTING
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_on_background_check_for_vetting_application(api):
    """PRD §2.9: "then the state-machine precondition that the target is in a state
    from which the requested transition is defined (`ERR_INVALID_STATE`). Only after
    all of the foregoing pass does the system evaluate the domain-specific business
    rules that govern each workflow."
    PRD §3.3: "that no background check already exists for the application, since
    exactly one is permitted."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_fee_unpaid_on_background_checks
    """
    # Application already advanced to VETTING (fee paid). A second background-check
    # attempt fails the SUBMITTED state precondition (ERR_INVALID_STATE) — the state
    # gate is evaluated regardless of the fiscal rule.
    set_clock()
    program = create_program()
    applicant = create_applicant(full_name="Ivan Vet")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api.submit_application(app["id"], headers))
    get_success_data(
        api.create_background_check(app["id"], background_check_payload(criminal_hits=1), VETTING)
    )
    # Now in VETTING; a second open is not from a defined transition state.
    resp = api.create_background_check(app["id"], background_check_payload(), VETTING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — validations section
# ---------------------------------------------------------------------------

def test_global_entry_nonimmigrant_rejected(api):
    """PRD §3.2: "When the program is `GLOBAL_ENTRY`, the applicant's `citizenship`
    must be `US_CITIZEN` or `LPR`, or the submission is rejected with
    `ERR_ELIGIBILITY_CITIZENSHIP`."

    Design: Corner/validations/global_entry_nonimmigrant_eligibility_rejected
    """
    program = create_program(code="GLOBAL_ENTRY", name="Global Entry", base_fee_cents=12000)
    applicant = create_applicant(full_name="Sue NonImm", citizenship="NONIMMIGRANT")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"], program_code="GLOBAL_ENTRY")
    resp = api.submit_application(app["id"], headers)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_CITIZENSHIP.value)


def test_disqualifying_flag_blocks_submit(api):
    """PRD §3.2: "The applicant must not have self-declared a permanently
    disqualifying conviction - that is, `disqualifying_flag` must be false - or the
    submission is rejected with `ERR_PERMANENTLY_DISQUALIFIED`."

    Design: Corner/validations/disqualifying_flag_blocks_submit
    """
    program = create_program()
    applicant = create_applicant(full_name="Tom Dq", disqualifying_flag=True)
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    resp = api.submit_application(app["id"], headers)
    validate_error(resp, ApiErrorId.ERR_PERMANENTLY_DISQUALIFIED.value)


def test_fee_unpaid_blocks_vetting(api):
    """PRD §3.3: "A `VettingOfficer` opens vetting on a `SUBMITTED` application,
    which requires that `fee_paid_cents` be at least `fee_due_cents` - a shortfall
    is rejected with `ERR_FEE_UNPAID`."

    Design: Corner/validations/fee_unpaid_blocks_vetting
    """
    program = create_program(base_fee_cents=7800)
    applicant = create_applicant(full_name="Wes Unpaid")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    # Submit with NO payment: fee_due 7800, fee_paid 0.
    get_success_data(api.submit_application(app["id"], headers))
    resp = api.create_background_check(app["id"], background_check_payload(), VETTING)
    validate_error(resp, ApiErrorId.ERR_FEE_UNPAID.value)


def test_renewal_source_not_approved_rejected(api):
    """PRD §3.2: "When `renews_from_application_id` is set, the named prior
    application must be `APPROVED` and must share the same `applicant_id` and
    `program_code`, or the submission is rejected with `ERR_RENEWAL_SOURCE_INVALID`."

    Design: Corner/validations/renewal_source_not_approved_rejected
    """
    program = create_program()
    applicant = create_applicant(full_name="Xan Src")
    headers = make_applicant_headers(applicant["id"])
    prior = create_draft_application(applicant["id"])  # never approved (DRAFT)
    renewal = create_draft_application(
        applicant["id"], renews_from_application_id=prior["id"]
    )
    resp = api.submit_application(renewal["id"], headers)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_SOURCE_INVALID.value)


def test_renewal_too_early_rejected(api):
    """PRD §3.2: "A renewal additionally may not be submitted too early: it must be
    submitted no sooner than the prior credential's `expires_at` minus the
    program's `renewal_window_days`, and an earlier submission is rejected with
    `ERR_RENEWAL_TOO_EARLY`."

    Design: Corner/validations/renewal_too_early_rejected
    """
    # Prior approved KTN expires 2031-06-09; window opens 2030-12-11.
    program, applicant, prior, _center, _slot, _appt, _ktn = setup_approved_application(
        program_overrides={"renewal_window_days": 180, "validity_years": 5}
    )
    # Clock is still 2026-06-09 from the happy-path setup: well before the window.
    headers = make_applicant_headers(applicant["id"])
    renewal = create_draft_application(
        applicant["id"], renews_from_application_id=prior["id"]
    )
    resp = api.submit_application(renewal["id"], headers)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_TOO_EARLY.value)
