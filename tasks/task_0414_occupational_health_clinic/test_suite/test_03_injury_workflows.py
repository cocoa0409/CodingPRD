"""Injury cases, work-status supersession, return-to-work, reopen cycle. Translates difficulty
queue (non_linear_state_machine / injury_case_reopen_cycle, transitive_cascade /
full_duty_workstatus_closes_case_recomputes_osha, resource_temporal_overlap /
work_status_closed_interval_touch_supersedes) plus corner injury/work-status instances.
"""
from test_helpers import (
    validate_error, get_success_data,
    TEST_USERS, ApiErrorId, panel,
    setup_injury_case, add_work_status, setup_checked_in_encounter,
    create_injury_case_payload, create_work_status_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]


# ─── Reopen cycle (non-linear state machine) ──────────

def test_injury_case_reopen_cycle_back_to_open(api):
    """PRD §3.7: "An injury case may be reopened from `CLOSED` back to `OPEN` by a `Clinician`,
    provided the case is `CLOSED` (otherwise `ERR_INJURY_CASE_NOT_CLOSED_FOR_REOPEN`) and the
    parent encounter is not yet `COMPLETED` or `VOIDED` (otherwise `ERR_ENCOUNTER_LOCKED`)".
    PRD §3.7: "from `OPEN` ... a `FULL_DUTY` disposition moves it directly to `CLOSED`".

    Design: Difficulty/non_linear_state_machine/injury_case_reopen_cycle
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="MEDICAL_TREATMENT")
    add_work_status(ic["id"], "FULL_DUTY", "2026-01-10", "2026-01-10")
    closed = get_success_data(api.get_injury_case(ic["id"], ADMIN))
    assert closed["status"] == "CLOSED"
    reopened = get_success_data(api.reopen_injury_case(ic["id"], CLIN))
    assert reopened["status"] == "OPEN"


def test_injury_case_reopen_permits_fresh_work_status(api):
    """PRD §3.7: "each reopen permits a fresh chain of work-status notes."
    PRD §3.7: "from `OPEN`, a `MODIFIED_DUTY` or `OFF_WORK` disposition moves the case to
    `RTW_PENDING`".

    Design: Difficulty/non_linear_state_machine/injury_case_reopen_cycle
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="MEDICAL_TREATMENT")
    add_work_status(ic["id"], "FULL_DUTY", "2026-01-10", "2026-01-10")
    get_success_data(api.reopen_injury_case(ic["id"], CLIN))
    # A fresh OFF_WORK note from the reopened OPEN state moves the case to RTW_PENDING.
    add_work_status(ic["id"], "OFF_WORK", "2026-02-01", "2026-02-05")
    after = get_success_data(api.get_injury_case(ic["id"], ADMIN))
    assert after["status"] == "RTW_PENDING"


