"""Disciplinary hearings: calendaring, disposition and the sanction ladder."""

from flask import Blueprint, g

import calc
from core import (
    add_days,
    clock_date,
    clock_now,
    created,
    db,
    err,
    fmt_date,
    get_body,
    new_row,
    now_ts,
    ok,
    parse_dt_str,
    qfilter,
    render_list,
    require_auth,
    setf,
    touch,
    v_date,
    v_datetime,
    v_enum,
    v_id,
    v_money,
    v_str,
)
import domain
from domain import D, find, must, rows
from routes_enforcement import prior_final_citation_count

bp = Blueprint("hearings", __name__)


@bp.route("/licensing/disciplinary-hearings", methods=["POST"])
def create_hearing():
    require_auth(["BoardAdmin", "HearingOfficer"])
    body = get_body()
    citation_id = v_id(body, "citation_id")
    presiding_officer_user_id = v_str(body, "presiding_officer_user_id")
    scheduled_start_utc = v_datetime(body, "scheduled_start_utc")
    scheduled_end_utc = v_datetime(body, "scheduled_end_utc")
    if scheduled_end_utc <= scheduled_start_utc:
        err("ERR_INVALID_REQUEST",
            "scheduled_end_utc must be strictly after scheduled_start_utc")

    citation = must("citations", citation_id)
    if citation["status"] != "APPEAL_REQUESTED":
        err("ERR_CITATION_STATE_INVALID",
            "only a citation in APPEAL_REQUESTED may be calendared")

    investigation = find("investigations", citation["investigation_id"])
    if (investigation is not None
            and presiding_officer_user_id ==
            investigation["assigned_investigator_user_id"]):
        err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "the presiding officer may not be the case's assigned investigator")

    for other in rows("disciplinary_hearings"):
        if other["status"] != "SCHEDULED":
            continue
        if other["presiding_officer_user_id"] != presiding_officer_user_id:
            continue
        other_start = parse_dt_str(other["scheduled_start_utc"])
        other_end = parse_dt_str(other["scheduled_end_utc"])
        if other_start < scheduled_end_utc and scheduled_start_utc < other_end:
            err("ERR_HEARING_SLOT_CONFLICT",
                "this officer already has an overlapping hearing block")

    row = new_row()
    row.update({
        "citation_id": citation["id"],
        "presiding_officer_user_id": presiding_officer_user_id,
        "scheduled_start_utc": body["scheduled_start_utc"],
        "scheduled_end_utc": body["scheduled_end_utc"],
        "status": "SCHEDULED",
        "decision": None,
        "findings_summary": None,
        "modified_penalty_cents": None,
        "sanction_points": None,
        "sanction_tier": None,
        "decided_at": None,
    })
    db.disciplinary_hearings[row["id"]] = row

    setf(citation, "status", "HEARING_SCHEDULED")
    touch(citation)
    return created(domain.ser_hearing(row))


@bp.route("/licensing/disciplinary-hearings/<rid>", methods=["GET"])
def get_hearing(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "Licensee"])
    return ok(domain.ser_hearing(must("disciplinary_hearings", rid)))


