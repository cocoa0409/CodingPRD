"""Startups and conflict-of-interest plans."""
from flask import Blueprint

from store import db, create_record, touch
from util import (ApiError, require, get_body, check_schema, v_nonempty_str,
                  v_str, v_enum, v_dt, v_int_min, ok_object, ok_list, paginate)
from serializers import ser_startup, ser_coi_plan, ser_license
from services import (compute_equity_bp, coi_coverage_active, coi_window_overlap,
                      startup_dissolve_cascade)

bp = Blueprint("startups", __name__)


def _get_disclosure_or_404(disclosure_id):
    disc = db.disclosures.get(disclosure_id)
    if disc is None:
        raise ApiError("ERR_DISCLOSURE_NOT_FOUND", 404, "Disclosure id does not exist")
    return disc


def _get_startup_or_404(startup_id):
    startup = db.startups.get(startup_id)
    if startup is None:
        raise ApiError("ERR_STARTUP_NOT_FOUND", 404, "Startup id does not exist")
    return startup


def _get_plan_or_404(plan_id):
    plan = db.coi_plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_COI_PLAN_NOT_FOUND", 404, "ConflictOfInterestPlan id does not exist")
    return plan


# ---------------------------------------------------------------------------
# Startups
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosures/<disclosureId>/startups", methods=["POST"])
def create_startup(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "name": (True, v_nonempty_str),
        "founded_date": (True, v_dt),
        "equity_model": (True, v_enum("FIXED", "ANTI_DILUTION")),
    })
    if disc["status"] != "PATENT_PURSUED":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Startup formation requires disclosure status PATENT_PURSUED")
    startup = create_record(db.startups, {
        "disclosure_id": disc["id"],
        "name": data["name"],
        "founded_date": data["founded_date"],
        "equity_model": data["equity_model"],
        "university_equity_bp": None,
        "equity_issued": False,
        "status": "INCORPORATION",
    })
    return ok_object(ser_startup(startup), status=201)


