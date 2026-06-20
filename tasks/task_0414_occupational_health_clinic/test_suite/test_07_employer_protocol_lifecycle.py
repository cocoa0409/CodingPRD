"""Employer account lifecycle, protocol activation cascades, encounter scheduling referential
rules. Translates difficulty queue (priority_pair_validation_conflict /
panel_referential_outranks_dot_constraint) plus corner employer/protocol state-machine and
validation instances.
"""
from test_helpers import (
    validate_error, validate_success, get_success_data,
    TEST_USERS, ApiErrorId, panel,
    setup_employer_with_active_protocol, create_employer, create_draft_protocol,
    create_worker, setup_issued_invoice, schedule_encounter,
    create_protocol_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]


# ─── Panel referential outranks DOT constraint (difficulty) ─

def test_panel_referential_outranks_dot_constraint(api):
    """PRD §3.3: "an `INJURY` carries no panel code, a `PHYSICAL` must use the `PHYSICAL` panel, a
    `DRUG_SCREEN` must use either `DRUG_DOT` or `DRUG_NON_DOT` ... a mismatch or a panel code
    absent from the active protocol is rejected with `ERR_PANEL_NOT_IN_PROTOCOL`."

    Design: Difficulty/priority_pair_validation_conflict/panel_referential_outranks_dot_constraint
    """
    # Non-DOT employer; active protocol has only a DRUG_NON_DOT panel (no DRUG_DOT).
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("DRUG_NON_DOT", "DRIVER", 8000, 0)], dot_regulated=False, legal_name="Kappa")
    wkr = create_worker(emp["id"], job_category="DRIVER")
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "DRUG_SCREEN", "panel_code": "DRUG_DOT"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_PANEL_NOT_IN_PROTOCOL.value)


def test_panel_referential_outranks_dot_constraint_physical_only(api):
    """PRD §3.3: "a `DRUG_SCREEN` must use either `DRUG_DOT` or `DRUG_NON_DOT` ... a mismatch or a
    panel code absent from the active protocol is rejected with `ERR_PANEL_NOT_IN_PROTOCOL`."

    Design: Difficulty/priority_pair_validation_conflict/panel_referential_outranks_dot_constraint
    """
    # Second translation: a non-DOT employer whose protocol holds only a PHYSICAL panel; the
    # DRUG_DOT request is absent from the active protocol -> referential error precedes DOT check.
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "DRIVER", 9000, 0)], dot_regulated=False, legal_name="Kappa2")
    wkr = create_worker(emp["id"], job_category="DRIVER")
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "DRUG_SCREEN", "panel_code": "DRUG_DOT"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_PANEL_NOT_IN_PROTOCOL.value)


# ─── Employer lifecycle (corner) ──────────────────────

def test_employer_suspend_from_active_succeeds(api):
    """PRD §3.2: "An `ACTIVE` employer may be suspended, which sets `account_status` to
    `SUSPENDED` and blocks new encounter scheduling for as long as it lasts; suspension requires
    the employer to be `ACTIVE`, otherwise `ERR_EMPLOYER_NOT_ACTIVE`."

    Design: Corner/state_machines/employer_suspend_from_active_succeeds
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    out = validate_success(api.suspend_employer(emp["id"], ADMIN))
    assert out["account_status"] == "SUSPENDED"


def test_employer_reactivate_when_not_suspended_rejected(api):
    """PRD §3.2: "A `SUSPENDED` employer may be reactivated back to `ACTIVE`; reactivation
    requires the employer to be `SUSPENDED`, otherwise `ERR_EMPLOYER_NOT_SUSPENDED`."

    Design: Corner/state_machines/employer_reactivate_when_not_suspended_rejected
    """
    emp = create_employer(legal_name="React Co")  # PROSPECT, never activated
    resp = api.reactivate_employer(emp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_SUSPENDED.value)


def test_employer_suspend_already_suspended_rejected(api):
    """PRD §3.2: "suspension requires the employer to be `ACTIVE`, otherwise
    `ERR_EMPLOYER_NOT_ACTIVE`."

    Design: Corner/state_machines/employer_suspend_already_suspended_rejected
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    get_success_data(api.suspend_employer(emp["id"], ADMIN))
    resp = api.suspend_employer(emp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_ACTIVE.value)


