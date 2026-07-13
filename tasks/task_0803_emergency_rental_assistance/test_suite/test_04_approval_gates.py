"""Approval-gate ordering, cross-entity gating, and temporal-overlap protection.

Translates queue-A priority_pair_validation_conflict, cross_entity_state_dependency
(approve side), resource_temporal_overlap, plus queue-B approval-validation instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_tenant_headers, make_landlord_headers, make_caseworker_headers,
    create_landlord_payload, create_unit_payload, create_application_payload,
    income_source_payload, ledger_payload, submit_w9_payload,
    build_application,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]


def _drive_second_app_to_under_review(api, *, pid, tid, lid, unit_id, arrears=None,
                                      prospective=None, requested_prospective_months=0,
                                      ledger_lines=(), income=("WAGES", 400000)):
    """Open a second application on shared program/tenant/landlord and drive it to
    UNDER_REVIEW (W-9 already verified for the landlord). Returns the application id."""
    th, lh = make_tenant_headers(tid), make_landlord_headers(lid)
    app_kwargs = dict(monthly_rent_cents=200000,
                      requested_prospective_months=requested_prospective_months)
    if arrears:
        app_kwargs["arrears_start_month"], app_kwargs["arrears_end_month"] = arrears
    else:
        app_kwargs["arrears_start_month"] = None
        app_kwargs["arrears_end_month"] = None
    if prospective:
        app_kwargs["prospective_start_date"], app_kwargs["prospective_end_date"] = prospective
    else:
        app_kwargs["prospective_start_date"] = None
        app_kwargs["prospective_end_date"] = None
    aid = get_success_data(api.create_application(
        create_application_payload(pid, tid, lid, unit_id, **app_kwargs), th))["id"]
    get_success_data(api.add_income_source(aid, income_source_payload(*income), th))
    get_success_data(api.complete_tenant_section(
        aid, {"hardship_type": "JOB_LOSS", "hardship_attested": True}, th))
    get_success_data(api.create_ledger(aid, ledger_payload(ledger_lines), lh))
    get_success_data(api.verify_ledger(aid, {"decision": "VERIFIED"}, ADMIN))
    get_success_data(api.complete_landlord_section(aid, {"ledger_confirmed": True}, lh))
    get_success_data(api.submit_application(aid, th))
    get_success_data(api.review_application(aid, CW))
    return aid


# =====================================================================
# Queue B — approval-validation corner instances
# =====================================================================

def test_approve_without_hardship_attested_rejected(api):
    """PRD §3.6: "`hardship_attested` must be true; otherwise `ERR_HARDSHIP_NOT_ATTESTED`
    (HTTP 422)."

    Design: Corner/validations/approve_without_hardship_attested_returns_error
    """
    ctx = build_application(
        api, review=True, hardship_attested=False, hardship_type="OTHER",
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    resp = api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-ha"))
    validate_error(resp, ApiErrorId.ERR_HARDSHIP_NOT_ATTESTED.value, expected_status=422)


def test_approve_with_unverified_ledger_rejected(api):
    """PRD §3.6: "The application's rent ledger `status` must be `VERIFIED`; otherwise
    `ERR_LEDGER_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/validations/approve_with_unverified_ledger_returns_error
    """
    ctx = build_application(
        api, review=True, verify_ledger=False,
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    resp = api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-lv"))
    validate_error(resp, ApiErrorId.ERR_LEDGER_NOT_VERIFIED.value, expected_status=422)


# =====================================================================
# Rule 5 — priority_pair_validation_conflict
# =====================================================================

def test_state_error_beats_funding_on_approve_of_draft(api):
    """PRD §2.6: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`, HTTP 409). Business-specific checks
    follow, in the order laid out in the workflow sections."
    PRD §3.6: "Approval is the decisive act. It is available only from `UNDER_REVIEW`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_approve
    """
    ctx = build_application(
        api, funding_pool_total_cents=0, income_limits={"2": 566667},
        submit_w9=False, income_sources=(), do_tenant_section=False,
        add_ledger=False, do_landlord_section=False, submit=False, review=False,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2,
    )
    resp = api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-approver-9"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_state_error_beats_funding_leaves_application_in_draft(api):
    """PRD §3.6: "Approval is the decisive act. It is available only from `UNDER_REVIEW`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_approve
    """
    ctx = build_application(
        api, funding_pool_total_cents=0, income_limits={"2": 566667},
        submit_w9=False, income_sources=(), do_tenant_section=False,
        add_ledger=False, do_landlord_section=False, submit=False, review=False,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2,
    )
    api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-approver-9b"))
    app = get_success_data(api.get_application(ctx["aid"], CW))
    assert app["status"] == "DRAFT"


def test_w9_referential_error_beats_income_constraint_on_approve(api):
    """PRD §3.6: "The landlord's `w9_status` must be `VERIFIED`; otherwise
    `ERR_W9_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_approve
    """
    ctx = build_application(
        api, review=True, submit_w9=True, verify_w9=False,
        income_limits={"2": 566667},
        income_sources=(("WAGES", 700000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    resp = api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-approver-10"))
    validate_error(resp, ApiErrorId.ERR_W9_NOT_VERIFIED.value, expected_status=422)


def test_w9_referential_error_leaves_application_under_review(api):
    """PRD §3.6: "The landlord's `w9_status` must be `VERIFIED`; otherwise
    `ERR_W9_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_approve
    """
    ctx = build_application(
        api, review=True, submit_w9=True, verify_w9=False,
        income_limits={"2": 566667},
        income_sources=(("WAGES", 700000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-approver-10b"))
    app = get_success_data(api.get_application(ctx["aid"], CW))
    assert app["status"] == "UNDER_REVIEW"


# =====================================================================
# Rule 7 — cross_entity_state_dependency (approve gated by landlord W-9)
# =====================================================================

def test_approve_blocked_when_landlord_w9_only_submitted(api):
    """PRD §3.6: "The landlord's `w9_status` must be `VERIFIED`; otherwise
    `ERR_W9_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/approve_gated_by_landlord_w9_verified
    """
    ctx = build_application(
        api, review=True, submit_w9=True, verify_w9=False,
        income_limits={"2": 566667},
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    resp = api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-approver-13"))
    validate_error(resp, ApiErrorId.ERR_W9_NOT_VERIFIED.value, expected_status=422)


def test_approve_blocked_by_w9_leaves_application_under_review(api):
    """PRD §3.6: "Approval is the decisive act. It is available only from `UNDER_REVIEW`
    and, when granted, computes and pins the award and moves `status` to `APPROVED`"

    Design: Difficulty/cross_entity_state_dependency/approve_gated_by_landlord_w9_verified
    """
    ctx = build_application(
        api, review=True, submit_w9=True, verify_w9=False,
        income_limits={"2": 566667},
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_caseworker_headers("cw-approver-13b"))
    app = get_success_data(api.get_application(ctx["aid"], CW))
    assert app["status"] == "UNDER_REVIEW"


# =====================================================================
# Rule 8 — resource_temporal_overlap
# =====================================================================

def test_arrears_window_shared_month_on_same_unit_rejected(api):
    """PRD §3.6: "Duplicate-benefit protection on arrears: the arrears window must share
    no calendar month with the arrears window of any other `APPROVED` or `DISBURSED`
    application for the same `unit_id`. Overlap is judged on the closed inclusive
    interval, so two windows that merely abut (one ending the month before the other
    begins) are allowed, but any shared month is rejected with `ERR_DUPLICATE_BENEFIT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/unit_arrears_month_overlap_adjacency_allowed
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-15",
        income_limits={"2": 566667}, income_sources=(("WAGES", 400000),),
        arrears_start_month="2025-12", arrears_end_month="2026-01",
        prospective_start_date=None, prospective_end_date=None,
        requested_prospective_months=0,
        ledger_lines=[
            {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 200000},
            {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 200000},
        ],
    )
    aid2 = _drive_second_app_to_under_review(
        api, pid=ctx["pid"], tid=ctx["tid"], lid=ctx["lid"], unit_id=ctx["uid"],
        arrears=("2026-01", "2026-02"), requested_prospective_months=0,
        ledger_lines=[
            {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 200000},
            {"month": "2026-02", "line_type": "CHARGE", "charge_cents": 200000},
        ],
    )
    resp = api.approve_application(aid2, {"decision_reason": "second"}, make_caseworker_headers("cw-approver-15b"))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BENEFIT.value, expected_status=409)


