"""Routes: logical clock, OffboardingCase lifecycle, notifications."""
from datetime import timedelta

from flask import g

from core import (
    ASSET_RETURN_GRACE_DAYS,
    CASE_TYPES,
    CLOCK,
    DB,
    ROLES,
    STATE_CODES,
    app,
    authenticate,
    bump,
    err_bad_request,
    err_case_terminal,
    err_deadline,
    err_fiscal,
    err_invalid_state,
    err_not_found,
    err_referential,
    err_sod,
    err_temporal,
    get_body,
    is_int,
    is_num,
    new_record,
    now_dt,
    ok_object,
    paginate,
    parse_dt,
    req_str,
    ser,
    ApiError,
)
from domain import (
    calc_final_pay_deadline,
    calc_last_day_determination,
    calc_revocation_schedule,
    emit_notification,
    notices_of,
    ready_gate,
    reconcile_case,
    review_of,
    statement_of,
    sweep,
    tasks_of,
    compute_asset_posture,
)

ALL_BUSINESS_ROLES = ROLES - {"PlatformAdmin"}
CASE_READ_ROLES = ALL_BUSINESS_ROLES
SUMMARY_ROLES = {"HRPartner", "HRDirector", "PayrollSpecialist", "Manager"}
NOTIFICATION_READ_ROLES = {"Manager", "HRPartner", "HRDirector"}