def test_employer_close_with_outstanding_balance_rejected(api):
    """PRD §3.2: "its `outstanding_balance_cents` must be exactly zero (otherwise
    `ERR_EMPLOYER_HAS_BALANCE`)".

    Design: Corner/state_machines/employer_close_with_outstanding_balance_rejected
    """
    emp, wkr, enc, inv = setup_issued_invoice(price_cents=9000, current_date="2026-03-15")
    resp = api.close_employer(emp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_HAS_BALANCE.value)


def test_employer_close_with_open_encounters_rejected(api):
    """PRD §3.2: "there must be no encounter for the employer in any of the in-flight states
    `SCHEDULED`, `IN_PROGRESS`, or `PENDING_RESULTS` (otherwise `ERR_OPEN_ENCOUNTERS_EXIST`)."

    Design: Corner/state_machines/employer_close_with_open_encounters_rejected
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="OP")
    schedule_encounter(emp["id"], wkr["id"], "PHYSICAL", "PHYSICAL")  # SCHEDULED, balance 0
    resp = api.close_employer(emp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_ENCOUNTERS_EXIST.value)


def test_employer_close_clean_succeeds_from_suspended(api):
    """PRD §3.2: "The employer must be either `ACTIVE` or `SUSPENDED` (otherwise
    `ERR_EMPLOYER_NOT_CLOSABLE`) ... When all three hold, `account_status` becomes `CLOSED`, which
    is terminal."

    Design: Corner/state_machines/employer_close_clean_succeeds_from_suspended
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    get_success_data(api.suspend_employer(emp["id"], ADMIN))
    out = validate_success(api.close_employer(emp["id"], ADMIN))
    assert out["account_status"] == "CLOSED"


def test_error_employer_not_closable_from_prospect(api):
    """PRD §3.2: "The employer must be either `ACTIVE` or `SUSPENDED` (otherwise
    `ERR_EMPLOYER_NOT_CLOSABLE`)".

    Design: Corner/errors/error_employer_not_closable_from_prospect
    """
    emp = create_employer(legal_name="NotClos Co")  # PROSPECT
    resp = api.close_employer(emp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_CLOSABLE.value)


# ─── Protocol lifecycle (corner) ──────────────────────

