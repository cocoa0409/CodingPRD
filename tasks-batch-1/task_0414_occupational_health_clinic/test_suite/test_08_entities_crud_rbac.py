"""Entity CRUD, defaults, computed/system fields, FK integrity, listing, validation-priority
ordering, not-found errors, RBAC denials, and the OCC positive path. Pure breadth coverage
translated from the corner-design index (sections: entities, validations, endpoints, errors,
rbac, cross_cutting_complexity_layers).
"""
from test_helpers import (
    validate_error, validate_success, validate_paginated, get_success_data,
    is_valid_uuid, NON_EXISTENT_UUID,
    TEST_USERS, ApiErrorId, panel, build_user_headers,
    create_employer, create_draft_protocol, create_worker,
    setup_employer_with_active_protocol, setup_issued_invoice,
    setup_employer_with_n_completed_physicals, complete_physical_encounter,
    setup_checked_in_encounter,
    create_employer_payload, create_protocol_payload, create_worker_payload,
    create_clearance_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]
COLLECTOR = TEST_USERS["collector_headers"]
MRO = TEST_USERS["mro_headers"]


# ─── Employer CRUD / defaults / system fields ─────────

def test_create_employer_returns_201_with_prospect_status(api):
    """PRD §3.1: "A freshly created employer starts in `PROSPECT` status with `account_status` set
    accordingly, a zero `outstanding_balance_cents`, and the version-tracked audit fields."

    Design: Corner/entities/create_employer_returns_201_with_prospect_status
    """
    out = validate_success(api.create_employer(
        create_employer_payload(legal_name="Acme Co", dot_regulated=False, mro_user_id="mro-1",
                                net_terms_days=30), ADMIN), 201)
    assert out["account_status"] == "PROSPECT"
    assert out["version"] == 1
    assert out["legal_name"] == "Acme Co"
    assert out["mro_user_id"] == "mro-1"


def test_get_employer_returns_stored_entity(api):
    """PRD §2.5: "When an endpoint path contains a resource identifier, the system validates it
    before doing any work, returning the resource-specific not-found error ... when it does not
    exist."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return
    the created or updated resource object in the data field."

    Design: Corner/entities/get_employer_returns_stored_entity
    """
    emp = create_employer(legal_name="Beta Co")
    out = validate_success(api.get_employer(emp["id"], ADMIN))
    assert out["id"] == emp["id"]
    assert out["legal_name"] == "Beta Co"


def test_list_employers_returns_pagination_envelope(api):
    """PRD §2.3: "The response envelope's `meta` object carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more` for every list response."

    Design: Corner/entities/list_employers_returns_pagination_envelope
    """
    create_employer(legal_name="Emp One")
    create_employer(legal_name="Emp Two")
    data, meta = validate_paginated(api.list_employers(ADMIN))
    assert meta["total_count"] >= 2
    assert "has_more" in meta
    assert isinstance(data, list)


def test_get_employer_nonexistent_returns_not_found(api):
    """PRD §2.5: "returning the resource-specific not-found error (for example
    `ERR_EMPLOYER_NOT_FOUND` ...) when it does not exist."

    Design: Corner/entities/get_employer_nonexistent_returns_employer_not_found
    """
    resp = api.get_employer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_FOUND.value)