def get_case_or_404(case_id):
    case = DB["cases"].get(case_id)
    if case is None:
        raise err_not_found("OffboardingCase %s not found" % case_id)
    return case


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@app.post("/offboarding/_clock/set_current_utc")
def set_clock():
    authenticate({"PlatformAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise err_bad_request("to_iso8601 must be an ISO 8601 UTC instant")
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw
    sweep()
    return ok_object({"current_utc": CLOCK["raw"]})


@app.get("/offboarding/_clock/current_utc")
def get_clock():
    authenticate({"PlatformAdmin"})
    return ok_object({"current_utc": CLOCK["raw"]})


# --------------------------------------------------------------------------
# OffboardingCase
# --------------------------------------------------------------------------
@app.post("/offboarding/offboarding-cases")
def create_case():
    authenticate({"HRPartner"})
    body = get_body()
    # Priority 6: temporal sanity (requires parseable dates)
    notice = parse_dt(body.get("notice_received_date"))
    requested = parse_dt(body.get("requested_last_day"))
    if notice is None or requested is None:
        raise err_bad_request("notice_received_date and requested_last_day must be ISO 8601 UTC instants")
    if requested < notice:
        raise err_temporal("requested_last_day must not be earlier than notice_received_date")
    # Priority 7: referential integrity (employee_ref uniqueness)
    employee_ref = body.get("employee_ref")
    if not isinstance(employee_ref, str) or not employee_ref:
        raise err_bad_request("employee_ref is required")
    if any(c["employee_ref"] == employee_ref for c in DB["cases"].values()):
        raise err_referential("employee_ref must be unique across all OffboardingCase rows")
    # Priority 11: fiscal sanity
    wage = body.get("hourly_wage_cents")
    if not is_int(wage):
        raise err_bad_request("hourly_wage_cents must be an integer")
    if wage <= 0:
        raise err_fiscal("hourly_wage_cents must be > 0")
    pto = body.get("pto_balance_hours")
    if not is_num(pto):
        raise err_bad_request("pto_balance_hours must be a number")
    if pto < 0:
        raise err_fiscal("pto_balance_hours must be >= 0")
    # Priority 13: payload shape (enums, remaining required fields, ranges)
    if body.get("case_type") not in CASE_TYPES:
        raise err_bad_request("case_type must be one of %s" % sorted(CASE_TYPES))
    if body.get("work_state_code") not in STATE_CODES:
        raise err_bad_request("work_state_code must be one of %s" % sorted(STATE_CODES))
    tenure = body.get("tenure_years")
    if not is_num(tenure) or tenure < 0:
        raise err_bad_request("tenure_years must be a non-negative number")
    req_str(body, "intake_hr_ref")

    case = new_record()
    case.update({
        "employee_ref": employee_ref,
        "case_type": body["case_type"],
        "work_state_code": body["work_state_code"],
        "notice_received_date": notice,
        "requested_last_day": requested,
        "determined_last_day": None,
        "final_pay_due_at": None,
        "pto_balance_hours": pto,
        "tenure_years": tenure,
        "hourly_wage_cents": wage,
        "status": "INTAKE",
        "revocation_posture": "NOT_STARTED",
        "asset_posture": "NOT_STARTED",
        "deduction_total_cents": 0,
        "rehire_code": None,
        "closed_at": None,
        "_intake_hr_ref": body["intake_hr_ref"],
        "_approved_by": None,
    })
    DB["cases"][case["id"]] = case
    emit_notification(case["id"], "INTAKE_ALERT")
    return ok_object(ser(case), status=201)


@app.get("/offboarding/offboarding-cases")
def list_cases():
    authenticate(CASE_READ_ROLES)
    records = list(DB["cases"].values())
    status = _q("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    wsc = _q("work_state_code")
    if wsc is not None:
        records = [c for c in records if c["work_state_code"] == wsc]
    ctype = _q("case_type")
    if ctype is not None:
        records = [c for c in records if c["case_type"] == ctype]
    return paginate(records)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@app.get("/offboarding/offboarding-cases/<case_id>")
def get_case(case_id):
    authenticate(CASE_READ_ROLES)
    return ok_object(ser(get_case_or_404(case_id)))


@app.get("/offboarding/offboarding-cases/<case_id>/summary")
def get_case_summary(case_id):
    authenticate(SUMMARY_ROLES)
    case = get_case_or_404(case_id)
    from domain import assets_of, compute_deduction_total, calc_final_net_pay
    projected = sum(
        i["deduction_amount_cents"]
        for i in assets_of(case_id)
        if i["deduction_status"] == "COMPUTED"
    )
    st = statement_of(case_id)
    if st is not None:
        _, net = calc_final_net_pay(
            st["regular_wages_cents"], st["pto_payout_cents"], case["deduction_total_cents"]
        )
        net_preview = net
    else:
        net_preview = 0
    data = {
        "revocation_posture": case["revocation_posture"],
        "asset_posture": case["asset_posture"],
        "deduction_total_cents": case["deduction_total_cents"],
        "projected_deduction_cents": projected,
        "net_pay_preview_cents": net_preview,
        "ready_to_close": ready_gate(case),
    }
    return ok_object(data)


@app.post("/offboarding/offboarding-cases/<case_id>/approve")
def approve_case(case_id):
    authenticate({"HRPartner"})
    case = get_case_or_404(case_id)
    # Priority 4: state legality
    if case["status"] != "INTAKE":
        raise err_invalid_state("Only an INTAKE case can be approved")
    # Priority 5: SoD-1 — approver must differ from the intake recorder
    if g.user_id == case["_intake_hr_ref"]:
        raise err_sod("Approver must differ from the intake recorder (SoD-1)")
    # Priority 6: temporal sanity re-checked at approval
    if case["requested_last_day"] < case["notice_received_date"]:
        raise err_temporal("requested_last_day must not be earlier than notice_received_date")

    determined = calc_last_day_determination(case)
    due_at, variant = calc_final_pay_deadline(case, determined)
    case["determined_last_day"] = determined
    case["final_pay_due_at"] = due_at
    case["_approved_by"] = g.user_id

    # Auto-create FinalPayStatement (DRAFT)
    st = new_record()
    st.update({
        "offboarding_case_id": case["id"],
        "regular_wages_cents": 0,
        "pto_payout_cents": 0,
        "deduction_total_cents": 0,
        "net_pay_cents": 0,
        "state_law_variant": variant,
        "due_at": due_at,
        "status": "DRAFT",
        "disbursed_at": None,
        "late_penalty_cents": 0,
        "_calc_by_ref": None,
    })
    DB["statements"][st["id"]] = st

    # Auto-create KnowledgeTransferPlan (DRAFT)
    plan = new_record()
    plan.update({
        "offboarding_case_id": case["id"],
        "owner_manager_ref": None,
        "required_session_count": 0,
        "status": "DRAFT",
        "completed_session_count": 0,
        "waived_reason": None,
    })
    DB["plans"][plan["id"]] = plan

    # Auto-create RehireEligibilityReview (DRAFT)
    review = new_record()
    review.update({
        "offboarding_case_id": case["id"],
        "reviewer_hr_ref": None,
        "recommended_code": "ELIGIBLE",
        "status": "DRAFT",
        "finalized_at": None,
        "rationale": None,
        "_return_reason": None,
    })
    DB["reviews"][review["id"]] = review

    # Stamp asset return deadlines and compute task schedules
    from domain import assets_of
    for item in assets_of(case["id"]):
        item["return_due_at"] = determined + timedelta(days=ASSET_RETURN_GRACE_DAYS)
        bump(item)
    for task in tasks_of(case["id"]):
        if task["scheduled_at"] is None:
            task["scheduled_at"] = calc_revocation_schedule(task["system_name"], determined)
            bump(task)

    case["status"] = "APPROVED"
    bump(case)
    emit_notification(case["id"], "LAST_DAY_CONFIRMED")
    return ok_object(ser(case))


@app.post("/offboarding/offboarding-cases/<case_id>/close")
def close_case(case_id):
    authenticate({"HRPartner"})
    case = get_case_or_404(case_id)
    # Priority 4: state legality (from-state + statement/notice preconditions)
    if case["status"] != "READY_TO_CLOSE":
        raise err_invalid_state("Only a READY_TO_CLOSE case can be closed")
    st = statement_of(case_id)
    if st is None or st["status"] not in ("DISBURSED", "LATE"):
        raise err_invalid_state("FinalPayStatement must be DISBURSED or LATE to close")
    for n in notices_of(case_id):
        if n["status"] not in ("SENT", "ACKNOWLEDGED", "ESCALATED"):
            raise err_invalid_state("All benefits notices must be dispatched before close")
    # Priority 12: legal deadline protection — finalized rehire review required
    review = review_of(case_id)
    if review is None or review["status"] != "FINALIZED":
        raise err_deadline("Close requires a FINALIZED rehire eligibility review")
    # Priority 13/14: payload shape + OCC
    body = get_body()
    expected = body.get("expected_offboarding_case_version")
    if not is_int(expected):
        raise err_bad_request("expected_offboarding_case_version is required")
    if expected != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412,
                       "OffboardingCase version has advanced since the caller's read")

    case["rehire_code"] = review["recommended_code"]
    case["closed_at"] = now_dt()
    case["status"] = "CLOSED"
    from domain import acks_of
    for k in acks_of(case_id):
        if k["status"] in ("PENDING", "REMINDED"):
            k["status"] = "EXPIRED"
            bump(k)
    bump(case)
    emit_notification(case_id, "CASE_CLOSED")
    return ok_object(ser(case))


@app.post("/offboarding/offboarding-cases/<case_id>/void")
def void_case(case_id):
    authenticate({"HRPartner"})
    case = get_case_or_404(case_id)
    if case["status"] not in ("INTAKE", "APPROVED"):
        raise err_invalid_state("Only an INTAKE or APPROVED case can be voided")
    if case["status"] == "APPROVED":
        if any(t["status"] in ("EXECUTED", "VERIFIED") for t in tasks_of(case_id)):
            raise err_invalid_state(
                "Case cannot be voided once revocation has been executed or verified")
    body = get_body()
    req_str(body, "void_reason")

    from domain import assets_of
    for t in tasks_of(case_id):
        if t["status"] in ("PENDING", "READY", "RETRY_SCHEDULED"):
            t["status"] = "WAIVED"
            bump(t)
    for a in assets_of(case_id):
        if a["status"] == "TRACKED":
            a["status"] = "WAIVED"
            bump(a)
    st = statement_of(case_id)
    if st is not None and st["status"] in ("DRAFT", "CALCULATED"):
        st["status"] = "VOIDED"
        bump(st)
    case["status"] = "VOIDED"
    bump(case)
    return ok_object(ser(case))


# --------------------------------------------------------------------------
# Manager notifications (read-only)
# --------------------------------------------------------------------------
def _filter_notifications(records):
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [n for n in records if n["offboarding_case_id"] == case_id]
    kind = _q("notification_kind")
    if kind is not None:
        records = [n for n in records if n["notification_kind"] == kind]
    sup = _q("suppressed")
    if sup is not None:
        flag = sup.lower() == "true"
        records = [n for n in records if n["suppressed"] == flag]
    return records


@app.get("/offboarding/manager-notifications")
def list_notifications():
    authenticate(NOTIFICATION_READ_ROLES)
    return paginate(_filter_notifications(list(DB["notifications"])))


@app.get("/offboarding/offboarding-cases/<case_id>/manager-notifications")
def list_case_notifications(case_id):
    authenticate(NOTIFICATION_READ_ROLES)
    get_case_or_404(case_id)
    records = [n for n in DB["notifications"] if n["offboarding_case_id"] == case_id]
    kind = _q("notification_kind")
    if kind is not None:
        records = [n for n in records if n["notification_kind"] == kind]
    return paginate(records)
