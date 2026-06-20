"""Encounter completion / void cascades, hire_status, clearance lifecycle, check-in guard.
Translates difficulty queue (transitive_cascade / void_rescinds_clearance_reverts_hire_status,
compensating_invariant / complete_then_void_conserves_hire_status,
cross_entity_state_dependency / checkin_requires_employer_active) plus corner encounter,
clearance, and consistency-model instances.
"""
from test_helpers import (
    validate_error, validate_success, get_success_data,
    TEST_USERS, ApiErrorId, panel,
    setup_checked_in_encounter, complete_physical_encounter, issue_clearance,
    create_clearance_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]


# ─── Transitive cascade: void -> rescind -> hire revert ─

def test_void_rescinds_clearance_reverts_hire_status(api):
    """PRD §3.4: "Voiding sets `status` to `VOIDED`, resets `billable_amount_cents` to 0,
    cascades any `ISSUED` clearance on the encounter to `RESCINDED`, and — as a transitive
    consequence of that rescission — reverts the worker's `hire_status` to `CANDIDATE` if it had
    been set from the clearance now being rescinded."

    Design: Difficulty/transitive_cascade/void_rescinds_clearance_reverts_hire_status
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT")
    voided = get_success_data(api.void_encounter(enc["id"], ADMIN))
    clr_after = get_success_data(api.get_clearance(clr["id"], ADMIN))
    wkr_after = get_success_data(api.get_worker(wkr["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert clr_after["status"] == "RESCINDED"
    assert wkr_after["hire_status"] == "CANDIDATE"


def test_void_resets_billable_amount_to_zero(api):
    """PRD §3.9: "On a void, the encounter's `billable_amount_cents` is reset to 0."
    PRD §3.4: "Voiding sets `status` to `VOIDED`, resets `billable_amount_cents` to 0, cascades
    any `ISSUED` clearance on the encounter to `RESCINDED`".

    Design: Difficulty/transitive_cascade/void_rescinds_clearance_reverts_hire_status
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT", price_cents=9000)
    assert enc["billable_amount_cents"] == 9000
    voided = get_success_data(api.void_encounter(enc["id"], ADMIN))
    assert voided["billable_amount_cents"] == 0
    clr_after = get_success_data(api.get_clearance(clr["id"], ADMIN))
    assert clr_after["status"] == "RESCINDED"


# ─── Compensating invariant: complete-then-void conserves hire_status ─

def test_complete_then_void_conserves_hire_status(api):
    """PRD §3.4: "When an encounter reaches `COMPLETED`, ... a `FIT` determination sets the worker
    to `CLEARED`".
    PRD §3.4: "as a transitive consequence of that rescission — reverts the worker's `hire_status`
    to `CANDIDATE` if it had been set from the clearance now being rescinded."

    Design: Difficulty/compensating_invariant/complete_then_void_conserves_hire_status
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT")
    cleared = get_success_data(api.get_worker(wkr["id"], ADMIN))
    assert cleared["hire_status"] == "CLEARED"  # forward action observed
    get_success_data(api.void_encounter(enc["id"], ADMIN))
    restored = get_success_data(api.get_worker(wkr["id"], ADMIN))
    assert restored["hire_status"] == "CANDIDATE"  # compensated back to pre-complete value


def test_complete_then_void_clearance_and_encounter_terminal(api):
    """PRD §3.4: "Voiding sets `status` to `VOIDED`, resets `billable_amount_cents` to 0, cascades
    any `ISSUED` clearance on the encounter to `RESCINDED`".

    Design: Difficulty/compensating_invariant/complete_then_void_conserves_hire_status
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT")
    voided = get_success_data(api.void_encounter(enc["id"], ADMIN))
    clr_after = get_success_data(api.get_clearance(clr["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert clr_after["status"] == "RESCINDED"
    wkr_after = get_success_data(api.get_worker(wkr["id"], ADMIN))
    assert wkr_after["hire_status"] == "CANDIDATE"


# ─── Cross-entity check-in guard (difficulty) ─────────

def test_checkin_requires_employer_active(api):
    """PRD §3.3: "Check-in requires the encounter to be `SCHEDULED` (otherwise
    `ERR_ENCOUNTER_NOT_SCHEDULED`) and the employer to be `ACTIVE` (otherwise
    `ERR_EMPLOYER_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_employer_active
    """
    emp, _ = (None, None)
    from test_helpers import setup_employer_with_active_protocol, create_worker, schedule_encounter
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="OP")
    enc = schedule_encounter(emp["id"], wkr["id"], "PHYSICAL", "PHYSICAL")
    # Suspend the employer between scheduling and check-in.
    get_success_data(api.suspend_employer(emp["id"], ADMIN))
    resp = api.check_in_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_ACTIVE.value)


def test_checkin_blocked_after_employer_suspended_second(api):
    """PRD §3.3: "Check-in requires the encounter to be `SCHEDULED` (otherwise
    `ERR_ENCOUNTER_NOT_SCHEDULED`) and the employer to be `ACTIVE` (otherwise
    `ERR_EMPLOYER_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_employer_active
    """
    # Second translation: a DRUG_SCREEN encounter scheduled, then employer suspended.
    from test_helpers import setup_employer_with_active_protocol, create_worker, schedule_encounter
    emp, _ = setup_employer_with_active_protocol(panels=[panel("DRUG_NON_DOT", "PACKER", 8000, 0)])
    wkr = create_worker(emp["id"], job_category="PACKER")
    enc = schedule_encounter(emp["id"], wkr["id"], "DRUG_SCREEN", "DRUG_NON_DOT")
    get_success_data(api.suspend_employer(emp["id"], ADMIN))
    resp = api.check_in_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_ACTIVE.value)


