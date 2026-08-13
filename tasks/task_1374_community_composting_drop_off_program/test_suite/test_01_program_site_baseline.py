"""Baseline: program defaults, not-found, required fields, RBAC denials,
immutable resources, activation preconditions."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_host_agreement_payload,
    create_material_payload,
    create_program_payload,
    create_site_payload,
    get_success_data,
    register_participant_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
OPERATOR = TEST_USERS["route_operator_headers"]
AUDITOR = TEST_USERS["municipal_auditor_headers"]
HOST = TEST_USERS["site_host_headers"]


def test_program_create_applies_defaults(api):
    """PRD §3.1: "Optional tuning knobs accepted at creation are
    `posture_contam_threshold` (the number of open contamination reports at a
    site that forces posture `WATCH`, defaulting to 3, with twice that number
    of severe reports forcing `SUSPENDED`), `posture_complaint_threshold` (the
    number of unresolved complaints in the rolling 14-day window that forces
    `WATCH`, defaulting to 2), and `diversion_credit_rate` (the bucket-credit
    points granted per net kilogram of accepted drop, defaulting to 1.0)."
    PRD §3.1: "A new program starts in `DRAFT` status with its `ops_run_index`
    at 0"

    Design: Corner/entities/program_create_defaults
    """
    resp = api.create_program(
        create_program_payload(name="PD", fiscal_year=2026), ADMIN)
    prog = validate_success(resp, expected_status=201)
    prog_id = prog["id"]

    got = validate_success(api.get_program(prog_id, ADMIN))
    assert got["posture_contam_threshold"] == 3
    assert got["posture_complaint_threshold"] == 2
    assert got["diversion_credit_rate"] == pytest.approx(1.0)
    assert got["status"] == "DRAFT"


def test_get_site_with_unknown_id_returns_not_found(api):
    """PRD §2.5: "The first id that does not exist — or that does not exist
    within the scope established by the ids to its left — produces
    `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/site_not_found_returns_404
    """
    prog = validate_success(api.create_program(
        create_program_payload(name="P", fiscal_year=2026), ADMIN),
        expected_status=201)

    resp = api.get_site(prog["id"], NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_site_create_missing_capacity_kg_rejected(api):
    """PRD §2.9: "A malformed request body, a missing required field, or an
    enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)"
    PRD §3.2: "Creating a site takes a `name`, an `address`, and a
    `capacity_kg`"

    Design: Corner/entities/missing_required_field_returns_invalid_request
    """
    prog = validate_success(api.create_program(
        create_program_payload(name="P", fiscal_year=2026), ADMIN),
        expected_status=201)

    resp = api.create_site(prog["id"], {"name": "S1", "address": "1 A St"},
                           ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_diversion_report_listing_is_read_only_surface(api):
    """PRD §2.4: "`DistributionAllocation` and `DiversionReport` carry only
    `id` and `created_at` — both `updated_at` and `version` are absent on
    them"
    PRD §3.8: "Diversion report listings support `status` and `method` filters
    and are restricted to `ProgramAdmin` and `MunicipalAuditor`."

    Design: Corner/entities/participant_immutable_no_put
    """
    prog = validate_success(api.create_program(
        create_program_payload(name="P", fiscal_year=2026), ADMIN),
        expected_status=201)

    resp = api.list_diversion_reports(prog["id"], AUDITOR)
    data, meta = validate_paginated(resp)
    assert data == [], "fresh program has no diversion reports"
    assert meta["total_count"] == 0


def test_participant_initial_state_is_pending_verify(api):
    """PRD §3.3: "A new participant starts in `PENDING_VERIFY` status, and the
    server mints a `verification_token` at registration."

    Design: Corner/state_machines/participant_initial_state_pending_verify
    """
    from test_helpers import setup_program_with_operational_site
    ids = setup_program_with_operational_site()

    reg = validate_success(api.register_participant(
        ids["prog_id"], register_participant_payload(), ANON),
        expected_status=201)
    assert reg["status"] == "PENDING_VERIFY"


def test_program_activate_requires_operational_site(api):
    """PRD §3.1: "Moving a program from `DRAFT` to `ACTIVE` requires at least
    one site already in `OPERATIONAL` status under the program — otherwise the
    activation is rejected with `ERR_PROGRAM_NO_OPERATIONAL_SITE` (HTTP 409)"

    Design: Corner/state_machines/program_activate_requires_operational_site
    """
    prog = validate_success(api.create_program(
        create_program_payload(name="P", fiscal_year=2026), ADMIN),
        expected_status=201)
    api.create_site(prog["id"], create_site_payload(), ADMIN)
    api.create_material(prog["id"], create_material_payload(), ADMIN)

    resp = api.activate_program(prog["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NO_OPERATIONAL_SITE)


def test_route_operator_cannot_create_program(api):
    """PRD §2.1: "If the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §4: POST /programs is authorized for ProgramAdmin only.

    Design: Corner/rbac/route_operator_cannot_create_program
    """
    resp = api.create_program(
        create_program_payload(name="X", fiscal_year=2026), OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_unrecognized_role_header_rejected(api):
    """PRD §2.1: "If either header is missing, or the role value is not one of
    the recognized roles below, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    from prd_bench_local_runner.testing import build_user_headers
    prog = validate_success(api.create_program(
        create_program_payload(name="P", fiscal_year=2026), ADMIN),
        expected_status=201)

    # Baseline: valid role works
    ok = api.get_program(prog["id"], ADMIN)
    validate_success(ok)

    bad = api.get_program(prog["id"], build_user_headers("x-1", "NotARole"))
    validate_error(bad, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
