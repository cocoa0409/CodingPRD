"""RebateApplication endpoints: intake, submission, inspection scheduling,
verification, approval, payment, rejection, withdrawal."""
from datetime import timedelta

from flask import Blueprint, g, request

from auth import ALL_ROLES, require_roles
from db import base_fields, light_fields, now_iso, store, today
from errors import ApiError
from lookups import (
    claim_of_line,
    ensure_program_open,
    get_application,
    get_program_year,
    get_trade_ally,
    lines_of,
    program_year_of_application,
)
from respond import respond_list, success
from serialize import application_out, inspection_out
from services import (
    committed_pct,
    fraud_screen,
    pacing_tier,
    price_line,
    recompute_eval,
    sampling_decision,
    to_date,
    touch,
)
from validate import get_body, req_date, req_str

bp = Blueprint("applications", __name__)

INVOICE_LOOKBACK_DAYS = 90


@bp.post("/applications")
@require_roles("TradeAlly")
def create_application():
    body = get_body()
    program_year_id = req_str(body, "program_year_id")
    trade_ally_id = req_str(body, "trade_ally_id")
    customer_account_number = req_str(body, "customer_account_number")
    service_address = req_str(body, "service_address")
    invoice_number = req_str(body, "invoice_number")
    invoice_date = req_date(body, "invoice_date")
    # Body FK resolution.
    py = get_program_year(program_year_id)
    get_trade_ally(trade_ally_id)
    # Program-open gate.
    ensure_program_open(py)
    # Ownership: the acting ally must be the applicant.
    if trade_ally_id != g.user_id:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "TradeAlly %s may not create applications on behalf of %s"
            % (g.user_id, trade_ally_id),
        )
    rec = base_fields()
    rec.update(
        {
            "program_year_id": program_year_id,
            "trade_ally_id": trade_ally_id,
            "customer_account_number": customer_account_number,
            "service_address": service_address,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "incentive_total_cents": 0,
            "claimed_kwh": 0,
            "final_kwh": 0,
            "inspection_required": False,
            "risk_score": 0,
            "auto_flag_status": "CLEAR",
            "status": "DRAFT",
            "submitted_at": None,
            "verified_by": None,
        }
    )
    store.applications[rec["id"]] = rec
    return success(application_out(rec), "object", 201)


