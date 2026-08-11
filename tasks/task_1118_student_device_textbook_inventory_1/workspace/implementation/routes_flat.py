"""Flat cross-program collection routes and single-resource aliases (PRD 2.4, 4)."""
from flask import Blueprint, request

from core import (STORE, agreement_json, assignment_json, auth, event_json,
                  fail, family_resource_scope, fee_json, fleet_json,
                  get_agreement, get_assignment, get_event, get_fee, get_fleet,
                  get_loaner, get_policy, get_report, get_student, get_sweep,
                  get_unit, list_response, loaner_json, ok_object, policy_json,
                  report_json, student_json, sweep_json, unit_json)

bp = Blueprint("flat", __name__)


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---------------------------------------------------------- flat lists -----
@bp.get("/api/students")
def flat_students():
    auth(["DistrictAdmin", "Registrar", "SiteTechnician"])
    pid, fp, fas, st = _q("program_id"), _q("financial_posture"), _q("family_agreement_status"), _q("status")
    recs = [s for s in STORE["students"].values()
            if (pid is None or s["program_id"] == pid)
            and (fp is None or s["financial_posture"] == fp)
            and (fas is None or s["family_agreement_status"] == fas)
            and (st is None or s["status"] == st)]
    return list_response(recs, student_json)


@bp.get("/api/fleets")
def flat_fleets():
    auth(["DistrictAdmin", "SiteTechnician", "Registrar"])
    pid, ac = _q("program_id"), _q("asset_class")
    recs = [f for f in STORE["fleets"].values()
            if (pid is None or f["program_id"] == pid)
            and (ac is None or f["asset_class"] == ac)]
    return list_response(recs, fleet_json)


@bp.get("/api/asset-units")
def flat_units():
    auth(["DistrictAdmin", "SiteTechnician", "Registrar"])
    fid, at, ls, cg, pid = (_q("fleet_id"), _q("assigned_to_student_id"),
                            _q("lifecycle_status"), _q("condition_grade"), _q("program_id"))
    out = []
    for u in STORE["units"].values():
        fleet = STORE["fleets"].get(u["fleet_id"])
        if fid and u["fleet_id"] != fid:
            continue
        if pid and (fleet is None or fleet["program_id"] != pid):
            continue
        if at and u["assigned_to_student_id"] != at:
            continue
        if ls and u["lifecycle_status"] != ls:
            continue
        if cg and u["condition_grade"] != cg:
            continue
        out.append(u)
    return list_response(out, unit_json)


@bp.get("/api/assignments")
def flat_assignments():
    auth(["DistrictAdmin", "Registrar", "SiteTechnician"])
    sid, aid, st = _q("student_account_id"), _q("asset_unit_id"), _q("status")
    recs = [a for a in STORE["assignments"].values()
            if (sid is None or a["student_account_id"] == sid)
            and (aid is None or a["asset_unit_id"] == aid)
            and (st is None or a["status"] == st)]
    return list_response(recs, assignment_json)


@bp.get("/api/damage-reports")
def flat_reports():
    auth(["DistrictAdmin", "Registrar", "SiteTechnician"])
    aid, st = _q("assignment_id"), _q("status")
    recs = [r for r in STORE["reports"].values()
            if (aid is None or r["assignment_id"] == aid)
            and (st is None or r["status"] == st)]
    return list_response(recs, report_json)


@bp.get("/api/fees")
def flat_fees():
    auth(["DistrictAdmin", "Registrar"])
    sid, src, st, ft = (_q("student_account_id"), _q("source_damage_report_id"),
                        _q("status"), _q("fee_type"))
    recs = [f for f in STORE["fees"].values()
            if (sid is None or f["student_account_id"] == sid)
            and (src is None or f["source_damage_report_id"] == src)
            and (st is None or f["status"] == st)
            and (ft is None or f["fee_type"] == ft)]
    return list_response(recs, fee_json)


@bp.get("/api/loaner-checkouts")
def flat_loaners():
    auth(["DistrictAdmin", "SiteTechnician"])
    sid, uid_, st = _q("student_account_id"), _q("loaner_asset_unit_id"), _q("status")
    recs = [c for c in STORE["loaners"].values()
            if (sid is None or c["student_account_id"] == sid)
            and (uid_ is None or c["loaner_asset_unit_id"] == uid_)
            and (st is None or c["status"] == st)]
    return list_response(recs, loaner_json)


@bp.get("/api/insurance-policies")
def flat_policies():
    auth(["DistrictAdmin", "Registrar"])
    sid, st = _q("student_account_id"), _q("status")
    recs = [p for p in STORE["policies"].values()
            if (sid is None or p["student_account_id"] == sid)
            and (st is None or p["status"] == st)]
    return list_response(recs, policy_json)