@bp.route("/licensing/disciplinary-hearings", methods=["GET"])
def list_hearings():
    require_auth(["BoardAdmin", "LicensingAnalyst", "HearingOfficer"])
    items = rows("disciplinary_hearings")
    for field in ("citation_id", "presiding_officer_user_id", "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_hearing)


def apply_sanction_tier(lic, tier):
    if lic is None:
        return
    today = clock_date()
    if tier in ("LETTER_OF_REPRIMAND", "PROBATION"):
        pass
    elif tier in ("SUSPENSION_30", "SUSPENSION_90"):
        days = 30 if tier == "SUSPENSION_30" else 90
        if lic["status"] in ("ACTIVE", "EXPIRED"):
            domain.suspend_license(lic, "DISCIPLINARY",
                                   fmt_date(add_days(today, days)))
    elif tier == "REVOCATION":
        if lic["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED"):
            domain.revoke_license(lic)
    domain.recompute_posture(lic)


@bp.route("/licensing/disciplinary-hearings/<rid>/decide", methods=["POST"])
def decide_hearing(rid):
    require_auth(["HearingOfficer"])
    body = get_body()
    decision = v_enum(body, "decision", ["AFFIRM", "MODIFY", "VACATE"])
    findings_summary = v_str(body, "findings_summary")
    modified_penalty_cents = v_money(body, "modified_penalty_cents", required=False)
    correction_verified_on = v_date(body, "correction_verified_on", required=False)

    hearing = must("disciplinary_hearings", rid)
    if hearing["status"] != "SCHEDULED":
        err("ERR_HEARING_STATE_INVALID", "only a SCHEDULED hearing may be decided")
    citation = find("citations", hearing["citation_id"])
    if citation is None or citation["status"] != "HEARING_SCHEDULED":
        err("ERR_HEARING_STATE_INVALID",
            "the citation is not standing in HEARING_SCHEDULED")

    if g.user_id != hearing["presiding_officer_user_id"]:
        err("ERR_NOT_PRESIDING_OFFICER",
            "only the hearing's presiding officer may render the disposition")

    if clock_now() < parse_dt_str(hearing["scheduled_start_utc"]):
        err("ERR_HEARING_NOT_CONVENED", "the hearing has not yet convened")

    if decision == "MODIFY":
        if modified_penalty_cents is None:
            err("ERR_PENALTY_EXCEEDS_STATUTORY_MAX",
                "modified_penalty_cents is required for a MODIFY decision")
    else:
        if modified_penalty_cents is not None:
            err("ERR_PENALTY_EXCEEDS_STATUTORY_MAX",
                "modified_penalty_cents must be omitted for this decision")
    if (modified_penalty_cents is not None
            and modified_penalty_cents > calc.STATUTORY_MAX_PENALTY_CENTS):
        err("ERR_PENALTY_EXCEEDS_STATUTORY_MAX",
            "the substituted penalty exceeds the statutory ceiling")

    lic = find("licenses", citation.get("license_id")) if citation.get("license_id") else None
    posture_before = lic["compliance_posture"] if lic is not None else None
    recovery_debt_before = (domain.license_outstanding_recovery(lic) > 0
                           if lic is not None else False)
    classification = find("trade_classifications", citation["classification_id"])

    setf(hearing, "decision", decision)
    setf(hearing, "findings_summary", findings_summary)
    setf(hearing, "modified_penalty_cents", modified_penalty_cents)
    setf(hearing, "decided_at", now_ts())
    setf(hearing, "status", "DECIDED")

    priors_now = prior_final_citation_count(citation.get("license_id"), citation["id"])

    if decision == "AFFIRM":
        mitigation = False
        if correction_verified_on is not None:
            setf(citation, "correction_completed_on", fmt_date(correction_verified_on))
            if correction_verified_on <= D(citation["correction_due_date"]):
                mitigation = True
        recalculated = calc.citation_civil_penalty(
            citation["severity"], citation["subject_type"],
            classification["hazard_tier"], priors_now, mitigation=mitigation)
        setf(citation, "prior_final_citation_count", priors_now)
        setf(citation, "civil_penalty_cents", recalculated)
        setf(citation, "penalty_variant", "POST_HEARING_RECALCULATION")
        setf(citation, "status", "AFFIRMED")
    elif decision == "MODIFY":
        setf(citation, "civil_penalty_cents", modified_penalty_cents)
        setf(citation, "penalty_variant", "POST_HEARING_RECALCULATION")
        setf(citation, "status", "MODIFIED")
    else:
        setf(citation, "civil_penalty_cents", 0)
        setf(citation, "penalty_variant", "POST_HEARING_RECALCULATION")
        setf(citation, "status", "VACATED")
    touch(citation)
    touch(hearing)

    investigation = find("investigations", citation["investigation_id"])
    if investigation is not None and investigation.get("complaint_id"):
        complaint = find("complaints", investigation["complaint_id"])
        if complaint is not None and complaint["status"] == "CITATION_ISSUED":
            setf(complaint, "status",
                 "CLOSED_UNFOUNDED" if decision == "VACATE" else "CLOSED_SANCTIONED")
            touch(complaint)

    if lic is not None:
        touch(find("licensees", lic["licensee_id"]))

    if decision in ("AFFIRM", "MODIFY"):
        points = calc.sanction_points(citation["severity"], priors_now, posture_before,
                                     citation["subject_type"], recovery_debt_before)
        tier = calc.sanction_tier(points)
        setf(hearing, "sanction_points", points)
        setf(hearing, "sanction_tier", tier)
        touch(hearing)
        apply_sanction_tier(lic, tier)
    elif lic is not None:
        domain.recompute_posture(lic)

    return ok(domain.ser_hearing(hearing))
