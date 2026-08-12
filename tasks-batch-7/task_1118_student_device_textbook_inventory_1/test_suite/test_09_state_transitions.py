"""State-machine invalid transitions, preconditions, idempotency, and
terminal lockdown (PRD §2.10, §3.1, §3.2, §3.6, §3.7, §3.9)."""

from test_helpers import (
    ApiErrorId,
    activate_program,
    create_fleet,
    create_program,
    enroll_student,
    file_damage_report,
    make_family_headers,
    settle_fee_payload,
    setup_confirmed_damage_fee,
    setup_retired_unit,
    setup_student_with_assignment,
    sign_agreement,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


def test_close_from_draft_rejected(api, admin_headers):
    """PRD §2.10: "Fifth, the target resource's own state precondition for the requested transition — a report must be `SUBMITTED` before it can be confirmed, and so on — rejected with `ERR_INVALID_STATE` where no more specific error exists."

    Closing a program requires SUMMER_COLLECTION; a DRAFT program cannot
    close. The rejection is a 409 state refusal (the PRD does not pin which
    of the two state-error identifiers fires for this particular transition).

    Design: Corner/state_machines/program_close_from_draft_returns_invalid_state
    """
    program = create_program()
    res = api.close_program(program["id"], admin_headers)
    assert res.status_code == 409, f"Expected 409, got {res.status_code}"
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_PROGRAM_STATE_FORBIDS.value,
              ApiErrorId.ERR_INVALID_STATE.value]
    )


def test_activate_program_with_no_fleet_rejected(api, admin_headers):
    """PRD §3.1: "Activation moves the program `DRAFT → ACTIVE` and is refused with `ERR_PROGRAM_HAS_NO_FLEET` until at least one fleet exists under the program, because an asset-less program has nothing to run."

    Design: Corner/state_machines/activate_program_with_no_fleet_rejected
    """
    program = create_program()
    res = api.activate_program(program["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_PROGRAM_HAS_NO_FLEET)


def test_withdraw_with_open_assignment_rejected(api, registrar_headers):
    """PRD §3.2: "Both transitions demand a clean desk: no assignment in `ACTIVE` or `OVERDUE` status may remain, else the request is refused with `ERR_OPEN_ASSIGNMENTS`, and the `financial_posture` must be `CLEAR`, else `ERR_FEES_OUTSTANDING`."

    Design: Corner/state_machines/withdraw_with_open_assignment_rejected
    """
    ctx = setup_student_with_assignment()
    assert ctx["assignment"]["status"] == "ACTIVE"
    res = api.withdraw_student(ctx["program"]["id"], ctx["student"]["id"],
                               registrar_headers)
    validate_error(res, ApiErrorId.ERR_OPEN_ASSIGNMENTS)


def test_double_sign_family_agreement_rejected(api):
    """PRD §2.10: "Fifth, the target resource's own state precondition for the requested transition — a report must be `SUBMITTED` before it can be confirmed, and so on — rejected with `ERR_INVALID_STATE` where no more specific error exists."

    Signing is the PENDING -> SIGNED transition; a second sign on an already
    SIGNED agreement violates the transition's state precondition.

    Design: Corner/state_machines/double_sign_family_agreement_rejected
    """
    program = create_program()
    create_fleet(program["id"])
    activate_program(program["id"])
    student = enroll_student(program["id"], "SIS-DS-1", "Double Sign")
    sign_agreement(program["id"], student["id"])
    res = api.sign_family_agreement(
        program["id"], student["id"],
        {"acceptable_use_version": "AUP-2026.v3", "signed_by_guardian_name": "G"},
        make_family_headers(student["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_disposed_unit_rejects_further_transitions(api, admin_headers):
    """PRD §3.9: "All three terminal states — `DISPOSED`, `DONATED`, `WRITTEN_OFF` — retain the record and its event trail for audit rather than deleting anything."
    PRD §2.10: "Fifth, the target resource's own state precondition for the requested transition — a report must be `SUBMITTED` before it can be confirmed, and so on — rejected with `ERR_INVALID_STATE` where no more specific error exists."

    DISPOSED is terminal: donating a disposed unit is rejected.

    Design: Corner/state_machines/retire_terminal_disposed_lockdown
    """
    program, fleet, retired = setup_retired_unit()
    disposed = validate_success(
        api.dispose_asset_unit(program["id"], retired["id"], admin_headers), 200
    )
    assert disposed["lifecycle_status"] == "DISPOSED"
    res = api.donate_asset_unit(program["id"], retired["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_draft_damage_report_rejected(api):
    """PRD §2.10: "Fifth, the target resource's own state precondition for the requested transition — a report must be `SUBMITTED` before it can be confirmed, and so on — rejected with `ERR_INVALID_STATE` where no more specific error exists."

    Design: Corner/state_machines/confirm_draft_damage_report_rejected
    """
    ctx = setup_student_with_assignment()
    report = file_damage_report(ctx, damage_category="COSMETIC",
                                observed_condition_grade="B")
    assert report["status"] == "DRAFT"
    res = api.confirm_damage_report(
        ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
        report["id"], TECH,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_settle_already_settled_fee_rejected(api, admin_headers):
    """PRD §2.10: "Fifth, the target resource's own state precondition for the requested transition — a report must be `SUBMITTED` before it can be confirmed, and so on — rejected with `ERR_INVALID_STATE` where no more specific error exists."

    Settlement is the ASSESSED -> SETTLED transition; a fee already SETTLED
    rejects a further settle call.

    Design: Corner/state_machines/settle_already_settled_fee_rejected
    """
    ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                     observed_condition_grade="A")
    fee = ctx["fee"]
    settled = validate_success(
        api.settle_fee(ctx["program"]["id"], ctx["student"]["id"], fee["id"],
                       settle_fee_payload(fee["amount_cents"]), admin_headers),
        200,
    )
    assert settled["status"] == "SETTLED"
    res = api.settle_fee(ctx["program"]["id"], ctx["student"]["id"], fee["id"],
                         settle_fee_payload(100), admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