@bp.get("/applications")
@require_roles(*ALL_ROLES)
def list_applications():
    program_year_id = request.args.get("program_year_id")
    trade_ally_id = request.args.get("trade_ally_id")
    status = request.args.get("status")
    auto_flag_status = request.args.get("auto_flag_status")
    rows = list(store.applications.values())
    if program_year_id is not None:
        rows = [r for r in rows if r["program_year_id"] == program_year_id]
    if trade_ally_id is not None:
        rows = [r for r in rows if r["trade_ally_id"] == trade_ally_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if auto_flag_status is not None:
        rows = [r for r in rows if r["auto_flag_status"] == auto_flag_status]
    return respond_list(rows, application_out)


@bp.get("/applications/<rid>")
@require_roles(*ALL_ROLES)
def get_application_route(rid):
    return success(application_out(get_application(rid)), "object", 200)


@bp.post("/applications/<rid>/submit")
@require_roles("TradeAlly")
def submit_application(rid):
    app = get_application(rid)
    py = program_year_of_application(app)
    # Fixed submission check order (PRD section 3.4).
    ensure_program_open(py)
    if app["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; submit requires DRAFT" % app["status"],
        )
    ally = store.trade_allies[app["trade_ally_id"]]
    if ally["enroll_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ALLY_NOT_ACTIVE",
            409,
            "TradeAlly.enroll_status is %s; submit requires ACTIVE"
            % ally["enroll_status"],
        )
    lines = lines_of(app["id"])
    for line in lines:
        measure = store.measures[line["measure_id"]]
        if not measure["is_active"]:
            raise ApiError(
                "ERR_MEASURE_INACTIVE",
                409,
                "Measure %s is inactive and may not appear on a submission"
                % measure["id"],
            )
    if not lines:
        raise ApiError(
            "ERR_NO_LINE_ITEMS",
            422,
            "Application has no line items",
        )
    # Invoice eligibility window: [opened_at date - 90 days, today] inclusive.
    opened_date = to_date(py["opened_at"][:10])
    today_date = today()
    earliest_allowed = opened_date - timedelta(days=INVOICE_LOOKBACK_DAYS)
    invoice_date = to_date(app["invoice_date"])
    if not (earliest_allowed <= invoice_date <= today_date):
        raise ApiError(
            "ERR_INVOICE_DATE_OUT_OF_RANGE",
            422,
            "invoice_date %s is outside [%s, %s]"
            % (app["invoice_date"], earliest_allowed.isoformat(),
               today_date.isoformat()),
        )
    # Pacing tier is computed before this application's incentive is added.
    pct = committed_pct(py)
    tier_name, tier_factor = pacing_tier(pct)
    priced = []
    for line in lines:
        measure = store.measures[line["measure_id"]]
        incentive = price_line(measure, line["quantity"], tier_factor)
        claimed = measure["deemed_kwh_per_unit"] * line["quantity"]
        priced.append((line, incentive, claimed))
    total_incentive = sum(p[1] for p in priced)
    total_claimed = sum(p[2] for p in priced)
    if total_incentive > py["budget_cap_cents"] - py["committed_cents"]:
        raise ApiError(
            "ERR_PROGRAM_CAP_EXCEEDED",
            402,
            "Submission of %d cents exceeds remaining program headroom of %d cents"
            % (total_incentive, py["budget_cap_cents"] - py["committed_cents"]),
        )
    # Ownership ranks after the business-content checks.
    if g.user_id != app["trade_ally_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "TradeAlly %s does not own application %s" % (g.user_id, app["id"]),
        )
    # --- commit ---
    for line, incentive, claimed in priced:
        line["pacing_tier_at_submit"] = tier_name
        line["incentive_cents"] = incentive
        line["claimed_kwh"] = claimed
        touch(line)
    app["incentive_total_cents"] = total_incentive
    app["claimed_kwh"] = total_claimed
    app["inspection_required"] = sampling_decision(app)
    risk_score, auto_flag_status, flags = fraud_screen(app, today_date)
    app["risk_score"] = risk_score
    app["auto_flag_status"] = auto_flag_status
    app["submitted_at"] = now_iso()
    app["status"] = "SUBMITTED"
    touch(app)
    for flag in flags:
        rec = light_fields()
        rec.update(
            {
                "application_id": app["id"],
                "flag_kind": flag["flag_kind"],
                "weight": flag["weight"],
                "detail": flag["detail"],
            }
        )
        store.fraud_flags[rec["id"]] = rec
    py["committed_cents"] += total_incentive
    touch(py)
    return success(application_out(app), "object", 200)


@bp.post("/applications/<rid>/schedule-pre-inspection")
@require_roles("ProgramAdministrator")
def schedule_pre_inspection(rid):
    app = get_application(rid)
    body = get_body()
    scheduled_on = req_date(body, "scheduled_on")
    py = program_year_of_application(app)
    ensure_program_open(py)
    if app["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; scheduling requires SUBMITTED"
            % app["status"],
        )
    if not app["inspection_required"]:
        raise ApiError(
            "ERR_INSPECTION_NOT_REQUIRED",
            409,
            "Application %s is not flagged for inspection" % app["id"],
        )
    rec = base_fields()
    rec.update(
        {
            "application_id": app["id"],
            "inspection_kind": "PRE",
            "scheduled_on": scheduled_on,
            "completed_on": None,
            "outcome": "PENDING",
            "fail_reason": None,
        }
    )
    store.inspections[rec["id"]] = rec
    app["status"] = "PRE_INSPECTION"
    touch(app)
    return success(inspection_out(rec), "object", 201)


@bp.post("/applications/<rid>/schedule-post-inspection")
@require_roles("ProgramAdministrator")
def schedule_post_inspection(rid):
    app = get_application(rid)
    body = get_body()
    scheduled_on = req_date(body, "scheduled_on")
    # Not separately gated on program-open: an application can only sit in
    # POST_INSPECTION while its program year is open.
    if app["status"] != "POST_INSPECTION":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; post-inspection scheduling "
            "requires POST_INSPECTION" % app["status"],
        )
    rec = base_fields()
    rec.update(
        {
            "application_id": app["id"],
            "inspection_kind": "POST",
            "scheduled_on": scheduled_on,
            "completed_on": None,
            "outcome": "PENDING",
            "fail_reason": None,
        }
    )
    store.inspections[rec["id"]] = rec
    return success(inspection_out(rec), "object", 201)


