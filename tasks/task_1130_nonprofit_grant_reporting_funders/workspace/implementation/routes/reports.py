"""Report and VarianceExplanation endpoints."""

from datetime import timedelta

from flask import request

import db
import services as S
import services_summary as SS
from db import store
from errors import (
    err_grant_suspended,
    err_invalid_state,
    err_match_shortfall,
    err_outcome_required,
    err_report_not_editable,
    err_validation,
    err_variance_required,
)
from middleware import ALL_READ_ROLES, actor, body, check_funder_scope, require_roles
from response import ok, paginate
from util import get_nonempty_str, get_str


def list_reports(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_reports(grant_id)  # period_index ASC (PRD 2.3 exception)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return ok([S.ser_report(r) for r in page], pagination=meta)


def get_report(report_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    return ok(S.ser_report(S.get_report(report_id)))


def edit_report(report_id):
    uid, role = actor()
    require_roles(role, {"GrantsOfficer"})
    rep = S.get_report(report_id)
    if rep["status"] != "DRAFT" or rep["frozen"]:
        raise err_report_not_editable()
    data = body()
    if "narrative_draft" in data:
        v = data["narrative_draft"]
        if not isinstance(v, str):
            raise err_validation("narrative_draft must be a string")
        rep["narrative_draft"] = v
    if "outcome_entries" in data:
        v = data["outcome_entries"]
        if not isinstance(v, list):
            raise err_validation("outcome_entries must be an array")
        for entry in v:
            if not isinstance(entry, dict):
                raise err_validation("outcome_entries entries must be objects")
            for key in ("metric_name", "target_value", "actual_value", "unit"):
                if key not in entry:
                    raise err_validation("outcome_entries entries require %s" % key)
        rep["outcome_entries"] = [dict(e) for e in v]
    rep["prepared_by_user_id"] = uid
    S.touch(rep)
    return ok(S.ser_report(rep))


def start_report(report_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    rep = S.get_report(report_id)
    grant = S.get_grant(rep["grant_id"])
    S.require_grant_active(grant)
    if rep["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED report can be started")
    if db.now() < rep["period_start"]:
        raise err_invalid_state("Report period has not started yet")
    rep["status"] = "DRAFT"
    S.touch(rep)
    return ok(S.ser_report(rep))


def submit_report(report_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    rep = S.get_report(report_id)
    if rep["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT report can be submitted")
    grant = S.get_grant(rep["grant_id"])
    if grant["status"] == "SUSPENDED" or rep["frozen"]:
        raise err_grant_suspended()
    # PRD 3.4 gate order: outcome data, then variance explanations, then match.
    if not rep["narrative_draft"] or len(rep["outcome_entries"]) < 1:
        raise err_outcome_required()
    for line in SS.breaching_lines(grant, rep):
        explained = any(
            v["budget_line_id"] == line["id"] and v["explanation_text"]
            for v in S.report_ves(rep["id"])
        )
        if not explained:
            raise err_variance_required(
                "Budget line %s breaches the variance threshold and lacks an explanation" % line["id"]
            )
    if rep["period_type"] == "FINAL":
        verified, _, _, _ = SS.match_totals(grant)
        if verified < grant["required_match_cents"]:
            raise err_match_shortfall()
    now = db.now()
    rep["submitted_at"] = now
    due_eod = rep["due_date"] + timedelta(hours=23, minutes=59, seconds=59)
    rep["submitted_late"] = now > due_eod
    rep["status"] = "SUBMITTED"
    S.touch(rep)
    for ve in S.report_ves(rep["id"]):
        if ve["status"] == "DRAFTED":
            ve["status"] = "SUBMITTED"
            S.touch(ve)
    return ok(S.ser_report(rep))


def _funder_report(report_id, role, uid):
    rep = S.get_report(report_id)
    grant = S.get_grant(rep["grant_id"])
    check_funder_scope(uid, grant)
    return rep, grant


def start_review(report_id):
    uid, role = actor()
    require_roles(role, {"Funder"})
    rep, _ = _funder_report(report_id, role, uid)
    if rep["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED report can enter review")
    rep["status"] = "UNDER_REVIEW"
    S.touch(rep)
    return ok(S.ser_report(rep))


def accept_report(report_id):
    uid, role = actor()
    require_roles(role, {"Funder"})
    rep, grant = _funder_report(report_id, role, uid)
    if rep["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW report can be accepted")
    rep["status"] = "ACCEPTED"
    S.touch(rep)
    if rep["period_type"] == "FINAL" and grant["status"] == "ACTIVE":
        grant["status"] = "CLOSEOUT"
        S.touch(grant)
    return ok(S.ser_report(rep))


def return_report(report_id):
    uid, role = actor()
    require_roles(role, {"Funder"})
    rep, _ = _funder_report(report_id, role, uid)
    if rep["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW report can be returned")
    data = body()
    reason = get_nonempty_str(data, "returned_reason")
    rep["status"] = "RETURNED"
    rep["returned_reason"] = reason
    S.touch(rep)
    for ve in S.report_ves(rep["id"]):
        if ve["status"] == "SUBMITTED":
            ve["status"] = "DRAFTED"
            S.touch(ve)
    return ok(S.ser_report(rep))


def revise_report(report_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    rep = S.get_report(report_id)
    if rep["status"] != "RETURNED":
        raise err_invalid_state("Only a RETURNED report can be revised")
    grant = S.get_grant(rep["grant_id"])
    if grant["status"] == "SUSPENDED":
        raise err_grant_suspended()
    rep["status"] = "DRAFT"
    rep["revision_count"] += 1
    S.touch(rep)
    return ok(S.ser_report(rep))


def create_ve(report_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    rep = S.get_report(report_id)
    if rep["status"] != "DRAFT" or rep["frozen"]:
        raise err_report_not_editable()
    data = body()
    line_id = get_str(data, "budget_line_id")
    text = get_nonempty_str(data, "explanation_text")
    line = store["budget_lines"].get(line_id)
    if line is None or line["grant_id"] != rep["grant_id"]:
        raise err_validation("budget_line_id must reference a budget line of this grant")
    # Snapshot the line's period-only variance percentage at this moment.
    pa = S.period_actual(line, rep)
    pb = S.period_budget(line, rep["period_index"])
    from util import variance_pct
    snapshot = variance_pct(pa, pb)
    for ve in S.report_ves(report_id):
        if ve["budget_line_id"] == line_id:
            # One explanation per budget line per report: refresh in place.
            ve["explanation_text"] = text
            ve["period_variance_pct_snapshot"] = snapshot
            S.touch(ve)
            return ok(S.ser_ve(ve), code=201)
    ve = S.stamp({
        "report_id": report_id,
        "budget_line_id": line_id,
        "explanation_text": text,
        "period_variance_pct_snapshot": snapshot,
        "status": "DRAFTED",
    })
    store["variance_explanations"][ve["id"]] = ve
    return ok(S.ser_ve(ve), code=201)


def list_ves(report_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_report(report_id)
    items = S.report_ves(report_id)
    page, meta = paginate(items)
    return ok([S.ser_ve(v) for v in page], pagination=meta)


def register(app):
    app.add_url_rule("/grants/<grant_id>/reports", "reports_list", list_reports, methods=["GET"])
    app.add_url_rule("/reports/<report_id>", "reports_get", get_report, methods=["GET"])
    app.add_url_rule("/reports/<report_id>", "reports_edit", edit_report, methods=["PUT"])
    app.add_url_rule("/reports/<report_id>/start", "reports_start", start_report, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/submit", "reports_submit", submit_report, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/start-review", "reports_start_review", start_review, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/accept", "reports_accept", accept_report, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/return", "reports_return", return_report, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/revise", "reports_revise", revise_report, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/variance-explanations", "ves_create", create_ve, methods=["POST"])
    app.add_url_rule("/reports/<report_id>/variance-explanations", "ves_list", list_ves, methods=["GET"])