@bp.route("/tlo/disclosures/<disclosureId>/startups", methods=["GET"])
def list_startups(disclosureId):
    require()
    disc = _get_disclosure_or_404(disclosureId)
    records = [s for s in db.startups.values() if s["disclosure_id"] == disc["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_startup(s) for s in page], limit, offset, total)


@bp.route("/tlo/startups/<startupId>", methods=["GET"])
def get_startup(startupId):
    require()
    return ok_object(ser_startup(_get_startup_or_404(startupId)))


@bp.route("/tlo/startups/<startupId>/issue-equity", methods=["POST"])
def issue_equity(startupId):
    require("TechTransferOfficer")
    startup = _get_startup_or_404(startupId)
    data = check_schema(get_body(), {
        "post_money_valuation_cents": (False, v_int_min(1)),
    })
    if startup["equity_model"] == "ANTI_DILUTION" and "post_money_valuation_cents" not in data:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "post_money_valuation_cents is required for ANTI_DILUTION equity")
    if startup["status"] != "INCORPORATION":
        raise ApiError("ERR_STARTUP_INVALID_STATE", 409,
                       "Issue-equity requires startup status INCORPORATION")
    if not coi_coverage_active(startup["id"]):
        raise ApiError("ERR_COI_COVERAGE_REQUIRED", 409,
                       "No APPROVED COI plan for this startup covers the current clock")
    startup["university_equity_bp"] = compute_equity_bp(
        startup, data.get("post_money_valuation_cents"))
    startup["equity_issued"] = True
    startup["status"] = "EQUITY_ISSUED"
    touch(startup)
    return ok_object(ser_startup(startup))


@bp.route("/tlo/startups/<startupId>/dissolve", methods=["POST"])
def dissolve_startup(startupId):
    require("TechTransferOfficer")
    startup = _get_startup_or_404(startupId)
    check_schema(get_body(), {})
    if startup["status"] not in ("INCORPORATION", "EQUITY_ISSUED"):
        raise ApiError("ERR_STARTUP_INVALID_STATE", 409,
                       "Dissolve requires startup status INCORPORATION or EQUITY_ISSUED")
    startup["status"] = "DISSOLVED"
    touch(startup)
    startup_dissolve_cascade(startup)
    return ok_object(ser_startup(startup))


@bp.route("/tlo/startups/<startupId>/licenses", methods=["GET"])
def list_startup_licenses(startupId):
    require()
    startup = _get_startup_or_404(startupId)
    records = [l for l in db.licenses.values() if l["startup_id"] == startup["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_license(l) for l in page], limit, offset, total)


# ---------------------------------------------------------------------------
# COI plans
# ---------------------------------------------------------------------------

@bp.route("/tlo/startups/<startupId>/coi-plans", methods=["POST"])
def create_coi_plan(startupId):
    require("ComplianceOfficer")
    startup = _get_startup_or_404(startupId)
    data = check_schema(get_body(), {
        "inventor_id": (True, v_nonempty_str),
        "coverage_start": (True, v_dt),
        "coverage_end": (True, v_dt),
        "management_plan_text": (True, v_str),
    })
    if data["coverage_end"] <= data["coverage_start"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "coverage_end must be after coverage_start")
    if data["inventor_id"] not in db.inventors:
        raise ApiError("ERR_INVENTOR_NOT_FOUND", 404, "Inventor id does not exist")
    on_roster = any(
        e["disclosure_id"] == startup["disclosure_id"] and e["inventor_id"] == data["inventor_id"]
        for e in db.entries.values()
    )
    if not on_roster:
        raise ApiError("ERR_INVENTOR_NOT_ON_DISCLOSURE", 422,
                       "COI plan inventor is not on the startup's disclosure roster")
    if coi_window_overlap(startup["id"], data["inventor_id"],
                          data["coverage_start"], data["coverage_end"],
                          ("SUBMITTED", "APPROVED")):
        raise ApiError("ERR_COI_WINDOW_OVERLAP", 409,
                       "Coverage window overlaps another SUBMITTED/APPROVED plan for this startup and inventor")
    plan = create_record(db.coi_plans, {
        "startup_id": startup["id"],
        "inventor_id": data["inventor_id"],
        "coverage_start": data["coverage_start"],
        "coverage_end": data["coverage_end"],
        "management_plan_text": data["management_plan_text"],
        "rejection_reason": None,
        "status": "SUBMITTED",
    })
    return ok_object(ser_coi_plan(plan), status=201)


@bp.route("/tlo/startups/<startupId>/coi-plans", methods=["GET"])
def list_coi_plans(startupId):
    require()
    startup = _get_startup_or_404(startupId)
    records = [p for p in db.coi_plans.values() if p["startup_id"] == startup["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_coi_plan(p) for p in page], limit, offset, total)


@bp.route("/tlo/coi-plans/<planId>", methods=["GET"])
def get_coi_plan(planId):
    require()
    return ok_object(ser_coi_plan(_get_plan_or_404(planId)))


@bp.route("/tlo/coi-plans/<planId>/approve", methods=["POST"])
def approve_coi_plan(planId):
    require("ComplianceDirector")
    plan = _get_plan_or_404(planId)
    check_schema(get_body(), {})
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_COI_NOT_REVIEWABLE", 409, "Approve requires plan status SUBMITTED")
    startup = db.startups[plan["startup_id"]]
    if startup["status"] == "DISSOLVED":
        raise ApiError("ERR_STARTUP_INVALID_STATE", 409, "Startup is DISSOLVED")
    if coi_window_overlap(plan["startup_id"], plan["inventor_id"],
                          plan["coverage_start"], plan["coverage_end"],
                          ("APPROVED",), exclude_id=plan["id"]):
        raise ApiError("ERR_COI_WINDOW_OVERLAP", 409,
                       "Coverage window overlaps another APPROVED plan for this startup and inventor")
    plan["status"] = "APPROVED"
    touch(plan)
    return ok_object(ser_coi_plan(plan))


@bp.route("/tlo/coi-plans/<planId>/reject", methods=["POST"])
def reject_coi_plan(planId):
    require("ComplianceDirector")
    plan = _get_plan_or_404(planId)
    data = check_schema(get_body(), {"rejection_reason": (True, v_str)})
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_COI_NOT_REVIEWABLE", 409, "Reject requires plan status SUBMITTED")
    plan["status"] = "REJECTED"
    plan["rejection_reason"] = data["rejection_reason"]
    touch(plan)
    return ok_object(ser_coi_plan(plan))


@bp.route("/tlo/coi-plans/<planId>", methods=["PATCH"])
def revise_coi_plan(planId):
    require("ComplianceOfficer")
    plan = _get_plan_or_404(planId)
    data = check_schema(get_body(), {
        "coverage_start": (False, v_dt),
        "coverage_end": (False, v_dt),
        "management_plan_text": (False, v_str),
    })
    new_start = data.get("coverage_start", plan["coverage_start"])
    new_end = data.get("coverage_end", plan["coverage_end"])
    if new_end <= new_start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "coverage_end must be after coverage_start")
    if plan["status"] != "REJECTED":
        raise ApiError("ERR_COI_NOT_REVISABLE", 409, "Revision requires plan status REJECTED")
    if coi_window_overlap(plan["startup_id"], plan["inventor_id"], new_start, new_end,
                          ("SUBMITTED", "APPROVED"), exclude_id=plan["id"]):
        raise ApiError("ERR_COI_WINDOW_OVERLAP", 409,
                       "Revised window overlaps another SUBMITTED/APPROVED plan for this startup and inventor")
    plan["coverage_start"] = new_start
    plan["coverage_end"] = new_end
    if "management_plan_text" in data:
        plan["management_plan_text"] = data["management_plan_text"]
    plan["rejection_reason"] = None
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok_object(ser_coi_plan(plan))