def test_protocol_activate_empty_panels_rejected(api):
    """PRD §3.1: "Before activation succeeds, the protocol's panels must be non-empty (otherwise
    `ERR_PROTOCOL_EMPTY_PANELS`)".

    Design: Corner/state_machines/protocol_activate_empty_panels_rejected
    """
    emp = create_employer(legal_name="EmptyP Co")
    proto = create_draft_protocol(emp["id"], panels=[])
    resp = api.activate_protocol(proto["id"], {"expected_employer_version": emp["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROTOCOL_EMPTY_PANELS.value)


def test_protocol_activate_duplicate_panel_code_rejected(api):
    """PRD §3.1: "no `panel_code` may appear more than once in the panel list (otherwise
    `ERR_DUPLICATE_PANEL_CODE`)".

    Design: Corner/state_machines/protocol_activate_duplicate_panel_code_rejected
    """
    emp = create_employer(legal_name="Dup Co")
    proto = create_draft_protocol(emp["id"], panels=[
        panel("PHYSICAL", "OP", 9000, 0), panel("PHYSICAL", "DRIVER", 8000, 0)])
    resp = api.activate_protocol(proto["id"], {"expected_employer_version": emp["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PANEL_CODE.value)


def test_protocol_activate_dot_employer_missing_dot_panel_rejected(api):
    """PRD §3.1: "if the owning employer is DOT-regulated the panel list must include a `DRUG_DOT`
    panel (otherwise `ERR_DOT_PANEL_REQUIRED`)".

    Design: Corner/state_machines/protocol_activate_dot_employer_missing_dot_panel_rejected
    """
    emp = create_employer(legal_name="Dot Co", dot_regulated=True)
    proto = create_draft_protocol(emp["id"], panels=[panel("PHYSICAL", "DRIVER", 9000, 0)])
    resp = api.activate_protocol(proto["id"], {"expected_employer_version": emp["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DOT_PANEL_REQUIRED.value)


def test_protocol_activate_retires_prior_active_cascade(api):
    """PRD §3.1: "any other protocol for the same employer that was `ACTIVE` is cascaded to
    `RETIRED` ... At most one protocol per employer may be `ACTIVE` at any time."

    Design: Corner/state_machines/protocol_activate_retires_prior_active_cascade
    """
    emp, p1 = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)],
                                                  legal_name="Retire Co")
    emp_v1 = get_success_data(api.get_employer(emp["id"], ADMIN))
    p2 = create_draft_protocol(emp["id"], panels=[panel("PHYSICAL", "OP", 11000, 0)])
    out = validate_success(api.activate_protocol(
        p2["id"], {"expected_employer_version": emp_v1["version"]}, ADMIN))
    assert out["status"] == "ACTIVE"
    p1_after = get_success_data(api.get_protocol(p1["id"], ADMIN))
    assert p1_after["status"] == "RETIRED"


def test_protocol_activate_prospect_to_active_employer_cascade(api):
    """PRD §3.1: "if the employer was in `PROSPECT`, it cascades to `ACTIVE`; and the employer's
    `version` increments by one."

    Design: Corner/state_machines/protocol_activate_prospect_to_active_employer_cascade
    """
    emp = create_employer(legal_name="Pros Co")
    proto = create_draft_protocol(emp["id"], panels=[panel("PHYSICAL", "OP", 9000, 0)])
    out = validate_success(api.activate_protocol(
        proto["id"], {"expected_employer_version": emp["version"]}, ADMIN))
    assert out["status"] == "ACTIVE"
    emp_after = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert emp_after["account_status"] == "ACTIVE"
    assert emp_after["version"] == 2


def test_protocol_activate_when_not_draft_rejected(api):
    """PRD §3.1: "Activation is permitted only when the protocol is currently `DRAFT`; otherwise
    it is rejected with `ERR_PROTOCOL_NOT_DRAFT`."

    Design: Corner/state_machines/protocol_activate_when_not_draft_rejected
    """
    emp, p1 = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)],
                                                  legal_name="NotDraft Co")
    emp_v1 = get_success_data(api.get_employer(emp["id"], ADMIN))
    resp = api.activate_protocol(p1["id"], {"expected_employer_version": emp_v1["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_DRAFT.value)


# ─── Encounter creation referential rules (corner validations) ─

def test_encounter_panel_type_mismatch_injury_with_panel_code_rejected(api):
    """PRD §3.3: "For an `INJURY` encounter the `panel_code` must be omitted." and "a mismatch or
    a panel code absent from the active protocol is rejected with `ERR_PANEL_NOT_IN_PROTOCOL`."

    Design: Corner/validations/encounter_panel_type_mismatch_injury_with_panel_code_rejected
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="OP")
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "INJURY", "panel_code": "PHYSICAL"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_PANEL_NOT_IN_PROTOCOL.value)


def test_encounter_job_category_panel_mismatch_rejected(api):
    """PRD §3.3: "For every non-injury encounter, the worker's `job_category` must match the
    chosen panel's `required_for_job_category`, or the request is rejected with
    `ERR_JOB_CATEGORY_PANEL_MISMATCH`".

    Design: Corner/validations/encounter_job_category_panel_mismatch_rejected
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="DRIVER")  # panel requires OP
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "PHYSICAL", "panel_code": "PHYSICAL"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_JOB_CATEGORY_PANEL_MISMATCH.value)


def test_dot_drug_screen_on_dot_employer_succeeds(api):
    """PRD §3.3: "A `DRUG_DOT` encounter may only be scheduled when the employer's `dot_regulated`
    is true".

    Design: Corner/validations/dot_drug_screen_on_dot_employer_succeeds
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("DRUG_DOT", "DRIVER", 12000, 0)], dot_regulated=True, legal_name="DotOk Co")
    wkr = create_worker(emp["id"], job_category="DRIVER")
    out = validate_success(api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "DRUG_SCREEN", "panel_code": "DRUG_DOT"}, CLIN), 201)
    assert out["status"] == "SCHEDULED"
    assert out["panel_code"] == "DRUG_DOT"


# ─── Clock endpoint (corner endpoints) ────────────────

def test_clock_set_advances_current_date_and_bumps_version(api):
    """PRD §2.10: "the system assigns that date to the employer's `current_date`, then runs the
    overdue re-evaluation described in §2.7 across that employer's invoices and increments the
    employer's `version`."

    Design: Corner/endpoints/clock_set_advances_employer_current_date_and_bumps_version
    """
    emp = create_employer(legal_name="Clk Co")  # version 1, no invoices
    out = validate_success(api.set_clock({"employer_id": emp["id"], "to_iso8601": "2026-06-19"}, ADMIN))
    assert out["current_date"] == "2026-06-19"
    assert out["version"] == 2