@bp.post("/applications/<rid>/verify")
@require_roles("VerificationInspector")
def verify_application(rid):
    app = get_application(rid)
    py = program_year_of_application(app)
    ensure_program_open(py)
    if app["status"] not in ("SUBMITTED", "POST_INSPECTION"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; verify requires SUBMITTED or "
            "POST_INSPECTION" % app["status"],
        )
    lines = lines_of(app["id"])
    # Measured-input validation runs before either inspection-obligation check.
    claims = {}
    for line in lines:
        claim = claim_of_line(line["id"])
        claims[line["id"]] = claim
        if claim and claim["claim_method"] == "MEASURED":
            pre = claim["pre_annual_kwh"]
            post = claim["post_annual_kwh"]
            if pre is None or post is None or not (post < pre):
                raise ApiError(
                    "ERR_INVALID_MEASURED_INPUT",
                    422,
                    "MEASURED claim on line %s requires pre_annual_kwh and "
                    "post_annual_kwh with post < pre" % line["id"],
                )
    if app["status"] == "SUBMITTED":
        if app["inspection_required"]:
            raise ApiError(
                "ERR_INSPECTION_REQUIRED_OUTSTANDING",
                409,
                "Application %s requires inspection before verification"
                % app["id"],
            )
    else:  # POST_INSPECTION
        passed_post = any(
            i for i in store.inspections.values()
            if i["application_id"] == app["id"]
            and i["inspection_kind"] == "POST"
            and i["outcome"] == "PASSED"
        )
        if not passed_post:
            raise ApiError(
                "ERR_POST_INSPECTION_NOT_PASSED",
                409,
                "Verification from POST_INSPECTION requires a passed POST "
                "inspection",
            )
    # --- commit: finalize savings line by line ---
    total_final = 0
    for line in lines:
        claim = claims[line["id"]]
        if claim and claim["claim_method"] == "MEASURED":
            line["measured_kwh"] = claim["pre_annual_kwh"] - claim["post_annual_kwh"]
            line["final_kwh"] = line["measured_kwh"]
        else:
            # No claim or DEEMED: keep the submission-pinned value.
            line["final_kwh"] = line["claimed_kwh"]
        if claim:
            claim["computed_kwh"] = line["final_kwh"]
        touch(line)
        total_final += line["final_kwh"]
    app["final_kwh"] = total_final
    app["verified_by"] = g.user_id
    app["status"] = "VERIFIED"
    touch(app)
    py["reported_kwh"] += total_final
    recompute_eval(py)
    touch(py)
    return success(application_out(app), "object", 200)


@bp.post("/applications/<rid>/approve")
@require_roles("ProgramAdministrator")
def approve_application(rid):
    app = get_application(rid)
    py = program_year_of_application(app)
    ensure_program_open(py)
    if app["status"] != "VERIFIED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; approve requires VERIFIED"
            % app["status"],
        )
    if app["auto_flag_status"] == "SUSPECT":
        raise ApiError(
            "ERR_FRAUD_SUSPECT_HOLD",
            409,
            "Application %s is held as SUSPECT and cannot be approved"
            % app["id"],
        )
    if g.user_id == app["verified_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            409,
            "Approver may not be the inspector who verified the application",
        )
    app["status"] = "APPROVED"
    touch(app)
    return success(application_out(app), "object", 200)


@bp.post("/applications/<rid>/pay")
@require_roles("PaymentProcessor")
def pay_application(rid):
    app = get_application(rid)
    py = program_year_of_application(app)
    ensure_program_open(py)
    if app["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; pay requires APPROVED" % app["status"],
        )
    app["status"] = "PAID"
    touch(app)
    py["committed_cents"] -= app["incentive_total_cents"]
    py["paid_cents"] += app["incentive_total_cents"]
    touch(py)
    return success(application_out(app), "object", 200)


@bp.post("/applications/<rid>/reject")
@require_roles("ProgramAdministrator")
def reject_application(rid):
    app = get_application(rid)
    py = program_year_of_application(app)
    ensure_program_open(py)
    if app["status"] not in ("SUBMITTED", "VERIFIED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; reject requires SUBMITTED or "
            "VERIFIED" % app["status"],
        )
    was_verified = app["status"] == "VERIFIED"
    app["status"] = "REJECTED"
    touch(app)
    py["committed_cents"] -= app["incentive_total_cents"]
    if was_verified:
        py["reported_kwh"] -= app["final_kwh"]
    recompute_eval(py)
    touch(py)
    return success(application_out(app), "object", 200)


@bp.post("/applications/<rid>/withdraw")
@require_roles("TradeAlly")
def withdraw_application(rid):
    app = get_application(rid)
    py = program_year_of_application(app)
    ensure_program_open(py)
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; withdraw requires DRAFT or "
            "SUBMITTED" % app["status"],
        )
    if g.user_id != app["trade_ally_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "TradeAlly %s does not own application %s" % (g.user_id, app["id"]),
        )
    was_submitted = app["status"] == "SUBMITTED"
    app["status"] = "WITHDRAWN"
    touch(app)
    if was_submitted:
        py["committed_cents"] -= app["incentive_total_cents"]
        touch(py)
    return success(application_out(app), "object", 200)
