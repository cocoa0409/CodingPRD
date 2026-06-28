"""State-machine behavior: plan-review cycle, inspection amend cycle, enforcement-case
branching and penalty assessment, and a sweep of invalid transitions / terminal lockdowns.

Queue A (Difficulty): non_linear_state_machine, dual_variant_calc (enforcement penalty).
Queue B (Corner): state_machines.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_code, create_inspector, create_establishment,
    create_establishment_with_approved_plan, create_permitted_establishment,
    setup_inspection_in_progress, setup_completed_inspection,
    add_violation, complete_inspection, schedule_inspection,
    open_enforcement_case, setup_case_hearing_scheduled, set_clock,
    create_plan_review_payload, create_complaint,
    TEST_USERS, make_inspector_headers,
)

CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


# ─── non_linear_state_machine / nls_inspection_complete_amend_complete_cycle ─
def test_complete_amend_complete_cycle_recomputes_score(api):
    """PRD §3.4: "Reopening moves an inspection from `COMPLETED` to `AMENDING`; it requires
    the inspection to be `COMPLETED` (otherwise `ERR_INSPECTION_NOT_COMPLETED`) and
    increments the inspection's `version` by one."
    PRD §3.4: "From `AMENDING` the inspector re-completes the inspection back to
    `COMPLETED`; re-completion requires the inspection to be `AMENDING` (otherwise
    `ERR_INSPECTION_NOT_AMENDING`) and again recomputes the scores, critical count, grade,
    and placard color."

    Start with two corrected violations (CRIT 12 + NC 9, final_score 89); reopen, delete the
    NC violation, re-complete: only the corrected CRIT 12 remains -> 100 - ceil(12/2) = 94,
    grade B (band A capped by 1 critical).

    Design: Difficulty/non_linear_state_machine/nls_inspection_complete_amend_complete_cycle
    """
    code_crit = create_code("CRITICAL", 12, code="3-501.16", title="Cold holding")
    code_nc = create_code("NON_CRITICAL", 9, code="6-301.11", title="Signage")
    est, insp, inspection = setup_inspection_in_progress(scheduled_index=10)
    add_violation(inspection["id"], code_crit["id"], insp["id"], corrected_on_site=True)
    v_nc = add_violation(inspection["id"], code_nc["id"], insp["id"], corrected_on_site=True)
    completed = complete_inspection(inspection["id"], insp["id"])
    assert completed["final_score"] == 89, f"expected 89 before amend, got {completed['final_score']}"

    reopened = validate_success(api.reopen_inspection(inspection["id"], make_inspector_headers(insp["id"])), 200)
    assert reopened["status"] == "AMENDING", f"reopen -> AMENDING, got {reopened['status']}"
    api.delete_violation(v_nc["id"], make_inspector_headers(insp["id"]))
    recompleted = complete_inspection(inspection["id"], insp["id"])
    assert recompleted["status"] == "COMPLETED", f"re-complete returns to COMPLETED, got {recompleted['status']}"
    assert recompleted["final_score"] == 94, f"100 - ceil(12/2) = 94, got {recompleted['final_score']}"
    assert recompleted["critical_count"] == 1, f"expected 1 critical, got {recompleted['critical_count']}"
    assert recompleted["grade"] == "B", f"band A(94) capped at B by 1 critical, got {recompleted['grade']}"


def test_reopen_increments_inspection_version(api):
    """PRD §3.4: "Reopening moves an inspection from `COMPLETED` to `AMENDING`; it requires
    the inspection to be `COMPLETED` (otherwise `ERR_INSPECTION_NOT_COMPLETED`) and
    increments the inspection's `version` by one."

    Design: Difficulty/non_linear_state_machine/nls_inspection_complete_amend_complete_cycle
    """
    _, insp, completed = setup_completed_inspection(scheduled_index=10, violations=[])
    version_before = completed["version"]
    reopened = validate_success(api.reopen_inspection(completed["id"], make_inspector_headers(insp["id"])), 200)
    assert reopened["status"] == "AMENDING", f"expected AMENDING, got {reopened['status']}"
    assert reopened["version"] == version_before + 1, (
        f"reopen increments version by one: {version_before} -> {reopened['version']}")


# ─── non_linear_state_machine / nls_enforcement_branch_hearing_vs_settle ─────
def test_enforcement_opened_forks_to_settle_and_hearing(api):
    """PRD §3.10: "On the settle path, the `EnforcementOfficer` settles an open case
    directly without a hearing, moving it straight from `OPENED` to `CLOSED`; settling
    requires the case to be `OPENED` (otherwise `ERR_CASE_NOT_OPENED`) and assesses the
    alleged penalty in full, setting `assessed_penalty_cents` equal to
    `alleged_penalty_cents` with no reduction and no ruling recorded."
    PRD §3.10: "Scheduling records the `hearing_index` and moves the case to
    `HEARING_SCHEDULED`."

    Two OPENED cases each alleged 40000: one settled (CLOSED, assessed 40000), the other
    scheduled for a hearing (HEARING_SCHEDULED).

    Design: Difficulty/non_linear_state_machine/nls_enforcement_branch_hearing_vs_settle
    """
    set_clock(30)
    est, _, _ = create_permitted_establishment()
    c_settle = open_enforcement_case(est["id"], 40000)
    c_hear = open_enforcement_case(est["id"], 40000)

    settled = validate_success(api.settle_enforcement_case(c_settle["id"], OFFICER), 200)
    assert settled["status"] == "CLOSED", f"settle -> CLOSED, got {settled['status']}"
    assert settled["assessed_penalty_cents"] == 40000, (
        f"settle assesses the alleged penalty in full, got {settled['assessed_penalty_cents']}")

    scheduled = validate_success(
        api.schedule_hearing(c_hear["id"], {"hearing_index": 35}, OFFICER), 200)
    assert scheduled["status"] == "HEARING_SCHEDULED", (
        f"schedule-hearing -> HEARING_SCHEDULED, got {scheduled['status']}")


def test_settle_path_records_no_ruling(api):
    """PRD §3.10: "settling requires the case to be `OPENED` (otherwise
    `ERR_CASE_NOT_OPENED`) and assesses the alleged penalty in full, setting
    `assessed_penalty_cents` equal to `alleged_penalty_cents` with no reduction and no
    ruling recorded."

    Design: Difficulty/non_linear_state_machine/nls_enforcement_branch_hearing_vs_settle
    """
    set_clock(30)
    est, _, _ = create_permitted_establishment()
    case = open_enforcement_case(est["id"], 40000)
    settled = validate_success(api.settle_enforcement_case(case["id"], OFFICER), 200)
    assert settled["status"] == "CLOSED", f"settle -> CLOSED, got {settled['status']}"
    assert settled.get("ruling") in (None, ""), f"settle records no ruling, got {settled.get('ruling')!r}"


# ─── dual_variant_calc / dv_enforcement_penalty_reduced_vs_settle_full ───────
def test_reduced_ruling_halves_penalty_vs_settle_full(api):
    """PRD §3.10: "a `REDUCED` ruling assesses the alleged penalty multiplied by one half
    and rounded down to a whole cent".
    PRD §3.10: "settling ... assesses the alleged penalty in full, setting
    `assessed_penalty_cents` equal to `alleged_penalty_cents` with no reduction".

    Same alleged 50000: REDUCED ruling assesses floor(50000*0.5)=25000; settle assesses 50000.

    Design: Difficulty/dual_variant_calc/dv_enforcement_penalty_reduced_vs_settle_full
    """
    set_clock(20)
    est, _, _ = create_permitted_establishment()
    case_settled = open_enforcement_case(est["id"], 50000)
    settled = validate_success(api.settle_enforcement_case(case_settled["id"], OFFICER), 200)
    assert settled["assessed_penalty_cents"] == 50000, (
        f"settle assesses full 50000, got {settled['assessed_penalty_cents']}")

    case_ruled = open_enforcement_case(est["id"], 50000)
    validate_success(api.schedule_hearing(case_ruled["id"], {"hearing_index": 25}, OFFICER), 200)
    set_clock(25)
    ruled = validate_success(api.rule_enforcement_case(case_ruled["id"], {"ruling": "REDUCED"}, DIRECTOR), 200)
    assert ruled["assessed_penalty_cents"] == 25000, (
        f"REDUCED assesses floor(50000*0.5)=25000, got {ruled['assessed_penalty_cents']}")


def test_upheld_ruling_assesses_full_penalty(api):
    """PRD §3.10: "an `UPHELD` ruling assesses the full alleged penalty."

    An UPHELD ruling on alleged 50000 assesses 50000.

    Design: Difficulty/dual_variant_calc/dv_enforcement_penalty_reduced_vs_settle_full
    """
    est, case = setup_case_hearing_scheduled(alleged_penalty_cents=50000, hearing_index=25, open_index=20)
    set_clock(25)
    ruled = validate_success(api.rule_enforcement_case(case["id"], {"ruling": "UPHELD"}, DIRECTOR), 200)
    assert ruled["status"] == "HEARD", f"rule -> HEARD, got {ruled['status']}"
    assert ruled["assessed_penalty_cents"] == 50000, (
        f"UPHELD assesses the full 50000, got {ruled['assessed_penalty_cents']}")


# ─── Corner / sm_plan_review_approve_from_already_approved_invalid ───────────
def test_approve_already_approved_plan_review_rejected(api):
    """PRD §3.2: "Approval moves a plan review from `SUBMITTED` to `APPROVED`; it requires
    that the plan review currently be `SUBMITTED` (otherwise `ERR_PLAN_REVIEW_NOT_SUBMITTED`)".

    Design: Corner/state_machines/sm_plan_review_approve_from_already_approved_invalid
    """
    est, pr = create_establishment_with_approved_plan()
    res = api.approve_plan_review(pr["id"], CLERK)
    validate_error(res, "ERR_PLAN_REVIEW_NOT_SUBMITTED", expected_status=409)
    after = validate_success(api.get_plan_review(pr["id"], CLERK), 200)
    assert after["status"] == "APPROVED", f"status unchanged, got {after['status']}"


# ─── Corner / sm_plan_review_resubmit_cycle_bumps_revision_round_and_refee ───
def test_resubmit_cycle_bumps_revision_round_and_recomputes_fee(api):
    """PRD §3.2: "resubmit requires the plan review to be `REJECTED` (otherwise
    `ERR_PLAN_REVIEW_NOT_REJECTED`), and when it succeeds it increments `revision_round`
    by one, accepts optionally revised `submitted_layout_sqft` and `equipment_count`,
    recomputes `plan_fee_cents` against the new layout and equipment, and clears the
    recorded `rejection_reason`."

    Reject a SUBMITTED plan, then resubmit with 1200 sqft / 10 equip:
    20000 + 700*50 (sqft 501..1200) + 10*1500 = 20000 + 35000 + 15000 = 70000.

    Design: Corner/state_machines/sm_plan_review_resubmit_cycle_bumps_revision_round_and_refee
    """
    est = create_establishment()
    pr = validate_success(api.create_plan_review(
        create_plan_review_payload(est["id"], submitted_layout_sqft=400, equipment_count=5), CLERK), 201)
    validate_success(api.reject_plan_review(pr["id"], {"rejection_reason": "Inadequate handwash placement"}, CLERK), 200)
    res = api.resubmit_plan_review(pr["id"], {"submitted_layout_sqft": 1200, "equipment_count": 10}, CLERK)
    resubmitted = validate_success(res, 200)
    assert resubmitted["status"] == "SUBMITTED", f"resubmit -> SUBMITTED, got {resubmitted['status']}"
    assert resubmitted["revision_round"] == 1, f"revision_round bumps to 1, got {resubmitted['revision_round']}"
    assert resubmitted["plan_fee_cents"] == 70000, f"expected 70000, got {resubmitted['plan_fee_cents']}"


# ─── Corner / sm_establishment_revoked_is_terminal_lockdown ──────────────────
def test_revoked_establishment_cannot_be_revoked_again(api):
    """PRD §3.3: "An establishment may be revoked from either `PERMITTED` or `SUSPENDED`;
    an attempt from any other status is rejected with `ERR_ESTABLISHMENT_NOT_REVOCABLE`."

    Design: Corner/state_machines/sm_establishment_revoked_is_terminal_lockdown
    """
    est, _, _ = create_permitted_establishment()
    validate_success(api.revoke_establishment(est["id"], DIRECTOR), 200)
    res = api.revoke_establishment(est["id"], DIRECTOR)
    validate_error(res, "ERR_ESTABLISHMENT_NOT_REVOCABLE", expected_status=409)
    after = validate_success(api.get_establishment(est["id"], DIRECTOR), 200)
    assert after["status"] == "REVOKED", f"status stays REVOKED, got {after['status']}"


# ─── Corner / sm_inspection_finalize_from_scheduled_invalid ──────────────────
def test_finalize_scheduled_inspection_rejected(api):
    """PRD §3.7: "Finalization requires the inspection to be `COMPLETED` (otherwise
    `ERR_INSPECTION_NOT_COMPLETED`)".

    Design: Corner/state_machines/sm_inspection_finalize_from_scheduled_invalid
    """
    inspector = create_inspector()
    est, _, _ = create_permitted_establishment()
    inspection = schedule_inspection(est["id"], inspector["id"], 0, "ROUTINE")
    res = api.finalize_inspection(
        inspection["id"], {"expected_inspection_version": inspection["version"]},
        make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_INSPECTION_NOT_COMPLETED", expected_status=409)
    after = validate_success(api.get_inspection(inspection["id"], CLERK), 200)
    assert after["status"] == "SCHEDULED", f"status stays SCHEDULED, got {after['status']}"


# ─── Corner / sm_inspection_initial_state_scheduled ──────────────────────────
def test_new_inspection_starts_scheduled(api):
    """PRD §3.4: "A new inspection begins `SCHEDULED`."

    Design: Corner/state_machines/sm_inspection_initial_state_scheduled
    """
    inspector = create_inspector()
    est, _, _ = create_permitted_establishment()
    inspection = schedule_inspection(est["id"], inspector["id"], 0, "ROUTINE")
    assert inspection["status"] == "SCHEDULED", f"new inspection is SCHEDULED, got {inspection['status']}"


# ─── Corner / sm_complaint_dispatch_from_received_invalid ────────────────────
def test_dispatch_received_complaint_rejected(api):
    """PRD §3.9: "dispatch requires the complaint to be `TRIAGED` (otherwise
    `ERR_COMPLAINT_NOT_TRIAGED`)".

    Design: Corner/state_machines/sm_complaint_dispatch_from_received_invalid
    """
    inspector = create_inspector()
    est, _, _ = create_permitted_establishment()
    complaint = create_complaint(est["id"], "SANITATION")
    res = api.dispatch_complaint(complaint["id"], {"inspector_id": inspector["id"]},
                                 make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_COMPLAINT_NOT_TRIAGED", expected_status=409)
    after = validate_success(api.get_complaint(complaint["id"], CLERK), 200)
    assert after["status"] == "RECEIVED", f"status stays RECEIVED, got {after['status']}"


# ─── Corner / sm_route_close_from_planned_invalid ────────────────────────────
def test_close_planned_route_rejected(api):
    """PRD §3.4: "closing requires the route to be `DISPATCHED` (otherwise
    `ERR_ROUTE_NOT_DISPATCHED`)".

    Design: Corner/state_machines/sm_route_close_from_planned_invalid
    """
    from test_helpers import create_route
    set_clock(5)
    inspector = create_inspector()
    route = create_route(inspector["id"], 5)
    res = api.close_inspection_route(route["id"], make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_ROUTE_NOT_DISPATCHED", expected_status=409)
    after = validate_success(api.get_inspection_route(route["id"], CLERK), 200)
    assert after["status"] == "PLANNED", f"status stays PLANNED, got {after['status']}"


# ─── Corner / sm_enforcement_close_from_opened_invalid ───────────────────────
def test_close_opened_case_rejected(api):
    """PRD §3.10: "A heard case is then closed by the `EnforcementOfficer`, moving it from
    `HEARD` to `CLOSED`; closing requires the case to be `HEARD` (otherwise
    `ERR_CASE_NOT_HEARD`)."

    Design: Corner/state_machines/sm_enforcement_close_from_opened_invalid
    """
    est, _, _ = create_permitted_establishment()
    case = open_enforcement_case(est["id"], 10000)
    res = api.close_enforcement_case(case["id"], OFFICER)
    validate_error(res, "ERR_CASE_NOT_HEARD", expected_status=409)
    after = validate_success(api.get_enforcement_case(case["id"], OFFICER), 200)
    assert after["status"] == "OPENED", f"status stays OPENED, got {after['status']}"
