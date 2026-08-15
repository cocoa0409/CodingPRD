"""QualityAudit void rules and ops-run window binding."""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    set_clock,
    setup_needs_reclean,
    setup_verified_clean,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


def test_audit_void_requires_fail_result_and_needs_reclean(api):
    """PRD §3.6: "An `InfectionPreventionist` may **void** an audit while three
    conditions all hold: the audit is still `SUBMITTED` (`ERR_AUDIT_NOT_SUBMITTED`
    otherwise), its result is `FAIL` and the linked request is still sitting in
    `NEEDS_RECLEAN` (`ERR_AUDIT_NOT_VOIDABLE` otherwise), and the audit's
    `created_ops_run_index` still equals the unit's current `ops_run_index`."

    Design: Corner/state_machines/audit_void_requires_fail_result_and_needs_reclean
    """
    ctx = setup_verified_clean()
    audits, _meta = validate_paginated(
        api.list_quality_audits(ANY, params={"clean_request_id": ctx["request"]["id"]})
    )
    assert len(audits) == 1
    audit_id = audits[0]["id"]
    audit = validate_success(api.get_quality_audit(audit_id, ANY))
    assert audit["result"] == "PASS"

    r = api.void_quality_audit(audit_id, IP)
    validate_error(r, ApiErrorId.ERR_AUDIT_NOT_VOIDABLE)

    after = validate_success(api.get_quality_audit(audit_id, ANY))
    assert after["audit_status"] == "SUBMITTED"
    req = validate_success(api.get_clean_request(ctx["request"]["id"], ANY))
    assert req["status"] == "VERIFIED"
    bed = validate_success(api.get_bed(ctx["bed"]["id"], ANY))
    assert bed["bed_status"] == "READY"


def test_audit_void_window_closes_after_ops_run(api):
    """PRD §3.6: "and the audit's `created_ops_run_index` still equals the
    unit's current `ops_run_index` — meaning no ops-run has closed since
    submission (`ERR_AUDIT_VOID_WINDOW_CLOSED` once one has)."

    Design: Corner/state_machines/audit_void_window_closes_after_ops_run
    """
    ctx = setup_needs_reclean()
    audit_id = ctx["audit"]["id"]

    get_success_data(api.run_ops_run(ctx["unit"]["id"], TEST_USERS["admin_headers"]))

    r = api.void_quality_audit(audit_id, IP)
    validate_error(r, ApiErrorId.ERR_AUDIT_VOID_WINDOW_CLOSED)

    audit_after = validate_success(api.get_quality_audit(audit_id, ANY))
    assert audit_after["audit_status"] == "SUBMITTED"
    req = validate_success(api.get_clean_request(ctx["request"]["id"], ANY))
    assert req["status"] == "NEEDS_RECLEAN"
    tech = validate_success(api.get_staff(ctx["tech"]["id"], ANY))
    assert tech["qa_fail_count"] == 1


def test_audit_void_twice_rejected_after_successful_void(api):
    """PRD §3.6: "A void runs the compensation cascade: the request moves
    `NEEDS_RECLEAN → PENDING_QA`, the bed moves `VACANT_DIRTY →
    AWAITING_VERIFICATION`, and the completing technician's `qa_fail_count`
    drops by one with productivity recomputed. The audit itself becomes
    `VOIDED`, terminal."

    Design: Corner/state_machines/audit_void_twice_rejected_after_successful_void
    """
    ctx = setup_needs_reclean()
    audit_id = ctx["audit"]["id"]

    voided = validate_success(api.void_quality_audit(audit_id, IP))
    assert voided["audit_status"] == "VOIDED"

    r_again = api.void_quality_audit(audit_id, IP)
    validate_error(r_again, ApiErrorId.ERR_AUDIT_NOT_SUBMITTED)

    req = validate_success(api.get_clean_request(ctx["request"]["id"], ANY))
    assert req["status"] == "PENDING_QA"
    tech = validate_success(api.get_staff(ctx["tech"]["id"], ANY))
    assert tech["qa_fail_count"] == 0