def test_injury_case_reopen_when_not_closed_rejected(api):
    """PRD §3.7: "provided the case is `CLOSED` (otherwise
    `ERR_INJURY_CASE_NOT_CLOSED_FOR_REOPEN`)".

    Design: Corner/state_machines/injury_case_reopen_when_not_closed_rejected
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="FIRST_AID")
    resp = api.reopen_injury_case(ic["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_INJURY_CASE_NOT_CLOSED_FOR_REOPEN.value)


def test_error_encounter_locked_on_reopen_completed_parent(api):
    """PRD §3.7: "the parent encounter is not yet `COMPLETED` or `VOIDED` (otherwise
    `ERR_ENCOUNTER_LOCKED`)".

    Design: Corner/errors/error_encounter_locked_on_injury_reopen_completed_parent
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="FIRST_AID")
    add_work_status(ic["id"], "FULL_DUTY", "2026-01-05", "2026-01-05")
    # INJURY needs no clearance; complete the encounter so the parent is COMPLETED.
    get_success_data(api.complete_encounter(enc["id"], CLIN))
    resp = api.reopen_injury_case(ic["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_LOCKED.value)


# ─── Transitive cascade: FULL_DUTY closes + supersedes + OSHA recompute ─

def test_full_duty_closes_case_supersedes_and_recomputes_osha(api):
    """PRD §3.7: "from `RTW_PENDING`, a `FULL_DUTY` disposition moves the case to `CLOSED`."
    PRD §3.11: "Because the intervals are closed, two notes that merely touch at a single boundary
    day — where the existing note's `valid_to` equals the new note's `valid_from` — do overlap,
    and the existing note is superseded."
    PRD §3.10: "otherwise, if `days_restricted` is at least 1 or `treatment_level` is
    `RESTRICTED_DUTY`, the case is recordable and `osha_column` is `RESTRICTED_TRANSFER`".

    Design: Difficulty/transitive_cascade/full_duty_workstatus_closes_case_recomputes_osha
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="RESTRICTED_DUTY",
                                          days_away=0, days_restricted=2)
    ws1 = add_work_status(ic["id"], "MODIFIED_DUTY", "2026-01-05", "2026-01-12",
                          restriction_text="no lifting >10kg")
    # FULL_DUTY note touching ws1 at the boundary day (valid_from == ws1.valid_to) from RTW_PENDING.
    ws2 = add_work_status(ic["id"], "FULL_DUTY", "2026-01-12", "2026-01-20")
    case = get_success_data(api.get_injury_case(ic["id"], ADMIN))
    ws1_after = get_success_data(api.get_work_status(ws1["id"], ADMIN))
    assert case["status"] == "CLOSED"
    assert ws1_after["superseded"] is True
    assert ws2["superseded"] is False
    assert case["osha_column"] == "RESTRICTED_TRANSFER"


def test_full_duty_cascade_supersession_new_note_not_superseded(api):
    """PRD §3.11: "The new note itself is never superseded at the moment it is created."
    PRD §3.7: "Every work-status creation supersedes overlapping prior notes on the same case
    (per §3.11) and triggers recomputation of the case's `is_osha_recordable` and `osha_column`."
    PRD §3.7: "from `RTW_PENDING`, a `FULL_DUTY` disposition moves the case to `CLOSED`."

    Design: Difficulty/transitive_cascade/full_duty_workstatus_closes_case_recomputes_osha
    """
    # Second translation: a later FULL_DUTY note overlapping the prior MODIFIED_DUTY note.
    # From RTW_PENDING only a FULL_DUTY disposition is a defined transition (PRD §3.7); it
    # supersedes the overlapping prior note while the new note itself is never superseded.
    emp, wkr, enc, ic = setup_injury_case(treatment_level="MEDICAL_TREATMENT")
    ws1 = add_work_status(ic["id"], "MODIFIED_DUTY", "2026-01-05", "2026-01-12",
                          restriction_text="light duty")
    ws2 = add_work_status(ic["id"], "FULL_DUTY", "2026-01-12", "2026-01-18")
    ws1_after = get_success_data(api.get_work_status(ws1["id"], ADMIN))
    case = get_success_data(api.get_injury_case(ic["id"], ADMIN))
    assert ws1_after["superseded"] is True
    assert ws2["superseded"] is False
    assert case["status"] == "CLOSED"


# ─── Closed-interval touch supersession (resource_temporal_overlap) ─

def test_work_status_touch_at_endpoint_supersedes(api):
    """PRD §3.11: "Two closed intervals overlap when the existing note's `valid_from` is on or
    before the new note's `valid_to` and the new note's `valid_from` is on or before the existing
    note's `valid_to`. Because the intervals are closed, two notes that merely touch at a single
    boundary day — where the existing note's `valid_to` equals the new note's `valid_from` — do
    overlap, and the existing note is superseded."

    Design: Difficulty/resource_temporal_overlap/work_status_closed_interval_touch_supersedes
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="MEDICAL_TREATMENT")
    ws1 = add_work_status(ic["id"], "MODIFIED_DUTY", "2026-01-05", "2026-01-12",
                          restriction_text="light duty")
    # New note's valid_from (2026-01-12) == ws1.valid_to (2026-01-12): touch at one boundary day.
    # From RTW_PENDING a FULL_DUTY note is the defined transition (PRD §3.7); the closed-interval
    # touch still supersedes the prior note.
    ws2 = add_work_status(ic["id"], "FULL_DUTY", "2026-01-12", "2026-01-20")
    ws1_after = get_success_data(api.get_work_status(ws1["id"], ADMIN))
    assert ws1_after["superseded"] is True
    assert ws2["superseded"] is False


def test_work_status_non_overlapping_not_superseded(api):
    """PRD §3.11: "Two closed intervals overlap when the existing note's `valid_from` is on or
    before the new note's `valid_to` and the new note's `valid_from` is on or before the existing
    note's `valid_to`."

    Design: Difficulty/resource_temporal_overlap/work_status_closed_interval_touch_supersedes
    """
    # Second translation: a strictly later, non-touching note does NOT supersede the earlier one.
    emp, wkr, enc, ic = setup_injury_case(treatment_level="MEDICAL_TREATMENT")
    ws1 = add_work_status(ic["id"], "MODIFIED_DUTY", "2026-01-05", "2026-01-12",
                          restriction_text="light duty")
    # Gap of two days (ws1 ends 01-12, ws2 starts 01-14): intervals do not overlap.
    # From RTW_PENDING a FULL_DUTY note is the defined transition (PRD §3.7); a non-overlapping
    # note does not supersede the earlier one.
    ws2 = add_work_status(ic["id"], "FULL_DUTY", "2026-01-14", "2026-01-20")
    ws1_after = get_success_data(api.get_work_status(ws1["id"], ADMIN))
    assert ws1_after["superseded"] is False
    assert ws2["superseded"] is False


# ─── Corner injury/work-status validations ────────────

def test_injury_case_created_initial_state_open(api):
    """PRD §3.7: "On creation the case starts in `OPEN`, denormalizes its `employer_id`, computes
    its OSHA recordability fields `is_osha_recordable` and `osha_column` (per §3.10)".

    Design: Corner/state_machines/injury_case_created_initial_state_open
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="INJURY", panel_code=None,
                                               panels=[panel("PHYSICAL", "OP", 9000, 0)])
    ic = get_success_data(api.create_injury_case(
        create_injury_case_payload(enc["id"], "FIRST_AID", days_away=0, days_restricted=0), CLIN))
    assert ic["status"] == "OPEN"
    assert ic["is_osha_recordable"] is False
    assert ic["osha_column"] == "NOT_RECORDABLE"


def test_work_status_modified_duty_missing_restriction_rejected(api):
    """PRD §2.6: request-body well-formedness "covers ... a missing `restriction_text` where one
    is mandatory".
    PRD §3.7: "an optional `restriction_text` that is required when the disposition is
    `MODIFIED_DUTY`".

    Design: Corner/state_machines/work_status_modified_duty_missing_restriction_text_rejected
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="MEDICAL_TREATMENT")
    resp = api.create_work_status(
        create_work_status_payload(ic["id"], "MODIFIED_DUTY", "2026-01-05", "2026-01-12"), CLIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_work_status_invalid_interval_from_after_to_rejected(api):
    """PRD §2.6: request-body well-formedness "covers ... an interval whose `valid_from` is later
    than its `valid_to`".

    Design: Corner/state_machines/work_status_invalid_interval_from_after_to_rejected
    """
    emp, wkr, enc, ic = setup_injury_case(treatment_level="FIRST_AID")
    resp = api.create_work_status(
        create_work_status_payload(ic["id"], "FULL_DUTY", "2026-01-20", "2026-01-10"), CLIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