# ─── Corner encounter lifecycle ───────────────────────

def test_encounter_created_initial_state_scheduled(api):
    """PRD §3.3: "At scheduling time the system snapshots the employer's currently `ACTIVE`
    protocol onto the encounter as `protocol_id`, pins the scheduling clinician's identity as
    `clinician_user_id`, and sets the encounter `status` to `SCHEDULED` with
    `billable_amount_cents` at 0 and `is_billed` false."

    Design: Corner/state_machines/encounter_created_initial_state_scheduled
    """
    from test_helpers import setup_employer_with_active_protocol, create_worker, make_clinician_headers
    emp, p1 = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="OP")
    out = validate_success(api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "PHYSICAL", "panel_code": "PHYSICAL"},
        make_clinician_headers("clin-1")), 201)
    assert out["status"] == "SCHEDULED"
    assert out["protocol_id"] == p1["id"]
    assert out["clinician_user_id"] == "clin-1"
    assert out["billable_amount_cents"] == 0
    assert out["is_billed"] is False


def test_encounter_checkin_when_not_scheduled_rejected(api):
    """PRD §3.3: "Check-in requires the encounter to be `SCHEDULED` (otherwise
    `ERR_ENCOUNTER_NOT_SCHEDULED`)".

    Design: Corner/state_machines/encounter_checkin_when_not_scheduled_rejected
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="PHYSICAL", panel_code="PHYSICAL")
    resp = api.check_in_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_SCHEDULED.value)


def test_physical_encounter_complete_without_clearance_rejected(api):
    """PRD §3.4: "this direct-completion path requires `encounter_type` to be `PHYSICAL`
    (otherwise `ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE`) and requires an `ISSUED` clearance to
    already exist for the encounter (otherwise `ERR_CLEARANCE_REQUIRED`)."

    Design: Corner/state_machines/physical_encounter_complete_without_clearance_rejected
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="PHYSICAL", panel_code="PHYSICAL")
    resp = api.complete_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_REQUIRED.value)


def test_drug_screen_encounter_direct_complete_rejected(api):
    """PRD §3.4: "this direct-completion path requires `encounter_type` to be `PHYSICAL`
    (otherwise `ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE`)".

    Design: Corner/state_machines/drug_screen_encounter_direct_complete_from_in_progress_rejected
    """
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="DRUG_SCREEN", panel_code="DRUG_NON_DOT", job_category="DRIVER",
        panels=[panel("DRUG_NON_DOT", "DRIVER", 8000, 0)])
    resp = api.complete_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE.value)


