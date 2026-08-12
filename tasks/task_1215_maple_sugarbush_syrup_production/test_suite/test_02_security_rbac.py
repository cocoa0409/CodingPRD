"""Authentication, role permission, and entity-backed identity (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId,
    activate_crew_member,
    create_bush,
    create_crew_member_payload,
    create_sap_run_payload,
    create_season_payload,
    hire_crew_member,
    make_fieldcrew_headers,
    make_sugarmaker_headers,
    schedule_cert_audit,
    set_clock,
    setup_live_operation,
    setup_open_season,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role
    outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_unauthenticated
    """
    res = api.create_season(create_season_payload(), headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_fieldcrew_cannot_open_season(api, manager_headers):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint,
    or whose identity does not match the operator reference the endpoint
    expects, is rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: "| POST | /sugarhouse/seasons/{id}/open | Open the season (PLANNED
    → OPEN) | SugarhouseManager |"

    Design: Corner/roles/fieldcrew_cannot_open_season
    """
    set_clock("2027-02-15T00:00:00Z")
    season = validate_success(
        api.create_season(create_season_payload(), manager_headers), 201)
    tapper = validate_success(
        api.create_crew_member(
            create_crew_member_payload(season["id"], name="Tammy Tapper",
                                       crew_role="TAPPER"),
            manager_headers),
        201)

    res = api.open_season(season["id"], make_fieldcrew_headers(tapper["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    after = validate_success(api.get_season(season["id"], manager_headers), 200)
    assert after["status"] == "PLANNED"


def test_sugarmaker_cannot_record_audit(api, manager_headers, inspector_headers):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint,
    or whose identity does not match the operator reference the endpoint
    expects, is rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §3.10: "Recording the result — the exclusive province of the
    `CertInspector` — takes the `result` of `PASS` or `FAIL` and requires the
    logical clock date to be on or after `scheduled_for` (otherwise
    `ERR_AUDIT_NOT_DUE`), moving the audit `SCHEDULED → RECORDED`."

    Design: Corner/roles/sugarmaker_cannot_record_audit
    """
    season = setup_open_season(clock="2027-02-01T00:00:00Z")
    bush = create_bush(season["id"])
    audit = schedule_cert_audit(bush["id"], "WOODS", "2027-02-10")
    grader = hire_crew_member(season["id"], "Gail Grader", "GRADER")
    activate_crew_member(grader["id"])

    res = api.record_cert_audit_result(
        audit["id"], {"result": "PASS"}, make_sugarmaker_headers(grader["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    audits, _meta = validate_paginated(
        api.list_cert_audits(bush["id"], inspector_headers))
    assert audits[0]["status"] == "SCHEDULED"


def test_fieldcrew_collected_by_mismatch_unauthorized(api, manager_headers):
    """PRD §2.1: "when a `FieldCrew` caller records a sap collection, the
    request's `collected_by` field must equal `X-User-ID`, and the same
    entity-backed comparison applies anywhere a `FieldCrew` caller is expected
    to act as a specific crew member."
    PRD §2.1: "A request whose role is not permitted on the target endpoint, or
    whose identity does not match the operator reference the endpoint expects,
    is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/roles/fieldcrew_collected_by_mismatch_unauthorized
    """
    ctx = setup_live_operation()
    second = hire_crew_member(ctx["season"]["id"], "Second Sam", "TAPPER")
    activate_crew_member(second["id"])

    res = api.create_sap_run(
        create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                               second["id"], gallons_collected=10.0),
        make_fieldcrew_headers(ctx["tapper"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