def test_abutting_arrears_window_on_same_unit_is_allowed(api):
    """PRD §3.6: "Overlap is judged on the closed inclusive interval, so two windows
    that merely abut (one ending the month before the other begins) are allowed, but any
    shared month is rejected with `ERR_DUPLICATE_BENEFIT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/unit_arrears_month_overlap_adjacency_allowed
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-15c",
        income_limits={"2": 566667}, income_sources=(("WAGES", 400000),),
        arrears_start_month="2025-12", arrears_end_month="2026-01",
        prospective_start_date=None, prospective_end_date=None,
        requested_prospective_months=0,
        ledger_lines=[
            {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 200000},
            {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 200000},
        ],
    )
    # app2's window [2026-02, 2026-03] merely abuts app1's [2025-12, 2026-01]: no shared month.
    aid2 = _drive_second_app_to_under_review(
        api, pid=ctx["pid"], tid=ctx["tid"], lid=ctx["lid"], unit_id=ctx["uid"],
        arrears=("2026-02", "2026-03"), requested_prospective_months=0,
        ledger_lines=[
            {"month": "2026-02", "line_type": "CHARGE", "charge_cents": 200000},
            {"month": "2026-03", "line_type": "CHARGE", "charge_cents": 200000},
        ],
    )
    data = validate_success(api.approve_application(
        aid2, {"decision_reason": "second"}, make_caseworker_headers("cw-approver-15d")))
    assert data["status"] == "APPROVED"


def test_adjacent_prospective_window_for_same_tenant_rejected(api):
    """PRD §3.6: "Prospective non-overlap: the prospective window must neither overlap
    nor fall within a one-month buffer of the prospective window of any other `APPROVED`
    or `DISBURSED` application for the same `tenant_id`. Because of the one-month buffer,
    even directly adjacent prospective windows are rejected with `ERR_PROSPECTIVE_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tenant_prospective_buffer_overlap_adjacency_rejected
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-16",
        income_limits={"2": 566667}, income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-05-31",
        requested_prospective_months=3, ledger_lines=[],
    )
    pid, tid = ctx["pid"], ctx["tid"]
    # Second landlord + unit for the same tenant.
    lid2 = get_success_data(api.create_landlord(create_landlord_payload(email="l2pb@x.com")))["id"]
    lh2 = make_landlord_headers(lid2)
    get_success_data(api.submit_w9(lid2, submit_w9_payload(tin="18-1818181", banking_last4="0016"), lh2))
    get_success_data(api.verify_w9(lid2, {"decision": "VERIFIED"}, ADMIN))
    uid2 = get_success_data(api.create_unit(create_unit_payload(lid2, address="17 O St"), lh2))["id"]

    aid2 = _drive_second_app_to_under_review(
        api, pid=pid, tid=tid, lid=lid2, unit_id=uid2,
        prospective=("2026-06-01", "2026-07-31"), requested_prospective_months=2,
        ledger_lines=[],
    )
    resp = api.approve_application(aid2, {"decision_reason": "second"}, make_caseworker_headers("cw-approver-16b"))
    validate_error(resp, ApiErrorId.ERR_PROSPECTIVE_OVERLAP.value, expected_status=409)


def test_prospective_window_beyond_one_month_buffer_is_allowed(api):
    """PRD §3.6: "Prospective non-overlap: the prospective window must neither overlap
    nor fall within a one-month buffer of the prospective window of any other `APPROVED`
    or `DISBURSED` application for the same `tenant_id`. Because of the one-month buffer,
    even directly adjacent prospective windows are rejected with `ERR_PROSPECTIVE_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tenant_prospective_buffer_overlap_adjacency_rejected
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-16c",
        income_limits={"2": 566667}, income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-05-31",
        requested_prospective_months=3, ledger_lines=[],
    )
    pid, tid = ctx["pid"], ctx["tid"]
    lid2 = get_success_data(api.create_landlord(create_landlord_payload(email="l3pb@x.com")))["id"]
    lh2 = make_landlord_headers(lid2)
    get_success_data(api.submit_w9(lid2, submit_w9_payload(tin="19-1919191", banking_last4="0017"), lh2))
    get_success_data(api.verify_w9(lid2, {"decision": "VERIFIED"}, ADMIN))
    uid2 = get_success_data(api.create_unit(create_unit_payload(lid2, address="18 O St"), lh2))["id"]

    # app1 ends 2026-05-31; app2 starts 2026-07-01, leaving all of June (2026-06) as a
    # gap month beyond the one-month buffer, so the window is allowed.
    aid2 = _drive_second_app_to_under_review(
        api, pid=pid, tid=tid, lid=lid2, unit_id=uid2,
        prospective=("2026-07-01", "2026-08-31"), requested_prospective_months=2,
        ledger_lines=[],
    )
    data = validate_success(api.approve_application(
        aid2, {"decision_reason": "second"}, make_caseworker_headers("cw-approver-16d")))
    assert data["status"] == "APPROVED"
