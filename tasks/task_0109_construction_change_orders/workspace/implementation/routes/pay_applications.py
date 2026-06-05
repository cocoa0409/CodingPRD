"""Pay-application and pay-app-line endpoints (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import db
import helpers as h
import services
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_PROJECT_VERSION,
    ERR_CROSS_PROJECT_REFERENCE, ERR_NONSEQUENTIAL_APPLICATION,
    ERR_BILLING_PERIOD_OVERLAP, ERR_OVERBILLING, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authenticate, require_role
from response import success

bp = Blueprint("pay_applications", __name__)


def _get_pa_or_404(pa_id):
    pa = db.pay_applications.get(pa_id)
    if pa is None:
        raise err(ERR_NOT_FOUND, "PayApplication not found.")
    return pa


def _project_pay_apps(project_id, exclude_rejected=True):
    out = []
    for pa in db.pay_applications.values():
        if pa["project_id"] != project_id:
            continue
        if exclude_rejected and pa["status"] == "REJECTED":
            continue
        out.append(pa)
    return out


@bp.post("/pay-applications")
def create_pay_application():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "application_number", "period_from",
                            "period_to", "expected_project_version"])

    project_id = h.as_string(body["project_id"], "project_id")
    project = db.projects.get(project_id)
    if project is None:
        raise err(ERR_NOT_FOUND, "Project not found.")

    application_number = h.as_int(body["application_number"], "application_number", minimum=1)
    period_from_dt = h.parse_datetime(body["period_from"], "period_from")
    period_to_dt = h.parse_datetime(body["period_to"], "period_to")
    expected = h.as_int(body["expected_project_version"], "expected_project_version")

    non_rejected = _project_pay_apps(project_id, exclude_rejected=True)

    # Sequencing (priority 7): application_number == highest_non_rejected + 1
    # (or 1 if none); period_to strictly after period_from and strictly after
    # the prior non-REJECTED application's period_to.
    if non_rejected:
        highest = max(pa["application_number"] for pa in non_rejected)
        prior = max(non_rejected, key=lambda pa: pa["application_number"])
        prior_to_dt = h.parse_datetime(prior["period_to"], "period_to")
    else:
        highest = 0
        prior_to_dt = None

    if application_number != highest + 1:
        raise err(ERR_NONSEQUENTIAL_APPLICATION,
                  "application_number must be highest_non_rejected + 1.")
    if not (period_to_dt > period_from_dt):
        raise err(ERR_NONSEQUENTIAL_APPLICATION,
                  "period_to must be strictly after period_from.")
    if prior_to_dt is not None and not (period_to_dt > prior_to_dt):
        raise err(ERR_NONSEQUENTIAL_APPLICATION,
                  "period_to must be strictly after the prior application's period_to.")

    # Billing-window overlap (priority 8): half-open [from, to). [a,b) and [c,d)
    # overlap iff a < d AND c < b. Adjacency allowed.
    for pa in non_rejected:
        a = period_from_dt
        b = period_to_dt
        c = h.parse_datetime(pa["period_from"], "period_from")
        d = h.parse_datetime(pa["period_to"], "period_to")
        if a < d and c < b:
            raise err(ERR_BILLING_PERIOD_OVERLAP,
                      "Billing window overlaps a non-REJECTED application.")

    # OCC stale-version (priority 16).
    if expected != project["version"]:
        raise err(ERR_STALE_PROJECT_VERSION, "expected_project_version is stale.")

    record = {
        "project_id": project_id,
        "application_number": application_number,
        "period_from": body["period_from"],
        "period_to": body["period_to"],
        "total_completed_and_stored_cents": 0,
        "total_retainage_cents": 0,
        "current_payment_due_cents": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
    }
    db.stamp_create(record)
    db.pay_applications[record["id"]] = record
    return success(h.pay_application_out(record), status=201)


@bp.get("/pay-applications/<pa_id>")
def get_pay_application(pa_id):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.pay_application_out(_get_pa_or_404(pa_id)))


@bp.get("/pay-applications")
def list_pay_applications():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.pay_applications.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.pay_application_out(r) for r in page], pagination=meta)


# ---- PayAppLine ----

@bp.post("/pay-app-lines")
def create_pay_app_line():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["pay_app_id", "sov_line_id", "work_completed_this_period_cents"])

    pay_app_id = h.as_string(body["pay_app_id"], "pay_app_id")
    sov_line_id = h.as_string(body["sov_line_id"], "sov_line_id")

    # Existence left-to-right (priority 3): pay_app then sov_line.
    pay_app = db.pay_applications.get(pay_app_id)
    if pay_app is None:
        raise err(ERR_NOT_FOUND, "PayApplication not found.")
    sov_line = db.sov_lines.get(sov_line_id)
    if sov_line is None:
        raise err(ERR_NOT_FOUND, "SovLine not found.")

    # Cross-project referential integrity (priority 4).
    if sov_line["project_id"] != pay_app["project_id"]:
        raise err(ERR_CROSS_PROJECT_REFERENCE,
                  "sov_line belongs to a different project than the pay application.")

    work_this = h.as_int(body["work_completed_this_period_cents"],
                         "work_completed_this_period_cents", allow_negative=False)
    materials = 0
    if body.get("materials_stored_cents") is not None:
        materials = h.as_int(body["materials_stored_cents"], "materials_stored_cents",
                             allow_negative=False)

    # work_completed_previous_cents snapshotted from SovLine.work_completed_to_date_cents
    # as of the most recently certified prior application (G703 column D).
    previous = sov_line["work_completed_to_date_cents"]
    billed_this_app = previous + work_this + materials
    line_retainage = services.line_retainage_cents(sov_line["retainage_pct"], billed_this_app)

    record = {
        "pay_app_id": pay_app_id,
        "sov_line_id": sov_line_id,
        "work_completed_this_period_cents": work_this,
        "materials_stored_cents": materials,
        "work_completed_previous_cents": previous,
        "line_retainage_cents": line_retainage,
    }
    db.stamp_create_line(record)
    db.pay_app_lines[record["id"]] = record
    return success(h.pay_app_line_out(record), status=201)


@bp.get("/pay-app-lines/<line_id>")
def get_pay_app_line(line_id):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    ln = db.pay_app_lines.get(line_id)
    if ln is None:
        raise err(ERR_NOT_FOUND, "PayAppLine not found.")
    return success(h.pay_app_line_out(ln))


@bp.get("/pay-app-lines")
def list_pay_app_lines():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    pay_app_id = request.args.get("pay_app_id")
    sov_line_id = request.args.get("sov_line_id")
    records = list(db.pay_app_lines.values())
    if pay_app_id:
        records = [r for r in records if r["pay_app_id"] == pay_app_id]
    if sov_line_id:
        records = [r for r in records if r["sov_line_id"] == sov_line_id]
    page, meta = h.paginate(records, limit, offset)
    return success([h.pay_app_line_out(r) for r in page], pagination=meta)


@bp.post("/pay-applications/<pa_id>/submit")
def submit_pay_application(pa_id):
    uid, role = authenticate()
    require_role(role, {"Contractor"})
    pa = _get_pa_or_404(pa_id)

    # State: DRAFT.
    if pa["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "PayApplication is not DRAFT.")

    lines = services.pay_app_line_for(pa_id)
    # At least one line exists (state precondition).
    if not lines:
        raise err(ERR_INVALID_STATE, "No pay-app lines exist for this application.")

    # Overbilling (priority 12): per line previous+this+stored <= sov scheduled.
    for ln in lines:
        sov = db.sov_lines.get(ln["sov_line_id"])
        billed = (ln["work_completed_previous_cents"]
                  + ln["work_completed_this_period_cents"]
                  + ln["materials_stored_cents"])
        if sov is not None and billed > sov["scheduled_value_cents"]:
            raise err(ERR_OVERBILLING, "Line bills beyond its scheduled value.")

    pa["status"] = "SUBMITTED"
    pa["submitted_by_user_id"] = uid
    services.compute_g702_totals(pa)
    db.touch(pa)
    return success(h.pay_application_out(pa))


@bp.post("/pay-applications/<pa_id>/certify")
def certify_pay_application(pa_id):
    uid, role = authenticate()
    require_role(role, {"Architect"})
    pa = _get_pa_or_404(pa_id)

    # State (priority 5) before segregation of duties (priority 6).
    if pa["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "PayApplication is not SUBMITTED.")
    if uid == pa["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Certifier must differ from the submitter.")
    # No OPEN RFI with ball_in_court == ARCHITECT on the project (blocks certify).
    for rfi in db.rfis.values():
        if (rfi["project_id"] == pa["project_id"] and rfi["status"] == "OPEN"
                and rfi["ball_in_court"] == "ARCHITECT"):
            raise err(ERR_INVALID_STATE, "An open architect-court RFI blocks certification.")

    project = db.projects.get(pa["project_id"])

    # Ledger write-back per pay-app line.
    for ln in services.pay_app_line_for(pa_id):
        sov = db.sov_lines.get(ln["sov_line_id"])
        if sov is None:
            continue
        sov["work_completed_to_date_cents"] = (
            ln["work_completed_previous_cents"] + ln["work_completed_this_period_cents"])
        sov["materials_stored_cents"] = ln["materials_stored_cents"]
        sov["retainage_withheld_to_date_cents"] += ln["line_retainage_cents"]
        db.touch(sov)

    pa["status"] = "CERTIFIED"
    pa["certified_by_user_id"] = uid
    db.touch(pa)

    # Recompute project derived fields; bump version.
    if project is not None:
        services.recompute_completed_and_stored(project)
        services.recompute_retainage_held(project)
        db.touch(project)
    return success(h.pay_application_out(pa))


@bp.post("/pay-applications/<pa_id>/reject")
def reject_pay_application(pa_id):
    uid, role = authenticate()
    require_role(role, {"Architect"})
    pa = _get_pa_or_404(pa_id)
    if pa["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "PayApplication is not SUBMITTED.")
    if uid == pa["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Rejecter must differ from the submitter.")
    pa["status"] = "REJECTED"
    db.touch(pa)
    return success(h.pay_application_out(pa))