def test_drug_screen_child_create_bubbles_to_pending_results(api):
    """PRD §3.3: "the act of creating the matching result entity moves the encounter automatically
    from `IN_PROGRESS` to `PENDING_RESULTS`: creating a `DrugScreen` does this for a
    `DRUG_SCREEN` encounter".

    Design: Corner/state_machines/drug_screen_child_create_bubbles_encounter_to_pending_results
    """
    from test_helpers import create_drug_screen_payload, make_clinician_headers
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="DRUG_SCREEN", panel_code="DRUG_NON_DOT", job_category="DRIVER",
        panels=[panel("DRUG_NON_DOT", "DRIVER", 8000, 0)])
    ds = validate_success(api.create_drug_screen(
        create_drug_screen_payload(enc["id"], specimen_seal_intact=True),
        make_clinician_headers("clin-1")), 201)
    assert ds["status"] == "AWAITING_COLLECTION"
    assert ds["is_dot"] is False
    enc_after = get_success_data(api.get_encounter(enc["id"], ADMIN))
    assert enc_after["status"] == "PENDING_RESULTS"


def test_encounter_cancel_from_scheduled_succeeds(api):
    """PRD §3.4: "An encounter may be cancelled by a `Clinician` while it is in `SCHEDULED` or
    `IN_PROGRESS` status (otherwise `ERR_ENCOUNTER_NOT_CANCELLABLE`); cancellation sets the
    `status` to `CANCELLED` and leaves `billable_amount_cents` at 0."

    Design: Corner/state_machines/encounter_cancel_from_scheduled_succeeds
    """
    from test_helpers import setup_employer_with_active_protocol, create_worker, schedule_encounter
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="OP")
    enc = schedule_encounter(emp["id"], wkr["id"], "PHYSICAL", "PHYSICAL")
    out = validate_success(api.cancel_encounter(enc["id"], CLIN))
    assert out["status"] == "CANCELLED"
    assert out["billable_amount_cents"] == 0


def test_encounter_cancel_from_completed_rejected(api):
    """PRD §3.4: "An encounter may be cancelled by a `Clinician` while it is in `SCHEDULED` or
    `IN_PROGRESS` status (otherwise `ERR_ENCOUNTER_NOT_CANCELLABLE`)".

    Design: Corner/state_machines/encounter_cancel_from_completed_rejected
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT")
    resp = api.cancel_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_CANCELLABLE.value)


# ─── Clearance lifecycle ──────────────────────────────

def test_clearance_fit_with_restrictions_missing_text_rejected(api):
    """PRD §3.8: "a `restriction_text` that is required when the determination is
    `FIT_WITH_RESTRICTIONS`."
    PRD §2.6: request-body well-formedness "covers ... a missing `restriction_text` where one is
    mandatory".

    Design: Corner/state_machines/clearance_fit_with_restrictions_missing_text_rejected
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="PHYSICAL", panel_code="PHYSICAL")
    resp = api.create_clearance(
        create_clearance_payload(enc["id"], "FIT_WITH_RESTRICTIONS"), CLIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_clearance_rescind_when_not_issued_rejected(api):
    """PRD §3.8: "rescission requires the clearance to be `ISSUED` (otherwise
    `ERR_CLEARANCE_NOT_ISSUED`)".

    Design: Corner/state_machines/clearance_rescind_when_not_issued_rejected
    """
    # Encounter checked in but NOT completed; clearance issued then rescinded once.
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="PHYSICAL", panel_code="PHYSICAL")
    clr = issue_clearance(enc["id"], "FIT")
    get_success_data(api.rescind_clearance(clr["id"], CLIN))
    resp = api.rescind_clearance(clr["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_ISSUED.value)


# ─── Immediate consistency ────────────────────────────

def test_immediate_consistency_completion_visible(api):
    """PRD §3.4: "When an encounter reaches `COMPLETED`, its `billable_amount_cents` is set per
    the encounter-billing rule ... a `FIT` determination sets the worker to `CLEARED`".

    Design: Corner/consistency_model/immediate_consistency_completion_visible_in_same_response
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT", price_cents=9000)
    assert enc["status"] == "COMPLETED"
    assert enc["billable_amount_cents"] == 9000
    wkr_after = get_success_data(api.get_worker(wkr["id"], ADMIN))
    assert wkr_after["hire_status"] == "CLEARED"