def test_create_employer_missing_legal_name_returns_invalid_request(api):
    """PRD §3.1: "The lifecycle begins when a `ClinicAdmin` opens an **Employer** account by
    supplying the employer's `legal_name`, the operator id of the Medical Review Officer who will
    adjudicate this employer's regulated drug screens as `mro_user_id`".
    PRD §2.6: request-body well-formedness "covers missing required fields".

    Design: Corner/entities/create_employer_missing_legal_name_returns_invalid_request
    """
    resp = api.create_employer({"mro_user_id": "mro-1"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_employer_omits_optional_defaults_applied(api):
    """PRD §3.1: "optionally a `dot_regulated` flag (defaulting to false ...), the invoice payment
    terms `net_terms_days` (defaulting to 30), and an initial `current_date` (defaulting to
    1970-01-01)."

    Design: Corner/entities/create_employer_omits_optional_defaults_applied
    """
    out = validate_success(api.create_employer(
        {"legal_name": "Default Co", "mro_user_id": "mro-1"}, ADMIN), 201)
    assert out["dot_regulated"] is False
    assert out["net_terms_days"] == 30
    assert out["current_date"] == "1970-01-01"
    assert out["outstanding_balance_cents"] == 0


def test_employer_outstanding_balance_computed_default_zero(api):
    """PRD §3.1: "A freshly created employer starts in `PROSPECT` status with `account_status` set
    accordingly, a zero `outstanding_balance_cents`, and the version-tracked audit fields."

    Design: Corner/entities/employer_outstanding_balance_computed_ignores_input
    """
    out = validate_success(api.create_employer(
        {"legal_name": "Comp Co", "mro_user_id": "mro-1"}, ADMIN), 201)
    assert out["outstanding_balance_cents"] == 0


def test_employer_system_fields_generated(api):
    """PRD §3.1: "A freshly created employer starts in `PROSPECT` status with `account_status` set
    accordingly, a zero `outstanding_balance_cents`, and the version-tracked audit fields."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/employer_system_fields_generated_input_ignored
    """
    out = validate_success(api.create_employer(
        {"legal_name": "Sys Co", "mro_user_id": "mro-1"}, ADMIN), 201)
    assert out["account_status"] == "PROSPECT"
    assert out["version"] == 1
    assert is_valid_uuid(out["id"])


# ─── Protocol type constraints ────────────────────────

def test_create_protocol_invalid_panel_enum_returns_invalid_request(api):
    """PRD §3.1: "Each panel is an object naming a `panel_code` (one of `PHYSICAL`, `DRUG_DOT`,
    `DRUG_NON_DOT`, `AUDIOMETRIC`, or `RESPIRATOR_FIT`)".
    PRD §2.6: request-body well-formedness "covers ... invalid enum values".

    Design: Corner/entities/create_protocol_invalid_panel_enum_returns_invalid_request
    """
    emp = create_employer(legal_name="Enum Co")
    resp = api.create_protocol(create_protocol_payload(
        emp["id"], [panel("XRAY", "OP", 100, 0)]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_protocol_negative_price_returns_invalid_request(api):
    """PRD §3.1: "a `price_cents` amount (which must be zero or greater)".
    PRD §2.6: request-body well-formedness "covers ... negative numbers where non-negative is
    required".

    Design: Corner/entities/create_protocol_negative_price_returns_invalid_request
    """
    emp = create_employer(legal_name="Neg Co")
    resp = api.create_protocol(create_protocol_payload(
        emp["id"], [panel("PHYSICAL", "OP", -5, 0)]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Worker creation / FK integrity ───────────────────

def test_worker_initial_hire_status_is_candidate(api):
    """PRD §3.3: "A new **Worker** starts with `hire_status` of `CANDIDATE`".

    Design: Corner/entities/worker_initial_hire_status_is_candidate
    """
    emp = create_employer(legal_name="Init Co")
    out = validate_success(api.create_worker(
        create_worker_payload(emp["id"], full_name="New Hire", job_category="OP"), ADMIN), 201)
    assert out["hire_status"] == "CANDIDATE"


def test_create_worker_wrong_employer_parent_returns_cross_employer(api):
    """PRD §2.5: "A body reference that is missing or that crosses employer boundaries is rejected
    with `ERR_CROSS_EMPLOYER_REFERENCE` (HTTP 404)."

    Design: Corner/entities/create_worker_wrong_employer_parent_returns_not_found
    """
    resp = api.create_worker(
        create_worker_payload(NON_EXISTENT_UUID, full_name="Ghost", job_category="OP"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CROSS_EMPLOYER_REFERENCE.value)


def test_encounter_worker_belongs_to_other_employer_returns_cross_employer(api):
    """PRD §2.5: "a referenced resource must exist and must belong to the same employer aggregate
    as the rest of the body — a worker must belong to the body's employer ... A body reference
    that is missing or that crosses employer boundaries is rejected with
    `ERR_CROSS_EMPLOYER_REFERENCE` (HTTP 404)."

    Design: Corner/entities/encounter_worker_belongs_to_other_employer_returns_cross_employer
    """
    empA, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)],
                                                  legal_name="Emp A")
    empB = create_employer(legal_name="Emp B")
    wkrB = create_worker(empB["id"], job_category="OP")
    resp = api.create_encounter(
        {"employer_id": empA["id"], "worker_id": wkrB["id"],
         "encounter_type": "PHYSICAL", "panel_code": "PHYSICAL"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_CROSS_EMPLOYER_REFERENCE.value)


def test_list_workers_filtered_by_employer_id(api):
    """PRD §2.5: "Children are discovered through filtered list endpoints rather than nested
    routes."

    Design: Corner/entities/list_workers_filtered_by_employer_id_reverse_reachability
    """
    emp = create_employer(legal_name="Filt Co")
    wkr = create_worker(emp["id"], full_name="Solo Worker", job_category="OP")
    data, meta = validate_paginated(api.list_workers(ADMIN, params={"employer_id": emp["id"]}))
    assert meta["total_count"] == 1
    assert all(w["employer_id"] == emp["id"] for w in data)


# ─── Endpoint listing / reverse reachability ──────────

def test_list_drug_screens_filtered_by_encounter(api):
    """PRD §2.5: "A drug screen carries the `encounter_id` of its owning encounter ... Children
    are discovered through filtered list endpoints rather than nested routes."

    Design: Corner/endpoints/list_drug_screens_filtered_by_encounter_reverse_reachability
    """
    from test_helpers import setup_drug_screen
    emp, wkr, enc, ds = setup_drug_screen(specimen_seal_intact=True)
    data, meta = validate_paginated(api.list_drug_screens(ADMIN, params={"encounter_id": enc["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == ds["id"]
    assert data[0]["encounter_id"] == enc["id"]


def test_list_invoices_filtered_by_status(api):
    """PRD §4: "GET `/clinic/invoices` List invoices (filter by employer, status)".
    PRD §3.13: "A `ClinicAdmin` creates a **DRAFT Invoice** for an employer over a billing period".

    Design: Corner/endpoints/list_invoices_filtered_by_status
    """
    emp, wkr, encs = setup_employer_with_n_completed_physicals(1, price_cents=9000,
                                                               current_date="2026-03-15")
    from test_helpers import create_draft_invoice
    inv = create_draft_invoice(emp["id"])
    data, meta = validate_paginated(api.list_invoices(
        ADMIN, params={"employer_id": emp["id"], "status": "DRAFT"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == inv["id"]
    assert data[0]["status"] == "DRAFT"


# ─── Validation priority ordering ─────────────────────

def test_auth_outranks_existence_missing_headers(api):
    """PRD §2.6: "The order is: first, user-context authentication
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT`, 401); ... third, existence of every resource named in
    the path".

    Design: Corner/validations/auth_outranks_existence_missing_headers_on_missing_resource
    """
    resp = api.get_employer(NON_EXISTENT_UUID, {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)


def test_authz_outranks_existence_wrong_role(api):
    """PRD §2.6: "second, role authorization (`ERR_INSUFFICIENT_PERMISSIONS`, 403); third,
    existence of every resource named in the path (the resource-specific not-found errors, 404)".

    Design: Corner/validations/authz_outranks_existence_wrong_role_on_missing_resource
    """
    resp = api.suspend_employer(NON_EXISTENT_UUID, COLLECTOR)  # Collector cannot suspend
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_existence_outranks_body_shape(api):
    """PRD §2.6: "third, existence of every resource named in the path (the resource-specific
    not-found errors, 404) ... fifth, request-body well-formedness (`ERR_INVALID_REQUEST`, 400)".

    Design: Corner/validations/existence_outranks_body_shape_missing_resource_with_bad_body
    """
    resp = api.record_lab_result(NON_EXISTENT_UUID, {"lab_result": "BOGUS"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_DRUG_SCREEN_NOT_FOUND.value)


def test_state_outranks_business_referential_on_completed_encounter(api):
    """PRD §3.3: "Check-in requires the encounter to be `SCHEDULED` (otherwise
    `ERR_ENCOUNTER_NOT_SCHEDULED`)".
    PRD §2.6: "seventh, the target resource's state precondition for the requested transition (the
    `ERR_..._NOT_...` state errors, 409). Business-rule checks specific to an operation ... are
    evaluated after these foundational layers".

    Design: Corner/validations/state_outranks_job_category_mismatch_on_completed_encounter
    """
    emp, wkr, enc, clr = complete_physical_encounter(determination="FIT")
    resp = api.check_in_encounter(enc["id"], CLIN)  # re-check-in a COMPLETED encounter
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_SCHEDULED.value)


# ─── Not-found errors ─────────────────────────────────

def test_surveillance_exam_not_found(api):
    """PRD §2.5: "returning the resource-specific not-found error (for example ...
    `ERR_SURVEILLANCE_EXAM_NOT_FOUND` ...) when it does not exist."

    Design: Corner/errors/error_surveillance_exam_not_found_stub
    """
    resp = api.get_surveillance_exam(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SURVEILLANCE_EXAM_NOT_FOUND.value)


# ─── RBAC denials / shared ops ────────────────────────

def test_clinician_cannot_create_employer_forbidden(api):
    """PRD §2.1: "The `ClinicAdmin` administers employer accounts, protocols, and invoices".
    PRD §2.1: "the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/clinician_cannot_create_employer_forbidden
    """
    resp = api.create_employer(
        create_employer_payload(legal_name="Forbid Co", mro_user_id="mro-1"), CLIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_collector_cannot_issue_clearance_forbidden(api):
    """PRD §2.1: "The `Clinician` runs encounters and clinical results — entering lab results,
    creating injury and surveillance records, and issuing clearances."
    PRD §2.1: "the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/collector_cannot_issue_clearance_forbidden
    """
    emp, wkr, enc = setup_checked_in_encounter(encounter_type="PHYSICAL", panel_code="PHYSICAL")
    resp = api.create_clearance(create_clearance_payload(enc["id"], "FIT"), COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_mro_cannot_schedule_encounter_forbidden(api):
    """PRD §4: "POST `/clinic/encounters` Schedule an encounter; snapshot the active protocol |
    ClinicAdmin, Clinician".
    PRD §2.1: "the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/mro_can_read_but_cannot_schedule_encounter_forbidden
    """
    emp, _ = setup_employer_with_active_protocol(panels=[panel("PHYSICAL", "OP", 9000, 0)])
    wkr = create_worker(emp["id"], job_category="OP")
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "PHYSICAL", "panel_code": "PHYSICAL"}, MRO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ─── OCC positive path ────────────────────────────────

def test_occ_protocol_activate_correct_version_succeeds(api):
    """PRD §2.8: "A request to activate a protocol must carry `expected_employer_version` matching
    the owning employer's current `version`."
    PRD §3.1: "if the employer was in `PROSPECT`, it cascades to `ACTIVE`; and the employer's
    `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_protocol_activate_correct_version_succeeds
    """
    emp = create_employer(legal_name="OccOk Co")
    proto = create_draft_protocol(emp["id"], panels=[panel("PHYSICAL", "OP", 9000, 0)])
    out = validate_success(api.activate_protocol(
        proto["id"], {"expected_employer_version": emp["version"]}, ADMIN))
    assert out["status"] == "ACTIVE"
    emp_after = get_success_data(api.get_employer(emp["id"], ADMIN))
    assert emp_after["version"] == 2
