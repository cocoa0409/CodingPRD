"""The locum pipeline: requisition guards, the credentialing checklist, case
off-ramps, the fail/expire re-open cycle, and the completion auto-fill
cascade."""
from test_helpers import (
    ApiErrorId,
    assert_credentialing_case,
    complete_item,
    create_locum_physician,
    create_requisition_payload,
    create_staff_physician,
    get_case_for_requisition,
    get_program,
    list_assignments,
    set_clock,
    setup_credentialing_case,
    setup_filled_requisition,
    setup_open_requisition,
    setup_shortfall_program,
    setup_sourced_requisition,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CRED = TEST_USERS["cred_officer_headers"]


# ─── Requisition creation and proposal guards ────────────────────────

def test_propose_staff_candidate_returns_candidate_not_locum(api):
    """PRD §3.5: "the candidate must be a LOCUM physician (a STAFF nominee is
    `ERR_CANDIDATE_NOT_LOCUM`)".

    Design: Corner/validations/propose_staff_candidate_returns_candidate_not_locum
    """
    _program, _slot, _gap, requisition = setup_open_requisition()
    staff = create_staff_physician("Dr Staff")
    resp = api.propose_candidate(requisition["id"], staff["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_LOCUM, 409)
    after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert after["status"] == "OPEN"
    assert after["candidate_physician_id"] is None


def test_propose_wrong_specialty_locum_returns_specialty_mismatch(api):
    """PRD §3.5: "the candidate must be a LOCUM physician (a STAFF nominee is
    `ERR_CANDIDATE_NOT_LOCUM`), ACTIVE (`ERR_PHYSICIAN_INACTIVE`),
    specialty-matched to the program (`ERR_SPECIALTY_MISMATCH`)".

    Design: Corner/validations/propose_wrong_specialty_locum_returns_specialty_mismatch
    """
    _program, _slot, _gap, requisition = setup_open_requisition()
    locum = create_locum_physician("Dr Locum", specialty="EMERGENCY_MEDICINE")
    resp = api.propose_candidate(requisition["id"], locum["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SPECIALTY_MISMATCH, 409)
    after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert after["status"] == "OPEN"


def test_second_requisition_on_requisitioned_gap_rejected(api):
    """PRD §3.5: "A `SchedulerAdmin` opens a locum requisition against an OPEN
    gap — any other gap phase is `ERR_GAP_NOT_OPEN`".

    Design: Corner/validations/second_requisition_on_requisitioned_gap_rejected
    """
    _program, _slot, gap, requisition = setup_open_requisition()
    resp = api.create_requisition(create_requisition_payload(gap["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_GAP_NOT_OPEN, 409)
    requisitions, _meta = validate_paginated(
        api.list_requisitions(ADMIN, params={"gap_id": gap["id"]})
    )
    assert len(requisitions) == 1
    assert requisitions[0]["id"] == requisition["id"]


def test_requisition_infeasible_lead_time_rejected(api):
    """PRD §3.5: "only while credentialing remains feasible: the logical clock
    must be strictly earlier than the slot's `window_start` minus the program's
    `credentialing_lead_hours` (default 120 hours, five days of lead time), or
    creation fails with `ERR_CREDENTIALING_INFEASIBLE`."

    The 2026-09-08 slot starts 2026-09-08T07:00:00Z; with the 120-hour lead the
    feasibility boundary is 2026-09-03T07:00:00Z and the clock is past it.

    Design: Corner/validations/requisition_infeasible_lead_time_rejected
    """
    _program, _slot, gap = setup_shortfall_program()
    set_clock("2026-09-03T08:00:00Z")
    resp = api.create_requisition(create_requisition_payload(gap["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CREDENTIALING_INFEASIBLE, 409)
    gap_after = validate_success(api.get_gap(gap["id"], ADMIN))
    assert gap_after["status"] == "OPEN"


def test_propose_candidate_on_sourced_requisition_returns_not_open(api):
    """PRD §3.5: "Candidate proposal moves OPEN → SOURCED (otherwise
    `ERR_REQUISITION_NOT_OPEN`)."

    Design: Corner/errors/propose_candidate_on_sourced_requisition_returns_not_open
    """
    _program, _slot, _gap, requisition, locum = setup_sourced_requisition()
    second = create_locum_physician("Dr Locum Two")
    resp = api.propose_candidate(requisition["id"], second["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN, 409)
    after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert after["candidate_physician_id"] == locum["id"]


def test_begin_credentialing_on_open_requisition_returns_not_sourced(api):
    """PRD §3.5: "Beginning credentialing is the `CredentialingOfficer`'s step,
    moving SOURCED → CREDENTIALING (`ERR_REQUISITION_NOT_SOURCED` otherwise)".

    Design: Corner/errors/begin_credentialing_on_open_requisition_returns_not_sourced
    """
    _program, _slot, _gap, requisition = setup_open_requisition()
    resp = api.begin_credentialing(requisition["id"], CRED)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_SOURCED, 409)
    cases, _meta = validate_paginated(
        api.list_cases(CRED, params={"requisition_id": requisition["id"]})
    )
    assert cases == [], "no credentialing case may be created by the rejected call"


# ─── Requisition cancellation cascade ────────────────────────────────

def test_requisition_cancel_reopens_gap_and_cancels_case(api):
    """PRD §3.5: "Cancelling from CREDENTIALING also moves the active
    CredentialingCase to CANCELLED"; "Cancellation returns the gap from
    REQUISITIONED to OPEN and clears the candidate".

    Design: Corner/state_machines/requisition_cancel_reopens_gap_and_cancels_case
    """
    _program, _slot, gap, requisition, _locum, case = setup_credentialing_case()
    complete_item(case["id"], "license_verification")

    resp = api.cancel_requisition(requisition["id"], ADMIN)
    cancelled = validate_success(resp, 200)
    assert cancelled["status"] == "CANCELLED"

    case_after = validate_success(api.get_case(case["id"], CRED))
    assert case_after["status"] == "CANCELLED"

    gap_after = validate_success(api.get_gap(gap["id"], ADMIN))
    assert gap_after["status"] == "OPEN"
    assert gap_after["resolved_by_assignment_id"] is None


# ─── Non-linear state machine: credentialing fail re-open cycle ──────

def _setup_failed_case():
    """Requisition in CREDENTIALING with one item completed, then failed."""
    program, slot, gap, requisition, locum, case = setup_credentialing_case()
    complete_item(case["id"], "license_verification")
    return program, slot, gap, requisition, locum, case


def test_credentialing_fail_reopens_requisition_but_not_gap(api):
    """PRD §3.5: "Both outcomes re-open the requisition from CREDENTIALING to
    OPEN, clear its `candidate_physician_id` to null, and leave the gap
    REQUISITIONED".

    Design: Difficulty/non_linear_state_machine/locum_requisition_credentialing_fail_reopen_cycle
    """
    _program, _slot, gap, requisition, _locum, case = _setup_failed_case()
    resp = api.fail_case(case["id"], "license mismatch", CRED)
    failed = validate_success(resp, 200)
    assert failed["status"] == "FAILED"

    req_after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert req_after["status"] == "OPEN"
    assert req_after["candidate_physician_id"] is None

    gap_after = validate_success(api.get_gap(gap["id"], ADMIN))
    assert gap_after["status"] == "REQUISITIONED"


def test_credentialing_reopen_cycle_accepts_second_candidate(api):
    """PRD §3.5: "the OPEN → SOURCED → CREDENTIALING → OPEN cycle may repeat for
    as many candidates as needed."

    Design: Difficulty/non_linear_state_machine/locum_requisition_credentialing_fail_reopen_cycle
    """
    _program, _slot, _gap, requisition, _locum, case1 = _setup_failed_case()
    validate_success(api.fail_case(case1["id"], "license mismatch", CRED))

    second = create_locum_physician("Dr Locum Two")
    sourced = validate_success(
        api.propose_candidate(requisition["id"], second["id"], ADMIN)
    )
    assert sourced["status"] == "SOURCED"
    assert sourced["candidate_physician_id"] == second["id"]

    cred = validate_success(api.begin_credentialing(requisition["id"], CRED))
    assert cred["status"] == "CREDENTIALING"

    cases, _meta = validate_paginated(
        api.list_cases(CRED, params={"requisition_id": requisition["id"]})
    )
    assert len(cases) == 2
    by_id = {c["id"]: c for c in cases}
    assert by_id[case1["id"]]["status"] == "FAILED"
    new_case = next(c for c in cases if c["id"] != case1["id"])
    assert new_case["status"] == "INITIATED"
    assert new_case["locum_physician_id"] == second["id"]


# ─── Checklist item guards ───────────────────────────────────────────

def test_privileges_granting_before_license_rejected(api):
    """PRD §3.5: "`privileges_granting` additionally requires
    `license_verification` to be completed first
    (`ERR_PREREQUISITE_ITEM_INCOMPLETE`)".

    Design: Corner/validations/privileges_granting_before_license_rejected
    """
    _program, _slot, _gap, _req, _locum, case = setup_credentialing_case()
    resp = api.complete_item(case["id"], "privileges_granting", CRED)
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_ITEM_INCOMPLETE, 409)
    after = validate_success(api.get_case(case["id"], CRED))
    assert after["status"] == "INITIATED"
    assert all(v.get("completed_at") is None for v in after["items"].values())


def test_duplicate_item_completion_rejected(api):
    """PRD §3.5: "an item already completed is rejected with
    `ERR_ITEM_ALREADY_COMPLETED`."

    Design: Corner/validations/duplicate_item_completion_rejected
    """
    _program, _slot, _gap, _req, _locum, case = setup_credentialing_case()
    complete_item(case["id"], "license_verification")
    resp = api.complete_item(case["id"], "license_verification", CRED)
    validate_error(resp, ApiErrorId.ERR_ITEM_ALREADY_COMPLETED, 409)
    after = validate_success(api.get_case(case["id"], CRED))
    assert after["status"] == "IN_PROGRESS"
    completed = [
        name for name, v in after["items"].items() if v.get("completed_at") is not None
    ]
    assert completed == ["license_verification"]


# ─── Deadline and expiry ─────────────────────────────────────────────

def test_expire_before_clear_by_rejected(api):
    """PRD §3.5: "Expiring a case requires the same active phases and
    additionally that the logical clock be strictly past `clear_by` (at or
    before the deadline, `ERR_CREDENTIALING_NOT_EXPIRED`)".

    With the clock at its 2026-08-01T00:00:00Z startup default and clear_by at
    2026-09-03T07:00:00Z, expiry is not yet available.

    Design: Corner/validations/expire_before_clear_by_rejected
    """
    _program, _slot, _gap, _req, _locum, case = setup_credentialing_case()
    resp = api.expire_case(case["id"], CRED)
    validate_error(resp, ApiErrorId.ERR_CREDENTIALING_NOT_EXPIRED, 409)
    after = validate_success(api.get_case(case["id"], CRED))
    assert after["status"] == "INITIATED"


def test_complete_item_after_deadline_then_expire_succeeds(api):
    """PRD §3.5: "the logical clock must be at or before `clear_by` — exactly at
    the deadline is permitted, later is `ERR_CREDENTIALING_DEADLINE_PASSED`";
    "Expiring a case requires the same active phases and additionally that the
    logical clock be strictly past `clear_by` ... moving it to EXPIRED."
    PRD §3.5: "Both outcomes re-open the requisition from CREDENTIALING to
    OPEN, clear its `candidate_physician_id` to null, and leave the gap
    REQUISITIONED".

    clear_by is 2026-09-03T07:00:00Z; the clock is set to 2026-09-04T00:00:00Z.

    Design: Corner/validations/complete_item_after_deadline_then_expire_succeeds
    """
    _program, _slot, gap, requisition, _locum, case = setup_credentialing_case()
    set_clock("2026-09-04T00:00:00Z")

    resp = api.complete_item(case["id"], "license_verification", CRED)
    validate_error(resp, ApiErrorId.ERR_CREDENTIALING_DEADLINE_PASSED, 409)
    after_reject = validate_success(api.get_case(case["id"], CRED))
    assert all(
        v.get("completed_at") is None for v in after_reject["items"].values()
    ), "the rejected completion must not stamp any item"

    expired = validate_success(api.expire_case(case["id"], CRED))
    assert expired["status"] == "EXPIRED"

    req_after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert req_after["status"] == "OPEN"
    assert req_after["candidate_physician_id"] is None
    gap_after = validate_success(api.get_gap(gap["id"], ADMIN))
    assert gap_after["status"] == "REQUISITIONED"


def test_complete_item_on_failed_case_returns_case_not_active(api):
    """PRD §3.5: "the case must be INITIATED or IN_PROGRESS
    (`ERR_CASE_NOT_ACTIVE`)".

    Design: Corner/errors/complete_item_on_failed_case_returns_case_not_active
    """
    _program, _slot, _gap, _req, _locum, case = setup_credentialing_case()
    validate_success(api.fail_case(case["id"], "license mismatch", CRED))
    resp = api.complete_item(case["id"], "license_verification", CRED)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ACTIVE, 409)
    after = validate_success(api.get_case(case["id"], CRED))
    assert after["status"] == "FAILED"


# ─── Terminal lockdown on FILLED requisitions ────────────────────────

def test_cancel_filled_requisition_returns_not_cancellable(api):
    """PRD §3.5: "A `SchedulerAdmin` may cancel a requisition from OPEN,
    SOURCED, or CREDENTIALING — any other phase is
    `ERR_REQUISITION_NOT_CANCELLABLE`."

    Design: Corner/errors/cancel_filled_requisition_returns_not_cancellable
    """
    _program, _slot, _gap, requisition, _locum, _case = setup_filled_requisition()
    resp = api.cancel_requisition(requisition["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_CANCELLABLE, 409)

    req_after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert req_after["status"] == "FILLED"
    fills = list_assignments(source_requisition_id=requisition["id"])
    assert len(fills) == 1
    assert fills[0]["status"] == "SCHEDULED", "the auto-fill assignment is untouched"


# ─── Transitive cascade: completion auto-fill ────────────────────────

def test_credentialing_completion_autofill_cascade_statuses(api):
    """PRD §3.5: "the fifth and final item moves it IN_PROGRESS → CLEARED,
    firing the auto-fill cascade in the same breath: the requisition advances
    CREDENTIALING → READY → FILLED, with READY transient inside the cascade; a
    CallAssignment is created for the candidate with `origin` LOCUM_FILL,
    `source_requisition_id` set, SCHEDULED status, and projected pay computed;
    the slot moves OPEN → ASSIGNED; the gap becomes RESOLVED with
    `resolved_by_assignment_id` set; and the reserve increases by the new
    projected pay".

    Design: Difficulty/transitive_cascade/credentialing_completion_autofill_cascade
    """
    program, slot, gap, requisition, _locum, case = setup_credentialing_case()
    for item in (
        "license_verification",
        "malpractice_verification",
        "privileges_granting",
        "health_screening",
    ):
        complete_item(case["id"], item)

    resp = api.complete_item(case["id"], "orientation", CRED)
    cleared = validate_success(resp, 200)
    assert_credentialing_case(cleared)
    assert cleared["status"] == "CLEARED"

    req_after = validate_success(api.get_requisition(requisition["id"], ADMIN))
    assert req_after["status"] == "FILLED"

    fills = list_assignments(source_requisition_id=requisition["id"])
    assert len(fills) == 1
    gap_after = validate_success(api.get_gap(gap["id"], ADMIN))
    assert gap_after["status"] == "RESOLVED"
    assert gap_after["resolved_by_assignment_id"] == fills[0]["id"]

    slot_after = validate_success(api.get_slot(slot["id"], ADMIN))
    assert slot_after["status"] == "ASSIGNED"


def test_credentialing_autofill_assignment_and_reserve(api):
    """PRD §3.5: "a CallAssignment is created for the candidate with `origin`
    LOCUM_FILL, `source_requisition_id` set, SCHEDULED status, and projected
    pay computed; ... and the reserve increases by the new projected pay".
    PRD §2.9: "LOCUM physicians are exempt from both the cap and the premium."

    The auto-fill pays the weekday primary base (50000) with no premium.

    Design: Difficulty/transitive_cascade/credentialing_completion_autofill_cascade
    """
    program, _slot, _gap, requisition, locum, case = setup_credentialing_case()
    for item in (
        "license_verification",
        "malpractice_verification",
        "privileges_granting",
        "health_screening",
        "orientation",
    ):
        complete_item(case["id"], item)

    fills = list_assignments(source_requisition_id=requisition["id"])
    assert len(fills) == 1
    fill = fills[0]
    assert fill["origin"] == "LOCUM_FILL"
    assert fill["source_requisition_id"] == requisition["id"]
    assert fill["physician_id"] == locum["id"]
    assert fill["status"] == "SCHEDULED"
    assert fill["projected_pay_cents"] == 50000

    program_after = get_program(program["id"])
    assert program_after["payroll_reserved_cents"] == 50000