@bp.get("/api/family-agreements")
def flat_agreements():
    auth(["DistrictAdmin", "Registrar"])
    sid, ss = _q("student_account_id"), _q("signature_state")
    recs = [a for a in STORE["agreements"].values()
            if (sid is None or a["student_account_id"] == sid)
            and (ss is None or a["signature_state"] == ss)]
    return list_response(recs, agreement_json)


@bp.get("/api/lifecycle-events")
def flat_events():
    auth(["DistrictAdmin", "SiteTechnician", "Registrar"])
    uid_, sup, et = _q("asset_unit_id"), _q("supersedes_event_id"), _q("event_type")
    recs = [e for e in STORE["events"].values()
            if (uid_ is None or e["asset_unit_id"] == uid_)
            and (sup is None or e["supersedes_event_id"] == sup)
            and (et is None or e["event_type"] == et)]
    return list_response(recs, event_json)


@bp.get("/api/audit-sweeps")
def flat_sweeps():
    auth(["DistrictAdmin", "SiteTechnician"])
    pid, st = _q("program_id"), _q("status")
    recs = [s for s in STORE["sweeps"].values()
            if (pid is None or s["program_id"] == pid)
            and (st is None or s["status"] == st)]
    return list_response(recs, sweep_json)


# --------------------------------------------------------- flat aliases ----
@bp.get("/api/students/<studentId>")
def alias_student(studentId):
    uid, role = auth(["DistrictAdmin", "Registrar", "SiteTechnician", "Family"])
    rec = get_student(studentId)
    family_resource_scope(rec["id"], uid, role)
    return ok_object(student_json(rec))


@bp.get("/api/fleets/<fleetId>")
def alias_fleet(fleetId):
    auth(["DistrictAdmin", "SiteTechnician", "Registrar"])
    return ok_object(fleet_json(get_fleet(fleetId)))


@bp.get("/api/asset-units/<assetId>")
def alias_unit(assetId):
    auth(["DistrictAdmin", "SiteTechnician", "Registrar"])
    return ok_object(unit_json(get_unit(assetId)))


@bp.get("/api/assignments/<assignmentId>")
def alias_assignment(assignmentId):
    uid, role = auth(["DistrictAdmin", "Registrar", "SiteTechnician", "Family"])
    rec = get_assignment(assignmentId)
    family_resource_scope(rec["student_account_id"], uid, role)
    return ok_object(assignment_json(rec))


@bp.get("/api/damage-reports/<reportId>")
def alias_report(reportId):
    uid, role = auth(["DistrictAdmin", "Registrar", "SiteTechnician", "Family"])
    rec = get_report(reportId)
    asg = STORE["assignments"].get(rec["assignment_id"])
    family_resource_scope(asg["student_account_id"] if asg else None, uid, role)
    return ok_object(report_json(rec))


@bp.get("/api/fees/<feeId>")
def alias_fee(feeId):
    uid, role = auth(["DistrictAdmin", "Registrar", "Family"])
    rec = get_fee(feeId)
    family_resource_scope(rec["student_account_id"], uid, role)
    return ok_object(fee_json(rec))


@bp.get("/api/loaner-checkouts/<checkoutId>")
def alias_loaner(checkoutId):
    uid, role = auth(["DistrictAdmin", "SiteTechnician", "Family"])
    rec = get_loaner(checkoutId)
    family_resource_scope(rec["student_account_id"], uid, role)
    return ok_object(loaner_json(rec))


@bp.get("/api/insurance-policies/<policyId>")
def alias_policy(policyId):
    uid, role = auth(["DistrictAdmin", "Registrar", "Family"])
    rec = get_policy(policyId)
    family_resource_scope(rec["student_account_id"], uid, role)
    return ok_object(policy_json(rec))


@bp.get("/api/family-agreements/<agreementId>")
def alias_agreement(agreementId):
    uid, role = auth(["DistrictAdmin", "Registrar", "Family"])
    rec = get_agreement(agreementId)
    family_resource_scope(rec["student_account_id"], uid, role)
    return ok_object(agreement_json(rec))


@bp.get("/api/lifecycle-events/<eventId>")
def alias_event(eventId):
    auth(["DistrictAdmin", "SiteTechnician", "Registrar"])
    return ok_object(event_json(get_event(eventId)))


@bp.get("/api/audit-sweeps/<sweepId>")
def alias_sweep(sweepId):
    auth(["DistrictAdmin", "SiteTechnician"])
    return ok_object(sweep_json(get_sweep(sweepId)))
